"""Clips page — /clips/{job_id}: gallery of rendered clips for a job."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from nicegui import ui

from autoedit.gui.data import get_job, list_clips_for_job


def build_clips_page(job_id: str) -> None:
    """Render the clip gallery inside the current NiceGUI context."""
    job = get_job(job_id)
    short = job_id[:8]

    # ── Header ────────────────────────────────────────────────────────────────
    with ui.row().classes("w-full items-center justify-between mb-4"):
        ui.label(f"Clips — {short}").classes("text-2xl font-bold text-blue-300")
        with ui.row().classes("gap-2"):
            ui.button("← Jobs", icon="arrow_back").props("flat color=grey").on_click(
                lambda: ui.navigate.to("/jobs")
            )
            ui.button("Timeline", icon="timeline").props("flat color=blue-3").on_click(
                lambda: ui.navigate.to(f"/timeline/{job_id}")
            )

    if job:
        with ui.row().classes("gap-6 mb-4 text-sm text-gray-500 font-mono"):
            ui.label(f"Estado: {job['status']}")
            ui.label(f"Etapa: {job['stage']}")
            ui.label(f"Creado: {job['created']}")

    clips = list_clips_for_job(job_id)

    if not clips:
        with ui.column().classes("w-full items-center mt-16 gap-4"):
            ui.icon("video_library").classes("text-6xl text-gray-700")
            ui.label("Sin clips renderizados para este job.").classes("text-gray-500 text-lg")
            ui.label(
                "Ejecuta autoedit render edit --job-id " + short + " para generar clips."
            ).classes("text-gray-600 text-sm font-mono")
        return

    # ── Stats bar ─────────────────────────────────────────────────────────────
    total  = len(clips)
    exists = sum(1 for c in clips if c["exists"])
    rated  = sum(1 for c in clips if c["rating"] > 0)

    with ui.row().classes("gap-8 mb-6 text-sm"):
        _stat("Total", str(total), "text-gray-300")
        _stat("En disco", str(exists), "text-green-400" if exists == total else "text-orange-400")
        _stat("Valorados", str(rated), "text-blue-300")

    # ── Clip grid ─────────────────────────────────────────────────────────────
    grid = ui.element("div").classes("grid gap-4").style(
        "grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));"
    )
    with grid:
        for clip in clips:
            _render_clip_card(clip)


def _stat(label: str, value: str, value_cls: str) -> None:
    with ui.column().classes("gap-0 items-center"):
        ui.label(value).classes(f"text-2xl font-bold {value_cls}")
        ui.label(label).classes("text-xs text-gray-500 uppercase tracking-wide")


def _render_clip_card(clip: dict) -> None:
    exists  = clip["exists"]
    rating  = clip["rating"] or 0
    border  = "border-gray-700" if exists else "border-red-900 opacity-70"

    with ui.card().classes(
        f"w-full bg-gray-800 border {border} "
        "hover:border-blue-500 transition-all duration-200"
    ):
        # ── Top row ──────────────────────────────────────────────────────────
        with ui.row().classes("w-full items-center justify-between"):
            ui.label(clip["id"][:8]).classes("font-mono text-blue-300 font-bold text-base")
            if exists:
                ui.badge("En disco", color="positive").props("rounded")
            else:
                ui.badge("Archivo ausente", color="negative").props("rounded")

        ui.separator().classes("my-1 bg-gray-700")

        # ── Metadata ─────────────────────────────────────────────────────────
        with ui.grid(columns=2).classes("w-full gap-x-6 gap-y-1 text-sm"):
            ui.label("Duración").classes("text-gray-400")
            ui.label(clip["duration"]).classes("text-gray-200 font-mono")

            ui.label("Resolución").classes("text-gray-400")
            ui.label(clip["size"]).classes("text-gray-200 font-mono")

            ui.label("Renderizado").classes("text-gray-400")
            ui.label(clip["rendered"]).classes("text-gray-200 font-mono text-xs")

            ui.label("Rating").classes("text-gray-400")
            stars = "★" * rating + "☆" * (5 - rating)
            ui.label(stars).classes("text-yellow-400 font-mono tracking-widest")

        ui.separator().classes("my-1 bg-gray-700")

        # ── File path ────────────────────────────────────────────────────────
        ui.label(clip["path"]).classes(
            "text-gray-600 font-mono text-xs w-full truncate"
        ).style("max-width:100%;")

        # ── Actions ──────────────────────────────────────────────────────────
        with ui.row().classes("w-full justify-end gap-2 mt-2"):
            if exists:
                ui.button(
                    "Abrir carpeta", icon="folder_open"
                ).props("flat dense color=teal").on_click(
                    lambda _, p=clip["path"]: _open_folder(p)
                )
            ui.button(
                "Copiar ruta", icon="content_copy"
            ).props("flat dense color=grey").on_click(
                lambda _, p=clip["path"]: ui.run_javascript(
                    f"navigator.clipboard.writeText({repr(p)})"
                )
            )


def _open_folder(file_path: str) -> None:
    folder = str(Path(file_path).parent)
    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", folder])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", folder])
        else:
            subprocess.Popen(["xdg-open", folder])
    except Exception as exc:
        ui.notify(str(exc), type="negative")
