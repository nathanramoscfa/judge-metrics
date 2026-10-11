# tests/integration/test_snapshot_export.py
"""The streamed export writes the very bytes the Phase 3 export wrote, on the golden data.

``snapshot_reference.reference_frames`` is the old export kept verbatim (every table through
``session.execute(...).all()``, converted cell by cell in Python); ``export_snapshot`` streams
each table from a server-side cursor with the conversions done in SQL. For the module's golden
ingest the two must agree table by table on the Parquet bytes (the sha256 of each file) and so on
the snapshot's content hash — that equality is what lets a snapshot exported before this change
be reused after it — and a second export of unchanged data reuses the directory.
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from judgemetrics.config import Settings
from judgemetrics.metrics.snapshot import (
    SNAPSHOT_TABLES,
    TableDigest,
    content_hash_of,
    export_snapshot,
)
from tests.golden.conftest import GoldenFixture
from tests.integration.snapshot_reference import reference_frames

pytestmark = [pytest.mark.golden, pytest.mark.integration]


def test_the_streamed_export_equals_the_reference_table_by_table(
    migrated_database: Engine,
    golden_fixture: GoldenFixture,
    test_settings: Settings,
    tmp_path: Path,
) -> None:
    del golden_fixture
    settings = test_settings.model_copy(update={"env": "test", "snapshot_dir": tmp_path})
    with Session(migrated_database) as session:
        frames = reference_frames(session)
        reference: dict[str, TableDigest] = {}
        for name in SNAPSHOT_TABLES:
            buffer = io.BytesIO()
            frames[name].write_parquet(buffer)
            reference[name] = TableDigest(
                hashlib.sha256(buffer.getvalue()).hexdigest(), frames[name].height
            )
        streamed = export_snapshot(session, settings)
        session.rollback()
    assert {name: digest.rows for name, digest in streamed.tables.items()} == {
        name: digest.rows for name, digest in reference.items()
    }
    for name in SNAPSHOT_TABLES:
        assert streamed.tables[name].sha256 == reference[name].sha256, name
    assert streamed.content_hash == content_hash_of(reference)
    assert streamed.tables["cases"].rows > 0 and streamed.tables["decisions"].rows > 0
    # The same data is the same snapshot: a second export reuses the directory.
    with Session(migrated_database) as session:
        again = export_snapshot(session, settings)
        session.rollback()
    assert again.reused and again.content_hash == streamed.content_hash
