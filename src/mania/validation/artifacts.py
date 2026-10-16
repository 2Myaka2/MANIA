"""Lightweight CSV artifact validators for MANIA."""

from __future__ import annotations

import csv
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from mania.constants import ARTIFACT_COLUMNS


class ArtifactValidationError(Exception):
    """Raised when an artifact fails lightweight validation."""


@dataclass(frozen=True)
class ArtifactValidationResult:
    """Result of validating a CSV artifact header."""

    artifact_name: str
    path: Path
    columns: tuple[str, ...]
    expected_columns: tuple[str, ...]
    missing_columns: tuple[str, ...]
    extra_columns: tuple[str, ...]
    duplicate_columns: tuple[str, ...]
    allow_extra_columns: bool = False

    @property
    def is_valid(self) -> bool:
        """Return whether the schema satisfies the requested constraints."""
        extras_are_valid = self.allow_extra_columns or not self.extra_columns
        return (
            not self.missing_columns
            and not self.duplicate_columns
            and extras_are_valid
        )


def read_csv_header(path: str | Path) -> tuple[str, ...]:
    """Read and return the first row from a CSV file."""
    csv_path = Path(path)
    with csv_path.open(encoding="utf-8", newline="") as csv_file:
        reader = csv.reader(csv_file)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise ArtifactValidationError(f"CSV file is empty: {csv_path}") from exc
    if not header:
        raise ArtifactValidationError(f"CSV file has an empty header: {csv_path}")
    return tuple(header)


def validate_csv_artifact_schema(
    path: str | Path,
    artifact_name: str,
    *,
    expected_columns: Sequence[str] | None = None,
    allow_extra_columns: bool = False,
) -> ArtifactValidationResult:
    """Validate a CSV artifact header against the MANIA data contract."""
    expected = _resolve_expected_columns(artifact_name, expected_columns)
    columns = read_csv_header(path)
    missing_columns = _missing_columns(columns, expected)
    extra_columns = _extra_columns(columns, expected)
    duplicate_columns = _duplicate_columns(columns)
    result = ArtifactValidationResult(
        artifact_name=artifact_name,
        path=Path(path),
        columns=columns,
        expected_columns=expected,
        missing_columns=missing_columns,
        extra_columns=extra_columns,
        duplicate_columns=duplicate_columns,
        allow_extra_columns=allow_extra_columns,
    )
    if not result.is_valid:
        raise ArtifactValidationError(_format_schema_error(result))
    return result


def validate_condition_column(
    path: str | Path,
    expected_condition: str,
    *,
    condition_column: str = "condition",
) -> None:
    """Validate that every CSV data row has the expected condition value."""
    csv_path = Path(path)
    with csv_path.open(encoding="utf-8", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        if reader.fieldnames is None:
            raise ArtifactValidationError(f"CSV file is empty: {csv_path}")
        if condition_column not in reader.fieldnames:
            raise ArtifactValidationError(
                f"Missing condition column {condition_column!r}: {csv_path}"
            )

        for row_number, row in enumerate(reader, start=2):
            if _is_empty_data_row(row):
                continue
            condition = row.get(condition_column)
            if condition is None or condition.strip() == "":
                raise ArtifactValidationError(
                    f"Missing condition value at row {row_number}: {csv_path}"
                )
            if condition != expected_condition:
                raise ArtifactValidationError(
                    "Mismatched condition value at "
                    f"row {row_number}: expected {expected_condition!r}, "
                    f"got {condition!r}"
                )


def _resolve_expected_columns(
    artifact_name: str,
    expected_columns: Sequence[str] | None,
) -> tuple[str, ...]:
    if expected_columns is not None:
        return tuple(expected_columns)
    if artifact_name not in ARTIFACT_COLUMNS:
        raise ArtifactValidationError(
            f"Unknown artifact {artifact_name!r}; provide expected_columns"
        )
    return ARTIFACT_COLUMNS[artifact_name]


def _missing_columns(
    columns: tuple[str, ...],
    expected_columns: tuple[str, ...],
) -> tuple[str, ...]:
    column_set = set(columns)
    return tuple(column for column in expected_columns if column not in column_set)


def _extra_columns(
    columns: tuple[str, ...],
    expected_columns: tuple[str, ...],
) -> tuple[str, ...]:
    expected_set = set(expected_columns)
    extras: list[str] = []
    seen_extras: set[str] = set()
    for column in columns:
        if column in expected_set or column in seen_extras:
            continue
        extras.append(column)
        seen_extras.add(column)
    return tuple(extras)


def _duplicate_columns(columns: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    duplicates: list[str] = []
    duplicate_set: set[str] = set()
    for column in columns:
        if column in seen and column not in duplicate_set:
            duplicates.append(column)
            duplicate_set.add(column)
        seen.add(column)
    return tuple(duplicates)


def _format_schema_error(result: ArtifactValidationResult) -> str:
    problems: list[str] = []
    if result.missing_columns:
        problems.append(f"missing columns: {', '.join(result.missing_columns)}")
    if result.extra_columns and not result.allow_extra_columns:
        problems.append(f"extra columns: {', '.join(result.extra_columns)}")
    if result.duplicate_columns:
        problems.append(f"duplicate columns: {', '.join(result.duplicate_columns)}")
    problem_text = "; ".join(problems)
    return f"Invalid schema for {result.artifact_name}: {problem_text}"


def _is_empty_data_row(row: dict[str, str | None]) -> bool:
    return all(value is None or value.strip() == "" for value in row.values())


__all__ = [
    "ArtifactValidationError",
    "ArtifactValidationResult",
    "read_csv_header",
    "validate_condition_column",
    "validate_csv_artifact_schema",
]
