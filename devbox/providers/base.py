"""Abstract provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod


class Provider(ABC):
    """Base class for devbox providers."""

    @abstractmethod
    def provision(self, name: str, preset: dict) -> None:
        """Provision a new devbox environment."""

    @abstractmethod
    def destroy(self, name: str) -> None:
        """Destroy an existing devbox environment."""
