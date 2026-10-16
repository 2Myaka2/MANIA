"""Validated, immutable run-provenance snapshots without runtime collection or I/O."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from math import isfinite
from pathlib import PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from mania.scientific_qualification import ScientificQualificationV1

from mania.software_identity import SoftwareIdentity

RUN_PROVENANCE_SCHEMA_VERSION = "mania.run_provenance.v0.1"
RUN_PROVENANCE_KIND = "mania_run_provenance"
RUN_PROVENANCE_FILENAME = "run_provenance.json"

RunProvenanceStatus = Literal["completed", "failed"]
RunProvenanceIssueSeverity = Literal["warning", "error"]
TimeSpacingStatus = Literal["uniform", "non_uniform", "unavailable"]


def _require_text(value: object, name: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be a non-empty stripped string")


def _require_integer(value: object, name: str, minimum: int = 0) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")


def _require_time(value: object, name: str, *, positive: bool = False) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a finite numeric value")
    try:
        finite = isfinite(value)
    except OverflowError:
        finite = False
    if not finite or value < 0 or (positive and value == 0):
        bound = "positive" if positive else "non-negative"
        raise ValueError(f"{name} must be finite and {bound}")


def _require_tuple(value: object, name: str, item_type: type) -> None:
    if not isinstance(value, tuple) or not all(
        isinstance(item, item_type) for item in value
    ):
        raise ValueError(f"{name} must be a tuple of {item_type.__name__} values")


def _freeze_json(value: object, active: set[int]) -> object:
    """Copy JSON input into mapping proxies and tuples, sorting mapping keys."""
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("resolved_configuration floats must be finite")
        return value
    if isinstance(value, (Mapping, list, tuple)):
        identity = id(value)
        if identity in active:
            raise ValueError("resolved_configuration must not contain cycles")
        active.add(identity)
        try:
            if isinstance(value, Mapping):
                if any(not isinstance(key, str) for key in value):
                    raise ValueError("resolved_configuration keys must be strings")
                return MappingProxyType(
                    {key: _freeze_json(value[key], active) for key in sorted(value)}
                )
            return tuple(_freeze_json(item, active) for item in value)
        finally:
            active.remove(identity)
    raise ValueError("resolved_configuration contains an unsupported JSON value")


def _thaw_json(value: object) -> object:
    """Return fresh JSON dictionaries and lists from the private snapshot."""
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


@dataclass(frozen=True)
class RequestedFrameSampling:
    """Requested sampling parameters; does not select or inspect frames."""

    frame_start: int = 0
    frame_stop: int | None = None
    frame_stride: int = 1
    max_frames: int | None = None

    def __post_init__(self) -> None:
        _require_integer(self.frame_start, "frame_start")
        _require_integer(self.frame_stride, "frame_stride", 1)
        if self.frame_stop is not None:
            _require_integer(self.frame_stop, "frame_stop")
            if self.frame_stop <= self.frame_start:
                raise ValueError("frame_stop must be greater than frame_start")
        if self.max_frames is not None:
            _require_integer(self.max_frames, "max_frames", 1)

    def to_dict(self) -> dict[str, object]:
        return {
            "frame_start": self.frame_start,
            "frame_stop": self.frame_stop,
            "frame_stride": self.frame_stride,
            "max_frames": self.max_frames,
        }


@dataclass(frozen=True)
class EffectiveFrameSampling:
    """Supplied observations only; unavailable metadata is never inferred."""

    source_frame_count: int | None
    sampled_frame_count: int
    first_source_frame_index: int | None
    last_source_frame_index: int | None
    first_time_ps: float | None
    last_time_ps: float | None
    time_spacing_status: TimeSpacingStatus
    observed_time_spacing_ps: float | None

    def __post_init__(self) -> None:
        _require_integer(self.sampled_frame_count, "sampled_frame_count")
        for name in (
            "source_frame_count",
            "first_source_frame_index",
            "last_source_frame_index",
        ):
            value = getattr(self, name)
            if value is not None:
                _require_integer(value, name)
        if (
            self.source_frame_count is not None
            and self.sampled_frame_count > self.source_frame_count
        ):
            raise ValueError("sampled_frame_count must not exceed source_frame_count")
        if self.time_spacing_status not in ("uniform", "non_uniform", "unavailable"):
            raise ValueError("invalid time_spacing_status")
        for name in ("first_time_ps", "last_time_ps", "observed_time_spacing_ps"):
            value = getattr(self, name)
            if value is not None:
                _require_time(value, name, positive=name == "observed_time_spacing_ps")
        if self.sampled_frame_count == 0:
            if any(
                value is not None
                for value in (
                    self.first_source_frame_index,
                    self.last_source_frame_index,
                    self.first_time_ps,
                    self.last_time_ps,
                    self.observed_time_spacing_ps,
                )
            ):
                raise ValueError(
                    "zero sampled frames require unavailable indexes/times"
                )
        elif (
            self.first_source_frame_index is None
            or self.last_source_frame_index is None
            or self.first_source_frame_index > self.last_source_frame_index
        ):
            raise ValueError("sampled frames require ordered first and last indexes")
        if (
            self.first_time_ps is not None
            and self.last_time_ps is not None
            and self.first_time_ps > self.last_time_ps
        ):
            raise ValueError("first_time_ps must not exceed last_time_ps")
        if self.sampled_frame_count < 2 and self.time_spacing_status != "unavailable":
            raise ValueError("fewer than two frames require unavailable time spacing")
        if self.time_spacing_status == "uniform":
            if self.observed_time_spacing_ps is None:
                raise ValueError(
                    "uniform time spacing requires observed_time_spacing_ps"
                )
        elif self.observed_time_spacing_ps is not None:
            raise ValueError(
                "only uniform time spacing may have observed_time_spacing_ps"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "source_frame_count": self.source_frame_count,
            "sampled_frame_count": self.sampled_frame_count,
            "first_source_frame_index": self.first_source_frame_index,
            "last_source_frame_index": self.last_source_frame_index,
            "first_time_ps": self.first_time_ps,
            "last_time_ps": self.last_time_ps,
            "time_spacing_status": self.time_spacing_status,
            "observed_time_spacing_ps": self.observed_time_spacing_ps,
        }


@dataclass(frozen=True)
class ConditionSamplingProvenance:
    """Requested and, when available, observed sampling for one condition."""

    condition: str
    requested: RequestedFrameSampling
    effective: EffectiveFrameSampling | None

    def __post_init__(self) -> None:
        _require_text(self.condition, "condition")
        if not isinstance(self.requested, RequestedFrameSampling):
            raise ValueError("requested must be RequestedFrameSampling")
        if self.effective is not None and not isinstance(
            self.effective, EffectiveFrameSampling
        ):
            raise ValueError("effective must be EffectiveFrameSampling or None")

    def to_dict(self) -> dict[str, object]:
        return {
            "condition": self.condition,
            "requested": self.requested.to_dict(),
            "effective": None if self.effective is None else self.effective.to_dict(),
        }


@dataclass(frozen=True)
class PortableArtifactReference:
    """A portable link only, without probing the filesystem or inventorying it."""

    role: str
    path: str

    def __post_init__(self) -> None:
        _require_text(self.role, "role")
        _require_text(self.path, "path")
        path = PurePosixPath(self.path)
        if (
            path.is_absolute()
            or PureWindowsPath(self.path).drive
            or "\\" in self.path
            or "\0" in self.path
            or "://" in self.path
            or any(part in (".", "..") for part in self.path.split("/"))
            or path.as_posix() != self.path
        ):
            raise ValueError("path must be a normalized portable relative POSIX path")

    def to_dict(self) -> dict[str, object]:
        return {"role": self.role, "path": self.path}


@dataclass(frozen=True)
class RunProvenanceIssue:
    """A caller-supplied portable warning or error, with no exception capture."""

    severity: RunProvenanceIssueSeverity
    code: str
    message: str
    stage: str | None = None
    condition: str | None = None

    def __post_init__(self) -> None:
        if self.severity not in ("warning", "error"):
            raise ValueError("severity must be warning or error")
        _require_text(self.code, "code")
        _require_text(self.message, "message")
        for name in ("stage", "condition"):
            value = getattr(self, name)
            if value is not None:
                _require_text(value, name)

    def to_dict(self) -> dict[str, object]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "stage": self.stage,
            "condition": self.condition,
        }


@dataclass(frozen=True)
class RunProvenance:
    """Final-run passport supplied entirely by the caller; never writes a file."""

    run_id: str
    workflow: str
    status: RunProvenanceStatus
    started_at_utc: datetime
    ended_at_utc: datetime
    software_identity: SoftwareIdentity
    command: tuple[str, ...]
    resolved_configuration: Mapping[str, object]
    conditions: tuple[str, ...]
    sampling_by_condition: tuple[ConditionSamplingProvenance, ...] = ()
    artifact_references: tuple[PortableArtifactReference, ...] = ()
    issues: tuple[RunProvenanceIssue, ...] = ()
    schema_version: str = field(default=RUN_PROVENANCE_SCHEMA_VERSION, init=False)
    kind: str = field(default=RUN_PROVENANCE_KIND, init=False)

    def __post_init__(self) -> None:
        _require_text(self.run_id, "run_id")
        _require_text(self.workflow, "workflow")
        if self.status not in ("completed", "failed"):
            raise ValueError("status must be completed or failed")
        for name in ("started_at_utc", "ended_at_utc"):
            value = getattr(self, name)
            if not isinstance(value, datetime) or value.utcoffset() is None:
                raise ValueError(f"{name} must be a timezone-aware datetime")
            object.__setattr__(self, name, value.astimezone(UTC))
        if self.ended_at_utc < self.started_at_utc:
            raise ValueError("ended_at_utc must not be earlier than started_at_utc")
        if not isinstance(self.software_identity, SoftwareIdentity):
            raise ValueError("software_identity must be SoftwareIdentity")
        _require_tuple(self.command, "command", str)
        if not self.command or any(not token for token in self.command):
            raise ValueError("command must contain non-empty argument tokens")
        _require_tuple(self.conditions, "conditions", str)
        for condition in self.conditions:
            _require_text(condition, "condition")
        if len(set(self.conditions)) != len(self.conditions):
            raise ValueError("conditions must be unique")
        _require_tuple(
            self.sampling_by_condition,
            "sampling_by_condition",
            ConditionSamplingProvenance,
        )
        sampling_names = [record.condition for record in self.sampling_by_condition]
        if len(set(sampling_names)) != len(sampling_names):
            raise ValueError("sampling condition names must be unique")
        if any(name not in self.conditions for name in sampling_names):
            raise ValueError("sampling condition must appear in conditions")
        _require_tuple(
            self.artifact_references, "artifact_references", PortableArtifactReference
        )
        pairs = [
            (reference.role, reference.path) for reference in self.artifact_references
        ]
        if len(set(pairs)) != len(pairs):
            raise ValueError("artifact reference (role, path) pairs must be unique")
        _require_tuple(self.issues, "issues", RunProvenanceIssue)
        if any(
            issue.condition is not None and issue.condition not in self.conditions
            for issue in self.issues
        ):
            raise ValueError("issue condition must appear in conditions")
        if not isinstance(self.resolved_configuration, Mapping):
            raise ValueError("resolved_configuration must be a mapping")
        object.__setattr__(
            self,
            "resolved_configuration",
            _freeze_json(self.resolved_configuration, set()),
        )

    def to_dict(self) -> dict[str, object]:
        """Return independent JSON data in contract order, with UTC microseconds."""
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "run_id": self.run_id,
            "workflow": self.workflow,
            "status": self.status,
            "started_at_utc": self.started_at_utc.isoformat(
                timespec="microseconds"
            ).replace("+00:00", "Z"),
            "ended_at_utc": self.ended_at_utc.isoformat(
                timespec="microseconds"
            ).replace("+00:00", "Z"),
            "software_identity": self.software_identity.to_dict(),
            "command": list(self.command),
            "resolved_configuration": _thaw_json(self.resolved_configuration),
            "conditions": list(self.conditions),
            "sampling_by_condition": [
                record.to_dict() for record in self.sampling_by_condition
            ],
            "artifact_references": [
                reference.to_dict() for reference in self.artifact_references
            ],
            "issues": [issue.to_dict() for issue in self.issues],
        }


__all__ = [
    "RUN_PROVENANCE_SCHEMA_VERSION",
    "RUN_PROVENANCE_KIND",
    "RUN_PROVENANCE_FILENAME",
    "RunProvenanceStatus",
    "RunProvenanceIssueSeverity",
    "TimeSpacingStatus",
    "RequestedFrameSampling",
    "EffectiveFrameSampling",
    "ConditionSamplingProvenance",
    "PortableArtifactReference",
    "RunProvenanceIssue",
    "RunProvenance",
]


@dataclass(frozen=True)
class ExploratoryRunProvenance(RunProvenance):
    """The separate v0.2 passport; the retained v0.1 dataclass is unchanged."""

    scientific_qualification: "ScientificQualificationV1" = field(kw_only=True)
    schema_version: str = field(default="mania.run_provenance.v0.2", init=False)

    def __post_init__(self) -> None:
        import json

        from mania.run_config import RunConfig
        from mania.scientific_qualification import ScientificQualificationV1

        super().__post_init__()
        if type(self.scientific_qualification) is not ScientificQualificationV1:
            raise ValueError("Exact typed scientific qualification required")
        config = RunConfig.model_validate_json(
            json.dumps(_thaw_json(self.resolved_configuration))
        )
        if self.workflow != "mania.run" or config.mode != "exploratory":
            raise ValueError("Provenance v0.2 requires exploratory mania.run")
        if tuple(
            s.input_identity for s in self.scientific_qualification.source_scopes
        ) != tuple(s.identity(config.project) for s in config.systems):
            raise ValueError("Provenance qualification source identities differ")

    def to_dict(self) -> dict[str, object]:
        result = super().to_dict()
        result["scientific_qualification"] = self.scientific_qualification.model_dump(
            mode="json"
        )
        return result
