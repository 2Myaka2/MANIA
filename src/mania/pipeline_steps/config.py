"""Configuration models for pipeline step workflows."""

from __future__ import annotations

import math
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


class NotebookExportGraphDiagnosticsWorkflowConfig(BaseModel):
    """Validated config for notebook export plus graph diagnostics workflow."""

    model_config = ConfigDict(frozen=True)

    source_dir: Path
    output_dir: Path
    diagnostics_output_dir: Path
    conditions: tuple[str, ...] | None = None
    frame_time_ps: float
    abs_tol: float = 1e-6
    weight_column: str = "contact_freq"
    degree_column: str = "degree"
    strength_column: str = "strength"

    @field_validator(
        "source_dir",
        "output_dir",
        "diagnostics_output_dir",
        mode="before",
    )
    @classmethod
    def validate_path(cls, value: Any) -> Any:
        """Reject empty string paths before Path conversion."""
        if isinstance(value, str) and value.strip() == "":
            raise ValueError("Path must not be empty")
        return value

    @field_validator("conditions", mode="before")
    @classmethod
    def validate_conditions(cls, value: object) -> tuple[str, ...] | None:
        """Normalize optional condition names."""
        if value is None:
            return None
        return _normalize_conditions(value)

    @field_validator("frame_time_ps")
    @classmethod
    def validate_frame_time_ps(cls, value: float) -> float:
        """Require positive finite frame time."""
        if not math.isfinite(value) or value <= 0:
            raise ValueError("frame_time_ps must be finite and positive")
        return value

    @field_validator("abs_tol")
    @classmethod
    def validate_abs_tol(cls, value: float) -> float:
        """Require non-negative finite graph diagnostics tolerance."""
        if not math.isfinite(value) or value < 0:
            raise ValueError("abs_tol must be finite and non-negative")
        return value

    @field_validator("weight_column", "degree_column", "strength_column")
    @classmethod
    def validate_column_name(cls, value: str) -> str:
        """Strip and validate metric column names."""
        stripped = value.strip()
        if stripped == "":
            raise ValueError("Column name must not be empty")
        return stripped

    def to_pipeline_kwargs(self) -> dict[str, object]:
        """Return keyword arguments for the composed pipeline workflow."""
        return {
            "source_dir": self.source_dir,
            "output_dir": self.output_dir,
            "diagnostics_output_dir": self.diagnostics_output_dir,
            "conditions": self.conditions,
            "frame_time_ps": self.frame_time_ps,
            "abs_tol": self.abs_tol,
            "weight_column": self.weight_column,
            "degree_column": self.degree_column,
            "strength_column": self.strength_column,
        }


def _normalize_conditions(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        raise ValueError("Conditions must be an iterable of names")
    if not isinstance(value, Iterable):
        raise ValueError("Conditions must be an iterable of names")

    normalized_conditions: list[str] = []
    seen_conditions: set[str] = set()
    for condition in value:
        if not isinstance(condition, str):
            raise ValueError(f"Condition names must be strings: {condition!r}")
        normalized = condition.strip()
        if normalized == "":
            raise ValueError("Condition name must not be empty")
        if normalized in seen_conditions:
            raise ValueError(
                f"Duplicate condition name after normalization: {normalized!r}"
            )
        normalized_conditions.append(normalized)
        seen_conditions.add(normalized)
    return tuple(normalized_conditions)


__all__ = ["NotebookExportGraphDiagnosticsWorkflowConfig"]
