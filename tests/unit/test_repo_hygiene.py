# tests/unit/test_repo_hygiene.py
"""Repository hygiene: the governance chassis from Phase 1 Step 1 stays intact.

These tests read the repository's own files, so they guard the license,
community files, placeholder-only `.env.example`, the pre-commit gate, the
SHA-pinned least-privilege CI workflow, the Compose services, the web
tier's chassis (Step 5: lockfile, container image, CI jobs, Dependabot), and
the agreement between the poe tasks and the Makefile shim.
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
    "8000",
    "9000",
    "9001",
    "3000",
    "http://api:8000",
    "false",
    "60",
    "10",
    "0.3",
    "data/synthetic/20260916",
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
SHARED_TARGETS = (
    "up",
    "down",
    "check",
    "test",
    "lint",
    "typecheck",
    "gate",
    "migrate",
    "dev-api",
    "dev-web",
    "ingest-fjc",
    "seed",
)
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
        "JUDGEMETRICS_ADMIN_DATABASE_URL",
        "JUDGEMETRICS_INGEST_DATABASE_URL",
        "JUDGEMETRICS_CORRECTION_CONTACT_KEY",
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
    for key in (
        "POSTGRES_PASSWORD",
        "MINIO_ROOT_PASSWORD",
        "JUDGEMETRICS_S3_SECRET_ACCESS_KEY",
        "JUDGEMETRICS_CORRECTION_CONTACT_KEY",
        "JUDGEMETRICS_IDENTIFIER_PEPPER",
    ):
        assert values[key] == "change-me", key
    for key in ("JUDGEMETRICS_DATABASE_URL", "JUDGEMETRICS_ADMIN_DATABASE_URL"):
        assert values[key].startswith("postgresql+psycopg://"), key
    assert "judgemetrics_app:" in values["JUDGEMETRICS_DATABASE_URL"]
    assert "judgemetrics_admin:" in values["JUDGEMETRICS_ADMIN_DATABASE_URL"]


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
    assert {"python", "security", "container", "web", "e2e", "test"} <= jobs.keys()
    assert jobs["test"]["needs"] == ["python", "security", "container", "web", "e2e"]
    assert jobs["test"]["if"] == "always()"
    assert "postgres:17" == jobs["python"]["services"]["postgres"]["image"]
    python_env = jobs["python"]["env"]
    assert python_env["JUDGEMETRICS_ENV"] == "test"
    assert python_env["JUDGEMETRICS_DATABASE_URL"].startswith(
        "postgresql+psycopg://judgemetrics_app:"
    )
    role_steps = [s for s in jobs["python"]["steps"] if "02-roles.sql" in s.get("run", "")]
    assert role_steps, "the python job must create the three database roles"
    container_steps = " ".join(
        f"{s.get('uses', '')} {s.get('run', '')}" for s in jobs["container"]["steps"]
    )
    assert "docker build -f infra/docker/api.Dockerfile" in container_steps
    assert "docker build -f infra/docker/web.Dockerfile" in container_steps
    scans = [s for s in jobs["container"]["steps"] if "trivy-action" in s.get("uses", "")]
    assert {scan["with"]["image-ref"] for scan in scans} == {
        "judgemetrics-api:ci",
        "judgemetrics-web:ci",
    }
    for scan in scans:
        assert scan["with"]["severity"] == "HIGH,CRITICAL"
        assert str(scan["with"]["exit-code"]) == "1"
    triggers = workflow.get("on") or workflow.get(True)
    assert triggers["push"]["branches"] == ["main"]
    assert "pull_request" in triggers
    assert workflow["concurrency"]["cancel-in-progress"] is True


def test_ci_web_and_e2e_jobs() -> None:
    jobs = _yaml(".github/workflows/ci.yml")["jobs"]
    web_runs = [s.get("run", "") for s in jobs["web"]["steps"]]
    assert jobs["web"]["defaults"]["run"]["working-directory"] == "web"
    for command in (
        "corepack enable",
        "pnpm install --frozen-lockfile",
        "pnpm lint",
        "pnpm typecheck",
        "pnpm test",
        "pnpm build",
        "pnpm audit --audit-level=high",
    ):
        assert command in web_runs, command
    # The bundle scan needs a build, so the build precedes the tests.
    assert web_runs.index("pnpm build") < web_runs.index("pnpm test")
    node_setups = [
        s for job in ("web", "e2e") for s in jobs[job]["steps"] if "setup-node" in s.get("uses", "")
    ]
    assert len(node_setups) == 2
    for step in node_setups:
        assert step["with"]["node-version-file"] == ".node-version"
    assert _read(".node-version").strip() == "22"

    e2e = jobs["e2e"]
    assert e2e["services"]["postgres"]["image"] == "postgres:17"
    assert e2e["env"]["JUDGEMETRICS_INGEST_DATABASE_URL"].startswith(
        "postgresql+psycopg://judgemetrics_ingest:"
    )
    assert e2e["env"]["NEXT_PUBLIC_API_BASE_URL"] == "http://localhost:8000"
    assert "JUDGEMETRICS_IDENTIFIER_PEPPER" in e2e["env"]
    e2e_runs = "\n".join(s.get("run", "") for s in e2e["steps"])
    for command in (
        "02-roles.sql",
        "uv sync --frozen",
        "uv run poe migrate",
        "uv run judgemetrics ingest run fjc --from-fixture tests/fixtures/fjc",
        "uv run judgemetrics ingest run synthetic --from-fixture tests/fixtures/golden",
        "uv run judgemetrics serve",
        "pnpm exec playwright install --with-deps chromium",
        "pnpm e2e",
    ):
        assert command in e2e_runs, command


def test_dependabot_covers_uv_actions_docker_and_npm() -> None:
    config = _yaml(".github/dependabot.yml")
    ecosystems = {u["package-ecosystem"]: u for u in config["updates"]}
    assert {"uv", "github-actions", "docker", "npm"} <= ecosystems.keys()
    assert ecosystems["docker"]["directory"] == "/infra/docker"
    assert ecosystems["npm"]["directory"] == "/web"
    for update in ecosystems.values():
        assert update["schedule"]["interval"] == "weekly"


def test_compose_defines_postgres_and_minio() -> None:
    compose = _yaml("docker-compose.yml")
    services = compose["services"]
    assert {"postgres", "minio", "minio-init", "api", "web"} <= services.keys()
    web = services["web"]
    assert web["profiles"] == ["app"]
    assert web["build"]["context"] == "web"
    assert web["build"]["dockerfile"] == "../infra/docker/web.Dockerfile"
    assert "NEXT_PUBLIC_API_BASE_URL" in web["build"]["args"]
    assert "api" in web["depends_on"]
    assert any(str(port).endswith(":3000") for port in web["ports"])
    assert "env_file" not in web, "the web image reads no .env"
    api = services["api"]
    assert api["profiles"] == ["app"]
    assert api["build"]["dockerfile"] == "infra/docker/api.Dockerfile"
    assert api["env_file"] == ".env"
    assert api["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert any(str(port).endswith(":8000") for port in api["ports"])
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


def test_api_dockerfile_is_hardened() -> None:
    dockerfile = _read("infra/docker/api.Dockerfile")
    assert dockerfile.startswith("# infra/docker/api.Dockerfile")
    assert "FROM python:3.13-slim" in dockerfile
    assert "uv sync --frozen --no-dev --no-group planning" in dockerfile
    assert "USER judgemetrics" in dockerfile
    assert "HEALTHCHECK" in dockerfile and "/api/v1/health" in dockerfile
    assert 'CMD ["judgemetrics", "serve", "--host", "0.0.0.0"]' in dockerfile
    assert "COPY .env" not in dockerfile
    assert ".env" not in [
        line.strip() for line in _read(".dockerignore").splitlines() if line.startswith("!")
    ]


def test_web_dockerfile_is_hardened() -> None:
    dockerfile = _read("infra/docker/web.Dockerfile")
    assert dockerfile.startswith("# infra/docker/web.Dockerfile")
    assert dockerfile.count("FROM node:22-alpine") == 3
    assert "corepack enable" in dockerfile
    assert "pnpm install --frozen-lockfile" in dockerfile
    assert "ARG NEXT_PUBLIC_API_BASE_URL" in dockerfile
    assert "/app/.next/standalone" in dockerfile
    assert "USER judgemetrics" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert 'CMD ["node", "server.js"]' in dockerfile
    assert "COPY .env" not in dockerfile
    ignore = [line.strip() for line in _read("web/.dockerignore").splitlines()]
    assert ".env" in ignore and ".env.*" in ignore and "node_modules" in ignore
    next_config = _read("web/next.config.ts")
    assert 'output: "standalone"' in next_config


def test_web_manifest_scripts_and_lockfile() -> None:
    import json

    manifest = json.loads(_read("web/package.json"))
    for script in ("dev", "build", "start", "lint", "typecheck", "test", "e2e", "generate:api"):
        assert script in manifest["scripts"], script
    assert manifest["scripts"]["typecheck"].endswith("tsc --noEmit")
    assert manifest["scripts"]["generate:api"] == (
        "openapi-typescript ../docs/openapi.json --output lib/api/schema.d.ts"
    )
    assert manifest["packageManager"].startswith("pnpm@")
    assert (REPO_ROOT / "web" / "pnpm-lock.yaml").is_file()
    assert (REPO_ROOT / "web" / "lib" / "api" / "schema.d.ts").is_file()
    for package in (
        "next",
        "next-themes",
        "@tanstack/react-table",
        "openapi-fetch",
    ):
        assert package in manifest["dependencies"], package
    for package in (
        "openapi-typescript",
        "vitest",
        "@testing-library/react",
        "@playwright/test",
        "eslint-plugin-security",
    ):
        assert package in manifest["devDependencies"], package
    env_example = _read("web/.env.example")
    assert "NEXT_PUBLIC_API_BASE_URL=http://localhost:8000" in env_example
    assert "JUDGEMETRICS_" not in env_example


def test_web_reads_no_server_side_variables() -> None:
    """Only NEXT_PUBLIC_* reaches the client bundle; the web tier reads nothing else."""
    web = REPO_ROOT / "web"
    offenders: list[str] = []
    for path in list(web.rglob("*.ts")) + list(web.rglob("*.tsx")):
        if "node_modules" in path.parts or ".next" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"process\.env\.([A-Z0-9_]+)", text):
            name = match.group(1)
            if not name.startswith("NEXT_PUBLIC_") and name not in {"CI", "PLAYWRIGHT_BASE_URL"}:
                offenders.append(f"{path.relative_to(REPO_ROOT)}: {name}")
        assert "dangerouslySetInnerHTML" not in text, path
    assert offenders == []


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
    assert tasks["migrate"] == "judgemetrics db upgrade"
    assert tasks["dev-api"] == "judgemetrics serve --reload"
    assert tasks["dev-web"] == "pnpm --dir web dev"
    assert tasks["ingest-fjc"] == "judgemetrics ingest run fjc"
    assert tasks["seed"] == "judgemetrics seed"
    assert _pyproject()["project"]["scripts"]["judgemetrics"] == "judgemetrics.cli:main"


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
        (".dockerignore", "# "),
        ("alembic.ini", "# "),
        ("infra/docker/api.Dockerfile", "# "),
        ("infra/docker/web.Dockerfile", "# "),
        ("web/.dockerignore", "# "),
        ("web/.env.example", "# "),
        ("web/next.config.ts", "// "),
        ("web/eslint.config.mjs", "// "),
        ("web/vitest.config.ts", "// "),
        ("web/playwright.config.ts", "// "),
        ("web/lib/api/client.ts", "// "),
        ("web/app/layout.tsx", "// "),
        ("web/app/page.tsx", "// "),
        ("web/app/globals.css", "/* "),
        ("web/tests/e2e/smoke.spec.ts", "// "),
        ("infra/docker/postgres/01-extensions.sql", "-- "),
        ("infra/docker/postgres/02-roles.sql", "-- "),
        ("CONTRIBUTING.md", "<!-- "),
        ("docs/ARCHITECTURE.md", "<!-- "),
        ("docs/DATA_MODEL.md", "<!-- "),
        ("data/README.md", "<!-- "),
        ("tests/fixtures/fjc/README.md", "<!-- "),
        ("tests/fixtures/golden/README.md", "<!-- "),
        ("docs/SYNTHETIC_DATA.md", "<!-- "),
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


def _python_sources() -> list[str]:
    sources: list[str] = []
    for top in ("src", "tests", "scripts", "alembic"):
        for path in sorted((REPO_ROOT / top).rglob("*.py")):
            sources.append(path.relative_to(REPO_ROOT).as_posix())
    return sources


@pytest.mark.parametrize("relative", _python_sources())
def test_every_python_file_starts_with_its_path(relative: str) -> None:
    first = _read(relative).splitlines()[0]
    assert first == f"# {relative}", f"{relative}: first line {first!r}"
