# tests/unit/test_cli_metrics.py
"""``judgemetrics metrics compute|verify`` and ``provenance trace``: argument validation
before any database work.

A malformed ``--subject``, ``--snapshot``, or observation id exits 2 with
a named error before a connection is opened (the URL below points
nowhere); the help text names the commands and the ``compute-metrics``
task and Makefile target invoke ``metrics compute``.
"""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

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


def test_help_lists_provenance_trace() -> None:
    result = CliRunner().invoke(app, ["provenance", "--help"])
    assert result.exit_code == 0
    assert "trace" in result.output
    result = CliRunner().invoke(app, ["provenance", "trace", "--help"])
    assert result.exit_code == 0
    # CI renders Typer's help with ANSI styling; compare the plain text.
    assert "--json" in re.sub(r"\[[0-9;]*m", "", result.output)


def test_trace_rejects_a_malformed_observation_id_before_touching_the_database() -> None:
    result = CliRunner().invoke(app, ["provenance", "trace", "not-an-id"], env=ENV)
    assert result.exit_code == 2, result.output
    assert "UUID" in result.output
    assert "nowhere" not in result.output


def test_compute_metrics_task_and_target_invoke_the_command() -> None:
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert re.search(r'^compute-metrics = "judgemetrics metrics compute"$', pyproject, re.M)
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "compute-metrics:\n\tuv run poe compute-metrics" in makefile
    assert "compute-metrics" in makefile.split(".PHONY:", 1)[1].splitlines()[0]
    assert (Path(REPO_ROOT) / ".gitignore").read_text(encoding="utf-8").count(
        "data/snapshots/"
    ) == 1


# --- Phase 5 Step 5: --source, metrics coverage, the models fit line (issue #40) -------------


@pytest.mark.parametrize(
    "command",
    [
        ["metrics", "compute", "--source", "nowhere"],
        ["metrics", "coverage", "--source", "nowhere"],
        ["validation", "report", "--source", "nowhere", "--check"],
    ],
)
def test_an_unregistered_source_is_refused_before_touching_the_database(
    command: list[str],
) -> None:
    result = CliRunner().invoke(app, command, env=ENV)
    assert result.exit_code == 2, result.output
    assert "unknown source nowhere" in result.output
    assert "cook_sao" in result.output and "synthetic" in result.output


def test_help_lists_coverage_and_the_source_options() -> None:
    plain = re.compile(r"\[[0-9;]*m")
    result = CliRunner().invoke(app, ["metrics", "--help"])
    assert result.exit_code == 0 and "coverage" in result.output
    for command in (["metrics", "compute"], ["metrics", "coverage"], ["validation", "report"]):
        result = CliRunner().invoke(app, [*command, "--help"])
        assert result.exit_code == 0, command
        assert "--source" in plain.sub("", result.output), command


def test_models_fit_prints_fitted_once_as_a_status(monkeypatch: pytest.MonkeyPatch) -> None:
    """Issue #40: the run's count is `new`; `fitted` appears once, as a status."""
    from judgemetrics.metrics.adjustment import catalog

    payload = {
        "snapshot": "a" * 64,
        "fitted": 13,
        "existing": 0,
        "statuses": {"fitted": 10, "unavailable": 3},
        "models": [],
    }
    summary = SimpleNamespace(snapshot="a" * 64, as_dict=lambda: payload)
    monkeypatch.setattr(catalog, "fit_snapshot", lambda *args, **kwargs: summary)
    result = CliRunner().invoke(app, ["models", "fit"], env=ENV)
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert lines[0] == f"snapshot {'a' * 64}"
    assert lines[1] == "new=13 existing=0 status fitted=10 unavailable=3"
    assert result.stdout.count("fitted=") == 1
