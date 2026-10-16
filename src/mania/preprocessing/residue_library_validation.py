"""Local residue-library validation for preprocessing manifest options."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from mania.preprocessing.input_manifest import ResidueLibraryInputConfig
from mania.preprocessing.residue_library_bridge import (
    PreprocessingResidueLibraryBridgeError,
    ResolvedResidueLibraryManifestOptions,
    resolve_residue_library_manifest_paths,
)
from mania.residue_library import (
    ResidueLibraryError,
    extend_residue_library,
    load_residue_library,
)

LIBRARY_PATH_FIELD = "residue_library.library_path"
CUSTOM_RESIDUES_PATH_FIELD = "residue_library.custom_residues_path"


@dataclass(frozen=True)
class PreprocessingResidueLibraryValidationIssue:
    """One local residue-library validation problem."""

    kind: Literal[
        "missing_library_path",
        "missing_file",
        "not_file",
        "load_error",
        "custom_load_error",
        "extension_error",
    ]
    field: str
    path: Path | None = None
    resolved_path: Path | None = None
    message: str = ""

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable validation issue."""
        return {
            "kind": self.kind,
            "field": self.field,
            "path": str(self.path) if self.path is not None else None,
            "resolved_path": (
                str(self.resolved_path)
                if self.resolved_path is not None
                else None
            ),
            "message": self.message,
        }


@dataclass(frozen=True)
class PreprocessingResidueLibraryValidationReport:
    """Result of local residue-library file validation."""

    resolved_options: ResolvedResidueLibraryManifestOptions | None
    issues: tuple[PreprocessingResidueLibraryValidationIssue, ...]
    library_loaded: bool
    custom_residues_applied: bool
    residue_count: int | None = None

    @property
    def passed(self) -> bool:
        """Return whether loading and any requested extension succeeded."""
        custom_path = (
            self.resolved_options.custom_residues_path
            if self.resolved_options is not None
            else None
        )
        return (
            not self.issues
            and self.library_loaded
            and (custom_path is None or self.custom_residues_applied)
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable validation report."""
        return {
            "passed": self.passed,
            "resolved_options": (
                self.resolved_options.to_dict()
                if self.resolved_options is not None
                else None
            ),
            "issues": [issue.to_dict() for issue in self.issues],
            "library_loaded": self.library_loaded,
            "custom_residues_applied": self.custom_residues_applied,
            "residue_count": self.residue_count,
        }


def validate_residue_library_from_manifest_options(
    options: ResidueLibraryInputConfig,
    *,
    base_dir: str | Path | None = None,
) -> PreprocessingResidueLibraryValidationReport:
    """Validate local residue-library files using existing library behavior."""
    try:
        resolved = resolve_residue_library_manifest_paths(
            options,
            base_dir=base_dir,
        )
    except PreprocessingResidueLibraryBridgeError:
        return _report_with_issue(
            resolved_options=None,
            issue=PreprocessingResidueLibraryValidationIssue(
                kind="missing_library_path",
                field=LIBRARY_PATH_FIELD,
                message=f"{LIBRARY_PATH_FIELD} is required for validation",
            ),
        )

    source_path_issue = _check_file(
        field=LIBRARY_PATH_FIELD,
        path=options.library_path,
        resolved_path=resolved.library_path,
    )
    if source_path_issue is not None:
        return _report_with_issue(
            resolved_options=resolved,
            issue=source_path_issue,
        )

    try:
        library = load_residue_library(resolved.library_path)
    except (OSError, UnicodeError, ResidueLibraryError) as exc:
        return _report_with_issue(
            resolved_options=resolved,
            issue=PreprocessingResidueLibraryValidationIssue(
                kind="load_error",
                field=LIBRARY_PATH_FIELD,
                path=options.library_path,
                resolved_path=resolved.library_path,
                message=f"Could not load source residue library: {exc}",
            ),
        )

    residue_count = len(library.residues)
    if resolved.custom_residues_path is None:
        return PreprocessingResidueLibraryValidationReport(
            resolved_options=resolved,
            issues=(),
            library_loaded=True,
            custom_residues_applied=False,
            residue_count=residue_count,
        )

    custom_path_issue = _check_file(
        field=CUSTOM_RESIDUES_PATH_FIELD,
        path=options.custom_residues_path,
        resolved_path=resolved.custom_residues_path,
    )
    if custom_path_issue is not None:
        return _report_with_issue(
            resolved_options=resolved,
            issue=custom_path_issue,
            library_loaded=True,
            residue_count=residue_count,
        )

    try:
        custom_library = load_residue_library(resolved.custom_residues_path)
    except (OSError, UnicodeError, ResidueLibraryError) as exc:
        return _report_with_issue(
            resolved_options=resolved,
            issue=PreprocessingResidueLibraryValidationIssue(
                kind="custom_load_error",
                field=CUSTOM_RESIDUES_PATH_FIELD,
                path=options.custom_residues_path,
                resolved_path=resolved.custom_residues_path,
                message=f"Could not load custom residue library: {exc}",
            ),
            library_loaded=True,
            residue_count=residue_count,
        )

    try:
        effective_library = extend_residue_library(
            library,
            custom_library.residues,
            allow_override_existing=resolved.allow_user_overrides,
        )
    except ResidueLibraryError as exc:
        return _report_with_issue(
            resolved_options=resolved,
            issue=PreprocessingResidueLibraryValidationIssue(
                kind="extension_error",
                field=CUSTOM_RESIDUES_PATH_FIELD,
                path=options.custom_residues_path,
                resolved_path=resolved.custom_residues_path,
                message=f"Could not apply custom residues: {exc}",
            ),
            library_loaded=True,
            residue_count=residue_count,
        )

    return PreprocessingResidueLibraryValidationReport(
        resolved_options=resolved,
        issues=(),
        library_loaded=True,
        custom_residues_applied=True,
        residue_count=len(effective_library.residues),
    )


def _check_file(
    *,
    field: str,
    path: Path | None,
    resolved_path: Path,
) -> PreprocessingResidueLibraryValidationIssue | None:
    if not resolved_path.exists():
        return PreprocessingResidueLibraryValidationIssue(
            kind="missing_file",
            field=field,
            path=path,
            resolved_path=resolved_path,
            message=f"Declared residue-library file does not exist: {resolved_path}",
        )
    if not resolved_path.is_file():
        return PreprocessingResidueLibraryValidationIssue(
            kind="not_file",
            field=field,
            path=path,
            resolved_path=resolved_path,
            message=f"Declared residue-library path is not a file: {resolved_path}",
        )
    return None


def _report_with_issue(
    *,
    resolved_options: ResolvedResidueLibraryManifestOptions | None,
    issue: PreprocessingResidueLibraryValidationIssue,
    library_loaded: bool = False,
    residue_count: int | None = None,
) -> PreprocessingResidueLibraryValidationReport:
    return PreprocessingResidueLibraryValidationReport(
        resolved_options=resolved_options,
        issues=(issue,),
        library_loaded=library_loaded,
        custom_residues_applied=False,
        residue_count=residue_count,
    )


__all__ = [
    "PreprocessingResidueLibraryValidationIssue",
    "PreprocessingResidueLibraryValidationReport",
    "validate_residue_library_from_manifest_options",
]
