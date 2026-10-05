# src/judgemetrics/ingest/cook_sao/sources.py
"""Verified locations of the Cook County State's Attorney case-level datasets.

The five current datasets were verified against the portal's metadata API
on 2026-10-05 (docs/DATA_SOURCES.md, entry ``cook_sao``): each is a Socrata
dataset on ``datacatalog.cookcountyil.gov`` whose bulk CSV export needs no
credential. ``DATASETS`` lists them in dependency order — Intake (a case
brought for felony review), Initiation (the charges filed), Dispositions,
Sentencing, Diversion — with the external id the runner keys the raw lake
on. The archived versions released on 2018-02-13 are recorded here and in
the register and never fetched: the SAO hashes ``CASE_ID`` and
``CASE_PARTICIPANT_ID`` "independently for every version released", so
they cannot be joined to the current release.

Every URL is a module constant over HTTPS; nothing in the data or the
portal's responses chooses a URL.
"""

from __future__ import annotations

from dataclasses import dataclass

SOURCE_ID = "cook_sao"

PORTAL_URL = "https://datacatalog.cookcountyil.gov"
# The portal's footer links its terms of use to the County's site terms.
TERMS_URL = "https://www.cookcountyil.gov/terms-use"
ATTRIBUTION = "Cook County State's Attorney's Office"
ATTRIBUTION_URL = "https://www.cookcountystatesattorney.org/"
# The SAO's documentation, attached to every dataset (read 2026-10-05).
GLOSSARY_URL = (
    "https://datacatalog.cookcountyil.gov/api/views/apwk-dzx8/files/"
    "4d3f91ea-857d-4f04-994f-918980b0b319?download=true&filename=CCSAO%20Data%20Glossary.pdf"
)
FLOWCHART_URL = (
    "https://datacatalog.cookcountyil.gov/api/views/apwk-dzx8/files/"
    "ebb427cf-8198-4b8d-bb7a-fd6906076eee?download=true"
    "&filename=CCSAO%20Felony%20Cases%20Flowchart.pdf"
)


@dataclass(frozen=True, slots=True)
class Dataset:
    """One Socrata dataset: its name, portal id, and the external id of its export."""

    name: str
    portal_id: str
    external_id: str

    @property
    def export_url(self) -> str:
        return f"{PORTAL_URL}/api/views/{self.portal_id}/rows.csv?accessType=DOWNLOAD"

    @property
    def metadata_url(self) -> str:
        return f"{PORTAL_URL}/api/views/{self.portal_id}.json"

    @property
    def page_url(self) -> str:
        return f"{PORTAL_URL}/d/{self.portal_id}"


INTAKE = Dataset("Intake", "3k7z-hchi", "intake.csv")
INITIATION = Dataset("Initiation", "7mck-ehwz", "initiation.csv")
DISPOSITIONS = Dataset("Dispositions", "apwk-dzx8", "dispositions.csv")
SENTENCING = Dataset("Sentencing", "tg8v-tm6u", "sentencing.csv")
DIVERSION = Dataset("Diversion", "gpu3-5dfh", "diversion.csv")

# Dependency order: the order the runner fetches and the excerpt writes.
DATASETS: tuple[Dataset, ...] = (INTAKE, INITIATION, DISPOSITIONS, SENTENCING, DIVERSION)
DATASETS_BY_EXTERNAL_ID: dict[str, Dataset] = {d.external_id: d for d in DATASETS}
EXTERNAL_IDS: tuple[str, ...] = tuple(d.external_id for d in DATASETS)

# The 2018-02-13 releases, archived on the portal on 2018-10-03 (no Diversion
# archive exists; no license is recorded on them). Never fetched.
ARCHIVED_DATASETS: tuple[Dataset, ...] = (
    Dataset("Intake [Archived from February 13, 2018]", "a2mv-5et6", "archived-intake.csv"),
    Dataset("Initiation [Archived from February 13, 2018]", "qr2q-atnt", "archived-initiation.csv"),
    Dataset(
        "Dispositions [Archived from February 13, 2018]", "75tm-jf99", "archived-dispositions.csv"
    ),
    Dataset("Sentencing [Archived from February 13, 2018]", "qhfs-h477", "archived-sentencing.csv"),
)
