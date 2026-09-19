"""`gflow ugc` — UGC and Storyboard Pipeline automation for creative workflows."""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import click
import structlog
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from gflow_cli import json_output
from gflow_cli._cli_helpers import _resolve_profile, run_with_handlers
from gflow_cli.api.client import FlowApiClient
from gflow_cli.config import get_settings

console = Console()
log = structlog.get_logger(__name__)


@click.group()
def ugc() -> None:
    """UGC & Storyboard Pipeline automation for AI video creation."""


def _parse_storyboard_markdown(md_path: Path) -> list[dict[str, Any]]:
    """Parse scenes from an Obsidian storyboard or motion prompts markdown file."""
    content = md_path.read_text(encoding="utf-8")
    scenes: list[dict[str, Any]] = []

    # Look for ## MOTION XX or ## SHOT XX or ## HOOK XX sections
    pattern = re.compile(
        r"##\s+(?:MOTION|SHOT|HOOK|TAKE)\s*(\d+)?\s*[-—:]?\s*([^\n]+)\n(.*?)(?=\n##\s+|\Z)",
        re.DOTALL | re.IGNORECASE,
    )

    base_dir = md_path.parent
    # Project root is typically 1 or 2 levels up from 04-Flow-Omni
    search_dirs = [base_dir, base_dir.parent, base_dir.parent.parent]

    for match in pattern.finditer(content):
        shot_num = match.group(1) or str(len(scenes) + 1).zfill(2)
        title = match.group(2).strip()
        body = match.group(3).strip()

        # Extract image file match
        img_match = re.search(r"[`'\"]?([\w\-. ]+\.(?:png|jpg|jpeg|webp))[`'\"]?", body, re.IGNORECASE)
        img_ref = None
        if img_match:
            cand_name = img_match.group(1).strip()
            for sdir in search_dirs:
                matches = list(sdir.glob(f"**/{cand_name}"))
                if matches:
                    img_ref = str(matches[0].resolve())
                    break
            if not img_ref:
                img_ref = cand_name

        # Clean prompt lines
        prompt_lines = []
        for line in body.splitlines():
            line_str = line.strip()
            if not line_str:
                continue
            if line_str.startswith("#"):
                continue
            if re.match(r"^\*?\*?(?:Ingredient|Still|Ref|Depois do export)", line_str, re.IGNORECASE):
                continue
            prompt_lines.append(line_str)
        prompt_text = " ".join(prompt_lines)

        scenes.append({
            "index": shot_num,
            "title": title,
            "image": img_ref,
            "prompt": prompt_text,
            "raw_body": body,
        })

    return scenes


@ugc.command("parse-storyboard")
@click.argument("storyboard_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--json", "emit_json", is_flag=True, help="Emit JSON output.")
def parse_storyboard(storyboard_file: Path, emit_json: bool) -> None:
    """Parse and inspect shots from a storyboard markdown file."""
    scenes = _parse_storyboard_markdown(storyboard_file)

    if emit_json:
        json_output.emit_json({"file": str(storyboard_file), "scenes": scenes})
        return

    table = Table(title=f"Storyboard Shots: {storyboard_file.name}", border_style="cyan")
    table.add_column("#", style="bold green", width=4)
    table.add_column("Title", style="bold white", width=25)
    table.add_column("Initial Frame / Still", style="yellow", width=45)
    table.add_column("Prompt Preview", style="dim", max_width=50)

    for sc in scenes:
        img_disp = Path(sc["image"]).name if sc["image"] else "[red]None[/red]"
        prompt_preview = sc["prompt"][:80] + "..." if len(sc["prompt"]) > 80 else sc["prompt"]
        table.add_row(sc["index"], sc["title"], img_disp, prompt_preview)

    console.print(table)


@ugc.command("batch-render")
@click.argument("storyboard_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--model", default="omni-flash", help="Video model (default: omni-flash).")
@click.option("--duration", type=int, default=10, help="Clip length in seconds (default: 10).")
@click.option("--aspect", default="9:16", help="Aspect ratio (default: 9:16).")
@click.option("--out-dir", type=click.Path(path_type=Path), default=None, help="Output directory for videos.")
@click.option("--project", "project_id", default=None, help="Flow project id.")
@click.option("--profile", default="personal", help="Auth profile name.")
@click.option("--dry-run", is_flag=True, help="Display render plan without submitting.")
def batch_render(
    storyboard_file: Path,
    model: str,
    duration: int,
    aspect: str,
    out_dir: Path | None,
    project_id: str | None,
    profile: str,
    dry_run: bool,
) -> None:
    """Batch render all takes from a storyboard file sequentially."""
    scenes = _parse_storyboard_markdown(storyboard_file)
    if not scenes:
        console.print("[red]No scenes found in storyboard file.[/red]")
        return

    dest_dir = out_dir or (storyboard_file.parent / "exports")
    dest_dir.mkdir(parents=True, exist_ok=True)

    console.print(Panel(
        f"[bold cyan]🎬 Storyboard Batch Render Plan[/bold cyan]\n"
        f"File: [white]{storyboard_file.name}[/white]\n"
        f"Model: [green]{model}[/green] | Duration: [green]{duration}s[/green] | Aspect: [green]{aspect}[/green]\n"
        f"Output Directory: [yellow]{dest_dir}[/yellow]\n"
        f"Total Takes: [bold white]{len(scenes)}[/bold white]",
        border_style="cyan"
    ))

    for sc in scenes:
        idx = sc["index"]
        title = sc["title"]
        slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", title.lower()).strip("-")
        out_file = dest_dir / f"MOTION-{idx}-{slug}-v1.mp4"
        console.print(f"\n[bold yellow]Take {idx}:[/bold yellow] {title}")
        console.print(f"  Frame: [dim]{sc['image']}[/dim]")
        console.print(f"  Target: [green]{out_file.name}[/green]")

        if dry_run:
            continue

        cmd = [
            "flow", "video", "i2v",
            "-i", str(sc["image"]),
            sc["prompt"],
            "--model", model,
            "--duration", str(duration),
            "--aspect", aspect,
            "--profile", profile,
            "-o", str(out_file),
        ]
        if project_id:
            cmd.extend(["--project", project_id])

        console.print(f"  [bold cyan]Executing generation...[/bold cyan]")
        res = subprocess.run(cmd)
        if res.returncode != 0:
            console.print(f"  [bold red]Take {idx} failed with exit code {res.returncode}[/bold red]")
        else:
            console.print(f"  [bold green]Take {idx} finished successfully![/bold green]")
            # Generate preview sheet
            preview_file = dest_dir / f"MOTION-{idx}-{slug}-v1.preview.png"
            prev_cmd = [
                "ffmpeg", "-y", "-i", str(out_file),
                "-vf", "fps=2,scale=360:-1,tile=4x3",
                str(preview_file)
            ]
            subprocess.run(prev_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if preview_file.exists():
                console.print(f"  [dim]Contact sheet saved: {preview_file.name}[/dim]")


@ugc.command("generate-preview")
@click.argument("video_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
def generate_preview(video_path: Path) -> None:
    """Generate a 4x3 contact sheet preview image for a video."""
    out_img = video_path.with_name(f"{video_path.stem}.preview.png")
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vf", "fps=2,scale=360:-1,tile=4x3",
        str(out_img)
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        console.print(f"[bold green]Preview generated:[/bold green] {out_img}")
    except Exception as e:
        console.print(f"[bold red]Failed to generate preview via ffmpeg:[/bold red] {e}")
