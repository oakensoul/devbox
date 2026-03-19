"""Tests for iTerm2 dynamic profile management."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from devbox.iterm2 import _build_profile, create_profile, remove_profile
from devbox.presets import Preset

_PRESET_DATA: dict[str, Any] = {
    "name": "test-preset",
    "description": "A test preset",
    "provider": "local",
    "github_account": "octocat",
    "color_scheme": "gruvbox",
}


def _make_preset(**overrides: Any) -> Preset:
    return Preset(**{**_PRESET_DATA, **overrides})


class TestBuildProfile:
    def test_profile_structure(self) -> None:
        preset = _make_preset()
        profile = _build_profile("dev1", preset)

        assert "Profiles" in profile
        assert len(profile["Profiles"]) == 1
        p = profile["Profiles"][0]
        assert p["Name"] == "devbox::dev1"
        assert p["Guid"] == "devbox-dev1"
        assert p["Badge Text"] == "dev1"
        assert p["Command"] == "ssh dx-dev1@localhost"
        assert p["Custom Command"] == "Yes"

    def test_color_preset_mapped(self) -> None:
        preset = _make_preset(color_scheme="solarized-dark")
        profile = _build_profile("dev1", preset)
        assert profile["Profiles"][0]["Color Preset"] == "Solarized Dark"

    def test_gruvbox_mapped(self) -> None:
        preset = _make_preset(color_scheme="gruvbox")
        profile = _build_profile("dev1", preset)
        assert profile["Profiles"][0]["Color Preset"] == "Gruvbox Dark"

    def test_unknown_color_passed_through(self) -> None:
        preset = _make_preset(color_scheme="custom-theme")
        profile = _build_profile("dev1", preset)
        assert profile["Profiles"][0]["Color Preset"] == "custom-theme"

    def test_tags_include_devbox_and_preset(self) -> None:
        preset = _make_preset()
        profile = _build_profile("dev1", preset)
        tags = profile["Profiles"][0]["Tags"]
        assert "devbox" in tags
        assert "test-preset" in tags


class TestCreateProfile:
    def test_writes_profile_json(self, tmp_path: Path) -> None:
        preset = _make_preset()
        path = create_profile("dev1", preset, profiles_dir=tmp_path)

        assert path.exists()
        assert path.name == "devbox-dev1.json"
        data = json.loads(path.read_text())
        assert data["Profiles"][0]["Name"] == "devbox::dev1"

    def test_creates_directory(self, tmp_path: Path) -> None:
        nested = tmp_path / "nested" / "profiles"
        preset = _make_preset()

        path = create_profile("dev1", preset, profiles_dir=nested)

        assert path.exists()
        assert nested.is_dir()

    def test_returns_path(self, tmp_path: Path) -> None:
        preset = _make_preset()
        path = create_profile("dev1", preset, profiles_dir=tmp_path)

        assert isinstance(path, Path)
        assert path.parent == tmp_path

    def test_invalid_name_raises(self, tmp_path: Path) -> None:
        preset = _make_preset()

        with pytest.raises(ValueError, match="kebab-case"):
            create_profile("Bad_Name", preset, profiles_dir=tmp_path)

    def test_overwrites_existing(self, tmp_path: Path) -> None:
        preset1 = _make_preset(color_scheme="nord")
        preset2 = _make_preset(color_scheme="dracula")

        create_profile("dev1", preset1, profiles_dir=tmp_path)
        path = create_profile("dev1", preset2, profiles_dir=tmp_path)

        data = json.loads(path.read_text())
        assert data["Profiles"][0]["Color Preset"] == "Dracula"


class TestRemoveProfile:
    def test_removes_existing(self, tmp_path: Path) -> None:
        preset = _make_preset()
        path = create_profile("dev1", preset, profiles_dir=tmp_path)
        assert path.exists()

        remove_profile("dev1", profiles_dir=tmp_path)

        assert not path.exists()

    def test_idempotent_when_missing(self, tmp_path: Path) -> None:
        # Should not raise
        remove_profile("nonexistent", profiles_dir=tmp_path)

    def test_invalid_name_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="kebab-case"):
            remove_profile("Bad_Name", profiles_dir=tmp_path)
