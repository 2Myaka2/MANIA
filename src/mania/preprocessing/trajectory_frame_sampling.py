"""Dependency-free frame sampling options for preprocessing trajectories."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass


@dataclass(frozen=True)
class PreprocessingFrameSamplingOptions:
    """Validated source-frame sampling options for preprocessing workflows."""

    frame_start: int = 0
    frame_stop: int | None = None
    frame_stride: int = 1
    max_frames: int | None = None

    def __post_init__(self) -> None:
        _require_non_negative_int(self.frame_start, "frame_start")
        if self.frame_stop is not None:
            _require_non_negative_int(self.frame_stop, "frame_stop")
            if self.frame_stop <= self.frame_start:
                raise ValueError(
                    "frame_stop must be greater than frame_start"
                )
        _require_positive_int(self.frame_stride, "frame_stride")
        if self.max_frames is not None:
            _require_positive_int(self.max_frames, "max_frames")

    def to_dict(self) -> dict[str, object]:
        """Return JSON-safe frame sampling metadata."""
        return {
            "frame_start": self.frame_start,
            "frame_stop": self.frame_stop,
            "frame_stride": self.frame_stride,
            "max_frames": self.max_frames,
        }


def iter_sampled_trajectory_frames(
    trajectory: Iterable[object],
    options: PreprocessingFrameSamplingOptions | None = None,
) -> Iterator[tuple[int, object]]:
    """Yield ``(source_frame_index, timestep)`` for sampled trajectory frames."""
    selected_options = options or PreprocessingFrameSamplingOptions()
    yielded_frame_count = 0
    for source_frame_index, timestep in enumerate(trajectory):
        if (
            selected_options.frame_stop is not None
            and source_frame_index >= selected_options.frame_stop
        ):
            break
        if source_frame_index < selected_options.frame_start:
            continue
        if (
            source_frame_index - selected_options.frame_start
        ) % selected_options.frame_stride != 0:
            continue

        yield source_frame_index, timestep
        yielded_frame_count += 1
        if (
            selected_options.max_frames is not None
            and yielded_frame_count >= selected_options.max_frames
        ):
            break


def _require_non_negative_int(value: object, field_name: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
    ):
        raise ValueError(f"{field_name} must be a non-negative int")


def _require_positive_int(value: object, field_name: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
    ):
        raise ValueError(f"{field_name} must be a positive int")


__all__ = [
    "PreprocessingFrameSamplingOptions",
    "iter_sampled_trajectory_frames",
]
