"""Residue-name reports for loaded preprocessing runtimes."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, TypeAlias, cast

from mania.preprocessing import trajectory_manifest_loader, trajectory_runtime

PreprocessingConditionLoadResult: TypeAlias = (
    trajectory_runtime.PreprocessingConditionLoadResult
)
PreprocessingManifestLoadResult: TypeAlias = (
    trajectory_manifest_loader.PreprocessingManifestLoadResult
)


class _RuntimeResidues(Protocol):
    resnames: Iterable[object]


class _RuntimeObject(Protocol):
    residues: _RuntimeResidues


@dataclass(frozen=True)
class PreprocessingResidueNameExtractionIssue:
    """One deterministic residue-name extraction issue."""

    kind: Literal[
        "condition_not_loaded",
        "runtime_missing",
        "residues_missing",
        "residue_names_missing",
        "residue_name_error",
        "invalid_residue_name",
        "manifest_load_issue",
    ]
    condition_name: str | None
    field: str
    message: str

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable issue dictionary."""
        return {
            "kind": self.kind,
            "condition_name": self.condition_name,
            "field": self.field,
            "message": self.message,
        }


@dataclass(frozen=True)
class PreprocessingConditionResidueNames:
    """Ordered residue names extracted for one loaded condition."""

    condition_name: str
    status: str
    passed: bool
    runtime_type: str | None
    topology_path: Path | None
    trajectory_paths: tuple[Path, ...]
    residue_names: tuple[str, ...]
    unique_residue_names: tuple[str, ...]
    residue_count: int | None
    unique_residue_count: int | None
    issues: tuple[PreprocessingResidueNameExtractionIssue, ...]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable residue-name report."""
        path_items = vars(self)["trajectory_paths"]
        return {
            "condition_name": self.condition_name,
            "status": self.status,
            "passed": self.passed,
            "runtime_type": self.runtime_type,
            "topology_path": (
                str(self.topology_path)
                if self.topology_path is not None
                else None
            ),
            "trajectory_paths": [str(path) for path in path_items],
            "residue_names": list(self.residue_names),
            "unique_residue_names": list(self.unique_residue_names),
            "residue_count": self.residue_count,
            "unique_residue_count": self.unique_residue_count,
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class PreprocessingManifestResidueNames:
    """Aggregate residue-name reports for manifest conditions."""

    condition_residue_names: tuple[PreprocessingConditionResidueNames, ...]
    issues: tuple[PreprocessingResidueNameExtractionIssue, ...] = ()

    @property
    def passed(self) -> bool:
        """Return whether every condition extraction passed."""
        return (
            bool(self.condition_residue_names)
            and self.issues == ()
            and all(item.passed for item in self.condition_residue_names)
        )

    @property
    def condition_names(self) -> tuple[str, ...]:
        """Return condition names in source result order."""
        return tuple(
            item.condition_name for item in self.condition_residue_names
        )

    @property
    def loaded_condition_names(self) -> tuple[str, ...]:
        """Return condition names whose extraction reports passed."""
        return tuple(
            item.condition_name
            for item in self.condition_residue_names
            if item.passed
        )

    @property
    def failed_condition_names(self) -> tuple[str, ...]:
        """Return condition names whose extraction reports failed."""
        return tuple(
            item.condition_name
            for item in self.condition_residue_names
            if not item.passed
        )

    @property
    def total_conditions(self) -> int:
        """Return the number of condition reports."""
        return len(self.condition_residue_names)

    @property
    def loaded_conditions(self) -> int:
        """Return the number of passing condition reports."""
        return len(self.loaded_condition_names)

    @property
    def failed_conditions(self) -> int:
        """Return the number of failing condition reports."""
        return len(self.failed_condition_names)

    @property
    def all_unique_residue_names(self) -> tuple[str, ...]:
        """Return first-seen residue names across all conditions."""
        unique_names: list[str] = []
        seen_names: set[str] = set()
        for item in self.condition_residue_names:
            for name in item.unique_residue_names:
                if name not in seen_names:
                    unique_names.append(name)
                    seen_names.add(name)
        return tuple(unique_names)

    def residue_names_for_condition(
        self,
        condition_name: str,
    ) -> PreprocessingConditionResidueNames | None:
        """Return one exact-name condition report."""
        for item in self.condition_residue_names:
            if item.condition_name == condition_name:
                return item
        return None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable aggregate report."""
        return {
            "passed": self.passed,
            "condition_residue_names": [
                item.to_dict() for item in self.condition_residue_names
            ],
            "issues": [issue.to_dict() for issue in self.issues],
            "condition_names": list(self.condition_names),
            "loaded_condition_names": list(self.loaded_condition_names),
            "failed_condition_names": list(self.failed_condition_names),
            "total_conditions": self.total_conditions,
            "loaded_conditions": self.loaded_conditions,
            "failed_conditions": self.failed_conditions,
            "all_unique_residue_names": list(self.all_unique_residue_names),
        }


def extract_condition_residue_names(
    result: PreprocessingConditionLoadResult,
) -> PreprocessingConditionResidueNames:
    """Extract ordered residue names from one existing load result."""
    runtime = result.runtime
    runtime_type = runtime.runtime_type if runtime is not None else None

    if result.status == "loaded" and runtime is None:
        return _failed_report(
            result,
            runtime_type=runtime_type,
            issue=PreprocessingResidueNameExtractionIssue(
                kind="runtime_missing",
                condition_name=result.condition_name,
                field="runtime",
                message="Condition load result has no runtime wrapper.",
            ),
        )

    if not result.passed:
        return _failed_report(
            result,
            runtime_type=runtime_type,
            issue=PreprocessingResidueNameExtractionIssue(
                kind="condition_not_loaded",
                condition_name=result.condition_name,
                field="status",
                message="Condition runtime is not loaded.",
            ),
        )

    if runtime is None:
        return _failed_report(
            result,
            runtime_type=None,
            issue=PreprocessingResidueNameExtractionIssue(
                kind="runtime_missing",
                condition_name=result.condition_name,
                field="runtime",
                message="Condition load result has no runtime wrapper.",
            ),
        )

    try:
        runtime_object = cast(_RuntimeObject, runtime.runtime_object)
        residues = runtime_object.residues
    except AttributeError:
        return _failed_report(
            result,
            runtime_type=runtime.runtime_type,
            issue=PreprocessingResidueNameExtractionIssue(
                kind="residues_missing",
                condition_name=result.condition_name,
                field="runtime_object.residues",
                message="Runtime object has no residues collection.",
            ),
        )
    except Exception:
        return _name_error_report(result, runtime.runtime_type)

    if residues is None:
        return _failed_report(
            result,
            runtime_type=runtime.runtime_type,
            issue=PreprocessingResidueNameExtractionIssue(
                kind="residues_missing",
                condition_name=result.condition_name,
                field="runtime_object.residues",
                message="Runtime object has no residues collection.",
            ),
        )

    try:
        raw_names = residues.resnames
    except AttributeError:
        return _failed_report(
            result,
            runtime_type=runtime.runtime_type,
            issue=PreprocessingResidueNameExtractionIssue(
                kind="residue_names_missing",
                condition_name=result.condition_name,
                field="runtime_object.residues.resnames",
                message="Runtime residues collection has no residue names.",
            ),
        )
    except Exception:
        return _name_error_report(result, runtime.runtime_type)

    if raw_names is None:
        return _failed_report(
            result,
            runtime_type=runtime.runtime_type,
            issue=PreprocessingResidueNameExtractionIssue(
                kind="residue_names_missing",
                condition_name=result.condition_name,
                field="runtime_object.residues.resnames",
                message="Runtime residues collection has no residue names.",
            ),
        )

    try:
        values = tuple(raw_names)
    except Exception:
        return _name_error_report(result, runtime.runtime_type)

    names: list[str] = []
    unique_names: list[str] = []
    seen_names: set[str] = set()
    issues: list[PreprocessingResidueNameExtractionIssue] = []
    for index, value in enumerate(values):
        if value is None:
            issues.append(_invalid_name_issue(result.condition_name, index))
            continue
        try:
            name = str(value).strip()
        except Exception:
            return _name_error_report(result, runtime.runtime_type)
        if name == "":
            issues.append(_invalid_name_issue(result.condition_name, index))
            continue
        names.append(name)
        if name not in seen_names:
            unique_names.append(name)
            seen_names.add(name)

    return _condition_report(
        result,
        runtime_type=runtime.runtime_type,
        residue_names=tuple(names),
        unique_residue_names=tuple(unique_names),
        residue_count=len(names),
        unique_residue_count=len(unique_names),
        issues=tuple(issues),
    )


def extract_manifest_residue_names(
    result: PreprocessingManifestLoadResult,
) -> PreprocessingManifestResidueNames:
    """Extract residue names from every condition result in order."""
    condition_reports = tuple(
        extract_condition_residue_names(condition_result)
        for condition_result in result.condition_results
    )
    issues = tuple(
        PreprocessingResidueNameExtractionIssue(
            kind="manifest_load_issue",
            condition_name=issue.condition_name,
            field=issue.field,
            message=issue.message,
        )
        for issue in result.issues
    )
    return PreprocessingManifestResidueNames(
        condition_residue_names=condition_reports,
        issues=issues,
    )


def _condition_report(
    result: PreprocessingConditionLoadResult,
    *,
    runtime_type: str | None,
    residue_names: tuple[str, ...],
    unique_residue_names: tuple[str, ...],
    residue_count: int | None,
    unique_residue_count: int | None,
    issues: tuple[PreprocessingResidueNameExtractionIssue, ...],
) -> PreprocessingConditionResidueNames:
    runtime_input = result.runtime_input
    path_items = vars(runtime_input)["trajectory_paths"]
    return PreprocessingConditionResidueNames(
        condition_name=result.condition_name,
        status=result.status,
        passed=result.passed and result.runtime is not None and not issues,
        runtime_type=runtime_type,
        topology_path=runtime_input.topology_path,
        trajectory_paths=path_items,
        residue_names=residue_names,
        unique_residue_names=unique_residue_names,
        residue_count=residue_count,
        unique_residue_count=unique_residue_count,
        issues=issues,
    )


def _failed_report(
    result: PreprocessingConditionLoadResult,
    *,
    runtime_type: str | None,
    issue: PreprocessingResidueNameExtractionIssue,
) -> PreprocessingConditionResidueNames:
    return _condition_report(
        result,
        runtime_type=runtime_type,
        residue_names=(),
        unique_residue_names=(),
        residue_count=None,
        unique_residue_count=None,
        issues=(issue,),
    )


def _name_error_report(
    result: PreprocessingConditionLoadResult,
    runtime_type: str,
) -> PreprocessingConditionResidueNames:
    return _failed_report(
        result,
        runtime_type=runtime_type,
        issue=PreprocessingResidueNameExtractionIssue(
            kind="residue_name_error",
            condition_name=result.condition_name,
            field="runtime_object.residues.resnames",
            message="Residue names could not be extracted.",
        ),
    )


def _invalid_name_issue(
    condition_name: str,
    index: int,
) -> PreprocessingResidueNameExtractionIssue:
    return PreprocessingResidueNameExtractionIssue(
        kind="invalid_residue_name",
        condition_name=condition_name,
        field=f"runtime_object.residues.resnames[{index}]",
        message="Residue name is empty or invalid.",
    )


__all__ = [
    "PreprocessingConditionResidueNames",
    "PreprocessingManifestResidueNames",
    "PreprocessingResidueNameExtractionIssue",
    "extract_condition_residue_names",
    "extract_manifest_residue_names",
]
