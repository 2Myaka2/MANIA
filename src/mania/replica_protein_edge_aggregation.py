"""Read-back-bound generic aggregation; private zeros require complete evidence."""

from decimal import Decimal
from pathlib import Path
from typing import Any

from mania._dataset_qc_json import read_model
from mania.dataset_qc_contract import QCDecisions, QCPolicy
from mania.dataset_qc_summary import validate_qc_group_availability
from mania.input_binding import verify_authority
from mania.replica_aggregation_contract import ReplicaGroup
from mania.replica_aggregation_manifest import ReplicaWindowInput, validate_group_inputs
from mania.replica_aggregation_tables import (
    ReplicaWindowRow,
    ReplicaWindowTable,
    occupancy_statistics,
)


def aggregate_windows(
    group: ReplicaGroup,
    inputs: tuple[ReplicaWindowInput, ...],
    *,
    policy: QCPolicy | None = None,
    decisions: tuple[QCDecisions, ...] | None = None,
    authority_root: Path | None = None,
) -> ReplicaWindowTable:
    if (policy is None) != (decisions is None):
        raise ValueError(
            "Selected QC requires explicit policy and supplied decisions together"
        )
    if any(m.decision_authority is not None for m in group.members) and policy is None:
        raise ValueError("QC-derived group cannot bypass its selected policy/decisions")
    if policy is not None and decisions is not None:
        if authority_root is None:
            raise ValueError("Selected QC needs its explicit authority root")
        validate_qc_group_availability(group, decisions, policy=policy)
        by_identity = {d.identity.model_dump_json(): d for d in decisions}
        for m in group.members:
            assert m.decision_authority is not None
            path = verify_authority(authority_root, m.decision_authority, m.identity)
            expected = by_identity[m.identity.model_dump_json()]
            if read_model(path, QCDecisions, root=authority_root) != expected:
                raise ValueError("Group decision contents differ from bound authority")
            bound = [
                a
                for a in expected.authority
                if a.role == "qc_policy"
                and a.sha256 == expected.parameters.policy_sha256
            ]
            if (
                len(bound) != 1
                or read_model(
                    authority_root / bound[0].path, QCPolicy, root=authority_root
                )
                != policy
            ):
                raise ValueError(
                    "QC decision policy contents differ from bound authority"
                )
    bindings = validate_group_inputs(group, inputs)
    if group.layer != "protein":
        available_keys = {
            m.identity.model_dump_json()
            for m in group.members
            if m.availability == "available"
        }
        for partner in {c.group_partner_id for c in group.partner_correspondence}:
            if {
                c.member_identity.model_dump_json()
                for c in group.partner_correspondence
                if c.group_partner_id == partner
            } != available_keys:
                raise ValueError(
                    "Correspondence must cover exactly the available roster"
                )
    rows = []
    for window in group.windows:
        physical = None
        observed: dict[tuple[Any, ...], dict[str, float]] = {}
        examples: dict[tuple[Any, ...], tuple[Any, dict[str, Any]]] = {}
        partner_names: dict[str, tuple[str, tuple[str, ...]]] = {}
        for inp, binding, replay in bindings:
            plan = binding.window_plan
            matching = [
                w
                for w in plan.windows
                if (w.window_id, w.window_index)
                == (window.window_id, window.window_index)
            ]
            if len(matching) != 1:
                raise ValueError("Member window is absent or ambiguous")
            actual = matching[0]
            if actual.sampled_frame_count == 0:
                raise ValueError(
                    "An available member window requires observed frames; "
                    "an empty observation population cannot contribute a private zero"
                )
            if (
                Decimal(str(actual.requested_start_ns)),
                Decimal(str(actual.requested_end_ns)),
                plan.boundary_profile,
                actual.requested_sample_indexes,
            ) != (
                Decimal(str(window.start_ns)),
                Decimal(str(window.end_ns)),
                window.boundary_profile,
                window.requested_sample_indexes,
            ):
                raise ValueError("Member requested window authority differs")
            params = dict(
                requested_production_start_ns=plan.requested_production_start_ns,
                requested_production_end_ns=plan.requested_production_end_ns,
                requested_window_start_ns=actual.requested_start_ns,
                requested_window_end_ns=actual.requested_end_ns,
                right_endpoint_inclusive=actual.right_endpoint_inclusive,
                window_length_ns=plan.requested_window_length_ns,
                window_step_ns=plan.requested_window_step_ns,
                overlap_percent=plan.requested_overlap_percent,
                boundary_profile=plan.boundary_profile,
            )
            if physical is not None and physical != params:
                raise ValueError("Member physical window definitions differ")
            physical = params
            table = getattr(replay, "canonical_" + group.layer)
            if table is None:
                raise ValueError("Reference table is required")
            # Replay retains unavailable specialized metadata; empty cannot mean zero.
            if group.layer != "protein":
                from mania.preprocessing.perframe_observations import (
                    read_perframe_observations,
                )

                saved = read_perframe_observations(
                    inp.root / inp.observation_directory,
                    __import__(
                        "mania.preprocessing.physical_time_execution_io",
                        fromlist=["read_preprocessing_temporal_execution"],
                    ).read_preprocessing_temporal_execution(
                        inp.temporal_evidence.verify(inp.root)
                    ),
                )
                conditions = saved.specialized.condition_results
                if len(conditions) != 1 or not getattr(
                    conditions[0].partner_catalog, group.layer + "_partner_count"
                ):
                    raise ValueError(
                        "Specialized observations are unavailable or not applicable"
                    )
                catalog = conditions[0].partner_catalog
                selected = [
                    c
                    for c in group.partner_correspondence
                    if c.member_identity == inp.identity
                ]
                by_local = {
                    p.partner_id: p
                    for p in catalog.partners
                    if p.partner_kind == group.layer
                }
                if {c.topology_local_partner_id for c in selected} != set(by_local):
                    raise ValueError(
                        "Correspondence must cover the complete declared partner roster"
                    )
                for c in selected:
                    p = by_local[c.topology_local_partner_id]
                    chemistry = (p.partner_name, tuple(x.resname for x in p.components))
                    prior = partner_names.get(c.group_partner_id)
                    if prior is not None and prior != chemistry:
                        raise ValueError("Correspondence partner chemistry differs")
                    partner_names[c.group_partner_id] = chemistry
            for r in table.rows:
                key: tuple[Any, ...]
                if (r.window_id, r.window_index) != (
                    window.window_id,
                    window.window_index,
                ):
                    continue
                if group.layer == "protein":
                    key = (
                        r.reference_chain_i,
                        r.reference_position_i,
                        r.reference_chain_j,
                        r.reference_position_j,
                        r.edge_type,
                    )
                    fields = dict(
                        reference_chain_j=r.reference_chain_j,
                        reference_position_j=r.reference_position_j,
                        reference_resname_j=r.reference_resname_j,
                        edge_type=r.edge_type,
                        group_partner_id=None,
                        partner_name=None,
                    )
                else:
                    local = getattr(r, group.layer + "_partner_id")
                    mappings = [
                        c
                        for c in group.partner_correspondence
                        if c.member_identity == inp.identity
                        and c.topology_local_partner_id == local
                    ]
                    if len(mappings) != 1:
                        raise ValueError(
                            "Observed topology-local partner lacks explicit cor"
                            "respondence"
                        )
                    partner = mappings[0].group_partner_id
                    name = getattr(r, group.layer + "_partner_name")
                    if partner_names[partner][0] != name:
                        raise ValueError(
                            "Observed partner differs from declared catalog"
                        )
                    key = (r.reference_chain_i, r.reference_position_i, partner)
                    fields = dict(
                        reference_chain_j=None,
                        reference_position_j=None,
                        reference_resname_j=None,
                        edge_type=None,
                        group_partner_id=partner,
                        partner_name=name,
                    )
                identity = inp.identity.model_dump_json()
                if identity in observed.setdefault(key, {}):
                    raise ValueError("Duplicate member observation")
                observed[key][identity] = r.occupancy
                examples[key] = (r, fields)
        if physical is None:
            continue
        available = tuple(i.identity for i, _, _ in bindings)
        order = {c.chain_id: i for i, c in enumerate(group.reference.chains)}

        def row_order(
            key: tuple[Any, ...],
            examples: dict[tuple[Any, ...], tuple[Any, dict[str, Any]]] = examples,
            order: dict[str, int] = order,
        ) -> tuple[Any, ...]:
            r, f = examples[key]
            return (
                order[r.reference_chain_i],
                r.reference_position_i,
                order[r.reference_chain_j]
                if group.layer == "protein"
                else f["group_partner_id"],
                r.reference_position_j if group.layer == "protein" else 0,
                r.edge_type if group.layer == "protein" else "",
            )

        for key in sorted(observed, key=row_order):
            r, fields = examples[key]
            values = tuple(
                observed[key].get(i.model_dump_json(), 0.0) for i in available
            )
            rows.append(
                ReplicaWindowRow.model_validate(
                    dict(
                        group_id=group.group_id,
                        layer=group.layer,
                        window_id=window.window_id,
                        window_index=window.window_index,
                        reference_id=group.reference.reference_id,
                        reference_sha256=group.reference.reference_sha256,
                        reference_chain_i=r.reference_chain_i,
                        reference_position_i=r.reference_position_i,
                        reference_resname_i=r.reference_resname_i,
                        contributing_replica_keys=available,
                        occupancy_values=values,
                        **physical,
                        **fields,
                        **occupancy_statistics(values),
                    )
                )
            )
    return ReplicaWindowTable(rows=tuple(rows))


def aggregate_canonical_protein_edges_across_replicas(
    group: ReplicaGroup, inputs: tuple[ReplicaWindowInput, ...], **context: Any
) -> ReplicaWindowTable:
    if group.layer != "protein":
        raise ValueError("Protein aggregation requires a protein group")
    return aggregate_windows(group, inputs, **context)
