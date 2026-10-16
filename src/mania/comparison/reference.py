"""Lightweight reference artifact comparison helpers."""

from __future__ import annotations

import csv
import json
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

COMPARISON_STATUS_PASS = "pass"
COMPARISON_STATUS_FAIL = "fail"

COMPARISON_MODE_FILE_EXISTS = "file_exists"
COMPARISON_MODE_CSV_EXACT = "csv_exact"
COMPARISON_MODE_CSV_NUMERIC_TOLERANCE = "csv_numeric_tolerance"
COMPARISON_MODE_JSON_EXACT = "json_exact"

_MAX_CSV_ROW_DIFFERENCES = 10
_MAX_NUMERIC_CSV_DIFFERENCES = 20


class ReferenceComparisonError(Exception):
    """Raised when the comparison harness is used with invalid inputs."""


@dataclass(frozen=True)
class ReferenceDifference:
    """A machine-readable difference found during reference comparison."""

    artifact: str
    check: str
    expected: str
    actual: str
    message: str


@dataclass(frozen=True)
class ReferenceComparisonResult:
    """Result for one compared artifact."""

    artifact: str
    status: str
    differences: tuple[ReferenceDifference, ...]

    @property
    def passed(self) -> bool:
        """Return whether this artifact comparison passed."""
        return self.status == COMPARISON_STATUS_PASS and not self.differences


@dataclass(frozen=True)
class ReferenceComparisonReport:
    """Collection of reference comparison results."""

    results: tuple[ReferenceComparisonResult, ...]

    @property
    def passed(self) -> bool:
        """Return whether every artifact comparison passed."""
        return all(result.passed for result in self.results)

    def failed_results(self) -> tuple[ReferenceComparisonResult, ...]:
        """Return only failing artifact comparison results."""
        return tuple(result for result in self.results if not result.passed)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation of this report."""
        return {
            "passed": self.passed,
            "results": [
                {
                    "artifact": result.artifact,
                    "status": result.status,
                    "passed": result.passed,
                    "differences": [
                        {
                            "artifact": difference.artifact,
                            "check": difference.check,
                            "expected": difference.expected,
                            "actual": difference.actual,
                            "message": difference.message,
                        }
                        for difference in result.differences
                    ],
                }
                for result in self.results
            ],
        }


@dataclass(frozen=True)
class CSVNumericToleranceComparisonConfig:
    """Configuration for numeric-tolerance CSV artifact comparison."""

    key_columns: tuple[str, ...]
    numeric_columns: tuple[str, ...]
    abs_tol: float
    text_columns: tuple[str, ...] = ()


@dataclass(frozen=True)
class ArtifactComparisonSpec:
    """Specification for comparing one artifact relative to two roots."""

    relative_path: str
    mode: str
    artifact: str | None = None
    numeric_tolerance: CSVNumericToleranceComparisonConfig | None = None


def compare_file_exists(
    path: str | Path,
    artifact: str | None = None,
) -> ReferenceComparisonResult:
    """Compare whether a file exists."""
    file_path = Path(path)
    artifact_name = _artifact_name(artifact, file_path)
    if file_path.is_file():
        return _pass_result(artifact_name)
    return _fail_result(
        artifact_name,
        ReferenceDifference(
            artifact=artifact_name,
            check="file_exists",
            expected="exists",
            actual="missing",
            message=f"Expected file to exist: {file_path}",
        ),
    )


def compare_csv_exact(
    expected_path: str | Path,
    actual_path: str | Path,
    artifact: str | None = None,
) -> ReferenceComparisonResult:
    """Compare two CSV files exactly as rows of strings."""
    expected_csv_path = Path(expected_path)
    actual_csv_path = Path(actual_path)
    artifact_name = _artifact_name(artifact, actual_csv_path, expected_csv_path)
    missing_file_differences = _missing_file_differences(
        artifact_name,
        (("expected", expected_csv_path), ("actual", actual_csv_path)),
    )
    if missing_file_differences:
        return _result_from_differences(artifact_name, missing_file_differences)

    expected_rows = _read_csv_rows(expected_csv_path)
    actual_rows = _read_csv_rows(actual_csv_path)

    differences: list[ReferenceDifference] = []
    expected_header = expected_rows[0] if expected_rows else []
    actual_header = actual_rows[0] if actual_rows else []
    if expected_header != actual_header:
        differences.append(
            ReferenceDifference(
                artifact=artifact_name,
                check="csv_header",
                expected=_json_string(expected_header),
                actual=_json_string(actual_header),
                message="CSV header differs",
            )
        )

    expected_data_rows = expected_rows[1:] if expected_rows else []
    actual_data_rows = actual_rows[1:] if actual_rows else []
    if len(expected_data_rows) != len(actual_data_rows):
        differences.append(
            ReferenceDifference(
                artifact=artifact_name,
                check="csv_row_count",
                expected=str(len(expected_data_rows)),
                actual=str(len(actual_data_rows)),
                message="CSV data row count differs",
            )
        )

    differing_rows = 0
    for row_index, (expected_row, actual_row) in enumerate(
        zip(expected_data_rows, actual_data_rows, strict=False),
        start=2,
    ):
        if expected_row == actual_row:
            continue
        differences.append(
            ReferenceDifference(
                artifact=artifact_name,
                check="csv_row",
                expected=_json_string(expected_row),
                actual=_json_string(actual_row),
                message=f"CSV row {row_index} differs",
            )
        )
        differing_rows += 1
        if differing_rows >= _MAX_CSV_ROW_DIFFERENCES:
            break

    return _result_from_differences(artifact_name, tuple(differences))


def compare_csv_numeric_tolerance(
    expected_path: str | Path,
    actual_path: str | Path,
    *,
    key_columns: Sequence[str],
    numeric_columns: Sequence[str],
    abs_tol: float,
    text_columns: Sequence[str] = (),
    artifact: str | None = None,
) -> ReferenceComparisonResult:
    """Compare CSV rows by key with absolute tolerance for numeric columns."""
    _validate_csv_numeric_tolerance_inputs(
        key_columns,
        numeric_columns,
        text_columns,
        abs_tol,
    )

    expected_csv_path = Path(expected_path)
    actual_csv_path = Path(actual_path)
    artifact_name = _artifact_name(artifact, actual_csv_path, expected_csv_path)
    missing_file_differences = _expected_actual_file_differences(
        artifact_name,
        expected_csv_path,
        actual_csv_path,
    )
    if missing_file_differences:
        return _result_from_differences(artifact_name, missing_file_differences)

    expected_csv = _read_csv_dict_rows(expected_csv_path, artifact_name)
    actual_csv = _read_csv_dict_rows(actual_csv_path, artifact_name)
    read_differences = (*expected_csv.differences, *actual_csv.differences)
    if read_differences:
        return _result_from_differences(artifact_name, read_differences)

    required_columns = (*key_columns, *numeric_columns, *text_columns)
    required_column_differences = _required_column_differences(
        artifact_name,
        required_columns,
        expected_csv.fieldnames,
        actual_csv.fieldnames,
    )
    if required_column_differences:
        return _result_from_differences(artifact_name, required_column_differences)

    differences: list[ReferenceDifference] = []
    expected_index = _index_rows_by_key(
        expected_csv.rows,
        key_columns,
        "expected",
        artifact_name,
        differences,
    )
    actual_index = _index_rows_by_key(
        actual_csv.rows,
        key_columns,
        "actual",
        artifact_name,
        differences,
    )
    if _comparison_truncated(differences):
        return _result_from_differences(artifact_name, tuple(differences))

    for expected_key in expected_index.ordered_keys:
        if expected_key not in actual_index.rows_by_key:
            _append_limited_difference(
                differences,
                ReferenceDifference(
                    artifact=artifact_name,
                    check="csv_missing_key",
                    expected=_format_key(expected_key),
                    actual="missing",
                    message=f"Missing actual row for key {_format_key(expected_key)}",
                ),
            )
            if _comparison_truncated(differences):
                return _result_from_differences(artifact_name, tuple(differences))

    for actual_key in actual_index.ordered_keys:
        if actual_key not in expected_index.rows_by_key:
            _append_limited_difference(
                differences,
                ReferenceDifference(
                    artifact=artifact_name,
                    check="csv_extra_key",
                    expected="absent",
                    actual=_format_key(actual_key),
                    message=f"Unexpected actual row for key {_format_key(actual_key)}",
                ),
            )
            if _comparison_truncated(differences):
                return _result_from_differences(artifact_name, tuple(differences))

    for expected_key in expected_index.ordered_keys:
        expected_row = expected_index.rows_by_key[expected_key]
        actual_row = actual_index.rows_by_key.get(expected_key)
        if actual_row is None:
            continue

        _compare_numeric_columns(
            artifact_name,
            expected_key,
            expected_row,
            actual_row,
            numeric_columns,
            abs_tol,
            differences,
        )
        if _comparison_truncated(differences):
            return _result_from_differences(artifact_name, tuple(differences))

        _compare_text_columns(
            artifact_name,
            expected_key,
            expected_row,
            actual_row,
            text_columns,
            differences,
        )
        if _comparison_truncated(differences):
            return _result_from_differences(artifact_name, tuple(differences))

    return _result_from_differences(artifact_name, tuple(differences))


def compare_json_exact(
    expected_path: str | Path,
    actual_path: str | Path,
    artifact: str | None = None,
) -> ReferenceComparisonResult:
    """Compare two JSON files exactly after loading them as Python objects."""
    expected_json_path = Path(expected_path)
    actual_json_path = Path(actual_path)
    artifact_name = _artifact_name(artifact, actual_json_path, expected_json_path)
    missing_file_differences = _missing_file_differences(
        artifact_name,
        (("expected", expected_json_path), ("actual", actual_json_path)),
    )
    if missing_file_differences:
        return _result_from_differences(artifact_name, missing_file_differences)

    expected_object = _read_json(expected_json_path)
    actual_object = _read_json(actual_json_path)
    if expected_object == actual_object:
        return _pass_result(artifact_name)
    return _fail_result(
        artifact_name,
        ReferenceDifference(
            artifact=artifact_name,
            check="json_exact",
            expected=_json_string(expected_object),
            actual=_json_string(actual_object),
            message="JSON objects differ",
        ),
    )


def compare_artifact_sets(
    expected_root: str | Path,
    actual_root: str | Path,
    specs: Iterable[ArtifactComparisonSpec],
) -> ReferenceComparisonReport:
    """Compare artifacts under two roots according to ordered specs."""
    expected_root_path = Path(expected_root)
    actual_root_path = Path(actual_root)
    results: list[ReferenceComparisonResult] = []

    for spec in specs:
        relative_path = _validate_artifact_relative_path(spec.relative_path)
        artifact_name = (
            spec.artifact if spec.artifact is not None else spec.relative_path
        )
        expected_path = expected_root_path / relative_path
        actual_path = actual_root_path / relative_path
        numeric_tolerance = spec.numeric_tolerance

        if spec.mode == COMPARISON_MODE_CSV_NUMERIC_TOLERANCE:
            if numeric_tolerance is None:
                raise ReferenceComparisonError(
                    "Numeric-tolerance CSV comparison requires numeric_tolerance"
                )
        elif numeric_tolerance is not None:
            raise ReferenceComparisonError(
                "numeric_tolerance is only valid for csv_numeric_tolerance mode"
            )

        if spec.mode == COMPARISON_MODE_FILE_EXISTS:
            results.append(compare_file_exists(actual_path, artifact=artifact_name))
            continue

        if spec.mode == COMPARISON_MODE_CSV_EXACT:
            missing_differences = _expected_actual_file_differences(
                artifact_name,
                expected_path,
                actual_path,
            )
            if missing_differences:
                results.append(
                    _result_from_differences(artifact_name, missing_differences)
                )
                continue
            results.append(
                compare_csv_exact(expected_path, actual_path, artifact=artifact_name)
            )
            continue

        if spec.mode == COMPARISON_MODE_JSON_EXACT:
            missing_differences = _expected_actual_file_differences(
                artifact_name,
                expected_path,
                actual_path,
            )
            if missing_differences:
                results.append(
                    _result_from_differences(artifact_name, missing_differences)
                )
                continue
            results.append(
                compare_json_exact(expected_path, actual_path, artifact=artifact_name)
            )
            continue

        if spec.mode == COMPARISON_MODE_CSV_NUMERIC_TOLERANCE:
            missing_differences = _expected_actual_file_differences(
                artifact_name,
                expected_path,
                actual_path,
            )
            if missing_differences:
                results.append(
                    _result_from_differences(artifact_name, missing_differences)
                )
                continue
            if numeric_tolerance is None:
                raise ReferenceComparisonError(
                    "Numeric-tolerance CSV comparison requires numeric_tolerance"
                )
            results.append(
                compare_csv_numeric_tolerance(
                    expected_path,
                    actual_path,
                    key_columns=numeric_tolerance.key_columns,
                    numeric_columns=numeric_tolerance.numeric_columns,
                    abs_tol=numeric_tolerance.abs_tol,
                    text_columns=numeric_tolerance.text_columns,
                    artifact=artifact_name,
                )
            )
            continue

        raise ReferenceComparisonError(f"Unknown comparison mode: {spec.mode!r}")

    return build_comparison_report(results)


def build_comparison_report(
    results: Iterable[ReferenceComparisonResult],
) -> ReferenceComparisonReport:
    """Build a reference comparison report from comparison results."""
    return ReferenceComparisonReport(results=tuple(results))


def write_comparison_report(
    report: ReferenceComparisonReport,
    path: str | Path,
) -> Path:
    """Write a reference comparison report as stable pretty JSON."""
    report_path = Path(path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report_path


@dataclass(frozen=True)
class _CsvDictRows:
    fieldnames: tuple[str, ...]
    rows: tuple[dict[str, str], ...]
    differences: tuple[ReferenceDifference, ...]


@dataclass(frozen=True)
class _CsvKeyIndex:
    rows_by_key: dict[tuple[str, ...], dict[str, str]]
    ordered_keys: tuple[tuple[str, ...], ...]


def _validate_csv_numeric_tolerance_inputs(
    key_columns: Sequence[str],
    numeric_columns: Sequence[str],
    text_columns: Sequence[str],
    abs_tol: float,
) -> None:
    if isinstance(key_columns, str):
        raise ReferenceComparisonError("key_columns must be a sequence of names")
    if isinstance(numeric_columns, str):
        raise ReferenceComparisonError("numeric_columns must be a sequence of names")
    if isinstance(text_columns, str):
        raise ReferenceComparisonError("text_columns must be a sequence of names")
    if not key_columns:
        raise ReferenceComparisonError("key_columns must not be empty")
    if not numeric_columns:
        raise ReferenceComparisonError("numeric_columns must not be empty")
    if abs_tol < 0 or not math.isfinite(abs_tol):
        raise ReferenceComparisonError("abs_tol must be a finite non-negative number")

    seen_columns: set[str] = set()
    for group_name, columns in (
        ("key_columns", key_columns),
        ("numeric_columns", numeric_columns),
        ("text_columns", text_columns),
    ):
        group_seen: set[str] = set()
        for column in columns:
            if column in group_seen:
                raise ReferenceComparisonError(
                    f"Duplicate column in {group_name}: {column!r}"
                )
            if column in seen_columns:
                raise ReferenceComparisonError(
                    f"Duplicate column across comparison inputs: {column!r}"
                )
            group_seen.add(column)
            seen_columns.add(column)


def _read_csv_dict_rows(path: Path, artifact: str) -> _CsvDictRows:
    try:
        with path.open(encoding="utf-8", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            fieldnames = reader.fieldnames
            if not fieldnames or any(fieldname == "" for fieldname in fieldnames):
                return _csv_dict_rows_error(
                    artifact,
                    path,
                    "CSV file must include a non-empty header",
                )
            if len(set(fieldnames)) != len(fieldnames):
                return _csv_dict_rows_error(
                    artifact,
                    path,
                    "CSV header contains duplicate column names",
                )

            rows: list[dict[str, str]] = []
            for line_number, row in enumerate(reader, start=2):
                if None in row:
                    return _csv_dict_rows_error(
                        artifact,
                        path,
                        f"CSV row {line_number} contains extra fields",
                    )
                if any(value is None for value in row.values()):
                    return _csv_dict_rows_error(
                        artifact,
                        path,
                        f"CSV row {line_number} contains missing fields",
                    )
                rows.append(dict(row))
            return _CsvDictRows(
                fieldnames=tuple(fieldnames),
                rows=tuple(rows),
                differences=(),
            )
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        return _csv_dict_rows_error(
            artifact,
            path,
            f"CSV file could not be read: {exc}",
        )


def _csv_dict_rows_error(
    artifact: str,
    path: Path,
    message: str,
) -> _CsvDictRows:
    return _CsvDictRows(
        fieldnames=(),
        rows=(),
        differences=(
            ReferenceDifference(
                artifact=artifact,
                check="csv_malformed",
                expected="readable CSV with header",
                actual=str(path),
                message=message,
            ),
        ),
    )


def _required_column_differences(
    artifact: str,
    required_columns: Sequence[str],
    expected_fieldnames: Sequence[str],
    actual_fieldnames: Sequence[str],
) -> tuple[ReferenceDifference, ...]:
    differences: list[ReferenceDifference] = []
    expected_fieldname_set = set(expected_fieldnames)
    actual_fieldname_set = set(actual_fieldnames)
    missing_expected = tuple(
        column for column in required_columns if column not in expected_fieldname_set
    )
    missing_actual = tuple(
        column for column in required_columns if column not in actual_fieldname_set
    )
    if missing_expected:
        differences.append(
            ReferenceDifference(
                artifact=artifact,
                check="csv_required_columns",
                expected=_json_string(required_columns),
                actual=_json_string(expected_fieldnames),
                message=(
                    "Expected CSV is missing required columns: "
                    f"{_json_string(missing_expected)}"
                ),
            )
        )
    if missing_actual:
        differences.append(
            ReferenceDifference(
                artifact=artifact,
                check="csv_required_columns",
                expected=_json_string(required_columns),
                actual=_json_string(actual_fieldnames),
                message=(
                    "Actual CSV is missing required columns: "
                    f"{_json_string(missing_actual)}"
                ),
            )
        )
    return tuple(differences)


def _index_rows_by_key(
    rows: Sequence[dict[str, str]],
    key_columns: Sequence[str],
    source_label: str,
    artifact: str,
    differences: list[ReferenceDifference],
) -> _CsvKeyIndex:
    rows_by_key: dict[tuple[str, ...], dict[str, str]] = {}
    ordered_keys: list[tuple[str, ...]] = []

    for row in rows:
        key = tuple(row[column] for column in key_columns)
        if key in rows_by_key:
            _append_limited_difference(
                differences,
                ReferenceDifference(
                    artifact=artifact,
                    check="csv_duplicate_key",
                    expected=f"unique {source_label} key",
                    actual=_format_key(key),
                    message=f"Duplicate {source_label} row key {_format_key(key)}",
                ),
            )
            if _comparison_truncated(differences):
                break
            continue
        rows_by_key[key] = row
        ordered_keys.append(key)

    return _CsvKeyIndex(rows_by_key=rows_by_key, ordered_keys=tuple(ordered_keys))


def _compare_numeric_columns(
    artifact: str,
    key: tuple[str, ...],
    expected_row: dict[str, str],
    actual_row: dict[str, str],
    numeric_columns: Sequence[str],
    abs_tol: float,
    differences: list[ReferenceDifference],
) -> None:
    for column in numeric_columns:
        expected_value = expected_row[column]
        actual_value = actual_row[column]
        try:
            expected_float = float(expected_value)
            actual_float = float(actual_value)
        except ValueError:
            _append_limited_difference(
                differences,
                ReferenceDifference(
                    artifact=artifact,
                    check="csv_numeric_parse",
                    expected=expected_value,
                    actual=actual_value,
                    message=(
                        f"Numeric parse failed for key {_format_key(key)}, "
                        f"column {column!r}, expected {expected_value!r}, "
                        f"actual {actual_value!r}, tolerance {abs_tol}"
                    ),
                ),
            )
            if _comparison_truncated(differences):
                return
            continue

        if not math.isfinite(expected_float) or not math.isfinite(actual_float):
            _append_limited_difference(
                differences,
                ReferenceDifference(
                    artifact=artifact,
                    check="csv_numeric_non_finite",
                    expected=expected_value,
                    actual=actual_value,
                    message=(
                        f"Non-finite numeric value for key {_format_key(key)}, "
                        f"column {column!r}, expected {expected_value!r}, "
                        f"actual {actual_value!r}, tolerance {abs_tol}"
                    ),
                ),
            )
            if _comparison_truncated(differences):
                return
            continue

        absolute_difference = abs(expected_float - actual_float)
        if absolute_difference > abs_tol:
            _append_limited_difference(
                differences,
                ReferenceDifference(
                    artifact=artifact,
                    check="csv_numeric_tolerance",
                    expected=expected_value,
                    actual=actual_value,
                    message=(
                        f"Numeric value differs for key {_format_key(key)}, "
                        f"column {column!r}, expected {expected_value!r}, "
                        f"actual {actual_value!r}, absolute difference "
                        f"{absolute_difference}, tolerance {abs_tol}"
                    ),
                ),
            )
            if _comparison_truncated(differences):
                return


def _compare_text_columns(
    artifact: str,
    key: tuple[str, ...],
    expected_row: dict[str, str],
    actual_row: dict[str, str],
    text_columns: Sequence[str],
    differences: list[ReferenceDifference],
) -> None:
    for column in text_columns:
        expected_value = expected_row[column]
        actual_value = actual_row[column]
        if expected_value == actual_value:
            continue
        _append_limited_difference(
            differences,
            ReferenceDifference(
                artifact=artifact,
                check="csv_text_exact",
                expected=expected_value,
                actual=actual_value,
                message=(
                    f"Text value differs for key {_format_key(key)}, "
                    f"column {column!r}, expected {expected_value!r}, "
                    f"actual {actual_value!r}"
                ),
            ),
        )
        if _comparison_truncated(differences):
            return


def _append_limited_difference(
    differences: list[ReferenceDifference],
    difference: ReferenceDifference,
) -> None:
    if _comparison_truncated(differences):
        return
    if len(differences) < _MAX_NUMERIC_CSV_DIFFERENCES:
        differences.append(difference)
        return
    differences.append(
        ReferenceDifference(
            artifact=difference.artifact,
            check="comparison_truncated",
            expected=f"at most {_MAX_NUMERIC_CSV_DIFFERENCES} detailed differences",
            actual=f"more than {_MAX_NUMERIC_CSV_DIFFERENCES} differences",
            message=(
                "Comparison differences truncated after "
                f"{_MAX_NUMERIC_CSV_DIFFERENCES} detailed differences"
            ),
        )
    )


def _comparison_truncated(differences: Sequence[ReferenceDifference]) -> bool:
    return any(difference.check == "comparison_truncated" for difference in differences)


def _format_key(key: tuple[str, ...]) -> str:
    return _json_string(key)


def _artifact_name(
    artifact: str | None,
    primary_path: Path,
    fallback_path: Path | None = None,
) -> str:
    if artifact is not None:
        return artifact
    if primary_path.name:
        return primary_path.name
    if fallback_path is not None and fallback_path.name:
        return fallback_path.name
    raise ReferenceComparisonError("Artifact name could not be inferred")


def _pass_result(artifact: str) -> ReferenceComparisonResult:
    return ReferenceComparisonResult(
        artifact=artifact,
        status=COMPARISON_STATUS_PASS,
        differences=(),
    )


def _fail_result(
    artifact: str,
    difference: ReferenceDifference,
) -> ReferenceComparisonResult:
    return ReferenceComparisonResult(
        artifact=artifact,
        status=COMPARISON_STATUS_FAIL,
        differences=(difference,),
    )


def _result_from_differences(
    artifact: str,
    differences: tuple[ReferenceDifference, ...],
) -> ReferenceComparisonResult:
    status = COMPARISON_STATUS_FAIL if differences else COMPARISON_STATUS_PASS
    return ReferenceComparisonResult(
        artifact=artifact,
        status=status,
        differences=differences,
    )


def _missing_file_differences(
    artifact: str,
    paths: tuple[tuple[str, Path], ...],
) -> tuple[ReferenceDifference, ...]:
    differences: list[ReferenceDifference] = []
    for label, path in paths:
        if path.is_file():
            continue
        differences.append(
            ReferenceDifference(
                artifact=artifact,
                check="file_exists",
                expected=f"{label} exists",
                actual="missing",
                message=f"Expected {label} file to exist: {path}",
            )
        )
    return tuple(differences)


def _expected_actual_file_differences(
    artifact: str,
    expected_path: Path,
    actual_path: Path,
) -> tuple[ReferenceDifference, ...]:
    differences: list[ReferenceDifference] = []
    if not expected_path.is_file():
        differences.append(
            ReferenceDifference(
                artifact=artifact,
                check="expected_file_exists",
                expected="exists",
                actual="missing",
                message=f"Expected reference file to exist: {expected_path}",
            )
        )
    if not actual_path.is_file():
        differences.append(
            ReferenceDifference(
                artifact=artifact,
                check="actual_file_exists",
                expected="exists",
                actual="missing",
                message=f"Expected actual file to exist: {actual_path}",
            )
        )
    return tuple(differences)


def _validate_artifact_relative_path(relative_path: str) -> Path:
    if relative_path == "":
        raise ReferenceComparisonError("Artifact relative path must not be empty")
    path = Path(relative_path)
    if path.is_absolute():
        raise ReferenceComparisonError(
            f"Artifact relative path must not be absolute: {relative_path!r}"
        )
    if ".." in path.parts:
        raise ReferenceComparisonError(
            f"Artifact relative path must not contain '..': {relative_path!r}"
        )
    return path


def _read_csv_rows(path: Path) -> list[list[str]]:
    with path.open(encoding="utf-8", newline="") as csv_file:
        return list(csv.reader(csv_file))


def _read_json(path: Path) -> Any:
    try:
        with path.open(encoding="utf-8") as json_file:
            return json.load(json_file)
    except json.JSONDecodeError as exc:
        raise ReferenceComparisonError(f"Invalid JSON file: {path}") from exc


def _json_string(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


__all__ = [
    "ArtifactComparisonSpec",
    "COMPARISON_MODE_CSV_EXACT",
    "COMPARISON_MODE_CSV_NUMERIC_TOLERANCE",
    "COMPARISON_MODE_FILE_EXISTS",
    "COMPARISON_MODE_JSON_EXACT",
    "COMPARISON_STATUS_FAIL",
    "COMPARISON_STATUS_PASS",
    "CSVNumericToleranceComparisonConfig",
    "ReferenceComparisonError",
    "ReferenceComparisonReport",
    "ReferenceComparisonResult",
    "ReferenceDifference",
    "build_comparison_report",
    "compare_artifact_sets",
    "compare_csv_exact",
    "compare_csv_numeric_tolerance",
    "compare_file_exists",
    "compare_json_exact",
    "write_comparison_report",
]
