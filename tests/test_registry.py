# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Robert Gunnar Johnson Jr.

"""Tests for the devbox registry module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from devbox.exceptions import RegistryError
from devbox.registry import (
    DevboxStatus,
    Registry,
    RegistryEntry,
    add_entry,
    find_entry,
    load_registry,
    remove_entry,
    save_registry,
    update_entry,
)


def _registry_path(tmp_path: Path) -> Path:
    return tmp_path / "registry.json"


def _make_entry(
    name: str = "dev1",
    preset: str = "default",
    status: DevboxStatus = DevboxStatus.CREATING,
    created: str = "2025-03-12",
) -> RegistryEntry:
    return RegistryEntry(name=name, preset=preset, status=status, created=created)


class TestLoadRegistry:
    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        reg = load_registry(_registry_path(tmp_path))
        assert reg.version == 1
        assert reg.devboxes == []

    def test_empty_file_returns_empty(self, tmp_path: Path) -> None:
        p = _registry_path(tmp_path)
        p.write_text("")
        reg = load_registry(p)
        assert reg.devboxes == []

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        p = tmp_path / "nested" / "dir" / "registry.json"
        reg = load_registry(p)
        assert p.parent.is_dir()
        assert reg.devboxes == []

    def test_loads_valid_data(self, tmp_path: Path) -> None:
        p = _registry_path(tmp_path)
        data = {
            "version": 1,
            "devboxes": [{"name": "dev1", "preset": "default", "created": "2025-03-12"}],
        }
        p.write_text(json.dumps(data))
        reg = load_registry(p)
        assert len(reg.devboxes) == 1
        assert reg.devboxes[0].name == "dev1"
        assert reg.devboxes[0].status == DevboxStatus.CREATING

    def test_unsupported_version_raises(self, tmp_path: Path) -> None:
        p = _registry_path(tmp_path)
        p.write_text(json.dumps({"version": 99, "devboxes": []}))
        with pytest.raises(RegistryError, match="Unsupported registry version: 99"):
            load_registry(p)

    def test_corrupt_json_raises_registry_error(self, tmp_path: Path) -> None:
        p = _registry_path(tmp_path)
        p.write_text("{not valid json")
        with pytest.raises(RegistryError, match="Corrupt registry file"):
            load_registry(p)


class TestSaveRegistry:
    def test_round_trip(self, tmp_path: Path) -> None:
        p = _registry_path(tmp_path)
        entry = _make_entry()
        reg = Registry(devboxes=[entry])
        save_registry(reg, p)
        loaded = load_registry(p)
        assert loaded == reg

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        p = tmp_path / "nested" / "registry.json"
        save_registry(Registry(), p)
        assert p.exists()

    def test_atomic_write_no_leftover_temp(self, tmp_path: Path) -> None:
        p = _registry_path(tmp_path)
        save_registry(Registry(), p)
        # No temp files should remain
        files = list(tmp_path.iterdir())
        assert len(files) == 1
        assert files[0].name == "registry.json"

    def test_file_content_is_valid_json(self, tmp_path: Path) -> None:
        p = _registry_path(tmp_path)
        entry = _make_entry()
        save_registry(Registry(devboxes=[entry]), p)
        data = json.loads(p.read_text())
        assert data["version"] == 1
        assert len(data["devboxes"]) == 1
        assert data["devboxes"][0]["name"] == "dev1"


class TestFilePermissions:
    def test_saved_file_is_0600(self, tmp_path: Path) -> None:
        p = _registry_path(tmp_path)
        save_registry(Registry(), p)
        assert (p.stat().st_mode & 0o777) == 0o600

    def test_tightens_existing_dir_permissions(self, tmp_path: Path) -> None:
        d = tmp_path / "loose"
        d.mkdir(mode=0o755)
        p = d / "registry.json"
        save_registry(Registry(), p)
        assert (d.stat().st_mode & 0o777) == 0o700


class TestAddEntry:
    def test_adds_entry(self, tmp_path: Path) -> None:
        p = _registry_path(tmp_path)
        add_entry(_make_entry("dev1"), p)
        reg = load_registry(p)
        assert len(reg.devboxes) == 1
        assert reg.devboxes[0].name == "dev1"

    def test_adds_multiple_entries(self, tmp_path: Path) -> None:
        p = _registry_path(tmp_path)
        add_entry(_make_entry("dev1"), p)
        add_entry(_make_entry("dev2"), p)
        reg = load_registry(p)
        assert len(reg.devboxes) == 2

    def test_duplicate_name_raises(self, tmp_path: Path) -> None:
        p = _registry_path(tmp_path)
        add_entry(_make_entry("dev1"), p)
        with pytest.raises(RegistryError, match="Duplicate devbox name: dev1"):
            add_entry(_make_entry("dev1"), p)


class TestRemoveEntry:
    def test_removes_entry(self, tmp_path: Path) -> None:
        p = _registry_path(tmp_path)
        add_entry(_make_entry("dev1"), p)
        add_entry(_make_entry("dev2"), p)
        remove_entry("dev1", p)
        reg = load_registry(p)
        assert len(reg.devboxes) == 1
        assert reg.devboxes[0].name == "dev2"

    def test_missing_name_raises(self, tmp_path: Path) -> None:
        p = _registry_path(tmp_path)
        with pytest.raises(RegistryError, match="Devbox not found: nope"):
            remove_entry("nope", p)


class TestFindEntry:
    def test_finds_existing(self, tmp_path: Path) -> None:
        p = _registry_path(tmp_path)
        add_entry(_make_entry("dev1"), p)
        result = find_entry("dev1", p)
        assert result is not None
        assert result.name == "dev1"

    def test_returns_none_for_missing(self, tmp_path: Path) -> None:
        p = _registry_path(tmp_path)
        assert find_entry("nope", p) is None


class TestUpdateEntry:
    def test_updates_fields(self, tmp_path: Path) -> None:
        p = _registry_path(tmp_path)
        add_entry(_make_entry("dev1"), p)
        update_entry("dev1", p, status=DevboxStatus.READY, last_seen="2025-03-12T10:00:00Z")
        result = find_entry("dev1", p)
        assert result is not None
        assert result.status == DevboxStatus.READY
        assert result.last_seen == "2025-03-12T10:00:00Z"

    def test_missing_name_raises(self, tmp_path: Path) -> None:
        p = _registry_path(tmp_path)
        with pytest.raises(RegistryError, match="Devbox not found: nope"):
            update_entry("nope", p, status=DevboxStatus.READY)

    def test_invalid_field_raises(self, tmp_path: Path) -> None:
        p = _registry_path(tmp_path)
        add_entry(_make_entry("dev1"), p)
        with pytest.raises(RegistryError, match="Invalid field: bogus"):
            update_entry("dev1", p, bogus="value")

    def test_rename_blocked(self, tmp_path: Path) -> None:
        p = _registry_path(tmp_path)
        add_entry(_make_entry("dev1"), p)
        with pytest.raises(RegistryError, match="Cannot rename"):
            update_entry("dev1", p, name="dev2")

    def test_invalid_status_value_raises(self, tmp_path: Path) -> None:
        p = _registry_path(tmp_path)
        add_entry(_make_entry("dev1"), p)
        with pytest.raises(RegistryError, match="Invalid field value"):
            update_entry("dev1", p, status="bogus")


class TestStatusTransitions:
    def test_creating_to_ready(self, tmp_path: Path) -> None:
        p = _registry_path(tmp_path)
        add_entry(_make_entry("dev1", status=DevboxStatus.CREATING), p)
        update_entry("dev1", p, status=DevboxStatus.READY)
        result = find_entry("dev1", p)
        assert result is not None
        assert result.status == DevboxStatus.READY

    def test_ready_to_nuking(self, tmp_path: Path) -> None:
        p = _registry_path(tmp_path)
        add_entry(_make_entry("dev1", status=DevboxStatus.READY), p)
        update_entry("dev1", p, status=DevboxStatus.NUKING)
        result = find_entry("dev1", p)
        assert result is not None
        assert result.status == DevboxStatus.NUKING


class TestModels:
    def test_devbox_status_values(self) -> None:
        assert DevboxStatus.CREATING.value == "creating"
        assert DevboxStatus.READY.value == "ready"
        assert DevboxStatus.NUKING.value == "nuking"

    def test_registry_entry_defaults(self) -> None:
        entry = RegistryEntry(name="x", preset="p", created="2025-01-01")
        assert entry.status == DevboxStatus.CREATING
        assert entry.last_seen is None
        assert entry.github_key_id is None

    def test_registry_defaults(self) -> None:
        reg = Registry()
        assert reg.version == 1
        assert reg.devboxes == []

    def test_invalid_github_key_id_raises(self) -> None:
        with pytest.raises(Exception, match="numeric"):
            RegistryEntry(name="x", preset="p", created="2025-01-01", github_key_id="abc")

    def test_valid_github_key_id_accepted(self) -> None:
        entry = RegistryEntry(name="x", preset="p", created="2025-01-01", github_key_id="12345")
        assert entry.github_key_id == "12345"

    def test_registry_entry_serialization(self) -> None:
        entry = _make_entry(
            name="dev1",
        )
        data = entry.model_dump()
        assert data["name"] == "dev1"
        assert data["status"] == "creating"
        restored = RegistryEntry.model_validate(data)
        assert restored == entry
