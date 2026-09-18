# tests/unit/test_synthetic_generator.py
"""Phase 2 Step 1: the deterministic synthetic generator.

The golden fixture under ``tests/fixtures/golden/`` regenerates
byte-identically from seed 7; the demo scale meets the brief's minimums
and models every listed behaviour; every planted edge case is recorded in
the configured quantity; every timestamp is ordered; every metric
numerator is bounded by its denominator; every name token comes from the
word lists.
"""

from __future__ import annotations

import csv
import json
import math
import re
from collections import Counter
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from judgemetrics.db.models.enums import ActorType
from judgemetrics.normalization.names import normalize_case_number, normalize_person_name
from judgemetrics.synthetic import (
    DEMO,
    GENERATOR_VERSION,
    GOLDEN,
    TINY,
    DatasetExistsError,
    Manifest,
    ScaleSpec,
    generate_dataset,
    verify_dataset,
)
from judgemetrics.synthetic.config import (
    BRIEF_MINIMUM_CASES,
    BRIEF_MINIMUM_COURTS,
    BRIEF_MINIMUM_JUDGES,
    BRIEF_MINIMUM_PERSONS,
    MAX_CASES_PER_PERSON,
    scale_spec,
)
from judgemetrics.synthetic.edge_cases import (
    EXPECTED_AMBIGUOUS_SAME_DOB_SAME_COURT,
    KIND_AMBIGUOUS_MISSING_DOB,
    KIND_AMBIGUOUS_SAME_DOB,
    KIND_DUPLICATE,
    KIND_MISSING_DESCRIPTION,
    KIND_MISSING_DISPOSITION,
    KIND_MISSING_DOB,
    KIND_MISSING_JUDGE,
    KIND_SPLIT,
    KINDS,
    configured_counts,
)
from judgemetrics.synthetic.rng import STREAM_NAMES, Streams, derive_stream
from judgemetrics.synthetic.truth import TRUTH_FILES, TRUTH_VERSION, WINDOWS_DAYS, days_between
from judgemetrics.synthetic.vocabulary import (
    ACTOR_TYPES,
    CHARGE_DISPOSITIONS,
    DECISION_TYPES,
    EVENT_TYPES,
    JUDICIAL_DISCRETION_CLASSIFICATIONS,
    OFFENSE_CATEGORIES,
    RELEASE_TYPES,
    SEVERITIES,
    VOCABULARY,
)
from judgemetrics.synthetic.wordlists import (
    FAMILY_TOKENS,
    GIVEN_TOKENS,
    MINIMUM_TOKENS,
    is_listed_name,
)
from judgemetrics.synthetic.writer import SOURCE_FILES, SOURCE_HEADERS

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]
GOLDEN_DIR = REPO_ROOT / "tests" / "fixtures" / "golden"
GOLDEN_SEED = 7
DEMO_SEED = 20260916

Rows = list[dict[str, str]]


def read_csv(path: Path) -> Rows:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def parse_ts(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    assert parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0), value
    return parsed


class Dataset:
    """A generated dataset directory read into memory, keyed by id."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.manifest = Manifest.load(root / "manifest.json")
        self.spec: ScaleSpec = scale_spec(self.manifest.scale)
        self.source = {name: read_csv(root / "source" / name) for name in SOURCE_FILES}
        self.persons = read_csv(root / "truth" / "persons.csv")
        self.subsequent = read_csv(root / "truth" / "subsequent_events.csv")
        self.expectations = read_csv(root / "truth" / "resolution_expectations.csv")
        self.planted = read_csv(root / "truth" / "planted.csv")
        self.metrics: dict[str, Any] = json.loads(
            (root / "truth" / "metrics.json").read_text(encoding="utf-8")
        )
        self.duplicate_numbers = {ids["case_number"] for ids in self.planted_ids(KIND_DUPLICATE)}

    def planted_ids(self, kind: str) -> list[dict[str, str]]:
        found: list[dict[str, str]] = []
        for row in self.planted:
            if row["kind"] == kind:
                found.append(dict(pair.split("=", 1) for pair in row["ids"].split(";")))
        return found

    def originals(self, name: str) -> Rows:
        """Rows of a source file without the duplicate copies (variant case numbers)."""
        return [row for row in self.source[name] if not row["case_number"].startswith("syn ")]

    def by_case(self, name: str) -> dict[str, Rows]:
        grouped: dict[str, Rows] = {}
        for row in self.originals(name):
            grouped.setdefault(row["case_number"], []).append(row)
        return grouped


@pytest.fixture(scope="session")
def golden_regenerated(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("golden")
    generate_dataset(GOLDEN_SEED, GOLDEN.name, out)
    return out


@pytest.fixture(scope="session")
def demo_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("demo")
    generate_dataset(DEMO_SEED, DEMO.name, out)
    return out


@pytest.fixture(scope="session")
def golden() -> Dataset:
    return Dataset(GOLDEN_DIR)


@pytest.fixture(scope="session")
def demo(demo_dir: Path) -> Dataset:
    return Dataset(demo_dir)


@pytest.fixture(scope="session", params=["golden", "demo"])
def dataset(request: pytest.FixtureRequest) -> Dataset:
    fixture: Dataset = request.getfixturevalue(request.param)
    return fixture


# --------------------------------------------------------------------------- #
# Determinism and the golden fixture
# --------------------------------------------------------------------------- #


def test_golden_regeneration_is_byte_identical(golden_regenerated: Path) -> None:
    manifest = Manifest.load(GOLDEN_DIR / "manifest.json")
    assert manifest.seed == GOLDEN_SEED and manifest.scale == GOLDEN.name
    for relative in sorted(manifest.files):
        expected = (GOLDEN_DIR / relative).read_bytes()
        actual = (golden_regenerated / relative).read_bytes()
        assert actual == expected, f"{relative} differs from the committed golden fixture"
    assert (golden_regenerated / "manifest.json").read_bytes() == (
        GOLDEN_DIR / "manifest.json"
    ).read_bytes()


def test_golden_fixture_verifies_clean() -> None:
    assert verify_dataset(GOLDEN_DIR) == []


def test_golden_manifest_carries_the_current_versions() -> None:
    manifest = Manifest.load(GOLDEN_DIR / "manifest.json")
    assert manifest.generator_version == GENERATOR_VERSION
    assert manifest.truth_version == TRUTH_VERSION
    assert set(manifest.files) == {f"source/{n}" for n in SOURCE_FILES} | {
        f"truth/{n}" for n in TRUTH_FILES
    }
    for relative, count in manifest.counts.items():
        rows = read_csv(GOLDEN_DIR / relative)
        assert len(rows) == count, relative


def test_two_seeds_differ(tmp_path: Path) -> None:
    other = generate_dataset(GOLDEN_SEED + 1, GOLDEN.name, tmp_path / "eight")
    golden = Manifest.load(GOLDEN_DIR / "manifest.json")
    assert other.files["source/participants.csv"] != golden.files["source/participants.csv"]
    assert other.files["source/cases.csv"] != golden.files["source/cases.csv"]


def test_generate_refuses_an_existing_dataset(tmp_path: Path) -> None:
    out = tmp_path / "tiny"
    first = generate_dataset(3, TINY.name, out)
    with pytest.raises(DatasetExistsError):
        generate_dataset(3, TINY.name, out)
    again = generate_dataset(3, TINY.name, out, force=True)
    assert again.files == first.files
    assert verify_dataset(out) == []


def test_verify_reports_mismatch_missing_and_unlisted(tmp_path: Path) -> None:
    out = tmp_path / "tiny"
    generate_dataset(5, TINY.name, out)
    (out / "source" / "cases.csv").write_bytes(b"case_number\nX\n")
    (out / "truth" / "persons.csv").unlink()
    (out / "source" / "extra.csv").write_text("a\n", encoding="utf-8")
    problems = verify_dataset(out)
    assert any(p.startswith("source/cases.csv: sha256") for p in problems)
    assert "truth/persons.csv: missing" in problems
    assert "source/extra.csv: not in manifest" in problems
    assert verify_dataset(tmp_path / "nowhere") == ["manifest.json: missing"]


def test_streams_are_independent_and_seeded_by_name() -> None:
    assert derive_stream(7, "world").random() == derive_stream(7, "world").random()
    assert derive_stream(7, "world").random() != derive_stream(7, "persons").random()
    assert derive_stream(7, "world").random() != derive_stream(8, "world").random()
    streams = Streams(7)
    assert {name: getattr(streams, name) for name in STREAM_NAMES}


# --------------------------------------------------------------------------- #
# The brief's minimums and behaviours at demo scale
# --------------------------------------------------------------------------- #


def test_demo_spec_meets_the_brief_minimums() -> None:
    assert DEMO.courts >= BRIEF_MINIMUM_COURTS
    assert DEMO.judges >= BRIEF_MINIMUM_JUDGES
    assert DEMO.cases >= BRIEF_MINIMUM_CASES
    assert DEMO.persons >= BRIEF_MINIMUM_PERSONS
    assert GOLDEN.courts >= 1 and GOLDEN.cases >= GOLDEN.persons


def test_demo_run_meets_the_brief_minimums(demo: Dataset) -> None:
    assert len(demo.source["courts.csv"]) >= BRIEF_MINIMUM_COURTS
    assert len({row["judge_code"] for row in demo.source["judges.csv"]}) >= BRIEF_MINIMUM_JUDGES
    assert len(demo.originals("cases.csv")) >= BRIEF_MINIMUM_CASES
    assert len({row["participant_id"] for row in demo.source["participants.csv"]}) >= (
        BRIEF_MINIMUM_PERSONS
    )
    assert len({row["true_person_id"] for row in demo.persons}) == DEMO.persons


def test_demo_run_models_every_listed_behaviour(demo: Dataset) -> None:
    assignments = Counter(row["case_number"] for row in demo.originals("assignments.csv"))
    assert max(assignments.values()) >= 2, "multiple judge assignments"
    charges = demo.originals("charges.csv")
    assert len({row["offense_category"] for row in charges}) >= 2, "multiple offense categories"
    decisions = demo.originals("decisions.csv")
    pretrial = [row for row in decisions if row["decision_type"] == "pretrial_release"]
    judicial = [row for row in pretrial if row["actor"] == "judge" and row["judge_code"]]
    assert any(row["detained"] == "false" for row in judicial), "release with a deciding judge"
    assert any(row["detained"] == "true" for row in judicial), "detention with a deciding judge"
    assert any(row["actor"] == "legislature_or_mandatory_rule" for row in pretrial)
    dismissal_actors = {
        row["disposition_actor"] for row in charges if row["disposition"] == "dismissed"
    }
    assert dismissal_actors == {"judge", "prosecutor"}, "dismissals attributed to both"
    dispositions = {row["disposition"] for row in charges}
    assert {"convicted_plea", "convicted_verdict", "acquitted", "pending"} <= dispositions
    assert demo.originals("sentences.csv"), "sentences"
    per_participant = Counter(row["participant_id"] for row in demo.originals("participants.csv"))
    assert max(per_participant.values()) >= 2, "subsequent cases"
    assert max(per_participant.values()) <= MAX_CASES_PER_PERSON
    event_types = {row["event_type"] for row in demo.originals("events.csv")}
    assert {"failure_to_appear", "bench_warrant", "revocation", "trial", "arraignment"} <= (
        event_types
    )
    outcome_types = {row["outcome_type"] for row in demo.subsequent}
    assert {"new_case", "new_charge", "reconviction", "failure_to_appear", "revocation"} <= (
        outcome_types
    )
    assert any(row["status"] == "open" for row in demo.originals("cases.csv"))


# --------------------------------------------------------------------------- #
# Names
# --------------------------------------------------------------------------- #


def test_word_lists_are_large_distinct_and_plain() -> None:
    for tokens in (GIVEN_TOKENS, FAMILY_TOKENS):
        assert len(tokens) >= MINIMUM_TOKENS
        assert len(set(tokens)) == len(tokens)
        for token in tokens:
            assert token.isalpha() and token.isascii() and token == token.capitalize(), token
            assert normalize_person_name(token) == token.lower()


def test_every_name_token_is_listed(dataset: Dataset) -> None:
    for row in dataset.source["participants.csv"]:
        assert is_listed_name(row["full_name"].strip().title()), row["full_name"]
    for row in dataset.source["judges.csv"]:
        name = row["full_name"]
        assert is_listed_name(name), name
        assert normalize_person_name(name) == name.lower()
        assert not name.startswith(("Hon", "Judge"))


def test_names_are_unique_except_planted_collisions(dataset: Dataset) -> None:
    ids_by_name: dict[str, set[str]] = {}
    for row in dataset.originals("participants.csv"):
        ids_by_name.setdefault(row["full_name"], set()).add(row["participant_id"])
    shared = {name for name, ids in ids_by_name.items() if len(ids) > 1}
    planted_shared = {
        ids["shared_name"]
        for kind in (KIND_AMBIGUOUS_SAME_DOB, KIND_AMBIGUOUS_MISSING_DOB)
        for ids in dataset.planted_ids(kind)
    }
    split_names: set[str] = set()
    split_ids = {
        pid for ids in dataset.planted_ids(KIND_SPLIT) for pid in ids["participant_ids"].split(",")
    }
    for row in dataset.originals("participants.csv"):
        if row["participant_id"] in split_ids:
            split_names.add(row["full_name"])
    assert shared == planted_shared | split_names
    judge_names = [row["full_name"] for row in dataset.source["judges.csv"]]
    judge_codes = {row["judge_code"]: row["full_name"] for row in dataset.source["judges.csv"]}
    assert len(set(judge_names)) == len(judge_codes)
    assert not (set(judge_names) & set(ids_by_name)), "a judge shares a name with a defendant"


# --------------------------------------------------------------------------- #
# Vocabulary
# --------------------------------------------------------------------------- #


def test_actor_vocabulary_equals_the_enum() -> None:
    assert ACTOR_TYPES == tuple(actor.value for actor in ActorType)
    assert VOCABULARY["actor_type"] is ACTOR_TYPES


def test_source_values_stay_inside_the_vocabulary(dataset: Dataset) -> None:
    for row in dataset.source["cases.csv"]:
        assert row["case_type"] in VOCABULARY["case_type"]
        assert row["status"] in VOCABULARY["case_status"]
    for row in dataset.source["charges.csv"]:
        assert row["offense_category"] in OFFENSE_CATEGORIES
        assert row["severity"] in SEVERITIES
        assert row["disposition"] in (*CHARGE_DISPOSITIONS, "")
        assert row["disposition_actor"] in (*ACTOR_TYPES, "")
        assert row["violent_flag"] in ("true", "false")
        assert row["statute_code"].startswith("SYN-")
    for row in dataset.source["events.csv"]:
        assert row["event_type"] in EVENT_TYPES
        assert row["actor"] in (*ACTOR_TYPES, "")
    for row in dataset.source["decisions.csv"]:
        assert row["decision_type"] in DECISION_TYPES
        assert row["actor"] in ACTOR_TYPES
        assert row["discretion"] in JUDICIAL_DISCRETION_CLASSIFICATIONS
        assert row["release_type"] in (*RELEASE_TYPES, "")
        for condition in filter(None, row["conditions"].split(";")):
            assert condition in VOCABULARY["release_condition"]
    for row in dataset.source["sentences.csv"]:
        for component in row["components"].split(";"):
            assert component in VOCABULARY["sentence_component"]
    for row in dataset.source["judges.csv"]:
        assert row["position"] in VOCABULARY["position"]
    for row in dataset.source["assignments.csv"]:
        assert row["assignment_type"] in VOCABULARY["assignment_type"]
    for row in dataset.source["participants.csv"]:
        assert row["party_type"] in VOCABULARY["party_type"]
    for row in dataset.subsequent:
        assert row["outcome_type"] in VOCABULARY["justice_event_type"]


def test_source_files_have_the_documented_headers_and_lf_newlines(dataset: Dataset) -> None:
    for name in SOURCE_FILES:
        raw = (dataset.root / "source" / name).read_bytes()
        assert b"\r" not in raw and raw.endswith(b"\n")
        header = raw.split(b"\n", 1)[0].decode("utf-8")
        assert header == ",".join(SOURCE_HEADERS[name]), name
        for line in raw.decode("utf-8").split("\n"):
            assert not line.endswith((" ", "\t")), f"{name}: trailing whitespace"
    for row in dataset.source["courts.csv"]:
        assert row["court_type"] == "circuit"
        assert row["jurisdiction"] == "Synthetic State" and row["state_code"] == "ZZ"
        assert row["name"].startswith("Synthetic County Circuit Court, Division ")


# --------------------------------------------------------------------------- #
# Planted edge cases
# --------------------------------------------------------------------------- #


def test_every_planted_kind_appears_in_the_configured_quantity(dataset: Dataset) -> None:
    decisions = dataset.originals("decisions.csv")
    judicial = sum(
        1
        for row in decisions
        if row["decision_type"] == "pretrial_release" and row["actor"] in ("judge", "unknown")
    )
    closed = {
        row["case_number"] for row in dataset.originals("cases.csv") if row["status"] == "closed"
    }
    closed_charges = sum(
        1 for row in dataset.originals("charges.csv") if row["case_number"] in closed
    )
    events = len(dataset.originals("events.csv"))
    expected = configured_counts(
        dataset.spec,
        judicial_pretrial_decisions=judicial,
        closed_case_charges=closed_charges,
        events=events,
    )
    actual = Counter(row["kind"] for row in dataset.planted)
    assert set(actual) == set(KINDS)
    assert dict(actual) == expected
    for row in dataset.planted:
        assert row["expected_behaviour"]


def test_duplicate_source_records_are_formatting_variants(dataset: Dataset) -> None:
    cases = {row["case_number"]: row for row in dataset.source["cases.csv"]}
    names = {
        (row["participant_id"], row["case_number"]): row["full_name"]
        for row in dataset.source["participants.csv"]
    }
    for ids in dataset.planted_ids(KIND_DUPLICATE):
        original, variant = ids["case_number"], ids["duplicate_case_number"]
        assert original != variant and variant in cases
        assert normalize_case_number(variant) == normalize_case_number(original)
        copy = dict(cases[variant])
        copy["case_number"] = original
        assert copy == cases[original]
        pid = ids["participant_id"]
        assert names[(pid, variant)] != names[(pid, original)]
        assert normalize_person_name(names[(pid, variant)]) == normalize_person_name(
            names[(pid, original)]
        )
    for name in SOURCE_FILES[2:]:
        for row in dataset.source[name]:
            if row["case_number"].startswith("syn "):
                assert row["case_number"].upper().replace(" ", "-") in dataset.duplicate_numbers


def test_ambiguous_pairs_are_distinct_persons(dataset: Dataset) -> None:
    participants = dataset.originals("participants.csv")
    truth = {
        (row["participant_id"], row["court_code"]): row["true_person_id"] for row in dataset.persons
    }
    for kind in (KIND_AMBIGUOUS_SAME_DOB, KIND_AMBIGUOUS_MISSING_DOB):
        for ids in dataset.planted_ids(kind):
            left, right = ids["participant_ids"].split(",")
            left_rows = [row for row in participants if row["participant_id"] == left]
            right_rows = [row for row in participants if row["participant_id"] == right]
            assert left_rows and right_rows
            assert {row["full_name"] for row in left_rows + right_rows} == {ids["shared_name"]}
            true_ids = {
                truth[(row["participant_id"], row["court_code"])] for row in left_rows + right_rows
            }
            assert len(true_ids) == 2, "two distinct true persons"
            assert not (
                {r["case_number"] for r in left_rows} & {r["case_number"] for r in right_rows}
            )
            if kind == KIND_AMBIGUOUS_SAME_DOB:
                assert len({row["date_of_birth"] for row in left_rows + right_rows}) == 1
                assert all(row["date_of_birth"] for row in left_rows + right_rows)
                # Disjoint courts unless the world had no such pair (tiny scale only).
                same_court = {r["court_code"] for r in left_rows} & {
                    r["court_code"] for r in right_rows
                }
                fallback = any(
                    row["expected_behaviour"] == EXPECTED_AMBIGUOUS_SAME_DOB_SAME_COURT
                    for row in dataset.planted
                    if row["kind"] == kind and ids["participant_ids"] in row["ids"]
                )
                assert bool(same_court) == fallback
            else:
                known = {row["date_of_birth"] != "" for row in left_rows} | {
                    row["date_of_birth"] != "" for row in right_rows
                }
                assert known == {True, False}, "exactly one side has a date of birth"


# A tiny-scale seed (found by tests/property) whose world holds no two unused
# persons in disjoint courts: the same-date-of-birth plant falls back to a
# same-court pair rather than failing the generation.
TINY_SEED_WITHOUT_DISJOINT_COURTS = 511


def test_tiny_seed_without_disjoint_courts_plants_a_same_court_ambiguous_pair(
    tmp_path: Path,
) -> None:
    generate_dataset(TINY_SEED_WITHOUT_DISJOINT_COURTS, "tiny", tmp_path)
    dataset = Dataset(tmp_path)
    rows = [row for row in dataset.planted if row["kind"] == KIND_AMBIGUOUS_SAME_DOB]
    assert len(rows) == 1
    (row,) = rows
    assert row["expected_behaviour"] == EXPECTED_AMBIGUOUS_SAME_DOB_SAME_COURT
    ids = dict(pair.split("=", 1) for pair in row["ids"].split(";"))
    left, right = ids["participant_ids"].split(",")
    participants = dataset.originals("participants.csv")
    left_rows = [r for r in participants if r["participant_id"] == left]
    right_rows = [r for r in participants if r["participant_id"] == right]
    assert {r["court_code"] for r in left_rows} & {r["court_code"] for r in right_rows}
    assert not ({r["case_number"] for r in left_rows} & {r["case_number"] for r in right_rows})
    assert len({r["date_of_birth"] for r in left_rows + right_rows}) == 1
    expectation = next(
        e
        for e in dataset.expectations
        if {e["left_participant_id"], e["right_participant_id"]} == {left, right}
    )
    assert expectation["expected_decision"] == "review"
    # The golden scale never needs the fallback: its planted text is the disjoint one.
    golden = Dataset(GOLDEN_DIR)
    for golden_row in golden.planted:
        assert golden_row["expected_behaviour"] != EXPECTED_AMBIGUOUS_SAME_DOB_SAME_COURT


def test_split_persons_share_identity_name_dob_and_a_case_link(dataset: Dataset) -> None:
    participants = dataset.originals("participants.csv")
    cases = {row["case_number"]: row for row in dataset.originals("cases.csv")}
    truth = {
        (row["participant_id"], row["court_code"]): row["true_person_id"] for row in dataset.persons
    }
    for ids in dataset.planted_ids(KIND_SPLIT):
        first_id, second_id = ids["participant_ids"].split(",")
        rows = [row for row in participants if row["participant_id"] in (first_id, second_id)]
        assert len({row["full_name"] for row in rows}) == 1
        assert len({row["date_of_birth"] for row in rows}) == 1 and rows[0]["date_of_birth"]
        assert {truth[(row["participant_id"], row["court_code"])] for row in rows} == {
            ids["true_person_id"]
        }
        second = cases[ids["second_case_number"]]
        assert second["related_case_number"] == ids["first_case_number"]
        assert second["court_code"] == ids["second_court_code"] != ids["first_court_code"]
        assert cases[ids["first_case_number"]]["court_code"] == ids["first_court_code"]


def test_resolution_expectations_name_every_planted_pair(dataset: Dataset) -> None:
    pairs = {
        (row["left_participant_id"], row["right_participant_id"]): row
        for row in dataset.expectations
    }
    expected_pairs: dict[tuple[str, str], str] = {}
    for kind, decision in (
        (KIND_SPLIT, "matched"),
        (KIND_AMBIGUOUS_SAME_DOB, "review"),
        (KIND_AMBIGUOUS_MISSING_DOB, "rejected"),
    ):
        for ids in dataset.planted_ids(kind):
            left, right = sorted(ids["participant_ids"].split(","))
            expected_pairs[(left, right)] = decision
    assert {pair: row["expected_decision"] for pair, row in pairs.items()} == expected_pairs
    known = {row["participant_id"] for row in dataset.source["participants.csv"]}
    for (left, right), row in pairs.items():
        assert left < right and {left, right} <= known
        assert row["reason"]


def test_missing_data_examples_exist(dataset: Dataset) -> None:
    decisions = {row["decision_id"]: row for row in dataset.originals("decisions.csv")}
    for ids in dataset.planted_ids(KIND_MISSING_JUDGE):
        row = decisions[ids["decision_id"]]
        assert (
            row["judge_code"] == "" and row["actor"] == "unknown" and row["discretion"] == "unknown"
        )
        assert row["decision_type"] == "pretrial_release" and row["release_type"]
    charges = {row["charge_id"]: row for row in dataset.originals("charges.csv")}
    closed = {
        row["case_number"] for row in dataset.originals("cases.csv") if row["status"] == "closed"
    }
    for ids in dataset.planted_ids(KIND_MISSING_DISPOSITION):
        row = charges[ids["charge_id"]]
        assert row["disposition"] == row["disposed_at"] == row["disposition_actor"] == ""
        assert row["case_number"] in closed
    events = {row["event_id"]: row for row in dataset.originals("events.csv")}
    for ids in dataset.planted_ids(KIND_MISSING_DESCRIPTION):
        assert events[ids["event_id"]]["description"] == ""
    participants = dataset.originals("participants.csv")
    for ids in dataset.planted_ids(KIND_MISSING_DOB):
        rows = [row for row in participants if row["participant_id"] == ids["participant_id"]]
        assert rows and all(row["date_of_birth"] == "" for row in rows)
    unplanned_missing = {
        row["charge_id"]
        for row in charges.values()
        if row["disposition"] == "" and row["case_number"] in closed
    }
    assert unplanned_missing == {
        ids["charge_id"] for ids in dataset.planted_ids(KIND_MISSING_DISPOSITION)
    }


# --------------------------------------------------------------------------- #
# Truth
# --------------------------------------------------------------------------- #


def test_truth_persons_cover_every_participant(dataset: Dataset) -> None:
    from_source = {
        (row["participant_id"], row["court_code"]) for row in dataset.source["participants.csv"]
    }
    from_truth = {(row["participant_id"], row["court_code"]) for row in dataset.persons}
    assert from_truth == from_source
    per_participant: dict[str, set[str]] = {}
    for row in dataset.persons:
        per_participant.setdefault(row["participant_id"], set()).add(row["true_person_id"])
    assert all(len(ids) == 1 for ids in per_participant.values()), "one true person per id"
    assert all(row["true_person_id"].startswith("P-") for row in dataset.persons)


def _case_timelines(dataset: Dataset) -> Iterator[tuple[dict[str, str], dict[str, Rows]]]:
    children = {name: dataset.by_case(name) for name in SOURCE_FILES[3:]}
    for case in dataset.originals("cases.csv"):
        number = case["case_number"]
        yield case, {name: grouped.get(number, []) for name, grouped in children.items()}


def test_every_case_timeline_is_strictly_ordered(dataset: Dataset) -> None:
    corpus_end_at = dataset.spec.corpus_end_at
    for case, rows in _case_timelines(dataset):
        filed_date = date.fromisoformat(case["filed_date"])
        charges = rows["charges.csv"]
        assert charges, case["case_number"]
        filed_at = parse_ts(charges[0]["filed_at"])
        assert filed_at.date() == filed_date
        assert dataset.spec.corpus_start <= filed_date <= dataset.spec.corpus_end
        assignments = sorted(rows["assignments.csv"], key=lambda r: r["start_at"])
        assert assignments, case["case_number"]
        assert assignments[0]["assignment_type"] == "initial"
        assert filed_at < parse_ts(assignments[0]["start_at"])
        for earlier, later in zip(assignments, assignments[1:], strict=False):
            assert earlier["end_at"] == later["start_at"], "a hand-off at one instant"
            assert later["assignment_type"] == "reassignment"
        events: dict[str, list[datetime]] = {row["event_type"]: [] for row in rows["events.csv"]}
        for row in rows["events.csv"]:
            events[row["event_type"]].append(parse_ts(row["event_at"]))
            assert parse_ts(row["event_at"]) < corpus_end_at
        decisions = {row["decision_type"]: row for row in rows["decisions.csv"]}
        arraignment = events.get("arraignment")
        pretrial = decisions.get("pretrial_release")
        if arraignment:
            assert parse_ts(assignments[0]["start_at"]) < arraignment[0]
            if pretrial:
                assert arraignment[0] < parse_ts(pretrial["decision_at"])
        disposed = [parse_ts(row["disposed_at"]) for row in charges if row["disposed_at"]]
        if disposed and pretrial:
            assert parse_ts(pretrial["decision_at"]) < min(disposed)
        if pretrial and pretrial["release_at"]:
            assert parse_ts(pretrial["decision_at"]) < parse_ts(pretrial["release_at"])
            assert pretrial["detained"] == "false"
        sentences = rows["sentences.csv"]
        if sentences:
            sentence_at = parse_ts(sentences[0]["sentence_at"])
            assert disposed and max(disposed) < sentence_at
            assert any(row["disposition"].startswith("convicted") for row in charges)
        if case["status"] == "closed":
            closed = date.fromisoformat(case["closed_date"])
            last = max(disposed + [parse_ts(s["sentence_at"]) for s in sentences])
            assert last.date() == closed
            assert assignments[-1]["end_at"] and parse_ts(assignments[-1]["end_at"]) == last
            assert all(row["disposition"] != "pending" for row in charges)
        else:
            assert case["closed_date"] == "" and assignments[-1]["end_at"] == ""
        for fta in events.get("failure_to_appear", []):
            assert pretrial and pretrial["detained"] == "false"
            # The warrant follows within ten days unless the corpus ends first.
            if fta + timedelta(days=11) < corpus_end_at:
                assert any(warrant > fta for warrant in events.get("bench_warrant", []))
        for revocation in events.get("revocation", []):
            assert sentences and parse_ts(sentences[0]["sentence_at"]) < revocation
        for hearing in events.get("hearing", []):
            if pretrial:
                assert hearing > parse_ts(pretrial["decision_at"])


def test_every_subsequent_event_follows_its_index_event(dataset: Dataset) -> None:
    assert dataset.subsequent
    seen: set[tuple[str, ...]] = set()
    cases_of = {row["case_number"]: row for row in dataset.originals("cases.csv")}
    for row in dataset.subsequent:
        index_at, outcome_at = parse_ts(row["index_at"]), parse_ts(row["outcome_at"])
        assert outcome_at > index_at
        days_after = int(row["days_after"])
        assert days_after >= 1
        assert days_after == days_between(index_at, outcome_at)
        assert days_after == math.ceil((outcome_at - index_at) / timedelta(days=1))
        assert row["index_event_type"] in ("pretrial_release", "disposition", "sentence")
        assert row["index_case_number"] in cases_of
        key = tuple(row.values())
        assert key not in seen, "rows are distinct"
        seen.add(key)


def _walk_rates(node: Any, path: str = "") -> Iterator[tuple[str, dict[str, Any]]]:
    if isinstance(node, dict):
        if "numerator" in node and "denominator" in node:
            yield path, node
        for key, value in node.items():
            yield from _walk_rates(value, f"{path}.{key}" if path else str(key))


def test_metric_numerators_never_exceed_denominators(dataset: Dataset) -> None:
    metrics = dataset.metrics
    assert metrics["truth_version"] == TRUTH_VERSION
    assert metrics["generator_version"] == GENERATOR_VERSION
    assert metrics["windows_days"] == list(WINDOWS_DAYS)
    assert set(metrics["judges"]) == {row["judge_code"] for row in dataset.source["judges.csv"]}
    assert set(metrics["courts"]) == {row["court_code"] for row in dataset.source["courts.csv"]}
    rates = list(_walk_rates(metrics["judges"])) + list(_walk_rates(metrics["courts"]))
    assert rates
    for path, rate in rates:
        assert 0 <= rate["numerator"] <= rate["denominator"], path
        if rate["denominator"] == 0:
            assert rate["value"] is None, path
        else:
            assert rate["value"] == pytest.approx(rate["numerator"] / rate["denominator"], abs=1e-6)
    for subject in (*metrics["judges"].values(), *metrics["courts"].values()):
        pretrial = subject["pretrial"]
        assert pretrial["released_count"] + pretrial["detained_count"] == pretrial["decisions"]
        assert pretrial["release_share"]["denominator"] == pretrial["decisions"]
        for window in WINDOWS_DAYS:
            entry = pretrial["windows"][str(window)]
            assert entry["followed"] <= entry["cohort"] == pretrial["released_count"]
            for outcome in ("failure_to_appear", "new_case", "reconviction"):
                assert entry[f"{outcome}_rate"]["denominator"] == entry["followed"]
        assert subject["eligible_defendants"] <= subject["eligible_cases"]
        assert (
            sum(subject["disposition_distribution"].values())
            == (subject["judicial_dismissal_rate"]["denominator"])
        )
    for key in ("eligible_cases", "pretrial.windows", "judicial_dismissal_rate", "sentences"):
        assert key in metrics["definitions"]


def test_metrics_agree_with_the_source_files(dataset: Dataset) -> None:
    """Independent recount of the simplest metrics straight from the CSVs."""
    metrics = dataset.metrics
    cases = dataset.originals("cases.csv")
    assignments = dataset.originals("assignments.csv")
    decisions = dataset.originals("decisions.csv")
    truth = {
        (row["participant_id"], row["court_code"]): row["true_person_id"] for row in dataset.persons
    }
    participants = {row["case_number"]: row for row in dataset.originals("participants.csv")}
    for court_code, block in metrics["courts"].items():
        in_court = [row for row in cases if row["court_code"] == court_code]
        assert block["eligible_cases"] == len(in_court)
        assert block["eligible_defendants"] == len(
            {
                truth[(participants[c["case_number"]]["participant_id"], court_code)]
                for c in in_court
            }
        )
        pretrial = [
            row
            for row in decisions
            if row["decision_type"] == "pretrial_release" and row["court_code"] == court_code
        ]
        judicial = [
            row
            for row in pretrial
            if row["actor"] == "judge" and row["discretion"] == "discretionary"
        ]
        assert block["pretrial"]["decisions"] == len(judicial)
        assert block["pretrial"]["released_count"] == sum(
            1 for r in judicial if r["detained"] == "false"
        )
        assert block["pretrial"]["statutory_release_count"] == sum(
            1 for r in pretrial if r["discretion"] == "mandatory"
        )
        assert block["pretrial"]["unknown_actor_count"] == sum(
            1 for r in pretrial if r["actor"] == "unknown"
        )
    for judge_code, block in metrics["judges"].items():
        assigned = {row["case_number"] for row in assignments if row["judge_code"] == judge_code}
        assert block["eligible_cases"] == len(assigned)
        judicial = [
            row
            for row in decisions
            if row["decision_type"] == "pretrial_release" and row["judge_code"] == judge_code
        ]
        assert block["pretrial"]["decisions"] == len(judicial)
        assert block["pretrial"]["detained_count"] == sum(
            1 for r in judicial if r["detained"] == "true"
        )
        sentences = [
            row for row in dataset.originals("sentences.csv") if row["judge_code"] == judge_code
        ]
        assert block["sentences"]["count"] == len(sentences)


def test_golden_truth_readme_lists_every_planted_item(golden: Dataset) -> None:
    text = (GOLDEN_DIR / "truth" / "README.md").read_text(encoding="utf-8")
    assert text.startswith("<!-- truth/README.md")
    assert "never enters" in text
    for row in golden.planted:
        first_key, first_value = row["ids"].split(";", 1)[0].split("=", 1)
        assert f"`{first_key}` = `{first_value}`" in text, row["ids"]
        assert row["kind"] in text
    for key in ("`eligible_cases`", "`judicial_dismissal_rate`", "TRUTH_VERSION"):
        assert key in text


def test_golden_fixture_readme_counts_match_the_manifest() -> None:
    """The hand-written fixture README repeats the manifest's row counts."""
    manifest = Manifest.load(GOLDEN_DIR / "manifest.json")
    text = (GOLDEN_DIR / "README.md").read_text(encoding="utf-8")
    assert text.startswith("<!-- tests/fixtures/golden/README.md -->")
    listed = {
        match.group(1): int(match.group(2))
        for match in re.finditer(r"^\| `((?:source|truth)/[a-z_]+\.csv)` +\| (\d+) +\|", text, re.M)
    }
    assert listed == manifest.counts
    assert f"| Seed              | `{manifest.seed}`" in text
    assert f"| Generator version | `{manifest.generator_version}`" in text
    assert f"| Truth version     | `{manifest.truth_version}`" in text
    kinds = Counter(row["kind"] for row in read_csv(GOLDEN_DIR / "truth" / "planted.csv"))
    for kind, count in kinds.items():
        assert re.search(rf"^\| `{kind}` +\| {count} +\|", text, re.M), kind


def test_corpus_end_is_respected(dataset: Dataset) -> None:
    corpus_end_at = dataset.spec.corpus_end_at
    assert corpus_end_at == datetime(dataset.spec.end_year + 1, 1, 1, tzinfo=UTC)
    for name in ("charges.csv", "decisions.csv", "sentences.csv", "assignments.csv"):
        for row in dataset.originals(name):
            for key, value in row.items():
                if key.endswith("_at") and value:
                    assert parse_ts(value) < corpus_end_at, (name, key)
