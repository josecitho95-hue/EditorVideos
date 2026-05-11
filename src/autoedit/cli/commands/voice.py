"""Voice commands -- autoedit voice register|list|delete|test."""

from __future__ import annotations

import shutil
import subprocess
import wave
from datetime import UTC, datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from autoedit.storage.db import init_db
from autoedit.storage.repositories.voices import VoiceProfileRepository

console = Console()
app = typer.Typer()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wav_duration(path: Path) -> float:
    """Return duration in seconds from a WAV header."""
    try:
        with wave.open(str(path)) as wf:
            return wf.getnframes() / wf.getframerate()
    except Exception:
        return 0.0


def _convert_to_24k_mono(src: Path, dst: Path) -> None:
    """Re-encode *src* to 24 kHz mono PCM WAV at *dst* using FFmpeg."""
    cmd = [
        "ffmpeg", "-y", "-i", str(src),
        "-ac", "1",           # mono
        "-ar", "24000",       # 24 kHz
        "-c:a", "pcm_s16le",  # 16-bit PCM
        str(dst),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg conversion failed:\n{result.stderr[:400]}")


def _auto_transcribe(audio_path: Path, language: str = "es") -> str:
    """Run faster-whisper on *audio_path* and return full transcript text."""
    console.print("[dim]Auto-transcribing reference audio with Whisper...[/dim]")
    from faster_whisper import WhisperModel

    model = WhisperModel("base", device="cpu", compute_type="int8")  # fast, good enough for ref
    segments, _ = model.transcribe(str(audio_path), language=language)
    text = " ".join(seg.text.strip() for seg in segments)
    return text.strip()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@app.command()
def register(
    audio_file: str = typer.Argument(..., help="Reference audio file (WAV, MP3, MP4...)"),
    voice_id: str = typer.Argument(..., help="Voice ID slug, e.g. 'me_v1'"),
    name: str = typer.Option("", "--name", "-n", help="Display name (defaults to voice_id)"),
    transcript: str = typer.Option("", "--transcript", "-t", help="Transcript of reference audio (auto-detected if omitted)"),
    language: str = typer.Option("es", "--lang", "-l", help="Language for auto-transcription"),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing voice profile"),
) -> None:
    """Register a voice profile for TTS cloning.

    The reference audio should be at least 15 seconds of clean speech
    (30 seconds recommended) with no background music or SFX.

    Examples::

        autoedit voice register my_voice.wav me_v1
        autoedit voice register clip.mp4 me_v1 --transcript "Lo que dije en el audio"
        autoedit voice register voice.mp3 me_v1 --name "Jose gaming" --lang es
    """
    init_db()

    src = Path(audio_file).resolve()
    if not src.exists():
        console.print(f"[red]File not found: {src}[/red]")
        raise typer.Exit(1)

    repo = VoiceProfileRepository()
    existing = repo.get(voice_id)
    if existing and not force:
        console.print(
            f"[yellow]Voice '{voice_id}' already registered.[/yellow] "
            "Use --force to overwrite."
        )
        raise typer.Exit(1)

    # Destination directory: data/voices/<voice_id>/
    from autoedit.settings import settings
    voices_dir = settings.data_dir / "voices" / voice_id
    voices_dir.mkdir(parents=True, exist_ok=True)
    ref_path = voices_dir / "ref.wav"

    # Convert to 24kHz mono WAV
    console.print(f"Converting {src.name} -> 24kHz mono WAV...")
    try:
        _convert_to_24k_mono(src, ref_path)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    duration = _wav_duration(ref_path)
    if duration < 5.0:
        console.print(f"[red]Reference audio too short ({duration:.1f}s). Need >= 15s.[/red]")
        raise typer.Exit(1)
    if duration < 15.0:
        console.print(f"[yellow]Warning: reference audio is {duration:.1f}s. 30s+ recommended.[/yellow]")

    # Transcript
    ref_text = transcript.strip()
    if not ref_text:
        try:
            ref_text = _auto_transcribe(ref_path, language=language)
            console.print(f"[dim]Auto-transcript: {ref_text[:120]}...[/dim]")
        except Exception as exc:
            console.print(f"[red]Auto-transcription failed: {exc}[/red]")
            console.print("Provide transcript manually with --transcript")
            raise typer.Exit(1) from exc

    display = name.strip() or voice_id
    repo.create(
        voice_id=voice_id,
        display_name=display,
        ref_audio_path=str(ref_path),
        ref_text=ref_text,
        duration_sec=duration,
        sample_rate_hz=24000,
    )

    console.print(f"\n[bold green]Voice '{voice_id}' registered[/bold green]")
    console.print(f"  Display  : {display}")
    console.print(f"  Audio    : {ref_path}")
    console.print(f"  Duration : {duration:.1f}s")
    console.print(f"  Transcript: {ref_text[:100]}{'...' if len(ref_text) > 100 else ''}")
    console.print(f"\nTest with: [cyan]autoedit voice test 'Texto de prueba' {voice_id}[/cyan]")


@app.command("list")
def list_voices() -> None:
    """List all registered voice profiles."""
    init_db()
    profiles = VoiceProfileRepository().list_all()

    if not profiles:
        console.print("[yellow]No voice profiles registered.[/yellow]")
        console.print("Register one with: [cyan]autoedit voice register <audio> <voice_id>[/cyan]")
        return

    table = Table(title="Registered Voice Profiles")
    table.add_column("ID", style="cyan")
    table.add_column("Display Name")
    table.add_column("Duration")
    table.add_column("Ref Audio")
    table.add_column("Registered")

    for p in profiles:
        audio_ok = "[green]OK[/green]" if Path(p.ref_audio_path).exists() else "[red]MISSING[/red]"
        table.add_row(
            p.id,
            p.display_name,
            f"{p.duration_sec:.1f}s",
            audio_ok,
            p.created_at[:10] if p.created_at else "?",
        )
    console.print(table)


@app.command()
def delete(
    voice_id: str = typer.Argument(..., help="Voice ID to delete"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Delete a registered voice profile."""
    init_db()
    if not yes:
        confirmed = typer.confirm(f"Delete voice profile '{voice_id}'?")
        if not confirmed:
            raise typer.Abort()

    deleted = VoiceProfileRepository().delete(voice_id)
    if deleted:
        console.print(f"[green]Voice '{voice_id}' deleted.[/green]")
    else:
        console.print(f"[red]Voice '{voice_id}' not found.[/red]")
        raise typer.Exit(1)


@app.command()
def test(
    text: str = typer.Argument(..., help="Text to synthesise"),
    voice_id: str = typer.Option("me_v1", "--voice", "-v", help="Voice ID to use"),
    output: str = typer.Option("", "--output", "-o", help="Output WAV path (default: data/voices/<id>/test_<ts>.wav)"),
) -> None:
    """Synthesise a test audio clip with a registered voice.

    Example::

        autoedit voice test "Que jugada tan increible, esto no lo voy a olvidar" me_v1
    """
    init_db()

    profile = VoiceProfileRepository().get(voice_id)
    if profile is None:
        console.print(f"[red]Voice '{voice_id}' not found. Register it first.[/red]")
        raise typer.Exit(1)

    if not Path(profile.ref_audio_path).exists():
        console.print(f"[red]Reference audio missing: {profile.ref_audio_path}[/red]")
        raise typer.Exit(1)

    # Determine output path
    if output:
        out_path = Path(output).resolve()
    else:
        from autoedit.settings import settings
        ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        out_path = settings.data_dir / "voices" / voice_id / f"test_{ts}.wav"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    console.print(f"Synthesising with voice [cyan]{voice_id}[/cyan]: \"{text[:60]}\"")
    console.print("[dim]Loading F5-TTS model (first run downloads ~800MB)...[/dim]")

    try:
        from autoedit.tts.f5_engine import F5TTSEngine
        engine = F5TTSEngine()
        duration = engine.synthesize(text=text, voice_id=voice_id, output_path=str(out_path))
    except Exception as exc:
        console.print(f"[bold red]TTS failed:[/bold red] {exc}")
        raise typer.Exit(1) from exc

    console.print(f"\n[bold green]Generated {duration:.2f}s audio[/bold green] -> {out_path}")
    console.print(f"Play with: [cyan]ffplay {out_path}[/cyan]")
