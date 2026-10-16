"""Authority-sensitive decisions and group availability; no reviewer invention."""

from typing import Literal

from mania.canonical_reference import InputIdentity
from mania.dataset_qc_contract import (
    QCCheckResult,
    QCDecisionRecord,
    QCDecisions,
    QCPolicy,
)
from mania.replica_aggregation_contract import ReplicaGroup


def automatic_decision(
    identity: InputIdentity, checks: tuple[QCCheckResult, ...]
) -> QCDecisionRecord:
    states = {c.status for c in checks}
    status: Literal["PASS", "FAIL", "REVIEW"] = (
        "FAIL" if "FAIL" in states else "REVIEW" if "REVIEW" in states else "PASS"
    )
    decisions: dict[str, Literal["available", "excluded", "pending_review"]] = {
        "FAIL": "excluded",
        "REVIEW": "pending_review",
        "PASS": "available",
    }
    return QCDecisionRecord(
        identity=identity,
        checks=checks,
        qc_status=status,
        release_decision=decisions[status],
        decision_mode="automatic",
        reason_code="source_checks_" + status.lower(),
        reviewer=None,
        review_note=None,
        review_authority_sha256=None,
    )


def validate_qc_group_availability(
    group: ReplicaGroup, decisions: tuple[QCDecisions, ...], *, policy: QCPolicy
) -> None:
    records = {}
    for document in decisions:
        QCDecisions.model_validate(document.model_dump())
        if (
            document.parameters.policy_id != policy.policy_id
            or document.reference != group.reference
        ):
            raise ValueError("Group QC policy/reference identity differs")
        for record in document.records:
            key = record.identity.model_dump_json()
            if key in records:
                raise ValueError("Duplicate supplied QC member identity")
            records[key] = record
    if set(records) != {m.identity.model_dump_json() for m in group.members}:
        raise ValueError("QC decisions must cover the exact expected group roster")
    for m in group.members:
        r = records[m.identity.model_dump_json()]
        from mania.dataset_qc_contract import REVIEW_CHECK_IDS

        required_checks = set(policy.required_check_ids)
        if r.qc_status == "FAIL":
            required_checks = {
                c
                for c in required_checks
                if c not in REVIEW_CHECK_IDS and not c.startswith("mad:")
            }
        if set(c.check_id for c in r.checks) != required_checks:
            raise ValueError("Decision omits selected required checks")
        if r.release_decision == "pending_review":
            raise ValueError("Pending REVIEW blocks group execution")
        if m.availability != "unavailable" and (r.release_decision == "excluded") != (
            m.availability == "excluded"
        ):
            raise ValueError("Group exclusion differs from QC decision")
        if m.decision_authority is None or not any(
            a == m.decision_authority for a in group.authority
        ):
            raise ValueError("Group availability lacks supplied QC decision authority")
