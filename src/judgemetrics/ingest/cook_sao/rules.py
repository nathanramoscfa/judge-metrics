# src/judgemetrics/ingest/cook_sao/rules.py
"""The Cook County rule tables: loader, validators, and matchers.

The seven tables under ``data/reference/cook_sao/`` turn the source's coded
values into canonical ones (docs/ARCHITECTURE.md "Cook County source"):

- ``attribution_rules.yaml`` — every (disposition, reason) pair, felony-review
  result, diversion program and result, and Initiation charging event: the
  canonical disposition, its finality, the actor, the judicial-discretion
  classification, an optional judicial ruling, and a rationale;
- ``pretrial_rules.yaml`` — every bond type under each legal regime (before
  and from 2023-09-18): the release semantics, never claiming a release the
  source does not record;
- ``sentence_rules.yaml`` — the sentence grain and currency, every phase,
  sentence type, commitment type, and unit, and the exact conversion of a
  term to days;
- ``offense_map.csv`` — every offense category and class to a canonical
  category and severity, an unmapped value being an error;
- ``courts.yaml`` — the jurisdiction, the six municipal districts and their
  parent court, and every court name and courthouse;
- ``judge_aliases.csv`` and ``judges.csv`` — every judge string resolved to a
  canonical judge or held ``ambiguous`` or ``unresolved`` with its reason.

``tables.yaml`` lists each table with its ``version`` and sha256.
``load_rules`` reads every table from a path built from the module's
constants (``yaml.safe_load`` or the ``csv`` module; a value is never
evaluated, formatted into SQL, or used as a path), refuses a table whose
digest or version differs from ``tables.yaml`` or from ``RULE_VERSIONS`` — so
an edit must bump the version beside the digest, and the connector's parser
version, which embeds ``RULE_VERSIONS``, re-derives every row — and validates
every field against case vocabulary 3, raising ``RuleError`` naming the file,
the key, and the field.

The matchers are total and deterministic: every input, a blank one or a value
no table lists included, returns a rule (the explicit fallback), ``None`` (no
value recorded, or a value the source never wrote, which the connector turns
into a rejected row and an issue), or a status — never an exception — and every
canonical value they return is a vocabulary value.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml

from judgemetrics.config import REPO_ROOT
from judgemetrics.db.models.enums import JurisdictionType
from judgemetrics.normalization import vocabulary
from judgemetrics.normalization.names import normalize_person_name

TABLES_DIR = REPO_ROOT / "data" / "reference" / "cook_sao"
TABLES_FILE = "tables.yaml"

ATTRIBUTION = "attribution_rules"
PRETRIAL = "pretrial_rules"
SENTENCE = "sentence_rules"
OFFENSE = "offense_map"
COURTS = "courts"
JUDGE_ALIASES = "judge_aliases"
JUDGES = "judges"
# Every table by name, in the order RULE_VERSION_TAG lists their versions.
TABLE_FILES: Mapping[str, str] = MappingProxyType(
    {
        ATTRIBUTION: "attribution_rules.yaml",
        PRETRIAL: "pretrial_rules.yaml",
        SENTENCE: "sentence_rules.yaml",
        OFFENSE: "offense_map.csv",
        COURTS: "courts.yaml",
        JUDGE_ALIASES: "judge_aliases.csv",
        JUDGES: "judges.csv",
    }
)
# The version of every table this code was written against: tables.yaml must
# state the same, and the connector's parser version embeds them (Step 4), so a
# table edit — which bumps its version here and there — re-derives every row.
RULE_VERSIONS: Mapping[str, int] = MappingProxyType(
    {
        ATTRIBUTION: 1,
        PRETRIAL: 1,
        SENTENCE: 1,
        OFFENSE: 1,
        COURTS: 1,
        JUDGE_ALIASES: 1,
        JUDGES: 1,
    }
)
RULE_VERSION_TAG = ".".join(str(RULE_VERSIONS[name]) for name in TABLE_FILES)

WILDCARD = "*"
UNKNOWN = "unknown"
CITES: tuple[str, ...] = ("glossary", "plain_legal_meaning")
UNKNOWN_REASON = "not settled by the source's documentation"
NON_JUDICIAL_ACTORS: frozenset[str] = frozenset({"prosecutor", "jury", "law_enforcement"})
FINAL_KIND = "final_charge_disposition"

# Pretrial regimes, and why a bond drafts no decision.
MONETARY_BAIL = "monetary_bail"
PRETRIAL_FAIRNESS_ACT = "pretrial_fairness_act"
REGIMES: tuple[str, ...] = (MONETARY_BAIL, PRETRIAL_FAIRNESS_ACT)
NO_BOND_TYPE = "no_bond_type"
NO_BOND_DATE = "no_bond_date"
UNLISTED_BOND_TYPE = "unlisted_bond_type"

# Sentence term conversion.
TERMINATIONS: tuple[str, ...] = ("instanter", "satisfactory", "unsatisfactory")
SATISFACTORY = "satisfactory"
MISSING_TERM = "missing_term"
UNPARSEABLE_TERM = "unparseable_term"
IMPLAUSIBLE_TERM = "implausible_term"
_TERM = re.compile(r"^[0-9]+(?:\.[0-9]+)?$")

# Judge aliases.
RESOLVED = "resolved"
AMBIGUOUS = "ambiguous"
UNRESOLVED = "unresolved"
STATUSES: tuple[str, ...] = (RESOLVED, AMBIGUOUS, UNRESOLVED)
EXACT = "exact"
RESOLVING_RULES: tuple[str, ...] = (
    EXACT,
    "spacing_or_case",
    "family_given_order",
    "middle_present_or_absent",
)
HOLDING_RULES: tuple[str, ...] = (
    "given_initial_only",
    "family_name_only",
    "given_name_variant",
    "family_name_variant",
)
NOT_IN_TABLE = "not in the alias table"
_KEY = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

ALIAS_HEADERS: tuple[str, ...] = (
    "source_string",
    "normalized",
    "status",
    "judge_key",
    "rule",
    "candidates",
    "reason",
)
JUDGE_HEADERS: tuple[str, ...] = ("judge_key", "display_name", "position")
OFFENSE_HEADERS: tuple[str, ...] = ("field", "source_value", "canonical_value", "note")
OFFENSE_FIELDS: Mapping[str, str] = MappingProxyType(
    {"offense_category": "offense_category", "class": "severity"}
)
RESTRICTED_SOURCE_KINDS: tuple[str, ...] = ("race", "gender")
_NOT_ALNUM = re.compile(r"[^a-z0-9]+")


class RuleError(ValueError):
    """A rule table is missing, altered, or states an invalid value (names file, key, field)."""


# --- rules ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class DispositionRule:
    """A (disposition, reason) pair's canonical disposition, finality, and attribution."""

    charge_disposition: str | None
    charge_disposition_reason: str | None
    disposition: str
    final: bool
    actor_type: str
    judicial_discretion_classification: str
    judicial_ruling: str | None
    event_type: str | None
    cites: str
    rationale: str
    fallback: bool = False


@dataclass(frozen=True, slots=True)
class FelonyReviewRule:
    """A felony-review result: the charging outcome it drafts (``None``: no decision)."""

    felony_review_result: str | None
    outcome: str | None
    actor_type: str
    judicial_discretion_classification: str
    cites: str
    rationale: str
    fallback: bool = False


@dataclass(frozen=True, slots=True)
class DiversionProgramRule:
    """A diversion program's stage and the attribution of its referral."""

    diversion_program: str | None
    stage: str | None
    actor_type: str
    judicial_discretion_classification: str
    cites: str
    rationale: str
    fallback: bool = False


@dataclass(frozen=True, slots=True)
class EventRule:
    """A diversion result or an Initiation charging event: the court event it drafts."""

    value: str | None
    event_type: str | None
    cites: str
    rationale: str
    fallback: bool = False


@dataclass(frozen=True, slots=True)
class NoProbableCauseRule:
    """Initiation's finding-of-no-probable-cause flag."""

    value: str
    event_type: str
    judicial_ruling: str
    actor_type: str
    cites: str
    rationale: str


@dataclass(frozen=True, slots=True)
class PretrialRule:
    """A bond type under one regime: the pretrial_release decision it drafts."""

    bond_type: str
    regime: str
    release_type: str
    detained_flag: bool
    releases: bool
    actor_type: str
    judicial_discretion_classification: str
    rationale: str


@dataclass(frozen=True, slots=True)
class PretrialMatch:
    """The rule a bond drafts, or ``None`` with why no decision is drafted."""

    rule: PretrialRule | None
    reason: str | None


@dataclass(frozen=True, slots=True)
class UnitRule:
    commitment_unit: str
    days_per_unit: Decimal | None
    flag: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class PhaseRule:
    sentence_phase: str
    phase: str | None
    ignored: bool
    supersedes_earlier: bool
    revocation: bool
    rationale: str


@dataclass(frozen=True, slots=True)
class SentenceTypeRule:
    sentence_type: str
    component: str | None
    flag: str | None
    terminates_probation: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class CommitmentTypeRule:
    commitment_type: str
    component: str | None
    flag: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class TermDays:
    """A commitment term in whole days, or ``None`` with the flag that says why."""

    days: int | None
    flag: str | None


@dataclass(frozen=True, slots=True)
class SentenceRowMatch:
    """One Sentencing row read through the sentence rules.

    ``matched`` is false when the phase or the sentence type is not in the
    table (the connector rejects the row); ``components`` are in the order
    the sentence type's, then the term's; ``flags`` follow the vocabulary.
    """

    matched: bool
    phase: str | None
    ignored: bool
    supersedes_earlier: bool
    revocation: bool
    components: tuple[str, ...]
    term_component: str | None
    days: int | None
    flags: tuple[str, ...]
    terminates_probation: str | None


@dataclass(frozen=True, slots=True)
class Court:
    key: str
    name: str
    court_type: str
    district: int | None
    seat: str | None
    parent: str | None


@dataclass(frozen=True, slots=True)
class Jurisdiction:
    key: str
    name: str
    jurisdiction_type: str
    state_code: str
    fips_code: str


@dataclass(frozen=True, slots=True)
class CourtMatch:
    """A row's court and the courthouse kept beside it."""

    court_key: str
    facility: str | None


@dataclass(frozen=True, slots=True)
class JudgeAlias:
    source_string: str
    normalized: str
    status: str
    judge_key: str | None
    rule: str
    candidates: tuple[str, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class JudgeEntry:
    judge_key: str
    display_name: str
    position: str


@dataclass(frozen=True, slots=True)
class JudgeMatch:
    """A judge string's canonical key (``resolved``) or why it has none."""

    status: str
    judge_key: str | None
    candidates: tuple[str, ...]
    reason: str


# --- validation helpers -------------------------------------------------------------------


def _fail(file: str, key: str, field: str, problem: str) -> RuleError:
    return RuleError(f"{file}: {key}: field {field!r} {problem}")


def _mapping(value: Any, file: str, key: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise RuleError(f"{file}: {key}: must be a mapping")
    return value


def _list(value: Any, file: str, key: str) -> list[Any]:
    if not isinstance(value, list) or not value:
        raise RuleError(f"{file}: {key}: must be a non-empty list")
    return value


def _fields(
    block: Mapping[str, Any],
    file: str,
    key: str,
    required: Iterable[str],
    optional: Iterable[str] = (),
) -> None:
    required = tuple(required)
    unknown = sorted(set(block) - set(required) - set(optional))
    if unknown:
        raise _fail(file, key, ", ".join(unknown), "is not a field of this table")
    missing = [name for name in required if name not in block]
    if missing:
        raise _fail(file, key, ", ".join(missing), "is required")


def _text(block: Mapping[str, Any], file: str, key: str, field: str) -> str:
    value = block.get(field)
    if not isinstance(value, str) or not value.strip():
        raise _fail(file, key, field, "must be a non-empty string")
    return " ".join(value.split())


def _source(block: Mapping[str, Any], file: str, key: str, field: str) -> str | None:
    """A source value as written (``None``: the blank value), never trimmed or rewritten."""
    value = block.get(field)
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise _fail(file, key, field, "must be a string or null")
    return value


def _flag(block: Mapping[str, Any], file: str, key: str, field: str) -> bool:
    value = block.get(field)
    if not isinstance(value, bool):
        raise _fail(file, key, field, "must be true or false")
    return value


def _vocab(value: Any, kind: str, file: str, key: str, field: str) -> str:
    if not isinstance(value, str) or not vocabulary.is_known(kind, value):
        raise _fail(file, key, field, f"{value!r} is not a {kind} value of the case vocabulary")
    return value


def _vocab_or_none(value: Any, kind: str, file: str, key: str, field: str) -> str | None:
    return None if value is None else _vocab(value, kind, file, key, field)


def _choice(value: Any, allowed: Iterable[str], file: str, key: str, field: str) -> str:
    allowed = tuple(allowed)
    if not isinstance(value, str) or value not in allowed:
        raise _fail(file, key, field, f"must be one of {', '.join(allowed)}; got {value!r}")
    return value


def _attribution(block: Mapping[str, Any], file: str, key: str, rationale: str) -> tuple[str, str]:
    """The actor and classification, checked against each other and the rationale."""
    actor = _vocab(block.get("actor_type"), "actor_type", file, key, "actor_type")
    discretion = _vocab(
        block.get("judicial_discretion_classification"),
        "judicial_discretion_classification",
        file,
        key,
        "judicial_discretion_classification",
    )
    if actor in NON_JUDICIAL_ACTORS and discretion != "non_judicial":
        raise _fail(
            file,
            key,
            "judicial_discretion_classification",
            f"must be non_judicial for actor {actor}",
        )
    if actor == UNKNOWN and discretion != UNKNOWN:
        raise _fail(file, key, "judicial_discretion_classification", "must be unknown")
    if UNKNOWN in (actor, discretion) and UNKNOWN_REASON not in rationale:
        raise _fail(file, key, "rationale", f"must say the value is {UNKNOWN_REASON!r}")
    return actor, discretion


# --- table readers ------------------------------------------------------------------------


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_manifest(directory: Path) -> Mapping[str, tuple[int, str]]:
    path = directory / TABLES_FILE
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RuleError(f"{TABLES_FILE}: cannot be read ({exc.__class__.__name__})") from exc
    except yaml.YAMLError as exc:
        raise RuleError(f"{TABLES_FILE}: not valid YAML ({exc.__class__.__name__})") from exc
    block = _mapping(payload, TABLES_FILE, "tables.yaml")
    _fields(block, TABLES_FILE, "tables.yaml", ("tables",))
    tables = _mapping(block["tables"], TABLES_FILE, "tables")
    if set(tables) != set(TABLE_FILES):
        raise _fail(
            TABLES_FILE,
            "tables",
            "tables",
            f"must list exactly {', '.join(TABLE_FILES)}; got {', '.join(sorted(tables))}",
        )
    entries: dict[str, tuple[int, str]] = {}
    for name, file in TABLE_FILES.items():
        entry = _mapping(tables[name], TABLES_FILE, name)
        _fields(entry, TABLES_FILE, name, ("file", "version", "sha256"))
        if entry["file"] != file:
            raise _fail(TABLES_FILE, name, "file", f"must be {file!r} (the module constant)")
        version = entry["version"]
        if isinstance(version, bool) or not isinstance(version, int) or version < 1:
            raise _fail(TABLES_FILE, name, "version", "must be a positive integer")
        if version != RULE_VERSIONS[name]:
            raise _fail(
                TABLES_FILE,
                name,
                "version",
                f"is {version} but the code expects {RULE_VERSIONS[name]} (RULE_VERSIONS)",
            )
        digest = entry["sha256"]
        if not isinstance(digest, str) or not _SHA256.match(digest):
            raise _fail(TABLES_FILE, name, "sha256", "must be 64 lowercase hex digits")
        entries[name] = (version, digest)
    return entries


def _read_table(directory: Path, name: str, digest: str) -> str:
    """A table's text, refused unless its bytes hash to the digest tables.yaml pins."""
    file = TABLE_FILES[name]
    try:
        data = (directory / file).read_bytes()
    except OSError as exc:
        raise RuleError(f"{file}: cannot be read ({exc.__class__.__name__})") from exc
    if _sha256(data) != digest:
        raise _fail(
            TABLES_FILE,
            name,
            "sha256",
            f"does not match {file}: an edit must bump the table's version beside its digest",
        )
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuleError(f"{file}: not UTF-8") from exc


def _yaml(name: str, text: str, version: int) -> Mapping[str, Any]:
    file = TABLE_FILES[name]
    try:
        payload = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise RuleError(f"{file}: not valid YAML ({exc.__class__.__name__})") from exc
    block = _mapping(payload, file, file)
    if block.get("version") != version:
        raise _fail(file, file, "version", f"must be {version}, the version tables.yaml pins")
    return block


def _csv(name: str, text: str, headers: tuple[str, ...]) -> list[dict[str, str]]:
    file = TABLE_FILES[name]
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if tuple(reader.fieldnames or ()) != headers:
        raise _fail(file, "header", "header", f"must be {', '.join(headers)}")
    rows: list[dict[str, str]] = []
    for line, row in enumerate(reader, start=2):
        if None in row or any(value is None for value in row.values()):
            raise _fail(file, f"line {line}", "row", "must have exactly the header's columns")
        rows.append(row)
    if not rows:
        raise RuleError(f"{file}: has no rows")
    return rows


# --- attribution_rules.yaml ---------------------------------------------------------------

_DISPOSITION_FIELDS = (
    "charge_disposition",
    "charge_disposition_reason",
    "disposition",
    "final",
    "actor_type",
    "judicial_discretion_classification",
    "event_type",
    "cites",
    "rationale",
)


def _disposition_rule(
    block: Mapping[str, Any], file: str, key: str, *, fallback: bool
) -> DispositionRule:
    required = _DISPOSITION_FIELDS[2:] if fallback else _DISPOSITION_FIELDS
    _fields(block, file, key, required, ("judicial_ruling",))
    rationale = _text(block, file, key, "rationale")
    disposition = _vocab(block.get("disposition"), "charge_disposition", file, key, "disposition")
    final = _flag(block, file, key, "final")
    if final != vocabulary.is_known(FINAL_KIND, disposition):
        raise _fail(
            file, key, "final", f"must be {not final} for disposition {disposition} ({FINAL_KIND})"
        )
    actor, discretion = _attribution(block, file, key, rationale)
    if fallback and (final or actor != UNKNOWN):
        raise _fail(file, key, "final", "the fallback is never final and never attributed")
    return DispositionRule(
        charge_disposition=None if fallback else _source(block, file, key, "charge_disposition"),
        charge_disposition_reason=(
            None if fallback else _source(block, file, key, "charge_disposition_reason")
        ),
        disposition=disposition,
        final=final,
        actor_type=actor,
        judicial_discretion_classification=discretion,
        judicial_ruling=_vocab_or_none(
            block.get("judicial_ruling"), "judicial_ruling", file, key, "judicial_ruling"
        ),
        event_type=_vocab_or_none(block.get("event_type"), "event_type", file, key, "event_type"),
        cites=_choice(block.get("cites"), CITES, file, key, "cites"),
        rationale=rationale,
        fallback=fallback,
    )


def _felony_review_rule(
    block: Mapping[str, Any], file: str, key: str, *, fallback: bool
) -> FelonyReviewRule:
    fields = ("outcome", "actor_type", "judicial_discretion_classification", "cites", "rationale")
    _fields(block, file, key, fields if fallback else ("felony_review_result", *fields))
    rationale = _text(block, file, key, "rationale")
    actor, discretion = _attribution(block, file, key, rationale)
    return FelonyReviewRule(
        felony_review_result=(
            None if fallback else _source(block, file, key, "felony_review_result")
        ),
        outcome=_vocab_or_none(block.get("outcome"), "charging_outcome", file, key, "outcome"),
        actor_type=actor,
        judicial_discretion_classification=discretion,
        cites=_choice(block.get("cites"), CITES, file, key, "cites"),
        rationale=rationale,
        fallback=fallback,
    )


def _diversion_program_rule(
    block: Mapping[str, Any], file: str, key: str, *, fallback: bool
) -> DiversionProgramRule:
    fields = ("stage", "actor_type", "judicial_discretion_classification", "cites", "rationale")
    _fields(block, file, key, fields if fallback else ("diversion_program", *fields))
    rationale = _text(block, file, key, "rationale")
    actor, discretion = _attribution(block, file, key, rationale)
    stage = _vocab_or_none(block.get("stage"), "diversion_stage", file, key, "stage")
    if stage is None and UNKNOWN_REASON not in rationale:
        raise _fail(file, key, "rationale", f"must say a null stage is {UNKNOWN_REASON!r}")
    return DiversionProgramRule(
        diversion_program=None if fallback else _source(block, file, key, "diversion_program"),
        stage=stage,
        actor_type=actor,
        judicial_discretion_classification=discretion,
        cites=_choice(block.get("cites"), CITES, file, key, "cites"),
        rationale=rationale,
        fallback=fallback,
    )


def _event_rule(
    block: Mapping[str, Any], file: str, key: str, value_field: str | None
) -> EventRule:
    fields = ("event_type", "cites", "rationale")
    _fields(block, file, key, fields if value_field is None else (value_field, *fields))
    return EventRule(
        value=None if value_field is None else _source(block, file, key, value_field),
        event_type=_vocab_or_none(block.get("event_type"), "event_type", file, key, "event_type"),
        cites=_choice(block.get("cites"), CITES, file, key, "cites"),
        rationale=_text(block, file, key, "rationale"),
        fallback=value_field is None,
    )


def _unique(keys: Sequence[Any], file: str, section: str, field: str) -> None:
    seen: set[Any] = set()
    for value in keys:
        if value in seen:
            raise _fail(file, f"{section}[{value!r}]", field, "is listed twice")
        seen.add(value)


@dataclass(frozen=True, slots=True)
class AttributionTables:
    dispositions: Mapping[tuple[str | None, str | None], DispositionRule]
    disposition_fallback: DispositionRule
    felony_review: Mapping[str | None, FelonyReviewRule]
    felony_review_fallback: FelonyReviewRule
    diversion_programs: Mapping[str | None, DiversionProgramRule]
    diversion_program_fallback: DiversionProgramRule
    diversion_results: Mapping[str | None, EventRule]
    diversion_result_fallback: EventRule
    initiation_events: Mapping[str | None, EventRule]
    no_probable_cause: NoProbableCauseRule
    summary: Mapping[str, Any]


ATTRIBUTION_SECTIONS: tuple[str, ...] = (
    "version",
    "documentation",
    "unknown_reason",
    "dispositions",
    "fallback",
    "felony_review",
    "felony_review_fallback",
    "diversion_programs",
    "diversion_program_fallback",
    "diversion_results",
    "diversion_result_fallback",
    "initiation_events",
    "finding_no_probable_cause",
    "summary",
)


def _parse_attribution(block: Mapping[str, Any]) -> AttributionTables:
    file = TABLE_FILES[ATTRIBUTION]
    _fields(block, file, file, ATTRIBUTION_SECTIONS)
    if block["unknown_reason"] != UNKNOWN_REASON:
        raise _fail(file, file, "unknown_reason", f"must be {UNKNOWN_REASON!r}")
    dispositions: list[DispositionRule] = []
    for index, entry in enumerate(_list(block["dispositions"], file, "dispositions")):
        rule = _disposition_rule(
            _mapping(entry, file, f"dispositions[{index}]"),
            file,
            f"dispositions[{index}]",
            fallback=False,
        )
        if rule.charge_disposition is None:
            raise _fail(file, f"dispositions[{index}]", "charge_disposition", "must be a value")
        dispositions.append(rule)
    pairs = [(r.charge_disposition, r.charge_disposition_reason) for r in dispositions]
    _unique(pairs, file, "dispositions", "charge_disposition_reason")
    felony = [
        _felony_review_rule(
            _mapping(e, file, f"felony_review[{i}]"), file, f"felony_review[{i}]", fallback=False
        )
        for i, e in enumerate(_list(block["felony_review"], file, "felony_review"))
    ]
    _unique([r.felony_review_result for r in felony], file, "felony_review", "result")
    programs = [
        _diversion_program_rule(
            _mapping(e, file, f"diversion_programs[{i}]"),
            file,
            f"diversion_programs[{i}]",
            fallback=False,
        )
        for i, e in enumerate(_list(block["diversion_programs"], file, "diversion_programs"))
    ]
    _unique([r.diversion_program for r in programs], file, "diversion_programs", "program")
    results = [
        _event_rule(
            _mapping(e, file, f"diversion_results[{i}]"),
            file,
            f"diversion_results[{i}]",
            "diversion_result",
        )
        for i, e in enumerate(_list(block["diversion_results"], file, "diversion_results"))
    ]
    _unique([r.value for r in results], file, "diversion_results", "diversion_result")
    events = [
        _event_rule(
            _mapping(e, file, f"initiation_events[{i}]"), file, f"initiation_events[{i}]", "event"
        )
        for i, e in enumerate(_list(block["initiation_events"], file, "initiation_events"))
    ]
    _unique([r.value for r in events], file, "initiation_events", "event")
    fnpc = _mapping(block["finding_no_probable_cause"], file, "finding_no_probable_cause")
    _fields(
        fnpc,
        file,
        "finding_no_probable_cause",
        ("value", "event_type", "judicial_ruling", "actor_type", "cites", "rationale"),
    )
    no_probable_cause = NoProbableCauseRule(
        value=_text(fnpc, file, "finding_no_probable_cause", "value"),
        event_type=_vocab(
            fnpc.get("event_type"), "event_type", file, "finding_no_probable_cause", "event_type"
        ),
        judicial_ruling=_vocab(
            fnpc.get("judicial_ruling"),
            "judicial_ruling",
            file,
            "finding_no_probable_cause",
            "judicial_ruling",
        ),
        actor_type=_vocab(
            fnpc.get("actor_type"), "actor_type", file, "finding_no_probable_cause", "actor_type"
        ),
        cites=_choice(fnpc.get("cites"), CITES, file, "finding_no_probable_cause", "cites"),
        rationale=_text(fnpc, file, "finding_no_probable_cause", "rationale"),
    )
    summary = block["summary"]
    if not isinstance(summary, dict):
        raise _fail(file, "summary", "summary", "must be a mapping")
    return AttributionTables(
        dispositions=MappingProxyType(
            {(r.charge_disposition, r.charge_disposition_reason): r for r in dispositions}
        ),
        disposition_fallback=_disposition_rule(
            _mapping(block["fallback"], file, "fallback"), file, "fallback", fallback=True
        ),
        felony_review=MappingProxyType({r.felony_review_result: r for r in felony}),
        felony_review_fallback=_felony_review_rule(
            _mapping(block["felony_review_fallback"], file, "felony_review_fallback"),
            file,
            "felony_review_fallback",
            fallback=True,
        ),
        diversion_programs=MappingProxyType({r.diversion_program: r for r in programs}),
        diversion_program_fallback=_diversion_program_rule(
            _mapping(block["diversion_program_fallback"], file, "diversion_program_fallback"),
            file,
            "diversion_program_fallback",
            fallback=True,
        ),
        diversion_results=MappingProxyType({r.value: r for r in results}),
        diversion_result_fallback=_event_rule(
            _mapping(block["diversion_result_fallback"], file, "diversion_result_fallback"),
            file,
            "diversion_result_fallback",
            None,
        ),
        initiation_events=MappingProxyType({r.value: r for r in events}),
        no_probable_cause=no_probable_cause,
        summary=MappingProxyType(dict(summary)),
    )


# --- pretrial_rules.yaml ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PretrialTables:
    act_effective: date
    bonds: Mapping[tuple[str, str], PretrialRule]
    em_flag_value: str
    em_condition: str


def _parse_pretrial(block: Mapping[str, Any]) -> PretrialTables:
    file = TABLE_FILES[PRETRIAL]
    _fields(
        block,
        file,
        file,
        ("version", "documentation", "released_means", "regimes", "electronic_monitoring", "bonds"),
    )
    _text(block, file, file, "released_means")
    regimes = _list(block["regimes"], file, "regimes")
    names = [_mapping(r, file, "regimes").get("name") for r in regimes]
    if names != list(REGIMES):
        raise _fail(file, "regimes", "name", f"must be {', '.join(REGIMES)} in that order")
    first = _mapping(regimes[0], file, MONETARY_BAIL)
    second = _mapping(regimes[1], file, PRETRIAL_FAIRNESS_ACT)
    _fields(first, file, MONETARY_BAIL, ("name", "until", "description"))
    _fields(second, file, PRETRIAL_FAIRNESS_ACT, ("name", "from", "description"))
    try:
        until = date.fromisoformat(str(first["until"]))
        start = date.fromisoformat(str(second["from"]))
    except ValueError as exc:
        raise _fail(file, "regimes", "from", "must be an ISO date") from exc
    if until != start:
        raise _fail(file, "regimes", "from", "must equal the earlier regime's `until`")
    em = _mapping(block["electronic_monitoring"], file, "electronic_monitoring")
    _fields(em, file, "electronic_monitoring", ("flag_value", "condition", "blank"))
    bonds: dict[tuple[str, str], PretrialRule] = {}
    for index, entry in enumerate(_list(block["bonds"], file, "bonds")):
        key = f"bonds[{index}]"
        rule_block = _mapping(entry, file, key)
        _fields(
            rule_block,
            file,
            key,
            (
                "bond_type",
                "regime",
                "release_type",
                "detained_flag",
                "releases",
                "actor_type",
                "judicial_discretion_classification",
                "rationale",
            ),
        )
        rationale = _text(rule_block, file, key, "rationale")
        actor, discretion = _attribution(rule_block, file, key, rationale)
        release_type = _vocab(
            rule_block.get("release_type"), "release_type", file, key, "release_type"
        )
        detained = _flag(rule_block, file, key, "detained_flag")
        releases = _flag(rule_block, file, key, "releases")
        if detained != (release_type == "detained"):
            raise _fail(file, key, "detained_flag", "must be true exactly for a detained release")
        if releases and (detained or release_type == "monetary_bond"):
            raise _fail(
                file, key, "releases", "a detention or a deposit or cash bond claims no release"
            )
        rule = PretrialRule(
            bond_type=_text(rule_block, file, key, "bond_type"),
            regime=_choice(rule_block.get("regime"), REGIMES, file, key, "regime"),
            release_type=release_type,
            detained_flag=detained,
            releases=releases,
            actor_type=actor,
            judicial_discretion_classification=discretion,
            rationale=rationale,
        )
        if (rule.bond_type, rule.regime) in bonds:
            raise _fail(file, key, "bond_type", "is listed twice under its regime")
        bonds[(rule.bond_type, rule.regime)] = rule
    for bond_type in {bond for bond, _ in bonds}:
        for regime in REGIMES:
            if (bond_type, regime) not in bonds:
                raise _fail(file, f"bonds[{bond_type!r}]", "regime", f"has no {regime} rule")
    return PretrialTables(
        act_effective=start,
        bonds=MappingProxyType(bonds),
        em_flag_value=_text(em, file, "electronic_monitoring", "flag_value"),
        em_condition=_vocab(
            em.get("condition"), "release_condition", file, "electronic_monitoring", "condition"
        ),
    )


# --- sentence_rules.yaml ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SentenceTables:
    maximum_days: int
    units: Mapping[str, UnitRule]
    phases: Mapping[str, PhaseRule]
    sentence_types: Mapping[str, SentenceTypeRule]
    commitment_types: Mapping[str, CommitmentTypeRule]


def _parse_sentence(block: Mapping[str, Any]) -> SentenceTables:
    file = TABLE_FILES[SENTENCE]
    _fields(
        block,
        file,
        file,
        (
            "version",
            "documentation",
            "grain",
            "terms",
            "current",
            "supersedes",
            "rounding",
            "maximum_days",
            "maximum_days_reason",
            "units",
            "phases",
            "sentence_types",
            "commitment_types",
        ),
    )
    for field in ("grain", "terms", "current", "supersedes", "maximum_days_reason"):
        _text(block, file, file, field)
    if block["rounding"] != "half_up":
        raise _fail(file, file, "rounding", "must be half_up")
    maximum = block["maximum_days"]
    if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum < 1:
        raise _fail(file, file, "maximum_days", "must be a positive integer")
    units: dict[str, UnitRule] = {}
    for index, entry in enumerate(_list(block["units"], file, "units")):
        key = f"units[{index}]"
        unit = _mapping(entry, file, key)
        _fields(unit, file, key, ("commitment_unit", "days_per_unit", "flag", "reason"))
        raw = unit.get("days_per_unit")
        flag = _vocab_or_none(unit.get("flag"), "sentence_term_flag", file, key, "flag")
        factor: Decimal | None = None
        if raw is not None:
            try:
                factor = Decimal(str(raw))
            except InvalidOperation as exc:
                raise _fail(file, key, "days_per_unit", "must be a decimal string") from exc
            if not isinstance(raw, str) or factor <= 0:
                raise _fail(file, key, "days_per_unit", "must be a positive decimal string")
        if (factor is None) == (flag is None):
            raise _fail(file, key, "flag", "a unit has a day count or a flag, never both")
        name = _text(unit, file, key, "commitment_unit")
        if name in units:
            raise _fail(file, key, "commitment_unit", "is listed twice")
        units[name] = UnitRule(name, factor, flag, _text(unit, file, key, "reason"))
    phases: dict[str, PhaseRule] = {}
    for index, entry in enumerate(_list(block["phases"], file, "phases")):
        key = f"phases[{index}]"
        phase = _mapping(entry, file, key)
        _fields(
            phase,
            file,
            key,
            ("sentence_phase", "phase", "ignored", "supersedes_earlier", "revocation", "rationale"),
        )
        ignored = _flag(phase, file, key, "ignored")
        canonical = _vocab_or_none(phase.get("phase"), "sentence_phase", file, key, "phase")
        if ignored != (canonical is None):
            raise _fail(file, key, "phase", "is null exactly for an ignored phase")
        name = _text(phase, file, key, "sentence_phase")
        if name in phases:
            raise _fail(file, key, "sentence_phase", "is listed twice")
        phases[name] = PhaseRule(
            sentence_phase=name,
            phase=canonical,
            ignored=ignored,
            supersedes_earlier=_flag(phase, file, key, "supersedes_earlier"),
            revocation=_flag(phase, file, key, "revocation"),
            rationale=_text(phase, file, key, "rationale"),
        )
    types: dict[str, SentenceTypeRule] = {}
    for index, entry in enumerate(_list(block["sentence_types"], file, "sentence_types")):
        key = f"sentence_types[{index}]"
        item = _mapping(entry, file, key)
        _fields(
            item,
            file,
            key,
            ("sentence_type", "component", "flag", "terminates_probation", "reason"),
        )
        terminates = item.get("terminates_probation")
        if terminates is not None:
            terminates = _choice(terminates, TERMINATIONS, file, key, "terminates_probation")
        component = _vocab_or_none(
            item.get("component"), "sentence_component", file, key, "component"
        )
        if terminates is not None and component is not None:
            raise _fail(file, key, "component", "a termination adds no component")
        name = _text(item, file, key, "sentence_type")
        if name in types:
            raise _fail(file, key, "sentence_type", "is listed twice")
        types[name] = SentenceTypeRule(
            sentence_type=name,
            component=component,
            flag=_vocab_or_none(item.get("flag"), "sentence_term_flag", file, key, "flag"),
            terminates_probation=terminates,
            reason=_text(item, file, key, "reason"),
        )
    commitments: dict[str, CommitmentTypeRule] = {}
    for index, entry in enumerate(_list(block["commitment_types"], file, "commitment_types")):
        key = f"commitment_types[{index}]"
        item = _mapping(entry, file, key)
        _fields(item, file, key, ("commitment_type", "component", "flag", "reason"))
        name = _text(item, file, key, "commitment_type")
        if name in commitments:
            raise _fail(file, key, "commitment_type", "is listed twice")
        commitments[name] = CommitmentTypeRule(
            commitment_type=name,
            component=_vocab_or_none(
                item.get("component"), "sentence_component", file, key, "component"
            ),
            flag=_vocab_or_none(item.get("flag"), "sentence_term_flag", file, key, "flag"),
            reason=_text(item, file, key, "reason"),
        )
    return SentenceTables(
        maximum_days=maximum,
        units=MappingProxyType(units),
        phases=MappingProxyType(phases),
        sentence_types=MappingProxyType(types),
        commitment_types=MappingProxyType(commitments),
    )


# --- offense_map.csv ----------------------------------------------------------------------


def _parse_offense(rows: list[dict[str, str]]) -> Mapping[tuple[str, str], str]:
    file = TABLE_FILES[OFFENSE]
    mapping: dict[tuple[str, str], str] = {}
    for line, row in enumerate(rows, start=2):
        key = f"line {line}"
        field = _choice(row["field"], tuple(OFFENSE_FIELDS), file, key, "field")
        canonical = _vocab(
            row["canonical_value"], OFFENSE_FIELDS[field], file, key, "canonical_value"
        )
        source = row["source_value"]
        if source != source.strip():
            raise _fail(file, key, "source_value", "must not carry outer whitespace")
        if (field, source) in mapping:
            raise _fail(file, key, "source_value", "is listed twice")
        if canonical == UNKNOWN:
            raise _fail(file, key, "canonical_value", "must name a category, never unknown")
        mapping[(field, source)] = canonical
    return MappingProxyType(mapping)


# --- courts.yaml --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CourtTables:
    jurisdiction: Jurisdiction
    courts: Mapping[str, Court]
    parent_key: str
    court_names: Mapping[str | None, str]
    facilities: Mapping[str | None, str | None]


def _parse_courts(block: Mapping[str, Any]) -> CourtTables:
    file = TABLE_FILES[COURTS]
    _fields(
        block,
        file,
        file,
        (
            "version",
            "documentation",
            "jurisdiction",
            "courts",
            "court_names",
            "facilities",
            "case_court",
        ),
    )
    _text(block, file, file, "case_court")
    j = _mapping(block["jurisdiction"], file, "jurisdiction")
    _fields(
        j, file, "jurisdiction", ("key", "name", "jurisdiction_type", "state_code", "fips_code")
    )
    jurisdiction = Jurisdiction(
        key=_text(j, file, "jurisdiction", "key"),
        name=_text(j, file, "jurisdiction", "name"),
        jurisdiction_type=_choice(
            j.get("jurisdiction_type"),
            tuple(member.value for member in JurisdictionType),
            file,
            "jurisdiction",
            "jurisdiction_type",
        ),
        state_code=_text(j, file, "jurisdiction", "state_code"),
        fips_code=_text(j, file, "jurisdiction", "fips_code"),
    )
    courts: dict[str, Court] = {}
    for index, entry in enumerate(_list(block["courts"], file, "courts")):
        key = f"courts[{index}]"
        item = _mapping(entry, file, key)
        _fields(item, file, key, ("key", "name", "court_type", "district", "seat", "parent"))
        court_key = _text(item, file, key, "key")
        if not _KEY.match(court_key) or court_key in courts:
            raise _fail(file, key, "key", "must be a unique lowercase slug")
        district = item.get("district")
        if district is not None and (isinstance(district, bool) or not isinstance(district, int)):
            raise _fail(file, key, "district", "must be an integer or null")
        seat = item.get("seat")
        parent = item.get("parent")
        courts[court_key] = Court(
            key=court_key,
            name=_text(item, file, key, "name"),
            court_type=_text(item, file, key, "court_type"),
            district=district,
            seat=None if seat is None else _text(item, file, key, "seat"),
            parent=None if parent is None else _text(item, file, key, "parent"),
        )
    parents = [court.key for court in courts.values() if court.parent is None]
    if len(parents) != 1:
        raise _fail(file, "courts", "parent", "exactly one court is the parent court")
    for court in courts.values():
        if court.parent is not None and court.parent not in courts:
            raise _fail(file, f"courts[{court.key!r}]", "parent", "names no court")
        if (court.district is None) != (court.parent is None):
            raise _fail(file, f"courts[{court.key!r}]", "district", "only a district has a parent")
    names: dict[str | None, str] = {}
    for index, entry in enumerate(_list(block["court_names"], file, "court_names")):
        key = f"court_names[{index}]"
        item = _mapping(entry, file, key)
        _fields(item, file, key, ("court_name", "court", "reason"))
        _text(item, file, key, "reason")
        name = _source(item, file, key, "court_name")
        target = item.get("court")
        if target not in courts or name in names:
            raise _fail(file, key, "court", "must name a court, once per court name")
        names[name] = str(target)
    facilities: dict[str | None, str | None] = {}
    for index, entry in enumerate(_list(block["facilities"], file, "facilities")):
        key = f"facilities[{index}]"
        item = _mapping(entry, file, key)
        _fields(item, file, key, ("facility", "court", "reason"))
        _text(item, file, key, "reason")
        name = _source(item, file, key, "facility")
        target = item.get("court")
        if (target is not None and target not in courts) or name in facilities:
            raise _fail(file, key, "court", "must name a court (or null), once per facility")
        facilities[name] = None if target is None else str(target)
    if None not in names or None not in facilities:
        raise _fail(file, "court_names", "court_name", "the blank value must be mapped")
    return CourtTables(
        jurisdiction=jurisdiction,
        courts=MappingProxyType(courts),
        parent_key=parents[0],
        court_names=MappingProxyType(names),
        facilities=MappingProxyType(facilities),
    )


# --- judge_aliases.csv and judges.csv -----------------------------------------------------


@dataclass(frozen=True, slots=True)
class JudgeTables:
    aliases: Mapping[str, JudgeAlias]
    by_normalized: Mapping[str, JudgeAlias]
    judges: Mapping[str, JudgeEntry]


def _parse_judges(
    alias_rows: list[dict[str, str]], judge_rows: list[dict[str, str]]
) -> JudgeTables:
    afile = TABLE_FILES[JUDGE_ALIASES]
    jfile = TABLE_FILES[JUDGES]
    judges: dict[str, JudgeEntry] = {}
    for line, row in enumerate(judge_rows, start=2):
        key = f"line {line}"
        judge_key = row["judge_key"]
        if not _KEY.match(judge_key) or judge_key in judges:
            raise _fail(jfile, key, "judge_key", "must be a unique lowercase slug")
        display = row["display_name"]
        if not display or display != " ".join(display.split()):
            raise _fail(jfile, key, "display_name", "must be non-empty with single spaces")
        judges[judge_key] = JudgeEntry(
            judge_key=judge_key,
            display_name=display,
            position=_vocab(row["position"], "position", jfile, key, "position"),
        )
    aliases: dict[str, JudgeAlias] = {}
    by_normalized: dict[str, JudgeAlias] = {}
    used: set[str] = set()
    for line, row in enumerate(alias_rows, start=2):
        key = f"line {line}"
        source = row["source_string"]
        if not source.strip() or source in aliases:
            raise _fail(afile, key, "source_string", "must be a non-blank string, listed once")
        normalized = row["normalized"]
        if normalized != normalize_person_name(source):
            raise _fail(afile, key, "normalized", "must be normalize_person_name(source_string)")
        if normalized in by_normalized:
            raise _fail(afile, key, "normalized", "is shared with another row")
        status = _choice(row["status"], STATUSES, afile, key, "status")
        alias_key = row["judge_key"] or None
        rule = row["rule"]
        candidates = tuple(row["candidates"].split(";")) if row["candidates"] else ()
        reason = row["reason"]
        if status == RESOLVED:
            if alias_key not in judges:
                raise _fail(afile, key, "judge_key", "must name a judges.csv key")
            _choice(rule, RESOLVING_RULES, afile, key, "rule")
            if candidates:
                raise _fail(afile, key, "candidates", "a resolved row names no candidates")
            used.add(str(alias_key))
        else:
            if alias_key is not None:
                raise _fail(afile, key, "judge_key", f"must be empty when {status}")
            _choice(rule, HOLDING_RULES, afile, key, "rule")
            if status == AMBIGUOUS and len(candidates) < 2:
                raise _fail(afile, key, "candidates", "an ambiguous row names its candidates")
        for candidate in candidates:
            if candidate not in judges:
                raise _fail(afile, key, "candidates", f"{candidate!r} is not a judges.csv key")
        if rule != EXACT and not reason.strip():
            raise _fail(afile, key, "reason", "every row but an exact one states its reason")
        alias = JudgeAlias(source, normalized, status, alias_key, rule, candidates, reason)
        aliases[source] = alias
        by_normalized[normalized] = alias
    orphans = sorted(set(judges) - used)
    if orphans:
        raise _fail(jfile, orphans[0], "judge_key", "is resolved by no alias")
    return JudgeTables(
        aliases=MappingProxyType(aliases),
        by_normalized=MappingProxyType(by_normalized),
        judges=MappingProxyType(judges),
    )


# --- the loaded tables and their matchers -------------------------------------------------


def _blank(value: str | None) -> bool:
    return value is None or not value.strip()


@dataclass(frozen=True, slots=True)
class CookSaoRules:
    """Every Cook County rule table, validated, with total and deterministic matchers."""

    versions: Mapping[str, int]
    digests: Mapping[str, str]
    attribution: AttributionTables
    pretrial: PretrialTables
    sentence: SentenceTables
    offense: Mapping[tuple[str, str], str]
    courts: CourtTables
    judges: JudgeTables

    # attribution ------------------------------------------------------------------------

    def disposition(self, charge_disposition: str | None, reason: str | None) -> DispositionRule:
        """The exact pair's rule, else the disposition's ``*`` rule, else the fallback."""
        if _blank(charge_disposition):
            return self.attribution.disposition_fallback
        reason = None if _blank(reason) else reason
        rules = self.attribution.dispositions
        return (
            rules.get((charge_disposition, reason))
            or rules.get((charge_disposition, WILDCARD))
            or self.attribution.disposition_fallback
        )

    def felony_review(self, result: str | None) -> FelonyReviewRule | None:
        """The result's rule (``None`` when no result is recorded), else the fallback."""
        if _blank(result):
            return None
        return self.attribution.felony_review.get(result) or self.attribution.felony_review_fallback

    def diversion_program(self, program: str | None) -> DiversionProgramRule:
        if _blank(program):
            return self.attribution.diversion_program_fallback
        return (
            self.attribution.diversion_programs.get(program)
            or self.attribution.diversion_program_fallback
        )

    def diversion_result(self, result: str | None) -> EventRule:
        key = None if _blank(result) else result
        return (
            self.attribution.diversion_results.get(key)
            or self.attribution.diversion_result_fallback
        )

    def initiation_event(self, event: str | None) -> EventRule | None:
        """The charging event's rule; ``None`` for a value no rule lists."""
        return self.attribution.initiation_events.get(None if _blank(event) else event)

    def no_probable_cause(self, flag: str | None) -> NoProbableCauseRule | None:
        """The finding's rule when the flag carries the documented value, else ``None``."""
        rule = self.attribution.no_probable_cause
        return rule if flag is not None and flag.strip() == rule.value else None

    # pretrial ---------------------------------------------------------------------------

    def regime(self, bond_date: date) -> str:
        return PRETRIAL_FAIRNESS_ACT if bond_date >= self.pretrial.act_effective else MONETARY_BAIL

    def pretrial_rule(self, bond_type: str | None, bond_date: date | None) -> PretrialMatch:
        """A bond's decision rule by its type and its own date, or why none is drafted."""
        if bond_type is None or _blank(bond_type):
            return PretrialMatch(None, NO_BOND_TYPE)
        if bond_date is None:
            return PretrialMatch(None, NO_BOND_DATE)
        rule = self.pretrial.bonds.get((bond_type, self.regime(bond_date)))
        if rule is None:
            return PretrialMatch(None, UNLISTED_BOND_TYPE)
        return PretrialMatch(rule, None)

    def electronic_monitoring(self, flag: str | None) -> str | None:
        """The release condition a set electronic-monitoring flag records, else ``None``."""
        if flag is not None and flag.strip() == self.pretrial.em_flag_value:
            return self.pretrial.em_condition
        return None

    # sentences --------------------------------------------------------------------------

    def term_days(self, term: str | None, unit: str | None) -> TermDays:
        """The exact conversion of a commitment term and unit to whole days (half up)."""
        if unit is None or _blank(unit):
            return TermDays(None, MISSING_TERM)
        rule = self.sentence.units.get(unit)
        if rule is None:
            return TermDays(None, UNPARSEABLE_TERM)
        if rule.days_per_unit is None:
            return TermDays(None, rule.flag)
        if term is None or _blank(term):
            return TermDays(None, MISSING_TERM)
        text = term.strip()
        if not _TERM.match(text):
            return TermDays(None, UNPARSEABLE_TERM)
        days = (Decimal(text) * rule.days_per_unit).quantize(Decimal(1), rounding=ROUND_HALF_UP)
        if days > self.sentence.maximum_days:
            return TermDays(None, IMPLAUSIBLE_TERM)
        return TermDays(int(days), None)

    def sentence_row(
        self,
        phase: str | None,
        sentence_type: str | None,
        commitment_type: str | None,
        term: str | None,
        unit: str | None,
    ) -> SentenceRowMatch:
        """One Sentencing row: its phase semantics, components, term in days, and flags."""
        phase_rule = None if _blank(phase) else self.sentence.phases.get(str(phase))
        type_rule = (
            None if _blank(sentence_type) else self.sentence.sentence_types.get(str(sentence_type))
        )
        commitment = (
            None
            if _blank(commitment_type)
            else self.sentence.commitment_types.get(str(commitment_type))
        )
        commitment_known = _blank(commitment_type) or commitment is not None
        matched = phase_rule is not None and type_rule is not None and commitment_known
        converted = self.term_days(term, unit)
        flags = {converted.flag} if converted.flag else set()
        components: list[str] = []
        term_component: str | None = None
        terminates = type_rule.terminates_probation if type_rule else None
        if type_rule is not None:
            if type_rule.flag:
                flags.add(type_rule.flag)
            if terminates is None:
                if type_rule.component:
                    components.append(type_rule.component)
                term_component = (
                    commitment.component if commitment and commitment.component else None
                ) or type_rule.component
                if commitment is not None and commitment.flag:
                    flags.add(commitment.flag)
                if term_component and term_component not in components:
                    components.append(term_component)
        order = vocabulary.values("sentence_term_flag")
        return SentenceRowMatch(
            matched=matched,
            phase=phase_rule.phase if phase_rule else None,
            ignored=phase_rule.ignored if phase_rule else False,
            supersedes_earlier=phase_rule.supersedes_earlier if phase_rule else False,
            revocation=phase_rule.revocation if phase_rule else False,
            components=tuple(components),
            term_component=term_component,
            days=converted.days if term_component else None,
            flags=tuple(flag for flag in order if flag in flags),
            terminates_probation=terminates,
        )

    # offenses, courts, judges -----------------------------------------------------------

    def offense_category(self, value: str | None) -> str | None:
        """The canonical category, or ``None``: an unmapped value is an error, no catch-all."""
        if value is None or _blank(value):
            return None
        return self.offense.get(("offense_category", value))

    def severity(self, class_value: str | None) -> str | None:
        """The canonical severity of a class (blank: the table's blank row), else ``None``."""
        key = "" if class_value is None or _blank(class_value) else class_value
        return self.offense.get(("class", key))

    def court_of_row(self, court_name: str | None, facility: str | None) -> CourtMatch | None:
        """A row's court: its court name's, a district courthouse's when the name is blank.

        ``None`` for a court name or courthouse no rule lists.
        """
        name = None if _blank(court_name) else court_name
        place = None if _blank(facility) else facility
        if name not in self.courts.court_names or place not in self.courts.facilities:
            return None
        court = self.courts.court_names[name]
        if name is None and self.courts.facilities[place] is not None:
            court = str(self.courts.facilities[place])
        return CourtMatch(court_key=court, facility=place)

    def case_court(self, row_courts: Iterable[str]) -> str:
        """A case's court from its rows' courts: its one district, else the parent court."""
        districts = {
            key for key in row_courts if key in self.courts.courts and key != self.courts.parent_key
        }
        return districts.pop() if len(districts) == 1 else self.courts.parent_key

    def judge(self, value: str | None) -> JudgeMatch | None:
        """A judge string's key or status (by the string, then its normalized form)."""
        if value is None or _blank(value):
            return None
        alias = self.judges.aliases.get(value) or self.judges.by_normalized.get(
            normalize_person_name(value)
        )
        if alias is None:
            return JudgeMatch(UNRESOLVED, None, (), NOT_IN_TABLE)
        return JudgeMatch(alias.status, alias.judge_key, alias.candidates, alias.reason)


# --- restricted categories ----------------------------------------------------------------


def restricted_category(kind: str, value: str | None) -> str | None:
    """A race or gender label as the vocabulary lists it: normalized, never recoded.

    Letter case and punctuation are normalized (``"White [Hispanic or Latino]"``
    → ``white_hispanic_or_latino``); a blank is ``unknown``; a label the
    vocabulary does not list is ``None`` (the connector rejects it).
    """
    if kind not in RESTRICTED_SOURCE_KINDS:
        msg = f"{kind!r} is not a restricted kind of this source"
        raise ValueError(msg)
    if value is None or _blank(value):
        return UNKNOWN
    normalized = _NOT_ALNUM.sub("_", value.strip().lower()).strip("_")
    return normalized if vocabulary.is_known(kind, normalized) else None


# --- summary ------------------------------------------------------------------------------


def _share(part: int, whole: int) -> float:
    return round(part / whole, 6) if whole else 0.0


def summarize(rules: CookSaoRules, pairs: Iterable[Sequence[Any]]) -> dict[str, Any]:
    """The attribution summary over (disposition, reason, rows) triples (the profile's)."""
    rows = 0
    distinct = 0
    unknown_rows = 0
    unknown_pairs = 0
    final_rows = 0
    fallback_pairs = 0
    by_actor: dict[str, int] = {}
    for disposition, reason, count in pairs:
        rule = rules.disposition(disposition, reason)
        rows += int(count)
        distinct += 1
        by_actor[rule.actor_type] = by_actor.get(rule.actor_type, 0) + int(count)
        if rule.actor_type == UNKNOWN:
            unknown_rows += int(count)
            unknown_pairs += 1
        if rule.final:
            final_rows += int(count)
        if rule.fallback:
            fallback_pairs += 1
    order = vocabulary.values("actor_type")
    return {
        "rows": rows,
        "pairs": distinct,
        "fallback_pairs": fallback_pairs,
        "unknown_actor_rows": unknown_rows,
        "unknown_actor_pairs": unknown_pairs,
        "unknown_actor_share": _share(unknown_rows, rows),
        "final_rows": final_rows,
        "final_share": _share(final_rows, rows),
        "actor_shares": {
            actor: _share(by_actor[actor], rows) for actor in order if by_actor.get(actor)
        },
    }


# --- loading ------------------------------------------------------------------------------


def parse_rules(directory: Path) -> CookSaoRules:
    """Every table of ``directory`` (named by the module constants), validated."""
    manifest = _read_manifest(directory)
    text = {name: _read_table(directory, name, digest) for name, (_, digest) in manifest.items()}
    return CookSaoRules(
        versions=MappingProxyType({name: version for name, (version, _) in manifest.items()}),
        digests=MappingProxyType({name: digest for name, (_, digest) in manifest.items()}),
        attribution=_parse_attribution(
            _yaml(ATTRIBUTION, text[ATTRIBUTION], RULE_VERSIONS[ATTRIBUTION])
        ),
        pretrial=_parse_pretrial(_yaml(PRETRIAL, text[PRETRIAL], RULE_VERSIONS[PRETRIAL])),
        sentence=_parse_sentence(_yaml(SENTENCE, text[SENTENCE], RULE_VERSIONS[SENTENCE])),
        offense=_parse_offense(_csv(OFFENSE, text[OFFENSE], OFFENSE_HEADERS)),
        courts=_parse_courts(_yaml(COURTS, text[COURTS], RULE_VERSIONS[COURTS])),
        judges=_parse_judges(
            _csv(JUDGE_ALIASES, text[JUDGE_ALIASES], ALIAS_HEADERS),
            _csv(JUDGES, text[JUDGES], JUDGE_HEADERS),
        ),
    )


@lru_cache(maxsize=1)
def load_rules() -> CookSaoRules:
    """The committed tables (``data/reference/cook_sao/``), validated once per process."""
    return parse_rules(TABLES_DIR)


__all__ = [
    "RULE_VERSIONS",
    "RULE_VERSION_TAG",
    "TABLES_DIR",
    "TABLE_FILES",
    "CookSaoRules",
    "RuleError",
    "load_rules",
    "parse_rules",
    "restricted_category",
    "summarize",
]
