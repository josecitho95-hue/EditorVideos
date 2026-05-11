"""AutoEdit AI — NiceGUI web application entry point.

Pages
-----
  /            → redirect to /jobs
  /jobs        → card grid of all pipeline runs
  /timeline/{job_id} → interactive timeline editor
  /clips/{job_id}    → rendered clip gallery

JS ↔ Python communication for the timeline canvas is handled through two
FastAPI POST routes registered on NiceGUI's built-in app object:
  POST /api/gui/timeline/update  — JS sends updated EditDecision dict
  POST /api/gui/timeline/select  — JS sends current selection {track, index}
"""

from __future__ import annotations

from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse
from nicegui import app, ui

# ── Static assets ─────────────────────────────────────────────────────────────
_STATIC_DIR = Path(__file__).parent / "static"
app.add_static_files("/static", str(_STATIC_DIR))


# ── FastAPI routes for JS → Python timeline communication ─────────────────────

@app.post("/api/gui/timeline/update")
async def _timeline_update(request: Request) -> JSONResponse:
    """Called by timeline.js when the user drags a handle or moves an effect."""
    from autoedit.gui.pages import timeline as tl
    try:
        body = await request.json()
        tl._STATE["decision"] = body
        tl._STATE["dirty"] = True
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    return JSONResponse({"ok": True})


@app.post("/api/gui/timeline/select")
async def _timeline_select(request: Request) -> JSONResponse:
    """Called by timeline.js when the user clicks an effect block or handle."""
    from autoedit.gui.pages import timeline as tl
    try:
        body = await request.json()
        tl._STATE["selection"] = body
        tl._STATE["_sel_dirty"] = True  # consumed by the polling timer in build_timeline_page
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    return JSONResponse({"ok": True})


# ── Shared navigation header ─────────────────────────────────────────────────

def _nav_header() -> None:
    """Top navigation bar — rendered inside every page function."""
    with ui.header(elevated=True).classes(
        "bg-gray-950 border-b border-gray-800 px-4 py-2"
    ):
        with ui.row().classes("w-full items-center gap-4"):
            ui.label("AutoEdit AI").classes(
                "text-xl font-bold text-blue-400 tracking-tight shrink-0"
            )
            ui.separator().props("vertical").classes("bg-gray-700").style("height:24px;")
            with ui.row().classes("gap-1"):
                ui.button("Jobs", icon="work").props("flat color=grey-4").on_click(
                    lambda: ui.navigate.to("/jobs")
                )
            ui.space()
            ui.label("🎮 v0.1-dev").classes("text-xs text-gray-700 font-mono")


# ── Pages ─────────────────────────────────────────────────────────────────────

@ui.page("/")
def _page_root() -> None:
    ui.navigate.to("/jobs")


@ui.page("/jobs")
def _page_jobs() -> None:
    from autoedit.gui.data import ensure_db
    from autoedit.gui.pages.jobs import build_jobs_page

    ensure_db()
    _nav_header()
    with ui.column().classes("w-full max-w-7xl mx-auto px-4 py-6"):
        build_jobs_page()


@ui.page("/timeline/{job_id}")
def _page_timeline(job_id: str) -> None:
    from autoedit.gui.data import ensure_db
    from autoedit.gui.pages.timeline import build_timeline_page

    ensure_db()
    # Inject the canvas JS before any page content
    ui.add_head_html('<script src="/static/timeline.js" defer></script>')
    _nav_header()
    build_timeline_page(job_id)


@ui.page("/clips/{job_id}")
def _page_clips(job_id: str) -> None:
    from autoedit.gui.data import ensure_db
    from autoedit.gui.pages.clips import build_clips_page

    ensure_db()
    _nav_header()
    with ui.column().classes("w-full max-w-7xl mx-auto px-4 py-6"):
        build_clips_page(job_id)


# ── Entry point ───────────────────────────────────────────────────────────────

def launch(port: int = 7880, open_browser: bool = True) -> None:
    """Start the NiceGUI web server (blocks until interrupted)."""
    from autoedit.gui.data import ensure_db

    ensure_db()
    ui.run(
        port=port,
        title="AutoEdit AI",
        favicon="🎮",
        dark=True,
        show=open_browser,
        reload=False,
        storage_secret="autoedit-mono-tenant",
    )
