# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Robert Gunnar Johnson Jr.

"""Health checking for devbox instances."""

from __future__ import annotations

import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

from devbox.naming import DX_PREFIX, validate_name

_ATROPHY_DAYS = 30


def read_heartbeat(name: str) -> datetime | None:
    """Read the heartbeat timestamp for a devbox user."""
    validate_name(name)
    heartbeat_path = Path(f"/Users/{DX_PREFIX}{name}/.devbox_heartbeat")
    if not heartbeat_path.exists():
        return None
    try:
        text = heartbeat_path.read_text(encoding="utf-8").strip()
        return datetime.fromisoformat(text)
    except (OSError, ValueError):
        return None


def health_status(last_seen: datetime | None) -> str:
    """Determine health status from last_seen timestamp.

    Returns ``"healthy"``, ``"atrophied"``, or ``"unknown"``.
    """
    if last_seen is None:
        return "unknown"
    now = datetime.now(UTC)
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=UTC)
    age = now - last_seen
    if age > timedelta(days=_ATROPHY_DAYS):
        return "atrophied"
    return "healthy"


def format_last_seen(last_seen: datetime | None) -> str:
    """Format *last_seen* as a human-readable relative time."""
    if last_seen is None:
        return "never"
    now = datetime.now(UTC)
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=UTC)
    delta = now - last_seen
    if delta.days > 0:
        return f"{delta.days}d ago"
    hours = delta.seconds // 3600
    if hours > 0:
        return f"{hours}h ago"
    minutes = delta.seconds // 60
    if minutes > 0:
        return f"{minutes}m ago"
    return "just now"


def check_ssh(name: str, timeout: int = 5) -> bool:
    """Probe SSH connectivity for a devbox user.

    Runs ``ssh -o ConnectTimeout=<timeout> -o BatchMode=yes
    dx-<name>@localhost echo ok`` and returns ``True`` on success.
    """
    validate_name(name)
    username = f"{DX_PREFIX}{name}"
    try:
        result = subprocess.run(
            [
                "ssh",
                "-o",
                f"ConnectTimeout={timeout}",
                "-o",
                "BatchMode=yes",
                f"{username}@localhost",
                "echo",
                "ok",
            ],
            capture_output=True,
            timeout=timeout + 5,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return result.returncode == 0


def check_all_ssh(names: list[str], timeout: int = 5) -> dict[str, bool]:
    """Probe SSH for multiple devboxes concurrently.

    Returns a mapping of name to reachability boolean.
    """
    results: dict[str, bool] = {}
    if not names:
        return results
    with ThreadPoolExecutor(max_workers=min(len(names), 10)) as pool:
        futures = {pool.submit(check_ssh, n, timeout): n for n in names}
        for future in futures:
            name = futures[future]
            try:
                results[name] = future.result()
            except Exception:
                results[name] = False
    return results


def get_health(
    name: str,
    last_seen: datetime | None,
    check_ssh_flag: bool = False,
) -> str:
    """Return composite health status for a devbox.

    When *check_ssh_flag* is ``True`` and SSH is unreachable the status
    is ``"unreachable"`` regardless of heartbeat age.
    """
    if check_ssh_flag and not check_ssh(name):
        return "unreachable"
    return health_status(last_seen)
