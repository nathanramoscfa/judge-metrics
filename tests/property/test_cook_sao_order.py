# tests/property/test_cook_sao_order.py
"""Permuting the rows of each Cook County export yields the same canonical rows.

The portal writes its rows in no order the connector may rely on: a new release, a
re-sorted export, or a parallel download could present the same rows differently. The
connector reads every export into a frame sorted by every column it uses, so a case's
rows reach ``build_case`` in a canonical order and every "first row wins" choice is a
function of the set of rows. This property shuffles the data lines of each of the five
fixture exports (the real-row excerpt, restricted columns holding vocabulary values so
the attribute choice is exercised too) and requires the drafts — every field, the
restricted values included — to equal the unshuffled run's.
"""

from __future__ import annotations

import io
import random

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from judgemetrics.ingest.base import CanonicalRecord, PartyAttributeDraft
from tests.unit.test_cook_sao_normalize import (
    fixture_bytes,
    normalize_all,
    with_restricted_values,
)

pytestmark = pytest.mark.property

DATA = with_restricted_values(fixture_bytes())


def canonical(drafts: list[CanonicalRecord]) -> list[str]:
    """Every draft as text, restricted values included (their ``repr`` withholds them)."""
    rendered = [
        f"{draft.natural_key}={draft.value}"
        if isinstance(draft, PartyAttributeDraft)
        else repr(draft)
        for draft in drafts
    ]
    return sorted(rendered)


BASELINE = canonical(normalize_all(DATA).drafts)


def shuffled(data: bytes, seed: int) -> bytes:
    lines = io.BytesIO(data).readlines()
    header, rows = lines[0], lines[1:]
    random.Random(seed).shuffle(rows)  # noqa: S311 - a test shuffle, not cryptography
    return b"".join([header, *rows])


@settings(
    max_examples=12,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
    derandomize=True,
)
@given(seeds=st.lists(st.integers(min_value=0, max_value=2**31), min_size=5, max_size=5))
def test_row_order_never_changes_the_drafts(seeds: list[int]) -> None:
    permuted = {
        name: shuffled(data, seed) for (name, data), seed in zip(DATA.items(), seeds, strict=True)
    }
    assert canonical(normalize_all(permuted).drafts) == BASELINE
