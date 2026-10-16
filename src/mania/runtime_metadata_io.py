"""Strict, atomic persistence of the accepted runtime metadata contract."""

import json
import os
import stat
import tempfile
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

from mania.runtime_metadata import (
    RUNTIME_METADATA_FILENAME,
    RUNTIME_METADATA_KIND,
    RUNTIME_METADATA_SCHEMA_VERSION,
    RuntimeEnvironment,
    RuntimeMetadata,
    RuntimePerformance,
)


class RuntimeMetadataReadError(ValueError):
    """A file cannot be read as the supported runtime metadata contract."""


def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key.")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError("Non-finite JSON constant.")


def _fields(value: Any, model: type[Any]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        item.name for item in fields(model)
    }:
        raise ValueError("Invalid object fields.")
    return value.copy()


def read_runtime_metadata(path: str | Path) -> RuntimeMetadata:
    """Reconstruct stored observations without recollecting run metadata."""
    if not isinstance(path, (str, Path)) or path == "":
        raise RuntimeMetadataReadError("path must be a Path or non-empty string.")
    try:
        target = Path(path)
        if not stat.S_ISREG(target.stat().st_mode):
            raise RuntimeMetadataReadError("Runtime metadata must be a regular file.")
        with target.open(encoding="utf-8") as stream:
            data = json.load(
                stream,
                object_pairs_hook=_json_object,
                parse_constant=_reject_json_constant,
            )
    except RuntimeMetadataReadError:
        raise
    except FileNotFoundError:
        raise RuntimeMetadataReadError("Runtime metadata file is missing.") from None
    except OSError:
        raise RuntimeMetadataReadError(
            "Runtime metadata file cannot be read."
        ) from None
    except (ValueError, RecursionError):
        raise RuntimeMetadataReadError(
            "Runtime metadata is not valid UTF-8 JSON."
        ) from None
    if not isinstance(data, dict):
        raise RuntimeMetadataReadError("Runtime metadata root must be a JSON object.")
    if data.get("schema_version") != RUNTIME_METADATA_SCHEMA_VERSION:
        raise RuntimeMetadataReadError("Unsupported runtime metadata schema_version.")
    if data.get("kind") != RUNTIME_METADATA_KIND:
        raise RuntimeMetadataReadError("Unsupported runtime metadata kind.")
    try:
        values = _fields(data, RuntimeMetadata)
        for item in fields(RuntimeMetadata):
            if not item.init:
                actual = values.pop(item.name)
                if type(actual) is not type(item.default) or actual != item.default:
                    raise ValueError("Invalid fixed contract field.")
        values["environment"] = RuntimeEnvironment(
            **_fields(values["environment"], RuntimeEnvironment)
        )
        values["performance"] = RuntimePerformance(
            **_fields(values["performance"], RuntimePerformance)
        )
        return RuntimeMetadata(**values)
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise RuntimeMetadataReadError("Invalid runtime metadata fields.") from None


@dataclass(frozen=True)
class RuntimeMetadataWriteResult:
    """Internal write outcome; local paths stay outside the portable model."""

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


def write_runtime_metadata(
    metadata: RuntimeMetadata,
    output_root: str | Path,
    *,
    overwrite: bool = False,
) -> RuntimeMetadataWriteResult:
    """Publish complete UTF-8 JSON atomically, without inspecting artifacts."""
    if type(metadata) is not RuntimeMetadata:
        raise ValueError("metadata must be RuntimeMetadata")
    if type(overwrite) is not bool:
        raise ValueError("overwrite must be a bool")
    if not isinstance(output_root, (str, Path)) or output_root == "":
        raise ValueError("output_root must be a Path or non-empty string")
    target = Path(output_root) / metadata.metadata_path
    directory = target.parent
    temporary: Path | None = None
    error: str | None = None
    try:
        if not overwrite and os.path.lexists(target):
            return RuntimeMetadataWriteResult(target, False, "Target already exists.")
        payload = (
            json.dumps(
                metadata.to_dict(),
                indent=2,
                sort_keys=False,
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        )
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=directory,
            prefix=f".{RUNTIME_METADATA_FILENAME}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
        if overwrite:
            os.replace(temporary, target)
        else:
            # Atomic publication without clobbering a concurrently created target.
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
    return RuntimeMetadataWriteResult(target, error is None, error)


__all__ = [
    "RuntimeMetadataReadError",
    "RuntimeMetadataWriteResult",
    "read_runtime_metadata",
    "write_runtime_metadata",
]
