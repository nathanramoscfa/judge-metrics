# tests/unit/test_phase02_verification.py
"""Phase 2 Step 6: the verification chassis stays intact.

The roadmap and the QA findings document exist, the verification script's
static mode exits 0 on the committed tree (so the `phase-verify (02)` check
and this test fail together on a broken deliverable), and the phase-verify
workflow's matrix includes this phase beside Phase 1.
"""

from __future__ import annotations

import subprocess  # argument lists over PATH tools, never a shell  # nosec B404
import sys
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFY_SCRIPT = REPO_ROOT / "scripts" / "verify_phase02.py"
STATIC_CHECKS = 44


def test_roadmap_doc_exists() -> None:
    path = REPO_ROOT / "docs" / "phase02-roadmap.md"
    assert path.is_file()
    assert path.read_text(encoding="utf-8").startswith("<!-- docs/phase02-roadmap.md -->")


def test_qa_findings_doc_exists() -> None:
    path = REPO_ROOT / "docs" / "phase02-qa-findings.md"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert text.startswith("<!-- docs/phase02-qa-findings.md -->")
    for section in (
        "## Step 1",
        "## Step 2",
        "## Step 3",
        "## Step 4",
        "## Step 5",
        "## Step 6",
        "### Alarm exercise",
        "## Pre-ship items",
        "## Phase 3 carry-over checklist",
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


def test_phase_verify_matrix_includes_02() -> None:
    workflow = yaml.safe_load(
        (REPO_ROOT / ".github" / "workflows" / "phase-verify.yml").read_text(encoding="utf-8")
    )
    matrix = workflow["jobs"]["verify"]["strategy"]["matrix"]["phase"]
    assert matrix == ["01", "02"]
    assert workflow["permissions"] == {"contents": "read"}
    # Neither --fast nor --security needs an application setting, so the
    # workflow sets no JUDGEMETRICS_ variable (the pepper included).
    env = workflow.get("env", {})
    assert not any(key.startswith("JUDGEMETRICS_") for key in env), env
    for step in workflow["jobs"]["verify"]["steps"]:
        step_env = step.get("env", {})
        assert not any(key.startswith("JUDGEMETRICS_") for key in step_env), step
