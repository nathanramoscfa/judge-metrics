# src/judgemetrics/ingest/synthetic/sources.py
"""What the ``source`` row records about the synthetic dataset.

The dataset is generated in this repository from a seed
(docs/DATA_SOURCES.md, entry ``synthetic``): there is nothing to fetch,
no terms, and no redistribution question, and ``source_type =
synthetic`` is what the runner refuses in production and what every
public surface labels. ``OBSERVABLE_OUTCOMES`` are the justice events the
generator documents (``synthetic/truth.py`` ``WINDOWED_OUTCOMES``);
``release_violation`` and ``rearrest`` are not among them, so the
registry's metrics over those outcomes are never published for this
source. Its capabilities (Phase 5 Step 5) are complete by construction: the
generator records every judge gate, one participant id per person across
courts (a cross-case person key), and revocations of both scopes.
"""

from __future__ import annotations

from judgemetrics.capabilities import SourceCapabilities
from judgemetrics.ingest.base import SourceInfo

SOURCE_ID = "synthetic"
OBSERVABLE_OUTCOMES: tuple[str, ...] = (
    "new_case",
    "new_charge",
    "reconviction",
    "failure_to_appear",
    "revocation",
)

SOURCE_INFO = SourceInfo(
    owner="this repository",
    source_type="synthetic",
    access_method="local_generator",
    terms_metadata={
        "redistribution": "not_applicable",
        "synthetic": True,
        "generator": "judgemetrics synthetic generate",
        "documentation": "docs/SYNTHETIC_DATA.md",
    },
    observable_outcomes=OBSERVABLE_OUTCOMES,
    capabilities=SourceCapabilities.full(),
    limitations=(
        "Labelled synthetic data generated in this repository from a seed: no court, judge, "
        "or person in it is real, and every figure describes the generator, not a justice "
        "system (docs/SYNTHETIC_DATA.md).",
        "The generator records every judge gate, one participant id per person across "
        "courts, failures to appear, and revocations; it generates no release violation and "
        "no separately sourced arrest, so the metrics over those outcomes are not observable "
        "for it.",
    ),
)
