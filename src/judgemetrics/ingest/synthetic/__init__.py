# src/judgemetrics/ingest/synthetic/__init__.py
"""The ``synthetic`` connector: the generated justice dataset through the standard runner.

``schema`` fixes the expected header set of each of the nine source files
(docs/SYNTHETIC_DATA.md "Source format"); ``sources`` the ``source`` row
facts; ``parse`` reads a file as strings and projects each row to the
expected columns; ``normalize`` maps rows onto the case-level drafts,
hashing every person attribute with ``judgemetrics.security.identifiers``;
``connector`` discovers ``manifest.json`` and the nine files under
``Settings.synthetic_dir``, never ``truth/``, and fails the run when a
file no longer matches the manifest.
"""
