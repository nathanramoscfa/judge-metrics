# src/judgemetrics/ingest/cook_sao/connector.py
"""``CookSaoConnector``: the Cook County State's Attorney case-level datasets.

Parser version ``1+<RULE_VERSION_TAG>`` (Phase 5 Step 4): it fetches, stores, parses,
and normalizes the five exports through Step 3's rule tables, and a change to any
table's version re-derives every stored export (``rules.RULE_VERSIONS``).

``discover`` lists the five current datasets from constants and makes no
network call (the runner calls it in fixture mode too). ``fetch`` first
reads the dataset's portal metadata — the rows-updated time, the license,
the attribution, the column list — into the artifact's response metadata,
which the runner records on the ``source_record``. When the rows-updated
time equals the one the previous record carries (the runner forwards it
as ``previous_rows_updated_at`` beside the previous digest), the export is
unchanged and nothing is downloaded. Otherwise the export streams to a
temporary file in the run's work directory under ``MAX_EXPORT_BYTES``,
hashed while it is written, with the previous ``ETag`` and
``Last-Modified`` sent so a ``304`` also short-circuits. Validation reads
the header row only and checks it, and the metadata's column list, against
the verified headers (missing → error naming the header, extra → warning).

``load_context`` (the runner calls it with all five artifacts whenever any is to be
parsed) validates the headers, reads every export into a sorted Polars frame, and
derives the judges and their services (``context.py``). ``parse`` then walks the exports
together in case-id order and yields, for each case and export, one record standing for
that export's rows of the case, attributed to that export's ``source_record``;
``normalize`` returns the drafts ``case.build_case`` assigned to it. Every entity of a
case spans several exports (a charge's offense is in Initiation, its disposition in
Dispositions), so a run that parses any export re-derives them all, and the upserts
write only what changed. The first ``parse`` call of a run streams the whole corpus; the
later calls of the same run yield nothing. Rows a rule table cannot place are left out
and reported as findings (``findings.py``, ``run_issues``), never as exceptions.

Nothing here logs a participant id, a case id, or a restricted value: the
fetch logs dataset names, sizes, and digests only.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import httpx
from pydantic import SecretStr

from judgemetrics.capabilities import CASE, SUPERVISION, SourceCapabilities
from judgemetrics.config import Settings, get_settings
from judgemetrics.ingest.base import (
    HEADER_ROWS_UPDATED_AT,
    PREVIOUS_ETAG,
    PREVIOUS_LAST_MODIFIED,
    PREVIOUS_ROWS_UPDATED_AT,
    PREVIOUS_SHA256,
    CanonicalRecord,
    CourtDraft,
    FetchError,
    IngestError,
    JudgeDraft,
    JudgeServiceDraft,
    JurisdictionDraft,
    NaturalKey,
    RawArtifact,
    RunIssue,
    SourceArtifact,
    SourceInfo,
    SourceRecordDraft,
    ValidationResult,
    utc_now,
)
from judgemetrics.ingest.cook_sao import sources
from judgemetrics.ingest.cook_sao.case import Env, build_case
from judgemetrics.ingest.cook_sao.context import CookContext
from judgemetrics.ingest.cook_sao.findings import Findings
from judgemetrics.ingest.cook_sao.rules import RULE_VERSION_TAG, CookSaoRules, load_rules
from judgemetrics.ingest.cook_sao.schema import (
    COVERAGE_END,
    COVERAGE_START,
    DATASET_ORDER,
    DISPOSITIONS_FILE,
    VERIFIED_HEADERS,
)
from judgemetrics.ingest.http import (
    DEFAULT_RETRIES,
    Sleep,
    download,
    download_to_file,
    make_client,
)
from judgemetrics.ingest.registry import register
from judgemetrics.logging import get_logger
from judgemetrics.normalization import vocabulary
from judgemetrics.normalization.names import normalize_person_name
from judgemetrics.security.identifiers import require_identifier_pepper

log = get_logger(__name__)

ClientFactory = Callable[[], httpx.AsyncClient]

# The largest export measured on 2026-10-05 is Initiation's, 512,058,076
# bytes (the five total 1,221,648,291); the cap, 1.5 GiB, is more than twice
# it, so a modest growth never fails a run and a runaway body still stops.
MAX_EXPORT_BYTES = 3 * 512 * 1024 * 1024
# A dataset's metadata document is about 80 KB.
MAX_METADATA_BYTES = 5 * 1024 * 1024
# The portal builds an export on the fly; allow a longer pause between reads.
EXPORT_TIMEOUT_SECONDS = 120.0

# Keys this connector adds to ``RawArtifact.response_headers`` (recorded in
# ``source_record.metadata``) besides ``rows_updated_at``.
META_PORTAL_ID = "portal_id"
META_LICENSE = "license"
META_ATTRIBUTION = "attribution"
META_COLUMNS = "columns"
META_METADATA_URL = "metadata_url"
COLUMN_SEPARATOR = ","

REDISTRIBUTION = {
    "aggregates": "yes",
    "record_level": "unverified",
    "commercial": "unverified",
}
# What the source can and cannot show (docs/METHODOLOGY.md "Source limitations",
# rendered from here beside the capabilities and the observable outcomes).
LIMITATIONS: tuple[str, ...] = (
    "Felony cases of three State's Attorney's Office bureaus received from 2011-01-01; the "
    "corpus ends on 2024-12-30, so every outcome window is right-censored there, and a row "
    "the exports date outside that window (a disposition before 2011, a typo year) enters "
    "no observation.",
    "A person is a case participation: the exports carry no identifier that follows a "
    "defendant from one case to another (participant ids are per case and re-hashed for "
    "every release), so no cross-case outcome - a new case, a new charge, a reconviction - "
    "is observable and no person history enters any measure.",
    "The judge on a disposition is the exports' JUDGE, which the SAO glossary defines as "
    'the "Judge who oversaw the case", read as the judge who entered the disposition; the '
    'sentencing judge is SENTENCE_JUDGE, the "Judge who oversaw the sentencing". The '
    "exports record no judge assignment and name no bond judge, so a judge metric gated on "
    "an assignment or on the deciding judge is not attributable for this source.",
    "A bond type records the bond court's decision, not a release: an individual (I) bond "
    "releases the person on recognizance, while a deposit (D) or cash (C) bond permits "
    "release once posted, which the exports do not record. The court-level pretrial counts "
    "and shares count these decisions; no judge does. From 2023-09-18 (the Pretrial "
    "Fairness Act) an I bond is a release whose discretion is unknown (the exports do not "
    "record whether the State petitioned to detain) and a D or C bond has an unknown actor "
    "and discretion.",
    "A revocation is read from a probation-violation sentencing in the same case: it "
    "revokes the probation the case's sentence imposed (scope supervision) and counts "
    "toward the revocation rates after a sentence and after a disposition; a revoked "
    "pretrial release is not recorded. Failure to appear is not observable: a bond "
    "forfeiture warrant appears only as a charge's last state.",
    "Each sentencing decision counts once: an amended or corrected sentencing replaces the "
    "sentence it corrects, while an original sentence and a later probation-violation, "
    "resentencing, or remand sentencing are separate decisions, each attributed to its own "
    "judge.",
)


@dataclass(frozen=True, slots=True)
class PortalMetadata:
    """What the portal's metadata document says about one dataset."""

    portal_id: str
    rows_updated_at: str
    license: str
    attribution: str
    columns: tuple[str, ...]

    def as_headers(self, metadata_url: str) -> dict[str, str]:
        return {
            META_PORTAL_ID: self.portal_id,
            HEADER_ROWS_UPDATED_AT: self.rows_updated_at,
            META_LICENSE: self.license,
            META_ATTRIBUTION: self.attribution,
            META_COLUMNS: COLUMN_SEPARATOR.join(self.columns),
            META_METADATA_URL: metadata_url,
        }


def parse_portal_metadata(data: bytes, *, portal_id: str) -> PortalMetadata:
    """The Socrata ``/api/views/<id>.json`` document → ``PortalMetadata``.

    ``rowsUpdatedAt`` (epoch seconds) becomes ISO 8601 UTC; the column list
    is the display names the export's header row carries, without the
    portal's ``:``-prefixed system columns.
    """
    try:
        document: Any = json.loads(data)
        if document.get("id") != portal_id:
            msg = f"metadata of {document.get('id')!r} where {portal_id!r} was requested"
            raise FetchError(msg)
        rows_updated = datetime.fromtimestamp(int(document["rowsUpdatedAt"]), UTC)
        license_name = str((document.get("license") or {}).get("name") or "")
        columns = tuple(
            str(column["name"])
            for column in document["columns"]
            if not str(column.get("fieldName", "")).startswith(":")
        )
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        msg = f"unreadable portal metadata for {portal_id}: {type(exc).__name__}"
        raise FetchError(msg) from exc
    return PortalMetadata(
        portal_id=portal_id,
        rows_updated_at=rows_updated.isoformat(),
        license=license_name,
        attribution=str(document.get("attribution") or ""),
        columns=columns,
    )


def read_header(raw: RawArtifact) -> list[str]:
    """The header row of a CSV artifact, reading its first line only."""
    if isinstance(raw.path_or_bytes, Path):
        with raw.path_or_bytes.open(encoding="utf-8-sig", newline="") as handle:
            return next(csv.reader(handle), [])
    text = raw.path_or_bytes.decode("utf-8-sig")
    return next(csv.reader(io.StringIO(text)), [])


def _header_problems(
    name: str, origin: str, headers: Iterable[str], verified: tuple[str, ...]
) -> tuple[list[str], list[str]]:
    present = list(headers)
    errors = [
        f"{name}: verified header {header!r} is missing from the {origin}"
        for header in verified
        if header not in present
    ]
    warnings = [
        f"{name}: {origin} header {header!r} is not in the verified set"
        for header in present
        if header not in verified
    ]
    return errors, warnings


@register
class CookSaoConnector:
    source_id = sources.SOURCE_ID
    # "1+<table versions>": a rule-table edit bumps a version, which re-derives every row.
    parser_version = f"1+{RULE_VERSION_TAG}"
    source_info = SourceInfo(
        owner="Cook County State's Attorney's Office",
        source_type="government_open_data",
        access_method="socrata_bulk_export",
        terms_metadata={
            "portal": sources.PORTAL_URL,
            "terms": sources.TERMS_URL,
            "license": "Public Domain",
            "attribution": sources.ATTRIBUTION,
            "attribution_url": sources.ATTRIBUTION_URL,
            "documentation": [sources.GLOSSARY_URL, sources.FLOWCHART_URL],
            "redistribution": REDISTRIBUTION,
            "datasets": {d.external_id: d.portal_id for d in sources.DATASETS},
        },
        # A probation-violation sentencing is a within-case revocation; no cross-case outcome
        # (new case, new charge, reconviction) is observable: the corpus has no person key.
        observable_outcomes=("revocation",),
        # Phase 5 Step 5: the exports name the judge of a disposition (JUDGE) and of a
        # sentencing (SENTENCE_JUDGE) and no other; a person is a case participation; the
        # one revocation they document revokes the probation a sentence imposed.
        capabilities=SourceCapabilities(
            judge_gates=("disposing_judge", "sentencing_judge"),
            person_key_scope=CASE,
            revocation_scopes=(SUPERVISION,),
        ),
        limitations=LIMITATIONS,
    )

    def __init__(
        self,
        client_factory: ClientFactory | None = None,
        *,
        max_bytes: int = MAX_EXPORT_BYTES,
        retries: int = DEFAULT_RETRIES,
        sleep: Sleep = asyncio.sleep,
        work_dir: Path | None = None,
        pepper: SecretStr | None = None,
        settings: Settings | None = None,
        rules: CookSaoRules | None = None,
    ) -> None:
        self._client_factory = client_factory or (lambda: make_client(EXPORT_TIMEOUT_SECONDS))
        self._max_bytes = max_bytes
        self._retries = retries
        self._sleep = sleep
        self._work_dir = work_dir
        self._pepper = pepper
        self._settings = settings
        self._rules = rules
        self._context: CookContext | None = None
        self._findings = Findings()
        self._streamed = False

    def use_work_dir(self, directory: Path) -> None:
        self._work_dir = directory

    async def discover(self) -> list[SourceArtifact]:
        return [
            SourceArtifact(
                source_id=self.source_id,
                external_id=dataset.external_id,
                uri=dataset.export_url,
                content_type="text/csv",
                metadata={"dataset": dataset.name, META_PORTAL_ID: dataset.portal_id},
            )
            for dataset in sources.DATASETS
        ]

    async def fetch(self, artifact: SourceArtifact) -> RawArtifact:
        dataset = sources.DATASETS_BY_EXTERNAL_ID.get(artifact.external_id)
        if dataset is None:
            msg = f"{artifact.external_id}: not a Cook County SAO artifact"
            raise FetchError(msg)
        if self._work_dir is None:
            msg = "the Cook County connector streams to a work directory; none was set"
            raise FetchError(msg)
        bound = log.bind(source=self.source_id, dataset=dataset.name)
        async with self._client_factory() as client:
            answer = await download(
                client,
                dataset.metadata_url,
                max_bytes=MAX_METADATA_BYTES,
                retries=self._retries,
                sleep=self._sleep,
            )
            portal = parse_portal_metadata(answer.data, portal_id=dataset.portal_id)
            headers = portal.as_headers(dataset.metadata_url)
            previous_sha256 = artifact.metadata.get(PREVIOUS_SHA256)
            previous_rows = artifact.metadata.get(PREVIOUS_ROWS_UPDATED_AT)
            if previous_sha256 and previous_rows == portal.rows_updated_at:
                bound.info("cook_sao.export.unchanged", rows_updated_at=portal.rows_updated_at)
                return RawArtifact.unchanged(
                    artifact,
                    sha256=previous_sha256,
                    retrieved_at=utc_now(),
                    response_headers=headers,
                )
            bound.info("cook_sao.export.downloading", rows_updated_at=portal.rows_updated_at)
            result = await download_to_file(
                client,
                dataset.export_url,
                directory=self._work_dir,
                etag=artifact.metadata.get(PREVIOUS_ETAG),
                last_modified=artifact.metadata.get(PREVIOUS_LAST_MODIFIED),
                max_bytes=self._max_bytes,
                retries=self._retries,
                sleep=self._sleep,
            )
        retrieved_at = utc_now()
        if result.not_modified or result.path is None or result.sha256 is None:
            if not previous_sha256:
                msg = f"{artifact.external_id}: 304 Not Modified without a previous sha256"
                raise FetchError(msg)
            return RawArtifact.unchanged(
                artifact,
                sha256=previous_sha256,
                retrieved_at=retrieved_at,
                response_headers={**result.headers, **headers},
            )
        bound.info("cook_sao.export.downloaded", size_bytes=result.size_bytes, sha256=result.sha256)
        return RawArtifact.from_path(
            artifact,
            result.path,
            retrieved_at=retrieved_at,
            response_headers={**result.headers, **headers},
            sha256=result.sha256,
            size_bytes=result.size_bytes,
        )

    def validate_raw(self, artifact: RawArtifact) -> ValidationResult:
        if artifact.not_modified:
            return ValidationResult.passed()
        name = artifact.artifact.external_id
        verified = VERIFIED_HEADERS.get(name)
        if verified is None:
            return ValidationResult.failed([f"{name}: not a Cook County SAO artifact"])
        try:
            headers = read_header(artifact)
        except (UnicodeDecodeError, csv.Error) as exc:
            return ValidationResult.failed([f"{name}: no readable CSV header row ({exc})"])
        if not headers or not any(header.strip() for header in headers):
            return ValidationResult.failed([f"{name}: the file is empty or has no header row"])
        errors, warnings = _header_problems(name, "export", headers, verified)
        columns = artifact.response_headers.get(META_COLUMNS)
        if columns:
            meta_errors, meta_warnings = _header_problems(
                name, "portal metadata", columns.split(COLUMN_SEPARATOR), verified
            )
            errors += meta_errors
            warnings += meta_warnings
        if errors:
            return ValidationResult.failed(errors, warnings)
        return ValidationResult.passed(warnings)

    # --- context, coverage, parsing, normalization ---------------------------------------

    def _rule_tables(self) -> CookSaoRules:
        if self._rules is None:
            self._rules = load_rules()
        return self._rules

    def _identifier_pepper(self) -> SecretStr:
        if self._pepper is None:
            settings = self._settings if self._settings is not None else get_settings()
            self._pepper = require_identifier_pepper(settings)
        return self._pepper

    def load_context(self, artifacts: Sequence[RawArtifact]) -> None:
        """Read all five exports into the indexes ``parse`` walks (``SupportsContext``)."""
        by_id = {raw.artifact.external_id: raw for raw in artifacts}
        sources_by_name: dict[str, Path | bytes] = {}
        problems: list[str] = []
        for name in DATASET_ORDER:
            raw = by_id.get(name)
            if raw is None:
                problems.append(f"{name}: not retrieved")
                continue
            result = self.validate_raw(raw)
            problems.extend(result.errors)
            sources_by_name[name] = raw.path_or_bytes
        if problems:
            msg = "the Cook County exports cannot be read: " + "; ".join(problems)
            raise IngestError(msg)
        self._findings = Findings()
        self._streamed = False
        self._context = CookContext.build(sources_by_name, self._rule_tables(), self._findings)

    def coverage_window(self) -> tuple[date, date] | None:
        """The corpus window: Intake and Initiation begin on 2011-01-01, the SAO stopped on 2024-12-30."""
        return COVERAGE_START, COVERAGE_END

    def run_issues(self) -> Sequence[RunIssue]:
        """What the run left out or flagged (``SupportsRunIssues``), after it has been parsed."""
        return self._findings.issues()

    def parse(self, artifact: RawArtifact) -> Iterable[SourceRecordDraft]:
        """The whole corpus, once per run (see the module docstring); later calls yield nothing."""
        if self._context is None or self._streamed:
            return []
        self._streamed = True
        return self._records(self._context)

    def _records(self, context: CookContext) -> Iterator[SourceRecordDraft]:
        rules = self._rule_tables()
        env = Env(rules=rules, pepper=self._identifier_pepper(), findings=self._findings)
        yield SourceRecordDraft(
            external_record_id="reference",
            effective_at=None,
            payload={"drafts": _reference_drafts(context, rules)},
            record_type="reference",
            artifact_id=DISPOSITIONS_FILE,
            rows=0,
        )
        for case_id, rows in context.cases():
            drafts = build_case(case_id, rows, env)
            for name in DATASET_ORDER:
                count = len(rows.get(name, ()))
                mine = drafts[name] if drafts is not None else []
                if count or mine:
                    yield SourceRecordDraft(
                        external_record_id=case_id,
                        effective_at=None,
                        payload={"drafts": mine},
                        record_type=name,
                        artifact_id=name,
                        rows=count,
                    )
        self._context = None

    def normalize(self, record: SourceRecordDraft) -> Iterable[CanonicalRecord]:
        drafts: list[CanonicalRecord] = record.payload["drafts"]
        return drafts


JUDGE_IDENTITY_SYSTEM = "cook_sao_judge"
COURT_IDENTITY_SYSTEM = "cook_sao_court"
SERVICE_BASIS = "first and last attributed disposition or sentence date"


def _reference_drafts(context: CookContext, rules: CookSaoRules) -> list[CanonicalRecord]:
    """The jurisdiction, the courts, the referenced judges, and their derived services."""
    tables = rules.courts
    jurisdiction = JurisdictionDraft(
        name=tables.jurisdiction.name,
        type=tables.jurisdiction.jurisdiction_type,
        state_code=tables.jurisdiction.state_code,
        fips_code=tables.jurisdiction.fips_code,
    )
    drafts: list[CanonicalRecord] = [jurisdiction]
    court_keys: dict[str, NaturalKey] = {}
    for court in tables.courts.values():
        draft = CourtDraft(
            canonical_name=court.name,
            court_type=court.court_type,
            jurisdiction_key=jurisdiction.natural_key,
            external_ids={COURT_IDENTITY_SYSTEM: court.key},
            state_code=tables.jurisdiction.state_code,
        )
        drafts.append(draft)
        court_keys[court.key] = draft.natural_key
    for judge_key in sorted(context.services):
        entry = rules.judges.judges[judge_key]
        judge = JudgeDraft(
            canonical_name=entry.display_name,
            normalized_name=normalize_person_name(entry.display_name),
            identity_key=(JUDGE_IDENTITY_SYSTEM, judge_key),
            external_ids={JUDGE_IDENTITY_SYSTEM: judge_key},
            status="unknown",
        )
        drafts.append(judge)
        for court_key, span in sorted(context.services[judge_key].items()):
            drafts.append(
                JudgeServiceDraft(
                    judge_key=judge.natural_key,
                    court_key=court_keys[court_key],
                    position_type=vocabulary.require("position", entry.position),
                    start_date=span.start,
                    end_date=span.end,
                    metadata={"derived": True, "basis": SERVICE_BASIS},
                )
            )
    return drafts
