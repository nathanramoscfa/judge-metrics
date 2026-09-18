# tests/unit/test_synthetic_connector.py
"""The synthetic connector: schema, discovery, parsing, and normalization over the golden fixture."""

from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import SecretStr

from judgemetrics.config import Settings
from judgemetrics.db.models.enums import ActorType
from judgemetrics.ingest.base import (
    CanonicalRecord,
    CaseDraft,
    CasePartyDraft,
    ChargeDraft,
    CourtDraft,
    CourtEventDraft,
    DecisionDraft,
    FetchError,
    JudgeAssignmentDraft,
    JudgeDraft,
    JudgeServiceDraft,
    JurisdictionDraft,
    JusticeEventDraft,
    NormalizationError,
    PersonDraft,
    RawArtifact,
    SentenceDraft,
    SourceArtifact,
    SupportsContext,
)
from judgemetrics.ingest.registry import get_connector, registered_sources
from judgemetrics.ingest.synthetic.connector import (
    ManifestDriftError,
    SyntheticConnector,
    check_relative_name,
    resolve_inside,
)
from judgemetrics.ingest.synthetic.normalize import SyntheticContext, normalize_record
from judgemetrics.ingest.synthetic.parse import parse_file
from judgemetrics.ingest.synthetic.schema import (
    EXPECTED_HEADERS,
    MANIFEST_FILE,
    PERSON_ATTRIBUTE_COLUMNS,
    SOURCE_FILES,
    artifact_id,
)
from judgemetrics.security.identifiers import IdentifierPepperMissingError
from judgemetrics.synthetic.generate import manifest_matches
from judgemetrics.synthetic.writer import SOURCE_FILES as WRITER_FILES
from judgemetrics.synthetic.writer import SOURCE_HEADERS

pytestmark = pytest.mark.unit

GOLDEN = Path(__file__).resolve().parents[1] / "fixtures" / "golden"
PEPPER = SecretStr("unit-test-pepper")
NOW = datetime(2026, 9, 17, 9, 0, tzinfo=UTC)
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _connector(dataset: Path = GOLDEN) -> SyntheticConnector:
    return SyntheticConnector(dataset, pepper=PEPPER)


def _raws(connector: SyntheticConnector) -> list[RawArtifact]:
    artifacts = asyncio.run(connector.discover())
    return [asyncio.run(connector.fetch(artifact)) for artifact in artifacts]


def _drafts(connector: SyntheticConnector) -> list[CanonicalRecord]:
    """Every draft of the dataset, produced the way the runner does it."""
    raws = _raws(connector)
    connector.load_context(raws)
    drafts: list[CanonicalRecord] = []
    for raw in raws:
        result = connector.validate_raw(raw)
        assert result.ok, result.errors
        for record in connector.parse(raw):
            drafts.extend(connector.normalize(record))
    return drafts


def _connector_context() -> SyntheticContext:
    connector = _connector()
    connector.load_context(_raws(connector))
    return connector.context


def _rows(name: str) -> list[dict[str, str]]:
    with (GOLDEN / "source" / name).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


# --- schema ---------------------------------------------------------------------------


def test_expected_headers_equal_the_generator_headers() -> None:
    assert SOURCE_FILES == WRITER_FILES
    assert EXPECTED_HEADERS == SOURCE_HEADERS
    for name in SOURCE_FILES:
        with (GOLDEN / "source" / name).open(encoding="utf-8", newline="") as handle:
            assert tuple(next(csv.reader(handle))) == EXPECTED_HEADERS[name]


def test_registered_with_synthetic_source_type_and_parser_version() -> None:
    connector = get_connector("synthetic")
    assert isinstance(connector, SyntheticConnector)
    assert connector.source_info.source_type == "synthetic"
    assert connector.source_info.terms_metadata["synthetic"] is True
    assert connector.source_info.terms_metadata["redistribution"] == "not_applicable"
    assert ("synthetic", "1") in [(s.source_id, s.parser_version) for s in registered_sources()]
    assert isinstance(connector, SupportsContext)


def test_constructor_needs_a_pepper(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JUDGEMETRICS_IDENTIFIER_PEPPER", raising=False)
    with pytest.raises(IdentifierPepperMissingError, match="JUDGEMETRICS_IDENTIFIER_PEPPER"):
        SyntheticConnector(GOLDEN, settings=Settings(env="test"))
    connector = SyntheticConnector(
        settings=Settings(env="test", identifier_pepper=PEPPER, synthetic_dir=GOLDEN)
    )
    assert connector.dataset_dir == GOLDEN


# --- discovery and fetch ---------------------------------------------------------------


def test_discover_lists_the_manifest_then_the_nine_files_and_never_truth() -> None:
    artifacts = asyncio.run(_connector().discover())
    ids = [artifact.external_id for artifact in artifacts]
    assert ids == [MANIFEST_FILE, *(artifact_id(name) for name in SOURCE_FILES)]
    assert not any("truth" in external_id for external_id in ids)
    assert all(artifact.source_id == "synthetic" for artifact in artifacts)
    assert artifacts[0].content_type == "application/json"
    assert all(artifact.content_type == "text/csv" for artifact in artifacts[1:])
    assert all(artifact.uri.startswith("file:") for artifact in artifacts)


def test_fetch_reads_bytes_from_disk_with_their_sha256() -> None:
    connector = _connector()
    for raw in _raws(connector):
        path = GOLDEN / Path(*raw.artifact.external_id.split("/"))
        assert raw.sha256 == hashlib.sha256(path.read_bytes()).hexdigest()
        assert raw.size_bytes == path.stat().st_size
        assert raw.response_headers["final_url"].startswith("file:")


def test_fetch_refuses_paths_outside_the_dataset(tmp_path: Path) -> None:
    connector = _connector(tmp_path)
    for bad in ("../manifest.json", "/etc/passwd", "source/../../x.csv", "", "source\\x.csv"):
        with pytest.raises(FetchError, match="plain relative path|escapes"):
            check_relative_name(bad) if bad != "source/../../x.csv" else resolve_inside(
                tmp_path, bad
            )
    with pytest.raises(FetchError, match="not found"):
        asyncio.run(
            connector.fetch(
                SourceArtifact("synthetic", "source/cases.csv", "file:///x", "text/csv")
            )
        )


# --- validation ------------------------------------------------------------------------


def _raw_for(name: str, data: bytes) -> RawArtifact:
    return RawArtifact.from_bytes(
        SourceArtifact("synthetic", name, "file:///x", "text/csv"), data, retrieved_at=NOW
    )


def test_missing_header_fails_naming_it_and_extra_header_warns() -> None:
    connector = _connector()
    rows = _rows("decisions.csv")
    out = io.StringIO()
    writer = csv.DictWriter(
        out, fieldnames=[h for h in EXPECTED_HEADERS["decisions.csv"] if h != "discretion"]
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({k: v for k, v in row.items() if k != "discretion"})
    result = connector.validate_raw(_raw_for("source/decisions.csv", out.getvalue().encode()))
    assert not result.ok
    assert result.errors == ["source/decisions.csv: missing expected header 'discretion'"]

    extra = "court_code,name,court_type,jurisdiction,state_code,motto\nC-1,X,circuit,Y,ZZ,m\n"
    result = connector.validate_raw(_raw_for("source/courts.csv", extra.encode()))
    assert result.ok
    assert result.warnings == ["source/courts.csv: header 'motto' is not in the expected set"]

    assert not connector.validate_raw(_raw_for("source/courts.csv", b"")).ok
    assert not connector.validate_raw(_raw_for("truth/persons.csv", b"a,b\n")).ok


def test_manifest_validation_checks_generator_version_and_listed_files() -> None:
    connector = _connector()
    manifest = json.loads((GOLDEN / MANIFEST_FILE).read_text(encoding="utf-8"))
    ok = connector.validate_raw(_raw_for(MANIFEST_FILE, json.dumps(manifest).encode()))
    assert ok.ok and ok.warnings == []

    stale = dict(manifest, generator_version="0")
    result = connector.validate_raw(_raw_for(MANIFEST_FILE, json.dumps(stale).encode()))
    assert not result.ok and "generator_version '0'" in result.errors[0]

    short = dict(manifest, files={k: v for k, v in manifest["files"].items() if "cases" not in k})
    result = connector.validate_raw(_raw_for(MANIFEST_FILE, json.dumps(short).encode()))
    assert not result.ok and "'source/cases.csv' is not listed" in result.errors[0]

    result = connector.validate_raw(_raw_for(MANIFEST_FILE, b"not json"))
    assert not result.ok and "unreadable manifest" in result.errors[0]


def test_load_context_fails_on_manifest_drift(tmp_path: Path) -> None:
    connector = _connector()
    raws = _raws(connector)
    edited = tmp_path / "cases.csv"
    edited.write_bytes((GOLDEN / "source" / "cases.csv").read_bytes() + b"\n")
    drifted = [
        RawArtifact.from_path(raw.artifact, edited, retrieved_at=NOW)
        if raw.artifact.external_id == "source/cases.csv"
        else raw
        for raw in raws
    ]
    with pytest.raises(ManifestDriftError, match="source/cases.csv: sha256 does not match"):
        connector.load_context(drifted)
    with pytest.raises(ManifestDriftError, match="manifest.json was not retrieved"):
        connector.load_context(raws[1:])


# --- parsing ----------------------------------------------------------------------------


def test_parse_projects_rows_to_the_expected_columns_as_strings() -> None:
    data = (GOLDEN / "source" / "participants.csv").read_bytes()
    records = list(parse_file("participants.csv", data))
    assert len(records) == 63
    first = records[0]
    assert first.record_type == "participants"
    assert first.external_record_id == "PT-000001"
    assert tuple(first.payload) == EXPECTED_HEADERS["participants.csv"]
    assert all(isinstance(value, str) for value in first.payload.values())
    # The duplicate copy's trailing whitespace is trimmed at parse time.
    copy = next(r for r in records if r.payload["case_number"] == "syn 2019 000005")
    assert copy.payload["full_name"] == copy.payload["full_name"].strip()


# --- normalization over the golden fixture -------------------------------------------------


@pytest.fixture(scope="module")
def golden_drafts() -> list[CanonicalRecord]:
    return _drafts(_connector())


def test_draft_counts_per_type(golden_drafts: list[CanonicalRecord]) -> None:
    counts = Counter(type(draft).__name__ for draft in golden_drafts)
    manifest = json.loads((GOLDEN / MANIFEST_FILE).read_text(encoding="utf-8"))["counts"]
    assert counts["JurisdictionDraft"] == counts["CourtDraft"] == manifest["source/courts.csv"]
    assert counts["JudgeDraft"] == counts["JudgeServiceDraft"] == manifest["source/judges.csv"]
    assert counts["CaseDraft"] == manifest["source/cases.csv"] == 63
    assert counts["PersonDraft"] == counts["CasePartyDraft"] == manifest["source/participants.csv"]
    assert counts["ChargeDraft"] == manifest["source/charges.csv"]
    assert counts["JudgeAssignmentDraft"] == manifest["source/assignments.csv"]
    assert counts["CourtEventDraft"] == manifest["source/events.csv"]
    assert counts["DecisionDraft"] == manifest["source/decisions.csv"]
    assert counts["SentenceDraft"] == manifest["source/sentences.csv"]
    assert counts["JusticeEventDraft"] > 0


def test_planted_duplicates_collapse_onto_one_case_key(
    golden_drafts: list[CanonicalRecord],
) -> None:
    cases = [draft for draft in golden_drafts if isinstance(draft, CaseDraft)]
    keys = Counter(case.natural_key for case in cases)
    duplicated = {key for key, count in keys.items() if count == 2}
    assert len(duplicated) == 3
    assert len(keys) == 60
    for key in duplicated:
        spellings = {case.case_number for case in cases if case.natural_key == key}
        assert len(spellings) == 2
    # The same holds for the duplicate copies' persons, parties, and child rows.
    persons = Counter(d.natural_key for d in golden_drafts if isinstance(d, PersonDraft))
    assert len(persons) == 42
    parties = Counter(d.natural_key for d in golden_drafts if isinstance(d, CasePartyDraft))
    assert len(parties) == 60
    charges = Counter(d.natural_key for d in golden_drafts if isinstance(d, ChargeDraft))
    assert sum(charges.values()) - len(charges) == sum(
        1 for row in _rows("charges.csv") if row["case_number"].startswith("syn ")
    )


def test_reference_drafts(golden_drafts: list[CanonicalRecord]) -> None:
    jurisdictions = {d for d in golden_drafts if isinstance(d, JurisdictionDraft)}
    assert jurisdictions == {JurisdictionDraft("Synthetic State", "state", "ZZ")}
    courts = {d.natural_key: d for d in golden_drafts if isinstance(d, CourtDraft)}
    assert len(courts) == 3
    for court in courts.values():
        assert court.court_type == "circuit"
        assert court.state_code == "ZZ"
        assert set(court.external_ids) == {"synthetic_court_code"}
    judges = {d.natural_key: d for d in golden_drafts if isinstance(d, JudgeDraft)}
    assert len(judges) == 6
    j4 = judges[("judge", "synthetic_judge_code", "J-0004")]
    assert j4.external_ids == {"synthetic_judge_code": "J-0004"}
    assert j4.normalized_name == "cinnabar hornbill"
    assert j4.status == "active"  # transferred: the second service record is open
    assert judges[("judge", "synthetic_judge_code", "J-0001")].status == "active"
    ended = [code for code, active in _connector_context().judge_active.items() if not active]
    for code in ended:
        assert judges[("judge", "synthetic_judge_code", code)].status == "inactive"
    services = [d for d in golden_drafts if isinstance(d, JudgeServiceDraft)]
    assert {s.position_type for s in services} <= {"circuit_judge", "associate_judge"}
    assert all(s.judge_key in judges and s.court_key in courts for s in services)


def test_person_drafts_carry_hashes_only(golden_drafts: list[CanonicalRecord]) -> None:
    persons = [d for d in golden_drafts if isinstance(d, PersonDraft)]
    for person in persons:
        assert person.identity[0] == "source_participant_id"
        assert set(person.identifier_hashes) <= {
            "source_participant_id",
            "full_name",
            "date_of_birth",
            "name_dob",
        }
        assert all(HEX64.match(value) for value in person.identifier_hashes.values())
        assert person.birth_year_known == ("date_of_birth" in person.identifier_hashes)
        assert ("name_dob" in person.identifier_hashes) == person.birth_year_known
    missing_dob = [p for p in persons if not p.birth_year_known]
    # Two planted missing_dob persons plus the ambiguous pair with a blanked date.
    assert len({p.natural_key for p in missing_dob}) == 3
    rendered = repr(persons)
    for row in _rows("participants.csv"):
        assert row["full_name"].strip() not in rendered
        assert row["date_of_birth"] not in rendered or not row["date_of_birth"]
    parties = [d for d in golden_drafts if isinstance(d, CasePartyDraft)]
    assert all(p.source_party_label == "defendant" for p in parties)
    assert all(p.person_key is not None for p in parties)


def test_charge_decision_and_event_drafts(golden_drafts: list[CanonicalRecord]) -> None:
    charges = [d for d in golden_drafts if isinstance(d, ChargeDraft)]
    assert {c.disposition for c in charges} <= {
        None,
        "dismissed",
        "acquitted",
        "convicted_plea",
        "convicted_verdict",
        "pending",
    }
    assert {c.disposition_actor for c in charges if c.disposition_actor} == {
        ActorType.JUDGE,
        ActorType.PROSECUTOR,
        ActorType.JURY,
    }
    assert all(c.filed_at.tzinfo is not None for c in charges)
    assert sum(1 for c in charges if c.disposition is None and c.source_row_id != "") == 2 + sum(
        1
        for row in _rows("charges.csv")
        if row["disposition"] == "" and row["case_number"][0] == "s"
    )

    decisions = [d for d in golden_drafts if isinstance(d, DecisionDraft)]
    pretrial = [d for d in decisions if d.decision_type == "pretrial_release"]
    assert all(d.pretrial is not None for d in pretrial)
    assert all(d.pretrial is None for d in decisions if d.decision_type != "pretrial_release")
    statutory = [d for d in pretrial if d.pretrial and d.pretrial.release_type == "statutory"]
    assert statutory and all(
        d.actor_type is ActorType.LEGISLATURE_OR_MANDATORY_RULE
        and d.judicial_discretion_classification == "mandatory"
        and d.judge_key is None
        for d in statutory
    )
    prosecutor = [d for d in decisions if d.actor_type is ActorType.PROSECUTOR]
    assert prosecutor and all(
        d.decision_type == "dismissal"
        and d.judicial_discretion_classification == "non_judicial"
        and d.judge_key is None
        for d in prosecutor
    )
    unknown = [d for d in decisions if d.actor_type is ActorType.UNKNOWN]
    assert {d.source_row_id for d in unknown} == {"DC-000025", "DC-000038", "DC-000062"}
    assert all(d.judicial_discretion_classification == "unknown" for d in unknown)
    bonded = next(d for d in pretrial if d.pretrial and d.pretrial.bond_amount)
    assert bonded.decision_value == {"release_type": "monetary_bond", "detained": False} or (
        bonded.decision_value["release_type"] == "monetary_bond"
    )
    with_conditions = next(d for d in pretrial if d.pretrial and d.pretrial.conditions)
    assert set(with_conditions.pretrial.conditions.values()) == {True}  # type: ignore[union-attr]

    events = [d for d in golden_drafts if isinstance(d, CourtEventDraft)]
    assert sum(1 for e in events if e.description is None) == 4  # planted missing_description
    fta = [e for e in events if e.event_type == "failure_to_appear"]
    assert fta and all(e.actor_type is ActorType.DEFENSE for e in fta)

    sentences = [d for d in golden_drafts if isinstance(d, SentenceDraft)]
    assert all(set(s.components) <= {"incarceration", "probation", "fine"} for s in sentences)
    assignments = [d for d in golden_drafts if isinstance(d, JudgeAssignmentDraft)]
    assert all(a.confidence is not None for a in assignments)


def test_justice_events_are_derived(golden_drafts: list[CanonicalRecord]) -> None:
    events = {d.natural_key: d for d in golden_drafts if isinstance(d, JusticeEventDraft)}
    by_type = Counter(e.event_type for e in events.values())
    assert by_type["failure_to_appear"] == 2
    assert by_type["revocation"] == 1
    assert by_type["new_case"] > 0
    assert by_type["reconviction"] > 0
    assert set(by_type) == {"failure_to_appear", "revocation", "new_case", "reconviction"}
    # new_case: independently recounted from the charges file (one per later case).
    filings: dict[str, dict[str, datetime]] = {}
    for row in _rows("charges.csv"):
        case = f"{row['court_code']}:{row['case_number'].upper().replace(' ', '-')}"
        filed = datetime.fromisoformat(row["filed_at"])
        current = filings.setdefault(row["participant_id"], {})
        current[case] = min(current.get(case, filed), filed)
    expected_new_cases = sum(
        1
        for cases in filings.values()
        for case, filed in cases.items()
        if any(other < filed for key, other in cases.items() if key != case)
    )
    assert by_type["new_case"] == expected_new_cases
    assert all(e.related_case_key is not None for e in events.values())
    assert all(e.confidence is not None for e in events.values())


def test_unknown_values_reject_the_row() -> None:
    context = SyntheticContext()
    connector = _connector()
    connector.load_context(_raws(connector))
    context = connector.context
    good = next(iter(parse_file("cases.csv", (GOLDEN / "source" / "cases.csv").read_bytes())))
    assert normalize_record(context, PEPPER, good)
    bad = {**good.payload, "case_type": "infraction"}
    with pytest.raises(NormalizationError, match="case_type 'infraction'"):
        normalize_record(
            context, PEPPER, good.__class__(good.external_record_id, None, bad, "cases")
        )
    bad = {**good.payload, "court_code": "C-9999"}
    with pytest.raises(NormalizationError, match="unknown court code"):
        normalize_record(
            context, PEPPER, good.__class__(good.external_record_id, None, bad, "cases")
        )
    bad = {**good.payload, "filed_date": "yesterday"}
    with pytest.raises(NormalizationError, match="not an ISO date"):
        normalize_record(
            context, PEPPER, good.__class__(good.external_record_id, None, bad, "cases")
        )


def test_person_attribute_columns_never_reach_a_draft_field(
    golden_drafts: list[CanonicalRecord],
) -> None:
    assert PERSON_ATTRIBUTE_COLUMNS == {"full_name", "date_of_birth"}
    names = {row["full_name"].strip() for row in _rows("participants.csv")}
    dobs = {row["date_of_birth"] for row in _rows("participants.csv")} - {""}
    rendered = repr([d for d in golden_drafts if not isinstance(d, JudgeDraft)])
    assert not any(name in rendered for name in names)
    assert not any(dob in rendered for dob in dobs)


# --- the seed skip rule ------------------------------------------------------------------


def test_manifest_matches_the_golden_fixture_only_for_its_seed_and_scale(tmp_path: Path) -> None:
    assert manifest_matches(GOLDEN, 7, "golden")
    assert not manifest_matches(GOLDEN, 8, "golden")
    assert not manifest_matches(GOLDEN, 7, "demo")
    assert not manifest_matches(tmp_path, 7, "golden")
    (tmp_path / "manifest.json").write_text("{", encoding="utf-8")
    assert not manifest_matches(tmp_path, 7, "golden")
