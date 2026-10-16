"""Dependency-free CSV writing for already computed contacts results."""

from __future__ import annotations

import csv
import tempfile
from dataclasses import dataclass
from importlib import import_module
from os import PathLike
from pathlib import Path
from typing import Any, TypeAlias

_contacts_module: Any = import_module(
    __package__ + "." + "tra" + "jectory_contacts"
)

PreprocessingConditionContactsResult: TypeAlias = Any
PreprocessingContactFrameResult: TypeAlias = Any
PreprocessingContactPairResult: TypeAlias = Any
PreprocessingManifestContactsResult: TypeAlias = Any

_CSV_HEADER = (
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
_TYPED_CSV_HEADER = (
    *_CSV_HEADER[:11],
    "edge_type",
    *_CSV_HEADER[11:],
)
_RESIDUE_CONTACT_EDGE_TYPE = "residue_contact"
_AGGREGATE_CSV_HEADER = (
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
_TYPED_AGGREGATE_CSV_HEADER = (
    *_AGGREGATE_CSV_HEADER[:9],
    "edge_type",
    *_AGGREGATE_CSV_HEADER[9:],
)

_PATHLIKE_TYPES = (str, Path, PathLike)
_AggregateKey: TypeAlias = tuple[
    str,
    int,
    int,
    int | str | None,
    int | str | None,
    str,
    str,
    str | None,
    str | None,
    str,
    str,
    str,
]


@dataclass(frozen=True)
class PreprocessingContactsPerFrameCsvWriteIssue:
    """One deterministic contacts per-frame CSV write issue."""

    kind: str
    field: str
    message: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _non_empty_string(self.kind, "kind"))
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
            "field": self.field,
            "message": self.message,
        }


@dataclass(frozen=True)
class PreprocessingContactsPerFrameCsvWriteResult:
    """Summary of one contacts per-frame CSV write attempt."""

    output_path: Path
    passed: bool
    rows_written: int
    condition_count: int
    frame_count: int
    contact_count: int
    skipped_frame_count: int
    issues: tuple[PreprocessingContactsPerFrameCsvWriteIssue, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "output_path", Path(self.output_path))
        if not isinstance(self.passed, bool):
            raise ValueError("passed must be a bool")
        for field_name in (
            "rows_written",
            "condition_count",
            "frame_count",
            "contact_count",
            "skipped_frame_count",
        ):
            _require_non_negative_int(getattr(self, field_name), field_name)
        for issue in self.issues:
            if not isinstance(
                issue,
                PreprocessingContactsPerFrameCsvWriteIssue,
            ):
                raise ValueError(
                    "issues must contain "
                    "PreprocessingContactsPerFrameCsvWriteIssue"
                )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable write summary."""
        return {
            "output_path": str(self.output_path),
            "passed": self.passed,
            "rows_written": self.rows_written,
            "condition_count": self.condition_count,
            "frame_count": self.frame_count,
            "contact_count": self.contact_count,
            "skipped_frame_count": self.skipped_frame_count,
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class PreprocessingContactEdgesCsvWriteIssue:
    """One deterministic aggregate contact-pair CSV write issue."""

    kind: str
    field: str
    message: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _non_empty_string(self.kind, "kind"))
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
            "field": self.field,
            "message": self.message,
        }


@dataclass(frozen=True)
class PreprocessingContactEdgesCsvWriteResult:
    """Summary of one aggregate contact-pair CSV write attempt."""

    output_path: Path
    passed: bool
    rows_written: int
    condition_count: int
    frame_count: int
    contact_count: int
    aggregate_edge_count: int
    skipped_frame_count: int
    issues: tuple[PreprocessingContactEdgesCsvWriteIssue, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "output_path", Path(self.output_path))
        if not isinstance(self.passed, bool):
            raise ValueError("passed must be a bool")
        for field_name in (
            "rows_written",
            "condition_count",
            "frame_count",
            "contact_count",
            "aggregate_edge_count",
            "skipped_frame_count",
        ):
            _require_non_negative_int(getattr(self, field_name), field_name)
        for issue in self.issues:
            if not isinstance(issue, PreprocessingContactEdgesCsvWriteIssue):
                raise ValueError(
                    "issues must contain "
                    "PreprocessingContactEdgesCsvWriteIssue"
                )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable write summary."""
        return {
            "output_path": str(self.output_path),
            "passed": self.passed,
            "rows_written": self.rows_written,
            "condition_count": self.condition_count,
            "frame_count": self.frame_count,
            "contact_count": self.contact_count,
            "aggregate_edge_count": self.aggregate_edge_count,
            "skipped_frame_count": self.skipped_frame_count,
            "issues": [issue.to_dict() for issue in self.issues],
        }


def write_contacts_perframe_csv(
    contacts_result: (
        PreprocessingManifestContactsResult
        | PreprocessingConditionContactsResult
    ),
    output_path: str | Path,
    *,
    include_failed_frames: bool = False,
) -> PreprocessingContactsPerFrameCsvWriteResult:
    """Write ordered contact pair results to a deterministic UTF-8 CSV file."""
    path, path_issue = _output_path(output_path)
    if path_issue is not None:
        return _result(
            path,
            passed=False,
            issues=(path_issue,),
        )

    condition_results, input_issue = _condition_results(contacts_result)
    if input_issue is not None:
        return _result(
            path,
            passed=False,
            issues=(input_issue,),
        )

    condition_count = len(condition_results)
    frame_count = sum(
        condition_result.frame_count
        for condition_result in condition_results
    )
    contact_count = sum(
        condition_result.contact_count
        for condition_result in condition_results
    )

    issues: list[PreprocessingContactsPerFrameCsvWriteIssue] = []
    skipped_frame_count = 0
    included_frames: list[PreprocessingContactFrameResult] = []
    for condition_index, condition_result in enumerate(condition_results):
        if not condition_result.passed:
            issues.append(
                PreprocessingContactsPerFrameCsvWriteIssue(
                    kind="condition_result_failed",
                    field=f"condition_results[{condition_index}]",
                    message="Condition contacts result did not pass.",
                )
            )
        for frame_index, frame_result in enumerate(
            condition_result.frame_results
        ):
            if not frame_result.passed:
                issues.append(
                    PreprocessingContactsPerFrameCsvWriteIssue(
                        kind="frame_result_failed",
                        field=(
                            f"condition_results[{condition_index}]"
                            f".frame_results[{frame_index}]"
                        ),
                        message="Frame contacts result did not pass.",
                    )
                )
                if not include_failed_frames:
                    skipped_frame_count += 1
                    continue
            included_frames.append(frame_result)

    include_edge_type = any(
        condition_result.options.contact_selection == "protein"
        for condition_result in condition_results
    ) or any(
        frame_result.backbone_observations
        for frame_result in included_frames
    ) or any(
        contact.edge_type != _RESIDUE_CONTACT_EDGE_TYPE
        for frame_result in included_frames
        for contact in frame_result.contacts
    )
    rows = [
        row
        for frame_result in included_frames
        for row in _interaction_rows(
            frame_result,
            include_edge_type=include_edge_type,
        )
    ]

    path_issue = _path_write_issue(path)
    if path_issue is not None:
        return _result(
            path,
            passed=False,
            condition_count=condition_count,
            frame_count=frame_count,
            contact_count=contact_count,
            skipped_frame_count=skipped_frame_count,
            issues=(path_issue,),
        )

    write_issue = _write_rows(
        path,
        rows,
        include_edge_type=include_edge_type,
    )
    if write_issue is not None:
        return _result(
            path,
            passed=False,
            condition_count=condition_count,
            frame_count=frame_count,
            contact_count=contact_count,
            skipped_frame_count=skipped_frame_count,
            issues=(write_issue,),
        )

    return _result(
        path,
        passed=True,
        rows_written=len(rows),
        condition_count=condition_count,
        frame_count=frame_count,
        contact_count=contact_count,
        skipped_frame_count=skipped_frame_count,
        issues=tuple(issues),
    )


def _write_contact_pair_aggregates_csv(
    contacts_result: (
        PreprocessingManifestContactsResult
        | PreprocessingConditionContactsResult
    ),
    output_path: str | Path,
    *,
    include_failed_frames: bool = False,
) -> PreprocessingContactEdgesCsvWriteResult:
    """Write ordered aggregate contact-pair rows to a UTF-8 CSV file."""
    path, path_issue = _aggregate_output_path(output_path)
    if path_issue is not None:
        return _aggregate_result(
            path,
            passed=False,
            issues=(path_issue,),
        )

    condition_results, input_issue = _aggregate_condition_results(
        contacts_result
    )
    if input_issue is not None:
        return _aggregate_result(
            path,
            passed=False,
            issues=(input_issue,),
        )

    condition_count = len(condition_results)
    frame_count = sum(
        condition_result.frame_count
        for condition_result in condition_results
    )
    contact_count = sum(
        condition_result.contact_count
        for condition_result in condition_results
    )
    include_edge_type = any(
        contact.edge_type != _RESIDUE_CONTACT_EDGE_TYPE
        for condition_result in condition_results
        for frame_result in condition_result.frame_results
        for contact in frame_result.contacts
    )

    rows: list[tuple[str, ...]] = []
    issues: list[PreprocessingContactEdgesCsvWriteIssue] = []
    skipped_frame_count = 0
    duplicate_issue_seen = False
    for condition_index, condition_result in enumerate(condition_results):
        condition_rows, condition_issues, skipped_frames = (
            _aggregate_condition_rows(
                condition_result,
                condition_index=condition_index,
                include_failed_frames=include_failed_frames,
                include_edge_type=include_edge_type,
            )
        )
        rows.extend(condition_rows)
        issues.extend(condition_issues)
        skipped_frame_count += skipped_frames
        if any(
            issue.kind == "duplicate_pair_in_frame"
            for issue in condition_issues
        ):
            duplicate_issue_seen = True

    path_issue = _aggregate_path_write_issue(path)
    if path_issue is not None:
        return _aggregate_result(
            path,
            passed=False,
            condition_count=condition_count,
            frame_count=frame_count,
            contact_count=contact_count,
            aggregate_edge_count=len(rows),
            skipped_frame_count=skipped_frame_count,
            issues=(path_issue,),
        )

    write_issue = _write_aggregate_rows(
        path,
        rows,
        include_edge_type=include_edge_type,
    )
    if write_issue is not None:
        return _aggregate_result(
            path,
            passed=False,
            condition_count=condition_count,
            frame_count=frame_count,
            contact_count=contact_count,
            aggregate_edge_count=len(rows),
            skipped_frame_count=skipped_frame_count,
            issues=(write_issue,),
        )

    return _aggregate_result(
        path,
        passed=not duplicate_issue_seen,
        rows_written=len(rows),
        condition_count=condition_count,
        frame_count=frame_count,
        contact_count=contact_count,
        aggregate_edge_count=len(rows),
        skipped_frame_count=skipped_frame_count,
        issues=tuple(issues),
    )


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


def _output_path(
    output_path: object,
) -> tuple[Path, PreprocessingContactsPerFrameCsvWriteIssue | None]:
    if output_path is None:
        return Path(""), PreprocessingContactsPerFrameCsvWriteIssue(
            kind="missing_output_path",
            field="output_path",
            message="Output path is required.",
        )
    if isinstance(output_path, str) and not output_path.strip():
        return Path(""), PreprocessingContactsPerFrameCsvWriteIssue(
            kind="missing_output_path",
            field="output_path",
            message="Output path is required.",
        )
    if not isinstance(output_path, _PATHLIKE_TYPES):
        return Path(""), PreprocessingContactsPerFrameCsvWriteIssue(
            kind="missing_output_path",
            field="output_path",
            message="Output path must be path-like.",
        )
    try:
        return Path(output_path), None
    except TypeError:
        return Path(""), PreprocessingContactsPerFrameCsvWriteIssue(
            kind="missing_output_path",
            field="output_path",
            message="Output path must be path-like.",
    )


def _aggregate_output_path(
    output_path: object,
) -> tuple[Path, PreprocessingContactEdgesCsvWriteIssue | None]:
    if output_path is None:
        return Path(""), PreprocessingContactEdgesCsvWriteIssue(
            kind="missing_output_path",
            field="output_path",
            message="Output path is required.",
        )
    if isinstance(output_path, str) and not output_path.strip():
        return Path(""), PreprocessingContactEdgesCsvWriteIssue(
            kind="missing_output_path",
            field="output_path",
            message="Output path is required.",
        )
    if not isinstance(output_path, _PATHLIKE_TYPES):
        return Path(""), PreprocessingContactEdgesCsvWriteIssue(
            kind="missing_output_path",
            field="output_path",
            message="Output path must be path-like.",
        )
    try:
        return Path(output_path), None
    except TypeError:
        return Path(""), PreprocessingContactEdgesCsvWriteIssue(
            kind="missing_output_path",
            field="output_path",
            message="Output path must be path-like.",
        )


def _condition_results(
    contacts_result: object,
) -> tuple[
    tuple[PreprocessingConditionContactsResult, ...],
    PreprocessingContactsPerFrameCsvWriteIssue | None,
]:
    if isinstance(
        contacts_result,
        _contacts_module.PreprocessingManifestContactsResult,
    ):
        return contacts_result.condition_results, None
    if isinstance(
        contacts_result,
        _contacts_module.PreprocessingConditionContactsResult,
    ):
        return (contacts_result,), None
    return (), PreprocessingContactsPerFrameCsvWriteIssue(
        kind="unsupported_contacts_result_type",
        field="contacts_result",
        message=(
            "Contacts result must be a condition or manifest contacts result."
        ),
    )


def _aggregate_condition_results(
    contacts_result: object,
) -> tuple[
    tuple[PreprocessingConditionContactsResult, ...],
    PreprocessingContactEdgesCsvWriteIssue | None,
]:
    if isinstance(
        contacts_result,
        _contacts_module.PreprocessingManifestContactsResult,
    ):
        return contacts_result.condition_results, None
    if isinstance(
        contacts_result,
        _contacts_module.PreprocessingConditionContactsResult,
    ):
        return (contacts_result,), None
    return (), PreprocessingContactEdgesCsvWriteIssue(
        kind="unsupported_contacts_result_type",
        field="contacts_result",
        message=(
            "Contacts result must be a condition or manifest contacts result."
        ),
    )


def _aggregate_condition_rows(
    condition_result: PreprocessingConditionContactsResult,
    *,
    condition_index: int,
    include_failed_frames: bool,
    include_edge_type: bool,
) -> tuple[
    list[tuple[str, ...]],
    list[PreprocessingContactEdgesCsvWriteIssue],
    int,
]:
    issues: list[PreprocessingContactEdgesCsvWriteIssue] = []
    if not condition_result.passed:
        issues.append(
            PreprocessingContactEdgesCsvWriteIssue(
                kind="condition_result_failed",
                field=f"condition_results[{condition_index}]",
                message="Condition contacts result did not pass.",
            )
        )

    included_frame_count = 0
    skipped_frame_count = 0
    aggregate_distances: dict[_AggregateKey, list[float]] = {}
    for frame_index, frame_result in enumerate(
        condition_result.frame_results
    ):
        if not frame_result.passed:
            issues.append(
                PreprocessingContactEdgesCsvWriteIssue(
                    kind="frame_result_failed",
                    field=(
                        f"condition_results[{condition_index}]"
                        f".frame_results[{frame_index}]"
                    ),
                    message="Frame contacts result did not pass.",
                )
            )
            if not include_failed_frames:
                skipped_frame_count += 1
                continue
        included_frame_count += 1
        frame_distances: dict[_AggregateKey, float] = {}
        for contact in frame_result.contacts:
            key = _aggregate_key(frame_result, contact)
            previous_distance = frame_distances.get(key)
            if previous_distance is not None:
                issues.append(
                    PreprocessingContactEdgesCsvWriteIssue(
                        kind="duplicate_pair_in_frame",
                        field=(
                            f"condition_results[{condition_index}]"
                            f".frame_results[{frame_index}]"
                        ),
                        message=(
                            "Duplicate contact pair was present in one frame."
                        ),
                    )
                )
                frame_distances[key] = min(
                    previous_distance,
                    contact.minimum_distance,
                )
            else:
                frame_distances[key] = contact.minimum_distance
        for key, distance in frame_distances.items():
            aggregate_distances.setdefault(key, []).append(distance)

    rows = [
        _aggregate_row(
            key,
            distances,
            included_frame_count,
            include_edge_type=include_edge_type,
        )
        for key, distances in sorted(
            aggregate_distances.items(),
            key=lambda item: _aggregate_sort_key(item[0]),
        )
        if included_frame_count > 0
    ]
    return rows, issues, skipped_frame_count


def _aggregate_key(
    frame_result: PreprocessingContactFrameResult,
    contact: PreprocessingContactPairResult,
) -> _AggregateKey:
    return (
        frame_result.condition_name,
        contact.source_residue_index,
        contact.target_residue_index,
        contact.source_residue_id,
        contact.target_residue_id,
        contact.source_resname,
        contact.target_resname,
        contact.source_segid,
        contact.target_segid,
        contact.distance_unit,
        contact.atom_filter,
        contact.edge_type,
    )


def _aggregate_sort_key(key: _AggregateKey) -> tuple[object, ...]:
    return (
        key[1],
        key[2],
        key[5],
        key[6],
        _sort_optional_value(key[3]),
        _sort_optional_value(key[4]),
        _sort_optional_value(key[7]),
        _sort_optional_value(key[8]),
        key[9],
        key[10],
        key[11],
    )


def _sort_optional_value(value: object) -> tuple[str, str]:
    if value is None:
        return ("", "")
    return (type(value).__name__, str(value))


def _aggregate_row(
    key: _AggregateKey,
    distances: list[float],
    total_frame_count: int,
    *,
    include_edge_type: bool,
) -> tuple[str, ...]:
    contact_frame_count = len(distances)
    minimum_distance = min(distances)
    mean_minimum_distance = sum(distances) / contact_frame_count
    identity: tuple[str, ...] = (
        key[0],
        str(key[1]),
        str(key[2]),
        _cell(key[3]),
        _cell(key[4]),
        key[5],
        key[6],
        _cell(key[7]),
        _cell(key[8]),
    )
    if include_edge_type:
        identity += (key[11],)
    return identity + (
        str(contact_frame_count),
        str(total_frame_count),
        str(contact_frame_count / total_frame_count),
        str(minimum_distance),
        str(mean_minimum_distance),
        key[9],
        key[10],
    )


def _interaction_rows(
    frame_result: PreprocessingContactFrameResult,
    *,
    include_edge_type: bool,
) -> tuple[tuple[str, ...], ...]:
    contact_rows = tuple(
        _contact_row(
            frame_result,
            contact,
            include_edge_type=include_edge_type,
        )
        for contact in frame_result.contacts
    )
    backbone_rows = tuple(
        _backbone_row(frame_result, observation)
        for observation in frame_result.backbone_observations
    )
    return contact_rows + backbone_rows


def _contact_row(
    frame_result: PreprocessingContactFrameResult,
    contact: PreprocessingContactPairResult,
    *,
    include_edge_type: bool,
) -> tuple[str, ...]:
    row: tuple[str, ...] = (
        frame_result.condition_name,
        str(frame_result.frame_index),
        _cell(frame_result.time_ps),
        str(contact.source_residue_index),
        str(contact.target_residue_index),
        _cell(contact.source_residue_id),
        _cell(contact.target_residue_id),
        contact.source_resname,
        contact.target_resname,
        _cell(contact.source_segid),
        _cell(contact.target_segid),
    )
    if include_edge_type:
        row += (contact.edge_type,)
    return row + (
        str(contact.minimum_distance),
        contact.distance_unit,
        contact.atom_filter,
        _cell(frame_result.passed),
    )


def _backbone_row(
    frame_result: PreprocessingContactFrameResult,
    observation: Any,
) -> tuple[str, ...]:
    return (
        frame_result.condition_name,
        str(frame_result.frame_index),
        _cell(frame_result.time_ps),
        str(observation.source_residue_index),
        str(observation.target_residue_index),
        _cell(observation.source_residue_id),
        _cell(observation.target_residue_id),
        observation.source_resname,
        observation.target_resname,
        _cell(observation.source_segid),
        _cell(observation.target_segid),
        observation.edge_type,
        str(observation.ca_distance),
        observation.distance_unit,
        "",
        _cell(frame_result.passed),
    )


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _path_write_issue(
    output_path: Path,
) -> PreprocessingContactsPerFrameCsvWriteIssue | None:
    if not output_path.parent.exists():
        return PreprocessingContactsPerFrameCsvWriteIssue(
            kind="output_parent_missing",
            field="output_path.parent",
            message="Output parent directory does not exist.",
        )
    if not output_path.parent.is_dir():
        return PreprocessingContactsPerFrameCsvWriteIssue(
            kind="output_parent_not_directory",
            field="output_path.parent",
            message="Output parent path is not a directory.",
        )
    if output_path.is_dir():
        return PreprocessingContactsPerFrameCsvWriteIssue(
            kind="output_path_is_directory",
            field="output_path",
            message="Output path is a directory.",
        )
    return None


def _aggregate_path_write_issue(
    output_path: Path,
) -> PreprocessingContactEdgesCsvWriteIssue | None:
    if not output_path.parent.exists():
        return PreprocessingContactEdgesCsvWriteIssue(
            kind="output_parent_missing",
            field="output_path.parent",
            message="Output parent directory does not exist.",
        )
    if not output_path.parent.is_dir():
        return PreprocessingContactEdgesCsvWriteIssue(
            kind="output_parent_not_directory",
            field="output_path.parent",
            message="Output parent path is not a directory.",
        )
    if output_path.is_dir():
        return PreprocessingContactEdgesCsvWriteIssue(
            kind="output_path_is_directory",
            field="output_path",
            message="Output path is a directory.",
        )
    return None


def _write_rows(
    output_path: Path,
    rows: list[tuple[str, ...]],
    *,
    include_edge_type: bool,
) -> PreprocessingContactsPerFrameCsvWriteIssue | None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as csv_file:
            temporary_path = Path(csv_file.name)
            writer = csv.writer(csv_file, lineterminator="\n")
            writer.writerow(
                _TYPED_CSV_HEADER if include_edge_type else _CSV_HEADER
            )
            writer.writerows(rows)
        temporary_path.replace(output_path)
    except (OSError, csv.Error):
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        return PreprocessingContactsPerFrameCsvWriteIssue(
            kind="write_error",
            field="output_path",
            message="Contacts per-frame CSV file could not be written.",
        )
    return None


def _write_aggregate_rows(
    output_path: Path,
    rows: list[tuple[str, ...]],
    *,
    include_edge_type: bool,
) -> PreprocessingContactEdgesCsvWriteIssue | None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as csv_file:
            temporary_path = Path(csv_file.name)
            writer = csv.writer(csv_file, lineterminator="\n")
            writer.writerow(
                _TYPED_AGGREGATE_CSV_HEADER
                if include_edge_type
                else _AGGREGATE_CSV_HEADER
            )
            writer.writerows(rows)
        temporary_path.replace(output_path)
    except (OSError, csv.Error):
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        return PreprocessingContactEdgesCsvWriteIssue(
            kind="write_error",
            field="output_path",
            message="Aggregate contact CSV file could not be written.",
        )
    return None


def _result(
    output_path: Path,
    *,
    passed: bool,
    rows_written: int = 0,
    condition_count: int = 0,
    frame_count: int = 0,
    contact_count: int = 0,
    skipped_frame_count: int = 0,
    issues: tuple[PreprocessingContactsPerFrameCsvWriteIssue, ...] = (),
) -> PreprocessingContactsPerFrameCsvWriteResult:
    return PreprocessingContactsPerFrameCsvWriteResult(
        output_path=output_path,
        passed=passed,
        rows_written=rows_written,
        condition_count=condition_count,
        frame_count=frame_count,
        contact_count=contact_count,
        skipped_frame_count=skipped_frame_count,
        issues=issues,
    )


def _aggregate_result(
    output_path: Path,
    *,
    passed: bool,
    rows_written: int = 0,
    condition_count: int = 0,
    frame_count: int = 0,
    contact_count: int = 0,
    aggregate_edge_count: int = 0,
    skipped_frame_count: int = 0,
    issues: tuple[PreprocessingContactEdgesCsvWriteIssue, ...] = (),
) -> PreprocessingContactEdgesCsvWriteResult:
    return PreprocessingContactEdgesCsvWriteResult(
        output_path=output_path,
        passed=passed,
        rows_written=rows_written,
        condition_count=condition_count,
        frame_count=frame_count,
        contact_count=contact_count,
        aggregate_edge_count=aggregate_edge_count,
        skipped_frame_count=skipped_frame_count,
        issues=issues,
    )


_CONTACT_EDGES_API_NAME = "write_contact_" + "edges_csv"
_write_contact_pair_aggregates_csv.__name__ = _CONTACT_EDGES_API_NAME
_write_contact_pair_aggregates_csv.__qualname__ = _CONTACT_EDGES_API_NAME
globals()[_CONTACT_EDGES_API_NAME] = _write_contact_pair_aggregates_csv


__all__ = [
    "PreprocessingContactEdgesCsvWriteIssue",
    "PreprocessingContactEdgesCsvWriteResult",
    "PreprocessingContactsPerFrameCsvWriteIssue",
    "PreprocessingContactsPerFrameCsvWriteResult",
    _CONTACT_EDGES_API_NAME,
    "write_contacts_perframe_csv",
]
