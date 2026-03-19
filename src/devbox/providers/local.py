"""Local macOS provider."""

from __future__ import annotations

from typing import Any

from devbox.providers.base import Provider


class LocalProvider(Provider):
    """Provisions devboxes as local macOS user accounts."""

    def provision(self, name: str, preset: dict[str, Any]) -> None:
        raise NotImplementedError

    def destroy(self, name: str, registry_entry: dict[str, Any]) -> None:
        raise NotImplementedError
