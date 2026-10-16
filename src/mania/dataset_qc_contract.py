"""Explicit scientific policies, evidence states and supplied reviewer decisions."""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from mania.canonical_reference import (
    AuthorityBinding,
    Digest,
    InputIdentity,
    ReferenceIdentity,
    Text,
)
from mania.canonical_reference import _StrictModel as StrictModel
from mania.input_binding import portable_path

HARD_CHECK_IDS = (
    "topology_readable",
    "trajectory_readable",
    "topology_trajectory_atom_count",
    "topology_trajectory_atom_order",
    "canonical_mapping_complete",
    "protein_pbc_integrity",
    "frame_time_strictly_increasing",
    "production_frame_coverage",
    "canonical_reference",
    "forbidden_self_loops",
    "duplicate_records",
    "occupancy_range",
)
REVIEW_CHECK_IDS = (
    "rmsd_drift",
    "protein_edge_empty_window_fraction",
)


def supported_check(check: str) -> bool:
    return (
        check in (*HARD_CHECK_IDS, *REVIEW_CHECK_IDS)
        or (
            len(check.split(":")) == 3
            and check.split(":")[0] == "mad"
            and check.split(":")[1]
            in ("edge_count", "contact_fraction", "basic_metric")
            and bool(check.split(":")[2])
        )
        or any(
            check.startswith(prefix) and bool(check[len(prefix) :])
            for prefix in ("required_metadata:", "required_artifact:", "schema:")
        )
    )


class QCPolicy(StrictModel):
    schema_version: Literal["mania.qc_policy.v1"]
    kind: Literal["mania_qc_policy"]
    policy_id: Text
    required_check_ids: tuple[Text, ...]
    required_evidence_roles: tuple[Text, ...]
    coverage_fraction: Annotated[float, Field(gt=0, le=1, allow_inf_nan=False)] | None
    empty_window_fraction: (
        Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)] | None
    )
    mad_multiplier: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None
    review_cohort_keys: tuple[Text, ...]
    decision_contract: Literal["fail_excluded_review_pending_external_resolution"]

    @model_validator(mode="after")
    def _policy(self) -> Self:
        for values in (
            self.required_check_ids,
            self.required_evidence_roles,
            self.review_cohort_keys,
        ):
            if len(set(values)) != len(values):
                raise ValueError("Policy lists must be unique and ordered")
        if not self.required_check_ids or not self.required_evidence_roles:
            raise ValueError(
                "An explicit nonempty policy and evidence roles are required"
            )
        if any(not supported_check(c) for c in self.required_check_ids):
            raise ValueError("Unknown scientific check")
        for name, chosen in (
            (
                "coverage_fraction",
                "production_frame_coverage" in self.required_check_ids,
            ),
            (
                "empty_window_fraction",
                "protein_edge_empty_window_fraction" in self.required_check_ids,
            ),
            (
                "mad_multiplier",
                any(c.startswith("mad:") for c in self.required_check_ids),
            ),
        ):
            if (getattr(self, name) is not None) != chosen:
                raise ValueError(
                    "Policy scalar required exactly for its selected source check"
                )
        if any(k not in InputIdentity.model_fields for k in self.review_cohort_keys):
            raise ValueError("Cohort keys must be approved input identity fields")
        if (
            any(c.startswith("mad:") for c in self.required_check_ids)
            and "engine" not in self.review_cohort_keys
        ):
            raise ValueError("MAD cohorts must preserve engine compatibility")
        return self


class AssessmentAuthority(StrictModel):
    reviewer: Text
    method: Text
    note: Text


class QCEvidenceRecord(StrictModel):
    check_id: Text
    state: Literal["positive", "negative", "missing", "not_applicable"]
    value: Annotated[float, Field(allow_inf_nan=False)] | int | bool | None
    evidence_role: Text
    evidence_sha256: Digest | None
    assessment_authority: AssessmentAuthority | None

    @model_validator(mode="after")
    def _evidence(self) -> Self:
        if not supported_check(self.check_id):
            raise ValueError("Unknown scientific check")
        if self.state == "missing":
            if (
                self.value is not None
                or self.evidence_sha256 is not None
                or self.assessment_authority is not None
            ):
                raise ValueError(
                    "Missing evidence cannot carry a measurement or authority"
                )
        elif self.evidence_sha256 is None:
            raise ValueError(
                "Present or inapplicable evidence requires its supplied digest"
            )
        if self.state == "not_applicable" and self.value is not None:
            raise ValueError("Inapplicable measurement must be null")
        if self.check_id == "rmsd_drift" and self.state in ("positive", "negative"):
            if type(self.value) is not bool or self.assessment_authority is None:
                raise ValueError(
                    "RMSD drift requires an external assessment with re"
                    "viewer, method and note"
                )
        return self


class QCParameters(StrictModel):
    policy_id: Text
    policy_sha256: Digest


class QCEvidence(StrictModel):
    schema_version: Literal["mania.qc_evidence.v1"]
    kind: Literal["mania_qc_evidence"]
    identity: InputIdentity
    reference: ReferenceIdentity | None
    parameters: QCParameters
    records: tuple[QCEvidenceRecord, ...]
    authority: tuple[AuthorityBinding, ...]

    @model_validator(mode="after")
    def _records(self) -> Self:
        checks = [r.check_id for r in self.records]
        if not checks or len(set(checks)) != len(checks):
            raise ValueError("Evidence requires unique checks")
        for a in self.authority:
            portable_path(a.path)
            if a.source_identity not in (None, self.identity):
                raise ValueError("Conflicting evidence source identity")
        keys = [(a.role, a.sha256) for a in self.authority]
        if len(set(keys)) != len(keys):
            raise ValueError("Duplicate authority")
        for r in self.records:
            if (
                r.state != "missing"
                and (r.evidence_role, r.evidence_sha256) not in keys
            ):
                raise ValueError("Evidence role/digest lacks supplied authority")
        return self


class QCCheckResult(StrictModel):
    check_id: Text
    severity: Literal["hard", "review"]
    status: Literal["PASS", "FAIL", "REVIEW"]
    value: Annotated[float, Field(allow_inf_nan=False)] | int | bool | None
    evidence_role: Text
    evidence_sha256: Digest | None

    @model_validator(mode="after")
    def _check(self) -> Self:
        if not supported_check(self.check_id):
            raise ValueError("Unknown QC check")
        review = self.check_id in REVIEW_CHECK_IDS or self.check_id.startswith("mad:")
        if (
            (self.severity == "review") != review
            or (review and self.status == "FAIL")
            or (not review and self.status == "REVIEW")
        ):
            raise ValueError("QC status differs from its source severity")
        if self.status == "PASS" and self.evidence_sha256 is None:
            raise ValueError("Missing evidence is never PASS")
        return self


class QCDecisionRecord(StrictModel):
    identity: InputIdentity
    checks: tuple[QCCheckResult, ...]
    qc_status: Literal["PASS", "FAIL", "REVIEW"]
    release_decision: Literal["available", "excluded", "pending_review"]
    decision_mode: Literal["automatic", "reviewer"]
    reason_code: Text
    reviewer: Text | None
    review_note: Text | None
    review_authority_sha256: Digest | None

    @model_validator(mode="after")
    def _decision(self) -> Self:
        ids = [c.check_id for c in self.checks]
        if not ids or len(set(ids)) != len(ids):
            raise ValueError("Decision requires unique nonempty checks")
        states = {c.status for c in self.checks}
        expected = (
            "FAIL" if "FAIL" in states else "REVIEW" if "REVIEW" in states else "PASS"
        )
        if self.qc_status != expected:
            raise ValueError("Decision status differs from checks")
        if self.qc_status == "FAIL" and (
            self.release_decision != "excluded" or self.decision_mode != "automatic"
        ):
            raise ValueError("FAIL is excluded and cannot be overridden")
        if self.qc_status == "PASS" and (
            self.release_decision != "available" or self.decision_mode != "automatic"
        ):
            raise ValueError("PASS requires automatic availability")
        if self.decision_mode == "automatic":
            if any(
                v is not None
                for v in (self.reviewer, self.review_note, self.review_authority_sha256)
            ):
                raise ValueError("Automatic decisions cannot invent reviewer authority")
            if self.qc_status == "REVIEW" and self.release_decision != "pending_review":
                raise ValueError("Unresolved REVIEW remains pending")
        elif (
            self.qc_status != "REVIEW"
            or self.release_decision == "pending_review"
            or any(
                v is None
                for v in (self.reviewer, self.review_note, self.review_authority_sha256)
            )
        ):
            raise ValueError(
                "Reviewer resolution requires complete supplied provenance"
            )
        return self


class QCDecisions(StrictModel):
    schema_version: Literal["mania.qc_decisions.v1"]
    kind: Literal["mania_qc_decisions"]
    identity: InputIdentity
    reference: ReferenceIdentity | None
    parameters: QCParameters
    records: tuple[QCDecisionRecord, ...]
    authority: tuple[AuthorityBinding, ...]

    @model_validator(mode="after")
    def _records(self) -> Self:
        ids = [r.identity for r in self.records]
        if not ids or len({i.model_dump_json() for i in ids}) != len(ids):
            raise ValueError("Decision identities must be unique")
        if self.identity is not None and any(i != self.identity for i in ids):
            raise ValueError("Decision envelope identity mismatch")
        for r in self.records:
            if r.review_authority_sha256 is not None and not any(
                a.sha256 == r.review_authority_sha256
                and a.source_identity == r.identity
                for a in self.authority
            ):
                raise ValueError("Reviewer resolution lacks its exact source authority")
        return self


def validate_policy_evidence(policy: QCPolicy, evidence: QCEvidence) -> None:
    QCPolicy.model_validate(policy.model_dump())
    QCEvidence.model_validate(evidence.model_dump())
    if evidence.parameters.policy_id != policy.policy_id:
        raise ValueError("Policy identity differs")
    if not any(
        a.role == "qc_policy" and a.sha256 == evidence.parameters.policy_sha256
        for a in evidence.authority
    ):
        raise ValueError("Missing policy digest authority")
    if set(r.check_id for r in evidence.records) != set(policy.required_check_ids):
        raise ValueError("Selected QC evidence/check roster mismatch")
    if not set(policy.required_evidence_roles) <= {
        r.evidence_role for r in evidence.records
    }:
        raise ValueError("Policy evidence role omitted")
