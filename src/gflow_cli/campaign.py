"""Autonomous Campaign Engine — Orchestrates multi-shot image & video generation from a YAML/JSON/TOML spec."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import subprocess
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import structlog
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.table import Table


def _load_env_fallback() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass

    for candidate in [Path(".env"), Path(__file__).resolve().parents[3] / ".env"]:
        if candidate.exists():
            try:
                for line in candidate.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k, v = k.strip(), v.strip().strip("\"'")
                        if k not in os.environ:
                            os.environ[k] = v
            except Exception:
                pass


_load_env_fallback()

console = Console()
log = structlog.get_logger(__name__)


@dataclass
class PersonaSpec:
    name: str = "Nico"
    dna_notes: str = ""
    face_sheet: str | None = None
    environment_sheet: str | None = None
    negative_prompt: str = ""


@dataclass
class SceneSpec:
    id: str
    title: str
    type: str = "i2v"  # "i2v", "t2i+i2v", "r2v", "t2v"
    still_prompt: str | None = None
    still_ref: str | None = None
    motion_prompt: str = ""
    duration: int = 10
    model: str = "omni-flash"
    aspect: str = "9:16"
    status: str = "pending"  # "pending", "still_done", "video_done", "failed"
    still_path: str | None = None
    video_path: str | None = None
    preview_path: str | None = None


@dataclass
class CampaignSpec:
    title: str
    project_id: str | None = None
    out_dir: str = "./exports"
    still_generator: str = "cloudflare"  # "cloudflare", "flow"
    still_model: str = "openai/gpt-image-2.5-sunburst"
    still_quality: str = "high"
    persona: PersonaSpec = field(default_factory=PersonaSpec)
    scenes: list[SceneSpec] = field(default_factory=list)

    @classmethod
    def from_file(cls, path: Path) -> CampaignSpec:
        content = path.read_text(encoding="utf-8")
        if path.suffix in (".yaml", ".yml"):
            data = yaml.safe_load(content)
        elif path.suffix == ".json":
            data = json.loads(content)
        else:
            raise ValueError(f"Unsupported campaign spec format: {path.suffix}")

        persona_data = data.get("persona", {})
        persona = PersonaSpec(
            name=persona_data.get("name", "Nico"),
            dna_notes=persona_data.get("dna_notes", ""),
            face_sheet=persona_data.get("face_sheet"),
            environment_sheet=persona_data.get("environment_sheet"),
            negative_prompt=persona_data.get("negative_prompt", ""),
        )

        scenes = []
        for s in data.get("scenes", []):
            scenes.append(SceneSpec(
                id=str(s.get("id")),
                title=s.get("title", f"Shot {s.get('id')}"),
                type=s.get("type", "i2v"),
                still_prompt=s.get("still_prompt"),
                still_ref=s.get("still_ref"),
                motion_prompt=s.get("motion_prompt", ""),
                duration=int(s.get("duration", 10)),
                model=s.get("model", "omni-flash"),
                aspect=s.get("aspect", "9:16"),
            ))

        return cls(
            title=data.get("title", path.stem),
            project_id=data.get("project_id"),
            out_dir=data.get("out_dir", "./exports"),
            still_generator=data.get("still_generator", "cloudflare"),
            still_model=data.get("still_model", "openai/gpt-image-2.5-sunburst"),
            still_quality=data.get("still_quality", "high"),
            persona=persona,
            scenes=scenes,
        )


class CampaignRunner:
    def __init__(self, spec: CampaignSpec, base_dir: Path, profile: str = "personal"):
        self.spec = spec
        self.base_dir = base_dir
        self.profile = profile
        self.out_dir = (base_dir / spec.out_dir).resolve()
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.state_file = base_dir / f"{spec.title.lower().replace(' ', '_')}_state.json"
        self._load_state()

    def _load_state(self) -> None:
        if self.state_file.exists():
            try:
                data = json.loads(self.state_file.read_text(encoding="utf-8"))
                state_map = {s["id"]: s for s in data.get("scenes", [])}
                for sc in self.spec.scenes:
                    if sc.id in state_map:
                        saved = state_map[sc.id]
                        sc.status = saved.get("status", sc.status)
                        sc.still_path = saved.get("still_path", sc.still_path)
                        sc.video_path = saved.get("video_path", sc.video_path)
                        sc.preview_path = saved.get("preview_path", sc.preview_path)
            except Exception as e:
                log.warning("campaign.state_load_failed", error=str(e))

    def _save_state(self) -> None:
        data = {
            "title": self.spec.title,
            "project_id": self.spec.project_id,
            "scenes": [asdict(sc) for sc in self.spec.scenes],
        }
        self.state_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _resolve_asset_path(self, rel_or_abs: str | None) -> Path | None:
        if not rel_or_abs:
            return None
        p = Path(rel_or_abs)
        if p.is_absolute() and p.exists():
            return p
        candidate = (self.base_dir / p).resolve()
        if candidate.exists():
            return candidate
        # Search recursively
        found = list(self.base_dir.glob(f"**/{p.name}"))
        if found:
            return found[0].resolve()
        return candidate

    def execute_all(self, dry_run: bool = False) -> None:
        console.print(Panel(
            f"[bold cyan]🎬 Campaign Runner: {self.spec.title}[/bold cyan]\n"
            f"Persona: [white]{self.spec.persona.name}[/white]\n"
            f"Output: [yellow]{self.out_dir}[/yellow]\n"
            f"Project ID: [green]{self.spec.project_id or 'Auto'}[/green]\n"
            f"Total Scenes: [bold white]{len(self.spec.scenes)}[/bold white]",
            border_style="cyan",
        ))

        for idx, scene in enumerate(self.spec.scenes, start=1):
            console.print(f"\n[bold yellow]── Scene [{scene.id}] {scene.title} ──[/bold yellow]")
            if scene.status == "video_done" and scene.video_path and Path(scene.video_path).exists():
                console.print(f"  [bold green]✓ Already completed:[/bold green] {Path(scene.video_path).name}")
                continue

            # 1. Resolve or Generate Still Frame
            still_file = self._resolve_asset_path(scene.still_ref)
            if not still_file or not still_file.exists():
                if scene.still_prompt:
                    console.print(f"  [cyan]Generating still frame for shot...[/cyan]")
                    # Still generation phase
                    generated_still = self.out_dir / f"STILL-{scene.id}.png"
                    if not dry_run:
                        self._generate_still(scene, generated_still)
                        still_file = generated_still
                        scene.still_path = str(still_file)
                else:
                    console.print(f"  [red]Error: Still frame not found and no prompt provided.[/red]")
                    continue
            else:
                scene.still_path = str(still_file)
                console.print(f"  [dim]Using initial frame: {still_file.name}[/dim]")

            # 2. Video Animation Phase
            video_file = self.out_dir / f"MOTION-{scene.id}-{scene.title.lower().replace(' ', '-')}-v1.mp4"
            console.print(f"  [bold cyan]Animating clip ({scene.model}, {scene.duration}s, {scene.aspect})...[/bold cyan]")

            if dry_run:
                console.print(f"  [dim]Dry run: would output to {video_file.name}[/dim]")
                continue

            success = self._generate_video(scene, still_file, video_file)
            if success:
                scene.status = "video_done"
                scene.video_path = str(video_file)
                # Generate preview
                preview_file = self.out_dir / f"{video_file.stem}.preview.png"
                self._generate_contact_sheet(video_file, preview_file)
                scene.preview_path = str(preview_file)
                console.print(f"  [bold green]✓ Take {scene.id} rendered and verified![/bold green]")
            else:
                scene.status = "failed"
                console.print(f"  [bold red]✗ Failed to render take {scene.id}[/bold red]")

            self._save_state()

        self._print_summary()

    def _generate_still(self, scene: SceneSpec, out_path: Path) -> bool:
        prompt = scene.still_prompt or ""
        if self.spec.persona.dna_notes:
            prompt = f"{prompt}. Character DNA: {self.spec.persona.dna_notes}"

        cf_token = os.getenv("CLOUDFLARE_API_TOKEN")
        cf_account = os.getenv("CLOUDFLARE_ACCOUNT_ID")
        generator = getattr(self.spec, "still_generator", "cloudflare")

        if generator == "cloudflare" and cf_token and cf_account:
            model = getattr(self.spec, "still_model", "openai/gpt-image-2.5-sunburst")
            console.print(f"  [cyan]Generating realistic still via Cloudflare AI Gateway ({model})...[/cyan]")
            try:
                if model.startswith("@cf/"):
                    url = f"https://api.cloudflare.com/client/v4/accounts/{cf_account}/ai/run/{model}"
                    payload = {"prompt": prompt}
                else:
                    url = f"https://api.cloudflare.com/client/v4/accounts/{cf_account}/ai/run"
                    payload = {
                        "model": model,
                        "input": {
                            "prompt": prompt,
                            "quality": "max",
                        },
                    }

                req = urllib.request.Request(
                    url,
                    headers={
                        "Authorization": f"Bearer {cf_token}",
                        "Content-Type": "application/json",
                    },
                    data=json.dumps(payload).encode("utf-8"),
                )
                with urllib.request.urlopen(req, timeout=120) as resp:
                    data = resp.read()
                    if data.startswith(b"\xff\xd8") or data.startswith(b"\x89PNG"):
                        out_path.write_bytes(data)
                        return True
                    res = json.loads(data.decode("utf-8"))
                    img_ref = (
                        res.get("result", {}).get("result", {}).get("image")
                        or res.get("result", {}).get("image")
                    )
                    if img_ref:
                        if img_ref.startswith("http"):
                            with urllib.request.urlopen(img_ref, timeout=60) as dl_resp:
                                out_path.write_bytes(dl_resp.read())
                        else:
                            out_path.write_bytes(base64.b64decode(img_ref))
                        return True
            except Exception as e:
                console.print(f"  [yellow]Cloudflare still generation failed: {e}. Falling back to flow image t2i...[/yellow]")

        cmd = [
            "flow", "image", "t2i",
            prompt,
            "--aspect", scene.aspect,
            "--profile", self.profile,
            "-o", str(out_path),
        ]
        if self.spec.project_id:
            cmd.extend(["--project", self.spec.project_id])
        res = subprocess.run(cmd)
        return res.returncode == 0

    def _generate_video(self, scene: SceneSpec, still_path: Path, out_path: Path) -> bool:
        cmd = [
            "flow", "video", "i2v",
            "-i", str(still_path),
            scene.motion_prompt,
            "--model", scene.model,
            "--duration", str(scene.duration),
            "--aspect", scene.aspect,
            "--profile", self.profile,
            "-o", str(out_path),
        ]
        if self.spec.project_id:
            cmd.extend(["--project", self.spec.project_id])
        res = subprocess.run(cmd)
        return res.returncode == 0

    def _generate_contact_sheet(self, video_path: Path, out_preview: Path) -> None:
        cmd = [
            "ffmpeg", "-y", "-i", str(video_path),
            "-vf", "fps=2,scale=360:-1,tile=4x3",
            str(out_preview),
        ]
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _print_summary(self) -> None:
        table = Table(title=f"Campaign Execution Summary: {self.spec.title}", border_style="cyan")
        table.add_column("ID", style="bold green", width=6)
        table.add_column("Title", style="bold white", width=25)
        table.add_column("Status", width=12)
        table.add_column("Video Output", style="dim", max_width=45)

        for sc in self.spec.scenes:
            status_style = "[green]Done[/green]" if sc.status == "video_done" else "[red]Pending/Failed[/red]"
            v_name = Path(sc.video_path).name if sc.video_path else "-"
            table.add_row(sc.id, sc.title, status_style, v_name)

        console.print("\n")
        console.print(table)
