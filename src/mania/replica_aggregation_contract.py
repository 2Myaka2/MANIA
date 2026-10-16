"""Explicit generic group membership, reference and observed window authority."""

from typing import Annotated, Any, Literal, Self

from pydantic import Field, model_validator

from mania.canonical_reference import (
    AuthorityBinding,
    InputIdentity,
    ReferenceIdentity,
    Text,
)
from mania.canonical_reference import _StrictModel as StrictModel
from mania.input_binding import portable_path
from mania.preprocessing.temporal_policy import (
    BoundaryProfile,
    require_boundary_profile,
)


class GroupMember(StrictModel):
    identity: InputIdentity
    availability: Literal["available", "unavailable", "excluded"]
    reason_code: Text | None
    decision_authority: AuthorityBinding | None

    @model_validator(mode="after")
    def _decision(self) -> Self:
        if self.availability != "available" and self.reason_code is None:
            raise ValueError("Unavailable/excluded members need an explicit reason")
        if self.decision_authority is not None:
            portable_path(self.decision_authority.path)
            if self.decision_authority.source_identity != self.identity:
                raise ValueError("Decision source identity differs")
        return self


class WindowKey(StrictModel):
    window_id: Text
    window_index: Annotated[int, Field(ge=0)]
    start_ns: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    end_ns: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    boundary_profile: BoundaryProfile
    requested_sample_indexes: tuple[Annotated[int, Field(ge=0)], ...]

    @model_validator(mode="after")
    def _window(self) -> Self:
        require_boundary_profile(self.boundary_profile)
        if self.end_ns <= self.start_ns or list(
            self.requested_sample_indexes
        ) != sorted(set(self.requested_sample_indexes)):
            raise ValueError(
                "Window interval and requested roster must be explicit and ordered"
            )
        return self


class PartnerCorrespondence(StrictModel):
    member_identity: InputIdentity
    topology_local_partner_id: Text
    group_partner_id: Text


class ReplicaGroup(StrictModel):
    schema_version: Literal["mania.replica_group.v1"]
    kind: Literal["mania_replica_group"]
    group_id: Text
    reference: ReferenceIdentity
    layer: Literal["protein", "lipid", "glycan"]
    members: tuple[GroupMember, ...]
    windows: tuple[WindowKey, ...]
    partner_correspondence: tuple[PartnerCorrespondence, ...]
    authority: tuple[AuthorityBinding, ...]

    @model_validator(mode="after")
    def _group(self) -> Self:
        keys = [m.identity.model_dump_json() for m in self.members]
        if not keys or len(set(keys)) != len(keys):
            raise ValueError("Expected members require unique complete identities")
        labels = [
            (
                m.identity.project,
                m.identity.system_id,
                m.identity.engine,
                m.identity.condition,
                m.identity.variant_id,
                m.identity.disulfide_state,
            )
            for m in self.members
        ]
        if any(k != labels[0] for k in labels):
            raise ValueError(
                "Group members have incompatible scientific labels or engines"
            )
        windows = [(w.window_id, w.window_index) for w in self.windows]
        if (
            not windows
            or len(set(windows)) != len(windows)
            or [w.window_index for w in self.windows]
            != sorted(set(w.window_index for w in self.windows))
        ):
            raise ValueError("Group windows require ordered unique identities")
        if self.layer == "protein" and self.partner_correspondence:
            raise ValueError("Protein groups cannot carry specialized correspondences")
        if self.layer != "protein" and not self.partner_correspondence:
            raise ValueError(
                "Specialized groups require explicit partner correspondence"
            )
        local = []
        target = []
        for c in self.partner_correspondence:
            key = c.member_identity.model_dump_json()
            if key not in keys:
                raise ValueError("Partner correspondence member is outside group")
            local.append((key, c.topology_local_partner_id))
            target.append((key, c.group_partner_id))
        if len(set(local)) != len(local) or len(set(target)) != len(target):
            raise ValueError("Partner correspondence must be one-to-one per member")
        for a in self.authority:
            portable_path(a.path)
            if (
                a.source_identity is not None
                and a.source_identity.model_dump_json() not in keys
            ):
                raise ValueError("Group authority refers to an undeclared member")
        if len({(a.role, a.path) for a in self.authority}) != len(self.authority):
            raise ValueError("Duplicate group authority")
        return self


def build_compatible_replica_aggregation_group(**kwargs: Any) -> ReplicaGroup:
    return ReplicaGroup(**kwargs)
