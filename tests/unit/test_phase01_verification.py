# tests/unit/test_phase01_verification.py
"""Phase 1 Step 6: the verification chassis stays intact.

The roadmap and the QA findings document exist, the verification script's
static mode exits 0 on the committed tree (so the `phase-verify` check and
this test fail together on a broken deliverable), and the phase-verify
workflow's matrix includes this phase.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFY_SCRIPT = REPO_ROOT / "scripts" / "verify_phase01.py"


def test_roadmap_doc_exists() -> None:
    path = REPO_ROOT / "docs" / "phase01-roadmap.md"
    assert path.is_file()
    assert path.read_text(encoding="utf-8").startswith("<!-- docs/phase01-roadmap.md -->")


def test_qa_findings_doc_exists() -> None:
    path = REPO_ROOT / "docs" / "phase01-qa-findings.md"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert text.startswith("<!-- docs/phase01-qa-findings.md -->")
    for section in ("## Step 1", "## Step 6", "## Pre-ship items"):
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
    assert completed.stdout.count("[PASS]") == 43


def test_phase_verify_matrix_includes_01() -> None:
    workflow = yaml.safe_load(
        (REPO_ROOT / ".github" / "workflows" / "phase-verify.yml").read_text(encoding="utf-8")
    )
    matrix = workflow["jobs"]["verify"]["strategy"]["matrix"]["phase"]
    assert "01" in matrix
    assert workflow["permissions"] == {"contents": "read"}
