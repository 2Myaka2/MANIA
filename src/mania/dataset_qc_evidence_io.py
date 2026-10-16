"""Explicit policy and evidence readers with exact supplied byte bindings."""

from pathlib import Path

from mania._dataset_qc_json import read_model, write_model
from mania.dataset_qc_contract import QCEvidence, QCPolicy, validate_policy_evidence


def read_qc_policy(path: Path, *, root: Path) -> QCPolicy:
    return read_model(path, QCPolicy, root=root)


def read_replica_hard_qc_evidence(
    path: Path, *, root: Path, policy: QCPolicy
) -> QCEvidence:
    result = read_model(path, QCEvidence, root=root)
    validate_policy_evidence(policy, result)
    bindings = [
        a
        for a in result.authority
        if a.role == "qc_policy" and a.sha256 == result.parameters.policy_sha256
    ]
    if (
        len(bindings) != 1
        or read_qc_policy(root / bindings[0].path, root=root) != policy
    ):
        raise ValueError("Policy content differs from bound policy")
    return result


read_replica_review_qc_evidence = read_replica_hard_qc_evidence
write_replica_hard_qc_evidence = write_model
write_replica_review_qc_evidence = write_model
