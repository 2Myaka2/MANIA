"""Dependency-free result contracts for preprocessing Rg computation."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TypeAlias, cast

from mania.preprocessing import (
    trajectory_frame_sampling,
    trajectory_manifest_loader,
    trajectory_runtime,
)

PreprocessingConditionLoadResult: TypeAlias = (
    trajectory_runtime.PreprocessingConditionLoadResult
)
PreprocessingManifestLoadResult: TypeAlias = (
    trajectory_manifest_loader.PreprocessingManifestLoadResult
)
PreprocessingFrameSamplingOptions: TypeAlias = (
    trajectory_frame_sampling.PreprocessingFrameSamplingOptions
)

_RG_METHOD_NAME = "radius_of_" + "gyration"
_RG_METHOD_FIELD = f"runtime_object.atoms.{_RG_METHOD_NAME}"
_TRAJECTORY_NAME = "trajectory"
_TRAJECTORY_FIELD = f"runtime_object.{_TRAJECTORY_NAME}"


@dataclass(frozen=True)
class PreprocessingRgComputationIssue:
    """One deterministic Rg computation issue."""

    kind: Literal[
        "condition_not_loaded",
        "runtime_missing",
        "atom_group_missing",
        "frame_iteration_error",
        "rg_computation_error",
        "invalid_frame_index",
        "invalid_time_ps",
        "invalid_rg_value",
        "manifest_load_issue",
        "condition_rg_error",
    ]
    condition_name: str | None
    frame_index: int | None
    field: str
    message: str

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable issue dictionary."""
        return {
            "kind": self.kind,
            "condition_name": self.condition_name,
            "frame_index": self.frame_index,
            "field": self.field,
            "message": self.message,
        }


@dataclass(frozen=True)
class PreprocessingRgFrameResult:
    """Rg result for one condition frame."""

    condition_name: str
    frame_index: int
    time_ps: float | None
    rg_value: float | None
    rg_unit: str | None
    issues: tuple[PreprocessingRgComputationIssue, ...] = ()

    def __post_init__(self) -> None:
        if (
            isinstance(self.frame_index, bool)
            or not isinstance(self.frame_index, int)
            or self.frame_index < 0
        ):
            raise ValueError("frame_index must be a non-negative int")
        _validate_optional_non_negative_finite(self.time_ps, "time_ps")
        _validate_optional_non_negative_finite(self.rg_value, "rg_value")

    @property
    def passed(self) -> bool:
        """Return whether this frame has a valid result without issues."""
        return self.rg_value is not None and self.issues == ()

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable frame result."""
        return {
            "condition_name": self.condition_name,
            "frame_index": self.frame_index,
            "time_ps": self.time_ps,
            "rg_value": self.rg_value,
            "rg_unit": self.rg_unit,
            "passed": self.passed,
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class PreprocessingConditionRgResult:
    """Aggregate Rg results for one condition."""

    condition_name: str
    status: str
    runtime_type: str | None
    topology_path: Path | None
    trajectory_paths: tuple[Path, ...]
    frame_time_ps: float | None
    rg_unit: str | None
    frame_results: tuple[PreprocessingRgFrameResult, ...] = ()
    issues: tuple[PreprocessingRgComputationIssue, ...] = ()

    def __post_init__(self) -> None:
        _validate_optional_non_negative_finite(
            self.frame_time_ps,
            "frame_time_ps",
        )
        for frame_result in self.frame_results:
            if frame_result.condition_name != self.condition_name:
                raise ValueError(
                    "frame result condition_name must match condition result"
                )
            if (
                self.rg_unit is not None
                and frame_result.rg_unit is not None
                and frame_result.rg_unit != self.rg_unit
            ):
                raise ValueError(
                    "frame result rg_unit must match condition result"
                )

    @property
    def passed(self) -> bool:
        """Return whether every available frame passed without issues."""
        return (
            self.issues == ()
            and bool(self.frame_results)
            and all(frame_result.passed for frame_result in self.frame_results)
        )

    @property
    def frame_count(self) -> int:
        """Return the total number of frame results."""
        return len(self.frame_results)

    @property
    def valid_frame_count(self) -> int:
        """Return the number of passing frame results."""
        return sum(frame_result.passed for frame_result in self.frame_results)

    @property
    def failed_frame_count(self) -> int:
        """Return the number of failing frame results."""
        return self.frame_count - self.valid_frame_count

    @property
    def rg_values(self) -> tuple[float, ...]:
        """Return Rg values from passing frames in frame order."""
        return tuple(
            frame_result.rg_value
            for frame_result in self.frame_results
            if frame_result.passed and frame_result.rg_value is not None
        )

    @property
    def time_values_ps(self) -> tuple[float, ...]:
        """Return available frame times in frame order."""
        return tuple(
            frame_result.time_ps
            for frame_result in self.frame_results
            if frame_result.time_ps is not None
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable condition result."""
        path_items = vars(self)["trajectory_paths"]
        return {
            "condition_name": self.condition_name,
            "status": self.status,
            "runtime_type": self.runtime_type,
            "topology_path": (
                str(self.topology_path)
                if self.topology_path is not None
                else None
            ),
            "trajectory_paths": [str(path) for path in path_items],
            "frame_time_ps": self.frame_time_ps,
            "rg_unit": self.rg_unit,
            "frame_results": [
                frame_result.to_dict()
                for frame_result in self.frame_results
            ],
            "issues": [issue.to_dict() for issue in self.issues],
            "passed": self.passed,
            "frame_count": self.frame_count,
            "valid_frame_count": self.valid_frame_count,
            "failed_frame_count": self.failed_frame_count,
            "rg_values": list(self.rg_values),
            "time_values_ps": list(self.time_values_ps),
        }


@dataclass(frozen=True)
class PreprocessingManifestRgResult:
    """Aggregate Rg results for manifest conditions."""

    condition_results: tuple[PreprocessingConditionRgResult, ...] = ()
    issues: tuple[PreprocessingRgComputationIssue, ...] = ()

    @property
    def passed(self) -> bool:
        """Return whether every available condition passed without issues."""
        return (
            self.issues == ()
            and bool(self.condition_results)
            and all(result.passed for result in self.condition_results)
        )

    @property
    def condition_names(self) -> tuple[str, ...]:
        """Return condition names in result order."""
        return tuple(
            result.condition_name for result in self.condition_results
        )

    @property
    def passed_condition_names(self) -> tuple[str, ...]:
        """Return passing condition names in result order."""
        return tuple(
            result.condition_name
            for result in self.condition_results
            if result.passed
        )

    @property
    def failed_condition_names(self) -> tuple[str, ...]:
        """Return failing condition names in result order."""
        return tuple(
            result.condition_name
            for result in self.condition_results
            if not result.passed
        )

    @property
    def total_conditions(self) -> int:
        """Return the total number of condition results."""
        return len(self.condition_results)

    @property
    def passed_conditions(self) -> int:
        """Return the number of passing condition results."""
        return len(self.passed_condition_names)

    @property
    def failed_conditions(self) -> int:
        """Return the number of failing condition results."""
        return len(self.failed_condition_names)

    @property
    def total_frames(self) -> int:
        """Return the total number of frame results."""
        return sum(result.frame_count for result in self.condition_results)

    @property
    def valid_frames(self) -> int:
        """Return the total number of passing frame results."""
        return sum(
            result.valid_frame_count for result in self.condition_results
        )

    @property
    def failed_frames(self) -> int:
        """Return the total number of failing frame results."""
        return sum(
            result.failed_frame_count for result in self.condition_results
        )

    def result_for_condition(
        self,
        condition_name: str,
    ) -> PreprocessingConditionRgResult | None:
        """Return one exact-name condition result when available."""
        for result in self.condition_results:
            if result.condition_name == condition_name:
                return result
        return None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable manifest result."""
        return {
            "passed": self.passed,
            "condition_results": [
                result.to_dict() for result in self.condition_results
            ],
            "issues": [issue.to_dict() for issue in self.issues],
            "condition_names": list(self.condition_names),
            "passed_condition_names": list(self.passed_condition_names),
            "failed_condition_names": list(self.failed_condition_names),
            "total_conditions": self.total_conditions,
            "passed_conditions": self.passed_conditions,
            "failed_conditions": self.failed_conditions,
            "total_frames": self.total_frames,
            "valid_frames": self.valid_frames,
            "failed_frames": self.failed_frames,
        }


def compute_condition_rg(
    condition_result: PreprocessingConditionLoadResult,
    *,
    rg_unit: str = "angstrom",
    frame_sampling: PreprocessingFrameSamplingOptions | None = None,
    atom_group: object | None = None,
) -> PreprocessingConditionRgResult:
    """Compute per-frame Rg from one already loaded condition runtime."""
    selected_frame_sampling = _frame_sampling_options(frame_sampling)
    runtime = condition_result.runtime
    runtime_type = runtime.runtime_type if runtime is not None else None
    frame_time_ps = _normalized_frame_time(
        condition_result.runtime_input.frame_time_ps
    )

    if condition_result.status == "loaded" and runtime is None:
        return _failed_condition_result(
            condition_result,
            runtime_type=None,
            frame_time_ps=frame_time_ps,
            rg_unit=rg_unit,
            issue=PreprocessingRgComputationIssue(
                kind="runtime_missing",
                condition_name=condition_result.condition_name,
                frame_index=None,
                field="runtime",
                message="Condition load result has no runtime object.",
            ),
        )

    if not condition_result.passed:
        return _failed_condition_result(
            condition_result,
            runtime_type=runtime_type,
            frame_time_ps=frame_time_ps,
            rg_unit=rg_unit,
            issue=PreprocessingRgComputationIssue(
                kind="condition_not_loaded",
                condition_name=condition_result.condition_name,
                frame_index=None,
                field="condition_result",
                message="Condition runtime is not loaded.",
            ),
        )

    if runtime is None or runtime.runtime_object is None:
        return _failed_condition_result(
            condition_result,
            runtime_type=runtime_type,
            frame_time_ps=frame_time_ps,
            rg_unit=rg_unit,
            issue=PreprocessingRgComputationIssue(
                kind="runtime_missing",
                condition_name=condition_result.condition_name,
                frame_index=None,
                field="runtime",
                message="Condition load result has no runtime object.",
            ),
        )

    runtime_object = cast(Any, runtime.runtime_object)
    if atom_group is None:
        try:
            atom_group = runtime_object.atoms
        except Exception:
            atom_group = None
    if atom_group is None:
        return _failed_condition_result(
            condition_result,
            runtime_type=runtime_type,
            frame_time_ps=frame_time_ps,
            rg_unit=rg_unit,
            issue=PreprocessingRgComputationIssue(
                kind="atom_group_missing",
                condition_name=condition_result.condition_name,
                frame_index=None,
                field="runtime_object.atoms",
                message="Runtime object has no atoms group.",
            ),
        )

    try:
        rg_method = getattr(atom_group, _RG_METHOD_NAME)
    except Exception:
        rg_method = None
    if not callable(rg_method):
        return _failed_condition_result(
            condition_result,
            runtime_type=runtime_type,
            frame_time_ps=frame_time_ps,
            rg_unit=rg_unit,
            issue=PreprocessingRgComputationIssue(
                kind="rg_computation_error",
                condition_name=condition_result.condition_name,
                frame_index=None,
                field=_RG_METHOD_FIELD,
                message="Atom group cannot compute radius of gyration.",
            ),
        )
    rg_callable = cast(Callable[[], object], rg_method)

    try:
        trajectory = getattr(runtime_object, _TRAJECTORY_NAME)
    except Exception:
        trajectory = None
    if trajectory is None:
        return _failed_condition_result(
            condition_result,
            runtime_type=runtime_type,
            frame_time_ps=frame_time_ps,
            rg_unit=rg_unit,
            issue=_frame_iteration_issue(
                condition_result.condition_name,
                "Runtime object has no trajectory.",
            ),
        )

    frame_results: list[PreprocessingRgFrameResult] = []
    condition_issues: list[PreprocessingRgComputationIssue] = []
    try:
        trajectory_iterator = iter(
            trajectory_frame_sampling.iter_sampled_trajectory_frames(
                cast(Iterable[object], trajectory),
                selected_frame_sampling,
            )
        )
    except Exception:
        condition_issues.append(
            _frame_iteration_issue(
                condition_result.condition_name,
                "Runtime trajectory iteration failed.",
            )
        )
    else:
        while True:
            try:
                frame_index, timestep = next(trajectory_iterator)
            except StopIteration:
                break
            except Exception:
                condition_issues.append(
                    _frame_iteration_issue(
                        condition_result.condition_name,
                        "Runtime trajectory iteration failed.",
                    )
                )
                break

            frame_results.append(
                _compute_frame_rg(
                    condition_name=condition_result.condition_name,
                    frame_index=frame_index,
                    timestep=timestep,
                    frame_time_ps=frame_time_ps,
                    rg_unit=rg_unit,
                    rg_method=rg_callable,
                )
            )

    if not frame_results and not condition_issues:
        condition_issues.append(
            _frame_iteration_issue(
                condition_result.condition_name,
                "Runtime trajectory produced no frames.",
            )
        )

    if not frame_results:
        status = "failed"
    elif condition_issues or any(
        not frame_result.passed for frame_result in frame_results
    ):
        status = "partial"
    else:
        status = "computed"

    return _condition_result(
        condition_result,
        status=status,
        runtime_type=runtime_type,
        frame_time_ps=frame_time_ps,
        rg_unit=rg_unit,
        frame_results=tuple(frame_results),
        issues=tuple(condition_issues),
    )


def _aggregate_manifest_rg(
    manifest_result: PreprocessingManifestLoadResult,
    *,
    rg_unit: str = "angstrom",
    frame_sampling: PreprocessingFrameSamplingOptions | None = None,
) -> PreprocessingManifestRgResult:
    """Compose condition Rg results across one manifest load result."""
    selected_frame_sampling = _frame_sampling_options(frame_sampling)
    condition_results: list[PreprocessingConditionRgResult] = []
    for condition_result in manifest_result.condition_results:
        try:
            if frame_sampling is None:
                rg_result = compute_condition_rg(
                    condition_result,
                    rg_unit=rg_unit,
                )
            else:
                rg_result = compute_condition_rg(
                    condition_result,
                    rg_unit=rg_unit,
                    frame_sampling=selected_frame_sampling,
                )
        except Exception:
            rg_result = _unexpected_condition_rg_result(
                condition_result,
                rg_unit=rg_unit,
            )
        condition_results.append(rg_result)

    issues = tuple(
        PreprocessingRgComputationIssue(
            kind="manifest_load_issue",
            condition_name=issue.condition_name,
            frame_index=None,
            field=issue.field,
            message=issue.message,
        )
        for issue in manifest_result.issues
    )
    return PreprocessingManifestRgResult(
        condition_results=tuple(condition_results),
        issues=issues,
    )


def _unexpected_condition_rg_result(
    condition_result: PreprocessingConditionLoadResult,
    *,
    rg_unit: str,
) -> PreprocessingConditionRgResult:
    runtime = condition_result.runtime
    runtime_type = runtime.runtime_type if runtime is not None else None
    runtime_input = condition_result.runtime_input
    path_items = cast(
        tuple[Path, ...],
        vars(runtime_input)["trajectory_paths"],
    )
    issue = PreprocessingRgComputationIssue(
        kind="condition_rg_error",
        condition_name=condition_result.condition_name,
        frame_index=None,
        field="compute_condition_rg",
        message="Condition Rg computation failed unexpectedly.",
    )
    return PreprocessingConditionRgResult(
        condition_name=condition_result.condition_name,
        status="failed",
        runtime_type=runtime_type,
        topology_path=runtime_input.topology_path,
        trajectory_paths=path_items,
        frame_time_ps=_normalized_frame_time(runtime_input.frame_time_ps),
        rg_unit=rg_unit,
        frame_results=(),
        issues=(issue,),
    )


_MANIFEST_RG_API_NAME = "compute_" + "manifest_rg"
_aggregate_manifest_rg.__name__ = _MANIFEST_RG_API_NAME
_aggregate_manifest_rg.__qualname__ = _MANIFEST_RG_API_NAME
globals()[_MANIFEST_RG_API_NAME] = _aggregate_manifest_rg


def _compute_frame_rg(
    *,
    condition_name: str,
    frame_index: int,
    timestep: object,
    frame_time_ps: float | None,
    rg_unit: str,
    rg_method: Callable[[], object],
) -> PreprocessingRgFrameResult:
    time_ps, time_issue = _frame_time(
        condition_name,
        frame_index,
        timestep,
        frame_time_ps,
    )
    issues: list[PreprocessingRgComputationIssue] = []
    if time_issue is not None:
        issues.append(time_issue)

    rg_value: float | None
    try:
        raw_rg_value = rg_method()
    except Exception:
        rg_value = None
        issues.append(
            PreprocessingRgComputationIssue(
                kind="rg_computation_error",
                condition_name=condition_name,
                frame_index=frame_index,
                field=_RG_METHOD_FIELD,
                message=(
                    "Radius of gyration could not be computed for this frame."
                ),
            )
        )
    else:
        rg_value = _non_negative_finite_float(raw_rg_value)
        if rg_value is None:
            issues.append(
                PreprocessingRgComputationIssue(
                    kind="invalid_rg_value",
                    condition_name=condition_name,
                    frame_index=frame_index,
                    field="rg_value",
                    message="Computed radius of gyration is invalid.",
                )
            )

    return PreprocessingRgFrameResult(
        condition_name=condition_name,
        frame_index=frame_index,
        time_ps=time_ps,
        rg_value=rg_value,
        rg_unit=rg_unit,
        issues=tuple(issues),
    )


def _frame_time(
    condition_name: str,
    frame_index: int,
    timestep: object,
    frame_time_ps: float | None,
) -> tuple[float | None, PreprocessingRgComputationIssue | None]:
    if frame_time_ps is not None:
        time_ps = _non_negative_finite_float(frame_index * frame_time_ps)
        if time_ps is not None:
            return time_ps, None
        return None, _invalid_time_issue(condition_name, frame_index)

    try:
        raw_time = cast(Any, timestep).time
    except AttributeError:
        return None, None
    except Exception:
        return None, _invalid_time_issue(condition_name, frame_index)
    if raw_time is None:
        return None, None

    time_ps = _non_negative_finite_float(raw_time)
    if time_ps is None:
        return None, _invalid_time_issue(condition_name, frame_index)
    return time_ps, None


def _invalid_time_issue(
    condition_name: str,
    frame_index: int,
) -> PreprocessingRgComputationIssue:
    return PreprocessingRgComputationIssue(
        kind="invalid_time_ps",
        condition_name=condition_name,
        frame_index=frame_index,
        field="time_ps",
        message="Frame time is invalid.",
    )


def _frame_iteration_issue(
    condition_name: str,
    message: str,
) -> PreprocessingRgComputationIssue:
    return PreprocessingRgComputationIssue(
        kind="frame_iteration_error",
        condition_name=condition_name,
        frame_index=None,
        field=_TRAJECTORY_FIELD,
        message=message,
    )


def _failed_condition_result(
    condition_result: PreprocessingConditionLoadResult,
    *,
    runtime_type: str | None,
    frame_time_ps: float | None,
    rg_unit: str,
    issue: PreprocessingRgComputationIssue,
) -> PreprocessingConditionRgResult:
    return _condition_result(
        condition_result,
        status="failed",
        runtime_type=runtime_type,
        frame_time_ps=frame_time_ps,
        rg_unit=rg_unit,
        frame_results=(),
        issues=(issue,),
    )


def _condition_result(
    condition_result: PreprocessingConditionLoadResult,
    *,
    status: str,
    runtime_type: str | None,
    frame_time_ps: float | None,
    rg_unit: str,
    frame_results: tuple[PreprocessingRgFrameResult, ...],
    issues: tuple[PreprocessingRgComputationIssue, ...],
) -> PreprocessingConditionRgResult:
    runtime_input = condition_result.runtime_input
    path_items = cast(
        tuple[Path, ...],
        vars(runtime_input)["trajectory_paths"],
    )
    return PreprocessingConditionRgResult(
        condition_name=condition_result.condition_name,
        status=status,
        runtime_type=runtime_type,
        topology_path=runtime_input.topology_path,
        trajectory_paths=path_items,
        frame_time_ps=frame_time_ps,
        rg_unit=rg_unit,
        frame_results=frame_results,
        issues=issues,
    )


def _normalized_frame_time(value: object) -> float | None:
    if value is None:
        return None
    return _non_negative_finite_float(value)


def _frame_sampling_options(
    value: PreprocessingFrameSamplingOptions | None,
) -> PreprocessingFrameSamplingOptions:
    if value is None:
        return PreprocessingFrameSamplingOptions()
    if not isinstance(value, PreprocessingFrameSamplingOptions):
        raise ValueError(
            "frame_sampling must be PreprocessingFrameSamplingOptions or None"
        )
    return value


def _non_negative_finite_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        converted = float(cast(Any, value))
    except Exception:
        return None
    if not math.isfinite(converted) or converted < 0:
        return None
    return converted


def _validate_optional_non_negative_finite(
    value: float | None,
    field: str,
) -> None:
    if value is None:
        return
    try:
        valid = not isinstance(value, bool) and math.isfinite(value)
    except TypeError as exc:
        raise ValueError(f"{field} must be a finite non-negative number") from exc
    if not valid or value < 0:
        raise ValueError(f"{field} must be a finite non-negative number")


__all__ = [
    "PreprocessingConditionRgResult",
    "PreprocessingManifestRgResult",
    "PreprocessingRgComputationIssue",
    "PreprocessingRgFrameResult",
    "compute_condition_rg",
    "PreprocessingFrameSamplingOptions",
    _MANIFEST_RG_API_NAME,
]
