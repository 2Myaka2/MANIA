"""Whole-partner lipid/glycan correspondence with shared source occupancy math."""

from typing import Any

from mania.replica_aggregation_contract import ReplicaGroup
from mania.replica_aggregation_manifest import ReplicaWindowInput
from mania.replica_aggregation_tables import ReplicaWindowTable
from mania.replica_protein_edge_aggregation import aggregate_windows


def aggregate_canonical_protein_lipid_across_replicas(
    group: ReplicaGroup, inputs: tuple[ReplicaWindowInput, ...], **context: Any
) -> ReplicaWindowTable:
    if group.layer != "lipid":
        raise ValueError("Lipid aggregation requires a lipid group")
    return aggregate_windows(group, inputs, **context)


def aggregate_canonical_protein_glycan_across_replicas(
    group: ReplicaGroup, inputs: tuple[ReplicaWindowInput, ...], **context: Any
) -> ReplicaWindowTable:
    if group.layer != "glycan":
        raise ValueError("Glycan aggregation requires a glycan group")
    return aggregate_windows(group, inputs, **context)
