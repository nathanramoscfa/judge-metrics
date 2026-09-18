# src/judgemetrics/entity_resolution/pipeline.py
"""The staged person-resolution pipeline: the ingest hook and ``rerun``.

The brief's four stages run in order on every candidate pair —
deterministic (a shared stable identifier), rules (reliable combinations,
never a name alone), probabilistic (the ``Scorer``, stubbed until Phase
7), then the manual-review queue for whatever is left — and the pipeline
stops at the first decisive stage (``evaluate``). Every pair that reached
the pipeline is stored as a candidate with its features, score, stage,
decision, and a trace of what each stage said.

Two entry points serve the ingest runner, both inside the run's single
transaction:

- ``resolve_persons(session, drafts, run)`` at step 10 finds each draft's
  person by its stable source identifier (the deterministic stage applied
  to incoming rows) or creates it, together with its identifier rows, and
  returns the person id per draft key;
- ``resolve_candidates(session, person_ids, run)`` right after step 12,
  once the run's cases and parties are published, generates candidate
  pairs among the run's persons and every existing person they block
  with, applies the stages, writes the candidates, applies system merges,
  and returns the merge map so the run's published ids follow it.

The split exists because case linkage — a rule-stage feature — is read
from the published rows, which keeps one feature code path for the hook
and for ``rerun(session, source=...)``, the ``er run`` command that
recomputes candidates for all persons (or one source's) under the current
model version without re-ingesting.

Idempotency: a second ingest of unchanged files parses nothing and calls
neither entry point with work; a forced re-parse finds the same persons
by stable identifier, blocks the same pairs, and upserts identical rows
(no write), and merged persons are never blocked again. A human decision
is never overwritten and its pair is never re-merged or re-rejected by
the system.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from judgemetrics.db.models import Base, IngestRun
from judgemetrics.db.models.enums import ResolutionDecision
from judgemetrics.entity_resolution import deterministic, rules, scoring
from judgemetrics.entity_resolution.candidates import (
    CandidateRow,
    Pair,
    StoredCandidate,
    UpsertCounts,
    load_candidates,
    upsert_candidates,
)
from judgemetrics.entity_resolution.config import (
    ENTITY_PERSON,
    MODEL_VERSION,
    STAGE_DETERMINISTIC,
    STAGE_PROBABILISTIC,
    STAGE_REVIEW,
    STAGE_RULE,
    SYSTEM_ACTOR,
    Thresholds,
    thresholds_for,
)
from judgemetrics.entity_resolution.features import (
    PairFeatures,
    PersonProfile,
    blocking_hashes,
    blocks_for,
    candidate_pairs,
    compute_features,
    load_profiles,
)
from judgemetrics.entity_resolution.merge import MergeError, canonical_person_id, merge_persons
from judgemetrics.entity_resolution.scoring import TRACE_SKIPPED, Scorer, StubScorer
from judgemetrics.entity_resolution.stages import StageResult
from judgemetrics.ingest.base import NaturalKey, PersonDraft, TaggedRecord, utc_now
from judgemetrics.ingest.publish import RunCounts, upsert_person_identifiers, upsert_persons
from judgemetrics.logging import get_logger

log = get_logger(__name__)

PERSON = Base.metadata.tables["person"]
SOURCE_RECORD = Base.metadata.tables["source_record"]
SOURCE = Base.metadata.tables["source"]

REASON_AMBIGUOUS = "no_decisive_stage"
SCORE_AMBIGUOUS = 0.50
TRACE_NO_SIGNAL = "no_signal"
TRACE_NO_DECISION = "no_decision"


@dataclass(frozen=True, slots=True)
class Outcome:
    """The pipeline's verdict on one pair, with the stage trace the candidate stores."""

    decision: ResolutionDecision
    score: float
    stage: str
    reason: str
    trace: dict[str, str]

    def features_payload(self, features: PairFeatures) -> dict[str, Any]:
        return {**features.as_dict(), "stage_trace": dict(self.trace)}


@dataclass(frozen=True, slots=True)
class PersonResolution:
    """What ``resolve_persons`` decided for the run's person drafts."""

    # Draft key → the person it resolved to (existing or newly created).
    ids: dict[NaturalKey, uuid.UUID]
    existing: frozenset[NaturalKey]
    created_persons: int
    created_identifiers: int


@dataclass(slots=True)
class ResolutionStats:
    pairs: int = 0
    candidates: UpsertCounts = field(default_factory=UpsertCounts)
    matched: int = 0
    rejected: int = 0
    review: int = 0
    merges: int = 0
    # drop person → keep person, for every merge this call applied.
    merged: dict[uuid.UUID, uuid.UUID] = field(default_factory=dict)

    def as_log(self) -> dict[str, int]:
        return {
            "pairs": self.pairs,
            "candidates_created": self.candidates.created,
            "candidates_updated": self.candidates.updated,
            "matched": self.matched,
            "rejected": self.rejected,
            "review": self.review,
            "merges": self.merges,
        }


# --- the stages -------------------------------------------------------------------------


def evaluate(
    features: PairFeatures,
    *,
    scorer: Scorer | None = None,
    thresholds: Thresholds | None = None,
) -> Outcome:
    """Apply the stages in order and stop at the first decisive one."""
    scorer = scorer if scorer is not None else StubScorer()
    thresholds = thresholds if thresholds is not None else thresholds_for(ENTITY_PERSON)
    trace: dict[str, str] = {}
    pending: StageResult | None = None

    first = deterministic.decide(features)
    trace[STAGE_DETERMINISTIC] = _trace(first) if first else TRACE_NO_SIGNAL
    if first is not None and first.decisive:
        return _outcome(first, trace)

    second = rules.decide(features)
    trace[STAGE_RULE] = _trace(second) if second else TRACE_NO_DECISION
    if second is not None:
        if second.decisive:
            return _outcome(second, trace)
        pending = second

    third = scoring.decide(features, scorer, thresholds)
    trace[STAGE_PROBABILISTIC] = _trace(third) if third else TRACE_SKIPPED
    if third is not None:
        if third.decisive:
            return _outcome(third, trace)
        pending = third if pending is None else pending

    if pending is not None:
        return _outcome(pending, trace)
    return Outcome(
        decision=ResolutionDecision.REVIEW,
        score=SCORE_AMBIGUOUS,
        stage=STAGE_REVIEW,
        reason=REASON_AMBIGUOUS,
        trace=trace,
    )


def _trace(result: StageResult) -> str:
    return f"{result.decision.value}:{result.reason}"


def _outcome(result: StageResult, trace: dict[str, str]) -> Outcome:
    return Outcome(
        decision=result.decision,
        score=result.score,
        stage=result.stage,
        reason=result.reason,
        trace=trace,
    )


# --- the ingest hook, part one: identity ---------------------------------------------------


def resolve_persons(
    session: Session,
    drafts: Sequence[TaggedRecord],
    run: IngestRun,
    counts: RunCounts | None = None,
) -> PersonResolution:
    """Find each draft's person by stable identifier or create it, with its identifier rows."""
    del run  # candidates are recorded against the run by ``resolve_candidates``
    keys = [item.record.natural_key for item in drafts]
    existing = deterministic.lookup_by_identity(session, keys)
    new_items = [item for item in drafts if item.record.natural_key not in existing]
    tally = counts if counts is not None else RunCounts()
    before_persons = tally.tables.get("person")
    before_identifiers = tally.tables.get("person_identifier")
    persons_before = before_persons.created if before_persons else 0
    identifiers_before = before_identifiers.created if before_identifiers else 0
    ids = upsert_persons(session, new_items, existing, tally)
    upsert_person_identifiers(session, drafts, ids, tally)
    persons_after = tally.tables["person"].created if "person" in tally.tables else 0
    identifiers_after = (
        tally.tables["person_identifier"].created if "person_identifier" in tally.tables else 0
    )
    for item in drafts:
        if not isinstance(item.record, PersonDraft):  # pragma: no cover - the runner partitions
            msg = f"expected a PersonDraft, got {type(item.record).__name__}"
            raise TypeError(msg)
    return PersonResolution(
        ids=ids,
        existing=frozenset(existing),
        created_persons=persons_after - persons_before,
        created_identifiers=identifiers_after - identifiers_before,
    )


# --- the ingest hook, part two: candidates, decisions, merges -----------------------------


def resolve_candidates(
    session: Session,
    person_ids: Sequence[uuid.UUID],
    run: IngestRun | None,
    *,
    scorer: Scorer | None = None,
    decided_at: datetime | None = None,
    actor: str = SYSTEM_ACTOR,
) -> ResolutionStats:
    """Block, evaluate, store, and merge for the run's persons and the persons they block with."""
    anchor = {canonical_person_id(session, pid) for pid in person_ids}
    if not anchor:
        return ResolutionStats()
    blocks = blocks_for(session, blocking_hashes(session, anchor))
    pairs = candidate_pairs(blocks, anchor)
    return _resolve_pairs(
        session,
        pairs,
        run_id=run.id if run is not None else None,
        scorer=scorer,
        decided_at=decided_at or (run.started_at if run is not None else utc_now()),
        actor=actor,
    )


def rerun(
    session: Session,
    *,
    source: str | None = None,
    scorer: Scorer | None = None,
    actor: str = SYSTEM_ACTOR,
) -> ResolutionStats:
    """Recompute candidates for every person (or one source's) under the current model version."""
    if source is None:
        blocks = blocks_for(session, None)
        pairs = candidate_pairs(blocks)
    else:
        members = set(
            session.execute(
                select(PERSON.c.id)
                .join(SOURCE_RECORD, SOURCE_RECORD.c.id == PERSON.c.source_record_id)
                .join(SOURCE, SOURCE.c.id == SOURCE_RECORD.c.source_id)
                .where(SOURCE.c.name == source, PERSON.c.merged_into_person_id.is_(None))
            ).scalars()
        )
        if not members:
            return ResolutionStats()
        blocks = blocks_for(session, blocking_hashes(session, members))
        pairs = candidate_pairs(blocks, members)
    return _resolve_pairs(
        session, pairs, run_id=None, scorer=scorer, decided_at=utc_now(), actor=actor
    )


def _resolve_pairs(
    session: Session,
    pairs: Sequence[Pair],
    *,
    run_id: uuid.UUID | None,
    scorer: Scorer | None,
    decided_at: datetime,
    actor: str,
) -> ResolutionStats:
    stats = ResolutionStats(pairs=len(pairs))
    if not pairs:
        return stats
    profiles = load_profiles(session, {pid for pair in pairs for pid in pair})
    stored = load_candidates(session, pairs, entity_type=ENTITY_PERSON, model_version=MODEL_VERSION)
    rows: list[CandidateRow] = []
    outcomes: dict[Pair, Outcome] = {}
    for left, right in pairs:
        features = compute_features(profiles[left], profiles[right])
        if not features.has_signal:
            continue
        outcome = evaluate(features, scorer=scorer)
        outcomes[(left, right)] = outcome
        existing = stored.get((left, right))
        if existing is not None and existing.human_decided:
            continue  # the human decision stands; nothing to store
        system_decided = outcome.decision is not ResolutionDecision.REVIEW
        rows.append(
            CandidateRow(
                entity_type=ENTITY_PERSON,
                left_id=left,
                right_id=right,
                model_version=MODEL_VERSION,
                features=outcome.features_payload(features),
                score=outcome.score,
                decision=outcome.decision,
                stage=outcome.stage,
                reason=outcome.reason,
                decided_at=decided_at if system_decided else None,
                decided_by=actor if system_decided else None,
                ingest_run_id=run_id,
            )
        )
    stats.candidates = upsert_candidates(session, rows)
    effective = load_candidates(
        session, outcomes, entity_type=ENTITY_PERSON, model_version=MODEL_VERSION
    )
    for pair in sorted(outcomes):
        candidate = effective.get(pair)
        if candidate is None:  # pragma: no cover - every evaluated pair was just written
            continue
        if candidate.decision is ResolutionDecision.MATCHED:
            stats.matched += 1
        elif candidate.decision is ResolutionDecision.REJECTED:
            stats.rejected += 1
        else:
            stats.review += 1
        if candidate.decision is ResolutionDecision.MATCHED and not candidate.human_decided:
            _apply_system_merge(session, candidate, stats, actor=actor, run_id=run_id)
    log.info(
        "er.resolved",
        run_id=str(run_id) if run_id else None,
        model_version=MODEL_VERSION,
        **stats.as_log(),
    )
    return stats


def _apply_system_merge(
    session: Session,
    candidate: StoredCandidate,
    stats: ResolutionStats,
    *,
    actor: str,
    run_id: uuid.UUID | None,
) -> None:
    left = canonical_person_id(session, candidate.left_id)
    right = canonical_person_id(session, candidate.right_id)
    if left == right:
        return  # already one person
    keep, drop = _keep_and_drop(session, left, right)
    try:
        merge_persons(
            session,
            keep,
            drop,
            actor=actor,
            reason=candidate.reason or "",
            stage=candidate.stage,
            confidence=candidate.score,
            payload={
                "candidate_id": str(candidate.id),
                "model_version": candidate.model_version,
                "decision": candidate.decision.value,
                "ingest_run_id": str(run_id) if run_id else None,
            },
        )
    except MergeError:
        log.warning("er.merge.skipped", candidate_id=str(candidate.id))
        return
    stats.merges += 1
    stats.merged[drop] = keep
    log.info("er.merged", candidate_id=str(candidate.id), stage=candidate.stage)


def _keep_and_drop(session: Session, a: uuid.UUID, b: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
    """The earlier-created person survives; ties break on the smaller id."""
    rows = session.execute(
        select(PERSON.c.id, PERSON.c.created_at).where(PERSON.c.id.in_([a, b]))
    ).all()
    ordered = sorted(rows, key=lambda row: (row.created_at, row.id))
    return ordered[0].id, ordered[1].id


def profiles_for(
    session: Session, person_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, PersonProfile]:
    """Profiles for callers that want to inspect features (the review queue)."""
    return load_profiles(session, person_ids)
