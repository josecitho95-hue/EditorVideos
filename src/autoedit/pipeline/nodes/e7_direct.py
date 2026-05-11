"""E7 Director node — generate EditDecision with LLM."""

import asyncio
import json
from pathlib import Path
from typing import Any

from loguru import logger

from autoedit.domain.edit_decision import EditDecision, Trim
from autoedit.domain.job import JobStatus, Stage
from autoedit.llm.openrouter import openrouter
from autoedit.pipeline.state import PipelineState
from autoedit.settings import settings
from autoedit.storage.repositories.edit_decisions import EditDecisionRepository
from autoedit.storage.repositories.highlights import HighlightRepository
from autoedit.storage.repositories.jobs import JobRepository

DIRECTOR_SYSTEM_PROMPT = """You are the Director AI for an auto-editing system that creates viral Twitch clips in the style of ConnorDawg: fast zooms, reaction memes, punchy SFX, and comedic narration.

EDITING STYLE — ConnorDawg DNA:
- Zoom punch-ins happen at the EXACT beat of the funny/rage/fail moment, not a second before.
- Multiple fast zooms (2-4 per clip) are better than one slow zoom. Keep each zoom short (0.5-2s).
- Meme overlays appear at the climax or right after the punchline — they feel like a reaction.
- SFX punctuate the moment: impact/boom for fail, victory jingle for win, bass drop for rage.
- Narration is the editor's sarcastic or hype voice: short, punchy lines in Spanish that react to what's happening ("Bro de verdad hizo eso...", "No me puedo creer esto").
- Titles are short, punchy, ENERGETIC — use caps for key words, Spanish OK, max 80 chars.

RULES BY INTENT:
- "fail": 2-4 zoom punch-ins timed to the fail + loud SFX at the moment of failure + reaction meme after + short sarcastic narration
- "rage": 3 rapid fast-intensity zooms (intensity ≥ 1.8) + loud impact SFX + rage meme + angry narration
- "funny_moment": 2-3 zooms at each laugh beat + meme at punchline + light funny narration
- "win": 2 zooms (one at attempt, one at victory) + celebration SFX + hype meme + hyped narration
- "reaction": 2 zooms (one at trigger, one at reaction peak) + shocked/reaction meme + SFX + narration describing the reaction
- "skill_play": 2-3 quick zooms during the sequence + win SFX + minimal narration
- "wholesome": 1-2 gentle zooms + soft SFX + short warm narration
- "other": 1 zoom only, no memes, no SFX, no narration — just a clean trim

TIMING RULES:
- Use the TRANSCRIPT WITH TIMING to find the EXACT second to place each effect.
- Place zoom "at_sec" values at the word where the peak emotion lands — not at the start of the clip.
- Meme overlays start 0.2-0.5s AFTER the key moment (reaction timing).
- SFX plays AT the moment or 0.1s before it.
- Narration goes at a natural pause AFTER the moment.

OUTPUT FORMAT — return ONLY a valid JSON object, zero markdown, zero commentary:
{
  "title": "PUNCHY title in Spanish — use CAPS for key word, max 80 chars",
  "trim": {
    "start_sec": <float — cut 0-3s before the relevant moment starts>,
    "end_sec": <float — cut 1-3s after the reaction/punchline finishes>,
    "reason": "one line explaining trim choice"
  },
  "zoom_events": [
    {
      "at_sec": <float — EXACT second relative to trim start>,
      "duration_sec": <float 0.3-2.0>,
      "kind": "punch_in",
      "intensity": <float 1.2-2.5 — higher = more aggressive>
    }
  ],
  "meme_overlays": [
    {
      "asset_id": "<exact id from ASSETS list>",
      "at_sec": <float>,
      "duration_sec": <float 1.0-5.0>,
      "position": "center",
      "scale": 0.5,
      "enter_anim": "pop",
      "exit_anim": "fade"
    }
  ],
  "sfx_cues": [
    {
      "asset_id": "<exact id from ASSETS list>",
      "at_sec": <float>,
      "volume_db": -3.0
    }
  ],
  "narration_cues": [
    {
      "text": "<Short punchy Spanish sentence, max 120 chars>",
      "at_sec": <float — at a natural pause, AFTER the moment>,
      "voice_id": "me_v1",
      "duck_main_audio_db": -12.0
    }
  ],
  "subtitle_style": {},
  "rationale": "<Spanish — explain your edit choices in 2-3 sentences>"
}

LIMITS: zoom_events ≤ 5, meme_overlays ≤ 4, sfx_cues ≤ 4, narration_cues ≤ 2.
Only use asset_ids that appear EXACTLY in the ASSETS section below.
"""


def _extract_timed_transcript(
    transcript_path: str | None,
    start_sec: float,
    end_sec: float,
) -> str:
    """Return transcript segments with timestamps relative to clip start."""
    if not transcript_path or not Path(transcript_path).exists():
        return "(no transcript available)"
    try:
        with open(transcript_path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return "(transcript load error)"

    lines: list[str] = []
    for seg in data.get("segments", []):
        seg_start = seg.get("start", 0)
        seg_end = seg.get("end", 0)
        # Include segments that overlap the window
        if seg_end < start_sec or seg_start > end_sec:
            continue
        rel_start = max(0.0, seg_start - start_sec)
        text = seg.get("text", "").strip()
        if not text:
            continue
        lines.append(f"[{rel_start:.1f}s] {text}")

    return "\n".join(lines) if lines else "(no transcript in this range)"


def _build_director_prompt(
    highlight: Any,
    window: Any,
    transcript_path: str | None,
    retrieved_assets: dict[str, Any],
) -> str:
    """Build a user prompt for the Director LLM."""
    clip_duration = window.end_sec - window.start_sec

    transcript_block = _extract_timed_transcript(
        transcript_path, window.start_sec, window.end_sec
    )

    # Visual assets — show up to 8 with their IDs clearly labeled
    visual_assets = retrieved_assets.get("visual", [])
    audio_assets = retrieved_assets.get("audio", [])

    def _fmt_asset(a: Any) -> str:
        tags = ", ".join(a.tags[:4]) if a.tags else ""
        desc = a.description or tags or a.kind.value
        return f"  ID={a.id}  [{a.kind.value}]  {desc}"

    visual_block = "\n".join(_fmt_asset(a) for a in visual_assets[:8]) or "  (none)"
    audio_block = "\n".join(_fmt_asset(a) for a in audio_assets[:8]) or "  (none)"

    prompt = f"""Create an edit plan for this Twitch highlight clip.

═══ CLIP INFO ═══
Intent    : {highlight.intent.value}
Confidence: {highlight.triage_confidence:.0%}
Window    : {window.start_sec:.1f}s – {window.end_sec:.1f}s  ({clip_duration:.1f}s total)
Context   : {highlight.triage_reasoning}

═══ TRANSCRIPT WITH TIMING (relative to clip start) ═══
{transcript_block}

═══ AVAILABLE VISUAL ASSETS (meme overlays) ═══
{visual_block}

═══ AVAILABLE AUDIO ASSETS (SFX) ═══
{audio_block}

Use the transcript timestamps to place zoom/SFX/meme effects at the EXACT right second.
Generate the edit plan JSON now."""
    return prompt


async def _direct_highlight(
    highlight: Any,
    window: Any,
    transcript_path: str | None,
    retrieved_assets: dict[str, Any],
) -> EditDecision | None:
    """Generate an EditDecision for a single highlight via LLM."""
    prompt = _build_director_prompt(highlight, window, transcript_path, retrieved_assets)

    logger.info(f"[E7] Director request for highlight {highlight.id} ({highlight.intent.value})")

    try:
        response = await openrouter.chat(
            model=settings.DIRECTOR_MODEL,
            messages=[
                {"role": "system", "content": DIRECTOR_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.75,
            max_tokens=2000,
            response_format={"type": "json_object"},
        )
    except Exception as exc:
        logger.warning(f"[E7] LLM call failed for highlight {highlight.id}: {exc}")
        return None

    # Parse JSON response
    try:
        raw = json.loads(response.content)
    except json.JSONDecodeError as exc:
        logger.warning(f"[E7] Invalid JSON: {exc}. Raw: {response.content[:200]}")
        return None

    # Inject highlight_id
    raw["highlight_id"] = highlight.id

    # Validate with Pydantic
    try:
        decision = EditDecision.model_validate(raw)
    except Exception as exc:
        logger.warning(f"[E7] Schema validation failed: {exc}. Raw keys: {list(raw.keys())}")
        decision = EditDecision(
            highlight_id=highlight.id,
            title=f"Clip {highlight.intent.value}",
            trim=Trim(start_sec=0.0, end_sec=window.end_sec - window.start_sec, reason="Fallback trim"),
            rationale="Director failed to generate valid plan; using fallback.",
        )

    logger.info(
        f"[E7] Decision for {highlight.id}: '{decision.title}' | "
        f"{len(decision.zoom_events)} zoom, "
        f"{len(decision.meme_overlays)} memes, "
        f"{len(decision.sfx_cues)} sfx, "
        f"{len(decision.narration_cues)} narration"
    )
    return decision


async def run(state: PipelineState) -> None:
    """Execute E7 Director."""
    logger.info(f"[E7] Starting director for job {state.job_id}")
    JobRepository().update_status(state.job_id, JobStatus.RUNNING, Stage.DIRECT)

    from autoedit.domain.ids import WindowId
    from autoedit.storage.repositories.windows import WindowRepository

    highlights = HighlightRepository().list_by_job(state.job_id, include_discarded=False)
    if not highlights:
        logger.info("[E7] No highlights to direct")
        return

    windows = WindowRepository().list_by_job(state.job_id)
    window_by_id = {WindowId(w.id): w for w in windows}

    _DIRECTOR_CONCURRENCY = 2
    semaphore = asyncio.Semaphore(_DIRECTOR_CONCURRENCY)
    transcript_path = state.transcript_path

    async def _direct_one(
        highlight: Any, window: Any, retrieved: dict[str, Any]
    ) -> EditDecision | None:
        async with semaphore:
            return await _direct_highlight(
                highlight=highlight,
                window=window,
                transcript_path=transcript_path,
                retrieved_assets=retrieved,
            )

    tasks: list[Any] = []
    for highlight in highlights:
        window = window_by_id.get(highlight.window_id)
        if not window:
            logger.warning(f"[E7] Window not found for highlight {highlight.id}")
            continue
        retrieved = state.retrieved_assets.get(highlight.id, {"visual": [], "audio": []})
        tasks.append(_direct_one(highlight, window, retrieved))

    results: list[EditDecision | None | BaseException] = await asyncio.gather(
        *tasks, return_exceptions=True
    )

    decisions: list[EditDecision] = []
    for r in results:
        if isinstance(r, BaseException):
            logger.warning(f"[E7] Director task raised: {r}")
        elif r is not None:
            decisions.append(r)

    repo = EditDecisionRepository()
    for decision in decisions:
        repo.create(decision, model=settings.DIRECTOR_MODEL)

    logger.info(f"[E7] Director complete: {len(decisions)} edit decisions created")
