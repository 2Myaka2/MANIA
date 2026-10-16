"""Supplied annotations with explicit completeness and unknown/false states."""

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


class _Annotation(_StrictModel):
    system_id: Text
    annotation_id: Text
    annotation_kind: Literal["region", "site", "variant"]
    reference_chain_id: Text
    start_position: Position | None
    end_position: Position | None
    site_position: Position | None
    value: str | bool | None
    knowledge_state: Literal["known", "unknown"]

    @model_validator(mode="after")
    def _shape(self) -> Self:
        if self.annotation_kind == "region":
            if (
                self.start_position is None
                or self.end_position is None
                or self.start_position > self.end_position
                or self.site_position is not None
            ):
                raise ValueError("Region requires inclusive bounds and no site")
        elif (
            self.site_position is None
            or self.start_position is not None
            or self.end_position is not None
        ):
            raise ValueError("Site/variant requires a site and no region bounds")
        if self.knowledge_state == "unknown" and self.value is not None:
            raise ValueError("Unknown annotation requires null value")
        return self

    def covers(self, key: ReferenceResidueKey) -> bool:
        if key.reference_chain_id != self.reference_chain_id:
            return False
        if self.site_position is not None:
            return key.reference_position == self.site_position
        assert self.start_position is not None and self.end_position is not None
        return self.start_position <= key.reference_position <= self.end_position


class RegionAnnotation(_Annotation):
    annotation_kind: Literal["region"]


class SiteAnnotation(_Annotation):
    annotation_kind: Literal["site"]


class VariantAnnotation(_Annotation):
    annotation_kind: Literal["variant"]


class _AnnotationParameters(_StrictModel):
    complete_site_roster: bool
    complete_variant_roster: bool
    complete_region_roster: bool


class SystemAnnotations(_StrictModel):
    schema_version: Literal["mania.annotations.v1"]
    kind: Literal["mania_annotations"]
    identity: InputIdentity
    reference: ReferenceIdentity
    parameters: _AnnotationParameters
    records: tuple[RegionAnnotation | SiteAnnotation | VariantAnnotation, ...]
    authority: tuple[AuthorityBinding, ...]

    @model_validator(mode="after")
    def _binding(self) -> Self:
        ids = [row.annotation_id for row in self.records]
        if len(set(ids)) != len(ids):
            raise ValueError("Annotation identifiers must be unique")
        if any(row.system_id != self.identity.system_id for row in self.records):
            raise ValueError("Annotation system identity mismatch")
        if not any(
            binding.source_identity == self.identity for binding in self.authority
        ) or any(
            binding.source_identity is not None
            and binding.source_identity != self.identity
            for binding in self.authority
        ):
            raise ValueError("Annotations require exact supplied authority binding")
        return self

    def validate_reference(self, reference: ProteinReference) -> None:
        if (
            type(reference) is not ProteinReference
            or self.reference != reference.reference
        ):
            raise ValueError("Annotation reference identity/digest mismatch")
        reference._require_verified()
        for row in self.records:
            positions = (
                (row.site_position,)
                if row.site_position is not None
                else (
                    row.start_position,
                    row.end_position,
                )
            )
            for position in positions:
                if position is None:
                    raise ValueError("Annotation is missing its reference position")
                reference.residue_at(
                    ReferenceResidueKey(
                        reference_chain_id=row.reference_chain_id,
                        reference_position=position,
                    )
                )

    def annotation_ids(self, key: ReferenceResidueKey) -> tuple[str, ...] | None:
        if type(key) is not ReferenceResidueKey:
            raise ValueError("Explicit reference key required")
        chain = next(
            (c for c in self.reference.chains if c.chain_id == key.reference_chain_id),
            None,
        )
        if chain is None or key.reference_position > len(chain.sequence):
            raise ValueError("Annotation key is outside reference roster")
        relevant = [row for row in self.records if row.covers(key)]
        if any(row.knowledge_state == "unknown" for row in relevant):
            return None
        if not all(
            (
                self.parameters.complete_region_roster,
                self.parameters.complete_site_roster,
                self.parameters.complete_variant_roster,
            )
        ):
            return None
        return tuple(row.annotation_id for row in relevant if row.value is not False)


def __getattr__(name: str) -> object:
    if name in (
        "BiologicalAnnotationError",
        "CanonicalResidueBiologicalAnnotation",
        "CanonicalVariantSiteAnnotation",
        "DatasetSystemBiologicalAnnotations",
        "GlycosylationSiteAnnotation",
        "NAPI2B_ECD_END",
        "NAPI2B_ECD_START",
        "NAPI2B_MX35_END",
        "NAPI2B_MX35_START",
        "is_napi2b_ecd_residue",
        "is_napi2b_mx35_residue",
    ):
        raise ImportError(
            "Fixed NaPi2b API moved to mania_napi2b.biological_annotations; "
            "install mania-napi2b and explicitly select a profile."
        )
    raise AttributeError(name)
