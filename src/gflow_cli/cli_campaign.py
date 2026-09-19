"""`gflow campaign` — Orchestrate complete creative campaigns from YAML/JSON specs."""

from __future__ import annotations

from pathlib import Path

import click
import structlog
import yaml
from rich.console import Console
from rich.panel import Panel

from gflow_cli.campaign import CampaignRunner, CampaignSpec

console = Console()
log = structlog.get_logger(__name__)


@click.group()
def campaign() -> None:
    """Manage and orchestrate end-to-end AI Creative Campaigns."""


@campaign.command("init")
@click.argument("name", default="claudeops-ugc-v1")
@click.option("--out", "out_path", type=click.Path(path_type=Path), default=None, help="Output file path.")
def init_campaign(name: str, out_path: Path | None) -> None:
    """Scaffold a new campaign.yaml template."""
    dest = out_path or Path(f"{name}.campaign.yaml")
    template = {
        "title": name,
        "project_id": "397f3132-c56d-4e5a-ac1e-6d815f071724",
        "out_dir": "./exports",
        "persona": {
            "name": "Nico",
            "dna_notes": "32-year-old Brazilian tech founder, warm olive skin with pores and stubble, dark brown eyes, messy dark hair, black crewneck tee. Candid iPhone look.",
            "face_sheet": "./02-Character-sheets/NICO-REIS-01-face-identity-sheet-v1.png",
            "environment_sheet": "./05-Environment/approved/NICO-SET-HOME-01-environment-sheet-v1.png",
            "negative_prompt": "no text, no watermark, no CGI wax skin, no beauty filters",
        },
        "scenes": [
            {
                "id": "01",
                "title": "Hook Talking Head",
                "type": "i2v",
                "still_ref": "./03-Frames/hooks/HOOK-01-demo-vs-prod-talking-v1.png",
                "motion_prompt": "Candid iPhone UGC talking head. Subtle natural head movement and blinks, mouth moving as if speaking to camera. Warm window light.",
                "duration": 10,
                "model": "omni-flash",
                "aspect": "9:16",
            },
            {
                "id": "02",
                "title": "Explain Laptop Pointing",
                "type": "i2v",
                "still_ref": "./03-Frames/hooks/HOOK-02-code-vs-ship-pointing-laptop-v1.png",
                "motion_prompt": "He continues pointing toward the laptop while talking to camera. Natural finger settle, blinks, torso lean. Screen stays unreadable.",
                "duration": 10,
                "model": "omni-flash",
                "aspect": "9:16",
            },
            {
                "id": "03",
                "title": "Calm CTA",
                "type": "i2v",
                "still_ref": "./03-Frames/hooks/HOOK-03-signal-cta-calm-v1.png",
                "motion_prompt": "Calm micro-smile and eye contact. Gentle open-palm hand motion, natural blinks, relaxed confident founder energy.",
                "duration": 10,
                "model": "omni-flash",
                "aspect": "9:16",
            },
        ],
    }

    dest.write_text(yaml.dump(template, sort_keys=False, allow_unicode=True), encoding="utf-8")
    console.print(Panel(
        f"[bold green]✓ Campaign template created:[/bold green] [white]{dest.resolve()}[/white]\n\n"
        f"Run this campaign with:\n"
        f"  [cyan]flow campaign run {dest.name}[/cyan]",
        border_style="green",
    ))


@campaign.command("run")
@click.argument("campaign_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--profile", default="personal", help="Auth profile name.")
@click.option("--dry-run", is_flag=True, help="Display the execution plan without spending credits.")
def run_campaign(campaign_file: Path, profile: str, dry_run: bool) -> None:
    """Execute an end-to-end creative campaign autonomously."""
    spec = CampaignSpec.from_file(campaign_file)
    runner = CampaignRunner(spec, base_dir=campaign_file.parent, profile=profile)
    runner.execute_all(dry_run=dry_run)
