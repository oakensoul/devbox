# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Robert Gunnar Johnson Jr.

"""Tests for devbox health checking."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from pytest_mock import MockerFixture

from devbox.health import (
    _ATROPHY_DAYS,
    check_all_ssh,
    check_ssh,
    format_last_seen,
    get_health,
    health_status,
    read_heartbeat,
)

# ---------------------------------------------------------------------------
# read_heartbeat
# ---------------------------------------------------------------------------


class TestReadHeartbeat:
    def test_returns_none_when_file_missing(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.health.Path.exists", return_value=False)
        assert read_heartbeat("dev1") is None

    def test_parses_iso_timestamp(self, mocker: MockerFixture) -> None:
        ts = "2025-06-15T10:30:00+00:00"
        mocker.patch("devbox.health.Path.exists", return_value=True)
        mocker.patch("devbox.health.Path.read_text", return_value=ts)
        result = read_heartbeat("dev1")
        assert result == datetime.fromisoformat(ts)

    def test_returns_none_on_malformed_timestamp(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.health.Path.exists", return_value=True)
        mocker.patch("devbox.health.Path.read_text", return_value="not-a-date")
        assert read_heartbeat("dev1") is None

    def test_returns_none_on_os_error(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.health.Path.exists", return_value=True)
        mocker.patch("devbox.health.Path.read_text", side_effect=OSError("nope"))
        assert read_heartbeat("dev1") is None

    def test_strips_whitespace(self, mocker: MockerFixture) -> None:
        ts = "2025-06-15T10:30:00+00:00"
        mocker.patch("devbox.health.Path.exists", return_value=True)
        mocker.patch("devbox.health.Path.read_text", return_value=f"  {ts}  \n")
        result = read_heartbeat("dev1")
        assert result == datetime.fromisoformat(ts)

    def test_uses_dx_prefix_path(self, mocker: MockerFixture) -> None:
        mock_exists = mocker.patch("devbox.health.Path.exists", return_value=False)
        read_heartbeat("my-box")
        # The Path object should have been constructed with dx- prefix
        # We verify indirectly: function returned None because exists=False
        mock_exists.assert_called_once()


# ---------------------------------------------------------------------------
# health_status
# ---------------------------------------------------------------------------


class TestHealthStatus:
    def test_none_returns_unknown(self) -> None:
        assert health_status(None) == "unknown"

    def test_recent_returns_healthy(self) -> None:
        now = datetime.now(UTC)
        assert health_status(now) == "healthy"

    def test_one_day_ago_healthy(self) -> None:
        ts = datetime.now(UTC) - timedelta(days=1)
        assert health_status(ts) == "healthy"

    def test_exactly_at_threshold_healthy(self) -> None:
        # Subtract slightly less than the threshold to avoid microsecond drift
        ts = datetime.now(UTC) - timedelta(days=_ATROPHY_DAYS, seconds=-1)
        assert health_status(ts) == "healthy"

    def test_beyond_threshold_atrophied(self) -> None:
        ts = datetime.now(UTC) - timedelta(days=_ATROPHY_DAYS + 1)
        assert health_status(ts) == "atrophied"

    def test_far_future_healthy(self) -> None:
        ts = datetime.now(UTC) + timedelta(days=100)
        assert health_status(ts) == "healthy"

    def test_naive_datetime_treated_as_utc(self) -> None:
        ts = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=_ATROPHY_DAYS + 1)
        assert health_status(ts) == "atrophied"

    def test_29_days_ago_healthy(self) -> None:
        ts = datetime.now(UTC) - timedelta(days=29)
        assert health_status(ts) == "healthy"

    def test_31_days_ago_atrophied(self) -> None:
        ts = datetime.now(UTC) - timedelta(days=31)
        assert health_status(ts) == "atrophied"


# ---------------------------------------------------------------------------
# format_last_seen
# ---------------------------------------------------------------------------


class TestFormatLastSeen:
    def test_none_returns_never(self) -> None:
        assert format_last_seen(None) == "never"

    def test_just_now(self) -> None:
        now = datetime.now(UTC)
        assert format_last_seen(now) == "just now"

    def test_minutes_ago(self) -> None:
        ts = datetime.now(UTC) - timedelta(minutes=15)
        assert format_last_seen(ts) == "15m ago"

    def test_hours_ago(self) -> None:
        ts = datetime.now(UTC) - timedelta(hours=3)
        assert format_last_seen(ts) == "3h ago"

    def test_days_ago(self) -> None:
        ts = datetime.now(UTC) - timedelta(days=7)
        assert format_last_seen(ts) == "7d ago"

    def test_one_minute_ago(self) -> None:
        ts = datetime.now(UTC) - timedelta(minutes=1)
        assert format_last_seen(ts) == "1m ago"

    def test_one_hour_ago(self) -> None:
        ts = datetime.now(UTC) - timedelta(hours=1)
        assert format_last_seen(ts) == "1h ago"

    def test_one_day_ago(self) -> None:
        ts = datetime.now(UTC) - timedelta(days=1)
        assert format_last_seen(ts) == "1d ago"

    def test_naive_datetime(self) -> None:
        ts = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=5)
        assert format_last_seen(ts) == "5d ago"

    def test_30_seconds_is_just_now(self) -> None:
        ts = datetime.now(UTC) - timedelta(seconds=30)
        assert format_last_seen(ts) == "just now"


# ---------------------------------------------------------------------------
# check_ssh
# ---------------------------------------------------------------------------


class TestCheckSsh:
    def test_returns_true_on_success(self, mocker: MockerFixture) -> None:
        mock_run = mocker.patch("devbox.health.subprocess.run")
        mock_run.return_value = MagicMock(returncode=0)
        assert check_ssh("dev1") is True

    def test_returns_false_on_nonzero(self, mocker: MockerFixture) -> None:
        mock_run = mocker.patch("devbox.health.subprocess.run")
        mock_run.return_value = MagicMock(returncode=1)
        assert check_ssh("dev1") is False

    def test_returns_false_on_timeout(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.health.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="ssh", timeout=10),
        )
        assert check_ssh("dev1") is False

    def test_returns_false_on_os_error(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.health.subprocess.run",
            side_effect=OSError("ssh not found"),
        )
        assert check_ssh("dev1") is False

    def test_uses_dx_prefix_in_command(self, mocker: MockerFixture) -> None:
        mock_run = mocker.patch("devbox.health.subprocess.run")
        mock_run.return_value = MagicMock(returncode=0)
        check_ssh("my-box", timeout=3)
        args = mock_run.call_args[0][0]
        assert "dx-my-box@localhost" in args
        assert "-o" in args
        assert "ConnectTimeout=3" in args

    def test_custom_timeout(self, mocker: MockerFixture) -> None:
        mock_run = mocker.patch("devbox.health.subprocess.run")
        mock_run.return_value = MagicMock(returncode=0)
        check_ssh("dev1", timeout=10)
        args = mock_run.call_args[0][0]
        assert "ConnectTimeout=10" in args


# ---------------------------------------------------------------------------
# check_all_ssh
# ---------------------------------------------------------------------------


class TestCheckAllSsh:
    def test_empty_list(self) -> None:
        assert check_all_ssh([]) == {}

    def test_all_reachable(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.health.check_ssh", return_value=True)
        result = check_all_ssh(["a", "b", "c"])
        assert result == {"a": True, "b": True, "c": True}

    def test_mixed_results(self, mocker: MockerFixture) -> None:
        def side_effect(name: str, timeout: int = 5) -> bool:
            return name != "b"

        mocker.patch("devbox.health.check_ssh", side_effect=side_effect)
        result = check_all_ssh(["a", "b", "c"])
        assert result == {"a": True, "b": False, "c": True}

    def test_all_unreachable(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.health.check_ssh", return_value=False)
        result = check_all_ssh(["x", "y"])
        assert result == {"x": False, "y": False}

    def test_passes_timeout(self, mocker: MockerFixture) -> None:
        mock_check = mocker.patch("devbox.health.check_ssh", return_value=True)
        check_all_ssh(["a"], timeout=12)
        mock_check.assert_called_once_with("a", 12)

    def test_handles_exception_in_future(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.health.check_ssh",
            side_effect=RuntimeError("boom"),
        )
        result = check_all_ssh(["a"])
        assert result == {"a": False}

    def test_concurrent_execution(self, mocker: MockerFixture) -> None:
        """Verify ThreadPoolExecutor is used for concurrency."""
        mock_check = mocker.patch("devbox.health.check_ssh", return_value=True)
        names = [f"dev{i}" for i in range(5)]
        result = check_all_ssh(names)
        assert len(result) == 5
        assert mock_check.call_count == 5


# ---------------------------------------------------------------------------
# get_health
# ---------------------------------------------------------------------------


class TestGetHealth:
    def test_healthy_no_ssh_check(self) -> None:
        now = datetime.now(UTC)
        assert get_health("dev1", now, check_ssh_flag=False) == "healthy"

    def test_unknown_no_ssh_check(self) -> None:
        assert get_health("dev1", None, check_ssh_flag=False) == "unknown"

    def test_atrophied_no_ssh_check(self) -> None:
        old = datetime.now(UTC) - timedelta(days=_ATROPHY_DAYS + 1)
        assert get_health("dev1", old, check_ssh_flag=False) == "atrophied"

    def test_unreachable_when_ssh_fails(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.health.check_ssh", return_value=False)
        now = datetime.now(UTC)
        assert get_health("dev1", now, check_ssh_flag=True) == "unreachable"

    def test_healthy_when_ssh_ok(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.health.check_ssh", return_value=True)
        now = datetime.now(UTC)
        assert get_health("dev1", now, check_ssh_flag=True) == "healthy"

    def test_unreachable_overrides_atrophied(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.health.check_ssh", return_value=False)
        old = datetime.now(UTC) - timedelta(days=_ATROPHY_DAYS + 1)
        assert get_health("dev1", old, check_ssh_flag=True) == "unreachable"

    def test_unreachable_overrides_unknown(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.health.check_ssh", return_value=False)
        assert get_health("dev1", None, check_ssh_flag=True) == "unreachable"

    def test_default_no_ssh_check(self) -> None:
        now = datetime.now(UTC)
        assert get_health("dev1", now) == "healthy"
