"""Database commands — autoedit db migrate|reset|backup."""

import shutil
from datetime import datetime

import typer
from rich.console import Console

from autoedit.settings import settings
from autoedit.storage.db import init_db

console = Console()
app = typer.Typer()


@app.command()
def migrate() -> None:
    """Create or upgrade SQLite database schema."""
    console.print("[bold cyan]Initializing database...[/bold cyan]")
    init_db()
    console.print(f"[bold green]Database ready at {settings.db_path}[/bold green]")


@app.command()
def reset(
    force: bool = typer.Option(False, "--force", help="Skip confirmation prompt"),
) -> None:
    """Drop and recreate the database."""
    if not force:
        confirm = typer.confirm(f"This will DELETE {settings.db_path}. Are you sure?")
        if not confirm:
            console.print("Aborted.")
            raise typer.Exit(0)

    if settings.db_path.exists():
        settings.db_path.unlink()
        console.print("[yellow]Database deleted.[/yellow]")

    init_db()
    console.print("[bold green]Database reset and recreated.[/bold green]")


@app.command()
def backup() -> None:
    """Create a timestamped backup of the database."""
    if not settings.db_path.exists():
        console.print("[red]Database does not exist — nothing to backup.[/red]")
        raise typer.Exit(1)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backup_path = settings.data_dir / f"autoedit_backup_{timestamp}.db"
    shutil.copy2(settings.db_path, backup_path)
    console.print(f"[bold green]Backup created: {backup_path}[/bold green]")
