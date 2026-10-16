"""Pure sparse specialized windows; Stage 28.A is the only episode engine."""

from dataclasses import asdict, dataclass
from decimal import Context, Decimal, localcontext
from typing import Any, ClassVar, Literal

from mania.preprocessing.contact_episodes import compute_window_contact_episodes
from mania.preprocessing.molecular_partner_entities import _require_index, _require_text
from mania.preprocessing.physical_time_sampling import ResolvedPhysicalTimeSamplingPlan
from mania.preprocessing.physical_time_windows import ResolvedPhysicalTimeWindowPlan
from mania.preprocessing.protein_edge_windows import (
    _occupancy,
    _require_number,
    _require_window_identity,
)
from mania.preprocessing.protein_glycan_contacts import (
    ProteinGlycanContactFrameResult,
    ProteinGlycanContactObservation,
)
from mania.preprocessing.protein_lipid_contacts import (
    ProteinLipidContactFrameResult,
    ProteinLipidContactObservation,
)

METRIC_COLUMNS = (
    "n_contact_frames",
    "occupancy",
    "n_contact_episodes",
    "mean_episode_length_ns",
    "max_episode_length_ns",
    "distance_mean_A",
    "distance_min_A",
)


@dataclass(frozen=True)
class _ProteinPartnerWindowMetric:
    window_id: str
    window_index: int
    protein_residue_index: int
    protein_residue_id: int | str | None
    protein_resname: str
    protein_segid: str | None
    n_resolved_frames_in_window: int
    n_contact_frames: int
    occupancy: float
    n_contact_episodes: int
    mean_episode_length_ns: float
    max_episode_length_ns: float
    distance_mean_A: float
    distance_min_A: float

    def __post_init__(self) -> None:
        _require_window_identity(self.window_id, self.window_index)
        for name in (
            "n_resolved_frames_in_window",
            "n_contact_frames",
            "n_contact_episodes",
        ):
            _require_index(getattr(self, name), name)
        if not 0 < self.n_contact_frames <= self.n_resolved_frames_in_window:
            raise ValueError(
                "Ordinary positive count must be within resolved frame count"
            )
        if not 0 < self.n_contact_episodes <= self.n_contact_frames:
            raise ValueError("Episode count must be within positive frame count")
        for name in METRIC_COLUMNS[1:]:
            if name == "n_contact_episodes":
                continue
            _require_number(getattr(self, name), name)
            object.__setattr__(self, name, float(getattr(self, name)))
        if self.occupancy != _occupancy(
            self.n_contact_frames, self.n_resolved_frames_in_window
        ):
            raise ValueError("Occupancy must use resolved-frame denominator")
        if self.max_episode_length_ns < self.mean_episode_length_ns:
            raise ValueError("Maximum lifetime must be at least the mean")
        if self.distance_min_A > self.distance_mean_A:
            raise ValueError("Minimum distance must not exceed the mean")
        if self.n_contact_frames == 1 and self.distance_min_A != self.distance_mean_A:
            raise ValueError(
                "One positive frame requires identical distance mean/minimum"
            )
        if (
            self.n_contact_episodes == 1
            and self.mean_episode_length_ns != self.max_episode_length_ns
        ):
            raise ValueError("One episode requires identical lifetime mean/maximum")
        if (
            self.n_contact_frames == self.n_contact_episodes
            and self.max_episode_length_ns != 0
        ):
            raise ValueError("Single-frame episodes must have zero duration")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for name, value in data.items():
            if isinstance(value, tuple):
                data[name] = list(value)
        return data


@dataclass(frozen=True)
class ProteinLipidWindowMetric(_ProteinPartnerWindowMetric):
    lipid_partner_id: str
    lipid_partner_name: str
    lipid_component_residue_indexes: tuple[int, ...]

    def __post_init__(self) -> None:
        super().__post_init__()
        ProteinLipidContactObservation(
            0,
            None,
            self.protein_residue_index,
            self.protein_residue_id,
            self.protein_resname,
            self.protein_segid,
            self.lipid_partner_id,
            self.lipid_partner_name,
            self.lipid_component_residue_indexes,
            self.distance_mean_A,
        )


@dataclass(frozen=True)
class ProteinGlycanWindowMetric(_ProteinPartnerWindowMetric):
    glycan_partner_id: str
    glycan_partner_name: str
    glycan_component_residue_indexes: tuple[int, ...]
    carrier_residue_index: int
    first_sugar_residue_index: int
    linkage_evidence: str
    carrier_link_atom_index: int | None
    first_sugar_link_atom_index: int | None

    def __post_init__(self) -> None:
        super().__post_init__()
        # Ordinary metrics must never materialize a covalently excluded pair.
        ProteinGlycanContactObservation(
            0,
            None,
            self.protein_residue_index,
            self.protein_residue_id,
            self.protein_resname,
            self.protein_segid,
            self.glycan_partner_id,
            self.glycan_partner_name,
            self.glycan_component_residue_indexes,
            self.carrier_residue_index,
            self.first_sugar_residue_index,
            self.linkage_evidence,
            self.carrier_link_atom_index,
            self.first_sugar_link_atom_index,
            False,
            None,
            self.distance_mean_A,
        )


def metric_key(
    metric: ProteinLipidWindowMetric | ProteinGlycanWindowMetric,
) -> tuple[int, str]:
    partner_id = (
        metric.lipid_partner_id
        if isinstance(metric, ProteinLipidWindowMetric)
        else metric.glycan_partner_id
    )
    return metric.protein_residue_index, partner_id


@dataclass(frozen=True)
class WindowSpecializedContactStatistics:
    window_id: str
    window_index: int
    requested_sample_count: int
    resolved_frame_count: int
    missing_sample_count: int
    coverage_fraction: float
    metrics: tuple[ProteinLipidWindowMetric | ProteinGlycanWindowMetric, ...]
    excluded_raw_observation_count: int = 0

    def __post_init__(self) -> None:
        _require_window_identity(self.window_id, self.window_index)
        for name in (
            "requested_sample_count",
            "resolved_frame_count",
            "missing_sample_count",
            "excluded_raw_observation_count",
        ):
            _require_index(getattr(self, name), name)
        if (
            self.requested_sample_count
            != self.resolved_frame_count + self.missing_sample_count
        ):
            raise ValueError("Window counts must agree")
        _require_number(self.coverage_fraction, "coverage_fraction")
        if self.coverage_fraction != (
            self.resolved_frame_count / self.requested_sample_count
            if self.requested_sample_count
            else 0.0
        ):
            raise ValueError("Window coverage must agree")
        if not isinstance(self.metrics, tuple) or any(
            type(m) not in (ProteinLipidWindowMetric, ProteinGlycanWindowMetric)
            for m in self.metrics
        ):
            raise ValueError("Invalid specialized metrics")
        keys = tuple(metric_key(m) for m in self.metrics)
        if keys != tuple(sorted(set(keys))):
            raise ValueError(
                "Metrics must be unique and ordered by protein index and partner ID"
            )
        if any(
            (m.window_id, m.window_index, m.n_resolved_frames_in_window)
            != (self.window_id, self.window_index, self.resolved_frame_count)
            for m in self.metrics
        ):
            raise ValueError("Metrics must match parent window")

    @property
    def observed_row_count(self) -> int:
        return len(self.metrics)

    def to_dict(self) -> dict[str, object]:
        return {
            **asdict(self),
            "observed_row_count": self.observed_row_count,
            "metrics": [m.to_dict() for m in self.metrics],
        }


@dataclass(frozen=True)
class _SpecializedWindowAggregation:
    execution_condition: str
    status: Literal["complete", "partial"]
    windows: tuple[WindowSpecializedContactStatistics, ...]
    metric_type: ClassVar[type[_ProteinPartnerWindowMetric]]

    def __post_init__(self) -> None:
        _require_text(self.execution_condition, "execution_condition")
        if self.status not in ("complete", "partial"):
            raise ValueError("Status must describe physical coverage only")
        if not isinstance(self.windows, tuple) or any(
            type(w) is not WindowSpecializedContactStatistics for w in self.windows
        ):
            raise ValueError("Invalid window summaries")
        if any(w.window_index != i for i, w in enumerate(self.windows)):
            raise ValueError("Windows must preserve Stage 27 ordering")
        if any(
            type(m) is not self.metric_type for w in self.windows for m in w.metrics
        ):
            raise ValueError("Aggregation must contain only its own partner kind")
        if (
            self.metric_type is ProteinLipidWindowMetric
            and self.excluded_raw_observation_count
        ):
            raise ValueError("Lipids have no covalent exclusion counter")

    @property
    def window_count(self) -> int:
        return len(self.windows)

    @property
    def observed_row_count(self) -> int:
        return sum(w.observed_row_count for w in self.windows)

    @property
    def excluded_raw_observation_count(self) -> int:
        """Sum of per-window exclusions; overlapping windows count independently."""
        return sum(w.excluded_raw_observation_count for w in self.windows)

    def to_dict(self) -> dict[str, object]:
        return {
            "execution_condition": self.execution_condition,
            "status": self.status,
            "window_count": self.window_count,
            "observed_row_count": self.observed_row_count,
            "excluded_raw_observation_count": self.excluded_raw_observation_count,
            "windows": [w.to_dict() for w in self.windows],
        }


@dataclass(frozen=True)
class ProteinLipidWindowAggregation(_SpecializedWindowAggregation):
    metric_type = ProteinLipidWindowMetric


@dataclass(frozen=True)
class ProteinGlycanWindowAggregation(_SpecializedWindowAggregation):
    metric_type = ProteinGlycanWindowMetric


def _aggregate(
    sampling: ResolvedPhysicalTimeSamplingPlan,
    windows: ResolvedPhysicalTimeWindowPlan,
    execution_condition: str,
    frames: Any,
    partner_count: int,
    kind: str,
) -> tuple[WindowSpecializedContactStatistics, ...]:
    if (
        type(sampling) is not ResolvedPhysicalTimeSamplingPlan
        or type(windows) is not ResolvedPhysicalTimeWindowPlan
    ):
        raise ValueError("Exact accepted physical plans required")
    if sampling.status == "failed" or windows.status == "failed":
        raise ValueError("Failed physical plans cannot be aggregated")
    if any(
        getattr(sampling, n) != getattr(windows, n)
        for n in ("requested_production_start_ns", "requested_production_end_ns")
    ):
        raise ValueError("Physical plan production bounds must agree")
    _require_text(execution_condition, "execution_condition")
    _require_index(partner_count, "partner_count")
    model = (
        ProteinLipidContactFrameResult
        if kind == "lipid"
        else ProteinGlycanContactFrameResult
    )
    if not isinstance(frames, tuple) or any(type(f) is not model for f in frames):
        raise ValueError("Exact specialized scientific frame results required")
    selected = tuple(s.source_frame_index for s in sampling.selected_samples)
    if tuple(f.frame_index for f in frames) != (selected if partner_count else ()):
        raise ValueError(
            "Scientific frame indexes must exactly match Stage 27 selection"
        )
    if any(getattr(f, f"{kind}_partner_count") != partner_count for f in frames):
        raise ValueError("Partner count must agree for every scientific frame")
    if len({f.protein_residue_count for f in frames}) > 1:
        raise ValueError("Protein membership count must remain constant")
    by_frame = {f.frame_index: f for f in frames}
    identities: dict[tuple[int, str], dict[str, Any]] = {}
    # Require stable pair source evidence across the whole condition, including
    # excluded raw evidence. This does not turn excluded evidence into negatives.
    for frame in frames:
        for contact in frame.contacts:
            identity = asdict(contact)
            for name in (
                "frame_index",
                "time_ps",
                "minimum_distance_A",
                "standard_summary_excluded",
                "standard_summary_exclusion_reason",
            ):
                identity.pop(name, None)
            key = contact.protein_residue_index, getattr(contact, f"{kind}_partner_id")
            if key in identities and identities[key] != identity:
                raise ValueError("Pair source evidence must remain constant")
            identities[key] = identity
    result = []
    metric_model = (
        ProteinLipidWindowMetric if kind == "lipid" else ProteinGlycanWindowMetric
    )
    for window in windows.windows:
        compute_window_contact_episodes(
            sampling, window, contact_source_frame_indexes=()
        )
        positives: dict[tuple[int, str], list[Any]] = {}
        excluded = 0
        for index in window.source_frame_indexes:
            for contact in by_frame[index].contacts if partner_count else ():
                if kind == "glycan" and contact.standard_summary_excluded:
                    excluded += 1
                    continue
                key = (
                    contact.protein_residue_index,
                    getattr(contact, f"{kind}_partner_id"),
                )
                positives.setdefault(key, []).append(contact)
        metrics = []
        for key, observations in sorted(positives.items()):
            episodes = compute_window_contact_episodes(
                sampling,
                window,
                contact_source_frame_indexes=tuple(c.frame_index for c in observations),
            )
            if (
                episodes.mean_episode_length_ns is None
                or episodes.max_episode_length_ns is None
            ):
                raise ValueError(
                    "Ordinary positive observations require episode durations"
                )
            distances = [Decimal(str(c.minimum_distance_A)) for c in observations]
            with localcontext(Context(prec=max(28, len(str(len(distances))) + 24))):
                mean = float(sum(distances, Decimal(0)) / Decimal(len(distances)))
            metrics.append(
                metric_model(
                    window_id=window.window_id,
                    window_index=window.window_index,
                    **identities[key],
                    n_resolved_frames_in_window=window.sampled_frame_count,
                    n_contact_frames=episodes.n_contact_frames,
                    occupancy=_occupancy(
                        episodes.n_contact_frames, window.sampled_frame_count
                    ),
                    n_contact_episodes=episodes.n_contact_episodes,
                    mean_episode_length_ns=episodes.mean_episode_length_ns,
                    max_episode_length_ns=episodes.max_episode_length_ns,
                    distance_mean_A=mean,
                    distance_min_A=float(min(distances)),
                )
            )
        result.append(
            WindowSpecializedContactStatistics(
                window.window_id,
                window.window_index,
                window.requested_sample_count,
                window.sampled_frame_count,
                window.missing_sample_count,
                window.coverage_fraction,
                tuple(metrics),
                excluded,
            )
        )
    return tuple(result)


def aggregate_protein_lipid_contacts_by_window(
    sampling_plan: ResolvedPhysicalTimeSamplingPlan,
    window_plan: ResolvedPhysicalTimeWindowPlan,
    *,
    execution_condition: str,
    frame_results: tuple[ProteinLipidContactFrameResult, ...],
    partner_count: int,
) -> ProteinLipidWindowAggregation:
    windows = _aggregate(
        sampling_plan,
        window_plan,
        execution_condition,
        frame_results,
        partner_count,
        "lipid",
    )
    return ProteinLipidWindowAggregation(
        execution_condition,
        "complete"
        if sampling_plan.status == window_plan.status == "complete"
        else "partial",
        windows,
    )


def aggregate_protein_glycan_contacts_by_window(
    sampling_plan: ResolvedPhysicalTimeSamplingPlan,
    window_plan: ResolvedPhysicalTimeWindowPlan,
    *,
    execution_condition: str,
    frame_results: tuple[ProteinGlycanContactFrameResult, ...],
    partner_count: int,
) -> ProteinGlycanWindowAggregation:
    windows = _aggregate(
        sampling_plan,
        window_plan,
        execution_condition,
        frame_results,
        partner_count,
        "glycan",
    )
    return ProteinGlycanWindowAggregation(
        execution_condition,
        "complete"
        if sampling_plan.status == window_plan.status == "complete"
        else "partial",
        windows,
    )
