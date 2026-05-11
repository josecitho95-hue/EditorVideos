"""AutoEdit Dashboard — Gradio web UI for reviewing, rating and managing clips.

Launch via:
    autoedit dashboard          # opens browser on http://localhost:7860
    autoedit dashboard --port 7861 --no-browser
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import gradio as gr

from autoedit.settings import settings
from autoedit.storage.db import get_session, init_db
from autoedit.storage.repositories.jobs import JobRepository
from autoedit.storage.repositories.windows import WindowRepository


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def _all_jobs() -> list[dict[str, Any]]:
    """Return all jobs as a list of dicts for display."""
    try:
        jobs = JobRepository().list_all()
        return [
            {
                "id": j.id[:12],
                "full_id": j.id,
                "status": j.status.value,
                "stage": j.current_stage.value if j.current_stage else "—",
                "vod": (j.vod_url or "")[-50:],
                "created": str(j.created_at)[:16],
            }
            for j in jobs
        ]
    except Exception as exc:
        return [{"error": str(exc)}]


def _job_choices() -> list[str]:
    """Return list of 'job_id  (status)' strings for dropdowns."""
    jobs = JobRepository().list_all()
    return [f"{j.id}  ({j.status.value})" for j in jobs] or ["(no jobs)"]


def _parse_job_id(choice: str) -> str:
    """Extract job_id from a dropdown choice string."""
    return choice.split("  ")[0].strip()


def _clips_for_job(job_id: str) -> list[dict[str, Any]]:
    """Return clip metadata for a job."""
    from autoedit.storage.db import ClipModel
    from sqlmodel import select

    try:
        with get_session() as session:
            clips = session.exec(
                select(ClipModel).where(ClipModel.job_id == job_id)
            ).all()
        return [
            {
                "clip_id": c.id,
                "path": c.output_path,
                "duration": f"{c.duration_sec:.1f}s",
                "size": f"{c.width}×{c.height}",
                "rendered": c.rendered_at[:16] if c.rendered_at else "—",
                "rating": c.user_rating or 0,
                "note": c.user_note or "",
            }
            for c in clips
            if Path(c.output_path).exists()
        ]
    except Exception as exc:
        return [{"error": str(exc)}]


def _edit_decision_for_clip(clip_id: str) -> dict[str, Any] | None:
    """Return the edit decision plan linked to a clip (via highlight_id)."""
    from autoedit.storage.db import ClipModel, EditDecisionModel
    from sqlmodel import select

    try:
        with get_session() as session:
            clip = session.exec(
                select(ClipModel).where(ClipModel.id == clip_id)
            ).first()
            if not clip or not clip.highlight_id:
                return None
            ed = session.exec(
                select(EditDecisionModel).where(
                    EditDecisionModel.highlight_id == clip.highlight_id
                )
            ).first()
            return ed.plan if ed else None
    except Exception:
        return None


def _save_clip_rating(clip_id: str, rating: int, note: str) -> str:
    """Persist user_rating and user_note for a clip."""
    from autoedit.storage.db import ClipModel
    from sqlmodel import select

    try:
        with get_session() as session:
            clip = session.exec(
                select(ClipModel).where(ClipModel.id == clip_id)
            ).first()
            if not clip:
                return "Clip not found"
            clip.user_rating = int(rating)
            clip.user_note = str(note)
            session.add(clip)
            session.commit()
        return f"Saved — {rating}⭐ for clip {clip_id[:8]}"
    except Exception as exc:
        return f"Error: {exc}"


# ---------------------------------------------------------------------------
# Tab builders
# ---------------------------------------------------------------------------

def build_jobs_tab() -> None:
    """Render the Jobs tab content."""
    gr.Markdown("### All jobs")

    with gr.Row():
        refresh_btn = gr.Button("Refresh", variant="secondary", scale=0)

    jobs_table = gr.DataFrame(
        headers=["id", "status", "stage", "vod", "created"],
        datatype=["str", "str", "str", "str", "str"],
        interactive=False,
        wrap=True,
    )

    def load_jobs():
        rows = _all_jobs()
        return [[r.get(k, "") for k in ("id", "status", "stage", "vod", "created")] for r in rows]

    refresh_btn.click(load_jobs, outputs=jobs_table)
    # Auto-load on tab open via a dummy state trigger
    jobs_table.value = load_jobs()  # type: ignore[assignment]


def build_clips_tab() -> None:
    """Render the Clips Viewer tab content."""
    gr.Markdown("### Clip Review")

    with gr.Row():
        job_dd = gr.Dropdown(
            label="Job",
            choices=_job_choices(),
            scale=3,
        )
        fmt_dd = gr.Dropdown(
            label="Format",
            choices=["youtube", "tiktok", "shorts", "square"],
            value="youtube",
            scale=1,
        )
        load_btn = gr.Button("Load clips", variant="primary", scale=0)

    clip_dd = gr.Dropdown(label="Select clip", choices=[], interactive=True)
    status_box = gr.Textbox(label="", interactive=False, lines=1)

    with gr.Row():
        with gr.Column(scale=3):
            video_player = gr.Video(label="Clip preview", interactive=False, height=400)

        with gr.Column(scale=2):
            title_box   = gr.Textbox(label="Title", interactive=False)
            timing_box  = gr.Textbox(label="Timing", interactive=False)
            effects_box = gr.Textbox(label="Effects", interactive=False, lines=4)
            rating_sl   = gr.Slider(0, 5, step=1, label="Rating ⭐", value=0)
            note_box    = gr.Textbox(label="Notes", placeholder="Your comments…", lines=2)

    with gr.Row():
        save_btn    = gr.Button("Save rating", variant="secondary")
        rerender_btn = gr.Button("Re-render this clip", variant="secondary")

    save_status = gr.Textbox(label="", interactive=False, lines=1)

    # Internal state: list of clip dicts, current clip_id
    _clips_state: gr.State = gr.State([])
    _clip_id_state: gr.State = gr.State("")

    def on_load(job_choice: str, fmt: str):
        if not job_choice or job_choice == "(no jobs)":
            return gr.update(choices=[]), [], ""
        job_id = _parse_job_id(job_choice)
        clips = _clips_for_job(job_id)
        if not clips or "error" in clips[0]:
            return gr.update(choices=["(no clips)"]), clips, "No clips found — render first."
        choices = [f"{c['clip_id'][:8]}  {c['duration']}  {c['size']}  ⭐{c['rating']}" for c in clips]
        return gr.update(choices=choices, value=choices[0] if choices else None), clips, f"{len(clips)} clip(s) loaded."

    def on_clip_select(choice: str, clips: list):
        if not choice or not clips:
            return None, "", "", "", 0, "", ""
        # Choice format: "CLIPID8  Xs  WxH  ⭐N"
        clip_id_prefix = choice.split("  ")[0].strip()
        clip = next((c for c in clips if c["clip_id"].startswith(clip_id_prefix)), None)
        if not clip:
            return None, "", "", "", 0, "", ""

        plan = _edit_decision_for_clip(clip["clip_id"])
        if plan:
            title = plan.get("title", "—")
            effects_lines = [
                f"Zooms:    {len(plan.get('zoom_events', []))}",
                f"Memes:    {len(plan.get('meme_overlays', []))}",
                f"SFX:      {len(plan.get('sfx_cues', []))}",
                f"Narration:{len(plan.get('narration_cues', []))}",
                "",
                plan.get("rationale", ""),
            ]
            effects = "\n".join(effects_lines)
        else:
            title = "—"
            effects = "(no edit decision)"
        timing = f"{clip['duration']}  |  {clip['rendered']}"

        rating = clip.get("rating") or 0
        note = clip.get("note") or ""

        return clip["path"], title, timing, effects, rating, note, clip["clip_id"]

    def on_save(clip_id: str, rating: int, note: str):
        if not clip_id:
            return "No clip selected"
        return _save_clip_rating(clip_id, rating, note)

    def on_rerender(job_choice: str, fmt: str, clip_id: str):
        """Re-render a single clip by running the full render edit command."""
        if not job_choice or not clip_id:
            return "Select a clip first"
        job_id = _parse_job_id(job_choice)
        cmd = [
            "uv", "run", "autoedit", "render", "edit",
            "--job-id", job_id,
            "--format", fmt,
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                                    cwd=str(Path(__file__).parents[4]))
            if result.returncode == 0:
                return "Re-render complete."
            return f"Re-render failed:\n{result.stderr[-500:]}"
        except Exception as exc:
            return f"Error: {exc}"

    load_btn.click(
        on_load,
        inputs=[job_dd, fmt_dd],
        outputs=[clip_dd, _clips_state, status_box],
    )

    clip_dd.change(
        on_clip_select,
        inputs=[clip_dd, _clips_state],
        outputs=[video_player, title_box, timing_box, effects_box, rating_sl, note_box, _clip_id_state],
    )

    save_btn.click(
        on_save,
        inputs=[_clip_id_state, rating_sl, note_box],
        outputs=[save_status],
    )

    rerender_btn.click(
        on_rerender,
        inputs=[job_dd, fmt_dd, _clip_id_state],
        outputs=[save_status],
    )


def build_pipeline_tab() -> None:
    """Render the Pipeline / Re-direct tab content."""
    gr.Markdown("### Re-run Director (E6 → E7 → E8)")
    gr.Markdown(
        "Re-generates edit decisions for an existing job without re-running "
        "transcription and scoring (E1–E5 stay intact)."
    )

    with gr.Row():
        job_dd = gr.Dropdown(
            label="Job",
            choices=_job_choices(),
            scale=3,
        )
        skip_tts_cb = gr.Checkbox(label="Skip TTS (E8)", value=False, scale=1)

    with gr.Row():
        direct_btn  = gr.Button("Re-direct job", variant="primary")
        render_btn  = gr.Button("Render after (YouTube)", variant="secondary")
        render_tiktok_btn = gr.Button("Render after (TikTok)", variant="secondary")

    output_box = gr.Textbox(label="Output", lines=10, interactive=False)

    def run_direct(job_choice: str, skip_tts: bool):
        if not job_choice or job_choice == "(no jobs)":
            return "Select a job first"
        job_id = _parse_job_id(job_choice)
        cmd = ["uv", "run", "autoedit", "job", "direct", job_id]
        if skip_tts:
            cmd.append("--skip-tts")
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=600,
                cwd=str(Path(__file__).parents[4]),
                encoding="utf-8", errors="replace",
            )
            out = result.stdout + result.stderr
            return out[-3000:] if len(out) > 3000 else out
        except Exception as exc:
            return f"Error: {exc}"

    def run_render(job_choice: str, fmt: str):
        if not job_choice or job_choice == "(no jobs)":
            return "Select a job first"
        job_id = _parse_job_id(job_choice)
        cmd = ["uv", "run", "autoedit", "render", "edit",
               "--job-id", job_id, "--format", fmt]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=600,
                cwd=str(Path(__file__).parents[4]),
                encoding="utf-8", errors="replace",
            )
            out = result.stdout + result.stderr
            return out[-3000:] if len(out) > 3000 else out
        except Exception as exc:
            return f"Error: {exc}"

    direct_btn.click(run_direct, inputs=[job_dd, skip_tts_cb], outputs=[output_box])
    render_btn.click(lambda jc: run_render(jc, "youtube"), inputs=[job_dd], outputs=[output_box])
    render_tiktok_btn.click(lambda jc: run_render(jc, "tiktok"), inputs=[job_dd], outputs=[output_box])


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def build_app() -> gr.Blocks:
    init_db()

    with gr.Blocks(title="AutoEdit Dashboard") as demo:
        gr.Markdown("# 🎬 AutoEdit Dashboard")
        gr.Markdown("Review clips, rate quality, and trigger re-renders without touching the CLI.")

        with gr.Tabs():
            with gr.Tab("📋 Jobs"):
                build_jobs_tab()

            with gr.Tab("🎞️ Clips Viewer"):
                build_clips_tab()

            with gr.Tab("🎬 Re-direct"):
                build_pipeline_tab()

    return demo


def launch(port: int = 7860, open_browser: bool = True) -> None:
    app = build_app()
    app.launch(
        server_port=port,
        inbrowser=open_browser,
        share=False,
        show_error=True,
        theme=gr.themes.Soft(primary_hue="violet"),
    )
