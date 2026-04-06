# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Robert Gunnar Johnson Jr.

"""Read/write ~/.devbox/registry.json."""

from __future__ import annotations

import contextlib
import json
import os
import re
import stat
import tempfile
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ValidationError, field_validator

from devbox.exceptions import RegistryError

REGISTRY_PATH = Path.home() / ".devbox" / "registry.json"

_UPDATABLE_FIELDS = frozenset({"preset", "status", "created", "last_seen", "github_key_id"})
_GITHUB_KEY_ID_RE = re.compile(r"^\d+$")


class DevboxStatus(StrEnum):
    """Lifecycle status for a devbox."""

    CREATING = "creating"
    READY = "ready"
    NUKING = "nuking"


class RegistryEntry(BaseModel):
    """A single devbox entry in the registry."""

    name: str
    preset: str
    status: DevboxStatus = DevboxStatus.CREATING
    created: str  # ISO date
    last_seen: str | None = None  # ISO datetime
    github_key_id: str | None = None

    @field_validator("github_key_id")
    @classmethod
    def validate_github_key_id(cls, v: str | None) -> str | None:
        """GitHub key IDs are numeric strings."""
        if v is not None and not _GITHUB_KEY_ID_RE.match(v):
            msg = f"Invalid github_key_id: must be numeric, got {v!r}"
            raise ValueError(msg)
        return v


class Registry(BaseModel):
    """Top-level registry schema."""

    version: int = 1
    devboxes: list[RegistryEntry] = []


def _ensure_dir(directory: Path) -> None:
    """Create directory with 0o700 or tighten existing permissions."""
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    current = directory.stat().st_mode & 0o777
    if current != 0o700:
        os.chmod(directory, 0o700)


def load_registry(path: Path | None = None) -> Registry:
    """Load the registry from disk. Returns empty registry if file missing."""
    registry_path = path or REGISTRY_PATH
    _ensure_dir(registry_path.parent)

    if not registry_path.exists():
        return Registry()

    text = registry_path.read_text(encoding="utf-8")
    if not text.strip():
        return Registry()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RegistryError(f"Corrupt registry file: {exc}") from exc

    version = data.get("version", 1)
    if version != 1:
        raise RegistryError(f"Unsupported registry version: {version}")

    return Registry.model_validate(data)


def save_registry(registry: Registry, path: Path | None = None) -> None:
    """Atomic write: write to temp file in same dir, then os.replace."""
    registry_path = path or REGISTRY_PATH
    _ensure_dir(registry_path.parent)

    content = registry.model_dump_json(indent=2) + "\n"

    fd, tmp_path = tempfile.mkstemp(
        dir=str(registry_path.parent),
        prefix=".registry_",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
        os.replace(tmp_path, str(registry_path))
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise


def add_entry(entry: RegistryEntry, path: Path | None = None) -> None:
    """Append entry to devboxes list. Raise RegistryError if duplicate name."""
    registry = load_registry(path)
    for existing in registry.devboxes:
        if existing.name == entry.name:
            raise RegistryError(f"Duplicate devbox name: {entry.name}")
    registry.devboxes.append(entry)
    save_registry(registry, path)


def remove_entry(name: str, path: Path | None = None) -> None:
    """Remove entry by name. Raise RegistryError if not found."""
    registry = load_registry(path)
    for i, existing in enumerate(registry.devboxes):
        if existing.name == name:
            registry.devboxes.pop(i)
            save_registry(registry, path)
            return
    raise RegistryError(f"Devbox not found: {name}")


def find_entry(name: str, path: Path | None = None) -> RegistryEntry | None:
    """Lookup by name, return RegistryEntry or None."""
    registry = load_registry(path)
    for existing in registry.devboxes:
        if existing.name == name:
            return existing
    return None


def update_entry(devbox_name: str, path: Path | None = None, **fields: object) -> None:
    """Partial update by name. Raise RegistryError if not found.

    The ``name`` field cannot be updated. Only fields in ``_UPDATABLE_FIELDS``
    are allowed. Values are validated via pydantic before saving.
    """
    registry = load_registry(path)
    for i, existing in enumerate(registry.devboxes):
        if existing.name == devbox_name:
            for key in fields:
                if key == "name":
                    raise RegistryError("Cannot rename a devbox via update_entry")
                if key not in _UPDATABLE_FIELDS:
                    raise RegistryError(f"Invalid field: {key}")
            try:
                updated_data = existing.model_dump() | fields
                registry.devboxes[i] = RegistryEntry.model_validate(updated_data)
            except ValidationError as exc:
                raise RegistryError(f"Invalid field value: {exc}") from exc
            save_registry(registry, path)
            return
    raise RegistryError(f"Devbox not found: {devbox_name}")
