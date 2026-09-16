# src/judgemetrics/repositories/__init__.py
"""Typed query functions over the canonical models.

A repository takes a ``Session`` and returns ORM rows (plus totals for
lists); it never builds response models and never formats SQL from
strings — every value is a bound parameter. The API's session connects as
the read-only ``judgemetrics_app`` role.
"""
