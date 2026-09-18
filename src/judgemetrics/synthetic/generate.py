# src/judgemetrics/synthetic/generate.py
"""``generate_dataset`` and ``verify_dataset``: the package's two entry points.

``generate_dataset(seed, scale, out)`` builds the world, simulates the
cases, assigns identifiers, plants the edge cases, and writes ``source/``,
``truth/``, and ``manifest.json`` (seed, scale, generator and truth
versions, row counts per CSV, and the sha256 of every source and truth
file). It refuses a directory that already holds a manifest or generated
files unless ``force`` is set, and it never deletes anything.
``verify_dataset(out)`` recomputes the hashes and reports every mismatch,
missing file, and unlisted file under ``source/`` and ``truth/``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from judgemetrics.synthetic.cases import build_cases
from judgemetrics.synthetic.config import GENERATOR_VERSION, ScaleSpec, scale_spec
from judgemetrics.synthetic.edge_cases import plant_edge_cases
from judgemetrics.synthetic.model import World, assign_identifiers
from judgemetrics.synthetic.rng import Streams
from judgemetrics.synthetic.truth import TRUTH_FILES, TRUTH_VERSION, write_truth
from judgemetrics.synthetic.world import build_world
from judgemetrics.synthetic.writer import SOURCE_FILES, sha256_file, write_json, write_source

MANIFEST_NAME = "manifest.json"
SOURCE_DIR = "source"
TRUTH_DIR = "truth"


class DatasetExistsError(FileExistsError):
    """The output directory already holds a generated dataset (use ``force``)."""


@dataclass(frozen=True, slots=True)
class Manifest:
    seed: int
    scale: str
    generator_version: str
    truth_version: str
    counts: dict[str, int]
    files: dict[str, str]
    path: Path = field(compare=False)

    def to_json(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "scale": self.scale,
            "generator_version": self.generator_version,
            "truth_version": self.truth_version,
            "counts": dict(sorted(self.counts.items())),
            "files": dict(sorted(self.files.items())),
        }

    @classmethod
    def load(cls, path: Path) -> Manifest:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            seed=int(payload["seed"]),
            scale=str(payload["scale"]),
            generator_version=str(payload["generator_version"]),
            truth_version=str(payload["truth_version"]),
            counts={str(k): int(v) for k, v in payload["counts"].items()},
            files={str(k): str(v) for k, v in payload["files"].items()},
            path=path,
        )


def build_dataset(seed: int, spec: ScaleSpec) -> tuple[World, Any]:
    """The in-memory world with identifiers assigned and edge cases planted."""
    streams = Streams(seed)
    world = build_world(spec, seed, streams)
    build_cases(world, streams)
    assign_identifiers(world)
    plants = plant_edge_cases(world, streams.edge_cases)
    return world, plants


def _generated_files(out: Path) -> list[Path]:
    found: list[Path] = []
    for sub in (SOURCE_DIR, TRUTH_DIR):
        directory = out / sub
        if directory.is_dir():
            found.extend(p for p in sorted(directory.rglob("*")) if p.is_file())
    return found


def generate_dataset(seed: int, scale: str, out: Path, *, force: bool = False) -> Manifest:
    """Generate the dataset for ``seed`` at ``scale`` into ``out``; returns the manifest."""
    spec = scale_spec(scale)
    out = out.resolve()
    manifest_path = out / MANIFEST_NAME
    if not force:
        if manifest_path.exists():
            msg = f"{manifest_path} exists; pass force to regenerate over it"
            raise DatasetExistsError(msg)
        existing = _generated_files(out)
        if existing:
            msg = f"{out} already holds {len(existing)} generated files; pass force to overwrite"
            raise DatasetExistsError(msg)
    world, plants = build_dataset(seed, spec)
    out.mkdir(parents=True, exist_ok=True)
    counts = write_source(world, out / SOURCE_DIR)
    counts.update(write_truth(world, plants, out / TRUTH_DIR))
    files: dict[str, str] = {}
    for name in SOURCE_FILES:
        files[f"{SOURCE_DIR}/{name}"] = sha256_file(out / SOURCE_DIR / name)
    for name in TRUTH_FILES:
        files[f"{TRUTH_DIR}/{name}"] = sha256_file(out / TRUTH_DIR / name)
    manifest = Manifest(
        seed=seed,
        scale=spec.name,
        generator_version=GENERATOR_VERSION,
        truth_version=TRUTH_VERSION,
        counts=counts,
        files=files,
        path=manifest_path,
    )
    write_json(manifest_path, manifest.to_json())
    return manifest


def manifest_matches(out: Path, seed: int, scale: str) -> bool:
    """Whether ``out`` already holds a manifest for ``seed``, ``scale``, and this generator.

    The ``seed`` command skips generation on a match; a different scale or
    an older generator version means the directory must be regenerated
    (``--force``), and an unreadable manifest counts as no match.
    """
    manifest_path = out.resolve() / MANIFEST_NAME
    if not manifest_path.is_file():
        return False
    try:
        manifest = Manifest.load(manifest_path)
    except (ValueError, KeyError, TypeError, OSError):
        return False
    return (
        manifest.seed == seed
        and manifest.scale == scale
        and manifest.generator_version == GENERATOR_VERSION
    )


def verify_dataset(out: Path) -> list[str]:
    """Every hash mismatch, missing file, or unlisted generated file; empty when clean."""
    out = out.resolve()
    manifest_path = out / MANIFEST_NAME
    if not manifest_path.is_file():
        return [f"{MANIFEST_NAME}: missing"]
    try:
        manifest = Manifest.load(manifest_path)
    except (ValueError, KeyError, TypeError) as exc:
        return [f"{MANIFEST_NAME}: unreadable ({exc.__class__.__name__})"]
    problems: list[str] = []
    for relative, expected in sorted(manifest.files.items()):
        path = out / relative
        if not path.is_file():
            problems.append(f"{relative}: missing")
            continue
        actual = sha256_file(path)
        if actual != expected:
            problems.append(f"{relative}: sha256 {actual} != manifest {expected}")
    listed = set(manifest.files)
    for path in _generated_files(out):
        relative = path.relative_to(out).as_posix()
        if relative not in listed:
            problems.append(f"{relative}: not in manifest")
    return sorted(problems)
