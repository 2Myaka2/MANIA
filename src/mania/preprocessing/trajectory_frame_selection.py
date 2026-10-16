"""Execute an already resolved selection using exact enumerated source indexes."""

from collections.abc import Iterable, Iterator


class ExplicitFrameSelectionError(ValueError):
    """An explicit source selection is invalid or cannot be fully observed."""


def iter_selected_trajectory_frames(
    trajectory: Iterable[object],
    source_frame_indexes: tuple[int, ...],
) -> Iterator[tuple[int, object]]:
    """Yield selected frames once, stopping immediately after the final target."""
    if not isinstance(source_frame_indexes, tuple) or not source_frame_indexes:
        raise ExplicitFrameSelectionError("Source indexes must be a non-empty tuple.")
    previous = -1
    for index in source_frame_indexes:
        if isinstance(index, bool) or not isinstance(index, int) or index <= previous:
            raise ExplicitFrameSelectionError(
                "Source indexes must be non-negative, strictly increasing integers."
            )
        previous = index
    selected = iter(source_frame_indexes)
    target = next(selected)
    for index, timestep in enumerate(trajectory):
        if index == target:
            yield index, timestep
            next_target = next(selected, None)
            if next_target is None:
                return
            target = next_target
    raise ExplicitFrameSelectionError("Trajectory ended before all selected frames.")
