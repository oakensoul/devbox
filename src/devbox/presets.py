"""Load and validate preset JSON files from ~/.dotfiles-private/devbox/presets/."""

from __future__ import annotations

from pathlib import Path
from typing import Any

PRESETS_DIR = Path.home() / ".dotfiles-private" / "devbox" / "presets"

# Preset schema:
# {
#   "name": "",
#   "description": "",
#   "provider": "",
#   "aws_profile": "",
#   "github_account": "",
#   "node_version": "lts",
#   "python_version": "3.12",
#   "brew_extras": [],
#   "npm_globals": [],
#   "pip_globals": [],
#   "mcp_profile": "",
#   "env_vars": {}
# }


def load_preset(name: str) -> dict[str, Any]:
    """Load a preset by name from the presets directory."""
    raise NotImplementedError


def validate_preset(data: dict[str, Any]) -> None:
    """Validate a preset dict against the expected schema. Raises on error."""
    raise NotImplementedError


def list_presets() -> list[str]:
    """Return names of all available presets."""
    raise NotImplementedError
