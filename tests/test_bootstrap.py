# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Robert Gunnar Johnson Jr.

"""Tests for bootstrap module — homebrew, nvm, pyenv, brew extras, npm/pip globals."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from devbox.bootstrap import (
    _run_checked,
    bootstrap_user,
    install_brew_extras,
    install_claude_code,
    install_homebrew,
    install_npm_globals,
    install_nvm,
    install_pip_globals,
    install_pyenv,
    run_loadout,
    setup_gh_auth,
)
from devbox.exceptions import BootstrapError
from devbox.presets import Preset


def _ok(stdout: str = "", stderr: str = "") -> MagicMock:
    """Return a successful CompletedProcess mock."""
    return MagicMock(returncode=0, stdout=stdout, stderr=stderr)


def _fail(code: int = 1, stderr: str = "boom") -> MagicMock:
    """Return a failed CompletedProcess mock."""
    return MagicMock(returncode=code, stdout="", stderr=stderr)


def _preset(**overrides: object) -> Preset:
    """Build a minimal valid Preset with optional overrides."""
    defaults: dict[str, object] = {
        "name": "test",
        "description": "test preset",
        "provider": "local",
        "github_account": "octocat",
        "node_version": "lts",
        "python_version": "3.12",
        "brew_extras": [],
        "npm_globals": [],
        "pip_globals": [],
    }
    defaults.update(overrides)
    return Preset.model_validate(defaults)


HOME = Path("/Users/dx-test")
USERNAME = "dx-test"


# ---------------------------------------------------------------------------
# _run_checked
# ---------------------------------------------------------------------------


class TestRunChecked:
    def test_success(self, mocker: MockerFixture) -> None:
        mock_run = mocker.patch("devbox.bootstrap.subprocess.run", return_value=_ok())
        result = _run_checked(["echo", "hi"], error_prefix="test", timeout=10)
        assert result.returncode == 0
        mock_run.assert_called_once()

    def test_nonzero_exit(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.bootstrap.subprocess.run", return_value=_fail())
        with pytest.raises(BootstrapError, match="exit code 1"):
            _run_checked(["false"], error_prefix="test", timeout=10)

    def test_nonzero_exit_includes_stderr(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.bootstrap.subprocess.run", return_value=_fail(stderr="details"))
        with pytest.raises(BootstrapError, match="details"):
            _run_checked(["false"], error_prefix="test", timeout=10)

    def test_file_not_found(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.bootstrap.subprocess.run",
            side_effect=FileNotFoundError("no such file"),
        )
        with pytest.raises(BootstrapError, match="command not found"):
            _run_checked(["nope"], error_prefix="test", timeout=10)

    def test_timeout(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.bootstrap.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="x", timeout=10),
        )
        with pytest.raises(BootstrapError, match="timed out"):
            _run_checked(["slow"], error_prefix="test", timeout=10)

    def test_stderr_truncated(self, mocker: MockerFixture) -> None:
        long_err = "x" * 1000
        mocker.patch("devbox.bootstrap.subprocess.run", return_value=_fail(stderr=long_err))
        with pytest.raises(BootstrapError) as exc_info:
            _run_checked(["fail"], error_prefix="test", timeout=10)
        # stderr tail is capped at 500 chars
        assert len(str(exc_info.value)) <= 600


# ---------------------------------------------------------------------------
# install_nvm
# ---------------------------------------------------------------------------


class TestInstallNvm:
    def test_happy_path(self, mocker: MockerFixture) -> None:
        mock_run = mocker.patch("devbox.bootstrap.subprocess.run", return_value=_ok())
        install_nvm(HOME, "lts", USERNAME)
        assert mock_run.call_count == 2

    def test_nvm_script_failure(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.bootstrap.subprocess.run", return_value=_fail())
        with pytest.raises(BootstrapError, match="nvm install"):
            install_nvm(HOME, "lts", USERNAME)

    def test_node_install_failure(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.bootstrap.subprocess.run",
            side_effect=[_ok(), _fail(stderr="node build failed")],
        )
        with pytest.raises(BootstrapError, match="node lts install"):
            install_nvm(HOME, "lts", USERNAME)


# ---------------------------------------------------------------------------
# install_pyenv
# ---------------------------------------------------------------------------


class TestInstallPyenv:
    def test_happy_path(self, mocker: MockerFixture) -> None:
        mock_run = mocker.patch("devbox.bootstrap.subprocess.run", return_value=_ok())
        install_pyenv(HOME, "3.12", USERNAME)
        assert mock_run.call_count == 2

    def test_pyenv_script_failure(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.bootstrap.subprocess.run", return_value=_fail())
        with pytest.raises(BootstrapError, match="pyenv install"):
            install_pyenv(HOME, "3.12", USERNAME)

    def test_python_build_failure(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.bootstrap.subprocess.run",
            side_effect=[_ok(), _fail(stderr="python build failed")],
        )
        with pytest.raises(BootstrapError, match=r"python 3\.12 install"):
            install_pyenv(HOME, "3.12", USERNAME)


# ---------------------------------------------------------------------------
# install_brew_extras
# ---------------------------------------------------------------------------


class TestInstallHomebrew:
    def test_happy_path(self, mocker: MockerFixture) -> None:
        mock_run = mocker.patch("devbox.bootstrap.subprocess.run", return_value=_ok())
        install_homebrew(HOME, USERNAME)
        assert mock_run.call_count == 2
        # First call: git clone
        clone_cmd = mock_run.call_args_list[0][0][0]
        assert clone_cmd[:3] == ["sudo", "-u", USERNAME]
        bash_arg = clone_cmd[-1]
        assert "git clone" in bash_arg
        assert ".homebrew" in bash_arg
        # Second call: brew update
        update_cmd = mock_run.call_args_list[1][0][0]
        assert ".homebrew/bin/brew" in update_cmd[-1]
        assert "update" in update_cmd[-1]

    def test_clone_failure(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.bootstrap.subprocess.run", return_value=_fail())
        with pytest.raises(BootstrapError, match="homebrew install"):
            install_homebrew(HOME, USERNAME)

    def test_update_failure(self, mocker: MockerFixture) -> None:
        mocker.patch(
            "devbox.bootstrap.subprocess.run",
            side_effect=[_ok(), _fail(stderr="update failed")],
        )
        with pytest.raises(BootstrapError, match="homebrew update"):
            install_homebrew(HOME, USERNAME)


class TestInstallBrewExtras:
    def test_happy_path(self, mocker: MockerFixture) -> None:
        mock_run = mocker.patch("devbox.bootstrap.subprocess.run", return_value=_ok())
        install_brew_extras(HOME, ["jq", "ripgrep"], USERNAME)
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[:3] == ["sudo", "-u", USERNAME]
        bash_arg = cmd[-1]
        assert ".homebrew/bin/brew" in bash_arg
        assert "jq" in bash_arg
        assert "ripgrep" in bash_arg

    def test_empty_list_is_noop(self, mocker: MockerFixture) -> None:
        mock_run = mocker.patch("devbox.bootstrap.subprocess.run")
        install_brew_extras(HOME, [], USERNAME)
        mock_run.assert_not_called()

    def test_failure(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.bootstrap.subprocess.run", return_value=_fail())
        with pytest.raises(BootstrapError, match="brew extras"):
            install_brew_extras(HOME, ["bad-pkg"], USERNAME)


# ---------------------------------------------------------------------------
# install_npm_globals
# ---------------------------------------------------------------------------


class TestInstallNpmGlobals:
    def test_happy_path(self, mocker: MockerFixture) -> None:
        mock_run = mocker.patch("devbox.bootstrap.subprocess.run", return_value=_ok())
        install_npm_globals(HOME, ["typescript", "ts-node"], USERNAME)
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[:3] == ["sudo", "-u", USERNAME]

    def test_empty_list_is_noop(self, mocker: MockerFixture) -> None:
        mock_run = mocker.patch("devbox.bootstrap.subprocess.run")
        install_npm_globals(HOME, [], USERNAME)
        mock_run.assert_not_called()

    def test_failure(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.bootstrap.subprocess.run", return_value=_fail())
        with pytest.raises(BootstrapError, match="npm globals"):
            install_npm_globals(HOME, ["bad"], USERNAME)


# ---------------------------------------------------------------------------
# install_pip_globals
# ---------------------------------------------------------------------------


class TestInstallPipGlobals:
    def test_happy_path(self, mocker: MockerFixture) -> None:
        mock_run = mocker.patch("devbox.bootstrap.subprocess.run", return_value=_ok())
        install_pip_globals(HOME, ["black", "ruff"], USERNAME)
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[:3] == ["sudo", "-u", USERNAME]

    def test_empty_list_is_noop(self, mocker: MockerFixture) -> None:
        mock_run = mocker.patch("devbox.bootstrap.subprocess.run")
        install_pip_globals(HOME, [], USERNAME)
        mock_run.assert_not_called()

    def test_failure(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.bootstrap.subprocess.run", return_value=_fail())
        with pytest.raises(BootstrapError, match="pip globals"):
            install_pip_globals(HOME, ["bad"], USERNAME)


# ---------------------------------------------------------------------------
# install_claude_code
# ---------------------------------------------------------------------------


class TestInstallClaudeCode:
    def test_happy_path(self, mocker: MockerFixture) -> None:
        mock_run = mocker.patch("devbox.bootstrap.subprocess.run", return_value=_ok())
        install_claude_code(HOME, USERNAME)
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[:3] == ["sudo", "-u", USERNAME]
        bash_script = cmd[-1]
        assert "claude.ai/install.sh" in bash_script

    def test_failure(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.bootstrap.subprocess.run", return_value=_fail())
        with pytest.raises(BootstrapError, match="claude code"):
            install_claude_code(HOME, USERNAME)


# ---------------------------------------------------------------------------
# setup_gh_auth
# ---------------------------------------------------------------------------


class TestSetupGhAuth:
    def test_happy_path(self, mocker: MockerFixture) -> None:
        mock_run = mocker.patch("devbox.bootstrap.subprocess.run", return_value=_ok())
        setup_gh_auth(HOME, USERNAME)
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert cmd[:3] == ["sudo", "-u", USERNAME]
        bash_script = cmd[-1]
        assert "gh config set git_protocol ssh" in bash_script

    def test_failure(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.bootstrap.subprocess.run", return_value=_fail())
        with pytest.raises(BootstrapError, match="gh config"):
            setup_gh_auth(HOME, USERNAME)


# ---------------------------------------------------------------------------
# bootstrap_user
# ---------------------------------------------------------------------------


class TestBootstrapUser:
    def test_all_steps_succeed(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.bootstrap.subprocess.run", return_value=_ok())
        preset = _preset()
        warnings = bootstrap_user(HOME, preset, USERNAME)
        assert warnings == []

    def test_homebrew_failure_continues(self, mocker: MockerFixture) -> None:
        """homebrew failure should warn but not block nvm/pyenv/brew/npm/pip/claude/gh."""
        # homebrew fails(1), nvm(2) + pyenv(2) + claude(1) + gh(1) = 7
        effects = [_fail(), _ok(), _ok(), _ok(), _ok(), _ok(), _ok()]
        mocker.patch("devbox.bootstrap.subprocess.run", side_effect=effects)
        preset = _preset()
        warnings = bootstrap_user(HOME, preset, USERNAME)
        assert len(warnings) == 1
        assert "homebrew" in warnings[0].lower()

    def test_nvm_failure_continues(self, mocker: MockerFixture) -> None:
        """nvm failure should warn but not block pyenv/brew/npm/pip/claude/gh."""
        # homebrew(2) + nvm fails(1) + pyenv(2) + claude(1) + gh(1) = 8
        effects = [_ok(), _ok(), _fail(), _ok(), _ok(), _ok(), _ok(), _ok()]
        mocker.patch("devbox.bootstrap.subprocess.run", side_effect=effects)
        preset = _preset()
        warnings = bootstrap_user(HOME, preset, USERNAME)
        assert len(warnings) == 1
        assert "nvm" in warnings[0].lower()

    def test_pyenv_failure_continues(self, mocker: MockerFixture) -> None:
        # homebrew(2) + nvm(2) + pyenv fails(1) + claude(1) + gh(1) = 8
        effects = [_ok(), _ok(), _ok(), _ok(), _fail(), _ok(), _ok(), _ok()]
        mocker.patch("devbox.bootstrap.subprocess.run", side_effect=effects)
        preset = _preset()
        warnings = bootstrap_user(HOME, preset, USERNAME)
        assert len(warnings) == 1
        assert "pyenv" in warnings[0].lower()

    def test_brew_failure_continues(self, mocker: MockerFixture) -> None:
        # homebrew(2) + nvm(2) + pyenv(2) + brew fails(1) + claude(1) + gh(1) = 9
        effects = [_ok(), _ok(), _ok(), _ok(), _ok(), _ok(), _fail(), _ok(), _ok()]
        mocker.patch("devbox.bootstrap.subprocess.run", side_effect=effects)
        preset = _preset(brew_extras=["jq"])
        warnings = bootstrap_user(HOME, preset, USERNAME)
        assert len(warnings) == 1
        assert "brew" in warnings[0].lower()

    def test_all_steps_fail(self, mocker: MockerFixture) -> None:
        mocker.patch("devbox.bootstrap.subprocess.run", return_value=_fail())
        preset = _preset(brew_extras=["jq"], npm_globals=["ts"], pip_globals=["black"])
        warnings = bootstrap_user(HOME, preset, USERNAME)
        assert len(warnings) == 8

    def test_empty_optional_lists_skip(self, mocker: MockerFixture) -> None:
        """With empty brew/npm/pip lists, homebrew + nvm + pyenv + claude + gh are called."""
        mock_run = mocker.patch("devbox.bootstrap.subprocess.run", return_value=_ok())
        preset = _preset()
        warnings = bootstrap_user(HOME, preset, USERNAME)
        assert warnings == []
        # homebrew = 2, nvm = 2, pyenv = 2, brew/npm/pip = 0, claude = 1, gh = 1
        assert mock_run.call_count == 8

    def test_npm_failure_still_runs_pip(self, mocker: MockerFixture) -> None:
        # homebrew(2) + nvm(2) + pyenv(2) + npm(1 fail) + pip(1 ok) + claude(1) + gh(1) = 10
        effects = [_ok(), _ok(), _ok(), _ok(), _ok(), _ok(), _fail(), _ok(), _ok(), _ok()]
        mocker.patch("devbox.bootstrap.subprocess.run", side_effect=effects)
        preset = _preset(npm_globals=["ts"], pip_globals=["black"])
        warnings = bootstrap_user(HOME, preset, USERNAME)
        assert len(warnings) == 1
        assert "npm" in warnings[0].lower()

    def test_pip_failure_is_last_warning(self, mocker: MockerFixture) -> None:
        # homebrew(2) + nvm(2) + pyenv(2) + pip(1 fail) + claude(1) + gh(1) = 9
        effects = [_ok(), _ok(), _ok(), _ok(), _ok(), _ok(), _fail(), _ok(), _ok()]
        mocker.patch("devbox.bootstrap.subprocess.run", side_effect=effects)
        preset = _preset(pip_globals=["bad"])
        warnings = bootstrap_user(HOME, preset, USERNAME)
        assert len(warnings) == 1
        assert "pip" in warnings[0].lower()


# ---------------------------------------------------------------------------
# run_loadout — dotfile clone retry logic
# ---------------------------------------------------------------------------


class TestRunLoadout:
    def _preset(self, **overrides: object) -> Preset:
        defaults: dict[str, object] = {
            "ssh_key": "id_ed25519",
            "github_account": "testuser",
            "loadout_orgs": ["personal"],
            "repos": [],
        }
        defaults.update(overrides)
        return _preset(**defaults)

    def test_clone_retries_on_failure(self, mocker: MockerFixture) -> None:
        """Dotfile clones should retry up to 2 times with backoff."""
        mocker.patch("shutil.which", return_value="/usr/local/bin/loadout")
        mocker.patch("devbox.bootstrap.time.sleep")
        # Clone dotfiles: ok, clone dotfiles-private: fail,
        # retry dotfiles-private: ok,
        # write loadout config + git safe.directory + loadout update
        mock_run = mocker.patch(
            "devbox.bootstrap.subprocess.run",
            side_effect=[_ok(), _fail(), _ok(), _ok(), _ok(), _ok()],
        )
        preset = self._preset()
        run_loadout(HOME, preset, USERNAME)
        assert mock_run.call_count == 6

    def test_clone_fails_after_retries(self, mocker: MockerFixture) -> None:
        """Raise BootstrapError after exhausting clone retries (non-connection error)."""
        mocker.patch("shutil.which", return_value="/usr/local/bin/loadout")
        mocker.patch("devbox.bootstrap.time.sleep")
        # Both clones fail with a non-connection error, retries also fail
        mock_run = mocker.patch(  # noqa: F841
            "devbox.bootstrap.subprocess.run",
            return_value=_fail(stderr="permission denied"),
        )
        preset = self._preset()
        with pytest.raises(BootstrapError, match="Failed to clone dotfiles after retries"):
            run_loadout(HOME, preset, USERNAME)

    def test_clone_fails_fast_on_connection_error(self, mocker: MockerFixture) -> None:
        """Fail fast and skip retries on connection errors."""
        mocker.patch("shutil.which", return_value="/usr/local/bin/loadout")
        mock_sleep = mocker.patch("devbox.bootstrap.time.sleep")
        mock_run = mocker.patch(
            "devbox.bootstrap.subprocess.run",
            return_value=_fail(stderr="Connection closed"),
        )
        preset = self._preset()
        with pytest.raises(BootstrapError, match="Failed to clone dotfiles after retries"):
            run_loadout(HOME, preset, USERNAME)
        # Should only attempt the first clone, then bail — no retries
        assert mock_run.call_count == 1
        # No retry backoff sleeps (only the initial clone delay or none)
        for call in mock_sleep.call_args_list:
            assert call.args[0] < 10  # no 30s+ retry backoff

    def test_skips_when_no_loadout_orgs(self, mocker: MockerFixture) -> None:
        """run_loadout is a no-op when loadout_orgs is empty."""
        mock_run = mocker.patch("devbox.bootstrap.subprocess.run")
        preset = self._preset(loadout_orgs=[])
        run_loadout(HOME, preset, USERNAME)
        mock_run.assert_not_called()
