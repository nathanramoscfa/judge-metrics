# tests/unit/test_smoke.py
"""Environment smoke test: the package imports and the CLI reports its version."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from judgemetrics import __version__
from judgemetrics.cli import app

pytestmark = pytest.mark.unit

runner = CliRunner()


def test_version_is_set() -> None:
    assert __version__
    assert __version__ != "0.0.0"


def test_cli_version_prints_package_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == __version__


def test_cli_lists_command_groups() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0, result.output
    for group in ("db", "serve", "ingest"):
        assert group in result.output


def test_ingest_list_sources_is_empty_until_step_3() -> None:
    result = runner.invoke(app, ["ingest", "list-sources"])
    assert result.exit_code == 0, result.output
    assert "no sources registered" in result.output


def test_db_group_has_migration_commands() -> None:
    result = runner.invoke(app, ["db", "--help"])
    assert result.exit_code == 0, result.output
    for command in ("upgrade", "downgrade", "current"):
        assert command in result.output
