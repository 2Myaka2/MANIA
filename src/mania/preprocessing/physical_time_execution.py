"""Plan Dataset temporal execution once from actual loaded trajectory times."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Iterable
from dataclasses import dataclass, field
from fractions import Fraction
from itertools import pairwise
from math import isfinite
from typing import TYPE_CHECKING, Literal, cast

from mania.dataset_identity import DatasetTrajectorySpec
from mania.preprocessing.dataset_binding import PreprocessingDatasetContext
from mania.preprocessing.physical_time_sampling import (
    MissingPhysicalTimeSample,
    PhysicalTimeSourceFrame,
    ResolvedPhysicalTimeSample,
    ResolvedPhysicalTimeSamplingPlan,
    resolve_physical_time_sampling,
)
from mania.preprocessing.physical_time_windows import (
    ResolvedPhysicalTimeWindowPlan,
    plan_physical_time_windows,
)
from mania.preprocessing.trajectory_manifest_loader import (
    PreprocessingManifestLoadResult,
)
from mania.preprocessing.trajectory_runtime import PreprocessingConditionLoadResult

if TYPE_CHECKING:
    from mania.preprocessing.trajectory_graph_workflow import (
        PreprocessingGraphWorkflowRuntimeLoadingResult,
    )

from mania.preprocessing.temporal_policy import (
    INCLUSIVE_BOUNDARY_PROFILE,
    LEGACY_BOUNDARY_PROFILE,
)

PREPROCESSING_TEMPORAL_EXECUTION_PROFILE_SCHEMA_VERSION = (
    "mania.preprocessing_temporal_execution.v0.2"
)
PREPROCESSING_TEMPORAL_EXECUTION_SCHEMA_VERSION = (
    "mania.preprocessing_temporal_execution.v0.1"
)
PREPROCESSING_TEMPORAL_EXECUTION_KIND = "mania_preprocessing_temporal_execution"
PREPROCESSING_TEMPORAL_EXECUTION_FILENAME = "temporal_execution.json"
PREPROCESSING_TEMPORAL_EXECUTION_ROLE = "temporal_execution"
PreprocessingTemporalExecutionStatus = Literal["complete", "partial"]


class PreprocessingPhysicalTimeExecutionError(ValueError):
    """Physical execution cannot be planned; science must not begin."""


@dataclass(frozen=True)
class PreprocessingConditionTemporalExecution:
    """Requested Dataset identity and its successful resolved execution plans."""

    execution_condition: str
    dataset_spec: DatasetTrajectorySpec
    sampling_plan: ResolvedPhysicalTimeSamplingPlan
    window_plan: ResolvedPhysicalTimeWindowPlan

    def __post_init__(self) -> None:
        if (
            not isinstance(self.execution_condition, str)
            or not self.execution_condition.strip()
            or self.execution_condition != self.execution_condition.strip()
        ):
            raise ValueError("execution_condition must be a non-empty stripped string")
        for name, model in (
            ("dataset_spec", DatasetTrajectorySpec),
            ("sampling_plan", ResolvedPhysicalTimeSamplingPlan),
            ("window_plan", ResolvedPhysicalTimeWindowPlan),
        ):
            if type(getattr(self, name)) is not model:
                raise ValueError(f"{name} must be exact {model.__name__}")
        if self.dataset_spec.identity.condition not in (None, self.execution_condition):
            raise ValueError(
                "Dataset scientific condition must equal execution condition"
            )
        temporal = self.dataset_spec.temporal
        for plan, names in (
            (
                self.sampling_plan,
                (
                    "production_start_ns",
                    "production_end_ns",
                    "frame_stride_ps",
                ),
            ),
            (
                self.window_plan,
                (
                    "production_start_ns",
                    "production_end_ns",
                    "window_length_ns",
                    "window_step_ns",
                    "overlap_percent",
                ),
            ),
        ):
            if plan.status not in ("complete", "partial"):
                raise ValueError("Failed plans cannot describe successful execution")
            if any(
                getattr(plan, f"requested_{name}") != getattr(temporal, name)
                for name in names
            ):
                raise ValueError(
                    "Temporal plan request must equal Dataset temporal request"
                )
        indexes = self.selected_source_frame_indexes
        if any(b <= a for a, b in pairwise(indexes)) or any(
            i >= self.sampling_plan.source_frame_count for i in indexes
        ):
            raise ValueError("Execution indexes must follow source enumeration")
        # Check the link between stored plans without resolving the trajectory again.
        selected = {
            sample.requested_sample_index: sample
            for sample in self.sampling_plan.selected_samples
        }
        missing = {
            sample.requested_sample_index
            for sample in self.sampling_plan.missing_samples
        }
        combined: tuple[ResolvedPhysicalTimeSample | MissingPhysicalTimeSample, ...] = (
            *self.sampling_plan.selected_samples,
            *self.sampling_plan.missing_samples,
        )
        records = sorted(
            combined,
            key=lambda sample: sample.requested_sample_index,
        )
        requested_times = tuple(
            Fraction(str(s.requested_time_ps)) / 1000 for s in records
        )
        start, end, length, step = (
            Fraction(str(getattr(temporal, name)))
            for name in (
                "production_start_ns",
                "production_end_ns",
                "window_length_ns",
                "window_step_ns",
            )
        )
        # Exact rational checks of serialized links do not resolve or time-match
        # a trajectory, regenerate sampling targets, or invoke either planner.
        if self.window_plan.window_count != (end - start - length) // step + 1:
            raise ValueError("Window count must describe the full requested schedule")
        for window in self.window_plan.windows:
            lower = start + window.window_index * step
            upper = lower + length
            inclusive = (
                self.window_plan.boundary_profile == INCLUSIVE_BOUNDARY_PROFILE
                or upper == end
            )
            if (
                window.requested_start_ns != float(lower)
                or window.requested_end_ns != float(upper)
                or window.right_endpoint_inclusive != inclusive
            ):
                raise ValueError("Window bounds must follow the requested schedule")
            first = bisect_left(requested_times, lower)
            last = (bisect_right if inclusive else bisect_left)(requested_times, upper)
            if window.requested_sample_indexes != tuple(range(first, last)):
                raise ValueError("Window membership must follow requested sample times")
            if any(
                i not in selected for i in window.selected_requested_sample_indexes
            ) or any(i not in missing for i in window.missing_requested_sample_indexes):
                raise ValueError(
                    "Window membership must correspond to the sampling plan"
                )
            samples = tuple(
                selected[i] for i in window.selected_requested_sample_indexes
            )
            if window.source_frame_indexes != tuple(
                s.source_frame_index for s in samples
            ):
                raise ValueError(
                    "Window source indexes must correspond to selected samples"
                )
            bounds = (
                samples[0].actual_time_ps if samples else None,
                samples[-1].actual_time_ps if samples else None,
            )
            if (window.effective_start_time_ps, window.effective_end_time_ps) != bounds:
                raise ValueError(
                    "Window effective bounds must describe selected samples"
                )

    @property
    def selected_source_frame_indexes(self) -> tuple[int, ...]:
        return tuple(s.source_frame_index for s in self.sampling_plan.selected_samples)

    def to_dict(self) -> dict[str, object]:
        return {
            "execution_condition": self.execution_condition,
            "dataset_spec": self.dataset_spec.to_dict(),
            "sampling_plan": self.sampling_plan.to_dict(),
            "window_plan": self.window_plan.to_dict(),
        }


@dataclass(frozen=True)
class PreprocessingTemporalExecution:
    """Ordered Dataset bindings; legacy conditions have no temporal record."""

    bindings: tuple[PreprocessingConditionTemporalExecution, ...]
    schema_version: str = field(
        default=PREPROCESSING_TEMPORAL_EXECUTION_SCHEMA_VERSION,
        init=False,
    )
    kind: str = field(default=PREPROCESSING_TEMPORAL_EXECUTION_KIND, init=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.bindings, tuple)
            or not self.bindings
            or any(
                type(b) is not PreprocessingConditionTemporalExecution
                for b in self.bindings
            )
        ):
            raise ValueError(
                "bindings must be a non-empty tuple of temporal executions"
            )
        profiles = {b.window_plan.boundary_profile for b in self.bindings}
        if len(profiles) != 1:
            raise ValueError("Temporal execution must use one boundary profile")
        object.__setattr__(
            self,
            "schema_version",
            (
                PREPROCESSING_TEMPORAL_EXECUTION_SCHEMA_VERSION
                if profiles == {LEGACY_BOUNDARY_PROFILE}
                else PREPROCESSING_TEMPORAL_EXECUTION_PROFILE_SCHEMA_VERSION
            ),
        )
        conditions = {b.execution_condition for b in self.bindings}
        keys = {b.dataset_spec.identity.replica_key for b in self.bindings}
        if len(conditions) != len(self.bindings) or len(keys) != len(self.bindings):
            raise ValueError(
                "Execution conditions and Dataset replica keys must be unique"
            )

    @property
    def status(self) -> PreprocessingTemporalExecutionStatus:
        return (
            "partial"
            if any(
                b.sampling_plan.status == "partial" or b.window_plan.status == "partial"
                for b in self.bindings
            )
            else "complete"
        )

    def selected_source_frame_indexes_by_condition(self) -> dict[str, tuple[int, ...]]:
        return {
            b.execution_condition: b.selected_source_frame_indexes
            for b in self.bindings
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "status": self.status,
            "bindings": [b.to_dict() for b in self.bindings],
        }


def collect_runtime_physical_time_source_frames(
    condition: PreprocessingConditionLoadResult,
) -> tuple[PhysicalTimeSourceFrame, ...]:
    """Enumerate one loaded trajectory once, reading only actual timestep.time."""
    if type(condition) is not PreprocessingConditionLoadResult or not condition.passed:
        raise PreprocessingPhysicalTimeExecutionError("A loaded condition is required.")
    assert condition.runtime is not None
    try:
        trajectory = cast(
            Iterable[object],
            getattr(condition.runtime.runtime_object, "trajectory", None),
        )
        frames = []
        for index, timestep in enumerate(trajectory):
            raw_time = getattr(timestep, "time", None)
            if raw_time is None or isinstance(raw_time, (bool, str, bytes)):
                raise ValueError
            time_ps = float(raw_time)
            if not isfinite(time_ps) or time_ps < 0:
                raise ValueError
            frames.append(PhysicalTimeSourceFrame(index, time_ps))
        return tuple(frames)
    except Exception:
        raise PreprocessingPhysicalTimeExecutionError(
            "Actual trajectory time axis is unavailable or invalid."
        ) from None


def build_preprocessing_temporal_execution(
    runtime_loading: PreprocessingGraphWorkflowRuntimeLoadingResult,
    dataset_context: PreprocessingDatasetContext,
) -> PreprocessingTemporalExecution:
    """Resolve sampling and windows before any scientific pass, in context order."""
    if type(dataset_context) is not PreprocessingDatasetContext:
        raise PreprocessingPhysicalTimeExecutionError("Dataset context is required.")
    loaded = runtime_loading.runtime_load_result
    if (
        not isinstance(loaded, PreprocessingManifestLoadResult)
        or not runtime_loading.passed
    ):
        raise PreprocessingPhysicalTimeExecutionError(
            "Authoritative loaded runtimes are required."
        )
    names = tuple(c.condition_name for c in loaded.condition_results)
    if len(set(names)) != len(names):
        raise PreprocessingPhysicalTimeExecutionError(
            "Runtime conditions must be unique."
        )
    bindings = []
    for binding in dataset_context.bindings:
        condition = loaded.result_for_condition(binding.execution_condition)
        if condition is None:
            raise PreprocessingPhysicalTimeExecutionError(
                "Dataset runtime condition is missing."
            )
        source = collect_runtime_physical_time_source_frames(condition)
        try:
            sampling = resolve_physical_time_sampling(
                source, temporal=binding.dataset_spec.temporal
            )
            if sampling.status == "failed":
                raise PreprocessingPhysicalTimeExecutionError(
                    "Physical sampling plan failed."
                )
            windows = plan_physical_time_windows(
                sampling,
                temporal=binding.dataset_spec.temporal,
                boundary_profile=(
                    dataset_context.temporal_policy.boundary_profile
                    if dataset_context.temporal_policy is not None
                    else LEGACY_BOUNDARY_PROFILE
                ),
            )
            if windows.status == "failed":
                raise PreprocessingPhysicalTimeExecutionError(
                    "Physical window plan failed."
                )
            bindings.append(
                PreprocessingConditionTemporalExecution(
                    binding.execution_condition,
                    binding.dataset_spec,
                    sampling,
                    windows,
                )
            )
        except PreprocessingPhysicalTimeExecutionError:
            raise
        except (TypeError, ValueError, OverflowError):
            raise PreprocessingPhysicalTimeExecutionError(
                "Temporal execution contract is invalid."
            ) from None
    return PreprocessingTemporalExecution(tuple(bindings))
