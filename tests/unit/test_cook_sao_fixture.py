# tests/unit/test_cook_sao_fixture.py
"""The committed Cook County fixture: blanked, verified headers, reproducible, documented.

The fixture is real public-domain rows; every value of the restricted and
quasi-identifying columns is empty in every row (the security gate of
Phase 5 Step 1), its headers are the verified sets, excerpting it writes it
again byte for byte, and its README names every case's strata.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from judgemetrics.cli import app
from judgemetrics.ingest.cook_sao.schema import BLANKED_COLUMNS, CASE_ID, VERIFIED_HEADERS
from judgemetrics.ingest.cook_sao.sources import EXTERNAL_IDS

pytestmark = pytest.mark.unit

FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "cook_sao"
FILES = (*EXTERNAL_IDS, "README.md")
CASE_ROW = re.compile(r"^\| (\d+) \| `(\d+)` \| ([^|]+) \| ([^|]*) \|$")
MAX_BYTES = 1024 * 1024


def _rows(name: str) -> tuple[list[str], list[list[str]]]:
    with (FIXTURE / name).open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        return header, list(reader)


def _case_ids() -> set[str]:
    ids: set[str] = set()
    for name in EXTERNAL_IDS:
        header, rows = _rows(name)
        index = header.index(CASE_ID)
        ids.update(row[index] for row in rows)
    return ids


def test_the_fixture_holds_the_five_files_and_a_readme() -> None:
    assert sorted(p.name for p in FIXTURE.iterdir()) == sorted(FILES)
    for name in FILES:
        data = (FIXTURE / name).read_bytes()
        assert len(data) < MAX_BYTES, name  # the large-file hook's limit
        assert b"\r" not in data, name


@pytest.mark.parametrize("name", EXTERNAL_IDS)
def test_every_blanked_value_is_empty_in_every_row(name: str) -> None:
    header, rows = _rows(name)
    blanked = [i for i, column in enumerate(header) if column in BLANKED_COLUMNS]
    assert blanked, name
    assert rows, name
    for row in rows:
        assert len(row) == len(header)
        assert [row[i] for i in blanked] == [""] * len(blanked)


@pytest.mark.parametrize("name", EXTERNAL_IDS)
def test_the_headers_are_the_verified_sets(name: str) -> None:
    header, _ = _rows(name)
    assert tuple(header) == VERIFIED_HEADERS[name]


def test_excerpting_the_fixture_reproduces_it_byte_for_byte(tmp_path: Path) -> None:
    out = tmp_path / "again"
    result = CliRunner().invoke(
        app,
        ["sources", "excerpt", "cook_sao", "--from-fixture", str(FIXTURE), "--out", str(out)],
    )
    assert result.exit_code == 0, result.output
    for name in FILES:
        assert (out / name).read_bytes() == (FIXTURE / name).read_bytes(), name


def test_the_excerpt_never_writes_over_its_input() -> None:
    result = CliRunner().invoke(
        app,
        ["sources", "excerpt", "cook_sao", "--from-fixture", str(FIXTURE), "--out", str(FIXTURE)],
    )
    assert result.exit_code == 2
    assert "--out must differ" in result.output


def test_the_readme_names_every_cases_strata() -> None:
    readme = (FIXTURE / "README.md").read_text(encoding="utf-8")
    assert readme.splitlines()[0] == "<!-- tests/fixtures/cook_sao/README.md -->"
    rows = [CASE_ROW.match(line) for line in readme.splitlines()]
    cases = [match for match in rows if match is not None]
    assert [int(match.group(1)) for match in cases] == list(range(1, len(cases) + 1))
    named = {match.group(2) for match in cases}
    assert named == _case_ids()
    for match in cases:
        chosen_for = match.group(3).strip()
        satisfied = [label.strip() for label in match.group(4).split(";")]
        assert chosen_for in satisfied, match.group(2)
    for column in BLANKED_COLUMNS:
        assert f"- `{column}`" in readme
    assert "## Strata no case satisfies\n\nNone." in readme
