"""Value models for future preprocessing trajectory runtime loading."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from mania.preprocessing.input_manifest import TrajectoryInputConfig


@dataclass(frozen=True)
class PreprocessingTrajectoryLoadIssue:
    """One deterministic future trajectory loading issue."""

    kind: Literal[
        "missing_optional_dependency",
        "missing_topology_path",
        "missing_trajectory_path",
        "topology_not_file",
        "trajectory_not_file",
        "load_error",
        "metadata_error",
        "not_loaded",
    ]
    field: str
    message: str
    path: Path | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable load issue."""
        return {
            "kind": self.kind,
            "field": self.field,
            "message": self.message,
            "path": str(self.path) if self.path is not None else None,
        }


@dataclass(frozen=True)
class PreprocessingConditionRuntimeInput:
    """Paths and optional frame timing for one future condition load."""

    condition_name: str
    topology_path: Path
    trajectory_paths: tuple[Path, ...]
    reference_structure_path: Path | None = None
    frame_time_ps: float | None = None

    @classmethod
    def from_manifest_condition(
        cls,
        condition_name: str,
        condition: TrajectoryInputConfig,
        *,
        base_dir: str | Path | None = None,
    ) -> PreprocessingConditionRuntimeInput:
        """Build runtime input using only an explicitly provided path base."""
        path_base = Path(base_dir) if base_dir is not None else None
        return cls(
            condition_name=condition_name,
            topology_path=_resolve_path(condition.topology_path, path_base),
            trajectory_paths=tuple(
                _resolve_path(path, path_base)
                for path in condition.trajectory_paths
            ),
            reference_structure_path=(
                _resolve_path(condition.reference_structure_path, path_base)
                if condition.reference_structure_path is not None
                else None
            ),
        )

    def to_dict(self) -> dict[str, object]:
        """Return JSON-serializable future runtime inputs."""
        return {
            "condition_name": self.condition_name,
            "topology_path": str(self.topology_path),
            "trajectory_paths": [str(path) for path in self.trajectory_paths],
            "reference_structure_path": (
                str(self.reference_structure_path)
                if self.reference_structure_path is not None
                else None
            ),
            "frame_time_ps": self.frame_time_ps,
        }


@dataclass(frozen=True)
class PreprocessingConditionRuntime:
    """Wrapper for one future condition runtime object."""

    condition_name: str
    runtime_object: object
    runtime_type: str
    topology_path: Path
    trajectory_paths: tuple[Path, ...]

    def to_dict(self) -> dict[str, object]:
        """Return runtime metadata without serializing the runtime object."""
        return {
            "condition_name": self.condition_name,
            "runtime_type": self.runtime_type,
            "topology_path": str(self.topology_path),
            "trajectory_paths": [str(path) for path in self.trajectory_paths],
            "has_runtime_object": True,
        }


@dataclass(frozen=True)
class PreprocessingConditionLoadResult:
    """Result shape for one future condition runtime load."""

    condition_name: str
    runtime_input: PreprocessingConditionRuntimeInput
    runtime: PreprocessingConditionRuntime | None = None
    issues: tuple[PreprocessingTrajectoryLoadIssue, ...] = ()
    status: Literal["not_loaded", "loaded", "failed"] = "not_loaded"

    @property
    def passed(self) -> bool:
        """Return whether loading succeeded without reported issues."""
        return (
            self.status == "loaded"
            and self.runtime is not None
            and self.issues == ()
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable condition load result."""
        return {
            "condition_name": self.condition_name,
            "status": self.status,
            "passed": self.passed,
            "runtime_input": self.runtime_input.to_dict(),
            "issues": [issue.to_dict() for issue in self.issues],
            "runtime": (
                self.runtime.to_dict() if self.runtime is not None else None
            ),
        }


def _resolve_path(path: Path, base_dir: Path | None) -> Path:
    if path.is_absolute() or base_dir is None:
        return path
    return base_dir / path


__all__ = [
    "PreprocessingConditionLoadResult",
    "PreprocessingConditionRuntime",
    "PreprocessingConditionRuntimeInput",
    "PreprocessingTrajectoryLoadIssue",
]
