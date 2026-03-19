"""Tests for devbox name validation."""

from __future__ import annotations

import pytest

from devbox.naming import validate_name


class TestValidNames:
    """validate_name returns the name unchanged for valid kebab-case names."""

    @pytest.mark.parametrize(
        "name",
        [
            "splash-work",
            "f1-experiment",
            "dev1",
            "a",
            "my-long-devbox-name",
            "abc",
            "123",
            "a1b2-c3d4",
            "x-y-z",
        ],
    )
    def test_valid_name_is_returned(self, name: str) -> None:
        assert validate_name(name) == name


class TestInvalidNames:
    """validate_name raises ValueError for every invalid input."""

    @pytest.mark.parametrize(
        "name",
        [
            "Splash",          # uppercase letter
            "splash_work",     # underscore
            "-bad",            # leading dash
            "bad-",            # trailing dash
            "splash--work",    # consecutive dashes
            "",                # empty string
            "has spaces",      # space
            "special!chars",   # exclamation mark
            "ALLCAPS",         # all uppercase
            "Mixed-Case",      # mixed case
            "-",               # lone dash
            "--",              # double dash only
            "a-",              # trailing dash, short name
            "-a",              # leading dash, short name
            "a--b",            # consecutive dashes in middle
            "hello world",     # space in middle
            "foo@bar",         # at-sign
            "foo.bar",         # dot
            "foo/bar",         # slash
        ],
    )
    def test_invalid_name_raises_value_error(self, name: str) -> None:
        with pytest.raises(ValueError):
            validate_name(name)

    def test_empty_string_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            validate_name("")

    def test_error_message_contains_the_name(self) -> None:
        with pytest.raises(ValueError, match="Splash"):
            validate_name("Splash")

    def test_error_message_is_descriptive(self) -> None:
        with pytest.raises(ValueError, match="kebab-case"):
            validate_name("bad_name")
