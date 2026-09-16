# src/judgemetrics/normalization/geography.py
"""United States state, district, and territory codes (``data/reference/us_states.csv``).

A canonical-domain lookup: connectors parse a place name out of their own
source's strings and ask here for the USPS code.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from judgemetrics.config import REPO_ROOT

US_STATES_PATH = REPO_ROOT / "data" / "reference" / "us_states.csv"
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class UsState:
    code: str
    name: str
    kind: str


def _fold(name: str) -> str:
    return _WHITESPACE.sub(" ", name).strip().casefold()


@lru_cache(maxsize=4)
def load_us_states(path: Path = US_STATES_PATH) -> tuple[UsState, ...]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    states = tuple(
        UsState(code=row["code"].strip(), name=row["name"].strip(), kind=row["kind"].strip())
        for row in rows
    )
    codes = [state.code for state in states]
    if len(set(codes)) != len(codes):
        msg = f"duplicate codes in {path}"
        raise ValueError(msg)
    return states


@lru_cache(maxsize=4)
def _by_name(path: Path = US_STATES_PATH) -> dict[str, str]:
    return {_fold(state.name): state.code for state in load_us_states(path)}


def state_code_for_name(name: str, path: Path = US_STATES_PATH) -> str | None:
    """``"New York"`` → ``"NY"``; unknown names → ``None``."""
    return _by_name(path).get(_fold(name))
