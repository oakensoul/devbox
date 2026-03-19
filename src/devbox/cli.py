"""Click CLI for devbox."""

from __future__ import annotations

import sys

import click
from rich.console import Console
from rich.table import Table

from devbox.core import create_devbox, list_devboxes, nuke_devbox, rebuild_devbox
from devbox.exceptions import DevboxError

console = Console(stderr=True)

_STATUS_ICONS: dict[str, str] = {
    "healthy": "[green]✅ healthy[/green]",
    "atrophied": "[yellow]⚠️  atrophied[/yellow]",
    "unreachable": "[red]❌ unreachable[/red]",
    "unknown": "[dim]— unknown[/dim]",
    "creating": "[blue]🔧 creating[/blue]",
    "nuking": "[red]💀 nuking[/red]",
}


@click.group()
def cli() -> None:
    """Manage disposable SSH-only macOS dev environments."""


@cli.command()
@click.argument("name")
@click.option("--preset", required=True, help="Preset name to use for provisioning.")
def create(name: str, preset: str) -> None:
    """Create a new devbox."""
    try:
        with console.status(f"[bold]Creating devbox {name!r} from preset {preset!r}..."):
            result = create_devbox(name, preset)
        console.print(f"[green]✓[/green] Devbox [bold]{name}[/bold] created successfully")
        console.print(f"  Connect: [cyan]ssh dx-{name}@localhost[/cyan]")
        console.print(f"  Status:  {result.get('status', 'ready')}")
    except (DevboxError, ValueError) as exc:
        console.print(f"[red]✗[/red] {exc}")
        sys.exit(1)


@cli.command()
@click.argument("name")
def rebuild(name: str) -> None:
    """Tear down and recreate an existing devbox."""
    try:
        with console.status(f"[bold]Rebuilding devbox {name!r}..."):
            rebuild_devbox(name)
        console.print(f"[green]✓[/green] Devbox [bold]{name}[/bold] rebuilt successfully")
        console.print(f"  Connect: [cyan]ssh dx-{name}@localhost[/cyan]")
    except (DevboxError, ValueError) as exc:
        console.print(f"[red]✗[/red] {exc}")
        sys.exit(1)


@cli.command()
@click.argument("name")
def nuke(name: str) -> None:
    """Permanently destroy a devbox and clean up all resources."""
    try:
        with console.status(f"[bold]Nuking devbox {name!r}..."):
            errors = nuke_devbox(name)
        if errors:
            console.print(f"[yellow]⚠[/yellow] Devbox [bold]{name}[/bold] nuked with warnings:")
            for err in errors:
                console.print(f"  [yellow]•[/yellow] {err}")
        else:
            console.print(f"[green]✓[/green] Devbox [bold]{name}[/bold] nuked")
    except (DevboxError, ValueError) as exc:
        console.print(f"[red]✗[/red] {exc}")
        sys.exit(1)


@cli.command("list")
def list_boxes() -> None:
    """List all registered devboxes."""
    try:
        entries = list_devboxes()
    except (DevboxError, ValueError) as exc:
        console.print(f"[red]✗[/red] {exc}")
        sys.exit(1)

    if not entries:
        console.print("[dim]No devboxes registered.[/dim]")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("NAME")
    table.add_column("PRESET")
    table.add_column("CREATED")
    table.add_column("LAST SEEN")
    table.add_column("STATUS")

    for entry in entries:
        status_str = _STATUS_ICONS.get(entry["status"], entry["status"])
        table.add_row(
            entry["name"],
            entry["preset"],
            entry["created"],
            entry["last_seen"],
            status_str,
        )

    # Table data goes to stdout; status/errors go to stderr via global console
    output_console = Console()
    output_console.print(table)
