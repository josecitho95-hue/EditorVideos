"""Ping command — autoedit ping."""

import asyncio
from datetime import datetime

import typer
from rich.console import Console

from autoedit.llm.openrouter import openrouter
from autoedit.settings import settings
from autoedit.storage.db import CostEntryModel, get_session

console = Console()
app = typer.Typer()


@app.callback(invoke_without_command=True)
def ping(
    model: str = typer.Option("deepseek/deepseek-chat-v3", "--model", "-m"),
) -> None:
    """Send a hello-world request to OpenRouter and record the cost."""
    if not settings.OPENROUTER_API_KEY:
        console.print("[red]OPENROUTER_API_KEY is not set in .env[/red]")
        raise typer.Exit(1)

    async def _run() -> None:
        console.print(f"[bold cyan]Pinging {model}...[/bold cyan]")
        try:
            resp = await openrouter.ping(model=model)
        except Exception as exc:
            console.print(f"[red]Request failed: {exc}[/red]")
            raise typer.Exit(1) from exc

        console.print(f"[bold green]Response:[/bold green] {resp.content.strip()}")
        console.print(f"Model: {resp.model}")
        console.print(f"Tokens: {resp.prompt_tokens} in / {resp.completion_tokens} out")

        # Record cost (heuristic: DeepSeek V3 ~ $0.27/M in, $1.10/M out)
        # This is a placeholder; real pricing module will be added later.
        cost = (resp.prompt_tokens * 0.27 + resp.completion_tokens * 1.10) / 1_000_000
        console.print(f"Estimated cost: ${cost:.6f}")

        with get_session() as session:
            entry = CostEntryModel(
                provider="openrouter",
                model=resp.model,
                tokens_in=resp.prompt_tokens,
                tokens_out=resp.completion_tokens,
                usd=cost,
                occurred_at=datetime.utcnow().isoformat(),
            )
            session.add(entry)
            session.commit()
            console.print("[dim]Cost recorded in database.[/dim]")

    asyncio.run(_run())
