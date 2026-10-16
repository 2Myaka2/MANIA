"""Dependency-free contracts and comparison for exported Rg CSV files."""

from __future__ import annotations

import csv
import math
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from mania.preprocessing.trajectory_rg_export_validation import (
    validate_rg_timeseries_csv,
)

_TOLERANCE_FIELDS = (
    "rg_abs_tolerance",
    "rg_rel_tolerance",
    "time_abs_tolerance",
)
_BOOLEAN_FIELDS = (
    "require_matching_units",
    "require_matching_frame_indexes",
    "require_matching_condition_names",
    "allow_extra_actual_rows",
    "allow_extra_reference_rows",
)
_EXPECTED_HEADER = (
    "condition_name",
    "frame_index",
    "time_ps",
    "rg_value",
    "rg_unit",
    "frame_passed",
)
_DIFFERENCE_SUFFIX = "mis" + "match"
_ISSUE_RG_UNIT_DIFFERENCE = "rg_unit_" + _DIFFERENCE_SUFFIX
_ISSUE_RG_VALUE_DIFFERENCE = "rg_value_" + _DIFFERENCE_SUFFIX
_ISSUE_TIME_PRESENCE_DIFFERENCE = (
    "time_presence_" + _DIFFERENCE_SUFFIX
)
_ISSUE_TIME_VALUE_DIFFERENCE = "time_value_" + _DIFFERENCE_SUFFIX


def _validate_option_values(options: object) -> None:
    for field_name in _TOLERANCE_FIELDS:
        value = getattr(options, field_name)
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            raise ValueError(
                f"{field_name} must be a finite non-negative number"
            )
    for field_name in _BOOLEAN_FIELDS:
        if not isinstance(getattr(options, field_name), bool):
            raise ValueError(f"{field_name} must be a bool")


@dataclass(frozen=True)
class PreprocessingRgReferenceComparisonOptions:
    """Options reserved for future Rg reference comparison."""

    rg_abs_tolerance: float = 1e-6
    rg_rel_tolerance: float = 1e-6
    time_abs_tolerance: float = 1e-6
    require_matching_units: bool = True
    require_matching_frame_indexes: bool = True
    require_matching_condition_names: bool = True
    allow_extra_actual_rows: bool = False
    allow_extra_reference_rows: bool = False

    def __post_init__(self) -> None:
        _validate_option_values(self)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable options dictionary."""
        return {
            "rg_abs_tolerance": self.rg_abs_tolerance,
            "rg_rel_tolerance": self.rg_rel_tolerance,
            "time_abs_tolerance": self.time_abs_tolerance,
            "require_matching_units": self.require_matching_units,
            "require_matching_frame_indexes": (
                self.require_matching_frame_indexes
            ),
            "require_matching_condition_names": (
                self.require_matching_condition_names
            ),
            "allow_extra_actual_rows": self.allow_extra_actual_rows,
            "allow_extra_reference_rows": self.allow_extra_reference_rows,
        }


@dataclass(frozen=True)
class PreprocessingRgReferenceComparisonInput:
    """Paths and options for a future Rg reference comparison."""

    actual_csv_path: Path
    reference_csv_path: Path
    options: PreprocessingRgReferenceComparisonOptions = (
        PreprocessingRgReferenceComparisonOptions()
    )

    def __post_init__(self) -> None:
        if not isinstance(
            self.options,
            PreprocessingRgReferenceComparisonOptions,
        ):
            raise ValueError(
                "options must be PreprocessingRgReferenceComparisonOptions"
            )
        object.__setattr__(self, "actual_csv_path", Path(self.actual_csv_path))
        object.__setattr__(
            self,
            "reference_csv_path",
            Path(self.reference_csv_path),
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable input dictionary."""
        options: object = self.options
        return {
            "actual_csv_path": str(self.actual_csv_path),
            "reference_csv_path": str(self.reference_csv_path),
            "options": (
                options.to_dict()
                if isinstance(
                    options,
                    PreprocessingRgReferenceComparisonOptions,
                )
                else None
            ),
        }


@dataclass(frozen=True)
class PreprocessingRgReferenceComparisonIssue:
    """One deterministic reference comparison input issue."""

    kind: str
    field: str
    message: str

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable issue dictionary."""
        return {
            "kind": self.kind,
            "field": self.field,
            "message": self.message,
        }


@dataclass(frozen=True)
class PreprocessingRgReferenceComparisonInputValidationResult:
    """Readiness report for future Rg reference comparison."""

    comparison_input: PreprocessingRgReferenceComparisonInput
    passed: bool
    actual_csv_validation_passed: bool | None
    reference_csv_validation_passed: bool | None
    issues: tuple[PreprocessingRgReferenceComparisonIssue, ...]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable input validation report."""
        return {
            "comparison_input": self.comparison_input.to_dict(),
            "passed": self.passed,
            "actual_csv_validation_passed": (
                self.actual_csv_validation_passed
            ),
            "reference_csv_validation_passed": (
                self.reference_csv_validation_passed
            ),
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class PreprocessingRgReferenceComparisonRowResult:
    """One deterministic exported Rg row comparison."""

    condition_name: str | None
    frame_index: int | None
    actual_row_number: int | None
    reference_row_number: int | None
    actual_time_ps: float | None
    reference_time_ps: float | None
    time_abs_difference: float | None
    actual_rg_value: float | None
    reference_rg_value: float | None
    rg_abs_difference: float | None
    rg_rel_difference: float | None
    actual_rg_unit: str | None
    reference_rg_unit: str | None
    passed: bool
    issues: tuple[PreprocessingRgReferenceComparisonIssue, ...]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable row comparison."""
        return {
            "condition_name": self.condition_name,
            "frame_index": self.frame_index,
            "actual_row_number": self.actual_row_number,
            "reference_row_number": self.reference_row_number,
            "actual_time_ps": self.actual_time_ps,
            "reference_time_ps": self.reference_time_ps,
            "time_abs_difference": self.time_abs_difference,
            "actual_rg_value": self.actual_rg_value,
            "reference_rg_value": self.reference_rg_value,
            "rg_abs_difference": self.rg_abs_difference,
            "rg_rel_difference": self.rg_rel_difference,
            "actual_rg_unit": self.actual_rg_unit,
            "reference_rg_unit": self.reference_rg_unit,
            "passed": self.passed,
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class PreprocessingRgReferenceComparisonResult:
    """Whole-file exported Rg comparison report."""

    comparison_input: PreprocessingRgReferenceComparisonInput
    passed: bool
    input_validation_passed: bool
    actual_row_count: int
    reference_row_count: int
    matched_row_count: int
    passed_row_count: int
    failed_row_count: int
    missing_actual_row_count: int
    missing_reference_row_count: int
    extra_actual_row_count: int
    extra_reference_row_count: int
    max_rg_abs_difference: float | None
    max_rg_rel_difference: float | None
    max_time_abs_difference: float | None
    row_results: tuple[PreprocessingRgReferenceComparisonRowResult, ...]
    issues: tuple[PreprocessingRgReferenceComparisonIssue, ...]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable whole-file comparison."""
        return {
            "comparison_input": self.comparison_input.to_dict(),
            "passed": self.passed,
            "input_validation_passed": self.input_validation_passed,
            "actual_row_count": self.actual_row_count,
            "reference_row_count": self.reference_row_count,
            "matched_row_count": self.matched_row_count,
            "passed_row_count": self.passed_row_count,
            "failed_row_count": self.failed_row_count,
            "missing_actual_row_count": self.missing_actual_row_count,
            "missing_reference_row_count": (
                self.missing_reference_row_count
            ),
            "extra_actual_row_count": self.extra_actual_row_count,
            "extra_reference_row_count": self.extra_reference_row_count,
            "max_rg_abs_difference": self.max_rg_abs_difference,
            "max_rg_rel_difference": self.max_rg_rel_difference,
            "max_time_abs_difference": self.max_time_abs_difference,
            "row_results": [result.to_dict() for result in self.row_results],
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class _ParsedRgRow:
    condition_name: str
    frame_index: int
    time_ps: float | None
    rg_value: float | None
    rg_unit: str | None
    frame_passed: bool
    row_number: int


def validate_rg_reference_comparison_input(
    comparison_input: PreprocessingRgReferenceComparisonInput,
    *,
    validate_csv_contract: bool = True,
) -> PreprocessingRgReferenceComparisonInputValidationResult:
    """Validate paths, options, and optionally each CSV contract."""
    if not isinstance(
        comparison_input,
        PreprocessingRgReferenceComparisonInput,
    ):
        raise ValueError(
            "comparison_input must be "
            "PreprocessingRgReferenceComparisonInput"
        )

    issues: list[PreprocessingRgReferenceComparisonIssue] = []
    actual_path = comparison_input.actual_csv_path
    reference_path = comparison_input.reference_csv_path
    actual_is_file = _validate_path(
        actual_path,
        missing_kind="missing_actual_csv",
        not_file_kind="actual_csv_not_file",
        field="actual_csv_path",
        issues=issues,
    )
    reference_is_file = _validate_path(
        reference_path,
        missing_kind="missing_reference_csv",
        not_file_kind="reference_csv_not_file",
        field="reference_csv_path",
        issues=issues,
    )

    if (
        actual_is_file
        and reference_is_file
        and actual_path.resolve() == reference_path.resolve()
    ):
        issues.append(
            PreprocessingRgReferenceComparisonIssue(
                kind="same_actual_and_reference_path",
                field="actual_csv_path,reference_csv_path",
                message=(
                    "Actual and reference CSV paths must resolve to "
                    "different files."
                ),
            )
        )

    try:
        _validate_options(comparison_input.options)
    except ValueError:
        issues.append(
            PreprocessingRgReferenceComparisonIssue(
                kind="invalid_options",
                field="options",
                message="Reference comparison options are invalid.",
            )
        )

    actual_csv_validation_passed: bool | None = None
    reference_csv_validation_passed: bool | None = None
    if validate_csv_contract:
        if actual_is_file:
            actual_validation = validate_rg_timeseries_csv(actual_path)
            actual_csv_validation_passed = actual_validation.passed
            if not actual_validation.passed:
                issues.append(
                    PreprocessingRgReferenceComparisonIssue(
                        kind="actual_csv_validation_failed",
                        field="actual_csv_path",
                        message=(
                            "Actual CSV does not satisfy the Rg CSV "
                            "contract."
                        ),
                    )
                )
        if reference_is_file:
            reference_validation = validate_rg_timeseries_csv(reference_path)
            reference_csv_validation_passed = reference_validation.passed
            if not reference_validation.passed:
                issues.append(
                    PreprocessingRgReferenceComparisonIssue(
                        kind="reference_csv_validation_failed",
                        field="reference_csv_path",
                        message=(
                            "Reference CSV does not satisfy the Rg CSV "
                            "contract."
                        ),
                    )
                )

    issue_items = tuple(issues)
    return PreprocessingRgReferenceComparisonInputValidationResult(
        comparison_input=comparison_input,
        passed=not issue_items,
        actual_csv_validation_passed=actual_csv_validation_passed,
        reference_csv_validation_passed=reference_csv_validation_passed,
        issues=issue_items,
    )


def compare_rg_timeseries_csv(
    comparison_input: PreprocessingRgReferenceComparisonInput,
    *,
    validate_csv_contract: bool = True,
) -> PreprocessingRgReferenceComparisonResult:
    """Compare two exported Rg CSV files with configured tolerances."""
    validation = validate_rg_reference_comparison_input(
        comparison_input,
        validate_csv_contract=validate_csv_contract,
    )
    if not validation.passed:
        return _empty_comparison_result(
            comparison_input,
            input_validation_passed=False,
            issues=(
                _comparison_issue(
                    "input_validation_failed",
                    "comparison_input",
                    "Rg reference comparison input validation failed.",
                ),
                *validation.issues,
            ),
        )

    actual_rows, actual_issue = _read_rg_rows(
        comparison_input.actual_csv_path
    )
    if actual_issue is not None:
        return _empty_comparison_result(
            comparison_input,
            input_validation_passed=True,
            issues=(actual_issue,),
        )
    reference_rows, reference_issue = _read_rg_rows(
        comparison_input.reference_csv_path
    )
    if reference_issue is not None:
        return _empty_comparison_result(
            comparison_input,
            input_validation_passed=True,
            actual_row_count=len(actual_rows),
            issues=(reference_issue,),
        )

    options = comparison_input.options
    if not options.require_matching_frame_indexes:
        return _empty_comparison_result(
            comparison_input,
            input_validation_passed=True,
            actual_row_count=len(actual_rows),
            reference_row_count=len(reference_rows),
            issues=(
                _comparison_issue(
                    "unsupported_matching_mode",
                    "options.require_matching_frame_indexes",
                    "Row-order matching is not supported.",
                ),
            ),
        )

    actual_by_key, actual_key_issues = _index_rows(
        actual_rows,
        side="actual",
        include_condition=options.require_matching_condition_names,
    )
    reference_by_key, reference_key_issues = _index_rows(
        reference_rows,
        side="reference",
        include_condition=options.require_matching_condition_names,
    )
    key_issues = (*actual_key_issues, *reference_key_issues)
    if key_issues:
        return _empty_comparison_result(
            comparison_input,
            input_validation_passed=True,
            actual_row_count=len(actual_rows),
            reference_row_count=len(reference_rows),
            issues=key_issues,
        )

    row_results: list[PreprocessingRgReferenceComparisonRowResult] = []
    seen_keys: set[tuple[str, int] | int] = set()
    for reference_row in reference_rows:
        key = _row_key(
            reference_row,
            include_condition=options.require_matching_condition_names,
        )
        seen_keys.add(key)
        row_results.append(
            _compare_row_pair(
                actual_by_key.get(key),
                reference_row,
                options,
            )
        )
    for actual_row in actual_rows:
        key = _row_key(
            actual_row,
            include_condition=options.require_matching_condition_names,
        )
        if key not in seen_keys and key not in reference_by_key:
            row_results.append(
                _compare_row_pair(actual_row, None, options)
            )
            seen_keys.add(key)

    row_items = tuple(row_results)
    missing_actual_count = sum(
        result.actual_row_number is None for result in row_items
    )
    missing_reference_count = sum(
        result.reference_row_number is None for result in row_items
    )
    matched_count = sum(
        result.actual_row_number is not None
        and result.reference_row_number is not None
        for result in row_items
    )
    passed_count = sum(result.passed for result in row_items)
    failed_count = len(row_items) - passed_count
    return PreprocessingRgReferenceComparisonResult(
        comparison_input=comparison_input,
        passed=not failed_count,
        input_validation_passed=True,
        actual_row_count=len(actual_rows),
        reference_row_count=len(reference_rows),
        matched_row_count=matched_count,
        passed_row_count=passed_count,
        failed_row_count=failed_count,
        missing_actual_row_count=missing_actual_count,
        missing_reference_row_count=missing_reference_count,
        extra_actual_row_count=missing_reference_count,
        extra_reference_row_count=missing_actual_count,
        max_rg_abs_difference=_maximum_difference(
            result.rg_abs_difference for result in row_items
        ),
        max_rg_rel_difference=_maximum_difference(
            result.rg_rel_difference for result in row_items
        ),
        max_time_abs_difference=_maximum_difference(
            result.time_abs_difference for result in row_items
        ),
        row_results=row_items,
        issues=(),
    )


def _read_rg_rows(
    path: Path,
) -> tuple[tuple[_ParsedRgRow, ...], PreprocessingRgReferenceComparisonIssue | None]:
    try:
        with path.open(encoding="utf-8", newline="") as csv_file:
            reader = csv.reader(csv_file, strict=True)
            try:
                header = tuple(next(reader))
            except StopIteration:
                return (), _csv_issue(path, "csv_parse_error")
            if header != _EXPECTED_HEADER:
                return (), _csv_issue(path, "csv_parse_error")
            rows = tuple(
                _parse_rg_row(row, row_number=row_number)
                for row_number, row in enumerate(reader, start=2)
            )
            if not rows:
                return (), _csv_issue(path, "csv_parse_error")
    except (OSError, UnicodeError):
        return (), _csv_issue(path, "csv_read_error")
    except (csv.Error, TypeError, ValueError):
        return (), _csv_issue(path, "csv_parse_error")
    return rows, None


def _parse_rg_row(row: list[str], *, row_number: int) -> _ParsedRgRow:
    if len(row) != len(_EXPECTED_HEADER):
        raise ValueError("invalid column count")
    condition_name = row[0]
    if not condition_name.strip():
        raise ValueError("missing condition name")
    frame_index = _parse_frame_index(row[1])
    time_ps = _parse_optional_number(row[2])
    rg_value = _parse_optional_number(row[3])
    if row[4] and not row[4].strip():
        raise ValueError("invalid Rg unit")
    rg_unit = row[4] or None
    if row[5] not in ("true", "false"):
        raise ValueError("invalid frame passed")
    return _ParsedRgRow(
        condition_name=condition_name,
        frame_index=frame_index,
        time_ps=time_ps,
        rg_value=rg_value,
        rg_unit=rg_unit,
        frame_passed=row[5] == "true",
        row_number=row_number,
    )


def _parse_frame_index(value: str) -> int:
    if not value or any(character < "0" or character > "9" for character in value):
        raise ValueError("invalid frame index")
    return int(value)


def _parse_optional_number(value: str) -> float | None:
    if value == "":
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError("invalid numeric value")
    return number


def _index_rows(
    rows: tuple[_ParsedRgRow, ...],
    *,
    side: Literal["actual", "reference"],
    include_condition: bool,
) -> tuple[
    dict[tuple[str, int] | int, _ParsedRgRow],
    tuple[PreprocessingRgReferenceComparisonIssue, ...],
]:
    indexed: dict[tuple[str, int] | int, _ParsedRgRow] = {}
    issues: list[PreprocessingRgReferenceComparisonIssue] = []
    for row in rows:
        key = _row_key(row, include_condition=include_condition)
        if key in indexed:
            kind = f"duplicate_{side}_row_key"
            issues.append(
                _comparison_issue(
                    kind,
                    f"{side}_csv_path",
                    f"Duplicate {side} row key at CSV row {row.row_number}.",
                )
            )
            if not include_condition:
                issues.append(
                    _comparison_issue(
                        "ambiguous_frame_key",
                        f"{side}_csv_path",
                        (
                            f"Frame index {row.frame_index} is not unique "
                            f"in the {side} CSV."
                        ),
                    )
                )
            continue
        indexed[key] = row
    return indexed, tuple(issues)


def _row_key(
    row: _ParsedRgRow,
    *,
    include_condition: bool,
) -> tuple[str, int] | int:
    if include_condition:
        return (row.condition_name, row.frame_index)
    return row.frame_index


def _compare_row_pair(
    actual: _ParsedRgRow | None,
    reference: _ParsedRgRow | None,
    options: PreprocessingRgReferenceComparisonOptions,
) -> PreprocessingRgReferenceComparisonRowResult:
    if actual is None:
        return _unpaired_row_result(
            actual=None,
            reference=reference,
            allowed=options.allow_extra_reference_rows,
        )
    if reference is None:
        return _unpaired_row_result(
            actual=actual,
            reference=None,
            allowed=options.allow_extra_actual_rows,
        )

    issues: list[PreprocessingRgReferenceComparisonIssue] = []
    if not actual.frame_passed:
        issues.append(
            _comparison_issue(
                "actual_frame_not_passed",
                "actual.frame_passed",
                "Actual frame did not pass Rg computation.",
            )
        )
    if not reference.frame_passed:
        issues.append(
            _comparison_issue(
                "reference_frame_not_passed",
                "reference.frame_passed",
                "Reference frame did not pass Rg computation.",
            )
        )

    time_abs_difference: float | None = None
    rg_abs_difference: float | None = None
    rg_rel_difference: float | None = None
    if actual.frame_passed and reference.frame_passed:
        time_abs_difference = _compare_time(actual, reference, options, issues)
        rg_abs_difference, rg_rel_difference = _compare_rg(
            actual,
            reference,
            options,
            issues,
        )

    return PreprocessingRgReferenceComparisonRowResult(
        condition_name=reference.condition_name,
        frame_index=reference.frame_index,
        actual_row_number=actual.row_number,
        reference_row_number=reference.row_number,
        actual_time_ps=actual.time_ps,
        reference_time_ps=reference.time_ps,
        time_abs_difference=time_abs_difference,
        actual_rg_value=actual.rg_value,
        reference_rg_value=reference.rg_value,
        rg_abs_difference=rg_abs_difference,
        rg_rel_difference=rg_rel_difference,
        actual_rg_unit=actual.rg_unit,
        reference_rg_unit=reference.rg_unit,
        passed=not issues,
        issues=tuple(issues),
    )


def _compare_time(
    actual: _ParsedRgRow,
    reference: _ParsedRgRow,
    options: PreprocessingRgReferenceComparisonOptions,
    issues: list[PreprocessingRgReferenceComparisonIssue],
) -> float | None:
    if (actual.time_ps is None) != (reference.time_ps is None):
        issues.append(
            _comparison_issue(
                _ISSUE_TIME_PRESENCE_DIFFERENCE,
                "time_ps",
                "Actual and reference time presence differs.",
            )
        )
        return None
    if actual.time_ps is None or reference.time_ps is None:
        return None
    difference = abs(actual.time_ps - reference.time_ps)
    if difference > options.time_abs_tolerance:
        issues.append(
            _comparison_issue(
                _ISSUE_TIME_VALUE_DIFFERENCE,
                "time_ps",
                "Actual and reference times exceed the absolute tolerance.",
            )
        )
    return difference


def _compare_rg(
    actual: _ParsedRgRow,
    reference: _ParsedRgRow,
    options: PreprocessingRgReferenceComparisonOptions,
    issues: list[PreprocessingRgReferenceComparisonIssue],
) -> tuple[float | None, float | None]:
    if actual.rg_value is None:
        issues.append(
            _comparison_issue(
                "actual_missing_rg_value",
                "actual.rg_value",
                "Actual passed frame is missing an Rg value.",
            )
        )
    if reference.rg_value is None:
        issues.append(
            _comparison_issue(
                "reference_missing_rg_value",
                "reference.rg_value",
                "Reference passed frame is missing an Rg value.",
            )
        )
    _compare_units(actual, reference, options, issues)
    if actual.rg_value is None or reference.rg_value is None:
        return None, None

    absolute = abs(actual.rg_value - reference.rg_value)
    if reference.rg_value == 0.0:
        relative = 0.0 if actual.rg_value == 0.0 else float("inf")
    else:
        relative = absolute / abs(reference.rg_value)
    if (
        absolute > options.rg_abs_tolerance
        and relative > options.rg_rel_tolerance
    ):
        issues.append(
            _comparison_issue(
                _ISSUE_RG_VALUE_DIFFERENCE,
                "rg_value",
                "Actual and reference Rg values exceed both tolerances.",
            )
        )
    return absolute, relative


def _compare_units(
    actual: _ParsedRgRow,
    reference: _ParsedRgRow,
    options: PreprocessingRgReferenceComparisonOptions,
    issues: list[PreprocessingRgReferenceComparisonIssue],
) -> None:
    if not options.require_matching_units:
        return
    if actual.rg_unit is None:
        issues.append(
            _comparison_issue(
                "actual_missing_rg_unit",
                "actual.rg_unit",
                "Actual passed frame is missing an Rg unit.",
            )
        )
    if reference.rg_unit is None:
        issues.append(
            _comparison_issue(
                "reference_missing_rg_unit",
                "reference.rg_unit",
                "Reference passed frame is missing an Rg unit.",
            )
        )
    if (
        actual.rg_unit is not None
        and reference.rg_unit is not None
        and actual.rg_unit != reference.rg_unit
    ):
        issues.append(
            _comparison_issue(
                _ISSUE_RG_UNIT_DIFFERENCE,
                "rg_unit",
                "Actual and reference Rg units differ.",
            )
        )


def _unpaired_row_result(
    *,
    actual: _ParsedRgRow | None,
    reference: _ParsedRgRow | None,
    allowed: bool,
) -> PreprocessingRgReferenceComparisonRowResult:
    if actual is None:
        issues = (
            _comparison_issue(
                "missing_actual_row",
                "actual_csv_path",
                "Reference row has no actual row with the same key.",
            ),
            _comparison_issue(
                "extra_reference_row",
                "reference_csv_path",
                "Reference row has no actual row with the same key.",
            ),
        )
        row = reference
    else:
        issues = (
            _comparison_issue(
                "missing_reference_row",
                "reference_csv_path",
                "Actual row has no reference row with the same key.",
            ),
            _comparison_issue(
                "extra_actual_row",
                "actual_csv_path",
                "Actual row has no reference row with the same key.",
            ),
        )
        row = actual
    if row is None:
        raise AssertionError("one comparison row must be present")
    return PreprocessingRgReferenceComparisonRowResult(
        condition_name=row.condition_name,
        frame_index=row.frame_index,
        actual_row_number=actual.row_number if actual is not None else None,
        reference_row_number=(
            reference.row_number if reference is not None else None
        ),
        actual_time_ps=actual.time_ps if actual is not None else None,
        reference_time_ps=(
            reference.time_ps if reference is not None else None
        ),
        time_abs_difference=None,
        actual_rg_value=actual.rg_value if actual is not None else None,
        reference_rg_value=(
            reference.rg_value if reference is not None else None
        ),
        rg_abs_difference=None,
        rg_rel_difference=None,
        actual_rg_unit=actual.rg_unit if actual is not None else None,
        reference_rg_unit=(
            reference.rg_unit if reference is not None else None
        ),
        passed=allowed,
        issues=issues,
    )


def _empty_comparison_result(
    comparison_input: PreprocessingRgReferenceComparisonInput,
    *,
    input_validation_passed: bool,
    actual_row_count: int = 0,
    reference_row_count: int = 0,
    issues: tuple[PreprocessingRgReferenceComparisonIssue, ...],
) -> PreprocessingRgReferenceComparisonResult:
    return PreprocessingRgReferenceComparisonResult(
        comparison_input=comparison_input,
        passed=False,
        input_validation_passed=input_validation_passed,
        actual_row_count=actual_row_count,
        reference_row_count=reference_row_count,
        matched_row_count=0,
        passed_row_count=0,
        failed_row_count=0,
        missing_actual_row_count=0,
        missing_reference_row_count=0,
        extra_actual_row_count=0,
        extra_reference_row_count=0,
        max_rg_abs_difference=None,
        max_rg_rel_difference=None,
        max_time_abs_difference=None,
        row_results=(),
        issues=issues,
    )


def _maximum_difference(values: Iterable[float | None]) -> float | None:
    available = [value for value in values if value is not None]
    return max(available, default=None)


def _comparison_issue(
    kind: str,
    field: str,
    message: str,
) -> PreprocessingRgReferenceComparisonIssue:
    return PreprocessingRgReferenceComparisonIssue(
        kind=kind,
        field=field,
        message=message,
    )


def _csv_issue(
    path: Path,
    kind: Literal["csv_read_error", "csv_parse_error"],
) -> PreprocessingRgReferenceComparisonIssue:
    return _comparison_issue(
        kind,
        str(path),
        "Rg CSV file could not be parsed for comparison.",
    )


def _validate_options(
    options: PreprocessingRgReferenceComparisonOptions,
) -> None:
    if not isinstance(options, PreprocessingRgReferenceComparisonOptions):
        raise ValueError(
            "options must be PreprocessingRgReferenceComparisonOptions"
        )
    _validate_option_values(options)


def _validate_path(
    path: Path,
    *,
    missing_kind: Literal[
        "missing_actual_csv",
        "missing_reference_csv",
    ],
    not_file_kind: Literal[
        "actual_csv_not_file",
        "reference_csv_not_file",
    ],
    field: str,
    issues: list[PreprocessingRgReferenceComparisonIssue],
) -> bool:
    if not path.exists():
        issues.append(
            PreprocessingRgReferenceComparisonIssue(
                kind=missing_kind,
                field=field,
                message=f"{field} does not exist.",
            )
        )
        return False
    if not path.is_file():
        issues.append(
            PreprocessingRgReferenceComparisonIssue(
                kind=not_file_kind,
                field=field,
                message=f"{field} is not a file.",
            )
        )
        return False
    return True
