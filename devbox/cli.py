"""Click CLI for devbox."""

import click


@click.group()
def cli():
    """Manage disposable SSH-only macOS dev environments."""


@cli.command()
@click.argument("name")
@click.option("--preset", required=True, help="Preset name to use for provisioning.")
def create(name: str, preset: str):
    """Create a new devbox."""
    raise NotImplementedError


@cli.command()
@click.argument("name")
def rebuild(name: str):
    """Tear down and recreate an existing devbox."""
    raise NotImplementedError


@cli.command()
@click.argument("name")
def nuke(name: str):
    """Permanently destroy a devbox and clean up all resources."""
    raise NotImplementedError


@cli.command("list")
def list_boxes():
    """List all registered devboxes."""
    raise NotImplementedError
