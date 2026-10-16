"""Pure Stage 28.A episodes for one contact, resolved window, and trajectory.

Requested sample indexes define continuity; actual resolved times define duration.
Contact detection, occupancy, edge identity, and workflow integration stay outside
this module. See docs/contact_episode_lifetime_contract.md.
"""

from dataclasses import asdict, dataclass, field
from decimal import Context, Decimal, localcontext
from itertools import pairwise
from math import isfinite

from mania.preprocessing.physical_time_sampling import (
    ResolvedPhysicalTimeSample,
    ResolvedPhysicalTimeSamplingPlan,
)
from mania.preprocessing.physical_time_windows import ResolvedPhysicalTimeWindow

CONTACT_EPISODE_SCHEMA_VERSION = "mania.contact_episode_summary.v0.1"
CONTACT_EPISODE_KIND = "mania_contact_episode_summary"
CONTACT_EPISODE_GAP_TOLERANCE = 0


class ContactEpisodeComputationError(ValueError):
    """Invalid episode input or inconsistent sampling/window membership."""


def _require_index(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContactEpisodeComputationError(f"{name} must be a non-negative integer")


def _require_number(value: object, name: str) -> None:
    valid = False
    if not isinstance(value, bool) and isinstance(value, (int, float)):
        try:
            valid = isfinite(value) and value >= 0
        except OverflowError:
            pass
    if not valid:
        raise ContactEpisodeComputationError(f"{name} must be finite and non-negative")


def _require_indexes(value: tuple[int, ...], name: str) -> None:
    if not isinstance(value, tuple):
        raise ContactEpisodeComputationError(f"{name} must be a tuple")
    for index in value:
        _require_index(index, name)
    if any(b <= a for a, b in pairwise(value)):
        raise ContactEpisodeComputationError(f"{name} must be strictly increasing")


def _decimal_context(values: tuple[Decimal, ...]) -> Context:
    # Cover the full exponent span for exact subtraction/summation, with guard
    # digits for averaging before float conversion. Ignore caller precision/traps.
    precision = (
        max(value.adjusted() for value in values)
        - min(int(value.as_tuple().exponent) for value in values)
        + len(str(len(values)))
        + 20
    )
    return Context(prec=max(28, precision))


def _duration_ns(start_ps: float, end_ps: float) -> float:
    values = (Decimal(str(start_ps)), Decimal(str(end_ps)))
    with localcontext(_decimal_context(values)):
        return float((values[1] - values[0]) / 1000)


def _mean_length(episodes: tuple["ContactEpisode", ...]) -> float | None:
    if not episodes:
        return None
    values = tuple(Decimal(str(episode.episode_length_ns)) for episode in episodes)
    with localcontext(_decimal_context(values)):
        return float(sum(values, Decimal(0)) / len(values))


@dataclass(frozen=True)
class ContactEpisode:
    """One maximal run of consecutive contact-positive requested positions."""

    episode_index: int
    start_requested_sample_index: int
    end_requested_sample_index: int
    start_source_frame_index: int
    end_source_frame_index: int
    contact_frame_count: int
    start_actual_time_ps: float
    end_actual_time_ps: float
    episode_length_ns: float
    source_frame_indexes: tuple[int, ...]

    def __post_init__(self) -> None:
        for name in (
            "episode_index",
            "start_requested_sample_index",
            "end_requested_sample_index",
            "start_source_frame_index",
            "end_source_frame_index",
            "contact_frame_count",
        ):
            _require_index(getattr(self, name), name)
        _require_indexes(self.source_frame_indexes, "source_frame_indexes")
        if not self.source_frame_indexes or self.contact_frame_count != len(
            self.source_frame_indexes
        ):
            raise ContactEpisodeComputationError(
                "contact_frame_count must equal a non-empty source tuple length"
            )
        if (
            self.end_requested_sample_index - self.start_requested_sample_index + 1
            != self.contact_frame_count
        ):
            raise ContactEpisodeComputationError(
                "requested index span must equal contact_frame_count"
            )
        if (self.start_source_frame_index, self.end_source_frame_index) != (
            self.source_frame_indexes[0],
            self.source_frame_indexes[-1],
        ):
            raise ContactEpisodeComputationError(
                "source endpoints must match first and last source frame indexes"
            )
        for name in (
            "start_actual_time_ps",
            "end_actual_time_ps",
            "episode_length_ns",
        ):
            _require_number(getattr(self, name), name)
        if self.end_actual_time_ps < self.start_actual_time_ps:
            raise ContactEpisodeComputationError("actual end must be at least start")
        if self.contact_frame_count == 1 and (
            self.end_actual_time_ps != self.start_actual_time_ps
        ):
            raise ContactEpisodeComputationError(
                "a single contact frame must have equal actual time endpoints"
            )
        if self.episode_length_ns != _duration_ns(
            self.start_actual_time_ps, self.end_actual_time_ps
        ):
            raise ContactEpisodeComputationError(
                "episode_length_ns must equal the Decimal actual-time duration"
            )

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["source_frame_indexes"] = list(self.source_frame_indexes)
        return result


@dataclass(frozen=True)
class WindowContactEpisodeSummary:
    """Episode aggregates, with absent lifetimes when no episode exists."""

    schema_version: str = field(default=CONTACT_EPISODE_SCHEMA_VERSION, init=False)
    kind: str = field(default=CONTACT_EPISODE_KIND, init=False)
    window_id: str
    window_index: int
    gap_tolerance: int = field(default=CONTACT_EPISODE_GAP_TOLERANCE, init=False)
    n_contact_frames: int
    n_contact_episodes: int
    mean_episode_length_ns: float | None
    max_episode_length_ns: float | None
    contact_source_frame_indexes: tuple[int, ...]
    episodes: tuple[ContactEpisode, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.window_id, str)
            or not self.window_id
            or self.window_id != self.window_id.strip()
        ):
            raise ContactEpisodeComputationError(
                "window_id must be a non-empty stripped string"
            )
        for name in ("window_index", "n_contact_frames", "n_contact_episodes"):
            _require_index(getattr(self, name), name)
        _require_indexes(
            self.contact_source_frame_indexes, "contact_source_frame_indexes"
        )
        if not isinstance(self.episodes, tuple) or any(
            type(episode) is not ContactEpisode for episode in self.episodes
        ):
            raise ContactEpisodeComputationError(
                "episodes must be a tuple of exact ContactEpisode records"
            )
        if self.n_contact_episodes != len(self.episodes):
            raise ContactEpisodeComputationError(
                "n_contact_episodes must equal episode count"
            )
        if self.n_contact_frames != sum(e.contact_frame_count for e in self.episodes):
            raise ContactEpisodeComputationError(
                "n_contact_frames must equal summed episode contact_frame_count"
            )
        if self.contact_source_frame_indexes != tuple(
            index for episode in self.episodes for index in episode.source_frame_indexes
        ):
            raise ContactEpisodeComputationError(
                "contact_source_frame_indexes must equal ordered episode membership"
            )
        if any(e.episode_index != i for i, e in enumerate(self.episodes)):
            raise ContactEpisodeComputationError(
                "episode indexes must be consecutive from zero"
            )
        if any(
            b.start_requested_sample_index <= a.end_requested_sample_index + 1
            or b.start_actual_time_ps < a.end_actual_time_ps
            for a, b in pairwise(self.episodes)
        ):
            raise ContactEpisodeComputationError(
                "episodes must be ordered with a requested-position gap between them"
            )
        for name, expected in (
            ("mean_episode_length_ns", _mean_length(self.episodes)),
            (
                "max_episode_length_ns",
                max((e.episode_length_ns for e in self.episodes), default=None),
            ),
        ):
            value = getattr(self, name)
            if value is not None:
                _require_number(value, name)
            if value != expected:
                raise ContactEpisodeComputationError(
                    f"{name} must equal its episode aggregate, or None without episodes"
                )

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["contact_source_frame_indexes"] = list(self.contact_source_frame_indexes)
        result["episodes"] = [episode.to_dict() for episode in self.episodes]
        return result


def _window_samples(
    sampling_plan: ResolvedPhysicalTimeSamplingPlan,
    window: ResolvedPhysicalTimeWindow,
) -> tuple[ResolvedPhysicalTimeSample, ...]:
    selected = {s.requested_sample_index: s for s in sampling_plan.selected_samples}
    missing = {s.requested_sample_index for s in sampling_plan.missing_samples}
    if any(
        i not in selected and i not in missing for i in window.requested_sample_indexes
    ):
        raise ContactEpisodeComputationError(
            "window requested indexes must exist in the sampling plan records"
        )
    if any(i not in selected for i in window.selected_requested_sample_indexes):
        raise ContactEpisodeComputationError(
            "window selected indexes must map to selected sampling records"
        )
    if any(i not in missing for i in window.missing_requested_sample_indexes):
        raise ContactEpisodeComputationError(
            "window missing indexes must map to missing sampling records"
        )
    samples = tuple(selected[i] for i in window.selected_requested_sample_indexes)
    if window.source_frame_indexes != tuple(s.source_frame_index for s in samples):
        raise ContactEpisodeComputationError(
            "window source indexes must match selected sampling records in order"
        )
    if (window.effective_start_time_ps, window.effective_end_time_ps) != (
        samples[0].actual_time_ps if samples else None,
        samples[-1].actual_time_ps if samples else None,
    ):
        raise ContactEpisodeComputationError(
            "window effective times must match selected sampling records"
        )
    return samples


def _make_episode(
    index: int, samples: list[ResolvedPhysicalTimeSample]
) -> ContactEpisode:
    first, last = samples[0], samples[-1]
    return ContactEpisode(
        episode_index=index,
        start_requested_sample_index=first.requested_sample_index,
        end_requested_sample_index=last.requested_sample_index,
        start_source_frame_index=first.source_frame_index,
        end_source_frame_index=last.source_frame_index,
        contact_frame_count=len(samples),
        start_actual_time_ps=first.actual_time_ps,
        end_actual_time_ps=last.actual_time_ps,
        episode_length_ns=_duration_ns(first.actual_time_ps, last.actual_time_ps),
        source_frame_indexes=tuple(s.source_frame_index for s in samples),
    )


def compute_window_contact_episodes(
    sampling_plan: ResolvedPhysicalTimeSamplingPlan,
    window: ResolvedPhysicalTimeWindow,
    *,
    contact_source_frame_indexes: tuple[int, ...],
) -> WindowContactEpisodeSummary:
    """Summarize already detected contact presence without matching or I/O.

    Window membership is authoritative. Missing positions and observed absences
    both break continuity; neither adds a contact frame or an inferred duration.
    Each call is independent, including overlapping windows and replicas.
    """
    if type(sampling_plan) is not ResolvedPhysicalTimeSamplingPlan:
        raise ContactEpisodeComputationError(
            "sampling_plan must be exact ResolvedPhysicalTimeSamplingPlan"
        )
    if type(window) is not ResolvedPhysicalTimeWindow:
        raise ContactEpisodeComputationError(
            "window must be exact ResolvedPhysicalTimeWindow"
        )
    _require_indexes(contact_source_frame_indexes, "contact_source_frame_indexes")
    samples_by_source = {
        s.source_frame_index: s for s in _window_samples(sampling_plan, window)
    }
    if any(i not in samples_by_source for i in contact_source_frame_indexes):
        raise ContactEpisodeComputationError(
            "contact source indexes must identify selected samples inside this window"
        )
    positives = tuple(samples_by_source[i] for i in contact_source_frame_indexes)
    if any(
        b.requested_sample_index <= a.requested_sample_index
        for a, b in pairwise(positives)
    ):
        raise ContactEpisodeComputationError(
            "contact source indexes must preserve requested sample order"
        )
    episodes: list[ContactEpisode] = []
    current: list[ResolvedPhysicalTimeSample] = []
    for sample in positives:
        if (
            current
            and sample.requested_sample_index != current[-1].requested_sample_index + 1
        ):
            episodes.append(_make_episode(len(episodes), current))
            current = []
        current.append(sample)
    if current:
        episodes.append(_make_episode(len(episodes), current))
    episode_tuple = tuple(episodes)
    return WindowContactEpisodeSummary(
        window_id=window.window_id,
        window_index=window.window_index,
        n_contact_frames=len(positives),
        n_contact_episodes=len(episodes),
        mean_episode_length_ns=_mean_length(episode_tuple),
        max_episode_length_ns=max(
            (e.episode_length_ns for e in episodes), default=None
        ),
        contact_source_frame_indexes=contact_source_frame_indexes,
        episodes=episode_tuple,
    )


__all__ = [
    "CONTACT_EPISODE_GAP_TOLERANCE",
    "CONTACT_EPISODE_KIND",
    "CONTACT_EPISODE_SCHEMA_VERSION",
    "ContactEpisode",
    "ContactEpisodeComputationError",
    "WindowContactEpisodeSummary",
    "compute_window_contact_episodes",
]
