"""Tests for the devbox exception hierarchy."""

import pytest

from devbox.exceptions import (
    DevboxError,
    GitHubError,
    MacOSUserError,
    OnePasswordError,
    PresetError,
    ProviderError,
    RegistryError,
)

ALL_SUBCLASSES = [
    PresetError,
    RegistryError,
    ProviderError,
    OnePasswordError,
    GitHubError,
    MacOSUserError,
]


class TestDevboxError:
    def test_is_subclass_of_exception(self) -> None:
        assert issubclass(DevboxError, Exception)

    def test_can_be_raised_and_caught(self) -> None:
        with pytest.raises(DevboxError):
            raise DevboxError("something went wrong")

    def test_carries_message(self) -> None:
        msg = "base error message"
        exc = DevboxError(msg)
        assert str(exc) == msg


class TestSubclasses:
    @pytest.mark.parametrize("exc_class", ALL_SUBCLASSES)
    def test_is_subclass_of_devbox_error(self, exc_class: type[DevboxError]) -> None:
        assert issubclass(exc_class, DevboxError)

    @pytest.mark.parametrize("exc_class", ALL_SUBCLASSES)
    def test_is_subclass_of_exception(self, exc_class: type[DevboxError]) -> None:
        assert issubclass(exc_class, Exception)

    @pytest.mark.parametrize("exc_class", ALL_SUBCLASSES)
    def test_can_be_raised_and_caught_as_devbox_error(
        self, exc_class: type[DevboxError]
    ) -> None:
        with pytest.raises(DevboxError):
            raise exc_class("error from subclass")

    @pytest.mark.parametrize("exc_class", ALL_SUBCLASSES)
    def test_carries_message(self, exc_class: type[DevboxError]) -> None:
        msg = f"{exc_class.__name__} message"
        exc = exc_class(msg)
        assert str(exc) == msg

    @pytest.mark.parametrize("exc_class", ALL_SUBCLASSES)
    def test_catching_devbox_error_catches_subclass(
        self, exc_class: type[DevboxError]
    ) -> None:
        caught: DevboxError | None = None
        try:
            raise exc_class("caught via base")
        except DevboxError as e:
            caught = e
        assert caught is not None
        assert isinstance(caught, exc_class)
