"""Read-only fixed Dataset authority, source selection and deterministic contacts.

No coordinate preparation, metric calculation, production producer or dispatcher.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from decimal import Decimal
from importlib.resources import files
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from mania.artifact_inventory import ArtifactInventory
from mania.biological_annotations import SystemAnnotations
from mania.dataset_measurement_review import MetricSourceSelection
from mania.input_binding import FileEvidence, member
from mania.preprocessing.molecular_partner_catalog_io import (
    read_molecular_partner_catalog,
)
from mania.preprocessing.molecular_partner_metadata_io import read_strict_json
from mania.preprocessing.protein_edge_window_table import _effective_ns
from mania.preprocessing.trajectory_contacts import PreprocessingContactDetectionOptions
from mania.preprocessing.trajectory_preprocessing_manifests import (
    build_edge_semantics_manifest,
)
from mania.replica_aggregation_manifest import ReplicaWindowInput
from mania_napi2b.biological_annotations import DatasetSystemBiologicalAnnotations
from mania_napi2b.publication import (
    DatasetReleaseMetadataTables,
    DatasetReleaseScienceError,
    ReplicaKey,
    build_dataset_release_contact_definition,
    publication_metadata_index,
    validate_dataset_release_scientific_relationships,
)
from mania_napi2b.tables import (
    REPLICA_KEY,
    WINDOW_KEY,
    DatasetReleaseTable,
    FixedWindowTable,
    PublicationRow,
    fixed_window_csv_bytes,
    publication_number,
    publication_table_spec,
    require_portable_publication_path,
)

if TYPE_CHECKING:
    from mania_napi2b.publication import DatasetReleaseScientificTables
    from mania_napi2b.publication_io import (
        DatasetReleaseExportManifest,
        ReleaseUpstreamRun,
    )


def _metric_table(records: Iterable[Mapping[str, object]]) -> DatasetReleaseTable:
    spec = publication_table_spec("metrics")
    rows = []
    for record in records:
        if set(record) != {c.name for c in spec.columns}:
            raise ValueError("Metric must retain exact frozen fields")
        rows.append(tuple(record[c.name] for c in spec.columns))
    return DatasetReleaseTable(spec, cast(tuple[PublicationRow, ...], tuple(rows)))


"""Construct publication metadata from versioned authority and explicit run inputs.

No historical publication input, coordinate loading or scientific calculation.
The existing Stage 33 projection remains the strict publication model boundary.
"""

AUTHORITY_RESOURCE = "data/publication/contact_definition_authority_v1.json"

AUTHORITY_SHA256 = "6beafe903e8ca10fc8b9d749108043c3d2c366aed0d516cc4a8041054a89c597"


def _canonical(value: Any) -> str:
    # JSON equality deliberately distinguishes boolean, integer and float leaves.
    return json.dumps(value, sort_keys=True, allow_nan=False, separators=(",", ":"))


def _authority_bytes() -> bytes:
    content = files("mania_napi2b").joinpath(AUTHORITY_RESOURCE).read_bytes()
    if hashlib.sha256(content).hexdigest() != AUTHORITY_SHA256:
        raise ValueError("Committed contact authority hash differs")
    return content


def _bound_path(workspace: Path, path: str) -> Path:
    require_portable_publication_path(path)
    return member(workspace, path)


def materialize_contact_definition_authority(workspace: Path, path: str) -> Path:
    """Copy exact package bytes; reject an existing substituted authority."""
    require_portable_publication_path(path)
    content = _authority_bytes()
    target = workspace / path
    if target.exists():
        if target.read_bytes() != content:
            raise ValueError("Materialized contact authority differs from package")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(content)
    return target


@dataclass(frozen=True)
class PublicationContactDefinition:
    """An exact nested Stage 33 input plus its strict flattened model."""

    replica_key: ReplicaKey
    contact_definition_id: str
    contact_layer: str
    interaction_type: str
    parameters: dict[str, Any]
    source_artifact_role: str
    source_artifact_path: str
    units: dict[str, str]

    def __post_init__(self) -> None:
        self.to_table()

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(
            dict(
                replica_key=list(self.replica_key),
                contact_definition_id=self.contact_definition_id,
                contact_layer=self.contact_layer,
                interaction_type=self.interaction_type,
                parameters=self.parameters,
                source_artifact_role=self.source_artifact_role,
                source_artifact_path=self.source_artifact_path,
                units=self.units,
            )
        )

    def to_table(self) -> DatasetReleaseTable:
        payload = self.to_dict()
        payload["replica_key"] = self.replica_key
        return build_dataset_release_contact_definition(**payload)


def _run_contact_configuration(
    workspace: Path, path: str, replica_key: ReplicaKey
) -> tuple[dict[str, Any], int]:
    run = read_strict_json(_bound_path(workspace, path))
    if (
        run["kind"] != "mania_run_provenance"
        or run["status"] != "completed"
        or type(run["run_id"]) is not str
        or not run["run_id"].strip()
    ):
        raise ValueError("Completed current run identity is required")
    configuration = run["resolved_configuration"]
    bindings = configuration["dataset_context"]["bindings"]
    selected = [
        b
        for b in bindings
        if tuple(
            b["dataset_spec"]["identity"][name]
            for name in ("dataset_id", "system_id", "trajectory_id", "replica_id")
        )
        == replica_key
    ]
    if len(selected) != 1:
        raise ValueError("Run configuration must bind exactly this replica identity")
    sampling = [
        s
        for s in run["sampling_by_condition"]
        if s["condition"] == selected[0]["execution_condition"]
    ]
    if len(sampling) != 1:
        raise ValueError("Exactly one current sampling binding is required")
    count = sampling[0]["effective"]["sampled_frame_count"]
    if type(count) is not int or count < 1:
        raise ValueError("Resolved sample count must be a positive integer")
    options = configuration["contact_detection_options"]
    validated = PreprocessingContactDetectionOptions(**options).to_dict(
        include_contact_selection=True
    )
    if _canonical(options) != _canonical(validated):
        raise ValueError("Contact options must be complete without normalization")
    if options["distance_unit"] != "angstrom":
        raise ValueError("Contact unit mismatch: accepted representation is angstrom")
    if options["contact_selection"] != "protein":
        raise ValueError("Protein publication requires protein contact selection")
    return options, count


def build_dataset_release_contact_definitions(
    *,
    workspace: Path,
    replica_key: ReplicaKey,
    edge_semantics_path: str,
    run_provenance_path: str,
    pbc_correction_status: dict[str, Any],
    specialized_authority_path: str | None = None,
    partner_catalog_path: str | None = None,
) -> tuple[PublicationContactDefinition, ...]:
    """Build every implemented protein definition and optional specialized pair.

    All paths are explicit workspace-relative artifact bindings. Supplying a
    specialized authority requires its exact package bytes and a partner catalog.
    PBC approval is explicit caller evidence, never inferred from coordinates.
    Current provenance supplies run identity, contact options and resolved count.
    """
    contract = json.loads(_authority_bytes())
    semantics = read_strict_json(_bound_path(workspace, edge_semantics_path))
    if _canonical(semantics) != _canonical(build_edge_semantics_manifest()):
        raise ValueError("Edge semantics differ from implemented publication authority")
    options, count = _run_contact_configuration(
        workspace, run_provenance_path, replica_key
    )
    pbc = copy.deepcopy(pbc_correction_status)
    expected_pbc = contract["pbc_required_values"]
    if set(pbc) != set(expected_pbc) | set(contract["pbc_path_fields"]) or any(
        _canonical(pbc[name]) != _canonical(value)
        for name, value in expected_pbc.items()
    ):
        raise ValueError(
            "PBC requires approved external protocol and internal_mic=false"
        )
    for name in contract["pbc_path_fields"]:
        _bound_path(workspace, pbc[name])
    # Preserve the accepted five-sample prose, but never apply it to another run.
    sample_label = "five" if count == 5 else str(count)
    common = contract["shared_parameters"] | dict(
        occupancy_denominator_semantics=contract[
            "occupancy_denominator_template"
        ].format(resolved_samples=sample_label),
        pbc_correction_status=pbc,
    )
    protein = contract["protein"]
    models = []
    for edge in semantics["edge_types"]:
        criteria = edge["detection_criteria"]
        cutoff = (
            dict(
                value=options["cutoff_distance"],
                unit=options["distance_unit"],
                comparator="<=",
            )
            if criteria.get("threshold_source") == "runtime contact definition"
            else criteria
        )
        models.append(
            PublicationContactDefinition(
                replica_key=replica_key,
                contact_definition_id=edge["name"],
                contact_layer=protein["contact_layer"],
                interaction_type=edge["canonical_backend_spelling"],
                parameters=copy.deepcopy(
                    common
                    | dict(
                        atom_selections=options,
                        cutoff=cutoff,
                        distance_definition=edge["definition"],
                        specialized_distance_semantics=protein[
                            "specialized_distance_semantics"
                        ],
                        type_specific_parameters=edge,
                    )
                ),
                source_artifact_role=protein["source_artifact_role"],
                source_artifact_path=edge_semantics_path,
                units=copy.deepcopy(protein["units"]),
            )
        )
    if specialized_authority_path is None:
        if partner_catalog_path is not None:
            raise ValueError("Partner catalog requires specialized authority binding")
        return tuple(models)
    materialized = _bound_path(workspace, specialized_authority_path)
    if materialized.read_bytes() != _authority_bytes():
        raise ValueError("Materialized contact authority differs from package")
    if partner_catalog_path is None:
        raise ValueError("Missing partner catalog binding")
    catalog = read_molecular_partner_catalog(
        _bound_path(workspace, partner_catalog_path)
    )
    if (
        len(catalog.bindings) != 1
        or catalog.bindings[0].dataset_spec.identity.replica_key != replica_key
    ):
        raise ValueError("Partner catalog source identity differs")
    for definition in contract["specialized_definitions"]:
        payload = copy.deepcopy(definition)
        payload.update(
            replica_key=replica_key, source_artifact_path=specialized_authority_path
        )
        payload["parameters"].update(copy.deepcopy(common))
        payload["parameters"]["type_specific_parameters"][
            contract["specialized_partner_binding_field"]
        ] = partner_catalog_path
        models.append(PublicationContactDefinition(**payload))
    return tuple(models)


@dataclass(frozen=True)
class AuthoritativePublicationMetric:
    """One supplied source record, with the exact frozen Stage 33.A fields.

    metric_id and source_record_key are explicit, deterministic source identities.
    This primary-science API requires a finite value even though the low-level
    frozen schema permits an upstream-authorized null. No QC evidence is promoted.
    """

    dataset_id: str
    system_id: str
    trajectory_id: str
    replica_id: str
    metric_id: str
    window_id: str | None
    window_index: int | None
    metric_name: str
    metric_value: float | int | Decimal
    unit: str | None
    source_artifact_role: str
    source_artifact_path: str
    source_record_key: str

    def __post_init__(self) -> None:
        if (self.window_id is None) != (self.window_index is None):
            raise DatasetReleaseScienceError("Metric window fields must pair")
        publication_number(self.metric_value)
        _metric_table((asdict(self),))


_COMMON_FIELDS: dict[str, str | None] = {
    "occupancy": None,
    "n_contact_frames": None,
    "n_contact_episodes": None,
    "mean_episode_length_ns": "ns",
    "max_episode_length_ns": "ns",
}
_FAMILY_FIELDS = {
    "protein": {**_COMMON_FIELDS, "edge_weight": None},
    "lipid": {
        **_COMMON_FIELDS,
        "distance_mean_A": "angstrom",
        "distance_min_A": "angstrom",
    },
    "glycan": {
        **_COMMON_FIELDS,
        "distance_mean_A": "angstrom",
        "distance_min_A": "angstrom",
    },
}
_CANONICAL_ROLES = {
    "protein": "canonical_protein_edge_window_table",
    "lipid": "canonical_protein_lipid_window_table",
    "glycan": "canonical_protein_glycan_window_table",
}


def fixed_source_record_key(row: Mapping[str, Any], layer: str) -> str:
    key = tuple(row[n] for n in REPLICA_KEY) + (row["window_id"],)
    if layer == "protein":
        key += (
            row["source_canonical_residue_number"],
            row["target_canonical_residue_number"],
            row["edge_type"],
        )
    else:
        key += (row["canonical_residue_number"], row[layer + "_partner_id"])
    return json.dumps(key, ensure_ascii=False, separators=(",", ":"))


def validate_publication_metric_sources(
    metrics: tuple[AuthoritativePublicationMetric, ...],
    fields: tuple[str, ...],
    *,
    workspace: Path,
    control: DatasetReleaseExportManifest,
    metadata: DatasetReleaseMetadataTables,
    canonical_sources: tuple[tuple[FileEvidence, FixedWindowTable], ...],
) -> None:
    """Pinned canonical numeric field selection, including exact physical evidence."""
    if len(metrics) != len(fields):
        raise ValueError("Metric selections/fields differ")
    windows = publication_metadata_index(metadata, "time_windows")
    simulations = publication_metadata_index(metadata, "simulations")
    for metric, field in zip(metrics, fields, strict=True):
        metric.__post_init__()
        if metric.window_id is None or metric.window_index is None:
            raise ValueError("Canonical metric requires a physical window")
        matches = [
            (e, t)
            for e, t in canonical_sources
            if e.path == metric.source_artifact_path
            and e.role == metric.source_artifact_role
        ]
        if len(matches) != 1:
            raise ValueError("Metric source must match exactly one canonical binding")
        descriptor, table = matches[0]
        layer = table.generic.layer
        if (
            descriptor.role != _CANONICAL_ROLES[layer]
            or field not in _FAMILY_FIELDS[layer]
            or metric.unit != _FAMILY_FIELDS[layer][field]
        ):
            raise ValueError("Unsupported metric numeric field or mismatching unit")
        bindings = [
            b
            for b in control.canonical_bindings
            if b.family == layer and b.path == descriptor.path
        ]
        if len(bindings) != 1:
            raise ValueError("Metric canonical control binding differs")
        if descriptor.verify(workspace).read_bytes() != fixed_window_csv_bytes(table):
            raise ValueError("Metric canonical source content differs")
        records = [
            row
            for row in table.records()
            if fixed_source_record_key(row, layer) == metric.source_record_key
        ]
        if len(records) != 1:
            raise ValueError("Metric source key must resolve to exactly one record")
        row = records[0]
        replica = tuple(getattr(metric, n) for n in REPLICA_KEY)
        if (
            tuple(row[n] for n in REPLICA_KEY) != replica
            or replica not in bindings[0].replica_keys
        ):
            raise ValueError("Metric source replica identity differs")
        if (
            replica not in simulations
            or simulations[replica]["included_in_scientific_release"] is not True
        ):
            raise ValueError("Metric source is not eligible scientific evidence")
        if (row["window_id"], row["window_index"]) != (
            metric.window_id,
            metric.window_index,
        ) or table.temporal.window_plan.boundary_profile != metadata.boundary_profile:
            raise ValueError("Metric source window/boundary identity differs")
        window = windows[tuple(getattr(metric, n) for n in WINDOW_KEY)]
        for source_name, window_name in (
            ("requested_window_start_ns", "requested_window_start_ns"),
            ("requested_window_end_ns", "requested_window_end_ns"),
            ("right_endpoint_inclusive", "right_endpoint_inclusive"),
            ("requested_sample_count", "expected_sample_count"),
            ("resolved_frame_count", "resolved_sample_count"),
            ("missing_sample_count", "missing_sample_count"),
            ("coverage_fraction", "coverage_fraction"),
        ):
            value = row[source_name]
            if (value if type(value) is bool else publication_number(value)) != window[
                window_name
            ]:
                raise ValueError("Metric source physical window evidence differs")
        for source_name, window_name in (
            ("effective_window_start_ns", "effective_start_ns"),
            ("effective_window_end_ns", "effective_end_ns"),
        ):
            expected = window[window_name]
            if not isinstance(expected, Decimal):
                raise ValueError("Metric source effective window evidence differs")
            sign, digits, exponent = expected.as_tuple()
            assert isinstance(exponent, int)
            source_ps = float(Decimal((sign, digits, exponent + 3)))
            if row[source_name] != _effective_ns(source_ps):
                raise ValueError("Metric source effective window evidence differs")
        if publication_number(metric.metric_value) != publication_number(row[field]):
            raise ValueError("Metric value differs from authoritative numeric field")


def build_dataset_release_metrics(
    metrics: tuple[AuthoritativePublicationMetric, ...],
    fields: tuple[str, ...],
    *,
    workspace: Path,
    control: DatasetReleaseExportManifest,
    metadata_tables: DatasetReleaseMetadataTables,
    canonical_sources: tuple[tuple[FileEvidence, FixedWindowTable], ...],
) -> DatasetReleaseTable:
    validate_publication_metric_sources(
        metrics,
        fields,
        workspace=workspace,
        control=control,
        metadata=metadata_tables,
        canonical_sources=canonical_sources,
    )
    table = _metric_table(asdict(metric) for metric in metrics)
    validate_dataset_release_scientific_relationships((table,), metadata_tables)
    return table


@dataclass(frozen=True)
class DatasetSources:
    """Explicit runtime bindings to existing contracts; no new serialized schema.

    Full QC candidates and the selected scientific population are separate.
    Each physical source and selection is supplied, never discovered in a study
    catalog. A primary generic group binds the other layer groups by authority.
    """

    workspace: Path
    control_evidence: FileEvidence
    policy_evidence: FileEvidence
    handoffs: tuple[
        tuple[FileEvidence, ReplicaWindowInput, SystemAnnotations | None, str | None],
        ...,
    ]
    qc_evidence_files: tuple[FileEvidence, ...]
    qc_decision_files: tuple[FileEvidence, ...]
    metric_selections: tuple[tuple[MetricSourceSelection, ...], ...]
    group_files: tuple[FileEvidence, ...]
    canonical_sources: tuple[tuple[FileEvidence, FixedWindowTable], ...]
    annotated_sources: tuple[tuple[FileEvidence, FixedWindowTable], ...]
    fixed_qc_files: tuple[FileEvidence, ...]
    publication_input_evidence: FileEvidence

    def validate(
        self,
        *,
        preview: bool = False,
    ) -> tuple[
        DatasetReleaseExportManifest,
        DatasetReleaseMetadataTables,
        DatasetReleaseScientificTables,
    ]:
        from mania.scientific_qualification import consumption

        if type(preview) is not bool:
            raise ValueError("Preview admission requires an explicit boolean")
        with consumption(
            "exploratory" if preview else "custom", independent=not preview
        ):
            return self._validate()

    def _validate(
        self,
    ) -> tuple[
        DatasetReleaseExportManifest,
        DatasetReleaseMetadataTables,
        DatasetReleaseScientificTables,
    ]:
        from mania._dataset_qc_json import read_model
        from mania.dataset_hard_qc import verify_hard_measurement_sources
        from mania.dataset_measurement_review import validate_window_measurements
        from mania.dataset_qc_contract import QCDecisions, QCPolicy
        from mania.dataset_qc_evidence_io import read_replica_hard_qc_evidence
        from mania.dataset_review_qc import evaluate_dataset_review_qc
        from mania.handoff import load_completed_handoff
        from mania.replica_aggregation_contract import ReplicaGroup
        from mania.replica_aggregation_tables_io import read_replica_window_csv
        from mania.replica_protein_edge_aggregation import aggregate_windows
        from mania_napi2b.publication import (
            DatasetReleaseScientificTables,
            _fixed_qc_decisions,
            _Legacybuild_dataset_qc_summary,
            build_dataset_release_metadata_tables,
            build_dataset_release_qc_tables,
            project_fixed_science,
            project_generic_aggregate,
            read_fixed_decision_set,
            replica_key,
            validate_complete_tables,
        )
        from mania_napi2b.publication_io import (
            read_dataset_release_export_manifest,
            read_dataset_release_publication_inputs,
        )
        from mania_napi2b.tables import read_publication_csv

        root = self.workspace
        control = read_dataset_release_export_manifest(
            self.control_evidence.verify(root)
        )
        policy = read_model(self.policy_evidence.verify(root), QCPolicy, root=root)
        if policy.policy_id != "napi2b.dataset.v1":
            raise ValueError("Fixed release requires explicitly selected NaPi2b policy")
        expected_parameters = {
            "production_frame_coverage": 0.95,
            "protein_edge_empty_window_fraction": 0.01,
        }
        for check, value in expected_parameters.items():
            parameter = (
                "coverage_fraction"
                if check == "production_frame_coverage"
                else "empty_window_fraction"
            )
            if (
                check in policy.required_check_ids
                and getattr(policy, parameter) != value
            ):
                raise ValueError("Selected fixed QC threshold differs")
        if (
            any(c.startswith("mad:") for c in policy.required_check_ids)
            and policy.mad_multiplier != 3.0
        ):
            raise ValueError("Selected fixed raw MAD multiplier differs")
        evidence = tuple(
            read_replica_hard_qc_evidence(e.verify(root), root=root, policy=policy)
            for e in self.qc_evidence_files
        )
        decisions = tuple(
            read_model(e.verify(root), QCDecisions, root=root)
            for e in self.qc_decision_files
        )
        if not evidence or tuple(e.identity for e in evidence) != tuple(
            d.identity for d in decisions
        ):
            raise ValueError("QC evidence/decision full source roster differs")
        groups = tuple(
            read_model(e.verify(root), ReplicaGroup, root=root)
            for e in self.group_files
        )
        if len(groups) != 3 or tuple(g.layer for g in groups) != (
            "protein",
            "lipid",
            "glycan",
        ):
            raise ValueError("Exactly three declared layer groups are required")
        primary = groups[0]
        if self.group_files[0].path != control.qc_derived_manifest_path:
            raise ValueError("QC-derived primary manifest source differs")
        for descriptor in self.group_files[1:]:
            if not any(
                (a.role, a.path, a.sha256, a.source_identity)
                == (descriptor.role, descriptor.path, descriptor.sha256, None)
                for a in primary.authority
            ):
                raise ValueError(
                    "Primary QC-derived manifest lacks corresponding layer authority"
                )
        if (
            member(root, control.aggregation_manifest_used_path).read_bytes()
            != self.group_files[0].verify(root).read_bytes()
        ):
            raise ValueError(
                "Aggregation manifest used differs from QC-derived manifest"
            )
        inputs = tuple(item[1] for item in self.handoffs)
        if tuple(i.identity for i in inputs) != tuple(e.identity for e in evidence):
            raise ValueError("Scientific handoff/QC source population differs")
        for descriptor, inp, scope_annotations, rmsd_directory in self.handoffs:
            handoff = load_completed_handoff(
                root,
                descriptor.path,
                window_input=inp,
                selected_layers=("protein", "lipid", "glycan"),
                annotations=scope_annotations,
                rmsd_directory=rmsd_directory,
            )
            descriptor.verify(root)
            if handoff.technical_subset:
                raise ValueError("Technical handoff cannot qualify a fixed release")
        hard_results = []
        for e, inp in zip(evidence, inputs, strict=True):
            raw_records = [
                r
                for r in e.records
                if r.check_id
                in (
                    "topology_readable",
                    "trajectory_readable",
                    "topology_trajectory_atom_count",
                    "topology_trajectory_atom_order",
                )
                and r.state != "missing"
            ]
            raw_descriptor = None
            if raw_records:
                selected = [
                    a
                    for a in e.authority
                    if (a.role, a.sha256, a.source_identity)
                    == (
                        raw_records[0].evidence_role,
                        raw_records[0].evidence_sha256,
                        e.identity,
                    )
                ]
                if len(selected) != 1:
                    raise ValueError("Raw source authority is absent or ambiguous")
                path = member(root, selected[0].path)
                raw_descriptor = FileEvidence(
                    role=selected[0].role,
                    path=selected[0].path,
                    size_bytes=path.stat().st_size,
                    sha256=selected[0].sha256,
                )
            hard_results.append(
                verify_hard_measurement_sources(
                    e, source=inp, policy=policy, raw_integrity=raw_descriptor
                )
            )
        hard = tuple(hard_results)
        if len(self.metric_selections) != len(evidence):
            raise ValueError("QC source metric selections are incomplete")
        for e, inp, selections in zip(
            evidence, inputs, self.metric_selections, strict=True
        ):
            validate_window_measurements(
                e, policy=policy, source=inp, group=primary, selections=selections
            )
        review = evaluate_dataset_review_qc(
            evidence,
            policy=policy,
            group=primary,
            window_inputs=inputs,
            metric_selections=self.metric_selections,
            hard_evaluations=hard,
        )
        for e, d, h, r in zip(evidence, decisions, hard, review, strict=True):
            expected = tuple(
                sorted(
                    (*h, *r), key=lambda c: policy.required_check_ids.index(c.check_id)
                )
            )
            if len(d.records) != 1 or d.records[0].checks != expected:
                raise ValueError(
                    "Final QC decisions differ from source-bound scientific checks"
                )
            if d.records[0].release_decision == "pending_review":
                raise ValueError("Unresolved REVIEW forbids fixed release")
            if d.records[0].review_authority_sha256 is not None and not any(
                a.sha256 == d.records[0].review_authority_sha256
                and a.source_identity == e.identity
                for a in d.authority
            ):
                raise ValueError("Supplied external resolution authority differs")
        from mania.dataset_qc_contract import AssessmentAuthority

        for document in decisions:
            record = document.records[0]
            if record.review_authority_sha256 is not None:
                bound = [
                    a
                    for a in document.authority
                    if a.sha256 == record.review_authority_sha256
                    and a.source_identity == record.identity
                ]
                if len(bound) != 1:
                    raise ValueError(
                        "External reviewer authority must resolve uniquely"
                    )
                external = AssessmentAuthority.model_validate(
                    read_strict_json(member(root, bound[0].path))
                )
                if (external.reviewer, external.note) != (
                    record.reviewer,
                    record.review_note,
                ):
                    raise ValueError(
                        "External reviewer content differs from supplied resolution"
                    )
        fixed_qc = tuple(
            read_publication_csv(e.role, e.verify(root)) for e in self.fixed_qc_files
        )
        _fixed_qc_decisions(fixed_qc)
        authoritative_fixed = read_fixed_decision_set(
            member(root, control.decision_set_path)
        )
        projected_fixed = build_dataset_release_qc_tables(
            authoritative_fixed, _Legacybuild_dataset_qc_summary(authoritative_fixed)
        )
        if any(getattr(projected_fixed, t.table_id) != t for t in fixed_qc):
            raise ValueError(
                "Fixed decision-set lineage differs from reconstructed QC audit"
            )
        stage32 = _verify_upstream(root, control.stage32_run)
        stage31 = _verify_upstream(root, control.stage31_run)
        _require_run_member(stage32, "output", control.decision_set_path, None)
        _require_run_member(stage32, "output", control.qc_derived_manifest_path, None)
        for descriptor in (*self.qc_decision_files, *self.group_files):
            _require_run_member(stage32, "output", descriptor.path, descriptor.sha256)
        _require_run_member(
            stage31,
            "input",
            control.aggregation_manifest_used_path,
            self.group_files[0].sha256,
        )
        published = read_dataset_release_publication_inputs(
            self.publication_input_evidence.verify(root)
        )
        if self.publication_input_evidence.path != control.publication_inputs_path:
            raise ValueError("Publication input role/path differs")
        canonical_keys = []
        temporal = []
        fixed_annotations: list[DatasetSystemBiologicalAnnotations] = []
        for inp in inputs:
            t, replay = inp.read_back()
            temporal.append(t)
            if inp.temporal_evidence.path not in control.temporal_evidence_paths:
                raise ValueError(
                    "Physical source evidence not bound into release control"
                )
        for descriptor, table in self.canonical_sources:
            table.__post_init__()
            if descriptor.role != _CANONICAL_ROLES[
                table.generic.layer
            ] or descriptor.verify(root).read_bytes() != fixed_window_csv_bytes(table):
                raise ValueError("Bound completed fixed source table differs")
            key = replica_key(table.generic.mapping.identity)
            candidate = next(
                (i for i in inputs if i.identity == table.generic.mapping.identity),
                None,
            )
            if candidate is None:
                raise ValueError("Fixed source table has no scientific handoff")
            t, replay = candidate.read_back()
            if (
                table.generic != getattr(replay, "canonical_" + table.generic.layer)
                or table.temporal != t
            ):
                raise ValueError(
                    "Fixed source differs from source-exact handoff replay"
                )
            bindings = [
                b
                for b in control.canonical_bindings
                if b.family == table.generic.layer and b.path == descriptor.path
            ]
            if len(bindings) != 1 or bindings[0].replica_keys != (key,):
                raise ValueError(
                    "Fixed canonical source binding/replica coverage differs"
                )
            canonical_keys.append((key, table.generic.layer))
            tagged = [
                (e, t)
                for e, t in self.annotated_sources
                if t.generic == table.generic and t.temporal == table.temporal
            ]
            if (
                len(tagged) != 1
                or tagged[0][1].annotations is None
                or tagged[0][0].verify(root).read_bytes()
                != fixed_window_csv_bytes(tagged[0][1])
            ):
                raise ValueError("Completed fixed annotated source absent or differs")
            annotation_model = tagged[0][1].annotations
            assert annotation_model is not None
            if annotation_model not in fixed_annotations:
                fixed_annotations.append(annotation_model)
        if len(self.annotated_sources) != len(self.canonical_sources):
            raise ValueError("Fixed annotation family coverage differs")
        if len(canonical_keys) != len(set(canonical_keys)) or set(canonical_keys) != {
            (replica_key(i.identity), layer)
            for i in inputs
            for layer in ("protein", "lipid", "glycan")
        }:
            raise ValueError("Incomplete canonical source family/population coverage")
        if {(a.dataset_id, a.system_id) for a in fixed_annotations} != set(
            control.annotation_publication_system_keys
        ):
            raise ValueError("Annotation system selection differs")
        for annotation in fixed_annotations:
            binding = next(
                (
                    b
                    for b in control.annotation_bindings
                    if (b.dataset_id, b.system_id)
                    == (annotation.dataset_id, annotation.system_id)
                ),
                None,
            )
            if binding is None or _canonical(
                read_strict_json(member(root, binding.path))
            ) != _canonical(annotation.to_dict()):
                raise ValueError("Fixed annotation source authority differs")
        raw_publication = read_strict_json(self.publication_input_evidence.verify(root))
        contact_groups: dict[ReplicaKey, list[dict[str, Any]]] = {}
        for definition in raw_publication["contact_definitions"]:
            key = tuple(definition["replica_key"])
            if len(key) != 4:
                raise ValueError("Contact definition needs full replica identity")
            contact_groups.setdefault(key, []).append(definition)
        if not set(control.scientific_release_replica_keys) <= set(contact_groups):
            raise ValueError(
                "Eligible scientific replicas require complete contact definitions"
            )
        authority_contract = json.loads(_authority_bytes())
        for key, declared in contact_groups.items():
            selected_handoffs = [
                item for item in self.handoffs if replica_key(item[1].identity) == key
            ]
            if len(selected_handoffs) != 1:
                raise ValueError("Contact definition source replica differs")
            handoff = load_completed_handoff(
                root,
                selected_handoffs[0][0].path,
                window_input=selected_handoffs[0][1],
                selected_layers=("protein", "lipid", "glycan"),
                annotations=selected_handoffs[0][2],
                rmsd_directory=selected_handoffs[0][3],
            )
            run_path = handoff.completion.marker_path
            from mania.preprocessing.perframe_observations import (
                read_perframe_observations,
            )
            from mania.preprocessing.physical_time_execution import (
                PreprocessingTemporalExecution,
            )
            from mania.run_provenance_io import read_run_provenance

            temporal_binding, _ = selected_handoffs[0][1].read_back()
            observed = read_perframe_observations(
                root / selected_handoffs[0][1].observation_directory,
                PreprocessingTemporalExecution((temporal_binding,)),
            )
            recorded = read_strict_json(member(root, run_path))
            actual_options = observed.protein.condition_results[0].options.to_dict(
                include_contact_selection=True
            )
            if _canonical(
                recorded["resolved_configuration"]["contact_detection_options"]
            ) != _canonical(actual_options):
                raise ValueError(
                    "Contact provenance options differ from actual completed "
                    "observations"
                )
            _, count = _run_contact_configuration(root, run_path, key)
            if count != temporal_binding.sampling_plan.sampled_frame_count:
                raise ValueError(
                    "Contact provenance count differs from physical source roster"
                )
            protein = [
                v
                for v in declared
                if v["contact_layer"] == authority_contract["protein"]["contact_layer"]
            ]
            specialized = [v for v in declared if v not in protein]
            if (
                not protein
                or not specialized
                or len({v["source_artifact_path"] for v in protein}) != 1
                or len({v["source_artifact_path"] for v in specialized}) != 1
            ):
                raise ValueError(
                    "Incomplete deterministic protein/specialized definitions"
                )
            pbc = protein[0]["parameters"]["pbc_correction_status"]
            expected_definitions = build_dataset_release_contact_definitions(
                workspace=root,
                replica_key=key,
                edge_semantics_path=protein[0]["source_artifact_path"],
                run_provenance_path=run_path,
                pbc_correction_status=pbc,
                specialized_authority_path=specialized[0]["source_artifact_path"],
                partner_catalog_path=selected_handoffs[0][1].observation_directory
                + "/molecular_partner_catalog.json",
            )
            if _canonical(declared) != _canonical(
                [v.to_dict() for v in expected_definitions]
            ):
                raise ValueError(
                    "Contact definitions differ from deterministic source aut"
                    "hority/options/order"
                )
        for software_record in published.software_versions.records():
            if (
                software_record["source_artifact_role"] != "run_provenance"
                or type(software_record["source_artifact_path"]) is not str
            ):
                raise ValueError("Unsupported software authority role")
            source_run = read_run_provenance(
                member(root, software_record["source_artifact_path"])
            )
            if (
                software_record["component_name"],
                software_record["version"],
                software_record["run_id"],
            ) != (
                source_run.software_identity.distribution_name,
                source_run.software_identity.version,
                source_run.run_id,
            ):
                raise ValueError(
                    "Software version differs from actual bound run provenance"
                )
        metadata = build_dataset_release_metadata_tables(
            decisions=decisions,
            policy=policy,
            groups=groups,
            fixed_qc_tables=fixed_qc,
            scientific_release_replica_keys=control.scientific_release_replica_keys,
            temporal_evidence=tuple(temporal),
            annotation_metadata=tuple(fixed_annotations),
            contact_definitions=published.contact_definitions,
            software_version_records=published.software_versions.records(),
        )
        science_tables = []
        for layer in ("protein", "lipid", "glycan"):
            parts = [
                project_fixed_science(t, metadata)
                for _, t in self.canonical_sources
                if t.generic.layer == layer
            ]
            spec = parts[0].spec
            science_tables.append(
                DatasetReleaseTable(spec, tuple(r for part in parts for r in part.rows))
            )
        for group, aggregate_path in zip(
            groups,
            (
                control.protein_aggregate_path,
                control.lipid_aggregate_path,
                control.glycan_aggregate_path,
            ),
            strict=True,
        ):
            if aggregate_path is None:
                raise ValueError("Required aggregate family artifact absent")
            _require_run_member(stage31, "output", aggregate_path, None)
            saved = read_replica_window_csv(member(root, aggregate_path))
            chosen = tuple(
                i
                for i in inputs
                if next(
                    m for m in group.members if m.identity == i.identity
                ).availability
                == "available"
            )
            expected_aggregate = aggregate_windows(
                group, chosen, policy=policy, decisions=decisions, authority_root=root
            )
            if saved != expected_aggregate:
                raise ValueError(
                    "Aggregate values/available contributions differ from sou"
                    "rce authority"
                )
            science_tables.append(project_generic_aggregate(saved, group, metadata))
        science_tables.append(
            build_dataset_release_metrics(
                published.metrics,
                published.metric_source_value_fields,
                workspace=root,
                control=control,
                metadata_tables=metadata,
                canonical_sources=self.canonical_sources,
            )
        )
        science = DatasetReleaseScientificTables(*science_tables)
        validate_complete_tables(metadata, science)
        return control, metadata, science


def _verify_upstream(root: Path, run: ReleaseUpstreamRun) -> ArtifactInventory:
    from mania.artifact_inventory_io import read_artifact_inventory
    from mania.run_provenance_io import read_run_provenance

    provenance = read_run_provenance(member(root, run.provenance_path))
    qualification = getattr(provenance, "scientific_qualification", None)
    if qualification is not None:
        from mania.scientific_qualification import consume_provenance

        for scope in qualification.source_scopes:
            consume_provenance(member(root, run.provenance_path), scope.input_identity)
    inventory = read_artifact_inventory(member(root, run.inventory_path))
    if provenance.workflow == "mania.run":
        from dataclasses import replace

        from mania.result_readers import read_run_summary, validate_run_artifacts
        from mania.scientific_qualification import consume_provenance

        provenance_file = member(root, run.provenance_path)
        source_root = next(
            (
                p
                for p in provenance_file.parents
                if (p / "summary.json").is_file()
                and p / read_run_summary(p).provenance_path == provenance_file
            ),
            None,
        )
        if source_root is None:
            raise ValueError(
                "Controller upstream requires its complete source-bound root"
            )
        checked = validate_run_artifacts(source_root)
        for identity in checked.plan.input_identities:
            consume_provenance(provenance_file, identity)
        if source_root / checked.summary.inventory_path != member(
            root, run.inventory_path
        ):
            raise ValueError("Controller upstream inventory selector differs")
        if inventory.checksum_mode != "sha256" or provenance.status != "completed":
            raise ValueError("Controller upstream needs completed SHA256 ownership")
        mapped = {b.artifact_id: b.path for b in run.input_bindings}
        inputs = {e.artifact_id for e in inventory.artifacts if e.direction == "input"}
        if set(mapped) != inputs:
            raise ValueError(
                "Controller source inputs require exact explicit workspace bindings"
            )
        prefix = source_root.relative_to(root)
        entries = []
        for entry in inventory.artifacts:
            relative = (
                mapped[entry.artifact_id]
                if entry.direction == "input"
                else (prefix / entry.path).as_posix()
            )
            target = member(root, relative)
            if (
                target.stat().st_size,
                hashlib.sha256(target.read_bytes()).hexdigest(),
            ) != (entry.byte_size, entry.sha256):
                raise ValueError("Controller source workspace binding differs")
            entries.append(replace(entry, path=relative))
        return replace(
            inventory, inventory_path=run.inventory_path, artifacts=tuple(entries)
        )
    if (
        provenance.status != "completed"
        or (provenance.run_id, provenance.workflow)
        != (inventory.run_id, inventory.workflow)
        or inventory.checksum_mode != "sha256"
        or inventory.inventory_path != run.inventory_path
    ):
        raise ValueError("Upstream completed run/inventory identity differs")
    mapped = {b.artifact_id: b.path for b in run.input_bindings}
    for entry in inventory.artifacts:
        path = (
            mapped.get(entry.artifact_id, entry.path)
            if entry.direction == "input"
            else entry.path
        )
        target = member(root, path)
        if (target.stat().st_size, hashlib.sha256(target.read_bytes()).hexdigest()) != (
            entry.byte_size,
            entry.sha256,
        ):
            raise ValueError("Upstream missing/stale input/output SHA256 or size")
    expected = {
        (
            e.role,
            mapped.get(e.artifact_id, e.path) if e.direction == "input" else e.path,
        )
        for e in inventory.artifacts
    }
    actual = {(e.role, e.path) for e in provenance.artifact_references}
    if actual != expected or len(actual) != len(provenance.artifact_references):
        raise ValueError("Upstream inventory/provenance graph incomplete")
    return inventory


def _require_run_member(
    inventory: ArtifactInventory, direction: str, path: str, sha256: str | None
) -> None:
    entries = [
        e for e in inventory.artifacts if e.direction == direction and e.path == path
    ]
    if len(entries) != 1 or (sha256 is not None and entries[0].sha256 != sha256):
        raise ValueError(
            "Required QC/manifest/aggregation lineage link absent or stale"
        )
