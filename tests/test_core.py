"""Tests for core devbox operations."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from devbox.core import (
    _CompensationStack,
    _format_last_seen,
    _health_status,
    _read_heartbeat,
    _safe_remove_entry,
    _shell_escape,
    create_devbox,
    list_devboxes,
    nuke_devbox,
    rebuild_devbox,
    sync_heartbeats,
    write_env_file,
)
from devbox.exceptions import DevboxError
from devbox.registry import DevboxStatus, Registry, RegistryEntry, save_registry

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
# _shell_escape
# ---------------------------------------------------------------------------


class TestShellEscape:
    def test_simple_value(self) -> None:
        assert _shell_escape("hello") == "'hello'"

    def test_value_with_spaces(self) -> None:
        assert _shell_escape("hello world") == "'hello world'"

    def test_value_with_single_quotes(self) -> None:
        result = _shell_escape("it's")
        # Should produce 'it'"'"'s'
        assert result == "'it'\"'\"'s'"

    def test_empty_string(self) -> None:
        assert _shell_escape("") == "''"

    def test_value_with_special_chars(self) -> None:
        result = _shell_escape("foo$bar")
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

    def test_chowns_when_target_user_provided(
        self, tmp_path: Path, mocker: MockerFixture
    ) -> None:
        mock_chown = mocker.patch("devbox.core.ssh.chown_path")
        write_env_file(tmp_path, {"KEY": "val"}, target_user="dx-mybox")
        mock_chown.assert_called_once_with(tmp_path / ".devbox-env", "dx-mybox")

    def test_no_chown_when_target_user_none(
        self, tmp_path: Path, mocker: MockerFixture
    ) -> None:
        mock_chown = mocker.patch("devbox.core.ssh.chown_path")
        write_env_file(tmp_path, {"KEY": "val"})
        mock_chown.assert_not_called()

    def test_no_chown_when_target_user_omitted(
        self, tmp_path: Path, mocker: MockerFixture
    ) -> None:
        mock_chown = mocker.patch("devbox.core.ssh.chown_path")
        write_env_file(tmp_path, {"KEY": "val"}, target_user=None)
        mock_chown.assert_not_called()


# ---------------------------------------------------------------------------
# _read_heartbeat
# ---------------------------------------------------------------------------


class TestReadHeartbeat:
    def test_returns_none_when_missing(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.core.Path.exists", return_value=False)
        assert _read_heartbeat("test") is None

    def test_returns_datetime_when_valid(self, mocker: MockerFixture) -> None:
        ts = "2025-06-15T12:00:00+00:00"
        mocker.patch("devbox.core.Path.exists", return_value=True)
        mocker.patch("devbox.core.Path.read_text", return_value=ts)
        result = _read_heartbeat("test")
        assert result is not None
        assert result.isoformat() == ts

    def test_returns_none_on_invalid_content(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.core.Path.exists", return_value=True)
        mocker.patch("devbox.core.Path.read_text", return_value="not-a-date")
        assert _read_heartbeat("test") is None

    def test_returns_none_on_os_error(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.core.Path.exists", return_value=True)
        mocker.patch("devbox.core.Path.read_text", side_effect=OSError("denied"))
        assert _read_heartbeat("test") is None


# ---------------------------------------------------------------------------
# _health_status
# ---------------------------------------------------------------------------


class TestHealthStatus:
    def test_unknown_when_none(self) -> None:
        assert _health_status(None) == "unknown"

    def test_healthy_recent(self) -> None:
        recent = datetime.now(UTC) - timedelta(days=1)
        assert _health_status(recent) == "healthy"

    def test_atrophied_old(self) -> None:
        old = datetime.now(UTC) - timedelta(days=31)
        assert _health_status(old) == "atrophied"

    def test_boundary_29_days_is_healthy(self) -> None:
        # 29 days is well under the 30-day threshold
        ts = datetime.now(UTC) - timedelta(days=29)
        assert _health_status(ts) == "healthy"

    def test_boundary_exact_30_days_is_healthy(self, mocker: MockerFixture) -> None:
        # Exactly 30 days uses > (not >=), so 30 days is still healthy
        now = datetime(2025, 7, 15, 12, 0, 0, tzinfo=UTC)
        mocker.patch("devbox.core.datetime", wraps=datetime)
        mocker.patch("devbox.core.datetime.now", return_value=now)
        ts = now - timedelta(days=30)
        assert _health_status(ts) == "healthy"

    def test_boundary_31_days_is_atrophied(self) -> None:
        ts = datetime.now(UTC) - timedelta(days=31)
        assert _health_status(ts) == "atrophied"

    def test_naive_datetime_treated_as_utc(self) -> None:
        naive = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=1)
        assert _health_status(naive) == "healthy"


# ---------------------------------------------------------------------------
# _format_last_seen
# ---------------------------------------------------------------------------


class TestFormatLastSeen:
    def test_none_returns_never(self) -> None:
        assert _format_last_seen(None) == "never"

    def test_days_ago(self) -> None:
        ts = datetime.now(UTC) - timedelta(days=5)
        assert _format_last_seen(ts) == "5d ago"

    def test_hours_ago(self) -> None:
        ts = datetime.now(UTC) - timedelta(hours=3)
        assert _format_last_seen(ts) == "3h ago"

    def test_minutes_ago(self) -> None:
        ts = datetime.now(UTC) - timedelta(minutes=10)
        assert _format_last_seen(ts) == "10m ago"

    def test_just_now(self) -> None:
        ts = datetime.now(UTC) - timedelta(seconds=5)
        assert _format_last_seen(ts) == "just now"

    def test_naive_datetime(self) -> None:
        naive = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=2)
        assert _format_last_seen(naive) == "2h ago"


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
        mocker.patch("devbox.core.ssh.generate_keypair", return_value="ssh-ed25519 AAAA...")
        mocker.patch("devbox.core.ssh.populate_authorized_keys")
        mocker.patch("devbox.core.github.add_ssh_key", return_value="12345")
        mocker.patch("devbox.core.github.remove_ssh_key")
        mocker.patch("devbox.core.onepassword.resolve_env_vars", return_value={"A": "B"})
        mocker.patch("devbox.core.sshd.ensure_ssh_access")
        mocker.patch("devbox.core.sshd.remove_user_from_ssh_group")
        mocker.patch("devbox.core.iterm2.create_profile")
        mocker.patch("devbox.core.iterm2.remove_profile")
        mocker.patch("devbox.core.macos.delete_user")
        # write_env_file writes to /Users/dx-mybox which won't exist; mock it
        mocker.patch("devbox.core.write_env_file")

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
        with pytest.raises(DevboxError, match="already exists"):
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

    def test_rollback_on_macos_failure(
        self, setup: dict[str, Any], mocker: MockerFixture
    ) -> None:
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

    def test_rollback_on_github_failure(
        self, setup: dict[str, Any], mocker: MockerFixture
    ) -> None:
        mocker.patch(
            "devbox.core.github.add_ssh_key",
            side_effect=DevboxError("github error"),
        )
        mock_delete_user = mocker.patch("devbox.core.macos.delete_user")
        with pytest.raises(DevboxError, match="github error"):
            create_devbox(
                "mybox",
                "test-preset",
                registry_path=setup["registry_path"],
                presets_dir=setup["presets_dir"],
            )
        # macOS user should be rolled back
        mock_delete_user.assert_called_once()
        # Registry should be cleaned up
        from devbox.registry import find_entry

        assert find_entry("mybox", setup["registry_path"]) is None

    def test_rollback_on_sshd_failure(
        self, setup: dict[str, Any], mocker: MockerFixture
    ) -> None:
        mocker.patch(
            "devbox.core.sshd.ensure_ssh_access",
            side_effect=DevboxError("sshd error"),
        )
        mock_remove_key = mocker.patch("devbox.core.github.remove_ssh_key")
        with pytest.raises(DevboxError, match="sshd error"):
            create_devbox(
                "mybox",
                "test-preset",
                registry_path=setup["registry_path"],
                presets_dir=setup["presets_dir"],
            )
        mock_remove_key.assert_called_once()

    def test_rollback_on_iterm2_failure(
        self, setup: dict[str, Any], mocker: MockerFixture
    ) -> None:
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

    def test_no_env_vars_skips_env_file(
        self, setup: dict[str, Any], mocker: MockerFixture
    ) -> None:
        # Preset without env_vars
        _make_preset_file(
            setup["presets_dir"], "no-env", env_vars={}
        )
        _make_registry(setup["registry_path"], [])
        mock_write = mocker.patch("devbox.core.write_env_file")
        create_devbox(
            "mybox",
            "no-env",
            registry_path=setup["registry_path"],
            presets_dir=setup["presets_dir"],
        )
        mock_write.assert_not_called()

    def test_with_env_vars(
        self, setup: dict[str, Any], mocker: MockerFixture
    ) -> None:
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

    def test_registry_entry_has_github_key_id(self, setup: dict[str, Any]) -> None:
        result = create_devbox(
            "mybox",
            "test-preset",
            registry_path=setup["registry_path"],
            presets_dir=setup["presets_dir"],
        )
        assert result["github_key_id"] == "12345"


# ---------------------------------------------------------------------------
# list_devboxes
# ---------------------------------------------------------------------------


class TestListDevboxes:
    def test_empty_registry(self, tmp_path: Path) -> None:
        registry_path = tmp_path / "registry.json"
        _make_registry(registry_path, [])
        result = list_devboxes(registry_path)
        assert result == []

    def test_entry_without_heartbeat(
        self, tmp_path: Path, mocker: MockerFixture
    ) -> None:
        registry_path = tmp_path / "registry.json"
        _make_registry(
            registry_path,
            [_entry("mybox", status=DevboxStatus.READY)],
        )
        mocker.patch("devbox.core._read_heartbeat", return_value=None)
        result = list_devboxes(registry_path)
        assert len(result) == 1
        assert result[0]["name"] == "mybox"
        assert result[0]["last_seen"] == "never"
        assert result[0]["status"] == "unknown"

    def test_entry_with_recent_heartbeat(
        self, tmp_path: Path, mocker: MockerFixture
    ) -> None:
        registry_path = tmp_path / "registry.json"
        _make_registry(
            registry_path,
            [_entry("mybox", status=DevboxStatus.READY)],
        )
        recent = datetime.now(UTC) - timedelta(hours=2)
        mocker.patch("devbox.core._read_heartbeat", return_value=recent)
        result = list_devboxes(registry_path)
        assert result[0]["status"] == "healthy"
        assert result[0]["last_seen"] == "2h ago"

    def test_entry_with_old_heartbeat(
        self, tmp_path: Path, mocker: MockerFixture
    ) -> None:
        registry_path = tmp_path / "registry.json"
        _make_registry(
            registry_path,
            [_entry("mybox", status=DevboxStatus.READY)],
        )
        old = datetime.now(UTC) - timedelta(days=45)
        mocker.patch("devbox.core._read_heartbeat", return_value=old)
        result = list_devboxes(registry_path)
        assert result[0]["status"] == "atrophied"

    def test_creating_status_preserved(
        self, tmp_path: Path, mocker: MockerFixture
    ) -> None:
        registry_path = tmp_path / "registry.json"
        _make_registry(
            registry_path,
            [_entry("mybox", status=DevboxStatus.CREATING)],
        )
        mocker.patch("devbox.core._read_heartbeat", return_value=None)
        result = list_devboxes(registry_path)
        # Non-READY status should use the raw status value
        assert result[0]["status"] == "creating"

    def test_nuking_status_preserved(
        self, tmp_path: Path, mocker: MockerFixture
    ) -> None:
        registry_path = tmp_path / "registry.json"
        _make_registry(
            registry_path,
            [_entry("mybox", status=DevboxStatus.NUKING)],
        )
        mocker.patch("devbox.core._read_heartbeat", return_value=None)
        result = list_devboxes(registry_path)
        assert result[0]["status"] == "nuking"

    def test_multiple_entries(
        self, tmp_path: Path, mocker: MockerFixture
    ) -> None:
        registry_path = tmp_path / "registry.json"
        _make_registry(
            registry_path,
            [
                _entry("box-a", status=DevboxStatus.READY),
                _entry("box-b", status=DevboxStatus.READY),
            ],
        )
        mocker.patch("devbox.core._read_heartbeat", return_value=None)
        result = list_devboxes(registry_path)
        assert len(result) == 2
        names = [r["name"] for r in result]
        assert "box-a" in names
        assert "box-b" in names

    def test_fallback_to_stored_last_seen(
        self, tmp_path: Path, mocker: MockerFixture
    ) -> None:
        registry_path = tmp_path / "registry.json"
        stored_ts = (datetime.now(UTC) - timedelta(days=2)).isoformat()
        _make_registry(
            registry_path,
            [_entry("mybox", status=DevboxStatus.READY, last_seen=stored_ts)],
        )
        mocker.patch("devbox.core._read_heartbeat", return_value=None)
        result = list_devboxes(registry_path)
        assert result[0]["last_seen"] == "2d ago"
        assert result[0]["status"] == "healthy"


# ---------------------------------------------------------------------------
# sync_heartbeats
# ---------------------------------------------------------------------------


class TestSyncHeartbeats:
    def test_updates_registry_from_heartbeat(
        self, tmp_path: Path, mocker: MockerFixture
    ) -> None:
        registry_path = tmp_path / "registry.json"
        _make_registry(
            registry_path,
            [_entry("mybox", status=DevboxStatus.READY)],
        )
        ts = datetime.now(UTC) - timedelta(hours=1)
        mocker.patch("devbox.core._read_heartbeat", return_value=ts)
        mock_update = mocker.patch("devbox.core.update_entry")

        sync_heartbeats(registry_path)

        mock_update.assert_called_once_with(
            "mybox", registry_path, last_seen=ts.isoformat()
        )

    def test_skips_when_no_heartbeat(
        self, tmp_path: Path, mocker: MockerFixture
    ) -> None:
        registry_path = tmp_path / "registry.json"
        _make_registry(
            registry_path,
            [_entry("mybox", status=DevboxStatus.READY)],
        )
        mocker.patch("devbox.core._read_heartbeat", return_value=None)
        mock_update = mocker.patch("devbox.core.update_entry")

        sync_heartbeats(registry_path)

        mock_update.assert_not_called()

    def test_suppresses_devbox_error(
        self, tmp_path: Path, mocker: MockerFixture
    ) -> None:
        registry_path = tmp_path / "registry.json"
        _make_registry(
            registry_path,
            [_entry("mybox", status=DevboxStatus.READY)],
        )
        ts = datetime.now(UTC) - timedelta(hours=1)
        mocker.patch("devbox.core._read_heartbeat", return_value=ts)
        mocker.patch(
            "devbox.core.update_entry",
            side_effect=DevboxError("registry write failed"),
        )

        # Should not raise
        sync_heartbeats(registry_path)

    def test_multiple_entries(
        self, tmp_path: Path, mocker: MockerFixture
    ) -> None:
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

        mocker.patch("devbox.core._read_heartbeat", side_effect=heartbeat_side_effect)
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

        mocker.patch("devbox.core.load_preset", return_value=MagicMock(github_account="testuser"))
        mocker.patch("devbox.core.github.remove_ssh_key")
        mocker.patch("devbox.core.sshd.remove_user_from_ssh_group")
        mocker.patch("devbox.core.macos.delete_user")
        mocker.patch("devbox.core.iterm2.remove_profile")

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

    def test_continues_on_github_error(
        self, setup: dict[str, Any], mocker: MockerFixture
    ) -> None:
        mocker.patch(
            "devbox.core.github.remove_ssh_key",
            side_effect=DevboxError("github down"),
        )
        # Should not raise — errors are logged but nuke continues
        errors = nuke_devbox("mybox", registry_path=setup["registry_path"])
        assert len(errors) == 1
        assert "github down" in errors[0]
        from devbox.registry import find_entry

        assert find_entry("mybox", setup["registry_path"]) is None

    def test_continues_on_sshd_error(
        self, setup: dict[str, Any], mocker: MockerFixture
    ) -> None:
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

    def test_continues_on_iterm2_error(
        self, setup: dict[str, Any], mocker: MockerFixture
    ) -> None:
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

    def test_no_github_key_skips_removal(
        self, setup: dict[str, Any], mocker: MockerFixture
    ) -> None:
        # Replace registry with entry that has no github_key_id
        _make_registry(
            setup["registry_path"],
            [_entry("mybox", status=DevboxStatus.READY, github_key_id=None)],
        )
        mock_remove = mocker.patch("devbox.core.github.remove_ssh_key")
        errors = nuke_devbox("mybox", registry_path=setup["registry_path"])
        assert errors == []
        mock_remove.assert_not_called()

    def test_catches_generic_exception(
        self, setup: dict[str, Any], mocker: MockerFixture
    ) -> None:
        """nuke_devbox catches Exception, not just DevboxError."""
        mocker.patch(
            "devbox.core.github.remove_ssh_key",
            side_effect=RuntimeError("unexpected"),
        )
        errors = nuke_devbox("mybox", registry_path=setup["registry_path"])
        assert len(errors) == 1
        assert "unexpected" in errors[0]

    def test_load_preset_failure_during_github_key_removal(
        self, setup: dict[str, Any], mocker: MockerFixture
    ) -> None:
        """If load_preset fails during GitHub key removal, error is captured and nuke continues."""
        mocker.patch(
            "devbox.core.load_preset",
            side_effect=DevboxError("preset file missing"),
        )
        errors = nuke_devbox("mybox", registry_path=setup["registry_path"])
        assert any("preset file missing" in e for e in errors)
        from devbox.registry import find_entry

        # Non-critical failure: registry entry should still be removed
        assert find_entry("mybox", setup["registry_path"]) is None


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
        mock_create.assert_called_once_with(
            "mybox", "test-preset", registry_path, presets_dir
        )
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
        mock_create.assert_called_once_with(
            "mybox", "custom-preset", registry_path, presets_dir
        )

    def test_nuke_critical_failure_raises(
        self, tmp_path: Path, mocker: MockerFixture
    ) -> None:
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
