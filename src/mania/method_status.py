"""Closed per-method states and approved Rg eligibility observations."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BeforeValidator, Field, model_validator

from mania.canonical_reference import InputIdentity
from mania.run_config import (
    PCA,
    QC,
    RMSD,
    Clustering,
    Contacts,
    Digest,
    Method,
    RegionEnrichment,
    Replay,
    Rg,
    RunModel,
    TemporalRin,
    _ordered,
)

MethodID = Literal[
    "contacts",
    "static_rin",
    "communities",
    "region_enrichment",
    "rg",
    "rmsd",
    "typed_interactions",
    "temporal_rin",
    "fingerprints",
    "pca",
    "clustering",
    "physical_windows",
    "lipid_contacts",
    "glycan_contacts",
    "replay",
    "comparison",
    "replica_aggregation",
    "qc",
    "profile_outputs",
]
MethodState = Literal[
    "not_requested",
    "not_applicable",
    "missing_optional_input",
    "planned",
    "running",
    "completed",
    "pending_review",
    "failed",
    "cancelled",
]


class EligibilityObservation(RunModel):
    state: Literal["established", "unestablished", "inapplicable", "invalid"]
    reason_code: str | None
    evidence_roles: Annotated[tuple[str, ...], BeforeValidator(_ordered)] = ()


class RgEligibility(RunModel):
    protein_selection: EligibilityObservation
    masses_and_input: EligibilityObservation
    pbc_suitability: EligibilityObservation


class RgEffectiveParameters(RunModel):
    selection: str
    selection_origin: Literal["automatic_protein", "explicit", "legacy_full_system"]
    include_failed_frames: bool
    resolved_atom_count: Annotated[int, Field(ge=0)] | None
    atom_identity_sha256: Digest | None
    eligibility: RgEligibility


EffectiveOptions = (
    RgEffectiveParameters
    | Contacts
    | RegionEnrichment
    | Rg
    | RMSD
    | TemporalRin
    | PCA
    | Clustering
    | Replay
    | QC
    | Method
)


class MethodStatus(RunModel):
    method_id: MethodID
    identity: InputIdentity | str
    request_origin: Literal["preset", "explicit", "dependency"]
    status: MethodState
    reason_code: str | None = None
    message: str = ""
    prerequisites: Annotated[tuple[MethodID, ...], BeforeValidator(_ordered)] = ()
    effective_parameters: EffectiveOptions
    artifact_roles: Annotated[tuple[str, ...], BeforeValidator(_ordered)] = ()

    @model_validator(mode="before")
    @classmethod
    def _options(cls, value: object) -> object:
        if isinstance(value, dict):
            value = dict(value)
            option = value.get("effective_parameters")
            name = value.get("method_id")
            if isinstance(option, dict):
                models: dict[str, type[RunModel]] = {
                    "contacts": Contacts,
                    "region_enrichment": RegionEnrichment,
                    "rg": RgEffectiveParameters if "eligibility" in option else Rg,
                    "rmsd": RMSD,
                    "temporal_rin": TemporalRin,
                    "pca": PCA,
                    "clustering": Clustering,
                    "replay": Replay,
                    "qc": QC,
                }
                # Unrequested methods have only the closed enabled field.
                model = (
                    Method
                    if set(option) == {"enabled"}
                    else models.get(str(name), Method)
                )
                value["effective_parameters"] = model.model_validate(option)
        return value


def unknown_rg(
    selection: str, *, automatic: bool, include_failed_frames: bool
) -> RgEffectiveParameters:
    observation = EligibilityObservation(
        state="unestablished",
        reason_code="runtime_eligibility_unverified",
        evidence_roles=(),
    )
    return RgEffectiveParameters(
        selection=selection,
        selection_origin="automatic_protein" if automatic else "explicit",
        include_failed_frames=include_failed_frames,
        resolved_atom_count=None,
        atom_identity_sha256=None,
        eligibility=RgEligibility(
            protein_selection=observation,
            masses_and_input=observation,
            pbc_suitability=observation,
        ),
    )
