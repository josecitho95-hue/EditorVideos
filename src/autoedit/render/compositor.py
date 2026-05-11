"""FFmpeg compositor — build filter_complex strings and full render commands.

Audio mixing model
------------------
Input layout expected by :func:`build_render_command` (when auxiliary audio is provided):

  [0]  source video+audio
  [1..N]  meme overlay images/videos   (optional)
  [N+1..M]  SFX audio files            (from sfx_paths)
  [M+1..K]  narration audio files      (from narration_paths)

Pass ``sfx_paths`` / ``narration_paths`` as lists of absolute file paths in the
same order as their corresponding ``sfx_cues`` / ``narration_cues`` lists.
"""

from __future__ import annotations

from autoedit.domain.edit_decision import MemeOverlay, NarrationCue, SfxCue, ZoomEvent, ZoomKind
from autoedit.render.reframe import CropParams


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def build_render_command(
    source: str,
    output: str,
    start: float = 0.0,
    end: float = 60.0,
    output_codec: str = "h264_nvenc",
    nvenc_preset: str = "p4",
    crop: CropParams | None = None,
    meme_overlays: list[MemeOverlay] | None = None,
    sfx_cues: list[SfxCue] | None = None,
    narration_cues: list[NarrationCue] | None = None,
    zoom_events: list[ZoomEvent] | None = None,
    subtitle_path: str | None = None,
    # Auxiliary audio file paths — must match order of sfx_cues / narration_cues
    sfx_paths: list[str] | None = None,
    narration_paths: list[str] | None = None,
    # Meme file paths — must match order of meme_overlays
    meme_paths: list[str] | None = None,
    # Output resolution — defaults to YouTube 1920×1080
    output_w: int = 1920,
    output_h: int = 1080,
    # Actual narration WAV durations in seconds — used for precise ducking
    narration_durations: list[float] | None = None,
) -> list[str]:
    """Build an FFmpeg command list for rendering a single clip.

    Returns:
        ``["ffmpeg", "-y", ...]`` — ready to pass to ``subprocess.run``.
    """
    _meme_overlays = meme_overlays or []
    _sfx_cues = sfx_cues or []
    _narration_cues = narration_cues or []
    _zoom_events = zoom_events or []
    _sfx_paths = sfx_paths or []
    _narration_paths = narration_paths or []
    _meme_paths = meme_paths or []

    cmd: list[str] = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-to", str(end),
        "-i", source,
    ]

    # Add auxiliary inputs in index order: memes → SFX → narrations
    for mp in _meme_paths:
        cmd.extend(["-i", mp])
    for sp in _sfx_paths:
        cmd.extend(["-i", sp])
    for np_ in _narration_paths:
        cmd.extend(["-i", np_])

    # Index offsets for filter_complex
    meme_input_offset = 1
    sfx_input_offset = 1 + len(_meme_paths)
    narration_input_offset = sfx_input_offset + len(_sfx_paths)

    filter_complex = build_filter_complex(
        meme_overlays=_meme_overlays,
        sfx_cues=_sfx_cues,
        narration_cues=_narration_cues,
        zoom_events=_zoom_events,
        subtitle_path=subtitle_path,
        crop=crop,
        meme_input_offset=meme_input_offset,
        sfx_input_offset=sfx_input_offset,
        sfx_available=len(_sfx_paths),
        narration_input_offset=narration_input_offset,
        narration_available=len(_narration_paths),
        output_w=output_w,
        output_h=output_h,
        narration_durations=narration_durations,
    )

    if filter_complex:
        cmd.extend(["-filter_complex", filter_complex, "-map", "[vout]", "-map", "[aout]"])
    elif crop:
        cmd.extend([
            "-vf",
            f"crop={crop.w}:{crop.h}:{crop.x}:{crop.y},scale={output_w}:{output_h}",
        ])
    else:
        cmd.extend(["-vf", f"scale={output_w}:{output_h}"])

    # Simple -af ducking fallback when there is no filter_complex but narration is present
    if not filter_complex and _narration_cues:
        simple_af = build_audio_filter(sfx_cues=[], narration_cues=_narration_cues)
        if simple_af:
            cmd.extend(["-af", simple_af])

    cmd.extend([
        "-c:v", output_codec,
        "-preset", nvenc_preset,
        "-tune", "hq",
        "-rc", "vbr",
        "-cq", "22",
        "-b:v", "8M",
        "-maxrate", "12M",
        "-bufsize", "16M",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        output,
    ])

    return cmd


# ---------------------------------------------------------------------------
# filter_complex builder
# ---------------------------------------------------------------------------


def build_filter_complex(
    meme_overlays: list[MemeOverlay],
    sfx_cues: list[SfxCue],
    narration_cues: list[NarrationCue] | None = None,
    zoom_events: list[ZoomEvent] | None = None,
    subtitle_path: str | None = None,
    crop: CropParams | None = None,
    meme_input_offset: int = 1,
    sfx_input_offset: int | None = None,
    sfx_available: int = 0,
    narration_input_offset: int | None = None,
    narration_available: int = 0,
    output_w: int = 1920,
    output_h: int = 1080,
    # Actual durations (seconds) of each narration WAV — used for precise
    # ducking so the main audio is only silenced while narration plays.
    # Falls back to a text-length estimate when not provided.
    narration_durations: list[float] | None = None,
) -> str:
    """Build an FFmpeg ``filter_complex`` string.

    Handles:
    * Crop + scale to 1080×1920
    * Zoompan events
    * Meme image overlays with enable-range
    * ASS subtitle burn-in
    * Narration volume ducking on main track
    * Per-stream ``adelay``/``volume`` for every SFX cue (not just the first!)
    * ``amix`` of all audio streams into ``[aout]``
    """
    _narration_cues = narration_cues or []
    _zoom_events = zoom_events or []

    # Auto-compute offsets if not explicitly provided
    if sfx_input_offset is None:
        sfx_input_offset = meme_input_offset + len(meme_overlays)
    if narration_input_offset is None:
        narration_input_offset = sfx_input_offset + sfx_available

    filters: list[str] = []

    # ------------------------------------------------------------------ video
    video_chain = "[0:v]"

    if crop:
        filters.append(
            f"{video_chain}crop={crop.w}:{crop.h}:{crop.x}:{crop.y},scale={output_w}:{output_h}[v0]"
        )
    else:
        filters.append(f"{video_chain}scale={output_w}:{output_h}[v0]")
    video_chain = "[v0]"

    for i, zoom in enumerate(_zoom_events):
        if zoom.kind == ZoomKind.PUNCH_IN:
            # Convert seconds → output frame numbers (source is 30 fps).
            # FFmpeg 8.0.1's zoompan expression evaluator exposes only a
            # restricted set of identifiers: 'on' (output frame number),
            # 'zoom', 'iw', 'ih', 'ow', 'oh', 'in', 'a', etc.
            # 't', 'n', 'fps', and comparison helpers like 'gt'/'gte'/'lte'/
            # 'between' are NOT available in this build's zoompan evaluator.
            # Workaround: use max(0,on-start)*max(0,end-on) — positive only
            # while on is strictly inside [start_f, end_f].
            z_start_f = int(zoom.at_sec * 30)
            z_end_f = int((zoom.at_sec + zoom.duration_sec) * 30)
            out_label = f"[vz{i}]"
            filters.append(
                f"{video_chain}zoompan="
                f"z='if(max(0,on-{z_start_f})*max(0,{z_end_f}-on),"
                f"min(zoom+0.05,{zoom.intensity}),1)'"
                f":d=1:s={output_w}x{output_h}{out_label}"
            )
            video_chain = out_label

    for i, meme in enumerate(meme_overlays):
        input_idx = meme_input_offset + i
        start = meme.at_sec
        end = meme.at_sec + meme.duration_sec
        out_label = f"[vm{i}]"
        filters.append(
            f"{video_chain}[{input_idx}:v]"
            f"overlay=W*0.3:H*0.7:enable='between(t,{start},{end})'"
            f"{out_label}"
        )
        video_chain = out_label

    if subtitle_path:
        # Escape colons for Windows paths and avoid filter-parsing issues
        safe_path = subtitle_path.replace("\\", "/").replace(":", "\\:")
        filters.append(f"{video_chain}subtitles='{safe_path}'[vout]")
    else:
        filters.append(f"{video_chain}null[vout]")

    # ------------------------------------------------------------------ audio
    audio_chain = "[0:a]"

    # Duck main audio during narration windows.
    # BUG FIX: Use actual narration duration (or a text-length estimate) so we
    # don't duck the main audio for longer than the narration actually plays.
    # Old code used a hardcoded 8 s which left 5-7 s of near-silent audio
    # after short narrations ended.
    duck_parts: list[str] = []
    for idx_cue, cue in enumerate(_narration_cues):
        factor = 10 ** (cue.duck_main_audio_db / 20)
        # Prefer actual probed duration; fall back to chars-per-second estimate.
        if narration_durations and idx_cue < len(narration_durations):
            nar_dur = narration_durations[idx_cue]
        else:
            # ~130 wpm Spanish, avg word ~5 chars + space = ~13 chars/sec
            nar_dur = max(1.5, len(cue.text) / 13.0)
        end_duck = cue.at_sec + nar_dur + 0.5  # 0.5 s tail buffer
        duck_parts.append(
            f"volume=enable='between(t,{cue.at_sec:.3f},{end_duck:.3f})':volume={factor:.4f}"
        )
    if duck_parts:
        filters.append(f"{audio_chain}{','.join(duck_parts)}[main_ducked]")
        audio_chain = "[main_ducked]"

    # SFX streams — one label per cue that has a corresponding file input
    sfx_labels: list[str] = []
    for i, sfx in enumerate(sfx_cues):
        if i >= sfx_available:
            break  # no file was provided for this cue
        input_idx = sfx_input_offset + i
        delay_ms = int(sfx.at_sec * 1000)
        vol_factor = 10 ** (sfx.volume_db / 20)
        label = f"[sfx{i}]"
        filters.append(
            f"[{input_idx}:a]adelay={delay_ms}|{delay_ms},volume={vol_factor:.4f}{label}"
        )
        sfx_labels.append(label)

    # Narration streams — one label per cue that has a corresponding file input.
    # Resample to 44100 Hz stereo so amix never encounters mismatched formats
    # (TTS WAVs are 24 kHz mono; main audio is typically 44.1 kHz stereo).
    nar_labels: list[str] = []
    for i, _cue in enumerate(_narration_cues):
        if i >= narration_available:
            break  # no file was provided for this cue
        input_idx = narration_input_offset + i
        delay_ms = int(_cue.at_sec * 1000)
        label = f"[nar{i}]"
        filters.append(
            f"[{input_idx}:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"adelay={delay_ms}|{delay_ms}{label}"
        )
        nar_labels.append(label)

    # Mix all audio streams
    all_audio = [audio_chain] + sfx_labels + nar_labels
    if len(all_audio) > 1:
        n = len(all_audio)
        mix_inputs = "".join(all_audio)
        filters.append(f"{mix_inputs}amix=inputs={n}:duration=first:normalize=0[aout]")
    else:
        filters.append(f"{audio_chain}anull[aout]")

    return ";".join(filters)


# ---------------------------------------------------------------------------
# Simple single-track audio filter (no external inputs)
# ---------------------------------------------------------------------------


def build_audio_filter(
    sfx_cues: list[SfxCue],
    narration_cues: list[NarrationCue],
) -> str:
    """Build an ``-af`` filter string that operates on the main audio track only.

    Use this only when there are no external SFX or narration file inputs.
    For full multi-track mixing use :func:`build_filter_complex` with
    ``sfx_paths`` / ``narration_paths`` passed to :func:`build_render_command`.

    Returns an empty string if no filtering is needed.
    """
    parts: list[str] = []

    # Duck main audio during narration cues
    for cue in narration_cues:
        factor = 10 ** (cue.duck_main_audio_db / 20)
        end_duck = cue.at_sec + 8.0
        parts.append(
            f"volume=enable='between(t,{cue.at_sec},{end_duck})':volume={factor:.4f}"
        )

    # Note: SFX mixing via -af is not supported (requires separate -i inputs).
    # The sfx_cues parameter is accepted for API symmetry but is intentionally
    # not processed here — use build_render_command with sfx_paths instead.

    return ",".join(parts) if parts else ""
