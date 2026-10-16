"""Strict explicit generic group IO and authority digests."""

from pathlib import Path
from typing import Any

from mania._dataset_qc_json import read_model, write_model
from mania.replica_aggregation_contract import ReplicaGroup


def read_replica_aggregation_manifest(path: Path, *, root: Path) -> ReplicaGroup:
    return read_model(path, ReplicaGroup, root=root)


write_replica_aggregation_manifest = write_model


def replica_aggregation_manifest_payload(group: ReplicaGroup) -> dict[str, Any]:
    return ReplicaGroup.model_validate(group.model_dump()).model_dump(mode="json")
