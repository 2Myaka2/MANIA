"""Optional sanity checks for local preprocessing reference packages."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from mania.preprocessing.input_manifest import (
    load_preprocessing_input_manifest,
)
from mania.preprocessing.path_validation import (
    PreprocessingPathValidationReport,
    validate_preprocessing_manifest_paths,
)


@dataclass(frozen=True)
class PreprocessingReferencePackageIssue:
    """One package-level local reference check failure."""

    kind: Literal[
        "missing_root",
        "not_directory",
        "missing_manifest",
        "manifest_not_file",
        "manifest_load_error",
    ]
    field: str
    path: Path
    message: str


@dataclass(frozen=True)
class PreprocessingReferencePackageReport:
    """Result of an explicit local reference package sanity check."""

    package_root: Path
    manifest_name: str
    manifest_path: Path
    manifest_loaded: bool
    issues: tuple[PreprocessingReferencePackageIssue, ...]
    path_validation: PreprocessingPathValidationReport | None = None

    @property
    def passed(self) -> bool:
        """Return whether package and declared path checks passed."""
        return (
            not self.issues
            and self.path_validation is not None
            and self.path_validation.passed
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable package report dictionary."""
        return {
            "passed": self.passed,
            "package_root": str(self.package_root),
            "manifest_name": self.manifest_name,
            "manifest_path": str(self.manifest_path),
            "manifest_loaded": self.manifest_loaded,
            "issues": [
                {
                    "kind": issue.kind,
                    "field": issue.field,
                    "path": str(issue.path),
                    "message": issue.message,
                }
                for issue in self.issues
            ],
            "path_validation": (
                self.path_validation.to_dict()
                if self.path_validation is not None
                else None
            ),
        }


def check_preprocessing_reference_package(
    package_root: str | Path,
    *,
    manifest_name: str = "preprocessing_manifest.yaml",
    check_output_root: bool = False,
) -> PreprocessingReferencePackageReport:
    """Check a local directory package and its declared manifest paths."""
    root_path = Path(package_root)
    manifest_path = root_path / manifest_name

    if not root_path.exists():
        return _package_issue_report(
            package_root=root_path,
            manifest_name=manifest_name,
            manifest_path=manifest_path,
            issue=PreprocessingReferencePackageIssue(
                kind="missing_root",
                field="package_root",
                path=root_path,
                message=f"Package root does not exist: {root_path}",
            ),
        )
    if not root_path.is_dir():
        return _package_issue_report(
            package_root=root_path,
            manifest_name=manifest_name,
            manifest_path=manifest_path,
            issue=PreprocessingReferencePackageIssue(
                kind="not_directory",
                field="package_root",
                path=root_path,
                message=f"Package root is not a directory: {root_path}",
            ),
        )
    if not manifest_path.exists():
        return _package_issue_report(
            package_root=root_path,
            manifest_name=manifest_name,
            manifest_path=manifest_path,
            issue=PreprocessingReferencePackageIssue(
                kind="missing_manifest",
                field="manifest_path",
                path=manifest_path,
                message=f"Package manifest does not exist: {manifest_path}",
            ),
        )
    if not manifest_path.is_file():
        return _package_issue_report(
            package_root=root_path,
            manifest_name=manifest_name,
            manifest_path=manifest_path,
            issue=PreprocessingReferencePackageIssue(
                kind="manifest_not_file",
                field="manifest_path",
                path=manifest_path,
                message=f"Package manifest is not a file: {manifest_path}",
            ),
        )

    try:
        manifest = load_preprocessing_input_manifest(manifest_path)
    except (ValueError, FileNotFoundError, IsADirectoryError, ValidationError) as exc:
        return _package_issue_report(
            package_root=root_path,
            manifest_name=manifest_name,
            manifest_path=manifest_path,
            issue=PreprocessingReferencePackageIssue(
                kind="manifest_load_error",
                field="manifest_path",
                path=manifest_path,
                message=f"Could not load package manifest: {exc}",
            ),
        )

    path_validation = validate_preprocessing_manifest_paths(
        manifest,
        base_dir=root_path,
        check_output_root=check_output_root,
    )
    return PreprocessingReferencePackageReport(
        package_root=root_path,
        manifest_name=manifest_name,
        manifest_path=manifest_path,
        manifest_loaded=True,
        issues=(),
        path_validation=path_validation,
    )


def _package_issue_report(
    *,
    package_root: Path,
    manifest_name: str,
    manifest_path: Path,
    issue: PreprocessingReferencePackageIssue,
) -> PreprocessingReferencePackageReport:
    return PreprocessingReferencePackageReport(
        package_root=package_root,
        manifest_name=manifest_name,
        manifest_path=manifest_path,
        manifest_loaded=False,
        issues=(issue,),
    )


__all__ = [
    "PreprocessingReferencePackageIssue",
    "PreprocessingReferencePackageReport",
    "check_preprocessing_reference_package",
]
