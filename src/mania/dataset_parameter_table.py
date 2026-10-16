"""Strict Dataset identity and requested-parameter CSV input contract.

Stage 26.B reads explicit rows only; execution binding belongs to Stage 26.C
and physical-time frame/window mechanics belong to Stage 27.
"""

from __future__ import annotations

import csv
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from mania.dataset_identity import (
    DatasetTemporalParameters,
    DatasetTrajectoryIdentity,
    DatasetTrajectorySpec,
)

DATASET_PARAMETER_TABLE_SCHEMA_VERSION = "mania.dataset_parameter_table.v0.1"
DATASET_PARAMETER_TABLE_KIND = "mania_dataset_parameter_table"
DATASET_PARAMETER_TABLE_COLUMNS = (
    "dataset_id",
    "system_id",
    "trajectory_id",
    "variant_id",
    "engine",
    "condition",
    "replica_id",
    "disulfide_state",
    "production_start_ns",
    "production_end_ns",
    "frame_stride_ps",
    "window_length_ns",
    "window_step_ns",
    "overlap_percent",
)


class DatasetParameterTable(BaseModel):
    """An ordered, non-empty set of requested specs with unique replica keys."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    specs: tuple[DatasetTrajectorySpec, ...] = Field(min_length=1)

    @field_validator("specs")
    @classmethod
    def validate_unique_replica_keys(
        cls, value: tuple[DatasetTrajectorySpec, ...]
    ) -> tuple[DatasetTrajectorySpec, ...]:
        """Validate identity uniqueness without scientific condition grouping."""
        seen_keys: set[tuple[str, str, str, str]] = set()
        for spec in value:
            key = spec.identity.replica_key
            if key in seen_keys:
                raise ValueError(f"Duplicate Dataset replica_key: {key!r}")
            seen_keys.add(key)
        return value

    @property
    def schema_version(self) -> str:
        """Expose the version without accepting a user-supplied schema tag."""
        return DATASET_PARAMETER_TABLE_SCHEMA_VERSION

    @property
    def kind(self) -> str:
        """Expose the kind without accepting a user-supplied schema tag."""
        return DATASET_PARAMETER_TABLE_KIND

    @property
    def row_count(self) -> int:
        """Return the number of supplied specs."""
        return len(self.specs)

    def to_dict(self) -> dict[str, object]:
        """Return independent JSON-safe data retaining source row order."""
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "row_count": self.row_count,
            "specs": [spec.to_dict() for spec in self.specs],
        }


class DatasetParameterTableReadError(ValueError):
    """An explicit CSV file could not be read as a Dataset parameter table."""


def read_dataset_parameter_table_csv(path: str | Path) -> DatasetParameterTable:
    """Read exact UTF-8 CSV columns and validate each row with Stage 26.A models."""
    table_path = Path(path)
    try:
        if not table_path.is_file():
            raise DatasetParameterTableReadError(
                "Dataset parameter table must be an existing regular file: "
                f"{table_path}"
            )
        with table_path.open("r", encoding="utf-8", newline="") as source:
            reader = csv.reader(source, strict=True)
            header = next(reader, None)
            if header is None or tuple(header) != DATASET_PARAMETER_TABLE_COLUMNS:
                raise DatasetParameterTableReadError(
                    f"Dataset parameter table header must equal "
                    f"{DATASET_PARAMETER_TABLE_COLUMNS!r}: {table_path}"
                )
            specs: list[DatasetTrajectorySpec] = []
            for row in reader:
                if len(row) != len(DATASET_PARAMETER_TABLE_COLUMNS):
                    raise DatasetParameterTableReadError(
                        f"Expected {len(DATASET_PARAMETER_TABLE_COLUMNS)} columns "
                        f"at line {reader.line_num}: {table_path}"
                    )
                cells = dict(zip(DATASET_PARAMETER_TABLE_COLUMNS, row, strict=True))
                try:
                    identity = DatasetTrajectoryIdentity.model_validate(
                        {
                            column: (
                                None
                                if column in {"condition", "disulfide_state"}
                                and not cells[column].strip()
                                else cells[column]
                            )
                            for column in DATASET_PARAMETER_TABLE_COLUMNS[:8]
                        }
                    )
                    temporal = DatasetTemporalParameters.model_validate(
                        {
                            column: float(cells[column])
                            for column in DATASET_PARAMETER_TABLE_COLUMNS[8:]
                        }
                    )
                    specs.append(
                        DatasetTrajectorySpec(identity=identity, temporal=temporal)
                    )
                except ValueError as exc:
                    raise DatasetParameterTableReadError(
                        f"Invalid Dataset parameter row at line {reader.line_num} "
                        f"in {table_path}: {exc}"
                    ) from exc
        return DatasetParameterTable(specs=tuple(specs))
    except (OSError, UnicodeError, csv.Error, ValidationError) as exc:
        raise DatasetParameterTableReadError(
            f"Cannot read Dataset parameter table {table_path}: {exc}"
        ) from exc


__all__ = [
    "DATASET_PARAMETER_TABLE_COLUMNS",
    "DATASET_PARAMETER_TABLE_KIND",
    "DATASET_PARAMETER_TABLE_SCHEMA_VERSION",
    "DatasetParameterTable",
    "DatasetParameterTableReadError",
    "read_dataset_parameter_table_csv",
]
