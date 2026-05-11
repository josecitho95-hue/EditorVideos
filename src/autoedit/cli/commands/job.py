"""Job commands — autoedit job add|local|list|show."""

import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from autoedit.domain.ids import JobId, VodId, new_id
from autoedit.domain.job import Job, JobConfig, JobStatus
from autoedit.pipeline.orchestrator import run_pipeline, run_pipeline_from_e1
from autoedit.storage.db import init_db
from autoedit.storage.repositories.jobs import JobRepository
from autoedit.storage.repositories.vods import VodRepository

console = Console()
app = typer.Typer()


@app.command()
def add(
    vod_url: str = typer.Argument(..., help="Twitch VOD URL"),
    config_file: str | None = typer.Option(None, "--config", "-c", help="Job config YAML file"),
    language: str = typer.Option("es", "--lang", "-l", help="Stream language (es/en/auto)"),
    clips: int = typer.Option(10, "--clips", help="Target number of clips"),
) -> None:
    """Add a new job and run the pipeline immediately (until E4)."""
    job_id = JobId(new_id())
    config = JobConfig(
        target_clip_count=clips,
        language=language,
    )

    job = Job(
        id=job_id,
        vod_url=vod_url,
        status=JobStatus.QUEUED,
        config=config,
        created_at=datetime.now(UTC),
    )
    JobRepository().create(job)
    console.print(f"Job created: {job_id}")
    console.print(f"VOD: {vod_url}")

    import asyncio
    try:
        asyncio.run(run_pipeline(job_id, vod_url, config))
        console.print(f"[bold green]Job {job_id} completed successfully[/bold green]")
    except Exception as exc:
        console.print(f"[bold red]Job {job_id} failed: {exc}[/bold red]")
        raise typer.Exit(1) from exc


@app.command("list")
def list_jobs(
    status: str | None = typer.Option(None, "--status", help="Filter by status"),
) -> None:
    """List all jobs."""
    repo = JobRepository()
    js = JobStatus(status) if status else None
    jobs = repo.list_all(status=js)

    table = Table(title="Jobs")
    table.add_column("ID", style="cyan")
    table.add_column("VOD")
    table.add_column("Status")
    table.add_column("Stage")
    table.add_column("Created")

    for job in jobs:
        table.add_row(
            job.id,
            job.vod_url,
            job.status.value,
            job.current_stage.value if job.current_stage else "",
            job.created_at.strftime("%Y-%m-%d %H:%M") if hasattr(job.created_at, "strftime") else str(job.created_at)[:16],
        )

    console.print(table)


@app.command()
def local(
    file_path: str = typer.Argument(..., help="Local video file (MP4)"),
    language: str = typer.Option("es", "--lang", "-l", help="Stream language (es/en/auto)"),
    clips: int = typer.Option(5, "--clips", help="Target number of clips"),
    skip_tts: bool = typer.Option(False, "--skip-tts", help="Skip E8 TTS (no voice cloning)"),
    until: str = typer.Option("e8", "--until", help="Run until this stage (e1-e8)"),
) -> None:
    """Run the pipeline on a LOCAL video file — skips E0 download.

    The video is copied to the data directory as source.mp4 and the pipeline
    runs from E1 (extract audio) onwards.  Useful for testing with your own
    recordings without a Twitch URL.

    Example::

        autoedit job local data/vods/test1/test1.mp4 --clips 3 --until e4
    """
    src = Path(file_path).resolve()
    if not src.exists():
        console.print(f"[red]File not found: {src}[/red]")
        raise typer.Exit(1)

    # --- Read video metadata via ffprobe ---
    ffprobe_cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_streams", "-show_format", str(src),
    ]
    probe = subprocess.run(ffprobe_cmd, capture_output=True, text=True)
    if probe.returncode != 0:
        console.print(f"[red]ffprobe failed — is FFmpeg installed?[/red]\n{probe.stderr[:200]}")
        raise typer.Exit(1)

    meta = json.loads(probe.stdout)
    duration = float(meta.get("format", {}).get("duration", 0))
    size_mb = round(int(meta.get("format", {}).get("size", 0)) / 1024 / 1024, 2)

    if duration < 1:
        console.print("[red]Could not determine video duration — aborting.[/red]")
        raise typer.Exit(1)

    # --- Set up DB and directories ---
    init_db()

    from autoedit.settings import settings
    from autoedit.storage.db import VodModel, get_session
    from sqlmodel import select

    vod_url = f"file://{src}"

    # Reuse existing VOD if the same file was already registered
    existing_vod: VodModel | None = None
    with get_session() as session:
        existing_vod = session.exec(
            select(VodModel).where(VodModel.url == vod_url)
        ).first()

    if existing_vod is not None:
        vod_id = VodId(existing_vod.id)
        vod_dir = Path(existing_vod.source_path).parent if existing_vod.source_path else (
            settings.data_dir / "vods" / vod_id
        )
        console.print(f"[yellow]VOD already registered[/yellow] — reusing {vod_id}")
    else:
        vod_id = VodId(new_id())
        vod_dir = settings.data_dir / "vods" / vod_id
        vod_dir.mkdir(parents=True, exist_ok=True)

        dest = vod_dir / "source.mp4"
        console.print(f"Copying {src.name} -> {dest} ...")
        shutil.copy2(src, dest)

        VodRepository().create(
            vod_id=vod_id,
            url=vod_url,
            title=src.stem,
            streamer="local",
            duration_sec=duration,
            recorded_at=None,
            language=language,
            source_path=str(dest),
            source_size_mb=size_mb,
        )

    # Ensure vod_dir exists (may differ from source path)
    vod_dir.mkdir(parents=True, exist_ok=True)

    job_id = JobId(new_id())
    config = JobConfig(target_clip_count=clips, language=language)
    job = Job(
        id=job_id,
        vod_url=vod_url,
        status=JobStatus.QUEUED,
        config=config,
        created_at=datetime.now(UTC),
    )
    JobRepository().create(job)
    JobRepository().update_vod_id(job_id, vod_id)

    console.print(f"\n[bold]Job:[/bold]  {job_id}")
    console.print(f"[bold]VOD:[/bold]  {vod_id}  ({duration:.0f}s, {size_mb:.1f} MB)")
    console.print(f"[bold]Dir:[/bold]  {vod_dir}")
    console.print(f"[bold]Run:[/bold]  E1 -> {until.upper()}\n")

    import asyncio
    try:
        asyncio.run(
            run_pipeline_from_e1(
                job_id=job_id,
                vod_id=vod_id,
                vod_dir=vod_dir,
                config=config,
                skip_tts=skip_tts,
                until=until.lower(),
            )
        )
        console.print(f"\n[bold green]Job {job_id} completed[/bold green]")
        console.print(f"  Run: [cyan]autoedit job show {job_id}[/cyan]")
    except Exception as exc:
        console.print(f"\n[bold red]Job {job_id} failed:[/bold red] {exc}")
        raise typer.Exit(1) from exc


@app.command()
def direct(
    job_id: str = typer.Argument(..., help="Existing job ID to re-direct"),
    skip_tts: bool = typer.Option(False, "--skip-tts", help="Skip E8 TTS after directing"),
) -> None:
    """Re-run E6 (retrieve) + E7 (director) + E8 (TTS) for an existing job.

    Use this to regenerate edit decisions after tweaking the Director prompt,
    without having to re-run the full pipeline (E1-E5 stay intact).

    Example::

        autoedit job direct 01KRC5YC3J1H1DJWGFSJF82PRY
        autoedit job direct 01KRC5YC3J1H1DJWGFSJF82PRY --skip-tts
    """
    from autoedit.settings import settings
    from autoedit.storage.repositories.edit_decisions import EditDecisionRepository
    from autoedit.storage.repositories.highlights import HighlightRepository
    from autoedit.storage.repositories.vods import VodRepository
    from autoedit.pipeline.state import PipelineState
    from autoedit.pipeline.nodes import e6_retrieve, e7_direct, e8_tts
    from autoedit.domain.ids import VodId
    import asyncio

    job = JobRepository().get(job_id)
    if not job:
        console.print(f"[red]Job not found: {job_id}[/red]")
        raise typer.Exit(1)

    if not job.vod_id:
        console.print("[red]Job has no associated VOD — run the full pipeline first.[/red]")
        raise typer.Exit(1)

    vod_dir = settings.data_dir / "vods" / job.vod_id
    if not (vod_dir / "source.mp4").exists():
        console.print(f"[red]source.mp4 not found in {vod_dir}[/red]")
        raise typer.Exit(1)

    # --- Delete existing edit decisions ---
    deleted = EditDecisionRepository().delete_by_job(job_id)
    if deleted:
        console.print(f"[yellow]Deleted {deleted} existing edit decision(s)[/yellow]")

    # --- Clear old TTS narration files so E8 regenerates them ---
    tts_dir = vod_dir / "tts"
    if tts_dir.exists():
        wav_files = list(tts_dir.glob("narration_*.wav"))
        for f in wav_files:
            f.unlink(missing_ok=True)
        if wav_files:
            console.print(f"[yellow]Cleared {len(wav_files)} old TTS file(s)[/yellow]")

    highlights = HighlightRepository().list_by_job(job_id, include_discarded=False)
    console.print(f"[cyan]Re-directing {len(highlights)} highlight(s) for job {job_id}[/cyan]")

    state = PipelineState(
        job_id=job_id,
        vod_url=job.vod_url or f"file://{vod_dir / 'source.mp4'}",
        vod_id=str(job.vod_id),
        vod_dir=vod_dir,
        config=job.config,
    )

    async def _run() -> None:
        await e6_retrieve.run(state)
        await e7_direct.run(state)
        if not skip_tts:
            await e8_tts.run(state)

    import asyncio as _asyncio
    try:
        _asyncio.run(_run())
        console.print(f"\n[bold green]Done. Now render with:[/bold green]")
        console.print(f"  [cyan]autoedit render edit --job-id {job_id}[/cyan]")
    except Exception as exc:
        console.print(f"\n[bold red]Failed: {exc}[/bold red]")
        raise typer.Exit(1) from exc


@app.command()
def show(
    job_id: str = typer.Argument(..., help="Job ID"),
) -> None:
    """Show job details."""
    job = JobRepository().get(job_id)
    if not job:
        console.print(f"[red]Job not found: {job_id}[/red]")
        raise typer.Exit(1)

    console.print(f"[bold]Job:[/bold] {job.id}")
    console.print(f"VOD: {job.vod_url}")
    console.print(f"Status: {job.status.value}")
    console.print(f"Stage: {job.current_stage.value if job.current_stage else 'N/A'}")
    console.print(f"Config: {job.config.model_dump_json(indent=2)}")
    if job.error:
        console.print(f"[red]Error: {job.error}[/red]")
