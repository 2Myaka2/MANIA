"""Optional local path validation for preprocessing input manifests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from mania.preprocessing.input_manifest import PreprocessingInputManifest


@dataclass(frozen=True)
class PreprocessingCheckedPath:
    """One declared manifest path checked against the local filesystem."""

    field: str
    path: Path
    resolved_path: Path
    condition: str | None = None
    required_type: Literal["file", "directory"] = "file"


@dataclass(frozen=True)
class PreprocessingPathValidationIssue:
    """One missing or incorrectly typed local manifest path."""

    kind: Literal["missing", "not_file", "not_directory"]
    field: str
    path: Path
    resolved_path: Path
    condition: str | None = None
    message: str = ""


@dataclass(frozen=True)
class PreprocessingPathValidationReport:
    """Result of explicit local preprocessing path checks."""

    checked_paths: tuple[PreprocessingCheckedPath, ...]
    issues: tuple[PreprocessingPathValidationIssue, ...]

    @property
    def passed(self) -> bool:
        """Return whether every checked path passed validation."""
        return len(self.issues) == 0

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable validation report dictionary."""
        return {
            "passed": self.passed,
            "checked_paths": [
                {
                    "field": checked.field,
                    "path": str(checked.path),
                    "resolved_path": str(checked.resolved_path),
                    "condition": checked.condition,
                    "required_type": checked.required_type,
                }
                for checked in self.checked_paths
            ],
            "issues": [
                {
                    "kind": issue.kind,
                    "field": issue.field,
                    "path": str(issue.path),
                    "resolved_path": str(issue.resolved_path),
                    "condition": issue.condition,
                    "message": issue.message,
                }
                for issue in self.issues
            ],
        }


def validate_preprocessing_manifest_paths(
    manifest: PreprocessingInputManifest,
    *,
    base_dir: str | Path | None = None,
    check_output_root: bool = False,
) -> PreprocessingPathValidationReport:
    """Check declared manifest paths against local filesystem metadata."""
    checked_paths: list[PreprocessingCheckedPath] = []
    issues: list[PreprocessingPathValidationIssue] = []
    path_base = Path(base_dir) if base_dir is not None else None

    for condition_config in manifest.conditions:
        condition = condition_config.condition
        _check_file_path(
            field=f"conditions[{condition}].topology_path",
            path=condition_config.topology_path,
            condition=condition,
            base_dir=path_base,
            checked_paths=checked_paths,
            issues=issues,
        )
        for index, trajectory_path in enumerate(
            condition_config.trajectory_paths
        ):
            _check_file_path(
                field=f"conditions[{condition}].trajectory_paths[{index}]",
                path=trajectory_path,
                condition=condition,
                base_dir=path_base,
                checked_paths=checked_paths,
                issues=issues,
            )
        if condition_config.reference_structure_path is not None:
            _check_file_path(
                field=f"conditions[{condition}].reference_structure_path",
                path=condition_config.reference_structure_path,
                condition=condition,
                base_dir=path_base,
                checked_paths=checked_paths,
                issues=issues,
            )

    residue_library = manifest.residue_library
    if residue_library.library_path is not None:
        _check_file_path(
            field="residue_library.library_path",
            path=residue_library.library_path,
            condition=None,
            base_dir=path_base,
            checked_paths=checked_paths,
            issues=issues,
        )
    if residue_library.custom_residues_path is not None:
        _check_file_path(
            field="residue_library.custom_residues_path",
            path=residue_library.custom_residues_path,
            condition=None,
            base_dir=path_base,
            checked_paths=checked_paths,
            issues=issues,
        )

    if check_output_root:
        _check_directory_path(
            field="output_root",
            path=manifest.output_root,
            base_dir=path_base,
            checked_paths=checked_paths,
            issues=issues,
        )

    return PreprocessingPathValidationReport(
        checked_paths=tuple(checked_paths),
        issues=tuple(issues),
    )


def _check_file_path(
    *,
    field: str,
    path: Path,
    condition: str | None,
    base_dir: Path | None,
    checked_paths: list[PreprocessingCheckedPath],
    issues: list[PreprocessingPathValidationIssue],
) -> None:
    resolved_path = _resolve_path(path, base_dir)
    checked_paths.append(
        PreprocessingCheckedPath(
            field=field,
            path=path,
            resolved_path=resolved_path,
            condition=condition,
        )
    )
    if not resolved_path.exists():
        issues.append(
            PreprocessingPathValidationIssue(
                kind="missing",
                field=field,
                path=path,
                resolved_path=resolved_path,
                condition=condition,
                message=f"Declared file path does not exist: {resolved_path}",
            )
        )
    elif not resolved_path.is_file():
        issues.append(
            PreprocessingPathValidationIssue(
                kind="not_file",
                field=field,
                path=path,
                resolved_path=resolved_path,
                condition=condition,
                message=f"Declared path is not a file: {resolved_path}",
            )
        )


def _check_directory_path(
    *,
    field: str,
    path: Path,
    base_dir: Path | None,
    checked_paths: list[PreprocessingCheckedPath],
    issues: list[PreprocessingPathValidationIssue],
) -> None:
    resolved_path = _resolve_path(path, base_dir)
    checked_paths.append(
        PreprocessingCheckedPath(
            field=field,
            path=path,
            resolved_path=resolved_path,
            required_type="directory",
        )
    )
    if not resolved_path.exists():
        issues.append(
            PreprocessingPathValidationIssue(
                kind="missing",
                field=field,
                path=path,
                resolved_path=resolved_path,
                message=f"Declared directory path does not exist: {resolved_path}",
            )
        )
    elif not resolved_path.is_dir():
        issues.append(
            PreprocessingPathValidationIssue(
                kind="not_directory",
                field=field,
                path=path,
                resolved_path=resolved_path,
                message=f"Declared path is not a directory: {resolved_path}",
            )
        )


def _resolve_path(path: Path, base_dir: Path | None) -> Path:
    if path.is_absolute() or base_dir is None:
        return path
    return base_dir / path


__all__ = [
    "PreprocessingCheckedPath",
    "PreprocessingPathValidationIssue",
    "PreprocessingPathValidationReport",
    "validate_preprocessing_manifest_paths",
]
