# tests/unit/test_smoke.py
"""Environment smoke test: the package imports and reports its version."""

import pytest

from judgemetrics import __version__, main


def test_version_is_set() -> None:
    assert __version__
    assert __version__ != "0.0.0"


def test_main_prints_version(capsys: pytest.CaptureFixture[str]) -> None:
    main()
    out = capsys.readouterr().out
    assert __version__ in out
