"""Explicit Stage 30.B source identities; numeric equality has no authority."""

import re
from dataclasses import dataclass, field, fields
from typing import Literal

from mania_napi2b.canonical_reference import (
    NAPI2B_CANONICAL_ISOFORM_ID,
    NAPI2B_CANONICAL_SEQUENCE_LENGTH,
    NAPI2B_CANONICAL_SEQUENCE_SHA256,
    NAPI2B_UNIPROT_SEQUENCE_VERSION,
    CanonicalProteinReference,
    CanonicalResidueReference,
)

CANONICAL_RESIDUE_MAPPING_SCHEMA_VERSION = "mania.canonical_residue_mapping.v0.1"
CANONICAL_RESIDUE_MAPPING_KIND = "mania_canonical_residue_mapping"
CANONICAL_RESIDUE_MAPPING_REFERENCE_ID = (
    f"uniprotkb:{NAPI2B_CANONICAL_ISOFORM_ID}:"
    f"sequence-v{NAPI2B_UNIPROT_SEQUENCE_VERSION}"
)
CANONICAL_RESIDUE_MAPPING_REFERENCE_SHA256 = NAPI2B_CANONICAL_SEQUENCE_SHA256

CanonicalResidueMappingStatus = Literal["mapped", "unmapped"]


class CanonicalResidueMappingError(ValueError):
    """Invalid explicit mapping contract or missing required source record."""


def _text(value: object, name: str) -> None:
    if type(value) is not str or not value or value != value.strip():
        raise CanonicalResidueMappingError(
            f"{name} must be a non-empty stripped string"
        )


def _source_key(
    source_engine: str,
    source_chain_id: str | None,
    source_resid: str,
    source_resname: str,
) -> tuple[str, str | None, str, str]:
    if type(source_engine) is not str or source_engine not in ("gromacs", "namd"):
        raise CanonicalResidueMappingError("source_engine must be gromacs or namd")
    if source_chain_id is not None:
        _text(source_chain_id, "source_chain_id")
    _text(source_resid, "source_resid")
    _text(source_resname, "source_resname")
    return source_engine, source_chain_id, source_resid, source_resname


@dataclass(frozen=True)
class CanonicalResidueMappingRecord:
    """Source evidence and explicit canonical state in separate namespaces.

    Construction checks canonical syntax/range. Reference validation establishes
    the standard canonical name at that position, without translating source names.
    """

    source_engine: str
    source_chain_id: str | None
    source_resid: str
    source_resname: str
    canonical_residue_number: int | None
    canonical_resname: str | None
    mapping_status: CanonicalResidueMappingStatus

    def __post_init__(self) -> None:
        _source_key(
            self.source_engine,
            self.source_chain_id,
            self.source_resid,
            self.source_resname,
        )
        if type(self.mapping_status) is not str or self.mapping_status not in (
            "mapped",
            "unmapped",
        ):
            raise CanonicalResidueMappingError(
                "mapping_status must be mapped or unmapped"
            )
        if self.mapping_status == "unmapped":
            if (
                self.canonical_residue_number is not None
                or self.canonical_resname is not None
            ):
                raise CanonicalResidueMappingError(
                    "unmapped canonical fields must both be None"
                )
        else:
            if (
                type(self.canonical_residue_number) is not int
                or not 1
                <= self.canonical_residue_number
                <= NAPI2B_CANONICAL_SEQUENCE_LENGTH
            ):
                raise CanonicalResidueMappingError(
                    "canonical_residue_number must be an integer in 1..690"
                )
            if (
                type(self.canonical_resname) is not str
                or re.fullmatch(r"[A-Z]{3}", self.canonical_resname) is None
            ):
                raise CanonicalResidueMappingError(
                    "canonical_resname must contain three uppercase ASCII letters"
                )

    @property
    def source_key(self) -> tuple[str, str | None, str, str]:
        """Return the complete exact source namespace, without canonical values."""
        return (
            self.source_engine,
            self.source_chain_id,
            self.source_resid,
            self.source_resname,
        )

    def to_dict(self) -> dict[str, object]:
        """Return independent scalars in declaration order."""
        return {item.name: getattr(self, item.name) for item in fields(self)}


@dataclass(frozen=True)
class CanonicalResidueMappingTable:
    """Ordered unique source records; empty and sparse tables are valid.

    Repeated canonical targets are allowed. This contract makes no trajectory
    coverage claim and contains no Dataset binding or lookup policy.
    """

    mappings: tuple[CanonicalResidueMappingRecord, ...]
    schema_version: str = field(
        init=False, default=CANONICAL_RESIDUE_MAPPING_SCHEMA_VERSION
    )
    kind: str = field(init=False, default=CANONICAL_RESIDUE_MAPPING_KIND)
    canonical_reference_id: str = field(
        init=False, default=CANONICAL_RESIDUE_MAPPING_REFERENCE_ID
    )
    canonical_reference_sequence_sha256: str = field(
        init=False, default=CANONICAL_RESIDUE_MAPPING_REFERENCE_SHA256
    )

    def __post_init__(self) -> None:
        if type(self.mappings) is not tuple or any(
            type(record) is not CanonicalResidueMappingRecord
            for record in self.mappings
        ):
            raise CanonicalResidueMappingError(
                "mappings must be a tuple of exact CanonicalResidueMappingRecord"
            )
        keys = [record.source_key for record in self.mappings]
        if len(set(keys)) != len(keys):
            raise CanonicalResidueMappingError("Duplicate source key")
        sort_keys = [
            (engine, chain if chain is not None else "", resid, resname)
            for engine, chain, resid, resname in keys
        ]
        if sort_keys != sorted(sort_keys):
            raise CanonicalResidueMappingError(
                "mappings must be ordered by exact source key"
            )

    def to_dict(self) -> dict[str, object]:
        """Return the self-describing JSON contract in fixed root/record order."""
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "canonical_reference_id": self.canonical_reference_id,
            "canonical_reference_sequence_sha256": (
                self.canonical_reference_sequence_sha256
            ),
            "mapping_count": len(self.mappings),
            "mappings": [record.to_dict() for record in self.mappings],
        }


def _require_table(table: CanonicalResidueMappingTable) -> None:
    if type(table) is not CanonicalResidueMappingTable:
        raise CanonicalResidueMappingError(
            "table must be exact CanonicalResidueMappingTable"
        )


def _require_reference(reference: CanonicalProteinReference) -> None:
    if type(reference) is not CanonicalProteinReference:
        raise CanonicalResidueMappingError(
            "reference must be exact CanonicalProteinReference"
        )
    if reference.reference_id != CANONICAL_RESIDUE_MAPPING_REFERENCE_ID:
        raise CanonicalResidueMappingError(
            "reference_id must match the pinned reference"
        )
    if reference.sequence_sha256 != CANONICAL_RESIDUE_MAPPING_REFERENCE_SHA256:
        raise CanonicalResidueMappingError(
            "sequence_sha256 must match the pinned reference"
        )


def _mapped_residue(
    record: CanonicalResidueMappingRecord, reference: CanonicalProteinReference
) -> CanonicalResidueReference:
    if record.mapping_status != "mapped":
        raise CanonicalResidueMappingError("Source residue is explicitly unmapped")
    number = record.canonical_residue_number
    if type(number) is not int or not 1 <= number <= NAPI2B_CANONICAL_SEQUENCE_LENGTH:
        raise CanonicalResidueMappingError(
            "canonical_residue_number must be an integer in 1..690"
        )
    residue = reference.residue_at(number)
    if record.canonical_resname != residue.canonical_resname:
        raise CanonicalResidueMappingError(
            f"canonical_resname must match the pinned reference at position {number}"
        )
    return residue


def validate_canonical_residue_mapping_table(
    table: CanonicalResidueMappingTable,
    *,
    reference: CanonicalProteinReference,
) -> CanonicalResidueMappingTable:
    """Validate canonical targets against the accepted local reference unchanged."""
    _require_table(table)
    _require_reference(reference)
    for record in table.mappings:
        if record.mapping_status == "mapped":
            _mapped_residue(record, reference)
    return table


def find_source_residue_mapping(
    table: CanonicalResidueMappingTable,
    *,
    source_engine: str,
    source_chain_id: str | None,
    source_resid: str,
    source_resname: str,
) -> CanonicalResidueMappingRecord | None:
    """Find an exact record; absent valid keys return None, with no fallback."""
    _require_table(table)
    key = _source_key(source_engine, source_chain_id, source_resid, source_resname)
    return next((record for record in table.mappings if record.source_key == key), None)


def require_source_residue_mapping(
    table: CanonicalResidueMappingTable,
    *,
    source_engine: str,
    source_chain_id: str | None,
    source_resid: str,
    source_resname: str,
) -> CanonicalResidueMappingRecord:
    """Require any explicit record, including an explicit unmapped record."""
    record = find_source_residue_mapping(
        table,
        source_engine=source_engine,
        source_chain_id=source_chain_id,
        source_resid=source_resid,
        source_resname=source_resname,
    )
    if record is None:
        raise CanonicalResidueMappingError("No explicit source residue mapping")
    return record


def require_mapped_source_residue(
    table: CanonicalResidueMappingTable,
    *,
    source_engine: str,
    source_chain_id: str | None,
    source_resid: str,
    source_resname: str,
) -> CanonicalResidueMappingRecord:
    """Require an explicit mapped record; absence and explicit unmapped both fail."""
    record = require_source_residue_mapping(
        table,
        source_engine=source_engine,
        source_chain_id=source_chain_id,
        source_resid=source_resid,
        source_resname=source_resname,
    )
    if record.mapping_status != "mapped":
        raise CanonicalResidueMappingError("Source residue is explicitly unmapped")
    return record


def canonical_residue_for_mapping(
    record: CanonicalResidueMappingRecord,
    reference: CanonicalProteinReference,
) -> CanonicalResidueReference:
    """Resolve only an explicit mapped record to its validated canonical residue."""
    if type(record) is not CanonicalResidueMappingRecord:
        raise CanonicalResidueMappingError(
            "record must be exact CanonicalResidueMappingRecord"
        )
    _require_reference(reference)
    return _mapped_residue(record, reference)


__all__ = [
    "CANONICAL_RESIDUE_MAPPING_KIND",
    "CANONICAL_RESIDUE_MAPPING_REFERENCE_ID",
    "CANONICAL_RESIDUE_MAPPING_REFERENCE_SHA256",
    "CANONICAL_RESIDUE_MAPPING_SCHEMA_VERSION",
    "CanonicalResidueMappingError",
    "CanonicalResidueMappingRecord",
    "CanonicalResidueMappingStatus",
    "CanonicalResidueMappingTable",
    "canonical_residue_for_mapping",
    "find_source_residue_mapping",
    "require_mapped_source_residue",
    "require_source_residue_mapping",
    "validate_canonical_residue_mapping_table",
]
