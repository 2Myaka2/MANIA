"""Observation-only environment and runtime contracts; no automatic artifact I/O."""

import platform
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib import metadata
from math import isfinite
from pathlib import PurePosixPath
from typing import Literal

RUNTIME_METADATA_SCHEMA_VERSION = "mania.runtime_metadata.v0.1"
RUNTIME_METADATA_KIND = "mania_runtime_metadata"
RUNTIME_METADATA_FILENAME = "runtime_metadata.json"

RuntimeMetadataScope = Literal["preprocessing", "analysis"]

# Keep the existing optional-runtime distribution-name convention.
_MDANALYSIS_DISTRIBUTION_NAME = "MD" + "Analysis"


def _require_text(value: object, name: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be a non-empty stripped string")


def _require_count(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def _require_seconds(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite non-negative number")
    try:
        valid = isfinite(value) and value >= 0
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(f"{name} must be a finite non-negative number")


def _require_metadata_path(value: str) -> None:
    _require_text(value, "metadata_path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or "\\" in value
        or ":" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
        or any(part in (".", "..") for part in value.split("/"))
        or path.as_posix() != value
        or path.name != RUNTIME_METADATA_FILENAME
    ):
        raise ValueError(
            "metadata_path must be a normalized portable relative POSIX path "
            f"ending in {RUNTIME_METADATA_FILENAME}"
        )


@dataclass(frozen=True)
class RuntimeEnvironment:
    """Software/platform versions without local paths or machine identifiers."""

    python_version: str
    python_implementation: str
    platform_system: str
    platform_release: str
    platform_machine: str
    numpy_version: str | None
    mdanalysis_version: str | None
    pydantic_version: str | None
    pyyaml_version: str | None

    def __post_init__(self) -> None:
        for name in (
            "python_version",
            "python_implementation",
            "platform_system",
            "platform_release",
            "platform_machine",
        ):
            _require_text(getattr(self, name), name)
        for name in (
            "numpy_version",
            "mdanalysis_version",
            "pydantic_version",
            "pyyaml_version",
        ):
            value = getattr(self, name)
            if value is not None:
                _require_text(value, name)

    def to_dict(self) -> dict[str, object]:
        return {
            "python_version": self.python_version,
            "python_implementation": self.python_implementation,
            "platform_system": self.platform_system,
            "platform_release": self.platform_release,
            "platform_machine": self.platform_machine,
            "numpy_version": self.numpy_version,
            "mdanalysis_version": self.mdanalysis_version,
            "pydantic_version": self.pydantic_version,
            "pyyaml_version": self.pyyaml_version,
        }


def _distribution_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def collect_runtime_environment() -> RuntimeEnvironment:
    """Observe only platform fields and installed distribution metadata."""
    return RuntimeEnvironment(
        python_version=platform.python_version(),
        python_implementation=platform.python_implementation(),
        platform_system=platform.system(),
        platform_release=platform.release(),
        platform_machine=platform.machine(),
        numpy_version=_distribution_version("numpy"),
        mdanalysis_version=_distribution_version(_MDANALYSIS_DISTRIBUTION_NAME),
        pydantic_version=_distribution_version("pydantic"),
        pyyaml_version=_distribution_version("PyYAML"),
    )


@dataclass(frozen=True)
class RuntimePerformance:
    """Operational duration and retained counters, without scientific statistics."""

    wall_clock_seconds: float
    condition_count: int
    sampled_frame_count: int | None = None
    seconds_per_sampled_frame: float | None = None
    contact_frame_count: int | None = None
    contact_observation_count: int | None = None

    def __post_init__(self) -> None:
        _require_seconds(self.wall_clock_seconds, "wall_clock_seconds")
        _require_count(self.condition_count, "condition_count")
        for name in (
            "sampled_frame_count",
            "contact_frame_count",
            "contact_observation_count",
        ):
            value = getattr(self, name)
            if value is not None:
                _require_count(value, name)
        if self.seconds_per_sampled_frame is not None:
            _require_seconds(
                self.seconds_per_sampled_frame, "seconds_per_sampled_frame"
            )
        if self.sampled_frame_count is None or self.sampled_frame_count == 0:
            if self.seconds_per_sampled_frame is not None:
                raise ValueError(
                    "unavailable/zero sampled frames require seconds/frame None"
                )
        elif self.seconds_per_sampled_frame is None:
            raise ValueError("positive sampled frames require seconds/frame")

    def to_dict(self) -> dict[str, object]:
        return {
            "wall_clock_seconds": self.wall_clock_seconds,
            "condition_count": self.condition_count,
            "sampled_frame_count": self.sampled_frame_count,
            "seconds_per_sampled_frame": self.seconds_per_sampled_frame,
            "contact_frame_count": self.contact_frame_count,
            "contact_observation_count": self.contact_observation_count,
        }


def build_runtime_performance(
    *,
    started_at_utc: datetime,
    ended_at_utc: datetime,
    condition_count: int,
    sampled_frame_count: int | None = None,
    contact_frame_count: int | None = None,
    contact_observation_count: int | None = None,
) -> RuntimePerformance:
    """Derive duration from supplied aware timestamps, without reading a clock."""
    for name, value in (
        ("started_at_utc", started_at_utc),
        ("ended_at_utc", ended_at_utc),
    ):
        if not isinstance(value, datetime) or value.utcoffset() is None:
            raise ValueError(f"{name} must be a timezone-aware datetime")
    if sampled_frame_count is not None:
        _require_count(sampled_frame_count, "sampled_frame_count")
    elapsed = ended_at_utc.astimezone(UTC) - started_at_utc.astimezone(UTC)
    seconds = elapsed.total_seconds()
    if seconds < 0:
        raise ValueError("ended_at_utc must not precede started_at_utc")
    return RuntimePerformance(
        wall_clock_seconds=seconds,
        condition_count=condition_count,
        sampled_frame_count=sampled_frame_count,
        seconds_per_sampled_frame=(
            seconds / sampled_frame_count if sampled_frame_count else None
        ),
        contact_frame_count=contact_frame_count,
        contact_observation_count=contact_observation_count,
    )


@dataclass(frozen=True)
class RuntimeMetadata:
    """Independent technical metadata; software identity stays in run provenance."""

    run_id: str
    workflow: str
    scope: RuntimeMetadataScope
    metadata_path: str
    environment: RuntimeEnvironment
    performance: RuntimePerformance
    schema_version: str = field(default=RUNTIME_METADATA_SCHEMA_VERSION, init=False)
    kind: str = field(default=RUNTIME_METADATA_KIND, init=False)

    def __post_init__(self) -> None:
        _require_text(self.run_id, "run_id")
        _require_text(self.workflow, "workflow")
        if self.scope not in ("preprocessing", "analysis"):
            raise ValueError("scope must be preprocessing or analysis")
        _require_metadata_path(self.metadata_path)
        if type(self.environment) is not RuntimeEnvironment:
            raise ValueError("environment must be exact RuntimeEnvironment")
        if type(self.performance) is not RuntimePerformance:
            raise ValueError("performance must be exact RuntimePerformance")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "run_id": self.run_id,
            "workflow": self.workflow,
            "scope": self.scope,
            "metadata_path": self.metadata_path,
            "environment": self.environment.to_dict(),
            "performance": self.performance.to_dict(),
        }


def build_runtime_metadata(
    *,
    run_id: str,
    workflow: str,
    scope: RuntimeMetadataScope,
    metadata_path: str,
    environment: RuntimeEnvironment,
    performance: RuntimePerformance,
) -> RuntimeMetadata:
    """Compose supplied snapshots without collecting any additional metadata."""
    return RuntimeMetadata(
        run_id=run_id,
        workflow=workflow,
        scope=scope,
        metadata_path=metadata_path,
        environment=environment,
        performance=performance,
    )


__all__ = [
    "RUNTIME_METADATA_FILENAME",
    "RUNTIME_METADATA_KIND",
    "RUNTIME_METADATA_SCHEMA_VERSION",
    "RuntimeEnvironment",
    "RuntimeMetadata",
    "RuntimeMetadataScope",
    "RuntimePerformance",
    "build_runtime_metadata",
    "build_runtime_performance",
    "collect_runtime_environment",
]
