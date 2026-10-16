"""Dependency-free CSV writing for already computed Rg results."""

from __future__ import annotations

import csv
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias

from mania.preprocessing import trajectory_rg

PreprocessingConditionRgResult: TypeAlias = (
    trajectory_rg.PreprocessingConditionRgResult
)
PreprocessingManifestRgResult: TypeAlias = (
    trajectory_rg.PreprocessingManifestRgResult
)
PreprocessingRgFrameResult: TypeAlias = trajectory_rg.PreprocessingRgFrameResult

_CSV_HEADER = (
    "condition_name",
    "frame_index",
    "time_ps",
    "rg_value",
    "rg_unit",
    "frame_passed",
)


@dataclass(frozen=True)
class PreprocessingRgCsvWriteIssue:
    """One deterministic Rg CSV write issue."""

    kind: Literal[
        "empty_rg_result",
        "no_writable_frames",
        "output_exists",
        "output_directory_missing",
        "output_path_is_directory",
        "write_error",
        "invalid_row",
    ]
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
class PreprocessingRgCsvWriteResult:
    """Summary of one Rg CSV write attempt."""

    output_path: Path
    passed: bool
    rows_written: int
    condition_count: int
    frame_count: int
    skipped_frame_count: int
    issues: tuple[PreprocessingRgCsvWriteIssue, ...]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable write summary."""
        return {
            "output_path": str(self.output_path),
            "passed": self.passed,
            "rows_written": self.rows_written,
            "condition_count": self.condition_count,
            "frame_count": self.frame_count,
            "skipped_frame_count": self.skipped_frame_count,
            "issues": [issue.to_dict() for issue in self.issues],
        }


def write_rg_timeseries_csv(
    rg_result: PreprocessingManifestRgResult | PreprocessingConditionRgResult,
    output_path: str | Path,
    *,
    include_failed_frames: bool = False,
    overwrite: bool = True,
) -> PreprocessingRgCsvWriteResult:
    """Write ordered frame results to a deterministic UTF-8 CSV file."""
    path = Path(output_path)
    condition_results = _condition_results(rg_result)
    condition_count = len(condition_results)
    frame_count = sum(
        len(condition_result.frame_results)
        for condition_result in condition_results
    )

    if (
        isinstance(rg_result, trajectory_rg.PreprocessingManifestRgResult)
        and not condition_results
    ):
        return _failed_result(
            path,
            condition_count=0,
            frame_count=0,
            kind="empty_rg_result",
            field="rg_result.condition_results",
            message="Manifest Rg result contains no condition results.",
        )

    rows: list[tuple[str, str, str, str, str, str]] = []
    row_issues: list[PreprocessingRgCsvWriteIssue] = []
    for condition_index, condition_result in enumerate(condition_results):
        for frame_result in condition_result.frame_results:
            if not include_failed_frames and not frame_result.passed:
                continue
            try:
                rows.append(_frame_row(frame_result))
            except (TypeError, ValueError):
                row_issues.append(
                    PreprocessingRgCsvWriteIssue(
                        kind="invalid_row",
                        field=(
                            "rg_result.condition_results"
                            f"[{condition_index}].frame_results"
                            f"[{frame_result.frame_index}]"
                        ),
                        message="Frame result cannot be represented as a CSV row.",
                    )
                )

    if row_issues:
        return PreprocessingRgCsvWriteResult(
            output_path=path,
            passed=False,
            rows_written=0,
            condition_count=condition_count,
            frame_count=frame_count,
            skipped_frame_count=frame_count,
            issues=tuple(row_issues),
        )

    if not rows:
        return _failed_result(
            path,
            condition_count=condition_count,
            frame_count=frame_count,
            kind="no_writable_frames",
            field="rg_result.frame_results",
            message="Rg result contains no writable frame rows.",
        )

    if not path.parent.is_dir():
        return _failed_result(
            path,
            condition_count=condition_count,
            frame_count=frame_count,
            kind="output_directory_missing",
            field="output_path.parent",
            message="Output parent directory is missing or is not a directory.",
        )
    if path.is_dir():
        return _failed_result(
            path,
            condition_count=condition_count,
            frame_count=frame_count,
            kind="output_path_is_directory",
            field="output_path",
            message="Output path is a directory.",
        )
    if path.exists() and not overwrite:
        return _failed_result(
            path,
            condition_count=condition_count,
            frame_count=frame_count,
            kind="output_exists",
            field="output_path",
            message="Output path already exists and overwrite is disabled.",
        )

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as csv_file:
            temporary_path = Path(csv_file.name)
            writer = csv.writer(csv_file, lineterminator="\n")
            writer.writerow(_CSV_HEADER)
            writer.writerows(rows)
        temporary_path.replace(path)
    except (OSError, csv.Error):
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        return _failed_result(
            path,
            condition_count=condition_count,
            frame_count=frame_count,
            kind="write_error",
            field="output_path",
            message="Rg CSV file could not be written.",
        )

    rows_written = len(rows)
    return PreprocessingRgCsvWriteResult(
        output_path=path,
        passed=True,
        rows_written=rows_written,
        condition_count=condition_count,
        frame_count=frame_count,
        skipped_frame_count=frame_count - rows_written,
        issues=(),
    )


def _condition_results(
    rg_result: PreprocessingManifestRgResult | PreprocessingConditionRgResult,
) -> tuple[PreprocessingConditionRgResult, ...]:
    if isinstance(rg_result, trajectory_rg.PreprocessingManifestRgResult):
        return rg_result.condition_results
    if isinstance(rg_result, trajectory_rg.PreprocessingConditionRgResult):
        return (rg_result,)
    raise TypeError("rg_result must be a manifest or condition Rg result")


def _frame_row(
    frame_result: PreprocessingRgFrameResult,
) -> tuple[str, str, str, str, str, str]:
    if not isinstance(frame_result.condition_name, str):
        raise TypeError("condition_name must be a string")
    if (
        isinstance(frame_result.frame_index, bool)
        or not isinstance(frame_result.frame_index, int)
        or frame_result.frame_index < 0
    ):
        raise ValueError("frame_index must be a non-negative int")
    if frame_result.rg_unit is not None and not isinstance(
        frame_result.rg_unit,
        str,
    ):
        raise TypeError("rg_unit must be a string or None")

    return (
        frame_result.condition_name,
        str(frame_result.frame_index),
        _optional_number_text(frame_result.time_ps),
        _optional_number_text(frame_result.rg_value),
        frame_result.rg_unit or "",
        "true" if frame_result.passed else "false",
    )


def _optional_number_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("numeric CSV values must be numbers or None")
    return str(value)


def _failed_result(
    output_path: Path,
    *,
    condition_count: int,
    frame_count: int,
    kind: Literal[
        "empty_rg_result",
        "no_writable_frames",
        "output_exists",
        "output_directory_missing",
        "output_path_is_directory",
        "write_error",
    ],
    field: str,
    message: str,
) -> PreprocessingRgCsvWriteResult:
    return PreprocessingRgCsvWriteResult(
        output_path=output_path,
        passed=False,
        rows_written=0,
        condition_count=condition_count,
        frame_count=frame_count,
        skipped_frame_count=frame_count,
        issues=(
            PreprocessingRgCsvWriteIssue(
                kind=kind,
                field=field,
                message=message,
            ),
        ),
    )


__all__ = [
    "PreprocessingRgCsvWriteIssue",
    "PreprocessingRgCsvWriteResult",
    "write_rg_timeseries_csv",
]
