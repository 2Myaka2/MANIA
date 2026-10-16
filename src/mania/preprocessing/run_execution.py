"""C06 execution adapters; numerical work remains in retained scientific APIs."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal, cast

from mania.input_binding import (
    FrameRequest,
    InputBinding,
    PhysicalRequest,
    verify_authority,
)
from mania.method_status import (
    EligibilityObservation,
    MethodStatus,
    RgEffectiveParameters,
    RgEligibility,
)
from mania.preprocessing.trajectory_runtime import (
    PreprocessingConditionLoadResult,
    PreprocessingConditionRuntimeInput,
)
from mania.run_config import QC, RMSD, RunConfig, RunPreflightError, System


@dataclass
class InputExecution:
    """Actual source objects and paths, never a success inferred from filenames."""

    system: System
    statuses: list[MethodStatus]
    values: dict[str, Any] = field(default_factory=dict)
    artifacts: list[tuple[str, Path, str | None]] = field(default_factory=list)
    observed_frames: list[tuple[int, float | None]] = field(default_factory=list)
    source_frame_count: int | None = None


def validate_authorities(config: RunConfig) -> None:
    """Read closed authorities; defer large coordinate/hash work to execution."""
    from mania.biological_annotations_io import read_system_annotations
    from mania.canonical_reference_io import read_protein_reference
    from mania.canonical_residue_mapping_io import read_residue_mapping
    from mania.preprocessing.molecular_partner_metadata_io import (
        read_molecular_partner_metadata,
        read_strict_json,
    )
    from mania.run_config import merge_methods

    try:
        verify_input_checksum_manifest(config, execution=False)
        for system in config.systems:
            options = merge_methods(config, system)
            if system.method_overrides is not None and any(
                getattr(system.method_overrides, name) is not None
                for name in ("comparison", "replica_aggregation", "profile_outputs")
            ):
                raise RunPreflightError(
                    "Grouped methods require an explicit root request and group "
                    "authority; per-input scientific options cannot determine "
                    "a group scope"
                )
            rmsd = options.get("rmsd")
            if (
                isinstance(rmsd, RMSD)
                and rmsd.enabled
                and rmsd.fit_selection != "legacy_mapped_ca"
            ):
                authority_root = (
                    system.input_binding_path.parent
                    if system.input_binding_path
                    else config._config_path.parent
                    if config._config_path
                    else Path.cwd()
                )
                if any(
                    not path.is_relative_to(authority_root)
                    for path in (system.topology, *system.trajectories)
                ):
                    raise RunPreflightError(
                        "RMSD source files require a shared explicit "
                        "configuration/input-binding authority root"
                    )
            if (
                isinstance(rmsd, RMSD)
                and rmsd.enabled
                and rmsd.reference is not None
                and rmsd.reference.kind == "external"
            ):
                from mania.result_readers import read_external_inputs

                _, pairing = read_external_inputs(system, rmsd, verify=False)
                if pairing.identity != system.identity(config.project):
                    raise ValueError("External atom mapping input identity differs")
                if any(
                    not p.is_relative_to(authority_root)
                    for p in (
                        cast(Path, rmsd.reference.path),
                        cast(Path, rmsd.reference.atom_mapping_path),
                    )
                ):
                    raise ValueError(
                        "External RMSD documents require the declared "
                        "shared authority root"
                    )
            if system.namd_authority:
                from mania.preprocessing.namd_authority import (
                    ElementControl,
                    TimeControl,
                    read_control,
                )

                read_control(system.namd_authority.elements_path, ElementControl)
                read_control(system.namd_authority.time_path, TimeControl)
            qc = options.get("qc")
            if (
                isinstance(qc, QC)
                and qc.enabled
                and qc.evidence_manifest_path is not None
            ):
                from mania.result_readers import read_qc_source_bindings

                bundle = read_qc_source_bindings(
                    qc.evidence_manifest_path, policy_path=qc.policy_path, verify=False
                )
                if system.identity(config.project) not in tuple(
                    m.identity for m in bundle.members
                ):
                    raise ValueError(
                        "QC bindings lack this explicitly requested identity"
                    )
            legacy = (
                isinstance(rmsd, RMSD)
                and rmsd.enabled
                and rmsd.fit_selection == "legacy_mapped_ca"
                and rmsd.evaluation_selection == "legacy_mapped_ca"
            )
            if legacy:
                validate_legacy_prerequisites(config, system, cast(RMSD, rmsd))
            ref = (
                read_protein_reference(system.reference.reference_path)
                if system.reference and not legacy
                else None
            )
            mapping = None
            if system.mapping_path and not legacy:
                if ref is None:
                    raise ValueError("Mapping requires a supplied reference")
                mapping = read_residue_mapping(system.mapping_path, reference=ref)
                if mapping.identity != system.identity(config.project):
                    raise ValueError("Mapping input identity differs")
                for authority in mapping.authority:
                    verify_authority(
                        system.input_binding_path.parent
                        if system.input_binding_path
                        else system.mapping_path.parent,
                        authority,
                        authority.source_identity,
                    )
            annotations = [
                system.annotations_path,
                getattr(
                    merge_methods(config, system).get("region_enrichment"),
                    "annotations_path",
                    None,
                ),
            ]
            for path in set(p for p in annotations if p is not None):
                if ref is None or mapping is None:
                    raise ValueError("Annotations require reference and mapping")
                table = read_system_annotations(path, reference=ref)
                if table.identity != system.identity(config.project):
                    raise ValueError("Annotation input identity differs")
                for authority in table.authority:
                    verify_authority(path.parent, authority, authority.source_identity)
            if system.partners_path:
                read_molecular_partner_metadata(system.partners_path)
            if system.input_binding_path:
                read_strict_json(system.input_binding_path)
                binding = InputBinding.model_validate_json(
                    system.input_binding_path.read_bytes()
                )
                if binding.identity != system.identity(config.project):
                    raise ValueError("Input binding identity differs")
                request = (
                    PhysicalRequest(**system.physical_time.model_dump())
                    if system.physical_time
                    else FrameRequest(**system.frames.model_dump())
                )
                if binding.temporal_request != request:
                    raise ValueError("Input binding temporal request differs")
                # Header-only planning must not stream large trajectory hashes.
                for evidence in binding.files:
                    path = binding_path(system.input_binding_path.parent, evidence.path)
                    if path.stat().st_size != evidence.size_bytes:
                        raise ValueError("Bound source size differs")
            if system.pbc.mode == "prepared" and not system.input_binding_path:
                raise ValueError(
                    "Prepared coordinates require source/atom/frame-bound "
                    "input_binding_path"
                )
        if (
            config.methods.profile_outputs is not None
            and config.methods.profile_outputs.enabled
        ):
            choice = next(
                (c for c in config.extensions if c.profile == "napi2b.dataset.v1"), None
            )
            if (
                choice is None
                or choice.options.qc_manifest_path is None
                or choice.options.release_input_manifest_path is None
            ):
                raise RunPreflightError(
                    "Selected profile outputs require both explicitly bound manifests"
                )
            active = selected_run_profile(choice)
            active.bindings_reader(
                choice.options.qc_manifest_path,
                release_path=choice.options.release_input_manifest_path,
                verify=False,
            )
        for comparison in config.comparisons:
            from mania.analysis.static_rin_comparison import read_static_rin_matching

            matching, _, _ = read_static_rin_matching(
                comparison.matching_path, verify_science=False
            )
            expected = tuple(
                next(
                    s.identity(config.project)
                    for s in config.systems
                    if (s.id, s.trajectory_id, s.replica_id)
                    == (m.system_id, m.trajectory_id, m.replica_id)
                )
                for m in comparison.members
            )
            if (
                tuple(m.identity for m in matching.members) != expected
                or matching.comparison_id != comparison.id
            ):
                raise ValueError(
                    "Comparison configuration and bound ordered members differ"
                )
    except (OSError, ValueError) as exc:
        raise RunPreflightError(f"Scientific authority: {exc}") from exc


def binding_path(root: Path, path: str) -> Path:
    from mania.input_binding import portable_path
    from mania.output_paths import require_input_file

    portable_path(path)
    target = require_input_file(root / path)
    if not target.is_relative_to(root):
        raise ValueError("Authority escapes declared root")
    return target


class _TrajectoryGuard:
    def __init__(
        self, runtime: Any, system: System, cancel: Callable[[], None]
    ) -> None:
        self.runtime, self.system, self.cancel = runtime, system, cancel

    def __iter__(self) -> Iterator[Any]:
        for timestep in self.runtime.trajectory:
            self.check(timestep)
            yield timestep

    def __len__(self) -> int:
        return len(self.runtime.trajectory)

    def __getitem__(self, index: int) -> Any:
        timestep = self.runtime.trajectory[index]
        self.check(timestep)
        return timestep

    def check(self, timestep: Any) -> None:
        self.cancel()
        if self.system.pbc.mode == "nonperiodic":
            dimensions = timestep.dimensions
            if dimensions is not None and any(float(v) != 0.0 for v in dimensions[:3]):
                raise ValueError("Unit cell contradicts explicit nonperiodicity")


class _RuntimeGuard:
    def __init__(
        self, runtime: Any, system: System, cancel: Callable[[], None]
    ) -> None:
        self._runtime = runtime
        self.trajectory: Any = _TrajectoryGuard(runtime, system, cancel)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._runtime, name)


def load_runtime(
    system: System,
    cancel: Callable[[], None],
    *,
    execution_condition: str | None = None,
) -> PreprocessingConditionLoadResult:
    from mania.preprocessing.namd_runtime import NAMDControlPaths
    from mania.preprocessing.trajectory_loader import load_single_condition_runtime

    if importlib.util.find_spec("MDAnalysis") is None:
        raise RunPreflightError(
            "Trajectory execution requires the optional MDAnalysis dependency"
        )
    control = (
        NAMDControlPaths(
            system.namd_authority.elements_path, system.namd_authority.time_path
        )
        if system.namd_authority
        else None
    )
    result = load_single_condition_runtime(
        PreprocessingConditionRuntimeInput(
            condition_name=execution_condition or system.condition or system.id,
            topology_path=system.topology,
            trajectory_paths=system.trajectories,
        ),
        namd_authority=control,
    )
    if not result.passed or result.runtime is None:
        raise RunPreflightError(
            "Trajectory load failed: " + "; ".join(i.message for i in result.issues)
        )
    if system.input_binding_path:
        from mania.input_binding import read_input_binding

        binding = read_input_binding(
            system.input_binding_path, root=system.input_binding_path.parent
        )
        if system.pbc.mode == "prepared":
            prep = binding.preparation
            if (
                prep is None
                or prep.mode != "prepared"
                or not prep.atom_order_preserved
                or not prep.frame_order_preserved
            ):
                raise RunPreflightError(
                    "Prepared coordinate atom/frame provenance is unestablished"
                )
            bound = {f.role: f for f in binding.files}
            if (
                bound["prepared_trajectory"].verify(system.input_binding_path.parent)
                not in system.trajectories
                or bound["preparation_evidence"].verify(
                    system.input_binding_path.parent
                )
                != system.pbc.preparation_evidence_path
            ):
                raise RunPreflightError(
                    "Prepared coordinate evidence differs from selected inputs"
                )
    return replace(
        result,
        runtime=replace(
            result.runtime,
            runtime_object=_RuntimeGuard(result.runtime.runtime_object, system, cancel),
        ),
    )


def atom_keys(group: Any, engine: Literal["gromacs", "namd"]) -> tuple[Any, ...]:
    from mania.preprocessing.trajectory_rmsd import SourceAtomKey

    def optional(atom: Any, name: str) -> str | None:
        try:
            value = getattr(atom, name)
        except (AttributeError, ValueError):
            return None
        return str(value) if value not in (None, "") else None

    return tuple(
        SourceAtomKey(
            engine=engine,
            chain_id=optional(a, "chainID"),
            segment_id=optional(a, "segid"),
            resid=str(a.resid),
            insertion_code=optional(a, "icode"),
            resname=str(a.resname),
            atom_name=str(a.name),
            element=str(a.element),
            atom_index=int(a.index),
            altloc=optional(a, "altLoc"),
        )
        for a in group
    )


def resolve_rg(
    runtime: Any, system: System, parameters: RgEffectiveParameters
) -> tuple[Any, RgEffectiveParameters]:
    np = importlib.import_module("numpy")

    group = runtime.select_atoms(parameters.selection)
    automatic = parameters.selection_origin == "automatic_protein"
    selection_ok = len(group) > 0
    if automatic:
        # Supported TPR molecular roster is explicit topology evidence. Do not
        # infer completeness or intended molecular identity from residue names.
        try:
            molnums = set(int(v) for v in group.molnums)
            selection_ok = len(molnums) == 1 and set(
                int(v)
                for v in runtime.atoms.indices[
                    runtime.atoms.molnums == next(iter(molnums))
                ]
            ) == set(int(v) for v in group.indices)
        except (AttributeError, ValueError, StopIteration):
            selection_ok = False
    try:
        masses = group.masses
        mass_attr = next(a for a in runtime._topology.attrs if a.attrname == "masses")
        masses_ok = (
            not bool(mass_attr.is_guessed)
            and bool(np.isfinite(masses).all())
            and bool((masses > 0).all())
            and bool(np.isfinite(group.positions).all())
        )
    except (AttributeError, ValueError, StopIteration):
        masses_ok = False
    # Preparation integrity alone cannot prove a complete unbroken protein.
    pbc_ok = system.pbc.mode == "nonperiodic"
    if pbc_ok:
        dimensions = runtime.trajectory[0].dimensions
        pbc_ok = dimensions is None or all(float(v) == 0.0 for v in dimensions[:3])

    def observation(
        ok: bool, reason: str, roles: tuple[str, ...]
    ) -> EligibilityObservation:
        return EligibilityObservation(
            state="established" if ok else "unestablished",
            reason_code=None if ok else reason,
            evidence_roles=roles,
        )

    try:
        roster_digest = hashlib.sha256(
            json.dumps(
                [k.to_dict() for k in atom_keys(group, system.engine)],
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
    except (AttributeError, ValueError):
        roster_digest = None
        selection_ok = False
    resolved = parameters.model_copy(
        update={
            "resolved_atom_count": len(group),
            "atom_identity_sha256": roster_digest,
            "eligibility": RgEligibility(
                protein_selection=observation(
                    selection_ok,
                    "complete_protein_identity_unestablished",
                    ("topology",),
                ),
                masses_and_input=observation(
                    masses_ok,
                    "authoritative_masses_or_input_unestablished",
                    ("topology", "trajectory"),
                ),
                pbc_suitability=observation(
                    pbc_ok,
                    "protein_pbc_suitability_unestablished",
                    ("pbc_declaration",),
                ),
            ),
        }
    )
    return group, resolved


def write_source_rows(
    path: Path,
    columns: tuple[str, ...],
    rows: Any,
    formatter: Callable[[object], object],
) -> None:
    """Relocate retained serialized rows without changing scientific labels."""
    from mania.preprocessing.trajectory_protein_contact_export import _write_csv

    _write_csv(
        path,
        columns,
        [{k: formatter(v) for k, v in row.to_dict().items()} for row in rows],
    )


def execute_contacts(
    execution: InputExecution,
    loaded: PreprocessingConditionLoadResult,
    options: Any,
    directory: Path,
    retain: bool,
    progress: Callable[[Any], None] | None,
) -> None:
    from mania.preprocessing.trajectory_contacts import (
        PreprocessingContactDetectionOptions,
        compute_condition_contacts,
    )
    from mania.preprocessing.trajectory_frame_sampling import (
        PreprocessingFrameSamplingOptions,
    )
    from mania.preprocessing.trajectory_preprocessing_manifests import (
        build_edge_semantics_manifest,
    )
    from mania.preprocessing.trajectory_protein_contact_export import (
        PROTEIN_CONTACT_EDGE_COLUMNS,
        PROTEIN_CONTACT_PERFRAME_COLUMNS,
        _artifact_rows,
        _write_csv,
    )
    from mania.preprocessing.trajectory_rmsd_io import atomic_json

    system = execution.system
    frame_options = system.frames
    indexes = execution.values.get("selected_indexes", frame_options.indexes)
    sampling = (
        None
        if indexes is not None
        else PreprocessingFrameSamplingOptions(
            frame_start=frame_options.start,
            frame_stop=frame_options.stop,
            frame_stride=frame_options.stride,
            max_frames=frame_options.max_frames,
        )
    )

    def observed(condition: str, index: int, time_ps: float | None) -> None:
        execution.observed_frames.append((index, time_ps))

    result = compute_condition_contacts(
        loaded,
        options=PreprocessingContactDetectionOptions(
            cutoff_distance=options.cutoff_distance,
            distance_unit=options.distance_unit,
            atom_filter=options.atom_filter,
            contact_selection=options.selection,
            skip_resnames=options.skip_resnames,
        ),
        frame_sampling=sampling,
        source_frame_indexes=indexes,
        selected_frame_observer=observed,
        progress_callback=progress,
    )
    execution.values["contact_options"] = options
    execution.values["contacts"] = result
    edge_rows, frame_rows = _artifact_rows(result)
    if options.min_frequency:
        from mania.preprocessing.trajectory_contact_accumulator import (
            InteractionAccumulator,
        )

        accumulator = InteractionAccumulator()
        for row in frame_rows:
            accumulator.add(
                condition_name=result.condition_name,
                frame_index=cast(int, row["frame_index"]),
                resid_i=cast(int, row["residue_index_i"]),
                resid_j=cast(int, row["residue_index_j"]),
                edge_type=cast(str, row["edge_type"]),
                distance_A=cast(float, row["distance_A"]),
            )
        accepted = {
            (a.resid_i, a.resid_j, a.edge_type)
            for a in accumulator.finalize(
                frame_count=result.frame_count, min_frequency=options.min_frequency
            )
        }
        edge_rows = [
            row
            for row in edge_rows
            if (row["residue_index_i"], row["residue_index_j"], row["edge_type"])
            in accepted
        ]
    from mania.preprocessing.trajectory_contacts_export import (
        _write_contact_pair_aggregates_csv,
    )

    aggregate = _write_contact_pair_aggregates_csv(
        result, directory / "contact_edges.csv", include_failed_frames=True
    )
    if aggregate.passed:
        execution.artifacts.append(
            ("contact_edges", directory / "contact_edges.csv", None)
        )
    _write_csv(
        directory / "protein_contact_edges.csv", PROTEIN_CONTACT_EDGE_COLUMNS, edge_rows
    )
    execution.artifacts.append(
        ("protein_contact_edges", directory / "protein_contact_edges.csv", None)
    )
    if retain:
        _write_csv(
            directory / "protein_contacts_perframe.csv",
            PROTEIN_CONTACT_PERFRAME_COLUMNS,
            frame_rows,
        )
        execution.artifacts.append(
            (
                "protein_contacts_perframe",
                directory / "protein_contacts_perframe.csv",
                None,
            )
        )
    atomic_json(directory / "edge_semantics.json", build_edge_semantics_manifest())
    execution.artifacts.append(
        ("edge_semantics", directory / "edge_semantics.json", None)
    )
    if not result.passed or not result.frame_results:
        raise ValueError(
            "Contact execution failed or selected no source frames: "
            + "; ".join(i.message for i in result.issues)
        )


def execute_analysis(
    execution: InputExecution,
    method: str,
    options: Any,
    preprocessing: Path,
    analysis: Path,
    token: str,
) -> None:
    from mania.analysis import (
        conformation_clustering,
        conformation_pca,
        contact_fingerprints,
        temporal,
        temporal_rin_metrics,
        temporal_rin_windows,
    )
    from mania.analysis import static_rin_communities as communities_api
    from mania.analysis import static_rin_graph as graph_api
    from mania.analysis import static_rin_metrics as metrics_api

    condition = execution.values["execution_condition"]
    values = execution.values
    result: Any
    if method == "static_rin":
        from mania.preprocessing.trajectory_graph_export import (
            build_preprocessing_graph_export_mapping,
        )
        from mania.preprocessing.trajectory_residue_table_export import (
            _write_residue_table,
        )

        mapping = build_preprocessing_graph_export_mapping(values["contacts"])
        if not mapping.passed:
            raise ValueError(
                "Retained static RIN input mapping failed: "
                + "; ".join(i.message for i in mapping.issues)
            )
        _write_residue_table(preprocessing / "residue_table.csv", list(mapping.nodes))
        execution.artifacts.append(
            ("residue_table", preprocessing / "residue_table.csv", None)
        )
        authority = execution.values["published_preprocessing"]
        graph = graph_api.build_static_rin_graph(
            preprocessing / "residue_table.csv",
            authority / "protein_contact_edges.csv",
            edge_semantics_path=authority / "edge_semantics.json",
        )
        values[method] = graph
        graph_api.write_static_rin_graph_json(graph, analysis / "graph.json")
        metrics = metrics_api.compute_static_rin_metrics(graph)
        values["centrality"] = metrics
        path = analysis / f"centrality_{token}.csv"
        write_source_rows(
            path,
            metrics_api.STATIC_RIN_METRICS_COLUMNS,
            metrics.node_metrics,
            metrics_api._csv_value,
        )
        execution.artifacts.extend(
            (
                (
                    "static_rin_graph",
                    analysis / "graph.json",
                    graph_api.STATIC_RIN_GRAPH_SCHEMA_VERSION,
                ),
                ("centrality", path, None),
            )
        )
    elif method == "communities":
        result = communities_api.compute_static_rin_communities(values["static_rin"])
        values[method] = result
        path = analysis / f"communities_{token}.csv"
        write_source_rows(
            path,
            communities_api.STATIC_RIN_COMMUNITIES_COLUMNS,
            result.assignments,
            communities_api._csv_value,
        )
        execution.artifacts.append((method, path, None))
    else:
        if "temporal_input" not in values:
            selected = next(
                (
                    s.effective_parameters
                    for s in execution.statuses
                    if s.method_id == "temporal_rin" and s.status != "not_requested"
                ),
                None,
            )
            config = temporal.TemporalRinConfig(
                window_size=getattr(selected, "window_size", 10),
                step_size=getattr(selected, "step_size", 10),
                min_frequency=getattr(selected, "min_frequency", 0.25),
            )
            values["temporal_input"] = temporal.load_temporal_rin_input(
                preprocessing / "protein_contacts_perframe.csv",
                condition=condition,
                config=config,
            )
        if method == "temporal_rin":
            result = temporal_rin_metrics.compute_temporal_rin_metrics(
                temporal_rin_windows.build_temporal_rin_window_graphs(
                    values["temporal_input"]
                )
            )
            path = analysis / f"temporal_rin_{token}.csv"
            write_source_rows(
                path,
                temporal_rin_metrics.TEMPORAL_RIN_METRICS_COLUMNS,
                result.windows,
                temporal_rin_metrics._csv_value,
            )
        elif method == "fingerprints":
            values[method] = contact_fingerprints.build_contact_fingerprint_matrix(
                values["temporal_input"]
            )
            return
        elif method == "pca":
            result = conformation_pca.build_conformation_pca_projection(
                values["fingerprints"],
                enable_pca=True,
                max_pca_components=options.max_components,
            )
            path = analysis / f"conformation_pca_{token}.csv"
            write_source_rows(
                path,
                conformation_pca.CONFORMATION_PCA_COLUMNS,
                result.rows,
                conformation_pca._csv_value,
            )
        elif method == "clustering":
            result = conformation_clustering.build_conformation_clusters(
                values["fingerprints"],
                clustering_basis=options.basis,
                pca_projection=values.get("pca"),
                pca_components_for_clustering=options.pca_components,
                config=conformation_clustering.ConformationClusteringConfig(
                    max_k=options.max_k, max_iterations=options.max_iterations
                ),
            )
            path = analysis / f"conformation_labels_{token}.csv"
            write_source_rows(
                path,
                conformation_clustering.CONFORMATION_LABELS_COLUMNS,
                result.rows,
                conformation_clustering._csv_value,
            )
        else:
            raise ValueError(f"Method requires its own retained adapter: {method}")
        values[method] = result
        execution.artifacts.append((method, path, None))


def prepare_sampling(
    execution: InputExecution, loaded: PreprocessingConditionLoadResult
) -> None:
    from mania.dataset_identity import (
        DatasetTemporalParameters,
        DatasetTrajectoryIdentity,
        DatasetTrajectorySpec,
    )
    from mania.preprocessing.physical_time_execution import (
        PreprocessingConditionTemporalExecution,
        PreprocessingTemporalExecution,
        collect_runtime_physical_time_source_frames,
    )
    from mania.preprocessing.physical_time_sampling import (
        resolve_physical_time_sampling,
    )
    from mania.preprocessing.physical_time_windows import plan_physical_time_windows

    system = execution.system
    assert loaded.runtime is not None
    execution.source_frame_count = len(
        cast(Any, loaded.runtime.runtime_object).trajectory
    )
    if system.physical_time is None:
        return
    physical = system.physical_time
    source_frames = collect_runtime_physical_time_source_frames(loaded)
    request = PhysicalRequest.model_validate(physical.model_dump())
    sampling = resolve_physical_time_sampling(source_frames, temporal=request)
    if sampling.status == "failed":
        raise ValueError("Physical sampling failed; no geometry is executed")
    execution.values["sampling"] = sampling
    execution.values["selected_indexes"] = tuple(
        s.source_frame_index for s in sampling.selected_samples
    )
    if not execution.values["selected_indexes"]:
        raise ValueError("No resolved physical-time samples")
    if physical.windows is not None and system.variant_id is not None:
        windows = physical.windows
        temporal = DatasetTemporalParameters(
            production_start_ns=physical.production_start_ns,
            production_end_ns=physical.production_end_ns,
            frame_stride_ps=physical.frame_stride_ps,
            window_length_ns=windows.length_ns,
            window_step_ns=windows.step_ns,
            overlap_percent=windows.overlap_percent,
        )
        identity = system.identity(execution.values["project"])
        spec = DatasetTrajectorySpec(
            identity=DatasetTrajectoryIdentity(
                dataset_id=identity.project,
                system_id=identity.system_id,
                trajectory_id=identity.trajectory_id,
                variant_id=system.variant_id,
                engine=identity.engine,
                condition=identity.condition,
                replica_id=identity.replica_id,
                disulfide_state=identity.disulfide_state,
            ),
            temporal=temporal,
        )
        binding = PreprocessingConditionTemporalExecution(
            execution.values["execution_condition"],
            spec,
            sampling,
            plan_physical_time_windows(
                sampling, temporal=temporal, boundary_profile=windows.boundary_profile
            ),
        )
        execution.values["temporal_execution"] = PreprocessingTemporalExecution(
            (binding,)
        )


class _SelectedTrajectory:
    def __init__(self, trajectory: Any, indexes: tuple[int, ...]) -> None:
        self.trajectory, self.indexes = trajectory, indexes

    def __iter__(self) -> Iterator[Any]:
        for index in self.indexes:
            yield self.trajectory[index]


def execute_rg(
    execution: InputExecution,
    loaded: PreprocessingConditionLoadResult,
    group: Any,
    options: RgEffectiveParameters,
    directory: Path,
) -> None:
    from mania.preprocessing.trajectory_frame_sampling import (
        PreprocessingFrameSamplingOptions,
    )
    from mania.preprocessing.trajectory_rg import compute_condition_rg
    from mania.preprocessing.trajectory_rg_export import write_rg_timeseries_csv

    assert loaded.runtime is not None
    indexes = execution.values.get("selected_indexes", execution.system.frames.indexes)
    selected = loaded
    sampling = None
    if indexes is not None:
        view = _RuntimeGuard.__new__(_RuntimeGuard)
        view._runtime = loaded.runtime.runtime_object
        view.trajectory = _SelectedTrajectory(
            cast(Any, loaded.runtime.runtime_object).trajectory, indexes
        )
        selected = replace(loaded, runtime=replace(loaded.runtime, runtime_object=view))
    else:
        frames = execution.system.frames
        sampling = PreprocessingFrameSamplingOptions(
            frames.start, frames.stop, frames.stride, frames.max_frames
        )
    result = compute_condition_rg(selected, atom_group=group, frame_sampling=sampling)
    if indexes is not None:
        result = replace(
            result,
            frame_results=tuple(
                replace(
                    row,
                    frame_index=indexes[row.frame_index],
                    issues=tuple(
                        replace(issue, frame_index=indexes[row.frame_index])
                        for issue in row.issues
                    ),
                )
                for row in result.frame_results
            ),
        )
    execution.values["rg"] = result
    path = directory / "rg_timeseries.csv"
    written = write_rg_timeseries_csv(
        result,
        path,
        include_failed_frames=options.include_failed_frames,
        overwrite=False,
    )
    if written.passed:
        execution.artifacts.append(("rg_timeseries", path, None))
    if not written.passed or not result.passed:
        raise ValueError("Requested Rg calculation failed; failed rows remain evidence")
    if not execution.observed_frames:
        execution.observed_frames.extend(
            (row.frame_index, row.time_ps) for row in result.frame_results
        )


def execute_rmsd(
    execution: InputExecution,
    loaded: PreprocessingConditionLoadResult,
    options: Any,
    directory: Path,
) -> None:
    from mania.preprocessing.trajectory_frame_sampling import (
        PreprocessingFrameSamplingOptions,
        iter_sampled_trajectory_frames,
    )
    from mania.preprocessing.trajectory_rmsd import (
        RMSDFrame,
        RMSDRow,
        measure_rmsd,
    )
    from mania.preprocessing.trajectory_rmsd_io import write_rmsd_measurement

    if (
        options.fit_selection == "legacy_mapped_ca"
        or options.evaluation_selection == "legacy_mapped_ca"
    ):
        execute_legacy_rmsd(execution, loaded, options, directory)
        return
    assert loaded.runtime is not None
    runtime: Any = loaded.runtime.runtime_object
    fit, evaluation = (
        runtime.select_atoms(options.fit_selection),
        runtime.select_atoms(options.evaluation_selection),
    )
    fit_keys, evaluation_keys = (
        atom_keys(fit, execution.system.engine),
        atom_keys(evaluation, execution.system.engine),
    )
    external = None
    if options.reference.kind == "external":
        from mania.result_readers import read_external_inputs

        external = read_external_inputs(execution.system, options, verify=True)
        coordinates, pairing = external
        if (
            pairing.identity != execution.system.identity(execution.values["project"])
            or tuple(p.source for p in pairing.fit_pairs) != fit_keys
            or tuple(p.source for p in pairing.evaluation_pairs) != evaluation_keys
        ):
            raise ValueError(
                "External RMSD pairs must exactly cover actual ordered selections"
            )
    from mania.canonical_reference import AuthorityBinding
    from mania.preprocessing.trajectory_rmsd_io import file_sha256

    root = (
        execution.system.input_binding_path.parent
        if execution.system.input_binding_path
        else execution.values["config_root"]
    )
    identity = execution.system.identity(execution.values["project"])
    source_paths = (
        ("topology", execution.system.topology),
        *(("trajectory", p) for p in execution.system.trajectories),
    )
    authorities = tuple(
        AuthorityBinding(
            role=role,
            path=path.relative_to(root).as_posix(),
            sha256=file_sha256(path),
            source_identity=identity,
        )
        for role, path in source_paths
    )
    external_reference = None
    external_authority = None
    if external is not None:
        from mania.preprocessing.trajectory_rmsd import RMSDCoordinates

        coordinates, pairing = external
        values = {a.atom: a.xyz_A for a in coordinates.atoms}
        external_reference = RMSDCoordinates(
            fit_keys,
            evaluation_keys,
            [values[p.reference] for p in pairing.fit_pairs],
            [values[p.reference] for p in pairing.evaluation_pairs],
        )
        external_authority = AuthorityBinding(
            role="rmsd_external_coordinates",
            path=options.reference.path.relative_to(root).as_posix(),
            sha256=file_sha256(options.reference.path),
            source_identity=identity,
        )
        authorities = (
            *authorities,
            external_authority,
            AuthorityBinding(
                role="rmsd_atom_mapping",
                path=options.reference.atom_mapping_path.relative_to(root).as_posix(),
                sha256=file_sha256(options.reference.atom_mapping_path),
                source_identity=identity,
            ),
        )
    samples = []
    selected_frames: Iterator[tuple[int, Any]]
    physical = execution.values.get("sampling")
    if physical is not None:
        selected = {s.requested_sample_index: s for s in physical.selected_samples}
        ordered = sorted(
            (*physical.selected_samples, *physical.missing_samples),
            key=lambda s: s.requested_sample_index,
        )
        for sample in ordered:
            resolved = selected.get(sample.requested_sample_index)
            if resolved is None:
                samples.append(
                    RMSDFrame(
                        RMSDRow(
                            requested_sample_index=sample.requested_sample_index,
                            requested_time_ps=sample.requested_time_ps,
                            state="missing",
                            runtime_frame_index=None,
                            source_frame_index=None,
                            prepared_frame_index=None,
                            actual_time_ps=None,
                            time_delta_ps=None,
                            rmsd_A=None,
                        ),
                        None,
                    )
                )
            else:
                runtime.trajectory[resolved.source_frame_index]
                samples.append(
                    _rmsd_frame(
                        resolved.source_frame_index,
                        resolved.actual_time_ps,
                        resolved.requested_sample_index,
                        resolved.requested_time_ps,
                        fit,
                        evaluation,
                        fit_keys,
                        evaluation_keys,
                    )
                )
    else:
        frames = execution.system.frames
        if frames.indexes is not None:
            selected_frames = (
                (index, runtime.trajectory[index]) for index in frames.indexes
            )
        else:
            selected_frames = iter_sampled_trajectory_frames(
                runtime.trajectory,
                PreprocessingFrameSamplingOptions(
                    frames.start, frames.stop, frames.stride, frames.max_frames
                ),
            )
        for ordinal, (index, timestep) in enumerate(selected_frames):
            time_ps = getattr(timestep, "time", None)
            samples.append(
                _rmsd_frame(
                    index,
                    None if time_ps is None else float(time_ps),
                    ordinal,
                    None,
                    fit,
                    evaluation,
                    fit_keys,
                    evaluation_keys,
                )
            )
    first = next((s for s in samples if s.row.state == "resolved"), None)
    if first is None:
        raise ValueError("No selected RMSD reference frame")
    if any(
        file_sha256(path) != authority.sha256
        for (_, path), authority in zip(
            source_paths, authorities[: len(source_paths)], strict=True
        )
    ):
        raise ValueError("RMSD source binding changed during coordinate execution")
    if external is not None:
        # Preserve the exact reference atom keys and mapping bytes as owned evidence.
        if read_external_inputs(execution.system, options, verify=True) != external:
            raise ValueError("External atom authority changed during execution")
        for role, source in (
            ("rmsd_external_coordinates", options.reference.path),
            ("rmsd_atom_mapping", options.reference.atom_mapping_path),
        ):
            path = directory / (role + ".json")
            path.write_bytes(source.read_bytes())
            execution.artifacts.append((role, path, "mania." + role + ".v1"))
    result = measure_rmsd(
        tuple(samples),
        identity=execution.system.identity(execution.values["project"]),
        fit_selection=fit_keys,
        evaluation_selection=evaluation_keys,
        reference=external_reference
        if external_reference is not None
        else "first_selected",
        reference_source=external_authority
        if external_authority is not None
        else cast(int, first.row.source_frame_index),
        sampling_kind="physical" if physical is not None else "frame",
        authority=authorities,
    )
    write_rmsd_measurement(result, directory)
    execution.values["rmsd"] = result
    execution.artifacts.extend(
        (
            ("rmsd_timeseries", directory / "rmsd_timeseries.csv", None),
            ("rmsd_measurement", directory / "rmsd_measurement.json", "mania.rmsd.v1"),
        )
    )
    if not execution.observed_frames:
        execution.observed_frames.extend(
            (cast(int, s.row.source_frame_index), s.row.actual_time_ps)
            for s in samples
            if s.row.state == "resolved"
        )


def _rmsd_frame(
    index: int,
    time_ps: float | None,
    ordinal: int,
    requested: float | None,
    fit: Any,
    evaluation: Any,
    fit_keys: tuple[Any, ...],
    evaluation_keys: tuple[Any, ...],
) -> Any:
    from mania.preprocessing.trajectory_rmsd import RMSDCoordinates, RMSDFrame, RMSDRow

    return RMSDFrame(
        RMSDRow(
            requested_sample_index=ordinal,
            requested_time_ps=requested,
            state="resolved",
            runtime_frame_index=index,
            source_frame_index=index,
            prepared_frame_index=None,
            actual_time_ps=time_ps,
            time_delta_ps=None
            if time_ps is None or requested is None
            else time_ps - requested,
            rmsd_A=0.0,
        ),
        RMSDCoordinates(
            fit_keys, evaluation_keys, fit.positions.copy(), evaluation.positions.copy()
        ),
    )


def execute_windows(
    execution: InputExecution, method: str, runtime: Any, directory: Path
) -> None:
    from mania.preprocessing.molecular_partner_metadata_io import (
        read_molecular_partner_metadata,
    )
    from mania.preprocessing.physical_time_execution_io import (
        write_preprocessing_temporal_execution,
    )
    from mania.preprocessing.protein_edge_window_execution import (
        build_preprocessing_protein_edge_window_source_table,
    )
    from mania.preprocessing.protein_edge_window_table_io import (
        write_dataset_protein_edge_window_csv,
    )
    from mania.preprocessing.specialized_contact_execution import (
        PreprocessingSpecializedContactExecution,
        build_specialized_contact_source_tables,
        execute_specialized_contact_condition,
    )
    from mania.preprocessing.specialized_contact_window_tables_io import (
        write_protein_glycan_window_csv,
        write_protein_lipid_window_csv,
    )
    from mania.preprocessing.trajectory_contacts import (
        PreprocessingManifestContactsResult,
    )

    temporal = execution.values["temporal_execution"]
    written: Any
    if method == "physical_windows":
        from mania.preprocessing.physical_time_execution_io import (
            read_preprocessing_temporal_execution,
        )

        if (directory / "temporal_execution.json").exists():
            if (
                read_preprocessing_temporal_execution(
                    directory / "temporal_execution.json"
                )
                != temporal
            ):
                raise ValueError("Temporal execution changed")
        else:
            written = write_preprocessing_temporal_execution(temporal, directory)
            if not written.passed:
                raise ValueError("Temporal execution serialization failed")
        result = build_preprocessing_protein_edge_window_source_table(
            temporal,
            PreprocessingManifestContactsResult((execution.values["contacts"],)),
        )
        path = directory / "protein_edges_by_window_source.csv"
        written = write_dataset_protein_edge_window_csv(result, directory)
        if not written.passed:
            raise ValueError("Source protein window serialization failed")
        execution.values["protein_windows"] = result
        project_windows(execution, result, "protein", directory)
        execution.artifacts.extend(
            (
                (
                    "temporal_execution",
                    directory / "temporal_execution.json",
                    temporal.schema_version,
                ),
                ("protein_windows", path, result.schema_version),
            )
        )
    else:
        if "specialized" not in execution.values:
            assert execution.system.partners_path is not None
            metadata = read_molecular_partner_metadata(execution.system.partners_path)
            specialized = PreprocessingSpecializedContactExecution(
                (
                    execute_specialized_contact_condition(
                        runtime, temporal.bindings[0], metadata
                    ),
                )
            )
            execution.values["specialized"] = specialized
            lipid, glycan = build_specialized_contact_source_tables(
                specialized, temporal
            )
            execution.values.update(lipid_windows=lipid, glycan_windows=glycan)
        layer = "lipid" if method == "lipid_contacts" else "glycan"
        result = execution.values[layer + "_windows"]
        path = directory / f"protein_{layer}_contacts_by_window_source.csv"
        writer = (
            write_protein_lipid_window_csv
            if layer == "lipid"
            else write_protein_glycan_window_csv
        )
        written = writer(result, directory)
        if not written.passed:
            raise ValueError("Specialized source window serialization failed")
        execution.artifacts.append((layer + "_windows", path, None))
        project_windows(execution, result, layer, directory)


def retain_windows(execution: InputExecution, directory: Path) -> None:
    from mania.preprocessing.perframe_observations import write_perframe_observations
    from mania.preprocessing.trajectory_contacts import (
        PreprocessingManifestContactsResult,
    )

    artifacts = write_perframe_observations(
        directory / "observations",
        execution.values["temporal_execution"],
        PreprocessingManifestContactsResult((execution.values["contacts"],)),
        execution.values.get("specialized"),
    )
    execution.artifacts.extend((role, path, None) for role, path in artifacts)
    if execution.values.get("specialized") is not None:
        execution.artifacts.append(
            (
                "molecular_partner_catalog",
                directory / "observations/molecular_partner_catalog.json",
                "mania.molecular_partner_catalog.v0.1",
            )
        )


def execute_replay(execution: InputExecution, options: Any, directory: Path) -> None:
    from mania.preprocessing.perframe_observations import PERFRAME_COMPLETION_FILENAME
    from mania.preprocessing.physical_time_execution_io import (
        read_preprocessing_temporal_execution,
    )
    from mania.preprocessing.protein_edge_window_table_io import (
        write_dataset_protein_edge_window_csv,
    )
    from mania.preprocessing.window_replay import replay_window_tables

    if options.completion_path.name != PERFRAME_COMPLETION_FILENAME:
        raise ValueError(
            "Replay completion path must identify the retained completion file"
        )
    from mania.scientific_qualification import consume_run_path

    consume_run_path(
        options.completion_path, execution.system.identity(execution.values["project"])
    )
    temporal = read_preprocessing_temporal_execution(options.execution_plan_path)
    expected = execution.system.identity(execution.values["project"])
    old = temporal.bindings[0].dataset_spec.identity
    if len(temporal.bindings) != 1 or (
        old.dataset_id,
        old.system_id,
        old.trajectory_id,
        old.replica_id,
        old.engine,
        old.condition,
        old.variant_id,
        old.disulfide_state,
    ) != tuple(expected.to_dict().values()):
        raise ValueError("Replay temporal/input identity differs")
    result = replay_window_tables(options.completion_path.parent, temporal)
    path = directory / "protein_edges_by_window_source.csv"
    written = write_dataset_protein_edge_window_csv(result.protein, directory)
    if not written.passed:
        raise ValueError("Replay output serialization failed")
    execution.values["replay"] = result
    execution.artifacts.append(("replayed_protein_windows", path, None))


def window_input(system: System, project: str) -> Any:
    """Construct a retained source object from explicit existing file roles."""
    from mania.canonical_reference_io import read_protein_reference
    from mania.canonical_residue_mapping_io import read_residue_mapping
    from mania.input_binding import read_input_binding
    from mania.replica_aggregation_manifest import ReplicaWindowInput

    if system.input_binding_path is None:
        raise RunPreflightError(
            "Source-bound QC/aggregation requires explicit input_binding_path"
        )
    root = system.input_binding_path.parent
    binding = read_input_binding(system.input_binding_path, root=root)
    if binding.identity != system.identity(project):
        raise ValueError("Window source input identity differs")
    files = {f.role: f for f in binding.files}
    required = {
        "reference",
        "residue_mapping",
        "temporal_execution",
        "perframe_completion",
        "contacts_perframe",
    }
    if not required <= files.keys():
        raise RunPreflightError(
            "Complete explicit source window/roster/reference roles are required"
        )
    reference = read_protein_reference(files["reference"].verify(root))
    mapping = read_residue_mapping(
        files["residue_mapping"].verify(root), reference=reference
    )
    directory = Path(files["perframe_completion"].path).parent.as_posix()
    if directory == ".":
        raise RunPreflightError(
            "Source observation directory must be an explicitly bound "
            "portable subdirectory"
        )
    evidence = tuple(
        f for f in binding.files if Path(f.path).is_relative_to(Path(directory))
    )
    result = ReplicaWindowInput(
        binding.identity,
        root,
        files["temporal_execution"],
        directory,
        mapping,
        reference,
        evidence,
        files["residue_mapping"],
        files["reference"],
    )
    from mania.scientific_qualification import consume_run_path

    consume_run_path(files["temporal_execution"].verify(root), binding.identity)
    result.read_back()
    return result


def execute_authoritative_method(
    execution: InputExecution,
    method: str,
    options: Any,
    preprocessing: Path,
    analysis: Path,
) -> None:
    result: Any
    if method == "region_enrichment":
        from mania.analysis import static_rin_region_enrichment as source
        from mania.biological_annotations_io import read_system_annotations
        from mania.canonical_reference_io import read_protein_reference
        from mania.canonical_residue_mapping_io import read_residue_mapping

        system = execution.system
        assert system.reference is not None and system.mapping_path is not None
        reference = read_protein_reference(system.reference.reference_path)
        mapping = read_residue_mapping(system.mapping_path, reference=reference)
        annotation_path = (
            getattr(options, "annotations_path", None) or system.annotations_path
        )
        assert annotation_path is not None
        annotations = read_system_annotations(
            annotation_path,
            reference=reference,
        )
        if not annotations.parameters.complete_region_roster:
            raise RunPreflightError(
                "Source enrichment requires complete supplied region labels"
            )
        nodes = []
        for node in execution.values["static_rin"].nodes:
            matches = [
                r
                for r in mapping.records
                if r.source.resid == node.resid
                and r.source.resname == node.resname
                and r.source.segment_id == node.segment_id
                and r.source.namespace_kind == "segment"
                and r.source.chain_id is None
                and r.source.insertion_code is None
                and r.mapping_status == "mapped"
            ]
            if len(matches) != 1:
                raise RunPreflightError(
                    "Enrichment node lacks unambiguous full supplied source identity"
                )
            row = matches[0]
            assert (
                row.reference_chain_id is not None
                and row.reference_position is not None
            )
            from mania.canonical_reference import ReferenceResidueKey

            key = ReferenceResidueKey(
                reference_chain_id=row.reference_chain_id,
                reference_position=row.reference_position,
            )
            regions = [
                r.annotation_id
                for r in annotations.records
                if r.annotation_kind == "region"
                and r.covers(key)
                and r.knowledge_state == "known"
                and r.value is not False
            ]
            if len(regions) > 1 or any(
                r.annotation_kind == "region"
                and r.covers(key)
                and r.knowledge_state == "unknown"
                for r in annotations.records
            ):
                raise RunPreflightError(
                    "Retained single-category enrichment requires exactly one "
                    "supplied region per node"
                )
            nodes.append(replace(node, region=regions[0] if regions else None))
        graph = replace(execution.values["static_rin"], nodes=tuple(nodes))
        result = source.compute_static_rin_region_enrichment(
            graph, execution.values["communities"]
        )
        path = (
            analysis / f"region_enrichment_{execution.values['trajectory_token']}.csv"
        )
        write_source_rows(
            path,
            source.STATIC_RIN_REGION_ENRICHMENT_COLUMNS,
            result.rows,
            source._csv_value,
        )
        execution.values[method] = result
        execution.artifacts.append((method, path, None))
    elif method == "qc":
        from mania._dataset_qc_json import read_model, write_model
        from mania.dataset_qc_contract import QCDecisions
        from mania.result_readers import execute_qc_sources

        bundle = execute_qc_sources(
            options.evidence_manifest_path, policy_path=options.policy_path
        )
        if options.policy_path is None:
            validate_selected_qc_policy(
                execution.values["selected_extensions"], bundle.policy
            )
        identity = execution.system.identity(execution.values["project"])
        result = next((d for d in bundle.decisions if d.identity == identity), None)
        if result is None:
            raise ValueError("QC cohort lacks requested input identity")
        root = options.evidence_manifest_path.parent
        decision = result.records[0]
        execution.values["qc_sources"] = bundle
        if options.review_decisions_path:
            supplied = read_model(options.review_decisions_path, QCDecisions, root=root)
            if (
                supplied.reference != result.reference
                or supplied.identity != result.identity
                or supplied.parameters != result.parameters
                or len(supplied.records) != 1
                or supplied.records[0].checks != decision.checks
            ):
                raise ValueError(
                    "Reviewer decision does not match actual policy/source checks"
                )
            result = supplied
        directory = analysis.parent / "qc"
        directory.mkdir(exist_ok=True)
        write_model(directory / "qc_decisions.json", result)
        execution.values["qc"] = result
        execution.values["qc_state"] = (
            "pending_review"
            if result.records[0].release_decision == "pending_review"
            else "failed"
            if result.records[0].qc_status == "FAIL"
            else "completed"
        )
        execution.artifacts.append(
            ("qc_decisions", directory / "qc_decisions.json", "mania.qc_decisions.v1")
        )
    else:
        raise ValueError("Unknown retained authoritative method")


def execute_group_method(
    config: RunConfig,
    status: MethodStatus,
    inputs: list[InputExecution],
    staging: Path,
    *,
    run_id: str | None = None,
) -> list[tuple[str, Path, str | None]]:
    definition: Any
    if status.method_id == "comparison":
        from mania.analysis.static_rin_comparison import (
            compare_static_rin_metrics_explicit,
            read_explicit_static_rin_comparison,
            write_explicit_static_rin_comparison,
        )

        index, definition = next(
            (i, d)
            for i, d in enumerate(config.comparisons, 1)
            if d.id == status.identity
        )
        if config._config_path is None:
            raise RunPreflightError(
                "Explicit comparison needs a config-bound portable matching identifier"
            )
        identifier = definition.matching_path.relative_to(
            config._config_path.parent
        ).as_posix()
        directory = staging / f"comparisons/g{index:04d}"
        directory.mkdir(parents=True)
        result = compare_static_rin_metrics_explicit(
            definition.matching_path, matching_identifier=identifier
        )
        write_explicit_static_rin_comparison(result, directory)
        read_explicit_static_rin_comparison(
            directory,
            matching_path=definition.matching_path,
            matching_identifier=identifier,
        )
        return [
            (
                "comparison",
                directory / "comparison.csv",
                "mania.static_rin_comparison.v1",
            ),
            ("stats", directory / "stats.csv", "mania.static_rin_stats.v1"),
        ]
    if status.method_id == "replica_aggregation":
        from mania._dataset_qc_json import read_model
        from mania.dataset_qc_contract import QCDecisions, QCPolicy
        from mania.replica_aggregation_manifest_io import (
            read_replica_aggregation_manifest,
        )
        from mania.replica_aggregation_tables_io import write_replica_window_csv
        from mania.replica_protein_edge_aggregation import aggregate_windows

        index, definition = next(
            (i, d)
            for i, d in enumerate(config.replica_groups, 1)
            if d.id == status.identity
        )
        root = definition.availability_path.parent
        group = read_replica_aggregation_manifest(
            definition.availability_path, root=root
        )
        expected = tuple(
            next(
                s.identity(config.project)
                for s in config.systems
                if (s.id, s.trajectory_id, s.replica_id)
                == (m.system_id, m.trajectory_id, m.replica_id)
            )
            for m in definition.members
        )
        if tuple(m.identity for m in group.members) != expected or (
            group.group_id,
            group.reference.reference_id,
            group.layer,
        ) != (definition.id, definition.reference_id, definition.layer):
            raise ValueError("Explicit aggregation group/source/configuration differs")
        sources = tuple(
            window_input(
                next(
                    s
                    for s in config.systems
                    if s.identity(config.project) == m.identity
                ),
                config.project,
            )
            for m in group.members
            if m.availability == "available"
        )
        policy, decisions = None, None
        if any(m.decision_authority is not None for m in group.members):
            decisions = tuple(
                read_model(
                    verify_authority(root, cast(Any, m.decision_authority), m.identity),
                    QCDecisions,
                    root=root,
                )
                for m in group.members
            )
            bindings = [a for a in decisions[0].authority if a.role == "qc_policy"]
            if len(bindings) != 1:
                raise ValueError("Explicit QC policy binding missing")
            policy = read_model(
                verify_authority(root, bindings[0], bindings[0].source_identity),
                QCPolicy,
                root=root,
            )
        table = aggregate_windows(
            group, sources, policy=policy, decisions=decisions, authority_root=root
        )
        directory = staging / f"replicas/g{index:04d}"
        directory.mkdir(parents=True)
        name = {
            "protein": "protein_edges_by_window_replica_aggregation.csv",
            "lipid": "protein_lipid_contacts_by_window_replica_aggregation.csv",
            "glycan": "protein_glycan_contacts_by_window_replica_aggregation.csv",
        }[definition.layer]
        path = directory / name
        write_replica_window_csv(table, path)
        return [("replica_aggregation", path, "mania.replica_windows.v1")]
    if status.method_id == "profile_outputs":
        from mania.run_config import merge_methods

        choice = next(c for c in config.extensions if c.profile == status.identity)
        active = selected_run_profile(choice)
        qc_requests = tuple(
            (
                sys.identity(config.project),
                opts.policy_path,
                opts.evidence_manifest_path,
            )
            for sys in config.systems
            if isinstance(opts := merge_methods(config, sys).get("qc"), QC)
            and opts.enabled
        )
        directory = staging / "profiles/p0001"
        preview_options = (
            {
                "exploratory": True,
                "run_id": run_id,
                "pbc_by_identity": tuple(
                    (s.identity(config.project), s.pbc.mode == "unverified")
                    for s in config.systems
                ),
            }
            if config.mode == "exploratory"
            else {}
        )
        return cast(
            list[tuple[str, Path, str | None]],
            active.run_executor(
                choice.options.qc_manifest_path,
                release_path=choice.options.release_input_manifest_path,
                directory=directory,
                qc_requests=qc_requests,
                **preview_options,
            ),
        )
    raise RunPreflightError("Unknown requested group method")


def validate_execution_dependencies(plan: Any) -> None:
    """Known missing execution dependencies fail before result-root creation."""
    coordinates = any(
        s.status == "planned"
        and s.method_id
        not in ("replay", "qc", "comparison", "replica_aggregation", "profile_outputs")
        for s in plan.methods
    )
    if coordinates and importlib.util.find_spec("MDAnalysis") is None:
        raise RunPreflightError(
            "Trajectory execution requires optional MDAnalysis==2.10.0"
        )


def configured_input_files(config: RunConfig) -> tuple[Path, ...]:
    from mania.run_config_io import _paths

    paths = tuple(
        p
        for name in type(config).model_fields
        if name != "output"
        for p in _paths(getattr(config, name))
    )
    if config._config_path is not None:
        paths = (*paths, config._config_path)
    return tuple(dict.fromkeys(paths))


def input_inventory(config: RunConfig, run_id: str) -> Any:
    """Existing C05 input descriptors; files stay at their configured locations."""
    from mania.artifact_inventory_io import (
        ArtifactInventoryFileSpec,
        build_artifact_inventory,
    )

    files = configured_input_files(config)
    specs = tuple(
        ArtifactInventoryFileSpec(
            artifact_id=f"input-{i:04d}",
            direction="input",
            role="source_input",
            local_path=path,
            path=f"inputs/i{i:04d}/{path.name}",
            format=path.suffix.lstrip(".") or "binary",
        )
        for i, path in enumerate(files, 1)
    )
    return build_artifact_inventory(
        run_id=run_id,
        workflow="mania.run",
        inventory_path="provenance/artifact_inventory.json",
        file_specs=specs,
        checksum_mode="sha256",
    )


def verify_input_checksum_manifest(config: RunConfig, *, execution: bool) -> None:
    from mania.artifact_inventory_io import read_artifact_inventory, stream_file_sha256

    supplied = config.reproducibility.input_checksum_manifest_path
    if supplied is None:
        return
    inventory = read_artifact_inventory(supplied)
    if inventory.checksum_mode != "sha256" or any(
        a.direction != "input" or a.sha256 is None for a in inventory.artifacts
    ):
        raise RunPreflightError(
            "Input checksum authority requires a SHA256 C05 input inventory"
        )
    configured = set(configured_input_files(config)) - {supplied}
    bound = set()
    for entry in inventory.artifacts:
        path = binding_path(supplied.parent, entry.path)
        if (
            path not in configured
            or path in bound
            or path.stat().st_size != entry.byte_size
        ):
            raise RunPreflightError(
                "Input checksum manifest scope/size differs from configured inputs"
            )
        if execution and stream_file_sha256(path) != entry.sha256:
            raise RunPreflightError(
                "Input checksum manifest digest differs from actual input"
            )
        bound.add(path)
    if bound != configured:
        raise RunPreflightError(
            "Input checksum manifest must cover all configured inputs without itself"
        )


def validate_legacy_prerequisites(
    config: RunConfig, system: System, options: RMSD
) -> None:
    if not any(e.profile == "napi2b.legacy.v1" for e in config.extensions):
        raise RunPreflightError(
            "legacy_mapped_ca requires explicitly selected napi2b.legacy.v1"
        )
    if (
        options.reference is None
        or options.reference.kind != "first_selected"
        or system.reference is None
        or system.mapping_path is None
        or system.input_binding_path is None
    ):
        raise RunPreflightError(
            "Legacy RMSD requires explicit "
            "production reference, fixed reference/mapping and preparation bindings"
        )
    if (
        system.physical_time is None
        or system.physical_time.windows is None
        or system.variant_id is None
        or system.pbc.mode != "prepared"
    ):
        raise RunPreflightError(
            "Legacy RMSD requires explicit physical "
            "production/window/variant and externally prepared inputs"
        )
    from mania_napi2b.canonical_reference_io import read_canonical_reference
    from mania_napi2b.canonical_residue_mapping_io import read_canonical_residue_mapping

    read_canonical_reference(system.reference.reference_path)
    read_canonical_residue_mapping(system.mapping_path)
    binding = InputBinding.model_validate_json(system.input_binding_path.read_bytes())
    files = {f.role: f for f in binding.files}
    if (
        not {
            "topology",
            "mapping",
            "raw_trajectory",
            "prepared_trajectory",
            "preparation_evidence",
        }
        <= files.keys()
    ):
        raise RunPreflightError(
            "Legacy RMSD requires complete supplied "
            "topology/mapping/raw/prepared/preparation roles"
        )
    if system.engine == "namd" and "raw_namd_time" not in files:
        raise RunPreflightError(
            "Raw NAMD frame lineage requires explicitly bound raw_namd_time control"
        )


def execute_legacy_rmsd(
    execution: InputExecution,
    loaded: PreprocessingConditionLoadResult,
    options: Any,
    directory: Path,
) -> None:
    """Selected C04 legacy kernel with proven complete raw/prepared frame lineage."""
    from mania_napi2b.canonical_residue_mapping_io import read_canonical_residue_mapping
    from mania_napi2b.profile import (
        activate_run_profile,
        bind_file,
        select_mapped_ca_atoms,
        write_rmsd_evidence,
    )

    from mania.input_binding import read_input_binding
    from mania.preprocessing.namd_runtime import NAMDControlPaths
    from mania.preprocessing.physical_time_execution import (
        collect_runtime_physical_time_source_frames,
    )
    from mania.preprocessing.physical_time_execution_io import (
        read_preprocessing_temporal_execution,
        write_preprocessing_temporal_execution,
    )
    from mania.preprocessing.trajectory_loader import load_single_condition_runtime

    system = execution.system
    assert (
        system.input_binding_path is not None
        and system.mapping_path is not None
        and loaded.runtime is not None
    )
    root = system.input_binding_path.parent
    binding = read_input_binding(system.input_binding_path, root=root)
    files = {f.role: f for f in binding.files}
    if (
        binding.preparation is None
        or not binding.preparation.frame_order_preserved
        or not binding.preparation.atom_order_preserved
    ):
        raise RunPreflightError(
            "Legacy raw/prepared frame/atom correspondence is unestablished"
        )
    if (
        files["topology"].verify(root) != system.topology
        or files["mapping"].verify(root) != system.mapping_path
        or files["prepared_trajectory"].verify(root) != system.trajectories[0]
    ):
        raise ValueError("Legacy source file roles differ from configured inputs")
    raw_path = files["raw_trajectory"].verify(root)
    controls = (
        NAMDControlPaths(
            system.namd_authority.elements_path, files["raw_namd_time"].verify(root)
        )
        if system.namd_authority
        else None
    )
    raw = load_single_condition_runtime(
        PreprocessingConditionRuntimeInput(
            loaded.condition_name, system.topology, (raw_path,)
        ),
        namd_authority=controls,
    )
    if not raw.passed or raw.runtime is None:
        raise RunPreflightError("Raw trajectory cannot establish legacy frame lineage")
    try:
        raw_frames = collect_runtime_physical_time_source_frames(raw)
        prepared_frames = collect_runtime_physical_time_source_frames(loaded)
        if tuple(f.time_ps for f in raw_frames) != tuple(
            f.time_ps for f in prepared_frames
        ) or len(cast(Any, raw.runtime.runtime_object).atoms) != len(
            cast(Any, loaded.runtime.runtime_object).atoms
        ):
            raise RunPreflightError(
                "Raw/prepared full time/atom rosters do "
                "not prove preserved correspondence"
            )
    finally:
        cast(Any, raw.runtime.runtime_object).trajectory.close()
    temporal = execution.values["temporal_execution"]
    temporal_path = directory / "temporal_execution.json"
    if temporal_path.exists():
        if read_preprocessing_temporal_execution(temporal_path) != temporal:
            raise ValueError("Changed temporal execution")
    elif not write_preprocessing_temporal_execution(temporal, directory).passed:
        raise ValueError("Legacy temporal evidence serialization failed")
    mapping = read_canonical_residue_mapping(system.mapping_path)
    active = activate_run_profile("napi2b.legacy.v1")
    accumulator = active.legacy_rmsd_factory(
        temporal.bindings[0],
        universe=loaded.runtime.runtime_object,
        mapping=mapping,
        source_frame_map=tuple(f.frame_index for f in raw_frames),
    )
    _, atoms = select_mapped_ca_atoms(
        loaded.runtime.runtime_object, mapping, system.engine
    )
    observer = accumulator.selected_frame_observer(atoms, loaded.runtime.runtime_object)
    for sample in temporal.bindings[0].sampling_plan.selected_samples:
        timestep = cast(Any, loaded.runtime.runtime_object).trajectory[
            sample.source_frame_index
        ]
        observer(loaded.condition_name, sample.source_frame_index, float(timestep.time))
    roles = {
        "topology": "topology",
        "mapping": "mapping",
        "prepared_trajectory": "prepared_trajectory",
        "raw_trajectory": "raw_trajectory",
        "preparation_report": "preparation_evidence",
    }
    source_bindings = {
        role: bind_file(files[source].verify(root), "input:" + role, files[source].path)
        for role, source in roles.items()
    }
    result = write_rmsd_evidence(
        accumulator, directory, source_bindings=source_bindings
    )
    execution.values["rmsd"] = result
    execution.artifacts.extend(
        (
            ("temporal_execution", temporal_path, temporal.schema_version),
            ("legacy_rmsd_timeseries", directory / "protein_rmsd_timeseries.csv", None),
            (
                "legacy_rmsd_measurement",
                directory / "protein_rmsd_measurement.json",
                "mania.protein_rmsd_measurement.v0.1",
            ),
        )
    )
    if not execution.observed_frames:
        execution.observed_frames.extend(
            (cast(int, r.runtime_frame_index), r.actual_time_ps)
            for r in accumulator.rows
            if r.state == "resolved"
        )


def project_windows(
    execution: InputExecution, source: Any, layer: str, directory: Path
) -> None:
    from mania.annotated_window_tables import build_annotated_reference_tables
    from mania.annotated_window_tables_io import write_annotated_reference_table
    from mania.biological_annotations_io import read_system_annotations
    from mania.canonical_reference_io import read_protein_reference
    from mania.canonical_residue_mapping_io import read_residue_mapping
    from mania.canonical_window_tables import build_reference_window_tables
    from mania.canonical_window_tables_io import write_reference_window_table

    system = execution.system
    if system.reference is None or system.mapping_path is None:
        return
    # The selected legacy source remains separate from generic reference types.
    if any(
        getattr(s.effective_parameters, "fit_selection", None) == "legacy_mapped_ca"
        for s in execution.statuses
        if s.status != "not_requested"
    ):
        return
    reference = read_protein_reference(system.reference.reference_path)
    mapping = read_residue_mapping(system.mapping_path, reference=reference)
    projected = cast(
        Any,
        build_reference_window_tables((source,), mapping=mapping, reference=reference),
    )[0]
    path = directory / f"{layer}_reference_windows.csv"
    write_reference_window_table(projected, path)
    execution.artifacts.append(
        (layer + "_reference_windows", path, "mania.reference_windows.v1")
    )
    execution.values[layer + "_reference_windows"] = projected
    if system.annotations_path is not None:
        annotations = read_system_annotations(
            system.annotations_path, reference=reference
        )
        annotated = cast(
            Any,
            build_annotated_reference_tables(
                (projected,), annotations=annotations, reference=reference
            ),
        )[0]
        path = directory / f"{layer}_annotated_reference_windows.csv"
        write_annotated_reference_table(annotated, path)
        execution.artifacts.append(
            (
                layer + "_annotated_reference_windows",
                path,
                "mania.annotated_reference_windows.v1",
            )
        )
        execution.values[layer + "_annotated_reference_windows"] = annotated


def result_state(execution: InputExecution, method: str) -> tuple[str, str | None]:
    if method == "qc":
        record = execution.values["qc"].records[0]
        return execution.values["qc_state"], record.reason_code
    if method in ("pca", "clustering", "fingerprints"):
        result = execution.values.get(method)
        if result is not None and result.status != "computed":
            if result.status == "pca_failed":
                return "failed", result.status
            return "not_applicable", result.status
    return "completed", None


def selected_run_profile(choice: Any) -> Any:
    """Invoke only compatible explicitly selected extension-owned run adapters."""
    from mania.extensions import load_selected_extension

    contribution = load_selected_extension(choice.id, choice.version, choice.profile)
    modules = {
        factory.__module__ for factory in contribution.reference_factories.values()
    }
    if len(modules) != 1:
        raise RunPreflightError(
            "Selected extension lacks an unambiguous run contribution"
        )
    module_name = next(iter(modules)).rsplit(".", 1)[0] + ".profile"
    return importlib.import_module(module_name).activate_run_profile(choice.profile)


def validate_selected_qc_policy(choices: Any, policy: Any) -> None:
    """An optional selected policy must match its explicitly bound source roster."""
    if len(choices) != 1:
        raise ValueError(
            "QC without policy_path requires one explicitly selected profile"
        )
    active = selected_run_profile(choices[0])
    expected = active.policy_factory(
        required_check_ids=policy.required_check_ids,
        required_evidence_roles=policy.required_evidence_roles,
        review_cohort_keys=policy.review_cohort_keys,
    )
    if expected != policy:
        raise ValueError(
            "Bound QC policy conflicts with explicitly selected profile policy"
        )
