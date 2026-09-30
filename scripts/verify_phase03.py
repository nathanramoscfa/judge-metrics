# scripts/verify_phase03.py
"""Phase 3 verification: static deliverable checks, tool suites, probes, and the V1-V6 matrix.

Modes are mutually exclusive; with no flag the script runs ``--fast`` plus
``--py``:

  --fast      the 49 static checks only (CI-safe on Ubuntu and Windows,
              well under 30 seconds: pathlib, re, json, hashlib, and
              ``git ls-files``; the registry is read with a minimal line
              reader, never a YAML library)
  --py        static + ruff, ruff format --check, mypy, the unit suite, and
              the integration, property, and golden suites when a database
              is configured (JUDGEMETRICS_TEST_DATABASE_URL preferred)
  --node      static + pnpm lint, typecheck, build, test in web/
  --e2e       static + the Playwright suites (skips with a reason when the
              API or the web app is not reachable)
  --security  the gate over the phase's surface: detect-secrets against the
              baseline, bandit over src, alembic, and scripts, pip-audit
              over uv.lock, pnpm audit
  --all       static + py + node + e2e + security
  --post      static + the V1-V6 matrix of docs/roadmap/phase03-roadmap.md:
              the first-milestone items 1-7 and 17 as subprocess steps, the
              bootstrap rerun, the seed and compute idempotency probes,
              ``metrics verify``, a ``provenance trace`` of one current
              observation, and ``gh pr checks`` for the current branch when
              gh is signed in

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
PHASE = "03"

Status = Literal["PASS", "FAIL", "SKIP"]
CheckFn = Callable[[], str | None]  # None on success, otherwise the failure reason

REGISTRY = "data/reference/metric_registry.yaml"
BRIEF = "docs/brief/judgemetrics-master-project-specification.xml"
# The slugs Step 1's requirement says the registry defines at least.
REQUIRED_SLUGS = (
    "eligible_cases",
    "eligible_defendants",
    "pretrial_decisions",
    "pretrial_released",
    "pretrial_detained",
    "pretrial_release_share",
    "statutory_release_count",
    "unknown_actor_pretrial_count",
    "failure_to_appear_rate",
    "new_case_rate",
    "new_charge_rate",
    "reconviction_rate",
    "release_violation_rate",
    "revocation_rate",
    "rearrest_rate",
    "failure_to_appear_survival",
    "new_case_survival",
    "reconviction_survival",
    "new_case_rate_after_disposition",
    "new_charge_rate_after_disposition",
    "reconviction_rate_after_disposition",
    "revocation_rate_after_disposition",
    "new_case_rate_after_sentence",
    "new_charge_rate_after_sentence",
    "reconviction_rate_after_sentence",
    "revocation_rate_after_sentence",
    "disposition_distribution",
    "judicial_dismissal_rate",
    "median_days_to_disposition",
    "sentence_count",
    "incarceration_days_median",
    "probation_days_median",
    "incarceration_days_median_by_offense_category",
)
BRIEF_WARNING_COUNT = 8
METRICS_STEP1_MODULES = (
    "__init__",
    "registry",
    "frame",
    "attribution",
    "index_events",
    "exposure",
    "windows",
    "censoring",
    "intervals",
    "methodology",
)
METRICS_STEP2_MODULES = ("snapshot", "compute", "suppression", "publish", "verify")
# Restricted person material no module under metrics/ (recursively) may name
# (check 9). `person_identifier` is allowed only inside snapshot.py's
# RESTRICTED_TABLES denylist and its docstring (the export's own guard names
# what it never reads); the others must not appear at all. Phase 4 Step 1
# added the restricted attributes and their table.
PERSON_COLUMNS = (
    "full_name",
    "date_of_birth",
    "public_person_key",
    "age_band",
    "synthetic_group",
    "party_attribute",
)
RESTRICTED_TABLE_READS = (
    re.compile(r'tables\[\s*"person_identifier"\s*\]'),
    re.compile(r'sa\.table\(\s*"person_identifier"'),
    re.compile(r"\bPersonIdentifier\b"),
    re.compile(r"\bFROM\s+person_identifier\b", re.IGNORECASE),
)
GOLDEN_DIR = "tests/fixtures/golden"
OPENAPI_PATHS = {
    "/api/v1/metrics",
    "/api/v1/judges/{judge_id}/metrics",
    "/api/v1/courts/{court_id}/metrics",
    "/api/v1/metrics/compare",
    "/api/v1/metrics/{observation_id}/provenance",
    "/api/v1/corrections",
}
SCHEMA_PERSON_FIELDS = ("person_id", "public_person_key", "full_name", "date_of_birth")
LOGGING_DENYLIST = ("correction_contact_key", "requester_contact", "contact", "reason")
QUERY_BUDGET_TOPICS = ("compare", "subject_metrics", "provenance", "corrections")
STEP4_WEB_FILES = (
    "web/components/metric-stat.tsx",
    "web/components/metric-panel.tsx",
    "web/components/cohort-selector.tsx",
    "web/lib/metrics.ts",
    "web/lib/coverage-cache.ts",
)
STEP5_WEB_FILES = (
    "web/app/corrections/page.tsx",
    "web/app/corrections/received/page.tsx",
    "web/app/api/corrections/route.ts",
    "web/components/correction-form.tsx",
)
BOOTSTRAP_SEQUENCE = ("up", "migrate", "ingest-fjc", "seed", "compute-metrics")
MILESTONE_ITEMS = 17
FIRST_MILESTONE_MIN_TESTS = 9
QA_SECTIONS = (
    "## Step 1",
    "## Step 2",
    "## Step 3",
    "## Step 4",
    "## Step 5",
    "## Step 6",
    "### Alarm exercise",
    "## Pre-ship items",
    "## Phase 4 carry-over checklist",
)
MODE_FLAGS = ("--fast", "--py", "--node", "--e2e", "--security", "--all", "--post")
PRE_COMMIT_HOOKS = ("detect-secrets", "bandit", "pip-audit")
SHA_PIN = re.compile(r"@[0-9a-f]{40}$")
# The security backstop (check 49): a PEM private-key header, an AWS access
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
# step 13 publishes metrics inside the seed's ingest.
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
# One current observation id, chosen at random, for the provenance probe.
OBSERVATION_SNIPPET = """
import json
import sqlalchemy as sa
from judgemetrics.config import get_settings
from judgemetrics.db.session import make_engine
engine = make_engine(get_settings().database_url)
observation = sa.table("metric_observation", sa.column("id"), sa.column("superseded_at"))
try:
    with engine.connect() as connection:
        found = connection.execute(
            sa.select(observation.c.id)
            .where(observation.c.superseded_at.is_(None))
            .order_by(sa.func.random())
            .limit(1)
        ).scalar_one_or_none()
finally:
    engine.dispose()
print(json.dumps({"id": None if found is None else str(found)}))
"""
# Wall-clock ceilings for the --post subprocesses. `uv run poe bootstrap` took
# 249 s from a clean database and 48 s on the rerun on the maintainer's
# machine (Phase 3 Step 5); the whole test suite takes minutes.
BOOTSTRAP_TIMEOUT = 900
SEED_TIMEOUT = 900
CHECK_TIMEOUT = 3_600
# The role URLs and the snapshot directory the --post probes override.
# Where the --post probes keep the scratch database's snapshots (git-ignored
# under data/snapshots/, apart from the live database's content-hash folders).
SCRATCH_SNAPSHOT_DIR = "data/snapshots/scratch-test-db"
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


# --------------------------------------------------------------------------- #
# Static checks 1-49
# --------------------------------------------------------------------------- #


def check_01() -> str | None:
    if (reason := _missing(REGISTRY)) is not None:
        return reason
    if (reason := _untracked(REGISTRY)) is not None:
        return reason
    if not _read(REGISTRY).startswith(f"# {REGISTRY}"):
        return f"{REGISTRY} lacks its path comment"
    if _registry_scalar("version") is None or not (_registry_scalar("version") or "").isdigit():
        return f"{REGISTRY} has no integer `version:`"
    if _registry_scalar("methodology_version") is None:
        return f"{REGISTRY} has no `methodology_version:`"
    if (count := len(_registry_limitations())) != BRIEF_WARNING_COUNT:
        return f"{REGISTRY} has {count} known_limitations, not {BRIEF_WARNING_COUNT}"
    slugs = _registry_slugs()
    if len(slugs) != len(set(slugs)):
        return f"{REGISTRY} repeats a slug"
    return _check_names(REQUIRED_SLUGS, set(slugs), f"{REGISTRY} slugs")


def check_02() -> str | None:
    return _missing(*(f"{PACKAGE}/metrics/{name}.py" for name in METRICS_STEP1_MODULES))


def check_03() -> str | None:
    relative = "alembic/versions/0005_metric_registry_and_snapshots.py"
    return _lacks_all(
        relative,
        (
            (r'^SNAPSHOT\s*=\s*"metric_snapshot"', 'SNAPSHOT = "metric_snapshot"'),
            (r'^MEMBER\s*=\s*"metric_observation_member"', 'MEMBER = "metric_observation_member"'),
            (r"op\.create_table\(\s*SNAPSHOT\b", "op.create_table(SNAPSHOT"),
            (r"op\.create_table\(\s*MEMBER\b", "op.create_table(MEMBER"),
            (r'add_column\(\s*SOURCE,\s*sa\.Column\("coverage_start"', "source.coverage_start"),
            (r'add_column\(\s*SOURCE,\s*sa\.Column\("coverage_end"', "source.coverage_end"),
            (
                r'add_column\(\s*SOURCE,\s*sa\.Column\("observable_outcomes"',
                "source.observable_outcomes",
            ),
            (r'^APP_ROLE\s*=\s*"judgemetrics_app"', "the APP_ROLE constant"),
            (
                r"GRANT [A-Z, ]+ ON TABLE \{table\} TO \{(?:APP|INGEST)_ROLE\}",
                "grants built from the role constants",
            ),
        ),
    )


def check_04() -> str | None:
    relative = "docs/METHODOLOGY.md"
    if (reason := _missing(relative, BRIEF)) is not None:
        return reason
    section = _markdown_section(relative, "Known limitations")
    if section is None:
        return f"{relative} has no `## Known limitations` section"
    warnings = _brief_warnings()
    if len(warnings) != BRIEF_WARNING_COUNT:
        return f"the brief yields {len(warnings)} warnings, not {BRIEF_WARNING_COUNT}"
    # The rendered list numbers and wraps each warning; compare the prose with
    # the markers removed and whitespace collapsed.
    body = _normalize(re.sub(r"^\s*\d+\.\s+", " ", section, flags=re.MULTILINE))
    absent = [str(i) for i, warning in enumerate(warnings, 1) if warning not in body]
    return f"{relative} lacks brief warning(s) {', '.join(absent)} verbatim" if absent else None


def check_05() -> str | None:
    if (reason := _missing(REGISTRY, BRIEF)) is not None:
        return reason
    registry, brief = _registry_limitations(), _brief_warnings()
    if len(brief) != BRIEF_WARNING_COUNT:
        return f"the brief yields {len(brief)} warnings, not {BRIEF_WARNING_COUNT}"
    differ = [
        str(i) for i, pair in enumerate(zip(registry, brief, strict=False), 1) if pair[0] != pair[1]
    ]
    if len(registry) != len(brief) or differ:
        return f"known_limitations differ from the brief at {', '.join(differ) or 'the count'}"
    return None


def check_06() -> str | None:
    files = ("tests/property/test_frame_invariants.py", "tests/unit/test_attribution.py")
    return _missing(*files) or _untracked(*files)


def check_07() -> str | None:
    return _lacks_all(
        f"{PACKAGE}/cli.py",
        (
            (r'add_typer\(methodology_app,\s*name="methodology"\)', "the `methodology` group"),
            (r'@methodology_app\.command\("render"\)', "`methodology render`"),
            (r'"--check"', "the `--check` option"),
        ),
    )


def check_08() -> str | None:
    return _lacks(
        "docs/ARCHITECTURE.md", r"^#+ Metrics engine\s*$", "a `Metrics engine` section"
    ) or _lacks_all(
        "docs/DATA_MODEL.md",
        (
            (r"\bmetric_snapshot\b", "`metric_snapshot`"),
            (r"\bmetric_observation_member\b", "`metric_observation_member`"),
        ),
    )


def check_09() -> str | None:
    root = _path(f"{PACKAGE}/metrics")
    modules = sorted(root.glob("**/*.py"))
    if not modules:
        return f"{PACKAGE}/metrics has no modules"
    for module in modules:
        text = module.read_text(encoding="utf-8")
        where = f"{PACKAGE}/metrics/{module.relative_to(root).as_posix()}"
        for column in PERSON_COLUMNS:
            if re.search(rf"\b{column}\b", text):
                return f"`{column}` in {where}"
        for pattern in RESTRICTED_TABLE_READS:
            if pattern.search(text):
                return f"a read of person_identifier in {where}"
        if module.relative_to(root).as_posix() != "snapshot.py" and re.search(
            r"\bperson_identifier\b", text
        ):
            return f"`person_identifier` in {where}"
    return None


def check_10() -> str | None:
    return _missing(*(f"{PACKAGE}/metrics/{name}.py" for name in METRICS_STEP2_MODULES))


def check_11() -> str | None:
    if (
        reason := _missing("pyproject.toml", "uv.lock", f"{PACKAGE}/metrics/snapshot.py")
    ) is not None:
        return reason
    project = _toml_table(_read("pyproject.toml"), "project") or ""
    dependencies = re.search(r"^dependencies\s*=\s*\[(.*?)^\]", project, re.MULTILINE | re.DOTALL)
    if dependencies is None or re.search(r'"duckdb\b', dependencies.group(1)) is None:
        return "[project.dependencies] does not list duckdb"
    if re.search(r'^name = "duckdb"$', _read("uv.lock"), re.MULTILINE) is None:
        return "uv.lock does not pin duckdb"
    snapshot = _read(f"{PACKAGE}/metrics/snapshot.py")
    if re.search(r"\b(?:INSTALL|LOAD)\b|install_extension\(|load_extension\(", snapshot):
        return "snapshot.py installs or loads a DuckDB extension"
    return None


def check_12() -> str | None:
    if (reason := _missing("pyproject.toml", "Makefile")) is not None:
        return reason
    return _check_names(("compute-metrics",), _poe_tasks(), "[tool.poe.tasks]") or _check_names(
        ("compute-metrics",), _makefile_targets(), "Makefile"
    )


def check_13() -> str | None:
    return _lacks_all(
        f"{PACKAGE}/cli.py",
        (
            (r'add_typer\(metrics_app,\s*name="metrics"\)', "the `metrics` group"),
            (r'@metrics_app\.command\("compute"\)', "`metrics compute`"),
            (r'@metrics_app\.command\("verify"\)', "`metrics verify`"),
        ),
    )


def _source_version(relative: str, constant: str) -> int | None:
    """``<constant> = "<n>"`` read from a source file with a regular expression."""
    found = re.search(rf'^{constant}\s*=\s*"(\d+)"', _read(relative), re.MULTILINE)
    return None if found is None else int(found.group(1))


def check_14() -> str | None:
    manifest_path = f"{GOLDEN_DIR}/manifest.json"
    truth_path = f"{GOLDEN_DIR}/truth/metrics.json"
    config_path = f"{PACKAGE}/synthetic/config.py"
    truth_module = f"{PACKAGE}/synthetic/truth.py"
    if (reason := _missing(manifest_path, truth_path, config_path, truth_module)) is not None:
        return reason
    manifest = json.loads(_read(manifest_path))
    # The source constants, not a literal: a later phase's version bump must
    # never fail this earlier phase's required check (Phase 4 Step 1).
    for key, relative, constant in (
        ("generator_version", config_path, "GENERATOR_VERSION"),
        ("truth_version", truth_module, "TRUTH_VERSION"),
    ):
        version = _source_version(relative, constant)
        if version is None or version < 2:
            return f"{relative} has no {constant} of at least 2"
        if str(manifest.get(key)) != str(version):
            return f"{manifest_path} {key} is not {constant} ({version})"
    if not isinstance(manifest.get("corpus"), dict):
        return f"{manifest_path} records no `corpus`"
    truth = json.loads(_read(truth_path))
    if "not_observable" not in truth:
        return f"{truth_path} has no `not_observable`"
    if "index_events" not in _dict_keys(truth):
        return f"{truth_path} has no `index_events`"
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        return f"{manifest_path} lists no files"
    tracked = set(_git_ls_files(GOLDEN_DIR))
    for name, expected in sorted(files.items()):
        member = f"{GOLDEN_DIR}/{name}"
        if member not in tracked:
            return f"{member} is listed in the manifest but not tracked by git"
        if hashlib.sha256(_path(member).read_bytes()).hexdigest() != expected:
            return f"sha256 mismatch for {member}"
    return None


def check_15() -> str | None:
    relative = "tests/golden/test_golden_metrics.py"
    return _missing(relative) or _untracked(relative)


def check_16() -> str | None:
    return _lacks_all(
        f"{PACKAGE}/ingest/runner.py",
        (
            (r"^def recompute_metrics\(", "recompute_metrics"),
            (
                r"^\s*from judgemetrics\.metrics(?:\.\w+)* import",
                "an import from judgemetrics.metrics",
            ),
        ),
    )


def check_17() -> str | None:
    relative = f"{PACKAGE}/ingest/base.py"
    if (
        reason := _lacks(relative, r"^class SupportsCoverage\(Protocol\)", "SupportsCoverage")
    ) is not None:
        return reason
    match = re.search(r"^class SourceInfo\b.*?(?=^class |\Z)", _read(relative), re.M | re.S)
    if match is None or re.search(r"^\s+observable_outcomes\s*:", match.group(0), re.M) is None:
        return "SourceInfo has no `observable_outcomes`"
    return None


def check_18() -> str | None:
    if (
        reason := _lacks(".gitignore", r"^/?data/snapshots/?\s*$", "`data/snapshots/`")
    ) is not None:
        return reason
    if (reason := _missing(".env.example")) is not None:
        return reason
    if "JUDGEMETRICS_SNAPSHOT_DIR" not in _env_example_values():
        return ".env.example does not document JUDGEMETRICS_SNAPSHOT_DIR"
    return None


def check_19() -> str | None:
    return _missing(f"{PACKAGE}/metrics/provenance.py") or _lacks_all(
        f"{PACKAGE}/cli.py",
        (
            (r'add_typer\(provenance_app,\s*name="provenance"\)', "the `provenance` group"),
            (r'@provenance_app\.command\("trace"\)', "`provenance trace`"),
        ),
    )


def check_20() -> str | None:
    return _missing(
        f"{PACKAGE}/api/routes/metrics.py",
        f"{PACKAGE}/api/routes/corrections.py",
        f"{PACKAGE}/schemas/metrics.py",
        f"{PACKAGE}/services/metrics.py",
        f"{PACKAGE}/repositories/metrics.py",
    )


def check_21() -> str | None:
    if (reason := _missing("docs/openapi.json")) is not None:
        return reason
    # A subset check (Phase 1 check 29, Phase 2 check 27): a later phase's
    # route never fails this required check; test_openapi.py pins the exact set.
    paths = json.loads(_read("docs/openapi.json")).get("paths", {})
    if absent := sorted(OPENAPI_PATHS - set(paths)):
        return f"openapi.json lacks Phase 3 paths {absent}"
    if "post" not in paths["/api/v1/corrections"]:
        return "openapi.json has no POST /api/v1/corrections"
    return None


def check_22() -> str | None:
    relative = "alembic/versions/0007_corrections_intake.py"
    if (reason := _missing(relative)) is not None:
        return reason
    text = _read(relative)
    if re.search(r'^TABLE\s*=\s*"correction_request"', text, re.MULTILINE) is None:
        return f"{relative} does not name correction_request"
    grants = re.findall(r"GRANT\s+([A-Z, ]+?)\s+ON\b", text)
    if not grants:
        return f"{relative} grants nothing"
    privileges = {p.strip() for grant in grants for p in grant.split(",")}
    return (
        f"{relative} grants {sorted(privileges)}, not INSERT only"
        if privileges != {"INSERT"}
        else None
    )


def check_23() -> str | None:
    relative = f"{PACKAGE}/schemas/metrics.py"
    if (reason := _missing(relative)) is not None:
        return reason
    text = _read(relative)
    found = [name for name in SCHEMA_PERSON_FIELDS if re.search(rf"\b{name}\b", text)]
    return f"{relative} names {', '.join(found)}" if found else None


def check_24() -> str | None:
    relative = f"{PACKAGE}/logging.py"
    if (reason := _missing(relative)) is not None:
        return reason
    text = _read(relative)
    absent = [name for name in LOGGING_DENYLIST if re.search(rf'"{name}"', text) is None]
    return f"{relative} denylist lacks {', '.join(absent)}" if absent else None


def check_25() -> str | None:
    return _lacks_all(
        "web/lib/api/schema.d.ts",
        (
            (r'"/api/v1/metrics/compare"', "/api/v1/metrics/compare"),
            (r'"/api/v1/corrections"', "/api/v1/corrections"),
        ),
    )


def check_26() -> str | None:
    return _lacks("docs/API.md", r"^## Metrics\s*$", "a `## Metrics` section") or _missing(
        "docs/PROVENANCE.md"
    )


def check_27() -> str | None:
    if (
        reason := _lacks_all(
            "tests/golden/test_public_contract.py",
            (
                (r"/metrics/compare", "/metrics/compare"),
                (r"/judges/\{id\}/metrics|/judges/\{judge_id\}/metrics", "the judge metrics route"),
                (r"/provenance", "the provenance route"),
            ),
        )
    ) is not None:
        return reason
    relative = "tests/integration/test_query_counts.py"
    if (reason := _missing(relative)) is not None:
        return reason
    tests = re.findall(r"^def (test_\w+)\(", _read(relative), re.MULTILINE)
    absent = [topic for topic in QUERY_BUDGET_TOPICS if not any(topic in name for name in tests)]
    return f"{relative} has no budget test for {', '.join(absent)}" if absent else None


def check_28() -> str | None:
    return _lacks(f"{PACKAGE}/repositories/search.py", r"word_similarity|<%", "word similarity")


def check_29() -> str | None:
    return _lacks_all(
        f"{PACKAGE}/api/routes/health.py",
        (
            (r"^\s+snapshot_hash\s*:", "a `snapshot_hash` field"),
            (r"^\s+metrics\s*:", "the `metrics` block"),
        ),
    )


def check_30() -> str | None:
    return _missing(*STEP4_WEB_FILES)


def check_31() -> str | None:
    page = "web/app/methodology/page.tsx"
    if (reason := _missing("web/app/compare/page.tsx", page, "web/lib/api/client.ts")) is not None:
        return reason
    if "metrics-note" in _read(page):
        return f"{page} still contains `metrics-note`"
    # The page reads the registry through the typed client (`getRegistry`),
    # whose one call is GET /api/v1/metrics.
    return _lacks(page, r"\bgetRegistry\(", "a getRegistry() call") or _lacks(
        "web/lib/api/client.ts",
        r'getRegistry\(\)[^{]*\{\s*return call\(\(\) => client\.GET\("/api/v1/metrics"\)\)',
        "getRegistry() over GET /api/v1/metrics",
    )


def check_32() -> str | None:
    return _lacks_all(
        "web/app/judges/[judgeId]/page.tsx",
        (
            (r"<MetricPanel\b", "<MetricPanel"),
            (r'data-testid="association-statement"', "the association statement test id"),
        ),
    )


def check_33() -> str | None:
    return _missing("web/tests/unit/metric-stat.test.tsx", "web/tests/e2e/metrics.spec.ts")


def check_34() -> str | None:
    return _lacks_all(
        "web/components/metric-stat.tsx",
        (
            (r"\bmethodologyHref\b", "methodologyHref"),
            (r"\bdata-suppressed=", "the data-suppressed notice attribute"),
        ),
    )


def check_35() -> str | None:
    return _lacks(
        "web/components/synthetic-banner.tsx",
        r'from "@/lib/coverage-cache"',
        "an import of lib/coverage-cache",
    )


def _screenshots(step: str, *, captures: bool) -> str | None:
    folder = f"docs/screenshots/phase03-{step}"
    if (reason := _missing(f"{folder}/README.md")) is not None:
        return reason
    if not captures:
        return None
    light = [p for p in _path(folder).glob("*-light.png") if p.stat().st_size > 0]
    dark = [p for p in _path(folder).glob("*-dark.png") if p.stat().st_size > 0]
    if not light or not dark:
        return f"{folder} lacks {'light' if not light else 'dark'} captures"
    return None


def check_36() -> str | None:
    return _screenshots("step4", captures=True)


def check_37() -> str | None:
    tracked = _git_ls_files("web/app", "web/components")
    # Bytes, so the icons and images under web/app are scanned without decoding.
    found = [
        rel
        for rel in tracked
        if _path(rel).is_file() and b"dangerouslySetInnerHTML" in _path(rel).read_bytes()
    ]
    return f"dangerouslySetInnerHTML in {', '.join(found)}" if found else None


def check_38() -> str | None:
    return _missing(*STEP5_WEB_FILES)


def check_39() -> str | None:
    return _missing("web/app/jurisdictions/[jurisdictionId]/page.tsx") or _lacks(
        "web/app/courts/[courtId]/page.tsx", r"<MetricPanel\b", "<MetricPanel"
    )


def check_40() -> str | None:
    if (reason := _missing("pyproject.toml", "Makefile")) is not None:
        return reason
    body = _toml_table(_read("pyproject.toml"), "tool.poe.tasks") or ""
    match = re.search(r"^bootstrap\s*=\s*\[(.*?)\]", body, re.MULTILINE)
    if match is None:
        return "[tool.poe.tasks] has no `bootstrap` sequence"
    stages = tuple(re.findall(r'"([\w-]+)"', match.group(1)))
    if stages != BOOTSTRAP_SEQUENCE:
        return f"bootstrap is {list(stages)}, not {list(BOOTSTRAP_SEQUENCE)}"
    return _check_names(("bootstrap",), _makefile_targets(), "Makefile")


def check_41() -> str | None:
    if (reason := _missing("README.md")) is not None:
        return reason
    match = re.search(
        r"^#+ The first milestone\s*$(.*?)(?=^#{1,3}\s|\Z)", _read("README.md"), re.M | re.S
    )
    if match is None:
        return "README.md has no `The first milestone` section"
    numbers = [int(n) for n in re.findall(r"^\s*(\d+)\.\s", match.group(1), re.MULTILINE)]
    if numbers != list(range(1, MILESTONE_ITEMS + 1)):
        return f"the milestone lists {len(numbers)} numbered items, not 1-{MILESTONE_ITEMS}"
    return None


def check_42() -> str | None:
    if (reason := _missing(".github/workflows/ci.yml")) is not None:
        return reason
    block = _yaml_job_block(_read(".github/workflows/ci.yml"), "e2e")
    if block is None:
        return "ci.yml has no `e2e` job"
    if re.search(r"uv run judgemetrics seed --out data/synthetic/ci\b", block) is None:
        return "the `e2e` job does not run `judgemetrics seed --out data/synthetic/ci`"
    if re.search(r"uv run judgemetrics metrics compute\b", block) is None:
        return "the `e2e` job does not run `judgemetrics metrics compute`"
    if re.search(r"--from-fixture tests/fixtures/golden\b", block):
        return "the `e2e` job still ingests tests/fixtures/golden"
    for variable in ("JUDGEMETRICS_IDENTIFIER_PEPPER", "JUDGEMETRICS_CORRECTION_CONTACT_KEY"):
        if re.search(rf"^\s+{variable}\s*:", block, re.MULTILINE):
            return f"the `e2e` job sets {variable} in `env:`"
        if re.search(rf'echo "{variable}=\$\w+" >> "\$GITHUB_ENV"', block) is None:
            return f"the `e2e` job does not write {variable} to $GITHUB_ENV"
    return None


def check_43() -> str | None:
    relative = "web/tests/e2e/first-milestone.spec.ts"
    if (reason := _missing(relative)) is not None:
        return reason
    tests = re.findall(r"^\s*test\(", _read(relative), re.MULTILINE)
    if len(tests) < FIRST_MILESTONE_MIN_TESTS:
        return f"{relative} has {len(tests)} tests, fewer than {FIRST_MILESTONE_MIN_TESTS}"
    return None


def check_44() -> str | None:
    return _screenshots("step5", captures=False)


def check_45() -> str | None:
    relative = f"scripts/verify_phase{PHASE}.py"
    if (reason := _missing(relative) or _untracked(relative)) is not None:
        return reason
    text = _read(relative)
    if not text.startswith(f"# {relative}\n"):
        return f"{relative} lacks its path comment"
    absent = [flag for flag in MODE_FLAGS if re.search(rf'add_argument\(\s*"{flag}"', text) is None]
    return f"{relative} lacks the argparse modes {', '.join(absent)}" if absent else None


def check_46() -> str | None:
    relative = f"docs/phase{PHASE}-qa-findings.md"
    if (reason := _missing(relative)) is not None:
        return reason
    text = _read(relative)
    absent = [section for section in QA_SECTIONS if section not in text]
    return f"{relative} lacks {', '.join(absent)}" if absent else None


def check_47() -> str | None:
    return _missing(f"docs/roadmap/phase{PHASE}-roadmap.md")


def check_48() -> str | None:
    relative = ".github/workflows/phase-verify.yml"
    if (reason := _missing(relative)) is not None:
        return reason
    matrix = re.search(r"phase:\s*\[([^\]]*)\]", _read(relative))
    entries = (
        {entry.strip().strip("\"'") for entry in matrix.group(1).split(",")} if matrix else set()
    )
    if absent := sorted({"01", "02", PHASE} - entries):
        return f"{relative} matrix lacks {', '.join(absent)}"
    return _unpinned_uses(relative)


def check_49() -> str | None:
    config = ".pre-commit-config.yaml"
    if (reason := _missing(config)) is not None:
        return reason
    hooks = set(re.findall(r"^\s*-\s*id:\s*([\w-]+)", _read(config), re.MULTILINE))
    if (reason := _check_names(PRE_COMMIT_HOOKS, hooks, f"{config} hooks")) is not None:
        return reason
    if re.search(r"entry:\s*uv run python scripts/audit_deps\.py", _read(config)) is None:
        return f"{config} pip-audit hook does not run scripts/audit_deps.py"
    for workflow in (".github/workflows/ci.yml", ".github/workflows/phase-verify.yml"):
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
    (
        1,
        "metric_registry.yaml is tracked, versioned, has 8 known_limitations and every slug",
        check_01,
    ),
    (2, "metrics/ has registry, frame, attribution, index_events ... methodology", check_02),
    (
        3,
        "alembic 0005 creates metric_snapshot and members, adds source coverage, grants",
        check_03,
    ),
    (4, "docs/METHODOLOGY.md Known limitations carries the brief's warnings verbatim", check_04),
    (5, "the registry's known_limitations equal the brief's warnings verbatim", check_05),
    (6, "test_frame_invariants.py and test_attribution.py exist and are tracked", check_06),
    (7, "cli.py registers methodology render with --check", check_07),
    (8, "ARCHITECTURE.md has Metrics engine; DATA_MODEL.md names the snapshot tables", check_08),
    (9, "no module under metrics/ reads person_identifier or a person column", check_09),
    (10, "metrics/ has snapshot, compute, suppression, publish, verify", check_10),
    (11, "duckdb is a runtime dependency pinned in uv.lock; snapshot.py loads nothing", check_11),
    (12, "poe task compute-metrics exists and the Makefile mirrors it", check_12),
    (13, "cli.py registers metrics compute and metrics verify", check_13),
    (
        14,
        "golden manifest at the source versions (>= 2) with corpus; truth metrics; sha256s",
        check_14,
    ),
    (15, "tests/golden/test_golden_metrics.py exists and is tracked", check_15),
    (16, "ingest/runner.py recompute_metrics imports from judgemetrics.metrics", check_16),
    (17, "ingest/base.py defines SupportsCoverage and SourceInfo.observable_outcomes", check_17),
    (
        18,
        ".gitignore excludes data/snapshots/; .env.example has JUDGEMETRICS_SNAPSHOT_DIR",
        check_18,
    ),
    (19, "metrics/provenance.py exists; cli.py registers provenance trace", check_19),
    (20, "metrics and corrections routes, schemas, services, repositories exist", check_20),
    (21, "docs/openapi.json lists the six Phase 3 paths (subset check)", check_21),
    (22, "alembic 0007 grants INSERT only on correction_request", check_22),
    (23, "schemas/metrics.py names no person field", check_23),
    (
        24,
        "logging.py denylist covers correction_contact_key, requester_contact, contact, reason",
        check_24,
    ),
    (25, "web/lib/api/schema.d.ts names /metrics/compare and /corrections", check_25),
    (26, "docs/API.md has a Metrics section; docs/PROVENANCE.md exists", check_26),
    (
        27,
        "test_public_contract.py names the metrics routes; test_query_counts.py budgets them",
        check_27,
    ),
    (28, "repositories/search.py uses word similarity", check_28),
    (29, "api/routes/health.py reports metrics.snapshot_hash on /ready", check_29),
    (30, "metric-stat, metric-panel, cohort-selector, lib/metrics, coverage-cache exist", check_30),
    (31, "compare page exists; methodology page reads GET /api/v1/metrics", check_31),
    (32, "the judge page renders MetricPanel and the association statement", check_32),
    (33, "metric-stat.test.tsx and metrics.spec.ts exist", check_33),
    (34, "metric-stat.tsx renders methodologyHref and a data-suppressed notice", check_34),
    (35, "synthetic-banner.tsx imports the coverage cache", check_35),
    (36, "docs/screenshots/phase03-step4 has README.md with light and dark captures", check_36),
    (37, "no dangerouslySetInnerHTML under web/app or web/components", check_37),
    (38, "corrections page, received page, route handler, and form component exist", check_38),
    (39, "jurisdiction page exists; the court page renders MetricPanel", check_39),
    (
        40,
        "poe bootstrap is up, migrate, ingest-fjc, seed, compute-metrics; Makefile mirrors",
        check_40,
    ),
    (41, "README.md The first milestone lists seventeen numbered items", check_41),
    (
        42,
        "ci.yml e2e seeds data/synthetic/ci, computes, keeps secrets in $GITHUB_ENV",
        check_42,
    ),
    (43, "web/tests/e2e/first-milestone.spec.ts has at least nine tests", check_43),
    (44, "docs/screenshots/phase03-step5/README.md exists", check_44),
    (45, f"scripts/verify_phase{PHASE}.py is tracked with its path comment and modes", check_45),
    (46, f"docs/phase{PHASE}-qa-findings.md has every rollup section", check_46),
    (47, f"docs/roadmap/phase{PHASE}-roadmap.md exists", check_47),
    (48, f'.github/workflows/phase-verify.yml matrix includes "{PHASE}"', check_48),
    (
        49,
        "security wiring: hooks, least-privilege pinned workflows, no key material",
        check_49,
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
    description = "pnpm --dir web e2e (smoke, metrics, first milestone)"
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
# --post: the milestone items, the probes, the V1-V6 matrix, and the PR checks
# --------------------------------------------------------------------------- #


def probe_environment() -> tuple[dict[str, str], str]:
    """The subprocess environment the writing probes run in, and where it points.

    With JUDGEMETRICS_TEST_DATABASE_URL configured, the three role URLs are
    pointed at the scratch database and JUDGEMETRICS_SNAPSHOT_DIR at
    `SCRATCH_SNAPSHOT_DIR` (Phase 3 Step 5's safe shape: the live database
    and its snapshots are untouched). The directory persists because the
    scratch database's observations cite their snapshots by path; a
    temporary one would leave a later `metrics verify` there unable to open
    them. Snapshots are content-addressed and never overwritten, so reuse
    is safe. Otherwise the configured database is used.
    """
    env = dict(os.environ)
    test_url = _configured_value("JUDGEMETRICS_TEST_DATABASE_URL")
    if test_url is None:
        return env, "the configured database (JUDGEMETRICS_TEST_DATABASE_URL unset)"
    for variable in ROLE_URL_VARIABLES:
        env[variable] = test_url
    env["JUDGEMETRICS_SNAPSHOT_DIR"] = str(_path(SCRATCH_SNAPSHOT_DIR))
    return env, f"the scratch test database, snapshots under {SCRATCH_SNAPSHOT_DIR}/"


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
    argv: Sequence[str], env: Mapping[str, str], timeout: float
) -> tuple[object | None, str]:
    """Run ``argv`` capturing stdout; the parsed JSON and a failure reason."""
    executable = tool(argv[0])
    if executable is None:
        return None, f"`{argv[0]}` not on PATH"
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
        return None, f"timed out after {timeout:.0f}s"
    if completed.returncode != 0:
        return None, f"exit code {completed.returncode}"
    document = _json_from(completed.stdout)
    return document, "" if document is not None else "printed no JSON"


def _counts(env: Mapping[str, str]) -> dict[str, int] | str:
    """Row counts of the probe tables, or the reason they could not be read."""
    document, reason = _run_json(
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
    heading("First milestone, items 1-5, and the bootstrap rerun (V5.3)")
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
            ("V5.3.bootstrap", "uv run poe bootstrap (idempotent rerun)"),
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
            "V5.3.bootstrap",
            "uv run poe bootstrap (idempotent rerun)",
            ["uv", "run", "poe", "bootstrap"],
            env=env,
            timeout=BOOTSTRAP_TIMEOUT,
        )
    )
    return outcomes


def seed_probe(env: Mapping[str, str]) -> Outcome:
    """Canonical and observation row counts are unchanged by a second `judgemetrics seed`."""
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
    """A second `metrics compute` over unchanged data publishes and supersedes nothing."""
    heading("Compute idempotency probe (V2.4)")
    description = "a second `metrics compute` publishes zero"
    argv = ["uv", "run", "judgemetrics", "metrics", "compute", "--json"]
    results: list[dict[str, object]] = []
    for attempt in ("first", "second"):
        print(f"\n$ {' '.join(argv)}  ({attempt})", flush=True)
        document, reason = _run_json(argv, env, SEED_TIMEOUT)
        if not isinstance(document, dict):
            return report(Outcome("probe.compute", description, "FAIL", reason or "not an object"))
        print(
            f"snapshot={document.get('snapshot')} subjects={document.get('subjects')} "
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
    moved = [key for key in ("observations", "superseded", "subjects_published") if second.get(key)]
    if moved:
        detail = ", ".join(f"{key}={second[key]}" for key in moved)
        return report(Outcome("probe.compute", description, "FAIL", detail))
    return report(Outcome("probe.compute", description, "PASS"))


def verify_probe(env: Mapping[str, str]) -> Outcome:
    heading("metrics verify (V2.4)")
    return run_command(
        "probe.verify",
        "uv run judgemetrics metrics verify exits 0",
        ["uv", "run", "judgemetrics", "metrics", "verify"],
        env=env,
        timeout=SEED_TIMEOUT,
    )


def trace_probe(env: Mapping[str, str]) -> Outcome:
    """`provenance trace` of one current observation, chosen at random, exits 0 complete."""
    heading("Provenance trace probe (V3.3)")
    description = "judgemetrics provenance trace <one current observation> is complete"
    document, reason = _run_json(["uv", "run", "python", "-c", OBSERVATION_SNIPPET], env, 120)
    if not isinstance(document, dict):
        return report(Outcome("probe.trace", description, "FAIL", f"id query failed ({reason})"))
    observation_id = document.get("id")
    if not isinstance(observation_id, str):
        return report(Outcome("probe.trace", description, "SKIP", "no current observation"))
    if re.fullmatch(r"[0-9a-f-]{36}", observation_id) is None:
        return report(Outcome("probe.trace", description, "FAIL", "the id is not a UUID"))
    uv = tool("uv")
    if uv is None:
        return report(Outcome("probe.trace", description, "FAIL", "`uv` not on PATH"))
    argv = [uv, "run", "judgemetrics", "provenance", "trace", observation_id]
    print(f"\n$ uv run judgemetrics provenance trace {observation_id}", flush=True)
    # The CLI's text output carries ids, hashes, counts, and artifact URIs:
    # no person material by Step 3's contract, so it is printed as it is.
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
        ("M7", "item 7: the web app serves /", f"{web}/", "uv run poe dev-web"),
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
    traced = trace_probe(env)
    services = milestone_services()
    e2e = e2e_suite()
    node = node_suites()
    security = security_suites()
    heading("Suites for V1-V3")
    registry_unit = pytest_suite(
        "V1.2",
        "test_metric_registry.py, test_attribution.py, test_methodology_render.py",
        "tests/unit/test_metric_registry.py",
        "tests/unit/test_attribution.py",
        "tests/unit/test_methodology_render.py",
    )
    frame_property = pytest_suite(
        "V1.3",
        "test_frame_invariants.py (HYPOTHESIS_PROFILE=ci)",
        "tests/property/test_frame_invariants.py",
        env={**os.environ, "HYPOTHESIS_PROFILE": "ci"},
    )
    migrations = integration_suite(
        "V1.4",
        "test_migrations.py and test_metric_registry_sync.py",
        "tests/integration/test_migrations.py",
        "tests/integration/test_metric_registry_sync.py",
    )
    golden = integration_suite(
        "V2.2",
        "test_golden_metrics.py, test_golden_counts.py, test_golden_fixture.py",
        "tests/golden/test_golden_metrics.py",
        "tests/golden/test_golden_counts.py",
        "tests/golden/test_golden_fixture.py",
    )
    ingest = integration_suite(
        "V2.3", "test_synthetic_ingest.py", "tests/integration/test_synthetic_ingest.py"
    )
    api = integration_suite(
        "V3.2",
        "test_api_metrics, test_api_corrections, test_api_search, test_query_counts, "
        "test_openapi, test_public_contract",
        "tests/integration/test_api_metrics.py",
        "tests/integration/test_api_corrections.py",
        "tests/integration/test_api_search.py",
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

    static_row("V1.1", 1, 9)
    suite_row(
        "V1.2",
        "test_metric_registry, test_attribution, test_methodology_render pass",
        registry_unit,
    )
    suite_row("V1.3", "test_frame_invariants.py passes under the ci profile", frame_property)
    suite_row(
        "V1.4", "test_migrations.py through 0005 and test_metric_registry_sync.py pass", migrations
    )
    static_row("V2.1", 10, 18)
    suite_row("V2.2", "test_golden_metrics, test_golden_counts, test_golden_fixture pass", golden)
    suite_row("V2.3", "test_synthetic_ingest.py (pipeline step 13) passes", ingest)
    rows.append(
        (
            "V2.4",
            "compute idempotency probe publishes zero; metrics verify exits 0",
            *suites_outcome((compute, verified)),
        )
    )
    static_row("V3.1", 19, 29)
    suite_row(
        "V3.2",
        "test_api_metrics, test_api_corrections, test_api_search, test_query_counts, "
        "test_openapi, test_public_contract pass",
        api,
    )
    suite_row("V3.3", "provenance trace of one current observation is complete", traced)
    rows.append(
        (
            "V3.4",
            "the `container` CI job is green on the current branch",
            *check_bucket(checks, "container"),
        )
    )
    static_row("V4.1", 30, 37)
    rows.append(("V4.2", "pnpm lint, typecheck, build, test pass", *suites_outcome(node)))
    rows.append(("V4.3", "metrics.spec.ts passes (pnpm e2e)", *e2e_row(e2e, checks)))
    static_row("V5.1", 38, 44)
    rows.append(("V5.2", "first-milestone.spec.ts passes (pnpm e2e)", *e2e_row(e2e, checks)))
    rows.append(
        (
            "V5.3",
            "bootstrap is idempotent; milestone items 1-7 and 17 pass",
            *suites_outcome((*setup, seed, *services, check_all)),
        )
    )
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
    matrix = next(o for o in statics if o.id == "48")
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
