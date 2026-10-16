"""Read-only generic handoff validation using a supplied provenance completion seal."""

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Self

if TYPE_CHECKING:
    from mania.biological_annotations import SystemAnnotations
    from mania.canonical_window_tables import SourceWindowTable
    from mania.replica_aggregation_manifest import ReplicaWindowInput

from pydantic import model_validator

from mania.canonical_reference import AuthorityBinding, Digest, InputIdentity, Text
from mania.canonical_reference import _StrictModel as StrictModel
from mania.input_binding import (
    FileEvidence,
    InputBinding,
    member,
    portable_path,
    read_input_binding,
    verify_authority,
)
from mania.preprocessing.molecular_partner_metadata_io import read_strict_json
from mania.run_provenance_io import read_run_provenance


class HandoffCompletion(StrictModel):
    marker_path: Text
    marker_sha256: Digest
    completed_roles: tuple[Text, ...]

    @model_validator(mode="after")
    def _roles(self) -> Self:
        portable_path(self.marker_path)
        if not self.completed_roles or len(set(self.completed_roles)) != len(
            self.completed_roles
        ):
            raise ValueError("Completion requires unique nonempty roles")
        return self


class HandoffManifest(StrictModel):
    schema_version: Literal["mania.handoff.v1"]
    kind: Literal["mania_handoff"]
    identity: InputIdentity
    binding: AuthorityBinding
    required_evidence: tuple[FileEvidence, ...]
    completion: HandoffCompletion
    technical_subset: bool
    source_operation: Text
    source_version: Text
    source_commit: str | None

    @model_validator(mode="after")
    def _complete(self) -> Self:
        import re

        roles = tuple(e.role for e in self.required_evidence)
        paths = tuple(e.path for e in self.required_evidence)
        if not roles or len(set(roles)) != len(roles) or len(set(paths)) != len(paths):
            raise ValueError("Handoff evidence roles and paths must be unique")
        if roles != self.completion.completed_roles:
            raise ValueError("Partial or reordered completion roles")
        if (
            self.completion.marker_path in (*paths, self.binding.path)
            or self.binding.path in paths
        ):
            raise ValueError("Cyclic or self-checksummed handoff")
        if self.binding.source_identity != self.identity:
            raise ValueError("Handoff input identity differs")
        if (
            self.source_commit is not None
            and re.fullmatch("[0-9a-f]{40}", self.source_commit) is None
        ):
            raise ValueError("Invalid source commit")
        return self


def load_completed_handoff(
    root: Path,
    path: str,
    *,
    window_input: "ReplicaWindowInput | None" = None,
    selected_layers: tuple[Literal["protein", "lipid", "glycan"], ...] | None = None,
    annotations: "SystemAnnotations | None" = None,
    rmsd_directory: str | None = None,
) -> HandoffManifest:
    """Verify an explicit handoff path and a complete existing provenance marker.

    Full evidence is read through retained scientific readers for an explicit
    supported scope. The existing typed input argument independently defines
    its required roles; completion lists never define scientific completeness.
    Successful read-back does not certify PBC or an external release decision.
    """
    target = member(root, path)
    handoff = HandoffManifest.model_validate_json(target.read_bytes())
    read_strict_json(target)
    if path in (
        handoff.binding.path,
        handoff.completion.marker_path,
        *(e.path for e in handoff.required_evidence),
    ):
        raise ValueError("Handoff cannot contain its own checksum")
    binding_path = verify_authority(root, handoff.binding, handoff.identity)
    binding = read_input_binding(binding_path, root=root)
    if binding.identity != handoff.identity:
        raise ValueError("Handoff/input identity mismatch")
    for evidence in handoff.required_evidence:
        evidence.verify(root)
    marker_path = verify_authority(
        root,
        AuthorityBinding(
            role="completion",
            path=handoff.completion.marker_path,
            sha256=handoff.completion.marker_sha256,
            source_identity=handoff.identity,
        ),
        handoff.identity,
    )
    from mania.scientific_qualification import consume_provenance

    consume_provenance(marker_path, handoff.identity)
    marker = read_run_provenance(marker_path)
    if (
        marker.status != "completed"
        or marker.workflow != handoff.source_operation
        or marker.software_identity.version != handoff.source_version
        or marker.software_identity.commit_sha != handoff.source_commit
    ):
        raise ValueError("Incomplete or conflicting completion provenance")
    expected = {(e.role, e.path) for e in handoff.required_evidence}
    expected.add((handoff.binding.role, handoff.binding.path))
    actual = [(e.role, e.path) for e in marker.artifact_references]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError("Stale or incomplete provenance dependency graph")
    if not handoff.technical_subset:
        _validate_scientific_scope(
            root,
            handoff,
            binding,
            marker.run_id,
            window_input=window_input,
            selected_layers=selected_layers,
            annotations=annotations,
            rmsd_directory=rmsd_directory,
        )
    return handoff


def read_handoff_inputs(path: Path, *, root: Path) -> InputBinding:
    return read_input_binding(path, root=root)


def _validate_scientific_scope(
    root: Path,
    handoff: HandoffManifest,
    binding: InputBinding,
    run_id: str,
    *,
    window_input: "ReplicaWindowInput | None",
    selected_layers: tuple[Literal["protein", "lipid", "glycan"], ...] | None,
    annotations: "SystemAnnotations | None",
    rmsd_directory: str | None,
) -> None:
    from mania.input_binding import PhysicalRequest

    if window_input is None:
        if selected_layers or rmsd_directory is None:
            raise ValueError(
                "Full scientific handoff requires explicit supported scope"
            )
        required = {e.role: e for e in handoff.required_evidence}
        for evidence in binding.files:
            if required.get(evidence.role) != evidence:
                raise ValueError("Mandatory RMSD input role/path differs")
        _validate_rmsd(root, handoff, required, rmsd_directory, None, binding=binding)
        if binding.preparation is not None:
            _validate_preparation(root, binding, required)
        _validate_inventory(root, handoff, run_id, required)
        return
    if not selected_layers:
        raise ValueError(
            "Full scientific window handoff requires explicit selected layers"
        )
    if len(set(selected_layers)) != len(selected_layers) or any(
        layer not in ("protein", "lipid", "glycan") for layer in selected_layers
    ):
        raise ValueError("Unsupported or duplicate scientific layer")
    if (
        window_input.root.resolve() != root.resolve()
        or window_input.identity != handoff.identity
    ):
        raise ValueError("Scientific scope root or source identity differs")
    required = {e.role: e for e in handoff.required_evidence}

    def require(evidence: FileEvidence) -> Path:
        if required.get(evidence.role) != evidence:
            raise ValueError(f"Mandatory scientific role/path differs: {evidence.role}")
        return evidence.verify(root)

    for evidence in (
        *binding.files,
        window_input.temporal_evidence,
        window_input.mapping_evidence,
        window_input.reference_evidence,
        *window_input.observation_evidence,
    ):
        require(evidence)
    if (
        binding.reference != window_input.reference.reference
        or binding.mapping_sha256 != window_input.mapping_evidence.sha256
    ):
        raise ValueError("Scientific reference/mapping binding differs")
    temporal, replay = window_input.read_back()
    request = binding.temporal_request
    if not isinstance(request, PhysicalRequest) or request.windows is None:
        raise ValueError("Window scope requires explicit physical window request")
    actual = temporal.dataset_spec.temporal
    if (
        request.production_start_ns,
        request.production_end_ns,
        request.frame_stride_ps,
        request.windows.length_ns,
        request.windows.step_ns,
        request.windows.overlap_percent,
        request.windows.boundary_profile,
    ) != (
        actual.production_start_ns,
        actual.production_end_ns,
        actual.frame_stride_ps,
        actual.window_length_ns,
        actual.window_step_ns,
        actual.overlap_percent,
        temporal.window_plan.boundary_profile,
    ):
        raise ValueError("Scientific physical request/window differs")
    # The retained completion reader checks every requested/resolved/missing row,
    # exact time and completed zero periods, not only rows with positive contacts.
    from mania.canonical_window_tables_io import read_reference_window_table
    from mania.preprocessing.perframe_observations import (
        PERFRAME_COMPLETION_FILENAME,
        PROTEIN_PERFRAME_PATH,
        SPECIALIZED_PERFRAME_FILES,
        read_perframe_observations,
    )
    from mania.preprocessing.physical_time_execution import (
        PreprocessingTemporalExecution,
    )
    from mania.preprocessing.protein_edge_window_table_io import (
        read_dataset_protein_edge_window_csv,
    )
    from mania.preprocessing.specialized_contact_window_tables_io import (
        read_protein_glycan_window_csv,
        read_protein_lipid_window_csv,
    )

    directory = window_input.observation_directory
    expected_paths = {
        "perframe_completion": directory + "/" + PERFRAME_COMPLETION_FILENAME,
        "contacts_perframe": directory + "/" + PROTEIN_PERFRAME_PATH,
    }
    if any(layer != "protein" for layer in selected_layers):
        expected_paths["molecular_partner_catalog"] = (
            directory + "/molecular_partner_catalog.json"
        )
        # C04 persists the pair together; both are scientific reader dependencies.
        expected_paths.update(
            {
                "protein_" + k + "_perframe": directory + "/" + v
                for k, v in SPECIALIZED_PERFRAME_FILES.items()
            }
        )
    for role, expected in expected_paths.items():
        if role not in required or required[role].path != expected:
            raise ValueError(f"Mandatory scientific role/path differs: {role}")
    saved = read_perframe_observations(
        root / directory, PreprocessingTemporalExecution((temporal,))
    )
    if (
        any(layer != "protein" for layer in selected_layers)
        and not saved.specialized.condition_results
    ):
        raise ValueError("Selected partner evidence is unavailable")
    readers: dict[str, Callable[[str | Path], SourceWindowTable]] = {
        "protein": read_dataset_protein_edge_window_csv,
        "lipid": read_protein_lipid_window_csv,
        "glycan": read_protein_glycan_window_csv,
    }
    for layer in selected_layers:
        source_role, reference_role = (
            layer + "_source_windows",
            layer + "_reference_windows",
        )
        if source_role not in required or reference_role not in required:
            raise ValueError("Mandatory scientific source/reference window role absent")
        source = readers[layer](required[source_role].verify(root))
        if source != getattr(replay, layer):
            raise ValueError("Scientific source windows differ from completed replay")
        projected = read_reference_window_table(
            required[reference_role].verify(root),
            source_table=source,
            mapping=window_input.mapping,
            reference=window_input.reference,
        )
        if projected != getattr(replay, "canonical_" + layer):
            raise ValueError("Scientific reference windows differ from source")
        if annotations is not None:
            from mania.annotated_window_tables_io import read_annotated_reference_table
            from mania.biological_annotations_io import read_system_annotations

            role = layer + "_annotated_windows"
            if "biological_annotations" not in required or role not in required:
                raise ValueError("Mandatory scientific annotation role absent")
            loaded = read_system_annotations(
                required["biological_annotations"].verify(root),
                reference=window_input.reference,
            )
            if loaded != annotations or loaded.identity != handoff.identity:
                raise ValueError("Scientific annotation identity/content differs")
            for authority in loaded.authority:
                verify_authority(root, authority, authority.source_identity)
            read_annotated_reference_table(
                required[role].verify(root),
                reference_table=projected,
                annotations=loaded,
                reference=window_input.reference,
            )
    if binding.preparation is not None:
        _validate_preparation(root, binding, required)
    if rmsd_directory is not None:
        _validate_rmsd(root, handoff, required, rmsd_directory, window_input)
    _validate_inventory(root, handoff, run_id, required)


def _validate_inventory(
    root: Path, handoff: HandoffManifest, run_id: str, required: dict[str, FileEvidence]
) -> None:
    from mania.artifact_inventory_io import read_artifact_inventory

    inventory_evidence = required.get("artifact_inventory")
    if inventory_evidence is None:
        raise ValueError("Mandatory scientific inventory role absent")
    inventory = read_artifact_inventory(inventory_evidence.verify(root))
    if (
        inventory.run_id,
        inventory.workflow,
        inventory.inventory_path,
        inventory.checksum_mode,
    ) != (
        run_id,
        handoff.source_operation,
        inventory_evidence.path,
        "sha256",
    ):
        raise ValueError("Scientific inventory/provenance identity differs")
    leaves = {
        (e.role, e.path, e.size_bytes, e.sha256)
        for e in handoff.required_evidence
        if e.role != "artifact_inventory"
    }
    binding_path = verify_authority(root, handoff.binding, handoff.identity)
    leaves.add(
        (
            handoff.binding.role,
            handoff.binding.path,
            binding_path.stat().st_size,
            handoff.binding.sha256,
        )
    )
    if {
        (e.role, e.path, e.byte_size, e.sha256) for e in inventory.artifacts
    } != leaves or len(inventory.artifacts) != len(leaves):
        raise ValueError("Scientific inventory has incomplete or stale bound leaves")


def _validate_preparation(
    root: Path, binding: InputBinding, required: dict[str, FileEvidence]
) -> None:
    from mania.preprocessing.protein_integrity_observations import (
        read_protein_integrity,
        validate_protein_integrity,
    )

    for role in (
        "protein_integrity_observations",
        "preparation_report",
        "frame_evidence",
    ):
        if role not in required:
            raise ValueError(
                "Preparation requires complete documentary integrity evidence"
            )
    integrity = read_protein_integrity(
        required["protein_integrity_observations"].verify(root)
    )
    old = integrity.dataset_identity
    if (
        old.dataset_id,
        old.system_id,
        old.trajectory_id,
        old.replica_id,
        old.engine,
        old.condition,
        old.variant_id,
        old.disulfide_state,
    ) != (
        binding.identity.project,
        binding.identity.system_id,
        binding.identity.trajectory_id,
        binding.identity.replica_id,
        binding.identity.engine,
        binding.identity.condition,
        binding.identity.variant_id,
        binding.identity.disulfide_state,
    ):
        raise ValueError("Integrity source identity differs")
    files = {f.role: f for f in binding.files}
    for role, source in integrity.source_bindings.items():
        evidence = files.get(role)
        if evidence is None or (source.sha256, source.byte_size) != (
            evidence.sha256,
            evidence.size_bytes,
        ):
            raise ValueError("Integrity coordinate provenance differs")
    validate_protein_integrity(
        integrity,
        required["preparation_report"].verify(root),
        required["frame_evidence"].verify(root),
    )
    if (
        any(f.bond_representation_max_error_A is None for f in integrity.observations)
        and integrity.protein_remains_broken is None
    ):
        raise ValueError(
            "Preparation handoff needs all-frame bonded observations or expli"
            "cit assessment"
        )
    # This verifies documentary observations, never scientific PBC suitability.


def _validate_rmsd(
    root: Path,
    handoff: HandoffManifest,
    required: dict[str, FileEvidence],
    directory: str,
    window_input: "ReplicaWindowInput | None",
    *,
    binding: InputBinding | None = None,
) -> None:
    from mania.preprocessing.trajectory_rmsd_io import read_rmsd_measurement

    portable_path(directory)
    for role, name in (
        ("rmsd_measurement", "rmsd_measurement.json"),
        ("rmsd_timeseries", "rmsd_timeseries.csv"),
    ):
        if role not in required or required[role].path != directory + "/" + name:
            raise ValueError("Mandatory RMSD role/path differs")
    measurement = read_rmsd_measurement(
        required["rmsd_measurement"].verify(root).parent
    )
    if measurement.identity != handoff.identity:
        raise ValueError("RMSD source identity differs")
    for authority in measurement.authority:
        verify_authority(root, authority, authority.source_identity)
    if isinstance(measurement.reference_source, AuthorityBinding):
        verify_authority(
            root,
            measurement.reference_source,
            measurement.reference_source.source_identity,
        )
    if window_input is None:
        from mania.input_binding import FrameRequest

        if (
            binding is None
            or not isinstance(binding.temporal_request, FrameRequest)
            or measurement.sampling_kind != "frame"
        ):
            raise ValueError(
                "Standalone full RMSD needs an explicit retained frame request"
            )
        request = binding.temporal_request
        if request.indexes is not None:
            expected = request.indexes
        elif request.stop is not None:
            expected = tuple(range(request.start, request.stop, request.stride))
            if request.max_frames is not None:
                expected = expected[: request.max_frames]
        else:
            raise ValueError(
                "Full frame RMSD lacks authoritative finite requested population"
            )
        if tuple(r.requested_sample_index for r in measurement.rows) != tuple(
            range(len(expected))
        ):
            raise ValueError("Standalone RMSD requested frame roster incomplete")
        for requested, row in zip(expected, measurement.rows, strict=True):
            if row.state == "resolved" and row.source_frame_index != requested:
                raise ValueError(
                    "Standalone RMSD requested/source frame identity differs"
                )
        return
    if measurement.sampling_kind != "physical":
        raise ValueError("RMSD source/sampling identity differs")
    temporal, _ = window_input.read_back()
    selected = {
        s.requested_sample_index: s for s in temporal.sampling_plan.selected_samples
    }
    missing = {
        s.requested_sample_index: s for s in temporal.sampling_plan.missing_samples
    }
    if tuple(r.requested_sample_index for r in measurement.rows) != tuple(
        range(temporal.sampling_plan.requested_sample_count)
    ):
        raise ValueError("RMSD requested frame roster incomplete")
    for row in measurement.rows:
        sample = selected.get(row.requested_sample_index)
        if sample is None:
            if (
                row.state != "missing"
                or row.requested_time_ps
                != missing[row.requested_sample_index].requested_time_ps
            ):
                raise ValueError("RMSD missing frame/time identity differs")
        elif (
            row.state,
            row.requested_time_ps,
            row.source_frame_index,
            row.actual_time_ps,
            row.time_delta_ps,
        ) != (
            "resolved",
            sample.requested_time_ps,
            sample.source_frame_index,
            sample.actual_time_ps,
            sample.time_delta_ps,
        ):
            raise ValueError("RMSD source frame/time identity differs")
    for atom in (*measurement.fit_atoms, *measurement.evaluation_atoms):
        matches = [
            r
            for r in window_input.mapping.records
            if (
                r.source.engine,
                r.source.chain_id,
                r.source.segment_id,
                r.source.resid,
                r.source.insertion_code,
                r.source.resname,
            )
            == (
                atom.engine,
                atom.chain_id,
                atom.segment_id,
                atom.resid,
                atom.insertion_code,
                atom.resname,
            )
        ]
        if len(matches) != 1 or matches[0].mapping_status != "mapped":
            raise ValueError("RMSD selection source/mapping identity differs")
