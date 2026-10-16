"""Coordinate-free generic RMSD presentation; drift requires supplied authority."""

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mania.dataset_qc_contract import QCEvidence, QCPolicy
    from mania.replica_aggregation_contract import ReplicaGroup
    from mania.replica_aggregation_manifest import ReplicaWindowInput

from mania.dataset_qc_contract import AssessmentAuthority, QCEvidenceRecord
from mania.handoff import load_completed_handoff
from mania.input_binding import FileEvidence, member
from mania.preprocessing.trajectory_rmsd_io import read_rmsd_measurement


def present_rmsd_review(
    root: Path, *, handoff_path: str, measurement_directory: str
) -> dict[str, object]:
    handoff = load_completed_handoff(root, handoff_path)
    required = {e.role: e for e in handoff.required_evidence}
    if not {"rmsd_measurement", "rmsd_timeseries"} <= required.keys():
        raise ValueError("Handoff must bind both RMSD evidence files")
    for role, name in [
        ("rmsd_measurement", "rmsd_measurement.json"),
        ("rmsd_timeseries", "rmsd_timeseries.csv"),
    ]:
        if required[role].path != measurement_directory + "/" + name:
            raise ValueError("RMSD directory differs from the handoff role/path")
        required[role].verify(root)
    measurement = read_rmsd_measurement(
        member(root, required["rmsd_measurement"].path).parent
    )
    if measurement.identity != handoff.identity:
        raise ValueError("RMSD source identity differs")
    return {
        "identity": measurement.identity.to_dict(),
        "measurement": measurement.to_dict(),
        "unit": "angstrom",
        "automatic_drift_classification": False,
        "assessment_state": "explicit_assessment_required",
    }


def build_rmsd_drift_assessment(
    root: Path,
    assessment: AssessmentAuthority | None,
    *,
    drift_detected: bool,
    handoff_path: str,
    measurement_directory: str,
) -> QCEvidenceRecord:
    present_rmsd_review(
        root, handoff_path=handoff_path, measurement_directory=measurement_directory
    )
    if assessment is None:
        raise ValueError("RMSD measurements alone cannot classify drift")
    AssessmentAuthority.model_validate(assessment.model_dump())
    handoff = load_completed_handoff(root, handoff_path)
    evidence = next(
        e for e in handoff.required_evidence if e.role == "rmsd_measurement"
    )
    return QCEvidenceRecord(
        check_id="rmsd_drift",
        state="negative" if drift_detected else "positive",
        value=drift_detected,
        evidence_role=evidence.role,
        evidence_sha256=evidence.sha256,
        assessment_authority=assessment,
    )


# Explicit runtime selections accompany the closed qc_evidence envelope. No
# selection/units/cohort fields are added to any public JSON or CSV schema.
MetricSourceSelection = tuple[str, FileEvidence, tuple[Any, ...], str, str | None]
_COMMON_NUMERIC_FIELDS: dict[str, str | None] = {
    "occupancy": None,
    "n_contact_frames": None,
    "n_contact_episodes": None,
    "mean_episode_length_ns": "ns",
    "max_episode_length_ns": "ns",
}
_SOURCE_NUMERIC_FIELDS = {
    "protein": {**_COMMON_NUMERIC_FIELDS, "edge_weight": None},
    "lipid": {
        **_COMMON_NUMERIC_FIELDS,
        "distance_mean_A": "angstrom",
        "distance_min_A": "angstrom",
    },
    "glycan": {
        **_COMMON_NUMERIC_FIELDS,
        "distance_mean_A": "angstrom",
        "distance_min_A": "angstrom",
    },
}


def validate_window_measurements(
    evidence: "QCEvidence",
    *,
    policy: "QCPolicy",
    source: "ReplicaWindowInput",
    group: "ReplicaGroup",
    selections: tuple[MetricSourceSelection, ...],
) -> dict[str, tuple[Any, ...]]:
    """Bind selected existing canonical numeric fields, never compute a metric.

    Families/names are explicitly supplied by the selected policy. The field
    name must be the exact existing upstream numeric field; its closed units
    are those of pinned FAIR dataset_release_source_authority. The row key uses
    the retained generic table's full deterministic source/reference order key.
    """
    from decimal import Context, Decimal, localcontext

    from mania.canonical_window_tables_io import read_reference_window_table
    from mania.dataset_qc_contract import validate_policy_evidence
    from mania.dataset_qc_evidence_io import read_qc_policy
    from mania.input_binding import verify_authority

    validate_policy_evidence(policy, evidence)
    if (
        source.identity != evidence.identity
        or evidence.reference != source.reference.reference
        or group.reference != evidence.reference
    ):
        raise ValueError("QC measurement source/reference identity differs")
    for authority in evidence.authority:
        verify_authority(source.root, authority, authority.source_identity)
    bound_policy = [a for a in evidence.authority if a.role == "qc_policy"]
    if (
        len(bound_policy) != 1
        or read_qc_policy(source.root / bound_policy[0].path, root=source.root)
        != policy
    ):
        raise ValueError("QC measurement policy content differs")
    temporal, replay = source.read_back()
    records = {r.check_id: r for r in evidence.records}
    selected = {s[0]: s for s in selections}
    if len(selected) != len(selections) or set(selected) != {
        k for k in records if k.startswith("mad:")
    }:
        raise ValueError("Incomplete or duplicate source metric selection roster")
    for check, role, descriptor, expected in (
        (
            "production_frame_coverage",
            "temporal_execution",
            source.temporal_evidence,
            temporal.sampling_plan.coverage_fraction,
        ),
    ):
        if check in records:
            r = records[check]
            if (r.evidence_role, r.evidence_sha256, r.value) != (
                role,
                descriptor.sha256,
                expected,
            ):
                raise ValueError(
                    "QC coverage differs from authoritative physical population"
                )
    if "protein_edge_empty_window_fraction" in records:
        if any(w.sampled_frame_count == 0 for w in temporal.window_plan.windows):
            raise ValueError(
                "Missing observation window is not a valid empty protein window"
            )
        complete = next(
            e for e in source.observation_evidence if e.role == "perframe_completion"
        )
        count = len(temporal.window_plan.windows)
        empty = sum(
            not any(
                r.window_id == w.window_id and r.window_index == w.window_index
                for r in replay.protein.rows
            )
            for w in temporal.window_plan.windows
        )
        with localcontext(Context(prec=max(50, len(str(count)) + 4))):
            fraction = float(Decimal(empty) / Decimal(count))
        r = records["protein_edge_empty_window_fraction"]
        if (r.evidence_role, r.evidence_sha256, r.value) != (
            complete.role,
            complete.sha256,
            fraction,
        ):
            raise ValueError("QC empty windows differ from completed source population")
    from mania.dataset_hard_qc import evaluate_replica_hard_qc

    if any(
        c.status == "FAIL" for c in evaluate_replica_hard_qc(evidence, policy=policy)
    ):
        return {}  # No raw-MAD measurement certification for a hard-FAIL member.
    result = {}
    for check, descriptor, key, field, unit in selections:
        _, family, name = check.split(":", 2)
        layer = group.layer
        allowed = _SOURCE_NUMERIC_FIELDS[layer]
        if name != field or field not in allowed or unit != allowed[field]:
            raise ValueError(
                "Unsupported source metric field/name/unit without conversion"
            )
        r = records[check]
        if r.state not in ("positive", "negative", "not_applicable") or r.value is None:
            raise ValueError("Incomplete metric cohort: missing is not zero")
        if descriptor.role != layer + "_reference_windows" or (
            r.evidence_role,
            r.evidence_sha256,
        ) != (descriptor.role, descriptor.sha256):
            raise ValueError("Source metric role/digest differs")
        if not any(
            (a.role, a.path, a.sha256, a.source_identity)
            == (descriptor.role, descriptor.path, descriptor.sha256, source.identity)
            for a in evidence.authority
        ):
            raise ValueError("Source metric lacks exact path/hash/replica authority")
        table = read_reference_window_table(
            descriptor.verify(source.root),
            source_table=getattr(replay, layer),
            mapping=source.mapping,
            reference=source.reference,
        )
        rows = [row for row in table.rows if table._order(row) == key]
        if len(rows) != 1:
            raise ValueError("Source metric row key must resolve uniquely")
        row = rows[0]
        value = getattr(row, field)
        if (
            type(value) not in (int, float)
            or type(r.value) not in (int, float)
            or Decimal(str(value)) != Decimal(str(r.value))
        ):
            raise ValueError(
                "Source metric value differs from authoritative numeric field"
            )
        if family == "edge_count" and (value < 0 or value != int(value)):
            raise ValueError("Source edge_count must be a nonnegative integer")
        if family == "contact_fraction" and not 0 <= value <= 1:
            raise ValueError("Source contact_fraction must lie in [0,1]")
        window = next(
            w
            for w in temporal.window_plan.windows
            if (w.window_id, w.window_index) == (row.window_id, row.window_index)
        )
        if window.sampled_frame_count == 0:
            raise ValueError("Source metric lacks an observed physical window")
        partner = None
        if layer != "protein":
            local = getattr(row, layer + "_partner_id")
            matches = [
                p
                for p in group.partner_correspondence
                if p.member_identity == source.identity
                and p.topology_local_partner_id == local
            ]
            if len(matches) != 1:
                raise ValueError("Source metric partner lacks group correspondence")
            partner = matches[0].group_partner_id
        result[check] = (
            evidence.identity.project,
            evidence.identity.system_id,
            evidence.identity.engine,
            evidence.identity.condition,
            evidence.identity.variant_id,
            evidence.identity.disulfide_state,
            source.reference.reference.reference_id,
            source.reference.reference.reference_sha256,
            layer,
            temporal.window_plan.boundary_profile,
            row.window_id,
            row.window_index,
            row.requested_window_start_ns,
            row.requested_window_end_ns,
            row.right_endpoint_inclusive,
            row.requested_sample_count,
            row.reference_chain_i,
            row.reference_position_i,
            (row.reference_chain_j, row.reference_position_j, row.edge_type)
            if layer == "protein"
            else partner,
            field,
            unit,
        )
    return result
