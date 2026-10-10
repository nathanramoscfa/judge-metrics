# tests/unit/test_methodology_render.py
"""The committed docs/METHODOLOGY.md equals the registry render (the docs/openapi.json pattern).

The document wraps at 80 columns, starts with its path comment, carries
one section per registry metric, states the index-event, exposure, and
censoring semantics, and lists the brief's eight statistical warnings
verbatim under "Known limitations"; ``judgemetrics methodology render
--check`` exits 0 against the committed file and 1 against a stale one.
Methodology 1.0 (Phase 4 Step 4): the "Adjusted statistics" section renders
the outcome model specification — the model, the targets, every feature
with its levels, known-at rule, and leakage justification, every exclusion
with its reason, the expected count, the brief's O/E interpretation
verbatim, the pooling, the interval, the thresholds, the controls, and the
limitations of adjustment — and the changelog runs 0.1, 0.2, 0.3, 1.0.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET  # noqa: S405 - the brief is a repository file
from pathlib import Path

import pytest
from typer.testing import CliRunner

from judgemetrics.cli import app as cli
from judgemetrics.config import REPO_ROOT
from judgemetrics.metrics.adjustment.spec import load_spec
from judgemetrics.metrics.methodology import (
    CHANGELOG,
    PATH_COMMENT,
    WIDTH,
    adjustment_prose,
    check_methodology,
    render_methodology,
    resolve_output,
)
from judgemetrics.metrics.registry import load_registry

pytestmark = pytest.mark.unit

COMMITTED = REPO_ROOT / "docs" / "METHODOLOGY.md"
BRIEF = REPO_ROOT / "docs" / "brief" / "judgemetrics-master-project-specification.xml"
# The brief's <risk_adjustment><interpretation>, normalized (the element is read below).
INTERPRETATION = (
    "An O/E ratio above 1 means observed outcomes exceeded the model's expected count for "
    "the defined cohort. A ratio below 1 means observed outcomes were below the model's "
    "expected count. It must not be described as proof that the judge caused the difference."
)


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
        "## Adjusted statistics",
        "## Metrics",
        "## Periods",
        "## Revocation scopes",
        "## Source limitations",
        "### Availability",
        "## Coverage statistics",
        "## Suppression",
        "### Measured cohorts",
        "## Known limitations",
        "## Methodology changelog",
    ):
        assert f"\n{heading}\n" in document, heading
    registry = load_registry()
    assert (
        f"Registry version {registry.version}; methodology version "
        f"{registry.methodology_version}" in document
    )
    assert registry.methodology_version == "1.1"
    assert "## Observed-to-expected ratios" not in document
    adjusted = _normalize(_section(document, "Adjusted statistics"))
    for phrase in (
        "(alpha + O) / (alpha + E)",
        "E / (E + alpha)",
        "maximum marginal (negative-binomial) likelihood",
        "2.5th and 97.5th percentiles",
        "500 replicates",
        "with the model refitted",
        "not a confidence interval for the judge's true ratio",
        "The judge is never a term of the model",
        "expected_below_minimum",
        "model_unavailable",
        "Unobserved confounding and selection on unobservables",
        "Model misspecification",
        "Restricted attributes excluded by policy",
        "Intervals conditional on the specification",
        "compared with contemporaneous cohorts",
        "never across sources",
        "docs/VALIDATION.md",
    ):
        assert phrase in adjusted, phrase
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
    changelog = _section(document, "Methodology changelog")
    assert "- 0.1 - first registry" in changelog
    assert "- 0.2 - Exposure is deferred by every incarceration term" in changelog
    assert "- 0.3 - Observed-to-expected ratios with partial pooling and bootstrap" in changelog
    assert "- 1.0 - The expected-outcome model, observed-to-expected ratios" in changelog
    assert "- 1.1 - Real-data semantics (registry version 3" in changelog
    assert [version for version, _ in CHANGELOG] == ["0.1", "0.2", "0.3", "1.0", "1.1"]
    assert CHANGELOG[-1][0] == registry.methodology_version
    assert changelog.index("- 0.3 -") < changelog.index("- 1.0 -")
    for metric in registry.of_kind("observed_expected"):
        section = _normalize(metrics[metrics.index(f"### {metric.name}") :].split("\n### ")[0])
        assert "Suppression threshold: 30 (suppressed below this cohort)" in section
        assert "below an expected count of 5 or without a fitted model" in section


def test_the_adjusted_statistics_section_renders_the_specification() -> None:
    spec = load_spec()
    document = render_methodology()
    section = _normalize(_section(document, "Adjusted statistics"))
    assert f"**Interpretation.** {INTERPRETATION}" in section
    root = ET.parse(BRIEF).getroot()  # noqa: S314 - repository file
    node = root.find(".//risk_adjustment/interpretation")
    assert node is not None
    assert _normalize(node.text or "") == INTERPRETATION
    for target in spec.targets:
        assert f"`{target.name}`: {_normalize(target.description)}" in section, target.name
    for feature in spec.features:
        start = section.index(f"- `{feature.name}`: ")
        entry = section[start : section.index(" - `", start + 1)]
        assert _normalize(feature.description) in entry, feature.name
        assert f"Leakage: {_normalize(feature.leakage)}" in entry, feature.name
        assert "Known at: " in entry and "Levels: " in entry, feature.name
        if not feature.data_levels:
            assert f"{feature.reference} (reference)" in entry, feature.name
    for exclusion in spec.excluded:
        assert f"`{exclusion.name}`: {_normalize(exclusion.reason)}" in section, exclusion.name
    prose = adjustment_prose(spec)
    assert prose.interpretation == INTERPRETATION
    assert len(prose.limitations) == 4
    assert [term for term, _ in prose.controls] == ["Temporal", "Jurisdiction"]
    assert [term for term, _ in prose.thresholds] == [
        "Events per column",
        "Cohort",
        "Expected count",
    ]


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
