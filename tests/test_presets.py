"""Tests for devbox preset loading and validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from devbox.exceptions import PresetError
from devbox.presets import Preset, list_presets, load_preset, validate_preset

VALID_PRESET: dict[str, Any] = {
    "name": "test-preset",
    "description": "A test preset",
    "provider": "local",
    "github_account": "octocat",
}


def _write_preset(directory: Path, name: str, data: dict[str, Any]) -> Path:
    """Write a preset JSON file and return its path."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class TestLoadPreset:
    """load_preset reads and validates a preset file."""

    def test_valid_preset_loads(self, tmp_path: Path) -> None:
        data = {**VALID_PRESET, "name": "my-preset"}
        _write_preset(tmp_path, "my-preset", data)
        preset = load_preset("my-preset", presets_dir=tmp_path)
        assert isinstance(preset, Preset)
        assert preset.name == "my-preset"
        assert preset.description == "A test preset"
        assert preset.provider == "local"
        assert preset.github_account == "octocat"

    def test_missing_file_raises_preset_error(self, tmp_path: Path) -> None:
        with pytest.raises(PresetError, match="not found"):
            load_preset("no-such-preset", presets_dir=tmp_path)

    def test_invalid_json_raises_preset_error(self, tmp_path: Path) -> None:
        tmp_path.mkdir(parents=True, exist_ok=True)
        (tmp_path / "bad-json.json").write_text("{not valid json", encoding="utf-8")
        with pytest.raises(PresetError, match="Invalid JSON"):
            load_preset("bad-json", presets_dir=tmp_path)

    def test_missing_required_fields_raises_preset_error(self, tmp_path: Path) -> None:
        _write_preset(tmp_path, "incomplete", {"name": "incomplete"})
        with pytest.raises(PresetError, match="validation failed"):
            load_preset("incomplete", presets_dir=tmp_path)

    def test_unknown_fields_raises_preset_error(self, tmp_path: Path) -> None:
        data = {**VALID_PRESET, "unknown_field": "surprise"}
        _write_preset(tmp_path, "extra-field", data)
        with pytest.raises(PresetError, match="validation failed"):
            load_preset("extra-field", presets_dir=tmp_path)

    def test_invalid_name_raises_preset_error(self, tmp_path: Path) -> None:
        with pytest.raises(PresetError, match="kebab-case"):
            load_preset("Bad_Name", presets_dir=tmp_path)

    def test_empty_name_raises_preset_error(self, tmp_path: Path) -> None:
        with pytest.raises(PresetError, match="empty"):
            load_preset("", presets_dir=tmp_path)


class TestPresetDefaults:
    """Preset model has correct default values."""

    def test_defaults_applied(self) -> None:
        preset = Preset(**VALID_PRESET)
        assert preset.version == 1
        assert preset.aws_profile == ""
        assert preset.color_scheme == "gruvbox"
        assert preset.node_version == "lts"
        assert preset.python_version == "3.12"
        assert preset.brew_extras == []
        assert preset.npm_globals == []
        assert preset.pip_globals == []
        assert preset.mcp_profile == ""
        assert preset.env_vars == {}

    def test_all_fields_correct_types(self) -> None:
        full_data: dict[str, Any] = {
            "version": 2,
            "name": "full",
            "description": "Full preset",
            "provider": "aws",
            "aws_profile": "my-profile",
            "github_account": "user",
            "color_scheme": "catppuccin",
            "node_version": "20",
            "python_version": "3.13",
            "brew_extras": ["htop", "jq"],
            "npm_globals": ["typescript"],
            "pip_globals": ["ruff"],
            "mcp_profile": "default",
            "env_vars": {"FOO": "bar"},
        }
        preset = Preset(**full_data)
        assert preset.version == 2
        assert isinstance(preset.brew_extras, list)
        assert isinstance(preset.env_vars, dict)
        assert preset.env_vars["FOO"] == "bar"


class TestValidatePreset:
    """validate_preset validates dicts against the Preset model."""

    def test_valid_data_returns_preset(self) -> None:
        result = validate_preset(VALID_PRESET)
        assert isinstance(result, Preset)
        assert result.name == "test-preset"

    def test_missing_required_field_raises_preset_error(self) -> None:
        with pytest.raises(PresetError, match="validation failed"):
            validate_preset({"name": "only-name"})

    def test_unknown_field_raises_preset_error(self) -> None:
        data = {**VALID_PRESET, "bogus": True}
        with pytest.raises(PresetError, match="validation failed"):
            validate_preset(data)

    def test_wrong_type_raises_preset_error(self) -> None:
        data = {**VALID_PRESET, "version": "not-an-int"}
        with pytest.raises(PresetError, match="validation failed"):
            validate_preset(data)


class TestListPresets:
    """list_presets returns sorted preset names."""

    def test_returns_sorted_names(self, tmp_path: Path) -> None:
        _write_preset(tmp_path, "zulu", VALID_PRESET)
        _write_preset(tmp_path, "alpha", VALID_PRESET)
        _write_preset(tmp_path, "mike", VALID_PRESET)
        result = list_presets(presets_dir=tmp_path)
        assert result == ["alpha", "mike", "zulu"]

    def test_returns_empty_list_for_missing_dir(self, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist"
        result = list_presets(presets_dir=missing)
        assert result == []

    def test_ignores_non_json_files(self, tmp_path: Path) -> None:
        _write_preset(tmp_path, "valid", VALID_PRESET)
        (tmp_path / "readme.txt").write_text("not a preset", encoding="utf-8")
        result = list_presets(presets_dir=tmp_path)
        assert result == ["valid"]

    def test_empty_directory(self, tmp_path: Path) -> None:
        tmp_path.mkdir(parents=True, exist_ok=True)
        result = list_presets(presets_dir=tmp_path)
        assert result == []

    def test_filters_invalid_names(self, tmp_path: Path) -> None:
        _write_preset(tmp_path, "valid-name", VALID_PRESET)
        (tmp_path / "Bad_Name.json").write_text("{}", encoding="utf-8")
        (tmp_path / "ALLCAPS.json").write_text("{}", encoding="utf-8")
        result = list_presets(presets_dir=tmp_path)
        assert result == ["valid-name"]


class TestPresetNameMatchesFilename:
    """Preset name field must match the filename."""

    def test_mismatched_name_raises(self, tmp_path: Path) -> None:
        data = {**VALID_PRESET, "name": "different-name"}
        _write_preset(tmp_path, "my-preset", data)
        with pytest.raises(PresetError, match="does not match filename"):
            load_preset("my-preset", presets_dir=tmp_path)


class TestPresetFieldValidation:
    """Preset fields are validated for injection safety."""

    def test_invalid_brew_extra_raises(self) -> None:
        data = {**VALID_PRESET, "brew_extras": ["valid", "foo; rm -rf /"]}
        with pytest.raises(PresetError, match="validation failed"):
            validate_preset(data)

    def test_brew_extra_starting_with_dash_raises(self) -> None:
        data = {**VALID_PRESET, "brew_extras": ["--config=/etc/passwd"]}
        with pytest.raises(PresetError, match="validation failed"):
            validate_preset(data)

    def test_valid_brew_extras_accepted(self) -> None:
        data = {**VALID_PRESET, "brew_extras": ["python@3.12", "htop", "jq"]}
        preset = validate_preset(data)
        assert preset.brew_extras == ["python@3.12", "htop", "jq"]

    def test_invalid_github_account_raises(self) -> None:
        data = {**VALID_PRESET, "github_account": "user; echo pwned"}
        with pytest.raises(PresetError, match="validation failed"):
            validate_preset(data)

    def test_valid_github_account_accepted(self) -> None:
        data = {**VALID_PRESET, "github_account": "my-org-123"}
        preset = validate_preset(data)
        assert preset.github_account == "my-org-123"

    def test_github_account_leading_hyphen_rejected(self) -> None:
        data = {**VALID_PRESET, "github_account": "-leading"}
        with pytest.raises(PresetError, match="validation failed"):
            validate_preset(data)

    def test_github_account_trailing_hyphen_rejected(self) -> None:
        data = {**VALID_PRESET, "github_account": "trailing-"}
        with pytest.raises(PresetError, match="validation failed"):
            validate_preset(data)

    def test_github_account_too_long_rejected(self) -> None:
        data = {**VALID_PRESET, "github_account": "a" * 40}
        with pytest.raises(PresetError, match="validation failed"):
            validate_preset(data)

    def test_invalid_npm_global_raises(self) -> None:
        data = {**VALID_PRESET, "npm_globals": ["valid", "bad; rm -rf /"]}
        with pytest.raises(PresetError, match="validation failed"):
            validate_preset(data)

    def test_invalid_pip_global_raises(self) -> None:
        data = {**VALID_PRESET, "pip_globals": ["--malicious"]}
        with pytest.raises(PresetError, match="validation failed"):
            validate_preset(data)

    def test_path_traversal_in_package_rejected(self) -> None:
        data = {**VALID_PRESET, "brew_extras": ["../../etc/passwd"]}
        with pytest.raises(PresetError, match="validation failed"):
            validate_preset(data)

    def test_unknown_provider_rejected(self) -> None:
        data = {**VALID_PRESET, "provider": "gcp"}
        with pytest.raises(PresetError, match="validation failed"):
            validate_preset(data)

    def test_valid_providers_accepted(self) -> None:
        for provider in ("local", "aws"):
            data = {**VALID_PRESET, "provider": provider}
            preset = validate_preset(data)
            assert preset.provider == provider

    def test_aws_profile_injection_rejected(self) -> None:
        data = {**VALID_PRESET, "aws_profile": "profile; echo pwned"}
        with pytest.raises(PresetError, match="validation failed"):
            validate_preset(data)

    def test_valid_aws_profile_accepted(self) -> None:
        data = {**VALID_PRESET, "aws_profile": "my-profile_v2"}
        preset = validate_preset(data)
        assert preset.aws_profile == "my-profile_v2"

    def test_node_version_injection_rejected(self) -> None:
        data = {**VALID_PRESET, "node_version": "20 && rm -rf /"}
        with pytest.raises(PresetError, match="validation failed"):
            validate_preset(data)

    def test_env_var_invalid_key_rejected(self) -> None:
        data = {**VALID_PRESET, "env_vars": {"BAD KEY": "val"}}
        with pytest.raises(PresetError, match="validation failed"):
            validate_preset(data)

    def test_env_var_dangerous_key_rejected(self) -> None:
        data = {**VALID_PRESET, "env_vars": {"LD_PRELOAD": "/evil.so"}}
        with pytest.raises(PresetError, match="validation failed"):
            validate_preset(data)

    def test_env_var_shell_metachar_in_value_rejected(self) -> None:
        data = {**VALID_PRESET, "env_vars": {"FOO": "$(rm -rf /)"}}
        with pytest.raises(PresetError, match="validation failed"):
            validate_preset(data)

    def test_env_var_op_ref_value_accepted(self) -> None:
        data = {**VALID_PRESET, "env_vars": {"TOKEN": "op://vault/item/field"}}
        preset = validate_preset(data)
        assert preset.env_vars["TOKEN"] == "op://vault/item/field"

    def test_env_var_plain_value_accepted(self) -> None:
        data = {**VALID_PRESET, "env_vars": {"APP_ENV": "production"}}
        preset = validate_preset(data)
        assert preset.env_vars["APP_ENV"] == "production"

    def test_brew_extras_non_list_rejected(self) -> None:
        data = {**VALID_PRESET, "brew_extras": "not-a-list"}
        with pytest.raises(PresetError, match="validation failed"):
            validate_preset(data)
