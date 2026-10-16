"""Pure, immutable contract for explicitly declared input and output artifacts."""

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath, PureWindowsPath
from typing import Literal

ARTIFACT_INVENTORY_SCHEMA_VERSION = "mania.artifact_inventory.v0.1"
ARTIFACT_INVENTORY_KIND = "mania_artifact_inventory"
ARTIFACT_INVENTORY_FILENAME = "artifact_inventory.json"

ArtifactDirection = Literal["input", "output"]
ArtifactChecksumMode = Literal["none", "sha256"]


def _require_text(value: object, name: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be a non-empty stripped string")


def _require_portable_path(value: str, name: str) -> None:
    _require_text(value, name)
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or PureWindowsPath(value).drive
        or "\\" in value
        or "://" in value
        or "\0" in value
        or any(part in (".", "..") for part in value.split("/"))
        or path.as_posix() != value
    ):
        raise ValueError(f"{name} must be a normalized portable relative POSIX path")


@dataclass(frozen=True)
class ArtifactInventoryEntry:
    """Portable identity and caller-supplied integrity metadata for one file."""

    artifact_id: str
    direction: ArtifactDirection
    role: str
    path: str
    format: str
    byte_size: int
    sha256: str | None
    condition: str | None = None

    def __post_init__(self) -> None:
        _require_text(self.artifact_id, "artifact_id")
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:\-]*", self.artifact_id) is None:
            raise ValueError(
                "artifact_id must use portable ASCII identifier characters"
            )
        if self.direction not in ("input", "output"):
            raise ValueError("direction must be input or output")
        _require_text(self.role, "role")
        _require_portable_path(self.path, "path")
        _require_text(self.format, "format")
        if re.fullmatch(r"[a-z0-9.+_\-]+", self.format) is None:
            raise ValueError("format must use lowercase ASCII format characters")
        if (
            isinstance(self.byte_size, bool)
            or not isinstance(self.byte_size, int)
            or self.byte_size < 0
        ):
            raise ValueError("byte_size must be a non-negative integer")
        if self.sha256 is not None and (
            not isinstance(self.sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", self.sha256) is None
        ):
            raise ValueError(
                "sha256 must be exactly 64 lowercase hexadecimal characters"
            )
        if self.condition is not None:
            _require_text(self.condition, "condition")

    def to_dict(self) -> dict[str, object]:
        return {
            "artifact_id": self.artifact_id,
            "direction": self.direction,
            "role": self.role,
            "path": self.path,
            "format": self.format,
            "byte_size": self.byte_size,
            "sha256": self.sha256,
            "condition": self.condition,
        }


@dataclass(frozen=True)
class ArtifactInventory:
    """An independently versioned, ordered inventory with no self-checksum."""

    run_id: str
    workflow: str
    inventory_path: str
    checksum_mode: ArtifactChecksumMode
    artifacts: tuple[ArtifactInventoryEntry, ...]
    schema_version: str = field(default=ARTIFACT_INVENTORY_SCHEMA_VERSION, init=False)
    kind: str = field(default=ARTIFACT_INVENTORY_KIND, init=False)

    def __post_init__(self) -> None:
        _require_text(self.run_id, "run_id")
        _require_text(self.workflow, "workflow")
        _require_portable_path(self.inventory_path, "inventory_path")
        if PurePosixPath(self.inventory_path).name != ARTIFACT_INVENTORY_FILENAME:
            raise ValueError("inventory_path must end with artifact_inventory.json")
        if self.checksum_mode not in ("none", "sha256"):
            raise ValueError("checksum_mode must be none or sha256")
        if not isinstance(self.artifacts, tuple) or not all(
            type(entry) is ArtifactInventoryEntry for entry in self.artifacts
        ):
            raise ValueError(
                "artifacts must be a tuple of ArtifactInventoryEntry values"
            )
        ids: set[str] = set()
        paths: set[str] = set()
        for entry in self.artifacts:
            if entry.artifact_id in ids:
                raise ValueError("artifact IDs must be unique")
            if entry.path in paths:
                raise ValueError("artifact paths must be unique")
            if entry.path == self.inventory_path or entry.role == "artifact_inventory":
                raise ValueError("inventory must not contain itself as an artifact")
            if (self.checksum_mode == "none") != (entry.sha256 is None):
                raise ValueError("artifact checksums must match checksum_mode")
            ids.add(entry.artifact_id)
            paths.add(entry.path)

    @property
    def artifact_count(self) -> int:
        return len(self.artifacts)

    @property
    def input_artifact_count(self) -> int:
        return sum(entry.direction == "input" for entry in self.artifacts)

    @property
    def output_artifact_count(self) -> int:
        return sum(entry.direction == "output" for entry in self.artifacts)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "run_id": self.run_id,
            "workflow": self.workflow,
            "inventory_path": self.inventory_path,
            "checksum_mode": self.checksum_mode,
            "artifact_count": self.artifact_count,
            "input_artifact_count": self.input_artifact_count,
            "output_artifact_count": self.output_artifact_count,
            "artifacts": [entry.to_dict() for entry in self.artifacts],
        }


__all__ = [
    "ARTIFACT_INVENTORY_FILENAME",
    "ARTIFACT_INVENTORY_KIND",
    "ARTIFACT_INVENTORY_SCHEMA_VERSION",
    "ArtifactChecksumMode",
    "ArtifactDirection",
    "ArtifactInventory",
    "ArtifactInventoryEntry",
]
