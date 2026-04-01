# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Robert Gunnar Johnson Jr.

"""GitHub SSH key lifecycle via the gh CLI."""

from __future__ import annotations

import json
import subprocess

from devbox.exceptions import GitHubError


def _run_gh(
    args: list[str], error_prefix: str, timeout: int = 15, stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a gh CLI command, raising GitHubError on failure."""
    cmd = ["gh", *args]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, input=stdin,
        )
    except FileNotFoundError:
        raise GitHubError("gh CLI is not installed — install it with: brew install gh") from None
    except subprocess.TimeoutExpired:
        raise GitHubError(f"{error_prefix}: timed out") from None

    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise GitHubError(f"{error_prefix} (exit code {result.returncode}): {stderr}")

    return result


def _find_existing_key(public_key: str) -> str | None:
    """Check if the public key is already registered on GitHub.

    Returns the key ID if found, None otherwise.
    """
    result = _run_gh(
        ["api", "/user/keys", "--paginate"],
        "Failed to list SSH keys",
    )

    try:
        keys = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise GitHubError(f"Failed to parse GitHub keys response: {exc}") from exc

    # Compare just the key type + data, ignoring the comment suffix
    target_parts = public_key.strip().split()[:2]
    target = " ".join(target_parts)

    for entry in keys:
        existing_parts = entry.get("key", "").strip().split()[:2]
        if " ".join(existing_parts) == target:
            return str(entry["id"])

    return None


def add_ssh_key(title: str, public_key: str, github_account: str) -> str:
    """Upload an SSH public key to GitHub. Returns the key ID as a string.

    If the key already exists, returns the existing key's ID without
    creating a duplicate.

    Raises :exc:`GitHubError` on failure.
    """
    existing_id = _find_existing_key(public_key)
    if existing_id is not None:
        return existing_id

    result = _run_gh(
        ["api", "/user/keys", "--method", "POST",
         "--field", f"title={title}", "--field", f"key={public_key}"],
        "Failed to add SSH key to GitHub",
    )

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise GitHubError(f"Failed to parse GitHub add-key response: {exc}") from exc

    key_id = data.get("id")
    if key_id is None:
        raise GitHubError("GitHub API response missing key ID")

    return str(key_id)


def remove_ssh_key(key_id: str, github_account: str) -> None:
    """Remove an SSH key from GitHub by key ID string.

    Idempotent — does not raise if the key is already gone.
    Raises :exc:`GitHubError` on other failures.
    """
    if not key_id.isdigit():
        raise GitHubError(f"Invalid key ID: {key_id!r} (must be numeric)")

    try:
        _run_gh(
            ["api", "--method", "DELETE", f"/user/keys/{key_id}"],
            "Failed to remove SSH key from GitHub",
        )
    except GitHubError as exc:
        if "404" in str(exc) or "not found" in str(exc).lower():
            return  # already gone — idempotent
        raise
