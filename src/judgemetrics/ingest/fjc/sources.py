# src/judgemetrics/ingest/fjc/sources.py
"""Verified locations of the FJC Biographical Directory export.

The export page and the two file URLs were verified live on 2026-09-16
(docs/DATA_SOURCES.md, entry ``fjc``: "Files (verified ...)" and "Fetch
verified ..."). Only the judge identity file and the federal judicial
service file are fetched; ``demographics.csv`` is deliberately absent.
"""

from __future__ import annotations

EXPORT_PAGE_URL = (
    "https://www.fjc.gov/history/judges/biographical-directory-article-iii-federal-judges-export"
)
FILES_BASE_URL = "https://www.fjc.gov/sites/default/files/history/"

JUDGES_FILE = "judges.csv"
SERVICE_FILE = "federal-judicial-service.csv"

JUDGES_CSV_URL = FILES_BASE_URL + JUDGES_FILE
SERVICE_CSV_URL = FILES_BASE_URL + SERVICE_FILE

ARTIFACT_URLS: dict[str, str] = {
    JUDGES_FILE: JUDGES_CSV_URL,
    SERVICE_FILE: SERVICE_CSV_URL,
}
