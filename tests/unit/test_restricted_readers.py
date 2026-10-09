# tests/unit/test_restricted_readers.py
"""One module reads the ``restricted`` schema: ``validation/fairness.py``.

Under ``src/judgemetrics/``, a reference to the restricted table — its name
``party_attribute``, its ORM class ``PartyAttribute``, a schema-qualified
``restricted.<name>``, or ``schema="restricted"`` — appears only in the one
reader (``validation/fairness.py``), the ORM model and the package that
exports it (``db/models/restricted.py``, ``db/models/__init__.py``), and
Phase 4 Step 1's write path (``ingest/base.py``, ``ingest/publish.py``,
``ingest/runner.py``, ``ingest/synthetic/``), and Phase 5 Step 4's second connector
(``ingest/cook_sao/``: race, gender, and the age band reach the table by the same write
path). The bare word "restricted" is
not the pattern: a dozen modules use it in prose. ``PartyAttributeDraft`` is
the write path's draft class and is matched as the table name it carries.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from judgemetrics.config import REPO_ROOT

pytestmark = pytest.mark.unit

PACKAGE = REPO_ROOT / "src" / "judgemetrics"
PATTERN = re.compile(
    r"party_attribute|\bPartyAttribute\b|\brestricted\.[A-Za-z_]\w*|schema\s*=\s*[\"']restricted[\"']"
)
READER = "validation/fairness.py"
ALLOWED_FILES = frozenset(
    {
        READER,
        "db/models/restricted.py",
        "db/models/__init__.py",
        "ingest/base.py",
        "ingest/publish.py",
        "ingest/runner.py",
    }
)
# A registered connector directory joins this tuple (``scripts/verify_phase04.py`` check 31
# reads it from here), so a later connector never fails an earlier phase's required check.
ALLOWED_DIRECTORIES = ("ingest/synthetic/", "ingest/cook_sao/")


def _relative(path: Path) -> str:
    return path.relative_to(PACKAGE).as_posix()


def _matching() -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        found = PATTERN.findall(path.read_text(encoding="utf-8"))
        if found:
            hits[_relative(path)] = sorted(set(found))
    return hits


def _allowed(relative: str) -> bool:
    return relative in ALLOWED_FILES or relative.startswith(ALLOWED_DIRECTORIES)


def test_only_the_fairness_module_and_the_write_path_name_the_restricted_table() -> None:
    hits = _matching()
    outside = {path: names for path, names in hits.items() if not _allowed(path)}
    assert outside == {}, f"modules outside the allow-list name the restricted table: {outside}"


def test_the_fairness_module_is_the_only_reader_outside_the_write_path() -> None:
    hits = _matching()
    assert READER in hits, "the subgroup calibration reads the restricted table"
    readers = {path for path in hits if not path.startswith(("db/models/", "ingest/"))}
    assert readers == {READER}


def test_the_pattern_matches_every_spelling_and_not_the_bare_word() -> None:
    for text in (
        "party_attribute",
        "select(PartyAttribute.value)",
        "FROM restricted.party_attribute",
        'Table("x", schema="restricted")',
        "Table('x', schema = 'restricted')",
    ):
        assert PATTERN.search(text), text
    for text in ("the restricted schema", "restricted attributes", "RESTRICTED_SCHEMA"):
        assert not PATTERN.search(text), text
