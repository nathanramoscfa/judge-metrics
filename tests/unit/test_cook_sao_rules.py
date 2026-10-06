# tests/unit/test_cook_sao_rules.py
"""The Cook County attribution rules map every profiled value and never misattribute.

Every (disposition, reason) pair, felony-review result, diversion program and
result, and Initiation charging event of ``data/reference/cook_sao/profile.yaml``
matches a listed rule (the fallback is reached only by a value the profile
never shows, whose meaning the documentation therefore leaves open); no rule
gives a prosecutor's or a jury's outcome to a judge; every procedural
non-final value is ``final: false``; the committed ``summary`` equals its
recomputation from the profile's counts; and a tampered table is refused with
``RuleError`` naming the file, the key, and the field.
"""

from __future__ import annotations

import hashlib
import re
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml

from judgemetrics.ingest.cook_sao import rules as cook_rules
from judgemetrics.ingest.cook_sao.rules import (
    RULE_VERSION_TAG,
    RULE_VERSIONS,
    TABLE_FILES,
    TABLES_DIR,
    UNKNOWN_REASON,
    CookSaoRules,
    RuleError,
    load_rules,
    parse_rules,
    summarize,
)
from judgemetrics.ingest.cook_sao.sources import FLOWCHART_URL, GLOSSARY_URL
from judgemetrics.normalization import vocabulary

pytestmark = pytest.mark.unit

PROFILE = yaml.safe_load((TABLES_DIR / "profile.yaml").read_text(encoding="utf-8"))
DATASETS = PROFILE["datasets"]
RULES = load_rules()

# The State's own decisions: whatever the reason, never a judge's.
PROSECUTOR_DISPOSITIONS = frozenset(
    {
        "Nolle Prosecution",
        "Nolle Pros - Aonic",
        "Nolle On Remand",
        "SOL",
        "Charge Rejected",
        "Superseded by Indictment",
    }
)
# The reasons the glossary defines as "Nolle Prosecution as result of ...": a
# pair carrying one is never a judge's dismissal, whatever its disposition says.
GLOSSARY_NOLLE_REASONS = frozenset(
    {
        "Complaining Witness Not in Court",
        "Complaining Witness No Prosecution",
        "DDPP Graduate",
        "Deferred Prosecution Program Completed",
        "DGS Graduation",
        "Drug Court Graduate",
        "INDICTMENT",
        "Mental Health Graduate",
        "Motion to Quash Arrest & Suppress Evidence/Sustained",
        "No Lab",
        "Nolle - AONIC",
        "Re-Indictment",
        "TERM",
        "Used in Aggravation",
        "Veteran's Court Graduate",
        "Warrant Quashed/Recalled",
    }
)
# The values that end no case on the merits (the roadmap names them).
NON_FINAL = frozenset(
    {
        "Superseded by Indictment",
        "Transferred - Misd Crt",
        "Mistrial Declared",
        "BFW",
        "Hold Pending Interlocutory",
    }
)
JURY_DISPOSITIONS = frozenset(
    {
        "Verdict Guilty",
        "Verdict-Not Guilty",
        "Verdict Guilty - Lesser Included",
        "Verdict Guilty - Amended Charge",
        "Verdict Guilty But Mentally Ill",
    }
)
PRINCIPLES = (
    "Attribute a decision to the actor who legally made it under Illinois",
    "never to whoever presided over",
    "A prosecutor's nolle prosequi or SOL is `prosecutor` and `non_judicial`.",
    "never counted as a judicial dismissal.",
    "A bench finding or a dismissal by the court is `judge`; a verdict is",
    "The conviction a guilty plea produces is `judge` and `discretionary`:",
    "is `final: false` and never counts as a disposition",
    "A post-judgment value is attributed to the court that entered it",
    '"not settled by the source\'s documentation". A rule never guesses to',
)


def _profile_pairs() -> Iterator[tuple[str, str | None, int]]:
    for dataset in ("dispositions.csv", "sentencing.csv"):
        yield from (
            (disposition, reason, count)
            for disposition, reason, count in DATASETS[dataset]["disposition_reason_pairs"]
        )


def _values(column: str) -> set[str]:
    found: set[str] = set()
    for dataset in DATASETS.values():
        entry = dataset["columns"].get(column)
        if entry and "values" in entry:
            found.update(str(value) for value, _ in entry["values"])
    return found


def _copy_tables(tmp_path: Path) -> Path:
    directory = tmp_path / "cook_sao"
    directory.mkdir()
    for file in (*TABLE_FILES.values(), cook_rules.TABLES_FILE):
        shutil.copyfile(TABLES_DIR / file, directory / file)
    return directory


def _rewrite(directory: Path, name: str, text: str, *, pin: bool = True) -> None:
    """Replace a table's text; ``pin`` updates its digest in tables.yaml so only the field fails."""
    file = TABLE_FILES[name]
    (directory / file).write_text(text, encoding="utf-8", newline="\n")
    if pin:
        manifest = (directory / cook_rules.TABLES_FILE).read_text(encoding="utf-8")
        old = yaml.safe_load(manifest)["tables"][name]["sha256"]
        new = hashlib.sha256((directory / file).read_bytes()).hexdigest()
        (directory / cook_rules.TABLES_FILE).write_text(
            manifest.replace(old, new), encoding="utf-8", newline="\n"
        )


def test_every_profiled_disposition_pair_matches_a_listed_rule() -> None:
    pairs = list(_profile_pairs())
    assert len(pairs) > 100
    for disposition, reason, _ in pairs:
        rule = RULES.disposition(disposition, reason)
        assert not rule.fallback, (disposition, reason)
        assert vocabulary.is_known("charge_disposition", rule.disposition)
        assert vocabulary.is_known("actor_type", rule.actor_type)
        assert vocabulary.is_known(
            "judicial_discretion_classification", rule.judicial_discretion_classification
        )


def test_the_fallback_is_reached_only_by_a_value_the_profile_never_shows() -> None:
    profiled = {(d, r) for d, r, _ in _profile_pairs()}
    fallback = RULES.disposition("Disposition the export never wrote", None)
    assert fallback.fallback and ("Disposition the export never wrote", None) not in profiled
    assert fallback is RULES.disposition(None, None) is RULES.disposition("   ", "x")
    assert (fallback.disposition, fallback.final, fallback.actor_type) == (
        "pending",
        False,
        "unknown",
    )
    assert UNKNOWN_REASON in fallback.rationale
    # A disposition with a `*` rule takes it for any reason; one without falls back.
    assert not RULES.disposition("Nolle Prosecution", "A reason never written").fallback
    assert RULES.disposition("Case Dismissed", "A reason never written").fallback
    assert RULES.disposition("Death Suggested-Cause Abated", "A reason never written").fallback


def test_no_rule_gives_a_prosecutor_or_jury_outcome_to_a_judge() -> None:
    rules = RULES.attribution.dispositions
    for (disposition, reason), rule in rules.items():
        if disposition in PROSECUTOR_DISPOSITIONS:
            assert rule.actor_type == "prosecutor", (disposition, reason)
            assert rule.judicial_discretion_classification == "non_judicial"
        if disposition in JURY_DISPOSITIONS:
            assert rule.actor_type == "jury", disposition
        if reason in GLOSSARY_NOLLE_REASONS:
            assert rule.actor_type != "judge", (disposition, reason)
    for disposition, reason, _ in _profile_pairs():
        rule = RULES.disposition(disposition, reason)
        if reason in GLOSSARY_NOLLE_REASONS or disposition in PROSECUTOR_DISPOSITIONS:
            assert rule.actor_type != "judge", (disposition, reason)
    # A judicial ruling recorded beside a nolle is a flag on the prosecutor's dismissal.
    flagged = [rule for rule in rules.values() if rule.judicial_ruling is not None]
    assert {rule.judicial_ruling for rule in flagged} == set(vocabulary.values("judicial_ruling"))
    for rule in flagged:
        assert rule.disposition == "dismissed"
        if rule.charge_disposition != "FNPC":
            assert rule.actor_type == "prosecutor", rule.charge_disposition_reason
    sustained = RULES.disposition(
        "Nolle Prosecution", "Motion to Quash Arrest & Suppress Evidence/Sustained"
    )
    assert (sustained.actor_type, sustained.judicial_ruling) == (
        "prosecutor",
        "suppression_granted",
    )
    # SOL reconciles the glossary's "Illinois judges remove cases" with its actor.
    sol = RULES.disposition("SOL", None)
    assert sol.actor_type == "prosecutor" and "Illinois judges remove cases" in sol.rationale


def test_bench_findings_and_court_dismissals_are_the_judges_and_pleas_are_justified() -> None:
    for disposition in ("Finding Guilty", "FNG", "FNG Reason Insanity", "FNPC"):
        assert RULES.disposition(disposition, None).actor_type == "judge", disposition
    assert RULES.disposition("Case Dismissed", None).actor_type == "judge"
    plea = RULES.disposition("Plea Of Guilty", None)
    assert (plea.disposition, plea.actor_type, plea.judicial_discretion_classification) == (
        "convicted_plea",
        "judge",
        "discretionary",
    )
    abated = RULES.disposition("Death Suggested-Cause Abated", None)
    assert (abated.actor_type, abated.judicial_discretion_classification) == (
        "legislature_or_mandatory_rule",
        "mandatory",
    )


def test_every_non_final_value_is_final_false_and_never_a_final_disposition() -> None:
    final_values = set(vocabulary.values("final_charge_disposition"))
    for disposition in NON_FINAL:
        rule = RULES.disposition(disposition, None)
        assert not rule.final and rule.disposition not in final_values, disposition
    for rule in RULES.attribution.dispositions.values():
        assert rule.final == (rule.disposition in final_values), rule.charge_disposition
    assert RULES.disposition("Superseded by Indictment", None).disposition == "superseded"
    assert RULES.disposition("Transferred - Misd Crt", None).disposition == "transferred"


def test_every_unknown_states_why_and_every_rule_cites_its_evidence() -> None:
    attribution = RULES.attribution
    rules: list[Any] = [
        *attribution.dispositions.values(),
        attribution.disposition_fallback,
        *attribution.felony_review.values(),
        attribution.felony_review_fallback,
        *attribution.diversion_programs.values(),
        attribution.diversion_program_fallback,
    ]
    for rule in rules:
        assert rule.cites in ("glossary", "plain_legal_meaning")
        assert 0 < len(rule.rationale.split()) <= 90, rule.rationale
        if "unknown" in (rule.actor_type, rule.judicial_discretion_classification):
            assert UNKNOWN_REASON in rule.rationale, rule.rationale
    document = yaml.safe_load(
        (TABLES_DIR / TABLE_FILES["attribution_rules"]).read_text(encoding="utf-8")
    )
    assert document["documentation"] == {"glossary": GLOSSARY_URL, "flowchart": FLOWCHART_URL}
    assert document["unknown_reason"] == UNKNOWN_REASON


def test_the_header_states_the_attribution_principles() -> None:
    text = (TABLES_DIR / TABLE_FILES["attribution_rules"]).read_text(encoding="utf-8")
    header = " ".join(
        line.removeprefix("#").strip() for line in text.splitlines() if line.startswith("#")
    )
    assert text.startswith("# data/reference/cook_sao/attribution_rules.yaml\n")
    for principle in PRINCIPLES:
        assert principle in header, principle


def test_the_summary_equals_its_recomputation_from_the_profile() -> None:
    pairs = DATASETS["dispositions.csv"]["disposition_reason_pairs"]
    recomputed = summarize(RULES, pairs)
    stored = dict(RULES.attribution.summary)
    assert stored.pop("dataset") == "dispositions.csv"
    assert stored == recomputed
    assert recomputed["rows"] == DATASETS["dispositions.csv"]["rows"]
    assert recomputed["fallback_pairs"] == 0
    assert recomputed["unknown_actor_pairs"] == sum(
        1 for d, r, _ in pairs if RULES.disposition(d, r).actor_type == "unknown"
    )
    assert sum(recomputed["actor_shares"].values()) == pytest.approx(1.0, abs=1e-5)


def test_every_profiled_felony_review_diversion_and_charging_value_matches() -> None:
    for result in _values("FELONY_REVIEW_RESULT"):
        rule = RULES.felony_review(result)
        assert rule is not None and not rule.fallback, result
        assert rule.outcome is None or vocabulary.is_known("charging_outcome", rule.outcome)
    assert RULES.felony_review(None) is None
    assert RULES.felony_review("A result never written") is RULES.attribution.felony_review_fallback
    # The glossary's documented outcomes.
    assert RULES.felony_review("Approved").outcome == "approved"  # type: ignore[union-attr]
    assert RULES.felony_review("Disregard").outcome == "rejected"  # type: ignore[union-attr]
    assert RULES.felony_review("Continued Investigation").outcome == "continued"  # type: ignore[union-attr]
    for rule in RULES.attribution.felony_review.values():
        if rule.outcome is not None:
            assert rule.actor_type == "prosecutor", rule.felony_review_result
    for program in _values("DIVERSION_PROGRAM"):
        assert not RULES.diversion_program(program).fallback, program
    for result in _values("DIVERSION_RESULT"):
        assert not RULES.diversion_result(result).fallback, result
    assert RULES.diversion_result(None).event_type is None
    assert RULES.diversion_program("DDPP").stage == "pre_plea"
    assert RULES.diversion_program("DC").stage == "post_plea"
    for event in _values("EVENT"):
        charging = RULES.initiation_event(event)
        assert charging is not None and charging.event_type is not None, event
    for flag in _values("FINDING_NO_PROBABLE_CAUSE"):
        assert RULES.no_probable_cause(flag) is not None
    assert RULES.no_probable_cause(None) is None


def test_the_versions_are_pinned_in_the_code_and_the_manifest() -> None:
    manifest = yaml.safe_load((TABLES_DIR / cook_rules.TABLES_FILE).read_text(encoding="utf-8"))
    assert set(manifest["tables"]) == set(RULE_VERSIONS) == set(TABLE_FILES)
    for name, entry in manifest["tables"].items():
        assert entry["version"] == RULE_VERSIONS[name] == RULES.versions[name]
        assert entry["file"] == TABLE_FILES[name]
        data = (TABLES_DIR / entry["file"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry["sha256"] == RULES.digests[name]
        assert b"\r" not in data
    assert RULE_VERSION_TAG == ".".join(str(RULE_VERSIONS[name]) for name in TABLE_FILES)
    assert re.fullmatch(r"\d+(\.\d+){6}", RULE_VERSION_TAG)


def test_every_table_loads_through_a_safe_reader() -> None:
    source = Path(cook_rules.__file__).read_text(encoding="utf-8")
    assert "yaml.safe_load(" in source and "csv.DictReader(" in source
    assert not re.search(r"\byaml\.(load|unsafe_load|full_load)\(", source)
    assert not re.search(r"\b(eval|exec|pickle)\b", source)
    assert source.startswith("# src/judgemetrics/ingest/cook_sao/rules.py\n")


def test_a_tampered_table_is_refused_naming_the_file_key_and_field(tmp_path: Path) -> None:
    directory = _copy_tables(tmp_path)
    assert isinstance(parse_rules(directory), CookSaoRules)
    text = (directory / TABLE_FILES["attribution_rules"]).read_text(encoding="utf-8")

    # A value outside the vocabulary, with its digest re-pinned: the field is named.
    _rewrite(
        directory,
        "attribution_rules",
        text.replace("actor_type: prosecutor", "actor_type: bailiff", 1),
    )
    with pytest.raises(
        RuleError, match=r"attribution_rules\.yaml: dispositions\[0\]: field 'actor_type'"
    ):
        parse_rules(directory)

    # A judge given a prosecutor's non-judicial classification is caught too.
    _rewrite(
        directory,
        "attribution_rules",
        text.replace(
            "    judicial_discretion_classification: non_judicial\n",
            "    judicial_discretion_classification: discretionary\n",
            1,
        ),
    )
    with pytest.raises(RuleError, match="field 'judicial_discretion_classification'"):
        parse_rules(directory)

    # A non-final value marked final contradicts the vocabulary's finality.
    _rewrite(
        directory,
        "attribution_rules",
        text.replace(
            "disposition: superseded\n    final: false", "disposition: superseded\n    final: true"
        ),
    )
    with pytest.raises(RuleError, match="field 'final'"):
        parse_rules(directory)

    # An edit without a new digest is refused by the manifest.
    _rewrite(directory, "attribution_rules", text + "\n", pin=False)
    with pytest.raises(RuleError, match=r"tables\.yaml: attribution_rules: field 'sha256'"):
        parse_rules(directory)

    # A version bump in the table without one in the code is refused.
    _rewrite(directory, "attribution_rules", text)
    parse_rules(directory)
    manifest = directory / cook_rules.TABLES_FILE
    pinned = manifest.read_text(encoding="utf-8")
    manifest.write_text(
        pinned.replace(
            "file: attribution_rules.yaml\n    version: 1",
            "file: attribution_rules.yaml\n    version: 2",
        ),
        encoding="utf-8",
        newline="\n",
    )
    with pytest.raises(RuleError, match=r"tables\.yaml: attribution_rules: field 'version'"):
        parse_rules(directory)
    manifest.write_text(pinned, encoding="utf-8", newline="\n")

    # An unknown field, and a path that is not the module constant's.
    _rewrite(
        directory,
        "attribution_rules",
        text.replace("unknown_reason:", "notes: x\nunknown_reason:", 1),
    )
    with pytest.raises(RuleError, match="field 'notes' is not a field of this table"):
        parse_rules(directory)
    _rewrite(directory, "attribution_rules", text)
    manifest.write_text(
        pinned.replace("file: attribution_rules.yaml", "file: ../attribution_rules.yaml"),
        encoding="utf-8",
        newline="\n",
    )
    with pytest.raises(RuleError, match="field 'file' must be 'attribution_rules.yaml'"):
        parse_rules(directory)
