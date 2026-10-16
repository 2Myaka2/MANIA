"""Dependency-free validation for exported contacts CSV files."""

from __future__ import annotations

import csv
import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

_CONTACTS_PERFRAME_HEADER = (
    "condition_name",
    "frame_index",
    "time_ps",
    "source_residue_index",
    "target_residue_index",
    "source_residue_id",
    "target_residue_id",
    "source_resname",
    "target_resname",
    "source_segid",
    "target_segid",
    "minimum_distance",
    "distance_unit",
    "atom_filter",
    "frame_passed",
)
_TYPED_CONTACTS_PERFRAME_HEADER = (
    *_CONTACTS_PERFRAME_HEADER[:11],
    "edge_type",
    *_CONTACTS_PERFRAME_HEADER[11:],
)
_CONTACT_EDGES_HEADER = (
    "condition_name",
    "source_residue_index",
    "target_residue_index",
    "source_residue_id",
    "target_residue_id",
    "source_resname",
    "target_resname",
    "source_segid",
    "target_segid",
    "contact_frame_count",
    "total_frame_count",
    "contact_frequency",
    "minimum_distance",
    "mean_minimum_distance",
    "distance_unit",
    "atom_filter",
)
_TYPED_CONTACT_EDGES_HEADER = (
    *_CONTACT_EDGES_HEADER[:9],
    "edge_type",
    *_CONTACT_EDGES_HEADER[9:],
)
_ATOM_FILTERS = ("heavy", "all")
_TYPED_CONTACT_EDGE_TYPES = (
    "residue_contact",
    "backbone",
    "hbond",
    "disulfide",
    "salt_bridge",
    "ionic",
    "aromatic_pi",
    "cation_pi",
    "hydrophobic",
    "vdw",
)
_FREQUENCY_TOLERANCE = 1e-12


@dataclass(frozen=True)
class PreprocessingContactsPerFrameCsvValidationIssue:
    """One deterministic contacts per-frame CSV validation issue."""

    kind: str
    row_number: int | None
    field: str
    message: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _non_empty_string(self.kind, "kind"))
        if self.row_number is not None and (
            isinstance(self.row_number, bool)
            or not isinstance(self.row_number, int)
            or self.row_number <= 0
        ):
            raise ValueError("row_number must be a positive int or None")
        object.__setattr__(
            self,
            "field",
            _non_empty_string(self.field, "field"),
        )
        object.__setattr__(
            self,
            "message",
            _non_empty_string(self.message, "message"),
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable issue dictionary."""
        return {
            "kind": self.kind,
            "row_number": self.row_number,
            "field": self.field,
            "message": self.message,
        }


@dataclass(frozen=True)
class PreprocessingContactsPerFrameCsvValidationResult:
    """Summary of one contacts per-frame CSV validation attempt."""

    csv_path: Path
    passed: bool
    row_count: int
    valid_row_count: int
    invalid_row_count: int
    condition_count: int
    frame_count: int
    contact_count: int
    issues: tuple[PreprocessingContactsPerFrameCsvValidationIssue, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "csv_path", Path(self.csv_path))
        if not isinstance(self.passed, bool):
            raise ValueError("passed must be a bool")
        for field_name in (
            "row_count",
            "valid_row_count",
            "invalid_row_count",
            "condition_count",
            "frame_count",
            "contact_count",
        ):
            _require_non_negative_int(getattr(self, field_name), field_name)
        for issue in self.issues:
            if not isinstance(
                issue,
                PreprocessingContactsPerFrameCsvValidationIssue,
            ):
                raise ValueError(
                    "issues must contain "
                    "PreprocessingContactsPerFrameCsvValidationIssue"
                )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable validation summary."""
        return {
            "csv_path": str(self.csv_path),
            "passed": self.passed,
            "row_count": self.row_count,
            "valid_row_count": self.valid_row_count,
            "invalid_row_count": self.invalid_row_count,
            "condition_count": self.condition_count,
            "frame_count": self.frame_count,
            "contact_count": self.contact_count,
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class PreprocessingContactEdgesCsvValidationIssue:
    """One deterministic aggregate contacts CSV validation issue."""

    kind: str
    row_number: int | None
    field: str
    message: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _non_empty_string(self.kind, "kind"))
        if self.row_number is not None and (
            isinstance(self.row_number, bool)
            or not isinstance(self.row_number, int)
            or self.row_number <= 0
        ):
            raise ValueError("row_number must be a positive int or None")
        object.__setattr__(
            self,
            "field",
            _non_empty_string(self.field, "field"),
        )
        object.__setattr__(
            self,
            "message",
            _non_empty_string(self.message, "message"),
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable issue dictionary."""
        return {
            "kind": self.kind,
            "row_number": self.row_number,
            "field": self.field,
            "message": self.message,
        }


_IssueT = TypeVar(
    "_IssueT",
    PreprocessingContactsPerFrameCsvValidationIssue,
    PreprocessingContactEdgesCsvValidationIssue,
)


@dataclass(frozen=True)
class PreprocessingContactEdgesCsvValidationResult:
    """Summary of one aggregate contacts CSV validation attempt."""

    csv_path: Path
    passed: bool
    row_count: int
    valid_row_count: int
    invalid_row_count: int
    condition_count: int
    aggregate_edge_count: int
    issues: tuple[PreprocessingContactEdgesCsvValidationIssue, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "csv_path", Path(self.csv_path))
        if not isinstance(self.passed, bool):
            raise ValueError("passed must be a bool")
        for field_name in (
            "row_count",
            "valid_row_count",
            "invalid_row_count",
            "condition_count",
            "aggregate_edge_count",
        ):
            _require_non_negative_int(getattr(self, field_name), field_name)
        for issue in self.issues:
            if not isinstance(
                issue,
                PreprocessingContactEdgesCsvValidationIssue,
            ):
                raise ValueError(
                    "issues must contain "
                    "PreprocessingContactEdgesCsvValidationIssue"
                )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable validation summary."""
        return {
            "csv_path": str(self.csv_path),
            "passed": self.passed,
            "row_count": self.row_count,
            "valid_row_count": self.valid_row_count,
            "invalid_row_count": self.invalid_row_count,
            "condition_count": self.condition_count,
            "aggregate_edge_count": self.aggregate_edge_count,
            "issues": [issue.to_dict() for issue in self.issues],
        }


def validate_contacts_perframe_csv(
    csv_path: str | Path,
) -> PreprocessingContactsPerFrameCsvValidationResult:
    """Validate one existing contacts per-frame CSV file."""
    path = Path(csv_path)
    file_issue = _read_file_issue(path, file_label="contacts per-frame CSV")
    if file_issue is not None:
        return _perframe_file_issue_result(path, *file_issue)

    read_result = _read_csv(path)
    if not isinstance(read_result, _CsvRows):
        return _perframe_file_issue_result(path, *read_result)
    header = read_result.header
    rows = read_result.rows

    if header not in (
        _CONTACTS_PERFRAME_HEADER,
        _TYPED_CONTACTS_PERFRAME_HEADER,
    ):
        return _perframe_file_issue_result(
            path,
            "invalid_header",
            "header",
            "Contacts per-frame CSV header does not match the expected schema.",
        )

    issues: list[PreprocessingContactsPerFrameCsvValidationIssue] = []
    valid_row_count = 0
    invalid_row_count = 0
    conditions: set[str] = set()
    frames: set[tuple[str, int]] = set()
    duplicate_keys: set[tuple[str, ...]] = set()

    for row_number, row in enumerate(rows, start=2):
        row_issues, row_summary = _validate_perframe_row(
            row,
            row_number=row_number,
            duplicate_keys=duplicate_keys,
            header=header,
        )
        issues.extend(row_issues)
        if row_issues:
            invalid_row_count += 1
        else:
            valid_row_count += 1
            conditions.add(row_summary.condition_name)
            frames.add((row_summary.condition_name, row_summary.frame_index))

    return PreprocessingContactsPerFrameCsvValidationResult(
        csv_path=path,
        passed=not issues,
        row_count=len(rows),
        valid_row_count=valid_row_count,
        invalid_row_count=invalid_row_count,
        condition_count=len(conditions),
        frame_count=len(frames),
        contact_count=valid_row_count,
        issues=tuple(issues),
    )


def validate_contact_edges_csv(
    csv_path: str | Path,
) -> PreprocessingContactEdgesCsvValidationResult:
    """Validate one existing aggregate contacts CSV file."""
    path = Path(csv_path)
    file_issue = _read_file_issue(path, file_label="aggregate contacts CSV")
    if file_issue is not None:
        return _edges_file_issue_result(path, *file_issue)

    read_result = _read_csv(path)
    if not isinstance(read_result, _CsvRows):
        return _edges_file_issue_result(path, *read_result)
    header = read_result.header
    rows = read_result.rows

    if header not in (
        _CONTACT_EDGES_HEADER,
        _TYPED_CONTACT_EDGES_HEADER,
    ):
        return _edges_file_issue_result(
            path,
            "invalid_header",
            "header",
            "Aggregate contacts CSV header does not match the expected schema.",
        )

    issues: list[PreprocessingContactEdgesCsvValidationIssue] = []
    valid_row_count = 0
    invalid_row_count = 0
    conditions: set[str] = set()
    duplicate_keys: set[tuple[str, ...]] = set()

    for row_number, row in enumerate(rows, start=2):
        row_issues, condition_name = _validate_edges_row(
            row,
            row_number=row_number,
            duplicate_keys=duplicate_keys,
            header=header,
        )
        issues.extend(row_issues)
        if row_issues:
            invalid_row_count += 1
        else:
            valid_row_count += 1
            conditions.add(condition_name)

    return PreprocessingContactEdgesCsvValidationResult(
        csv_path=path,
        passed=not issues,
        row_count=len(rows),
        valid_row_count=valid_row_count,
        invalid_row_count=invalid_row_count,
        condition_count=len(conditions),
        aggregate_edge_count=valid_row_count,
        issues=tuple(issues),
    )


@dataclass(frozen=True)
class _PerFrameRowSummary:
    condition_name: str
    frame_index: int


@dataclass(frozen=True)
class _CsvRows:
    header: tuple[str, ...]
    rows: list[list[str]]


def _validate_perframe_row(
    row: list[str],
    *,
    row_number: int,
    duplicate_keys: set[tuple[str, ...]],
    header: tuple[str, ...],
) -> tuple[
    list[PreprocessingContactsPerFrameCsvValidationIssue],
    _PerFrameRowSummary,
]:
    issues: list[PreprocessingContactsPerFrameCsvValidationIssue] = []
    if len(row) != len(header):
        issues.append(
            _perframe_issue(
                "invalid_column_count",
                row_number,
                "row",
                f"CSV row must contain exactly {len(header)} columns.",
            )
        )

    fields = _row_fields(row, header)
    typed_row = header == _TYPED_CONTACTS_PERFRAME_HEADER
    edge_type = fields.get("edge_type", "residue_contact")
    _add_required_issues(
        issues,
        row_number,
        fields,
        (
            "condition_name",
            "frame_index",
            "source_residue_index",
            "target_residue_index",
            "source_resname",
            "target_resname",
            "minimum_distance",
            "distance_unit",
            "frame_passed",
        ),
        _perframe_issue,
    )
    if typed_row and edge_type not in _TYPED_CONTACT_EDGE_TYPES:
        issues.append(
            _perframe_issue(
                "invalid_edge_type",
                row_number,
                "edge_type",
                "Edge type must be a supported protein contact type.",
            )
        )
    if edge_type != "backbone" and not fields["atom_filter"]:
        issues.append(
            _perframe_issue(
                "missing_required_value",
                row_number,
                "atom_filter",
                "Required value is missing.",
            )
        )

    frame_index = _validate_non_negative_integer(
        fields["frame_index"],
        row_number=row_number,
        field="frame_index",
        issues=issues,
        issue_factory=_perframe_issue,
    )
    source_index = _validate_non_negative_integer(
        fields["source_residue_index"],
        row_number=row_number,
        field="source_residue_index",
        issues=issues,
        issue_factory=_perframe_issue,
    )
    target_index = _validate_non_negative_integer(
        fields["target_residue_index"],
        row_number=row_number,
        field="target_residue_index",
        issues=issues,
        issue_factory=_perframe_issue,
    )
    if (
        source_index is not None
        and target_index is not None
        and source_index == target_index
    ):
        issues.append(
            _perframe_issue(
                "same_residue_pair",
                row_number,
                "target_residue_index",
                "Source and target residue indexes must differ.",
            )
        )

    _validate_optional_time_ps(
        fields["time_ps"],
        row_number=row_number,
        issues=issues,
    )
    _validate_required_float(
        fields["minimum_distance"],
        row_number=row_number,
        field="minimum_distance",
        issues=issues,
        issue_factory=_perframe_issue,
    )
    if fields["atom_filter"]:
        _validate_atom_filter(
            fields["atom_filter"],
            row_number=row_number,
            issues=issues,
            issue_factory=_perframe_issue,
        )
    if fields["frame_passed"] not in ("", "true", "false"):
        issues.append(
            _perframe_issue(
                "invalid_frame_passed",
                row_number,
                "frame_passed",
                "Frame passed value must be exactly true or false.",
            )
        )
    elif fields["frame_passed"] == "":
        issues.append(
            _perframe_issue(
                "invalid_frame_passed",
                row_number,
                "frame_passed",
                "Frame passed value must be exactly true or false.",
            )
        )

    key = tuple(
        fields[field_name]
        for field_name in (
            "condition_name",
            "frame_index",
            "source_residue_index",
            "target_residue_index",
            "source_residue_id",
            "target_residue_id",
            "source_resname",
            "target_resname",
            "source_segid",
            "target_segid",
            *(('edge_type',) if typed_row else ()),
            "distance_unit",
            "atom_filter",
        )
    )
    _add_duplicate_key_issue(
        issues,
        key,
        duplicate_keys,
        row_number=row_number,
        issue_factory=_perframe_issue,
    )

    return issues, _PerFrameRowSummary(
        condition_name=fields["condition_name"],
        frame_index=frame_index if frame_index is not None else 0,
    )


def _validate_edges_row(
    row: list[str],
    *,
    row_number: int,
    duplicate_keys: set[tuple[str, ...]],
    header: tuple[str, ...],
) -> tuple[list[PreprocessingContactEdgesCsvValidationIssue], str]:
    issues: list[PreprocessingContactEdgesCsvValidationIssue] = []
    if len(row) != len(header):
        issues.append(
            _edges_issue(
                "invalid_column_count",
                row_number,
                "row",
                f"CSV row must contain exactly {len(header)} columns.",
            )
        )

    fields = _row_fields(row, header)
    typed_row = header == _TYPED_CONTACT_EDGES_HEADER
    edge_type = fields.get("edge_type", "residue_contact")
    _add_required_issues(
        issues,
        row_number,
        fields,
        (
            "condition_name",
            "source_residue_index",
            "target_residue_index",
            "source_resname",
            "target_resname",
            "contact_frame_count",
            "total_frame_count",
            "contact_frequency",
            "minimum_distance",
            "mean_minimum_distance",
            "distance_unit",
            "atom_filter",
            *(('edge_type',) if typed_row else ()),
        ),
        _edges_issue,
    )
    if typed_row and edge_type not in _TYPED_CONTACT_EDGE_TYPES:
        issues.append(
            _edges_issue(
                "invalid_edge_type",
                row_number,
                "edge_type",
                "Edge type must be a supported protein contact type.",
            )
        )

    source_index = _validate_non_negative_integer(
        fields["source_residue_index"],
        row_number=row_number,
        field="source_residue_index",
        issues=issues,
        issue_factory=_edges_issue,
    )
    target_index = _validate_non_negative_integer(
        fields["target_residue_index"],
        row_number=row_number,
        field="target_residue_index",
        issues=issues,
        issue_factory=_edges_issue,
    )
    if (
        source_index is not None
        and target_index is not None
        and source_index == target_index
    ):
        issues.append(
            _edges_issue(
                "same_residue_pair",
                row_number,
                "target_residue_index",
                "Source and target residue indexes must differ.",
            )
        )

    contact_frame_count = _validate_positive_integer(
        fields["contact_frame_count"],
        row_number=row_number,
        field="contact_frame_count",
        invalid_kind="invalid_contact_frame_count",
        issues=issues,
    )
    total_frame_count = _validate_positive_integer(
        fields["total_frame_count"],
        row_number=row_number,
        field="total_frame_count",
        invalid_kind="invalid_total_frame_count",
        issues=issues,
    )
    if (
        contact_frame_count is not None
        and total_frame_count is not None
        and contact_frame_count > total_frame_count
    ):
        issues.append(
            _edges_issue(
                "contact_frame_count_exceeds_total_frame_count",
                row_number,
                "contact_frame_count",
                "Contact frame count must not exceed total frame count.",
            )
        )

    contact_frequency = _validate_contact_frequency(
        fields["contact_frequency"],
        row_number=row_number,
        issues=issues,
    )
    minimum_distance = _validate_required_float(
        fields["minimum_distance"],
        row_number=row_number,
        field="minimum_distance",
        issues=issues,
        issue_factory=_edges_issue,
    )
    mean_minimum_distance = _validate_required_float(
        fields["mean_minimum_distance"],
        row_number=row_number,
        field="mean_minimum_distance",
        issues=issues,
        issue_factory=_edges_issue,
    )
    if (
        minimum_distance is not None
        and mean_minimum_distance is not None
        and mean_minimum_distance < minimum_distance
    ):
        issues.append(
            _edges_issue(
                "mean_distance_below_minimum_distance",
                row_number,
                "mean_minimum_distance",
                "Mean minimum distance must be at least the minimum distance.",
            )
        )

    if (
        contact_frame_count is not None
        and total_frame_count is not None
        and contact_frequency is not None
        and abs(contact_frequency - contact_frame_count / total_frame_count)
        > _FREQUENCY_TOLERANCE
    ):
        issues.append(
            _edges_issue(
                "contact_frequency_mismatch",
                row_number,
                "contact_frequency",
                "Contact frequency must match contact_frame_count divided by "
                "total_frame_count.",
            )
        )

    _validate_atom_filter(
        fields["atom_filter"],
        row_number=row_number,
        issues=issues,
        issue_factory=_edges_issue,
    )

    key = tuple(
        fields[field_name]
        for field_name in (
            "condition_name",
            "source_residue_index",
            "target_residue_index",
            "source_residue_id",
            "target_residue_id",
            "source_resname",
            "target_resname",
            "source_segid",
            "target_segid",
            *(('edge_type',) if typed_row else ()),
            "distance_unit",
            "atom_filter",
        )
    )
    _add_duplicate_key_issue(
        issues,
        key,
        duplicate_keys,
        row_number=row_number,
        issue_factory=_edges_issue,
    )

    return issues, fields["condition_name"]


def _read_file_issue(
    path: Path,
    *,
    file_label: str,
) -> tuple[str, str, str] | None:
    if not path.exists():
        return "missing_file", "csv_path", f"{file_label} file does not exist."
    if path.is_dir():
        return (
            "path_is_directory",
            "csv_path",
            f"{file_label} path is a directory.",
        )
    return None


def _read_csv(
    path: Path,
) -> _CsvRows | tuple[str, str, str]:
    try:
        with path.open(encoding="utf-8", newline="") as csv_file:
            reader = csv.reader(csv_file, strict=True)
            try:
                header = tuple(next(reader))
            except StopIteration:
                return (
                    "empty_file",
                    "csv_path",
                    "Contacts CSV file is empty.",
                )
            rows = list(reader)
    except (OSError, UnicodeError, csv.Error):
        return (
            "read_error",
            "csv_path",
            "Contacts CSV file could not be read as UTF-8 CSV.",
        )
    return _CsvRows(header=header, rows=rows)


def _row_fields(
    row: list[str],
    header: tuple[str, ...],
) -> dict[str, str]:
    return {
        field_name: row[index] if index < len(row) else ""
        for index, field_name in enumerate(header)
    }


def _add_required_issues(
    issues: list[_IssueT],
    row_number: int,
    fields: dict[str, str],
    required_fields: tuple[str, ...],
    issue_factory: Callable[[str, int | None, str, str], _IssueT],
) -> None:
    for field_name in required_fields:
        if fields[field_name].strip() == "":
            issues.append(
                issue_factory(
                    "empty_required_field",
                    row_number,
                    field_name,
                    "Required field must not be empty.",
                )
            )


def _validate_non_negative_integer(
    value: str,
    *,
    row_number: int,
    field: str,
    issues: list[_IssueT],
    issue_factory: Callable[[str, int | None, str, str], _IssueT],
) -> int | None:
    if value.strip() == "":
        return None
    integer = _integer(value)
    if integer is None:
        issues.append(
            issue_factory(
                "invalid_integer",
                row_number,
                field,
                "Field must be an integer.",
            )
        )
        return None
    if integer < 0:
        issues.append(
            issue_factory(
                "negative_integer",
                row_number,
                field,
                "Field must be a non-negative integer.",
            )
        )
        return None
    return integer


def _validate_positive_integer(
    value: str,
    *,
    row_number: int,
    field: str,
    invalid_kind: str,
    issues: list[PreprocessingContactEdgesCsvValidationIssue],
) -> int | None:
    if value.strip() == "":
        return None
    integer = _integer(value)
    if integer is None or integer <= 0:
        issues.append(
            _edges_issue(
                invalid_kind,
                row_number,
                field,
                "Field must be a positive integer.",
            )
        )
        return None
    return integer


def _validate_optional_time_ps(
    value: str,
    *,
    row_number: int,
    issues: list[PreprocessingContactsPerFrameCsvValidationIssue],
) -> None:
    if value == "":
        return
    number = _float(value)
    if number is None or number < 0:
        issues.append(
            _perframe_issue(
                "invalid_time_ps",
                row_number,
                "time_ps",
                "Frame time must be empty or a finite non-negative number.",
            )
        )


def _validate_required_float(
    value: str,
    *,
    row_number: int,
    field: str,
    issues: list[_IssueT],
    issue_factory: Callable[[str, int | None, str, str], _IssueT],
) -> float | None:
    if value.strip() == "":
        return None
    number = _float(value)
    if number is None:
        issues.append(
            issue_factory(
                "invalid_float",
                row_number,
                field,
                "Field must be a finite number.",
            )
        )
        return None
    if number < 0:
        issues.append(
            issue_factory(
                "negative_float",
                row_number,
                field,
                "Field must be non-negative.",
            )
        )
        return None
    return number


def _validate_contact_frequency(
    value: str,
    *,
    row_number: int,
    issues: list[PreprocessingContactEdgesCsvValidationIssue],
) -> float | None:
    if value.strip() == "":
        return None
    number = _float(value)
    if number is None or number < 0 or number > 1:
        issues.append(
            _edges_issue(
                "invalid_contact_frequency",
                row_number,
                "contact_frequency",
                "Contact frequency must be a finite number from 0 to 1.",
            )
        )
        return None
    return number


def _validate_atom_filter(
    value: str,
    *,
    row_number: int,
    issues: list[_IssueT],
    issue_factory: Callable[[str, int | None, str, str], _IssueT],
) -> None:
    if value == "" or value in _ATOM_FILTERS:
        return
    issues.append(
        issue_factory(
            "invalid_atom_filter",
            row_number,
            "atom_filter",
            "Atom filter must be exactly heavy or all.",
        )
    )


def _add_duplicate_key_issue(
    issues: list[_IssueT],
    key: tuple[str, ...],
    duplicate_keys: set[tuple[str, ...]],
    *,
    row_number: int,
    issue_factory: Callable[[str, int | None, str, str], _IssueT],
) -> None:
    if key in duplicate_keys:
        issues.append(
            issue_factory(
                "duplicate_row_key",
                row_number,
                "row",
                "CSV row key must be unique.",
            )
        )
    else:
        duplicate_keys.add(key)


def _integer(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        return None


def _float(value: str) -> float | None:
    try:
        number = float(value)
    except ValueError:
        return None
    if not math.isfinite(number):
        return None
    return number


def _non_empty_string(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a non-empty string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must be a non-empty string")
    return normalized


def _require_non_negative_int(value: object, field_name: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
    ):
        raise ValueError(f"{field_name} must be a non-negative int")


def _perframe_issue(
    kind: str,
    row_number: int | None,
    field: str,
    message: str,
) -> PreprocessingContactsPerFrameCsvValidationIssue:
    return PreprocessingContactsPerFrameCsvValidationIssue(
        kind=kind,
        row_number=row_number,
        field=field,
        message=message,
    )


def _edges_issue(
    kind: str,
    row_number: int | None,
    field: str,
    message: str,
) -> PreprocessingContactEdgesCsvValidationIssue:
    return PreprocessingContactEdgesCsvValidationIssue(
        kind=kind,
        row_number=row_number,
        field=field,
        message=message,
    )


def _perframe_file_issue_result(
    csv_path: Path,
    kind: str,
    field: str,
    message: str,
) -> PreprocessingContactsPerFrameCsvValidationResult:
    return PreprocessingContactsPerFrameCsvValidationResult(
        csv_path=csv_path,
        passed=False,
        row_count=0,
        valid_row_count=0,
        invalid_row_count=0,
        condition_count=0,
        frame_count=0,
        contact_count=0,
        issues=(_perframe_issue(kind, None, field, message),),
    )


def _edges_file_issue_result(
    csv_path: Path,
    kind: str,
    field: str,
    message: str,
) -> PreprocessingContactEdgesCsvValidationResult:
    return PreprocessingContactEdgesCsvValidationResult(
        csv_path=csv_path,
        passed=False,
        row_count=0,
        valid_row_count=0,
        invalid_row_count=0,
        condition_count=0,
        aggregate_edge_count=0,
        issues=(_edges_issue(kind, None, field, message),),
    )


__all__ = [
    "PreprocessingContactEdgesCsvValidationIssue",
    "PreprocessingContactEdgesCsvValidationResult",
    "PreprocessingContactsPerFrameCsvValidationIssue",
    "PreprocessingContactsPerFrameCsvValidationResult",
    "validate_contact_edges_csv",
    "validate_contacts_perframe_csv",
]
