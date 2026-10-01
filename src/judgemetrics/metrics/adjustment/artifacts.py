# src/judgemetrics/metrics/adjustment/artifacts.py
"""Fitted-model artifacts: canonical JSON, content-addressed, written once.

A fitted model is recorded as one JSON document (``render``): keys sorted,
no insignificant whitespace, ASCII only, every float rounded to
``SIGNIFICANT_DIGITS`` (12) significant digits and written in Python's
shortest round-trip form (``-0.0`` normalized to ``0.0``; a NaN or an
infinity is refused), datetimes as ISO 8601 UTC strings, and a trailing
newline — so the same model always yields the same bytes. Its sha256 is
its id (``content_hash``).

``artifact_path(root, snapshot_hash, content_hash)`` is the only way a path
is formed: both hashes are validated as 64 lowercase hexadecimal characters
before they become path components, and the resolved path must lie under
``root`` (``JUDGEMETRICS_SNAPSHOT_DIR``):
``<root>/<snapshot hash>/models/<content hash>.json``. ``write_artifact``
creates the file exclusively (``open(path, "xb")``) and never overwrites:
an equal file already there is a no-op, a different one raises
``ArtifactError``. Artifacts are read back as JSON only — never ``pickle``,
``numpy.load``, or ``eval``.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

ARTIFACT_VERSION = 1
SIGNIFICANT_DIGITS = 12
MODELS_DIRECTORY = "models"
SUFFIX = ".json"
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class ArtifactError(RuntimeError):
    """An artifact cannot be rendered, placed, written, or read consistently."""


def validate_hash(value: str, what: str) -> str:
    """``value`` when it is 64 lowercase hexadecimal characters; ``ArtifactError`` otherwise."""
    if not isinstance(value, str) or not HEX64.match(value):
        msg = f"a {what} is a 64-character lowercase hexadecimal sha256"
        raise ArtifactError(msg)
    return value


def round_significant(value: float) -> float:
    """``value`` rounded to 12 significant digits (``-0.0`` becomes ``0.0``)."""
    if not math.isfinite(value):
        msg = "an artifact cannot carry a NaN or an infinity"
        raise ArtifactError(msg)
    rounded = float(f"{value:.{SIGNIFICANT_DIGITS}g}")
    return 0.0 if rounded == 0.0 else rounded


def canonical(value: Any) -> Any:
    """``value`` as plain JSON types with every float rounded (see the module docstring)."""
    if value is None or isinstance(value, bool | str):
        return value
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, int | np.integer):
        return int(value)
    if isinstance(value, float | np.floating):
        return round_significant(float(value))
    if isinstance(value, datetime):
        if value.tzinfo is None:
            msg = "an artifact datetime must be timezone-aware"
            raise ArtifactError(msg)
        return value.astimezone(UTC).isoformat()
    if isinstance(value, np.ndarray):
        return [canonical(item) for item in value.tolist()]
    if isinstance(value, Mapping):
        return {str(key): canonical(item) for key, item in value.items()}
    if isinstance(value, Sequence):
        return [canonical(item) for item in value]
    msg = f"an artifact cannot carry a {type(value).__name__}"
    raise ArtifactError(msg)


def render(payload: Mapping[str, Any]) -> bytes:
    """The canonical bytes of ``payload``."""
    text = json.dumps(
        canonical(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return (text + "\n").encode("ascii")


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def artifact_path(root: Path, snapshot_hash: str, model_hash: str) -> Path:
    """``<root>/<snapshot hash>/models/<content hash>.json``, both hashes validated, under root."""
    snapshot = validate_hash(snapshot_hash, "snapshot id")
    model = validate_hash(model_hash, "model content hash")
    base = root.resolve()
    path = (base / snapshot / MODELS_DIRECTORY / f"{model}{SUFFIX}").resolve()
    if not path.is_relative_to(base):
        msg = f"an artifact path must lie under {base}"
        raise ArtifactError(msg)
    return path


def write_artifact(root: Path, snapshot_hash: str, data: bytes) -> tuple[Path, str, bool]:
    """Write ``data`` once under its content hash: ``(path, hash, written)``.

    An equal file already at the path is a no-op (``written`` false); a
    different one raises ``ArtifactError`` — an artifact is never overwritten.
    """
    digest = content_hash(data)
    path = artifact_path(root, snapshot_hash, digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(data)
    except FileExistsError:
        if path.read_bytes() != data:
            msg = f"artifact {digest} already exists with different bytes"
            raise ArtifactError(msg) from None
        return path, digest, False
    return path, digest, True


def read_artifact(path: Path) -> dict[str, Any]:
    """An artifact parsed as JSON (``ArtifactError`` when it is missing or malformed)."""
    try:
        payload = json.loads(path.read_bytes().decode("ascii"))
    except (OSError, ValueError) as exc:
        msg = f"artifact {path.name} is unreadable ({exc.__class__.__name__})"
        raise ArtifactError(msg) from exc
    if not isinstance(payload, dict):
        msg = f"artifact {path.name} is not a JSON object"
        raise ArtifactError(msg)
    return payload


def first_difference(stored: Any, fresh: Any, path: str = "") -> str | None:
    """The dotted path of the first field where two parsed artifacts differ (sorted keys)."""
    if isinstance(stored, dict) and isinstance(fresh, dict):
        for key in sorted(set(stored) | set(fresh)):
            where = f"{path}.{key}" if path else key
            if key not in stored or key not in fresh:
                return where
            found = first_difference(stored[key], fresh[key], where)
            if found is not None:
                return found
        return None
    if isinstance(stored, list) and isinstance(fresh, list):
        if len(stored) != len(fresh):
            return path or "(root)"
        for index, (left, right) in enumerate(zip(stored, fresh, strict=True)):
            found = first_difference(left, right, f"{path}[{index}]")
            if found is not None:
                return found
        return None
    return None if stored == fresh else (path or "(root)")
