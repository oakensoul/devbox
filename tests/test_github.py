# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Robert Gunnar Johnson Jr.

"""Tests for the GitHub API SSH key lifecycle."""

from __future__ import annotations

import json
import subprocess

import pytest
from pytest_mock import MockerFixture

from devbox.exceptions import GitHubError
from devbox.github import add_ssh_key, remove_ssh_key


def _gh_result(stdout: str = "", stderr: str = "", returncode: int = 0):
    """Build a fake subprocess.CompletedProcess for _run_gh."""
    return subprocess.CompletedProcess(
        args=["gh"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


class TestAddSSHKey:
    def test_returns_key_id_new_key(self, mocker: MockerFixture) -> None:
        # First call: list keys (empty), second call: POST new key
        mocker.patch(
            "devbox.github._run_gh",
            side_effect=[
                _gh_result(stdout="[]"),  # _find_existing_key
                _gh_result(stdout=json.dumps({"id": 12345, "key": "ssh-ed25519 AAAA"})),
            ],
        )

        result = add_ssh_key("devbox-dev1", "ssh-ed25519 AAAA", "octocat")

        assert result == "12345"

    def test_returns_existing_key_id_on_duplicate(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.github._run_gh",
            return_value=_gh_result(stdout=json.dumps([{"id": 999, "key": "ssh-ed25519 AAAA"}])),
        )

        result = add_ssh_key("devbox-dev1", "ssh-ed25519 AAAA", "octocat")

        assert result == "999"

    def test_sends_correct_gh_api_args(self, mocker: MockerFixture) -> None:
        mock_run = mocker.patch(
            "devbox.github._run_gh",
            side_effect=[
                _gh_result(stdout="[]"),
                _gh_result(stdout=json.dumps({"id": 1})),
            ],
        )

        add_ssh_key("devbox-dev1", "ssh-ed25519 AAAA", "octocat")

        # Second call is the POST
        post_call = mock_run.call_args_list[1]
        args = post_call[0][0]
        assert "POST" in args
        assert "/user/keys" in args
        assert "title=devbox-dev1" in args
        assert "key=ssh-ed25519 AAAA" in args

    def test_gh_cli_not_installed_raises(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.github._run_gh",
            side_effect=GitHubError("gh CLI is not installed"),
        )

        with pytest.raises(GitHubError, match="gh CLI is not installed"):
            add_ssh_key("devbox-dev1", "ssh-ed25519 AAAA", "octocat")

    def test_gh_cli_error_raises(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.github._run_gh",
            side_effect=GitHubError("Failed to list SSH keys (exit code 1): some error"),
        )

        with pytest.raises(GitHubError, match="Failed to list SSH keys"):
            add_ssh_key("devbox-dev1", "ssh-ed25519 AAAA", "octocat")

    def test_missing_id_in_response_raises(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.github._run_gh",
            side_effect=[
                _gh_result(stdout="[]"),
                _gh_result(stdout=json.dumps({"key": "ssh-ed25519 AAAA"})),
            ],
        )

        with pytest.raises(GitHubError, match="missing key ID"):
            add_ssh_key("devbox-dev1", "ssh-ed25519 AAAA", "octocat")

    def test_malformed_json_response_raises(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.github._run_gh",
            side_effect=[
                _gh_result(stdout="[]"),
                _gh_result(stdout="not json"),
            ],
        )

        with pytest.raises(GitHubError, match="Failed to parse"):
            add_ssh_key("devbox-dev1", "ssh-ed25519 AAAA", "octocat")

    def test_timeout_raises(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.github._run_gh",
            side_effect=GitHubError("Failed to list SSH keys: timed out"),
        )

        with pytest.raises(GitHubError, match="timed out"):
            add_ssh_key("devbox-dev1", "ssh-ed25519 AAAA", "octocat")


class TestRemoveSSHKey:
    def test_removes_key(self, mocker: MockerFixture) -> None:
        mock_run = mocker.patch(
            "devbox.github._run_gh",
            return_value=_gh_result(),
        )

        remove_ssh_key("12345", "octocat")

        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "DELETE" in args
        assert "/user/keys/12345" in args

    def test_idempotent_on_404(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.github._run_gh",
            side_effect=GitHubError("Failed (exit code 1): 404 not found"),
        )

        # Should not raise
        remove_ssh_key("99999", "octocat")

    def test_non_404_error_raises(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.github._run_gh",
            side_effect=GitHubError("Failed (exit code 1): 500 server error"),
        )

        with pytest.raises(GitHubError, match="500 server error"):
            remove_ssh_key("12345", "octocat")

    def test_invalid_key_id_raises(self) -> None:
        with pytest.raises(GitHubError, match="Invalid key ID"):
            remove_ssh_key("not-a-number", "octocat")

    def test_path_traversal_key_id_raises(self) -> None:
        with pytest.raises(GitHubError, match="Invalid key ID"):
            remove_ssh_key("123/../../orgs", "octocat")

    def test_timeout_raises(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.github._run_gh",
            side_effect=GitHubError("Failed to remove SSH key: timed out"),
        )

        with pytest.raises(GitHubError, match="timed out"):
            remove_ssh_key("12345", "octocat")
