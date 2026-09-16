# src/judgemetrics/openapi.py
"""Render the API's OpenAPI document deterministically.

``docs/openapi.json`` is a committed snapshot of this output: Step 5
generates the web client from it, and ``tests/unit/test_openapi.py`` fails
when a route changes without the document being regenerated
(``judgemetrics openapi export``). The document depends on the routes and
the package version only, never on settings, so it renders the same on
every machine.
"""

from __future__ import annotations

import json
from typing import Any

from judgemetrics.config import Settings


def openapi_document() -> dict[str, Any]:
    """The document of an app built with test settings (no database contact)."""
    from judgemetrics.main import create_app

    app = create_app(Settings(env="test", log_format="json"))
    try:
        return app.openapi()
    finally:
        app.state.engine.dispose()


def render_openapi() -> str:
    """Sorted keys, two-space indent, LF line endings, one trailing newline."""
    return json.dumps(openapi_document(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"
