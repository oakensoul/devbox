# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Robert Gunnar Johnson Jr.

"""Abstract provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Provider(ABC):
    """Base class for devbox providers."""

    @abstractmethod
    def provision(self, name: str, preset: dict[str, Any]) -> dict[str, Any]:
        """Provision a new devbox environment."""

    @abstractmethod
    def destroy(self, name: str, registry_entry: dict[str, Any]) -> None:
        """Destroy an existing devbox environment."""
