# tests/unit/test_repo_hygiene.py
"""Repository hygiene: the governance chassis from Phase 1 Step 1 stays intact.

These tests read the repository's own files, so they guard the license,
community files, placeholder-only `.env.example`, the pre-commit gate, the
SHA-pinned least-privilege CI workflow, the Compose services, and the
agreement between the poe tasks and the Makefile shim.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]

# Values in `.env.example` that are allowed as-is: non-secret constants.
NON_SECRET_CONSTANTS = {
    "local",
    "console",
    "json",
    "judgemetrics",
    "judgemetrics-raw",
    "s3://judgemetrics-raw",
    "http://localhost:9000",
    "5432",
    "9000",
    "9001",
}
# Shapes that would indicate a real credential was pasted in.
SECRET_SHAPES = [
    re.compile(r"AKIA[0-9A-Z]{16}"),  # AWS access key id
    re.compile(r"(?i)ghp_[0-9a-z]{36}"),  # GitHub token
    re.compile(r"(?i)sk-[0-9a-z]{20,}"),  # generic API key
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"[0-9a-f]{32,}"),  # long hex (hashes, tokens)
    re.compile(r"[A-Za-z0-9+/]{40,}={0,2}"),  # long base64
]
GATE_TOOLS = ("ruff", "mypy", "bandit", "detect-secrets", "pip-audit")
SHARED_TARGETS = ("up", "down", "check", "test", "lint", "typecheck", "gate")
SHA_PIN = re.compile(r"@[0-9a-f]{40}$")


def _read(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def _yaml(relative: str) -> Any:
    return yaml.safe_load(_read(relative))


def _pyproject() -> dict[str, Any]:
    return tomllib.loads(_read("pyproject.toml"))


def _env_example_values() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in _read(".env.example").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, _, value = line.partition("=")
        # Docker Compose treats " #" after an unquoted value as a comment.
        value = value.split(" #", 1)[0]
        values[key.strip()] = value.strip()
    return values


def test_license_exists_and_is_apache() -> None:
    text = _read("LICENSE")
    assert "Apache License" in text
    assert "Version 2.0, January 2004" in text
    project = _pyproject()["project"]
    assert project["license"] == "Apache-2.0"
    assert project["license-files"] == ["LICENSE"]


@pytest.mark.parametrize(
    "relative",
    [
        "CONTRIBUTING.md",
        "SECURITY.md",
        "CODE_OF_CONDUCT.md",
        ".github/ISSUE_TEMPLATE/bug_report.md",
        ".github/ISSUE_TEMPLATE/feature_request.md",
        ".github/ISSUE_TEMPLATE/data_source_issue.md",
        ".github/PULL_REQUEST_TEMPLATE.md",
    ],
)
def test_community_files_exist(relative: str) -> None:
    path = REPO_ROOT / relative
    assert path.is_file(), relative
    assert path.stat().st_size > 0, relative


def test_security_policy_points_at_private_disclosure() -> None:
    text = _read("SECURITY.md")
    assert "security/advisories" in text
    assert "Do not open a public issue" in text


def test_pull_request_template_sections() -> None:
    text = _read(".github/PULL_REQUEST_TEMPLATE.md")
    for section in (
        "## Roadmap step",
        "## Summary",
        "## Test plan",
        "## Screenshots (UI)",
        "## Breaking changes",
        "## Rollback plan",
        "## Security gate",
        "## Definition of done",
        "## Issues opened",
    ):
        assert section in text, section


def test_env_example_has_only_placeholders() -> None:
    values = _env_example_values()
    expected_keys = {
        "JUDGEMETRICS_ENV",
        "JUDGEMETRICS_DATABASE_URL",
        "JUDGEMETRICS_RAW_STORE_URL",
        "JUDGEMETRICS_S3_ENDPOINT_URL",
        "JUDGEMETRICS_S3_ACCESS_KEY_ID",
        "JUDGEMETRICS_S3_SECRET_ACCESS_KEY",
        "JUDGEMETRICS_LOG_FORMAT",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "JUDGEMETRICS_APP_DB_PASSWORD",
        "JUDGEMETRICS_INGEST_DB_PASSWORD",
        "JUDGEMETRICS_ADMIN_DB_PASSWORD",
        "MINIO_ROOT_USER",
        "MINIO_ROOT_PASSWORD",
    }
    assert expected_keys <= values.keys(), expected_keys - values.keys()
    for key, value in values.items():
        assert value, f"{key} has no value"
        for shape in SECRET_SHAPES:
            assert not shape.search(value), f"{key} looks like a real secret"
        is_placeholder = value == "change-me"
        is_placeholder_url = "://" in value and ":change-me@" in value
        assert is_placeholder or is_placeholder_url or value in NON_SECRET_CONSTANTS, (
            f"{key}={value!r} is neither a change-me placeholder nor a known constant"
        )
    for key in ("POSTGRES_PASSWORD", "MINIO_ROOT_PASSWORD", "JUDGEMETRICS_S3_SECRET_ACCESS_KEY"):
        assert values[key] == "change-me", key


def test_no_dotenv_is_tracked() -> None:
    gitignore = _read(".gitignore").splitlines()
    assert ".env" in gitignore
    assert "!.env.example" in gitignore


def test_precommit_config_lists_gate_checks() -> None:
    config = _yaml(".pre-commit-config.yaml")
    hook_ids: list[str] = []
    entries: list[str] = []
    for repo in config["repos"]:
        for hook in repo["hooks"]:
            hook_ids.append(hook["id"])
            entries.append(hook.get("entry", ""))
    joined = " ".join(hook_ids + entries)
    for tool in GATE_TOOLS:
        assert tool in joined, f"{tool} missing from the pre-commit gate"
    local_hooks = {
        hook["id"]: hook
        for repo in config["repos"]
        if repo["repo"] == "local"
        for hook in repo["hooks"]
    }
    assert local_hooks["pip-audit"]["stages"] == ["pre-push"]
    assert local_hooks["mypy"]["pass_filenames"] is False
    assert "--baseline .secrets.baseline" in local_hooks["detect-secrets"]["entry"]
    assert (REPO_ROOT / ".secrets.baseline").is_file()
    for repo in config["repos"]:
        if repo["repo"] != "local":
            assert re.fullmatch(r"[0-9a-f]{40}", repo["rev"]), repo["repo"]


def test_ci_actions_are_sha_pinned() -> None:
    workflow = _yaml(".github/workflows/ci.yml")
    uses: list[str] = []
    for job in workflow["jobs"].values():
        for step in job.get("steps", []):
            if "uses" in step:
                uses.append(step["uses"])
    assert uses, "no actions found"
    for ref in uses:
        assert SHA_PIN.search(ref), f"{ref} is not pinned to a 40-character commit SHA"
    # The version comment next to each pin is what Dependabot keeps current.
    for line in _read(".github/workflows/ci.yml").splitlines():
        if "uses:" in line:
            assert re.search(r"# v\d+\.\d+\.\d+", line), line


def test_ci_declares_least_privilege_permissions() -> None:
    workflow = _yaml(".github/workflows/ci.yml")
    assert workflow["permissions"] == {"contents": "read"}
    for name, job in workflow["jobs"].items():
        if "permissions" in job:
            assert job["permissions"] == {"contents": "read"}, name
    text = _read(".github/workflows/ci.yml")
    secrets_used = set(re.findall(r"secrets\.([A-Za-z_]+)", text))
    assert not secrets_used, (
        f"repository secrets exposed to a PR-triggered workflow: {secrets_used}"
    )


def test_ci_has_required_jobs_and_aggregate_gate() -> None:
    workflow = _yaml(".github/workflows/ci.yml")
    jobs = workflow["jobs"]
    assert {"python", "security", "test"} <= jobs.keys()
    assert jobs["test"]["needs"] == ["python", "security"]
    assert jobs["test"]["if"] == "always()"
    assert "postgres:17" == jobs["python"]["services"]["postgres"]["image"]
    triggers = workflow.get("on") or workflow.get(True)
    assert triggers["push"]["branches"] == ["main"]
    assert "pull_request" in triggers
    assert workflow["concurrency"]["cancel-in-progress"] is True


def test_dependabot_covers_uv_and_actions() -> None:
    config = _yaml(".github/dependabot.yml")
    ecosystems = {u["package-ecosystem"]: u for u in config["updates"]}
    assert {"uv", "github-actions"} <= ecosystems.keys()
    for update in ecosystems.values():
        assert update["schedule"]["interval"] == "weekly"


def test_compose_defines_postgres_and_minio() -> None:
    compose = _yaml("docker-compose.yml")
    services = compose["services"]
    assert {"postgres", "minio", "minio-init"} <= services.keys()
    postgres = services["postgres"]
    assert postgres["image"] == "postgres:17"
    assert "healthcheck" in postgres and "pg_isready" in " ".join(postgres["healthcheck"]["test"])
    mounts = " ".join(postgres["volumes"])
    assert "01-extensions.sql:/docker-entrypoint-initdb.d/" in mounts
    assert "02-roles.sql:/docker-entrypoint-initdb.d/" in mounts
    for key in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"):
        assert key in postgres["environment"]
    assert "healthcheck" in services["minio"]
    assert "minio" in services["minio"]["image"]
    assert services["minio-init"]["depends_on"]["minio"]["condition"] == "service_healthy"
    init_script = "\n".join(services["minio-init"]["command"])
    assert "version enable" in init_script
    assert {"postgres-data", "minio-data"} <= compose["volumes"].keys()
    extensions = _read("infra/docker/postgres/01-extensions.sql")
    assert "CREATE EXTENSION IF NOT EXISTS pg_trgm;" in extensions
    roles = _read("infra/docker/postgres/02-roles.sql")
    for role in ("judgemetrics_app", "judgemetrics_ingest", "judgemetrics_admin"):
        assert f"CREATE ROLE {role} LOGIN PASSWORD :'" in roles, role
    assert "GRANT SELECT ON ALL TABLES IN SCHEMA public TO judgemetrics_app;" in roles
    assert "INSERT" not in roles.split("judgemetrics_app;")[0].split("-- App:")[-1]


def test_compose_reads_secrets_from_env_only() -> None:
    text = _read("docker-compose.yml")
    for key in ("POSTGRES_PASSWORD", "MINIO_ROOT_PASSWORD"):
        assert re.search(rf"{key}: \$\{{{key}:\?", text), f"{key} must be required from .env"


def test_command_interface_targets_present() -> None:
    tasks = _pyproject()["tool"]["poe"]["tasks"]
    makefile = _read("Makefile")
    make_targets = set(re.findall(r"^([a-z][a-z-]*):", makefile, flags=re.MULTILINE))
    phony = re.search(r"^\.PHONY:(.*)$", makefile, flags=re.MULTILINE)
    assert phony is not None
    for target in SHARED_TARGETS:
        assert target in tasks, f"poe task {target} missing"
        assert target in make_targets, f"Makefile target {target} missing"
        assert target in phony.group(1).split(), f"{target} not in .PHONY"
        body = re.search(rf"^{target}:\n\t(.+)$", makefile, flags=re.MULTILINE)
        assert body is not None and body.group(1) == f"uv run poe {target}", target
    assert tasks["down"] == "docker compose down"
    assert "docker compose up -d --wait" in tasks["up-services"]
    assert tasks["gate"] == ["gate-commit", "gate-push"]
    assert tasks["gate-commit"] == "pre-commit run --all-files"


def test_pytest_config_has_markers_and_testpaths() -> None:
    options = _pyproject()["tool"]["pytest"]["ini_options"]
    assert options["testpaths"] == ["tests/unit", "tests/integration"]
    markers = " ".join(options["markers"])
    assert "unit:" in markers and "integration:" in markers


def test_bandit_configured_to_exclude_tests() -> None:
    bandit = _pyproject()["tool"]["bandit"]
    assert "tests" in bandit["exclude_dirs"]


@pytest.mark.parametrize(
    ("relative", "prefix"),
    [
        ("tests/unit/test_repo_hygiene.py", "# "),
        ("tests/unit/test_smoke.py", "# "),
        ("scripts/audit_deps.py", "# "),
        (".pre-commit-config.yaml", "# "),
        (".github/workflows/ci.yml", "# "),
        (".github/dependabot.yml", "# "),
        ("docker-compose.yml", "# "),
        (".env.example", "# "),
        ("infra/docker/postgres/01-extensions.sql", "-- "),
        ("infra/docker/postgres/02-roles.sql", "-- "),
        ("CONTRIBUTING.md", "<!-- "),
        ("SECURITY.md", "<!-- "),
        ("CODE_OF_CONDUCT.md", "<!-- "),
        (".github/PULL_REQUEST_TEMPLATE.md", "<!-- "),
    ],
)
def test_first_line_is_repo_relative_path(relative: str, prefix: str) -> None:
    first = _read(relative).splitlines()[0]
    expected = f"{prefix}{relative}"
    assert first.startswith(expected), f"{relative}: first line {first!r}"


@pytest.mark.parametrize(
    "relative",
    [
        ".github/ISSUE_TEMPLATE/bug_report.md",
        ".github/ISSUE_TEMPLATE/feature_request.md",
        ".github/ISSUE_TEMPLATE/data_source_issue.md",
    ],
)
def test_issue_templates_carry_path_after_front_matter(relative: str) -> None:
    # GitHub requires YAML front matter on the first line, so the path
    # comment is the first line after it.
    lines = _read(relative).splitlines()
    assert lines[0] == "---"
    closing = lines.index("---", 1)
    after = [line for line in lines[closing + 1 :] if line.strip()]
    assert after[0] == f"<!-- {relative} -->", after[0]
