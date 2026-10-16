"""Strict, deterministic CSV persistence for the Stage 28.C source table."""

import csv
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mania.preprocessing.protein_edge_window_table import (
    DATASET_PROTEIN_EDGE_WINDOW_CSV_FILENAME,
    DatasetProteinEdgeWindowRow,
    DatasetProteinEdgeWindowTable,
)

DATASET_PROTEIN_EDGE_WINDOW_CSV_COLUMNS = (
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
)

_OPTIONAL_COLUMNS = frozenset(
    (
        "condition",
        "disulfide_state",
        "source_chain_id",
        "target_chain_id",
        "source_resid",
        "target_resid",
    )
)
_INT_COLUMNS = frozenset(
    (
        "window_index",
        "requested_sample_count",
        "resolved_frame_count",
        "missing_sample_count",
        "source_residue_index",
        "target_residue_index",
        "n_contact_frames",
        "n_contact_episodes",
    )
)
_FLOAT_COLUMNS = frozenset(
    (
        "requested_window_start_ns",
        "requested_window_end_ns",
        "effective_window_start_ns",
        "effective_window_end_ns",
        "coverage_fraction",
        "occupancy",
        "mean_episode_length_ns",
        "max_episode_length_ns",
        "edge_weight",
    )
)
_INTEGER = re.compile(r"(?:0|[1-9][0-9]*)")
_FLOAT = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


class DatasetProteinEdgeWindowCsvReadError(ValueError):
    """Unusable CSV encoding, structure, scalar, or table contract."""


def _text(value: object, name: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be a non-empty stripped string")


@dataclass(frozen=True)
class DatasetProteinEdgeWindowCsvWriteResult:
    """Local destination and portable write outcome."""

    output_path: Path
    written: bool
    error: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.output_path, Path):
            raise ValueError("output_path must be a Path")
        if type(self.written) is not bool:
            raise ValueError("written must be a bool")
        if self.error is not None:
            _text(self.error, "error")
        if self.written != (self.error is None):
            raise ValueError("written must be true exactly when error is absent")

    @property
    def passed(self) -> bool:
        return self.written and self.error is None

    def to_dict(self) -> dict[str, object]:
        return {
            "output_path": str(self.output_path),
            "written": self.written,
            "error": self.error,
            "passed": self.passed,
        }


@dataclass(frozen=True)
class DatasetProteinEdgeWindowCsvValidationIssue:
    """Portable issue, containing no file contents or local path."""

    field: str
    message: str

    def __post_init__(self) -> None:
        _text(self.field, "field")
        _text(self.message, "message")

    def to_dict(self) -> dict[str, object]:
        return {"field": self.field, "message": self.message}


@dataclass(frozen=True)
class DatasetProteinEdgeWindowCsvValidationReport:
    """Strict-reader result; passing does not confer publication readiness."""

    csv_path: Path
    row_count: int | None
    issues: tuple[DatasetProteinEdgeWindowCsvValidationIssue, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.csv_path, Path):
            raise ValueError("csv_path must be a Path")
        if self.row_count is not None and (
            type(self.row_count) is not int or self.row_count < 0
        ):
            raise ValueError("row_count must be a non-negative integer or None")
        if not isinstance(self.issues, tuple) or any(
            type(issue) is not DatasetProteinEdgeWindowCsvValidationIssue
            for issue in self.issues
        ):
            raise ValueError("issues must be a tuple of exact CSV validation issues")
        if (self.row_count is None) != bool(self.issues):
            raise ValueError("row_count must be absent exactly when issues exist")

    @property
    def passed(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict[str, object]:
        return {
            "csv_path": str(self.csv_path),
            "row_count": self.row_count,
            "issues": [issue.to_dict() for issue in self.issues],
            "passed": self.passed,
        }


def _serialize(value: object) -> str:
    if value is None:
        return ""
    if type(value) is bool:
        return "true" if value else "false"
    if isinstance(value, float):
        return repr(value)
    return str(value)


def write_dataset_protein_edge_window_csv(
    table: DatasetProteinEdgeWindowTable,
    output_dir: str | Path,
    *,
    overwrite: bool = False,
) -> DatasetProteinEdgeWindowCsvWriteResult:
    """Atomically publish one UTF-8 CSV, including a header for an empty table."""
    if type(table) is not DatasetProteinEdgeWindowTable:
        raise ValueError("table must be exact DatasetProteinEdgeWindowTable")
    if type(overwrite) is not bool:
        raise ValueError("overwrite must be a bool")
    if not isinstance(output_dir, (str, Path)) or output_dir == "":
        raise ValueError("output_dir must be a Path or non-empty string")
    target = Path(output_dir) / DATASET_PROTEIN_EDGE_WINDOW_CSV_FILENAME
    temporary: Path | None = None
    error: str | None = None
    try:
        if not overwrite and os.path.lexists(target):
            return DatasetProteinEdgeWindowCsvWriteResult(
                target, False, "Target already exists."
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=target.parent,
            prefix=f".{DATASET_PROTEIN_EDGE_WINDOW_CSV_FILENAME}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(DATASET_PROTEIN_EDGE_WINDOW_CSV_COLUMNS)
            for row in table.rows:
                writer.writerow(
                    [
                        _serialize(getattr(row, name))
                        for name in DATASET_PROTEIN_EDGE_WINDOW_CSV_COLUMNS
                    ]
                )
        if overwrite:
            os.replace(temporary, target)
        else:
            # Atomic no-clobber publication, even if another writer wins a race.
            os.link(temporary, target)
    except FileExistsError:
        error = "Target already exists."
    except OSError:
        error = "Filesystem write failed."
    except (csv.Error, TypeError, ValueError, OverflowError):
        error = "CSV serialization failed."
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                error = "Temporary file cleanup failed."
    return DatasetProteinEdgeWindowCsvWriteResult(target, error is None, error)


def _parse(name: str, value: str) -> str | bool | int | float | None:
    if name in _OPTIONAL_COLUMNS:
        return None if value == "" else value
    if name == "right_endpoint_inclusive":
        if value not in ("true", "false"):
            raise ValueError("Invalid boolean cell.")
        return value == "true"
    if name in _INT_COLUMNS:
        if _INTEGER.fullmatch(value) is None:
            raise ValueError("Invalid integer cell.")
        return int(value)
    if name in _FLOAT_COLUMNS:
        if _FLOAT.fullmatch(value) is None:
            raise ValueError("Invalid float cell.")
        return float(value)  # Row validation rejects non-finite/negative values.
    return value


def _path(path: str | Path) -> Path:
    if not isinstance(path, (str, Path)) or path == "":
        raise DatasetProteinEdgeWindowCsvReadError(
            "path must be a Path or non-empty string."
        )
    return Path(path)


def read_dataset_protein_edge_window_csv(
    path: str | Path,
) -> DatasetProteinEdgeWindowTable:
    """Require exact columns, scalars, uniqueness and existing row order."""
    target = _path(path)
    try:
        if not stat.S_ISREG(target.stat().st_mode):
            raise ValueError("Expected a regular file.")
        with target.open(encoding="utf-8", newline="") as stream:
            reader = csv.reader(stream, strict=True)
            if tuple(next(reader, ())) != DATASET_PROTEIN_EDGE_WINDOW_CSV_COLUMNS:
                raise ValueError("Invalid header.")
            rows = []
            for cells in reader:
                if len(cells) != len(DATASET_PROTEIN_EDGE_WINDOW_CSV_COLUMNS):
                    raise ValueError("Invalid cell count.")
                values: dict[str, Any] = {
                    name: _parse(name, cell)
                    for name, cell in zip(
                        DATASET_PROTEIN_EDGE_WINDOW_CSV_COLUMNS, cells, strict=True
                    )
                }
                rows.append(DatasetProteinEdgeWindowRow(**values))
        return DatasetProteinEdgeWindowTable(tuple(rows))
    except (OSError, csv.Error, TypeError, ValueError, OverflowError):
        raise DatasetProteinEdgeWindowCsvReadError(
            "Invalid or unreadable Dataset protein-edge window CSV."
        ) from None


def validate_dataset_protein_edge_window_csv(
    path: str | Path,
) -> DatasetProteinEdgeWindowCsvValidationReport:
    """Delegate interpretation to the strict reader without artifact discovery."""
    target = _path(path)
    try:
        table = read_dataset_protein_edge_window_csv(target)
    except DatasetProteinEdgeWindowCsvReadError as exc:
        return DatasetProteinEdgeWindowCsvValidationReport(
            target,
            None,
            (DatasetProteinEdgeWindowCsvValidationIssue("csv", str(exc)),),
        )
    return DatasetProteinEdgeWindowCsvValidationReport(target, table.row_count, ())


__all__ = [
    "DATASET_PROTEIN_EDGE_WINDOW_CSV_COLUMNS",
    "DatasetProteinEdgeWindowCsvReadError",
    "DatasetProteinEdgeWindowCsvValidationIssue",
    "DatasetProteinEdgeWindowCsvValidationReport",
    "DatasetProteinEdgeWindowCsvWriteResult",
    "read_dataset_protein_edge_window_csv",
    "validate_dataset_protein_edge_window_csv",
    "write_dataset_protein_edge_window_csv",
]
