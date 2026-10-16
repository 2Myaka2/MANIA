"""Explicit file inspection, opt-in streaming SHA256, and atomic inventory writing."""

import hashlib
import io
import json
import os
import stat
import tempfile
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any, BinaryIO

from mania.artifact_inventory import (
    ARTIFACT_INVENTORY_FILENAME,
    ARTIFACT_INVENTORY_KIND,
    ARTIFACT_INVENTORY_SCHEMA_VERSION,
    ArtifactChecksumMode,
    ArtifactDirection,
    ArtifactInventory,
    ArtifactInventoryEntry,
)

ARTIFACT_INVENTORY_DEFAULT_HASH_CHUNK_SIZE = 1024 * 1024


class ArtifactInventoryReadError(ValueError):
    """An inventory cannot be read as the supported portable contract."""


def _inventory_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key.")
        result[key] = value
    return result


def _reject_inventory_json_constant(value: str) -> None:
    raise ValueError("Non-finite JSON constant.")


def _inventory_fields(value: Any, expected: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("Invalid object fields.")
    return value.copy()


def read_artifact_inventory(path: str | Path) -> ArtifactInventory:
    """Read exact v0.1 JSON, delegating artifact semantics to the existing models."""
    if not isinstance(path, (str, Path)) or path == "":
        raise ArtifactInventoryReadError("path must be a Path or non-empty string.")
    try:
        target = Path(path)
        if not stat.S_ISREG(target.stat().st_mode):
            raise ArtifactInventoryReadError(
                "Artifact inventory must be a regular file."
            )
        with target.open(encoding="utf-8") as stream:
            data = json.load(
                stream,
                object_pairs_hook=_inventory_json_object,
                parse_constant=_reject_inventory_json_constant,
            )
    except ArtifactInventoryReadError:
        raise
    except FileNotFoundError:
        raise ArtifactInventoryReadError(
            "Artifact inventory file is missing."
        ) from None
    except OSError:
        raise ArtifactInventoryReadError(
            "Artifact inventory file cannot be read."
        ) from None
    except (ValueError, RecursionError):
        raise ArtifactInventoryReadError(
            "Artifact inventory is not valid UTF-8 JSON."
        ) from None
    if not isinstance(data, dict):
        raise ArtifactInventoryReadError(
            "Artifact inventory root must be a JSON object."
        )
    if data.get("schema_version") != ARTIFACT_INVENTORY_SCHEMA_VERSION:
        raise ArtifactInventoryReadError(
            "Unsupported artifact inventory schema_version."
        )
    if data.get("kind") != ARTIFACT_INVENTORY_KIND:
        raise ArtifactInventoryReadError("Unsupported artifact inventory kind.")
    try:
        count_names = {
            "artifact_count",
            "input_artifact_count",
            "output_artifact_count",
        }
        values = _inventory_fields(
            data, {item.name for item in fields(ArtifactInventory)} | count_names
        )
        values.pop("schema_version")
        values.pop("kind")
        counts = {name: values.pop(name) for name in count_names}
        if not isinstance(values["artifacts"], list):
            raise ValueError("artifacts must be a JSON array.")
        values["artifacts"] = tuple(
            ArtifactInventoryEntry(
                **_inventory_fields(
                    entry, {item.name for item in fields(ArtifactInventoryEntry)}
                )
            )
            for entry in values["artifacts"]
        )
        inventory = ArtifactInventory(**values)
        if any(
            type(count) is not int or count != getattr(inventory, name)
            for name, count in counts.items()
        ):
            raise ValueError("Invalid derived counts.")
        return inventory
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise ArtifactInventoryReadError("Invalid artifact inventory fields.") from None


@dataclass(frozen=True)
class ArtifactInventoryFileSpec:
    """Authoritative metadata plus an execution-only local path; performs no I/O."""

    artifact_id: str
    direction: ArtifactDirection
    role: str
    local_path: Path
    path: str
    format: str
    condition: str | None = None

    def __post_init__(self) -> None:
        # Path() produces the platform's concrete Path type (e.g. PosixPath).
        if type(self.local_path) is not type(Path()):
            raise ValueError("local_path must be an exact Path")
        _metadata_entry(self)


def _metadata_entry(spec: ArtifactInventoryFileSpec) -> ArtifactInventoryEntry:
    return ArtifactInventoryEntry(
        artifact_id=spec.artifact_id,
        direction=spec.direction,
        role=spec.role,
        path=spec.path,
        format=spec.format,
        byte_size=0,
        sha256=None,
        condition=spec.condition,
    )


class ArtifactInventoryBuildError(ValueError):
    """A declared file could not be inspected consistently; no partial result."""


def _descriptor_stat(stream: BinaryIO) -> os.stat_result | None:
    try:
        descriptor = stream.fileno()
    except (AttributeError, io.UnsupportedOperation):
        return None
    return os.fstat(descriptor)


def _same_file_state(before: os.stat_result, after: os.stat_result) -> bool:
    return (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)


def stream_file_sha256(
    path: Path,
    *,
    chunk_size: int = ARTIFACT_INVENTORY_DEFAULT_HASH_CHUNK_SIZE,
) -> str:
    """Hash bounded binary chunks, checking byte count and descriptor stability."""
    if type(path) is not type(Path()):
        raise ValueError("path must be an exact Path")
    if (
        isinstance(chunk_size, bool)
        or not isinstance(chunk_size, int)
        or chunk_size <= 0
    ):
        raise ValueError("chunk_size must be a positive integer")
    digest = hashlib.sha256()
    byte_count = 0
    with path.open("rb") as stream:
        before = _descriptor_stat(stream)
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
            byte_count += len(chunk)
        after = _descriptor_stat(stream)
        if (
            before is not None
            and after is not None
            and (not _same_file_state(before, after) or byte_count != before.st_size)
        ):
            raise ValueError("File changed during SHA256 hashing.")
    return digest.hexdigest()


def build_artifact_inventory(
    *,
    run_id: str,
    workflow: str,
    inventory_path: str,
    file_specs: tuple[ArtifactInventoryFileSpec, ...],
    checksum_mode: ArtifactChecksumMode = "none",
) -> ArtifactInventory:
    """Inspect only declared regular files, with all metadata validated before I/O."""
    if not isinstance(file_specs, tuple) or not all(
        type(spec) is ArtifactInventoryFileSpec for spec in file_specs
    ):
        raise ValueError(
            "file_specs must be a tuple of ArtifactInventoryFileSpec values"
        )
    if checksum_mode not in ("none", "sha256"):
        raise ValueError("checksum_mode must be none or sha256")
    # Validate the entire portable contract before inspecting even the first file.
    metadata = ArtifactInventory(
        run_id=run_id,
        workflow=workflow,
        inventory_path=inventory_path,
        checksum_mode="none",
        artifacts=tuple(_metadata_entry(spec) for spec in file_specs),
    )
    entries: list[ArtifactInventoryEntry] = []
    for spec, entry in zip(file_specs, metadata.artifacts, strict=True):
        try:
            before = spec.local_path.stat()
            if not stat.S_ISREG(before.st_mode):
                raise ArtifactInventoryBuildError(
                    f"Artifact '{entry.artifact_id}' must be a regular file."
                )
        except ArtifactInventoryBuildError:
            raise
        except (OSError, ValueError):
            raise ArtifactInventoryBuildError(
                f"Could not inspect artifact '{entry.artifact_id}'."
            ) from None
        checksum = None
        if checksum_mode == "sha256":
            try:
                checksum = stream_file_sha256(spec.local_path)
                after = spec.local_path.stat()
                # The stream checks bytes read against its descriptor's size;
                # these metadata checks also cover the surrounding inspection.
                if not _same_file_state(before, after):
                    raise ValueError("File changed during SHA256 hashing.")
            except (OSError, ValueError):
                raise ArtifactInventoryBuildError(
                    f"Could not hash artifact '{entry.artifact_id}'."
                ) from None
        entries.append(replace(entry, byte_size=before.st_size, sha256=checksum))
    return replace(metadata, checksum_mode=checksum_mode, artifacts=tuple(entries))


@dataclass(frozen=True)
class ArtifactInventoryWriteResult:
    """Internal writer outcome; its output path is outside the portable payload."""

    output_path: Path
    written: bool
    error: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.output_path, Path):
            raise ValueError("output_path must be a Path")
        if type(self.written) is not bool:
            raise ValueError("written must be a bool")
        if self.error is not None and (
            not isinstance(self.error, str)
            or not self.error
            or self.error != self.error.strip()
        ):
            raise ValueError("error must be a non-empty stripped string")
        if self.written != (self.error is None):
            raise ValueError("written must be true exactly when error is absent")

    @property
    def passed(self) -> bool:
        return self.written and self.error is None

    def to_dict(self) -> dict[str, object]:
        return {
            "output_path": str(self.output_path),
            "written": self.written,
            "error": self.error,
            "passed": self.passed,
        }


def write_artifact_inventory(
    inventory: ArtifactInventory,
    output_root: str | Path,
    *,
    overwrite: bool = False,
) -> ArtifactInventoryWriteResult:
    """Publish complete JSON from a same-directory temporary file, without hashing."""
    if type(inventory) is not ArtifactInventory:
        raise ValueError("inventory must be an exact ArtifactInventory")
    if type(overwrite) is not bool:
        raise ValueError("overwrite must be a bool")
    if not isinstance(output_root, (str, Path)) or output_root == "":
        raise ValueError("output_root must be a Path or non-empty string")
    target = Path(output_root) / inventory.inventory_path
    temporary: Path | None = None
    error: str | None = None
    try:
        if not overwrite and os.path.lexists(target):
            return ArtifactInventoryWriteResult(target, False, "Target already exists.")
        payload = (
            json.dumps(
                inventory.to_dict(),
                indent=2,
                sort_keys=False,
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=target.parent,
            prefix=f".{ARTIFACT_INVENTORY_FILENAME}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
        if overwrite:
            os.replace(temporary, target)
        else:
            # Atomic publication also protects a target created concurrently.
            os.link(temporary, target)
    except FileExistsError:
        error = "Target already exists."
    except OSError:
        error = "Filesystem write failed."
    except (TypeError, ValueError, OverflowError, RecursionError):
        error = "JSON serialization failed."
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                error = "Temporary file cleanup failed."
    return ArtifactInventoryWriteResult(target, error is None, error)


__all__ = [
    "ARTIFACT_INVENTORY_DEFAULT_HASH_CHUNK_SIZE",
    "ArtifactInventoryBuildError",
    "ArtifactInventoryFileSpec",
    "ArtifactInventoryReadError",
    "ArtifactInventoryWriteResult",
    "build_artifact_inventory",
    "read_artifact_inventory",
    "stream_file_sha256",
    "write_artifact_inventory",
]
