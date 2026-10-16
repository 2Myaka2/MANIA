"""Strict explicit molecular-partner control files; no classification inference."""

import json
import os
import stat
import tempfile
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from mania.preprocessing.molecular_partner_entities import (
    ExplicitMolecularPartnerDefinition,
    MolecularPartnerComponentClassification,
    _require_records,
)

MOLECULAR_PARTNER_METADATA_SCHEMA_VERSION = "mania.molecular_partner_metadata.v0.1"
MOLECULAR_PARTNER_METADATA_KIND = "mania_molecular_partner_metadata"


@dataclass(frozen=True)
class MolecularPartnerMetadata:
    classifications: tuple[MolecularPartnerComponentClassification, ...]
    explicit_partners: tuple[ExplicitMolecularPartnerDefinition, ...]
    schema_version: str = field(
        init=False, default=MOLECULAR_PARTNER_METADATA_SCHEMA_VERSION
    )
    kind: str = field(init=False, default=MOLECULAR_PARTNER_METADATA_KIND)

    def __post_init__(self) -> None:
        _require_records(
            self.classifications,
            MolecularPartnerComponentClassification,
            "classifications",
        )
        _require_records(
            self.explicit_partners,
            ExplicitMolecularPartnerDefinition,
            "explicit_partners",
        )
        indexes = [c.residue_index for c in self.classifications]
        if len(set(indexes)) != len(indexes):
            raise ValueError("Duplicate classification residue indexes")
        ids = [p.partner_id for p in self.explicit_partners]
        components = [
            i for p in self.explicit_partners for i in p.component_residue_indexes
        ]
        if len(set(ids)) != len(ids) or len(set(components)) != len(components):
            raise ValueError(
                "Explicit partner IDs and component membership must be unique"
            )
        object.__setattr__(
            self,
            "classifications",
            tuple(sorted(self.classifications, key=lambda c: c.residue_index)),
        )
        object.__setattr__(
            self,
            "explicit_partners",
            tuple(
                sorted(
                    self.explicit_partners,
                    key=lambda p: (p.partner_kind == "glycan", p.partner_id),
                )
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "classifications": [c.to_dict() for c in self.classifications],
            "explicit_partners": [p.to_dict() for p in self.explicit_partners],
        }


class MolecularPartnerMetadataReadError(ValueError):
    """Invalid or unreadable explicit molecular-partner metadata."""


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise ValueError("Non-finite JSON constant")


def read_strict_json(path: str | Path) -> Any:
    target = Path(path)
    if not stat.S_ISREG(target.stat().st_mode):
        raise ValueError("Expected a regular JSON file")
    return json.loads(
        target.read_text(encoding="utf-8"),
        object_pairs_hook=_object,
        parse_constant=_constant,
    )


def exact_fields(value: Any, names: set[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != names:
        raise ValueError("Invalid JSON object fields")
    return value.copy()


def json_array(value: Any) -> list[Any]:
    if type(value) is not list:
        raise ValueError("Expected a JSON array")
    return value


def reconstruct_record(value: Any, model: type[Any]) -> Any:
    values = exact_fields(value, {f.name for f in fields(model)})
    for item in fields(model):
        if not item.init:
            actual = values.pop(item.name)
            if type(actual) is not type(item.default) or actual != item.default:
                raise ValueError("Unsupported fixed contract field")
    for name in ("component_residue_indexes", "component_atom_indexes", "atom_indexes"):
        if name in values:
            values[name] = tuple(json_array(values[name]))
    return model(**values)


def read_molecular_partner_metadata(path: str | Path) -> MolecularPartnerMetadata:
    try:
        data = exact_fields(
            read_strict_json(path), {f.name for f in fields(MolecularPartnerMetadata)}
        )
        if (
            data.pop("schema_version") != MOLECULAR_PARTNER_METADATA_SCHEMA_VERSION
            or data.pop("kind") != MOLECULAR_PARTNER_METADATA_KIND
        ):
            raise ValueError("Unsupported metadata contract")
        return MolecularPartnerMetadata(
            tuple(
                reconstruct_record(c, MolecularPartnerComponentClassification)
                for c in json_array(data["classifications"])
            ),
            tuple(
                reconstruct_record(p, ExplicitMolecularPartnerDefinition)
                for p in json_array(data["explicit_partners"])
            ),
        )
    except (OSError, TypeError, ValueError, OverflowError, RecursionError):
        raise MolecularPartnerMetadataReadError(
            "Invalid or unreadable molecular partner metadata."
        ) from None


@dataclass(frozen=True)
class SpecializedArtifactWriteResult:
    output_path: Path
    written: bool
    error: str | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.output_path, Path)
            or type(self.written) is not bool
            or self.written != (self.error is None)
        ):
            raise ValueError("Invalid artifact write outcome")
        if self.error is not None and (
            not isinstance(self.error, str) or not self.error
        ):
            raise ValueError("Invalid artifact write error")

    @property
    def passed(self) -> bool:
        return self.written


@dataclass(frozen=True)
class SpecializedArtifactValidationReport:
    path: Path
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.error is None


def write_atomic_text(
    payload: str, target: Path, *, overwrite: bool
) -> SpecializedArtifactWriteResult:
    if type(overwrite) is not bool:
        raise ValueError("overwrite must be a bool")
    temporary: Path | None = None
    error = None
    try:
        if not overwrite and os.path.lexists(target):
            return SpecializedArtifactWriteResult(
                target, False, "Target already exists."
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
            os.link(temporary, target)
    except FileExistsError:
        error = "Target already exists."
    except OSError:
        error = "Filesystem write failed."
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                error = "Temporary file cleanup failed."
    return SpecializedArtifactWriteResult(target, error is None, error)


def write_molecular_partner_metadata(
    metadata: MolecularPartnerMetadata, path: str | Path, *, overwrite: bool = False
) -> SpecializedArtifactWriteResult:
    if type(metadata) is not MolecularPartnerMetadata:
        raise ValueError("metadata must be exact MolecularPartnerMetadata")
    payload = (
        json.dumps(metadata.to_dict(), indent=2, ensure_ascii=False, allow_nan=False)
        + "\n"
    )
    return write_atomic_text(payload, Path(path), overwrite=overwrite)


def validate_molecular_partner_metadata(
    path: str | Path,
) -> SpecializedArtifactValidationReport:
    try:
        read_molecular_partner_metadata(path)
    except MolecularPartnerMetadataReadError as exc:
        return SpecializedArtifactValidationReport(Path(path), str(exc))
    return SpecializedArtifactValidationReport(Path(path))
