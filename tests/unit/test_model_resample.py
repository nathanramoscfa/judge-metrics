# tests/unit/test_model_resample.py
"""Person-cluster bootstrap weights: seeded streams, sorted keys, whole clusters.

The stream is derived exactly as ``synthetic/rng.py`` derives its streams;
each replicate draws as many clusters as there are, so the weights of one
replicate sum to the row count of the clusters drawn and every row of a
cluster carries its cluster's weight; the draws depend on the seed, the
stream, and the cluster keys alone — never on the order of the rows.
"""

from __future__ import annotations

import numpy as np
import pytest

from judgemetrics.metrics.adjustment.resample import (
    cluster_index,
    derive_stream,
    replicate_stream,
    replicates,
)
from judgemetrics.synthetic import rng as synthetic_rng

pytestmark = pytest.mark.unit

CLUSTERS = ["k3", "k1", "k2", "k1", "k3", "k3", "k4"]


def test_the_stream_is_derived_as_the_synthetic_generator_derives_its_streams() -> None:
    ours = derive_stream(20260930, "bootstrap:new_case:365")
    theirs = synthetic_rng.derive_stream(20260930, "bootstrap:new_case:365")
    assert [ours.random() for _ in range(5)] == [theirs.random() for _ in range(5)]
    assert replicate_stream("new_case", 365) == "bootstrap:new_case:365"
    assert replicate_stream("pretrial_release", None) == "bootstrap:pretrial_release:none"


def test_every_replicate_resamples_whole_clusters() -> None:
    keys, rows = cluster_index(CLUSTERS)
    assert keys == ("k1", "k2", "k3", "k4")
    draws = list(replicates(CLUSTERS, seed=7, stream="s", count=50))
    assert len(draws) == 50
    for weights in draws:
        assert weights.shape == (len(CLUSTERS),)
        per_cluster = [weights[rows == index] for index in range(len(keys))]
        assert all(np.all(values == values[0]) for values in per_cluster)
        assert sum(float(values[0]) for values in per_cluster) == len(keys)
    assert len({weights.tobytes() for weights in draws}) > 1


def test_the_draws_depend_on_the_seed_the_stream_and_the_keys_only() -> None:
    first = np.vstack(list(replicates(CLUSTERS, seed=7, stream="s", count=10)))
    again = np.vstack(list(replicates(CLUSTERS, seed=7, stream="s", count=10)))
    assert first.tobytes() == again.tobytes()
    # Reordering the rows reorders the weights with them and changes nothing else.
    order = [6, 5, 4, 3, 2, 1, 0]
    shuffled = np.vstack(
        list(replicates([CLUSTERS[i] for i in order], seed=7, stream="s", count=10))
    )
    assert shuffled.tobytes() == first[:, order].tobytes()
    other_seed = np.vstack(list(replicates(CLUSTERS, seed=8, stream="s", count=10)))
    other_stream = np.vstack(list(replicates(CLUSTERS, seed=7, stream="t", count=10)))
    assert first.tobytes() != other_seed.tobytes()
    assert first.tobytes() != other_stream.tobytes()
    assert list(replicates([], seed=7, stream="s", count=2))[0].shape == (0,)
