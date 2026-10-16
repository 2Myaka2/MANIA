"""Residue-library QC for explicit preprocessing residue-name inputs."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from mania.preprocessing.input_manifest import ResidueLibraryInputConfig
from mania.preprocessing.residue_library_bridge import (
    load_residue_library_from_manifest_options,
)
from mania.preprocessing.residue_library_validation import (
    PreprocessingResidueLibraryValidationReport,
    validate_residue_library_from_manifest_options,
)
from mania.residue_library import (
    ResidueLibraryQCError,
    ResidueQCReport,
    normalize_resname,
    run_residue_library_qc,
)

EXPLICIT_RESIDUE_NAMES_CONDITION = "explicit"


@dataclass(frozen=True)
class PreprocessingResidueQCIssue:
    """One preprocessing-level residue QC problem."""

    kind: Literal[
        "residue_library_validation_failed",
        "empty_residue_names",
        "invalid_residue_name",
        "qc_error",
    ]
    field: str
    message: str

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable preprocessing QC issue."""
        return {
            "kind": self.kind,
            "field": self.field,
            "message": self.message,
        }


@dataclass(frozen=True)
class PreprocessingResidueQCReport:
    """Result of residue QC for explicit preprocessing residue names."""

    residue_library_validation: PreprocessingResidueLibraryValidationReport
    qc_report: ResidueQCReport | None
    residue_names: tuple[str, ...]
    checked_residue_names: tuple[str, ...]
    skipped_residue_names: tuple[str, ...]
    issues: tuple[PreprocessingResidueQCIssue, ...]

    @property
    def passed(self) -> bool:
        """Return whether validation and residue QC both passed."""
        return (
            self.residue_library_validation.passed
            and self.qc_report is not None
            and not self.issues
            and not self.qc_report.has_errors()
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable preprocessing residue QC report."""
        return {
            "passed": self.passed,
            "residue_library_validation": (
                self.residue_library_validation.to_dict()
            ),
            "qc_report": (
                _serialize_qc_report(self.qc_report)
                if self.qc_report is not None
                else None
            ),
            "residue_names": list(self.residue_names),
            "checked_residue_names": list(self.checked_residue_names),
            "skipped_residue_names": list(self.skipped_residue_names),
            "issues": [issue.to_dict() for issue in self.issues],
        }


def run_residue_qc_from_manifest_options(
    options: ResidueLibraryInputConfig,
    residue_names: Iterable[str],
    *,
    base_dir: str | Path | None = None,
) -> PreprocessingResidueQCReport:
    """Run existing residue-library QC for explicit residue names."""
    validation = validate_residue_library_from_manifest_options(
        options,
        base_dir=base_dir,
    )
    if not validation.passed:
        return _report_with_issue(
            validation=validation,
            issue=PreprocessingResidueQCIssue(
                kind="residue_library_validation_failed",
                field="residue_library",
                message="Residue-library validation failed",
            ),
        )

    normalized_names, normalization_issue = _normalize_residue_names(
        residue_names
    )
    if normalization_issue is not None:
        return _report_with_issue(
            validation=validation,
            issue=normalization_issue,
        )

    resolved_options = validation.resolved_options
    if resolved_options is None:
        raise RuntimeError("Passed residue-library validation has no resolved options")
    skip_resnames = set(resolved_options.skip_resnames)
    checked_names = tuple(
        name
        for name in normalized_names
        if normalize_resname(name) not in skip_resnames
    )
    skipped_names = tuple(
        name
        for name in normalized_names
        if normalize_resname(name) in skip_resnames
    )
    if not checked_names:
        return _report_with_issue(
            validation=validation,
            issue=PreprocessingResidueQCIssue(
                kind="empty_residue_names",
                field="residue_names",
                message="No residue names remain available for QC",
            ),
            residue_names=normalized_names,
            checked_residue_names=checked_names,
            skipped_residue_names=skipped_names,
        )

    library = load_residue_library_from_manifest_options(
        options,
        base_dir=base_dir,
    )
    try:
        qc_report = run_residue_library_qc(
            {EXPLICIT_RESIDUE_NAMES_CONDITION: checked_names},
            library,
            skip_resnames=(),
            fail_on_error=False,
        )
    except ResidueLibraryQCError as exc:
        return _report_with_issue(
            validation=validation,
            issue=PreprocessingResidueQCIssue(
                kind="qc_error",
                field="residue_qc",
                message=f"Residue QC failed: {exc}",
            ),
            residue_names=normalized_names,
            checked_residue_names=checked_names,
            skipped_residue_names=skipped_names,
        )

    return PreprocessingResidueQCReport(
        residue_library_validation=validation,
        qc_report=qc_report,
        residue_names=normalized_names,
        checked_residue_names=checked_names,
        skipped_residue_names=skipped_names,
        issues=(),
    )


def _normalize_residue_names(
    residue_names: Iterable[str],
) -> tuple[tuple[str, ...], PreprocessingResidueQCIssue | None]:
    if isinstance(residue_names, str):
        return (), _invalid_residue_name_issue(
            "residue_names must be an iterable of strings, not a plain string"
        )

    normalized_names: list[str] = []
    for residue_name in residue_names:
        if not isinstance(residue_name, str):
            return (), _invalid_residue_name_issue(
                "residue_names entries must be strings"
            )
        normalized = residue_name.strip()
        if not normalized:
            return (), _invalid_residue_name_issue(
                "residue_names entries must not be empty"
            )
        normalized_names.append(normalized)

    if not normalized_names:
        return (), PreprocessingResidueQCIssue(
            kind="empty_residue_names",
            field="residue_names",
            message="No residue names were provided for QC",
        )
    return tuple(normalized_names), None


def _invalid_residue_name_issue(message: str) -> PreprocessingResidueQCIssue:
    return PreprocessingResidueQCIssue(
        kind="invalid_residue_name",
        field="residue_names",
        message=message,
    )


def _report_with_issue(
    *,
    validation: PreprocessingResidueLibraryValidationReport,
    issue: PreprocessingResidueQCIssue,
    residue_names: tuple[str, ...] = (),
    checked_residue_names: tuple[str, ...] = (),
    skipped_residue_names: tuple[str, ...] = (),
) -> PreprocessingResidueQCReport:
    return PreprocessingResidueQCReport(
        residue_library_validation=validation,
        qc_report=None,
        residue_names=residue_names,
        checked_residue_names=checked_residue_names,
        skipped_residue_names=skipped_residue_names,
        issues=(issue,),
    )


def _serialize_qc_report(report: ResidueQCReport) -> dict[str, object]:
    return {
        "passed": not report.has_errors(),
        "has_errors": report.has_errors(),
        "unknown_resnames": list(report.unknown_resnames()),
        "status_counts": dict(report.status_counts()),
        "rows": [
            {
                "resname": row.resname,
                "status": row.status,
                "coverage": row.coverage,
                "block_type": row.block_type,
                "source_file": row.source_file,
                "conditions": list(row.conditions),
            }
            for row in report.rows
        ],
    }


__all__ = [
    "PreprocessingResidueQCIssue",
    "PreprocessingResidueQCReport",
    "run_residue_qc_from_manifest_options",
]
