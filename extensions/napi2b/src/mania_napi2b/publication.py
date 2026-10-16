"""Pure fixed Dataset-v1 projections and source-exact logical validation.

Private legacy QC carriers reconstruct existing frozen fields, not a new schema.
Scientific execution and source reads belong to publication_authority.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field, fields, is_dataclass, replace
from decimal import Decimal
from pathlib import Path
from types import UnionType
from typing import (
    Any,
    Literal,
    TypeAlias,
    Union,
    cast,
    get_args,
    get_origin,
    get_type_hints,
)

from pydantic import BaseModel

from mania.canonical_reference import InputIdentity
from mania.dataset_qc_contract import QCDecisions, QCPolicy
from mania.dataset_qc_summary import validate_qc_group_availability
from mania.input_binding import portable_path
from mania.preprocessing.molecular_partner_metadata_io import read_strict_json
from mania.preprocessing.physical_time_execution import (
    PreprocessingConditionTemporalExecution,
)
from mania.preprocessing.temporal_policy import (
    LEGACY_BOUNDARY_PROFILE,
    BoundaryProfile,
    require_boundary_profile,
)
from mania.replica_aggregation_contract import GroupMember, ReplicaGroup
from mania.replica_aggregation_tables import ReplicaWindowTable
from mania_napi2b.biological_annotations import DatasetSystemBiologicalAnnotations
from mania_napi2b.canonical_residue_mapping import (
    CANONICAL_RESIDUE_MAPPING_REFERENCE_ID,
    CANONICAL_RESIDUE_MAPPING_REFERENCE_SHA256,
)
from mania_napi2b.tables import (
    CANONICAL_NODE_COUNT,
    CONTACT_DEFINITION_REQUIRED_PARAMETERS,
    METADATA_TABLE_IDS,
    PUBLICATION_TABLE_SPECS,
    REPLICA_KEY,
    SYSTEM_KEY,
    WINDOW_KEY,
    DatasetReleaseTable,
    FixedWindowTable,
    PublicationScalar,
    build_dataset_release_nodes,
    build_dataset_release_residue_annotations,
    build_publication_table,
    publication_number,
    publication_table_spec,
)

ReplicaKey: TypeAlias = tuple[str, str, str, str]
SystemKey: TypeAlias = tuple[str, str]
HardQCStatus = Literal["pass", "fail"]
ReviewQCStatus = Literal["pass", "review"]
_LABELS = ("engine", "variant_id", "condition", "disulfide_state")


def require_fixed_metadata(model: object) -> None:
    if (
        getattr(model, "canonical_reference_id", None),
        getattr(model, "canonical_reference_sequence_sha256", None),
    ) != (
        CANONICAL_RESIDUE_MAPPING_REFERENCE_ID,
        CANONICAL_RESIDUE_MAPPING_REFERENCE_SHA256,
    ):
        raise ValueError("Fixed source reference differs")


"""Pure Stage 32.A QC evidence and authoritative release-decision contract.

Findings are supplied observations, not calculated QC. Stage 32.B/32.C own
evaluation; Stage 32.D will bridge decisions to Stage 31 availability.
"""
DATASET_QC_DECISION_SET_SCHEMA_VERSION = "mania.dataset_qc_decision_set.v0.1"
DATASET_QC_DECISION_SET_KIND = "mania_dataset_qc_decision_set"
_LegacyQCStatus = Literal["pass", "review", "fail"]
_LegacyQCReleaseDecision = Literal["available", "pending_review", "excluded"]
_LegacyQCDecisionMode = Literal["automatic", "manual"]
_HardFailReasonCode = Literal[
    "TOPOLOGY_UNREADABLE",
    "TRAJECTORY_UNREADABLE",
    "TOPOLOGY_TRAJECTORY_ATOM_COUNT_MISMATCH",
    "TOPOLOGY_TRAJECTORY_ATOM_ORDER_MISMATCH",
    "CANONICAL_MAPPING_INCOMPLETE",
    "PROTEIN_PBC_BROKEN",
    "FRAME_TIME_NOT_STRICTLY_INCREASING",
    "PRODUCTION_FRAME_COVERAGE_BELOW_95_PERCENT",
    "REQUIRED_METADATA_MISSING",
    "REQUIRED_ARTIFACT_MISSING",
    "SCHEMA_INVALID",
    "CANONICAL_REFERENCE_MISMATCH",
    "FORBIDDEN_SELF_LOOP",
    "DUPLICATE_RECORD",
    "OCCUPANCY_OUT_OF_RANGE",
]
_ReviewReasonCode = Literal[
    "RMSD_DRIFT_REVIEW",
    "PROTEIN_EDGE_EMPTY_WINDOW_FRACTION_ABOVE_1_PERCENT",
    "EDGE_COUNT_MAD_OUTLIER_REVIEW",
    "CONTACT_FRACTION_MAD_OUTLIER_REVIEW",
    "BASIC_METRIC_MAD_OUTLIER_REVIEW",
    "MAD_ZERO_REFERENCE_DISTRIBUTION_REVIEW",
]
_LegacyQCReasonCode = Literal[_HardFailReasonCode, _ReviewReasonCode]
_LegacyQCEvidenceType = Literal[
    "artifact", "metric", "window", "mapping", "pbc", "manual_review"
]


class _LegacyDatasetQCContractError(ValueError):
    """Invalid QC structure, severity, identity or decision traceability."""


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value.strip():
        raise _LegacyDatasetQCContractError(f"{name} must be a non-empty string")
    return value.strip()


def _literal(value: object, allowed: tuple[str, ...], name: str) -> None:
    if type(value) is not str or value not in allowed:
        raise _LegacyDatasetQCContractError(f"{name} must be exactly one of {allowed}")


def expected_qc_status(reason_code: _LegacyQCReasonCode) -> Literal["fail", "review"]:
    """Return the frozen severity class; no reason code represents PASS."""
    _literal(reason_code, get_args(_LegacyQCReasonCode), "reason_code")
    return "fail" if reason_code in get_args(_HardFailReasonCode) else "review"


def _portable_path(value: str) -> None:
    if (
        any(part in ("", ".", "..") for part in value.split("/"))
        or any(marker in value for marker in ("\\", ":", "~", "$", "%"))
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise _LegacyDatasetQCContractError(
            "artifact_path must be a portable relative forward-slash path wit"
            "hout traversal, home or environment expansion"
        )


@dataclass(frozen=True)
class _LegacyQCEvidenceRecord:
    """Structured portable evidence; supplied text is not scientifically evaluated."""

    evidence_id: str
    evidence_type: _LegacyQCEvidenceType
    artifact_role: str | None
    artifact_path: str | None
    window_id: str | None
    metric_name: str | None
    observed_value: str | None
    expected_or_threshold: str | None
    details: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_id", _text(self.evidence_id, "evidence_id"))
        _literal(self.evidence_type, get_args(_LegacyQCEvidenceType), "evidence_type")
        for name in (
            "artifact_role",
            "artifact_path",
            "window_id",
            "metric_name",
            "observed_value",
            "expected_or_threshold",
            "details",
        ):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _text(value, name))
        if self.artifact_path is not None:
            _portable_path(self.artifact_path)
        artifact = self.artifact_role is not None and self.artifact_path is not None
        structured = {
            "artifact": artifact,
            "metric": self.metric_name is not None and self.observed_value is not None,
            "window": self.window_id is not None
            and any(
                value is not None
                for value in (self.metric_name, self.observed_value, self.details)
            ),
            "mapping": artifact or self.details is not None,
            "pbc": artifact
            or self.observed_value is not None
            or self.details is not None,
            "manual_review": self.details is not None,
        }
        if not structured[self.evidence_type]:
            raise _LegacyDatasetQCContractError(
                f"{self.evidence_type} evidence lacks its required structured payload"
            )

    def to_dict(self) -> dict[str, object]:
        return {item.name: getattr(self, item.name) for item in fields(self)}


@dataclass(frozen=True)
class _LegacyReplicaQCCheckResult:
    """One auditable check, including evidence for a PASS."""

    check_id: str
    status: _LegacyQCStatus
    reason_code: _LegacyQCReasonCode | None
    human_readable_reason: str | None
    evidence: tuple[_LegacyQCEvidenceRecord, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "check_id", _text(self.check_id, "check_id"))
        _literal(self.status, get_args(_LegacyQCStatus), "status")
        if (
            type(self.evidence) is not tuple
            or not self.evidence
            or any(type(item) is not _LegacyQCEvidenceRecord for item in self.evidence)
        ):
            raise _LegacyDatasetQCContractError(
                "evidence must be a non-empty tuple of exact QCEvidenceRecord values"
            )
        ids = tuple(item.evidence_id for item in self.evidence)
        if len(set(ids)) != len(ids):
            raise _LegacyDatasetQCContractError(
                "evidence IDs must be unique within a check"
            )
        if self.status == "pass":
            if self.reason_code is not None or self.human_readable_reason is not None:
                raise _LegacyDatasetQCContractError(
                    "PASS must have no reason code or prose"
                )
        else:
            if (
                self.reason_code is None
                or expected_qc_status(self.reason_code) != self.status
            ):
                raise _LegacyDatasetQCContractError(
                    "reason_code must match the check status"
                )
            object.__setattr__(
                self,
                "human_readable_reason",
                _text(self.human_readable_reason, "human_readable_reason"),
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "check_id": self.check_id,
            "status": self.status,
            "reason_code": self.reason_code,
            "human_readable_reason": self.human_readable_reason,
            "evidence": [item.to_dict() for item in self.evidence],
        }


@dataclass(frozen=True)
class _LegacyReplicaQCDecisionRecord:
    """Authoritative decision for one full Dataset replica key, never condition."""

    dataset_id: str
    system_id: str
    trajectory_id: str
    replica_id: str
    qc_status: _LegacyQCStatus
    findings: tuple[_LegacyReplicaQCCheckResult, ...]
    release_decision: _LegacyQCReleaseDecision
    decision_mode: _LegacyQCDecisionMode
    decision_reason_code: _LegacyQCReasonCode | None
    human_readable_reason: str | None
    decision_evidence_ids: tuple[str, ...]
    reviewer: str | None
    decision_note: str | None

    def __post_init__(self) -> None:
        for name in ("dataset_id", "system_id", "trajectory_id", "replica_id"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        _literal(self.qc_status, get_args(_LegacyQCStatus), "qc_status")
        _literal(
            self.release_decision,
            get_args(_LegacyQCReleaseDecision),
            "release_decision",
        )
        _literal(self.decision_mode, get_args(_LegacyQCDecisionMode), "decision_mode")
        if (
            type(self.findings) is not tuple
            or not self.findings
            or any(
                type(item) is not _LegacyReplicaQCCheckResult for item in self.findings
            )
        ):
            raise _LegacyDatasetQCContractError(
                "findings must be a non-empty tuple of exact ReplicaQCCheckRe"
                "sult values"
            )
        checks = tuple(item.check_id for item in self.findings)
        if len(set(checks)) != len(checks):
            raise _LegacyDatasetQCContractError(
                "check IDs must be unique within a replica"
            )
        evidence_ids = tuple(
            evidence.evidence_id for item in self.findings for evidence in item.evidence
        )
        if len(set(evidence_ids)) != len(evidence_ids):
            raise _LegacyDatasetQCContractError(
                "evidence IDs must be unique across findings"
            )
        statuses = {item.status for item in self.findings}
        expected = (
            "fail"
            if "fail" in statuses
            else "review"
            if "review" in statuses
            else "pass"
        )
        if self.qc_status != expected:
            raise _LegacyDatasetQCContractError(
                "qc_status must equal the status derived from findings"
            )
        if type(self.decision_evidence_ids) is not tuple:
            raise _LegacyDatasetQCContractError("decision_evidence_ids must be a tuple")
        ids = tuple(
            _text(value, "decision evidence ID") for value in self.decision_evidence_ids
        )
        if len(set(ids)) != len(ids):
            raise _LegacyDatasetQCContractError("decision evidence IDs must be unique")
        if not set(ids).issubset(evidence_ids):
            raise _LegacyDatasetQCContractError(
                "decision evidence references unknown evidence"
            )
        object.__setattr__(self, "decision_evidence_ids", ids)
        if self.qc_status == "pass":
            if (
                self.release_decision != "available"
                or self.decision_mode != "automatic"
                or self.decision_reason_code is not None
                or (self.human_readable_reason is not None)
                or ids
                or (self.reviewer is not None)
                or (self.decision_note is not None)
            ):
                raise _LegacyDatasetQCContractError(
                    "PASS requires automatic available with no decision reaso"
                    "n, evidence references or manual provenance"
                )
            return
        if (
            self.decision_reason_code is None
            or expected_qc_status(self.decision_reason_code) != self.qc_status
        ):
            raise _LegacyDatasetQCContractError(
                "decision reason must match the QC status class"
            )
        matching = tuple(
            item
            for item in self.findings
            if item.reason_code == self.decision_reason_code
            and item.status == self.qc_status
        )
        if not matching:
            raise _LegacyDatasetQCContractError(
                "decision reason must occur in a matching finding"
            )
        supporting_ids = {
            evidence.evidence_id for item in matching for evidence in item.evidence
        }
        if not ids or not set(ids).issubset(supporting_ids):
            raise _LegacyDatasetQCContractError(
                "decision evidence must support findings carrying the decision reason"
            )
        object.__setattr__(
            self,
            "human_readable_reason",
            _text(self.human_readable_reason, "human_readable_reason"),
        )
        if self.qc_status == "fail" and (
            self.release_decision != "excluded" or self.decision_mode != "automatic"
        ):
            raise _LegacyDatasetQCContractError(
                "FAIL requires automatic excluded; no manual override"
            )
        if self.decision_mode == "automatic":
            if self.qc_status == "review" and self.release_decision != "pending_review":
                raise _LegacyDatasetQCContractError(
                    "automatic REVIEW requires pending_review"
                )
            if self.reviewer is not None or self.decision_note is not None:
                raise _LegacyDatasetQCContractError(
                    "automatic decisions forbid reviewer and decision_note"
                )
        else:
            if self.release_decision not in ("available", "excluded"):
                raise _LegacyDatasetQCContractError(
                    "manual REVIEW must resolve to available or excluded"
                )
            for name in ("reviewer", "decision_note"):
                object.__setattr__(self, name, _text(getattr(self, name), name))

    @property
    def replica_key(self) -> tuple[str, str, str, str]:
        return (self.dataset_id, self.system_id, self.trajectory_id, self.replica_id)

    def to_dict(self) -> dict[str, object]:
        result = {item.name: getattr(self, item.name) for item in fields(self)}
        result["findings"] = [item.to_dict() for item in self.findings]
        result["decision_evidence_ids"] = list(self.decision_evidence_ids)
        return result


@dataclass(frozen=True)
class _LegacyDatasetQCDecisionSet:
    """Sorted replica decisions pinned to the accepted Stage 30 reference."""

    records: tuple[_LegacyReplicaQCDecisionRecord, ...]
    schema_version: str = field(
        init=False, default=DATASET_QC_DECISION_SET_SCHEMA_VERSION
    )
    kind: str = field(init=False, default=DATASET_QC_DECISION_SET_KIND)
    canonical_reference_id: str = field(
        init=False, default=CANONICAL_RESIDUE_MAPPING_REFERENCE_ID
    )
    canonical_reference_sequence_sha256: str = field(
        init=False, default=CANONICAL_RESIDUE_MAPPING_REFERENCE_SHA256
    )

    def __post_init__(self) -> None:
        if type(self.records) is not tuple or any(
            type(item) is not _LegacyReplicaQCDecisionRecord for item in self.records
        ):
            raise _LegacyDatasetQCContractError(
                "records must be a tuple of exact ReplicaQCDecisionRecord values"
            )
        keys = tuple(item.replica_key for item in self.records)
        if len(set(keys)) != len(keys):
            raise _LegacyDatasetQCContractError("replica keys must be unique")
        object.__setattr__(
            self,
            "records",
            tuple(sorted(self.records, key=lambda item: item.replica_key)),
        )

    def to_dict(self) -> dict[str, object]:
        result = {item.name: getattr(self, item.name) for item in fields(self)}
        result["records"] = [item.to_dict() for item in self.records]
        return result


def _Legacybuild_dataset_qc_decision_set(
    records: tuple[_LegacyReplicaQCDecisionRecord, ...],
) -> _LegacyDatasetQCDecisionSet:
    """Validate and sort full replica keys without changing the supplied tuple."""
    return _LegacyDatasetQCDecisionSet(records)


@dataclass(frozen=True)
class _LegacyDatasetQCSummaryRow:
    dataset_id: str
    system_id: str
    trajectory_id: str
    replica_id: str
    hard_qc_status: HardQCStatus
    review_qc_status: ReviewQCStatus | None
    qc_status: _LegacyQCStatus
    release_decision: _LegacyQCReleaseDecision
    decision_mode: _LegacyQCDecisionMode
    decision_reason_code: _LegacyQCReasonCode | None
    human_readable_reason: str | None
    reviewer: str | None
    decision_note: str | None
    hard_fail_count: int
    review_finding_count: int
    total_check_count: int

    def __post_init__(self) -> None:
        for item in fields(self):
            value = getattr(self, item.name)
            if item.name.endswith("_count"):
                if type(value) is not int or value < 0:
                    raise ValueError("Summary counts must be non-negative integers")
            elif value is not None and (type(value) is not str or not value.strip()):
                raise ValueError("Summary text must be non-empty")
        if any(
            getattr(self, n) is None
            for n in ("dataset_id", "system_id", "trajectory_id", "replica_id")
        ):
            raise ValueError("Summary identity must be present")
        if self.qc_status not in ("pass", "review", "fail") or (
            self.hard_qc_status != ("fail" if self.qc_status == "fail" else "pass")
            or self.review_qc_status
            != (None if self.qc_status == "fail" else self.qc_status)
            or (self.hard_fail_count > 0) != (self.qc_status == "fail")
            or ((self.review_finding_count > 0) != (self.qc_status == "review"))
            or (
                self.total_check_count
                < max(1, self.hard_fail_count + self.review_finding_count)
            )
        ):
            raise ValueError("Summary statuses/counts disagree")
        allowed = {
            ("pass", "available", "automatic"),
            ("fail", "excluded", "automatic"),
            ("review", "pending_review", "automatic"),
            ("review", "available", "manual"),
            ("review", "excluded", "manual"),
        }
        if (self.qc_status, self.release_decision, self.decision_mode) not in allowed:
            raise ValueError("Invalid summary decision combination")
        if self.qc_status == "pass":
            if self.decision_reason_code is not None or self.human_readable_reason:
                raise ValueError("PASS summary forbids reason")
        elif self.decision_reason_code is None or (
            expected_qc_status(self.decision_reason_code) != self.qc_status
            or self.human_readable_reason is None
        ):
            raise ValueError("Summary reason must match status")
        if self.decision_mode == "manual":
            if self.reviewer is None or self.decision_note is None:
                raise ValueError("Manual summary requires reviewer and note")
        elif self.reviewer is not None or self.decision_note is not None:
            raise ValueError("Automatic summary forbids manual provenance")

    @property
    def replica_key(self) -> tuple[str, str, str, str]:
        return (self.dataset_id, self.system_id, self.trajectory_id, self.replica_id)


@dataclass(frozen=True)
class _LegacyDatasetQCSummary:
    rows: tuple[_LegacyDatasetQCSummaryRow, ...]

    def __post_init__(self) -> None:
        if type(self.rows) is not tuple or any(
            type(r) is not _LegacyDatasetQCSummaryRow for r in self.rows
        ):
            raise ValueError("Expected tuple of exact summary rows")
        for row in self.rows:
            replace(row)
        if len({r.replica_key for r in self.rows}) != len(self.rows):
            raise ValueError("Duplicate summary replica key")
        object.__setattr__(
            self, "rows", tuple(sorted(self.rows, key=lambda r: r.replica_key))
        )


def _Legacybuild_dataset_qc_summary(
    decisions: _LegacyDatasetQCDecisionSet,
) -> _LegacyDatasetQCSummary:
    return _LegacyDatasetQCSummary(
        tuple(
            _LegacyDatasetQCSummaryRow(
                *r.replica_key,
                "fail" if r.qc_status == "fail" else "pass",
                None if r.qc_status == "fail" else r.qc_status,
                r.qc_status,
                r.release_decision,
                r.decision_mode,
                r.decision_reason_code,
                r.human_readable_reason,
                r.reviewer,
                r.decision_note,
                sum(c.status == "fail" for c in r.findings),
                sum(c.status == "review" for c in r.findings),
                len(r.findings),
            )
            for r in decisions.records
        )
    )


"Lossless normalization of authoritative Stage 32 decisions and summary."


class DatasetReleaseQCError(ValueError):
    """Inconsistent or non-production-resolved publication QC evidence."""


def validate_publication_qc_inputs(
    decisions: _LegacyDatasetQCDecisionSet, summary: _LegacyDatasetQCSummary
) -> None:
    if (
        type(decisions) is not _LegacyDatasetQCDecisionSet
        or type(summary) is not _LegacyDatasetQCSummary
    ):
        raise DatasetReleaseQCError("Expected accepted Stage 32 decisions and summary")
    require_fixed_metadata(decisions)
    records = tuple(
        replace(
            r,
            findings=tuple(
                replace(f, evidence=tuple(replace(e) for e in f.evidence))
                for f in r.findings
            ),
        )
        for r in decisions.records
    )
    if _LegacyDatasetQCDecisionSet(records) != decisions:
        raise DatasetReleaseQCError("Decision input must already be validated")
    if not records:
        raise DatasetReleaseQCError(
            "Publication requires at least one candidate replica"
        )
    if any(r.release_decision == "pending_review" for r in records):
        raise DatasetReleaseQCError("pending_review is not a publishable release state")
    if replace(summary) != _Legacybuild_dataset_qc_summary(decisions):
        raise DatasetReleaseQCError("Stage 32 summary and decisions disagree")


@dataclass(frozen=True)
class DatasetReleaseQCTables:
    quality_control: DatasetReleaseTable
    quality_control_findings: DatasetReleaseTable
    quality_control_evidence: DatasetReleaseTable


def build_dataset_release_qc_tables(
    decisions: _LegacyDatasetQCDecisionSet, summary: _LegacyDatasetQCSummary
) -> DatasetReleaseQCTables:
    """Keep PASS findings, all evidence, selected IDs and manual provenance."""
    validate_publication_qc_inputs(decisions, summary)
    findings: list[dict[str, object]] = []
    evidence: list[dict[str, object]] = []
    for decision in decisions.records:
        identity = dict(
            zip(
                ("dataset_id", "system_id", "trajectory_id", "replica_id"),
                decision.replica_key,
                strict=True,
            )
        )
        selected = set(decision.decision_evidence_ids)
        traced: list[str] = []
        for finding in decision.findings:
            findings.append(
                {
                    **identity,
                    "check_id": finding.check_id,
                    "status": finding.status,
                    "reason_code": finding.reason_code,
                    "human_readable_reason": finding.human_readable_reason,
                }
            )
            for item in finding.evidence:
                used = item.evidence_id in selected
                if used:
                    traced.append(item.evidence_id)
                evidence.append(
                    {
                        **identity,
                        "check_id": finding.check_id,
                        **item.to_dict(),
                        "used_for_decision": used,
                    }
                )
        if len(traced) != len(selected) or set(traced) != selected:
            raise DatasetReleaseQCError("Decision evidence must map exactly once")
    return DatasetReleaseQCTables(
        build_publication_table("quality_control", (asdict(r) for r in summary.rows)),
        build_publication_table("quality_control_findings", findings),
        build_publication_table("quality_control_evidence", evidence),
    )


class DatasetReleaseMetadataError(ValueError):
    """Missing authority, inconsistent metadata or invalid publication selection."""


def _unique_replica_keys(keys: Iterable[ReplicaKey]) -> tuple[ReplicaKey, ...]:
    values = tuple(keys)
    if any(
        type(k) is not tuple
        or len(k) != 4
        or any(type(v) is not str or not v or v != v.strip() for v in k)
        for k in values
    ) or len(values) != len(set(values)):
        raise DatasetReleaseMetadataError("Full replica keys must be exact and unique")
    return values


def _effective_ns(value: float | None) -> Decimal | None:
    if value is None:
        return None
    sign, digits, exponent = publication_number(value).as_tuple()
    assert isinstance(exponent, int)
    return Decimal((sign, digits, exponent - 3))


def _validate_window_labels(table: DatasetReleaseTable) -> None:
    identities: dict[tuple[object, ...], tuple[object, ...]] = {}
    names = (
        "requested_production_start_ns",
        "requested_production_end_ns",
        "requested_window_start_ns",
        "requested_window_end_ns",
        "right_endpoint_inclusive",
        "window_length_ns",
        "window_step_ns",
        "overlap_percent",
        "frame_stride_ps",
    )
    for row in table.records():
        replica = tuple(row[n] for n in REPLICA_KEY)
        definition = tuple(row[n] for n in names)
        for label in ("window_id", "window_index"):
            key = (*replica, label, row[label])
            if key in identities and identities[key] != definition:
                raise DatasetReleaseMetadataError(
                    "Duplicate window label/index has incompatible physical definitions"
                )
            identities[key] = definition


def build_dataset_release_time_windows(
    evidence: tuple[PreprocessingConditionTemporalExecution, ...],
) -> DatasetReleaseTable:
    rows: list[dict[str, object]] = []
    for execution in evidence:
        if type(execution) is not PreprocessingConditionTemporalExecution:
            raise DatasetReleaseMetadataError(
                "Expected accepted Stage 27 temporal evidence"
            )
        replace(execution.sampling_plan)
        replace(execution.window_plan)
        replace(execution)  # Accepted plan links, without either planner/evaluator.
        identity = execution.dataset_spec.identity
        plan = execution.window_plan
        for window in plan.windows:
            replace(window)  # Counts, coverage, bounds and partition consistency.
            rows.append(
                {
                    **{n: getattr(identity, n) for n in REPLICA_KEY},
                    "window_id": window.window_id,
                    "window_index": window.window_index,
                    "requested_production_start_ns": plan.requested_production_start_ns,
                    "requested_production_end_ns": plan.requested_production_end_ns,
                    "requested_window_start_ns": window.requested_start_ns,
                    "requested_window_end_ns": window.requested_end_ns,
                    "right_endpoint_inclusive": window.right_endpoint_inclusive,
                    "window_length_ns": plan.requested_window_length_ns,
                    "window_step_ns": plan.requested_window_step_ns,
                    "overlap_percent": plan.requested_overlap_percent,
                    "frame_stride_ps": (
                        execution.sampling_plan.requested_frame_stride_ps
                    ),
                    "expected_sample_count": window.requested_sample_count,
                    "resolved_sample_count": window.sampled_frame_count,
                    "missing_sample_count": window.missing_sample_count,
                    "coverage_fraction": window.coverage_fraction,
                    "effective_start_ns": _effective_ns(window.effective_start_time_ps),
                    "effective_end_ns": _effective_ns(window.effective_end_time_ps),
                }
            )
    table = build_publication_table("time_windows", rows)
    _validate_window_labels(table)
    return table


def build_dataset_release_contact_definition(
    *,
    replica_key: ReplicaKey,
    contact_definition_id: str,
    contact_layer: str,
    interaction_type: str,
    parameters: Mapping[str, object],
    source_artifact_role: str,
    source_artifact_path: str,
    units: Mapping[str, str] | None = None,
) -> DatasetReleaseTable:
    """Project a caller's complete accepted definition tree, including all options.

    Parameters come from recorded configuration/accepted semantic evidence, e.g.
    PreprocessingContactDetectionOptions.to_dict(include_contact_selection=True),
    typed edge semantics/atom maps and Stage 29 constants. No defaults, thresholds,
    PBC preparation or inapplicable parameters are inferred here.
    """
    _unique_replica_keys((replica_key,))
    if (
        not isinstance(parameters, Mapping)
        or not set(CONTACT_DEFINITION_REQUIRED_PARAMETERS) <= parameters.keys()
    ):
        raise DatasetReleaseMetadataError(
            "Contact definition lacks required accepted parameter roots"
        )
    rows: list[dict[str, object]] = []
    units = {} if units is None else units

    def visit(value: object, path: str) -> None:
        row: dict[str, object] = {
            **dict(zip(REPLICA_KEY, replica_key, strict=True)),
            "contact_definition_id": contact_definition_id,
            "contact_layer": contact_layer,
            "interaction_type": interaction_type,
            "parameter_path": path,
            "string_value": None,
            "integer_value": None,
            "number_value": None,
            "boolean_value": None,
            "unit": units.get(path),
            "source_artifact_role": source_artifact_role,
            "source_artifact_path": source_artifact_path,
        }
        if isinstance(value, Mapping):
            kind = "object"
        elif type(value) in (tuple, list):
            kind = "array"
        elif value is None:
            kind = "null"
        elif type(value) is bool:
            kind = "boolean"
        elif type(value) is int:
            kind = "integer"
        elif type(value) in (float, Decimal):
            kind = "number"
        elif type(value) is str:
            kind = "string"
        else:
            raise DatasetReleaseMetadataError("Unsupported contact parameter value")
        row["parameter_kind"] = kind
        if kind in ("string", "integer", "number", "boolean"):
            row[f"{kind}_value"] = value
        rows.append(row)
        if isinstance(value, Mapping):
            if any(type(k) is not str for k in value):
                raise DatasetReleaseMetadataError("Contact object keys must be text")
            for name in sorted(value):
                escaped = name.replace("~", "~0").replace("/", "~1")
                visit(value[name], f"{path}/{escaped}")
        elif isinstance(value, (tuple, list)):
            for index, item in enumerate(value):
                visit(item, f"{path}/{index}")

    try:
        visit(parameters, "$")
    except RecursionError:
        raise DatasetReleaseMetadataError(
            "Contact parameter tree is cyclic or too deep"
        ) from None
    if not set(units) <= {r["parameter_path"] for r in rows}:
        raise DatasetReleaseMetadataError(
            "Unit evidence references an unknown parameter path"
        )
    return build_publication_table("contact_definitions", rows)


def build_dataset_release_software_versions(
    records: Iterable[Mapping[str, object]],
) -> DatasetReleaseTable:
    """Copy exact schema-shaped run/caller evidence; never inspect this environment.

    Different runs may legitimately record different versions. Conflicting (or
    duplicate) records under the frozen source-scoped primary key always fail.
    """
    return build_publication_table("software_versions", records)


@dataclass(frozen=True)
class DatasetReleaseMetadataTables:
    systems: DatasetReleaseTable
    simulations: DatasetReleaseTable
    time_windows: DatasetReleaseTable
    contact_definitions: DatasetReleaseTable
    software_versions: DatasetReleaseTable
    quality_control: DatasetReleaseTable
    quality_control_findings: DatasetReleaseTable
    quality_control_evidence: DatasetReleaseTable
    nodes: DatasetReleaseTable
    residue_annotations: DatasetReleaseTable
    boundary_profile: BoundaryProfile = field(
        default=LEGACY_BOUNDARY_PROFILE, kw_only=True
    )

    def __post_init__(self) -> None:
        require_boundary_profile(self.boundary_profile)
        for name in METADATA_TABLE_IDS:
            table = getattr(self, name)
            if type(table) is not DatasetReleaseTable or table.table_id != name:
                raise DatasetReleaseMetadataError(
                    "Bundle table identity must match its slot"
                )
        if not self.systems.row_count or not self.simulations.row_count:
            raise DatasetReleaseMetadataError(
                "Release candidate population must be nonempty"
            )
        if self.nodes.row_count != CANONICAL_NODE_COUNT:
            raise DatasetReleaseMetadataError(
                "Release nodes must contain all 690 positions"
            )
        validate_dataset_release_metadata_relationships(self)

    @property
    def tables(self) -> tuple[DatasetReleaseTable, ...]:
        return tuple(getattr(self, name) for name in METADATA_TABLE_IDS)

    def to_dict(self) -> dict[str, object]:
        return {t.table_id: t.to_dict() for t in self.tables}


def validate_dataset_release_metadata_relationships(
    bundle: DatasetReleaseMetadataTables,
) -> None:
    """All in-scope frozen FKs, including complete simulations/QC linkage."""
    tables = {t.table_id: t for t in bundle.tables}
    for table in bundle.tables:
        for fk in table.spec.foreign_keys:
            target = tables.get(fk.target_table)
            if target is None:
                continue
            keys = {tuple(r[n] for n in fk.target_columns) for r in target.records()}
            if any(
                tuple(r[n] for n in fk.local_columns) not in keys
                for r in table.records()
            ):
                raise DatasetReleaseMetadataError(
                    f"Invalid {table.table_id} -> {target.table_id} foreign key"
                )
    _validate_window_labels(bundle.time_windows)


class DatasetReleaseScienceError(ValueError):
    """Missing publication authority or inconsistent scientific relationships."""


def _key(
    row: Mapping[str, PublicationScalar], names: tuple[str, ...]
) -> tuple[PublicationScalar, ...]:
    return tuple(row[n] for n in names)


def publication_metadata_index(
    metadata_tables: DatasetReleaseMetadataTables, table_id: str
) -> dict[tuple[PublicationScalar, ...], dict[str, PublicationScalar]]:
    """Validate and index an in-scope accepted metadata table, without mutation."""
    if type(metadata_tables) is not DatasetReleaseMetadataTables:
        raise DatasetReleaseScienceError("Expected Stage 33.B metadata tables")
    table = getattr(metadata_tables, table_id)
    if type(table) is not DatasetReleaseTable or table.table_id != table_id:
        raise DatasetReleaseScienceError("Metadata table identity must match its slot")
    validated = DatasetReleaseTable(table.spec, table.rows)
    return {_key(r, table.spec.primary_key): r for r in validated.records()}


def validate_dataset_release_scientific_relationships(
    tables: Iterable[DatasetReleaseTable],
    metadata_tables: DatasetReleaseMetadataTables,
) -> None:
    """Validate only science/aggregate/metric links to the supplied 33.B tables."""
    indexes = {
        name: publication_metadata_index(metadata_tables, name)
        for name in ("systems", "simulations", "time_windows", "nodes")
    }
    for table in tables:
        validated = DatasetReleaseTable(table.spec, table.rows)
        for row in validated.records():
            global_metric = table.table_id == "metrics" and row["window_id"] is None
            if table.table_id == "metrics" and (
                (row["window_id"] is None) != (row["window_index"] is None)
            ):
                raise DatasetReleaseScienceError("Metric window fields must pair")
            for fk in table.spec.foreign_keys:
                if global_metric and fk.target_table == "time_windows":
                    continue
                target = indexes[fk.target_table].get(_key(row, fk.local_columns))
                if target is None:
                    raise DatasetReleaseScienceError(
                        f"Invalid {table.table_id} -> {fk.target_table} foreign key"
                    )
                if fk.target_table == "nodes":
                    number = fk.local_columns[-1]
                    name = number.replace("residue_number", "resname")
                    if row[name] != target["canonical_resname"]:
                        raise DatasetReleaseScienceError(
                            "Canonical node name disagrees"
                        )
            if all(n in row for n in REPLICA_KEY):
                simulation = indexes["simulations"][_key(row, REPLICA_KEY)]
                if simulation["included_in_scientific_release"] is not True:
                    raise DatasetReleaseScienceError(
                        "Publication row requires a science-included simulation"
                    )
                identity = simulation
            else:
                identity = indexes["systems"][_key(row, SYSTEM_KEY)]
            if any(n in row and row[n] != identity[n] for n in _LABELS):
                raise DatasetReleaseScienceError("Publication identity labels disagree")
            if table.relative_path.startswith("science/"):
                window = indexes["time_windows"][_key(row, WINDOW_KEY)]
                pairs = (
                    ("requested_window_start_ns", "requested_window_start_ns"),
                    ("requested_window_end_ns", "requested_window_end_ns"),
                    ("right_endpoint_inclusive", "right_endpoint_inclusive"),
                    ("requested_sample_count", "expected_sample_count"),
                    ("resolved_frame_count", "resolved_sample_count"),
                    ("missing_sample_count", "missing_sample_count"),
                    ("coverage_fraction", "coverage_fraction"),
                )
                if any(row[a] != window[b] for a, b in pairs):
                    raise DatasetReleaseScienceError(
                        "Science requested window/denominator evidence disagrees"
                    )


@dataclass(frozen=True)
class DatasetReleaseScientificTables:
    protein_edges_by_window: DatasetReleaseTable
    protein_lipid_contacts_by_window: DatasetReleaseTable
    protein_glycan_contacts_by_window: DatasetReleaseTable
    protein_edges_by_window_replica_aggregation: DatasetReleaseTable
    protein_lipid_contacts_by_window_replica_aggregation: DatasetReleaseTable
    protein_glycan_contacts_by_window_replica_aggregation: DatasetReleaseTable
    metrics: DatasetReleaseTable

    def __post_init__(self) -> None:
        for item in fields(self):
            table = getattr(self, item.name)
            if type(table) is not DatasetReleaseTable or table.table_id != item.name:
                raise DatasetReleaseScienceError("Science table must match bundle slot")
            DatasetReleaseTable(table.spec, table.rows)

    @property
    def tables(self) -> tuple[DatasetReleaseTable, ...]:
        return tuple(getattr(self, item.name) for item in fields(self))

    def to_dict(self) -> dict[str, object]:
        return {table.table_id: table.to_dict() for table in self.tables}


def _fixed_qc_decisions(
    tables: tuple[DatasetReleaseTable, ...],
) -> _LegacyDatasetQCDecisionSet:
    by_id = {t.table_id: t for t in tables}
    required = {
        "quality_control",
        "quality_control_findings",
        "quality_control_evidence",
    }
    if len(tables) != 3 or set(by_id) != required:
        raise ValueError("Exact three fixed QC tables are required")
    records = []
    for raw_summary in by_id["quality_control"].records():
        summary: dict[str, Any] = dict(raw_summary)
        _LegacyDatasetQCSummaryRow(**summary)
        key = (
            summary["dataset_id"],
            summary["system_id"],
            summary["trajectory_id"],
            summary["replica_id"],
        )
        findings = []
        chosen = []
        for raw_row in by_id["quality_control_findings"].records():
            row: dict[str, Any] = dict(raw_row)
            if tuple(row[n] for n in REPLICA_KEY) != key:
                continue
            evidence = []
            for raw_item in by_id["quality_control_evidence"].records():
                item: dict[str, Any] = dict(raw_item)
                if (
                    tuple(item[n] for n in REPLICA_KEY) != key
                    or item["check_id"] != row["check_id"]
                ):
                    continue
                data = {f.name: item[f.name] for f in fields(_LegacyQCEvidenceRecord)}
                evidence.append(_LegacyQCEvidenceRecord(**data))
                if item["used_for_decision"]:
                    chosen.append(item["evidence_id"])
            findings.append(
                _LegacyReplicaQCCheckResult(
                    row["check_id"],
                    row["status"],
                    row["reason_code"],
                    row["human_readable_reason"],
                    tuple(evidence),
                )
            )
        records.append(
            _LegacyReplicaQCDecisionRecord(
                *key,
                summary["qc_status"],
                tuple(findings),
                summary["release_decision"],
                summary["decision_mode"],
                summary["decision_reason_code"],
                summary["human_readable_reason"],
                tuple(chosen),
                summary["reviewer"],
                summary["decision_note"],
            )
        )
    result = _LegacyDatasetQCDecisionSet(tuple(records))
    expected = build_dataset_release_qc_tables(
        result, _Legacybuild_dataset_qc_summary(result)
    )
    if any(by_id[n] != getattr(expected, n) for n in required):
        raise ValueError(
            "Fixed QC findings/evidence/population/counts differ on reconstruction"
        )
    return result


def build_dataset_release_metadata_tables(
    *,
    decisions: tuple[QCDecisions, ...],
    policy: QCPolicy,
    groups: tuple[ReplicaGroup, ...],
    fixed_qc_tables: tuple[DatasetReleaseTable, ...],
    scientific_release_replica_keys: tuple[ReplicaKey, ...],
    temporal_evidence: tuple[PreprocessingConditionTemporalExecution, ...],
    annotation_metadata: tuple[DatasetSystemBiologicalAnnotations, ...],
    contact_definitions: tuple[DatasetReleaseTable, ...],
    software_version_records: Iterable[Mapping[str, object]],
) -> DatasetReleaseMetadataTables:
    """Project explicit source authorities; do not evaluate or create a release."""
    if not groups:
        raise ValueError("QC-derived aggregation groups are required")
    profiles = {w.boundary_profile for g in groups for w in g.windows} | {
        t.window_plan.boundary_profile for t in temporal_evidence
    }
    if len(profiles) != 1:
        raise ValueError("Release cannot mix temporal boundary profiles")
    members: dict[str, GroupMember] = {}
    records = {
        d.identity.model_dump_json(): d for doc in decisions for d in doc.records
    }
    if len(records) != sum(len(d.records) for d in decisions):
        raise ValueError("Duplicate QC decision identity")
    for group in groups:
        validate_qc_group_availability(group, decisions, policy=policy)
        for member in group.members:
            member_key = member.identity.model_dump_json()
            if member_key in members and members[member_key] != member:
                raise ValueError("Member metadata/availability differs across layers")
            members[member_key] = member
    if set(members) != set(records):
        raise ValueError("QC/manifest candidate population differs")
    fixed = _fixed_qc_decisions(fixed_qc_tables)
    fixed_by_key = {r.replica_key: r for r in fixed.records}
    if set(fixed_by_key) != {replica_key(m.identity) for m in members.values()}:
        raise ValueError("Fixed/generic QC candidate population differs")
    for member in members.values():
        generic = records[member.identity.model_dump_json()]
        legacy = fixed_by_key[replica_key(member.identity)]
        if (
            legacy.qc_status,
            legacy.release_decision,
            legacy.decision_mode,
            legacy.reviewer,
            legacy.decision_note,
        ) != (
            generic.qc_status.lower(),
            generic.release_decision,
            "manual" if generic.decision_mode == "reviewer" else "automatic",
            generic.reviewer,
            generic.review_note,
        ) or {f.check_id: f.status for f in legacy.findings} != {
            f.check_id: f.status.lower() for f in generic.checks
        }:
            raise ValueError(
                "Fixed/generic QC findings or supplied reviewer authority differ"
            )
    selected = set(_unique_replica_keys(scientific_release_replica_keys))
    available = {
        replica_key(m.identity)
        for m in members.values()
        if m.availability == "available"
        and records[m.identity.model_dump_json()].release_decision == "available"
    }
    if not selected or not selected <= available:
        raise ValueError("Scientific release requires QC-available complete members")
    systems: dict[SystemKey, dict[str, Any]] = {}
    simulations = []
    for member in members.values():
        ident = member.identity
        labels = {n: getattr(ident, n) for n in _LABELS}
        key = (ident.project, ident.system_id)
        row = dict(dataset_id=key[0], system_id=key[1], **labels)
        if key in systems and systems[key] != row:
            raise ValueError("System metadata disagree across replicas")
        systems[key] = row
        decision = fixed_by_key[replica_key(ident)]
        simulations.append(
            dict(
                **dict(zip(REPLICA_KEY, replica_key(ident), strict=True)),
                **labels,
                qc_status=decision.qc_status,
                release_decision=decision.release_decision,
                decision_mode=decision.decision_mode,
                decision_reason_code=decision.decision_reason_code,
                human_readable_reason=decision.human_readable_reason,
                aggregation_availability_status=member.availability,
                aggregation_availability_reason=member.reason_code,
                included_in_scientific_release=replica_key(ident) in selected,
                included_in_replica_aggregation=member.availability == "available",
            )
        )
    if {(a.dataset_id, a.system_id) for a in annotation_metadata} != set(systems):
        raise ValueError(
            "Every candidate system needs explicit complete fixed annotations"
        )
    for execution in temporal_evidence:
        old = execution.dataset_spec.identity
        candidate = next(
            (m for m in members.values() if replica_key(m.identity) == old.replica_key),
            None,
        )
        if candidate is None or any(
            getattr(old, n) != getattr(candidate.identity, n) for n in _LABELS
        ):
            raise ValueError("Temporal evidence differs from candidate source identity")
    qc = {t.table_id: t for t in fixed_qc_tables}
    return DatasetReleaseMetadataTables(
        build_publication_table("systems", systems.values()),
        build_publication_table("simulations", simulations),
        build_dataset_release_time_windows(temporal_evidence),
        build_publication_table(
            "contact_definitions", (r for t in contact_definitions for r in t.records())
        ),
        build_dataset_release_software_versions(software_version_records),
        qc["quality_control"],
        qc["quality_control_findings"],
        qc["quality_control_evidence"],
        build_dataset_release_nodes(),
        build_dataset_release_residue_annotations(
            annotation_metadata, annotation_publication_system_keys=tuple(systems)
        ),
        boundary_profile=next(iter(profiles)),
    )


def replica_key(identity: InputIdentity) -> ReplicaKey:
    return (
        identity.project,
        identity.system_id,
        identity.trajectory_id,
        identity.replica_id,
    )


def project_fixed_science(
    table: FixedWindowTable, metadata: DatasetReleaseMetadataTables
) -> DatasetReleaseTable:
    table.__post_init__()
    ident = table.generic.mapping.identity
    simulation = publication_metadata_index(metadata, "simulations").get(
        replica_key(ident)
    )
    if simulation is None:
        raise ValueError("Unknown scientific source replica")
    name = {
        "protein": "protein_edges_by_window",
        "lipid": "protein_lipid_contacts_by_window",
        "glycan": "protein_glycan_contacts_by_window",
    }[table.generic.layer]
    rows = (
        ()
        if simulation["included_in_scientific_release"] is not True
        else table.records()
    )
    spec = publication_table_spec(name)
    result = build_publication_table(
        name,
        (
            {
                c.name: CANONICAL_RESIDUE_MAPPING_REFERENCE_ID
                if c.name == "canonical_reference_id"
                else row[c.name]
                for c in spec.columns
            }
            for row in rows
        ),
    )
    validate_dataset_release_scientific_relationships((result,), metadata)
    return result


def project_generic_aggregate(
    table: ReplicaWindowTable,
    group: ReplicaGroup,
    metadata: DatasetReleaseMetadataTables,
) -> DatasetReleaseTable:
    ReplicaWindowTable.model_validate(table.model_dump())
    name = {
        "protein": "protein_edges_by_window_replica_aggregation",
        "lipid": "protein_lipid_contacts_by_window_replica_aggregation",
        "glycan": "protein_glycan_contacts_by_window_replica_aggregation",
    }[group.layer]
    available = tuple(
        m.identity for m in group.members if m.availability == "available"
    )
    rows = []
    for row in table.rows:
        if (
            row.group_id != group.group_id
            or row.layer != group.layer
            or row.contributing_replica_keys != available
        ):
            raise ValueError("Aggregate contribution population/group differs")
        if row.reference_sha256 != group.reference.reference_sha256:
            raise ValueError("Aggregate generic reference differs")
        d = row.model_dump()
        ident = group.members[0].identity
        d.update(
            dataset_id=ident.project,
            system_id=ident.system_id,
            engine=ident.engine,
            variant_id=ident.variant_id,
            condition=ident.condition,
            disulfide_state=ident.disulfide_state,
            canonical_reference_id=CANONICAL_RESIDUE_MAPPING_REFERENCE_ID,
        )
        if group.layer == "protein":
            d.update(
                source_canonical_residue_number=row.reference_position_i,
                source_canonical_resname=row.reference_resname_i,
                target_canonical_residue_number=row.reference_position_j,
                target_canonical_resname=row.reference_resname_j,
            )
        else:
            d.update(
                canonical_residue_number=row.reference_position_i,
                canonical_resname=row.reference_resname_i,
                partner_correspondence_id=row.group_partner_id,
            )
        rows.append({c.name: d[c.name] for c in publication_table_spec(name).columns})
    result = build_publication_table(name, rows)
    validate_dataset_release_scientific_relationships((result,), metadata)
    return result


def validate_complete_tables(
    metadata: DatasetReleaseMetadataTables, science: DatasetReleaseScientificTables
) -> None:
    metadata.__post_init__()
    science.__post_init__()
    tables = (*metadata.tables, *science.tables)
    if len(tables) != 17 or {t.spec for t in tables} != set(PUBLICATION_TABLE_SPECS):
        raise ValueError("Exactly the 17 frozen tables are required")
    if metadata.nodes != build_dataset_release_nodes():
        raise ValueError("Fixed 690-node source reference differs")
    for system in metadata.systems.records():
        rows = [
            r
            for r in metadata.residue_annotations.records()
            if all(r[n] == system[n] for n in SYSTEM_KEY)
        ]
        if len(rows) != 690 or {r["canonical_residue_number"] for r in rows} != set(
            range(1, 691)
        ):
            raise ValueError("Incomplete fixed annotation population")
    validate_dataset_release_scientific_relationships(science.tables, metadata)


def _decode_legacy(value: Any, model: Any) -> Any:
    origin, args = get_origin(model), get_args(model)
    if origin in (Union, UnionType):
        for choice in args:
            try:
                return _decode_legacy(value, choice)
            except (ValueError, TypeError, OverflowError):
                continue
        raise ValueError("Value does not match any permitted model type")
    if origin is Literal:
        if not any(type(value) is type(a) and value == a for a in args):
            raise ValueError("Invalid exact literal")
        return value
    if origin is tuple:
        if type(value) is not list:
            raise ValueError("Expected JSON array")
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(_decode_legacy(v, args[0]) for v in value)
        if len(value) != len(args):
            raise ValueError("Invalid fixed tuple length")
        return tuple(_decode_legacy(v, t) for v, t in zip(value, args, strict=True))
    if model is Path:
        return Path(portable_path(value))
    if model in (str, bool, int, float, type(None)):
        valid = type(value) is model or (model is float and type(value) is int)
        if not valid or (type(value) is float and not math.isfinite(value)):
            raise ValueError("Invalid strict JSON scalar")
        return value
    if is_dataclass(model) or (
        isinstance(model, type) and issubclass(model, BaseModel)
    ):
        constructor: Any = model
        dataclass_fields = fields(model) if is_dataclass(model) else ()
        names = (
            tuple(f.name for f in dataclass_fields)
            if dataclass_fields
            else tuple(constructor.model_fields)
        )
        if type(value) is not dict or set(value) != set(names):
            raise ValueError("Invalid exact JSON object fields")
        hints = get_type_hints(model)
        # Accepted generic canonical tables specialize their row type here.
        if hasattr(model, "_row_type"):
            hints["rows"] = tuple[model._row_type, ...]
        parsed = {n: _decode_legacy(value[n], hints[n]) for n in names}
        derived = {f.name for f in dataclass_fields if not f.init}
        result = constructor(**{n: v for n, v in parsed.items() if n not in derived})
        if any(parsed[n] != getattr(result, n) for n in derived):
            raise ValueError("Fixed or derived model metadata mismatch")
        return result
    raise TypeError("Unsupported QC serialization type")


def read_fixed_decision_set(path: Path) -> _LegacyDatasetQCDecisionSet:
    return cast(
        _LegacyDatasetQCDecisionSet,
        _decode_legacy(read_strict_json(path), _LegacyDatasetQCDecisionSet),
    )
