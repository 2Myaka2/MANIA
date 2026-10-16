"""Strict atomic UTF-8 specialized source CSVs, including header-only tables."""

import csv
import io
import re
from pathlib import Path
from typing import Any

from mania.preprocessing.molecular_partner_metadata_io import (
    SpecializedArtifactValidationReport,
    SpecializedArtifactWriteResult,
    write_atomic_text,
)
from mania.preprocessing.protein_edge_window_table_io import (
    _FLOAT,
    _INTEGER,
    _serialize,
)
from mania.preprocessing.specialized_contact_window_tables import (
    DATASET_COLUMNS,
    GLYCAN_COLUMNS,
    LIPID_COLUMNS,
    PROTEIN_COLUMNS,
    PROTEIN_GLYCAN_CONTACTS_BY_WINDOW_SOURCE_FILENAME,
    PROTEIN_LIPID_CONTACTS_BY_WINDOW_SOURCE_FILENAME,
    WINDOW_COLUMNS,
    ProteinGlycanWindowRow,
    ProteinGlycanWindowTable,
    ProteinLipidWindowRow,
    ProteinLipidWindowTable,
)
from mania.preprocessing.specialized_contact_windows import METRIC_COLUMNS

PROTEIN_LIPID_WINDOW_CSV_COLUMNS = (
    DATASET_COLUMNS + WINDOW_COLUMNS + PROTEIN_COLUMNS + LIPID_COLUMNS + METRIC_COLUMNS
)
PROTEIN_GLYCAN_WINDOW_CSV_COLUMNS = (
    DATASET_COLUMNS + WINDOW_COLUMNS + PROTEIN_COLUMNS + GLYCAN_COLUMNS + METRIC_COLUMNS
)
_COMPONENTS = re.compile(r"(?:0|[1-9][0-9]*)(?:;(?:0|[1-9][0-9]*))*")
_OPTIONAL = {
    "condition",
    "disulfide_state",
    "protein_chain_id",
    "protein_resid",
    "carrier_link_atom_index",
    "first_sugar_link_atom_index",
}
_INTS = {
    "window_index",
    "requested_sample_count",
    "resolved_frame_count",
    "missing_sample_count",
    "protein_residue_index",
    "carrier_residue_index",
    "first_sugar_residue_index",
    "carrier_link_atom_index",
    "first_sugar_link_atom_index",
    "n_contact_frames",
    "n_contact_episodes",
}
_FLOATS = {
    "requested_window_start_ns",
    "requested_window_end_ns",
    "effective_window_start_ns",
    "effective_window_end_ns",
    "coverage_fraction",
    "occupancy",
    "mean_episode_length_ns",
    "max_episode_length_ns",
    "distance_mean_A",
    "distance_min_A",
}


class SpecializedContactWindowCsvReadError(ValueError):
    """Invalid specialized source CSV structure, scalar, row, or order."""


def _parse(name: str, value: str) -> Any:
    if value == "" and name in _OPTIONAL:
        return None
    if name in _OPTIONAL and value in ("None", "null", "NA"):
        raise ValueError("Nullable CSV cells must be blank")
    if name.endswith("component_residue_indexes"):
        if not _COMPONENTS.fullmatch(value):
            raise ValueError("Invalid component index encoding")
        indexes = tuple(int(v) for v in value.split(";"))
        if indexes != tuple(sorted(set(indexes))):
            raise ValueError("Component indexes must be strictly increasing")
        return indexes
    if name in _INTS:
        if not _INTEGER.fullmatch(value):
            raise ValueError("Invalid integer cell")
        return int(value)
    if name in _FLOATS:
        if not _FLOAT.fullmatch(value):
            raise ValueError("Invalid numeric cell")
        return float(value)
    if name == "right_endpoint_inclusive":
        if value not in ("true", "false"):
            raise ValueError("Invalid boolean cell")
        return value == "true"
    return value


def _read(path: str | Path, kind: str) -> Any:
    columns = (
        PROTEIN_LIPID_WINDOW_CSV_COLUMNS
        if kind == "lipid"
        else PROTEIN_GLYCAN_WINDOW_CSV_COLUMNS
    )
    row_type = ProteinLipidWindowRow if kind == "lipid" else ProteinGlycanWindowRow
    table_type = (
        ProteinLipidWindowTable if kind == "lipid" else ProteinGlycanWindowTable
    )
    try:
        with Path(path).open(encoding="utf-8", newline="") as stream:
            reader = csv.reader(stream, strict=True)
            if tuple(next(reader, ())) != columns:
                raise ValueError("Invalid exact CSV header")
            rows = []
            for cells in reader:
                values = {
                    name: _parse(name, value)
                    for name, value in zip(columns, cells, strict=True)
                }
                rows.append(row_type(**values))
        return table_type(tuple(rows))
    except (OSError, csv.Error, ValueError, TypeError, OverflowError):
        raise SpecializedContactWindowCsvReadError(
            "Invalid or unreadable specialized contact window CSV."
        ) from None


def read_protein_lipid_window_csv(path: str | Path) -> ProteinLipidWindowTable:
    result: ProteinLipidWindowTable = _read(path, "lipid")
    return result


def read_protein_glycan_window_csv(path: str | Path) -> ProteinGlycanWindowTable:
    result: ProteinGlycanWindowTable = _read(path, "glycan")
    return result


def _write(
    table: ProteinLipidWindowTable | ProteinGlycanWindowTable,
    output_dir: str | Path,
    overwrite: bool,
) -> SpecializedArtifactWriteResult:
    lipid = type(table) is ProteinLipidWindowTable
    columns = (
        PROTEIN_LIPID_WINDOW_CSV_COLUMNS if lipid else PROTEIN_GLYCAN_WINDOW_CSV_COLUMNS
    )
    filename = (
        PROTEIN_LIPID_CONTACTS_BY_WINDOW_SOURCE_FILENAME
        if lipid
        else PROTEIN_GLYCAN_CONTACTS_BY_WINDOW_SOURCE_FILENAME
    )
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(columns)
    for row in table.rows:
        writer.writerow(
            ";".join(str(i) for i in getattr(row, name))
            if name.endswith("component_residue_indexes")
            else _serialize(getattr(row, name))
            for name in columns
        )
    return write_atomic_text(
        stream.getvalue(), Path(output_dir) / filename, overwrite=overwrite
    )


def write_protein_lipid_window_csv(
    table: ProteinLipidWindowTable, output_dir: str | Path, *, overwrite: bool = False
) -> SpecializedArtifactWriteResult:
    if type(table) is not ProteinLipidWindowTable:
        raise ValueError("Exact lipid table required")
    return _write(table, output_dir, overwrite)


def write_protein_glycan_window_csv(
    table: ProteinGlycanWindowTable, output_dir: str | Path, *, overwrite: bool = False
) -> SpecializedArtifactWriteResult:
    if type(table) is not ProteinGlycanWindowTable:
        raise ValueError("Exact glycan table required")
    return _write(table, output_dir, overwrite)


def _validate(path: str | Path, kind: str) -> SpecializedArtifactValidationReport:
    try:
        _read(path, kind)
    except SpecializedContactWindowCsvReadError as exc:
        return SpecializedArtifactValidationReport(Path(path), str(exc))
    return SpecializedArtifactValidationReport(Path(path))


def validate_protein_lipid_window_csv(
    path: str | Path,
) -> SpecializedArtifactValidationReport:
    return _validate(path, "lipid")


def validate_protein_glycan_window_csv(
    path: str | Path,
) -> SpecializedArtifactValidationReport:
    return _validate(path, "glycan")
