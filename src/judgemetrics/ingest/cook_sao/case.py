# src/judgemetrics/ingest/cook_sao/case.py
"""One Cook County case: the rows of every export that mention it → its canonical drafts.

``build_case`` receives the rows of one ``CASE_ID`` in each of the five exports (read,
cleaned, and sorted by ``frames.read_export``) and returns the drafts of the case
grouped by the export they are attributed to, each natural key exactly once:

- the **case** — number = the SAO case id, court = the one municipal district its
  Dispositions and Sentencing rows name (else the parent court: ``courts.yaml``),
  filing date = the earliest received date of any row, status = closed when every
  charge has ended (a final disposition, or superseded or transferred), closing date =
  the latest disposition date; attributed to the first export that has the case;
- one **person** per case participant (the participant id is per case: this source
  has no cross-case person key), hashed with the pepper in the source's own namespace,
  its **defendant party** keyed ``defendant:<ordinal>`` (the ordinal is the
  participant's position among the case's normalized ids in code-point order, as
  revision 0008 keys the synthetic parties — no participant id reaches a canonical
  column), and its restricted **race, gender, and age band** (the first export, in
  the order Intake, Initiation, Dispositions, Sentencing, Diversion, with a valid
  label wins; the raw values leave this module only as vocabulary values);
- one **charge** per charge version, keyed ``<ordinal>:<charge id>:<version id>``
  (co-defendants share charge ids): its offense and class through ``offense_map.csv``,
  its disposition, finality, and actor through ``attribution_rules.yaml``, the
  disposing judge through the alias table. A version filed in Initiation and replaced
  by an amended version of the same charge in a later export is not published (the
  later version is);
- the **court events** the tables define (a disposition's own event, the charging
  event, a finding of no probable cause, a diversion's close), the **charging** decision
  of the felony review, the **diversion** decisions, the **bond** decision (one per
  participant, under the rule of the regime its own date falls in), the **sentences**
  (one per participant, date, and phase), and a within-case **revocation** event at
  each probation-violation sentencing.

Nothing here logs, and no draft or finding carries a participant id or a raw restricted
value.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import SecretStr

from judgemetrics.db.models.enums import ActorType
from judgemetrics.ingest.base import (
    CanonicalRecord,
    CaseDraft,
    CasePartyDraft,
    ChargeDraft,
    CourtEventDraft,
    DecisionDraft,
    JusticeEventDraft,
    NaturalKey,
    NormalizationError,
    PartyAttributeDraft,
    PersonDraft,
    PretrialReleaseDraft,
    SentenceDraft,
)
from judgemetrics.ingest.cook_sao import findings as codes
from judgemetrics.ingest.cook_sao.findings import Findings
from judgemetrics.ingest.cook_sao.rules import (
    NO_BOND_DATE,
    NO_BOND_TYPE,
    RESOLVED,
    UNLISTED_BOND_TYPE,
    CookSaoRules,
    restricted_category,
)
from judgemetrics.ingest.cook_sao.schema import (
    COVERAGE_START,
    DATASET_ORDER,
    DISPOSITIONS_FILE,
    DIVERSION_FILE,
    INITIATION_FILE,
    INTAKE_FILE,
    SENTENCING_FILE,
)
from judgemetrics.ingest.cook_sao.sources import SOURCE_ID
from judgemetrics.normalization import vocabulary
from judgemetrics.normalization.age_bands import age_band, parse_age
from judgemetrics.normalization.case_numbers import normalize_case_number
from judgemetrics.security.identifiers import (
    KIND_SOURCE_PARTICIPANT_ID,
    hash_identifier,
    normalize_identifier,
)

Row = dict[str, Any]
Rows = Mapping[str, Sequence[Row]]

CASE_TYPE = "felony"
PARTY_TYPE = "defendant"
RACE = "race"
GENDER = "gender"
AGE_BAND = "age_band"
DERIVED_CONFIDENCE = Decimal("1.0000")
MAX_STATUTE_LENGTH = 128
MAX_BOND_AMOUNT = Decimal("999999999999.99")
CLOSED = "closed"
OPEN = "open"
# The sentence phases that supersede the sentences they follow, in vocabulary order.
SENTENCE_PHASES = vocabulary.values("sentence_phase")

# Column names of a charge's offense, by the export it is read from.
INITIATION_CHARGE = ("CHARGE_OFFENSE_TITLE", "CHAPTER", "ACT", "SECTION", "CLASS")
DISPOSED_CHARGE = (
    "DISPOSITION_CHARGED_OFFENSE_TITLE",
    "DISPOSITION_CHARGED_CHAPTER",
    "DISPOSITION_CHARGED_ACT",
    "DISPOSITION_CHARGED_SECTION",
    "DISPOSITION_CHARGED_CLASS",
)
NO_TITLE = "(no offense title recorded)"


@dataclass(frozen=True, slots=True)
class Env:
    """What building a case needs besides its rows: the tables, the pepper, the findings."""

    rules: CookSaoRules
    pepper: SecretStr
    findings: Findings


@dataclass(slots=True)
class _Version:
    """One charge version of one participant, with the rows of every export that carry it."""

    initiation: Row | None = None
    disposition: Row | None = None
    sentencing: list[Row] = field(default_factory=list)


@dataclass(slots=True)
class _Charge:
    participant: str
    charge_id: str
    version_id: str
    home: str
    source: Row
    columns: tuple[str, ...]
    disposition: str | None
    actor: ActorType | None
    disposed_at: datetime | None
    judge: str | None
    ended: bool
    has_rule: bool


@dataclass(frozen=True, slots=True)
class _SentenceGroup:
    participant: str
    when: datetime
    phase: str
    supersedes: bool
    revocation: bool
    rows: tuple[tuple[Row, Any], ...]
    charges: frozenset[tuple[str, str]]


def _utc(value: datetime | None) -> datetime | None:
    return None if value is None else value.replace(tzinfo=UTC)


def _text(row: Row, column: str) -> str | None:
    value = row.get(column)
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def person_key(pepper: SecretStr, participant: str) -> NaturalKey:
    """The person's natural key: the source-qualified peppered hash of the participant id."""
    digest = hash_identifier(pepper, KIND_SOURCE_PARTICIPANT_ID, participant, source=SOURCE_ID)
    return ("person", KIND_SOURCE_PARTICIPANT_ID, digest)


def statute_code(chapter: str | None, act: str | None, section: str | None) -> str | None:
    """``720 ILCS 5/24-1.2(a)(2)`` from the three citation columns, else what is present."""
    real_act = act if act and act != "-" else None
    if chapter and real_act and section:
        text = f"{chapter} ILCS {real_act}/{section}"
    else:
        text = " ".join(part for part in (chapter, real_act, section) if part)
    return text[:MAX_STATUTE_LENGTH] or None


def _decimal(text: str | None) -> Decimal | None:
    if text is None:
        return None
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    if not value.is_finite() or value < 0 or value > MAX_BOND_AMOUNT:
        return None
    return value.quantize(Decimal("0.01"))


def build_case(case_id: str, rows: Rows, env: Env) -> dict[str, list[CanonicalRecord]] | None:
    """The drafts of case ``case_id`` by attributed export, or ``None`` when it has none.

    ``rows`` maps an export's file name to the case's rows in that export (a missing
    name has none). Rows a rule table cannot place are left out and counted in
    ``env.findings``.
    """
    rules, findings = env.rules, env.findings
    usable = _usable_rows(rows, env)
    filed = _filing_date(usable)
    if filed is None:
        findings.add(codes.CASE_WITHOUT_FILING_DATE)
        return None
    if filed < COVERAGE_START:
        findings.add(codes.RECEIVED_BEFORE_COVERAGE, detail=filed.strftime("%Y"))

    present = [name for name in DATASET_ORDER if usable.get(name)]
    if not present:
        return None
    participants = _participants(usable)
    ordinals = {participant: index for index, participant in enumerate(participants, start=1)}
    home_of = _participant_homes(usable, participants)

    court = rules.courts.courts[_case_court(usable, rules)]
    court_key: NaturalKey = ("court", court.name, court.court_type)
    normalized_number = normalize_case_number(case_id)
    case_key: NaturalKey = ("case", court.name, court.court_type, normalized_number)
    person_keys = {p: person_key(env.pepper, p) for p in participants}
    party_keys: dict[str, NaturalKey] = {
        p: ("case_party", *case_key[1:], f"{PARTY_TYPE}:{ordinals[p]}") for p in participants
    }

    out: dict[str, list[CanonicalRecord]] = {name: [] for name in DATASET_ORDER}

    # --- charges, and the status they decide ---------------------------------------
    charges = _charges(usable, env, ordinals)
    status, closed = _status(charges)
    out[present[0]].append(
        CaseDraft(
            court_key=court_key,
            case_number=case_id,
            case_number_normalized=normalized_number,
            case_type=vocabulary.require("case_type", CASE_TYPE),
            filed_date=filed,
            closed_date=closed,
            status=vocabulary.require("case_status", status),
            source_row_id=case_id,
        )
    )
    attributes = _attributes(usable, participants, findings)
    for participant in participants:
        home = out[home_of[participant]]
        key = person_keys[participant]
        home.append(
            PersonDraft(
                identity=(key[1], key[2]),
                identifier_hashes={key[1]: key[2]},
                birth_year_known=False,
            )
        )
        party = CasePartyDraft(
            case_key=case_key,
            person_key=key,
            party_type=vocabulary.require("party_type", PARTY_TYPE),
            source_party_label=None,
            source_row_id=party_keys[participant][-1],
        )
        home.append(party)
        home.extend(
            PartyAttributeDraft(party.natural_key, attribute, value)
            for attribute, value in attributes[participant].items()
        )

    filed_at = datetime(filed.year, filed.month, filed.day, tzinfo=UTC)
    for charge in charges:
        ordinal = ordinals[charge.participant]
        title, chapter, act, section, klass = (_text(charge.source, c) for c in charge.columns)
        category = _category(charge.source, rules)
        severity = rules.severity(klass)
        if category is None:
            findings.add(
                codes.UNMAPPED_VALUE,
                charge.home,
                f"the offense category {_category_value(charge.source)!r}",
            )
            continue
        if severity is None:
            findings.add(codes.UNMAPPED_VALUE, charge.home, f"the offense class {klass!r}")
            continue
        judge_key = ("judge", "cook_sao_judge", charge.judge) if charge.judge else None
        out[charge.home].append(
            ChargeDraft(
                case_key=case_key,
                person_key=person_keys[charge.participant],
                statute_code=statute_code(chapter, act, section),
                description=title or NO_TITLE,
                offense_category=category,
                severity=severity,
                violent_flag=None,
                filed_at=filed_at,
                disposed_at=_utc(charge.disposed_at),
                disposition=charge.disposition,
                disposition_actor=charge.actor,
                source_row_id=f"{ordinal}:{charge.charge_id}:{charge.version_id}",
                judge_key=judge_key,
            )
        )

    _disposition_events(out, charges, usable, case_key, person_keys, ordinals, rules)
    _initiation_facts(out, usable, case_key, person_keys, ordinals, env)
    _charging_decisions(out, usable, case_key, person_keys, ordinals, env)
    _bond_decisions(out, usable, case_key, person_keys, ordinals, env)
    _diversion(out, usable, case_key, person_keys, ordinals, env)
    _sentences(out, usable, case_key, person_keys, ordinals, env)
    return out


# --- rows ---------------------------------------------------------------------------


def _usable_rows(rows: Rows, env: Env) -> dict[str, list[Row]]:
    """The rows whose court the tables place; the others are counted and left out."""
    usable: dict[str, list[Row]] = {}
    for name in DATASET_ORDER:
        kept: list[Row] = []
        for row in rows.get(name, ()):
            if name in (DISPOSITIONS_FILE, SENTENCING_FILE):
                prefix = "DISPOSITION" if name == DISPOSITIONS_FILE else "SENTENCE"
                match = env.rules.court_of_row(
                    _text(row, f"{prefix}_COURT_NAME"), _text(row, f"{prefix}_COURT_FACILITY")
                )
                if match is None:
                    env.findings.add(
                        codes.COURT_UNLISTED,
                        name,
                        f"{prefix}_COURT_NAME or {prefix}_COURT_FACILITY",
                    )
                    continue
                row = {**row, "_court": match.court_key}
            kept.append(row)
        usable[name] = kept
    return usable


def _filing_date(usable: Mapping[str, Sequence[Row]]) -> date | None:
    earliest: datetime | None = None
    for rows in usable.values():
        for row in rows:
            received = row.get("RECEIVED_DATE")
            if received is not None and (earliest is None or received < earliest):
                earliest = received
    return None if earliest is None else earliest.date()


def _case_court(usable: Mapping[str, Sequence[Row]], rules: CookSaoRules) -> str:
    keys = {
        row["_court"]
        for name in (DISPOSITIONS_FILE, SENTENCING_FILE)
        for row in usable.get(name, ())
    }
    return rules.case_court(keys)


def _participants(usable: Mapping[str, Sequence[Row]]) -> list[str]:
    ids = {
        normalize_identifier(KIND_SOURCE_PARTICIPANT_ID, row["CASE_PARTICIPANT_ID"])
        for rows in usable.values()
        for row in rows
    }
    return sorted(ids)


def _participant_homes(
    usable: Mapping[str, Sequence[Row]], participants: list[str]
) -> dict[str, str]:
    homes: dict[str, str] = {}
    for name in DATASET_ORDER:
        for row in usable.get(name, ()):
            participant = normalize_identifier(
                KIND_SOURCE_PARTICIPANT_ID, row["CASE_PARTICIPANT_ID"]
            )
            homes.setdefault(participant, name)
    return {participant: homes[participant] for participant in participants}


def _pid(row: Row) -> str:
    return normalize_identifier(KIND_SOURCE_PARTICIPANT_ID, row["CASE_PARTICIPANT_ID"])


# --- restricted attributes -----------------------------------------------------------


def _attributes(
    usable: Mapping[str, Sequence[Row]], participants: list[str], findings: Findings
) -> dict[str, dict[str, str]]:
    """Per participant: race, gender, and age band as vocabulary values, nothing raw."""
    candidates: dict[str, dict[str, list[str]]] = {
        participant: {RACE: [], GENDER: [], AGE_BAND: []} for participant in participants
    }
    unlisted: dict[str, set[str]] = {participant: set() for participant in participants}
    bad_age: set[str] = set()
    for name in DATASET_ORDER:
        for row in usable.get(name, ()):
            participant = _pid(row)
            mine = candidates[participant]
            for kind, column in ((RACE, "RACE"), (GENDER, "GENDER")):
                raw = _text(row, column)
                if raw is None:
                    continue
                value = restricted_category(kind, raw)
                if value is None:
                    unlisted[participant].add(kind)
                else:
                    mine[kind].append(value)
            if "AGE_AT_INCIDENT" in row:
                try:
                    age = parse_age(row["AGE_AT_INCIDENT"] or "")
                except NormalizationError:
                    bad_age.add(participant)
                else:
                    if age is not None:
                        mine[AGE_BAND].append(age_band(age))
    resolved: dict[str, dict[str, str]] = {}
    conflicts: Counter[str] = Counter()
    for participant in participants:
        picked: dict[str, str] = {}
        for kind in (RACE, GENDER, AGE_BAND):
            options = candidates[participant][kind]
            if len(set(options)) > 1:
                conflicts[kind] += 1
            picked[kind] = options[0] if options else vocabulary.UNKNOWN
        for kind in unlisted[participant]:
            findings.add(codes.RESTRICTED_VALUE_UNLISTED, detail=kind)
        resolved[participant] = {
            kind: vocabulary.require(kind, value) for kind, value in picked.items()
        }
    for kind, count in conflicts.items():
        findings.add(codes.RESTRICTED_VALUE_CONFLICT, detail=kind, count=count)
    if bad_age:
        findings.add(codes.INVALID_AGE, count=len(bad_age))
    return resolved


# --- charges --------------------------------------------------------------------------


def _category_value(row: Row) -> str:
    return str(_text(row, "UPDATED_OFFENSE_CATEGORY") or _text(row, "OFFENSE_CATEGORY") or "")


def _category(row: Row, rules: CookSaoRules) -> str | None:
    return rules.offense_category(_category_value(row) or None)


def _charges(
    usable: Mapping[str, Sequence[Row]], env: Env, ordinals: Mapping[str, int]
) -> list[_Charge]:
    rules, findings = env.rules, env.findings
    versions: dict[tuple[str, str, str], _Version] = {}
    for name in (INITIATION_FILE, DISPOSITIONS_FILE, SENTENCING_FILE):
        for row in usable.get(name, ()):
            key = (_pid(row), str(row["CHARGE_ID"]), str(row["CHARGE_VERSION_ID"]))
            version = versions.setdefault(key, _Version())
            if name == INITIATION_FILE:
                version.initiation = version.initiation or row
            elif name == DISPOSITIONS_FILE:
                version.disposition = version.disposition or row
            else:
                version.sentencing.append(row)
    # An Initiation version with no later row, beside a later version of its charge, was amended away.
    later: set[tuple[str, str]] = {
        (participant, charge_id)
        for (participant, charge_id, _), version in versions.items()
        if version.disposition is not None or version.sentencing
    }
    charges: list[_Charge] = []
    replaced = 0
    for (participant, charge_id, version_id), version in sorted(versions.items()):
        later_rows = version.disposition is not None or bool(version.sentencing)
        if not later_rows and (participant, charge_id) in later:
            replaced += 1
            continue
        if version.disposition is not None:
            source, home, columns = version.disposition, DISPOSITIONS_FILE, DISPOSED_CHARGE
        elif version.sentencing:
            source, home, columns = version.sentencing[0], SENTENCING_FILE, DISPOSED_CHARGE
        elif version.initiation is not None:
            source, home, columns = version.initiation, INITIATION_FILE, INITIATION_CHARGE
        else:  # a version always has a row in some export
            continue
        decided = version.disposition or (version.sentencing[0] if version.sentencing else None)
        disposition: str | None = None
        actor: ActorType | None = None
        disposed_at: datetime | None = None
        ended = False
        if decided is not None:
            rule = rules.disposition(
                _text(decided, "CHARGE_DISPOSITION"), _text(decided, "CHARGE_DISPOSITION_REASON")
            )
            disposition = vocabulary.require("charge_disposition", rule.disposition)
            actor = ActorType(vocabulary.require("actor_type", rule.actor_type))
            disposed_at = decided.get("DISPOSITION_DATE")
            ended = rule.final or rule.disposition in ("superseded", "transferred")
            if disposed_at is None:
                findings.add(codes.CHARGE_WITHOUT_DISPOSITION_DATE)
        judge: str | None = None
        if version.disposition is not None:
            match = rules.judge(_text(version.disposition, "JUDGE"))
            if match is not None and match.status == RESOLVED:
                judge = match.judge_key
        charges.append(
            _Charge(
                participant=participant,
                charge_id=charge_id,
                version_id=version_id,
                home=home,
                source=source,
                columns=columns,
                disposition=disposition,
                actor=actor,
                disposed_at=disposed_at,
                judge=judge,
                ended=ended,
                has_rule=decided is not None,
            )
        )
    if replaced:
        findings.add(codes.CHARGE_VERSION_REPLACED, count=replaced)
    return charges


def _status(charges: Sequence[_Charge]) -> tuple[str, date | None]:
    """``closed`` (and the latest disposition date) when every charge has ended."""
    by_charge: dict[tuple[str, str], list[_Charge]] = {}
    for charge in charges:
        by_charge.setdefault((charge.participant, charge.charge_id), []).append(charge)
    if not by_charge:
        return OPEN, None
    for versions in by_charge.values():
        decided = [v for v in versions if v.has_rule]
        if not decided or not all(v.ended for v in decided):
            return OPEN, None
    dates = [c.disposed_at for c in charges if c.ended and c.disposed_at is not None]
    return CLOSED, (max(dates).date() if dates else None)


# --- events ---------------------------------------------------------------------------


def _disposition_events(
    out: dict[str, list[CanonicalRecord]],
    charges: Sequence[_Charge],
    usable: Mapping[str, Sequence[Row]],
    case_key: NaturalKey,
    person_keys: Mapping[str, NaturalKey],
    ordinals: Mapping[str, int],
    rules: CookSaoRules,
) -> None:
    """A disposition's own court event, once per participant, event type, actor, and instant."""
    seen: dict[tuple[str, str, str, datetime], list[str]] = {}
    for charge in charges:
        if charge.home != DISPOSITIONS_FILE or charge.disposed_at is None:
            continue
        rule = rules.disposition(
            _text(charge.source, "CHARGE_DISPOSITION"),
            _text(charge.source, "CHARGE_DISPOSITION_REASON"),
        )
        if rule.event_type is None:
            continue
        key = (
            charge.participant,
            vocabulary.require("event_type", rule.event_type),
            vocabulary.require("actor_type", rule.actor_type),
            charge.disposed_at,
        )
        judges = seen.setdefault(key, [])
        if charge.judge is not None:
            judges.append(charge.judge)
    for (participant, event_type, actor, at), judges in sorted(seen.items()):
        judge = sorted(judges)[0] if judges else None
        out[DISPOSITIONS_FILE].append(
            CourtEventDraft(
                case_key=case_key,
                person_key=person_keys[participant],
                judge_key=("judge", "cook_sao_judge", judge) if judge else None,
                event_type=event_type,
                event_at=at.replace(tzinfo=UTC),
                description=None,
                actor_type=ActorType(actor),
                source_row_id=(
                    f"disposition:{ordinals[participant]}:{event_type}:{actor}:{at:%Y%m%d%H%M%S}"
                ),
            )
        )


def _initiation_facts(
    out: dict[str, list[CanonicalRecord]],
    usable: Mapping[str, Sequence[Row]],
    case_key: NaturalKey,
    person_keys: Mapping[str, NaturalKey],
    ordinals: Mapping[str, int],
    env: Env,
) -> None:
    """The charging event and the finding of no probable cause of Initiation."""
    rules, findings = env.rules, env.findings
    events: set[tuple[str, str, datetime]] = set()
    findings_of_no_cause: set[tuple[str, datetime]] = set()
    for row in usable.get(INITIATION_FILE, ()):
        participant = _pid(row)
        event_value = _text(row, "EVENT")
        rule = rules.initiation_event(event_value)
        at = row.get("EVENT_DATE")
        if rule is None:
            findings.add(codes.IGNORED_VALUE, INITIATION_FILE, "an EVENT value")
        elif rule.event_type is not None:
            if at is None:
                findings.add(codes.FACT_UNDATED, detail="charging events")
            else:
                events.add((participant, vocabulary.require("event_type", rule.event_type), at))
        flag = rules.no_probable_cause(_text(row, "FINDING_NO_PROBABLE_CAUSE"))
        if flag is not None:
            if at is None:
                findings.add(codes.FACT_UNDATED, detail="findings of no probable cause")
            else:
                findings_of_no_cause.add((participant, at))
    for participant, event_type, at in sorted(events):
        out[INITIATION_FILE].append(
            CourtEventDraft(
                case_key=case_key,
                person_key=person_keys[participant],
                judge_key=None,
                event_type=event_type,
                event_at=_utc(at) or at,
                description=None,
                actor_type=None,
                source_row_id=f"initiation:{ordinals[participant]}:{event_type}:{at:%Y%m%d%H%M%S}",
            )
        )
    rule_of_finding = rules.attribution.no_probable_cause
    for participant, at in sorted(findings_of_no_cause):
        out[INITIATION_FILE].append(
            CourtEventDraft(
                case_key=case_key,
                person_key=person_keys[participant],
                judge_key=None,
                event_type=vocabulary.require("event_type", rule_of_finding.event_type),
                event_at=_utc(at) or at,
                description=rule_of_finding.judicial_ruling,
                actor_type=ActorType(vocabulary.require("actor_type", rule_of_finding.actor_type)),
                source_row_id=f"finding:{ordinals[participant]}:{at:%Y%m%d%H%M%S}",
            )
        )


# --- decisions -------------------------------------------------------------------------


def _charging_decisions(
    out: dict[str, list[CanonicalRecord]],
    usable: Mapping[str, Sequence[Row]],
    case_key: NaturalKey,
    person_keys: Mapping[str, NaturalKey],
    ordinals: Mapping[str, int],
    env: Env,
) -> None:
    """One charging decision per participant: the first export with a felony-review result."""
    rules, findings = env.rules, env.findings
    done: set[str] = set()
    for name in (INTAKE_FILE, INITIATION_FILE, DISPOSITIONS_FILE, SENTENCING_FILE):
        for row in usable.get(name, ()):
            participant = _pid(row)
            result = _text(row, "FELONY_REVIEW_RESULT")
            if participant in done or result is None:
                continue
            done.add(participant)
            rule = rules.felony_review(result)
            if rule is None or rule.outcome is None:
                continue
            at = row.get("FELONY_REVIEW_DATE")
            if at is None:
                findings.add(codes.FACT_UNDATED, detail="felony-review results")
                continue
            out[name].append(
                DecisionDraft(
                    case_key=case_key,
                    person_key=person_keys[participant],
                    judge_key=None,
                    decision_type=vocabulary.require("decision_type", "charging"),
                    decision_at=_utc(at) or at,
                    decision_value={
                        "outcome": vocabulary.require("charging_outcome", rule.outcome),
                        "felony_review_result": result,
                    },
                    actor_type=ActorType(vocabulary.require("actor_type", rule.actor_type)),
                    judicial_discretion_classification=vocabulary.require(
                        "judicial_discretion_classification",
                        rule.judicial_discretion_classification,
                    ),
                    pretrial=None,
                    source_row_id=f"charging:{ordinals[participant]}",
                )
            )


def _bond_decisions(
    out: dict[str, list[CanonicalRecord]],
    usable: Mapping[str, Sequence[Row]],
    case_key: NaturalKey,
    person_keys: Mapping[str, NaturalKey],
    ordinals: Mapping[str, int],
    env: Env,
) -> None:
    """One bond decision per participant: the initial bond under its own date's regime."""
    rules, findings = env.rules, env.findings
    reasons = {
        NO_BOND_TYPE: "no bond type is recorded",
        NO_BOND_DATE: "a bond type is recorded without a valid date",
        UNLISTED_BOND_TYPE: "the bond type is not in pretrial_rules.yaml",
    }
    chosen: dict[str, Row] = {}
    participants = {_pid(candidate) for candidate in usable.get(INITIATION_FILE, ())}
    for candidate in usable.get(INITIATION_FILE, ()):
        owner = _pid(candidate)
        if _text(candidate, "BOND_TYPE_INITIAL") is not None and owner not in chosen:
            chosen[owner] = candidate
    for participant in sorted(participants):
        row = chosen.get(participant)
        if row is None:
            findings.add(codes.BOND_NOT_DRAFTED, detail=reasons[NO_BOND_TYPE])
            continue
        bond_type = _text(row, "BOND_TYPE_INITIAL")
        at = row.get("BOND_DATE_INITIAL")
        match = rules.pretrial_rule(bond_type, None if at is None else at.date())
        if match.rule is None or at is None:
            findings.add(codes.BOND_NOT_DRAFTED, detail=reasons[match.reason or NO_BOND_DATE])
            continue
        rule = match.rule
        moment = _utc(at) or at
        amount = _decimal(_text(row, "BOND_AMOUNT_INITIAL"))
        condition = rules.electronic_monitoring(_text(row, "BOND_ELECTRONIC_MONITOR_FLAG_INITIAL"))
        conditions = {vocabulary.require("release_condition", condition): True} if condition else {}
        out[INITIATION_FILE].append(
            DecisionDraft(
                case_key=case_key,
                person_key=person_keys[participant],
                judge_key=None,
                decision_type=vocabulary.require("decision_type", "pretrial_release"),
                decision_at=moment,
                decision_value={"bond_type": bond_type, "regime": rule.regime},
                actor_type=ActorType(vocabulary.require("actor_type", rule.actor_type)),
                judicial_discretion_classification=vocabulary.require(
                    "judicial_discretion_classification", rule.judicial_discretion_classification
                ),
                pretrial=PretrialReleaseDraft(
                    release_type=vocabulary.require("release_type", rule.release_type),
                    bond_amount=amount,
                    conditions=conditions,
                    release_at=moment if rule.releases else None,
                    detained_flag=rule.detained_flag,
                ),
                source_row_id=f"bond:{ordinals[participant]}",
                judge_not_recorded=True,
            )
        )


def _diversion(
    out: dict[str, list[CanonicalRecord]],
    usable: Mapping[str, Sequence[Row]],
    case_key: NaturalKey,
    person_keys: Mapping[str, NaturalKey],
    ordinals: Mapping[str, int],
    env: Env,
) -> None:
    """A diversion decision per referral, and its close as an event when the result is recorded."""
    rules, findings = env.rules, env.findings
    seen: set[str] = set()
    for row in usable.get(DIVERSION_FILE, ()):
        participant = _pid(row)
        program = _text(row, "DIVERSION_PROGRAM")
        referred = row.get("REFERRAL_DATE")
        program_rule = rules.diversion_program(program)
        if referred is None:
            findings.add(codes.FACT_UNDATED, detail="diversion referrals")
            continue
        stamp = f"{referred:%Y%m%d%H%M%S}"
        label = f"{ordinals[participant]}:{program or ''}:{stamp}"
        result = _text(row, "DIVERSION_RESULT")
        if f"d:{label}" not in seen:
            seen.add(f"d:{label}")
            out[DIVERSION_FILE].append(
                DecisionDraft(
                    case_key=case_key,
                    person_key=person_keys[participant],
                    judge_key=None,
                    decision_type=vocabulary.require("decision_type", "diversion"),
                    decision_at=_utc(referred) or referred,
                    decision_value={
                        "program": program,
                        "stage": program_rule.stage,
                    },
                    actor_type=ActorType(vocabulary.require("actor_type", program_rule.actor_type)),
                    judicial_discretion_classification=vocabulary.require(
                        "judicial_discretion_classification",
                        program_rule.judicial_discretion_classification,
                    ),
                    pretrial=None,
                    source_row_id=f"diversion:{label}",
                    # The exports name no judge or officer for a referral.
                    judge_not_recorded=True,
                )
            )
        result_rule = rules.diversion_result(result)
        closed = row.get("DIVERSION_CLOSED_DATE")
        if result_rule.event_type is not None and f"e:{label}" not in seen:
            seen.add(f"e:{label}")
            if closed is None:
                findings.add(codes.FACT_UNDATED, detail="diversion results")
                continue
            out[DIVERSION_FILE].append(
                CourtEventDraft(
                    case_key=case_key,
                    person_key=person_keys[participant],
                    judge_key=None,
                    event_type=vocabulary.require("event_type", result_rule.event_type),
                    event_at=_utc(closed) or closed,
                    description=None,
                    actor_type=None,
                    source_row_id=f"diversion_result:{label}",
                )
            )


# --- sentences -------------------------------------------------------------------------


def _unlisted_columns(rules: CookSaoRules, row: Row) -> str:
    sentence = rules.sentence
    names: list[str] = []
    phase, kind, commitment = (
        _text(row, "SENTENCE_PHASE"),
        _text(row, "SENTENCE_TYPE"),
        _text(row, "COMMITMENT_TYPE"),
    )
    if phase is None or phase not in sentence.phases:
        names.append("SENTENCE_PHASE")
    if kind is None or kind not in sentence.sentence_types:
        names.append("SENTENCE_TYPE")
    if commitment is not None and commitment not in sentence.commitment_types:
        names.append("COMMITMENT_TYPE")
    return " and ".join(names)


def _sentences(
    out: dict[str, list[CanonicalRecord]],
    usable: Mapping[str, Sequence[Row]],
    case_key: NaturalKey,
    person_keys: Mapping[str, NaturalKey],
    ordinals: Mapping[str, int],
    env: Env,
) -> None:
    rules, findings = env.rules, env.findings
    grouped: dict[tuple[str, datetime | None, str], list[tuple[Row, Any]]] = {}
    for row in usable.get(SENTENCING_FILE, ()):
        phase_text = _text(row, "SENTENCE_PHASE")
        phase_rule = rules.sentence.phases.get(phase_text) if phase_text else None
        if phase_rule is not None and phase_rule.ignored:
            findings.add(codes.SENTENCE_PHASE_IGNORED, SENTENCING_FILE, str(phase_text))
            continue
        match = rules.sentence_row(
            phase_text,
            _text(row, "SENTENCE_TYPE"),
            _text(row, "COMMITMENT_TYPE"),
            _text(row, "COMMITMENT_TERM"),
            _text(row, "COMMITMENT_UNIT"),
        )
        if not match.matched or match.phase is None:
            findings.add(codes.SENTENCE_UNMATCHED, SENTENCING_FILE, _unlisted_columns(rules, row))
            continue
        for flag in match.flags:
            findings.add(codes.SENTENCE_TERM_FLAGGED, SENTENCING_FILE, flag)
        key = (_pid(row), row.get("SENTENCE_DATE"), str(match.phase))
        grouped.setdefault(key, []).append((row, match))

    groups: list[_SentenceGroup] = []
    for (participant, when, phase), members in sorted(
        grouped.items(), key=lambda item: (item[0][0], item[0][1] or datetime.min, item[0][2])
    ):
        if when is None:
            findings.add(codes.SENTENCE_WITHOUT_DATE, SENTENCING_FILE)
            continue
        phase_rule = next(m.supersedes_earlier for _, m in members)
        groups.append(
            _SentenceGroup(
                participant=participant,
                when=when,
                phase=phase,
                supersedes=phase_rule,
                revocation=members[0][1].revocation,
                rows=tuple(members),
                charges=frozenset(
                    (str(r["CHARGE_ID"]), str(r["CHARGE_VERSION_ID"])) for r, _ in members
                ),
            )
        )

    for group in groups:
        participant = group.participant
        ordinal = ordinals[participant]
        moment = _utc(group.when) or group.when
        terminations = [m.terminates_probation for _, m in group.rows]
        new_sentence = any(t is None for t in terminations)
        if group.revocation and not all(t == "satisfactory" for t in terminations):
            out[SENTENCING_FILE].append(
                JusticeEventDraft(
                    person_key=person_keys[participant],
                    event_type=vocabulary.require("justice_event_type", "revocation"),
                    event_at=moment,
                    related_case_key=case_key,
                    description=None,
                    confidence=DERIVED_CONFIDENCE,
                )
            )
        if not new_sentence:
            continue
        current = [(r, m) for r, m in group.rows if _text(r, "CURRENT_SENTENCE_FLAG") == "true"]
        pool = current or list(group.rows)
        incarceration = [
            m.days for _, m in pool if m.term_component == "incarceration" and m.days is not None
        ]
        probation = [
            m.days for _, m in pool if m.term_component == "probation" and m.days is not None
        ]
        components = sorted(
            {c for _, m in group.rows for c in m.components},
            key=vocabulary.values("sentence_component").index,
        )
        terms = [
            {
                "component": m.term_component,
                "days": m.days,
                "flags": list(m.flags),
                "current": _text(r, "CURRENT_SENTENCE_FLAG") == "true",
                "sentence_type": _text(r, "SENTENCE_TYPE"),
                "commitment_type": _text(r, "COMMITMENT_TYPE"),
                "charge": f"{ordinal}:{r['CHARGE_ID']}:{r['CHARGE_VERSION_ID']}",
            }
            for r, m in group.rows
            if m.terminates_probation is None
        ]
        superseded = any(
            other.participant == participant
            and other.supersedes
            and (other.when, SENTENCE_PHASES.index(other.phase))
            > (group.when, SENTENCE_PHASES.index(group.phase))
            and group.charges & other.charges
            for other in groups
        )
        judge = _sentence_judge(group, rules, findings)
        out[SENTENCING_FILE].append(
            SentenceDraft(
                case_key=case_key,
                person_key=person_keys[participant],
                judge_key=("judge", "cook_sao_judge", judge) if judge else None,
                sentence_at=moment,
                incarceration_days=max(incarceration) if incarceration else None,
                probation_days=max(probation) if probation else None,
                fine_amount=None,
                components={
                    "phase": group.phase,
                    "current": bool(current),
                    "superseded": superseded,
                    "components": components,
                    "terms": terms,
                },
                source_row_id=f"{ordinal}:{group.when:%Y-%m-%d}:{group.phase}",
            )
        )


def _sentence_judge(group: _SentenceGroup, rules: CookSaoRules, findings: Findings) -> str | None:
    keys: Counter[str] = Counter()
    for row, _ in group.rows:
        match = rules.judge(_text(row, "SENTENCE_JUDGE"))
        if match is not None and match.status == RESOLVED and match.judge_key is not None:
            keys[match.judge_key] += 1
    if not keys:
        return None
    if len(keys) > 1:
        findings.add(codes.SENTENCE_JUDGES_DIFFER, SENTENCING_FILE)
    best = max(keys.values())
    return sorted(key for key, count in keys.items() if count == best)[0]


def judge_strings(rows: Iterable[Row], column: str) -> Counter[str]:
    """How many rows carry each judge string of ``column`` (blank strings excluded)."""
    counts: Counter[str] = Counter()
    for row in rows:
        value = row.get(column)
        if value is not None and str(value).strip():
            counts[str(value)] += 1
    return counts


__all__ = ["Env", "build_case", "judge_strings", "person_key", "statute_code"]
