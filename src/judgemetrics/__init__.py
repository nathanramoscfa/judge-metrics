# src/judgemetrics/__init__.py
"""JudgeMetrics: reproducible analytics over public criminal-court records.

The application package is built phase by phase per ROADMAP.md. Until
Phase 1 lands, this module exposes only the package version and a
placeholder console entry point so the environment can be smoke-tested.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("judgemetrics")
except PackageNotFoundError:  # pragma: no cover - source tree without install
    __version__ = "0.0.0"


def main() -> None:
    """Placeholder console entry point; Phase 1 replaces it with the Typer CLI."""
    print(f"judgemetrics {__version__} - see ROADMAP.md (Phase 1 has not started).")
