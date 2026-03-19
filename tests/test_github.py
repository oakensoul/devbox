# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Robert Gunnar Johnson Jr.

"""Tests for the GitHub API SSH key lifecycle."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from devbox.exceptions import GitHubError
from devbox.github import add_ssh_key, remove_ssh_key


class TestAddSSHKey:
    def test_returns_key_id(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.github._get_token", return_value="ghp_test")
        mock_post = mocker.patch("devbox.github.requests.post")
        mock_post.return_value = MagicMock(
            status_code=201,
            json=MagicMock(return_value={"id": 12345, "key": "ssh-ed25519 AAAA"}),
        )

        result = add_ssh_key("devbox-dev1", "ssh-ed25519 AAAA", "octocat")

        assert result == "12345"

    def test_sends_correct_request(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.github._get_token", return_value="ghp_test")
        mock_post = mocker.patch("devbox.github.requests.post")
        mock_post.return_value = MagicMock(
            status_code=201,
            json=MagicMock(return_value={"id": 1}),
        )

        add_ssh_key("devbox-dev1", "ssh-ed25519 AAAA", "octocat")

        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args[1]
        assert call_kwargs["json"] == {"title": "devbox-dev1", "key": "ssh-ed25519 AAAA"}
        assert "Bearer ghp_test" in call_kwargs["headers"]["Authorization"]

    def test_duplicate_key_raises(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.github._get_token", return_value="ghp_test")
        mock_post = mocker.patch("devbox.github.requests.post")
        mock_post.return_value = MagicMock(status_code=422)

        with pytest.raises(GitHubError, match="duplicate"):
            add_ssh_key("devbox-dev1", "ssh-ed25519 AAAA", "octocat")

    def test_auth_failure_raises(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.github._get_token", return_value="bad_token")
        mock_post = mocker.patch("devbox.github.requests.post")
        mock_post.return_value = MagicMock(status_code=401)

        with pytest.raises(GitHubError, match="authentication failed"):
            add_ssh_key("devbox-dev1", "ssh-ed25519 AAAA", "octocat")

    def test_rate_limit_raises(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.github._get_token", return_value="ghp_test")
        mock_post = mocker.patch("devbox.github.requests.post")
        mock_post.return_value = MagicMock(status_code=403)

        with pytest.raises(GitHubError, match="rate limit"):
            add_ssh_key("devbox-dev1", "ssh-ed25519 AAAA", "octocat")

    def test_unexpected_status_raises(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.github._get_token", return_value="ghp_test")
        mock_post = mocker.patch("devbox.github.requests.post")
        mock_post.return_value = MagicMock(status_code=500)

        with pytest.raises(GitHubError, match="unexpected status 500"):
            add_ssh_key("devbox-dev1", "ssh-ed25519 AAAA", "octocat")

    def test_network_error_raises(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.github._get_token", return_value="ghp_test")
        import requests

        mocker.patch(
            "devbox.github.requests.post",
            side_effect=requests.ConnectionError("fail"),
        )

        with pytest.raises(GitHubError, match="request failed"):
            add_ssh_key("devbox-dev1", "ssh-ed25519 AAAA", "octocat")

    def test_missing_id_in_response_raises(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.github._get_token", return_value="ghp_test")
        mock_post = mocker.patch("devbox.github.requests.post")
        mock_post.return_value = MagicMock(
            status_code=201,
            json=MagicMock(return_value={"key": "ssh-ed25519 AAAA"}),
        )

        with pytest.raises(GitHubError, match="missing key ID"):
            add_ssh_key("devbox-dev1", "ssh-ed25519 AAAA", "octocat")


class TestRemoveSSHKey:
    def test_removes_key(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.github._get_token", return_value="ghp_test")
        mock_delete = mocker.patch("devbox.github.requests.delete")
        mock_delete.return_value = MagicMock(status_code=204)

        remove_ssh_key("12345", "octocat")

        mock_delete.assert_called_once()
        assert "12345" in mock_delete.call_args[0][0]

    def test_idempotent_on_404(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.github._get_token", return_value="ghp_test")
        mock_delete = mocker.patch("devbox.github.requests.delete")
        mock_delete.return_value = MagicMock(status_code=404)

        # Should not raise
        remove_ssh_key("99999", "octocat")

    def test_auth_failure_raises(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.github._get_token", return_value="bad_token")
        mock_delete = mocker.patch("devbox.github.requests.delete")
        mock_delete.return_value = MagicMock(status_code=401)

        with pytest.raises(GitHubError, match="authentication failed"):
            remove_ssh_key("12345", "octocat")

    def test_unexpected_status_raises(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.github._get_token", return_value="ghp_test")
        mock_delete = mocker.patch("devbox.github.requests.delete")
        mock_delete.return_value = MagicMock(status_code=500)

        with pytest.raises(GitHubError, match="unexpected status 500"):
            remove_ssh_key("12345", "octocat")

    def test_network_error_raises(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.github._get_token", return_value="ghp_test")
        import requests

        mocker.patch(
            "devbox.github.requests.delete",
            side_effect=requests.ConnectionError("fail"),
        )

        with pytest.raises(GitHubError, match="request failed"):
            remove_ssh_key("12345", "octocat")

    def test_invalid_key_id_raises(self) -> None:
        with pytest.raises(GitHubError, match="Invalid key ID"):
            remove_ssh_key("not-a-number", "octocat")

    def test_path_traversal_key_id_raises(self) -> None:
        with pytest.raises(GitHubError, match="Invalid key ID"):
            remove_ssh_key("123/../../orgs", "octocat")

    def test_rate_limit_raises(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.github._get_token", return_value="ghp_test")
        mock_delete = mocker.patch("devbox.github.requests.delete")
        mock_delete.return_value = MagicMock(status_code=403)

        with pytest.raises(GitHubError, match="rate limit"):
            remove_ssh_key("12345", "octocat")
