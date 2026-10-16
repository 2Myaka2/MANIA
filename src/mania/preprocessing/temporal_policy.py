"""Closed, versioned window-boundary contracts; sampling is independent."""

from typing import Final, Literal

from pydantic import BaseModel, ConfigDict

LEGACY_BOUNDARY_PROFILE: Final = "mania.window_boundaries.legacy.v1"
INCLUSIVE_BOUNDARY_PROFILE: Final = "mania.window_boundaries.inclusive.v1"
BoundaryProfile = Literal[
    "mania.window_boundaries.legacy.v1", "mania.window_boundaries.inclusive.v1"
]


def require_boundary_profile(value: object) -> None:
    if type(value) is not str or value not in (
        LEGACY_BOUNDARY_PROFILE,
        INCLUSIVE_BOUNDARY_PROFILE,
    ):
        raise ValueError("Unknown temporal boundary profile")


class PreprocessingTemporalPolicy(BaseModel):
    """Explicit manifest request, separate from the six Dataset numbers."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["mania.preprocessing_temporal_policy.v0.1"]
    boundary_profile: BoundaryProfile
