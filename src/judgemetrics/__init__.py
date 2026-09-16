# src/judgemetrics/__init__.py
"""JudgeMetrics: reproducible analytics over public criminal-court records.

The application package is built phase by phase per ROADMAP.md. This module
exposes only the package version; the console entry point is
``judgemetrics.cli:main``.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("judgemetrics")
except PackageNotFoundError:  # pragma: no cover - source tree without install
    __version__ = "0.0.0"

__all__ = ["__version__"]
