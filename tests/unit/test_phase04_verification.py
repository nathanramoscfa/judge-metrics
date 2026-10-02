# tests/unit/test_phase04_verification.py
"""Phase 4 Step 6: the verification chassis stays intact.

The roadmap and the QA findings document exist, the verification script's
static mode exits 0 on the committed tree (so the `phase-verify (04)` check
and this test fail together on a broken deliverable), the phase-verify
workflow's matrix includes this phase beside Phases 1 to 3 (a subset, never
the exact list: Phase 3 finding 6.1), and the script's standard-library
readers agree with ``yaml.safe_load`` and the brief.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess  # argument lists over PATH tools, never a shell  # nosec B404
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFY_SCRIPT = REPO_ROOT / "scripts" / "verify_phase04.py"
STATIC_CHECKS = 50
BRIEF = REPO_ROOT / "docs" / "brief" / "judgemetrics-master-project-specification.xml"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verify_phase04", VERIFY_SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # The script's dataclasses resolve their module through sys.modules.
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        del sys.modules[spec.name]
    return module


def _yaml(relative: str) -> dict[str, object]:
    loaded = yaml.safe_load((REPO_ROOT / relative).read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return loaded


def _normalize(text: str) -> str:
    return " ".join(text.split())


def test_roadmap_doc_exists() -> None:
    path = REPO_ROOT / "docs" / "roadmap" / "phase04-roadmap.md"
    assert path.is_file()
    assert path.read_text(encoding="utf-8").startswith("<!-- docs/roadmap/phase04-roadmap.md -->")


def test_qa_findings_doc_exists() -> None:
    path = REPO_ROOT / "docs" / "phase04-qa-findings.md"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert text.startswith("<!-- docs/phase04-qa-findings.md -->")
    for section in (
        "## Step 1",
        "## Step 2",
        "## Step 3",
        "## Step 4",
        "## Step 5",
        "## Step 6",
        "### Alarm exercise",
        "## Pre-ship items",
        "## Phase 5 carry-over checklist",
    ):
        assert section in text, section


def test_verify_script_fast_exits_zero() -> None:
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, str(VERIFY_SCRIPT), "--fast"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "[FAIL]" not in completed.stdout
    assert completed.stdout.count("[PASS]") == STATIC_CHECKS


def test_phase_verify_matrix_includes_04() -> None:
    workflow = _yaml(".github/workflows/phase-verify.yml")
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict)
    matrix = jobs["verify"]["strategy"]["matrix"]["phase"]
    assert {"01", "02", "03", "04"} <= set(matrix)
    assert workflow["permissions"] == {"contents": "read"}
    # Neither --fast nor --security needs an application setting, so the
    # workflow sets no JUDGEMETRICS_ variable (the pepper included).
    env = workflow.get("env", {})
    assert isinstance(env, dict)
    assert not any(key.startswith("JUDGEMETRICS_") for key in env), env
    for step in jobs["verify"]["steps"]:
        step_env = step.get("env", {})
        assert not any(key.startswith("JUDGEMETRICS_") for key in step_env), step


def test_registry_readers_match_yaml() -> None:
    """The registry's limitations and slugs as the script reads them equal yaml.safe_load."""
    verify = _load_script()
    registry = _yaml("data/reference/metric_registry.yaml")
    limitations = registry["known_limitations"]
    metrics = registry["metrics"]
    assert isinstance(limitations, list) and isinstance(metrics, list)
    expected = [_normalize(text) for text in limitations]
    assert verify._registry_limitations() == expected
    assert verify._registry_slugs() == [m["slug"] for m in metrics]
    assert verify._brief_warnings() == expected
    entries = verify._registry_entries()
    assert list(entries) == [m["slug"] for m in metrics]
    for metric in metrics:
        if metric["kind"] == "observed_expected":
            assert metric["slug"] in verify.ADJUSTED_SLUGS
            assert metric["suppression_threshold"] == verify.ADJUSTED_THRESHOLD
    assert verify._registry_scalar("methodology_version") == registry["methodology_version"]


def test_specification_reader_matches_yaml() -> None:
    """The features as the script reads them (name, known_at, leakage) equal yaml.safe_load."""
    verify = _load_script()
    specification = _yaml("data/reference/outcome_model.yaml")
    features = specification["features"]
    assert isinstance(features, list)
    read = verify._spec_features()
    assert [f["name"] for f in read] == [f["name"] for f in features]
    for ours, theirs in zip(read, features, strict=True):
        assert ours["known_at"] == theirs["known_at"], theirs["name"]
        assert ours["leakage"] == _normalize(theirs["leakage"]), theirs["name"]
    assert set(verify.SPEC_BLOCKS) <= set(specification)
    assert verify._top_level_keys(verify.SPECIFICATION) == list(specification)


def test_brief_interpretation_reader_matches_reference() -> None:
    """The interpretation reader equals an independent regular expression over the brief."""
    verify = _load_script()
    brief = BRIEF.read_text(encoding="utf-8")
    block = re.search(r"<risk_adjustment>(.*?)</risk_adjustment>", brief, re.DOTALL)
    assert block is not None
    inner = re.search(r"<interpretation>\s*(.*?)\s*</interpretation>", block.group(1), re.DOTALL)
    assert inner is not None
    assert verify._brief_interpretation() == _normalize(inner.group(1))
    assert verify._brief_interpretation().startswith("An O/E ratio above 1")


def test_changelog_reader_matches_module() -> None:
    from judgemetrics.metrics.methodology import CHANGELOG

    verify = _load_script()
    assert verify._changelog_versions() == [version for version, _ in CHANGELOG]
