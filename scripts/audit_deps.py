# scripts/audit_deps.py
"""Dependency audit for the security gate: `pip-audit --strict` over `uv.lock`.

Auditing the live virtual environment fails closed for the wrong reason (the
editable `judgemetrics` project is not on PyPI), so the gate audits what is
actually pinned: the lockfile, exported with hashes for every dependency group.
Runs identically on Windows and Ubuntu CI.
"""

from __future__ import annotations

import shutil
import subprocess  # argument lists over PATH tools, never a shell  # nosec B404
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    uv = shutil.which("uv")
    if uv is None:
        print("audit_deps: `uv` not found on PATH", file=sys.stderr)
        return 2
    with tempfile.TemporaryDirectory() as tmp:
        requirements = Path(tmp) / "requirements-audit.txt"
        export = subprocess.run(  # noqa: S603 - fixed argv, no shell  # nosec B603
            [
                uv,
                "export",
                "--frozen",
                "--no-emit-project",
                "--all-groups",
                "--quiet",
                "-o",
                str(requirements),
            ],
            cwd=REPO_ROOT,
            check=False,
        )
        if export.returncode != 0:
            print("audit_deps: `uv export` failed; is uv.lock up to date?", file=sys.stderr)
            return export.returncode
        audit = subprocess.run(  # noqa: S603 - fixed argv, no shell  # nosec B603
            [
                sys.executable,
                "-m",
                "pip_audit",
                "--strict",
                "--require-hashes",
                "--progress-spinner",
                "off",
                "-r",
                str(requirements),
            ],
            cwd=REPO_ROOT,
            check=False,
        )
        return audit.returncode


if __name__ == "__main__":
    raise SystemExit(main())
