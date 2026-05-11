"""E5 Triage node: classify window intent with LLM."""

import asyncio
import json
from pathlib import Path

from loguru import logger

from autoedit.domain.highlight import Highlight, Intent, TriageResult
from autoedit.domain.ids import HighlightId, JobId, WindowId, new_id
from autoedit.domain.job import JobStatus, Stage
from autoedit.domain.signals import WindowCandidate
from autoedit.llm.openrouter import openrouter
from autoedit.pipeline.state import PipelineState
from autoedit.settings import settings
from autoedit.storage.repositories.highlights import HighlightRepository
from autoedit.storage.repositories.jobs import JobRepository
from autoedit.storage.repositories.windows import WindowRepository

TRIAGE_SYSTEM_PROMPT = """You are a professional video editor triaging Twitch stream clips.
Your task is to classify the intent of a video segment based on its transcript and audience signals.

Possible intents:
- fail: The streamer fails at a game, falls, or makes a mistake. Chat erupts with laughter or mockery.
- win: The streamer achieves something difficult, beats a boss, wins a match.
- reaction: The streamer reacts to something surprising, scary, or emotional.
- rage: The streamer gets angry, frustrated, or tilted. Chat fuels the fire.
- funny_moment: A genuinely funny moment, joke, or unexpected situation.
- skill_play: Impressive gameplay, clutch, or high-skill maneuver.
- wholesome: Heartwarming, kind, or touching moment.
- other: None of the above, or not clip-worthy.

Respond ONLY with valid JSON in this exact schema:
{
  "intent": "<one of the above>",
  "confidence": 0.0-1.0,
  "keep": true/false,
  "reasoning": "brief explanation in Spanish"
}
"""


def _build_triage_prompt(window: WindowCandidate, transcript_path: str | None) -> str:
    """Build a prompt for the triage LLM."""
    # Load transcript segments for this window
    transcript_excerpt = ""
    if transcript_path and Path(transcript_path).exists():
        try:
            with open(transcript_path, encoding="utf-8") as f:
                data = json.load(f)
            segments = data.get("segments", [])
            # Filter segments within window time range
            window_segments = [
                s.get("text", "").strip()
                for s in segments
                if s.get("start", 0) >= window.start_sec and s.get("end", 0) <= window.end_sec
            ]
            transcript_excerpt = " ".join(window_segments)[:500]
        except Exception:
            pass

    if not transcript_excerpt:
        transcript_excerpt = window.transcript_excerpt or "(no transcript available)"

    prompt = f"""Analyze this Twitch stream segment and classify its intent.

SEGMENT INFO:
- Duration: {window.start_sec:.1f}s to {window.end_sec:.1f}s ({window.end_sec - window.start_sec:.1f}s total)
- Audience score: {window.score:.3f}
- Signal breakdown: audio={window.score_breakdown.get('audio', 0):.2f}, chat={window.score_breakdown.get('chat', 0):.2f}, transcript={window.score_breakdown.get('transcript', 0):.2f}, scene={window.score_breakdown.get('scene', 0):.2f}

TRANSCRIPT:
{transcript_excerpt}

Classify the intent and decide if this segment is worth keeping as a highlight clip."""
    return prompt


async def _triage_window(window: WindowCandidate, transcript_path: str | None) -> TriageResult:
    """Send a single window to the LLM for triage classification."""
    prompt = _build_triage_prompt(window, transcript_path)

    logger.info(f"[E5] Triage request for window {window.id} ({window.start_sec:.1f}s-{window.end_sec:.1f}s)")

    response = await openrouter.chat(
        model=settings.TRIAGE_MODEL,
        messages=[
            {"role": "system", "content": TRIAGE_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        max_tokens=200,
        response_format={"type": "json_object"},
    )

    # Parse JSON response
    try:
        result = json.loads(response.content)
    except json.JSONDecodeError as exc:
        logger.warning(f"[E5] Invalid JSON from LLM: {exc}. Raw: {response.content[:200]}")
        # Fallback: mark as other with low confidence
        return TriageResult(
            intent=Intent.OTHER,
            confidence=0.0,
            keep=False,
            reasoning=f"Parse error: {exc}",
        )

    # Validate intent
    intent_str = result.get("intent", "other")
    try:
        intent = Intent(intent_str)
    except ValueError:
        logger.warning(f"[E5] Unknown intent '{intent_str}', defaulting to other")
        intent = Intent.OTHER

    triage = TriageResult(
        intent=intent,
        confidence=float(result.get("confidence", 0.0)),
        keep=bool(result.get("keep", False)),
        reasoning=str(result.get("reasoning", ""))[:500],
    )

    logger.info(f"[E5] Triage result: intent={triage.intent.value}, confidence={triage.confidence:.2f}, keep={triage.keep}")
    return triage


_TRIAGE_CONCURRENCY = 3  # max simultaneous LLM calls — avoids rate-limit bursts


async def run(state: PipelineState) -> None:
    """Execute E5 Triage."""
    logger.info(f"[E5] Starting triage for job {state.job_id}")
    JobRepository().update_status(state.job_id, JobStatus.RUNNING, Stage.TRIAGE)

    # Load top windows for this job
    windows = WindowRepository().list_by_job(state.job_id)
    if not windows:
        logger.warning(f"[E5] No windows found for job {state.job_id}")
        return

    # Triage top windows (configurable limit)
    max_to_triage = min(len(windows), state.config.target_clip_count * 3)
    triage_targets = windows[:max_to_triage]

    logger.info(f"[E5] Triaging {len(triage_targets)} windows (max {max_to_triage})")

    semaphore = asyncio.Semaphore(_TRIAGE_CONCURRENCY)
    transcript_path = state.transcript_path
    job_id = state.job_id

    async def _triage_one(window: WindowCandidate) -> Highlight:
        async with semaphore:
            try:
                triage = await _triage_window(window, transcript_path)
            except Exception as exc:
                logger.warning(f"[E5] Triage failed for window {window.id}: {exc}")
                triage = TriageResult(
                    intent=Intent.OTHER,
                    confidence=0.0,
                    keep=False,
                    reasoning=f"LLM error: {exc}",
                )
        return Highlight(
            id=HighlightId(new_id()),
            window_id=WindowId(window.id),
            job_id=JobId(job_id),
            intent=triage.intent,
            triage_confidence=triage.confidence,
            triage_reasoning=triage.reasoning,
            discarded=not triage.keep,
            discard_reason=None if triage.keep else triage.reasoning,
        )

    highlights: list[Highlight] = await asyncio.gather(
        *[_triage_one(w) for w in triage_targets]
    )

    # Persist highlights
    HighlightRepository().create_many(highlights)

    kept = sum(1 for h in highlights if not h.discarded)
    logger.info(f"[E5] Triage complete: {kept}/{len(highlights)} windows kept")
