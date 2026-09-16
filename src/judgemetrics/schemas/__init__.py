# src/judgemetrics/schemas/__init__.py
"""Pydantic response models for the public API (``judgemetrics.api``).

Schemas are the only shapes that leave the API: a schema names every field
it exposes, so an ORM column that is not listed here (``raw_object_path``,
timestamps, foreign keys with no public meaning) never reaches a client.
"""
