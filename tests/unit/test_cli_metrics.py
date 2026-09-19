# tests/unit/test_cli_metrics.py
"""``judgemetrics metrics compute|verify``: argument validation before any database work.

A malformed ``--subject`` or ``--snapshot`` exits 2 with a named error
before a connection is opened (the URL below points nowhere); the help
text names both commands and the ``compute-metrics`` task and Makefile
target invoke ``metrics compute``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from judgemetrics.cli import app
from judgemetrics.config import REPO_ROOT

pytestmark = pytest.mark.unit

ENV = {
    "JUDGEMETRICS_ENV": "test",
    "JUDGEMETRICS_DATABASE_URL": "postgresql+psycopg://nobody@localhost:1/nowhere",
    "JUDGEMETRICS_LOG_FORMAT": "json",
}


def test_help_lists_compute_and_verify() -> None:
    result = CliRunner().invoke(app, ["metrics", "--help"])
    assert result.exit_code == 0
    assert "compute" in result.output and "verify" in result.output


def test_compute_rejects_a_malformed_subject_before_touching_the_database() -> None:
    result = CliRunner().invoke(app, ["metrics", "compute", "--subject", "person:x"], env=ENV)
    assert result.exit_code == 2, result.output
    assert "judge:<uuid> or court:<uuid>" in result.output


def test_verify_rejects_a_malformed_snapshot_id_before_touching_the_database() -> None:
    result = CliRunner().invoke(app, ["metrics", "verify", "--snapshot", "../etc"], env=ENV)
    assert result.exit_code == 2, result.output
    assert "64-character" in result.output


def test_compute_metrics_task_and_target_invoke_the_command() -> None:
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r'^compute-metrics = "judgemetrics metrics compute"$', pyproject, re.M)
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "compute-metrics:\n\tuv run poe compute-metrics" in makefile
    assert "compute-metrics" in makefile.split(".PHONY:", 1)[1].splitlines()[0]
    assert (Path(REPO_ROOT) / ".gitignore").read_text(encoding="utf-8").count(
        "data/snapshots/"
    ) == 1
