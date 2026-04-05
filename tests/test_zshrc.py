# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Robert Gunnar Johnson Jr.

"""Tests for zshrc generation and heartbeat hook management."""

from __future__ import annotations

import os
from pathlib import Path

from pytest_mock import MockerFixture

from devbox.zshrc import (
    ENV_SOURCE_LINE,
    HEARTBEAT_HOOK,
    LOADOUT_NOTICE,
    LOGIN_NOTICE,
    generate_zshrc,
    is_hook_installed,
    write_zshrc,
)


class TestConstants:
    def test_heartbeat_hook_contains_date_command(self) -> None:
        assert "date -u" in HEARTBEAT_HOOK

    def test_heartbeat_hook_contains_marker(self) -> None:
        assert "# devbox heartbeat" in HEARTBEAT_HOOK

    def test_heartbeat_hook_contains_chmod(self) -> None:
        assert "chmod 644" in HEARTBEAT_HOOK

    def test_heartbeat_hook_writes_to_file(self) -> None:
        assert ".devbox_heartbeat" in HEARTBEAT_HOOK

    def test_env_source_line_contains_marker(self) -> None:
        assert "# devbox environment" in ENV_SOURCE_LINE

    def test_env_source_line_sources_devbox_env(self) -> None:
        assert ".devbox-env" in ENV_SOURCE_LINE

    def test_env_source_line_checks_file_exists(self) -> None:
        assert "[ -f ~/.devbox-env ]" in ENV_SOURCE_LINE


class TestLoginNotice:
    def test_login_notice_is_empty(self) -> None:
        assert LOGIN_NOTICE == ""

    def test_loadout_notice_alias(self) -> None:
        assert LOADOUT_NOTICE is LOGIN_NOTICE


class TestGenerateZshrc:
    def test_includes_name(self) -> None:
        content = generate_zshrc("my-dev")
        assert "my-dev" in content

    def test_includes_heartbeat_hook(self) -> None:
        content = generate_zshrc("test-box")
        assert HEARTBEAT_HOOK in content

    def test_includes_env_source_line(self) -> None:
        content = generate_zshrc("test-box")
        assert ENV_SOURCE_LINE in content

    def test_ends_with_newline(self) -> None:
        content = generate_zshrc("test-box")
        assert content.endswith("\n")

    def test_env_before_heartbeat(self) -> None:
        content = generate_zshrc("test-box")
        env_pos = content.index("# devbox environment")
        heartbeat_pos = content.index("# devbox heartbeat")
        assert env_pos < heartbeat_pos

    def test_different_names_produce_different_output(self) -> None:
        a = generate_zshrc("alpha")
        b = generate_zshrc("beta")
        assert a != b


class TestWriteZshrc:
    def test_creates_zshrc_file(self, tmp_path: Path, mocker: MockerFixture) -> None:
        mocker.patch("devbox.zshrc.chown_path")
        write_zshrc(tmp_path, "my-dev", "dx-my-dev")
        assert (tmp_path / ".zshrc.local").exists()

    def test_file_contains_generated_content(self, tmp_path: Path, mocker: MockerFixture) -> None:
        mocker.patch("devbox.zshrc.chown_path")
        write_zshrc(tmp_path, "my-dev", "dx-my-dev")
        content = (tmp_path / ".zshrc.local").read_text(encoding="utf-8")
        assert content == generate_zshrc("my-dev")

    def test_file_permissions_are_0644(self, tmp_path: Path, mocker: MockerFixture) -> None:
        mocker.patch("devbox.zshrc.chown_path")
        write_zshrc(tmp_path, "my-dev", "dx-my-dev")
        mode = os.stat(tmp_path / ".zshrc.local").st_mode & 0o777
        assert mode == 0o644

    def test_creates_zshenv_with_homebrew_env(self, tmp_path: Path, mocker: MockerFixture) -> None:
        mocker.patch("devbox.zshrc.chown_path")
        write_zshrc(tmp_path, "my-dev", "dx-my-dev")
        zshenv = (tmp_path / ".zshenv").read_text(encoding="utf-8")
        assert "HOMEBREW_PREFIX" in zshenv
        assert "$HOME/.homebrew" in zshenv
        assert ".homebrew/bin" in zshenv
        assert ".homebrew/sbin" in zshenv
        assert ".homebrew/share/zsh/site-functions" in zshenv
        assert "(-/N)" in zshenv
        assert "ssh-agent" in zshenv
        assert "ssh-add" in zshenv

    def test_zshenv_does_not_contain_compinit(self, tmp_path: Path, mocker: MockerFixture) -> None:
        mocker.patch("devbox.zshrc.chown_path")
        write_zshrc(tmp_path, "my-dev", "dx-my-dev")
        zshenv = (tmp_path / ".zshenv").read_text(encoding="utf-8")
        assert "compinit" not in zshenv

    def test_zshenv_permissions_are_0644(self, tmp_path: Path, mocker: MockerFixture) -> None:
        mocker.patch("devbox.zshrc.chown_path")
        write_zshrc(tmp_path, "my-dev", "dx-my-dev")
        mode = os.stat(tmp_path / ".zshenv").st_mode & 0o777
        assert mode == 0o644

    def test_chown_called_with_correct_args(self, tmp_path: Path, mocker: MockerFixture) -> None:
        mock_chown = mocker.patch("devbox.zshrc.chown_path")
        write_zshrc(tmp_path, "my-dev", "dx-my-dev")
        calls = [str(c) for c in mock_chown.call_args_list]
        assert any(".zshrc.local" in c and "dx-my-dev" in c for c in calls)

    def test_overwrites_existing_zshrc(self, tmp_path: Path, mocker: MockerFixture) -> None:
        mocker.patch("devbox.zshrc.chown_path")
        (tmp_path / ".zshrc.local").write_text("old content", encoding="utf-8")
        write_zshrc(tmp_path, "my-dev", "dx-my-dev")
        content = (tmp_path / ".zshrc.local").read_text(encoding="utf-8")
        assert "old content" not in content
        assert "my-dev" in content


class TestIsHookInstalled:
    def test_returns_false_when_no_zshrc(self, tmp_path: Path) -> None:
        assert is_hook_installed(tmp_path) is False

    def test_returns_false_when_zshrc_empty(self, tmp_path: Path) -> None:
        (tmp_path / ".zshrc.local").write_text("", encoding="utf-8")
        assert is_hook_installed(tmp_path) is False

    def test_returns_false_when_no_hook(self, tmp_path: Path) -> None:
        (tmp_path / ".zshrc.local").write_text("# some other config\n", encoding="utf-8")
        assert is_hook_installed(tmp_path) is False

    def test_returns_true_when_hook_present(self, tmp_path: Path) -> None:
        (tmp_path / ".zshrc.local").write_text(generate_zshrc("test-box"), encoding="utf-8")
        assert is_hook_installed(tmp_path) is True

    def test_returns_true_when_hook_among_other_content(self, tmp_path: Path) -> None:
        content = "# custom stuff\n" + HEARTBEAT_HOOK + "\n# more stuff\n"
        (tmp_path / ".zshrc.local").write_text(content, encoding="utf-8")
        assert is_hook_installed(tmp_path) is True

    def test_idempotent_after_write(self, tmp_path: Path, mocker: MockerFixture) -> None:
        mocker.patch("devbox.zshrc.chown_path")
        write_zshrc(tmp_path, "my-dev", "dx-my-dev")
        assert is_hook_installed(tmp_path) is True
