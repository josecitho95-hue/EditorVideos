"""E6 Retrieve node — search Qdrant for assets matching highlight intent."""

from loguru import logger

from autoedit.assets.retrieval import AssetRetrieval
from autoedit.domain.job import JobStatus, Stage
from autoedit.pipeline.state import PipelineState
from autoedit.settings import settings
from autoedit.storage.repositories.highlights import HighlightRepository
from autoedit.storage.repositories.jobs import JobRepository


async def run(state: PipelineState) -> None:
    """Execute E6 Retrieve."""
    logger.info(f"[E6] Starting asset retrieval for job {state.job_id}")
    JobRepository().update_status(state.job_id, JobStatus.RUNNING, Stage.RETRIEVE)

    # Ensure Qdrant collections exist with the correct vector dimension.
    # This also auto-recreates collections that were created with a different
    # embedding model (e.g. 384-dim sentence-transformers -> 512-dim CLIP).
    from autoedit.assets.retrieval import ensure_collections
    ensure_collections()

    # Load kept highlights for this job
    highlights = HighlightRepository().list_by_job(state.job_id, include_discarded=False)
    if not highlights:
        logger.info("[E6] No highlights to retrieve assets for")
        return

    retrieval = AssetRetrieval()
    state.retrieved_assets = {}

    for highlight in highlights:
        logger.info(f"[E6] Retrieving assets for highlight {highlight.id} ({highlight.intent.value})")

        # Search visual assets
        visual_assets = retrieval.search_visual(
            intent=highlight.intent,
            top_k=settings.ASSET_RETRIEVAL_TOP_K,
        )
        logger.info(f"[E6] Visual assets: {len(visual_assets)}")

        # Search audio assets
        audio_assets = retrieval.search_audio(
            intent=highlight.intent,
            top_k=settings.ASSET_RETRIEVAL_TOP_K,
        )
        logger.info(f"[E6] Audio assets: {len(audio_assets)}")

        state.retrieved_assets[highlight.id] = {
            "visual": visual_assets,
            "audio": audio_assets,
        }

    total_visual = sum(len(v["visual"]) for v in state.retrieved_assets.values())
    total_audio = sum(len(v["audio"]) for v in state.retrieved_assets.values())
    logger.info(f"[E6] Retrieve complete: {total_visual} visual, {total_audio} audio assets")
