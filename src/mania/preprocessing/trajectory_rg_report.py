"""Dependency-free in-memory reporting for existing Rg results."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from mania.preprocessing.trajectory_rg import (
    PreprocessingConditionRgResult,
    PreprocessingManifestRgResult,
)
from mania.preprocessing.trajectory_rg_export import (
    PreprocessingRgCsvWriteResult,
)
from mania.preprocessing.trajectory_rg_export_validation import (
    PreprocessingRgCsvValidationResult,
)
from mania.preprocessing.trajectory_rg_reference_comparison import (
    PreprocessingRgReferenceComparisonResult,
)


@dataclass(frozen=True)
class PreprocessingRgReportBundleIssue:
    """One deterministic Rg report bundle issue."""

    kind: Literal[
        "missing_computation_result",
        "invalid_computation_result",
        "invalid_write_result",
        "invalid_validation_result",
        "invalid_comparison_result",
        "inconsistent_export_counts",
        "inconsistent_validation_counts",
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
class PreprocessingRgReportBundleSummary:
    """Flattened status and count summary for existing Rg reports."""

    computation_present: bool
    computation_passed: bool | None
    condition_count: int
    computed_condition_count: int
    failed_condition_count: int
    frame_count: int
    passed_frame_count: int
    failed_frame_count: int
    csv_write_present: bool
    csv_write_passed: bool | None
    csv_rows_written: int | None
    csv_validation_present: bool
    csv_validation_passed: bool | None
    csv_validation_row_count: int | None
    comparison_present: bool
    comparison_passed: bool | None
    comparison_matched_row_count: int | None
    comparison_failed_row_count: int | None
    max_rg_abs_difference: float | None
    max_rg_rel_difference: float | None
    max_time_abs_difference: float | None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable flattened summary."""
        return {
            "computation_present": self.computation_present,
            "computation_passed": self.computation_passed,
            "condition_count": self.condition_count,
            "computed_condition_count": self.computed_condition_count,
            "failed_condition_count": self.failed_condition_count,
            "frame_count": self.frame_count,
            "passed_frame_count": self.passed_frame_count,
            "failed_frame_count": self.failed_frame_count,
            "csv_write_present": self.csv_write_present,
            "csv_write_passed": self.csv_write_passed,
            "csv_rows_written": self.csv_rows_written,
            "csv_validation_present": self.csv_validation_present,
            "csv_validation_passed": self.csv_validation_passed,
            "csv_validation_row_count": self.csv_validation_row_count,
            "comparison_present": self.comparison_present,
            "comparison_passed": self.comparison_passed,
            "comparison_matched_row_count": (
                self.comparison_matched_row_count
            ),
            "comparison_failed_row_count": (
                self.comparison_failed_row_count
            ),
            "max_rg_abs_difference": self.max_rg_abs_difference,
            "max_rg_rel_difference": self.max_rg_rel_difference,
            "max_time_abs_difference": self.max_time_abs_difference,
        }


@dataclass(frozen=True)
class PreprocessingRgReportBundle:
    """Complete in-memory report for existing Stage 12 Rg results."""

    summary: PreprocessingRgReportBundleSummary
    computation_result: (
        PreprocessingManifestRgResult
        | PreprocessingConditionRgResult
        | None
    )
    csv_write_result: PreprocessingRgCsvWriteResult | None
    csv_validation_result: PreprocessingRgCsvValidationResult | None
    comparison_result: PreprocessingRgReferenceComparisonResult | None
    issues: tuple[PreprocessingRgReportBundleIssue, ...]

    @property
    def passed(self) -> bool:
        """Return whether every provided report passed without bundle issues."""
        return (
            not self.issues
            and (
                self.computation_result is None
                or self.computation_result.passed
            )
            and (
                self.csv_write_result is None
                or self.csv_write_result.passed
            )
            and (
                self.csv_validation_result is None
                or self.csv_validation_result.passed
            )
            and (
                self.comparison_result is None
                or self.comparison_result.passed
            )
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable report bundle."""
        return {
            "summary": self.summary.to_dict(),
            "computation_result": (
                self.computation_result.to_dict()
                if self.computation_result is not None
                else None
            ),
            "csv_write_result": (
                self.csv_write_result.to_dict()
                if self.csv_write_result is not None
                else None
            ),
            "csv_validation_result": (
                self.csv_validation_result.to_dict()
                if self.csv_validation_result is not None
                else None
            ),
            "comparison_result": (
                self.comparison_result.to_dict()
                if self.comparison_result is not None
                else None
            ),
            "issues": [issue.to_dict() for issue in self.issues],
            "passed": self.passed,
        }


def build_rg_report_bundle(
    *,
    computation_result: (
        PreprocessingManifestRgResult
        | PreprocessingConditionRgResult
        | None
    ) = None,
    csv_write_result: PreprocessingRgCsvWriteResult | None = None,
    csv_validation_result: PreprocessingRgCsvValidationResult | None = None,
    comparison_result: PreprocessingRgReferenceComparisonResult | None = None,
) -> PreprocessingRgReportBundle:
    """Build an in-memory bundle from already available Rg result objects."""
    issues: list[PreprocessingRgReportBundleIssue] = []
    computation = _normalize_computation(computation_result, issues)
    write = _normalize_write(csv_write_result, issues)
    validation = _normalize_validation(csv_validation_result, issues)
    comparison = _normalize_comparison(comparison_result, issues)

    if computation_result is None:
        issues.append(
            _issue(
                "missing_computation_result",
                "computation_result",
                "An Rg computation result is required.",
            )
        )

    summary = _build_summary(
        computation,
        write,
        validation,
        comparison,
    )
    _add_consistency_issues(
        summary,
        write,
        validation,
        comparison,
        issues,
    )
    return PreprocessingRgReportBundle(
        summary=summary,
        computation_result=computation,
        csv_write_result=write,
        csv_validation_result=validation,
        comparison_result=comparison,
        issues=tuple(issues),
    )


def _normalize_computation(
    value: object,
    issues: list[PreprocessingRgReportBundleIssue],
) -> PreprocessingManifestRgResult | PreprocessingConditionRgResult | None:
    if value is None or isinstance(
        value,
        (PreprocessingManifestRgResult, PreprocessingConditionRgResult),
    ):
        return value
    issues.append(
        _issue(
            "invalid_computation_result",
            "computation_result",
            "Computation result has an unsupported type.",
        )
    )
    return None


def _normalize_write(
    value: object,
    issues: list[PreprocessingRgReportBundleIssue],
) -> PreprocessingRgCsvWriteResult | None:
    if value is None or isinstance(value, PreprocessingRgCsvWriteResult):
        return value
    issues.append(
        _issue(
            "invalid_write_result",
            "csv_write_result",
            "CSV write result has an unsupported type.",
        )
    )
    return None


def _normalize_validation(
    value: object,
    issues: list[PreprocessingRgReportBundleIssue],
) -> PreprocessingRgCsvValidationResult | None:
    if value is None or isinstance(value, PreprocessingRgCsvValidationResult):
        return value
    issues.append(
        _issue(
            "invalid_validation_result",
            "csv_validation_result",
            "CSV validation result has an unsupported type.",
        )
    )
    return None


def _normalize_comparison(
    value: object,
    issues: list[PreprocessingRgReportBundleIssue],
) -> PreprocessingRgReferenceComparisonResult | None:
    if value is None or isinstance(
        value,
        PreprocessingRgReferenceComparisonResult,
    ):
        return value
    issues.append(
        _issue(
            "invalid_comparison_result",
            "comparison_result",
            "Reference comparison result has an unsupported type.",
        )
    )
    return None


def _build_summary(
    computation: (
        PreprocessingManifestRgResult
        | PreprocessingConditionRgResult
        | None
    ),
    write: PreprocessingRgCsvWriteResult | None,
    validation: PreprocessingRgCsvValidationResult | None,
    comparison: PreprocessingRgReferenceComparisonResult | None,
) -> PreprocessingRgReportBundleSummary:
    (
        condition_count,
        computed_condition_count,
        failed_condition_count,
        frame_count,
        passed_frame_count,
        failed_frame_count,
    ) = _computation_counts(computation)
    return PreprocessingRgReportBundleSummary(
        computation_present=computation is not None,
        computation_passed=(
            computation.passed if computation is not None else None
        ),
        condition_count=condition_count,
        computed_condition_count=computed_condition_count,
        failed_condition_count=failed_condition_count,
        frame_count=frame_count,
        passed_frame_count=passed_frame_count,
        failed_frame_count=failed_frame_count,
        csv_write_present=write is not None,
        csv_write_passed=write.passed if write is not None else None,
        csv_rows_written=write.rows_written if write is not None else None,
        csv_validation_present=validation is not None,
        csv_validation_passed=(
            validation.passed if validation is not None else None
        ),
        csv_validation_row_count=(
            validation.row_count if validation is not None else None
        ),
        comparison_present=comparison is not None,
        comparison_passed=(
            comparison.passed if comparison is not None else None
        ),
        comparison_matched_row_count=(
            comparison.matched_row_count
            if comparison is not None
            else None
        ),
        comparison_failed_row_count=(
            comparison.failed_row_count
            if comparison is not None
            else None
        ),
        max_rg_abs_difference=(
            comparison.max_rg_abs_difference
            if comparison is not None
            else None
        ),
        max_rg_rel_difference=(
            comparison.max_rg_rel_difference
            if comparison is not None
            else None
        ),
        max_time_abs_difference=(
            comparison.max_time_abs_difference
            if comparison is not None
            else None
        ),
    )


def _computation_counts(
    computation: (
        PreprocessingManifestRgResult
        | PreprocessingConditionRgResult
        | None
    ),
) -> tuple[int, int, int, int, int, int]:
    if isinstance(computation, PreprocessingManifestRgResult):
        return (
            computation.total_conditions,
            computation.passed_conditions,
            computation.failed_conditions,
            computation.total_frames,
            computation.valid_frames,
            computation.failed_frames,
        )
    if isinstance(computation, PreprocessingConditionRgResult):
        computed_count = int(computation.passed)
        return (
            1,
            computed_count,
            1 - computed_count,
            computation.frame_count,
            computation.valid_frame_count,
            computation.failed_frame_count,
        )
    return (0, 0, 0, 0, 0, 0)


def _add_consistency_issues(
    summary: PreprocessingRgReportBundleSummary,
    write: PreprocessingRgCsvWriteResult | None,
    validation: PreprocessingRgCsvValidationResult | None,
    comparison: PreprocessingRgReferenceComparisonResult | None,
    issues: list[PreprocessingRgReportBundleIssue],
) -> None:
    if (
        write is not None
        and validation is not None
        and write.passed
        and validation.passed
        and write.rows_written != validation.row_count
    ):
        issues.append(
            _issue(
                "inconsistent_validation_counts",
                "csv_write_result.rows_written,csv_validation_result.row_count",
                "CSV write and validation row counts differ.",
            )
        )
    if (
        write is not None
        and summary.computation_present
        and write.rows_written > summary.frame_count
    ):
        issues.append(
            _issue(
                "inconsistent_export_counts",
                "csv_write_result.rows_written",
                "CSV rows written exceed computed frame count.",
            )
        )
    if (
        validation is not None
        and comparison is not None
        and validation.passed
        and validation.row_count != comparison.actual_row_count
    ):
        issues.append(
            _issue(
                "inconsistent_validation_counts",
                (
                    "csv_validation_result.row_count,"
                    "comparison_result.actual_row_count"
                ),
                "CSV validation and comparison actual row counts differ.",
            )
        )


def _issue(
    kind: Literal[
        "missing_computation_result",
        "invalid_computation_result",
        "invalid_write_result",
        "invalid_validation_result",
        "invalid_comparison_result",
        "inconsistent_export_counts",
        "inconsistent_validation_counts",
    ],
    field: str,
    message: str,
) -> PreprocessingRgReportBundleIssue:
    return PreprocessingRgReportBundleIssue(
        kind=kind,
        field=field,
        message=message,
    )
