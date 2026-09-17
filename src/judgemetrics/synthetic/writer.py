# src/judgemetrics/synthetic/writer.py
"""Rendering the world as the nine source CSV files, plus the file primitives.

Source files are UTF-8 with ``\\n`` newlines, a header row, one file each,
sorted by id; an empty string means missing; timestamps are timezone-aware
UTC ISO 8601. A case planted as a duplicate source record is emitted twice,
the copy immediately after the original with only formatting differences
(``edge_cases.duplicate_case_number`` and ``duplicate_full_name``). No
value ever ends a line with whitespace, so the repository's whitespace
hooks leave the golden fixture untouched.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Any

from judgemetrics.synthetic.edge_cases import duplicate_case_number, duplicate_full_name
from judgemetrics.synthetic.model import Case, World

Row = list[str]

SOURCE_FILES: tuple[str, ...] = (
    "courts.csv",
    "judges.csv",
    "cases.csv",
    "participants.csv",
    "charges.csv",
    "assignments.csv",
    "events.csv",
    "decisions.csv",
    "sentences.csv",
)

SOURCE_HEADERS: dict[str, tuple[str, ...]] = {
    "courts.csv": ("court_code", "name", "court_type", "jurisdiction", "state_code"),
    "judges.csv": ("judge_code", "full_name", "court_code", "position", "start_date", "end_date"),
    "cases.csv": (
        "case_number",
        "court_code",
        "case_type",
        "filed_date",
        "closed_date",
        "status",
        "related_case_number",
    ),
    "participants.csv": (
        "participant_id",
        "case_number",
        "court_code",
        "party_type",
        "full_name",
        "date_of_birth",
        "age_at_filing",
    ),
    "charges.csv": (
        "charge_id",
        "case_number",
        "court_code",
        "participant_id",
        "statute_code",
        "description",
        "offense_category",
        "severity",
        "violent_flag",
        "filed_at",
        "disposed_at",
        "disposition",
        "disposition_actor",
    ),
    "assignments.csv": (
        "assignment_id",
        "case_number",
        "court_code",
        "judge_code",
        "assignment_type",
        "start_at",
        "end_at",
    ),
    "events.csv": (
        "event_id",
        "case_number",
        "court_code",
        "participant_id",
        "judge_code",
        "event_type",
        "event_at",
        "actor",
        "description",
    ),
    "decisions.csv": (
        "decision_id",
        "case_number",
        "court_code",
        "participant_id",
        "judge_code",
        "decision_type",
        "decision_at",
        "actor",
        "discretion",
        "release_type",
        "bond_amount",
        "detained",
        "release_at",
        "conditions",
    ),
    "sentences.csv": (
        "sentence_id",
        "case_number",
        "court_code",
        "participant_id",
        "judge_code",
        "sentence_at",
        "incarceration_days",
        "probation_days",
        "fine_amount",
        "components",
    ),
}


def fmt_ts(value: datetime | None) -> str:
    return "" if value is None else value.isoformat()


def fmt_date(value: date | None) -> str:
    return "" if value is None else value.isoformat()


def fmt_bool(value: bool | None) -> str:
    if value is None:
        return ""
    return "true" if value else "false"


def fmt_opt(value: object) -> str:
    return "" if value is None else str(value)


def write_csv(path: Path, header: Sequence[str], rows: Iterable[Sequence[str]]) -> int:
    """Write ``rows`` under ``header`` with LF newlines; returns the row count."""
    count = 0
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        for row in rows:
            if row and row[-1].endswith((" ", "\t")):
                msg = f"{path.name}: a value ending in whitespace would end the line: {row[0]}"
                raise ValueError(msg)
            writer.writerow(row)
            count += 1
    return count


def write_json(path: Path, payload: Any) -> None:
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _case_rows(case: Case, *, copy: bool) -> dict[str, list[Row]]:
    number = duplicate_case_number(case.case_number) if copy else case.case_number
    name = duplicate_full_name(case.person.full_name) if copy else case.person.full_name
    person = case.person
    pid = case.participant_id
    rows: dict[str, list[Row]] = {name_: [] for name_ in SOURCE_FILES}
    rows["cases.csv"].append(
        [
            number,
            case.court_code,
            case.case_type,
            fmt_date(case.filed_date),
            fmt_date(case.closed_date),
            case.status,
            fmt_opt(case.related_case_number),
        ]
    )
    rows["participants.csv"].append(
        [
            pid,
            number,
            case.court_code,
            "defendant",
            name,
            fmt_date(person.date_of_birth) if person.dob_known else "",
            str(person.age_on(case.filed_date)),
        ]
    )
    for charge in case.charges:
        rows["charges.csv"].append(
            [
                charge.charge_id,
                number,
                case.court_code,
                pid,
                charge.offense.statute_code,
                charge.offense.description,
                charge.offense.offense_category,
                charge.offense.severity,
                fmt_bool(charge.offense.violent_flag),
                fmt_ts(charge.filed_at),
                fmt_ts(charge.disposed_at),
                fmt_opt(charge.disposition),
                fmt_opt(charge.disposition_actor),
            ]
        )
    for assignment in case.assignments:
        rows["assignments.csv"].append(
            [
                assignment.assignment_id,
                number,
                case.court_code,
                assignment.judge_code,
                assignment.assignment_type,
                fmt_ts(assignment.start_at),
                fmt_ts(assignment.end_at),
            ]
        )
    for event in case.events:
        rows["events.csv"].append(
            [
                event.event_id,
                number,
                case.court_code,
                pid,
                fmt_opt(event.judge_code),
                event.event_type,
                fmt_ts(event.event_at),
                fmt_opt(event.actor),
                fmt_opt(event.description),
            ]
        )
    for decision in case.decisions:
        rows["decisions.csv"].append(
            [
                decision.decision_id,
                number,
                case.court_code,
                pid,
                fmt_opt(decision.judge_code),
                decision.decision_type,
                fmt_ts(decision.decision_at),
                decision.actor,
                decision.discretion,
                fmt_opt(decision.release_type),
                fmt_opt(decision.bond_amount),
                fmt_bool(decision.detained),
                fmt_ts(decision.release_at),
                ";".join(decision.conditions),
            ]
        )
    if case.sentence is not None:
        sentence = case.sentence
        rows["sentences.csv"].append(
            [
                sentence.sentence_id,
                number,
                case.court_code,
                pid,
                sentence.judge_code,
                fmt_ts(sentence.sentence_at),
                fmt_opt(sentence.incarceration_days),
                fmt_opt(sentence.probation_days),
                fmt_opt(sentence.fine_amount),
                ";".join(sentence.components),
            ]
        )
    return rows


def render_source(world: World) -> dict[str, list[Row]]:
    """Every source file's rows, sorted by id, duplicate copies beside their originals."""
    files: dict[str, list[Row]] = {name: [] for name in SOURCE_FILES}
    for court in world.courts:
        files["courts.csv"].append(
            [court.code, court.name, court.court_type, court.jurisdiction, court.state_code]
        )
    for judge in world.judges:
        for service in sorted(judge.services, key=lambda s: (s.start_date, s.court_code)):
            files["judges.csv"].append(
                [
                    judge.code,
                    judge.full_name,
                    service.court_code,
                    service.position,
                    fmt_date(service.start_date),
                    fmt_date(service.end_date),
                ]
            )
    participants: list[tuple[tuple[str, str, int], Row]] = []
    for case in sorted(world.cases, key=Case.sort_key):
        for copy in (False, True) if case.duplicate else (False,):
            rows = _case_rows(case, copy=copy)
            for name in SOURCE_FILES:
                if name == "participants.csv":
                    for row in rows[name]:
                        participants.append(
                            ((case.participant_id, case.case_number, int(copy)), row)
                        )
                else:
                    files[name].extend(rows[name])
    participants.sort(key=lambda item: item[0])
    files["participants.csv"] = [row for _, row in participants]
    return files


def write_source(world: World, source_dir: Path) -> dict[str, int]:
    """Write the nine files; returns ``{"source/<file>": rows}``."""
    source_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}
    for name, rows in render_source(world).items():
        counts[f"source/{name}"] = write_csv(source_dir / name, SOURCE_HEADERS[name], rows)
    return counts
