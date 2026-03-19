"""Devbox exception hierarchy."""


class DevboxError(Exception):
    """Base exception for all devbox errors."""


class PresetError(DevboxError):
    """Preset not found, invalid, or malformed."""


class RegistryError(DevboxError):
    """Registry read/write errors, duplicate names, missing entries."""


class ProviderError(DevboxError):
    """Provider-level errors during provision/destroy."""


class OnePasswordError(DevboxError):
    """1Password CLI errors — not installed, locked, bad reference."""


class GitHubError(DevboxError):
    """GitHub API errors — auth, rate limiting, key operations."""


class MacOSUserError(DevboxError):
    """dscl errors — user creation/deletion failures, UID exhaustion."""
