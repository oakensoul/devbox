# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Robert Gunnar Johnson Jr.

"""iTerm2 dynamic profile creation/removal."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from devbox.exceptions import ITermError
from devbox.naming import validate_name
from devbox.presets import Preset

PROFILES_DIR = Path.home() / "Library" / "Application Support" / "iTerm2" / "DynamicProfiles"

# Map preset color_scheme values to iTerm2 color preset names.
_COLOR_PRESETS: dict[str, str] = {
    "solarized-dark": "Solarized Dark",
    "nord": "Nord",
    "dracula": "Dracula",
    "gruvbox": "Gruvbox Dark",
    "catppuccin": "catppuccin-mocha",
}


def _profile_path(name: str, profiles_dir: Path | None = None) -> Path:
    """Return the profile JSON path for a devbox."""
    directory = profiles_dir if profiles_dir is not None else PROFILES_DIR
    return directory / f"devbox-{name}.json"


# tmux session the "(tmux)" profile attaches to (created on first use).
TMUX_SESSION = "main"


def _tmux_command(name: str) -> str:
    """SSH command that attaches (or creates) a tmux -CC session on the devbox.

    Runs through a login shell so PATH includes Homebrew: either the devbox's
    own ``~/.homebrew`` or, via macOS path_helper, the host's ``/opt/homebrew``.
    Uses Apple's ``/bin/zsh`` explicitly: a source-built zsh in the devbox's
    Homebrew can be broken after a macOS upgrade (hangs on command substitution).
    """
    return f"ssh -t dx-{name} \"/bin/zsh -lc 'tmux -CC new-session -A -s {TMUX_SESSION}'\""


def _build_profile(name: str, preset: Preset) -> dict[str, Any]:
    """Build the iTerm2 dynamic profile dict.

    Produces two profiles: ``devbox::<name>`` (plain SSH) and
    ``devbox::<name> (tmux)`` (SSH straight into iTerm2 tmux integration).
    """
    color_preset = _COLOR_PRESETS.get(preset.color_scheme, preset.color_scheme)

    base: dict[str, object] = {
        "Badge Text": name,
        "Custom Command": "Yes",
        "Dynamic Profile Parent Name": "Default",
        "Semantic History": {
            "action": "best editor",
        },
        "Tags": ["devbox", preset.name],
    }

    # Only set Color Preset if a non-empty color_scheme was provided.
    if color_preset:
        base["Color Preset"] = color_preset

    ssh_profile: dict[str, object] = {
        **base,
        "Name": f"devbox::{name}",
        "Guid": f"devbox-{name}",
        "Command": f"ssh dx-{name}",
    }
    tmux_profile: dict[str, object] = {
        **base,
        "Name": f"devbox::{name} (tmux)",
        "Guid": f"devbox-{name}-tmux",
        "Command": _tmux_command(name),
        "Tags": ["devbox", "tmux", preset.name],
    }

    return {"Profiles": [ssh_profile, tmux_profile]}


def create_profile(name: str, preset: Preset, profiles_dir: Path | None = None) -> Path:
    """Create an iTerm2 dynamic profile for the devbox.

    Writes the profile JSON and returns the path to the file.
    Raises :exc:`ITermError` on failure.
    """
    validate_name(name)
    path = _profile_path(name, profiles_dir)
    path.parent.mkdir(parents=True, exist_ok=True)

    profile = _build_profile(name, preset)

    try:
        path.write_text(json.dumps(profile, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        raise ITermError(f"Failed to write iTerm2 profile: {exc}") from exc

    return path


def remove_profile(name: str, profiles_dir: Path | None = None) -> None:
    """Remove the iTerm2 dynamic profile for the devbox.

    Idempotent — does not raise if the profile is already gone.
    """
    validate_name(name)
    path = _profile_path(name, profiles_dir)

    if not path.exists():
        return

    try:
        path.unlink()
    except OSError as exc:
        raise ITermError(f"Failed to remove iTerm2 profile: {exc}") from exc
