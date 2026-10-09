# scripts/verify_phase04.py
"""Phase 4 verification: static deliverable checks, tool suites, probes, and the V1-V6 matrix.

Modes are mutually exclusive; with no flag the script runs ``--fast`` plus
``--py``:

  --fast      the 50 static checks only (CI-safe on Ubuntu and Windows,
              well under 30 seconds: pathlib, re, json, hashlib, and
              ``git ls-files``; the registry and the outcome model
              specification are read with minimal line readers, never a
              YAML library, and the brief with a regular expression, never
              an XML parser)
  --py        static + ruff, ruff format --check, mypy, the unit suite, and
              the integration, property, and golden suites when a database
              is configured (JUDGEMETRICS_TEST_DATABASE_URL preferred)
  --node      static + pnpm lint, typecheck, build, test in web/
  --e2e       static + the Playwright suites (smoke, metrics, first
              milestone, adjusted; skips with a reason when the API or the
              web app is not reachable)
  --security  the gate over the phase's surface: detect-secrets against the
              baseline, bandit over src, alembic, and scripts, pip-audit
              over uv.lock, pnpm audit
  --all       static + e2e + node + py + security
  --post      static + the V1-V6 matrix of docs/roadmap/phase04-roadmap.md:
              ``gh pr checks`` for the current branch when gh is signed in,
              the first-milestone setup and the bootstrap rerun, the seed
              and compute idempotency probes (a second compute fits no model
              and publishes nothing), ``metrics verify``, ``models verify
              --refit``, ``validation report --check`` and ``validation
              recovery`` against the probe's dataset, a ``provenance trace``
              of one current adjusted observation, the reachability items,
              the web, Playwright, and security suites, the V-suites, and
              ``uv run poe check``

The ``--post`` probes that write (``poe migrate``, ``poe seed``, ``poe
bootstrap``, ``metrics compute``) run against the scratch test database
when JUDGEMETRICS_TEST_DATABASE_URL is configured: the three role URLs are
pointed at it and JUDGEMETRICS_SNAPSHOT_DIR at data/snapshots/scratch-test-db,
so the live database and its snapshots keep their state. Without it they
run against the configured database, and the script says so.

Every static check is independent and reads the repository only; it prints
``[PASS] NN description`` or ``[FAIL] NN description — reason``. Suites are
subprocesses with argument lists (never a shell) over tools resolved on
PATH (``uv``, ``pnpm``, ``gh``, ``git``, ``docker``). The script prints
check names, paths, counts, hashes, and tool output; it never prints
repository file contents, a database row, or a setting's value. Exit 0
when nothing failed, 1 otherwise. Runs unmodified on Windows and Ubuntu.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess  # argument lists over PATH tools, never a shell  # nosec B404
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = REPO_ROOT / "web"
PACKAGE = "src/judgemetrics"
PHASE = "04"

Status = Literal["PASS", "FAIL", "SKIP"]
CheckFn = Callable[[], str | None]  # None on success, otherwise the failure reason

REGISTRY = "data/reference/metric_registry.yaml"
SPECIFICATION = "data/reference/outcome_model.yaml"
VOCABULARY = "data/reference/case_vocabulary.yaml"
BRIEF = "docs/brief/judgemetrics-master-project-specification.xml"
BRIEF_WARNING_COUNT = 8
GOLDEN_DIR = "tests/fixtures/golden"
SYNTHETIC_CONFIG = f"{PACKAGE}/synthetic/config.py"
SYNTHETIC_RNG = f"{PACKAGE}/synthetic/rng.py"
SYNTHETIC_TRUTH = f"{PACKAGE}/synthetic/truth.py"
METHODOLOGY_MODULE = f"{PACKAGE}/metrics/methodology.py"
CLI = f"{PACKAGE}/cli.py"
CI_WORKFLOW = ".github/workflows/ci.yml"
# The versions Phase 4 Step 1 set; checks compare the source constants with
# `>=` so a later phase's bump never fails this phase's required check.
MINIMUM_GENERATOR_VERSION = 3
MINIMUM_TRUTH_VERSION = 3
MINIMUM_VOCABULARY_VERSION = 2
MINIMUM_PARSER_VERSION = 2
MINIMUM_REGISTRY_VERSION = 2
MINIMUM_METHODOLOGY = (1, 0)
NEW_STREAMS = ("effects", "attributes")
EFFECTS_KEYS = ("judges", "targets", "controls", "definitions")
EFFECT_TARGETS = ("pretrial_release", "new_case", "failure_to_appear")
RESTRICTED_KINDS = ("restricted_attribute", "age_band", "synthetic_group")
SCRUBBED_KEYS = ("age_band", "synthetic_group", "attribute_value")
STEP1_TESTS = (
    "tests/unit/test_synthetic_effects.py",
    "tests/property/test_effects_invariants.py",
    "tests/integration/test_restricted_schema.py",
    "tests/unit/test_exposure_deferral.py",
)
SPEC_BLOCKS = (
    "targets",
    "features",
    "excluded",
    "model",
    "temporal_split",
    "seed",
    "bootstrap",
    "pooling",
    "thresholds",
    "recovery",
)
MODEL_VERSION = "expected-logit-v1"
ADJUSTMENT_STEP2_MODULES = (
    "__init__",
    "spec",
    "features",
    "logistic",
    "resample",
    "diagnostics",
    "artifacts",
    "fit",
)
ADJUSTMENT_STEP3_MODULES = ("expected", "pooling", "bootstrap")
# Code that would deserialize or evaluate an artifact (check 15). Uses, not
# mentions: artifacts.py's docstring names all three as what it never does.
UNSAFE_LOADS = (
    ("pickle", re.compile(r"^\s*(?:import|from)\s+pickle\b|\bpickle\.\w+\(", re.MULTILINE)),
    ("numpy.load", re.compile(r"\b(?:numpy|np)\.load\(")),
    ("eval(", re.compile(r"(?<![\w.])eval\(")),
)
FORBIDDEN_LOCKED = ("scipy", "scikit-learn", "statsmodels", "pandas")
STEP2_TESTS = (
    "tests/unit/test_outcome_model_spec.py",
    "tests/unit/test_logistic.py",
    "tests/unit/test_adjustment_features.py",
    "tests/property/test_feature_leakage.py",
    "tests/unit/test_model_diagnostics.py",
    "tests/unit/test_model_artifacts.py",
    "tests/integration/test_outcome_models.py",
)
ADJUSTED_SLUGS = (
    "pretrial_release_observed_expected",
    "new_case_observed_expected",
    "failure_to_appear_observed_expected",
)
ADJUSTED_THRESHOLD = 30
SUPPRESSION_REASONS = ("below_threshold", "expected_below_minimum", "model_unavailable")
ADJUSTED_VERIFIED_COLUMNS = (
    "expected_count",
    "expected_rate",
    "standardized_ratio",
    "pooling_weight",
    "suppression_reason",
)
STEP3_TESTS = (
    "tests/unit/test_pooling.py",
    "tests/unit/test_bootstrap.py",
    "tests/golden/test_golden_adjusted.py",
    "tests/golden/test_golden_recovery.py",
    "tests/integration/test_api_adjusted.py",
)
VALIDATION_MODULES = (
    "__init__",
    "report",
    "fairness",
    "sensitivity",
    "stability",
    "recovery",
    "inputs",
    "statistics",
)
# Check 31 mirrors tests/unit/test_restricted_readers.py: the restricted
# table, its ORM class, a schema-qualified name, or the schema keyword
# appear only in the one reader, the model, and Step 1's write path.
RESTRICTED_NAME = re.compile(
    r"party_attribute|\bPartyAttribute\b|\brestricted\.[A-Za-z_]\w*"
    r"|schema\s*=\s*[\"']restricted[\"']"
)
RESTRICTED_ALLOWED_FILES = (
    "validation/fairness.py",
    "db/models/restricted.py",
    "db/models/__init__.py",
    "ingest/base.py",
    "ingest/publish.py",
    "ingest/runner.py",
)
# The connector directories that may name the restricted table are the ones
# tests/unit/test_restricted_readers.py lists (read with a line reader, so a connector
# registered in a later phase never fails this check); this is the fallback minimum.
RESTRICTED_ALLOWED_DIRECTORIES = ("ingest/synthetic/",)
RESTRICTED_READERS_TEST = "tests/unit/test_restricted_readers.py"
VALIDATION_DOC = "docs/VALIDATION.md"
VALIDATION_SECTIONS = (
    "Summary",
    "Calibration",
    "Feature stability",
    "Missing-data sensitivity",
    "Bootstrap stability",
    "Subgroup calibration",
    "Recovery",
)
UUID_SHAPE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
HEX64 = re.compile(r"(?<![0-9a-fA-F])[0-9a-fA-F]{64}(?![0-9a-fA-F])")
CHANGELOG_VERSIONS = ("0.1", "0.2", "0.3", "1.0")
STEP4_TESTS = (
    "tests/unit/test_validation_report.py",
    "tests/unit/test_subgroup_calibration.py",
    "tests/integration/test_fairness_analysis.py",
    "tests/unit/test_restricted_readers.py",
)
SCHEMA_PERSON_FIELDS = ("person_id", "public_person_key", "full_name", "date_of_birth")
SCHEMA_ADJUSTED_FIELDS = ("ratio_lower", "ratio_upper", "pooling_weight", "suppression_reason")
MODELS_PATH = "/api/v1/models/{model_id}"
# Phase 3's six paths and the model card, asserted as a subset (Phase 3
# finding 6.1): a later phase's route never fails this check;
# test_openapi.py pins the exact set.
OPENAPI_PATHS = {
    "/api/v1/metrics",
    "/api/v1/judges/{judge_id}/metrics",
    "/api/v1/courts/{court_id}/metrics",
    "/api/v1/metrics/compare",
    "/api/v1/metrics/{observation_id}/provenance",
    "/api/v1/corrections",
    MODELS_PATH,
}
INTERVAL_LABEL = "95% bootstrap interval"
STEP5_WEB_TESTS = (
    "web/tests/unit/adjusted-stat.test.tsx",
    "web/tests/unit/model-page.test.tsx",
    "web/tests/e2e/adjusted.spec.ts",
)
ADJUSTED_SPEC_MIN_TESTS = 5
QA_SECTIONS = (
    "## Step 1",
    "## Step 2",
    "## Step 3",
    "## Step 4",
    "## Step 5",
    "## Step 6",
    "### Alarm exercise",
    "## Pre-ship items",
    "## Phase 5 carry-over checklist",
)
MATRIX_ENTRIES = {"01", "02", "03", PHASE}
MODE_FLAGS = ("--fast", "--py", "--node", "--e2e", "--security", "--all", "--post")
PRE_COMMIT_HOOKS = ("detect-secrets", "bandit", "pip-audit")
SHA_PIN = re.compile(r"@[0-9a-f]{40}$")
# The security backstop (check 50): a PEM private-key header, an AWS access
# key id, or any PEM block header in the phase's source, web, data, and doc
# trees. Bytes patterns so binary files are scanned too without decoding;
# complete headers only, so a regex source or prose that mentions the marker
# never matches.
BACKSTOP_PATTERNS = (
    ("private-key header", re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("AKIA-style access key", re.compile(rb"AKIA[0-9A-Z]{16}")),
    ("PEM block", re.compile(rb"-----BEGIN [A-Z ]+-----")),
)
BACKSTOP_TREES = (
    "src",
    "alembic",
    "scripts",
    "web/app",
    "web/components",
    "web/lib",
    "data/reference",
    "docs",
)
BACKSTOP_EXCLUDED_PREFIXES = ("docs/brief/",)
# Lockfiles carry integrity hashes, not credentials (the pre-commit hook's
# exclude pattern); the baseline is the scanner's own state.
SECRET_SCAN_EXCLUDES = ("uv.lock", "web/pnpm-lock.yaml", ".secrets.baseline")
# Longest argv (in characters) handed to detect-secrets-hook per call; well
# under the Windows command-line limit.
ARGV_BUDGET = 20_000
# The seed idempotency probe counts these canonical tables before and after a
# second `judgemetrics seed`; `metric_observation` joins them because pipeline
# step 13 publishes metrics inside the seed's ingest, and `outcome_model`
# because a seed must never fit a model (step 13 computes the descriptive
# kinds only).
SEED_PROBE_TABLES = (
    "jurisdiction",
    "court",
    "judge",
    "judge_service",
    "person",
    "court_case",
    "case_party",
    "judge_assignment",
    "charge",
    "court_event",
    "decision",
    "pretrial_release",
    "sentence",
    "justice_event",
    "metric_observation",
    "outcome_model",
)
# Run through `uv run python -c <snippet> <tables...>` (the script itself
# stays standard-library only): row counts of the named tables as one JSON
# object on stdout, read through the configured settings.
COUNT_SNIPPET = """
import json
import sys
import sqlalchemy as sa
from judgemetrics.config import get_settings
from judgemetrics.db.session import make_engine
engine = make_engine(get_settings().database_url)
try:
    with engine.connect() as connection:
        counts = {
            name: connection.execute(
                sa.select(sa.func.count()).select_from(sa.table(name))
            ).scalar_one()
            for name in sys.argv[1:]
        }
finally:
    engine.dispose()
print(json.dumps(counts))
"""
# One current observed_expected observation that cites a model, chosen at
# random, for the adjusted provenance probe.
OBSERVATION_SNIPPET = """
import json
import sqlalchemy as sa
from judgemetrics.config import get_settings
from judgemetrics.db.session import make_engine
engine = make_engine(get_settings().database_url)
observation = sa.table(
    "metric_observation",
    sa.column("id"),
    sa.column("superseded_at"),
    sa.column("metric_definition_id"),
    sa.column("outcome_model_id"),
)
definition = sa.table("metric_definition", sa.column("id"), sa.column("kind"))
try:
    with engine.connect() as connection:
        found = connection.execute(
            sa.select(observation.c.id)
            .join(definition, definition.c.id == observation.c.metric_definition_id)
            .where(
                observation.c.superseded_at.is_(None),
                observation.c.outcome_model_id.is_not(None),
                definition.c.kind == "observed_expected",
            )
            .order_by(sa.func.random())
            .limit(1)
        ).scalar_one_or_none()
finally:
    engine.dispose()
print(json.dumps({"id": None if found is None else str(found)}))
"""
# Wall-clock ceilings for the --post subprocesses. `uv run poe bootstrap` took
# 249 s from a clean database and 48 s on the rerun on the maintainer's
# machine (Phase 3 Step 5); a fitting compute of the demo seed takes minutes
# (thirteen models at 500 replicates each, Phase 4 Step 2), and the whole
# test suite takes minutes.
BOOTSTRAP_TIMEOUT = 1_800
SEED_TIMEOUT = 1_800
CHECK_TIMEOUT = 3_600
# Where the --post probes keep the scratch database's snapshots (git-ignored
# under data/snapshots/, apart from the live database's content-hash folders).
SCRATCH_SNAPSHOT_DIR = "data/snapshots/scratch-test-db"
# The dataset `uv run poe seed` writes when JUDGEMETRICS_SYNTHETIC_DIR is
# unset (Settings.synthetic_dir); the validation probes read its truth.
DEFAULT_SYNTHETIC_DIR = "data/synthetic/20260916"
ROLE_URL_VARIABLES = (
    "JUDGEMETRICS_DATABASE_URL",
    "JUDGEMETRICS_ADMIN_DATABASE_URL",
    "JUDGEMETRICS_INGEST_DATABASE_URL",
)

# --------------------------------------------------------------------------- #
# Results and output
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Outcome:
    """One reported item: a static check, a suite, a probe, or a V-check."""

    id: str
    description: str
    status: Status
    reason: str = ""

    @property
    def failed(self) -> bool:
        return self.status == "FAIL"


def report(outcome: Outcome) -> Outcome:
    line = f"[{outcome.status}] {outcome.id} {outcome.description}"
    if outcome.reason:
        line += f" — {outcome.reason}"
    print(line, flush=True)
    return outcome


def heading(text: str) -> None:
    print(f"\n== {text} ==", flush=True)


# --------------------------------------------------------------------------- #
# Static-check helpers (pathlib, re, json, hashlib, and `git ls-files` only)
# --------------------------------------------------------------------------- #


def _path(relative: str) -> Path:
    return REPO_ROOT / relative


def _read(relative: str) -> str:
    return _path(relative).read_text(encoding="utf-8")


def _missing(*relatives: str) -> str | None:
    absent = [rel for rel in relatives if not _path(rel).is_file()]
    return f"missing {', '.join(absent)}" if absent else None


def _lacks(relative: str, pattern: str, what: str) -> str | None:
    """Failure reason when ``relative`` exists but does not match ``pattern``."""
    if (reason := _missing(relative)) is not None:
        return reason
    if re.search(pattern, _read(relative), re.MULTILINE) is None:
        return f"{relative} lacks {what}"
    return None


def _lacks_all(relative: str, patterns: Sequence[tuple[str, str]]) -> str | None:
    """The first failure reason over ``(pattern, what)`` pairs, or None."""
    for pattern, what in patterns:
        if (reason := _lacks(relative, pattern, what)) is not None:
            return reason
    return None


def _git_ls_files(*pathspecs: str) -> list[str]:
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git not on PATH")
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell  # nosec B603
        [git, "ls-files", "-z", "--", *pathspecs],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
    )
    return [name for name in completed.stdout.decode("utf-8").split("\0") if name]


def _untracked(*relatives: str) -> str | None:
    """Failure reason naming any of ``relatives`` that git does not track."""
    tracked = set(_git_ls_files(*relatives))
    absent = [rel for rel in relatives if rel not in tracked]
    return f"not tracked by git: {', '.join(absent)}" if absent else None


def _yaml_job_block(workflow: str, job: str) -> str | None:
    """The lines of one job under ``jobs:`` (two-space indented key) or None."""
    lines = workflow.splitlines()
    start = next((i for i, line in enumerate(lines) if line == f"  {job}:"), None)
    if start is None:
        return None
    end = next(
        (i for i in range(start + 1, len(lines)) if re.match(r"^  [A-Za-z_][\w-]*:", lines[i])),
        len(lines),
    )
    return "\n".join(lines[start:end])


def _toml_table(text: str, table: str) -> str | None:
    """The body of one ``[table]`` (or ``[[table]]``) in a TOML document."""
    match = re.search(rf"^\[{re.escape(table)}\]\n(.*?)(?=^\[|\Z)", text, re.MULTILINE | re.DOTALL)
    return match.group(1) if match else None


def _poe_tasks() -> set[str]:
    body = _toml_table(_read("pyproject.toml"), "tool.poe.tasks") or ""
    return set(re.findall(r'^"?([A-Za-z][\w-]*)"?\s*=', body, re.MULTILINE))


def _makefile_targets() -> set[str]:
    return set(re.findall(r"^([A-Za-z][\w-]*):", _read("Makefile"), re.MULTILINE))


def _env_example_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in _read(".env.example").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        # Docker Compose treats " #" after an unquoted value as a comment.
        values[key.strip()] = value.split(" #", 1)[0].strip()
    return values


def _check_names(names: Sequence[str], found: set[str], what: str) -> str | None:
    absent = [name for name in names if name not in found]
    return f"{what} missing {', '.join(absent)}" if absent else None


def _unpinned_uses(relative: str) -> str | None:
    if (reason := _missing(relative)) is not None:
        return reason
    uses = re.findall(r"^\s*-?\s*uses:\s*(\S+)", _read(relative), re.MULTILINE)
    if not uses:
        return f"{relative} has no `uses:` lines"
    unpinned = [ref for ref in uses if SHA_PIN.search(ref) is None]
    return f"{relative} has unpinned actions: {', '.join(unpinned)}" if unpinned else None


def _dict_keys(node: object) -> set[str]:
    """Every key of every mapping nested anywhere in a JSON document."""
    keys: set[str] = set()
    if isinstance(node, dict):
        for key, value in node.items():
            keys.add(str(key))
            keys |= _dict_keys(value)
    elif isinstance(node, list):
        for item in node:
            keys |= _dict_keys(item)
    return keys


def _normalize(text: str) -> str:
    """Collapse every run of whitespace to one space (wrapped prose compares equal)."""
    return " ".join(text.split())


def _registry_scalar(key: str) -> str | None:
    """A top-level scalar of the registry (``key: value``), quotes stripped."""
    match = re.search(rf"^{re.escape(key)}:\s*(.+?)\s*$", _read(REGISTRY), re.MULTILINE)
    return match.group(1).strip("\"'") if match else None


def _registry_limitations() -> list[str]:
    """The registry's ``known_limitations`` items, folded to one line each.

    A minimal reader for the one shape the file uses (a block sequence of
    ``- >-`` folded scalars or plain / quoted scalars at two-space indent),
    so the script needs no YAML library; the unit suite loads the registry
    with ``yaml.safe_load`` and pins the same equality.
    """
    items: list[list[str]] = []
    inside = False
    for line in _read(REGISTRY).splitlines():
        if line.startswith("known_limitations:"):
            inside = True
            continue
        if not inside:
            continue
        if line and not line.startswith(" "):
            break
        item = re.match(r"^  - ?(.*)$", line)
        if item is not None:
            head = item.group(1).strip()
            items.append([] if head in (">-", ">", "|", "|-") else [head.strip("\"'")])
        elif line.strip() and items:
            items[-1].append(line.strip())
    return [_normalize(" ".join(parts)) for parts in items]


def _registry_slugs() -> list[str]:
    return re.findall(r"^  - slug:\s*([a-z0-9_]+)\s*$", _read(REGISTRY), re.MULTILINE)


def _brief_warnings() -> list[str]:
    """The brief's ``<important_statistical_warnings>`` in order, whitespace-normalized.

    The XML is read with a regular expression over the one element (the
    element holds plain text only), which keeps the script free of an XML
    parser that SAST flags on principle.
    """
    block = re.search(
        r"<important_statistical_warnings>(.*?)</important_statistical_warnings>",
        _read(BRIEF),
        re.DOTALL,
    )
    if block is None:
        return []
    return [
        _normalize(text)
        for text in re.findall(r"<warning>(.*?)</warning>", block.group(1), re.DOTALL)
    ]


def _markdown_section(relative: str, title: str) -> str | None:
    """The body of a ``## title`` section (up to the next heading of level 1-2)."""
    match = re.search(
        rf"^##\s+{re.escape(title)}\s*$(.*?)(?=^#{{1,2}}\s|\Z)",
        _read(relative),
        re.MULTILINE | re.DOTALL,
    )
    return match.group(1) if match else None


def _registry_entries() -> dict[str, str]:
    """Slug → the lines of its registry entry (up to the next ``  - slug:``)."""
    text = _read(REGISTRY)
    starts = [m for m in re.finditer(r"^  - slug:\s*([a-z0-9_]+)\s*$", text, re.MULTILINE)]
    entries: dict[str, str] = {}
    for i, match in enumerate(starts):
        end = starts[i + 1].start() if i + 1 < len(starts) else len(text)
        entries[match.group(1)] = text[match.start() : end]
    return entries


def _top_level_keys(relative: str) -> list[str]:
    return re.findall(r"^([a-z_]+):", _read(relative), re.MULTILINE)


def _spec_features() -> list[dict[str, str]]:
    """The specification's ``features`` entries, each key folded to one line.

    A minimal reader for the one shape the file uses (a block sequence of
    mappings at two-space indent whose keys sit at four spaces, folded
    ``>-`` values continuing at six), so the script needs no YAML library;
    the unit suite loads the file with ``yaml.safe_load`` and pins the
    names, ``known_at``, and ``leakage`` this returns.
    """
    items: list[dict[str, list[str]]] = []
    key: str | None = None
    inside = False
    for line in _read(SPECIFICATION).splitlines():
        if line.startswith("features:"):
            inside = True
            continue
        if not inside:
            continue
        if line and not line.startswith(" "):
            break
        if (start := re.match(r"^  - name:\s*(\S+)\s*$", line)) is not None:
            items.append({"name": [start.group(1)]})
            key = "name"
            continue
        if (pair := re.match(r"^    ([a-z_]+):\s*(.*?)\s*$", line)) is not None and items:
            key, value = pair.group(1), pair.group(2)
            items[-1][key] = [] if value in (">-", ">", "|", "|-") else [value.strip("\"'")]
            continue
        if line.startswith("      ") and line.strip() and items and key is not None:
            items[-1][key].append(line.strip())
    return [{k: _normalize(" ".join(v)) for k, v in item.items()} for item in items]


def _brief_interpretation() -> str | None:
    """The brief's ``<risk_adjustment><interpretation>``, whitespace-normalized."""
    match = re.search(r"<interpretation>(.*?)</interpretation>", _read(BRIEF), re.DOTALL)
    return None if match is None else _normalize(match.group(1))


def _source_version(relative: str, constant: str) -> int | None:
    """``<constant> = "<n>"`` read from a source file with a regular expression."""
    found = re.search(rf'^\s*{constant}\s*=\s*"(\d+)"', _read(relative), re.MULTILINE)
    return None if found is None else int(found.group(1))


def _tuple_literal(relative: str, name: str) -> list[str] | None:
    """The string items of a ``NAME: ... = ( ... )`` tuple literal, or None."""
    match = re.search(rf"^{name}\b[^=]*=\s*\((.*?)^\)", _read(relative), re.MULTILINE | re.DOTALL)
    return None if match is None else re.findall(r'"([^"]*)"', match.group(1))


def _changelog_versions() -> list[str]:
    match = re.search(
        r"^CHANGELOG\b[^=]*=\s*\((.*?)^\)", _read(METHODOLOGY_MODULE), re.MULTILINE | re.DOTALL
    )
    if match is None:
        return []
    return re.findall(r'^\s{8}"(\d+\.\d+)",\s*$', match.group(1), re.MULTILINE)


def _function_body(relative: str, name: str) -> str | None:
    """The source of one top-level ``def name(`` up to the next top-level statement."""
    match = re.search(
        # The next top-level statement; a multi-line signature's closing
        # `) -> T:` sits at column 0 and is not one.
        rf"^def {re.escape(name)}\(.*?(?=^[A-Za-z_@#])",
        _read(relative) + "\n#",
        re.MULTILINE | re.DOTALL,
    )
    return None if match is None else match.group(0)


def _tracked(*relatives: str) -> str | None:
    return _missing(*relatives) or _untracked(*relatives)


# --------------------------------------------------------------------------- #
# Static checks 1-50
# --------------------------------------------------------------------------- #

# Step 1 — planted effects, synthetic restricted attributes, restricted schema


def check_01() -> str | None:
    if (reason := _missing(SYNTHETIC_CONFIG, SYNTHETIC_RNG)) is not None:
        return reason
    version = _source_version(SYNTHETIC_CONFIG, "GENERATOR_VERSION")
    if version is None or version < MINIMUM_GENERATOR_VERSION:
        return f"{SYNTHETIC_CONFIG} GENERATOR_VERSION is not at least {MINIMUM_GENERATOR_VERSION}"
    streams = _tuple_literal(SYNTHETIC_RNG, "STREAM_NAMES")
    if streams is None:
        return f"{SYNTHETIC_RNG} has no STREAM_NAMES tuple"
    return _check_names(NEW_STREAMS, set(streams), "STREAM_NAMES")


def check_02() -> str | None:
    if (reason := _missing(SYNTHETIC_TRUTH)) is not None:
        return reason
    version = _source_version(SYNTHETIC_TRUTH, "TRUTH_VERSION")
    if version is None or version < MINIMUM_TRUTH_VERSION:
        return f"{SYNTHETIC_TRUTH} TRUTH_VERSION is not at least {MINIMUM_TRUTH_VERSION}"
    files = _tuple_literal(SYNTHETIC_TRUTH, "TRUTH_FILES")
    if files is None:
        return f"{SYNTHETIC_TRUTH} has no TRUTH_FILES tuple"
    return _check_names(("effects.json",), set(files), "TRUTH_FILES")


def check_03() -> str | None:
    manifest_path = f"{GOLDEN_DIR}/manifest.json"
    effects_path = f"{GOLDEN_DIR}/truth/effects.json"
    if (reason := _missing(manifest_path, SYNTHETIC_CONFIG, SYNTHETIC_TRUTH)) is not None:
        return reason
    manifest = json.loads(_read(manifest_path))
    for key, relative, constant, minimum in (
        ("generator_version", SYNTHETIC_CONFIG, "GENERATOR_VERSION", MINIMUM_GENERATOR_VERSION),
        ("truth_version", SYNTHETIC_TRUTH, "TRUTH_VERSION", MINIMUM_TRUTH_VERSION),
    ):
        version = _source_version(relative, constant)
        if version is None or version < minimum:
            return f"{relative} has no {constant} of at least {minimum}"
        if str(manifest.get(key)) != str(version):
            return f"{manifest_path} {key} is not {constant} ({version})"
    if (reason := _tracked(effects_path)) is not None:
        return reason
    files = manifest.get("files")
    if not isinstance(files, dict) or "truth/effects.json" not in files:
        return f"{manifest_path} does not list truth/effects.json"
    if hashlib.sha256(_path(effects_path).read_bytes()).hexdigest() != files["truth/effects.json"]:
        return f"sha256 mismatch for {effects_path}"
    effects = json.loads(_read(effects_path))
    if absent := [key for key in EFFECTS_KEYS if key not in effects]:
        return f"{effects_path} lacks {', '.join(absent)}"
    targets = effects["targets"]
    names = set(targets) if isinstance(targets, (dict, list)) else set()
    return _check_names(EFFECT_TARGETS, {str(name) for name in names}, f"{effects_path} targets")


def check_04() -> str | None:
    relative = "alembic/versions/0008_restricted_schema.py"
    if (
        reason := _lacks_all(
            relative,
            (
                (r'^SCHEMA\s*=\s*"restricted"', 'SCHEMA = "restricted"'),
                (r'^TABLE\s*=\s*"party_attribute"', 'TABLE = "party_attribute"'),
                (r"CREATE SCHEMA \{SCHEMA\}", "CREATE SCHEMA {SCHEMA}"),
                (r"op\.create_table\(\s*TABLE\b", "op.create_table(TABLE"),
                (r'^APP_ROLE\s*=\s*"judgemetrics_app"', "the APP_ROLE constant"),
            ),
        )
    ) is not None:
        return reason
    text = _read(relative)
    if re.search(r"GRANT\b[^\n]*\bTO\s+(?:\{APP_ROLE\}|judgemetrics_app)\b", text):
        return f"{relative} grants something to the app role"
    if re.search(r"REVOKE ALL ON SCHEMA \{SCHEMA\} FROM \{APP_ROLE\}", text) is None:
        return f"{relative} does not revoke the app role's schema privileges"
    return None


def check_05() -> str | None:
    return _lacks("alembic/env.py", r"include_schemas\s*=\s*True", "include_schemas=True")


def check_06() -> str | None:
    return _lacks(
        "infra/docker/postgres/03-test-database.sql",
        r"REVOKE ALL ON SCHEMA restricted FROM judgemetrics_app",
        "the app role's revoke on the restricted schema",
    )


def check_07() -> str | None:
    if (reason := _missing(VOCABULARY)) is not None:
        return reason
    match = re.search(r"^version:\s*(\d+)\s*$", _read(VOCABULARY), re.MULTILINE)
    if match is None or int(match.group(1)) < MINIMUM_VOCABULARY_VERSION:
        return f"{VOCABULARY} version is not at least {MINIMUM_VOCABULARY_VERSION}"
    kinds = set(re.findall(r"^  ([a-z_]+):", _read(VOCABULARY), re.MULTILINE))
    return _check_names(RESTRICTED_KINDS, kinds, f"{VOCABULARY} kinds")


def check_08() -> str | None:
    normalize = f"{PACKAGE}/ingest/synthetic/normalize.py"
    connector = f"{PACKAGE}/ingest/synthetic/connector.py"
    if (reason := _missing(normalize, connector)) is not None:
        return reason
    text = _read(normalize)
    if re.search(r"source_row_id\s*=\s*context\.party_row_id\(", text) is None:
        return f"{normalize} does not key the case party with party_row_id()"
    if re.search(
        r"source_row_id\s*=\s*(?:normalized\b|participant_id\b|normalize_identifier\()", text
    ):
        return f"{normalize} writes the participant id into source_row_id"
    version = _source_version(connector, "parser_version")
    if version is None or version < MINIMUM_PARSER_VERSION:
        return f"{connector} parser_version is not at least {MINIMUM_PARSER_VERSION}"
    return None


def check_09() -> str | None:
    relative = f"{PACKAGE}/logging.py"
    if (reason := _missing(relative)) is not None:
        return reason
    match = re.search(r"^SENSITIVE_KEYS\b.*?^\)", _read(relative), re.MULTILINE | re.DOTALL)
    if match is None:
        return f"{relative} has no SENSITIVE_KEYS"
    keys = set(re.findall(r'"([a-z_]+)"', match.group(0)))
    return _check_names(SCRUBBED_KEYS, keys, "SENSITIVE_KEYS")


def check_10() -> str | None:
    if (reason := _missing(METHODOLOGY_MODULE)) is not None:
        return reason
    if "0.2" not in _changelog_versions():
        return f"{METHODOLOGY_MODULE} CHANGELOG has no 0.2 entry"
    return _tracked(*STEP1_TESTS)


def check_11() -> str | None:
    relative = "scripts/verify_phase03.py"
    if (reason := _missing(relative)) is not None:
        return reason
    body = _function_body(relative, "check_14")
    if body is None:
        return f"{relative} has no check_14"
    if "_source_version(" not in body:
        return f"{relative} check 14 does not read the source constants"
    if re.search(r"""(?:==|!=)\s*["']2["']|["']2["']\s*(?:==|!=)""", body):
        return f'{relative} check 14 still compares with a literal "2"'
    return None


# Step 2 — the specification and the baseline model


def check_12() -> str | None:
    if (reason := _tracked(SPECIFICATION)) is not None:
        return reason
    text = _read(SPECIFICATION)
    if not text.startswith(f"# {SPECIFICATION}"):
        return f"{SPECIFICATION} lacks its path comment"
    if re.search(r"^version:\s*\d+\s*$", text, re.MULTILINE) is None:
        return f"{SPECIFICATION} has no integer `version:`"
    if re.search(rf"^model_version:\s*{re.escape(MODEL_VERSION)}\s*$", text, re.MULTILINE) is None:
        return f"{SPECIFICATION} model_version is not {MODEL_VERSION}"
    return _check_names(SPEC_BLOCKS, set(_top_level_keys(SPECIFICATION)), SPECIFICATION)


def check_13() -> str | None:
    if (reason := _missing(SPECIFICATION)) is not None:
        return reason
    features = _spec_features()
    if not features:
        return f"{SPECIFICATION} lists no features"
    lacking = [
        feature["name"]
        for feature in features
        if not feature.get("known_at") or not feature.get("leakage")
    ]
    return f"features without known_at or leakage: {', '.join(lacking)}" if lacking else None


def check_14() -> str | None:
    return _missing(
        *(f"{PACKAGE}/metrics/adjustment/{name}.py" for name in ADJUSTMENT_STEP2_MODULES)
    )


def check_15() -> str | None:
    root = _path(f"{PACKAGE}/metrics")
    for module in sorted(root.glob("**/*.py")):
        text = module.read_text(encoding="utf-8")
        for label, pattern in UNSAFE_LOADS:
            if pattern.search(text):
                return f"`{label}` in {PACKAGE}/metrics/{module.relative_to(root).as_posix()}"
    return _lacks(
        f"{PACKAGE}/metrics/adjustment/artifacts.py",
        r"""\.open\(\s*["']xb["']\s*\)|open\([^)]*["']xb["']""",
        'an exclusive "xb" create',
    )


def check_16() -> str | None:
    if (reason := _missing("pyproject.toml", "uv.lock")) is not None:
        return reason
    project = _toml_table(_read("pyproject.toml"), "project") or ""
    dependencies = re.search(r"^dependencies\s*=\s*\[(.*?)^\]", project, re.MULTILINE | re.DOTALL)
    if dependencies is None or re.search(r'"numpy\b', dependencies.group(1)) is None:
        return "[project.dependencies] does not list numpy"
    lock = _read("uv.lock")
    if re.search(r'^name = "numpy"$', lock, re.MULTILINE) is None:
        return "uv.lock does not pin numpy"
    found = [n for n in FORBIDDEN_LOCKED if re.search(rf'^name = "{n}"$', lock, re.MULTILINE)]
    return f"uv.lock holds {', '.join(found)}" if found else None


def check_17() -> str | None:
    return _lacks_all(
        "alembic/versions/0009_outcome_models.py",
        (
            (r'^TABLE\s*=\s*"outcome_model"', 'TABLE = "outcome_model"'),
            (r'sa\.Column\("content_hash"', "the content_hash column"),
            (r'sa\.Column\("coefficients"', "the coefficients column"),
            (r'^APP_PRIVILEGES\s*=\s*"SELECT"', 'APP_PRIVILEGES = "SELECT"'),
            (
                r"GRANT \{APP_PRIVILEGES\} ON TABLE \{TABLE\} TO \{APP_ROLE\}",
                "the app grant built from the constants",
            ),
        ),
    )


def check_18() -> str | None:
    return _lacks_all(
        CLI,
        (
            (r'add_typer\(models_app,\s*name="models"\)', "the `models` group"),
            (r'@models_app\.command\("fit"\)', "`models fit`"),
            (r'@models_app\.command\("list"\)', "`models list`"),
            (r'@models_app\.command\("show"\)', "`models show`"),
            (r'@models_app\.command\("verify"\)', "`models verify`"),
            (r'"--refit"', "the `--refit` option"),
        ),
    )


def check_19() -> str | None:
    return _tracked(*STEP2_TESTS)


def check_20() -> str | None:
    if (reason := _missing(CI_WORKFLOW)) is not None:
        return reason
    workflow = _read(CI_WORKFLOW)
    e2e = _yaml_job_block(workflow, "e2e")
    if e2e is None:
        return f"{CI_WORKFLOW} has no `e2e` job"
    positions = []
    for command in ("metrics compute", "models fit", "models verify"):
        found = re.search(rf"run: uv run judgemetrics {command}\b", e2e)
        if found is None:
            return f"the `e2e` job does not run `judgemetrics {command}`"
        positions.append(found.start())
    if positions != sorted(positions):
        return "the `e2e` job does not run models fit and verify after metrics compute"
    container = _yaml_job_block(workflow, "container")
    if container is None:
        return f"{CI_WORKFLOW} has no `container` job"
    if "import judgemetrics.metrics.adjustment.logistic" not in container:
        return "the `container` job does not import the NumPy solver in the API image"
    return None


# Step 3 — expected counts, ratios, pooling, recovery


def check_21() -> str | None:
    if (reason := _missing(REGISTRY)) is not None:
        return reason
    version = _registry_scalar("version")
    if version is None or not version.isdigit() or int(version) < MINIMUM_REGISTRY_VERSION:
        return f"{REGISTRY} version is not at least {MINIMUM_REGISTRY_VERSION}"
    entries = _registry_entries()
    for slug in ADJUSTED_SLUGS:
        entry = entries.get(slug)
        if entry is None:
            return f"{REGISTRY} has no {slug}"
        if re.search(r"^    kind:\s*observed_expected\s*$", entry, re.MULTILINE) is None:
            return f"{slug} is not kind observed_expected"
        if re.search(r"^    adjustment:\s*$", entry, re.MULTILINE) is None:
            return f"{slug} has no adjustment block"
        threshold = re.search(r"^    suppression_threshold:\s*(\d+)\s*$", entry, re.MULTILINE)
        if threshold is None or int(threshold.group(1)) != ADJUSTED_THRESHOLD:
            return f"{slug} suppression_threshold is not {ADJUSTED_THRESHOLD}"
    return None


def check_22() -> str | None:
    return _missing(
        *(f"{PACKAGE}/metrics/adjustment/{name}.py" for name in ADJUSTMENT_STEP3_MODULES)
    )


def check_23() -> str | None:
    relative = "alembic/versions/0010_adjusted_observations.py"
    if (
        reason := _lacks_all(
            relative,
            (
                (r'^MODEL_COLUMN\s*=\s*"outcome_model_id"', "outcome_model_id"),
                (r'^WEIGHT_COLUMN\s*=\s*"pooling_weight"', "pooling_weight"),
                (r'^REASON_COLUMN\s*=\s*"suppression_reason"', "suppression_reason"),
            ),
        )
    ) is not None:
        return reason
    text = _read(relative)
    absent = [reason for reason in SUPPRESSION_REASONS if f'"{reason}"' not in text]
    return f"{relative} lacks the reasons {', '.join(absent)}" if absent else None


def check_24() -> str | None:
    relative = f"{PACKAGE}/metrics/publish.py"
    if (reason := _missing(relative)) is not None:
        return reason
    columns = _tuple_literal(relative, "VERIFIED_COLUMNS")
    if columns is None:
        return f"{relative} has no VERIFIED_COLUMNS"
    return _check_names(ADJUSTED_VERIFIED_COLUMNS, set(columns), "VERIFIED_COLUMNS")


def check_25() -> str | None:
    relative = f"{PACKAGE}/ingest/runner.py"
    if (reason := _missing(relative)) is not None:
        return reason
    body = _function_body(relative, "recompute_metrics")
    if body is None:
        return f"{relative} has no recompute_metrics"
    if re.search(r"\bkinds\s*=\s*DESCRIPTIVE_KINDS\b", body) is None:
        return "recompute_metrics does not restrict step 13 to DESCRIPTIVE_KINDS"
    return None


def check_26() -> str | None:
    if (reason := _tracked(*STEP3_TESTS)) is not None:
        return reason
    match = re.search(r"^recovery:\s*$(.*?)(?=^\S|\Z)", _read(SPECIFICATION), re.M | re.S)
    if match is None:
        return f"{SPECIFICATION} has no recovery block"
    numbers = re.findall(r"^\s+[a-z_]+:\s*(\d+(?:\.\d+)?)\s*$", match.group(1), re.MULTILINE)
    if len(numbers) < 5:
        return f"the recovery block holds {len(numbers)} numeric tolerances, fewer than 5"
    return None


def check_27() -> str | None:
    relative = f"{PACKAGE}/api/routes/health.py"
    if (reason := _missing(relative)) is not None:
        return reason
    match = re.search(r"^class MetricsReadiness\b.*?(?=^class |\Z)", _read(relative), re.M | re.S)
    if match is None:
        return f"{relative} has no MetricsReadiness"
    if re.search(r"^\s+models\s*:", match.group(0), re.MULTILINE) is None:
        return "MetricsReadiness has no `models` field"
    return None


def check_28() -> str | None:
    return _lacks(
        f"{PACKAGE}/metrics/provenance.py",
        r"outcome model \{model\.content_hash\}",
        "the model's content hash in the rendered trace",
    )


def check_29() -> str | None:
    return _lacks_all(
        "docs/DATA_MODEL.md",
        (
            (r"\bobserved_expected\b", "`observed_expected`"),
            (r"\boutcome_model\b", "`outcome_model`"),
            (r"\bparty_attribute\b", "`party_attribute`"),
        ),
    ) or _lacks("docs/ARCHITECTURE.md", r"^#+ Risk adjustment\s*$", "a `Risk adjustment` heading")


# Step 4 — validation and methodology 1.0


def check_30() -> str | None:
    return _missing(*(f"{PACKAGE}/validation/{name}.py" for name in VALIDATION_MODULES))


def _restricted_allowed_directories() -> tuple[str, ...]:
    """The directories ``test_restricted_readers.py`` allows, else the Phase 4 minimum."""
    if not _path(RESTRICTED_READERS_TEST).is_file():
        return RESTRICTED_ALLOWED_DIRECTORIES
    match = re.search(
        r"^ALLOWED_DIRECTORIES = \(([^)]*)\)", _read(RESTRICTED_READERS_TEST), re.MULTILINE
    )
    listed = tuple(re.findall(r'"([^"]+)"', match.group(1))) if match else ()
    return tuple(dict.fromkeys((*RESTRICTED_ALLOWED_DIRECTORIES, *listed)))


def check_31() -> str | None:
    root = _path(PACKAGE)
    outside = []
    allowed_directories = _restricted_allowed_directories()
    for module in sorted(root.rglob("*.py")):
        relative = module.relative_to(root).as_posix()
        if relative in RESTRICTED_ALLOWED_FILES or relative.startswith(allowed_directories):
            continue
        if RESTRICTED_NAME.search(module.read_text(encoding="utf-8")):
            outside.append(f"{PACKAGE}/{relative}")
    if outside:
        return f"the restricted table is named outside the allow-list: {', '.join(outside)}"
    reader = _path(f"{PACKAGE}/validation/fairness.py")
    if not reader.is_file() or RESTRICTED_NAME.search(reader.read_text(encoding="utf-8")) is None:
        return "validation/fairness.py does not read the restricted table"
    return None


def check_32() -> str | None:
    if (reason := _tracked(VALIDATION_DOC)) is not None:
        return reason
    text = _read(VALIDATION_DOC)
    if not text.startswith(f"<!-- {VALIDATION_DOC} -->"):
        return f"{VALIDATION_DOC} lacks its path comment"
    if "Generated by `judgemetrics validation report`" not in text[:400]:
        return f"{VALIDATION_DOC} lacks the generated notice"
    headings = re.findall(r"^## (.+?)\s*$", text, re.MULTILINE)
    absent = [s for s in VALIDATION_SECTIONS if not any(h.startswith(s) for h in headings)]
    if absent:
        return f"{VALIDATION_DOC} lacks the sections {', '.join(absent)}"
    if UUID_SHAPE.search(text):
        return f"{VALIDATION_DOC} contains a UUID-shaped string"
    if HEX64.search(text):
        return f"{VALIDATION_DOC} contains a 64-hex string"
    return None


def check_33() -> str | None:
    relative = "docs/METHODOLOGY.md"
    if (reason := _missing(REGISTRY, relative, BRIEF)) is not None:
        return reason
    version = _registry_scalar("methodology_version") or ""
    if (
        re.fullmatch(r"\d+\.\d+", version) is None
        or tuple(int(part) for part in version.split(".")) < MINIMUM_METHODOLOGY
    ):
        return f"{REGISTRY} methodology_version is not at least 1.0"
    if f"methodology version {version}" not in _read(relative):
        return f"{relative} does not state methodology version {version}"
    adjusted = _markdown_section(relative, "Adjusted statistics")
    if adjusted is None:
        return f"{relative} has no `## Adjusted statistics` section"
    interpretation = _brief_interpretation()
    if not interpretation:
        return "the brief yields no <interpretation>"
    if interpretation not in _normalize(re.sub(r"^\s*>\s?", " ", adjusted, flags=re.MULTILINE)):
        return f"{relative} Adjusted statistics lacks the brief's interpretation verbatim"
    limitations = _markdown_section(relative, "Known limitations")
    if limitations is None:
        return f"{relative} has no `## Known limitations` section"
    warnings = _brief_warnings()
    if len(warnings) != BRIEF_WARNING_COUNT:
        return f"the brief yields {len(warnings)} warnings, not {BRIEF_WARNING_COUNT}"
    body = _normalize(re.sub(r"^\s*\d+\.\s+", " ", limitations, flags=re.MULTILINE))
    absent = [str(i) for i, warning in enumerate(warnings, 1) if warning not in body]
    return f"{relative} lacks brief warning(s) {', '.join(absent)} verbatim" if absent else None


def check_34() -> str | None:
    if (reason := _missing(METHODOLOGY_MODULE)) is not None:
        return reason
    versions = _changelog_versions()
    if versions[: len(CHANGELOG_VERSIONS)] != list(CHANGELOG_VERSIONS):
        return f"CHANGELOG lists {versions}, not {list(CHANGELOG_VERSIONS)} first"
    return None


def check_35() -> str | None:
    return (
        _lacks_all(
            CLI,
            (
                (r'add_typer\(validation_app,\s*name="validation"\)', "the `validation` group"),
                (r'@validation_app\.command\("report"\)', "`validation report`"),
                (r'@validation_app\.command\("recovery"\)', "`validation recovery`"),
            ),
        )
        or _validation_report_options()
    )


def _validation_report_options() -> str | None:
    body = _function_body(CLI, "validation_report")
    if body is None:
        return f"{CLI} has no validation_report"
    absent = [flag for flag in ("--check", "--truth") if f'"{flag}"' not in body]
    return f"`validation report` lacks {', '.join(absent)}" if absent else None


def check_36() -> str | None:
    if (reason := _missing(CI_WORKFLOW)) is not None:
        return reason
    block = _yaml_job_block(_read(CI_WORKFLOW), "e2e")
    if block is None:
        return f"{CI_WORKFLOW} has no `e2e` job"
    if re.search(r"run: uv run judgemetrics validation report --check\b", block) is None:
        return "the `e2e` job does not run `judgemetrics validation report --check`"
    return None


def check_37() -> str | None:
    return _tracked(*STEP4_TESTS)


# Step 5 — adjusted panels and the model card


def check_38() -> str | None:
    relative = f"{PACKAGE}/schemas/metrics.py"
    if (reason := _missing(relative)) is not None:
        return reason
    text = _read(relative)
    kind = re.search(r"^MetricKind\s*=\s*Literal\[(.*?)\]", text, re.MULTILINE | re.DOTALL)
    if kind is None or '"observed_expected"' not in kind.group(1):
        return "MetricKind does not list observed_expected"
    method = re.search(r"^IntervalMethod\s*=\s*Literal\[(.*?)\]", text, re.MULTILINE | re.DOTALL)
    if method is None or '"bootstrap"' not in method.group(1):
        return "IntervalMethod does not list bootstrap"
    absent = [f for f in SCHEMA_ADJUSTED_FIELDS if re.search(rf"^\s+{f}\s*:", text, re.M) is None]
    if absent:
        return f"{relative} does not declare {', '.join(absent)}"
    found = [name for name in SCHEMA_PERSON_FIELDS if re.search(rf"\b{name}\b", text)]
    return f"{relative} names {', '.join(found)}" if found else None


def check_39() -> str | None:
    if (reason := _missing(f"{PACKAGE}/api/routes/models.py", "docs/openapi.json")) is not None:
        return reason
    paths = json.loads(_read("docs/openapi.json")).get("paths", {})
    if absent := sorted(OPENAPI_PATHS - set(paths)):
        return f"openapi.json lacks {absent}"
    return None


def check_40() -> str | None:
    return _lacks_all(
        "web/lib/api/schema.d.ts",
        (
            (re.escape(f'"{MODELS_PATH}"'), MODELS_PATH),
            (r'"observed_expected"', "observed_expected"),
        ),
    )


def check_41() -> str | None:
    component = "web/components/adjusted-stat.tsx"
    if (
        reason := _lacks_all(
            component,
            (
                (r'data-testid="adjusted-stat"', 'data-testid="adjusted-stat"'),
                (r"\bdata-reason=", "the data-reason attribute"),
                (r"\bformatRatioInterval\(", "formatRatioInterval()"),
                (r"\bmethodologyHref\b", "methodologyHref"),
            ),
        )
    ) is not None:
        return reason
    # The interval's label lives in lib/metrics.ts (INTERVAL_METHOD_LABEL),
    # which formatRatioInterval renders (Phase 4 Step 5's note to this step).
    return _lacks(
        "web/lib/metrics.ts",
        rf'bootstrap:\s*"{re.escape(INTERVAL_LABEL)}"',
        f'the "{INTERVAL_LABEL}" label',
    )


def check_42() -> str | None:
    if (reason := _missing("web/app/models/[modelId]/page.tsx")) is not None:
        return reason
    library = "web/lib/metrics.ts"
    if (reason := _missing(library)) is not None:
        return reason
    panels = re.search(
        r"^export const JUDGE_PANELS\b.*?^\];", _read(library), re.MULTILINE | re.DOTALL
    )
    if panels is None or re.search(r'\bid:\s*"adjusted"', panels.group(0)) is None:
        return "JUDGE_PANELS has no `adjusted` panel"
    page = "web/app/judges/[judgeId]/page.tsx"
    if (reason := _missing(page)) is not None:
        return reason
    count = _read(page).count('data-testid="association-statement"')
    return f"{page} renders {count} association statements, not 1" if count != 1 else None


def check_43() -> str | None:
    return _lacks(
        "web/app/methodology/page.tsx",
        r'\bid="adjusted-statistics"',
        "the adjusted-statistics section",
    )


def check_44() -> str | None:
    if (reason := _tracked(*STEP5_WEB_TESTS)) is not None:
        return reason
    relative = "web/tests/e2e/adjusted.spec.ts"
    tests = re.findall(r"^\s*test\(", _read(relative), re.MULTILINE)
    if len(tests) < ADJUSTED_SPEC_MIN_TESTS:
        return f"{relative} has {len(tests)} tests, fewer than {ADJUSTED_SPEC_MIN_TESTS}"
    return None


def check_45() -> str | None:
    folder = f"docs/screenshots/phase{PHASE}-step5"
    if (reason := _missing(f"{folder}/README.md")) is not None:
        return reason
    light = [p for p in _path(folder).glob("*-light.png") if p.stat().st_size > 0]
    dark = [p for p in _path(folder).glob("*-dark.png") if p.stat().st_size > 0]
    if not light or not dark:
        return f"{folder} lacks {'light' if not light else 'dark'} captures"
    return None


# Step 6 — self-checks


def check_46() -> str | None:
    relative = f"scripts/verify_phase{PHASE}.py"
    if (reason := _tracked(relative)) is not None:
        return reason
    text = _read(relative)
    if not text.startswith(f"# {relative}\n"):
        return f"{relative} lacks its path comment"
    absent = [flag for flag in MODE_FLAGS if re.search(rf'add_argument\(\s*"{flag}"', text) is None]
    return f"{relative} lacks the argparse modes {', '.join(absent)}" if absent else None


def check_47() -> str | None:
    relative = f"docs/phase{PHASE}-qa-findings.md"
    if (reason := _missing(relative)) is not None:
        return reason
    text = _read(relative)
    absent = [section for section in QA_SECTIONS if section not in text]
    return f"{relative} lacks {', '.join(absent)}" if absent else None


def check_48() -> str | None:
    return _missing(f"docs/roadmap/phase{PHASE}-roadmap.md")


def check_49() -> str | None:
    relative = ".github/workflows/phase-verify.yml"
    if (reason := _missing(relative)) is not None:
        return reason
    matrix = re.search(r"phase:\s*\[([^\]]*)\]", _read(relative))
    entries = (
        {entry.strip().strip("\"'") for entry in matrix.group(1).split(",")} if matrix else set()
    )
    # A subset, never the exact list (Phase 3 finding 6.1).
    if absent := sorted(MATRIX_ENTRIES - entries):
        return f"{relative} matrix lacks {', '.join(absent)}"
    return _unpinned_uses(relative)


def check_50() -> str | None:
    config = ".pre-commit-config.yaml"
    if (reason := _missing(config)) is not None:
        return reason
    hooks = set(re.findall(r"^\s*-\s*id:\s*([\w-]+)", _read(config), re.MULTILINE))
    if (reason := _check_names(PRE_COMMIT_HOOKS, hooks, f"{config} hooks")) is not None:
        return reason
    if re.search(r"entry:\s*uv run python scripts/audit_deps\.py", _read(config)) is None:
        return f"{config} pip-audit hook does not run scripts/audit_deps.py"
    for workflow in (CI_WORKFLOW, ".github/workflows/phase-verify.yml"):
        if (reason := _lacks(workflow, r"^permissions:", "top-level `permissions:`")) is not None:
            return reason
        if (reason := _unpinned_uses(workflow)) is not None:
            return reason
    for relative in _git_ls_files(*BACKSTOP_TREES):
        path = _path(relative)
        if relative.startswith(BACKSTOP_EXCLUDED_PREFIXES) or not path.is_file():
            continue
        data = path.read_bytes()
        for label, pattern in BACKSTOP_PATTERNS:
            if pattern.search(data):
                return f"{label} in {relative}"
    return None


STATIC_CHECKS: tuple[tuple[int, str, CheckFn], ...] = (
    (1, "GENERATOR_VERSION >= 3; STREAM_NAMES has effects and attributes", check_01),
    (2, "TRUTH_VERSION >= 3; TRUTH_FILES has effects.json", check_02),
    (
        3,
        "golden manifest at the source versions; truth/effects.json tracked, hashed, complete",
        check_03,
    ),
    (
        4,
        "alembic 0008 creates restricted.party_attribute and grants the app role nothing",
        check_04,
    ),
    (5, "alembic/env.py sets include_schemas", check_05),
    (6, "03-test-database.sql revokes the app role's usage of the restricted schema", check_06),
    (7, "case_vocabulary.yaml >= 2 with restricted_attribute, age_band, synthetic_group", check_07),
    (8, "the synthetic party key holds no participant id; parser_version >= 2", check_08),
    (9, "logging SENSITIVE_KEYS has age_band, synthetic_group, attribute_value", check_09),
    (10, "CHANGELOG carries 0.2; the Step 1 tests are tracked", check_10),
    (11, "verify_phase03.py check 14 reads the source constants", check_11),
    (
        12,
        "outcome_model.yaml is tracked, versioned, expected-logit-v1, with every block",
        check_12,
    ),
    (13, "every specification feature has known_at and leakage", check_13),
    (14, "metrics/adjustment/ has spec, features, logistic, resample ... fit", check_14),
    (15, "no module under metrics/ unpickles, np.loads, or evals; artifacts open xb", check_15),
    (16, "numpy is a dependency pinned in uv.lock; no scipy/sklearn/statsmodels/pandas", check_16),
    (17, "alembic 0009 creates outcome_model and grants the app role SELECT", check_17),
    (18, "cli.py registers models fit, list, show, verify --refit", check_18),
    (19, "the Step 2 test files are tracked", check_19),
    (
        20,
        "ci.yml e2e fits and verifies models after compute; container imports the solver",
        check_20,
    ),
    (21, "the registry >= 2 has the three observed_expected metrics at threshold 30", check_21),
    (22, "metrics/adjustment/ has expected, pooling, bootstrap", check_22),
    (23, "alembic 0010 adds outcome_model_id, pooling_weight, suppression_reason", check_23),
    (24, "publish.VERIFIED_COLUMNS covers the adjusted columns", check_24),
    (25, "ingest/runner.recompute_metrics restricts step 13 to the descriptive kinds", check_25),
    (26, "the Step 3 tests are tracked; the recovery block holds tolerances", check_26),
    (27, "api/routes/health.py reports models under metrics", check_27),
    (28, "metrics/provenance.py names the model's content hash in the trace", check_28),
    (29, "DATA_MODEL.md names the Phase 4 tables; ARCHITECTURE.md has Risk adjustment", check_29),
    (30, "validation/ has report, fairness, sensitivity, stability, recovery ...", check_30),
    (31, "only the allowed modules name the restricted table", check_31),
    (32, "docs/VALIDATION.md is generated, sectioned, and names no UUID or hash", check_32),
    (
        33,
        "methodology >= 1.0; METHODOLOGY.md has the interpretation and the warnings",
        check_33,
    ),
    (34, "CHANGELOG lists 0.1, 0.2, 0.3, 1.0 in order", check_34),
    (35, "cli.py registers validation report (--check, --truth) and recovery", check_35),
    (36, "ci.yml e2e runs validation report --check", check_36),
    (37, "the Step 4 tests are tracked", check_37),
    (38, "schemas/metrics.py serves the adjusted kind and names no person field", check_38),
    (39, "api/routes/models.py exists; openapi.json has the models and Phase 3 paths", check_39),
    (40, "web/lib/api/schema.d.ts names the model route and observed_expected", check_40),
    (41, "adjusted-stat.tsx renders the bootstrap interval and the methodology link", check_41),
    (42, "the model page exists; JUDGE_PANELS has adjusted; one association statement", check_42),
    (43, "the methodology page has the adjusted-statistics section", check_43),
    (44, "the Step 5 web tests are tracked; adjusted.spec.ts has five tests", check_44),
    (45, "docs/screenshots/phase04-step5 has README.md with light and dark captures", check_45),
    (46, f"scripts/verify_phase{PHASE}.py is tracked with its path comment and modes", check_46),
    (47, f"docs/phase{PHASE}-qa-findings.md has every rollup section", check_47),
    (48, f"docs/roadmap/phase{PHASE}-roadmap.md exists", check_48),
    (49, f'.github/workflows/phase-verify.yml matrix includes "01"-"{PHASE}"', check_49),
    (
        50,
        "security wiring: hooks, least-privilege pinned workflows, no key material",
        check_50,
    ),
)


def run_static_checks() -> list[Outcome]:
    heading(f"Static checks ({len(STATIC_CHECKS)})")
    outcomes: list[Outcome] = []
    for number, description, check in STATIC_CHECKS:
        try:
            reason = check()
        except Exception as exc:  # a broken check is a failed check, never a crash
            reason = f"{type(exc).__name__}: {exc}"
        status: Status = "PASS" if reason is None else "FAIL"
        outcomes.append(report(Outcome(f"{number:02d}", description, status, reason or "")))
    return outcomes


def statics_in_range(outcomes: Sequence[Outcome], first: int, last: int) -> Outcome:
    failed = [o.id for o in outcomes if first <= int(o.id) <= last and o.failed]
    reason = f"failed: {', '.join(failed)}" if failed else ""
    return Outcome("", "", "FAIL" if failed else "PASS", reason)


# --------------------------------------------------------------------------- #
# Suites: subprocesses over repository-local tools
# --------------------------------------------------------------------------- #


def tool(name: str) -> str | None:
    return shutil.which(name)


def run_command(
    item_id: str,
    description: str,
    argv: Sequence[str],
    *,
    cwd: Path = REPO_ROOT,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
) -> Outcome:
    """Run one tool invocation, streaming its output; PASS on exit 0."""
    executable = tool(argv[0])
    if executable is None:
        return report(Outcome(item_id, description, "FAIL", f"`{argv[0]}` not on PATH"))
    where = "" if cwd == REPO_ROOT else f" (in {cwd.relative_to(REPO_ROOT).as_posix()}/)"
    print(f"\n$ {' '.join(argv)}{where}", flush=True)
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv over PATH, no shell  # nosec B603
            [executable, *argv[1:]],
            cwd=cwd,
            env=None if env is None else dict(env),
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        sys.stdout.flush()
        return report(Outcome(item_id, description, "FAIL", f"timed out after {timeout:.0f}s"))
    sys.stdout.flush()
    if completed.returncode == 0:
        return report(Outcome(item_id, description, "PASS"))
    return report(Outcome(item_id, description, "FAIL", f"exit code {completed.returncode}"))


def _configured_value(variable: str) -> str | None:
    """The value of ``variable`` from the environment or the local .env, or None.

    The value is used only to build a subprocess environment; it is never
    printed.
    """
    if value := os.environ.get(variable):
        return value
    env_file = _path(".env")
    if os.environ.get("JUDGEMETRICS_ENV", "local") == "local" and env_file.is_file():
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            match = re.match(rf"\s*{variable}\s*=\s*(\S.*)$", raw)
            if match is not None:
                return match.group(1).split(" #", 1)[0].strip().strip("\"'") or None
    return None


def _configured(variable: str) -> str | None:
    """Where ``variable`` is set from ("environment", ".env"), or None."""
    if os.environ.get(variable):
        return "environment"
    return ".env" if _configured_value(variable) is not None else None


def database_configured() -> str | None:
    """Where the database suites' URL comes from, or None.

    The scratch test database (`JUDGEMETRICS_TEST_DATABASE_URL`) is
    preferred; the configured database is the fallback the root conftest
    warns about, and here the caveat is printed once per suite.
    """
    if (source := _configured("JUDGEMETRICS_TEST_DATABASE_URL")) is not None:
        return f"JUDGEMETRICS_TEST_DATABASE_URL from {source}"
    if (source := _configured("JUDGEMETRICS_DATABASE_URL")) is not None:
        return (
            f"JUDGEMETRICS_DATABASE_URL from {source}; JUDGEMETRICS_TEST_DATABASE_URL unset, so "
            "the suite runs on the configured database, where the golden fixture purges the "
            "synthetic source (run `uv run poe seed` afterwards)"
        )
    return None


def pytest_suite(
    item_id: str, description: str, *targets: str, env: Mapping[str, str] | None = None
) -> Outcome:
    return run_command(item_id, description, ["uv", "run", "pytest", *targets], env=env)


def integration_suite(item_id: str, description: str, *targets: str) -> Outcome:
    source = database_configured()
    if source is None:
        return report(
            Outcome(
                item_id,
                description,
                "SKIP",
                "no database: set JUDGEMETRICS_TEST_DATABASE_URL (uv run poe up creates "
                "judgemetrics_test) or JUDGEMETRICS_DATABASE_URL",
            )
        )
    print(f"(database: {source})", flush=True)
    return pytest_suite(item_id, description, *targets)


def py_suites() -> list[Outcome]:
    heading("Python suites (--py)")
    return [
        run_command("py.lint", "uv run poe lint", ["uv", "run", "poe", "lint"]),
        run_command("py.fmt", "uv run poe fmt-check", ["uv", "run", "poe", "fmt-check"]),
        run_command("py.types", "uv run poe typecheck", ["uv", "run", "poe", "typecheck"]),
        pytest_suite("py.unit", 'uv run pytest -m "not integration"', "-m", "not integration"),
        integration_suite("py.integration", "uv run pytest -m integration", "-m", "integration"),
        integration_suite("py.property", "uv run pytest -m property", "-m", "property"),
        integration_suite("py.golden", "uv run pytest -m golden", "-m", "golden"),
    ]


def pnpm(item_id: str, script: str, *args: str) -> Outcome:
    """``pnpm <script>`` run inside web/ (equivalent to ``pnpm --dir web``).

    The working directory matters: corepack reads the ``packageManager``
    pin from the package.json of the directory it is invoked in, so
    ``pnpm --dir web`` from the repository root would fetch the latest
    pnpm and then refuse to run against web/'s pinned version.
    """
    argv = ["pnpm", script, *args]
    return run_command(item_id, f"pnpm --dir web {' '.join(argv[1:])}", argv, cwd=WEB_DIR)


def node_suites() -> list[Outcome]:
    heading("Web suites (--node)")
    # The build precedes the tests, as in CI: the Vitest bundle scan needs a
    # production build to inspect.
    return [
        pnpm("node.lint", "lint"),
        pnpm("node.types", "typecheck"),
        pnpm("node.build", "build"),
        pnpm("node.test", "test"),
    ]


def reachable(url: str) -> bool:
    try:
        # The caller has already required an http(s) scheme.
        with urllib.request.urlopen(url, timeout=5) as response:  # noqa: S310 # nosec B310
            return 200 <= int(response.status) < 400
    except (urllib.error.URLError, OSError, ValueError):
        return False


def service_bases() -> tuple[str, str] | str:
    """The API and web base URLs, or the reason they are unusable."""
    api = os.environ.get("NEXT_PUBLIC_API_BASE_URL", "http://localhost:8000").rstrip("/")
    web = os.environ.get("PLAYWRIGHT_BASE_URL", "http://localhost:3000").rstrip("/")
    for base in (api, web):
        if not base.startswith(("http://", "https://")):
            return f"not an http(s) URL: {base}"
    return api, web


def e2e_suite() -> Outcome:
    heading("Playwright (--e2e)")
    description = "pnpm --dir web e2e (smoke, metrics, first milestone, adjusted)"
    bases = service_bases()
    if isinstance(bases, str):
        return report(Outcome("e2e", description, "FAIL", bases))
    api, web = bases
    if not reachable(f"{api}/api/v1/ready"):
        return report(
            Outcome(
                "e2e",
                description,
                "SKIP",
                f"API not ready at {api}/api/v1/ready (start it: uv run poe dev-api; the "
                "database needs the demo seed and computed metrics: uv run poe bootstrap)",
            )
        )
    if not reachable(f"{web}/methodology"):
        return report(
            Outcome(
                "e2e",
                description,
                "SKIP",
                f"web app not serving {web}/methodology (start it: uv run poe dev-web)",
            )
        )
    # The first-milestone corrections test submits one request per run and
    # the local API allows five an hour per client address: a sixth --e2e
    # run within the hour sees a 429 on that one test. That is the limiter
    # (JUDGEMETRICS_ENV=local), not a failure of the page; CI runs with the
    # limiter off under JUDGEMETRICS_ENV=test.
    print(
        "(note: more than five --e2e runs an hour against a local API make the corrections "
        "test answer 429 — the rate limiter, not the page)",
        flush=True,
    )
    outcome = pnpm("e2e", "e2e")
    return Outcome("e2e", description, outcome.status, outcome.reason)


def secret_scan_batches() -> list[list[str]]:
    """Tracked files for detect-secrets-hook, batched under the argv budget."""
    batches: list[list[str]] = [[]]
    size = 0
    for relative in _git_ls_files():
        if relative in SECRET_SCAN_EXCLUDES or not _path(relative).is_file():
            continue
        if size + len(relative) + 1 > ARGV_BUDGET:
            batches.append([])
            size = 0
        batches[-1].append(relative)
        size += len(relative) + 1
    return [batch for batch in batches if batch]


def secret_scan() -> Outcome:
    """The pre-commit secret scan over every tracked file, against the baseline.

    ``detect-secrets scan --baseline`` rewrites the baseline and exits 0 even
    when it finds something new; ``detect-secrets-hook`` is the fail-closed
    form the pre-commit gate runs, so it is the one used here.
    """
    description = "detect-secrets-hook --baseline .secrets.baseline (all tracked files)"
    uv = tool("uv")
    if uv is None:
        return report(Outcome("sec.secrets", description, "FAIL", "`uv` not on PATH"))
    try:
        batches = secret_scan_batches()
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        return report(Outcome("sec.secrets", description, "FAIL", f"git ls-files failed: {exc}"))
    total = sum(map(len, batches))
    print(f"\n$ uv run detect-secrets-hook --baseline .secrets.baseline <{total} files>")
    for batch in batches:
        completed = subprocess.run(  # noqa: S603 - fixed argv over PATH, no shell  # nosec B603
            [uv, "run", "detect-secrets-hook", "--baseline", ".secrets.baseline", *batch],
            cwd=REPO_ROOT,
            check=False,
        )
        if completed.returncode != 0:
            return report(Outcome("sec.secrets", description, "FAIL", "potential secret found"))
    return report(Outcome("sec.secrets", description, "PASS"))


def security_suites() -> list[Outcome]:
    heading("Security gate (--security)")
    return [
        secret_scan(),
        run_command(
            "sec.sast",
            "bandit -c pyproject.toml -r src alembic scripts",
            [
                "uv",
                "run",
                "bandit",
                "-c",
                "pyproject.toml",
                "-r",
                "src",
                "alembic",
                "scripts",
                "-q",
            ],
        ),
        run_command(
            "sec.pip-audit",
            "pip-audit --strict over uv.lock (scripts/audit_deps.py)",
            ["uv", "run", "python", "scripts/audit_deps.py"],
        ),
        pnpm("sec.pnpm-audit", "audit", "--audit-level=high"),
    ]


# --------------------------------------------------------------------------- #
# --post: the milestone setup, the probes, the V1-V6 matrix, and the PR checks
# --------------------------------------------------------------------------- #


def probe_environment() -> tuple[dict[str, str], str]:
    """The subprocess environment the writing probes run in, and where it points.

    With JUDGEMETRICS_TEST_DATABASE_URL configured, the three role URLs are
    pointed at the scratch database and JUDGEMETRICS_SNAPSHOT_DIR at
    `SCRATCH_SNAPSHOT_DIR` (Phase 3 Step 5's safe shape: the live database
    and its snapshots are untouched). The directory persists because the
    scratch database's observations cite their snapshots, and its models
    their artifacts, by path; a temporary one would leave a later `metrics
    verify` or `models verify` there unable to open them. Snapshots and
    artifacts are content-addressed and never overwritten, so reuse is
    safe. Otherwise the configured database is used.
    """
    env = dict(os.environ)
    test_url = _configured_value("JUDGEMETRICS_TEST_DATABASE_URL")
    if test_url is None:
        return env, "the configured database (JUDGEMETRICS_TEST_DATABASE_URL unset)"
    for variable in ROLE_URL_VARIABLES:
        env[variable] = test_url
    env["JUDGEMETRICS_SNAPSHOT_DIR"] = str(_path(SCRATCH_SNAPSHOT_DIR))
    return env, f"the scratch test database, snapshots under {SCRATCH_SNAPSHOT_DIR}/"


def probe_dataset() -> str:
    """The synthetic dataset `uv run poe seed` writes, relative to the repository."""
    return _configured_value("JUDGEMETRICS_SYNTHETIC_DIR") or DEFAULT_SYNTHETIC_DIR


def _utf8(env: Mapping[str, str]) -> dict[str, str]:
    """``env`` with the child's stdio forced to UTF-8.

    A captured child writes its stdout in the locale encoding (cp1252 on
    Windows), so a CLI line with an em dash would not decode as UTF-8.
    """
    return {**env, "PYTHONIOENCODING": "utf-8"}


def _json_from(stdout: str) -> object | None:
    """The JSON document a CLI printed last on stdout (log lines may precede it)."""
    lines = stdout.splitlines()
    for start in range(len(lines) - 1, -1, -1):
        if lines[start].startswith(("{", "[")):
            try:
                document: object = json.loads("\n".join(lines[start:]))
            except json.JSONDecodeError:
                continue
            return document
    return None


def _run_json(
    argv: Sequence[str], env: Mapping[str, str], timeout: float, *, ok_codes: Sequence[int] = (0,)
) -> tuple[object | None, str, int | None]:
    """Run ``argv`` capturing stdout; the parsed JSON, a failure reason, and the exit code."""
    executable = tool(argv[0])
    if executable is None:
        return None, f"`{argv[0]}` not on PATH", None
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv over PATH, no shell  # nosec B603
            [executable, *argv[1:]],
            cwd=REPO_ROOT,
            env=_utf8(env),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return None, f"timed out after {timeout:.0f}s", None
    if completed.returncode not in ok_codes:
        return None, f"exit code {completed.returncode}", completed.returncode
    document = _json_from(completed.stdout)
    reason = "" if document is not None else "printed no JSON"
    return document, reason, completed.returncode


def _counts(env: Mapping[str, str]) -> dict[str, int] | str:
    """Row counts of the probe tables, or the reason they could not be read."""
    document, reason, _ = _run_json(
        ["uv", "run", "python", "-c", COUNT_SNIPPET, *SEED_PROBE_TABLES], env, 120
    )
    if not isinstance(document, dict):
        return f"count query failed ({reason or 'not an object'})"
    return {str(name): int(count) for name, count in document.items()}


def docker_available() -> str | None:
    """None when the Docker daemon answers, otherwise the reason it does not."""
    docker = tool("docker")
    if docker is None:
        return "docker not on PATH"
    try:
        completed = subprocess.run(  # noqa: S603 - fixed argv, no shell  # nosec B603
            [docker, "info", "--format", "{{.ServerVersion}}"],
            cwd=REPO_ROOT,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return "docker info timed out"
    return None if completed.returncode == 0 else "the Docker daemon is not running"


def milestone_setup(env: Mapping[str, str]) -> list[Outcome]:
    """First-milestone items 1-5 as subprocess steps, then the bootstrap rerun."""
    heading("First milestone, items 1-5, and the bootstrap rerun")
    outcomes = [
        run_command(
            "M1",
            "item 1: the project is checked out (git rev-parse --show-toplevel)",
            ["git", "rev-parse", "--show-toplevel"],
        ),
        run_command("M2", "item 2: uv sync", ["uv", "sync"], timeout=SEED_TIMEOUT),
    ]
    if (reason := docker_available()) is not None:
        for item_id, description in (
            ("M3", "item 3: uv run poe up"),
            ("M4", "item 4: uv run poe migrate"),
            ("M5", "item 5: uv run poe seed"),
            ("M.bootstrap", "uv run poe bootstrap (idempotent rerun)"),
        ):
            outcomes.append(report(Outcome(item_id, description, "SKIP", reason)))
        return outcomes
    outcomes.append(
        run_command("M3", "item 3: uv run poe up", ["uv", "run", "poe", "up"], timeout=600)
    )
    outcomes.append(
        run_command(
            "M4",
            "item 4: uv run poe migrate",
            ["uv", "run", "poe", "migrate"],
            env=env,
            timeout=600,
        )
    )
    if _configured("JUDGEMETRICS_IDENTIFIER_PEPPER") is None:
        outcomes.append(
            report(
                Outcome(
                    "M5",
                    "item 5: uv run poe seed",
                    "SKIP",
                    "JUDGEMETRICS_IDENTIFIER_PEPPER is not configured",
                )
            )
        )
    else:
        outcomes.append(
            run_command(
                "M5",
                "item 5: uv run poe seed",
                ["uv", "run", "poe", "seed"],
                env=env,
                timeout=SEED_TIMEOUT,
            )
        )
    outcomes.append(
        run_command(
            "M.bootstrap",
            "uv run poe bootstrap (idempotent rerun)",
            ["uv", "run", "poe", "bootstrap"],
            env=env,
            timeout=BOOTSTRAP_TIMEOUT,
        )
    )
    return outcomes


def seed_probe(env: Mapping[str, str]) -> Outcome:
    """Canonical, observation, and model row counts are unchanged by a second seed."""
    heading("Seed idempotency probe")
    description = "row counts unchanged after a second `judgemetrics seed`"

    def skip(reason: str) -> Outcome:
        return report(Outcome("probe.seed", description, "SKIP", reason))

    if _configured("JUDGEMETRICS_IDENTIFIER_PEPPER") is None:
        return skip("JUDGEMETRICS_IDENTIFIER_PEPPER is not configured")
    before = _counts(env)
    if isinstance(before, str):
        return skip(before)
    if before.get("court_case", 0) == 0:
        return skip("the database holds no cases (run `uv run poe bootstrap` first)")
    print("before: " + ", ".join(f"{name}={count}" for name, count in before.items()))
    seed = run_command(
        "probe.seed.run",
        "uv run judgemetrics seed",
        ["uv", "run", "judgemetrics", "seed"],
        env=env,
        timeout=SEED_TIMEOUT,
    )
    if seed.failed:
        return report(Outcome("probe.seed", description, "FAIL", "the second seed did not succeed"))
    after = _counts(env)
    if isinstance(after, str):
        return report(Outcome("probe.seed", description, "FAIL", after))
    print("after:  " + ", ".join(f"{name}={count}" for name, count in after.items()))
    changed = [
        f"{name} {before[name]} -> {after.get(name)}"
        for name in before
        if after.get(name) != before[name]
    ]
    if changed:
        return report(Outcome("probe.seed", description, "FAIL", "; ".join(changed)))
    return report(Outcome("probe.seed", description, "PASS"))


def compute_probe(env: Mapping[str, str]) -> Outcome:
    """A second `metrics compute` over unchanged data fits, publishes, and supersedes nothing."""
    heading("Compute idempotency probe (V3.4)")
    description = "a second `metrics compute` fits no model and publishes zero"
    argv = ["uv", "run", "judgemetrics", "metrics", "compute", "--json"]
    results: list[dict[str, object]] = []
    for attempt in ("first", "second"):
        print(f"\n$ {' '.join(argv)}  ({attempt})", flush=True)
        document, reason, _ = _run_json(argv, env, SEED_TIMEOUT)
        if not isinstance(document, dict):
            return report(Outcome("probe.compute", description, "FAIL", reason or "not an object"))
        print(
            f"snapshot={document.get('snapshot')} subjects={document.get('subjects')} "
            f"models_fitted={document.get('models_fitted')} "
            f"models_read={document.get('models_read')} "
            f"observations={document.get('observations')} "
            f"superseded={document.get('superseded')} "
            f"subjects_published={document.get('subjects_published')} "
            f"subjects_unchanged={document.get('subjects_unchanged')}",
            flush=True,
        )
        results.append(document)
    second = results[-1]
    if not second.get("subjects"):
        return report(
            Outcome("probe.compute", description, "SKIP", "no subjects computed (empty database)")
        )
    moved = [
        key
        for key in ("models_fitted", "observations", "superseded", "subjects_published")
        if second.get(key)
    ]
    if moved:
        detail = ", ".join(f"{key}={second[key]}" for key in moved)
        return report(Outcome("probe.compute", description, "FAIL", detail))
    if not second.get("models_read"):
        return report(
            Outcome("probe.compute", description, "FAIL", "the compute read no fitted model")
        )
    return report(Outcome("probe.compute", description, "PASS"))


def verify_probe(env: Mapping[str, str]) -> Outcome:
    heading("metrics verify (V3.4)")
    return run_command(
        "probe.verify",
        "uv run judgemetrics metrics verify exits 0",
        ["uv", "run", "judgemetrics", "metrics", "verify"],
        env=env,
        timeout=SEED_TIMEOUT,
    )


def refit_probe(env: Mapping[str, str]) -> Outcome:
    heading("models verify --refit (V2.5)")
    return run_command(
        "probe.refit",
        "uv run judgemetrics models verify --refit exits 0",
        ["uv", "run", "judgemetrics", "models", "verify", "--refit"],
        env=env,
        timeout=SEED_TIMEOUT,
    )


def validation_probes(env: Mapping[str, str]) -> tuple[Outcome, Outcome]:
    """`validation report --check` and `validation recovery` over the probe's dataset."""
    heading("validation report --check and validation recovery (V4.3)")
    dataset = probe_dataset()
    report_check = run_command(
        "probe.validation",
        f"uv run judgemetrics validation report --check --truth {dataset} exits 0",
        ["uv", "run", "judgemetrics", "validation", "report", "--check", "--truth", dataset],
        env=_utf8(env),
        timeout=SEED_TIMEOUT,
    )
    description = f"uv run judgemetrics validation recovery --truth {dataset} meets the tolerances"
    if not _path(dataset).is_dir():
        return report_check, report(
            Outcome("probe.recovery", description, "SKIP", f"{dataset} does not exist")
        )
    print(f"\n$ uv run judgemetrics validation recovery --truth {dataset} --json", flush=True)
    document, reason, code = _run_json(
        ["uv", "run", "judgemetrics", "validation", "recovery", "--truth", dataset, "--json"],
        env,
        SEED_TIMEOUT,
        ok_codes=(0, 1),
    )
    if not isinstance(document, dict):
        return report_check, report(Outcome("probe.recovery", description, "FAIL", reason))
    fits = document.get("fits")
    for fit in fits if isinstance(fits, list) else []:
        if isinstance(fit, dict):
            print(
                f"  {fit.get('target')} window={fit.get('window_days')} "
                f"judges={fit.get('judges')} spearman={fit.get('spearman')} "
                f"coverage={fit.get('coverage')} passed={fit.get('passed')}",
                flush=True,
            )
    if code != 0 or document.get("passed") is not True:
        return report_check, report(
            Outcome("probe.recovery", description, "FAIL", "a figure is below its tolerance")
        )
    return report_check, report(Outcome("probe.recovery", description, "PASS"))


def trace_probe(env: Mapping[str, str]) -> Outcome:
    """`provenance trace` of one current adjusted observation names its model, complete."""
    heading("Adjusted provenance trace probe (V3.5)")
    description = "judgemetrics provenance trace <one current adjusted observation> is complete"
    document, reason, _ = _run_json(["uv", "run", "python", "-c", OBSERVATION_SNIPPET], env, 120)
    if not isinstance(document, dict):
        return report(Outcome("probe.trace", description, "FAIL", f"id query failed ({reason})"))
    observation_id = document.get("id")
    if not isinstance(observation_id, str):
        return report(
            Outcome("probe.trace", description, "SKIP", "no current adjusted observation")
        )
    if re.fullmatch(r"[0-9a-f-]{36}", observation_id) is None:
        return report(Outcome("probe.trace", description, "FAIL", "the id is not a UUID"))
    uv = tool("uv")
    if uv is None:
        return report(Outcome("probe.trace", description, "FAIL", "`uv` not on PATH"))
    argv = [uv, "run", "judgemetrics", "provenance", "trace", observation_id]
    print(f"\n$ uv run judgemetrics provenance trace {observation_id}", flush=True)
    # The CLI's text output carries ids, hashes, counts, and artifact URIs:
    # no person material by Phase 3 Step 3's contract, so it is printed as it is.
    completed = subprocess.run(  # noqa: S603 - fixed argv over PATH, no shell  # nosec B603
        argv,
        cwd=REPO_ROOT,
        env=_utf8(env),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        check=False,
    )
    print(completed.stdout, end="", flush=True)
    if completed.returncode != 0:
        return report(
            Outcome("probe.trace", description, "FAIL", f"exit code {completed.returncode}")
        )
    if re.search(r"^outcome model [0-9a-f]{64}$", completed.stdout, re.MULTILINE) is None:
        return report(Outcome("probe.trace", description, "FAIL", "the trace names no model"))
    if re.search(r"^complete: yes$", completed.stdout, re.MULTILINE) is None:
        return report(Outcome("probe.trace", description, "FAIL", "the trace is not complete"))
    return report(Outcome("probe.trace", description, "PASS"))


def milestone_services() -> list[Outcome]:
    """First-milestone items 6 and 7: the API answers /ready and the web app serves /."""
    heading("First milestone, items 6-7")
    bases = service_bases()
    if isinstance(bases, str):
        return [
            report(Outcome(i, d, "FAIL", bases)) for i, d in (("M6", "item 6"), ("M7", "item 7"))
        ]
    api, web = bases
    outcomes = []
    for item_id, description, url, start in (
        (
            "M6",
            "item 6: the API answers /api/v1/ready",
            f"{api}/api/v1/ready",
            "uv run poe dev-api",
        ),
        ("M7", "item 7: the web app serves /", f"{web}/", "uv run poe dev-web (Windows: pnpm dev)"),
    ):
        if reachable(url):
            outcomes.append(report(Outcome(item_id, description, "PASS")))
        else:
            outcomes.append(
                report(Outcome(item_id, description, "SKIP", f"not reachable at {url} ({start})"))
            )
    return outcomes


def pr_checks() -> dict[str, str] | None:
    """Check name → bucket for the current branch's PR, or None when unavailable."""
    gh = tool("gh")
    if gh is None:
        print("gh not on PATH; PR checks unavailable", flush=True)
        return None
    auth = subprocess.run(  # noqa: S603 - fixed argv, no shell  # nosec B603
        [gh, "auth", "status"], cwd=REPO_ROOT, capture_output=True, check=False
    )
    if auth.returncode != 0:
        print("gh is not signed in; PR checks unavailable", flush=True)
        return None
    checks = subprocess.run(  # noqa: S603 - fixed argv, no shell  # nosec B603
        [gh, "pr", "checks", "--json", "name,bucket,workflow"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if not checks.stdout.strip():
        print("no pull request for the current branch; PR checks unavailable", flush=True)
        return None
    try:
        rows = json.loads(checks.stdout)
    except json.JSONDecodeError:
        print("gh pr checks returned no JSON; PR checks unavailable", flush=True)
        return None
    result = {str(row["name"]): str(row["bucket"]) for row in rows}
    heading("gh pr checks (current branch)")
    for name, bucket in sorted(result.items()):
        print(f"  {bucket:<8} {name}")
    return result


def check_bucket(checks: dict[str, str] | None, prefix: str) -> tuple[Status, str]:
    if checks is None:
        return "SKIP", "PR checks unavailable (gh not signed in or no PR for this branch)"
    matches = {name: bucket for name, bucket in checks.items() if name.startswith(prefix)}
    if not matches:
        return "FAIL", f"no check named `{prefix}…` on the PR"
    not_green = [f"{name}: {bucket}" for name, bucket in matches.items() if bucket != "pass"]
    return ("FAIL", "; ".join(not_green)) if not_green else ("PASS", "")


def suites_outcome(outcomes: Sequence[Outcome]) -> tuple[Status, str]:
    failed = [o.id for o in outcomes if o.failed]
    if failed:
        return "FAIL", f"failed: {', '.join(failed)}"
    skipped = [o.id for o in outcomes if o.status == "SKIP"]
    if skipped and len(skipped) == len(outcomes):
        return "SKIP", "; ".join(o.reason for o in outcomes if o.status == "SKIP")
    if skipped:
        return "PASS", f"skipped: {', '.join(skipped)}"
    return "PASS", ""


def e2e_row(e2e: Outcome, checks: dict[str, str] | None) -> tuple[Status, str]:
    """The local Playwright run, or the PR's `e2e` CI job when the run skipped."""
    if e2e.status != "SKIP" or checks is None:
        return e2e.status, e2e.reason
    status, reason = check_bucket(checks, "e2e")
    return status, reason or "local run skipped; the PR's `e2e` job is green"


def post_matrix(statics: Sequence[Outcome]) -> list[Outcome]:
    """Run every suite and probe the V-checks need once, then report V1.1-V6.4.

    The writing probes run first, inside `probe_environment()`, so the
    scratch database holds a bootstrapped dataset while they read it; the
    Python suites (which purge the synthetic source from the scratch
    database through the golden fixture) and item 17 run last.
    """
    checks = pr_checks()
    env, where = probe_environment()
    print(f"\n(probes write to {where})", flush=True)
    setup = milestone_setup(env)
    seed = seed_probe(env)
    compute = compute_probe(env)
    verified = verify_probe(env)
    refit = refit_probe(env)
    validation, recovery = validation_probes(env)
    traced = trace_probe(env)
    services = milestone_services()
    e2e = e2e_suite()
    node = node_suites()
    security = security_suites()
    ci_profile = {**os.environ, "HYPOTHESIS_PROFILE": "ci"}
    heading("Suites for V1-V5")
    effects_unit = pytest_suite(
        "V1.2",
        "test_synthetic_effects, test_effects_invariants (ci), test_frame_invariants (ci), "
        "test_exposure_deferral",
        "tests/unit/test_synthetic_effects.py",
        "tests/property/test_effects_invariants.py",
        "tests/property/test_frame_invariants.py",
        "tests/unit/test_exposure_deferral.py",
        env=ci_profile,
    )
    restricted = integration_suite(
        "V1.3",
        "test_restricted_schema, test_migrations, test_synthetic_ingest",
        "tests/integration/test_restricted_schema.py",
        "tests/integration/test_migrations.py",
        "tests/integration/test_synthetic_ingest.py",
    )
    golden = integration_suite(
        "V1.4",
        "test_golden_fixture, test_golden_metrics, test_public_contract",
        "tests/golden/test_golden_fixture.py",
        "tests/golden/test_golden_metrics.py",
        "tests/golden/test_public_contract.py",
    )
    model_unit = pytest_suite(
        "V2.2",
        "test_outcome_model_spec, test_logistic, test_adjustment_features, "
        "test_model_diagnostics, test_model_artifacts",
        "tests/unit/test_outcome_model_spec.py",
        "tests/unit/test_logistic.py",
        "tests/unit/test_adjustment_features.py",
        "tests/unit/test_model_diagnostics.py",
        "tests/unit/test_model_artifacts.py",
    )
    leakage = pytest_suite(
        "V2.3",
        "test_feature_leakage (HYPOTHESIS_PROFILE=ci)",
        "tests/property/test_feature_leakage.py",
        env=ci_profile,
    )
    models = integration_suite(
        "V2.4", "test_outcome_models", "tests/integration/test_outcome_models.py"
    )
    estimator = integration_suite(
        "V3.2",
        "test_pooling, test_bootstrap, test_api_adjusted",
        "tests/unit/test_pooling.py",
        "tests/unit/test_bootstrap.py",
        "tests/integration/test_api_adjusted.py",
    )
    golden_adjusted = integration_suite(
        "V3.3",
        "test_golden_adjusted, test_golden_recovery",
        "tests/golden/test_golden_adjusted.py",
        "tests/golden/test_golden_recovery.py",
    )
    validation_suite = integration_suite(
        "V4.2",
        "test_validation_report, test_subgroup_calibration, test_fairness_analysis, "
        "test_restricted_readers, test_methodology_render",
        "tests/unit/test_validation_report.py",
        "tests/unit/test_subgroup_calibration.py",
        "tests/integration/test_fairness_analysis.py",
        "tests/unit/test_restricted_readers.py",
        "tests/unit/test_methodology_render.py",
    )
    api = integration_suite(
        "V5.2",
        "test_api_adjusted, test_schemas_metrics, test_query_counts, test_openapi, "
        "test_public_contract",
        "tests/integration/test_api_adjusted.py",
        "tests/unit/test_schemas_metrics.py",
        "tests/integration/test_query_counts.py",
        "tests/unit/test_openapi.py",
        "tests/golden/test_public_contract.py",
    )
    heading("First milestone, item 17")
    check_all = run_command(
        "M17",
        "item 17: uv run poe check",
        ["uv", "run", "poe", "check"],
        timeout=CHECK_TIMEOUT,
    )
    security_status, security_reason = suites_outcome(security)
    all_static = statics_in_range(statics, 1, len(STATIC_CHECKS))
    on_ci_linux = sys.platform.startswith("linux") and os.environ.get("CI") == "true"

    heading("Post-implementation verification (V1-V6)")
    rows: list[tuple[str, str, Status, str]] = []

    def static_row(vid: str, first: int, last: int) -> None:
        o = statics_in_range(statics, first, last)
        rows.append((vid, f"Static checks {first}-{last} all PASS", o.status, o.reason))

    def suite_row(vid: str, description: str, outcome: Outcome) -> None:
        rows.append((vid, description, outcome.status, outcome.reason))

    static_row("V1.1", 1, 11)
    suite_row("V1.2", "effects, frame, and exposure-deferral suites pass", effects_unit)
    suite_row("V1.3", "restricted schema, migrations through 0010, synthetic ingest", restricted)
    suite_row("V1.4", "golden fixture 3/3, golden metrics, public contract", golden)
    static_row("V2.1", 12, 20)
    suite_row("V2.2", "the Step 2 unit tests pass", model_unit)
    suite_row("V2.3", "test_feature_leakage.py passes under the ci profile", leakage)
    suite_row("V2.4", "test_outcome_models.py passes", models)
    suite_row("V2.5", "models verify --refit exits 0 on the scratch database", refit)
    static_row("V3.1", 21, 29)
    suite_row("V3.2", "test_pooling, test_bootstrap, test_api_adjusted pass", estimator)
    suite_row("V3.3", "test_golden_adjusted and test_golden_recovery pass", golden_adjusted)
    rows.append(
        (
            "V3.4",
            "a second compute fits and publishes nothing; metrics verify exits 0",
            *suites_outcome((compute, verified)),
        )
    )
    suite_row("V3.5", "provenance trace of an adjusted observation names its model", traced)
    static_row("V4.1", 30, 37)
    suite_row("V4.2", "validation, calibration, fairness, readers, methodology", validation_suite)
    rows.append(
        (
            "V4.3",
            "validation report --check exits 0; validation recovery meets the tolerances",
            *suites_outcome((validation, recovery)),
        )
    )
    static_row("V5.1", 38, 45)
    suite_row("V5.2", "adjusted API, schemas, query counts, OpenAPI, public contract", api)
    rows.append(("V5.3", "pnpm lint, typecheck, build, test pass", *suites_outcome(node)))
    rows.append(("V5.4", "adjusted.spec.ts and the Playwright suites pass", *e2e_row(e2e, checks)))
    if on_ci_linux:
        rows.append(
            (
                "V6.1",
                f"verify_phase{PHASE}.py --fast exits 0 on Ubuntu CI",
                all_static.status,
                all_static.reason,
            )
        )
    elif checks is not None:
        rows.append(
            (
                "V6.1",
                f"verify_phase{PHASE}.py --fast exits 0 on Ubuntu CI",
                *check_bucket(checks, f"phase-verify ({PHASE})"),
            )
        )
    else:
        status: Status = "SKIP" if not all_static.failed else "FAIL"
        reason = (
            all_static.reason
            or "not on Ubuntu CI and no PR checks to read; static checks pass locally"
        )
        rows.append(("V6.1", f"verify_phase{PHASE}.py --fast exits 0 on Ubuntu CI", status, reason))
    matrix = next(o for o in statics if o.id == "49")
    rows.append(
        ("V6.2", f'phase-verify.yml matrix includes "{PHASE}"', matrix.status, matrix.reason)
    )
    rows.append(
        (
            "V6.3",
            f"all {len(STATIC_CHECKS)} static checks pass",
            all_static.status,
            all_static.reason,
        )
    )
    rows.append(
        ("V6.4", f"verify_phase{PHASE}.py --security exits 0", security_status, security_reason)
    )
    # The first-milestone items carry no V id in Phase 4's matrix; one row
    # keeps their failures in the summary, as Phase 3's V5.3 did.
    rows.append(
        (
            "M",
            "milestone items 1-7 and 17, the bootstrap rerun, and the seed probe pass",
            *suites_outcome((*setup, seed, *services, check_all)),
        )
    )
    return [
        report(Outcome(vid, description, status, reason))
        for vid, description, status, reason in rows
    ]


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog=f"verify_phase{PHASE}.py",
        description=f"Phase {int(PHASE)} verification (default: --fast plus --py).",
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--fast", action="store_true", help="static checks only (CI-safe)")
    modes.add_argument("--py", action="store_true", help="static + ruff, mypy, pytest")
    modes.add_argument(
        "--node", action="store_true", help="static + pnpm lint/typecheck/build/test"
    )
    modes.add_argument("--e2e", action="store_true", help="static + Playwright")
    modes.add_argument("--security", action="store_true", help="secret scan + SAST + audits")
    modes.add_argument("--all", action="store_true", help="static + py + node + e2e + security")
    modes.add_argument(
        "--post",
        action="store_true",
        help="static + V1-V6 matrix + milestone items + probes + gh pr checks",
    )
    return parser.parse_args(argv)


def mode_name(args: argparse.Namespace) -> str:
    for name in ("fast", "py", "node", "e2e", "security", "all", "post"):
        if getattr(args, name):
            return name
    return "default (fast + py)"


def summary(mode: str, outcomes: Sequence[Outcome], elapsed: float) -> int:
    passed = sum(o.status == "PASS" for o in outcomes)
    failed = sum(o.status == "FAIL" for o in outcomes)
    skipped = sum(o.status == "SKIP" for o in outcomes)
    heading("Summary")
    print(f"  {'mode':<8} {mode}")
    print(f"  {'passed':<8} {passed}")
    print(f"  {'failed':<8} {failed}")
    print(f"  {'skipped':<8} {skipped}")
    print(f"  {'total':<8} {len(outcomes)}")
    print(f"  {'elapsed':<8} {elapsed:.1f}s")
    if failed:
        print(f"\nFAILED: {', '.join(o.id for o in outcomes if o.failed)}", flush=True)
        return 1
    print("\nOK", flush=True)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args(argv)
    mode = mode_name(args)
    started = time.perf_counter()
    outcomes: list[Outcome] = []
    if mode == "security":
        outcomes.extend(security_suites())
    else:
        statics = run_static_checks()
        outcomes.extend(statics)
        # The Playwright suite precedes the Python suites in --all: without
        # the scratch test database the golden fixture purges the synthetic
        # source the Playwright flows need (verify_phase02 post_matrix).
        if mode in ("e2e", "all"):
            outcomes.append(e2e_suite())
        if mode in ("node", "all"):
            outcomes.extend(node_suites())
        if mode in ("py", "default (fast + py)", "all"):
            outcomes.extend(py_suites())
        if mode == "all":
            outcomes.extend(security_suites())
        if mode == "post":
            outcomes.extend(post_matrix(statics))
    return summary(mode, outcomes, time.perf_counter() - started)


if __name__ == "__main__":
    raise SystemExit(main())
