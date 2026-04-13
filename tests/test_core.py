# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Robert Gunnar Johnson Jr.

"""Tests for core devbox operations."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pytest_mock import MockerFixture

from devbox.core import (
    _CompensationStack,
    _safe_remove_entry,
    create_devbox,
    list_devboxes,
    nuke_devbox,
    rebuild_devbox,
    refresh_devbox,
    sync_heartbeats,
    write_env_file,
)
from devbox.exceptions import DevboxError
from devbox.registry import DevboxStatus, Registry, RegistryEntry, save_registry
from devbox.utils import shell_escape

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_preset_file(presets_dir: Path, name: str, **overrides: Any) -> Path:
    """Create a minimal valid preset JSON in *presets_dir*."""
    data: dict[str, Any] = {
        "name": name,
        "description": "test preset",
        "provider": "local",
        "github_account": "testuser",
    }
    data.update(overrides)
    path = presets_dir / f"{name}.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _make_registry(registry_path: Path, entries: list[RegistryEntry]) -> None:
    """Persist a list of RegistryEntry objects to *registry_path*."""
    reg = Registry(devboxes=entries)
    save_registry(reg, registry_path)


def _entry(name: str, **kwargs: Any) -> RegistryEntry:
    """Shorthand for creating a RegistryEntry with defaults."""
    defaults: dict[str, Any] = {"preset": "test-preset", "created": "2025-01-01"}
    defaults.update(kwargs)
    return RegistryEntry(name=name, **defaults)


# ---------------------------------------------------------------------------
# shell_escape
# ---------------------------------------------------------------------------


class TestShellEscape:
    def test_simple_value(self) -> None:
        assert shell_escape("hello") == "'hello'"

    def test_value_with_spaces(self) -> None:
        assert shell_escape("hello world") == "'hello world'"

    def test_value_with_single_quotes(self) -> None:
        result = shell_escape("it's")
        # Should produce 'it'"'"'s'
        assert result == "'it'\"'\"'s'"

    def test_empty_string(self) -> None:
        assert shell_escape("") == "''"

    def test_value_with_special_chars(self) -> None:
        result = shell_escape("foo$bar")
        assert result == "'foo$bar'"


# ---------------------------------------------------------------------------
# write_env_file
# ---------------------------------------------------------------------------


class TestWriteEnvFile:
    def test_writes_correct_format(self, tmp_path: Path) -> None:
        write_env_file(tmp_path, {"MY_VAR": "hello", "OTHER": "world"})
        env_path = tmp_path / ".devbox-env"
        content = env_path.read_text(encoding="utf-8")
        assert "export MY_VAR='hello'" in content
        assert "export OTHER='world'" in content
        assert content.endswith("\n")

    def test_sets_permissions_0600(self, tmp_path: Path) -> None:
        write_env_file(tmp_path, {"KEY": "val"})
        env_path = tmp_path / ".devbox-env"
        mode = os.stat(env_path).st_mode & 0o777
        assert mode == 0o600

    def test_empty_dict_writes_newline_only(self, tmp_path: Path) -> None:
        write_env_file(tmp_path, {})
        env_path = tmp_path / ".devbox-env"
        assert env_path.read_text(encoding="utf-8") == "\n"

    def test_escapes_single_quotes_in_values(self, tmp_path: Path) -> None:
        write_env_file(tmp_path, {"TOKEN": "it's-a-secret"})
        content = (tmp_path / ".devbox-env").read_text(encoding="utf-8")
        assert "export TOKEN='it'\"'\"'s-a-secret'" in content

    def test_chowns_when_target_user_provided(self, tmp_path: Path, mocker: MockerFixture) -> None:
        mock_chown = mocker.patch("devbox.core.ssh.chown_path")
        write_env_file(tmp_path, {"KEY": "val"}, target_user="dx-mybox")
        mock_chown.assert_called_once_with(tmp_path / ".devbox-env", "dx-mybox")

    def test_no_chown_when_target_user_none(self, tmp_path: Path, mocker: MockerFixture) -> None:
        mock_chown = mocker.patch("devbox.core.ssh.chown_path")
        write_env_file(tmp_path, {"KEY": "val"})
        mock_chown.assert_not_called()

    def test_no_chown_when_target_user_omitted(self, tmp_path: Path, mocker: MockerFixture) -> None:
        mock_chown = mocker.patch("devbox.core.ssh.chown_path")
        write_env_file(tmp_path, {"KEY": "val"}, target_user=None)
        mock_chown.assert_not_called()


# ---------------------------------------------------------------------------
# _CompensationStack
# ---------------------------------------------------------------------------


class TestCompensationStack:
    def test_push_and_rollback(self) -> None:
        stack = _CompensationStack()
        order: list[int] = []
        stack.push("first", lambda: order.append(1))
        stack.push("second", lambda: order.append(2))
        errors = stack.rollback()
        assert errors == []
        assert order == [2, 1], "Should execute in reverse order"

    def test_rollback_clears_actions(self) -> None:
        stack = _CompensationStack()
        stack.push("a", lambda: None)
        stack.rollback()
        # Second rollback should be a no-op
        errors = stack.rollback()
        assert errors == []

    def test_rollback_continues_on_error(self) -> None:
        stack = _CompensationStack()
        called: list[str] = []
        stack.push("first", lambda: called.append("first"))

        def fail() -> None:
            raise RuntimeError("boom")

        stack.push("second", fail)
        stack.push("third", lambda: called.append("third"))

        errors = stack.rollback()
        assert len(errors) == 1
        assert "boom" in errors[0]
        # Both non-failing undos should have run
        assert called == ["third", "first"]

    def test_empty_rollback(self) -> None:
        stack = _CompensationStack()
        errors = stack.rollback()
        assert errors == []

    def test_all_fail(self) -> None:
        stack = _CompensationStack()

        def fail_a() -> None:
            raise RuntimeError("a")

        def fail_b() -> None:
            raise RuntimeError("b")

        stack.push("a", fail_a)
        stack.push("b", fail_b)
        errors = stack.rollback()
        assert len(errors) == 2


# ---------------------------------------------------------------------------
# _safe_remove_entry
# ---------------------------------------------------------------------------


class TestSafeRemoveEntry:
    def test_removes_existing_entry(self, tmp_path: Path) -> None:
        registry_path = tmp_path / "registry.json"
        _make_registry(registry_path, [_entry("mybox")])
        _safe_remove_entry("mybox", registry_path)
        from devbox.registry import find_entry

        assert find_entry("mybox", registry_path) is None

    def test_ignores_missing_entry(self, tmp_path: Path) -> None:
        registry_path = tmp_path / "registry.json"
        _make_registry(registry_path, [])
        # Should not raise
        _safe_remove_entry("nonexistent", registry_path)


# ---------------------------------------------------------------------------
# create_devbox
# ---------------------------------------------------------------------------


class TestCreateDevbox:
    @pytest.fixture()
    def setup(self, tmp_path: Path, mocker: MockerFixture) -> dict[str, Any]:
        """Set up preset dir, registry path, and mock all external calls."""
        presets_dir = tmp_path / "presets"
        presets_dir.mkdir()
        _make_preset_file(presets_dir, "test-preset")

        registry_path = tmp_path / "registry.json"
        _make_registry(registry_path, [])

        mocker.patch("devbox.core.macos.create_user", return_value="dx-mybox")
        mocker.patch("devbox.core.ssh.copy_keypair", return_value="ssh-ed25519 AAAA...")
        mocker.patch("devbox.core.ssh.populate_authorized_keys")
        mocker.patch("devbox.core.ssh.add_ssh_config_entry")
        mocker.patch("devbox.core.ssh.remove_ssh_config_entry")
        mocker.patch("devbox.core.onepassword.resolve_env_vars", return_value={"A": "B"})
        mocker.patch("devbox.core.sshd.ensure_ssh_access")
        mocker.patch("devbox.core.sshd.remove_user_from_ssh_group")
        mocker.patch("devbox.core.iterm2.create_profile")
        mocker.patch("devbox.core.iterm2.remove_profile")
        mocker.patch("devbox.core.macos.delete_user")
        mocker.patch("devbox.core.sudoers.add_user")
        mocker.patch("devbox.core.sudoers.remove_user")
        mocker.patch("devbox.core._sudo_chown")
        # write_env_file writes to /Users/dx-mybox which won't exist; mock it
        mocker.patch("devbox.core.write_env_file")
        mocker.patch("devbox.core.inject_auth")
        mocker.patch("devbox.core.bootstrap_user", return_value=[])
        mocker.patch("devbox.core.write_zshrc")
        mocker.patch("devbox.core.time.sleep")

        return {
            "presets_dir": presets_dir,
            "registry_path": registry_path,
        }

    def test_happy_path(self, setup: dict[str, Any]) -> None:
        result = create_devbox(
            "mybox",
            "test-preset",
            registry_path=setup["registry_path"],
            presets_dir=setup["presets_dir"],
        )
        assert result["name"] == "mybox"
        assert result["status"] == DevboxStatus.READY

    def test_duplicate_name_raises(self, setup: dict[str, Any]) -> None:
        _make_registry(
            setup["registry_path"],
            [_entry("mybox", status=DevboxStatus.READY)],
        )
        with pytest.raises(Exception, match="Duplicate devbox name"):
            create_devbox(
                "mybox",
                "test-preset",
                registry_path=setup["registry_path"],
                presets_dir=setup["presets_dir"],
            )

    def test_invalid_name_raises(self, setup: dict[str, Any]) -> None:
        with pytest.raises(ValueError, match="kebab-case"):
            create_devbox(
                "Bad_Name",
                "test-preset",
                registry_path=setup["registry_path"],
                presets_dir=setup["presets_dir"],
            )

    def test_rollback_on_macos_failure(self, setup: dict[str, Any], mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.core.macos.create_user",
            side_effect=DevboxError("user creation failed"),
        )
        with pytest.raises(DevboxError, match="user creation failed"):
            create_devbox(
                "mybox",
                "test-preset",
                registry_path=setup["registry_path"],
                presets_dir=setup["presets_dir"],
            )
        # Registry entry should be rolled back
        from devbox.registry import find_entry

        assert find_entry("mybox", setup["registry_path"]) is None

    def test_rollback_on_sshd_failure(self, setup: dict[str, Any], mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.core.sshd.ensure_ssh_access",
            side_effect=DevboxError("sshd error"),
        )
        with pytest.raises(DevboxError, match="sshd error"):
            create_devbox(
                "mybox",
                "test-preset",
                registry_path=setup["registry_path"],
                presets_dir=setup["presets_dir"],
            )

    def test_rollback_on_iterm2_failure(self, setup: dict[str, Any], mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.core.iterm2.create_profile",
            side_effect=DevboxError("iterm2 error"),
        )
        mock_remove_ssh = mocker.patch("devbox.core.sshd.remove_user_from_ssh_group")
        with pytest.raises(DevboxError, match="iterm2 error"):
            create_devbox(
                "mybox",
                "test-preset",
                registry_path=setup["registry_path"],
                presets_dir=setup["presets_dir"],
            )
        # sshd compensation should fire (it was registered before iterm2)
        mock_remove_ssh.assert_called_once()

    def test_no_env_vars_skips_env_file(self, setup: dict[str, Any], mocker: MockerFixture) -> None:
        # Preset without env_vars
        _make_preset_file(setup["presets_dir"], "no-env", env_vars={})
        _make_registry(setup["registry_path"], [])
        mock_write = mocker.patch("devbox.core.write_env_file")
        create_devbox(
            "mybox",
            "no-env",
            registry_path=setup["registry_path"],
            presets_dir=setup["presets_dir"],
        )
        mock_write.assert_not_called()

    def test_with_env_vars(self, setup: dict[str, Any], mocker: MockerFixture) -> None:
        _make_preset_file(
            setup["presets_dir"],
            "with-env",
            env_vars={"SECRET": "op://vault/item/field"},
        )
        _make_registry(setup["registry_path"], [])
        mock_resolve = mocker.patch(
            "devbox.core.onepassword.resolve_env_vars",
            return_value={"SECRET": "resolved-value"},
        )
        mock_write = mocker.patch("devbox.core.write_env_file")
        create_devbox(
            "mybox",
            "with-env",
            registry_path=setup["registry_path"],
            presets_dir=setup["presets_dir"],
        )
        mock_resolve.assert_called_once_with({"SECRET": "op://vault/item/field"})
        mock_write.assert_called_once()


# ---------------------------------------------------------------------------
# list_devboxes
# ---------------------------------------------------------------------------


class TestListDevboxes:
    def test_empty_registry(self, tmp_path: Path) -> None:
        registry_path = tmp_path / "registry.json"
        _make_registry(registry_path, [])
        result = list_devboxes(registry_path)
        assert result == []

    def test_entry_without_heartbeat(self, tmp_path: Path, mocker: MockerFixture) -> None:
        registry_path = tmp_path / "registry.json"
        _make_registry(
            registry_path,
            [_entry("mybox", status=DevboxStatus.READY)],
        )
        mocker.patch("devbox.core.read_heartbeat", return_value=None)
        result = list_devboxes(registry_path)
        assert len(result) == 1
        assert result[0]["name"] == "mybox"
        assert result[0]["last_seen"] == "never"
        assert result[0]["status"] == "unknown"

    def test_entry_with_recent_heartbeat(self, tmp_path: Path, mocker: MockerFixture) -> None:
        registry_path = tmp_path / "registry.json"
        _make_registry(
            registry_path,
            [_entry("mybox", status=DevboxStatus.READY)],
        )
        recent = datetime.now(UTC) - timedelta(hours=2)
        mocker.patch("devbox.core.read_heartbeat", return_value=recent)
        result = list_devboxes(registry_path)
        assert result[0]["status"] == "healthy"
        assert result[0]["last_seen"] == "2h ago"

    def test_entry_with_old_heartbeat(self, tmp_path: Path, mocker: MockerFixture) -> None:
        registry_path = tmp_path / "registry.json"
        _make_registry(
            registry_path,
            [_entry("mybox", status=DevboxStatus.READY)],
        )
        old = datetime.now(UTC) - timedelta(days=45)
        mocker.patch("devbox.core.read_heartbeat", return_value=old)
        result = list_devboxes(registry_path)
        assert result[0]["status"] == "atrophied"

    def test_creating_status_preserved(self, tmp_path: Path, mocker: MockerFixture) -> None:
        registry_path = tmp_path / "registry.json"
        _make_registry(
            registry_path,
            [_entry("mybox", status=DevboxStatus.CREATING)],
        )
        mocker.patch("devbox.core.read_heartbeat", return_value=None)
        result = list_devboxes(registry_path)
        # Non-READY status should use the raw status value
        assert result[0]["status"] == "creating"

    def test_nuking_status_preserved(self, tmp_path: Path, mocker: MockerFixture) -> None:
        registry_path = tmp_path / "registry.json"
        _make_registry(
            registry_path,
            [_entry("mybox", status=DevboxStatus.NUKING)],
        )
        mocker.patch("devbox.core.read_heartbeat", return_value=None)
        result = list_devboxes(registry_path)
        assert result[0]["status"] == "nuking"

    def test_multiple_entries(self, tmp_path: Path, mocker: MockerFixture) -> None:
        registry_path = tmp_path / "registry.json"
        _make_registry(
            registry_path,
            [
                _entry("box-a", status=DevboxStatus.READY),
                _entry("box-b", status=DevboxStatus.READY),
            ],
        )
        mocker.patch("devbox.core.read_heartbeat", return_value=None)
        result = list_devboxes(registry_path)
        assert len(result) == 2
        names = [r["name"] for r in result]
        assert "box-a" in names
        assert "box-b" in names

    def test_fallback_to_stored_last_seen(self, tmp_path: Path, mocker: MockerFixture) -> None:
        registry_path = tmp_path / "registry.json"
        stored_ts = (datetime.now(UTC) - timedelta(days=2)).isoformat()
        _make_registry(
            registry_path,
            [_entry("mybox", status=DevboxStatus.READY, last_seen=stored_ts)],
        )
        mocker.patch("devbox.core.read_heartbeat", return_value=None)
        result = list_devboxes(registry_path)
        assert result[0]["last_seen"] == "2d ago"
        assert result[0]["status"] == "healthy"


# ---------------------------------------------------------------------------
# sync_heartbeats
# ---------------------------------------------------------------------------


class TestSyncHeartbeats:
    def test_updates_registry_from_heartbeat(self, tmp_path: Path, mocker: MockerFixture) -> None:
        registry_path = tmp_path / "registry.json"
        _make_registry(
            registry_path,
            [_entry("mybox", status=DevboxStatus.READY)],
        )
        ts = datetime.now(UTC) - timedelta(hours=1)
        mocker.patch("devbox.core.read_heartbeat", return_value=ts)
        mock_update = mocker.patch("devbox.core.update_entry")

        sync_heartbeats(registry_path)

        mock_update.assert_called_once_with("mybox", registry_path, last_seen=ts.isoformat())

    def test_skips_when_no_heartbeat(self, tmp_path: Path, mocker: MockerFixture) -> None:
        registry_path = tmp_path / "registry.json"
        _make_registry(
            registry_path,
            [_entry("mybox", status=DevboxStatus.READY)],
        )
        mocker.patch("devbox.core.read_heartbeat", return_value=None)
        mock_update = mocker.patch("devbox.core.update_entry")

        sync_heartbeats(registry_path)

        mock_update.assert_not_called()

    def test_suppresses_devbox_error(self, tmp_path: Path, mocker: MockerFixture) -> None:
        registry_path = tmp_path / "registry.json"
        _make_registry(
            registry_path,
            [_entry("mybox", status=DevboxStatus.READY)],
        )
        ts = datetime.now(UTC) - timedelta(hours=1)
        mocker.patch("devbox.core.read_heartbeat", return_value=ts)
        mocker.patch(
            "devbox.core.update_entry",
            side_effect=DevboxError("registry write failed"),
        )

        # Should not raise
        sync_heartbeats(registry_path)

    def test_multiple_entries(self, tmp_path: Path, mocker: MockerFixture) -> None:
        registry_path = tmp_path / "registry.json"
        _make_registry(
            registry_path,
            [
                _entry("box-a", status=DevboxStatus.READY),
                _entry("box-b", status=DevboxStatus.READY),
            ],
        )
        ts_a = datetime.now(UTC) - timedelta(hours=1)
        ts_b = datetime.now(UTC) - timedelta(hours=2)

        def heartbeat_side_effect(name: str) -> datetime | None:
            return {"box-a": ts_a, "box-b": ts_b}.get(name)

        mocker.patch("devbox.core.read_heartbeat", side_effect=heartbeat_side_effect)
        mock_update = mocker.patch("devbox.core.update_entry")

        sync_heartbeats(registry_path)

        assert mock_update.call_count == 2


# ---------------------------------------------------------------------------
# nuke_devbox
# ---------------------------------------------------------------------------


class TestNukeDevbox:
    @pytest.fixture()
    def setup(self, tmp_path: Path, mocker: MockerFixture) -> dict[str, Any]:
        presets_dir = tmp_path / "presets"
        presets_dir.mkdir()
        _make_preset_file(presets_dir, "test-preset")

        registry_path = tmp_path / "registry.json"
        _make_registry(
            registry_path,
            [_entry("mybox", status=DevboxStatus.READY, github_key_id="999")],
        )

        mocker.patch("devbox.core.sudoers.remove_user")
        mocker.patch("devbox.core.sshd.remove_user_from_ssh_group")
        mocker.patch("devbox.core.macos.delete_user")
        mocker.patch("devbox.core.iterm2.remove_profile")
        mocker.patch("devbox.core.ssh.remove_ssh_config_entry")

        return {"registry_path": registry_path, "presets_dir": presets_dir}

    def test_happy_path(self, setup: dict[str, Any]) -> None:
        errors = nuke_devbox("mybox", registry_path=setup["registry_path"])
        assert errors == []
        from devbox.registry import find_entry

        assert find_entry("mybox", setup["registry_path"]) is None

    def test_not_found_raises(self, setup: dict[str, Any]) -> None:
        with pytest.raises(DevboxError, match="not found"):
            nuke_devbox("no-such-box", registry_path=setup["registry_path"])

    def test_invalid_name_raises(self, setup: dict[str, Any]) -> None:
        with pytest.raises(ValueError, match="kebab-case"):
            nuke_devbox("Bad_Name", registry_path=setup["registry_path"])

    def test_continues_on_sshd_error(self, setup: dict[str, Any], mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.core.sshd.remove_user_from_ssh_group",
            side_effect=DevboxError("sshd error"),
        )
        errors = nuke_devbox("mybox", registry_path=setup["registry_path"])
        assert len(errors) == 1
        assert "sshd error" in errors[0]
        from devbox.registry import find_entry

        assert find_entry("mybox", setup["registry_path"]) is None

    def test_macos_delete_failure_keeps_registry_entry(
        self, setup: dict[str, Any], mocker: MockerFixture
    ) -> None:
        mocker.patch(
            "devbox.core.macos.delete_user",
            side_effect=DevboxError("user stuck"),
        )
        errors = nuke_devbox("mybox", registry_path=setup["registry_path"])
        assert any("user stuck" in e for e in errors)
        from devbox.registry import find_entry

        # Critical failure: registry entry kept in 'nuking' state
        entry = find_entry("mybox", setup["registry_path"])
        assert entry is not None
        assert entry.status == DevboxStatus.NUKING

    def test_continues_on_iterm2_error(self, setup: dict[str, Any], mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.core.iterm2.remove_profile",
            side_effect=DevboxError("profile stuck"),
        )
        errors = nuke_devbox("mybox", registry_path=setup["registry_path"])
        assert len(errors) == 1
        assert "profile stuck" in errors[0]
        from devbox.registry import find_entry

        # iterm2 is not critical, entry should be removed
        assert find_entry("mybox", setup["registry_path"]) is None

    def test_catches_generic_exception(self, setup: dict[str, Any], mocker: MockerFixture) -> None:
        """nuke_devbox catches Exception, not just DevboxError."""
        mocker.patch(
            "devbox.core.sshd.remove_user_from_ssh_group",
            side_effect=RuntimeError("unexpected"),
        )
        errors = nuke_devbox("mybox", registry_path=setup["registry_path"])
        assert len(errors) == 1
        assert "unexpected" in errors[0]


# ---------------------------------------------------------------------------
# rebuild_devbox
# ---------------------------------------------------------------------------


class TestRebuildDevbox:
    def test_happy_path(self, tmp_path: Path, mocker: MockerFixture) -> None:
        presets_dir = tmp_path / "presets"
        presets_dir.mkdir()
        _make_preset_file(presets_dir, "test-preset")

        registry_path = tmp_path / "registry.json"
        _make_registry(
            registry_path,
            [_entry("mybox", status=DevboxStatus.READY, github_key_id="999")],
        )

        def fake_nuke(name: str, registry_path: Path | None = None) -> list[str]:
            from devbox.registry import remove_entry

            remove_entry(name, registry_path)
            return []

        mock_nuke = mocker.patch("devbox.core.nuke_devbox", side_effect=fake_nuke)
        mock_create = mocker.patch(
            "devbox.core.create_devbox",
            return_value={"name": "mybox", "status": "ready"},
        )

        result = rebuild_devbox(
            "mybox",
            registry_path=registry_path,
            presets_dir=presets_dir,
        )
        mock_nuke.assert_called_once_with("mybox", registry_path)
        mock_create.assert_called_once_with("mybox", "test-preset", registry_path, presets_dir)
        assert result["name"] == "mybox"

    def test_not_found_raises(self, tmp_path: Path) -> None:
        registry_path = tmp_path / "registry.json"
        _make_registry(registry_path, [])
        with pytest.raises(DevboxError, match="not found"):
            rebuild_devbox("no-such-box", registry_path=registry_path)

    def test_invalid_name_raises(self, tmp_path: Path) -> None:
        registry_path = tmp_path / "registry.json"
        _make_registry(registry_path, [])
        with pytest.raises(ValueError, match="kebab-case"):
            rebuild_devbox("Bad_Name", registry_path=registry_path)

    def test_preserves_preset(self, tmp_path: Path, mocker: MockerFixture) -> None:
        presets_dir = tmp_path / "presets"
        presets_dir.mkdir()
        _make_preset_file(presets_dir, "custom-preset")

        registry_path = tmp_path / "registry.json"
        _make_registry(
            registry_path,
            [_entry("mybox", preset="custom-preset", status=DevboxStatus.READY)],
        )

        def fake_nuke(name: str, registry_path: Path | None = None) -> list[str]:
            from devbox.registry import remove_entry

            remove_entry(name, registry_path)
            return []

        mocker.patch("devbox.core.nuke_devbox", side_effect=fake_nuke)
        mock_create = mocker.patch(
            "devbox.core.create_devbox",
            return_value={"name": "mybox"},
        )

        rebuild_devbox("mybox", registry_path=registry_path, presets_dir=presets_dir)
        # Ensure the original preset name is passed to create
        mock_create.assert_called_once_with("mybox", "custom-preset", registry_path, presets_dir)

    def test_nuke_critical_failure_raises(self, tmp_path: Path, mocker: MockerFixture) -> None:
        """If nuke leaves the registry entry (critical failure), rebuild raises DevboxError."""
        registry_path = tmp_path / "registry.json"
        _make_registry(
            registry_path,
            [_entry("mybox", status=DevboxStatus.READY, github_key_id="999")],
        )

        # nuke_devbox runs but leaves entry in 'nuking' state (critical failure)
        def fake_nuke(name: str, registry_path: Path | None = None) -> list[str]:
            from devbox.registry import update_entry

            update_entry(name, registry_path, status=DevboxStatus.NUKING)
            return ["macOS user deletion: user stuck"]

        mocker.patch("devbox.core.nuke_devbox", side_effect=fake_nuke)

        with pytest.raises(DevboxError, match="nuke failed to fully clean up"):
            rebuild_devbox("mybox", registry_path=registry_path)


# ---------------------------------------------------------------------------
# refresh_devbox
# ---------------------------------------------------------------------------


class TestRefreshDevbox:
    def _setup(self, tmp_path: Path, **preset_overrides: Any) -> tuple[Path, Path]:
        presets_dir = tmp_path / "presets"
        presets_dir.mkdir()
        _make_preset_file(presets_dir, "test-preset", **preset_overrides)
        registry_path = tmp_path / "registry.json"
        _make_registry(
            registry_path,
            [_entry("mybox", status=DevboxStatus.READY)],
        )
        return registry_path, presets_dir

    def test_default_calls_refresh_dotfiles_only(
        self, tmp_path: Path, mocker: MockerFixture
    ) -> None:
        registry_path, presets_dir = self._setup(
            tmp_path, brew_extras=["jq"], npm_globals=["typescript"]
        )
        mock_refresh = mocker.patch("devbox.bootstrap.refresh_dotfiles")
        mock_brew = mocker.patch("devbox.bootstrap.install_brew_extras")
        mock_npm = mocker.patch("devbox.bootstrap.install_npm_globals")
        mock_pip = mocker.patch("devbox.bootstrap.install_pip_globals")

        refresh_devbox("mybox", registry_path=registry_path, presets_dir=presets_dir)

        mock_refresh.assert_called_once()
        _, kwargs = mock_refresh.call_args
        assert kwargs == {"with_brew": False, "with_globals": False}
        mock_brew.assert_not_called()
        mock_npm.assert_not_called()
        mock_pip.assert_not_called()

    def test_with_brew_runs_extras(self, tmp_path: Path, mocker: MockerFixture) -> None:
        registry_path, presets_dir = self._setup(tmp_path, brew_extras=["jq", "fd"])
        mocker.patch("devbox.bootstrap.refresh_dotfiles")
        mock_brew = mocker.patch("devbox.bootstrap.install_brew_extras")

        refresh_devbox(
            "mybox",
            with_brew=True,
            registry_path=registry_path,
            presets_dir=presets_dir,
        )

        mock_brew.assert_called_once()
        args = mock_brew.call_args[0]
        assert args[1] == ["jq", "fd"]
        assert args[2] == "dx-mybox"

    def test_with_globals_runs_npm_and_pip(self, tmp_path: Path, mocker: MockerFixture) -> None:
        registry_path, presets_dir = self._setup(
            tmp_path, npm_globals=["typescript"], pip_globals=["ruff"]
        )
        mocker.patch("devbox.bootstrap.refresh_dotfiles")
        mock_npm = mocker.patch("devbox.bootstrap.install_npm_globals")
        mock_pip = mocker.patch("devbox.bootstrap.install_pip_globals")

        refresh_devbox(
            "mybox",
            with_globals=True,
            registry_path=registry_path,
            presets_dir=presets_dir,
        )

        mock_npm.assert_called_once()
        mock_pip.assert_called_once()

    def test_not_found_raises(self, tmp_path: Path) -> None:
        registry_path = tmp_path / "registry.json"
        _make_registry(registry_path, [])
        with pytest.raises(DevboxError, match="not found"):
            refresh_devbox("no-such", registry_path=registry_path)

    def test_invalid_name_raises(self, tmp_path: Path) -> None:
        registry_path = tmp_path / "registry.json"
        _make_registry(registry_path, [])
        with pytest.raises(ValueError, match="kebab-case"):
            refresh_devbox("Bad_Name", registry_path=registry_path)

    @pytest.mark.parametrize(
        "status",
        [DevboxStatus.CREATING, DevboxStatus.NUKING],
    )
    def test_non_ready_status_raises(self, tmp_path: Path, status: DevboxStatus) -> None:
        presets_dir = tmp_path / "presets"
        presets_dir.mkdir()
        _make_preset_file(presets_dir, "test-preset")
        registry_path = tmp_path / "registry.json"
        _make_registry(registry_path, [_entry("mybox", status=status)])
        with pytest.raises(DevboxError, match="not ready"):
            refresh_devbox("mybox", registry_path=registry_path, presets_dir=presets_dir)

    def test_with_brew_skips_install_when_no_extras(
        self, tmp_path: Path, mocker: MockerFixture
    ) -> None:
        registry_path, presets_dir = self._setup(tmp_path, brew_extras=[])
        mocker.patch("devbox.bootstrap.refresh_dotfiles")
        mock_brew = mocker.patch("devbox.bootstrap.install_brew_extras")
        refresh_devbox(
            "mybox",
            with_brew=True,
            registry_path=registry_path,
            presets_dir=presets_dir,
        )
        mock_brew.assert_not_called()

    def test_refresh_dotfiles_failure_short_circuits(
        self, tmp_path: Path, mocker: MockerFixture
    ) -> None:
        registry_path, presets_dir = self._setup(tmp_path, brew_extras=["jq"])
        mocker.patch(
            "devbox.bootstrap.refresh_dotfiles",
            side_effect=DevboxError("ssh exploded"),
        )
        mock_brew = mocker.patch("devbox.bootstrap.install_brew_extras")
        with pytest.raises(DevboxError, match="ssh exploded"):
            refresh_devbox(
                "mybox",
                with_brew=True,
                registry_path=registry_path,
                presets_dir=presets_dir,
            )
        mock_brew.assert_not_called()


# ---------------------------------------------------------------------------
# create_devbox dry-run
# ---------------------------------------------------------------------------


class TestCreateDevboxDryRun:
    @pytest.fixture()
    def setup(self, tmp_path: Path, mocker: MockerFixture) -> dict[str, Any]:
        """Set up preset dir, registry path, and mock all external calls."""
        presets_dir = tmp_path / "presets"
        presets_dir.mkdir()
        _make_preset_file(
            presets_dir,
            "test-preset",
            env_vars={"SECRET": "op://vault/item/field", "OTHER": "plain"},
        )

        registry_path = tmp_path / "registry.json"
        _make_registry(registry_path, [])

        # Mock all side-effecting modules to detect if they are called
        mocker.patch("devbox.core.macos.create_user", return_value="dx-mybox")
        mocker.patch("devbox.core.ssh.copy_keypair", return_value="ssh-ed25519 AAAA...")
        mocker.patch("devbox.core.ssh.populate_authorized_keys")
        mocker.patch("devbox.core.onepassword.resolve_env_vars", return_value={"A": "B"})
        mocker.patch("devbox.core.sshd.ensure_ssh_access")
        mocker.patch("devbox.core.sshd.remove_user_from_ssh_group")
        mocker.patch("devbox.core.iterm2.create_profile")
        mocker.patch("devbox.core.iterm2.remove_profile")
        mocker.patch("devbox.core.macos.delete_user")
        mocker.patch("devbox.core.write_env_file")

        return {
            "presets_dir": presets_dir,
            "registry_path": registry_path,
        }

    def test_returns_dry_run_status(self, setup: dict[str, Any]) -> None:
        result = create_devbox(
            "mybox",
            "test-preset",
            registry_path=setup["registry_path"],
            presets_dir=setup["presets_dir"],
            dry_run=True,
        )
        assert result["status"] == "dry-run"
        assert result["name"] == "mybox"
        assert result["preset"] == "test-preset"

    def test_returns_actions_list(self, setup: dict[str, Any]) -> None:
        result = create_devbox(
            "mybox",
            "test-preset",
            registry_path=setup["registry_path"],
            presets_dir=setup["presets_dir"],
            dry_run=True,
        )
        actions = result["actions"]
        assert isinstance(actions, list)
        assert len(actions) == 9

    def test_action_messages_contain_expected_text(self, setup: dict[str, Any]) -> None:
        result = create_devbox(
            "mybox",
            "test-preset",
            registry_path=setup["registry_path"],
            presets_dir=setup["presets_dir"],
            dry_run=True,
        )
        actions = result["actions"]
        assert any("Would create registry entry" in a for a in actions)
        assert any("Would create macOS user dx-mybox" in a for a in actions)
        assert any("Would copy SSH key" in a for a in actions)
        assert any("Would populate authorized_keys" in a for a in actions)
        assert any("Would resolve 2 environment variables" in a for a in actions)
        assert any("Would install per-devbox Homebrew" in a for a in actions)
        assert any("Would write .zshrc with heartbeat hook" in a for a in actions)
        assert any("Would ensure SSH access for dx-mybox" in a for a in actions)
        assert any("Would create iTerm2 profile devbox::mybox" in a for a in actions)

    def test_no_side_effects(self, setup: dict[str, Any], mocker: MockerFixture) -> None:
        """Dry run must not call any side-effecting functions."""
        mock_create_user = mocker.patch("devbox.core.macos.create_user")
        mock_copy_keypair = mocker.patch("devbox.core.ssh.copy_keypair")
        mock_ensure_ssh = mocker.patch("devbox.core.sshd.ensure_ssh_access")
        mock_create_profile = mocker.patch("devbox.core.iterm2.create_profile")
        mock_resolve_env = mocker.patch("devbox.core.onepassword.resolve_env_vars")

        create_devbox(
            "mybox",
            "test-preset",
            registry_path=setup["registry_path"],
            presets_dir=setup["presets_dir"],
            dry_run=True,
        )
        # None of the side-effecting mocks should have been called
        mock_create_user.assert_not_called()
        mock_copy_keypair.assert_not_called()
        mock_ensure_ssh.assert_not_called()
        mock_create_profile.assert_not_called()
        mock_resolve_env.assert_not_called()

    def test_no_registry_entry_created(self, setup: dict[str, Any]) -> None:
        """Dry run must not write to the registry."""
        create_devbox(
            "mybox",
            "test-preset",
            registry_path=setup["registry_path"],
            presets_dir=setup["presets_dir"],
            dry_run=True,
        )
        from devbox.registry import find_entry

        assert find_entry("mybox", setup["registry_path"]) is None

    def test_duplicate_name_succeeds_in_dry_run(self, setup: dict[str, Any]) -> None:
        """Dry run does not check for duplicate names (validation is deferred to real run)."""
        _make_registry(
            setup["registry_path"],
            [_entry("mybox", status=DevboxStatus.READY)],
        )
        result = create_devbox(
            "mybox",
            "test-preset",
            registry_path=setup["registry_path"],
            presets_dir=setup["presets_dir"],
            dry_run=True,
        )
        assert result["status"] == "dry-run"

    def test_invalid_name_still_raises(self, setup: dict[str, Any]) -> None:
        """Dry run still validates the name."""
        with pytest.raises(ValueError, match="kebab-case"):
            create_devbox(
                "Bad_Name",
                "test-preset",
                registry_path=setup["registry_path"],
                presets_dir=setup["presets_dir"],
                dry_run=True,
            )

    def test_no_inject_auth_bootstrap_or_zshrc(
        self, setup: dict[str, Any], mocker: MockerFixture
    ) -> None:
        """Dry run must not call inject_auth, bootstrap_user, or write_zshrc."""
        mock_inject = mocker.patch("devbox.core.inject_auth")
        mock_bootstrap = mocker.patch("devbox.core.bootstrap_user")
        mock_zshrc = mocker.patch("devbox.core.write_zshrc")

        create_devbox(
            "mybox",
            "test-preset",
            registry_path=setup["registry_path"],
            presets_dir=setup["presets_dir"],
            dry_run=True,
        )

        mock_inject.assert_not_called()
        mock_bootstrap.assert_not_called()
        mock_zshrc.assert_not_called()


# ---------------------------------------------------------------------------
# nuke_devbox dry-run
# ---------------------------------------------------------------------------


class TestNukeDevboxDryRun:
    @pytest.fixture()
    def setup(self, tmp_path: Path, mocker: MockerFixture) -> dict[str, Any]:
        presets_dir = tmp_path / "presets"
        presets_dir.mkdir()
        _make_preset_file(presets_dir, "test-preset")

        registry_path = tmp_path / "registry.json"
        _make_registry(
            registry_path,
            [_entry("mybox", status=DevboxStatus.READY, github_key_id="999")],
        )

        mocker.patch("devbox.core.sshd.remove_user_from_ssh_group")
        mocker.patch("devbox.core.macos.delete_user")
        mocker.patch("devbox.core.iterm2.remove_profile")

        return {"registry_path": registry_path, "presets_dir": presets_dir}

    def test_returns_actions_list(self, setup: dict[str, Any]) -> None:
        actions = nuke_devbox("mybox", registry_path=setup["registry_path"], dry_run=True)
        assert isinstance(actions, list)
        assert len(actions) > 0
        assert any("Would mark devbox" in a for a in actions)
        assert any("Would remove" in a and "SSH access group" in a for a in actions)
        assert any("Would delete macOS user" in a for a in actions)
        assert any("Would remove iTerm2 profile" in a for a in actions)
        assert any("Would remove registry entry" in a for a in actions)

    def test_no_side_effects(self, setup: dict[str, Any], mocker: MockerFixture) -> None:
        """Dry run must not call any side-effecting functions."""
        mock_remove_ssh = mocker.patch("devbox.core.sshd.remove_user_from_ssh_group")
        mock_delete_user = mocker.patch("devbox.core.macos.delete_user")
        mock_remove_profile = mocker.patch("devbox.core.iterm2.remove_profile")

        nuke_devbox("mybox", registry_path=setup["registry_path"], dry_run=True)
        mock_remove_ssh.assert_not_called()
        mock_delete_user.assert_not_called()
        mock_remove_profile.assert_not_called()

    def test_registry_entry_preserved(self, setup: dict[str, Any]) -> None:
        """Dry run must not modify the registry."""
        nuke_devbox("mybox", registry_path=setup["registry_path"], dry_run=True)
        from devbox.registry import find_entry

        entry = find_entry("mybox", setup["registry_path"])
        assert entry is not None
        assert entry.status == DevboxStatus.READY

    def test_not_found_still_raises(self, setup: dict[str, Any]) -> None:
        with pytest.raises(DevboxError, match="not found"):
            nuke_devbox("no-such-box", registry_path=setup["registry_path"], dry_run=True)

    def test_invalid_name_still_raises(self, setup: dict[str, Any]) -> None:
        with pytest.raises(ValueError, match="kebab-case"):
            nuke_devbox("Bad_Name", registry_path=setup["registry_path"], dry_run=True)
