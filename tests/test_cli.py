"""Tests for the Click CLI interface."""

from __future__ import annotations

from typing import Any

import pytest
from click.testing import CliRunner
from pytest_mock import MockerFixture

from devbox.cli import cli
from devbox.exceptions import DevboxError


@pytest.fixture()
def runner() -> CliRunner:
    return CliRunner()


def _sample_entries() -> list[dict[str, Any]]:
    return [
        {
            "name": "web",
            "preset": "python-dev",
            "created": "2025-06-01T10:00:00",
            "last_seen": "2025-06-02T12:00:00",
            "status": "healthy",
        },
        {
            "name": "api",
            "preset": "rust-dev",
            "created": "2025-05-15T08:30:00",
            "last_seen": "2025-06-01T09:00:00",
            "status": "atrophied",
        },
    ]


class TestCliGroup:
    def test_help_text(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Manage disposable SSH-only macOS dev environments" in result.output

    def test_no_args_shows_usage(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, [])
        assert result.exit_code == 2
        assert "Usage" in result.output

    def test_unknown_command(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["bogus"])
        assert result.exit_code != 0


class TestCreateCommand:
    def test_happy_path(
        self, runner: CliRunner, mocker: MockerFixture
    ) -> None:
        mocker.patch(
            "devbox.cli.create_devbox",
            return_value={"status": "ready"},
        )
        mocker.patch("devbox.cli.console")

        result = runner.invoke(cli, ["create", "mybox", "--preset", "py-dev"])

        assert result.exit_code == 0

    def test_calls_core_with_correct_args(
        self, runner: CliRunner, mocker: MockerFixture
    ) -> None:
        mock_create = mocker.patch(
            "devbox.cli.create_devbox",
            return_value={"status": "ready"},
        )
        mocker.patch("devbox.cli.console")

        runner.invoke(cli, ["create", "mybox", "--preset", "py-dev"])

        mock_create.assert_called_once_with("mybox", "py-dev")

    def test_success_output_mentions_name(
        self, runner: CliRunner, mocker: MockerFixture
    ) -> None:
        mocker.patch(
            "devbox.cli.create_devbox",
            return_value={"status": "ready"},
        )
        mock_console = mocker.patch("devbox.cli.console")

        runner.invoke(cli, ["create", "mybox", "--preset", "py-dev"])

        printed = " ".join(str(c) for c in mock_console.print.call_args_list)
        assert "mybox" in printed
        assert "created" in printed

    def test_success_output_shows_ssh_hint(
        self, runner: CliRunner, mocker: MockerFixture
    ) -> None:
        mocker.patch(
            "devbox.cli.create_devbox",
            return_value={"status": "ready"},
        )
        mock_console = mocker.patch("devbox.cli.console")

        runner.invoke(cli, ["create", "mybox", "--preset", "py-dev"])

        printed = " ".join(str(c) for c in mock_console.print.call_args_list)
        assert "ssh dx-mybox@localhost" in printed

    def test_devbox_error_exits_1(
        self, runner: CliRunner, mocker: MockerFixture
    ) -> None:
        mocker.patch(
            "devbox.cli.create_devbox",
            side_effect=DevboxError("boom"),
        )
        mocker.patch("devbox.cli.console")

        result = runner.invoke(cli, ["create", "mybox", "--preset", "py-dev"])

        assert result.exit_code == 1

    def test_devbox_error_prints_message(
        self, runner: CliRunner, mocker: MockerFixture
    ) -> None:
        mocker.patch(
            "devbox.cli.create_devbox",
            side_effect=DevboxError("preset not found"),
        )
        mock_console = mocker.patch("devbox.cli.console")

        runner.invoke(cli, ["create", "mybox", "--preset", "bad"])

        printed = " ".join(str(c) for c in mock_console.print.call_args_list)
        assert "preset not found" in printed

    def test_value_error_exits_1(
        self, runner: CliRunner, mocker: MockerFixture
    ) -> None:
        mocker.patch(
            "devbox.cli.create_devbox",
            side_effect=ValueError("invalid name"),
        )
        mocker.patch("devbox.cli.console")

        result = runner.invoke(cli, ["create", "mybox", "--preset", "py-dev"])

        assert result.exit_code == 1

    def test_missing_preset_flag(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["create", "mybox"])
        assert result.exit_code != 0
        assert "preset" in result.output.lower() or "preset" in (result.stderr or "").lower()


class TestRebuildCommand:
    def test_happy_path(
        self, runner: CliRunner, mocker: MockerFixture
    ) -> None:
        mocker.patch("devbox.cli.rebuild_devbox")
        mocker.patch("devbox.cli.console")

        result = runner.invoke(cli, ["rebuild", "mybox"])

        assert result.exit_code == 0

    def test_calls_core_with_name(
        self, runner: CliRunner, mocker: MockerFixture
    ) -> None:
        mock_rebuild = mocker.patch("devbox.cli.rebuild_devbox")
        mocker.patch("devbox.cli.console")

        runner.invoke(cli, ["rebuild", "mybox"])

        mock_rebuild.assert_called_once_with("mybox")

    def test_success_output_mentions_rebuilt(
        self, runner: CliRunner, mocker: MockerFixture
    ) -> None:
        mocker.patch("devbox.cli.rebuild_devbox")
        mock_console = mocker.patch("devbox.cli.console")

        runner.invoke(cli, ["rebuild", "mybox"])

        printed = " ".join(str(c) for c in mock_console.print.call_args_list)
        assert "rebuilt" in printed
        assert "mybox" in printed

    def test_devbox_error_exits_1(
        self, runner: CliRunner, mocker: MockerFixture
    ) -> None:
        mocker.patch(
            "devbox.cli.rebuild_devbox",
            side_effect=DevboxError("not found"),
        )
        mocker.patch("devbox.cli.console")

        result = runner.invoke(cli, ["rebuild", "mybox"])

        assert result.exit_code == 1

    def test_devbox_error_prints_message(
        self, runner: CliRunner, mocker: MockerFixture
    ) -> None:
        mocker.patch(
            "devbox.cli.rebuild_devbox",
            side_effect=DevboxError("not found"),
        )
        mock_console = mocker.patch("devbox.cli.console")

        runner.invoke(cli, ["rebuild", "mybox"])

        printed = " ".join(str(c) for c in mock_console.print.call_args_list)
        assert "not found" in printed

    def test_value_error_exits_1(
        self, runner: CliRunner, mocker: MockerFixture
    ) -> None:
        mocker.patch(
            "devbox.cli.rebuild_devbox",
            side_effect=ValueError("invalid name"),
        )
        mocker.patch("devbox.cli.console")

        result = runner.invoke(cli, ["rebuild", "mybox"])

        assert result.exit_code == 1


class TestNukeCommand:
    def test_happy_path(
        self, runner: CliRunner, mocker: MockerFixture
    ) -> None:
        mocker.patch("devbox.cli.nuke_devbox", return_value=[])
        mocker.patch("devbox.cli.console")

        result = runner.invoke(cli, ["nuke", "mybox"])

        assert result.exit_code == 0

    def test_calls_core_with_name(
        self, runner: CliRunner, mocker: MockerFixture
    ) -> None:
        mock_nuke = mocker.patch("devbox.cli.nuke_devbox", return_value=[])
        mocker.patch("devbox.cli.console")

        runner.invoke(cli, ["nuke", "mybox"])

        mock_nuke.assert_called_once_with("mybox")

    def test_success_output_mentions_nuked(
        self, runner: CliRunner, mocker: MockerFixture
    ) -> None:
        mocker.patch("devbox.cli.nuke_devbox", return_value=[])
        mock_console = mocker.patch("devbox.cli.console")

        runner.invoke(cli, ["nuke", "mybox"])

        printed = " ".join(str(c) for c in mock_console.print.call_args_list)
        assert "nuked" in printed
        assert "mybox" in printed

    def test_nuke_with_warnings(
        self, runner: CliRunner, mocker: MockerFixture
    ) -> None:
        mocker.patch(
            "devbox.cli.nuke_devbox",
            return_value=["failed to remove SSH key", "leftover volume"],
        )
        mock_console = mocker.patch("devbox.cli.console")

        result = runner.invoke(cli, ["nuke", "mybox"])

        assert result.exit_code == 0
        printed = " ".join(str(c) for c in mock_console.print.call_args_list)
        assert "warnings" in printed
        assert "failed to remove SSH key" in printed
        assert "leftover volume" in printed

    def test_devbox_error_exits_1(
        self, runner: CliRunner, mocker: MockerFixture
    ) -> None:
        mocker.patch(
            "devbox.cli.nuke_devbox",
            side_effect=DevboxError("destroy failed"),
        )
        mocker.patch("devbox.cli.console")

        result = runner.invoke(cli, ["nuke", "mybox"])

        assert result.exit_code == 1

    def test_devbox_error_prints_message(
        self, runner: CliRunner, mocker: MockerFixture
    ) -> None:
        mocker.patch(
            "devbox.cli.nuke_devbox",
            side_effect=DevboxError("destroy failed"),
        )
        mock_console = mocker.patch("devbox.cli.console")

        runner.invoke(cli, ["nuke", "mybox"])

        printed = " ".join(str(c) for c in mock_console.print.call_args_list)
        assert "destroy failed" in printed

    def test_value_error_exits_1(
        self, runner: CliRunner, mocker: MockerFixture
    ) -> None:
        mocker.patch(
            "devbox.cli.nuke_devbox",
            side_effect=ValueError("invalid name"),
        )
        mocker.patch("devbox.cli.console")

        result = runner.invoke(cli, ["nuke", "mybox"])

        assert result.exit_code == 1


class TestListCommand:
    def test_empty_list_output(
        self, runner: CliRunner, mocker: MockerFixture
    ) -> None:
        mocker.patch("devbox.cli.list_devboxes", return_value=[])
        mock_console = mocker.patch("devbox.cli.console")

        result = runner.invoke(cli, ["list"])

        assert result.exit_code == 0
        printed = " ".join(str(c) for c in mock_console.print.call_args_list)
        assert "No devboxes registered" in printed

    def test_table_output_contains_entry_names(
        self, runner: CliRunner, mocker: MockerFixture
    ) -> None:
        mocker.patch("devbox.cli.list_devboxes", return_value=_sample_entries())
        mocker.patch("devbox.cli.console")

        result = runner.invoke(cli, ["list"])

        assert result.exit_code == 0
        # Table is printed to a local Console(stdout), so check result.output
        assert "web" in result.output
        assert "api" in result.output

    def test_table_output_contains_presets(
        self, runner: CliRunner, mocker: MockerFixture
    ) -> None:
        mocker.patch("devbox.cli.list_devboxes", return_value=_sample_entries())
        mocker.patch("devbox.cli.console")

        result = runner.invoke(cli, ["list"])

        assert "python-dev" in result.output
        assert "rust-dev" in result.output

    def test_table_output_contains_dates(
        self, runner: CliRunner, mocker: MockerFixture
    ) -> None:
        mocker.patch("devbox.cli.list_devboxes", return_value=_sample_entries())
        mocker.patch("devbox.cli.console")

        result = runner.invoke(cli, ["list"])

        assert "2025-06-01" in result.output

    def test_table_output_contains_status(
        self, runner: CliRunner, mocker: MockerFixture
    ) -> None:
        mocker.patch("devbox.cli.list_devboxes", return_value=_sample_entries())
        mocker.patch("devbox.cli.console")

        result = runner.invoke(cli, ["list"])

        assert "healthy" in result.output

    def test_devbox_error_exits_1(
        self, runner: CliRunner, mocker: MockerFixture
    ) -> None:
        mocker.patch(
            "devbox.cli.list_devboxes",
            side_effect=DevboxError("registry corrupt"),
        )
        mocker.patch("devbox.cli.console")

        result = runner.invoke(cli, ["list"])

        assert result.exit_code == 1

    def test_devbox_error_prints_message(
        self, runner: CliRunner, mocker: MockerFixture
    ) -> None:
        mocker.patch(
            "devbox.cli.list_devboxes",
            side_effect=DevboxError("registry corrupt"),
        )
        mock_console = mocker.patch("devbox.cli.console")

        runner.invoke(cli, ["list"])

        printed = " ".join(str(c) for c in mock_console.print.call_args_list)
        assert "registry corrupt" in printed

    def test_value_error_exits_1(
        self, runner: CliRunner, mocker: MockerFixture
    ) -> None:
        mocker.patch(
            "devbox.cli.list_devboxes",
            side_effect=ValueError("bad registry"),
        )
        mocker.patch("devbox.cli.console")

        result = runner.invoke(cli, ["list"])

        assert result.exit_code == 1
