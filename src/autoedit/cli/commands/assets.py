"""Assets commands — autoedit assets ingest|list|stats."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from autoedit.assets.retrieval import AssetRetrieval, ensure_collections
from autoedit.domain.clip import AssetKind
from autoedit.settings import settings
from autoedit.storage.db import init_db

console = Console()
app = typer.Typer()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_KIND_LABELS: dict[AssetKind, str] = {
    AssetKind.VISUAL_IMAGE: "image",
    AssetKind.VISUAL_VIDEO: "video",
    AssetKind.AUDIO_SFX: "sfx",
    AssetKind.MEME: "meme",
}

_SOURCE_CHOICES = ["bttv", "7tv", "ffz", "freesound", "pixabay", "all"]


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@app.command()
def ingest(
    source: str = typer.Argument(
        "all",
        help=f"Source to ingest: {', '.join(_SOURCE_CHOICES)}",
    ),
    limit: int = typer.Option(
        200,
        "--limit",
        "-n",
        help="Max assets per source (emotes) or results per query (SFX/images)",
    ),
    freesound_key: str = typer.Option(
        "",
        "--freesound-key",
        envvar="FREESOUND_API_KEY",
        help="Freesound API key (or set FREESOUND_API_KEY in .env)",
    ),
    pixabay_key: str = typer.Option(
        "",
        "--pixabay-key",
        envvar="PIXABAY_API_KEY",
        help="Pixabay API key (or set PIXABAY_API_KEY in .env)",
    ),
) -> None:
    """Ingest assets from external sources into the local catalog.

    Examples::

        autoedit assets ingest all
        autoedit assets ingest bttv --limit 300
        autoedit assets ingest freesound --freesound-key YOUR_KEY
        autoedit assets ingest pixabay --pixabay-key YOUR_KEY
    """
    init_db()
    ensure_collections()

    retrieval = AssetRetrieval()
    assets_dir = settings.data_dir / "assets"
    total_added = 0

    source = source.lower()
    if source not in _SOURCE_CHOICES:
        console.print(
            f"[red]Unknown source '{source}'. Choose from: {', '.join(_SOURCE_CHOICES)}[/red]"
        )
        raise typer.Exit(1)

    # ---- Emote sources (no auth) ----
    emote_sources: list[str] = []
    if source in ("bttv", "all"):
        emote_sources.append("bttv")
    if source in ("7tv", "all"):
        emote_sources.append("7tv")
    if source in ("ffz", "all"):
        emote_sources.append("ffz")

    if emote_sources:
        from autoedit.assets.ingest.twitch_emotes import run as ingest_emotes
        console.print(
            f"[cyan]Ingesting emotes from: {', '.join(emote_sources).upper()}...[/cyan]"
        )
        try:
            added = ingest_emotes(
                dest_dir=assets_dir / "emotes",
                retrieval=retrieval,
                limit_per_source=limit,
                sources=emote_sources,
            )
            total_added += added
            console.print(f"  [green]+{added}[/green] emotes")
        except Exception as exc:
            console.print(f"  [red]Emote ingest failed: {exc}[/red]")

    # ---- Freesound ----
    if source in ("freesound", "all"):
        key = freesound_key or settings.FREESOUND_API_KEY
        if not key:
            console.print(
                "[yellow]Skipping Freesound — no FREESOUND_API_KEY set.[/yellow]\n"
                "  Get one at: https://freesound.org/apiv2/apply/"
            )
        else:
            from autoedit.assets.ingest.freesound import run as ingest_freesound
            console.print("[cyan]Ingesting SFX from Freesound...[/cyan]")
            try:
                added = ingest_freesound(
                    dest_dir=assets_dir / "sfx",
                    retrieval=retrieval,
                    api_key=key,
                    results_per_query=limit,
                )
                total_added += added
                console.print(f"  [green]+{added}[/green] SFX tracks")
            except Exception as exc:
                console.print(f"  [red]Freesound ingest failed: {exc}[/red]")

    # ---- Pixabay ----
    if source in ("pixabay", "all"):
        key = pixabay_key or settings.PIXABAY_API_KEY
        if not key:
            console.print(
                "[yellow]Skipping Pixabay — no PIXABAY_API_KEY set.[/yellow]\n"
                "  Get one at: https://pixabay.com/api/docs/#api_key"
            )
        else:
            from autoedit.assets.ingest.pixabay import run as ingest_pixabay
            console.print("[cyan]Ingesting images from Pixabay...[/cyan]")
            try:
                added = ingest_pixabay(
                    dest_dir=assets_dir / "images",
                    retrieval=retrieval,
                    api_key=key,
                    results_per_query=limit,
                )
                total_added += added
                console.print(f"  [green]+{added}[/green] images")
            except Exception as exc:
                console.print(f"  [red]Pixabay ingest failed: {exc}[/red]")

    console.print(f"\n[bold green]Done — {total_added} new assets added to catalog[/bold green]")


@app.command("list")
def list_assets(
    kind: str = typer.Option(
        "all",
        "--kind",
        "-k",
        help="Filter by kind: image, video, sfx, meme, all",
    ),
    limit: int = typer.Option(50, "--limit", "-n", help="Max rows to display"),
) -> None:
    """List assets in the catalog."""
    init_db()
    retrieval = AssetRetrieval()

    kind_filter: AssetKind | None = None
    if kind != "all":
        kind_map = {v: k for k, v in _KIND_LABELS.items()}
        kind_filter = kind_map.get(kind)
        if not kind_filter:
            console.print(f"[red]Unknown kind '{kind}'. Choose: image, video, sfx, meme, all[/red]")
            raise typer.Exit(1)

    assets = retrieval._repo.list_all(kind=kind_filter)
    if not assets:
        console.print("[yellow]No assets in catalog.[/yellow]")
        console.print("Run: [cyan]autoedit assets ingest all[/cyan]")
        return

    table = Table(title=f"Assets ({len(assets)} total)")
    table.add_column("ID", style="dim", max_width=8)
    table.add_column("Kind", style="cyan")
    table.add_column("Tags")
    table.add_column("Intent")
    table.add_column("File")

    for a in assets[:limit]:
        file_ok = "[green]OK[/green]" if Path(a.file_path).exists() else "[red]MISSING[/red]"
        table.add_row(
            a.id[:8],
            _KIND_LABELS.get(a.kind, a.kind.value),
            ", ".join(a.tags[:3]),
            ", ".join(a.intent_affinity[:2]),
            file_ok,
        )

    console.print(table)
    if len(assets) > limit:
        console.print(f"[dim]... and {len(assets) - limit} more (use --limit to see more)[/dim]")


@app.command()
def stats() -> None:
    """Show asset catalog statistics."""
    init_db()
    retrieval = AssetRetrieval()

    table = Table(title="Asset Catalog Stats")
    table.add_column("Kind", style="cyan")
    table.add_column("Count", justify="right")
    table.add_column("On disk", justify="right")

    grand_total = 0
    grand_ok = 0
    for kind in AssetKind:
        assets = retrieval._repo.list_all(kind=kind)
        on_disk = sum(1 for a in assets if Path(a.file_path).exists())
        table.add_row(_KIND_LABELS[kind], str(len(assets)), str(on_disk))
        grand_total += len(assets)
        grand_ok += on_disk

    table.add_section()
    table.add_row("[bold]TOTAL[/bold]", f"[bold]{grand_total}[/bold]", f"[bold]{grand_ok}[/bold]")
    console.print(table)

    if grand_total == 0:
        console.print(
            "\n[yellow]Catalog is empty.[/yellow] "
            "Run: [cyan]autoedit assets ingest all[/cyan]"
        )


@app.command()
def search(
    query: str = typer.Argument(..., help="Intent or description to search for"),
    kind: str = typer.Option("image", "--kind", "-k", help="image | sfx"),
    top_k: int = typer.Option(5, "--top", "-n", help="Number of results"),
) -> None:
    """Search assets by intent/description using semantic similarity.

    Example::

        autoedit assets search "fail funny mistake"
        autoedit assets search "victory win" --kind image --top 3
    """
    init_db()
    ensure_collections()

    from autoedit.domain.highlight import Intent

    retrieval = AssetRetrieval()

    # Map kind string to search method
    if kind == "sfx":
        # Use text query as-is against audio collection
        from autoedit.assets.embeddings import embed_text
        vec = embed_text(query)[0]
        results = retrieval._repo.search_qdrant(
            query_vector=vec,
            intent="other",
            collection="assets_audio",
            top_k=top_k,
        )
    else:
        from autoedit.assets.embeddings import embed_text
        vec = embed_text(query)[0]
        results = retrieval._repo.search_qdrant(
            query_vector=vec,
            intent="other",
            collection="assets_visual",
            top_k=top_k,
        )

    if not results:
        console.print("[yellow]No results found.[/yellow]")
        return

    table = Table(title=f"Search results for '{query}'")
    table.add_column("Score", justify="right")
    table.add_column("Kind")
    table.add_column("Tags")
    table.add_column("File")

    for r in results:
        asset = retrieval._repo.get(r["id"])
        if not asset:
            continue
        table.add_row(
            f"{r['score']:.3f}",
            _KIND_LABELS.get(asset.kind, "?"),
            ", ".join(asset.tags[:4]),
            Path(asset.file_path).name,
        )

    console.print(table)
