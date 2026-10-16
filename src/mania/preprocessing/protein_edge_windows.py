"""Pure Stage 28.B sparse protein edges over accepted physical-time windows.

Only successfully computed per-frame contacts supply presence. Stage 28.A owns
all episode semantics; resolved window frames alone supply occupancy denominators.
See docs/protein_edge_window_aggregation_contract.md.
"""

from dataclasses import asdict, dataclass, field
from decimal import Context, Decimal, localcontext
from math import isfinite
from typing import Literal

from mania.preprocessing.contact_episodes import (
    ContactEpisodeComputationError,
    WindowContactEpisodeSummary,
    compute_window_contact_episodes,
)
from mania.preprocessing.physical_time_sampling import ResolvedPhysicalTimeSamplingPlan
from mania.preprocessing.physical_time_windows import (
    ResolvedPhysicalTimeWindow,
    ResolvedPhysicalTimeWindowPlan,
)
from mania.preprocessing.trajectory_contacts import (
    PreprocessingConditionContactsResult,
    PreprocessingContactDetectionOptions,
    PreprocessingContactFrameResult,
    PreprocessingContactPairResult,
)

PROTEIN_EDGE_WINDOW_SCHEMA_VERSION = "mania.protein_edge_window_aggregation.v0.1"
PROTEIN_EDGE_WINDOW_KIND = "mania_protein_edge_window_aggregation"

ProteinEdgeWindowAggregationStatus = Literal["complete", "partial"]
_EdgeKey = tuple[int, int, str]


class ProteinEdgeWindowAggregationError(ValueError):
    """Invalid physical coverage, contact evidence, or aggregated metric."""


def _require_index(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProteinEdgeWindowAggregationError(
            f"{name} must be a non-negative integer"
        )


def _require_text(value: object, name: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ProteinEdgeWindowAggregationError(
            f"{name} must be a non-empty stripped string"
        )


def _require_residue_id(value: object, name: str) -> None:
    if value is None or (isinstance(value, int) and not isinstance(value, bool)):
        return
    if isinstance(value, str):
        _require_text(value, name)
        return
    raise ProteinEdgeWindowAggregationError(
        f"{name} must be an int, non-empty stripped string, or None"
    )


def _require_number(value: object, name: str) -> None:
    valid = False
    if not isinstance(value, bool) and isinstance(value, (int, float)):
        try:
            valid = isfinite(value) and value >= 0
        except OverflowError:
            pass
    if not valid:
        raise ProteinEdgeWindowAggregationError(
            f"{name} must be finite and non-negative"
        )


def _occupancy(numerator: int, denominator: int) -> float:
    # Independent of caller Decimal precision, rounding, and traps. Retain
    # enough quotient digits for the single conversion to the public float.
    with localcontext(Context(prec=max(28, len(str(denominator)) + 20))):
        return float(Decimal(numerator) / Decimal(denominator))


def _require_window_identity(window_id: str, window_index: int) -> None:
    _require_text(window_id, "window_id")
    _require_index(window_index, "window_index")
    if window_id != f"window_{window_index + 1:04d}":
        raise ProteinEdgeWindowAggregationError(
            "window_id must match the Stage 27 window_index naming convention"
        )


@dataclass(frozen=True)
class ProteinEdgeWindowMetric:
    """One observed undirected residue pair/type in one resolved window."""

    window_id: str
    window_index: int
    source_residue_index: int
    target_residue_index: int
    source_residue_id: int | str | None
    target_residue_id: int | str | None
    source_resname: str
    target_resname: str
    source_segid: str | None
    target_segid: str | None
    edge_type: str
    n_resolved_frames_in_window: int
    n_contact_frames: int
    occupancy: float
    n_contact_episodes: int
    mean_episode_length_ns: float
    max_episode_length_ns: float
    edge_weight: float

    def __post_init__(self) -> None:
        _require_text(self.window_id, "window_id")
        for name in (
            "window_index",
            "source_residue_index",
            "target_residue_index",
            "n_resolved_frames_in_window",
            "n_contact_frames",
            "n_contact_episodes",
        ):
            _require_index(getattr(self, name), name)
        if self.source_residue_index >= self.target_residue_index:
            raise ProteinEdgeWindowAggregationError(
                "source residue index must be less than target residue index"
            )
        for name in ("source_residue_id", "target_residue_id"):
            _require_residue_id(getattr(self, name), name)
        for name in ("source_resname", "target_resname", "edge_type"):
            _require_text(getattr(self, name), name)
        for name in ("source_segid", "target_segid"):
            value = getattr(self, name)
            if value is not None:
                _require_text(value, name)
        if not 0 < self.n_contact_frames <= self.n_resolved_frames_in_window:
            raise ProteinEdgeWindowAggregationError(
                "contact count must be positive and at most resolved frame count"
            )
        if not 0 < self.n_contact_episodes <= self.n_contact_frames:
            raise ProteinEdgeWindowAggregationError(
                "episode count must be positive and at most contact frame count"
            )
        for name in (
            "occupancy",
            "mean_episode_length_ns",
            "max_episode_length_ns",
            "edge_weight",
        ):
            _require_number(getattr(self, name), name)
            object.__setattr__(self, name, float(getattr(self, name)))
        if not 0 < self.occupancy <= 1 or self.occupancy != _occupancy(
            self.n_contact_frames, self.n_resolved_frames_in_window
        ):
            raise ProteinEdgeWindowAggregationError(
                "occupancy must equal the Decimal contact/resolved frame ratio"
            )
        if self.max_episode_length_ns < self.mean_episode_length_ns:
            raise ProteinEdgeWindowAggregationError(
                "maximum episode length must be at least mean episode length"
            )
        if self.edge_weight != self.occupancy:
            raise ProteinEdgeWindowAggregationError("edge_weight must equal occupancy")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _edge_order(edge: ProteinEdgeWindowMetric) -> tuple[str, int, int]:
    return edge.edge_type, edge.source_residue_index, edge.target_residue_index


@dataclass(frozen=True)
class WindowProteinEdgeStatistics:
    """Physical coverage and sparse observed edges, including empty windows."""

    window_id: str
    window_index: int
    requested_sample_count: int
    resolved_frame_count: int
    missing_sample_count: int
    coverage_fraction: float
    edge_count: int
    edges: tuple[ProteinEdgeWindowMetric, ...]

    def __post_init__(self) -> None:
        _require_window_identity(self.window_id, self.window_index)
        for name in (
            "requested_sample_count",
            "resolved_frame_count",
            "missing_sample_count",
            "edge_count",
        ):
            _require_index(getattr(self, name), name)
        if self.requested_sample_count != (
            self.resolved_frame_count + self.missing_sample_count
        ):
            raise ProteinEdgeWindowAggregationError(
                "requested count must equal resolved plus missing counts"
            )
        _require_number(self.coverage_fraction, "coverage_fraction")
        # Preserve Stage 27 coverage arithmetic, including zero requested targets.
        coverage = (
            self.resolved_frame_count / self.requested_sample_count
            if self.requested_sample_count
            else 0.0
        )
        if self.coverage_fraction != coverage:
            raise ProteinEdgeWindowAggregationError(
                "coverage must equal resolved/requested count, or zero"
            )
        object.__setattr__(self, "coverage_fraction", float(self.coverage_fraction))
        if not isinstance(self.edges, tuple) or any(
            type(edge) is not ProteinEdgeWindowMetric for edge in self.edges
        ):
            raise ProteinEdgeWindowAggregationError(
                "edges must be a tuple of exact ProteinEdgeWindowMetric records"
            )
        if self.edge_count != len(self.edges):
            raise ProteinEdgeWindowAggregationError("edge_count must equal edge count")
        for edge in self.edges:
            if (edge.window_id, edge.window_index) != (
                self.window_id,
                self.window_index,
            ):
                raise ProteinEdgeWindowAggregationError(
                    "every edge must belong to this exact window"
                )
            if edge.n_resolved_frames_in_window != self.resolved_frame_count:
                raise ProteinEdgeWindowAggregationError(
                    "every edge denominator must equal resolved_frame_count"
                )
        keys = tuple(_edge_order(edge) for edge in self.edges)
        if keys != tuple(sorted(set(keys))):
            raise ProteinEdgeWindowAggregationError(
                "edges must be unique and ordered by type, source index, target index"
            )

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["edges"] = [edge.to_dict() for edge in self.edges]
        return result


@dataclass(frozen=True)
class ProteinEdgeWindowAggregation:
    """One execution condition; status describes physical coverage only."""

    schema_version: str = field(default=PROTEIN_EDGE_WINDOW_SCHEMA_VERSION, init=False)
    kind: str = field(default=PROTEIN_EDGE_WINDOW_KIND, init=False)
    status: ProteinEdgeWindowAggregationStatus
    execution_condition: str
    window_count: int
    observed_edge_row_count: int
    windows: tuple[WindowProteinEdgeStatistics, ...]

    def __post_init__(self) -> None:
        if self.status not in ("complete", "partial"):
            raise ProteinEdgeWindowAggregationError(
                "status must be complete or partial"
            )
        _require_text(self.execution_condition, "execution_condition")
        _require_index(self.window_count, "window_count")
        _require_index(self.observed_edge_row_count, "observed_edge_row_count")
        if not isinstance(self.windows, tuple) or any(
            type(window) is not WindowProteinEdgeStatistics for window in self.windows
        ):
            raise ProteinEdgeWindowAggregationError(
                "windows must be a tuple of exact WindowProteinEdgeStatistics records"
            )
        if self.window_count != len(self.windows):
            raise ProteinEdgeWindowAggregationError(
                "window_count must equal window count"
            )
        if self.observed_edge_row_count != sum(w.edge_count for w in self.windows):
            raise ProteinEdgeWindowAggregationError(
                "observed_edge_row_count must equal summed window edge counts"
            )
        if any(w.window_index != i for i, w in enumerate(self.windows)):
            raise ProteinEdgeWindowAggregationError(
                "windows must preserve consecutive Stage 27 indexes and IDs"
            )

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["windows"] = [window.to_dict() for window in self.windows]
        return result


@dataclass(frozen=True)
class _CanonicalEdge:
    source_residue_index: int
    target_residue_index: int
    source_residue_id: int | str | None
    target_residue_id: int | str | None
    source_resname: str
    target_resname: str
    source_segid: str | None
    target_segid: str | None
    edge_type: str

    @property
    def key(self) -> _EdgeKey:
        return self.source_residue_index, self.target_residue_index, self.edge_type


def _canonical_edge(contact: PreprocessingContactPairResult) -> _CanonicalEdge:
    source, target = "source", "target"
    if contact.source_residue_index > contact.target_residue_index:
        source, target = target, source
    return _CanonicalEdge(
        **{
            f"{side}_{name}": getattr(contact, f"{original}_{name}")
            for name in ("residue_index", "residue_id", "resname", "segid")
            for side, original in (("source", source), ("target", target))
        },
        edge_type=contact.edge_type,
    )


def _episodes(
    sampling_plan: ResolvedPhysicalTimeSamplingPlan,
    window: ResolvedPhysicalTimeWindow,
    indexes: tuple[int, ...],
) -> WindowContactEpisodeSummary:
    try:
        return compute_window_contact_episodes(
            sampling_plan, window, contact_source_frame_indexes=indexes
        )
    except ContactEpisodeComputationError as exc:
        raise ProteinEdgeWindowAggregationError(str(exc)) from None


def aggregate_protein_edges_by_window(
    sampling_plan: ResolvedPhysicalTimeSamplingPlan,
    window_plan: ResolvedPhysicalTimeWindowPlan,
    *,
    contacts_result: PreprocessingConditionContactsResult,
) -> ProteinEdgeWindowAggregation:
    """Aggregate already computed protein contacts without I/O or time matching."""
    for value, model, name in (
        (sampling_plan, ResolvedPhysicalTimeSamplingPlan, "sampling_plan"),
        (window_plan, ResolvedPhysicalTimeWindowPlan, "window_plan"),
        (contacts_result, PreprocessingConditionContactsResult, "contacts_result"),
    ):
        if type(value) is not model:
            raise ProteinEdgeWindowAggregationError(
                f"{name} must be exact {model.__name__}"
            )
    if sampling_plan.status == "failed" or window_plan.status == "failed":
        raise ProteinEdgeWindowAggregationError("physical plans must not be failed")
    if (
        type(contacts_result.options) is not PreprocessingContactDetectionOptions
        or contacts_result.options.contact_selection != "protein"
    ):
        raise ProteinEdgeWindowAggregationError(
            "contacts must use exact detection options with contact_selection protein"
        )
    if any(
        type(frame) is not PreprocessingContactFrameResult
        for frame in contacts_result.frame_results
    ):
        raise ProteinEdgeWindowAggregationError(
            "contact frames must be exact PreprocessingContactFrameResult records"
        )
    if contacts_result.passed is not True:
        raise ProteinEdgeWindowAggregationError(
            "contact computation must be computed and passed for every selected frame"
        )
    selected = tuple(s.source_frame_index for s in sampling_plan.selected_samples)
    frames = {frame.frame_index: frame for frame in contacts_result.frame_results}
    if set(frames) != set(selected):
        raise ProteinEdgeWindowAggregationError(
            "contact frame indexes must exactly match selected source frame indexes"
        )
    if any(
        type(contact) is not PreprocessingContactPairResult
        for index in selected
        for contact in frames[index].contacts
    ):
        raise ProteinEdgeWindowAggregationError(
            "contacts must be exact PreprocessingContactPairResult records"
        )
    if any(
        getattr(window_plan, name) != getattr(sampling_plan, name)
        for name in ("requested_production_start_ns", "requested_production_end_ns")
    ):
        raise ProteinEdgeWindowAggregationError(
            "window and sampling plans must have identical requested production bounds"
        )
    # Validate every window even when its sparse observed-edge universe is empty.
    for window in window_plan.windows:
        _episodes(sampling_plan, window, ())

    statistics: list[WindowProteinEdgeStatistics] = []
    for window in window_plan.windows:
        identities: dict[_EdgeKey, _CanonicalEdge] = {}
        positives: dict[_EdgeKey, list[int]] = {}
        for index in window.source_frame_indexes:
            seen: set[_EdgeKey] = set()
            for contact in frames[index].contacts:
                edge = _canonical_edge(contact)
                key = edge.key
                if key in identities and identities[key] != edge:
                    raise ProteinEdgeWindowAggregationError(
                        "canonical edge residue metadata must agree within a window"
                    )
                identities[key] = edge
                if key not in seen:
                    positives.setdefault(key, []).append(index)
                    seen.add(key)
        metrics: list[ProteinEdgeWindowMetric] = []
        for key in sorted(identities, key=lambda key: (key[2], key[0], key[1])):
            summary = _episodes(sampling_plan, window, tuple(positives[key]))
            if (
                summary.mean_episode_length_ns is None
                or summary.max_episode_length_ns is None
            ):
                raise ProteinEdgeWindowAggregationError(
                    "an observed edge must have episode lifetimes"
                )
            occupancy = _occupancy(summary.n_contact_frames, window.sampled_frame_count)
            metrics.append(
                ProteinEdgeWindowMetric(
                    window_id=window.window_id,
                    window_index=window.window_index,
                    **asdict(identities[key]),
                    n_resolved_frames_in_window=window.sampled_frame_count,
                    n_contact_frames=summary.n_contact_frames,
                    occupancy=occupancy,
                    n_contact_episodes=summary.n_contact_episodes,
                    mean_episode_length_ns=summary.mean_episode_length_ns,
                    max_episode_length_ns=summary.max_episode_length_ns,
                    edge_weight=occupancy,
                )
            )
        statistics.append(
            WindowProteinEdgeStatistics(
                window_id=window.window_id,
                window_index=window.window_index,
                requested_sample_count=window.requested_sample_count,
                resolved_frame_count=window.sampled_frame_count,
                missing_sample_count=window.missing_sample_count,
                coverage_fraction=window.coverage_fraction,
                edge_count=len(metrics),
                edges=tuple(metrics),
            )
        )
    return ProteinEdgeWindowAggregation(
        status=(
            "complete"
            if sampling_plan.status == window_plan.status == "complete"
            else "partial"
        ),
        execution_condition=contacts_result.condition_name,
        window_count=len(statistics),
        observed_edge_row_count=sum(w.edge_count for w in statistics),
        windows=tuple(statistics),
    )


__all__ = [
    "PROTEIN_EDGE_WINDOW_KIND",
    "PROTEIN_EDGE_WINDOW_SCHEMA_VERSION",
    "ProteinEdgeWindowAggregation",
    "ProteinEdgeWindowAggregationError",
    "ProteinEdgeWindowAggregationStatus",
    "ProteinEdgeWindowMetric",
    "WindowProteinEdgeStatistics",
    "aggregate_protein_edges_by_window",
]
