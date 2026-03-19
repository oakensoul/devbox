"""GitHub API — SSH key lifecycle (add/remove)."""

from __future__ import annotations

import requests

from devbox.exceptions import GitHubError
from devbox.onepassword import get_secret

_GITHUB_API = "https://api.github.com"
_OP_TOKEN_REF = "op://Development/github-{account}-token/credential"


def _get_token(github_account: str) -> str:
    """Resolve the GitHub PAT from 1Password for the given account."""
    ref = _OP_TOKEN_REF.format(account=github_account)
    return get_secret(ref)


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def add_ssh_key(title: str, public_key: str, github_account: str) -> str:
    """Upload an SSH public key to GitHub. Returns the key ID as a string.

    Raises :exc:`GitHubError` on failure (auth, rate limit, duplicate key).
    """
    token = _get_token(github_account)
    url = f"{_GITHUB_API}/user/keys"

    try:
        response = requests.post(
            url,
            headers=_headers(token),
            json={"title": title, "key": public_key},
            timeout=15,
        )
    except requests.RequestException as exc:
        raise GitHubError(f"GitHub API request failed: {exc}") from exc

    if response.status_code == 422:
        raise GitHubError("SSH key already exists on GitHub (duplicate)")

    if response.status_code == 401:
        raise GitHubError("GitHub authentication failed — check your token")

    if response.status_code == 403:
        raise GitHubError("GitHub API rate limit exceeded or forbidden")

    if response.status_code != 201:
        raise GitHubError(
            f"GitHub API returned unexpected status {response.status_code}"
        )

    data = response.json()
    key_id = data.get("id")
    if key_id is None:
        raise GitHubError("GitHub API response missing key ID")

    return str(key_id)


def remove_ssh_key(key_id: str, github_account: str) -> None:
    """Remove an SSH key from GitHub by key ID string.

    Idempotent — does not raise if the key is already gone (404).
    Raises :exc:`GitHubError` on other failures.
    """
    token = _get_token(github_account)
    url = f"{_GITHUB_API}/user/keys/{key_id}"

    try:
        response = requests.delete(
            url,
            headers=_headers(token),
            timeout=15,
        )
    except requests.RequestException as exc:
        raise GitHubError(f"GitHub API request failed: {exc}") from exc

    if response.status_code == 404:
        return  # already gone — idempotent

    if response.status_code == 401:
        raise GitHubError("GitHub authentication failed — check your token")

    if response.status_code not in (204, 200):
        raise GitHubError(
            f"GitHub API returned unexpected status {response.status_code}"
        )
