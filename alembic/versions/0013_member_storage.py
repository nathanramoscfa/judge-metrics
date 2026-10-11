# alembic/versions/0013_member_storage.py
"""Member storage: one row per member per family, not per observation.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-11 09:00:00+00:00

Phase 5 Step 6 (docs/DATA_MODEL.md "Member families", docs/ARCHITECTURE.md
"Metrics engine"). Revision 0005 stored every member of every observation, so a
case in the numerator of a rate was written once per window and once per calendar
year: 822,777 member rows for the demo's 3,426 observations before calendar years,
and at Cook County's scale a billion. The members of the observations of one
definition, subject, source, and snapshot are the same canonical rows cut
differently, so they are stored once:

- ``metric_member_family``: one row per family and content — ``members_hash`` is the
  sha256 over the member kind and the canonical rows
  (``judgemetrics.metrics.members.MemberFamily.digest``), unique with the
  definition, subject, source, and snapshot, so equal members are one family and a
  changed family is a new row (an observation that cited the old one keeps it);
  ``member_kind`` (checked against the six kinds), ``row_count``, ``member_count``.
- ``metric_member``: the family's rows, keyed ``(family_id, ordinal)`` in the
  canonical order — ``member_id`` (a public entity id, never a person id),
  ``anchor_year``, ``dimension_value``, ``counted_mask`` and ``followed_mask`` (bit
  ``i`` is the flag in the definition's ``i``-th window; bit 0 without windows) and
  ``multiplicity``.
- ``metric_observation.member_family_id`` (not null, RESTRICT, indexed).
- ``metric_observation_member`` is dropped.
- ``ingest_run.metrics_deferred_reason`` (text, nullable): why pipeline step 13 left a run's
  metrics to the next full ``metrics compute`` (the run touched more than the declared size).

The existing rows are converted: for each group of observations sharing a definition,
subject, source, and snapshot (superseded ones too) the members of every observation
are folded into one canonical family. Each observation's own multiset is recovered
exactly by the filter ``members.MemberFamily.project`` states; when several rows share
an id, year, and dimension and differ in their flags the pairing across windows is not
recorded by the observations, so it is fixed by sorted order (the same rule the engine
applies), which leaves every observation's multiset unchanged. An inconsistent group
(a year observation holding a row the whole window lacks, a distribution row counted in
two values) stops the migration with a message naming the observation: nothing is
guessed. The module is self-contained — it imports neither the models nor the engine.

Grants, from constants: the app role ``SELECT`` on both new tables (as it had on the
old one: entity ids of public rows), the ingest role ``SELECT, INSERT, UPDATE, DELETE``.
``downgrade()`` recreates ``metric_observation_member`` with its indexes and grants,
expands every observation's members from its family, and drops the new tables and the
column; ``upgrade()`` then ``downgrade()`` leaves every observation's member multiset
as it was.
"""

from __future__ import annotations

import hashlib
import uuid
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "judgemetrics_app"
INGEST_ROLE = "judgemetrics_ingest"
APP_PRIVILEGES = "SELECT"
INGEST_PRIVILEGES = "SELECT, INSERT, UPDATE, DELETE"

OBSERVATION_TABLE = "metric_observation"
DEFINITION_TABLE = "metric_definition"
SNAPSHOT_TABLE = "metric_snapshot"
SOURCE_TABLE = "source"
FAMILY_TABLE = "metric_member_family"
MEMBER_TABLE = "metric_member"
OLD_TABLE = "metric_observation_member"
FAMILY_COLUMN = "member_family_id"
RUN_TABLE = "ingest_run"
DEFERRED_COLUMN = "metrics_deferred_reason"
NEW_TABLES: tuple[str, ...] = (FAMILY_TABLE, MEMBER_TABLE)
MEMBER_KINDS: tuple[str, ...] = (
    "decision",
    "charge",
    "court_case",
    "sentence",
    "court_event",
    "justice_event",
)
# The fallback kind of a family with no member when no other family of its definition names one.
DEFAULT_KIND = "court_case"
SUBJECT_TYPE = postgresql.ENUM(
    "judge", "court", "jurisdiction", name="subject_type", create_type=False
)

UUID_TEXT = sa.UUID(as_uuid=False)
# Lightweight table definitions for the conversion's statements (the models are never imported).
OBSERVATION = sa.table(
    OBSERVATION_TABLE,
    sa.column("id", UUID_TEXT),
    sa.column("metric_definition_id", UUID_TEXT),
    sa.column("subject_type", SUBJECT_TYPE),
    sa.column("subject_id", UUID_TEXT),
    sa.column("source_id", UUID_TEXT),
    sa.column("snapshot_id", UUID_TEXT),
    sa.column("window_days", sa.Integer()),
    sa.column("calendar_year", sa.SmallInteger()),
    sa.column("dimension_value", sa.Text()),
    sa.column(FAMILY_COLUMN, UUID_TEXT),
)
DEFINITION = sa.table(
    DEFINITION_TABLE,
    sa.column("id", UUID_TEXT),
    sa.column("kind", sa.Text()),
    sa.column("windows_days", postgresql.JSONB()),
    sa.column("dimension", sa.Text()),
)
FAMILY = sa.table(
    FAMILY_TABLE,
    sa.column("id", UUID_TEXT),
    sa.column("metric_definition_id", UUID_TEXT),
    sa.column("subject_type", SUBJECT_TYPE),
    sa.column("subject_id", UUID_TEXT),
    sa.column("source_id", UUID_TEXT),
    sa.column("snapshot_id", UUID_TEXT),
    sa.column("member_kind", sa.Text()),
    sa.column("members_hash", sa.CHAR(64)),
    sa.column("row_count", sa.Integer()),
    sa.column("member_count", sa.Integer()),
)
MEMBER = sa.table(
    MEMBER_TABLE,
    sa.column("family_id", UUID_TEXT),
    sa.column("ordinal", sa.Integer()),
    sa.column("member_id", UUID_TEXT),
    sa.column("anchor_year", sa.SmallInteger()),
    sa.column("dimension_value", sa.Text()),
    sa.column("counted_mask", sa.SmallInteger()),
    sa.column("followed_mask", sa.SmallInteger()),
    sa.column("multiplicity", sa.Integer()),
)
OLD = sa.table(
    OLD_TABLE,
    sa.column("observation_id", UUID_TEXT),
    sa.column("member_kind", sa.Text()),
    sa.column("member_id", UUID_TEXT),
    sa.column("counted", sa.Boolean()),
    sa.column("followed", sa.Boolean()),
)

FAMILY_KEY = "uq_metric_member_family_key"
FAMILY_FK_OBSERVATION = "fk_metric_observation_member_family_id_metric_member_family"
FAMILY_INDEX_OBSERVATION = "ix_metric_observation_member_family_id"

# How the columns of a family row read for a kind of metric (judgemetrics.metrics.members).
PLAIN = "plain"
BELONGS_TO = "belongs_to"
COUNTED_IN = "counted_in"
WINDOWED_KINDS = ("windowed_rate", "survival", "observed_expected")
BATCH = 5000

# An atom is (member id, anchor year or None, dimension or None, counted mask, followed mask);
# a row of a family is an atom with its multiplicity.
Atom = tuple[str, int | None, str | None, int, int]
Row = tuple[str, int | None, str | None, int, int, int]


class ConversionError(RuntimeError):
    """The stored members of a group of observations do not fold into one family."""


def _quoted(values: Sequence[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _role_exists(role: str) -> bool:
    bind = op.get_bind()
    return bool(
        bind.execute(
            sa.text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": role}
        ).scalar()
    )


def _apply_grants() -> None:
    """Role and table names and privileges are fixed module constants, never input."""
    for table in NEW_TABLES:
        if _role_exists(APP_ROLE):
            op.execute(f"GRANT {APP_PRIVILEGES} ON TABLE {table} TO {APP_ROLE}")
        if _role_exists(INGEST_ROLE):
            op.execute(f"GRANT {INGEST_PRIVILEGES} ON TABLE {table} TO {INGEST_ROLE}")


# --- the canonical family: rows, order, and digest ---------------------------------------------


def _sort_key(row: Row | Atom) -> tuple[Any, ...]:
    ident, year, dimension, counted, followed = row[0], row[1], row[2], row[3], row[4]
    return (
        ident,
        (year is not None, year or 0),
        (dimension is not None, dimension or ""),
        counted,
        followed,
    )


def _rows(atoms: Sequence[Atom]) -> list[Row]:
    """Merge identical atoms into rows with a multiplicity, in canonical order."""
    merged = Counter(atoms)
    return [
        (*atom, copies) for atom, copies in sorted(merged.items(), key=lambda p: _sort_key(p[0]))
    ]


def _digest(kind: str, rows: Sequence[Row]) -> str:
    lines = [
        f"{ident}|{'' if year is None else year}|{dimension or ''}|{counted}|{followed}|{copies}"
        for ident, year, dimension, counted, followed, copies in rows
    ]
    return hashlib.sha256((f"{kind}\n" + "\n".join(lines)).encode("utf-8")).hexdigest()


# --- upgrade: fold the observations' members into a family ------------------------------------


def _mode(kind: str, dimension: str | None) -> str:
    if kind == "distribution":
        return COUNTED_IN
    if kind == "median" and dimension is not None:
        return BELONGS_TO
    return PLAIN


def _windows(kind: str, windows_days: Sequence[int] | None) -> tuple[int | None, ...]:
    if kind in WINDOWED_KINDS and windows_days:
        return tuple(windows_days)
    return (None,)


def _subtract(whole: Counter[Any], parts: Sequence[Counter[Any]], what: str) -> Counter[Any]:
    """``whole`` less every part, as multisets; a part the whole lacks is an inconsistency."""
    remaining = Counter(whole)
    for part in parts:
        remaining.subtract(part)
    if any(count < 0 for count in remaining.values()):
        msg = f"{what}: a calendar-year observation holds members the whole window lacks"
        raise ConversionError(msg)
    return +remaining


def _paired(
    ident: str, year: int | None, dimension: str | None, keys: dict[int, list[int]]
) -> list[Atom]:
    """The atoms of one id: the ``k``-th smallest ``2 * counted + followed`` of every slot to atom ``k``."""
    sizes = {len(values) for values in keys.values()}
    if len(sizes) != 1:
        msg = f"member {ident}: its windows hold different numbers of rows"
        raise ConversionError(msg)
    atoms: list[Atom] = []
    for position in range(sizes.pop()):
        counted = sum((values[position] >> 1) << slot for slot, values in keys.items())
        followed = sum((values[position] & 1) << slot for slot, values in keys.items())
        atoms.append((ident, year, dimension, counted, followed))
    return atoms


def _plain_atoms(
    year: int | None, dimension: str | None, cells: dict[int, Counter[tuple[str, bool, bool]]]
) -> list[Atom]:
    """Atoms of a group whose observations differ by window only (``cells``: slot to multiset)."""
    per_id: dict[str, dict[int, list[int]]] = {}
    for slot, members in cells.items():
        for (ident, counted, followed), copies in members.items():
            per_id.setdefault(ident, {}).setdefault(slot, []).extend(
                [2 * int(counted) + int(followed)] * copies
            )
    atoms: list[Atom] = []
    for ident in sorted(per_id):
        keys = {slot: sorted(values) for slot, values in per_id[ident].items()}
        if set(keys) != set(cells):
            msg = f"member {ident}: absent from some of the observation's windows"
            raise ConversionError(msg)
        atoms.extend(_paired(ident, year, dimension, keys))
    return atoms


def _counted_in_atoms(
    year: int | None, cells: dict[str, Counter[tuple[str, bool, bool]]]
) -> list[Atom]:
    """Atoms of a distribution group (``cells``: dimension value to multiset): the value counted in."""
    seen: dict[str, tuple[str | None, bool]] = {}
    for dimension, members in sorted(cells.items()):
        for (ident, counted, followed), copies in members.items():
            if copies != 1:
                msg = f"member {ident}: a distribution row appears {copies} times"
                raise ConversionError(msg)
            previous = seen.get(ident)
            value = dimension if counted else None
            if previous is None:
                seen[ident] = (value, followed)
                continue
            if previous[1] != followed:
                msg = f"member {ident}: followed in some values of a distribution and not others"
                raise ConversionError(msg)
            if value is not None and previous[0] is not None:
                msg = f"member {ident}: counted in two values of a distribution"
                raise ConversionError(msg)
            seen[ident] = (previous[0] if previous[0] is not None else value, followed)
    return [
        (ident, year, value, 0, int(followed)) for ident, (value, followed) in sorted(seen.items())
    ]


def _belonging_atoms(
    year: int | None, cells: dict[str, Counter[tuple[str, bool, bool]]]
) -> list[Atom]:
    """Atoms of a median-by-dimension group: a row belongs to the observation of its dimension."""
    atoms: list[Atom] = []
    for dimension, members in sorted(cells.items()):
        for (ident, counted, followed), copies in members.items():
            atoms.extend([(ident, year, dimension, int(counted), int(followed))] * copies)
    return atoms


def _group_atoms(
    mode: str,
    windows: Sequence[int | None],
    observations: Sequence[dict[str, Any]],
    members: dict[str, Counter[tuple[str, bool, bool]]],
) -> list[Atom]:
    """The atoms of one group of observations (see the module docstring)."""
    what = f"observation {observations[0]['id']}"
    by_year: dict[int | None, list[dict[str, Any]]] = {}
    for observation in observations:
        by_year.setdefault(observation["calendar_year"], []).append(observation)
    years = sorted(year for year in by_year if year is not None)

    def cells(items: Sequence[dict[str, Any]]) -> dict[Any, Counter[tuple[str, bool, bool]]]:
        found: dict[Any, Counter[tuple[str, bool, bool]]] = {}
        for item in items:
            if mode == COUNTED_IN:
                cell: Any = item["dimension_value"]
            elif mode == BELONGS_TO:
                cell = item["dimension_value"]
            else:
                cell = (
                    windows.index(item["window_days"]) if item["window_days"] in windows else None
                )
                if cell is None:
                    msg = f"{what}: window {item['window_days']} is not one of {windows}"
                    raise ConversionError(msg)
            if cell in found:
                msg = f"{what}: two observations of one kind in the same period"
                raise ConversionError(msg)
            found[cell] = members[item["id"]]
        return found

    groups: dict[int | None, dict[Any, Counter[tuple[str, bool, bool]]]] = {
        year: cells(by_year[year]) for year in years
    }
    whole = cells(by_year.get(None, []))
    if years:
        leftover = {
            cell: _subtract(counter, [groups[year].get(cell, Counter()) for year in years], what)
            for cell, counter in whole.items()
        }
        leftover = {cell: counter for cell, counter in leftover.items() if counter}
        if leftover:
            groups[None] = leftover
    elif whole:
        groups[None] = whole
    atoms: list[Atom] = []
    for year, group in groups.items():
        if mode == COUNTED_IN:
            atoms.extend(_counted_in_atoms(year, group))
        elif mode == BELONGS_TO:
            atoms.extend(_belonging_atoms(year, group))
        else:
            atoms.extend(_plain_atoms(year, None, group))
    return atoms


def _group_observations(bind: sa.Connection) -> Iterator[list[dict[str, Any]]]:
    """Observations grouped by definition, subject, source, and snapshot (superseded included)."""
    statement = (
        sa.select(
            OBSERVATION.c.id,
            OBSERVATION.c.metric_definition_id,
            OBSERVATION.c.subject_type,
            OBSERVATION.c.subject_id,
            OBSERVATION.c.source_id,
            OBSERVATION.c.snapshot_id,
            OBSERVATION.c.window_days,
            OBSERVATION.c.calendar_year,
            OBSERVATION.c.dimension_value,
            DEFINITION.c.kind,
            DEFINITION.c.windows_days,
            DEFINITION.c.dimension,
        )
        .join(DEFINITION, DEFINITION.c.id == OBSERVATION.c.metric_definition_id)
        .order_by(
            OBSERVATION.c.metric_definition_id,
            OBSERVATION.c.subject_type,
            OBSERVATION.c.subject_id,
            OBSERVATION.c.source_id,
            OBSERVATION.c.snapshot_id,
            OBSERVATION.c.calendar_year.nulls_first(),
            OBSERVATION.c.window_days.nulls_first(),
            OBSERVATION.c.dimension_value.nulls_first(),
            OBSERVATION.c.id,
        )
    )
    current: list[dict[str, Any]] = []
    key: tuple[Any, ...] | None = None
    for row in bind.execute(statement).mappings():
        item = dict(row)
        item_key = tuple(
            item[name]
            for name in (
                "metric_definition_id",
                "subject_type",
                "subject_id",
                "source_id",
                "snapshot_id",
            )
        )
        if item_key != key and current:
            yield current
            current = []
        key = item_key
        current.append(item)
    if current:
        yield current


def _members_of(
    bind: sa.Connection, observation_ids: Sequence[str]
) -> dict[str, Counter[tuple[str, bool, bool]]]:
    """Each observation's member multiset ``{(id, counted, followed): copies}``."""
    members: dict[str, Counter[tuple[str, bool, bool]]] = {
        oid: Counter() for oid in observation_ids
    }
    result = bind.execute(
        sa.select(
            OLD.c.observation_id,
            sa.cast(OLD.c.member_id, sa.Text),
            OLD.c.counted,
            OLD.c.followed,
        ).where(OLD.c.observation_id.in_(list(observation_ids)))
    )
    for observation_id, ident, counted, followed in result:
        members[observation_id][(ident, bool(counted), bool(followed))] += 1
    return members


def _insert_family(
    bind: sa.Connection, group: Sequence[dict[str, Any]], kind: str, rows: Sequence[Row]
) -> str:
    first = group[0]
    digest = _digest(kind, rows)
    identity = {
        "metric_definition_id": first["metric_definition_id"],
        "subject_type": first["subject_type"],
        "subject_id": first["subject_id"],
        "source_id": first["source_id"],
        "snapshot_id": first["snapshot_id"],
        "members_hash": digest,
    }
    found = bind.execute(
        sa.select(FAMILY.c.id).where(*(FAMILY.c[name] == value for name, value in identity.items()))
    ).scalar()
    if found is not None:
        return str(found)
    family_id = str(uuid.uuid4())
    bind.execute(
        sa.insert(FAMILY).values(
            id=family_id,
            member_kind=kind,
            row_count=len(rows),
            member_count=sum(row[5] for row in rows),
            **identity,
        )
    )
    _copy(
        bind,
        f"COPY {MEMBER_TABLE} (family_id, ordinal, member_id, anchor_year, dimension_value, "
        "counted_mask, followed_mask, multiplicity) FROM STDIN",
        (
            (family_id, ordinal, ident, year, dimension, counted, followed, copies)
            for ordinal, (ident, year, dimension, counted, followed, copies) in enumerate(rows)
        ),
    )
    return family_id


def _copy(bind: sa.Connection, statement: str, rows: Iterable[tuple[Any, ...]]) -> None:
    """``COPY`` rows into a table inside the migration's transaction (a constant statement)."""
    driver = bind.connection.driver_connection
    if driver is None:  # pragma: no cover - a live connection has one
        msg = "the migration has no driver connection to COPY through"
        raise ConversionError(msg)
    with driver.cursor() as cursor, cursor.copy(statement) as copy:
        for row in rows:
            copy.write_row(row)


def _kinds_of_definitions(bind: sa.Connection) -> dict[str, str]:
    """The member kind each definition's stored members have (one per definition)."""
    found: dict[str, str] = {}
    result = bind.execute(
        sa.select(OBSERVATION.c.metric_definition_id, OLD.c.member_kind)
        .join(OBSERVATION, OBSERVATION.c.id == OLD.c.observation_id)
        .distinct()
        .order_by(OBSERVATION.c.metric_definition_id, OLD.c.member_kind)
    )
    for definition, kind in result:
        if definition in found:
            msg = f"definition {definition}: members of several kinds {found[definition]}, {kind}"
            raise ConversionError(msg)
        found[definition] = kind
    return found


def _convert_up(bind: sa.Connection) -> None:
    kind_of_definition = _kinds_of_definitions(bind)
    for group in _group_observations(bind):
        first = group[0]
        mode = _mode(first["kind"], first["dimension"])
        windows = _windows(first["kind"], first["windows_days"])
        members = _members_of(bind, [item["id"] for item in group])
        rows = _rows(_group_atoms(mode, windows, group, members))
        # A family with no member has no kind of its own: its definition's other families name it.
        kind = kind_of_definition.get(first["metric_definition_id"], DEFAULT_KIND)
        family_id = _insert_family(bind, group, kind, rows)
        bind.execute(
            sa.update(OBSERVATION)
            .where(OBSERVATION.c.id.in_([item["id"] for item in group]))
            .values({FAMILY_COLUMN: family_id})
        )


def upgrade() -> None:
    op.create_table(
        FAMILY_TABLE,
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("metric_definition_id", sa.UUID(), nullable=False),
        sa.Column("subject_type", SUBJECT_TYPE, nullable=False),
        sa.Column("subject_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("snapshot_id", sa.UUID(), nullable=False),
        sa.Column("member_kind", sa.Text(), nullable=False),
        sa.Column("members_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("member_count", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            f"member_kind IN ({_quoted(MEMBER_KINDS)})",
            name=op.f("ck_metric_member_family_member_kind"),
        ),
        sa.CheckConstraint(
            "row_count >= 0 AND member_count >= row_count",
            name=op.f("ck_metric_member_family_counts"),
        ),
        sa.ForeignKeyConstraint(
            ["metric_definition_id"],
            [f"{DEFINITION_TABLE}.id"],
            name=op.f("fk_metric_member_family_metric_definition_id_metric_definition"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            [f"{SOURCE_TABLE}.id"],
            name=op.f("fk_metric_member_family_source_id_source"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            [f"{SNAPSHOT_TABLE}.id"],
            name=op.f("fk_metric_member_family_snapshot_id_metric_snapshot"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_metric_member_family")),
        sa.UniqueConstraint(
            "metric_definition_id",
            "subject_type",
            "subject_id",
            "source_id",
            "snapshot_id",
            "members_hash",
            name=op.f(FAMILY_KEY),
        ),
    )
    op.create_index(
        op.f("ix_metric_member_family_source_id"), FAMILY_TABLE, ["source_id"], unique=False
    )
    op.create_index(
        op.f("ix_metric_member_family_snapshot_id"), FAMILY_TABLE, ["snapshot_id"], unique=False
    )
    op.create_table(
        MEMBER_TABLE,
        sa.Column("family_id", sa.UUID(), nullable=False),
        sa.Column("ordinal", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("member_id", sa.UUID(), nullable=False),
        sa.Column("anchor_year", sa.SmallInteger(), nullable=True),
        sa.Column("dimension_value", sa.Text(), nullable=True),
        sa.Column("counted_mask", sa.SmallInteger(), nullable=False),
        sa.Column("followed_mask", sa.SmallInteger(), nullable=False),
        sa.Column("multiplicity", sa.Integer(), nullable=False),
        sa.CheckConstraint("multiplicity > 0", name=op.f("ck_metric_member_multiplicity")),
        sa.CheckConstraint(
            "counted_mask >= 0 AND followed_mask >= 0", name=op.f("ck_metric_member_masks")
        ),
        sa.ForeignKeyConstraint(
            ["family_id"],
            [f"{FAMILY_TABLE}.id"],
            name=op.f("fk_metric_member_family_id_metric_member_family"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("family_id", "ordinal", name=op.f("pk_metric_member")),
    )
    _apply_grants()

    op.add_column(OBSERVATION_TABLE, sa.Column(FAMILY_COLUMN, sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f(FAMILY_FK_OBSERVATION),
        OBSERVATION_TABLE,
        FAMILY_TABLE,
        [FAMILY_COLUMN],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        op.f(FAMILY_INDEX_OBSERVATION), OBSERVATION_TABLE, [FAMILY_COLUMN], unique=False
    )

    _convert_up(op.get_bind())

    op.alter_column(OBSERVATION_TABLE, FAMILY_COLUMN, nullable=False)
    op.add_column(RUN_TABLE, sa.Column(DEFERRED_COLUMN, sa.Text(), nullable=True))
    op.drop_index("ix_metric_observation_member_member", table_name=OLD_TABLE)
    op.drop_index("ix_metric_observation_member_observation_id", table_name=OLD_TABLE)
    op.drop_table(OLD_TABLE)


# --- downgrade: expand each observation's members from its family -----------------------------


def _expand(
    mode: str, slot: int, year: int | None, dimension: str | None, rows: Sequence[Row]
) -> Iterator[tuple[str, bool, bool]]:
    """The observation's member multiset, ``(id, counted, followed)`` per copy (``project``)."""
    bit = 1 << slot
    for ident, anchor, own_dimension, counted, followed, copies in rows:
        if year is not None and anchor != year:
            continue
        if mode == BELONGS_TO and dimension is not None and own_dimension != dimension:
            continue
        flag = (own_dimension == dimension) if mode == COUNTED_IN else bool(counted & bit)
        for _ in range(copies):
            yield ident, flag, bool(followed & bit)


def _convert_down(bind: sa.Connection) -> None:
    families = bind.execute(
        sa.select(
            FAMILY.c.id,
            FAMILY.c.member_kind,
            DEFINITION.c.kind,
            DEFINITION.c.windows_days,
            DEFINITION.c.dimension,
        )
        .join(DEFINITION, DEFINITION.c.id == FAMILY.c.metric_definition_id)
        .order_by(FAMILY.c.id)
    ).all()
    for family_id, member_kind, kind, windows_days, dimension in families:
        mode = _mode(kind, dimension)
        windows = _windows(kind, windows_days)
        rows: list[Row] = [
            (ident, year, value, counted, followed, copies)
            for ident, year, value, counted, followed, copies in bind.execute(
                sa.select(
                    sa.cast(MEMBER.c.member_id, sa.Text),
                    MEMBER.c.anchor_year,
                    MEMBER.c.dimension_value,
                    MEMBER.c.counted_mask,
                    MEMBER.c.followed_mask,
                    MEMBER.c.multiplicity,
                )
                .where(MEMBER.c.family_id == family_id)
                .order_by(MEMBER.c.ordinal)
            )
        ]
        observations = bind.execute(
            sa.select(
                OBSERVATION.c.id,
                OBSERVATION.c.window_days,
                OBSERVATION.c.calendar_year,
                OBSERVATION.c.dimension_value,
            )
            .where(OBSERVATION.c[FAMILY_COLUMN] == family_id)
            .order_by(OBSERVATION.c.id)
        ).all()
        for observation_id, window_days, year, observation_dimension in observations:
            slot = windows.index(window_days)
            _copy(
                bind,
                f"COPY {OLD_TABLE} (observation_id, member_kind, member_id, counted, followed) "
                "FROM STDIN",
                (
                    (observation_id, member_kind, ident, counted, followed)
                    for ident, counted, followed in _expand(
                        mode, slot, year, observation_dimension, rows
                    )
                ),
            )


def downgrade() -> None:
    op.create_table(
        OLD_TABLE,
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("observation_id", sa.UUID(), nullable=False),
        sa.Column("member_kind", sa.Text(), nullable=False),
        sa.Column("member_id", sa.UUID(), nullable=False),
        sa.Column("counted", sa.Boolean(), nullable=False),
        sa.Column("followed", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            f"member_kind IN ({_quoted(MEMBER_KINDS)})",
            name=op.f("ck_metric_observation_member_member_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["observation_id"],
            [f"{OBSERVATION_TABLE}.id"],
            name=op.f("fk_metric_observation_member_observation_id_metric_observation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_metric_observation_member")),
    )
    if _role_exists(APP_ROLE):
        op.execute(f"GRANT {APP_PRIVILEGES} ON TABLE {OLD_TABLE} TO {APP_ROLE}")
    if _role_exists(INGEST_ROLE):
        op.execute(f"GRANT {INGEST_PRIVILEGES} ON TABLE {OLD_TABLE} TO {INGEST_ROLE}")

    _convert_down(op.get_bind())

    op.create_index(
        "ix_metric_observation_member_observation_id", OLD_TABLE, ["observation_id"], unique=False
    )
    op.create_index(
        "ix_metric_observation_member_member", OLD_TABLE, ["member_kind", "member_id"], unique=False
    )
    op.drop_column(RUN_TABLE, DEFERRED_COLUMN)
    op.drop_index(op.f(FAMILY_INDEX_OBSERVATION), table_name=OBSERVATION_TABLE)
    op.drop_constraint(op.f(FAMILY_FK_OBSERVATION), OBSERVATION_TABLE, type_="foreignkey")
    op.drop_column(OBSERVATION_TABLE, FAMILY_COLUMN)
    op.drop_table(MEMBER_TABLE)
    op.drop_index(op.f("ix_metric_member_family_snapshot_id"), table_name=FAMILY_TABLE)
    op.drop_index(op.f("ix_metric_member_family_source_id"), table_name=FAMILY_TABLE)
    op.drop_table(FAMILY_TABLE)
