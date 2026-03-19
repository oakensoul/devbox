"""Load and validate preset JSON files from ~/.dotfiles-private/devbox/presets/."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from devbox.exceptions import PresetError
from devbox.naming import validate_name

PRESETS_DIR = Path.home() / ".dotfiles-private" / "devbox" / "presets"


class Preset(BaseModel):
    """Pydantic model for a devbox preset."""

    model_config = ConfigDict(extra="forbid")

    version: int = 1
    name: str
    description: str
    provider: str
    aws_profile: str = ""
    github_account: str
    color_scheme: str = "gruvbox"
    node_version: str = "lts"
    python_version: str = "3.12"
    brew_extras: list[str] = []
    npm_globals: list[str] = []
    pip_globals: list[str] = []
    mcp_profile: str = ""
    env_vars: dict[str, str] = {}


def load_preset(name: str, presets_dir: Path | None = None) -> Preset:
    """Load a preset by name from the presets directory.

    Raises :exc:`PresetError` if the file is missing, contains invalid JSON,
    or fails validation against the Preset model.
    """
    try:
        validate_name(name)
    except ValueError as exc:
        raise PresetError(str(exc)) from exc

    directory = presets_dir if presets_dir is not None else PRESETS_DIR
    preset_path = directory / f"{name}.json"

    if not preset_path.exists():
        raise PresetError(f"Preset file not found: {preset_path}")

    try:
        raw = preset_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PresetError(f"Failed to read preset file: {exc}") from exc

    try:
        data: dict[str, Any] = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PresetError(f"Invalid JSON in preset {name!r}: {exc}") from exc

    return validate_preset(data)


def validate_preset(data: dict[str, Any]) -> Preset:
    """Validate a dict against the Preset model.

    Returns the validated :class:`Preset` if valid, raises :exc:`PresetError` otherwise.
    """
    try:
        return Preset.model_validate(data)
    except ValidationError as exc:
        raise PresetError(f"Preset validation failed: {exc}") from exc


def list_presets(presets_dir: Path | None = None) -> list[str]:
    """Return sorted list of preset names (filenames without ``.json``).

    Returns an empty list if the directory does not exist.
    """
    directory = presets_dir if presets_dir is not None else PRESETS_DIR

    if not directory.is_dir():
        return []

    return sorted(p.stem for p in directory.glob("*.json"))
