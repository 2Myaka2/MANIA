"""Explicit full source identities, coverage and reference-bound mappings."""

from typing import Literal, Self

from pydantic import model_validator

from mania.canonical_reference import (
    AuthorityBinding,
    InputIdentity,
    Position,
    ProteinReference,
    ReferenceIdentity,
    ReferenceResidueKey,
    Text,
    _StrictModel,
)


class SourceResidueKey(_StrictModel):
    engine: Literal["gromacs", "namd"]
    namespace_kind: Literal["chain", "segment"]
    chain_id: Text | None
    segment_id: Text | None
    resid: Text
    insertion_code: Text | None
    resname: Text


class ResidueMappingRecord(_StrictModel):
    source: SourceResidueKey
    mapping_status: Literal["mapped", "unmapped"]
    reference_chain_id: Text | None
    reference_position: Position | None
    reference_resname: Text | None
    reason_code: Text | None

    @model_validator(mode="after")
    def _status(self) -> Self:
        values = (
            self.reference_chain_id,
            self.reference_position,
            self.reference_resname,
        )
        if self.mapping_status == "mapped":
            if any(value is None for value in values):
                raise ValueError("Mapped records require reference fields")
        elif any(value is not None for value in values) or self.reason_code is None:
            raise ValueError(
                "Unmapped records require null reference fields and an explicit reason"
            )
        return self


class _MappingParameters(_StrictModel):
    represented_source_roster: tuple[SourceResidueKey, ...]


class ResidueMappingTable(_StrictModel):
    schema_version: Literal["mania.residue_mapping.v1"]
    kind: Literal["mania_residue_mapping"]
    identity: InputIdentity
    reference: ReferenceIdentity
    parameters: _MappingParameters
    records: tuple[ResidueMappingRecord, ...]
    authority: tuple[AuthorityBinding, ...]

    @model_validator(mode="after")
    def _coverage(self) -> Self:
        sources = [record.source for record in self.records]
        roster = self.parameters.represented_source_roster
        if len(set(roster)) != len(roster) or len(set(sources)) != len(sources):
            raise ValueError("Source keys must be unique")
        if set(sources) != set(roster):
            raise ValueError("Mapping must cover exactly the represented source roster")
        if any(source.engine != self.identity.engine for source in sources):
            raise ValueError("Source engine conflicts with mapping identity")
        targets = [
            (record.reference_chain_id, record.reference_position)
            for record in self.records
            if record.mapping_status == "mapped"
        ]
        if len(set(targets)) != len(targets):
            raise ValueError("Represented mapped targets must be unique")
        if not any(
            binding.source_identity == self.identity for binding in self.authority
        ) or any(
            binding.source_identity is not None
            and binding.source_identity != self.identity
            for binding in self.authority
        ):
            raise ValueError("Mapping requires exact source-bound authority")
        return self

    def validate_reference(self, reference: ProteinReference) -> None:
        if (
            type(reference) is not ProteinReference
            or self.reference != reference.reference
        ):
            raise ValueError("Mapping reference identity/digest mismatch")
        reference._require_verified()
        for record in self.records:
            if record.mapping_status == "mapped":
                if (
                    record.reference_chain_id is None
                    or record.reference_position is None
                ):
                    raise ValueError("Mapped record is missing reference identity")
                key = ReferenceResidueKey(
                    reference_chain_id=record.reference_chain_id,
                    reference_position=record.reference_position,
                )
                if reference.residue_at(key).resname != record.reference_resname:
                    raise ValueError("Mapped reference chemistry mismatch")


def require_mapped_source_residue(
    table: ResidueMappingTable,
    source: SourceResidueKey,
) -> ResidueMappingRecord:
    if type(table) is not ResidueMappingTable or type(source) is not SourceResidueKey:
        raise ValueError("Explicit mapping table and full source key are required")
    for record in table.records:
        if record.source == source:
            if record.mapping_status == "mapped":
                return record
            raise ValueError("Source residue is explicitly unmapped")
    raise ValueError("No explicit source residue mapping")


def __getattr__(name: str) -> object:
    if name in (
        "CANONICAL_RESIDUE_MAPPING_KIND",
        "CANONICAL_RESIDUE_MAPPING_REFERENCE_ID",
        "CANONICAL_RESIDUE_MAPPING_REFERENCE_SHA256",
        "CANONICAL_RESIDUE_MAPPING_SCHEMA_VERSION",
        "CanonicalResidueMappingError",
        "CanonicalResidueMappingRecord",
        "CanonicalResidueMappingTable",
        "canonical_residue_for_mapping",
        "find_source_residue_mapping",
        "require_source_residue_mapping",
        "validate_canonical_residue_mapping_table",
    ):
        raise ImportError(
            "Fixed NaPi2b API moved to mania_napi2b.canonical_residue_mapping; "
            "install mania-napi2b and explicitly select a profile."
        )
    raise AttributeError(name)
