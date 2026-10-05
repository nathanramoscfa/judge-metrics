# tests/unit/test_cook_sao_profile.py
"""The Cook County value-set profile: deterministic, no restricted counts, the cross-case key.

CI has no raw lake, so ``profile --check`` over the stored exports is the
post-merge check (V1.3); here the profile is built from the committed
fixture, and the committed ``profile.yaml`` is checked for its shape, its
digests, its restricted columns, and the cross-case measurement.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from judgemetrics.cli import app
from judgemetrics.ingest.cook_sao.profile import (
    HEADER,
    PROFILE_VERSION,
    build_profile,
    load_profile,
    render_profile,
)
from judgemetrics.ingest.cook_sao.schema import (
    AGE_AT_INCIDENT,
    CODED_COLUMNS,
    RESTRICTED_VALUE_COLUMNS,
    VERIFIED_HEADERS,
)
from judgemetrics.ingest.cook_sao.sources import EXTERNAL_IDS
from judgemetrics.ingest.cook_sao.stored import fixture_artifacts

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "cook_sao"
COMMITTED = REPO_ROOT / "data" / "reference" / "cook_sao" / "profile.yaml"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
AGE_KEYS = {"nulls", "min", "max", "unparseable"}


@pytest.fixture(scope="module")
def fixture_profile() -> dict[str, Any]:
    return build_profile(fixture_artifacts(FIXTURE))


@pytest.fixture(scope="module")
def committed() -> dict[str, Any]:
    return load_profile(COMMITTED)


def _assert_restricted_without_counts(profile: dict[str, Any]) -> None:
    for name, dataset in profile["datasets"].items():
        columns = dataset["columns"]
        for column in RESTRICTED_VALUE_COLUMNS:
            if column not in VERIFIED_HEADERS[name]:
                continue
            entry = columns[column]
            assert set(entry) == {"values"}, (name, column)
            assert all(isinstance(value, str) for value in entry["values"]), (name, column)
            assert entry["values"] == sorted(entry["values"]), (name, column)
        if AGE_AT_INCIDENT in VERIFIED_HEADERS[name]:
            assert set(columns[AGE_AT_INCIDENT]) <= AGE_KEYS, name


# --- the fixture's profile -------------------------------------------------------------


def test_the_fixture_profile_is_deterministic(fixture_profile: dict[str, Any]) -> None:
    first = render_profile(fixture_profile)
    second = render_profile(build_profile(fixture_artifacts(FIXTURE)))
    assert first == second
    assert first.startswith(HEADER)
    assert first.splitlines()[0] == "# data/reference/cook_sao/profile.yaml"


def test_the_fixture_profile_lists_restricted_values_without_counts(
    fixture_profile: dict[str, Any],
) -> None:
    _assert_restricted_without_counts(fixture_profile)
    # The fixture blanks them: no value, and every age is null.
    for name, dataset in fixture_profile["datasets"].items():
        if "RACE" in VERIFIED_HEADERS[name]:
            assert dataset["columns"]["RACE"] == {"values": []}
        if AGE_AT_INCIDENT in VERIFIED_HEADERS[name]:
            assert dataset["columns"][AGE_AT_INCIDENT]["nulls"] == dataset["rows"]


def test_the_fixture_profile_finds_no_participant_under_two_cases(
    fixture_profile: dict[str, Any],
) -> None:
    for name in EXTERNAL_IDS:
        assert fixture_profile["keys"][name]["participants_in_more_than_one_case"] == 0, name


def test_the_fixture_profile_carries_no_record_facts(fixture_profile: dict[str, Any]) -> None:
    for artifact in fixture_profile["artifacts"]:
        assert artifact["rows_updated_at"] is None and artifact["retrieved_at"] is None
        assert SHA256.match(artifact["sha256"])


def test_the_fixture_values_are_a_subset_of_the_corpus_values(
    fixture_profile: dict[str, Any], committed: dict[str, Any]
) -> None:
    for name, coded in CODED_COLUMNS.items():
        for column in coded:
            corpus = {v for v, _ in committed["datasets"][name]["columns"][column]["values"]}
            excerpt = {v for v, _ in fixture_profile["datasets"][name]["columns"][column]["values"]}
            assert excerpt <= corpus, (name, column, excerpt - corpus)


# --- the committed profile -------------------------------------------------------------


def test_the_committed_profile_names_the_five_stored_exports(committed: dict[str, Any]) -> None:
    assert committed["version"] == PROFILE_VERSION
    assert committed["source"] == "cook_sao"
    assert [a["external_id"] for a in committed["artifacts"]] == list(EXTERNAL_IDS)
    for artifact in committed["artifacts"]:
        assert SHA256.match(artifact["sha256"]), artifact["external_id"]
        assert artifact["bytes"] > 0
        assert artifact["rows_updated_at"].startswith("2026-04-02T")
        assert artifact["retrieved_at"]
    assert set(committed["datasets"]) == set(EXTERNAL_IDS)


def test_the_committed_profile_lists_restricted_columns_without_counts(
    committed: dict[str, Any],
) -> None:
    _assert_restricted_without_counts(committed)
    text = COMMITTED.read_text(encoding="utf-8")
    for column in RESTRICTED_VALUE_COLUMNS:
        # The only places a restricted column is named are its values-only entries.
        assert len(re.findall(rf"^\s+{column}:\s*$", text, re.MULTILINE)) == sum(
            column in VERIFIED_HEADERS[name] for name in EXTERNAL_IDS
        )


def test_the_committed_profile_measures_the_cross_case_key(committed: dict[str, Any]) -> None:
    for name in EXTERNAL_IDS:
        keys = committed["keys"][name]
        assert keys["participants_in_more_than_one_case"] == 0, name
        if name != "intake.csv":
            assert keys["in_intake"]["participants_under_another_case"] == 0, name


def test_the_committed_profile_is_a_pure_render(committed: dict[str, Any]) -> None:
    """Re-dumping the parsed file gives the file: it was rendered, never hand-edited."""
    assert render_profile(committed) == COMMITTED.read_text(encoding="utf-8")


def test_the_committed_profile_parses_with_safe_load() -> None:
    document = yaml.safe_load(COMMITTED.read_text(encoding="utf-8"))
    assert isinstance(document, dict)


# --- the command -----------------------------------------------------------------------


def test_profile_command_from_the_fixture_writes_and_checks(
    tmp_path: Path, fixture_profile: dict[str, Any]
) -> None:
    runner = CliRunner()
    out = tmp_path / "profile.yaml"
    args = ["sources", "profile", "cook_sao", "--from-fixture", str(FIXTURE), "--out", str(out)]
    written = runner.invoke(app, args)
    assert written.exit_code == 0, written.output
    assert out.read_text(encoding="utf-8") == render_profile(fixture_profile)
    checked = runner.invoke(app, [*args, "--check"])
    assert checked.exit_code == 0, checked.output
    out.write_text(out.read_text(encoding="utf-8").replace("rows: ", "rows:  ", 1), "utf-8")
    drifted = runner.invoke(app, [*args, "--check"])
    assert drifted.exit_code == 1
    assert "differs from the profile render" in drifted.output


def test_profile_command_refuses_another_source(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        app, ["sources", "profile", "fjc", "--out", str(tmp_path / "x.yaml")]
    )
    assert result.exit_code == 2
    assert "no profile or excerpt" in result.output
