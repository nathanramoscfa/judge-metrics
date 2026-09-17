# scripts/verify_phase01.py
"""Phase 1 verification: static deliverable checks, tool suites, and the V1-V6 matrix.

Modes are mutually exclusive; with no flag the script runs ``--fast`` plus
``--py``:

  --fast      the 43 static checks only (CI-safe on Ubuntu and Windows,
              well under 30 seconds: pathlib, re, json, and ``git ls-files``)
  --py        static + ruff, ruff format --check, mypy, the unit suite, and
              the integration suite when a database is configured
  --node      static + pnpm lint, typecheck, build, test in web/
  --e2e       static + the Playwright smoke test (skips with a reason when
              the API or the web app is not reachable)
  --security  the gate over the phase's surface: detect-secrets against the
              baseline, bandit, pip-audit over uv.lock, pnpm audit
  --all       static + py + node + e2e + security
  --post      static + the V1-V6 matrix of docs/phase01-roadmap.md, plus
              ``gh pr checks`` for the current branch when gh is signed in

Every static check is independent and reads the repository only; it prints
``[PASS] NN description`` or ``[FAIL] NN description — reason``. Suites are
subprocesses with argument lists (never a shell) over tools resolved on
PATH (``uv``, ``pnpm``, ``gh``, ``git``). The script prints check names,
paths, and tool output; it never prints repository file contents. Exit 0
when nothing failed, 1 otherwise. Runs unmodified on Windows and Ubuntu.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import subprocess
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
PHASE = "01"

Status = Literal["PASS", "FAIL", "SKIP"]
CheckFn = Callable[[], str | None]  # None on success, otherwise the failure reason

CANONICAL_TABLES = (
    "jurisdiction",
    "court",
    "judge",
    "judge_service",
    "person",
    "person_identifier",
    "court_case",
    "case_party",
    "judge_assignment",
    "charge",
    "court_event",
    "decision",
    "pretrial_release",
    "sentence",
    "justice_event",
    "source",
    "source_record",
    "ingest_run",
    "entity_resolution_candidate",
    "metric_definition",
    "metric_observation",
    "data_quality_issue",
    "correction_request",
)
OPENAPI_PATHS = {
    "/api/v1/health",
    "/api/v1/ready",
    "/api/v1/judges",
    "/api/v1/judges/{judge_id}",
    "/api/v1/judges/{judge_id}/service",
    "/api/v1/courts",
    "/api/v1/courts/{court_id}",
    "/api/v1/jurisdictions",
    "/api/v1/jurisdictions/{jurisdiction_id}",
    "/api/v1/search",
}
GATE_TOOLS = ("ruff", "mypy", "bandit", "detect-secrets", "pip-audit")
WEB_SCRIPTS = ("lint", "typecheck", "test", "build", "e2e", "generate:api")
SHA_PIN = re.compile(r"@[0-9a-f]{40}$")
# Shapes that would indicate a real credential was pasted into .env.example
# (the same list as tests/unit/test_repo_hygiene.py).
SECRET_SHAPES = (
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)ghp_[0-9a-z]{36}"),
    re.compile(r"(?i)sk-[0-9a-z]{20,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"[0-9a-f]{32,}"),
    re.compile(r"[A-Za-z0-9+/]{40,}={0,2}"),
)
# The security backstop (check 39): a PEM private-key header, an AWS access
# key id, or any PEM block header in the phase's source, web, test, doc,
# and infra trees. Bytes patterns so binary files (screenshots) are scanned
# too without decoding.
BACKSTOP_PATTERNS = (
    ("private-key header", re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("AKIA-style access key", re.compile(rb"AKIA[0-9A-Z]{16}")),
    ("PEM block", re.compile(rb"-----BEGIN [A-Z ]+-----")),
)
BACKSTOP_TREES = ("src", "web", "tests", "docs", "infra")
# Lockfiles carry integrity hashes, not credentials (the pre-commit hook's
# exclude pattern); the baseline is the scanner's own state.
SECRET_SCAN_EXCLUDES = ("uv.lock", "web/pnpm-lock.yaml", ".secrets.baseline")
# Longest argv (in characters) handed to detect-secrets-hook per call; well
# under the Windows command-line limit.
ARGV_BUDGET = 20_000


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
# Static-check helpers (pathlib, re, json, and `git ls-files` only)
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


def _git_ls_files(*pathspecs: str) -> list[str]:
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git not on PATH")
    completed = subprocess.run(  # noqa: S603 - fixed argv, no shell
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


def _poe_tasks() -> set[str]:
    text = _read("pyproject.toml")
    match = re.search(r"^\[tool\.poe\.tasks\]\n(.*?)(?=^\[|\Z)", text, re.MULTILINE | re.DOTALL)
    if match is None:
        return set()
    return set(re.findall(r'^"?([A-Za-z][\w-]*)"?\s*=', match.group(1), re.MULTILINE))


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


# --------------------------------------------------------------------------- #
# Static checks 1-43
# --------------------------------------------------------------------------- #


def check_01() -> str | None:
    return _lacks("LICENSE", r"Apache License", '"Apache License"')


def check_02() -> str | None:
    return _missing("CONTRIBUTING.md", "SECURITY.md", "CODE_OF_CONDUCT.md")


def check_03() -> str | None:
    return _missing(
        ".github/PULL_REQUEST_TEMPLATE.md",
        ".github/ISSUE_TEMPLATE/bug_report.md",
        ".github/ISSUE_TEMPLATE/feature_request.md",
        ".github/ISSUE_TEMPLATE/data_source_issue.md",
    )


def check_04() -> str | None:
    if (reason := _missing(".pre-commit-config.yaml")) is not None:
        return reason
    text = _read(".pre-commit-config.yaml")
    absent = [tool for tool in GATE_TOOLS if tool not in text]
    return f".pre-commit-config.yaml does not name {', '.join(absent)}" if absent else None


def check_05() -> str | None:
    return _missing(".secrets.baseline")


def _unpinned_uses(relative: str) -> str | None:
    if (reason := _missing(relative)) is not None:
        return reason
    uses = re.findall(r"^\s*-?\s*uses:\s*(\S+)", _read(relative), re.MULTILINE)
    if not uses:
        return f"{relative} has no `uses:` lines"
    unpinned = [ref for ref in uses if SHA_PIN.search(ref) is None]
    return f"{relative} has unpinned actions: {', '.join(unpinned)}" if unpinned else None


def check_06() -> str | None:
    return _unpinned_uses(".github/workflows/ci.yml")


def check_07() -> str | None:
    if (reason := _missing(".github/workflows/ci.yml")) is not None:
        return reason
    text = _read(".github/workflows/ci.yml")
    if re.search(r"^permissions:", text, re.MULTILINE) is None:
        return "ci.yml declares no top-level `permissions:`"
    block = _yaml_job_block(text, "test")
    if block is None:
        return "ci.yml has no `test` job"
    if re.search(r"^\s+if:\s*always\(\)", block, re.MULTILINE) is None:
        return "the `test` job lacks `if: always()`"
    return None


def check_08() -> str | None:
    if (reason := _missing("docker-compose.yml")) is not None:
        return reason
    text = _read("docker-compose.yml")
    absent = [svc for svc in ("postgres", "minio") if f"\n  {svc}:" not in text]
    if absent:
        return f"docker-compose.yml lacks services {', '.join(absent)}"
    if (reason := _missing("infra/docker/postgres/02-roles.sql")) is not None:
        return reason
    return _lacks("infra/docker/postgres/01-extensions.sql", r"pg_trgm", "pg_trgm")


def check_09() -> str | None:
    if (reason := _missing(".env.example")) is not None:
        return reason
    for key, value in _env_example_values().items():
        for shape in SECRET_SHAPES:
            if shape.search(value):
                return f".env.example value for {key} matches a secret shape"
    if _git_ls_files(".env"):
        return ".env is tracked by git"
    return None


def check_10() -> str | None:
    if (reason := _missing("pyproject.toml", "Makefile")) is not None:
        return reason
    wanted = ("up", "down", "check", "gate")
    return _check_names(wanted, _poe_tasks(), "[tool.poe.tasks]") or _check_names(
        wanted, _makefile_targets(), "Makefile"
    )


def check_11() -> str | None:
    if (reason := _missing(".github/dependabot.yml")) is not None:
        return reason
    ecosystems = set(
        re.findall(r"package-ecosystem:\s*\"?([\w-]+)", _read(".github/dependabot.yml"))
    )
    return _check_names(("uv", "github-actions"), ecosystems, "dependabot.yml ecosystems")


def check_12() -> str | None:
    return _lacks(f"{PACKAGE}/config.py", r"^class Settings\(", "class Settings") or _lacks(
        f"{PACKAGE}/config.py", r'"JUDGEMETRICS_"', 'the "JUDGEMETRICS_" env prefix'
    )


def check_13() -> str | None:
    return _lacks(f"{PACKAGE}/logging.py", r"^def scrub_sensitive\(", "scrub_sensitive")


def check_14() -> str | None:
    return _lacks(f"{PACKAGE}/main.py", r"^def create_app\(", "create_app")


def check_15() -> str | None:
    relative = f"{PACKAGE}/api/routes/health.py"
    return _lacks(relative, r'"/health"', "/health") or _lacks(relative, r'"/ready"', "/ready")


def check_16() -> str | None:
    versions = sorted(_path("alembic/versions").glob("*.py"))
    if not versions:
        return "alembic/versions has no migration"
    text = "\n".join(path.read_text(encoding="utf-8") for path in versions)
    if "pg_trgm" not in text:
        return "no migration creates pg_trgm"
    created = set(re.findall(r'op\.create_table\(\s*"(\w+)"', text))
    return _check_names(CANONICAL_TABLES, created, "migrations create_table")


def check_17() -> str | None:
    modules = sorted(_path(f"{PACKAGE}/db/models").glob("*.py"))
    if not modules:
        return f"{PACKAGE}/db/models has no modules"
    text = "\n".join(path.read_text(encoding="utf-8") for path in modules)
    tables = set(re.findall(r'__tablename__\s*=\s*"(\w+)"', text))
    return _check_names(CANONICAL_TABLES, tables, "db/models __tablename__")


def check_18() -> str | None:
    if (reason := _missing("infra/docker/api.Dockerfile")) is not None:
        return reason
    return _lacks("docker-compose.yml", r"^  api:", "an `api` service")


def check_19() -> str | None:
    if (reason := _missing(".github/workflows/ci.yml")) is not None:
        return reason
    block = _yaml_job_block(_read(".github/workflows/ci.yml"), "container")
    if block is None:
        return "ci.yml has no `container` job"
    if "docker build" not in block:
        return "the `container` job builds no image"
    if "trivy" not in block.lower():
        return "the `container` job scans no image"
    return None


def check_20() -> str | None:
    return _check_names(("migrate", "dev-api"), _poe_tasks(), "[tool.poe.tasks]")


def check_21() -> str | None:
    return _lacks(f"{PACKAGE}/ingest/base.py", r"^class SourceConnector\(", "SourceConnector")


def check_22() -> str | None:
    relative = f"{PACKAGE}/ingest/store.py"
    return _lacks(
        relative, r"^class FilesystemRawObjectStore\b", "FilesystemRawObjectStore"
    ) or _lacks(relative, r"^class S3RawObjectStore\b", "S3RawObjectStore")


def check_23() -> str | None:
    return _lacks(f"{PACKAGE}/ingest/runner.py", r"^def run_ingest\(", "run_ingest")


def check_24() -> str | None:
    return _lacks(
        f"{PACKAGE}/ingest/fjc/connector.py", r'source_id\s*=\s*"fjc"', 'source id "fjc"'
    ) or _check_names(("ingest-fjc",), _poe_tasks(), "[tool.poe.tasks]")


def check_25() -> str | None:
    if (
        reason := _missing(
            "tests/fixtures/fjc/judges.csv",
            "tests/fixtures/fjc/federal-judicial-service.csv",
            "tests/fixtures/fjc/README.md",
        )
    ) is not None:
        return reason
    return _lacks(
        "tests/fixtures/fjc/README.md",
        r"Retrieved:?\*?\*?\s*\d{4}-\d{2}-\d{2}",
        "a retrieval date",
    )


def check_26() -> str | None:
    return _missing("docs/ARCHITECTURE.md", "docs/DATA_MODEL.md", "data/README.md")


def check_27() -> str | None:
    if (reason := _missing("docs/DATA_SOURCES.md")) is not None:
        return reason
    match = re.search(
        r"^## `fjc`.*?(?=^## |\Z)", _read("docs/DATA_SOURCES.md"), re.MULTILINE | re.DOTALL
    )
    if match is None:
        return "docs/DATA_SOURCES.md has no `fjc` entry"
    entry = match.group(0)
    if re.search(r"Headers \(verified \d{4}-\d{2}-\d{2}", entry) is None:
        return "the `fjc` entry lists no verified headers"
    absent = [f for f in ("judges.csv", "federal-judicial-service.csv", "`nid`") if f not in entry]
    return f"the `fjc` headers omit {', '.join(absent)}" if absent else None


def check_28() -> str | None:
    return _missing(
        *(
            f"{PACKAGE}/api/routes/{name}.py"
            for name in ("judges", "courts", "jurisdictions", "search")
        )
    )


def check_29() -> str | None:
    if (reason := _missing("docs/openapi.json")) is not None:
        return reason
    document = json.loads(_read("docs/openapi.json"))
    paths = set(document.get("paths", {}))
    if paths != OPENAPI_PATHS:
        extra = sorted(paths - OPENAPI_PATHS)
        absent = sorted(OPENAPI_PATHS - paths)
        return f"openapi.json paths differ (missing {absent}, unexpected {extra})"
    return None


def check_30() -> str | None:
    relative = f"{PACKAGE}/schemas/common.py"
    return _lacks(relative, r"^class Page\b", "Page") or _lacks(
        relative, r"^class Provenance\b", "Provenance"
    )


def check_31() -> str | None:
    if (reason := _missing(f"{PACKAGE}/api/ratelimit.py")) is not None:
        return reason
    text = _read(f"{PACKAGE}/config.py")
    wanted = (
        "search_rate_limit_per_minute",
        "search_rate_limit_burst",
        "search_rate_limit_enabled",
    )
    found = {name for name in wanted if re.search(rf"^\s+{name}\s*:", text, re.MULTILINE)}
    return _check_names(wanted, found, "config.py settings")


def check_32() -> str | None:
    if (reason := _missing("docs/API.md", "tests/integration/test_query_counts.py")) is not None:
        return reason
    api_tests = sorted(_path("tests/integration").glob("test_api_*.py"))
    return None if api_tests else "tests/integration has no test_api_*.py"


def check_33() -> str | None:
    if (reason := _missing("web/package.json")) is not None:
        return reason
    scripts = json.loads(_read("web/package.json")).get("scripts", {})
    return _check_names(WEB_SCRIPTS, set(scripts), "web/package.json scripts")


def check_34() -> str | None:
    return _missing("web/lib/api/schema.d.ts", "web/lib/api/client.ts")


def check_35() -> str | None:
    return _missing("web/app/judges/[judgeId]/page.tsx", "web/app/methodology/page.tsx")


def check_36() -> str | None:
    return _missing("web/tests/e2e/smoke.spec.ts")


def check_37() -> str | None:
    if (reason := _missing(".github/workflows/ci.yml")) is not None:
        return reason
    text = _read(".github/workflows/ci.yml")
    test_block = _yaml_job_block(text, "test")
    if test_block is None:
        return "ci.yml has no `test` job"
    needs = re.search(r"needs:\s*\[([^\]]*)\]", test_block)
    needed = {name.strip() for name in needs.group(1).split(",")} if needs else set()
    if (reason := _check_names(("web", "e2e"), needed, "the `test` job's needs")) is not None:
        return reason
    container = _yaml_job_block(text, "container")
    if container is None or "web.Dockerfile" not in container:
        return "the `container` job does not build the web image"
    return None


def check_38() -> str | None:
    return _missing("infra/docker/web.Dockerfile") or _check_names(
        ("dev-web",), _poe_tasks(), "[tool.poe.tasks]"
    )


def check_39() -> str | None:
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
    return None


def check_40() -> str | None:
    return _missing(f"scripts/verify_phase{PHASE}.py")


def check_41() -> str | None:
    return _missing(f"docs/phase{PHASE}-qa-findings.md")


def check_42() -> str | None:
    return _missing(f"docs/phase{PHASE}-roadmap.md")


def check_43() -> str | None:
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
    (1, 'LICENSE exists and contains "Apache License"', check_01),
    (2, "CONTRIBUTING.md, SECURITY.md, CODE_OF_CONDUCT.md exist", check_02),
    (3, "pull-request template and the three issue templates exist", check_03),
    (4, ".pre-commit-config.yaml names ruff, mypy, bandit, detect-secrets, pip-audit", check_04),
    (5, ".secrets.baseline exists", check_05),
    (6, "ci.yml: every `uses:` is pinned to a 40-hex SHA", check_06),
    (7, "ci.yml declares top-level permissions and a `test` job with `if: always()`", check_07),
    (
        8,
        "docker-compose.yml defines postgres and minio; pg_trgm and roles init scripts exist",
        check_08,
    ),
    (9, ".env.example exists with placeholder values only; .env is not tracked", check_09),
    (10, "poe tasks up, down, check, gate exist and the Makefile mirrors them", check_10),
    (11, "dependabot.yml covers uv and github-actions", check_11),
    (12, "config.py defines Settings with env prefix JUDGEMETRICS_", check_12),
    (13, "logging.py defines scrub_sensitive", check_13),
    (14, "main.py defines create_app", check_14),
    (15, "api/routes/health.py declares /health and /ready", check_15),
    (16, "alembic/versions baseline creates pg_trgm and every canonical table", check_16),
    (17, "db/models modules define all twenty-three entities", check_17),
    (18, "infra/docker/api.Dockerfile exists and compose defines api", check_18),
    (19, "ci.yml has a `container` job that builds and scans images", check_19),
    (20, "poe tasks migrate and dev-api exist", check_20),
    (21, "ingest/base.py defines SourceConnector", check_21),
    (22, "ingest/store.py defines FilesystemRawObjectStore and S3RawObjectStore", check_22),
    (23, "ingest/runner.py defines run_ingest", check_23),
    (24, 'ingest/fjc/connector.py registers source id "fjc"; poe task ingest-fjc exists', check_24),
    (25, "tests/fixtures/fjc holds both CSVs and a README with a retrieval date", check_25),
    (26, "docs/ARCHITECTURE.md, docs/DATA_MODEL.md, data/README.md exist", check_26),
    (27, "docs/DATA_SOURCES.md `fjc` entry lists verified headers", check_27),
    (28, "api/routes judges, courts, jurisdictions, search exist", check_28),
    (29, "docs/openapi.json lists the eight v1 paths plus health and ready", check_29),
    (30, "schemas/common.py defines Page and Provenance", check_30),
    (31, "api/ratelimit.py exists and config.py defines the search rate-limit settings", check_31),
    (32, "docs/API.md, tests/integration/test_api_*.py, test_query_counts.py exist", check_32),
    (33, "web/package.json declares lint, typecheck, test, build, e2e, generate:api", check_33),
    (34, "web/lib/api/schema.d.ts and client.ts exist", check_34),
    (35, "web/app/judges/[judgeId]/page.tsx and web/app/methodology/page.tsx exist", check_35),
    (36, "web/tests/e2e/smoke.spec.ts exists", check_36),
    (37, "ci.yml `test` needs web and e2e; the `container` job builds the web image", check_37),
    (38, "infra/docker/web.Dockerfile exists; poe task dev-web exists", check_38),
    (39, "security backstop: no private-key header, AKIA key, or PEM block in the trees", check_39),
    (40, f"scripts/verify_phase{PHASE}.py exists", check_40),
    (41, f"docs/phase{PHASE}-qa-findings.md exists", check_41),
    (42, f"docs/phase{PHASE}-roadmap.md exists", check_42),
    (43, f'.github/workflows/phase-verify.yml matrix includes "{PHASE}"', check_43),
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
    completed = subprocess.run(  # noqa: S603 - fixed argv over PATH-resolved tools, no shell
        [executable, *argv[1:]], cwd=cwd, check=False
    )
    sys.stdout.flush()
    if completed.returncode == 0:
        return report(Outcome(item_id, description, "PASS"))
    return report(Outcome(item_id, description, "FAIL", f"exit code {completed.returncode}"))


def database_configured() -> str | None:
    """Where the integration suite's database URL comes from, or None."""
    if os.environ.get("JUDGEMETRICS_DATABASE_URL"):
        return "environment"
    env_file = _path(".env")
    if os.environ.get("JUDGEMETRICS_ENV", "local") == "local" and env_file.is_file():
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            if re.match(r"\s*JUDGEMETRICS_DATABASE_URL\s*=\s*\S", raw):
                return ".env"
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
                "no database: set JUDGEMETRICS_DATABASE_URL or start the Compose services",
            )
        )
    print(f"(database URL from {source})", flush=True)
    return pytest_suite(item_id, description, *targets)


def py_suites() -> list[Outcome]:
    heading("Python suites (--py)")
    outcomes = [
        run_command("py.lint", "uv run poe lint", ["uv", "run", "poe", "lint"]),
        run_command("py.fmt", "uv run poe fmt-check", ["uv", "run", "poe", "fmt-check"]),
        run_command("py.types", "uv run poe typecheck", ["uv", "run", "poe", "typecheck"]),
        pytest_suite("py.unit", 'uv run pytest -m "not integration"', "-m", "not integration"),
        integration_suite("py.integration", "uv run pytest -m integration", "-m", "integration"),
    ]
    return outcomes


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
        with urllib.request.urlopen(url, timeout=5) as response:  # noqa: S310
            return 200 <= int(response.status) < 400
    except (urllib.error.URLError, OSError, ValueError):
        return False


def e2e_suite() -> Outcome:
    heading("Playwright smoke (--e2e)")
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
                f"API not ready at {api}/api/v1/ready (start it: uv run poe dev-api)",
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
    print(
        f"\n$ uv run detect-secrets-hook --baseline .secrets.baseline <{sum(map(len, batches))} files>"
    )
    for batch in batches:
        completed = subprocess.run(  # noqa: S603 - fixed argv over PATH-resolved tools, no shell
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
            "bandit -c pyproject.toml -r src alembic",
            ["uv", "run", "bandit", "-c", "pyproject.toml", "-r", "src", "alembic", "-q"],
        ),
        run_command(
            "sec.pip-audit",
            "pip-audit --strict over uv.lock (scripts/audit_deps.py)",
            ["uv", "run", "python", "scripts/audit_deps.py"],
        ),
        pnpm("sec.pnpm-audit", "audit", "--audit-level=high"),
    ]


# --------------------------------------------------------------------------- #
# --post: the V1-V6 matrix and the pull request's checks
# --------------------------------------------------------------------------- #


def pr_checks() -> dict[str, str] | None:
    """Check name → bucket for the current branch's PR, or None when unavailable."""
    gh = tool("gh")
    if gh is None:
        print("gh not on PATH; PR checks unavailable", flush=True)
        return None
    auth = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [gh, "auth", "status"], cwd=REPO_ROOT, capture_output=True, check=False
    )
    if auth.returncode != 0:
        print("gh is not signed in; PR checks unavailable", flush=True)
        return None
    checks = subprocess.run(  # noqa: S603 - fixed argv, no shell
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
    """Run every suite the V-checks need once, then report V1.1-V6.4."""
    checks = pr_checks()
    security = security_suites()
    heading("Suites for V1-V5")
    hygiene = pytest_suite(
        "V1.2", "tests/unit/test_repo_hygiene.py", "tests/unit/test_repo_hygiene.py"
    )
    core_unit = pytest_suite(
        "V2.2",
        "test_settings.py, test_logging.py, test_names.py",
        "tests/unit/test_settings.py",
        "tests/unit/test_logging.py",
        "tests/unit/test_names.py",
    )
    core_integration = integration_suite(
        "V2.3",
        "test_migrations.py and test_health.py",
        "tests/integration/test_migrations.py",
        "tests/integration/test_health.py",
    )
    ingest_unit = pytest_suite(
        "V3.2",
        "test_store.py, test_fjc_normalize.py, test_quality_checks.py",
        "tests/unit/test_store.py",
        "tests/unit/test_fjc_normalize.py",
        "tests/unit/test_quality_checks.py",
    )
    ingest_integration = integration_suite(
        "V3.3", "test_fjc_ingest.py (idempotency)", "tests/integration/test_fjc_ingest.py"
    )
    api_tests = sorted(
        str(p.relative_to(REPO_ROOT)).replace(os.sep, "/")
        for p in _path("tests/integration").glob("test_api_*.py")
    )
    api_integration = integration_suite(
        "V4.2",
        "test_api_*.py and test_query_counts.py",
        *api_tests,
        "tests/integration/test_query_counts.py",
    )
    openapi = pytest_suite("V4.3", "OpenAPI snapshot test", "tests/unit/test_openapi.py")
    node = node_suites()
    e2e = e2e_suite()
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
    suite_row("V1.2", "tests/unit/test_repo_hygiene.py passes", hygiene)
    rows.append(("V1.3", "--security exits 0", security_status, security_reason))
    static_row("V2.1", 12, 20)
    suite_row("V2.2", "test_settings.py, test_logging.py, test_names.py pass", core_unit)
    suite_row("V2.3", "test_migrations.py and test_health.py pass", core_integration)
    rows.append(
        (
            "V2.4",
            "the `container` CI job is green on the current branch",
            *check_bucket(checks, "container"),
        )
    )
    static_row("V3.1", 21, 27)
    suite_row(
        "V3.2", "test_store.py, test_fjc_normalize.py, test_quality_checks.py pass", ingest_unit
    )
    suite_row("V3.3", "test_fjc_ingest.py passes (idempotency)", ingest_integration)
    static_row("V4.1", 28, 32)
    suite_row("V4.2", "test_api_*.py and test_query_counts.py pass", api_integration)
    suite_row("V4.3", "OpenAPI snapshot test passes", openapi)
    static_row("V5.1", 33, 38)
    rows.append(("V5.2", "pnpm lint, typecheck, test, build pass", *suites_outcome(node)))
    suite_row("V5.3", "pnpm e2e passes", e2e)
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
    matrix = next(o for o in statics if o.id == "43")
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
    modes.add_argument("--e2e", action="store_true", help="static + Playwright smoke")
    modes.add_argument("--security", action="store_true", help="secret scan + SAST + audits")
    modes.add_argument("--all", action="store_true", help="static + py + node + e2e + security")
    modes.add_argument("--post", action="store_true", help="static + V1-V6 matrix + gh pr checks")
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
        if mode in ("py", "default (fast + py)", "all"):
            outcomes.extend(py_suites())
        if mode in ("node", "all"):
            outcomes.extend(node_suites())
        if mode in ("e2e", "all"):
            outcomes.append(e2e_suite())
        if mode == "all":
            outcomes.extend(security_suites())
        if mode == "post":
            outcomes.extend(post_matrix(statics))
    return summary(mode, outcomes, time.perf_counter() - started)


if __name__ == "__main__":
    raise SystemExit(main())
