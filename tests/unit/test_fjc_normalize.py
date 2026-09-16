# tests/unit/test_fjc_normalize.py
"""FJC rows → canonical drafts: names, status, court types, state codes, dates."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from judgemetrics.ingest.base import (
    CourtDraft,
    JudgeDraft,
    JudgeServiceDraft,
    JurisdictionDraft,
    NormalizationError,
    SourceRecordDraft,
)
from judgemetrics.ingest.fjc.normalize import (
    FEDERAL_JURISDICTION,
    birth_year_metadata,
    court_type_for,
    judge_draft,
    judge_status,
    normalize_record,
    parse_fjc_date,
    service_drafts,
    service_groups,
    state_code_for_court,
)
from judgemetrics.ingest.fjc.schema import (
    COURT_TYPES,
    RECORD_TYPE_JUDGE,
    RECORD_TYPE_SERVICE,
    group_header,
)

pytestmark = pytest.mark.unit


def _judge_payload(
    groups: list[dict[str, str]] | None = None, /, **identity: str
) -> dict[str, str]:
    payload = {
        "nid": "1377101",
        "jid": "42",
        "Last Name": "Alito",
        "First Name": "Samuel",
        "Middle Name": "A.",
        "Suffix": "Jr.",
        "Birth Year": "1950",
    }
    payload.update(identity)
    for index, group in enumerate(groups or [], start=1):
        for field, value in group.items():
            payload[group_header(field, index)] = value
    return payload


def _service_payload(**overrides: str) -> dict[str, str]:
    payload = {
        "nid": "1377101",
        "Sequence": "2",
        "Judge Name": "Alito, Samuel A., Jr.",
        "Court Type": "Supreme Court",
        "Court Name": "Supreme Court of the United States",
        "Appointment Title": "Associate Justice",
        "Recess Appointment Date": "",
        "Commission Date": "2006-01-31",
        "Senior Status Date": "",
        "Termination": "",
        "Termination Date": "",
    }
    payload.update(overrides)
    return payload


def test_judge_draft_maps_identity_and_name() -> None:
    draft = judge_draft(
        _judge_payload(
            [
                {
                    "Court Name": "U.S. Court of Appeals for the Third Circuit",
                    "Commission Date": "1990-04-30",
                    "Termination": "Appointment to Another Judicial Position",
                },
                {
                    "Court Name": "Supreme Court of the United States",
                    "Commission Date": "2006-01-31",
                },
            ]
        )
    )
    assert draft.canonical_name == "Samuel A. Alito, Jr."
    assert draft.normalized_name == "samuel a alito jr"
    assert draft.identity_key == ("fjc_nid", "1377101")
    assert draft.external_ids == {"fjc_nid": "1377101", "fjc_jid": "42"}
    assert draft.status == "active"
    assert draft.metadata == {"birth_year": 1950}
    assert draft.natural_key == ("judge", "fjc_nid", "1377101")


def test_judge_draft_ignores_blank_suffix_and_jid() -> None:
    draft = judge_draft(_judge_payload(**{"Suffix": " ", "jid": "", "Middle Name": ""}))
    assert draft.canonical_name == "Samuel Alito"
    assert draft.external_ids == {"fjc_nid": "1377101"}


def test_judge_draft_keeps_diacritics_in_canonical_and_folds_them_in_normalized() -> None:
    draft = judge_draft(
        _judge_payload(
            **{
                "Last Name": "Alarcón",
                "First Name": "Arthur",
                "Middle Name": "Lawrence",
                "Suffix": "",
            }
        )
    )
    assert draft.canonical_name == "Arthur Lawrence Alarcón"
    assert draft.normalized_name == "arthur lawrence alarcon"


def test_judge_draft_requires_nid() -> None:
    with pytest.raises(NormalizationError, match="nid"):
        judge_draft(_judge_payload(nid=""))


@pytest.mark.parametrize(
    ("groups", "expected"),
    [
        ([], "unknown"),
        ([{"Court Name": "X", "Commission Date": "2000-01-01"}], "active"),
        (
            [
                {
                    "Court Name": "X",
                    "Commission Date": "2000-01-01",
                    "Senior Status Date": "2015-01-01",
                }
            ],
            "senior",
        ),
        (
            [{"Court Name": "X", "Commission Date": "2000-01-01", "Termination": "Death"}],
            "deceased",
        ),
        (
            [{"Court Name": "X", "Commission Date": "2000-01-01", "Termination": "Retirement"}],
            "retired",
        ),
        (
            [{"Court Name": "X", "Commission Date": "2000-01-01", "Termination": "Resignation"}],
            "resigned",
        ),
        (
            [
                {
                    "Court Name": "X",
                    "Commission Date": "2000-01-01",
                    "Termination": "Impeachment & Conviction",
                }
            ],
            "removed",
        ),
        (
            [
                {
                    "Court Name": "X",
                    "Commission Date": "2000-01-01",
                    "Termination": "Recess Appointment-Not Confirmed",
                }
            ],
            "inactive",
        ),
        (
            [
                {
                    "Court Name": "X",
                    "Commission Date": "2000-01-01",
                    "Termination": "Abolition of Court",
                }
            ],
            "inactive",
        ),
        (
            [{"Court Name": "X", "Commission Date": "2000-01-01", "Termination": "Something New"}],
            "unknown",
        ),
        # The latest appointment decides, even when the file lists it first.
        (
            [
                {"Court Name": "Later", "Commission Date": "2006-01-31"},
                {
                    "Court Name": "Earlier",
                    "Commission Date": "1990-04-30",
                    "Termination": "Appointment to Another Judicial Position",
                },
            ],
            "active",
        ),
        # A pending appointment without dates does not hide a live earlier one.
        (
            [
                {"Court Name": "Serving", "Commission Date": "2010-01-01"},
                {"Court Name": "Pending"},
            ],
            "active",
        ),
        # A recess appointment date counts as the start.
        (
            [{"Court Name": "X", "Recess Appointment Date": "1949-10-21", "Termination": "Death"}],
            "deceased",
        ),
    ],
)
def test_judge_status_derivation(groups: list[dict[str, str]], expected: str) -> None:
    payload = _judge_payload(groups)
    assert judge_status(service_groups(payload, "judge 1")) == expected
    assert judge_draft(payload).status == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1950", {"birth_year": 1950}),
        ("ca. 1793", {"birth_year": 1793, "birth_year_approximate": True}),
        ("ca.1793", {"birth_year": 1793, "birth_year_approximate": True}),
        ("", {}),
        ("unknown", {}),
        ("19", {}),
    ],
)
def test_birth_year_metadata(raw: str, expected: dict[str, Any]) -> None:
    assert birth_year_metadata(raw) == expected


@pytest.mark.parametrize(("raw", "expected"), sorted(COURT_TYPES.items()))
def test_court_type_mapping_covers_every_verified_value(raw: str, expected: str) -> None:
    assert court_type_for(raw) == expected
    assert expected in {"district", "appeals", "supreme", "other"}


def test_unknown_court_type_maps_to_other() -> None:
    assert court_type_for("U.S. Court of Something New") == "other"
    assert court_type_for("") == "other"


@pytest.mark.parametrize(
    ("name", "court_type", "expected"),
    [
        ("U.S. District Court for the District of Maryland", "district", "MD"),
        ("U.S. District Court for the Southern District of New York", "district", "NY"),
        ("U.S. District Court for the Middle District of Florida", "district", "FL"),
        ("U.S. District Court for the District of California", "district", "CA"),
        ("U.S. District Court for the District of Columbia", "district", "DC"),
        (
            "U.S. District Court for the District of Columbia (Supreme Court of the District of Columbia)",
            "district",
            "DC",
        ),
        ("U.S. District Court for the District of Puerto Rico", "district", "PR"),
        (
            "U.S. District Court for the Albemarle, Cape Fear & Pamptico Districts of North Carolina",
            "district",
            "NC",
        ),
        ("U.S. District Court for the District of Orleans", "district", None),
        ("U.S. District Court for the District of the Canal Zone", "district", None),
        ("U.S. Circuit Court for the Districts of California", "other", None),
        ("U.S. Court of Appeals for the Ninth Circuit", "appeals", None),
        ("Supreme Court of the United States", "supreme", None),
        ("U.S. Court of International Trade", "other", None),
    ],
)
def test_state_code_parsed_from_district_court_names(
    name: str, court_type: str, expected: str | None
) -> None:
    assert state_code_for_court(name, court_type) == expected


def test_parse_fjc_date() -> None:
    assert parse_fjc_date("2006-01-31", column="Commission Date", record_id="r") == date(
        2006, 1, 31
    )
    assert parse_fjc_date("", column="Commission Date", record_id="r") is None
    assert parse_fjc_date("  ", column="Commission Date", record_id="r") is None
    with pytest.raises(NormalizationError, match="Commission Date"):
        parse_fjc_date("01/31/2006", column="Commission Date", record_id="r")
    with pytest.raises(NormalizationError, match="Termination Date"):
        parse_fjc_date("2006-02-30", column="Termination Date", record_id="r")


def test_service_drafts_from_commission_date() -> None:
    court, service = service_drafts(_service_payload())
    assert court == CourtDraft(
        canonical_name="Supreme Court of the United States",
        court_type="supreme",
        jurisdiction_key=FEDERAL_JURISDICTION.natural_key,
        external_ids={"fjc_court_name": "Supreme Court of the United States"},
        state_code=None,
    )
    assert service.judge_key == ("judge", "fjc_nid", "1377101")
    assert service.court_key == court.natural_key
    assert service.position_type == "Associate Justice"
    assert service.start_date == date(2006, 1, 31)
    assert service.end_date is None
    assert service.metadata == {"fjc_sequence": "2", "start_date_basis": "commission_date"}
    assert service.natural_key == (
        "judge_service",
        "fjc_nid",
        "1377101",
        "Supreme Court of the United States",
        "supreme",
        "Associate Justice",
        "2006-01-31",
    )


def test_service_drafts_fall_back_to_the_recess_appointment_date() -> None:
    _, service = service_drafts(
        _service_payload(
            **{
                "Court Type": "U.S. District Court",
                "Court Name": "U.S. District Court for the Northern District of Georgia",
                "Appointment Title": "Judge",
                "Recess Appointment Date": "1949-10-21",
                "Commission Date": "",
                "Termination": "Recess Appointment-Not Confirmed",
                "Termination Date": "1950-10-31",
            }
        )
    )
    assert service.start_date == date(1949, 10, 21)
    assert service.end_date == date(1950, 10, 31)
    assert service.metadata["start_date_basis"] == "recess_appointment_date"
    assert service.metadata["termination"] == "Recess Appointment-Not Confirmed"


def test_service_drafts_without_any_start_date() -> None:
    _, service = service_drafts(_service_payload(**{"Commission Date": ""}))
    assert service.start_date is None
    assert "start_date_basis" not in service.metadata
    assert service.natural_key[-1] == ""


def test_service_drafts_carry_senior_status_and_state_code() -> None:
    court, service = service_drafts(
        _service_payload(
            **{
                "Court Type": "U.S. District Court",
                "Court Name": "U.S. District Court for the Middle District of Florida",
                "Appointment Title": "Judge",
                "Commission Date": "1993-11-24",
                "Senior Status Date": "2010-04-08",
            }
        )
    )
    assert court.court_type == "district"
    assert court.state_code == "FL"
    assert service.metadata["senior_status_date"] == "2010-04-08"


@pytest.mark.parametrize("missing", ["nid", "Court Name", "Appointment Title"])
def test_service_drafts_require_identity_court_and_title(missing: str) -> None:
    with pytest.raises(NormalizationError):
        service_drafts(_service_payload(**{missing: ""}))


def test_service_drafts_reject_bad_dates() -> None:
    with pytest.raises(NormalizationError, match="Termination Date"):
        service_drafts(_service_payload(**{"Termination Date": "1950/10/31"}))


def test_normalize_record_dispatches_on_record_type() -> None:
    judge = normalize_record(
        SourceRecordDraft("1377101", None, _judge_payload(), record_type=RECORD_TYPE_JUDGE)
    )
    assert len(judge) == 1 and isinstance(judge[0], JudgeDraft)
    service = normalize_record(
        SourceRecordDraft("1377101:2", None, _service_payload(), record_type=RECORD_TYPE_SERVICE)
    )
    assert [type(record) for record in service] == [
        JurisdictionDraft,
        CourtDraft,
        JudgeServiceDraft,
    ]
    assert service[0] == FEDERAL_JURISDICTION
    with pytest.raises(NormalizationError, match="record type"):
        normalize_record(SourceRecordDraft("x", None, {}, record_type="mystery"))


def test_federal_jurisdiction_draft() -> None:
    assert FEDERAL_JURISDICTION.name == "United States federal courts"
    assert FEDERAL_JURISDICTION.type == "federal"
    assert FEDERAL_JURISDICTION.state_code is None
    assert FEDERAL_JURISDICTION.natural_key == (
        "jurisdiction",
        "United States federal courts",
        "federal",
    )
