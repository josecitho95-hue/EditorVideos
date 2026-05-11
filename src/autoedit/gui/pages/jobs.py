"""Jobs page — /jobs: card grid of all pipeline runs."""

from __future__ import annotations

from nicegui import ui

from autoedit.gui.data import list_jobs


STATUS_COLORS: dict[str, str] = {
    "completed": "positive",
    "running":   "warning",
    "failed":    "negative",
    "pending":   "grey",
    "queued":    "info",
}

STAGE_ICONS: dict[str, str] = {
    "ingest":     "download",
    "transcribe": "mic",
    "analyze":    "equalizer",
    "score":      "bar_chart",
    "triage":     "filter_alt",
    "retrieve":   "search",
    "direct":     "movie_edit",
    "tts":        "record_voice_over",
    "—":          "hourglass_empty",
}


def build_jobs_page() -> None:
    """Render the jobs listing inside the current NiceGUI context."""
    jobs = list_jobs()

    with ui.row().classes("w-full items-center justify-between mb-4"):
        ui.label("Pipeline Jobs").classes("text-2xl font-bold text-blue-300")
        refresh_btn = ui.button("Refresh", icon="refresh").props("flat color=blue-3")

    if not jobs or "error" in jobs[0]:
        err = jobs[0].get("error", "No jobs found") if jobs else "No jobs found"
        ui.label(err).classes("text-red-400 text-lg")
        return

    grid_container = ui.element("div").classes(
        "grid gap-4"
    ).style("grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));")

    def render_grid() -> None:
        grid_container.clear()
        _jobs = list_jobs()
        with grid_container:
            for job in _jobs:
                _render_job_card(job)

    render_grid()
    refresh_btn.on_click(render_grid)


def _render_job_card(job: dict) -> None:
    status  = job.get("status", "pending")
    stage   = job.get("stage", "—")
    color   = STATUS_COLORS.get(status, "grey")
    icon    = STAGE_ICONS.get(stage, "movie")

    with ui.card().classes(
        "w-full bg-gray-800 border border-gray-700 hover:border-blue-500 "
        "transition-all duration-200 cursor-pointer"
    ) as card:
        with ui.row().classes("w-full items-center justify-between"):
            with ui.row().classes("items-center gap-2"):
                ui.icon(icon).classes(f"text-{color}")
                ui.label(job["id_short"]).classes("font-mono text-blue-300 font-bold text-lg")
            ui.badge(status, color=color).props("rounded")

        ui.separator().classes("my-1 bg-gray-600")

        with ui.grid(columns=2).classes("w-full gap-x-4 gap-y-1 text-sm"):
            ui.label("Stage").classes("text-gray-400")
            ui.label(stage).classes("text-gray-200")
            ui.label("Created").classes("text-gray-400")
            ui.label(job["created"]).classes("text-gray-200 font-mono")
            ui.label("VOD").classes("text-gray-400")
            ui.label(job["vod_url"] or "—").classes(
                "text-gray-300 font-mono text-xs truncate"
            ).style("max-width: 160px;")

        ui.separator().classes("my-1 bg-gray-600")

        with ui.row().classes("w-full gap-2 justify-end"):
            ui.button(
                "Ver Timeline", icon="timeline",
            ).props("flat dense color=blue-3").on_click(
                lambda _, jid=job["id"]: ui.navigate.to(f"/timeline/{jid}")
            )
            ui.button(
                "Clips", icon="video_library",
            ).props("flat dense color=teal").on_click(
                lambda _, jid=job["id"]: ui.navigate.to(f"/clips/{jid}")
            )
