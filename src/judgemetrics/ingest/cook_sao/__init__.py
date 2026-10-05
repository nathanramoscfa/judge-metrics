# src/judgemetrics/ingest/cook_sao/__init__.py
"""The Cook County State's Attorney connector (docs/DATA_SOURCES.md, ``cook_sao``).

``sources`` holds the five current datasets' portal ids and URLs (and the
archived versions, recorded and never fetched), ``schema`` the verified
export headers and the column classes the profile and the excerpt read,
``connector`` the registered ``CookSaoConnector`` (parser version ``0``:
fetch and store only), and ``profile`` and ``excerpt`` the two
``judgemetrics sources`` commands over the stored artifacts.
"""
