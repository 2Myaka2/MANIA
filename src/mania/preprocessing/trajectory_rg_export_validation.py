"""Dependency-free validation for exported Rg CSV files."""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

_EXPECTED_HEADER = (
    "condition_name",
    "frame_index",
    "time_ps",
    "rg_value",
    "rg_unit",
    "frame_passed",
)


@dataclass(frozen=True)
class PreprocessingRgCsvValidationIssue:
    """One deterministic Rg CSV validation issue."""

    kind: Literal[
        "missing_file",
        "not_file",
        "read_error",
        "empty_file",
        "invalid_header",
        "no_data_rows",
        "invalid_column_count",
        "missing_condition_name",
        "invalid_frame_index",
        "invalid_time_ps",
        "invalid_rg_value",
        "invalid_rg_unit",
        "invalid_frame_passed",
        "passed_frame_missing_rg_value",
        "passed_frame_missing_rg_unit",
        "non_monotonic_frame_index",
    ]
    row_number: int | None
    field: str
    message: str

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable issue dictionary."""
        return {
            "kind": self.kind,
            "row_number": self.row_number,
            "field": self.field,
            "message": self.message,
        }


@dataclass(frozen=True)
class PreprocessingRgCsvValidationResult:
    """Summary of one Rg CSV validation attempt."""

    csv_path: Path
    passed: bool
    row_count: int
    valid_row_count: int
    invalid_row_count: int
    issues: tuple[PreprocessingRgCsvValidationIssue, ...]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable validation summary."""
        return {
            "csv_path": str(self.csv_path),
            "passed": self.passed,
            "row_count": self.row_count,
            "valid_row_count": self.valid_row_count,
            "invalid_row_count": self.invalid_row_count,
            "issues": [issue.to_dict() for issue in self.issues],
        }


def validate_rg_timeseries_csv(
    csv_path: str | Path,
) -> PreprocessingRgCsvValidationResult:
    """Validate one existing Rg CSV file without modifying it."""
    path = Path(csv_path)
    if not path.exists():
        return _file_issue_result(
            path,
            kind="missing_file",
            field="csv_path",
            message="Rg CSV file does not exist.",
        )
    if not path.is_file():
        return _file_issue_result(
            path,
            kind="not_file",
            field="csv_path",
            message="Rg CSV path is not a file.",
        )

    try:
        with path.open(encoding="utf-8", newline="") as csv_file:
            reader = csv.reader(csv_file, strict=True)
            try:
                header = tuple(next(reader))
            except StopIteration:
                return _file_issue_result(
                    path,
                    kind="empty_file",
                    field="csv_path",
                    message="Rg CSV file is empty.",
                )
            rows = list(reader)
    except (OSError, UnicodeError, csv.Error):
        return _file_issue_result(
            path,
            kind="read_error",
            field="csv_path",
            message="Rg CSV file could not be read as UTF-8 CSV.",
        )

    if header != _EXPECTED_HEADER:
        return _file_issue_result(
            path,
            kind="invalid_header",
            field="header",
            message="Rg CSV header does not match the expected schema.",
        )
    if not rows:
        return _file_issue_result(
            path,
            kind="no_data_rows",
            field="rows",
            message="Rg CSV file contains no data rows.",
        )

    issues: list[PreprocessingRgCsvValidationIssue] = []
    valid_row_count = 0
    invalid_row_count = 0
    last_frame_index_by_condition: dict[str, int] = {}

    for row_number, row in enumerate(rows, start=2):
        row_issues = _validate_row(
            row,
            row_number=row_number,
            last_frame_index_by_condition=last_frame_index_by_condition,
        )
        issues.extend(row_issues)
        if row_issues:
            invalid_row_count += 1
        else:
            valid_row_count += 1

    return PreprocessingRgCsvValidationResult(
        csv_path=path,
        passed=not issues,
        row_count=len(rows),
        valid_row_count=valid_row_count,
        invalid_row_count=invalid_row_count,
        issues=tuple(issues),
    )


def _validate_row(
    row: list[str],
    *,
    row_number: int,
    last_frame_index_by_condition: dict[str, int],
) -> list[PreprocessingRgCsvValidationIssue]:
    issues: list[PreprocessingRgCsvValidationIssue] = []
    if len(row) != len(_EXPECTED_HEADER):
        issues.append(
            _row_issue(
                kind="invalid_column_count",
                row_number=row_number,
                field="row",
                message="CSV row must contain exactly 6 columns.",
            )
        )

    condition_name = _field(row, 0)
    normalized_condition: str | None = None
    if condition_name is not None:
        normalized_condition = condition_name.strip()
        if not normalized_condition:
            issues.append(
                _row_issue(
                    kind="missing_condition_name",
                    row_number=row_number,
                    field="condition_name",
                    message="Condition name must not be empty.",
                )
            )
            normalized_condition = None

    frame_index_text = _field(row, 1)
    frame_index: int | None = None
    if frame_index_text is not None:
        frame_index = _non_negative_integer(frame_index_text)
        if frame_index is None:
            issues.append(
                _row_issue(
                    kind="invalid_frame_index",
                    row_number=row_number,
                    field="frame_index",
                    message="Frame index must be a non-negative integer.",
                )
            )

    time_text = _field(row, 2)
    if time_text is not None and not _valid_optional_number(time_text):
        issues.append(
            _row_issue(
                kind="invalid_time_ps",
                row_number=row_number,
                field="time_ps",
                message="Frame time must be empty or a finite non-negative number.",
            )
        )

    rg_value_text = _field(row, 3)
    rg_value_valid = (
        rg_value_text is not None
        and _valid_optional_number(rg_value_text)
    )
    if rg_value_text is not None and not rg_value_valid:
        issues.append(
            _row_issue(
                kind="invalid_rg_value",
                row_number=row_number,
                field="rg_value",
                message="Rg value must be empty or a finite non-negative number.",
            )
        )

    rg_unit = _field(row, 4)
    rg_unit_valid = rg_unit is not None and (
        rg_unit == "" or bool(rg_unit.strip())
    )
    if rg_unit is not None and not rg_unit_valid:
        issues.append(
            _row_issue(
                kind="invalid_rg_unit",
                row_number=row_number,
                field="rg_unit",
                message="Rg unit must be empty or contain non-whitespace text.",
            )
        )

    frame_passed = _field(row, 5)
    frame_passed_valid = frame_passed in ("true", "false")
    if frame_passed is not None and not frame_passed_valid:
        issues.append(
            _row_issue(
                kind="invalid_frame_passed",
                row_number=row_number,
                field="frame_passed",
                message="Frame passed value must be exactly true or false.",
            )
        )

    if frame_passed == "true":
        if rg_value_text == "":
            issues.append(
                _row_issue(
                    kind="passed_frame_missing_rg_value",
                    row_number=row_number,
                    field="rg_value",
                    message="A passed frame must include an Rg value.",
                )
            )
        if rg_unit == "":
            issues.append(
                _row_issue(
                    kind="passed_frame_missing_rg_unit",
                    row_number=row_number,
                    field="rg_unit",
                    message="A passed frame must include an Rg unit.",
                )
            )

    if normalized_condition is not None and frame_index is not None:
        last_frame_index = last_frame_index_by_condition.get(
            normalized_condition
        )
        if last_frame_index is not None and frame_index < last_frame_index:
            issues.append(
                _row_issue(
                    kind="non_monotonic_frame_index",
                    row_number=row_number,
                    field="frame_index",
                    message=(
                        "Frame index is smaller than the previous index "
                        "for this condition."
                    ),
                )
            )
        last_frame_index_by_condition[normalized_condition] = frame_index

    return issues


def _field(row: list[str], index: int) -> str | None:
    if index >= len(row):
        return None
    return row[index]


def _non_negative_integer(value: str) -> int | None:
    if not value or any(character < "0" or character > "9" for character in value):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _valid_optional_number(value: str) -> bool:
    if value == "":
        return True
    try:
        number = float(value)
    except ValueError:
        return False
    return math.isfinite(number) and number >= 0


def _row_issue(
    *,
    kind: Literal[
        "invalid_column_count",
        "missing_condition_name",
        "invalid_frame_index",
        "invalid_time_ps",
        "invalid_rg_value",
        "invalid_rg_unit",
        "invalid_frame_passed",
        "passed_frame_missing_rg_value",
        "passed_frame_missing_rg_unit",
        "non_monotonic_frame_index",
    ],
    row_number: int,
    field: str,
    message: str,
) -> PreprocessingRgCsvValidationIssue:
    return PreprocessingRgCsvValidationIssue(
        kind=kind,
        row_number=row_number,
        field=field,
        message=message,
    )


def _file_issue_result(
    csv_path: Path,
    *,
    kind: Literal[
        "missing_file",
        "not_file",
        "read_error",
        "empty_file",
        "invalid_header",
        "no_data_rows",
    ],
    field: str,
    message: str,
) -> PreprocessingRgCsvValidationResult:
    return PreprocessingRgCsvValidationResult(
        csv_path=csv_path,
        passed=False,
        row_count=0,
        valid_row_count=0,
        invalid_row_count=0,
        issues=(
            PreprocessingRgCsvValidationIssue(
                kind=kind,
                row_number=None,
                field=field,
                message=message,
            ),
        ),
    )


__all__ = [
    "PreprocessingRgCsvValidationIssue",
    "PreprocessingRgCsvValidationResult",
    "validate_rg_timeseries_csv",
]
