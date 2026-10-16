"""Strict offline JSON control artifacts for explicit Stage 30.B mappings."""

import json
import os
import stat
import tempfile
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

from mania_napi2b.canonical_reference_io import load_default_napi2b_canonical_reference
from mania_napi2b.canonical_residue_mapping import (
    CANONICAL_RESIDUE_MAPPING_KIND,
    CANONICAL_RESIDUE_MAPPING_REFERENCE_ID,
    CANONICAL_RESIDUE_MAPPING_REFERENCE_SHA256,
    CANONICAL_RESIDUE_MAPPING_SCHEMA_VERSION,
    CanonicalResidueMappingRecord,
    CanonicalResidueMappingTable,
    validate_canonical_residue_mapping_table,
)

CANONICAL_RESIDUE_MAPPING_FILENAME = "canonical_residue_mapping.json"

_CONTRACT = {
    "schema_version": CANONICAL_RESIDUE_MAPPING_SCHEMA_VERSION,
    "kind": CANONICAL_RESIDUE_MAPPING_KIND,
    "canonical_reference_id": CANONICAL_RESIDUE_MAPPING_REFERENCE_ID,
    "canonical_reference_sequence_sha256": CANONICAL_RESIDUE_MAPPING_REFERENCE_SHA256,
}
_ROOT_FIELDS = (*_CONTRACT, "mapping_count", "mappings")
_ROW_FIELDS = tuple(item.name for item in fields(CanonicalResidueMappingRecord))


class CanonicalResidueMappingReadError(ValueError):
    """Invalid, missing, or unreadable explicit mapping JSON."""


def _text(value: object, name: str) -> None:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError(f"{name} must be a non-empty stripped string")


@dataclass(frozen=True)
class CanonicalResidueMappingWriteResult:
    """Local output path and portable write outcome."""

    output_path: Path
    written: bool
    error: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.output_path, Path):
            raise ValueError("output_path must be a Path")
        if type(self.written) is not bool:
            raise ValueError("written must be a bool")
        if self.error is not None:
            _text(self.error, "error")
        if self.written != (self.error is None):
            raise ValueError("written must be true exactly when error is absent")

    @property
    def passed(self) -> bool:
        return self.written and self.error is None


@dataclass(frozen=True)
class CanonicalResidueMappingValidationIssue:
    """Portable strict-reader issue without local paths or payload contents."""

    field: str
    message: str

    def __post_init__(self) -> None:
        _text(self.field, "field")
        _text(self.message, "message")


@dataclass(frozen=True)
class CanonicalResidueMappingValidationReport:
    """Reader acceptance and counts; acceptance does not establish source coverage."""

    mapping_path: Path
    mapping_count: int | None
    mapped_count: int | None
    unmapped_count: int | None
    issues: tuple[CanonicalResidueMappingValidationIssue, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.mapping_path, Path):
            raise ValueError("mapping_path must be a Path")
        if type(self.issues) is not tuple or any(
            type(issue) is not CanonicalResidueMappingValidationIssue
            for issue in self.issues
        ):
            raise ValueError(
                "issues must be a tuple of exact mapping validation issues"
            )
        for name in ("mapping_count", "mapped_count", "unmapped_count"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{name} must be a non-negative integer or None")
            if (value is None) != bool(self.issues):
                raise ValueError("counts must be absent exactly when issues exist")
        if (
            self.mapping_count is not None
            and self.mapped_count is not None
            and self.unmapped_count is not None
            and self.mapping_count != self.mapped_count + self.unmapped_count
        ):
            raise ValueError(
                "mapping_count must equal mapped_count plus unmapped_count"
            )

    @property
    def passed(self) -> bool:
        return not self.issues


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise ValueError("Non-finite JSON constant")


def _path(path: str | Path) -> Path:
    if not isinstance(path, (str, Path)) or path == "":
        raise ValueError("path must be a Path or non-empty string")
    return Path(path)


def read_canonical_residue_mapping(path: str | Path) -> CanonicalResidueMappingTable:
    """Require exact keys/order, strict scalars, and the packaged canonical target."""
    try:
        target = _path(path)
        if not stat.S_ISREG(target.stat().st_mode):
            raise ValueError("Expected a regular JSON file")
        data = json.loads(
            target.read_text(encoding="utf-8"),
            object_pairs_hook=_object,
            parse_constant=_constant,
        )
        if type(data) is not dict or tuple(data) != _ROOT_FIELDS:
            raise ValueError("Invalid mapping root fields or order")
        for name, expected in _CONTRACT.items():
            if type(data[name]) is not str or data[name] != expected:
                raise ValueError("Unsupported mapping contract")
        rows = data["mappings"]
        if (
            type(rows) is not list
            or type(data["mapping_count"]) is not int
            or data["mapping_count"] != len(rows)
        ):
            raise ValueError("Invalid mapping_count or mappings array")
        records = []
        for row in rows:
            if type(row) is not dict or tuple(row) != _ROW_FIELDS:
                raise ValueError("Invalid mapping record fields or order")
            records.append(CanonicalResidueMappingRecord(**row))
        table = CanonicalResidueMappingTable(tuple(records))
        return validate_canonical_residue_mapping_table(
            table, reference=load_default_napi2b_canonical_reference()
        )
    except (OSError, TypeError, ValueError, OverflowError, RecursionError):
        raise CanonicalResidueMappingReadError(
            "Invalid or unreadable canonical residue mapping."
        ) from None


def write_canonical_residue_mapping(
    table: CanonicalResidueMappingTable,
    path: str | Path,
    *,
    overwrite: bool = False,
) -> CanonicalResidueMappingWriteResult:
    """Validate first, then atomically publish deterministic UTF-8 JSON.

    Invalid arguments/reference semantics raise before filesystem mutation.
    Filesystem or serialization failures return a portable failed write result.
    """
    validate_canonical_residue_mapping_table(
        table, reference=load_default_napi2b_canonical_reference()
    )
    if type(overwrite) is not bool:
        raise ValueError("overwrite must be a bool")
    target = _path(path)
    temporary: Path | None = None
    error: str | None = None
    try:
        if not overwrite and os.path.lexists(target):
            return CanonicalResidueMappingWriteResult(
                target, False, "Target already exists."
            )
        payload = (
            json.dumps(
                table.to_dict(),
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
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
        if overwrite:
            os.replace(temporary, target)
        else:
            # Atomic no-clobber publication, including concurrent destination creation.
            os.link(temporary, target)
    except FileExistsError:
        error = "Target already exists."
    except OSError:
        error = "Filesystem write failed."
    except (TypeError, ValueError, OverflowError):
        error = "JSON serialization failed."
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                error = "Temporary file cleanup failed."
    return CanonicalResidueMappingWriteResult(target, error is None, error)


def validate_canonical_residue_mapping(
    path: str | Path,
) -> CanonicalResidueMappingValidationReport:
    """Delegate all mapping interpretation to the strict reader."""
    target = _path(path)
    try:
        table = read_canonical_residue_mapping(target)
    except CanonicalResidueMappingReadError as exc:
        return CanonicalResidueMappingValidationReport(
            target,
            None,
            None,
            None,
            (CanonicalResidueMappingValidationIssue("mapping", str(exc)),),
        )
    count = len(table.mappings)
    mapped = sum(record.mapping_status == "mapped" for record in table.mappings)
    return CanonicalResidueMappingValidationReport(
        target, count, mapped, count - mapped, ()
    )


__all__ = [
    "CANONICAL_RESIDUE_MAPPING_FILENAME",
    "CanonicalResidueMappingReadError",
    "CanonicalResidueMappingValidationIssue",
    "CanonicalResidueMappingValidationReport",
    "CanonicalResidueMappingWriteResult",
    "read_canonical_residue_mapping",
    "validate_canonical_residue_mapping",
    "write_canonical_residue_mapping",
]
