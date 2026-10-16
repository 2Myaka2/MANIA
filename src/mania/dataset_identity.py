"""Independent Dataset v1.0 identity and requested physical-time contracts.

Stage 26.A validates caller-supplied metadata only. Integration belongs to
Stage 26.B; operational frame and window semantics belong to Stage 27.
"""

from __future__ import annotations

import math
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DATASET_TRAJECTORY_SPEC_SCHEMA_VERSION = "mania.dataset_trajectory_spec.v0.1"
DATASET_TRAJECTORY_SPEC_KIND = "mania_dataset_trajectory_spec"

DatasetEngine = Literal["gromacs", "namd"]


def _strip_text(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Value must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError("Value must not be empty or whitespace-only")
    return normalized


class DatasetTrajectoryIdentity(BaseModel):
    """Explicit trajectory identity, independent of legacy condition inputs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset_id: str
    system_id: str
    trajectory_id: str
    variant_id: str
    engine: DatasetEngine
    condition: str | None
    replica_id: str
    disulfide_state: str | None = None

    @field_validator(
        "dataset_id",
        "system_id",
        "trajectory_id",
        "variant_id",
        "replica_id",
        mode="before",
    )
    @classmethod
    def validate_identifier(cls, value: object) -> str:
        """Require actual non-empty strings without imposing an ID convention."""
        return _strip_text(value)

    @field_validator("engine", mode="before")
    @classmethod
    def normalize_engine(cls, value: object) -> str:
        """Normalize spelling before validation against DatasetEngine."""
        return _strip_text(value).lower()

    @field_validator("condition", "disulfide_state", mode="before")
    @classmethod
    def validate_optional_label(cls, value: object) -> str | None:
        """Preserve explicit absence; never infer missing scientific labels."""
        return None if value is None else _strip_text(value)

    @property
    def replica_key(self) -> tuple[str, str, str, str]:
        """Return an identity/reference key, never a statistical grouping key."""
        return (self.dataset_id, self.system_id, self.trajectory_id, self.replica_id)

    def to_dict(self) -> dict[str, object]:
        """Return independent JSON data in field declaration order."""
        return self.model_dump(mode="json")


class DatasetTemporalParameters(BaseModel):
    """Requested physical values only; no frame or window calculations."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    production_start_ns: float = Field(ge=0)
    production_end_ns: float
    frame_stride_ps: float = Field(gt=0)
    window_length_ns: float = Field(gt=0)
    window_step_ns: float = Field(gt=0)
    overlap_percent: float = Field(ge=0, lt=100)

    @field_validator("*", mode="before")
    @classmethod
    def reject_boolean(cls, value: object) -> object:
        """Do not let Python booleans become physical numeric parameters."""
        if isinstance(value, bool):
            raise ValueError("Physical-time parameters must not be bool")
        return value

    @field_validator("*")
    @classmethod
    def validate_finite(cls, value: float) -> float:
        """Reject NaN and either infinity for every numeric field."""
        if not math.isfinite(value):
            raise ValueError("Physical-time parameters must be finite")
        return value

    @model_validator(mode="after")
    def validate_production_interval(self) -> Self:
        """Require a positive interval containing the requested window length."""
        if self.production_end_ns <= self.production_start_ns:
            raise ValueError(
                "production_end_ns must be greater than production_start_ns"
            )
        if self.window_length_ns > self.production_end_ns - self.production_start_ns:
            raise ValueError("window_length_ns must not exceed the production duration")
        return self

    def to_dict(self) -> dict[str, object]:
        """Return requested values in declaration order, retaining their units."""
        return self.model_dump(mode="json")


class DatasetTrajectorySpec(BaseModel):
    """A versioned in-memory specification with no paths or runtime metadata."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    identity: DatasetTrajectoryIdentity
    temporal: DatasetTemporalParameters

    @property
    def schema_version(self) -> str:
        """Expose the contract version without accepting it as user input."""
        return DATASET_TRAJECTORY_SPEC_SCHEMA_VERSION

    @property
    def kind(self) -> str:
        """Expose the contract kind without accepting it as user input."""
        return DATASET_TRAJECTORY_SPEC_KIND

    def to_dict(self) -> dict[str, object]:
        """Return independent JSON data in stable root and nested key order."""
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "identity": self.identity.to_dict(),
            "temporal": self.temporal.to_dict(),
        }


__all__ = [
    "DATASET_TRAJECTORY_SPEC_KIND",
    "DATASET_TRAJECTORY_SPEC_SCHEMA_VERSION",
    "DatasetEngine",
    "DatasetTemporalParameters",
    "DatasetTrajectoryIdentity",
    "DatasetTrajectorySpec",
]
