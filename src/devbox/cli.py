# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Robert Gunnar Johnson Jr.

"""Click CLI for devbox."""

from __future__ import annotations

import subprocess
import sys

import click
from rich.console import Console
from rich.table import Table

from devbox.core import (
    create_devbox,
    list_devboxes,
    nuke_devbox,
    rebuild_devbox,
    refresh_devbox,
)
from devbox.exceptions import DevboxError
from devbox.registry import DevboxStatus, load_registry

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
    except (DevboxError, ValueError) as exc:
        console.print(f"[red]✗[/red] {exc}")
        sys.exit(1)


@cli.command()
@click.argument("name", required=False)
@click.option("--all", "all_", is_flag=True, default=False, help="Refresh every registered devbox.")
@click.option(
    "--with-brew",
    is_flag=True,
    default=False,
    help=(
        "Also reinstall brew packages: BOTH the loadout Brewfile AND the "
        "preset's brew_extras (two different sets). Required to pick up preset "
        "brew_extras changes. Slow: 15-30 min/box, serial under --all."
    ),
)
@click.option(
    "--with-globals",
    is_flag=True,
    default=False,
    help=(
        "Also reinstall npm/pip globals: BOTH the loadout globals AND the "
        "preset's npm_globals/pip_globals. Required to pick up preset globals changes."
    ),
)
def refresh(name: str | None, all_: bool, with_brew: bool, with_globals: bool) -> None:
    """Push current dotfiles/config to an existing devbox without destroying state."""
    if all_ and name:
        console.print("[red]✗[/red] Pass either NAME or --all, not both")
        sys.exit(1)
    if not all_ and not name:
        console.print("[red]✗[/red] Pass a devbox NAME or --all")
        sys.exit(1)

    if all_:
        entries = load_registry()
        targets = [e.name for e in entries if e.status == DevboxStatus.READY]
        if not targets:
            console.print("[yellow]No ready devboxes to refresh[/yellow]")
            return
    else:
        # name is non-None — guarded by the "Pass a devbox NAME or --all" check above.
        targets = [name] if name is not None else []

    scope_parts = ["dotfiles"]
    if with_brew:
        scope_parts.append("brew")
    if with_globals:
        scope_parts.append("globals")
    scope = ", ".join(scope_parts)

    failures: list[tuple[str, str]] = []
    for box in targets:
        try:
            with console.status(f"[bold]Refreshing {box!r} ({scope})..."):
                refresh_devbox(box, with_brew=with_brew, with_globals=with_globals)
            console.print(f"[green]✓[/green] {box} refreshed ({scope})")
        except (DevboxError, ValueError) as exc:
            # Catch DevboxError (incl. BootstrapError subclass) and ValueError
            # from validate_name. Let KeyboardInterrupt and other unexpected
            # exceptions propagate so users can abort cleanly.
            console.print(f"[red]✗[/red] {box}: {exc}")
            failures.append((box, str(exc)))
        except Exception as exc:
            # For --all, an unexpected error on one box shouldn't abort the
            # rest. Record it and keep going. Single-box invocations re-raise.
            if not all_:
                raise
            console.print(f"[red]✗[/red] {box}: unexpected error: {exc}")
            failures.append((box, f"unexpected error: {exc}"))

    if not all_ and not failures:
        # Single-box success — match create/rebuild and remind user how to connect.
        console.print(f"  Connect: [cyan]ssh dx-{targets[0]}[/cyan]")

    if failures:
        n_fail = len(failures)
        n_total = len(targets)
        noun = "refresh" if n_fail == 1 else "refreshes"
        console.print(f"\n[red]{n_fail} of {n_total} {noun} failed:[/red]")
        for box, err in failures:
            console.print(f"  [red]•[/red] {box}: {err}")
        sys.exit(1)
    elif all_:
        n = len(targets)
        noun = "devbox" if n == 1 else "devboxes"
        console.print(f"\n[green]✓[/green] {n} {noun} refreshed")


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
            # Warm up sudo outside the spinner so the password prompt is visible
            result = subprocess.run(["sudo", "-v"], timeout=60)  # noqa: S607
            if result.returncode != 0:
                console.print("[red]✗[/red] sudo authentication failed")
                sys.exit(1)
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
