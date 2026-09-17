# tests/unit/test_cli_synthetic.py
"""The ``judgemetrics synthetic generate|verify`` commands."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from judgemetrics.cli import app
from judgemetrics.synthetic import GENERATOR_VERSION, Manifest

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_DIR = REPO_ROOT / "tests" / "fixtures" / "golden"

runner = CliRunner()


def _combined(result: object) -> str:
    output = str(getattr(result, "output", ""))
    stderr = getattr(result, "stderr", "")
    return output + (stderr if isinstance(stderr, str) else "")


def test_synthetic_group_is_registered() -> None:
    result = runner.invoke(app, ["synthetic", "--help"])
    assert result.exit_code == 0, result.output
    assert "generate" in result.output and "verify" in result.output


def test_generate_writes_a_dataset_and_prints_counts(tmp_path: Path) -> None:
    out = tmp_path / "tiny"
    result = runner.invoke(
        app, ["synthetic", "generate", "--seed", "11", "--scale", "tiny", "--out", str(out)]
    )
    assert result.exit_code == 0, _combined(result)
    assert "source/cases.csv\t" in result.output
    assert "truth/planted.csv\t" in result.output
    assert f"wrote {out.resolve() / 'manifest.json'}" in result.output
    manifest = Manifest.load(out / "manifest.json")
    assert manifest.seed == 11 and manifest.scale == "tiny"
    assert manifest.generator_version == GENERATOR_VERSION
    assert (out / "source" / "courts.csv").is_file() and (out / "truth" / "README.md").is_file()


def test_generate_refuses_an_existing_manifest_without_force(tmp_path: Path) -> None:
    out = tmp_path / "tiny"
    argv = ["synthetic", "generate", "--seed", "11", "--scale", "tiny", "--out", str(out)]
    assert runner.invoke(app, argv).exit_code == 0
    before = (out / "manifest.json").read_bytes()
    refused = runner.invoke(app, argv)
    assert refused.exit_code == 1
    assert "force" in _combined(refused)
    assert (out / "manifest.json").read_bytes() == before
    forced = runner.invoke(app, [*argv, "--force"])
    assert forced.exit_code == 0, _combined(forced)
    assert (out / "manifest.json").read_bytes() == before


def test_generate_rejects_an_unknown_scale(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["synthetic", "generate", "--scale", "huge", "--out", str(tmp_path / "x")]
    )
    assert result.exit_code == 2


def test_verify_exits_zero_on_the_golden_fixture() -> None:
    result = runner.invoke(app, ["synthetic", "verify", str(GOLDEN_DIR)])
    assert result.exit_code == 0, _combined(result)
    assert "verified" in result.output


def test_verify_exits_one_after_a_flipped_byte(tmp_path: Path) -> None:
    copy = tmp_path / "golden"
    shutil.copytree(GOLDEN_DIR, copy)
    assert runner.invoke(app, ["synthetic", "verify", str(copy)]).exit_code == 0
    target = copy / "source" / "cases.csv"
    data = bytearray(target.read_bytes())
    data[-2] ^= 0x01
    target.write_bytes(bytes(data))
    result = runner.invoke(app, ["synthetic", "verify", str(copy)])
    assert result.exit_code == 1
    assert "mismatch: source/cases.csv" in _combined(result)


def test_verify_exits_one_without_a_manifest(tmp_path: Path) -> None:
    result = runner.invoke(app, ["synthetic", "verify", str(tmp_path)])
    assert result.exit_code == 1
    assert "manifest.json: missing" in _combined(result)
