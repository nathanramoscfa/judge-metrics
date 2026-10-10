# tests/unit/test_cook_sao_normalize.py
"""The Cook County connector's mapping, over the committed real-row fixture and small variants.

No database: ``load_context`` → ``parse`` → ``normalize`` over ``tests/fixtures/cook_sao``
(73 cases, 905 rows; the restricted and quasi-identifying columns blank), checking that each
natural key is drafted exactly once, that the rule tables are applied, that the party keys
are ordinals, that restricted values leave the connector only as ``PartyAttributeDraft``
vocabulary values, and that no participant id appears in a draft or a finding.
"""

from __future__ import annotations

import csv
import io
from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import SecretStr

from judgemetrics.db.models.enums import ActorType, IssueSeverity
from judgemetrics.ingest.base import (
    CanonicalRecord,
    CaseDraft,
    CasePartyDraft,
    ChargeDraft,
    CourtDraft,
    CourtEventDraft,
    DecisionDraft,
    JudgeDraft,
    JudgeServiceDraft,
    JurisdictionDraft,
    JusticeEventDraft,
    PartyAttributeDraft,
    PersonDraft,
    RawArtifact,
    SentenceDraft,
    SourceArtifact,
    SourceRecordDraft,
    utc_now,
)
from judgemetrics.ingest.cook_sao import findings as codes
from judgemetrics.ingest.cook_sao.case import statute_code
from judgemetrics.ingest.cook_sao.connector import CookSaoConnector
from judgemetrics.ingest.cook_sao.findings import Findings
from judgemetrics.ingest.cook_sao.frames import read_export
from judgemetrics.ingest.cook_sao.rules import RULE_VERSION_TAG, RULE_VERSIONS
from judgemetrics.ingest.cook_sao.schema import (
    COVERAGE_END,
    COVERAGE_START,
    DATASET_ORDER,
    VERIFIED_HEADERS,
)
from judgemetrics.ingest.cook_sao.sources import DATASETS
from judgemetrics.security.identifiers import hash_identifier

pytestmark = pytest.mark.unit

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "cook_sao"
PEPPER = SecretStr("unit-test-pepper-not-a-secret")  # pragma: allowlist secret


def artifacts(contents: Mapping[str, bytes]) -> list[RawArtifact]:
    return [
        RawArtifact.from_bytes(
            SourceArtifact("cook_sao", dataset.external_id, "x", "text/csv"),
            contents[dataset.external_id],
            retrieved_at=utc_now(),
        )
        for dataset in DATASETS
    ]


def fixture_bytes() -> dict[str, bytes]:
    return {
        dataset.external_id: (FIXTURES / dataset.external_id).read_bytes() for dataset in DATASETS
    }


@dataclass
class Normalized:
    drafts: list[CanonicalRecord]
    by_artifact: dict[str, list[CanonicalRecord]]
    seen: int
    findings: Findings
    issues: list[tuple[str, str, str]]


def normalize_all(contents: Mapping[str, bytes]) -> Normalized:
    connector = CookSaoConnector(pepper=PEPPER)
    raws = artifacts(contents)
    connector.load_context(raws)
    drafts: list[CanonicalRecord] = []
    by_artifact: dict[str, list[CanonicalRecord]] = {name: [] for name in DATASET_ORDER}
    seen = 0
    for raw in raws:
        for record in connector.parse(raw):
            seen += record.rows
            produced = list(connector.normalize(record))
            drafts.extend(produced)
            assert record.artifact_id is not None
            by_artifact[record.artifact_id].extend(produced)
    issues = [
        (issue.issue_code, issue.artifact_id or "", issue.description)
        for issue in connector.run_issues()
    ]
    return Normalized(drafts, by_artifact, seen, connector._findings, issues)


@pytest.fixture(scope="module")
def fixture_run() -> Normalized:
    return normalize_all(fixture_bytes())


def of_type[R](drafts: list[CanonicalRecord], kind: type[R]) -> list[R]:
    return [draft for draft in drafts if isinstance(draft, kind)]


def participant_ids() -> set[str]:
    ids: set[str] = set()
    for dataset in DATASETS:
        with (FIXTURES / dataset.external_id).open(encoding="utf-8", newline="") as handle:
            ids.update(row["CASE_PARTICIPANT_ID"].strip() for row in csv.DictReader(handle))
    return ids


# --- the connector's identity ------------------------------------------------------------


def test_the_parser_version_embeds_every_rule_tables_version() -> None:
    assert CookSaoConnector.parser_version == f"1+{RULE_VERSION_TAG}"
    assert RULE_VERSION_TAG == ".".join(str(RULE_VERSIONS[name]) for name in RULE_VERSIONS)


def test_the_source_documents_revocation_and_nothing_else() -> None:
    assert CookSaoConnector.source_info.observable_outcomes == ("revocation",)
    assert CookSaoConnector(pepper=PEPPER).coverage_window() == (COVERAGE_START, COVERAGE_END)
    assert (COVERAGE_START, COVERAGE_END) == (date(2011, 1, 1), date(2024, 12, 30))


# --- one draft per natural key ------------------------------------------------------------


def test_each_natural_key_is_drafted_exactly_once(fixture_run: Normalized) -> None:
    keys = Counter(draft.natural_key for draft in fixture_run.drafts)
    assert [key for key, count in keys.items() if count > 1] == []


def test_every_row_is_seen_once_and_the_drafts_are_the_expected_number(
    fixture_run: Normalized,
) -> None:
    assert fixture_run.seen == 15 + 156 + 616 + 116 + 2
    counts = Counter(type(draft).__name__ for draft in fixture_run.drafts)
    assert dict(counts) == {
        "JurisdictionDraft": 1,
        "CourtDraft": 7,
        "JudgeDraft": 47,
        "JudgeServiceDraft": 52,
        "CaseDraft": 73,
        "PersonDraft": 82,
        "CasePartyDraft": 82,
        "PartyAttributeDraft": 246,
        "ChargeDraft": 631,
        "CourtEventDraft": 83,
        "DecisionDraft": 60,
        "SentenceDraft": 61,
        "JusticeEventDraft": 1,
    }


def test_the_reference_drafts_are_the_county_the_courts_and_the_judges(
    fixture_run: Normalized,
) -> None:
    (jurisdiction,) = of_type(fixture_run.drafts, JurisdictionDraft)
    assert (jurisdiction.name, jurisdiction.type, jurisdiction.state_code) == (
        "Cook County, Illinois",
        "county",
        "IL",
    )
    assert jurisdiction.fips_code == "17031"
    courts = of_type(fixture_run.drafts, CourtDraft)
    assert {court.court_type for court in courts} == {"circuit", "municipal_district"}
    assert sum(court.court_type == "municipal_district" for court in courts) == 6
    judges = of_type(fixture_run.drafts, JudgeDraft)
    assert all(judge.identity_key[0] == "cook_sao_judge" for judge in judges)
    assert all(judge.external_ids == {"cook_sao_judge": judge.identity_key[1]} for judge in judges)
    services = of_type(fixture_run.drafts, JudgeServiceDraft)
    assert all(service.metadata["derived"] is True for service in services)
    assert all(service.position_type == "unstated" for service in services)
    judge_keys = {judge.natural_key for judge in judges}
    assert {service.judge_key for service in services} <= judge_keys


def test_every_draft_is_attributed_to_the_export_it_comes_from(fixture_run: Normalized) -> None:
    by = fixture_run.by_artifact
    assert all(isinstance(d, SentenceDraft | JusticeEventDraft) for d in by["sentencing.csv"])
    assert {type(d) for d in by["diversion.csv"]} <= {DecisionDraft, CourtEventDraft}
    assert any(isinstance(d, ChargeDraft) for d in by["dispositions.csv"])
    assert any(isinstance(d, ChargeDraft) for d in by["initiation.csv"])
    assert any(isinstance(d, DecisionDraft) for d in by["initiation.csv"])
    assert any(isinstance(d, CaseDraft) for d in by["intake.csv"])
    assert any(isinstance(d, JurisdictionDraft) for d in by["dispositions.csv"])


# --- cases, courts, parties -----------------------------------------------------------------


def case_by_number(drafts: list[CanonicalRecord], number: str) -> CaseDraft:
    return next(c for c in of_type(drafts, CaseDraft) if c.case_number == number)


def test_a_case_takes_its_one_district_else_the_parent_court(fixture_run: Normalized) -> None:
    case = case_by_number(fixture_run.drafts, "164216912897")
    assert case.court_key == (
        "court",
        "Circuit Court of Cook County, Second Municipal District",
        "municipal_district",
    )
    assert case.case_type == "felony" and case.related_case_number_normalized is None
    # PROMIS conversion cases name no district: the parent court takes them.
    promis = case_by_number(fixture_run.drafts, "130891024591")
    assert promis.court_key == ("court", "Circuit Court of Cook County", "circuit")


def test_the_filing_date_is_the_earliest_received_date_and_status_follows_the_charges(
    fixture_run: Normalized,
) -> None:
    closed = case_by_number(fixture_run.drafts, "164216912897")
    assert closed.filed_date == date(2005, 7, 29) and closed.status == "closed"
    assert closed.closed_date == date(2011, 3, 24)
    # An open case: an Initiation row and no Dispositions row.
    open_case = case_by_number(fixture_run.drafts, "208406191741")
    assert open_case.status == "open" and open_case.closed_date is None


def test_parties_are_keyed_by_ordinal_in_code_point_order_of_the_participant_ids(
    fixture_run: Normalized,
) -> None:
    case = case_by_number(fixture_run.drafts, "331993083190")
    parties = [
        p for p in of_type(fixture_run.drafts, CasePartyDraft) if p.case_key[-1] == case.case_number
    ]
    assert sorted(p.source_row_id for p in parties) == ["defendant:1", "defendant:2"]
    persons = {p.natural_key: p for p in of_type(fixture_run.drafts, PersonDraft)}
    rows = list(csv.DictReader(io.StringIO((FIXTURES / "intake.csv").read_text(encoding="utf-8"))))
    ids = sorted({r["CASE_PARTICIPANT_ID"].strip() for r in rows if r["CASE_ID"] == "331993083190"})
    hashes = [hash_identifier(PEPPER, "source_participant_id", i, source="cook_sao") for i in ids]
    ordered = {p.source_row_id: p.person_key for p in parties}
    first, second = ordered["defendant:1"], ordered["defendant:2"]
    assert first is not None and second is not None
    assert [first[2], second[2]] == hashes
    assert all(key in persons for key in ordered.values() if key is not None)


def test_a_person_is_the_source_qualified_hash_and_carries_no_name_or_date(
    fixture_run: Normalized,
) -> None:
    persons = of_type(fixture_run.drafts, PersonDraft)
    assert len(persons) == len(participant_ids()) == 82
    expected = {
        hash_identifier(PEPPER, "source_participant_id", i, source="cook_sao")
        for i in participant_ids()
    }
    assert {p.identity[1] for p in persons} == expected
    assert all(set(p.identifier_hashes) == {"source_participant_id"} for p in persons)
    assert all(p.birth_year_known is False for p in persons)


# --- restricted attributes -----------------------------------------------------------------------


def test_restricted_values_leave_the_connector_only_as_party_attribute_drafts(
    fixture_run: Normalized,
) -> None:
    attributes = of_type(fixture_run.drafts, PartyAttributeDraft)
    assert Counter(a.attribute for a in attributes) == {"race": 82, "gender": 82, "age_band": 82}
    # The fixture's restricted columns are blank: every value is the explicit unknown.
    assert {a.value for a in attributes} == {"unknown"}
    assert all("unknown" not in repr(a) for a in attributes), "repr withholds the value"
    for draft in fixture_run.drafts:
        if not isinstance(draft, PartyAttributeDraft):
            assert not hasattr(draft, "race") and not hasattr(draft, "gender")


def with_restricted_values(contents: Mapping[str, bytes]) -> dict[str, bytes]:
    """The fixture with vocabulary values written into the blank restricted columns."""
    out: dict[str, bytes] = {}
    for name, data in contents.items():
        rows = list(csv.DictReader(io.StringIO(data.decode("utf-8"))))
        headers = list(rows[0])
        for row in rows:
            if "RACE" in row:
                row["RACE"] = "Black"
            if "GENDER" in row:
                row["GENDER"] = "Female"
            if "AGE_AT_INCIDENT" in row:
                row["AGE_AT_INCIDENT"] = "40"
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=headers, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
        out[name] = buffer.getvalue().encode("utf-8")
    return out


def test_vocabulary_values_in_the_restricted_columns_become_attribute_drafts() -> None:
    run = normalize_all(with_restricted_values(fixture_bytes()))
    values = Counter((a.attribute, a.value) for a in of_type(run.drafts, PartyAttributeDraft))
    assert values == {("race", "black"): 82, ("gender", "female"): 82, ("age_band", "35-44"): 82}
    text = "".join(repr(d) for d in run.drafts) + "".join(desc for _, _, desc in run.issues)
    assert "Female" not in text and "black" not in text and "35-44" not in text


def test_unlisted_restricted_labels_and_bad_ages_are_findings_not_values() -> None:
    data = fixture_bytes()
    rows = list(csv.DictReader(io.StringIO(data["intake.csv"].decode("utf-8"))))
    headers = list(rows[0])
    rows[0]["RACE"] = "Not A Listed Label"
    rows[0]["AGE_AT_INCIDENT"] = "forty"
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=headers, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    data["intake.csv"] = buffer.getvalue().encode("utf-8")
    run = normalize_all(data)
    by_code = {code: desc for code, _, desc in run.issues}
    assert codes.RESTRICTED_VALUE_UNLISTED in by_code and codes.INVALID_AGE in by_code
    text = "".join(by_code.values()) + "".join(repr(d) for d in run.drafts)
    assert "Not A Listed Label" not in text and "forty" not in text
    assert run.findings.rejected_rows() == 0


# --- charges, dispositions, judges ---------------------------------------------------------------------


def charges_of(drafts: list[CanonicalRecord], number: str) -> list[ChargeDraft]:
    return [c for c in of_type(drafts, ChargeDraft) if c.case_key[-1] == number]


def test_a_prosecutors_nolle_is_a_prosecutor_dismissal_never_a_judicial_one(
    fixture_run: Normalized,
) -> None:
    for charge in of_type(fixture_run.drafts, ChargeDraft):
        if charge.disposition == "dismissed" and charge.disposition_actor is ActorType.PROSECUTOR:
            return
    pytest.fail("no prosecutor dismissal in the fixture")


def test_a_plea_is_a_discretionary_conviction_with_a_plea_hearing_event(
    fixture_run: Normalized,
) -> None:
    pleas = [
        c for c in of_type(fixture_run.drafts, ChargeDraft) if c.disposition == "convicted_plea"
    ]
    assert pleas and all(c.disposition_actor is ActorType.JUDGE for c in pleas)
    events = of_type(fixture_run.drafts, CourtEventDraft)
    assert any(e.event_type == "plea_hearing" for e in events)


def test_a_charge_keeps_its_participants_ordinal_and_the_charge_ids(
    fixture_run: Normalized,
) -> None:
    for charge in of_type(fixture_run.drafts, ChargeDraft):
        ordinal, charge_id, version_id = charge.source_row_id.split(":")
        assert ordinal.isdigit() and charge_id.isdigit() and version_id.isdigit()
        assert charge.filed_at.tzinfo is UTC
        assert charge.violent_flag is None


def test_an_amended_charge_is_published_once_by_its_latest_version(fixture_run: Normalized) -> None:
    # Case 358106755135: Initiation filed three charges; one reached Dispositions as a new version.
    charges = charges_of(fixture_run.drafts, "358106755135")
    assert len(charges) == 3
    assert any(
        code == codes.CHARGE_VERSION_REPLACED and "1 charge versions" in desc
        for code, _, desc in fixture_run.issues
    )


def test_the_disposing_judge_comes_from_the_alias_table(fixture_run: Normalized) -> None:
    charges = of_type(fixture_run.drafts, ChargeDraft)
    named = [c for c in charges if c.judge_key is not None]
    assert named and all(
        c.judge_key and c.judge_key[:2] == ("judge", "cook_sao_judge") for c in named
    )
    judge_keys = {j.natural_key for j in of_type(fixture_run.drafts, JudgeDraft)}
    assert {c.judge_key for c in named} <= judge_keys
    unresolved = [
        (code, desc) for code, _, desc in fixture_run.issues if code == codes.JUDGE_UNRESOLVED
    ]
    assert len(unresolved) == 1 and "Sutker" in unresolved[0][1]
    assert "1 rows are published without a judge" in unresolved[0][1]


# --- decisions, events, sentences ------------------------------------------------------------------------


def test_a_bond_is_one_decision_per_participant_with_no_judge_and_no_claimed_release(
    fixture_run: Normalized,
) -> None:
    bonds = [
        d
        for d in of_type(fixture_run.drafts, DecisionDraft)
        if d.decision_type == "pretrial_release"
    ]
    assert len(bonds) == 8 and all(b.source_row_id.startswith("bond:") for b in bonds)
    assert all(b.judge_key is None and b.judge_not_recorded for b in bonds)
    assert all(b.pretrial is not None for b in bonds)
    for bond in bonds:
        assert bond.pretrial is not None
        if bond.pretrial.release_type != "recognizance":
            assert bond.pretrial.release_at is None, "a deposit or cash bond claims no release"
        assert bond.pretrial.detained_flag == (bond.pretrial.release_type == "detained")
    amounts = [b.pretrial.bond_amount for b in bonds if b.pretrial and b.pretrial.bond_amount]
    assert all(isinstance(a, Decimal) for a in amounts)


def test_the_charging_and_diversion_decisions_are_the_prosecutors_or_unknown(
    fixture_run: Normalized,
) -> None:
    decisions = of_type(fixture_run.drafts, DecisionDraft)
    charging = [d for d in decisions if d.decision_type == "charging"]
    assert charging and all(d.actor_type is ActorType.PROSECUTOR for d in charging)
    assert all(
        d.decision_value["outcome"] in {"approved", "rejected", "continued"} for d in charging
    )
    diversion = [d for d in decisions if d.decision_type == "diversion"]
    assert len(diversion) == 2
    assert {d.decision_value["program"] for d in diversion} == {"DS", "VC"}


def test_a_diversion_graduation_is_a_court_event(fixture_run: Normalized) -> None:
    events = of_type(fixture_run.drafts, CourtEventDraft)
    assert [e.event_type for e in events if e.event_type.startswith("diversion_")] == [
        "diversion_completed"
    ]


def test_sentences_carry_days_flags_and_their_phase(fixture_run: Normalized) -> None:
    sentences = of_type(fixture_run.drafts, SentenceDraft)
    phases = Counter(s.components["phase"] for s in sentences)
    assert phases["original"] > 0 and phases["probation_violation"] > 0
    life = [s for s in sentences if any("life" in term["flags"] for term in s.components["terms"])]
    assert life and all(s.incarceration_days is None or s.incarceration_days > 0 for s in life)
    assert all(s.fine_amount is None for s in sentences)
    for sentence in sentences:
        assert set(sentence.components) == {
            "phase",
            "current",
            "superseded",
            "replaced",
            "components",
            "terms",
        }
        assert sentence.sentence_at.tzinfo is UTC


def test_only_a_correction_replaces_a_sentence(fixture_run: Normalized) -> None:
    """sentence_rules version 2: an amended or corrected sentencing replaces what it follows.

    A replaced sentence is superseded too, and its participant has a later amended
    sentencing in the case; a probation-violation, resentencing, or remand sentencing
    supersedes the sentence it follows without replacing it (two decisions).
    """
    sentences = of_type(fixture_run.drafts, SentenceDraft)
    replaced = [s for s in sentences if s.components["replaced"]]
    assert replaced, "the fixture holds an amended sentencing that replaces an earlier one"
    for sentence in replaced:
        assert sentence.components["superseded"]
        assert any(
            other.components["phase"] == "amended"
            and other.person_key == sentence.person_key
            and other.case_key == sentence.case_key
            and other.sentence_at >= sentence.sentence_at
            for other in sentences
        )
    superseded_only = [
        s for s in sentences if s.components["superseded"] and not s.components["replaced"]
    ]
    assert superseded_only, "a sentence superseded by a non-correcting phase stays a decision"


def test_a_probation_violation_sentencing_is_a_within_case_revocation(
    fixture_run: Normalized,
) -> None:
    (event,) = of_type(fixture_run.drafts, JusticeEventDraft)
    assert event.event_type == "revocation"
    assert event.related_case_key is not None and event.related_case_key[0] == "case"
    sentences = [
        s
        for s in of_type(fixture_run.drafts, SentenceDraft)
        if s.components["phase"] == "probation_violation" and s.person_key == event.person_key
    ]
    assert sentences and sentences[0].sentence_at == event.event_at


# --- findings and secrecy ------------------------------------------------------------------------------------


def test_the_findings_of_the_fixture(fixture_run: Normalized) -> None:
    by_key = {
        (code, artifact, desc.split(":")[0] if False else desc)
        for code, artifact, desc in fixture_run.issues
    }
    codes_found = Counter(code for code, _, _ in fixture_run.issues)
    assert codes_found == {
        codes.BOND_NOT_DRAFTED: 1,
        codes.CHARGE_VERSION_REPLACED: 1,
        codes.JUDGE_UNRESOLVED: 1,
        codes.RECEIVED_BEFORE_COVERAGE: 10,
        codes.SENTENCE_TERM_FLAGGED: 4,
    }
    assert len(by_key) == len(fixture_run.issues)
    before = [d for c, _, d in fixture_run.issues if c == codes.RECEIVED_BEFORE_COVERAGE]
    assert sum(int(d.split()[0]) for d in before) == 63
    assert fixture_run.findings.rejected_rows() == 0


def test_no_participant_id_appears_in_a_draft_or_a_finding(fixture_run: Normalized) -> None:
    text = "".join(repr(d) for d in fixture_run.drafts)
    text += "".join(f"{code}|{artifact}|{desc}" for code, artifact, desc in fixture_run.issues)
    text += "".join(d.natural_key.__repr__() for d in fixture_run.drafts)
    leaked = [i for i in participant_ids() if i in text]
    assert leaked == []


def test_every_finding_has_a_severity_and_names_no_row() -> None:
    for code, (severity, template, _) in codes.TEMPLATES.items():
        assert isinstance(severity, IssueSeverity) and "{" in template, code
    with pytest.raises(KeyError):
        Findings().add("not_a_finding")


# --- reading the exports -----------------------------------------------------------------------------------------


def test_dates_out_of_range_or_not_dates_are_nulled_and_counted() -> None:
    header = ",".join(VERIFIED_HEADERS["intake.csv"])
    columns = list(VERIFIED_HEADERS["intake.csv"])

    def line(**values: str) -> str:
        row = dict.fromkeys(columns, "")
        row.update(values)
        return ",".join(row[c] for c in columns)

    text = "\n".join(
        [
            header,
            line(CASE_ID="1", CASE_PARTICIPANT_ID=" 7 ", RECEIVED_DATE="03/04/2015"),
            line(CASE_ID="2", CASE_PARTICIPANT_ID="8", RECEIVED_DATE="07/22/2924 12:00:00 AM"),
            line(CASE_ID="3", CASE_PARTICIPANT_ID="9", RECEIVED_DATE="13/45/2016"),
            line(CASE_ID="4", CASE_PARTICIPANT_ID="10", RECEIVED_DATE="01/01/1850"),
            line(CASE_ID="5", CASE_PARTICIPANT_ID="", RECEIVED_DATE="03/04/2015"),
        ]
    )
    findings = Findings()
    frame = read_export(text.encode("utf-8"), "intake.csv", findings)
    assert frame.height == 4  # the row without a participant is dropped and counted
    rows = {r["CASE_ID"]: r for r in frame.iter_rows(named=True)}
    assert rows["1"]["CASE_PARTICIPANT_ID"] == "7"
    assert rows["1"]["RECEIVED_DATE"] == datetime(2015, 3, 4)
    assert rows["2"]["RECEIVED_DATE"] is None and rows["3"]["RECEIVED_DATE"] is None
    assert rows["4"]["RECEIVED_DATE"] is None
    assert findings.counts[(codes.DATE_AFTER_CORPUS_END, "intake.csv", "RECEIVED_DATE")] == 1
    assert findings.counts[(codes.UNPARSEABLE_DATE, "intake.csv", "RECEIVED_DATE")] == 2
    assert findings.counts[(codes.ROW_WITHOUT_KEY, "intake.csv", "CASE_PARTICIPANT_ID")] == 1


def test_an_unlisted_offense_category_rejects_the_charge_row_with_a_finding() -> None:
    data = fixture_bytes()
    text = data["initiation.csv"].decode("utf-8")
    assert "Aggravated Discharge Firearm" in text
    data["initiation.csv"] = text.replace(
        "Aggravated Discharge Firearm", "A Category No Table Lists"
    ).encode("utf-8")
    run = normalize_all(data)
    rejected = [d for code, _, d in run.issues if code == codes.UNMAPPED_VALUE]
    assert rejected and "A Category No Table Lists" in rejected[0]
    assert run.findings.rejected_rows() > 0
    assert len(of_type(run.drafts, ChargeDraft)) < 631


@pytest.mark.parametrize(
    ("chapter", "act", "section", "expected"),
    [
        ("720", "5", "24-1.2(a)(2)", "720 ILCS 5/24-1.2(a)(2)"),
        ("38", "-", "9-1(a)(2)", "38 9-1(a)(2)"),
        ("38-12-11-A(2)", None, None, "38-12-11-A(2)"),
        (None, None, None, None),
    ],
)
def test_statute_codes(
    chapter: str | None, act: str | None, section: str | None, expected: str | None
) -> None:
    assert statute_code(chapter, act, section) == expected


def test_parse_streams_the_corpus_once_per_run_and_a_new_context_starts_again() -> None:
    connector = CookSaoConnector(pepper=PEPPER)
    raws = artifacts(fixture_bytes())
    connector.load_context(raws)
    first = list(connector.parse(raws[0]))
    assert first and list(connector.parse(raws[1])) == []
    connector.load_context(raws)
    again = list(connector.parse(raws[0]))
    assert [r.rows for r in again] == [r.rows for r in first]


def test_records_name_the_export_their_drafts_belong_to() -> None:
    connector = CookSaoConnector(pepper=PEPPER)
    raws = artifacts(fixture_bytes())
    connector.load_context(raws)
    records: Iterator[SourceRecordDraft] = iter(connector.parse(raws[0]))
    reference = next(records)
    assert (reference.record_type, reference.artifact_id, reference.rows) == (
        "reference",
        "dispositions.csv",
        0,
    )
    rest = list(records)
    assert {r.artifact_id for r in rest} == set(DATASET_ORDER)
    assert all(r.record_type == r.artifact_id for r in rest)
