# scripts/verify_phase02.py
"""Phase 2 verification: static deliverable checks, tool suites, and the V1-V6 matrix.

Modes are mutually exclusive; with no flag the script runs ``--fast`` plus
``--py``:

  --fast      the 44 static checks only (CI-safe on Ubuntu and Windows,
              well under 30 seconds: pathlib, re, json, hashlib, and
              ``git ls-files``)
  --py        static + ruff, ruff format --check, mypy, the unit suite, and
              the integration, property, and golden suites when a database
              is configured (JUDGEMETRICS_TEST_DATABASE_URL preferred)
  --node      static + pnpm lint, typecheck, build, test in web/
  --e2e       static + the Playwright suite (skips with a reason when the
              API or the web app is not reachable)
  --security  the gate over the phase's surface: detect-secrets against the
              baseline, bandit over src, alembic, and scripts, pip-audit
              over uv.lock, pnpm audit
  --all       static + py + node + e2e + security
  --post      static + the V1-V6 matrix of docs/phase02-roadmap.md, the seed
              idempotency probe, plus ``gh pr checks`` for the current branch
              when gh is signed in

Every static check is independent and reads the repository only; it prints
``[PASS] NN description`` or ``[FAIL] NN description — reason``. Suites are
subprocesses with argument lists (never a shell) over tools resolved on
PATH (``uv``, ``pnpm``, ``gh``, ``git``). The script prints check names,
paths, and tool output; it never prints repository file contents. Exit 0
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
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = REPO_ROOT / "web"
PACKAGE = "src/judgemetrics"
PHASE = "02"

Status = Literal["PASS", "FAIL", "SKIP"]
CheckFn = Callable[[], str | None]  # None on success, otherwise the failure reason

SYNTHETIC_MODULES = (
    "config",
    "rng",
    "wordlists",
    "world",
    "cases",
    "edge_cases",
    "truth",
    "writer",
    "generate",
)
# The brief's synthetic demo dataset minimums (<synthetic_demo_dataset>).
BRIEF_MINIMUMS = {"courts": 5, "judges": 20, "persons": 3_000, "cases": 5_000}
# Nondeterminism the generator must never call: module-level ``random``
# functions, wall-clock time, random UUIDs, OS entropy. Each pattern requires
# the call parenthesis so a docstring that names the function does not match.
NONDETERMINISTIC_CALLS = (
    ("datetime.now()", re.compile(r"\bdatetime\.now\(")),
    ("uuid.uuid4()", re.compile(r"\buuid4\(")),
    ("os.urandom()", re.compile(r"\burandom\(")),
    (
        "module-level random.*()",
        re.compile(
            r"(?<![\w.])random\.(?:random|randint|randrange|choice|choices|shuffle|sample|"
            r"uniform|gauss|seed|getrandbits|triangular|betavariate|expovariate|"
            r"normalvariate|lognormvariate|vonmisesvariate|paretovariate|weibullvariate)\("
        ),
    ),
)
GOLDEN_DIR = "tests/fixtures/golden"
GOLDEN_SOURCE_FILES = (
    "assignments.csv",
    "cases.csv",
    "charges.csv",
    "courts.csv",
    "decisions.csv",
    "events.csv",
    "judges.csv",
    "participants.csv",
    "sentences.csv",
)
GOLDEN_TRUTH_FILES = (
    "metrics.json",
    "persons.csv",
    "planted.csv",
    "resolution_expectations.csv",
    "subsequent_events.csv",
    "README.md",
)
CASE_LEVEL_DRAFTS = (
    "CaseDraft",
    "CasePartyDraft",
    "JudgeAssignmentDraft",
    "ChargeDraft",
    "CourtEventDraft",
    "PretrialReleaseDraft",
    "DecisionDraft",
    "SentenceDraft",
    "JusticeEventDraft",
)
CASE_LEVEL_UPSERTS = (
    "upsert_cases",
    "upsert_parties",
    "upsert_assignments",
    "upsert_charges",
    "upsert_events",
    "upsert_decisions",
    "upsert_sentences",
    "upsert_justice_events",
)
SYNTHETIC_CONNECTOR_MODULES = ("schema", "parse", "normalize", "connector", "sources")
SCRUBBER_DENYLIST = ("identifier_pepper", "value_hash", "date_of_birth", "full_name")
ER_MODULES = (
    "config",
    "features",
    "deterministic",
    "rules",
    "scoring",
    "candidates",
    "queue",
    "merge",
    "pipeline",
)
ER_STAGES = ("deterministic", "rules", "probabilistic", "review")
OPENAPI_PATHS = {
    "/api/v1/health",
    "/api/v1/ready",
    "/api/v1/judges",
    "/api/v1/judges/{judge_id}",
    "/api/v1/judges/{judge_id}/service",
    "/api/v1/judges/{judge_id}/cases",
    "/api/v1/courts",
    "/api/v1/courts/{court_id}",
    "/api/v1/jurisdictions",
    "/api/v1/jurisdictions/{jurisdiction_id}",
    "/api/v1/search",
    "/api/v1/cases/{case_id}",
    "/api/v1/cases/{case_id}/timeline",
    "/api/v1/coverage",
}
# Names of the restricted person material that must never appear as a
# property of the public contract (docs/openapi.json, web/lib/api/schema.d.ts).
RESTRICTED_NAMES = (
    "value_hash",
    "encrypted_value",
    "date_of_birth",
    "full_name",
    "person_identifier",
)
API_DOC_PATHS = (
    "/cases/{case_id}",
    "/cases/{case_id}/timeline",
    "/judges/{judge_id}/cases",
    "/coverage",
)
PROPERTY_TESTS = (
    "test_event_ordering",
    "test_case_numbers",
    "test_resolution_consistency",
    "test_ingest_idempotent",
)
GOLDEN_TESTS = (
    "test_golden_fixture",
    "test_golden_resolution",
    "test_golden_counts",
    "test_public_contract",
)
SHA_PIN = re.compile(r"@[0-9a-f]{40}$")
# The security backstop (check 40): a PEM private-key header, an AWS access
# key id, or any PEM block header in the phase's source, web, test, doc,
# infra, and data trees. Bytes patterns so binary files are scanned too
# without decoding; complete headers only, so a regex source or prose that
# mentions the marker never matches.
BACKSTOP_PATTERNS = (
    ("private-key header", re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("AKIA-style access key", re.compile(rb"AKIA[0-9A-Z]{16}")),
    ("PEM block", re.compile(rb"-----BEGIN [A-Z ]+-----")),
)
BACKSTOP_TREES = ("src", "web", "tests", "docs", "infra", "data")
# Lockfiles carry integrity hashes, not credentials (the pre-commit hook's
# exclude pattern); the baseline is the scanner's own state.
SECRET_SCAN_EXCLUDES = ("uv.lock", "web/pnpm-lock.yaml", ".secrets.baseline")
# Longest argv (in characters) handed to detect-secrets-hook per call; well
# under the Windows command-line limit.
ARGV_BUDGET = 20_000
# The seed idempotency probe (V2.4) counts these canonical tables before and
# after a second `judgemetrics seed`; the app role can read every one.
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
)
# `judgemetrics seed` writes data/synthetic/<seed> for its default seed
# (src/judgemetrics/cli.py DEFAULT_SYNTHETIC_SEED); the probe needs that
# dataset to exist already so the second seed skips generation.
SEED_DATASET_MANIFEST = "data/synthetic/20260916/manifest.json"
# Run through `uv run python -c <snippet> <tables...>` (the script itself
# stays standard-library only): row counts of the named tables as one JSON
# object on stdout, read through the configured settings (a local .env).
SEED_COUNT_SNIPPET = """
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


# --------------------------------------------------------------------------- #
# Results and output
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Outcome:
    """One reported item: a static check, a suite, or a V-check."""

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


# --------------------------------------------------------------------------- #
# Static checks 1-44
# --------------------------------------------------------------------------- #


def check_01() -> str | None:
    return _missing(*(f"{PACKAGE}/synthetic/{name}.py" for name in SYNTHETIC_MODULES))


def check_02() -> str | None:
    relative = f"{PACKAGE}/synthetic/config.py"
    if (
        reason := _lacks_all(
            relative,
            (
                (r"^GENERATOR_VERSION\s*=", "GENERATOR_VERSION"),
                (r"^GOLDEN\s*=\s*ScaleSpec\(", "GOLDEN"),
                (r"^DEMO\s*=\s*ScaleSpec\(", "DEMO"),
                (r"^TINY\s*=\s*ScaleSpec\(", "TINY"),
            ),
        )
    ) is not None:
        return reason
    demo = re.search(r"^DEMO\s*=\s*ScaleSpec\((.*?)^\)", _read(relative), re.MULTILINE | re.DOTALL)
    if demo is None:
        return "DEMO's ScaleSpec call is not a literal"
    short: list[str] = []
    for field, minimum in BRIEF_MINIMUMS.items():
        literal = re.search(rf"\b{field}\s*=\s*([\d_]+)", demo.group(1))
        if literal is None:
            return f"DEMO has no literal `{field}=`"
        if int(literal.group(1).replace("_", "")) < minimum:
            short.append(f"{field} {literal.group(1)} < {minimum}")
    return f"DEMO below the brief's minimums: {', '.join(short)}" if short else None


def check_03() -> str | None:
    modules = sorted(_path(f"{PACKAGE}/synthetic").glob("*.py"))
    if not modules:
        return f"{PACKAGE}/synthetic has no modules"
    for module in modules:
        text = module.read_text(encoding="utf-8")
        for label, pattern in NONDETERMINISTIC_CALLS:
            if pattern.search(text):
                return f"{label} in {PACKAGE}/synthetic/{module.name}"
    return None


def check_04() -> str | None:
    return _missing(
        f"{GOLDEN_DIR}/manifest.json",
        *(f"{GOLDEN_DIR}/source/{name}" for name in GOLDEN_SOURCE_FILES),
        *(f"{GOLDEN_DIR}/truth/{name}" for name in GOLDEN_TRUTH_FILES),
    )


def check_05() -> str | None:
    relative = f"{GOLDEN_DIR}/manifest.json"
    if (reason := _missing(relative)) is not None:
        return reason
    files = json.loads(_read(relative)).get("files")
    if not isinstance(files, dict) or not files:
        return f"{relative} lists no files"
    tracked = set(_git_ls_files(GOLDEN_DIR))
    for name, expected in sorted(files.items()):
        member = f"{GOLDEN_DIR}/{name}"
        if member not in tracked:
            return f"{member} is listed in the manifest but not tracked by git"
        actual = hashlib.sha256(_path(member).read_bytes()).hexdigest()
        if actual != expected:
            return f"sha256 mismatch for {member}"
    return None


def check_06() -> str | None:
    relative = "data/reference/synthetic_offenses.csv"
    if (reason := _missing(relative)) is not None:
        return reason
    header = _read(relative).splitlines()[0] if _read(relative).strip() else ""
    columns = {column.strip() for column in header.split(",")}
    wanted = ("statute_code", "description", "offense_category", "severity")
    return _check_names(wanted, columns, f"{relative} header")


def check_07() -> str | None:
    relative = "docs/SYNTHETIC_DATA.md"
    return _lacks(relative, r"truth_version", "`truth_version`") or _lacks(
        relative, r"GENERATOR_VERSION", "`GENERATOR_VERSION`"
    )


def check_08() -> str | None:
    return _lacks_all(
        f"{PACKAGE}/cli.py",
        (
            (r'add_typer\(synthetic_app,\s*name="synthetic"\)', "the `synthetic` group"),
            (r'@synthetic_app\.command\("generate"\)', "`synthetic generate`"),
            (r'@synthetic_app\.command\("verify"\)', "`synthetic verify`"),
        ),
    )


def check_09() -> str | None:
    relative = f"{PACKAGE}/ingest/base.py"
    if (reason := _missing(relative)) is not None:
        return reason
    classes = set(re.findall(r"^class (\w+Draft)\b", _read(relative), re.MULTILINE))
    return _check_names(CASE_LEVEL_DRAFTS, classes, f"{relative} drafts")


def check_10() -> str | None:
    # The upserts live in ingest/publish.py (the runner imports them and calls
    # them at its publish step); the roadmap named them under the runner.
    publish = f"{PACKAGE}/ingest/publish.py"
    if (reason := _missing(publish, f"{PACKAGE}/ingest/runner.py")) is not None:
        return reason
    functions = set(re.findall(r"^def (upsert_\w+)\(", _read(publish), re.MULTILINE))
    if (reason := _check_names(CASE_LEVEL_UPSERTS, functions, f"{publish} upserts")) is not None:
        return reason
    return _lacks(
        f"{PACKAGE}/ingest/runner.py",
        r"^from judgemetrics\.ingest\.publish import",
        "an import of ingest/publish.py",
    )


def check_11() -> str | None:
    relative = "alembic/versions/0003_case_level_natural_keys.py"
    return _lacks_all(
        relative,
        (
            (r'"uq_person_identifier_stable"', "uq_person_identifier_stable"),
            (r'sa\.Column\(\s*"source_row_id"', "a `source_row_id` column"),
        ),
    )


def check_12() -> str | None:
    return _lacks(
        "data/reference/case_vocabulary.yaml", r"^version:\s*\d+", "`version:`"
    ) or _missing(f"{PACKAGE}/normalization/vocabulary.py")


def check_13() -> str | None:
    return _lacks(
        f"{PACKAGE}/security/identifiers.py", r"^def hash_identifier\(", "hash_identifier"
    ) or _lacks_all(
        f"{PACKAGE}/config.py",
        (
            (r"^\s+identifier_pepper\s*:\s*SecretStr", "`identifier_pepper: SecretStr`"),
            (r"^\s+synthetic_dir\s*:", "`synthetic_dir`"),
        ),
    )


def check_14() -> str | None:
    if (
        reason := _missing(
            *(f"{PACKAGE}/ingest/synthetic/{name}.py" for name in SYNTHETIC_CONNECTOR_MODULES)
        )
    ) is not None:
        return reason
    if (
        reason := _lacks(
            f"{PACKAGE}/ingest/registry.py",
            r'"judgemetrics\.ingest\.synthetic\.connector"',
            "the synthetic connector module",
        )
    ) is not None:
        return reason
    modules = sorted(_path(f"{PACKAGE}/ingest/synthetic").glob("*.py"))
    text = "\n".join(path.read_text(encoding="utf-8") for path in modules)
    if re.search(r'source_type\s*=\s*"synthetic"', text) is None:
        return f'{PACKAGE}/ingest/synthetic sets no `source_type = "synthetic"`'
    return None


def check_15() -> str | None:
    if (reason := _missing(".env.example")) is not None:
        return reason
    value = _env_example_values().get("JUDGEMETRICS_IDENTIFIER_PEPPER")
    if value is None:
        return ".env.example does not document JUDGEMETRICS_IDENTIFIER_PEPPER"
    if not value or re.search(r"change-me|placeholder|replace", value, re.IGNORECASE) is None:
        return "JUDGEMETRICS_IDENTIFIER_PEPPER in .env.example is not a placeholder"
    return None


def check_16() -> str | None:
    if (reason := _missing("pyproject.toml", "Makefile")) is not None:
        return reason
    return (
        _check_names(("seed",), _poe_tasks(), "[tool.poe.tasks]")
        or _check_names(("seed",), _makefile_targets(), "Makefile")
        or _lacks(f"{PACKAGE}/cli.py", r'@app\.command\("seed"\)', "`seed`")
    )


def check_17() -> str | None:
    relative = f"{PACKAGE}/logging.py"
    if (reason := _missing(relative)) is not None:
        return reason
    text = _read(relative)
    absent = [name for name in SCRUBBER_DENYLIST if re.search(rf'"{name}"', text) is None]
    return f"{relative} denylist lacks {', '.join(absent)}" if absent else None


def check_18() -> str | None:
    return _missing(*(f"{PACKAGE}/entity_resolution/{name}.py" for name in ER_MODULES))


def check_19() -> str | None:
    relative = f"{PACKAGE}/entity_resolution/scoring.py"
    return _lacks(relative, r"^class Scorer\(Protocol\)", "class Scorer(Protocol)") or _lacks(
        relative, r"^class StubScorer\b", "StubScorer"
    )


def check_20() -> str | None:
    return _missing("data/reference/entity_resolution_thresholds.yaml") or _lacks(
        f"{PACKAGE}/entity_resolution/config.py", r"^MODEL_VERSION\s*=", "MODEL_VERSION"
    )


def check_21() -> str | None:
    relative = "alembic/versions/0004_entity_resolution_review.py"
    if (reason := _missing(relative)) is not None:
        return reason
    text = _read(relative)
    if '"audit_log"' not in text or "op.create_table(" not in text:
        return f"{relative} does not create audit_log"
    if "audit_log_append_only" not in text:
        return f"{relative} lacks the audit_log_append_only trigger"
    return None


def check_22() -> str | None:
    relative = f"{PACKAGE}/entity_resolution/rules.py"
    return _lacks_all(
        relative,
        (
            (r"never (?:\w+ )*name alone", "the `never name alone` guard comment"),
            (r'REASON_NAME_ONLY\s*=\s*"name_only"', "the `name_only` rejection reason"),
            (r"ResolutionDecision\.REJECTED,\s*SCORE_NAME_ONLY", "a name-only rejection"),
        ),
    )


def check_23() -> str | None:
    return _lacks_all(
        f"{PACKAGE}/cli.py",
        (
            (r'add_typer\(er_app,\s*name="er"\)', "the `er` group"),
            (r'er_app\.add_typer\(er_review_app,\s*name="review"\)', "the `er review` group"),
            (r'@er_app\.command\("run"\)', "`er run`"),
            (r'@er_review_app\.command\("list"\)', "`er review list`"),
            (r'@er_review_app\.command\("decide"\)', "`er review decide`"),
        ),
    )


def check_24() -> str | None:
    relative = "docs/ENTITY_RESOLUTION.md"
    if (reason := _missing(relative)) is not None:
        return reason
    headings = " ".join(re.findall(r"^#+ (.+)$", _read(relative), re.MULTILINE)).lower()
    absent = [stage for stage in ER_STAGES if stage not in headings]
    return f"{relative} headings name no {', '.join(absent)} stage" if absent else None


def check_25() -> str | None:
    return _missing("tests/integration/test_entity_resolution.py")


def check_26() -> str | None:
    return _missing(f"{PACKAGE}/api/routes/cases.py", f"{PACKAGE}/api/routes/coverage.py")


def check_27() -> str | None:
    if (reason := _missing("docs/openapi.json")) is not None:
        return reason
    # Later phases add paths; this required check asserts only that every
    # Phase 2 path is still served (verify_phase01 finding 4.2 applied
    # forward). The exact current set is tests/unit/test_openapi.py's job.
    paths = set(json.loads(_read("docs/openapi.json")).get("paths", {}))
    if absent := sorted(OPENAPI_PATHS - paths):
        return f"openapi.json lacks Phase 2 paths {absent}"
    return None


def check_28() -> str | None:
    if (reason := _missing("docs/openapi.json")) is not None:
        return reason
    found = sorted(set(RESTRICTED_NAMES) & _dict_keys(json.loads(_read("docs/openapi.json"))))
    return f"openapi.json names restricted properties {found}" if found else None


def check_29() -> str | None:
    relative = f"{PACKAGE}/schemas/common.py"
    if (reason := _missing(relative)) is not None:
        return reason
    match = re.search(r"^class Provenance\b.*?(?=^class |\Z)", _read(relative), re.M | re.S)
    if match is None:
        return f"{relative} lacks Provenance"
    if re.search(r"^\s+synthetic\s*:\s*bool", match.group(0), re.MULTILINE) is None:
        return "Provenance has no `synthetic: bool` field"
    return _missing(f"{PACKAGE}/schemas/cases.py", f"{PACKAGE}/schemas/coverage.py")


def check_30() -> str | None:
    return _missing(
        "web/app/cases/[caseId]/page.tsx",
        "web/app/judges/[judgeId]/cases/page.tsx",
        "web/components/synthetic-banner.tsx",
    )


def check_31() -> str | None:
    return _lacks("web/app/layout.tsx", r"<SyntheticBanner\b", "<SyntheticBanner />")


def check_32() -> str | None:
    return _lacks("web/tests/e2e/smoke.spec.ts", r"/cases/", "a `/cases/` scenario")


def check_33() -> str | None:
    if (reason := _missing(".github/workflows/ci.yml")) is not None:
        return reason
    block = _yaml_job_block(_read(".github/workflows/ci.yml"), "e2e")
    if block is None:
        return "ci.yml has no `e2e` job"
    # Phase 2 ingested the golden fixture; Phase 3 Step 5 switched the job to
    # the seeded demo dataset (`judgemetrics seed`), the same synthetic
    # connector at demo scale. Either satisfies this check.
    if (
        re.search(r"ingest run synthetic --from-fixture tests/fixtures/golden\b", block) is None
        and re.search(r"uv run judgemetrics seed\b", block) is None
    ):
        return "the `e2e` job ingests neither tests/fixtures/golden nor the demo seed"
    # The pepper is a fixed job variable (Phase 2) or generated into $GITHUB_ENV
    # in a step (Phase 3 Step 5); either way the job names it.
    if re.search(r"JUDGEMETRICS_IDENTIFIER_PEPPER[:=]", block) is None:
        return "the `e2e` job sets no JUDGEMETRICS_IDENTIFIER_PEPPER"
    return None


def check_34() -> str | None:
    if (reason := _missing("docs/API.md")) is not None:
        return reason
    text = _read("docs/API.md")
    absent = [path for path in API_DOC_PATHS if f"`{path}`" not in text]
    return f"docs/API.md does not document {', '.join(absent)}" if absent else None


def check_35() -> str | None:
    if (reason := _missing("pyproject.toml")) is not None:
        return reason
    text = _read("pyproject.toml")
    groups = _toml_table(text, "dependency-groups") or ""
    dev = re.search(r"^dev\s*=\s*\[(.*?)^\]", groups, re.MULTILINE | re.DOTALL)
    if dev is None or re.search(r'"hypothesis\b', dev.group(1)) is None:
        return "pyproject.toml dev group does not declare hypothesis"
    options = _toml_table(text, "tool.pytest.ini_options") or ""
    markers = set(re.findall(r'^\s*"(\w+):', options, re.MULTILINE))
    return _check_names(("property", "golden"), markers, "pytest markers")


def check_36() -> str | None:
    return _missing(*(f"tests/property/{name}.py" for name in PROPERTY_TESTS))


def check_37() -> str | None:
    return _missing(*(f"tests/golden/{name}.py" for name in GOLDEN_TESTS))


def check_38() -> str | None:
    if (reason := _missing(".env.example")) is not None:
        return reason
    if "JUDGEMETRICS_TEST_DATABASE_URL" not in _env_example_values():
        return ".env.example does not document JUDGEMETRICS_TEST_DATABASE_URL"
    if (
        reason := _lacks(
            f"{PACKAGE}/config.py", r"^\s+test_database_url\s*:", "`test_database_url`"
        )
    ) is not None:
        return reason
    scripts = sorted(_path("infra/docker/postgres").glob("*.sql"))
    text = "\n".join(path.read_text(encoding="utf-8") for path in scripts)
    if re.search(r"CREATE DATABASE.*judgemetrics_test|judgemetrics_test.*CREATE DATABASE", text):
        return None
    return "no infra/docker/postgres init script creates judgemetrics_test"


def check_39() -> str | None:
    return _lacks(
        f"{GOLDEN_DIR}/README.md",
        r"judgemetrics synthetic generate --seed 7 --scale golden",
        "the regeneration command",
    )


def check_40() -> str | None:
    try:
        tracked = _git_ls_files(*BACKSTOP_TREES)
    except (RuntimeError, subprocess.CalledProcessError):
        tracked = [
            str(path.relative_to(REPO_ROOT)).replace(os.sep, "/")
            for tree in BACKSTOP_TREES
            for path in _path(tree).rglob("*")
            if path.is_file() and "node_modules" not in path.parts
        ]
    for relative in tracked:
        path = _path(relative)
        if relative in SECRET_SCAN_EXCLUDES or not path.is_file():
            continue
        data = path.read_bytes()
        for label, pattern in BACKSTOP_PATTERNS:
            if pattern.search(data):
                return f"{label} in {relative}"
    schema = "web/lib/api/schema.d.ts"
    if (reason := _missing(schema)) is not None:
        return reason
    text = _read(schema)
    found = [name for name in RESTRICTED_NAMES if re.search(rf"\b{name}\b", text)]
    return f"{schema} names restricted columns {found}" if found else None


def check_41() -> str | None:
    return _missing(f"scripts/verify_phase{PHASE}.py")


def check_42() -> str | None:
    return _missing(f"docs/phase{PHASE}-qa-findings.md")


def check_43() -> str | None:
    return _missing(f"docs/phase{PHASE}-roadmap.md")


def check_44() -> str | None:
    relative = ".github/workflows/phase-verify.yml"
    if (reason := _missing(relative)) is not None:
        return reason
    text = _read(relative)
    matrix = re.search(r"phase:\s*\[([^\]]*)\]", text)
    entries = (
        {entry.strip().strip("\"'") for entry in matrix.group(1).split(",")} if matrix else set()
    )
    if PHASE not in entries:
        return f'{relative} matrix does not include "{PHASE}"'
    return _unpinned_uses(relative)


STATIC_CHECKS: tuple[tuple[int, str, CheckFn], ...] = (
    (
        1,
        "synthetic/ has config, rng, wordlists, world, cases, edge_cases, truth, writer, generate",
        check_01,
    ),
    (
        2,
        "synthetic/config.py defines GOLDEN, DEMO, TINY, GENERATOR_VERSION; DEMO meets minimums",
        check_02,
    ),
    (3, "synthetic/ never calls datetime.now, uuid4, os.urandom, or module-level random", check_03),
    (
        4,
        "tests/fixtures/golden holds manifest.json, the nine source CSVs, the truth files",
        check_04,
    ),
    (5, "every sha256 in the golden manifest matches the tracked file", check_05),
    (6, "data/reference/synthetic_offenses.csv exists with its header", check_06),
    (7, "docs/SYNTHETIC_DATA.md names truth_version and GENERATOR_VERSION", check_07),
    (8, "cli.py registers the synthetic group with generate and verify", check_08),
    (9, "ingest/base.py defines the nine case-level drafts", check_09),
    (
        10,
        "ingest/publish.py defines upsert_cases through upsert_justice_events for the runner",
        check_10,
    ),
    (
        11,
        "alembic 0003 creates uq_person_identifier_stable and source_row_id",
        check_11,
    ),
    (
        12,
        "data/reference/case_vocabulary.yaml is versioned; normalization/vocabulary.py exists",
        check_12,
    ),
    (
        13,
        "identifiers.py hash_identifier; config.py identifier_pepper: SecretStr, synthetic_dir",
        check_13,
    ),
    (
        14,
        'ingest/synthetic modules exist, are registered, and set source_type = "synthetic"',
        check_14,
    ),
    (15, ".env.example documents JUDGEMETRICS_IDENTIFIER_PEPPER with a placeholder", check_15),
    (16, "poe task seed exists, the Makefile mirrors it, cli.py registers seed", check_16),
    (
        17,
        "logging.py denylist covers identifier_pepper, value_hash, date_of_birth, full_name",
        check_17,
    ),
    (
        18,
        "entity_resolution/ has the nine framework modules (config through pipeline)",
        check_18,
    ),
    (19, "entity_resolution/scoring.py defines Scorer(Protocol) and StubScorer", check_19),
    (
        20,
        "entity_resolution_thresholds.yaml exists; entity_resolution/config.py MODEL_VERSION",
        check_20,
    ),
    (
        21,
        "alembic 0004_entity_resolution_review creates audit_log and the append-only trigger",
        check_21,
    ),
    (
        22,
        "entity_resolution/rules.py never matches a name alone (guard comment, name_only)",
        check_22,
    ),
    (23, "cli.py registers er run, er review list, er review decide", check_23),
    (
        24,
        "docs/ENTITY_RESOLUTION.md names the deterministic, rules, probabilistic, review stages",
        check_24,
    ),
    (25, "tests/integration/test_entity_resolution.py exists", check_25),
    (26, "api/routes/cases.py and api/routes/coverage.py exist", check_26),
    (27, "docs/openapi.json lists the twelve Phase 2 v1 paths plus health and ready", check_27),
    (28, "docs/openapi.json names no restricted property", check_28),
    (
        29,
        "schemas/common.py Provenance has synthetic; schemas/cases.py and coverage.py exist",
        check_29,
    ),
    (30, "web case page, judge cases page, and synthetic-banner component exist", check_30),
    (31, "web/app/layout.tsx renders the synthetic banner", check_31),
    (32, "web/tests/e2e/smoke.spec.ts contains a case-page scenario", check_32),
    (
        33,
        "ci.yml e2e job ingests a synthetic dataset and sets JUDGEMETRICS_IDENTIFIER_PEPPER",
        check_33,
    ),
    (34, "docs/API.md documents the case, timeline, judge cases, and coverage endpoints", check_34),
    (35, "pyproject.toml declares hypothesis in dev and the property and golden markers", check_35),
    (
        36,
        "tests/property has the four property modules",
        check_36,
    ),
    (37, "tests/golden has fixture, resolution, counts, and public contract tests", check_37),
    (
        38,
        ".env.example, config.py, and the Postgres init scripts define the scratch test database",
        check_38,
    ),
    (39, "tests/fixtures/golden/README.md names the regeneration command", check_39),
    (
        40,
        "security backstop: no key header, AKIA key, PEM block; no restricted name in schema.d.ts",
        check_40,
    ),
    (41, f"scripts/verify_phase{PHASE}.py exists", check_41),
    (42, f"docs/phase{PHASE}-qa-findings.md exists", check_42),
    (43, f"docs/phase{PHASE}-roadmap.md exists", check_43),
    (44, f'.github/workflows/phase-verify.yml matrix includes "{PHASE}"', check_44),
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
) -> Outcome:
    """Run one tool invocation, streaming its output; PASS on exit 0."""
    executable = tool(argv[0])
    if executable is None:
        return report(Outcome(item_id, description, "FAIL", f"`{argv[0]}` not on PATH"))
    where = "" if cwd == REPO_ROOT else f" (in {cwd.relative_to(REPO_ROOT).as_posix()}/)"
    print(f"\n$ {' '.join(argv)}{where}", flush=True)
    completed = subprocess.run(  # noqa: S603 - fixed argv over PATH, no shell  # nosec B603
        [executable, *argv[1:]], cwd=cwd, check=False
    )
    sys.stdout.flush()
    if completed.returncode == 0:
        return report(Outcome(item_id, description, "PASS"))
    return report(Outcome(item_id, description, "FAIL", f"exit code {completed.returncode}"))


def _configured(variable: str) -> str | None:
    """Where ``variable`` is set from ("environment", ".env"), or None."""
    if os.environ.get(variable):
        return "environment"
    env_file = _path(".env")
    if os.environ.get("JUDGEMETRICS_ENV", "local") == "local" and env_file.is_file():
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            if re.match(rf"\s*{variable}\s*=\s*\S", raw):
                return ".env"
    return None


def database_configured() -> str | None:
    """Where the database suites' URL comes from, or None.

    The scratch test database (`JUDGEMETRICS_TEST_DATABASE_URL`, Step 5) is
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


def pytest_suite(item_id: str, description: str, *targets: str) -> Outcome:
    return run_command(item_id, description, ["uv", "run", "pytest", *targets])


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


def e2e_suite() -> Outcome:
    heading("Playwright (--e2e)")
    api = os.environ.get("NEXT_PUBLIC_API_BASE_URL", "http://localhost:8000").rstrip("/")
    web = os.environ.get("PLAYWRIGHT_BASE_URL", "http://localhost:3000").rstrip("/")
    for base in (api, web):
        if not base.startswith(("http://", "https://")):
            return report(
                Outcome("e2e", "pnpm --dir web e2e", "FAIL", f"not an http(s) URL: {base}")
            )
    if not reachable(f"{api}/api/v1/ready"):
        return report(
            Outcome(
                "e2e",
                "pnpm --dir web e2e",
                "SKIP",
                f"API not ready at {api}/api/v1/ready (start it: uv run poe dev-api; the "
                "database needs the FJC and golden fixtures or the demo seed)",
            )
        )
    if not reachable(f"{web}/methodology"):
        return report(
            Outcome(
                "e2e",
                "pnpm --dir web e2e",
                "SKIP",
                f"web app not serving {web}/methodology (start it: uv run poe dev-web)",
            )
        )
    return pnpm("e2e", "e2e")


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
# --post: the seed idempotency probe, the V1-V6 matrix, and the PR's checks
# --------------------------------------------------------------------------- #


def _seed_counts() -> dict[str, int] | str:
    """Row counts of the probe tables, or the reason they could not be read."""
    uv = tool("uv")
    if uv is None:
        return "`uv` not on PATH"
    completed = subprocess.run(  # noqa: S603 - fixed argv and code, no shell  # nosec B603
        [uv, "run", "python", "-c", SEED_COUNT_SNIPPET, *SEED_PROBE_TABLES],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if completed.returncode != 0:
        return f"count query failed (exit code {completed.returncode})"
    try:
        counts = json.loads(completed.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return "count query printed no JSON"
    return {str(name): int(count) for name, count in counts.items()}


def seed_probe() -> Outcome:
    """V2.4: canonical row counts are unchanged by a second `judgemetrics seed`.

    Runs only against a seeded local database: the default dataset's manifest
    must exist (so the second seed skips generation), the pepper and a
    database URL must be configured, and `court_case` must already hold rows
    (a first seed is an ingest, not an idempotency probe).
    """
    heading("Seed idempotency probe (V2.4)")
    description = "canonical row counts unchanged after a second `judgemetrics seed`"

    def skip(reason: str) -> Outcome:
        return report(Outcome("V2.4", description, "SKIP", reason))

    if not _path(SEED_DATASET_MANIFEST).is_file():
        return skip(f"no seeded dataset at {SEED_DATASET_MANIFEST} (run `uv run poe seed`)")
    if _configured("JUDGEMETRICS_IDENTIFIER_PEPPER") is None:
        return skip("JUDGEMETRICS_IDENTIFIER_PEPPER is not configured")
    if _configured("JUDGEMETRICS_DATABASE_URL") is None:
        return skip("no database: set JUDGEMETRICS_DATABASE_URL or start the Compose services")
    before = _seed_counts()
    if isinstance(before, str):
        return skip(before)
    if before.get("court_case", 0) == 0:
        return skip("the database holds no cases (run `uv run poe seed` first)")
    print("before: " + ", ".join(f"{name}={count}" for name, count in before.items()))
    seed = run_command(
        "V2.4.seed", "uv run judgemetrics seed", ["uv", "run", "judgemetrics", "seed"]
    )
    if seed.failed:
        return report(Outcome("V2.4", description, "FAIL", "the second seed did not succeed"))
    after = _seed_counts()
    if isinstance(after, str):
        return report(Outcome("V2.4", description, "FAIL", after))
    print("after:  " + ", ".join(f"{name}={count}" for name, count in after.items()))
    changed = [
        f"{name} {before[name]} -> {after.get(name)}"
        for name in before
        if after.get(name) != before[name]
    ]
    if changed:
        return report(Outcome("V2.4", description, "FAIL", "; ".join(changed)))
    return report(Outcome("V2.4", description, "PASS"))


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
    return "PASS", ""


def post_matrix(statics: Sequence[Outcome]) -> list[Outcome]:
    """Run every suite the V-checks need once, then report V1.1-V6.4.

    The Playwright suite, the web suites, and the seed probe run before the
    Python suites: on a machine without the scratch test database the golden
    fixture purges the synthetic source from the configured database, which
    the Playwright case flow and the probe both need (verify_phase01 finding
    6.8; with `JUDGEMETRICS_TEST_DATABASE_URL` set the order no longer
    matters).
    """
    checks = pr_checks()
    e2e = e2e_suite()
    node = node_suites()
    probe = seed_probe()
    security = security_suites()
    heading("Suites for V1-V5")
    golden_verify = run_command(
        "V1.3",
        f"judgemetrics synthetic verify {GOLDEN_DIR}",
        ["uv", "run", "judgemetrics", "synthetic", "verify", GOLDEN_DIR],
    )
    generator_unit = pytest_suite(
        "V1.2",
        "test_synthetic_generator.py and test_cli_synthetic.py",
        "tests/unit/test_synthetic_generator.py",
        "tests/unit/test_cli_synthetic.py",
    )
    connector_unit = pytest_suite(
        "V2.2",
        "test_case_numbers.py, test_identifiers.py, test_vocabulary.py, "
        "test_synthetic_connector.py, test_drafts.py",
        "tests/unit/test_case_numbers.py",
        "tests/unit/test_identifiers.py",
        "tests/unit/test_vocabulary.py",
        "tests/unit/test_synthetic_connector.py",
        "tests/unit/test_drafts.py",
    )
    connector_integration = integration_suite(
        "V2.3",
        "test_synthetic_ingest.py and test_migrations.py",
        "tests/integration/test_synthetic_ingest.py",
        "tests/integration/test_migrations.py",
    )
    er_tests = sorted(
        str(p.relative_to(REPO_ROOT)).replace(os.sep, "/")
        for p in _path("tests/unit").glob("test_er_*.py")
    )
    er_unit = (
        pytest_suite("V3.2", "tests/unit/test_er_*.py", *er_tests)
        if er_tests
        else report(Outcome("V3.2", "tests/unit/test_er_*.py", "FAIL", "no test_er_*.py"))
    )
    er_integration = integration_suite(
        "V3.3", "test_entity_resolution.py", "tests/integration/test_entity_resolution.py"
    )
    api_integration = integration_suite(
        "V4.2",
        "test_api_cases.py, test_api_coverage.py, test_api_judges.py, test_api_search.py, "
        "test_query_counts.py, test_openapi.py",
        "tests/integration/test_api_cases.py",
        "tests/integration/test_api_coverage.py",
        "tests/integration/test_api_judges.py",
        "tests/integration/test_api_search.py",
        "tests/integration/test_query_counts.py",
        "tests/unit/test_openapi.py",
    )
    property_suite = integration_suite("V5.2", 'pytest -m "property"', "-m", "property")
    golden_suite = integration_suite("V5.3", 'pytest -m "golden"', "-m", "golden")
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

    static_row("V1.1", 1, 8)
    suite_row("V1.2", "test_synthetic_generator.py and test_cli_synthetic.py pass", generator_unit)
    suite_row("V1.3", f"judgemetrics synthetic verify {GOLDEN_DIR} exits 0", golden_verify)
    static_row("V2.1", 9, 17)
    suite_row(
        "V2.2",
        "test_case_numbers, test_identifiers, test_vocabulary, test_synthetic_connector, "
        "test_drafts pass",
        connector_unit,
    )
    suite_row("V2.3", "test_synthetic_ingest.py and test_migrations.py pass", connector_integration)
    suite_row("V2.4", "seed idempotency probe: row counts unchanged", probe)
    static_row("V3.1", 18, 25)
    suite_row("V3.2", "test_er_*.py unit tests pass", er_unit)
    suite_row("V3.3", "test_entity_resolution.py passes", er_integration)
    static_row("V4.1", 26, 34)
    suite_row(
        "V4.2",
        "test_api_cases, test_api_coverage, test_api_judges, test_api_search, "
        "test_query_counts, test_openapi pass",
        api_integration,
    )
    rows.append(("V4.3", "pnpm lint, typecheck, build, test pass", *suites_outcome(node)))
    rows.append(
        (
            "V4.4",
            "the `container` CI job is green on the current branch",
            *check_bucket(checks, "container"),
        )
    )
    suite_row("V4.5", "pnpm e2e passes (the case scenario)", e2e)
    static_row("V5.1", 35, 39)
    suite_row("V5.2", "pytest -m property passes", property_suite)
    suite_row("V5.3", "pytest -m golden passes", golden_suite)
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
    matrix = next(o for o in statics if o.id == "44")
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
        "--post", action="store_true", help="static + V1-V6 matrix + seed probe + gh pr checks"
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
        # The Playwright suite precedes the Python suites in --all for the
        # reason given in post_matrix: without the scratch test database the
        # golden fixture purges the synthetic source the case flow needs.
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
