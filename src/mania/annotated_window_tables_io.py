"""Strict annotated window CSV; blank unknown differs from known empty []."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mania.annotated_window_tables import (
    AnnotatedReferenceWindowTable,
    build_annotated_reference_tables,
)
from mania.biological_annotations import SystemAnnotations
from mania.canonical_reference import ProteinReference
from mania.canonical_window_tables import ReferenceWindowTable
from mania.canonical_window_tables_io import (
    _cell,
    _csv_text,
    _read_rows,
)
from mania.canonical_window_tables_io import (
    _parse as _reference_parse,
)
from mania.preprocessing.molecular_partner_metadata_io import write_atomic_text

COLUMNS = {
    "protein": (
        "dataset_id",
        "system_id",
        "trajectory_id",
        "variant_id",
        "engine",
        "condition",
        "replica_id",
        "disulfide_state",
        "window_id",
        "window_index",
        "requested_window_start_ns",
        "requested_window_end_ns",
        "right_endpoint_inclusive",
        "effective_window_start_ns",
        "effective_window_end_ns",
        "requested_sample_count",
        "resolved_frame_count",
        "missing_sample_count",
        "coverage_fraction",
        "source_residue_index",
        "target_residue_index",
        "source_chain_id",
        "target_chain_id",
        "source_resid",
        "target_resid",
        "source_resname",
        "target_resname",
        "edge_type",
        "n_contact_frames",
        "occupancy",
        "n_contact_episodes",
        "mean_episode_length_ns",
        "max_episode_length_ns",
        "edge_weight",
        "reference_id",
        "reference_sha256",
        "reference_chain_i",
        "reference_position_i",
        "reference_resname_i",
        "reference_chain_j",
        "reference_position_j",
        "reference_resname_j",
        "annotation_ids_i",
        "annotation_ids_j",
    ),
    "lipid": (
        "dataset_id",
        "system_id",
        "trajectory_id",
        "variant_id",
        "engine",
        "condition",
        "replica_id",
        "disulfide_state",
        "window_id",
        "window_index",
        "requested_window_start_ns",
        "requested_window_end_ns",
        "right_endpoint_inclusive",
        "effective_window_start_ns",
        "effective_window_end_ns",
        "requested_sample_count",
        "resolved_frame_count",
        "missing_sample_count",
        "coverage_fraction",
        "protein_residue_index",
        "protein_chain_id",
        "protein_resid",
        "protein_resname",
        "lipid_partner_id",
        "lipid_partner_name",
        "lipid_component_residue_indexes",
        "n_contact_frames",
        "occupancy",
        "n_contact_episodes",
        "mean_episode_length_ns",
        "max_episode_length_ns",
        "distance_mean_A",
        "distance_min_A",
        "reference_id",
        "reference_sha256",
        "reference_chain_i",
        "reference_position_i",
        "reference_resname_i",
        "annotation_ids_i",
    ),
    "glycan": (
        "dataset_id",
        "system_id",
        "trajectory_id",
        "variant_id",
        "engine",
        "condition",
        "replica_id",
        "disulfide_state",
        "window_id",
        "window_index",
        "requested_window_start_ns",
        "requested_window_end_ns",
        "right_endpoint_inclusive",
        "effective_window_start_ns",
        "effective_window_end_ns",
        "requested_sample_count",
        "resolved_frame_count",
        "missing_sample_count",
        "coverage_fraction",
        "protein_residue_index",
        "protein_chain_id",
        "protein_resid",
        "protein_resname",
        "glycan_partner_id",
        "glycan_partner_name",
        "glycan_component_residue_indexes",
        "carrier_residue_index",
        "first_sugar_residue_index",
        "linkage_evidence",
        "carrier_link_atom_index",
        "first_sugar_link_atom_index",
        "n_contact_frames",
        "occupancy",
        "n_contact_episodes",
        "mean_episode_length_ns",
        "max_episode_length_ns",
        "distance_mean_A",
        "distance_min_A",
        "reference_id",
        "reference_sha256",
        "reference_chain_i",
        "reference_position_i",
        "reference_resname_i",
        "annotation_ids_i",
    ),
}


def _parse(name: str, value: str, layer: str) -> Any:
    if name.startswith("annotation_ids_"):
        if value == "":
            return None
        parsed = json.loads(value)
        if type(parsed) is not list or any(type(v) is not str for v in parsed):
            raise ValueError("Annotation IDs require a JSON string array")
        return tuple(parsed)
    return _reference_parse(name, value, layer)


def annotated_window_csv_text(table: AnnotatedReferenceWindowTable) -> str:
    table.__post_init__()

    def cell(value: Any) -> str:
        if type(value) is tuple and (not value or type(value[0]) is str):
            return json.dumps(value, ensure_ascii=True, separators=(",", ":"))
        return _cell(value)

    return _csv_text(table, COLUMNS[table.layer], cell)


def write_annotated_reference_table(
    table: AnnotatedReferenceWindowTable, path: str | Path, *, overwrite: bool = False
) -> None:
    result = write_atomic_text(
        annotated_window_csv_text(table), Path(path), overwrite=overwrite
    )
    if not result.passed:
        raise ValueError("Annotated window write failed: " + str(result.error))


def read_annotated_reference_table(
    path: str | Path,
    *,
    reference_table: ReferenceWindowTable,
    annotations: SystemAnnotations,
    reference: ProteinReference,
) -> AnnotatedReferenceWindowTable:
    table = build_annotated_reference_tables(
        reference_table, annotations=annotations, reference=reference
    )
    if isinstance(table, tuple):
        raise ValueError("One reference family is required for one CSV")
    rows = _read_rows(path, table, COLUMNS[table.layer], _parse)
    result = type(table)(rows, reference_table, annotations, reference)
    if Path(path).read_bytes() != annotated_window_csv_text(result).encode():
        raise ValueError(
            "Annotated CSV must retain exact values, order and unknown states"
        )
    return result


def validate_annotated_reference_table(
    path: str | Path,
    *,
    reference_table: ReferenceWindowTable,
    annotations: SystemAnnotations,
    reference: ProteinReference,
) -> AnnotatedReferenceWindowTable:
    return read_annotated_reference_table(
        path,
        reference_table=reference_table,
        annotations=annotations,
        reference=reference,
    )
