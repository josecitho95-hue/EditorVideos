"""Timeline editor page — /timeline/{job_id}.

Layout
------
┌─ left drawer (240px) ───────────────────┐  ┌─ main area ────────────────────────────┐
│ Highlights list (cards)                 │  │ Header: title + save/render buttons   │
│ - intent badge                          │  ├────────────────────────────────────────┤
│ - confidence                            │  │ Timeline canvas (interactive JS)       │
│ - click → loads that decision           │  ├────────────────────────────────────────┤
│                                         │  │ Properties panel (selected effect)     │
│                                         │  │  - form fields that update on select   │
│                                         │  │  - Narration: text textarea            │
│                                         │  │  - Zoom: intensity slider              │
└─────────────────────────────────────────┘  └────────────────────────────────────────┘
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from nicegui import ui

from autoedit.domain.edit_decision import (
    EditDecision,
    MemeOverlay,
    NarrationCue,
    SfxCue,
    Trim,
    ZoomEvent,
    ZoomKind,
)
from autoedit.gui.data import (
    get_edit_decision,
    get_window_for_highlight,
    list_highlights_for_job,
    save_edit_decision,
)
from autoedit.settings import settings

INTENT_COLORS: dict[str, str] = {
    "fail":         "red",
    "win":          "green",
    "reaction":     "purple",
    "rage":         "deep-orange",
    "funny_moment": "amber",
    "skill_play":   "cyan",
    "wholesome":    "pink",
    "other":        "grey",
}


# ---------------------------------------------------------------------------
# In-memory session state (mono-tenant, one browser at a time)
# ---------------------------------------------------------------------------

_STATE: dict[str, Any] = {
    "job_id":        None,
    "highlight_id":  None,
    "decision":      None,   # EditDecision dict (plain JSON)
    "duration":      60.0,
    "dirty":         False,
    "selection":     None,   # {track, handle, index, effect}
    "_sel_dirty":    False,  # set by /api/gui/timeline/select route; consumed by polling timer
}


def build_timeline_page(job_id: str) -> None:
    """Render the full timeline editor for a job."""
    _STATE["job_id"] = job_id

    highlights = list_highlights_for_job(job_id)

    # ── Sidebar (highlight list) ───────────────────────────────────────────────
    with ui.left_drawer(value=True).classes(
        "bg-gray-900 border-r border-gray-700"
    ).style("width: 260px;"):
        ui.label("Highlights").classes("text-lg font-bold text-blue-300 px-4 pt-4 pb-2")
        ui.separator().classes("bg-gray-700 mb-2")

        if not highlights:
            ui.label("Sin highlights").classes("text-gray-500 text-sm px-4")
        else:
            with ui.scroll_area().style("height: calc(100vh - 80px);"):
                for h in highlights:
                    _build_highlight_card(h)

    # ── Main content ────────────────────────────────────────────────────────────
    with ui.column().classes("w-full h-full gap-0"):
        _build_main_area(job_id)


def _build_highlight_card(h: dict) -> None:
    intent  = h["intent"]
    color   = INTENT_COLORS.get(intent, "grey")
    conf_pct = int(h["confidence"] * 100)

    with ui.card().classes(
        "w-full mx-2 mb-2 bg-gray-800 border border-gray-700 "
        "hover:border-blue-400 cursor-pointer transition-all"
    ).style("margin-left:8px; margin-right:8px; width:calc(100% - 16px);") as card:
        with ui.row().classes("items-center justify-between w-full"):
            ui.badge(intent, color=color).props("rounded dense")
            ui.label(f"{conf_pct}%").classes("text-xs text-gray-400 font-mono")
        ui.label(h["title"]).classes("text-sm text-gray-200 mt-1 leading-tight")
        ui.label(
            f"{h['window_start']:.0f}s – {h['window_end']:.0f}s"
            f"  ({h['window_duration']:.0f}s)"
        ).classes("text-xs font-mono text-gray-500 mt-1")

        if not h["has_decision"]:
            ui.label("Sin decisión").classes("text-xs text-orange-400 mt-1")

    card.on_click(lambda _, hid=h["id"]: _load_highlight(hid))


def _build_main_area(job_id: str) -> None:
    # ── Top bar ────────────────────────────────────────────────────────────────
    with ui.row().classes(
        "w-full items-center justify-between px-4 py-3 "
        "bg-gray-900 border-b border-gray-700"
    ):
        title_label = ui.label("Selecciona un highlight").classes(
            "text-xl font-bold text-white truncate"
        ).style("max-width:60%;")
        dirty_badge = ui.badge("Sin cambios", color="grey").props("rounded")
        dirty_badge.set_visibility(False)

        with ui.row().classes("gap-2"):
            save_btn = ui.button("Guardar", icon="save").props("color=green")
            render_btn = ui.button("Re-render", icon="movie").props("color=blue outlined")
            tiktok_btn = ui.button("TikTok", icon="smartphone").props("color=purple outlined")
            split_btn  = ui.button("Split", icon="view_agenda").props("color=deep-purple outlined")

    save_btn.set_enabled(False)
    render_btn.set_enabled(False)
    tiktok_btn.set_enabled(False)
    split_btn.set_enabled(False)

    # ── Timeline canvas ────────────────────────────────────────────────────────
    with ui.card().classes("mx-4 mt-3 bg-gray-800 border border-gray-700").style("padding:12px;"):
        ui.label("Timeline").classes("text-xs text-gray-400 mb-2 font-mono uppercase")
        canvas_container = ui.element("div").style(
            "width:100%; min-height:280px; background:#0f172a; border-radius:8px;"
        )
        canvas_container.props('id="timeline-container"')

    # ── Status bar (underneath timeline) ─────────────────────────────────────
    status_row = ui.row().classes("w-full px-4 py-1 gap-4 text-xs font-mono text-gray-500")
    with status_row:
        dur_label   = ui.label("Duración: —")
        sel_label   = ui.label("Selección: —")
        offset_label = ui.label("Ventana: —")

    # ── Properties panel ──────────────────────────────────────────────────────
    with ui.card().classes("mx-4 mt-3 mb-4 bg-gray-800 border border-gray-700"):
        with ui.row().classes("w-full items-center justify-between px-4 py-2 border-b border-gray-700"):
            props_title = ui.label("Propiedades").classes("text-sm font-bold text-gray-300")
            with ui.row().classes("gap-2"):
                add_zoom_btn = ui.button("+ Zoom",      icon="zoom_in"   ).props("flat dense color=teal")
                add_meme_btn = ui.button("+ Meme",      icon="image"     ).props("flat dense color=pink")
                add_sfx_btn  = ui.button("+ SFX",       icon="music_note").props("flat dense color=orange")
                add_nar_btn  = ui.button("+ Narración", icon="mic"       ).props("flat dense color=purple")
                del_btn      = ui.button("Eliminar",    icon="delete"    ).props("flat dense color=red")

        props_area = ui.element("div").classes("p-4")
        with props_area:
            no_sel_label = ui.label("Haz clic en un elemento del timeline para editarlo.")\
                .classes("text-gray-500 text-sm")

    add_zoom_btn.set_enabled(False)
    add_meme_btn.set_enabled(False)
    add_sfx_btn.set_enabled(False)
    add_nar_btn.set_enabled(False)
    del_btn.set_enabled(False)

    # ── Narration text rationale ──────────────────────────────────────────────
    with ui.card().classes("mx-4 mb-4 bg-gray-800 border border-gray-700"):
        with ui.row().classes("w-full items-center px-4 py-2 border-b border-gray-700"):
            ui.icon("notes").classes("text-gray-400")
            ui.label("Razonamiento del Director").classes("text-sm font-bold text-gray-300 ml-2")
        rationale_label = ui.label("—").classes("text-gray-400 text-sm px-4 py-3 italic")

    # =========================================================================
    # Helper closures — capture all widgets by reference
    # =========================================================================

    def _mark_dirty() -> None:
        _STATE["dirty"] = True
        dirty_badge.set_text("Cambios sin guardar")
        dirty_badge.props("color=orange")
        dirty_badge.set_visibility(True)

    def _mark_clean() -> None:
        _STATE["dirty"] = False
        dirty_badge.set_text("Guardado ✓")
        dirty_badge.props("color=green")
        dirty_badge.set_visibility(True)

    def _push_to_canvas(data: dict | None = None) -> None:
        """Send current (or given) decision data to the JS timeline."""
        d = data or _STATE.get("decision")
        if d is None:
            return
        safe = json.dumps(d).replace("'", "\\'")
        ui.run_javascript(f"window.timelineAPI.setData({safe});")

    def _refresh_props_panel() -> None:
        """Redraw the properties panel for the current selection."""
        sel = _STATE.get("selection")
        decision = _STATE.get("decision")
        props_area.clear()
        with props_area:
            if sel is None or decision is None:
                ui.label("Haz clic en un elemento del timeline para editarlo.")\
                    .classes("text-gray-500 text-sm")
                del_btn.set_enabled(False)
                return

            del_btn.set_enabled(True)
            track   = sel.get("track")
            handle  = sel.get("handle")
            idx     = sel.get("index")
            effect  = sel.get("effect") or {}

            if track == "trim" and handle:
                _render_trim_props(decision, _mark_dirty, _push_to_canvas)
            elif track == "zoom" and idx is not None:
                _render_zoom_props(decision, idx, _mark_dirty, _push_to_canvas)
            elif track == "meme" and idx is not None:
                _render_meme_props(decision, idx, _mark_dirty, _push_to_canvas)
            elif track == "sfx" and idx is not None:
                _render_sfx_props(decision, idx, _mark_dirty, _push_to_canvas)
            elif track == "narration" and idx is not None:
                _render_narration_props(decision, idx, _mark_dirty, _push_to_canvas)
            else:
                ui.label(f"Track: {track}").classes("text-gray-400 text-sm")

    def _load_highlight_internal(highlight_id: str) -> None:
        ed = get_edit_decision(highlight_id)
        win = get_window_for_highlight(highlight_id)

        _STATE["highlight_id"] = highlight_id
        _STATE["dirty"] = False
        _STATE["selection"] = None

        if ed is None:
            title_label.set_text("Sin decisión editorial")
            dirty_badge.set_visibility(False)
            rationale_label.set_text("Este highlight no tiene plan de edición. Ejecuta E7 primero.")
            save_btn.set_enabled(False)
            render_btn.set_enabled(False)
            tiktok_btn.set_enabled(False)
            split_btn.set_enabled(False)
            add_zoom_btn.set_enabled(False)
            add_meme_btn.set_enabled(False)
            add_sfx_btn.set_enabled(False)
            add_nar_btn.set_enabled(False)
            return

        win_start = win["start_sec"] if win else 0.0
        win_end   = win["end_sec"]   if win else ed.trim.end_sec + 5
        duration  = win_end - win_start

        _STATE["duration"] = duration
        _STATE["window_offset"] = win_start

        # Build timeline-compatible dict
        d = ed.model_dump(mode="json")
        d["duration"] = duration
        _STATE["decision"] = d

        title_label.set_text(ed.title)
        rationale_label.set_text(ed.rationale or "—")
        dirty_badge.set_visibility(False)

        dur_label.set_text(f"Duración: {duration:.1f}s")
        offset_label.set_text(f"Ventana: {win_start:.1f}s–{win_end:.1f}s")
        sel_label.set_text("Selección: —")

        save_btn.set_enabled(True)
        render_btn.set_enabled(True)
        tiktok_btn.set_enabled(True)
        split_btn.set_enabled(True)
        add_zoom_btn.set_enabled(True)
        add_meme_btn.set_enabled(True)
        add_sfx_btn.set_enabled(True)
        add_nar_btn.set_enabled(True)

        _push_to_canvas(d)
        _refresh_props_panel()

    # Wire global load function so sidebar cards can call it
    global _load_highlight
    _load_highlight = _load_highlight_internal

    # ── Save ──────────────────────────────────────────────────────────────────

    def on_save() -> None:
        d = _STATE.get("decision")
        hid = _STATE.get("highlight_id")
        if not d or not hid:
            return
        try:
            ed = EditDecision.model_validate(d)
            ok = save_edit_decision(ed)
            if ok:
                _mark_clean()
                ui.notify("Guardado correctamente", type="positive")
            else:
                ui.notify("Error al guardar", type="negative")
        except Exception as exc:
            ui.notify(f"Error: {exc}", type="negative")

    save_btn.on_click(on_save)

    # ── Re-render ─────────────────────────────────────────────────────────────

    def _run_render(fmt: str, layout: str = "crop") -> None:
        jid = _STATE.get("job_id")
        if not jid:
            return
        on_save()   # auto-save before render
        cmd = [
            "uv", "run", "autoedit", "render", "edit",
            "--job-id", jid, "--format", fmt, "--layout", layout,
        ]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=600,
                cwd=str(Path(__file__).parents[5]),
                encoding="utf-8", errors="replace",
            )
            out = result.stdout + result.stderr
            snippet = out[-1500:] if len(out) > 1500 else out
            with ui.dialog() as dlg, ui.card().classes("bg-gray-900 w-full max-w-2xl"):
                ui.label(f"Render {fmt.upper()} — {'OK' if result.returncode == 0 else 'FAILED'}")\
                    .classes("text-lg font-bold " + ("text-green-400" if result.returncode == 0 else "text-red-400"))
                ui.code(snippet, language="bash").classes("w-full text-xs max-h-64 overflow-auto")
                ui.button("Cerrar", on_click=dlg.close).props("flat color=grey")
            dlg.open()
        except Exception as exc:
            ui.notify(str(exc), type="negative")

    render_btn.on_click(lambda: _run_render("youtube"))
    tiktok_btn.on_click(lambda: _run_render("tiktok"))
    split_btn.on_click(lambda: _run_render("tiktok", "split"))

    # ── Add-effect buttons ───────────────────────────────────────────────────

    def _add_effect(track: str) -> None:
        d = _STATE.get("decision")
        if not d:
            return
        mid = d.get("duration", 60.0) / 2

        if track == "zoom":
            d.setdefault("zoom_events", []).append({
                "at_sec": mid, "duration_sec": 1.0,
                "kind": "punch_in", "intensity": 1.5,
            })
        elif track == "meme":
            d.setdefault("meme_overlays", []).append({
                "asset_id": "???", "at_sec": mid, "duration_sec": 2.0,
                "position": "center", "scale": 0.5,
                "enter_anim": "pop", "exit_anim": "fade",
            })
        elif track == "sfx":
            d.setdefault("sfx_cues", []).append({
                "asset_id": "???", "at_sec": mid, "volume_db": -6.0,
            })
        elif track == "narration":
            d.setdefault("narration_cues", []).append({
                "text": "Bro de verdad hizo eso...",
                "at_sec": mid, "voice_id": "me_v1",
                "duck_main_audio_db": -12.0,
            })

        _mark_dirty()
        _push_to_canvas(d)

    add_zoom_btn.on_click(lambda: _add_effect("zoom"))
    add_meme_btn.on_click(lambda: _add_effect("meme"))
    add_sfx_btn.on_click(lambda: _add_effect("sfx"))
    add_nar_btn.on_click(lambda: _add_effect("narration"))

    # ── Delete ────────────────────────────────────────────────────────────────

    def on_delete() -> None:
        sel = _STATE.get("selection")
        d   = _STATE.get("decision")
        if not sel or not d:
            return
        track = sel.get("track")
        idx   = sel.get("index")
        key_map = {
            "zoom": "zoom_events", "meme": "meme_overlays",
            "sfx": "sfx_cues", "narration": "narration_cues",
        }
        key = key_map.get(track)
        if key and idx is not None and 0 <= idx < len(d.get(key, [])):
            d[key].pop(idx)
            _STATE["selection"] = None
            _mark_dirty()
            _push_to_canvas(d)
            _refresh_props_panel()
            sel_label.set_text("Selección: —")

    del_btn.on_click(on_delete)

    # ── Polling timer — picks up selection changes posted by timeline.js ──────
    # The FastAPI route /api/gui/timeline/select sets _STATE["_sel_dirty"] = True.
    # We can't call UI functions from that thread, so we poll here at 300 ms.

    def _poll_selection() -> None:
        if not _STATE.get("_sel_dirty"):
            return
        _STATE["_sel_dirty"] = False
        _refresh_props_panel()
        sel = _STATE.get("selection") or {}
        track = sel.get("track", "—")
        idx   = sel.get("index")
        sel_label.set_text(
            f"Selección: {track}" + (f" #{idx + 1}" if idx is not None else "")
        )

    ui.timer(0.30, _poll_selection)


# ---------------------------------------------------------------------------
# Per-track properties panels
# ---------------------------------------------------------------------------

def _render_trim_props(d: dict, mark_dirty, push_canvas) -> None:
    trim = d.get("trim", {})
    ui.label("Trim — Inicio / Fin").classes("text-sm font-bold text-blue-300 mb-2")
    with ui.grid(columns=2).classes("w-full gap-3"):
        with ui.column():
            ui.label("Inicio (s)").classes("text-xs text-gray-400")
            start_inp = ui.number(value=trim.get("start_sec", 0.0), step=0.1, format="%.1f")\
                .classes("w-full")

        with ui.column():
            ui.label("Fin (s)").classes("text-xs text-gray-400")
            end_inp = ui.number(value=trim.get("end_sec", 30.0), step=0.1, format="%.1f")\
                .classes("w-full")

    ui.label("Razón").classes("text-xs text-gray-400 mt-2")
    reason_inp = ui.input(value=trim.get("reason", "")).classes("w-full")

    def apply() -> None:
        d["trim"]["start_sec"] = float(start_inp.value)
        d["trim"]["end_sec"]   = float(end_inp.value)
        d["trim"]["reason"]    = reason_inp.value
        mark_dirty()
        push_canvas()

    ui.button("Aplicar", on_click=apply).props("color=blue dense").classes("mt-3")


def _render_zoom_props(d: dict, idx: int, mark_dirty, push_canvas) -> None:
    zooms = d.get("zoom_events", [])
    if idx >= len(zooms):
        return
    z = zooms[idx]
    ui.label(f"Zoom #{idx + 1}").classes("text-sm font-bold text-teal-300 mb-2")
    with ui.grid(columns=2).classes("w-full gap-3"):
        with ui.column():
            ui.label("Tiempo (s)").classes("text-xs text-gray-400")
            at_inp  = ui.number(value=z.get("at_sec", 0), step=0.1, format="%.1f").classes("w-full")
        with ui.column():
            ui.label("Duración (s)").classes("text-xs text-gray-400")
            dur_inp = ui.number(value=z.get("duration_sec", 1.0), step=0.1, format="%.1f").classes("w-full")

    ui.label("Intensidad").classes("text-xs text-gray-400 mt-2")
    int_sl = ui.slider(min=1.0, max=2.5, step=0.05, value=z.get("intensity", 1.5)).classes("w-full")
    ui.label().bind_text_from(int_sl, "value", lambda v: f"{v:.2f}×").classes("text-teal-300 text-sm")

    def apply() -> None:
        zooms[idx]["at_sec"]       = float(at_inp.value)
        zooms[idx]["duration_sec"] = float(dur_inp.value)
        zooms[idx]["intensity"]    = float(int_sl.value)
        mark_dirty()
        push_canvas()

    ui.button("Aplicar", on_click=apply).props("color=teal dense").classes("mt-3")


def _render_meme_props(d: dict, idx: int, mark_dirty, push_canvas) -> None:
    memes = d.get("meme_overlays", [])
    if idx >= len(memes):
        return
    m = memes[idx]
    ui.label(f"Meme #{idx + 1}").classes("text-sm font-bold text-pink-300 mb-2")
    with ui.grid(columns=2).classes("w-full gap-3"):
        with ui.column():
            ui.label("Tiempo (s)").classes("text-xs text-gray-400")
            at_inp  = ui.number(value=m.get("at_sec", 0), step=0.1, format="%.1f").classes("w-full")
        with ui.column():
            ui.label("Duración (s)").classes("text-xs text-gray-400")
            dur_inp = ui.number(value=m.get("duration_sec", 2.0), step=0.1, format="%.1f").classes("w-full")

    ui.label("Asset ID").classes("text-xs text-gray-400 mt-2")
    aid_inp = ui.input(value=m.get("asset_id", "")).classes("w-full font-mono text-sm")

    ui.label("Escala").classes("text-xs text-gray-400 mt-2")
    scale_sl = ui.slider(min=0.1, max=1.0, step=0.05, value=m.get("scale", 0.5)).classes("w-full")
    ui.label().bind_text_from(scale_sl, "value", lambda v: f"{v:.2f}").classes("text-pink-300 text-sm")

    with ui.grid(columns=2).classes("w-full gap-3 mt-2"):
        with ui.column():
            ui.label("Posición").classes("text-xs text-gray-400")
            pos_sel = ui.select(
                ["center", "top_left", "top_right", "bottom_left", "bottom_right"],
                value=m.get("position", "center"),
            ).classes("w-full")
        with ui.column():
            ui.label("Entrada").classes("text-xs text-gray-400")
            enter_sel = ui.select(
                ["pop", "slide_in", "fade_in", "bounce"],
                value=m.get("enter_anim", "pop"),
            ).classes("w-full")

    def apply() -> None:
        memes[idx]["at_sec"]       = float(at_inp.value)
        memes[idx]["duration_sec"] = float(dur_inp.value)
        memes[idx]["asset_id"]     = aid_inp.value.strip()
        memes[idx]["scale"]        = float(scale_sl.value)
        memes[idx]["position"]     = pos_sel.value
        memes[idx]["enter_anim"]   = enter_sel.value
        mark_dirty()
        push_canvas()

    ui.button("Aplicar", on_click=apply).props("color=pink dense").classes("mt-3")


def _render_sfx_props(d: dict, idx: int, mark_dirty, push_canvas) -> None:
    cues = d.get("sfx_cues", [])
    if idx >= len(cues):
        return
    s = cues[idx]
    ui.label(f"SFX #{idx + 1}").classes("text-sm font-bold text-orange-300 mb-2")
    with ui.grid(columns=2).classes("w-full gap-3"):
        with ui.column():
            ui.label("Tiempo (s)").classes("text-xs text-gray-400")
            at_inp = ui.number(value=s.get("at_sec", 0), step=0.1, format="%.1f").classes("w-full")
        with ui.column():
            ui.label("Volumen (dB)").classes("text-xs text-gray-400")
            vol_inp = ui.number(value=s.get("volume_db", -6.0), step=0.5, format="%.1f").classes("w-full")

    ui.label("Asset ID").classes("text-xs text-gray-400 mt-2")
    aid_inp = ui.input(value=s.get("asset_id", "")).classes("w-full font-mono text-sm")

    def apply() -> None:
        cues[idx]["at_sec"]    = float(at_inp.value)
        cues[idx]["volume_db"] = float(vol_inp.value)
        cues[idx]["asset_id"]  = aid_inp.value.strip()
        mark_dirty()
        push_canvas()

    ui.button("Aplicar", on_click=apply).props("color=orange dense").classes("mt-3")


def _render_narration_props(d: dict, idx: int, mark_dirty, push_canvas) -> None:
    cues = d.get("narration_cues", [])
    if idx >= len(cues):
        return
    n = cues[idx]
    ui.label(f"Narración #{idx + 1}").classes("text-sm font-bold text-purple-300 mb-2")
    with ui.grid(columns=2).classes("w-full gap-3"):
        with ui.column():
            ui.label("Tiempo (s)").classes("text-xs text-gray-400")
            at_inp  = ui.number(value=n.get("at_sec", 0), step=0.1, format="%.1f").classes("w-full")
        with ui.column():
            ui.label("Duck audio (dB)").classes("text-xs text-gray-400")
            duck_inp = ui.number(value=n.get("duck_main_audio_db", -12.0), step=1.0, format="%.0f")\
                .classes("w-full")

    ui.label("Texto de narración").classes("text-xs text-gray-400 mt-2")
    text_inp = ui.textarea(value=n.get("text", "")).props("rows=3").classes("w-full")

    ui.label("Voz").classes("text-xs text-gray-400 mt-2")
    voice_inp = ui.input(value=n.get("voice_id", "me_v1")).classes("w-full font-mono text-sm")

    def apply() -> None:
        cues[idx]["at_sec"]             = float(at_inp.value)
        cues[idx]["duck_main_audio_db"] = float(duck_inp.value)
        cues[idx]["text"]               = text_inp.value.strip()
        cues[idx]["voice_id"]           = voice_inp.value.strip()
        mark_dirty()
        push_canvas()

    ui.button("Aplicar", on_click=apply).props("color=purple dense").classes("mt-3")


# ---------------------------------------------------------------------------
# Global placeholder — overwritten by build_timeline_page() at runtime
# ---------------------------------------------------------------------------

def _load_highlight(highlight_id: str) -> None:
    """Placeholder, replaced at runtime."""
