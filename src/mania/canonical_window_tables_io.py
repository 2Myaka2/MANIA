"""Strict, source-bound CSV read/write for all generic reference window layers."""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

from mania.canonical_reference import ProteinReference
from mania.canonical_residue_mapping import ResidueMappingTable
from mania.canonical_window_tables import (
    ReferenceWindowTable,
    SourceWindowTable,
    build_reference_window_tables,
)
from mania.preprocessing.molecular_partner_metadata_io import write_atomic_text
from mania.preprocessing.protein_edge_window_table_io import (
    _INTEGER,
    _serialize,
)
from mania.preprocessing.protein_edge_window_table_io import (
    _parse as _protein_parse,
)
from mania.preprocessing.specialized_contact_window_tables_io import (
    _parse as _partner_parse,
)

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
    ),
}


def _parse(name: str, value: str, layer: str) -> Any:
    if name.startswith("reference_position_"):
        if not _INTEGER.fullmatch(value) or int(value) < 1:
            raise ValueError("Invalid reference position cell")
        return int(value)
    if name.startswith("reference_"):
        return value
    return (_protein_parse if layer == "protein" else _partner_parse)(name, value)


def _cell(value: Any) -> str:
    if type(value) is tuple:
        return ";".join(str(v) for v in value)
    return _serialize(value)


def reference_window_csv_text(table: ReferenceWindowTable) -> str:
    table.__post_init__()
    return _csv_text(table, COLUMNS[table.layer], _cell)


def _csv_text(table: Any, columns: tuple[str, ...], serializer: Any) -> str:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(columns)
    for row in table.rows:
        writer.writerow([serializer(getattr(row, name)) for name in columns])
    return stream.getvalue()


def _read_rows(
    path: str | Path, table: Any, columns: tuple[str, ...], parser: Any
) -> tuple[Any, ...]:
    with Path(path).open(encoding="utf-8", newline="") as stream:
        reader = csv.reader(stream, strict=True)
        if tuple(next(reader, ())) != columns:
            raise ValueError("Exact ordered window columns required")
        rows = []
        for values in reader:
            if len(values) != len(columns):
                raise ValueError("Malformed window row")
            data = {
                name: parser(name, raw, table.layer)
                for name, raw in zip(columns, values, strict=True)
            }
            rows.append(table.row_type(**data))
    return tuple(rows)


def write_reference_window_table(
    table: ReferenceWindowTable, path: str | Path, *, overwrite: bool = False
) -> None:
    result = write_atomic_text(
        reference_window_csv_text(table), Path(path), overwrite=overwrite
    )
    if not result.passed:
        raise ValueError("Reference window write failed: " + str(result.error))


def read_reference_window_table(
    path: str | Path,
    *,
    source_table: SourceWindowTable,
    mapping: ResidueMappingTable,
    reference: ProteinReference,
) -> ReferenceWindowTable:
    table = build_reference_window_tables(
        source_table, mapping=mapping, reference=reference
    )
    if isinstance(table, tuple):
        raise ValueError("One typed source family is required for one CSV")
    rows = _read_rows(path, table, COLUMNS[table.layer], _parse)
    result = type(table)(rows, source_table, mapping, reference)
    if Path(path).read_bytes() != reference_window_csv_text(result).encode():
        raise ValueError(
            "Reference CSV must retain exact source representation and order"
        )
    return result


def validate_reference_window_table(
    path: str | Path,
    *,
    source_table: SourceWindowTable,
    mapping: ResidueMappingTable,
    reference: ProteinReference,
) -> ReferenceWindowTable:
    return read_reference_window_table(
        path, source_table=source_table, mapping=mapping, reference=reference
    )
