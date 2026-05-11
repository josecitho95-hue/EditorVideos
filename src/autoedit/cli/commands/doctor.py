"""Health check command — autoedit doctor."""

import subprocess
import sys

import httpx
import typer
from rich.console import Console
from rich.table import Table

from autoedit.settings import settings

console = Console()
app = typer.Typer()


def _check_python() -> tuple[bool, str]:
    version = sys.version_info
    ok = version.major == 3 and version.minor >= 12
    return ok, f"Python {version.major}.{version.minor}.{version.micro}"


def _check_redis() -> tuple[bool, str]:
    try:
        import redis

        r = redis.from_url(settings.REDIS_URL, socket_connect_timeout=2)  # type: ignore[no-untyped-call]
        r.ping()
        return True, f"Redis reachable at {settings.REDIS_URL}"
    except Exception as exc:
        return False, f"Redis unreachable: {exc}"


def _check_qdrant() -> tuple[bool, str]:
    try:
        resp = httpx.get(f"{settings.QDRANT_URL}/healthz", timeout=5.0)
        ok = resp.status_code == 200
        return ok, f"Qdrant at {settings.QDRANT_URL} — {resp.status_code}"
    except Exception as exc:
        return False, f"Qdrant unreachable: {exc}"


def _check_gpu() -> tuple[bool, str]:
    try:
        import torch

        if not torch.cuda.is_available():
            return False, "CUDA not available"
        name = torch.cuda.get_device_name(0)
        mem = torch.cuda.get_device_properties(0).total_memory / (1024**3)
        return True, f"{name}, {mem:.1f} GB VRAM"
    except Exception as exc:
        return False, f"PyTorch GPU check failed: {exc}"


def _check_nvenc() -> tuple[bool, str]:
    try:
        result = subprocess.run(
            [settings.FFMPEG_BIN, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        encoders = result.stdout
        available = []
        for codec in ("h264_nvenc", "hevc_nvenc", "av1_nvenc"):
            if codec in encoders:
                available.append(codec)
        ok = len(available) > 0
        return ok, ", ".join(available) if ok else "No NVENC encoders found"
    except Exception as exc:
        return False, f"FFmpeg check failed: {exc}"


def _check_models() -> tuple[bool, str]:
    models_dir = settings.data_dir / "models"
    expected = [
        "faster-whisper-large-v3",
        "clip-vit-b-32",
        "f5-tts",
    ]
    found = []
    missing = []
    for m in expected:
        if (models_dir / m).exists():
            found.append(m)
        else:
            missing.append(m)
    ok = len(missing) == 0
    msg = f"Found {len(found)}/{len(expected)} models"
    if missing:
        msg += f" — missing: {', '.join(missing)}"
    return ok, msg


def _check_voice() -> tuple[bool, str]:
    voice_file = settings.data_dir / "voice_ref" / "me.wav"
    ok = voice_file.exists()
    return (
        ok,
        f"Voice profile: {voice_file}"
        if ok
        else "No voice profile registered (run 'autoedit voice register')",
    )


def _check_assets() -> tuple[bool, str]:
    visual_dir = settings.data_dir / "assets" / "visual"
    audio_dir = settings.data_dir / "assets" / "audio"
    visual_count = len(list(visual_dir.glob("*"))) if visual_dir.exists() else 0
    audio_count = len(list(audio_dir.glob("*"))) if audio_dir.exists() else 0
    ok = True  # Empty catalog is valid for Sprint 0
    return ok, f"Assets catalog: {visual_count} visual, {audio_count} audio"


@app.callback(invoke_without_command=True)
def doctor() -> None:
    """Run health checks for all AutoEdit AI dependencies."""
    table = Table(title="AutoEdit AI — Health Check")
    table.add_column("Check", style="cyan")
    table.add_column("Status", style="bold")
    table.add_column("Details")

    checks = [
        ("Python 3.12+", _check_python),
        ("Redis", _check_redis),
        ("Qdrant", _check_qdrant),
        ("GPU (PyTorch)", _check_gpu),
        ("FFmpeg NVENC", _check_nvenc),
        ("Models downloaded", _check_models),
        ("Voice profile", _check_voice),
        ("Assets catalog", _check_assets),
    ]

    all_ok = True
    for name, fn in checks:
        ok, detail = fn()
        status = "OK" if ok else "FAIL"
        style = "green" if ok else "red"
        table.add_row(name, f"[{style}]{status}[/{style}]", detail)
        if not ok:
            all_ok = False

    console.print(table)

    if all_ok:
        console.print("\n[bold green]All systems operational.[/bold green]")
        raise typer.Exit(0)
    else:
        console.print("\n[bold yellow]Some checks failed — review details above.[/bold yellow]")
        raise typer.Exit(1)
