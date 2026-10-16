"""Selected source QC comparisons over supplied, source-bound observations."""

import re
from dataclasses import dataclass, fields
from decimal import Context, Decimal, localcontext
from pathlib import Path
from typing import TYPE_CHECKING, Literal, get_args

if TYPE_CHECKING:
    from mania.input_binding import FileEvidence
    from mania.preprocessing.physical_time_sampling import (
        ResolvedPhysicalTimeSamplingPlan,
    )
    from mania.replica_aggregation_manifest import ReplicaWindowInput

from mania.dataset_qc_contract import (
    HARD_CHECK_IDS,
    QCCheckResult,
    QCEvidence,
    QCPolicy,
    validate_policy_evidence,
)


def evaluate_replica_hard_qc(
    evidence: QCEvidence,
    *,
    policy: QCPolicy,
    source_sampling: "ResolvedPhysicalTimeSamplingPlan | None" = None,
) -> tuple[QCCheckResult, ...]:
    validate_policy_evidence(policy, evidence)
    result = []
    for r in evidence.records:
        if r.check_id not in HARD_CHECK_IDS and not r.check_id.startswith(
            ("required_metadata:", "required_artifact:", "schema:")
        ):
            continue
        if r.state == "missing":
            passing = False
        elif r.state == "not_applicable":
            raise ValueError(
                "Required hard scientific checks cannot be marked inapplicable"
            )
        elif r.check_id == "production_frame_coverage":
            if (
                not isinstance(r.value, (int, float))
                or isinstance(r.value, bool)
                or not 0 <= r.value <= 1
                or policy.coverage_fraction is None
            ):
                raise ValueError(
                    "Coverage requires a finite explicit fraction and policy"
                )
            if source_sampling is None:
                passing = Decimal(str(r.value)) >= Decimal(
                    str(policy.coverage_fraction)
                )
            else:
                if r.value != source_sampling.coverage_fraction:
                    raise ValueError(
                        "Coverage differs from authoritative requested/resolv"
                        "ed population"
                    )
                expected = source_sampling.requested_sample_count
                with localcontext(Context(prec=max(50, len(str(expected)) + 4))):
                    passing = Decimal(source_sampling.sampled_frame_count) >= Decimal(
                        str(policy.coverage_fraction)
                    ) * Decimal(expected)
        else:
            if type(r.value) is not bool:
                raise ValueError(
                    "Source hard check requires a supplied boolean assessment"
                )
            passing = r.value
        if r.state in ("positive", "negative") and (r.state == "positive") != passing:
            raise ValueError("Contradictory scientific evidence state")
        result.append(
            QCCheckResult(
                check_id=r.check_id,
                severity="hard",
                status="PASS" if passing else "FAIL",
                value=r.value,
                evidence_role=r.evidence_role,
                evidence_sha256=r.evidence_sha256,
            )
        )
    return tuple(result)


_SourceEvidenceType = Literal[
    "artifact", "metric", "window", "mapping", "pbc", "manual_review"
]


def _text(value: object, name: str) -> str:
    # Strip outer whitespace only; never infer identifiers or rewrite prose.
    if type(value) is not str or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value.strip()


def _literal(value: object, allowed: tuple[str, ...], name: str) -> None:
    if type(value) is not str or value not in allowed:
        raise ValueError(f"{name} must be exactly one of {allowed}")


def _portable_path(value: str) -> None:
    # Lexical validation only: no resolution, expansion, existence check or I/O.
    if (
        any(part in ("", ".", "..") for part in value.split("/"))
        or any(marker in value for marker in ("\\", ":", "~", "$", "%"))
        or any(ord(char) < 32 or ord(char) == 127 for char in value)
    ):
        raise ValueError(
            "artifact_path must be a portable relative forward-slash path "
            "without traversal, home or environment expansion"
        )


@dataclass(frozen=True)
class _SourceArtifactRecord:
    """Structured portable evidence; supplied text is not scientifically evaluated."""

    evidence_id: str
    evidence_type: _SourceEvidenceType
    artifact_role: str | None
    artifact_path: str | None
    window_id: str | None
    metric_name: str | None
    observed_value: str | None
    expected_or_threshold: str | None
    details: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_id", _text(self.evidence_id, "evidence_id"))
        _literal(self.evidence_type, get_args(_SourceEvidenceType), "evidence_type")
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
            raise ValueError(
                f"{self.evidence_type} evidence lacks its required structured payload"
            )

    def to_dict(self) -> dict[str, object]:
        return {item.name: getattr(self, item.name) for item in fields(self)}


def _evidence(value: object) -> None:
    if (
        type(value) is not _SourceArtifactRecord
        or value.evidence_type == "manual_review"
    ):
        raise ValueError("Hard integrity needs exact existing source artifact evidence")
    value.__post_init__()


def _bool(value: object, name: str) -> None:
    if type(value) is not bool:
        raise ValueError(f"{name} must be exact bool")


def _item_id(value: str) -> str:
    value = _text(value, "item ID")
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value) is None:
        raise ValueError(
            "item IDs require letters, digits, dots, dashes or underscores"
        )
    return value


@dataclass(frozen=True)
class _SourceRawIntegrity:
    """Authoritative observations of the same declared all-atom universe."""

    topology_readable: bool
    trajectory_readable: bool
    topology_atom_count: int | None
    trajectory_atom_count: int | None
    atom_order_consistent: bool | None
    atom_universe_id: str
    topology_evidence: _SourceArtifactRecord
    trajectory_evidence: _SourceArtifactRecord
    atom_order_evidence: _SourceArtifactRecord | None

    def __post_init__(self) -> None:
        for source in ("topology", "trajectory"):
            readable = getattr(self, f"{source}_readable")
            count = getattr(self, f"{source}_atom_count")
            _bool(readable, f"{source}_readable")
            if count is not None and (type(count) is not int or count < 0):
                raise ValueError("atom counts must be non-negative exact ints")
            if readable and count is None:
                raise ValueError("readable sources require atom-count evidence")
            _evidence(getattr(self, f"{source}_evidence"))
        object.__setattr__(self, "atom_universe_id", _item_id(self.atom_universe_id))
        if self.atom_order_consistent is not None:
            _bool(self.atom_order_consistent, "atom_order_consistent")
            _evidence(self.atom_order_evidence)
        elif self.atom_order_evidence is not None:
            _evidence(self.atom_order_evidence)


def _read_raw_integrity(descriptor: "FileEvidence", root: Path) -> _SourceRawIntegrity:
    """Read the existing pinned raw-observation type, not a new public envelope."""
    from mania.input_binding import member
    from mania.preprocessing.molecular_partner_metadata_io import (
        exact_fields,
        read_strict_json,
    )
    from mania.preprocessing.trajectory_rmsd_io import file_sha256

    data = exact_fields(
        read_strict_json(descriptor.verify(root)),
        {f.name for f in fields(_SourceRawIntegrity)},
    )
    for name in ("topology_evidence", "trajectory_evidence", "atom_order_evidence"):
        value = data[name]
        if value is not None:
            data[name] = _SourceArtifactRecord(
                **exact_fields(value, {f.name for f in fields(_SourceArtifactRecord)})
            )
    result = _SourceRawIntegrity(**data)
    for leaf in (
        result.topology_evidence,
        result.trajectory_evidence,
        result.atom_order_evidence,
    ):
        if leaf is None:
            continue
        if (
            leaf.artifact_path is None
            or leaf.artifact_role is None
            or leaf.details is None
        ):
            raise ValueError(
                "Raw observation lacks actual portable artifact/hash lineage"
            )
        path = member(root, leaf.artifact_path)
        digests = re.findall(r"sha256=([0-9a-f]{64})(?:;|$| )", leaf.details)
        if len(digests) != 1 or digests[0] != file_sha256(path):
            raise ValueError("Raw observation source SHA256 differs")
    return result


def verify_hard_measurement_sources(
    evidence: QCEvidence,
    *,
    source: "ReplicaWindowInput",
    policy: QCPolicy,
    raw_integrity: "FileEvidence | None" = None,
) -> tuple[QCCheckResult, ...]:
    """Certify selected existing hard observations through their actual readers."""
    from itertools import pairwise

    from mania.input_binding import verify_authority
    from mania.preprocessing.protein_integrity_observations import (
        read_protein_integrity,
    )

    validate_policy_evidence(policy, evidence)
    if (
        evidence.identity != source.identity
        or evidence.reference != source.reference.reference
    ):
        raise ValueError("Hard source/reference identity differs")
    for authority in evidence.authority:
        verify_authority(source.root, authority, authority.source_identity)
    from mania.scientific_qualification import consume_run_path

    consume_run_path(source.temporal_evidence.verify(source.root), source.identity)
    temporal, _ = source.read_back()
    records = {r.check_id: r for r in evidence.records}
    expected: dict[str, tuple[FileEvidence, bool | float]] = {
        "production_frame_coverage": (
            source.temporal_evidence,
            temporal.sampling_plan.coverage_fraction,
        ),
        "frame_time_strictly_increasing": (
            source.temporal_evidence,
            not any(
                b.actual_time_ps <= a.actual_time_ps
                for a, b in pairwise(temporal.sampling_plan.selected_samples)
            )
            and not any(
                i.code == "non_monotonic_source_time"
                for i in temporal.sampling_plan.issues
            ),
        ),
        "canonical_mapping_complete": (
            source.mapping_evidence,
            all(r.mapping_status == "mapped" for r in source.mapping.records),
        ),
        "canonical_reference": (source.reference_evidence, True),
    }
    completion = next(
        e for e in source.observation_evidence if e.role == "perframe_completion"
    )
    expected.update(
        {
            c: (completion, True)
            for c in ("forbidden_self_loops", "duplicate_records", "occupancy_range")
        }
    )
    raw_checks = {
        "topology_readable",
        "trajectory_readable",
        "topology_trajectory_atom_count",
        "topology_trajectory_atom_order",
    }
    if raw_checks & records.keys():
        if raw_integrity is None:
            raise ValueError("Required raw integrity source report is absent")
        raw = _read_raw_integrity(raw_integrity, source.root)
        expected.update(
            {
                "topology_readable": (raw_integrity, raw.topology_readable),
                "trajectory_readable": (raw_integrity, raw.trajectory_readable),
                "topology_trajectory_atom_count": (
                    raw_integrity,
                    raw.topology_readable
                    and raw.trajectory_readable
                    and raw.topology_atom_count == raw.trajectory_atom_count,
                ),
                "topology_trajectory_atom_order": (
                    raw_integrity,
                    raw.topology_readable
                    and raw.trajectory_readable
                    and raw.atom_order_consistent is True,
                ),
            }
        )
    if "protein_pbc_integrity" in records:
        r = records["protein_pbc_integrity"]
        matches = [
            a
            for a in evidence.authority
            if (a.role, a.sha256) == (r.evidence_role, r.evidence_sha256)
        ]
        if len(matches) != 1:
            raise ValueError("PBC integrity source authority is absent")
        path = verify_authority(source.root, matches[0], source.identity)
        integrity = read_protein_integrity(path)
        old = integrity.dataset_identity
        if (
            old.dataset_id,
            old.system_id,
            old.trajectory_id,
            old.replica_id,
            old.engine,
        ) != (
            source.identity.project,
            source.identity.system_id,
            source.identity.trajectory_id,
            source.identity.replica_id,
            source.identity.engine,
        ) or integrity.protein_remains_broken is None:
            raise ValueError("PBC assessment source identity/value unavailable")
        from mania.input_binding import FileEvidence

        expected["protein_pbc_integrity"] = (
            FileEvidence(
                role=r.evidence_role,
                path=matches[0].path,
                size_bytes=path.stat().st_size,
                sha256=matches[0].sha256,
            ),
            not integrity.protein_remains_broken,
        )
    for r in evidence.records:
        if r.check_id not in HARD_CHECK_IDS and not r.check_id.startswith(
            ("required_metadata:", "required_artifact:", "schema:")
        ):
            continue
        if r.state == "missing":
            continue
        if r.check_id.startswith(
            ("required_metadata:", "required_artifact:", "schema:")
        ):
            bound = [
                a
                for a in evidence.authority
                if (a.role, a.sha256, a.source_identity)
                == (r.evidence_role, r.evidence_sha256, source.identity)
            ]
            if len(bound) != 1:
                raise ValueError("Required artifact lacks exact source/path authority")
            path = verify_authority(source.root, bound[0], source.identity)
            from mania.input_binding import FileEvidence

            descriptor = FileEvidence(
                role=r.evidence_role,
                path=bound[0].path,
                size_bytes=path.stat().st_size,
                sha256=bound[0].sha256,
            )
            if r.check_id.startswith("schema:"):
                _read_required_artifact(path, source, role=descriptor.role)
            expected[r.check_id] = (descriptor, True)
        if r.check_id not in expected:
            raise ValueError("Unsupported strict hard source reader: " + r.check_id)
        descriptor, value = expected[r.check_id]
        if (r.evidence_role, r.evidence_sha256, r.value) != (
            descriptor.role,
            descriptor.sha256,
            value,
        ) or not any(
            (a.role, a.path, a.sha256, a.source_identity)
            == (descriptor.role, descriptor.path, descriptor.sha256, source.identity)
            for a in evidence.authority
        ):
            raise ValueError(
                "Hard QC value differs from authoritative source field/role/hash"
            )
    return evaluate_replica_hard_qc(
        evidence, policy=policy, source_sampling=temporal.sampling_plan
    )


def _read_required_artifact(
    path: Path, source: "ReplicaWindowInput", *, role: str
) -> None:
    """Known retained strict readers; an unknown artifact is never schema PASS."""
    from mania.artifact_inventory_io import read_artifact_inventory
    from mania.biological_annotations_io import read_system_annotations
    from mania.canonical_reference_io import read_protein_reference
    from mania.canonical_residue_mapping_io import read_residue_mapping
    from mania.preprocessing.molecular_partner_catalog_io import (
        read_molecular_partner_catalog,
    )
    from mania.preprocessing.molecular_partner_metadata_io import read_strict_json
    from mania.preprocessing.physical_time_execution_io import (
        read_preprocessing_temporal_execution,
    )
    from mania.preprocessing.trajectory_rmsd_io import read_rmsd_measurement
    from mania.run_provenance_io import read_run_provenance
    from mania.runtime_metadata_io import read_runtime_metadata

    if path.suffix != ".json":
        temporal, replay = source.read_back()
        from mania.canonical_window_tables_io import read_reference_window_table
        from mania.preprocessing.protein_edge_window_table_io import (
            read_dataset_protein_edge_window_csv,
        )
        from mania.preprocessing.specialized_contact_window_tables_io import (
            read_protein_glycan_window_csv,
            read_protein_lipid_window_csv,
        )

        readers = {
            "protein": read_dataset_protein_edge_window_csv,
            "lipid": read_protein_lipid_window_csv,
            "glycan": read_protein_glycan_window_csv,
        }
        for layer in ("protein", "lipid", "glycan"):
            if role == layer + "_source_windows":
                if readers[layer](path) != getattr(replay, layer):
                    raise ValueError("Required source CSV differs")
                return
            if role == layer + "_reference_windows":
                read_reference_window_table(
                    path,
                    source_table=getattr(replay, layer),
                    mapping=source.mapping,
                    reference=source.reference,
                )
                return
        raise ValueError("Required schema needs an explicitly supported strict reader")
    data = read_strict_json(path)
    schema = data.get("schema_version")
    if schema == "mania.reference.v1":
        if read_protein_reference(path) != source.reference:
            raise ValueError("Required source reference differs")
    elif schema == "mania.residue_mapping.v1":
        if read_residue_mapping(path, reference=source.reference) != source.mapping:
            raise ValueError("Required source mapping differs")
    elif schema == "mania.annotations.v1":
        read_system_annotations(path, reference=source.reference)
    elif schema in (
        "mania.preprocessing_temporal_execution.v0.1",
        "mania.preprocessing_temporal_execution.v0.2",
    ):
        read_preprocessing_temporal_execution(path)
    elif schema == "mania.rmsd.v1":
        read_rmsd_measurement(path.parent)
    elif schema == "mania.molecular_partner_catalog.v0.1":
        read_molecular_partner_catalog(path)
    elif schema == "mania.artifact_inventory.v0.1":
        read_artifact_inventory(path)
    elif schema == "mania.run_provenance.v0.1":
        read_run_provenance(path)
    elif schema == "mania.runtime_metadata.v0.1":
        read_runtime_metadata(path)
    else:
        raise ValueError("Unknown required schema has no scientific reader")
