"""Main CLI entrypoint for AutoEdit AI."""

import typer

from autoedit.cli.commands.assets import app as assets_app
from autoedit.cli.commands.db import app as db_app
from autoedit.cli.commands.doctor import app as doctor_app
from autoedit.cli.commands.job import app as job_app
from autoedit.cli.commands.ping import app as ping_app
from autoedit.cli.commands.render import app as render_app
from autoedit.cli.commands.voice import app as voice_app
from autoedit.cli.commands.worker import app as worker_app

app = typer.Typer(
    name="autoedit",
    help="AutoEdit AI - Twitch VOD to edited clips",
    no_args_is_help=True,
)

app.add_typer(doctor_app, name="doctor", help="Health checks")
app.add_typer(db_app, name="db", help="Database operations")
app.add_typer(ping_app, name="ping", help="Ping OpenRouter")
app.add_typer(job_app, name="job", help="Job operations")
app.add_typer(render_app, name="render", help="Render clips from windows")
app.add_typer(voice_app, name="voice", help="Voice profile management (TTS)")
app.add_typer(assets_app, name="assets", help="Asset catalog management (emotes, SFX, images)")
app.add_typer(worker_app, name="worker", help="Worker operations")


@app.command()
def dashboard(
    port: int = typer.Option(7860, "--port", "-p", help="Port to listen on"),
    no_browser: bool = typer.Option(False, "--no-browser", help="Do not open browser automatically"),
) -> None:
    """Launch the Gradio review dashboard (http://localhost:7860).

    Review rendered clips, rate quality 1-5 stars, add notes, and
    trigger re-renders or re-direct passes without touching the CLI.

    Example::

        autoedit dashboard
        autoedit dashboard --port 7861 --no-browser
    """
    from autoedit.dashboard.app import launch
    launch(port=port, open_browser=not no_browser)


@app.command()
def gui(
    port: int = typer.Option(7880, "--port", "-p", help="Port to listen on"),
    no_browser: bool = typer.Option(False, "--no-browser", help="Do not open browser automatically"),
) -> None:
    """Launch the NiceGUI editor (http://localhost:7880).

    Full-featured web UI with interactive timeline editor, clip gallery,
    job browser and live save/render integration.

    Example::

        autoedit gui
        autoedit gui --port 7881 --no-browser
    """
    from autoedit.gui.app import launch
    launch(port=port, open_browser=not no_browser)


if __name__ == "__main__":
    app()
