"""Pure Stage 27.B windows over authoritative Stage 27.A sample records."""

from bisect import bisect_left, bisect_right
from dataclasses import asdict, dataclass, field
from decimal import Context, Decimal, localcontext
from itertools import pairwise
from math import isclose, isfinite
from typing import Literal

from mania.dataset_identity import DatasetTemporalParameters
from mania.preprocessing.physical_time_sampling import (
    MissingPhysicalTimeSample,
    ResolvedPhysicalTimeSample,
    ResolvedPhysicalTimeSamplingPlan,
)
from mania.preprocessing.temporal_policy import (
    INCLUSIVE_BOUNDARY_PROFILE,
    LEGACY_BOUNDARY_PROFILE,
    BoundaryProfile,
    require_boundary_profile,
)

PHYSICAL_TIME_WINDOW_PROFILE_SCHEMA_VERSION = "mania.physical_time_windows.v0.2"
PHYSICAL_TIME_WINDOW_SCHEMA_VERSION = "mania.physical_time_windows.v0.1"
PHYSICAL_TIME_WINDOW_KIND = "mania_physical_time_windows"
WINDOW_OVERLAP_PERCENT_ABS_TOLERANCE = 1e-6
WINDOW_OVERLAP_PERCENT_REL_TOLERANCE = 1e-9

PhysicalTimeWindowStatus = Literal["complete", "partial", "empty"]
PhysicalTimeWindowPlanStatus = Literal["complete", "partial", "failed"]


def _require_index(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def _require_number(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite non-negative number")
    try:
        valid = isfinite(value) and value >= 0
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(f"{name} must be a finite non-negative number")


def _require_text(value: object, name: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be a non-empty stripped string")


def _window_status(sampled: int, missing: int) -> PhysicalTimeWindowStatus:
    if not sampled:
        return "empty"
    return "partial" if missing else "complete"


@dataclass(frozen=True)
class ResolvedPhysicalTimeWindow:
    """Requested membership and observed bounds; empty includes zero targets."""

    window_index: int
    window_id: str
    requested_start_ns: float
    requested_end_ns: float
    right_endpoint_inclusive: bool
    requested_sample_count: int
    sampled_frame_count: int
    missing_sample_count: int
    coverage_fraction: float
    effective_start_time_ps: float | None
    effective_end_time_ps: float | None
    requested_sample_indexes: tuple[int, ...]
    selected_requested_sample_indexes: tuple[int, ...]
    missing_requested_sample_indexes: tuple[int, ...]
    source_frame_indexes: tuple[int, ...]
    status: PhysicalTimeWindowStatus

    def __post_init__(self) -> None:
        for name in (
            "window_index",
            "requested_sample_count",
            "sampled_frame_count",
            "missing_sample_count",
        ):
            _require_index(getattr(self, name), name)
        _require_text(self.window_id, "window_id")
        for name in ("requested_start_ns", "requested_end_ns", "coverage_fraction"):
            _require_number(getattr(self, name), name)
        if self.requested_end_ns <= self.requested_start_ns:
            raise ValueError("requested window interval must be positive")
        if type(self.right_endpoint_inclusive) is not bool:
            raise ValueError("right_endpoint_inclusive must be an exact bool")
        for name, count in (
            ("requested_sample_indexes", self.requested_sample_count),
            ("selected_requested_sample_indexes", self.sampled_frame_count),
            ("missing_requested_sample_indexes", self.missing_sample_count),
            ("source_frame_indexes", self.sampled_frame_count),
        ):
            indexes = getattr(self, name)
            if not isinstance(indexes, tuple) or len(indexes) != count:
                raise ValueError(f"{name} must be a tuple matching its count")
            for index in indexes:
                _require_index(index, name)
            if name != "source_frame_indexes" and any(
                b <= a for a, b in pairwise(indexes)
            ):
                raise ValueError(f"{name} must preserve requested-grid order")
        assigned = (
            self.selected_requested_sample_indexes
            + self.missing_requested_sample_indexes
        )
        if (
            self.requested_sample_count
            != self.sampled_frame_count + self.missing_sample_count
            or tuple(sorted(assigned)) != self.requested_sample_indexes
        ):
            raise ValueError("selected and missing indexes must partition requested")
        if len(set(self.source_frame_indexes)) != self.sampled_frame_count:
            raise ValueError("source indexes must be unique within a window")
        coverage = (
            self.sampled_frame_count / self.requested_sample_count
            if self.requested_sample_count
            else 0.0
        )
        if self.coverage_fraction != coverage:
            raise ValueError("coverage must equal sampled / requested, or zero")
        for name in ("effective_start_time_ps", "effective_end_time_ps"):
            value = getattr(self, name)
            if value is not None:
                _require_number(value, name)
            if (value is not None) != (self.sampled_frame_count > 0):
                raise ValueError("effective bounds must exist iff samples exist")
        if (
            self.effective_start_time_ps is not None
            and self.effective_end_time_ps is not None
            and self.effective_end_time_ps < self.effective_start_time_ps
        ):
            raise ValueError("effective end must be at least effective start")
        if self.status != _window_status(
            self.sampled_frame_count, self.missing_sample_count
        ):
            raise ValueError("window status must agree with counts")

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        for name in (
            "requested_sample_indexes",
            "selected_requested_sample_indexes",
            "missing_requested_sample_indexes",
            "source_frame_indexes",
        ):
            result[name] = list(getattr(self, name))
        return result


@dataclass(frozen=True)
class PhysicalTimeWindowPlanningIssue:
    """Portable deterministic diagnostic, optionally scoped to one window."""

    severity: Literal["error", "warning"]
    code: str
    message: str
    window_index: int | None = None

    def __post_init__(self) -> None:
        if self.severity not in ("error", "warning"):
            raise ValueError("severity must be error or warning")
        _require_text(self.code, "code")
        _require_text(self.message, "message")
        if self.window_index is not None:
            _require_index(self.window_index, "window_index")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _window_parameters(
    length: float,
    step: float,
    overlap: float,
) -> tuple[float | None, PhysicalTimeWindowPlanningIssue | None]:
    if not 0 < step <= length:
        return None, PhysicalTimeWindowPlanningIssue(
            "error",
            "invalid_window_step",
            "Window step must satisfy 0 < step <= window length.",
        )
    implied = (1 - step / length) * 100
    if not isclose(
        overlap,
        implied,
        rel_tol=WINDOW_OVERLAP_PERCENT_REL_TOLERANCE,
        abs_tol=WINDOW_OVERLAP_PERCENT_ABS_TOLERANCE,
    ):
        return implied, PhysicalTimeWindowPlanningIssue(
            "error",
            "inconsistent_window_overlap",
            "Supplied overlap must agree with (1 - step / length) * 100.",
        )
    return implied, None


@dataclass(frozen=True)
class ResolvedPhysicalTimeWindowPlan:
    """Full requested schedule with totals counting intentional overlap."""

    schema_version: str = field(default=PHYSICAL_TIME_WINDOW_SCHEMA_VERSION, init=False)
    kind: str = field(default=PHYSICAL_TIME_WINDOW_KIND, init=False)
    status: PhysicalTimeWindowPlanStatus
    requested_production_start_ns: float
    requested_production_end_ns: float
    requested_window_length_ns: float
    requested_window_step_ns: float
    requested_overlap_percent: float
    implied_overlap_percent: float | None
    window_count: int
    complete_window_count: int
    partial_window_count: int
    empty_window_count: int
    windows_with_samples_count: int
    total_window_requested_sample_count: int
    total_window_sampled_frame_count: int
    total_window_missing_sample_count: int
    windows: tuple[ResolvedPhysicalTimeWindow, ...]
    issues: tuple[PhysicalTimeWindowPlanningIssue, ...]

    boundary_profile: BoundaryProfile = LEGACY_BOUNDARY_PROFILE

    def __post_init__(self) -> None:
        require_boundary_profile(self.boundary_profile)
        object.__setattr__(
            self,
            "schema_version",
            (
                PHYSICAL_TIME_WINDOW_SCHEMA_VERSION
                if self.boundary_profile == LEGACY_BOUNDARY_PROFILE
                else PHYSICAL_TIME_WINDOW_PROFILE_SCHEMA_VERSION
            ),
        )
        for name in (
            "requested_production_start_ns",
            "requested_production_end_ns",
            "requested_window_length_ns",
            "requested_window_step_ns",
            "requested_overlap_percent",
        ):
            _require_number(getattr(self, name), name)
        if (
            self.requested_production_end_ns <= self.requested_production_start_ns
            or self.requested_window_length_ns <= 0
            or self.requested_overlap_percent >= 100
        ):
            raise ValueError("invalid requested production/window contract")
        implied, parameter_issue = _window_parameters(
            self.requested_window_length_ns,
            self.requested_window_step_ns,
            self.requested_overlap_percent,
        )
        if self.implied_overlap_percent is not None:
            _require_number(self.implied_overlap_percent, "implied_overlap_percent")
        if self.implied_overlap_percent != implied:
            raise ValueError("implied overlap must describe the requested schedule")
        for name, record_type in (
            ("windows", ResolvedPhysicalTimeWindow),
            ("issues", PhysicalTimeWindowPlanningIssue),
        ):
            records = getattr(self, name)
            if not isinstance(records, tuple) or any(
                type(record) is not record_type for record in records
            ):
                raise ValueError(f"{name} must be a tuple of {record_type.__name__}")
        if parameter_issue is not None and (
            self.windows or parameter_issue not in self.issues
        ):
            raise ValueError("invalid schedule requires its error and no windows")
        for index, window in enumerate(self.windows):
            if (window.window_index, window.window_id) != (
                index,
                f"window_{index + 1:04d}",
            ):
                raise ValueError("windows must have consecutive indexes and IDs")
        for name, expected in (
            ("window_count", len(self.windows)),
            (
                "complete_window_count",
                sum(w.status == "complete" for w in self.windows),
            ),
            ("partial_window_count", sum(w.status == "partial" for w in self.windows)),
            ("empty_window_count", sum(w.status == "empty" for w in self.windows)),
            (
                "windows_with_samples_count",
                sum(w.sampled_frame_count > 0 for w in self.windows),
            ),
            (
                "total_window_requested_sample_count",
                sum(w.requested_sample_count for w in self.windows),
            ),
            (
                "total_window_sampled_frame_count",
                sum(w.sampled_frame_count for w in self.windows),
            ),
            (
                "total_window_missing_sample_count",
                sum(w.missing_sample_count for w in self.windows),
            ),
        ):
            value = getattr(self, name)
            _require_index(value, name)
            if value != expected:
                raise ValueError(f"{name} must equal its window aggregate")
        for issue in self.issues:
            if (
                issue.window_index is not None
                and issue.window_index >= self.window_count
            ):
                raise ValueError("issue window_index must identify a generated window")
        expected_status = _plan_status(self.windows, self.issues)
        if self.status != expected_status:
            raise ValueError("plan status must agree with windows and errors")

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        if self.boundary_profile == LEGACY_BOUNDARY_PROFILE:
            result.pop("boundary_profile")
        result["windows"] = [window.to_dict() for window in self.windows]
        result["issues"] = [issue.to_dict() for issue in self.issues]
        return result


def _plan_status(
    windows: tuple[ResolvedPhysicalTimeWindow, ...],
    issues: tuple[PhysicalTimeWindowPlanningIssue, ...],
) -> PhysicalTimeWindowPlanStatus:
    if any(i.severity == "error" for i in issues) or not any(
        w.sampled_frame_count for w in windows
    ):
        return "failed"
    return "complete" if all(w.status == "complete" for w in windows) else "partial"


def _make_plan(
    temporal: DatasetTemporalParameters,
    implied: float | None,
    windows: tuple[ResolvedPhysicalTimeWindow, ...],
    issues: tuple[PhysicalTimeWindowPlanningIssue, ...],
    boundary_profile: BoundaryProfile,
) -> ResolvedPhysicalTimeWindowPlan:
    return ResolvedPhysicalTimeWindowPlan(
        boundary_profile=boundary_profile,
        status=_plan_status(windows, issues),
        requested_production_start_ns=temporal.production_start_ns,
        requested_production_end_ns=temporal.production_end_ns,
        requested_window_length_ns=temporal.window_length_ns,
        requested_window_step_ns=temporal.window_step_ns,
        requested_overlap_percent=temporal.overlap_percent,
        implied_overlap_percent=implied,
        window_count=len(windows),
        complete_window_count=sum(w.status == "complete" for w in windows),
        partial_window_count=sum(w.status == "partial" for w in windows),
        empty_window_count=sum(w.status == "empty" for w in windows),
        windows_with_samples_count=sum(w.sampled_frame_count > 0 for w in windows),
        total_window_requested_sample_count=sum(
            w.requested_sample_count for w in windows
        ),
        total_window_sampled_frame_count=sum(w.sampled_frame_count for w in windows),
        total_window_missing_sample_count=sum(w.missing_sample_count for w in windows),
        windows=windows,
        issues=issues,
    )


def _make_window(
    index: int,
    start: Decimal,
    end: Decimal,
    inclusive: bool,
    members: tuple[ResolvedPhysicalTimeSample | MissingPhysicalTimeSample, ...],
) -> ResolvedPhysicalTimeWindow:
    selected = tuple(s for s in members if isinstance(s, ResolvedPhysicalTimeSample))
    missing = tuple(s for s in members if isinstance(s, MissingPhysicalTimeSample))
    return ResolvedPhysicalTimeWindow(
        window_index=index,
        window_id=f"window_{index + 1:04d}",
        requested_start_ns=float(start),
        requested_end_ns=float(end),
        right_endpoint_inclusive=inclusive,
        requested_sample_count=len(members),
        sampled_frame_count=len(selected),
        missing_sample_count=len(missing),
        coverage_fraction=len(selected) / len(members) if members else 0.0,
        effective_start_time_ps=selected[0].actual_time_ps if selected else None,
        effective_end_time_ps=selected[-1].actual_time_ps if selected else None,
        requested_sample_indexes=tuple(s.requested_sample_index for s in members),
        selected_requested_sample_indexes=tuple(
            s.requested_sample_index for s in selected
        ),
        missing_requested_sample_indexes=tuple(
            s.requested_sample_index for s in missing
        ),
        source_frame_indexes=tuple(s.source_frame_index for s in selected),
        status=_window_status(len(selected), len(missing)),
    )


def plan_physical_time_windows(
    sampling_plan: ResolvedPhysicalTimeSamplingPlan,
    *,
    temporal: DatasetTemporalParameters,
    boundary_profile: BoundaryProfile = LEGACY_BOUNDARY_PROFILE,
) -> ResolvedPhysicalTimeWindowPlan:
    """Assign 27.A records by requested time, without re-resolving source frames.

    Only full Decimal windows exist. The versioned profile controls the right
    endpoint; requested sampling and full-window positions are unchanged.
    """
    require_boundary_profile(boundary_profile)
    if type(sampling_plan) is not ResolvedPhysicalTimeSamplingPlan:
        raise ValueError("sampling_plan must be exact ResolvedPhysicalTimeSamplingPlan")
    if type(temporal) is not DatasetTemporalParameters:
        raise ValueError("temporal must be exact DatasetTemporalParameters")
    implied, parameter_issue = _window_parameters(
        temporal.window_length_ns,
        temporal.window_step_ns,
        temporal.overlap_percent,
    )
    issues = [parameter_issue] if parameter_issue is not None else []
    if any(
        Decimal(str(getattr(temporal, name)))
        != Decimal(str(getattr(sampling_plan, f"requested_{name}")))
        for name in ("production_start_ns", "production_end_ns", "frame_stride_ps")
    ):
        issues.append(
            PhysicalTimeWindowPlanningIssue(
                "error",
                "sampling_contract_mismatch",
                "Production bounds and stride must match the sampling plan request.",
            )
        )
    combined: tuple[ResolvedPhysicalTimeSample | MissingPhysicalTimeSample, ...] = (
        *sampling_plan.selected_samples,
        *sampling_plan.missing_samples,
    )
    records = tuple(
        sorted(
            combined,
            key=lambda sample: sample.requested_sample_index,
        )
    )
    if len(records) != sampling_plan.requested_sample_count or any(
        record.requested_sample_index != index for index, record in enumerate(records)
    ):
        issues.append(
            PhysicalTimeWindowPlanningIssue(
                "error",
                "sampling_contract_mismatch",
                "Sampling records must uniquely cover all requested sample indexes.",
            )
        )
    if issues:
        return _make_plan(temporal, implied, (), tuple(issues), boundary_profile)

    values = tuple(
        Decimal(str(value))
        for value in (
            temporal.production_start_ns,
            temporal.production_end_ns,
            temporal.window_length_ns,
            temporal.window_step_ns,
        )
    )
    target_ps = tuple(Decimal(str(record.requested_time_ps)) for record in records)
    # Cover the whole exponent span, including ps -> ns and the first omitted
    # window. Use our own context so caller precision/traps cannot alter boundaries.
    decimals = values + target_ps
    precision = (
        max(d.adjusted() for d in decimals)
        - min(int(d.as_tuple().exponent) for d in decimals)
        + 8
    )
    windows: list[ResolvedPhysicalTimeWindow] = []
    with localcontext(Context(prec=max(1, precision))):
        production_start, production_end, length, step = values
        target_ns = tuple(t / 1000 for t in target_ps)
        index = 0
        while True:
            start = production_start + index * step
            end = start + length
            if end > production_end:
                break
            inclusive = (
                boundary_profile == INCLUSIVE_BOUNDARY_PROFILE or end == production_end
            )
            lower = bisect_left(target_ns, start)
            upper = (bisect_right if inclusive else bisect_left)(target_ns, end)
            windows.append(
                _make_window(index, start, end, inclusive, records[lower:upper])
            )
            index += 1
    if not windows:
        issues.append(
            PhysicalTimeWindowPlanningIssue(
                "error",
                "no_full_windows",
                "No full requested window fits production.",
            )
        )
    else:
        for status, code in (
            ("empty", "empty_windows_present"),
            ("partial", "partial_windows_present"),
        ):
            count = sum(w.status == status for w in windows)
            if count:
                issues.append(
                    PhysicalTimeWindowPlanningIssue(
                        "warning",
                        code,
                        f"{count} requested windows are {status}.",
                    )
                )
        if not any(w.sampled_frame_count for w in windows):
            issues.append(
                PhysicalTimeWindowPlanningIssue(
                    "error",
                    "no_resolved_window_samples",
                    "No generated window contains a resolved source sample.",
                )
            )
    return _make_plan(
        temporal, implied, tuple(windows), tuple(issues), boundary_profile
    )


__all__ = [
    "PHYSICAL_TIME_WINDOW_SCHEMA_VERSION",
    "PHYSICAL_TIME_WINDOW_KIND",
    "WINDOW_OVERLAP_PERCENT_ABS_TOLERANCE",
    "WINDOW_OVERLAP_PERCENT_REL_TOLERANCE",
    "PhysicalTimeWindowStatus",
    "PhysicalTimeWindowPlanStatus",
    "ResolvedPhysicalTimeWindow",
    "PhysicalTimeWindowPlanningIssue",
    "ResolvedPhysicalTimeWindowPlan",
    "plan_physical_time_windows",
]
