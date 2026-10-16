"""Lightweight metadata reports for loaded preprocessing runtimes."""

from __future__ import annotations

import operator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from mania.preprocessing.trajectory_manifest_loader import (
    PreprocessingManifestLoadResult,
)
from mania.preprocessing.trajectory_runtime import (
    PreprocessingConditionLoadResult,
)


@dataclass(frozen=True)
class PreprocessingRuntimeMetadataIssue:
    """One deterministic runtime metadata collection issue."""

    kind: Literal[
        "condition_not_loaded",
        "runtime_missing",
        "runtime_attribute_error",
        "unsupported_runtime",
        "metadata_error",
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
class PreprocessingConditionRuntimeMetadata:
    """Safe metadata collected for one condition runtime result."""

    condition_name: str
    status: str
    passed: bool
    runtime_type: str | None
    topology_path: Path | None
    trajectory_paths: tuple[Path, ...]
    reference_structure_path: Path | None
    frame_time_ps: float | None
    atom_count: int | None
    residue_count: int | None
    segment_count: int | None
    frame_count: int | None
    trajectory_count: int
    issues: tuple[PreprocessingRuntimeMetadataIssue, ...]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable metadata dictionary."""
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
            "trajectory_paths": [
                str(path) for path in self.trajectory_paths
            ],
            "reference_structure_path": (
                str(self.reference_structure_path)
                if self.reference_structure_path is not None
                else None
            ),
            "frame_time_ps": self.frame_time_ps,
            "atom_count": self.atom_count,
            "residue_count": self.residue_count,
            "segment_count": self.segment_count,
            "frame_count": self.frame_count,
            "trajectory_count": self.trajectory_count,
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class PreprocessingManifestRuntimeMetadata:
    """Aggregate metadata for manifest condition load results."""

    condition_metadata: tuple[PreprocessingConditionRuntimeMetadata, ...]
    issues: tuple[PreprocessingRuntimeMetadataIssue, ...] = ()

    @property
    def passed(self) -> bool:
        """Return whether every condition metadata report passed."""
        return (
            bool(self.condition_metadata)
            and self.issues == ()
            and all(item.passed for item in self.condition_metadata)
        )

    @property
    def condition_names(self) -> tuple[str, ...]:
        """Return all condition names in source result order."""
        return tuple(item.condition_name for item in self.condition_metadata)

    @property
    def loaded_condition_names(self) -> tuple[str, ...]:
        """Return condition names whose metadata reports passed."""
        return tuple(
            item.condition_name
            for item in self.condition_metadata
            if item.passed
        )

    @property
    def failed_condition_names(self) -> tuple[str, ...]:
        """Return condition names whose metadata reports failed."""
        return tuple(
            item.condition_name
            for item in self.condition_metadata
            if not item.passed
        )

    @property
    def total_conditions(self) -> int:
        """Return the number of condition metadata entries."""
        return len(self.condition_metadata)

    @property
    def loaded_conditions(self) -> int:
        """Return the number of passing condition metadata entries."""
        return len(self.loaded_condition_names)

    @property
    def failed_conditions(self) -> int:
        """Return the number of failing condition metadata entries."""
        return len(self.failed_condition_names)

    def metadata_for_condition(
        self,
        condition_name: str,
    ) -> PreprocessingConditionRuntimeMetadata | None:
        """Return one exact-name condition metadata entry."""
        for item in self.condition_metadata:
            if item.condition_name == condition_name:
                return item
        return None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable aggregate metadata dictionary."""
        return {
            "passed": self.passed,
            "condition_metadata": [
                item.to_dict() for item in self.condition_metadata
            ],
            "issues": [issue.to_dict() for issue in self.issues],
            "condition_names": list(self.condition_names),
            "loaded_condition_names": list(self.loaded_condition_names),
            "failed_condition_names": list(self.failed_condition_names),
            "total_conditions": self.total_conditions,
            "loaded_conditions": self.loaded_conditions,
            "failed_conditions": self.failed_conditions,
        }


def collect_condition_runtime_metadata(
    result: PreprocessingConditionLoadResult,
) -> PreprocessingConditionRuntimeMetadata:
    """Collect safe metadata from one existing condition load result."""
    runtime = result.runtime
    runtime_type = runtime.runtime_type if runtime is not None else None

    if result.status == "loaded" and runtime is None:
        issue = PreprocessingRuntimeMetadataIssue(
            kind="runtime_missing",
            condition_name=result.condition_name,
            field="runtime",
            message="Loaded condition result has no runtime wrapper.",
        )
        return _condition_metadata(
            result,
            runtime_type=runtime_type,
            issues=(issue,),
        )

    if not result.passed:
        issue = PreprocessingRuntimeMetadataIssue(
            kind="condition_not_loaded",
            condition_name=result.condition_name,
            field="status",
            message="Condition runtime is not loaded.",
        )
        return _condition_metadata(
            result,
            runtime_type=runtime_type,
            issues=(issue,),
        )

    if runtime is None:
        issue = PreprocessingRuntimeMetadataIssue(
            kind="runtime_missing",
            condition_name=result.condition_name,
            field="runtime",
            message="Condition runtime wrapper is unavailable.",
        )
        return _condition_metadata(
            result,
            runtime_type=None,
            issues=(issue,),
        )

    count_specs = (
        ("atom_count", "atoms", "n_atoms"),
        ("residue_count", "residues", "n_residues"),
        ("segment_count", "segments", "n_segments"),
        ("frame_count", "trajectory", "n_frames"),
    )
    counts: dict[str, int | None] = {}
    issues: list[PreprocessingRuntimeMetadataIssue] = []
    missing_fields: list[str] = []

    for field, collection_name, count_name in count_specs:
        count, state = _safe_count(
            runtime.runtime_object,
            collection_name,
            count_name,
        )
        counts[field] = count
        if state == "missing":
            missing_fields.append(field)
        elif state == "error":
            issues.append(
                _attribute_issue(result.condition_name, field)
            )

    if len(missing_fields) == len(count_specs) and not issues:
        issues.append(
            PreprocessingRuntimeMetadataIssue(
                kind="unsupported_runtime",
                condition_name=result.condition_name,
                field="runtime",
                message="Runtime exposes no supported count metadata.",
            )
        )
    else:
        issues.extend(
            _attribute_issue(result.condition_name, field)
            for field in missing_fields
        )

    return _condition_metadata(
        result,
        runtime_type=runtime.runtime_type,
        atom_count=counts["atom_count"],
        residue_count=counts["residue_count"],
        segment_count=counts["segment_count"],
        frame_count=counts["frame_count"],
        issues=tuple(issues),
    )


def collect_manifest_runtime_metadata(
    result: PreprocessingManifestLoadResult,
) -> PreprocessingManifestRuntimeMetadata:
    """Collect condition metadata and preserve manifest-level issues."""
    condition_metadata = tuple(
        collect_condition_runtime_metadata(condition_result)
        for condition_result in result.condition_results
    )
    issues = tuple(
        PreprocessingRuntimeMetadataIssue(
            kind="manifest_load_issue",
            condition_name=issue.condition_name,
            field=issue.field,
            message=issue.message,
        )
        for issue in result.issues
    )
    return PreprocessingManifestRuntimeMetadata(
        condition_metadata=condition_metadata,
        issues=issues,
    )


def _condition_metadata(
    result: PreprocessingConditionLoadResult,
    *,
    runtime_type: str | None,
    atom_count: int | None = None,
    residue_count: int | None = None,
    segment_count: int | None = None,
    frame_count: int | None = None,
    issues: tuple[PreprocessingRuntimeMetadataIssue, ...],
) -> PreprocessingConditionRuntimeMetadata:
    runtime_input = result.runtime_input
    return PreprocessingConditionRuntimeMetadata(
        condition_name=result.condition_name,
        status=result.status,
        passed=result.passed and result.runtime is not None and not issues,
        runtime_type=runtime_type,
        topology_path=runtime_input.topology_path,
        trajectory_paths=runtime_input.trajectory_paths,
        reference_structure_path=runtime_input.reference_structure_path,
        frame_time_ps=runtime_input.frame_time_ps,
        atom_count=atom_count,
        residue_count=residue_count,
        segment_count=segment_count,
        frame_count=frame_count,
        trajectory_count=len(runtime_input.trajectory_paths),
        issues=issues,
    )


def _safe_count(
    runtime_object: object,
    collection_name: str,
    count_name: str,
) -> tuple[int | None, Literal["collected", "missing", "error"]]:
    try:
        collection = getattr(runtime_object, collection_name)
    except AttributeError:
        return None, "missing"
    except Exception:
        return None, "error"

    try:
        value = getattr(collection, count_name)
    except AttributeError:
        try:
            value = len(collection)
        except TypeError:
            return None, "missing"
        except Exception:
            return None, "error"
    except Exception:
        return None, "error"

    try:
        count = operator.index(value)
    except (TypeError, ValueError):
        return None, "error"
    if count < 0:
        return None, "error"
    return count, "collected"


def _attribute_issue(
    condition_name: str,
    field: str,
) -> PreprocessingRuntimeMetadataIssue:
    return PreprocessingRuntimeMetadataIssue(
        kind="runtime_attribute_error",
        condition_name=condition_name,
        field=field,
        message=f"Runtime count metadata is unavailable for {field}.",
    )


__all__ = [
    "PreprocessingConditionRuntimeMetadata",
    "PreprocessingManifestRuntimeMetadata",
    "PreprocessingRuntimeMetadataIssue",
    "collect_condition_runtime_metadata",
    "collect_manifest_runtime_metadata",
]
