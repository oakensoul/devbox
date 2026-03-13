"""Local macOS provider."""

from __future__ import annotations

from devbox.providers.base import Provider


class LocalProvider(Provider):
    """Provisions devboxes as local macOS user accounts."""

    def provision(self, name: str, preset: dict) -> None:
        raise NotImplementedError

    def destroy(self, name: str) -> None:
        raise NotImplementedError
