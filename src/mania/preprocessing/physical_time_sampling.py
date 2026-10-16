"""Pure Stage 27.A resolution of a closed physical-time sampling request.

Only production bounds and frame stride are consumed. Window parameters and
workflow integration belong to later stages. See physical_time_sampling_contract.md.
"""

from collections import Counter
from dataclasses import asdict, dataclass
from decimal import Context, Decimal, localcontext
from itertools import pairwise
from math import fsum, isclose, isfinite
from typing import Literal

from mania.dataset_identity import DatasetTemporalParameters
from mania.input_binding import PhysicalRequest

PHYSICAL_TIME_MATCH_ABS_TOLERANCE_PS = 1e-6
PHYSICAL_TIME_MATCH_REL_TOLERANCE = 1e-9

PhysicalTimeSamplingStatus = Literal["complete", "partial", "failed"]


def _require_index(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def _require_number(value: object, name: str, *, signed: bool = False) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite number")
    try:
        valid = isfinite(value) and (signed or value >= 0)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(f"{name} must be finite" + ("" if signed else " and >= 0"))


def _matches(actual: float, requested: float) -> bool:
    return isclose(
        actual,
        requested,
        rel_tol=PHYSICAL_TIME_MATCH_REL_TOLERANCE,
        abs_tol=PHYSICAL_TIME_MATCH_ABS_TOLERANCE_PS,
    )


@dataclass(frozen=True)
class PhysicalTimeSourceFrame:
    """One caller-supplied source index and physical time, without trajectory I/O."""

    frame_index: int
    time_ps: float

    def __post_init__(self) -> None:
        _require_index(self.frame_index, "frame_index")
        _require_number(self.time_ps, "time_ps")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ResolvedPhysicalTimeSample:
    """An actual source frame matched within the public technical tolerance."""

    requested_sample_index: int
    requested_time_ps: float
    source_frame_index: int
    actual_time_ps: float
    time_delta_ps: float

    def __post_init__(self) -> None:
        _require_index(self.requested_sample_index, "requested_sample_index")
        _require_index(self.source_frame_index, "source_frame_index")
        _require_number(self.requested_time_ps, "requested_time_ps")
        _require_number(self.actual_time_ps, "actual_time_ps")
        _require_number(self.time_delta_ps, "time_delta_ps", signed=True)
        if not _matches(self.actual_time_ps, self.requested_time_ps):
            raise ValueError(
                "actual/requested times must match within public tolerance"
            )
        if self.time_delta_ps != self.actual_time_ps - self.requested_time_ps:
            raise ValueError(
                "time_delta_ps must equal actual_time_ps - requested_time_ps"
            )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class MissingPhysicalTimeSample:
    """An unresolved requested target; no source frame is fabricated."""

    requested_sample_index: int
    requested_time_ps: float

    def __post_init__(self) -> None:
        _require_index(self.requested_sample_index, "requested_sample_index")
        _require_number(self.requested_time_ps, "requested_time_ps")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class PhysicalTimeSamplingIssue:
    """A deterministic diagnostic with optional frame/grid indexes."""

    severity: Literal["error", "warning"]
    code: str
    message: str
    frame_index: int | None = None
    requested_sample_index: int | None = None

    def __post_init__(self) -> None:
        if self.severity not in ("error", "warning"):
            raise ValueError("severity must be error or warning")
        for name in ("code", "message"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError(f"{name} must be a non-empty stripped string")
        for name in ("frame_index", "requested_sample_index"):
            value = getattr(self, name)
            if value is not None:
                _require_index(value, name)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _requested_times(
    start_ns: float, end_ns: float, stride_ps: float
) -> tuple[float, ...]:
    values = tuple(Decimal(str(value)) for value in (start_ns, end_ns, stride_ps))
    # Enough precision for exact addition across the whole input exponent range,
    # including ns -> ps. Do not inherit the caller's Decimal precision or traps.
    shifts = (3, 3, 0)
    largest = max(
        value.adjusted() + shift for value, shift in zip(values, shifts, strict=True)
    )
    smallest = min(
        int(value.as_tuple().exponent) + shift
        for value, shift in zip(values, shifts, strict=True)
    )
    with localcontext(Context(prec=max(1, largest - smallest + 2))):
        start, end, stride = values
        target = start * 1000
        end *= 1000
        if not isfinite(float(end)):
            raise ValueError("requested production times must be finite in ps")
        targets: list[float] = []
        while target <= end:
            targets.append(float(target))
            target += stride
    return tuple(targets)


def _effective_stride(
    selected: tuple[ResolvedPhysicalTimeSample, ...], missing_count: int
) -> float | None:
    if missing_count or len(selected) < 2:
        return None
    if any(
        b.requested_sample_index != a.requested_sample_index + 1
        for a, b in pairwise(selected)
    ):
        return None
    return fsum(b.actual_time_ps - a.actual_time_ps for a, b in pairwise(selected)) / (
        len(selected) - 1
    )


def _status(sampled: int, missing: int, fatal: bool) -> PhysicalTimeSamplingStatus:
    if fatal or sampled == 0:
        return "failed"
    return "partial" if missing else "complete"


@dataclass(frozen=True)
class ResolvedPhysicalTimeSamplingPlan:
    """Requested contract and observed resolution, with no QC exclusion policy."""

    status: PhysicalTimeSamplingStatus
    requested_production_start_ns: float
    requested_production_end_ns: float
    requested_frame_stride_ps: float
    match_abs_tolerance_ps: float
    match_rel_tolerance: float
    source_frame_count: int
    source_start_time_ps: float | None
    source_end_time_ps: float | None
    requested_sample_count: int
    sampled_frame_count: int
    missing_sample_count: int
    coverage_fraction: float
    effective_start_time_ps: float | None
    effective_end_time_ps: float | None
    effective_stride_ps: float | None
    selected_samples: tuple[ResolvedPhysicalTimeSample, ...]
    missing_samples: tuple[MissingPhysicalTimeSample, ...]
    issues: tuple[PhysicalTimeSamplingIssue, ...]

    def __post_init__(self) -> None:
        for name in (
            "requested_production_start_ns",
            "requested_production_end_ns",
            "requested_frame_stride_ps",
            "match_abs_tolerance_ps",
            "match_rel_tolerance",
            "coverage_fraction",
        ):
            _require_number(getattr(self, name), name)
        if self.requested_production_end_ns <= self.requested_production_start_ns:
            raise ValueError("requested production interval must be positive")
        if self.requested_frame_stride_ps <= 0:
            raise ValueError("requested_frame_stride_ps must be positive")
        if (
            self.match_abs_tolerance_ps != PHYSICAL_TIME_MATCH_ABS_TOLERANCE_PS
            or self.match_rel_tolerance != PHYSICAL_TIME_MATCH_REL_TOLERANCE
        ):
            raise ValueError("matching tolerances must equal the public constants")
        for name in (
            "source_frame_count",
            "requested_sample_count",
            "sampled_frame_count",
            "missing_sample_count",
        ):
            _require_index(getattr(self, name), name)
        for name, record_type in (
            ("selected_samples", ResolvedPhysicalTimeSample),
            ("missing_samples", MissingPhysicalTimeSample),
            ("issues", PhysicalTimeSamplingIssue),
        ):
            records = getattr(self, name)
            if not isinstance(records, tuple) or any(
                type(record) is not record_type for record in records
            ):
                raise ValueError(f"{name} must be a tuple of {record_type.__name__}")
        if self.sampled_frame_count != len(self.selected_samples):
            raise ValueError("sampled_frame_count must equal selected record count")
        if self.missing_sample_count != len(self.missing_samples):
            raise ValueError("missing_sample_count must equal missing record count")
        if (
            self.requested_sample_count < 1
            or self.sampled_frame_count + self.missing_sample_count
            != self.requested_sample_count
            or self.sampled_frame_count > self.source_frame_count
        ):
            raise ValueError("requested/source/sample counts are inconsistent")
        if (
            self.coverage_fraction
            != self.sampled_frame_count / self.requested_sample_count
        ):
            raise ValueError("coverage_fraction must equal sampled / requested count")

        targets = _requested_times(
            self.requested_production_start_ns,
            self.requested_production_end_ns,
            self.requested_frame_stride_ps,
        )
        if self.requested_sample_count != len(targets):
            raise ValueError(
                "requested_sample_count must equal closed Decimal grid size"
            )
        seen: set[int] = set()
        for records in (self.selected_samples, self.missing_samples):
            previous_index = -1
            for record in records:
                index = record.requested_sample_index
                if index in seen or not previous_index < index < len(targets):
                    raise ValueError("sample records must partition the grid in order")
                if record.requested_time_ps != targets[index]:
                    raise ValueError(
                        "requested_time_ps must equal its Decimal grid target"
                    )
                seen.add(index)
                previous_index = index
        if len({s.source_frame_index for s in self.selected_samples}) != len(
            self.selected_samples
        ):
            raise ValueError("a source frame may be selected at most once")
        if any(
            b.actual_time_ps <= a.actual_time_ps
            for a, b in pairwise(self.selected_samples)
        ):
            raise ValueError("selected actual times must be strictly increasing")
        for name in (
            "source_start_time_ps",
            "source_end_time_ps",
            "effective_start_time_ps",
            "effective_end_time_ps",
            "effective_stride_ps",
        ):
            value = getattr(self, name)
            if value is not None:
                _require_number(value, name)
        if self.source_frame_count == 0:
            if (
                self.source_start_time_ps is not None
                or self.source_end_time_ps is not None
            ):
                raise ValueError("empty source requires absent source extent")
        elif (
            self.source_start_time_ps is None
            or self.source_end_time_ps is None
            or self.source_start_time_ps > self.source_end_time_ps
        ):
            raise ValueError("nonempty source requires its minimum/maximum time extent")
        for sample in self.selected_samples:
            if (
                self.source_start_time_ps is None
                or self.source_end_time_ps is None
                or not self.source_start_time_ps
                <= sample.actual_time_ps
                <= self.source_end_time_ps
            ):
                raise ValueError(
                    "selected actual time must lie within the source extent"
                )
        expected_start = (
            self.selected_samples[0].actual_time_ps if self.selected_samples else None
        )
        expected_end = (
            self.selected_samples[-1].actual_time_ps if self.selected_samples else None
        )
        if (self.effective_start_time_ps, self.effective_end_time_ps) != (
            expected_start,
            expected_end,
        ):
            raise ValueError("effective bounds must describe first/last selected times")
        if self.effective_stride_ps != _effective_stride(
            self.selected_samples, self.missing_sample_count
        ):
            raise ValueError(
                "effective_stride_ps must describe complete actual spacing"
            )
        for issue in self.issues:
            if (
                issue.requested_sample_index is not None
                and issue.requested_sample_index >= self.requested_sample_count
            ):
                raise ValueError(
                    "issue requested_sample_index must lie within the grid"
                )
        if self.status != _status(
            self.sampled_frame_count,
            self.missing_sample_count,
            any(issue.severity == "error" for issue in self.issues),
        ):
            raise ValueError(
                "status must agree with resolution counts and fatal issues"
            )

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["selected_samples"] = [
            record.to_dict() for record in self.selected_samples
        ]
        result["missing_samples"] = [
            record.to_dict() for record in self.missing_samples
        ]
        result["issues"] = [issue.to_dict() for issue in self.issues]
        return result


def _source_issues(
    source: tuple[PhysicalTimeSourceFrame, ...],
) -> list[PhysicalTimeSamplingIssue]:
    if not source:
        return [
            PhysicalTimeSamplingIssue(
                "error", "empty_source_time_axis", "Source time axis is empty."
            )
        ]
    issues: list[PhysicalTimeSamplingIssue] = []
    seen: set[int] = set()
    first_duplicate: int | None = None
    first_non_monotonic: int | None = None
    duplicate_count = non_monotonic_count = 0
    previous_time = -1.0
    for frame in source:
        if frame.frame_index in seen:
            duplicate_count += 1
            if first_duplicate is None:
                first_duplicate = frame.frame_index
        if frame.time_ps <= previous_time:
            non_monotonic_count += 1
            if first_non_monotonic is None:
                first_non_monotonic = frame.frame_index
        seen.add(frame.frame_index)
        previous_time = frame.time_ps
    if duplicate_count:
        issues.append(
            PhysicalTimeSamplingIssue(
                "error",
                "duplicate_source_frame_index",
                f"Source axis contains {duplicate_count} repeated frame indexes.",
                frame_index=first_duplicate,
            )
        )
    if non_monotonic_count:
        issues.append(
            PhysicalTimeSamplingIssue(
                "error",
                "non_monotonic_source_time",
                f"Source axis contains {non_monotonic_count} "
                "non-increasing time steps.",
                frame_index=first_non_monotonic,
            )
        )
    return issues


def resolve_physical_time_sampling(
    source_frames: tuple[PhysicalTimeSourceFrame, ...],
    *,
    temporal: DatasetTemporalParameters | PhysicalRequest,
) -> ResolvedPhysicalTimeSamplingPlan:
    """Resolve closed Decimal-grid targets without snapping, clamping, or windows.

    Invalid source axes resolve no targets. Ambiguities retain only independent,
    unique matches, and always fail the plan. Both targets in a source reuse
    conflict remain missing; grid order never breaks a tie.
    """
    if not isinstance(source_frames, tuple):
        raise ValueError("source_frames must be a tuple of PhysicalTimeSourceFrame")
    if any(type(frame) is not PhysicalTimeSourceFrame for frame in source_frames):
        raise ValueError("source_frames must contain only PhysicalTimeSourceFrame")
    if type(temporal) not in (DatasetTemporalParameters, PhysicalRequest):
        raise ValueError(
            "temporal must be exact DatasetTemporalParameters or PhysicalRequest"
        )
    if type(temporal) is PhysicalRequest:
        PhysicalRequest.model_validate(temporal.model_dump())
    targets = _requested_times(
        temporal.production_start_ns,
        temporal.production_end_ns,
        temporal.frame_stride_ps,
    )
    issues = _source_issues(source_frames)
    # Monotonic candidate bounds advance at most N times each: O(N + M).
    # Keep bounds to detect source reuse even across a multi-frame ambiguity.
    bounds: list[tuple[int, int]] = []
    usage_changes: Counter[int] = Counter()
    lower = upper = 0
    if not issues:
        for target in targets:
            while lower < len(source_frames):
                actual = source_frames[lower].time_ps
                if actual >= target or _matches(actual, target):
                    break
                lower += 1
            upper = max(lower, upper)
            while upper < len(source_frames) and _matches(
                source_frames[upper].time_ps, target
            ):
                upper += 1
            bounds.append((lower, upper))
            if upper > lower:
                usage_changes[lower] += 1
                usage_changes[upper] -= 1
    usage: list[int] = []
    count = 0
    for index in range(len(source_frames)):
        count += usage_changes[index]
        usage.append(count)
    selected: list[ResolvedPhysicalTimeSample] = []
    missing: list[MissingPhysicalTimeSample] = []
    ambiguous_indexes: list[int] = []
    for index, target in enumerate(targets):
        lo, hi = bounds[index] if bounds else (0, 0)
        if hi - lo == 1 and usage[lo] == 1:
            frame = source_frames[lo]
            selected.append(
                ResolvedPhysicalTimeSample(
                    index,
                    target,
                    frame.frame_index,
                    frame.time_ps,
                    frame.time_ps - target,
                )
            )
        else:
            missing.append(MissingPhysicalTimeSample(index, target))
            if hi > lo:
                ambiguous_indexes.append(index)
    if ambiguous_indexes:
        issues.append(
            PhysicalTimeSamplingIssue(
                "error",
                "ambiguous_time_match",
                f"{len(ambiguous_indexes)} requested targets have multiple source "
                "matches "
                "or share a matching source frame with another target.",
                requested_sample_index=ambiguous_indexes[0],
            )
        )
    if missing:
        issues.append(
            PhysicalTimeSamplingIssue(
                "warning",
                "requested_samples_missing",
                f"{len(missing)} of {len(targets)} requested samples are unresolved.",
            )
        )
    if not selected:
        issues.append(
            PhysicalTimeSamplingIssue(
                "error",
                "no_requested_samples_resolved",
                "No requested samples resolved to unique source frames.",
            )
        )
    selected_tuple = tuple(selected)
    return ResolvedPhysicalTimeSamplingPlan(
        status=_status(
            len(selected),
            len(missing),
            any(issue.severity == "error" for issue in issues),
        ),
        requested_production_start_ns=temporal.production_start_ns,
        requested_production_end_ns=temporal.production_end_ns,
        requested_frame_stride_ps=temporal.frame_stride_ps,
        match_abs_tolerance_ps=PHYSICAL_TIME_MATCH_ABS_TOLERANCE_PS,
        match_rel_tolerance=PHYSICAL_TIME_MATCH_REL_TOLERANCE,
        source_frame_count=len(source_frames),
        source_start_time_ps=min(
            (frame.time_ps for frame in source_frames), default=None
        ),
        source_end_time_ps=max(
            (frame.time_ps for frame in source_frames), default=None
        ),
        requested_sample_count=len(targets),
        sampled_frame_count=len(selected),
        missing_sample_count=len(missing),
        coverage_fraction=len(selected) / len(targets),
        effective_start_time_ps=selected[0].actual_time_ps if selected else None,
        effective_end_time_ps=selected[-1].actual_time_ps if selected else None,
        effective_stride_ps=_effective_stride(selected_tuple, len(missing)),
        selected_samples=selected_tuple,
        missing_samples=tuple(missing),
        issues=tuple(issues),
    )


__all__ = [
    "PHYSICAL_TIME_MATCH_ABS_TOLERANCE_PS",
    "PHYSICAL_TIME_MATCH_REL_TOLERANCE",
    "MissingPhysicalTimeSample",
    "PhysicalTimeSamplingIssue",
    "PhysicalTimeSamplingStatus",
    "PhysicalTimeSourceFrame",
    "ResolvedPhysicalTimeSample",
    "ResolvedPhysicalTimeSamplingPlan",
    "resolve_physical_time_sampling",
]
