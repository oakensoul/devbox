"""Load and validate preset JSON files from ~/.dotfiles-private/devbox/presets/."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from devbox.exceptions import PresetError
from devbox.naming import validate_name

PRESETS_DIR = Path.home() / ".dotfiles-private" / "devbox" / "presets"

_PACKAGE_NAME_RE = re.compile(r"^[a-zA-Z0-9@_./-]+$")
_GITHUB_ACCOUNT_RE = re.compile(r"^[a-zA-Z0-9-]+$")


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

    @field_validator("brew_extras", "npm_globals", "pip_globals", mode="before")
    @classmethod
    def validate_package_names(cls, v: list[str]) -> list[str]:
        """Reject package names that could cause injection in subprocess calls."""
        for pkg in v:
            if not _PACKAGE_NAME_RE.match(pkg) or pkg.startswith("-"):
                msg = f"Invalid package name: {pkg!r}"
                raise ValueError(msg)
        return v

    @field_validator("github_account")
    @classmethod
    def validate_github_account(cls, v: str) -> str:
        """Reject GitHub account names with special characters."""
        if not _GITHUB_ACCOUNT_RE.match(v):
            msg = f"Invalid GitHub account: {v!r}"
            raise ValueError(msg)
        return v


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

    preset = validate_preset(data)

    if preset.name != name:
        raise PresetError(
            f"Preset name {preset.name!r} does not match filename {name!r}"
        )

    return preset


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

    names = []
    for p in directory.glob("*.json"):
        try:
            validate_name(p.stem)
            names.append(p.stem)
        except ValueError:
            continue
    return sorted(names)
