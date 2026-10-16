"""Configuration models and YAML loading for MANIA."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator


class ProjectConfig(BaseModel):
    """Project metadata for a MANIA run."""

    name: str
    run_id: str


class SystemConfig(BaseModel):
    """Input files and condition metadata for one system."""

    topology: str
    trajectory: str
    condition: str
    label: int


class RuntimeConfig(BaseModel):
    """Runtime options for a MANIA run."""

    output_dir: str
    cache_dir: str
    temp_dir: str
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    run_mode: Literal["full", "analysis"] = "full"
    resume: bool = True
    overwrite: bool = False
    strict_validation: bool = True
    n_jobs: int = 1


class FeatureConfig(BaseModel):
    """Feature flags for optional analysis stages."""

    rg: bool = True
    energy_rerun: bool = False
    energy_groups: list[str] = Field(default_factory=list)
    esm2: bool = False


class MANIAConfig(BaseModel):
    """Top-level MANIA YAML configuration."""

    project: ProjectConfig
    systems: dict[str, SystemConfig]
    runtime: RuntimeConfig
    features: FeatureConfig = Field(default_factory=FeatureConfig)

    @field_validator("systems")
    @classmethod
    def validate_system_count(
        cls, systems: dict[str, SystemConfig]
    ) -> dict[str, SystemConfig]:
        """Allow one-condition and two-condition configurations only."""
        if len(systems) not in {1, 2}:
            msg = "systems must contain one or two condition entries"
            raise ValueError(msg)
        return systems


def load_config(path: str | Path) -> MANIAConfig:
    """Load and validate a MANIA YAML configuration file."""
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as file:
        raw_config = yaml.safe_load(file)

    if not isinstance(raw_config, dict):
        msg = "Configuration file must contain a YAML mapping at the top level."
        raise ValueError(msg)

    return MANIAConfig.model_validate(raw_config)
