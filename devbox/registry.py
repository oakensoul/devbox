"""Read/write ~/.devbox/registry.json."""

from __future__ import annotations

from pathlib import Path

REGISTRY_PATH = Path.home() / ".devbox" / "registry.json"

# Registry schema:
# {
#   "devboxes": [
#     {
#       "name": "devbox1",
#       "preset": "splash-data",
#       "created": "2025-03-12",
#       "last_seen": "2025-03-12T10:00:00Z",
#       "github_key_id": "12345678"
#     }
#   ]
# }


def load_registry() -> dict:
    """Load the registry from disk. Returns empty structure if missing."""
    raise NotImplementedError


def save_registry(data: dict) -> None:
    """Write the registry back to disk."""
    raise NotImplementedError
