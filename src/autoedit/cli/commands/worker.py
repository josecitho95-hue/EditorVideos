"""Worker commands — autoedit worker run."""

import typer
from arq import run_worker
from rich.console import Console

from autoedit.workers.worker import WorkerSettings

console = Console()
app = typer.Typer()


@app.command()
def run() -> None:
    """Start the arq worker."""
    console.print("[bold cyan]Starting arq worker...[/bold cyan]")
    run_worker(WorkerSettings)  # type: ignore[arg-type]
