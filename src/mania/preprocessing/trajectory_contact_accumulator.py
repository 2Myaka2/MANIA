"""Dependency-free aggregation for sampled residue interactions."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TypeAlias

InteractionResidueId: TypeAlias = int | str


def _non_empty_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _residue_id(value: object, field_name: str) -> InteractionResidueId:
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an int or string")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return _non_empty_string(value, field_name)
    raise ValueError(f"{field_name} must be an int or string")


def _non_negative_int(value: object, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative int")


def _positive_int(value: object, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive int")


def _non_negative_number(value: object, field_name: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(
            f"{field_name} must be a finite non-negative number"
        )


def _frequency(value: object, field_name: str) -> None:
    _non_negative_number(value, field_name)
    if isinstance(value, (int, float)) and value > 1:
        raise ValueError(f"{field_name} must not exceed 1")


@dataclass(frozen=True)
class InteractionAggregateResult:
    """One deterministic aggregate produced by InteractionAccumulator."""

    condition_name: str
    resid_i: InteractionResidueId
    resid_j: InteractionResidueId
    edge_type: str
    observed_frame_count: int
    occurrence_count: int
    sampled_frame_count: int
    contact_freq: float
    mean_dist_A: float
    std_dist_A: float
    first_seen_frame: int
    last_seen_frame: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "condition_name",
            _non_empty_string(self.condition_name, "condition_name"),
        )
        object.__setattr__(self, "resid_i", _residue_id(self.resid_i, "resid_i"))
        object.__setattr__(self, "resid_j", _residue_id(self.resid_j, "resid_j"))
        if self.resid_i == self.resid_j:
            raise ValueError("resid_i and resid_j must differ")
        object.__setattr__(
            self,
            "edge_type",
            _non_empty_string(self.edge_type, "edge_type"),
        )
        _positive_int(self.observed_frame_count, "observed_frame_count")
        _positive_int(self.occurrence_count, "occurrence_count")
        _positive_int(self.sampled_frame_count, "sampled_frame_count")
        if self.observed_frame_count > self.sampled_frame_count:
            raise ValueError(
                "observed_frame_count must not exceed sampled_frame_count"
            )
        if self.occurrence_count < self.observed_frame_count:
            raise ValueError(
                "occurrence_count must not be less than observed_frame_count"
            )
        _frequency(self.contact_freq, "contact_freq")
        _non_negative_number(self.mean_dist_A, "mean_dist_A")
        _non_negative_number(self.std_dist_A, "std_dist_A")
        _non_negative_int(self.first_seen_frame, "first_seen_frame")
        _non_negative_int(self.last_seen_frame, "last_seen_frame")
        if self.first_seen_frame > self.last_seen_frame:
            raise ValueError(
                "first_seen_frame must not exceed last_seen_frame"
            )

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic JSON-safe aggregate dictionary."""
        return {
            "condition": self.condition_name,
            "resid_i": self.resid_i,
            "resid_j": self.resid_j,
            "edge_type": self.edge_type,
            "observed_frame_count": self.observed_frame_count,
            "occurrence_count": self.occurrence_count,
            "sampled_frame_count": self.sampled_frame_count,
            "contact_freq": self.contact_freq,
            "mean_dist_A": self.mean_dist_A,
            "std_dist_A": self.std_dist_A,
            "first_seen_frame": self.first_seen_frame,
            "last_seen_frame": self.last_seen_frame,
        }


@dataclass(frozen=True)
class _InteractionKey:
    condition_name: str
    resid_i: InteractionResidueId
    resid_j: InteractionResidueId
    edge_type: str


@dataclass
class _InteractionObservations:
    frame_indexes: set[int] = field(default_factory=set)
    distances_A: list[float] = field(default_factory=list)


class InteractionAccumulator:
    """Accumulate typed residue-pair observations across sampled frames."""

    def __init__(self) -> None:
        self._observations: dict[
            _InteractionKey,
            _InteractionObservations,
        ] = {}

    def add(
        self,
        *,
        condition_name: str,
        frame_index: int,
        resid_i: InteractionResidueId,
        resid_j: InteractionResidueId,
        edge_type: str,
        distance_A: float,
    ) -> None:
        """Record one interaction occurrence at its original frame index."""
        normalized_condition = _non_empty_string(
            condition_name,
            "condition_name",
        )
        _non_negative_int(frame_index, "frame_index")
        normalized_i = _residue_id(resid_i, "resid_i")
        normalized_j = _residue_id(resid_j, "resid_j")
        if normalized_i == normalized_j:
            raise ValueError("resid_i and resid_j must differ")
        canonical_i, canonical_j = _canonical_pair(normalized_i, normalized_j)
        normalized_edge_type = _non_empty_string(edge_type, "edge_type")
        _non_negative_number(distance_A, "distance_A")
        key = _InteractionKey(
            condition_name=normalized_condition,
            resid_i=canonical_i,
            resid_j=canonical_j,
            edge_type=normalized_edge_type,
        )
        observations = self._observations.setdefault(
            key,
            _InteractionObservations(),
        )
        observations.frame_indexes.add(frame_index)
        observations.distances_A.append(float(distance_A))

    def finalize(
        self,
        *,
        frame_count: int,
        edge_type: str | None = None,
        min_frequency: float = 0.0,
    ) -> tuple[InteractionAggregateResult, ...]:
        """Finalize filtered aggregate rows using the sampled denominator."""
        _non_negative_int(frame_count, "frame_count")
        _frequency(min_frequency, "min_frequency")
        selected_edge_type = (
            None if edge_type is None else _non_empty_string(edge_type, "edge_type")
        )
        if frame_count == 0:
            if self._observations:
                raise ValueError(
                    "frame_count must be positive when observations exist"
                )
            return ()

        rows: list[InteractionAggregateResult] = []
        for key, observations in sorted(
            self._observations.items(),
            key=lambda item: _sort_key(item[0]),
        ):
            if selected_edge_type is not None and key.edge_type != selected_edge_type:
                continue
            observed_frame_count = len(observations.frame_indexes)
            contact_frequency = observed_frame_count / frame_count
            if contact_frequency < min_frequency:
                continue
            mean_distance = sum(observations.distances_A) / len(
                observations.distances_A
            )
            variance = sum(
                (distance - mean_distance) ** 2
                for distance in observations.distances_A
            ) / len(observations.distances_A)
            rows.append(
                InteractionAggregateResult(
                    condition_name=key.condition_name,
                    resid_i=key.resid_i,
                    resid_j=key.resid_j,
                    edge_type=key.edge_type,
                    observed_frame_count=observed_frame_count,
                    occurrence_count=len(observations.distances_A),
                    sampled_frame_count=frame_count,
                    contact_freq=contact_frequency,
                    mean_dist_A=mean_distance,
                    std_dist_A=math.sqrt(variance),
                    first_seen_frame=min(observations.frame_indexes),
                    last_seen_frame=max(observations.frame_indexes),
                )
            )
        return tuple(rows)


def _canonical_pair(
    resid_i: InteractionResidueId,
    resid_j: InteractionResidueId,
) -> tuple[InteractionResidueId, InteractionResidueId]:
    if _residue_sort_key(resid_j) < _residue_sort_key(resid_i):
        return resid_j, resid_i
    return resid_i, resid_j


def _residue_sort_key(residue_id: InteractionResidueId) -> tuple[int, int, str]:
    if isinstance(residue_id, int):
        return 0, residue_id, ""
    return 1, 0, residue_id


def _sort_key(key: _InteractionKey) -> tuple[object, ...]:
    return (
        key.condition_name,
        key.edge_type,
        _residue_sort_key(key.resid_i),
        _residue_sort_key(key.resid_j),
    )


__all__ = ["InteractionAccumulator", "InteractionAggregateResult"]
