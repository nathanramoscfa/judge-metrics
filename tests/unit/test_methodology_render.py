# tests/unit/test_methodology_render.py
"""The committed docs/METHODOLOGY.md equals the registry render (the docs/openapi.json pattern).

The document wraps at 80 columns, starts with its path comment, carries
one section per registry metric, states the index-event, exposure, and
censoring semantics, and lists the brief's eight statistical warnings
verbatim under "Known limitations"; ``judgemetrics methodology render
--check`` exits 0 against the committed file and 1 against a stale one.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET  # noqa: S405 - the brief is a repository file
from pathlib import Path

import pytest
from typer.testing import CliRunner

from judgemetrics.cli import app as cli
from judgemetrics.config import REPO_ROOT
from judgemetrics.metrics.methodology import (
    PATH_COMMENT,
    WIDTH,
    check_methodology,
    render_methodology,
    resolve_output,
)
from judgemetrics.metrics.registry import load_registry

pytestmark = pytest.mark.unit

COMMITTED = REPO_ROOT / "docs" / "METHODOLOGY.md"
BRIEF = REPO_ROOT / "docs" / "brief" / "judgemetrics-master-project-specification.xml"


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _section(document: str, heading: str) -> str:
    start = document.index(f"\n## {heading}\n")
    rest = document[start + 1 :]
    end = rest.find("\n## ", 1)
    return rest if end == -1 else rest[:end]


def test_committed_document_equals_the_render() -> None:
    rendered = render_methodology()
    assert rendered.endswith("\n") and not rendered.endswith("\n\n")
    assert "\r" not in rendered
    assert COMMITTED.read_bytes().decode("utf-8") == rendered, (
        "docs/METHODOLOGY.md is stale: run `uv run judgemetrics methodology render`"
    )
    assert check_methodology(COMMITTED) == []


def test_document_shape_and_width() -> None:
    document = render_methodology()
    lines = document.splitlines()
    assert lines[0] == PATH_COMMENT
    assert all(len(line) <= WIDTH for line in lines), [line for line in lines if len(line) > WIDTH]
    for heading in (
        "## How to read a number",
        "## Index events, exposure, and censoring",
        "## Attribution",
        "## Metrics",
        "## Suppression",
        "## Known limitations",
        "## Methodology changelog",
    ):
        assert f"\n{heading}\n" in document, heading
    registry = load_registry()
    assert f"Registry version {registry.version}; methodology version 0.1" in document
    metrics = _section(document, "Metrics")
    for metric in registry.metrics.values():
        assert f"\n### {metric.name}\n" in metrics, metric.slug
        assert f"- Slug: `{metric.slug}` (version {metric.version})." in metrics, metric.slug
    for term in ("Numerator", "Denominator", "Date range", "Coverage", "Sample size"):
        assert f"**{term}**" in _section(document, "How to read a number")
    semantics = _normalize(_section(document, "Index events, exposure, and censoring"))
    for phrase in (
        "exposure start, exposure start + w days]",
        "sentence_at + incarceration_days",
        "strictly before that instant",
        "1 - S(w)",
        "Greenwood",
        "never a zero",
    ):
        assert phrase in semantics, phrase
    assert "- 0.1 - first registry" in _section(document, "Methodology changelog")


def test_known_limitations_are_the_briefs_warnings_verbatim() -> None:
    root = ET.parse(BRIEF).getroot()  # noqa: S314 - repository file
    node = root.find(".//important_statistical_warnings")
    assert node is not None
    warnings = [_normalize(w.text or "") for w in node.findall("warning")]
    assert len(warnings) == 8
    section = _normalize(_section(render_methodology(), "Known limitations"))
    for index, warning in enumerate(warnings, start=1):
        assert f"{index}. {warning}" in section, warning


def test_cli_render_and_check(tmp_path: Path) -> None:
    out = tmp_path / "nested" / "METHODOLOGY.md"
    result = CliRunner().invoke(cli, ["methodology", "render", "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert out.read_bytes() == render_methodology().encode("utf-8")
    result = CliRunner().invoke(cli, ["methodology", "render", "--out", str(out), "--check"])
    assert result.exit_code == 0, result.output
    out.write_text(out.read_text(encoding="utf-8") + "\nstale line\n", encoding="utf-8")
    result = CliRunner().invoke(cli, ["methodology", "render", "--out", str(out), "--check"])
    assert result.exit_code == 1
    assert "differs from the registry render" in result.output
    assert "+" in result.output or "-" in result.output
    missing = tmp_path / "missing.md"
    result = CliRunner().invoke(cli, ["methodology", "render", "--out", str(missing), "--check"])
    assert result.exit_code == 1
    assert "is missing" in result.output


def test_relative_output_paths_resolve_under_the_repository_root() -> None:
    assert resolve_output(Path("docs/METHODOLOGY.md")) == COMMITTED.resolve()
    absolute = Path.cwd().resolve() / "elsewhere.md"
    assert resolve_output(absolute) == absolute
