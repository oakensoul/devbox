# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Robert Gunnar Johnson Jr.

"""Click CLI for devbox."""

from __future__ import annotations

import sys

import click
from rich.console import Console
from rich.table import Table

from devbox.core import create_devbox, list_devboxes, nuke_devbox, rebuild_devbox
from devbox.exceptions import DevboxError
from devbox.presets import load_preset

console = Console(stderr=True)

_STATUS_ICONS: dict[str, str] = {
    "healthy": "[green]✅ healthy[/green]",
    "atrophied": "[yellow]⚠️  atrophied[/yellow]",
    "unreachable": "[red]❌ unreachable[/red]",
    "unknown": "[dim]— unknown[/dim]",
    "creating": "[blue]🔧 creating[/blue]",
    "nuking": "[red]💀 nuking[/red]",
}


def _print_claude_auth_status(preset_name: str) -> None:
    """Print Claude Code auth status after create/rebuild.

    If CLAUDE_CODE_OAUTH_TOKEN is present in the preset env_vars, the token
    will be available in the devbox and no action is needed. Otherwise, print
    instructions for setting it up.
    """
    try:
        preset_obj = load_preset(preset_name)
        has_token = "CLAUDE_CODE_OAUTH_TOKEN" in preset_obj.env_vars
    except Exception:
        has_token = False

    if has_token:
        console.print("  Claude Code: [green]✓[/green] OAuth token configured")
    else:
        console.print("  Claude Code: [yellow]⚠[/yellow]  OAuth token not configured")
        console.print("    To enable Claude Code in this devbox:")
        console.print("    1. Run [cyan]claude setup-token[/cyan] on your primary shell")
        console.print("    2. Store the token in 1Password (e.g. [dim]op://Vault/Item/credential[/dim])")
        console.print(f"    3. Add [cyan]CLAUDE_CODE_OAUTH_TOKEN[/cyan] to the [bold]{preset_name}[/bold] preset env_vars and rebuild")


@click.group()
def cli() -> None:
    """Manage disposable SSH-only macOS dev environments."""


@cli.command()
@click.argument("name")
@click.option("--preset", default=None, help="Preset name (defaults to the devbox name).")
@click.option("--dry-run", is_flag=True, default=False, help="Preview actions without executing.")
def create(name: str, preset: str | None, dry_run: bool) -> None:
    """Create a new devbox."""
    if preset is None:
        preset = name
    try:
        if dry_run:
            result = create_devbox(name, preset, dry_run=True)
            console.print(f"[bold]Dry-run for creating devbox {name!r}:[/bold]")
            for action in result.get("actions", []):
                console.print(f"  [cyan]•[/cyan] {action}")
        else:
            # Preflight runs outside the spinner so sudo can prompt if needed
            console.print(f"[bold]Preparing devbox {name!r} from preset {preset!r}...[/bold]")
            from devbox.core import preflight_devbox
            preflight_devbox(name, preset)
            status = console.status(f"[bold]Creating devbox {name!r}...[/bold]")
            status.start()
            def _on_step(msg: str) -> None:
                status.update(f"[bold]{msg}[/bold]")
            try:
                result = create_devbox(name, preset, on_step=_on_step)
            finally:
                status.stop()
            console.print(f"[green]✓[/green] Devbox [bold]{name}[/bold] created successfully")
            console.print(f"  Connect: [cyan]ssh dx-{name}[/cyan]")
            _print_claude_auth_status(preset)
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
        console.print(f"  Connect: [cyan]ssh dx-{name}[/cyan]")
        _print_claude_auth_status(name)
    except (DevboxError, ValueError) as exc:
        console.print(f"[red]✗[/red] {exc}")
        sys.exit(1)


@cli.command()
@click.argument("name")
@click.option("--dry-run", is_flag=True, default=False, help="Preview actions without executing.")
def nuke(name: str, dry_run: bool) -> None:
    """Permanently destroy a devbox and clean up all resources."""
    try:
        if dry_run:
            actions = nuke_devbox(name, dry_run=True)
            console.print(f"[bold]Dry-run for nuking devbox {name!r}:[/bold]")
            for action in actions:
                console.print(f"  [cyan]•[/cyan] {action}")
        else:
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
@click.option("--check", is_flag=True, default=False, help="Probe SSH connectivity.")
def list_boxes(check: bool) -> None:
    """List all registered devboxes."""
    try:
        entries = list_devboxes(check_ssh=check)
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
        status = entry["status"]
        status_str = _STATUS_ICONS.get(status, status)
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
