"""Strict ordered generic replica CSV; JSON vector cells and absent SD retained."""

import csv
import io
import json
from pathlib import Path

from mania.preprocessing.molecular_partner_metadata_io import write_atomic_text
from mania.replica_aggregation_tables import ReplicaWindowRow, ReplicaWindowTable

COLUMNS = tuple(ReplicaWindowRow.model_fields)


def replica_aggregation_csv_bytes(table: ReplicaWindowTable) -> bytes:
    ReplicaWindowTable.model_validate(table.model_dump())
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(COLUMNS)
    for row in table.rows:
        data = row.model_dump(mode="json")
        values = []
        for key in COLUMNS:
            v = data[key]
            values.append(
                ""
                if v is None
                else json.dumps(v, separators=(",", ":"), allow_nan=False)
                if isinstance(v, list)
                else "true"
                if v is True
                else "false"
                if v is False
                else str(v)
            )
        writer.writerow(values)
    return stream.getvalue().encode()


def read_replica_window_csv(path: Path) -> ReplicaWindowTable:
    with path.open(newline="", encoding="utf-8") as stream:
        records = list(csv.reader(stream))
    if not records or tuple(records[0]) != COLUMNS:
        raise ValueError("CSV column mismatch")
    integers = {
        "window_index",
        "reference_position_i",
        "reference_position_j",
        "n_replicates_available",
        "n_replicates_supporting",
    }
    numbers = {
        "requested_production_start_ns",
        "requested_production_end_ns",
        "requested_window_start_ns",
        "requested_window_end_ns",
        "window_length_ns",
        "window_step_ns",
        "overlap_percent",
        "mean_occupancy",
        "std_occupancy",
        "median_occupancy",
        "support_fraction",
    }
    rows = []
    for cells in records[1:]:
        if len(cells) != len(COLUMNS):
            raise ValueError("CSV row width mismatch")
        data = {}
        for key, value in zip(COLUMNS, cells, strict=True):
            if value == "":
                v = None
            elif key in ("contributing_replica_keys", "occupancy_values"):
                v = json.loads(value)
            elif key == "right_endpoint_inclusive":
                if value not in ("true", "false"):
                    raise ValueError("CSV boolean must be true/false")
                v = value == "true"
            elif key in integers:
                if not value.isdecimal():
                    raise ValueError("CSV integer syntax invalid")
                v = int(value)
            elif key in numbers:
                v = float(value)
            else:
                v = value
            data[key] = v
        rows.append(
            ReplicaWindowRow.model_validate_json(json.dumps(data, allow_nan=False))
        )
    return ReplicaWindowTable(rows=tuple(rows))


def write_replica_window_csv(
    table: ReplicaWindowTable, path: Path, *, overwrite: bool = False
) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(path)
    result = write_atomic_text(
        replica_aggregation_csv_bytes(table).decode(), path, overwrite=overwrite
    )
    if not result.passed:
        raise ValueError(result.error)
