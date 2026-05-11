"""Render command — autoedit render / autoedit render edit."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from autoedit.domain.ids import ClipId, new_id
from autoedit.render.compositor import build_render_command
from autoedit.render.ffmpeg_runner import run_ffmpeg
from autoedit.render.reframe import (
    FORMAT_DIMENSIONS,
    OutputFormat,
    compute_crop,
    compute_smart_crop,
    compute_split_layout,
)
from autoedit.render.subtitles import Word, build_ass_subtitles
from autoedit.settings import settings
from autoedit.storage.db import ClipModel, get_session
from autoedit.storage.repositories.jobs import JobRepository
from autoedit.storage.repositories.windows import WindowRepository

console = Console()
app = typer.Typer()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _load_transcript_words(transcript_path: str, start_sec: float, end_sec: float) -> list[Word]:
    """Load transcript words within a time range."""
    path = Path(transcript_path)
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    words: list[Word] = []
    for seg in data.get("segments", []):
        for w in seg.get("words", []):
            w_start = w.get("start", 0)
            w_end = w.get("end", 0)
            if w_start >= start_sec and w_end <= end_sec:
                words.append(
                    Word(
                        text=w.get("word", "").strip(),
                        start_sec=w_start - start_sec,
                        end_sec=w_end - start_sec,
                    )
                )
    return words


def _probe_audio_duration(path: str) -> float:
    """Return audio duration in seconds via ffprobe. Returns 0.0 on error."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "csv=p=0",
        path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return float(result.stdout.strip())
    except Exception:
        return 0.0


def _probe_dimensions(source: str) -> tuple[int, int]:
    """Return (width, height) of a video file via ffprobe.

    Falls back to 1920×1080 on error.
    """
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "json",
        source,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        if streams:
            return int(streams[0]["width"]), int(streams[0]["height"])
    except Exception:
        pass
    return 1920, 1080


def _persist_clip(
    clip_id: ClipId,
    job_id: str,
    highlight_id: str | None,
    output_path: str,
    duration_sec: float,
    codec: str,
    width: int = 1920,
    height: int = 1080,
) -> None:
    """Write clip metadata to SQLite."""
    from datetime import UTC, datetime
    with get_session() as session:
        clip_model = ClipModel(
            id=clip_id,
            highlight_id=highlight_id,
            job_id=job_id,
            output_path=output_path,
            duration_sec=duration_sec,
            width=width,
            height=height,
            fps=30.0,
            codec=codec,
            rendered_at=datetime.now(UTC).isoformat(),
        )
        session.add(clip_model)
        session.commit()


# ---------------------------------------------------------------------------
# Window-based render (Sprint 2 — quick preview, no edit decisions)
# ---------------------------------------------------------------------------

@app.callback(invoke_without_command=True)
def render(
    ctx: typer.Context,
    job_id: str | None = typer.Option(None, "--job-id", "-j", help="Job ID to render windows from"),
    top_n: int = typer.Option(5, "--top", "-n", help="Number of top windows to render"),
    output_dir: str | None = typer.Option(None, "--output-dir", "-o", help="Output directory for clips"),
    fmt: str = typer.Option("youtube", "--format", "-f", help="Output format: youtube (default), tiktok, shorts, square"),
    layout: str = typer.Option("crop", "--layout", "-l", help="Layout mode: crop (default, smart/center crop) | split (gameplay top + face close-up bottom)"),
) -> None:
    """Render top-N scoring windows into MP4 clips (quick preview).

    Output format defaults to YouTube 1920×1080. Use --format tiktok for 1080×1920.

    For full quality rendering with effects, zooms and narration use:

        autoedit render edit --job-id <id>
    """
    if ctx.invoked_subcommand:
        return  # let subcommand handle it

    if not job_id:
        console.print("[red]--job-id is required.[/red]")
        console.print("Usage: autoedit render --job-id <id>")
        console.print("       autoedit render edit --job-id <id>")
        raise typer.Exit(1)

    job = JobRepository().get(job_id)
    if not job:
        console.print(f"[red]Job not found: {job_id}[/red]")
        raise typer.Exit(1)

    if not job.vod_id:
        console.print("[red]Job has no associated VOD[/red]")
        raise typer.Exit(1)

    vod_dir = settings.data_dir / "vods" / job.vod_id
    source_path = vod_dir / "source.mp4"
    transcript_path = vod_dir / "transcript.json"

    if not source_path.exists():
        console.print(f"[red]VOD source not found: {source_path}[/red]")
        raise typer.Exit(1)

    windows = WindowRepository().list_by_job(job_id)[:top_n]
    if not windows:
        console.print(f"[yellow]No windows found for job {job_id}[/yellow]")
        raise typer.Exit(0)

    # Resolve output dimensions from --format
    fmt_key = fmt.lower()
    if fmt_key not in FORMAT_DIMENSIONS:
        console.print(f"[red]Unknown format '{fmt}'. Choose: youtube, tiktok, shorts, square[/red]")
        raise typer.Exit(1)
    output_w, output_h = FORMAT_DIMENSIONS[fmt_key]

    # Detect actual video dimensions
    input_w, input_h = _probe_dimensions(str(source_path))
    console.print(f"[dim]Source: {input_w}×{input_h} -> Output: {output_w}×{output_h} ({fmt_key})[/dim]")

    out_dir = Path(output_dir) if output_dir else vod_dir / "clips"
    out_dir.mkdir(parents=True, exist_ok=True)

    table = Table(title=f"Rendered Clips for Job {job_id}")
    table.add_column("#", style="cyan")
    table.add_column("Window", style="dim")
    table.add_column("Clip Path")
    table.add_column("Duration")

    for i, window in enumerate(windows, 1):
        clip_id = ClipId(new_id())
        clip_path = out_dir / f"{clip_id}.mp4"
        ass_path = out_dir / f"{clip_id}.ass"

        words = _load_transcript_words(
            str(transcript_path),
            window.start_sec,
            window.end_sec,
        )
        if words:
            ass_content = build_ass_subtitles(words, play_res_x=output_w, play_res_y=output_h)
            ass_path.write_text(ass_content, encoding="utf-8")

        # Layout selection:
        #   split → split-screen (game top / face bottom) — portrait only
        #   crop  → smart/center crop (default)
        layout_key = layout.lower()
        split = None
        crop = None
        if layout_key == "split" and fmt_key in ("tiktok", "shorts"):
            split = compute_split_layout(
                video_path=str(source_path),
                start_sec=window.start_sec,
                end_sec=window.end_sec,
                input_w=input_w,
                input_h=input_h,
                output_w=output_w,
                output_h=output_h,
            )
        elif fmt_key in ("tiktok", "shorts"):
            crop = compute_smart_crop(
                video_path=str(source_path),
                start_sec=window.start_sec,
                end_sec=window.end_sec,
                input_w=input_w,
                input_h=input_h,
                output_w=output_w,
                output_h=output_h,
            )
        else:
            crop = compute_crop(input_w=input_w, input_h=input_h, output_w=output_w, output_h=output_h)

        cmd = build_render_command(
            source=str(source_path),
            output=str(clip_path),
            start=window.start_sec,
            end=window.end_sec,
            output_codec=job.config.output_codec,
            nvenc_preset=settings.NVENC_PRESET,
            crop=crop,
            split_layout=split,
            subtitle_path=str(ass_path) if words else None,
            output_w=output_w,
            output_h=output_h,
        )

        try:
            run_ffmpeg(cmd)
            duration = window.end_sec - window.start_sec
            _persist_clip(clip_id, job_id, None, str(clip_path), duration, job.config.output_codec, output_w, output_h)
            table.add_row(
                str(i),
                f"{window.start_sec:.1f}s–{window.end_sec:.1f}s",
                str(clip_path),
                f"{duration:.1f}s",
            )
        except Exception as exc:
            console.print(f"[red]Failed to render window {i}: {exc}[/red]")

    console.print(table)
    console.print(f"[bold green]Rendered {len(windows)} clip(s) to {out_dir}[/bold green]")


# ---------------------------------------------------------------------------
# EditDecision-based render (Sprint 5 — full quality with all effects)
# ---------------------------------------------------------------------------

@app.command("edit")
def render_edit(
    job_id: str = typer.Option(..., "--job-id", "-j", help="Job ID with completed E7/E8"),
    output_dir: str | None = typer.Option(None, "--output-dir", "-o", help="Output directory for clips"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print FFmpeg commands without executing"),
    fmt: str = typer.Option("youtube", "--format", "-f", help="Output format: youtube (default), tiktok, shorts, square"),
    layout: str = typer.Option("crop", "--layout", "-l", help="Layout mode: crop (default) | split (gameplay top + face bottom, portrait only)"),
    dedup_iou: float = typer.Option(0.40, "--dedup-iou", help="IoU threshold for pre-render deduplication (0=off, 0.4=default)"),
) -> None:
    """Render clips from E7 EditDecisions with full effects.

    Applies zoom events, meme overlays, SFX, narration and karaoke subtitles
    as planned by the Director agent in E7/E8.

    Output format defaults to YouTube 1920×1080. Use --format tiktok for 1080×1920.

    Example::

        autoedit render edit --job-id abc123
        autoedit render edit --job-id abc123 --format tiktok
    """
    from autoedit.storage.repositories.assets import AssetRepository
    from autoedit.storage.repositories.edit_decisions import EditDecisionRepository

    job = JobRepository().get(job_id)
    if not job:
        console.print(f"[red]Job not found: {job_id}[/red]")
        raise typer.Exit(1)

    if not job.vod_id:
        console.print("[red]Job has no associated VOD[/red]")
        raise typer.Exit(1)

    vod_dir = settings.data_dir / "vods" / job.vod_id
    source_path = vod_dir / "source.mp4"
    transcript_path = vod_dir / "transcript.json"
    tts_dir = vod_dir / "tts"

    if not source_path.exists():
        console.print(f"[red]VOD source not found: {source_path}[/red]")
        raise typer.Exit(1)

    decisions = EditDecisionRepository().list_by_job(job_id)
    if not decisions:
        console.print(f"[yellow]No edit decisions found for job {job_id}.[/yellow]")
        console.print("Run the full pipeline (E7 director) first, or use: autoedit render --job-id <id>")
        raise typer.Exit(0)

    # Build highlight → window offset map so we can convert window-relative
    # trim timestamps (what E7 outputs) to absolute source timestamps for FFmpeg.
    # E7 receives the transcript with times relative to window start (0 = window
    # start), so its trim.start_sec / trim.end_sec are offsets within the window,
    # NOT absolute positions in the source file.
    _windows = WindowRepository().list_by_job(job_id)
    _window_by_id: dict[str, object] = {str(w.id): w for w in _windows}

    from autoedit.storage.repositories.highlights import HighlightRepository as _HR
    _highlights = _HR().list_by_job(job_id, include_discarded=True)
    _highlight_window_offset: dict[str, float] = {}
    for _h in _highlights:
        _w = _window_by_id.get(str(_h.window_id))
        if _w:
            _highlight_window_offset[str(_h.id)] = float(_w.start_sec)
    console.print(f"[dim]Window offsets loaded for {len(_highlight_window_offset)} highlight(s)[/dim]")

    # --- Pre-render deduplication (IoU NMS on final time ranges) ---
    if dedup_iou > 0:
        from autoedit.scoring.dedup import DeduplicationInput, deduplicate_decisions

        _hid_to_conf = {str(h.id): h.triage_confidence for h in _highlights}
        dedup_inputs = [
            DeduplicationInput(
                decision=d,
                window_offset=_highlight_window_offset.get(str(d.highlight_id), 0.0),
                confidence=_hid_to_conf.get(str(d.highlight_id), 0.5),
            )
            for d in decisions
        ]
        kept = deduplicate_decisions(dedup_inputs, iou_threshold=dedup_iou)
        if len(kept) < len(decisions):
            console.print(
                f"[yellow]Deduplication: {len(kept)}/{len(decisions)} decisions "
                f"kept (IoU threshold={dedup_iou:.2f})[/yellow]"
            )
        decisions = [di.decision for di in kept]

    # Resolve output dimensions from --format
    fmt_key = fmt.lower()
    if fmt_key not in FORMAT_DIMENSIONS:
        console.print(f"[red]Unknown format '{fmt}'. Choose: youtube, tiktok, shorts, square[/red]")
        raise typer.Exit(1)
    output_w, output_h = FORMAT_DIMENSIONS[fmt_key]

    console.print(f"[cyan]Rendering {len(decisions)} EditDecision(s) for job {job_id}[/cyan]")

    # Detect source video dimensions once
    input_w, input_h = _probe_dimensions(str(source_path))
    console.print(f"[dim]Source: {input_w}×{input_h} -> Output: {output_w}×{output_h} ({fmt_key})[/dim]")

    asset_repo = AssetRepository()

    out_dir = Path(output_dir) if output_dir else vod_dir / "clips_edit"
    out_dir.mkdir(parents=True, exist_ok=True)

    table = Table(title=f"Rendered Clips — EditDecisions ({job_id})")
    table.add_column("Highlight", style="dim", max_width=10)
    table.add_column("Title", max_width=30)
    table.add_column("Trim")
    table.add_column("Zoom")
    table.add_column("Memes")
    table.add_column("SFX")
    table.add_column("Narration")
    table.add_column("Status")

    rendered = 0
    for decision in decisions:
        highlight_id = decision.highlight_id
        clip_id = ClipId(new_id())
        clip_path = out_dir / f"{clip_id}.mp4"
        ass_path = out_dir / f"{clip_id}.ass"

        # --- Resolve timing from EditDecision.trim ---
        # E7 outputs trim timestamps RELATIVE to the window start (0 = start of
        # the scored window, not start of the source video).  We must add the
        # window's absolute start offset to get the correct FFmpeg -ss/-to.
        _window_offset = _highlight_window_offset.get(str(highlight_id), 0.0)
        start_sec = _window_offset + decision.trim.start_sec
        end_sec = _window_offset + decision.trim.end_sec
        console.print(
            f"[dim]  {highlight_id[:8]}: window_offset={_window_offset:.1f}s  "
            f"trim={decision.trim.start_sec:.1f}–{decision.trim.end_sec:.1f}s  "
            f"-> abs {start_sec:.1f}–{end_sec:.1f}s[/dim]"
        )

        # --- Resolve meme asset paths ---
        meme_paths: list[str] = []
        valid_meme_overlays = []
        for overlay in decision.meme_overlays:
            asset = asset_repo.get(overlay.asset_id)
            if asset and Path(asset.file_path).exists():
                meme_paths.append(asset.file_path)
                valid_meme_overlays.append(overlay)
            else:
                console.print(
                    f"[yellow]  Meme asset {overlay.asset_id} missing — skipping overlay[/yellow]"
                )

        # --- Resolve SFX asset paths ---
        sfx_paths: list[str] = []
        valid_sfx_cues = []
        for cue in decision.sfx_cues:
            asset = asset_repo.get(cue.asset_id)
            if asset and Path(asset.file_path).exists():
                sfx_paths.append(asset.file_path)
                valid_sfx_cues.append(cue)
            else:
                console.print(
                    f"[yellow]  SFX asset {cue.asset_id} missing — skipping cue[/yellow]"
                )

        # --- Resolve narration WAV paths + probe actual durations ---
        narration_paths: list[str] = []
        narration_durations: list[float] = []
        valid_narration_cues = []
        for cue in decision.narration_cues:
            key = f"{highlight_id}_{int(cue.at_sec)}"
            wav_path = tts_dir / f"narration_{key}.wav"
            if wav_path.exists():
                narration_paths.append(str(wav_path))
                narration_durations.append(_probe_audio_duration(str(wav_path)))
                valid_narration_cues.append(cue)
            else:
                console.print(
                    f"[yellow]  Narration WAV missing for cue at {cue.at_sec}s "
                    f"(run E8 first) — skipping[/yellow]"
                )

        # --- Build subtitles ---
        words = _load_transcript_words(str(transcript_path), start_sec, end_sec)
        if words:
            ass_content = build_ass_subtitles(words, play_res_x=output_w, play_res_y=output_h)
            ass_path.write_text(ass_content, encoding="utf-8")

        # --- Build FFmpeg command ---
        # Layout selection:
        #   split → split-screen (game top / face bottom) — portrait only
        #   crop  → smart/center crop (default)
        layout_key = layout.lower()
        _split_layout = None
        crop = None
        if layout_key == "split" and fmt_key in ("tiktok", "shorts"):
            _split_layout = compute_split_layout(
                video_path=str(source_path),
                start_sec=start_sec,
                end_sec=end_sec,
                input_w=input_w,
                input_h=input_h,
                output_w=output_w,
                output_h=output_h,
            )
        elif fmt_key in ("tiktok", "shorts"):
            crop = compute_smart_crop(
                video_path=str(source_path),
                start_sec=start_sec,
                end_sec=end_sec,
                input_w=input_w,
                input_h=input_h,
                output_w=output_w,
                output_h=output_h,
            )
        else:
            crop = compute_crop(input_w=input_w, input_h=input_h, output_w=output_w, output_h=output_h)
        cmd = build_render_command(
            source=str(source_path),
            output=str(clip_path),
            start=start_sec,
            end=end_sec,
            output_codec=job.config.output_codec,
            nvenc_preset=settings.NVENC_PRESET,
            crop=crop,
            split_layout=_split_layout,
            meme_overlays=valid_meme_overlays,
            sfx_cues=valid_sfx_cues,
            narration_cues=valid_narration_cues,
            zoom_events=decision.zoom_events,
            subtitle_path=str(ass_path) if words else None,
            sfx_paths=sfx_paths,
            narration_paths=narration_paths,
            narration_durations=narration_durations,
            meme_paths=meme_paths,
            output_w=output_w,
            output_h=output_h,
        )

        if dry_run:
            console.print(f"\n[dim]DRY RUN — {decision.title}[/dim]")
            console.print(" ".join(cmd))
            status = "[cyan]DRY RUN[/cyan]"
        else:
            try:
                run_ffmpeg(cmd)
                duration = end_sec - start_sec
                _persist_clip(
                    clip_id, job_id, highlight_id,
                    str(clip_path), duration, job.config.output_codec,
                    output_w, output_h,
                )
                rendered += 1
                status = "[green]OK[/green]"
            except Exception as exc:
                console.print(f"[red]  Failed to render {decision.title}: {exc}[/red]")
                status = "[red]FAILED[/red]"

        table.add_row(
            highlight_id[:8],
            decision.title[:30],
            f"{start_sec:.1f}–{end_sec:.1f}s",
            str(len(decision.zoom_events)),
            str(len(valid_meme_overlays)),
            str(len(valid_sfx_cues)),
            str(len(valid_narration_cues)),
            status,
        )

    console.print(table)
    if not dry_run:
        console.print(f"[bold green]Rendered {rendered}/{len(decisions)} clips to {out_dir}[/bold green]")
