"""Read-only technical validation of explicit MANIA run result roots."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal, Self, cast

from pydantic import Field, model_validator

from mania.canonical_reference import InputIdentity, Text, _StrictModel
from mania.input_binding import FileEvidence, portable_path
from mania.output_paths import require_input_file, safe_absolute
from mania.preprocessing.specialized_contact_window_tables_io import (
    read_protein_glycan_window_csv,
    read_protein_lipid_window_csv,
)
from mania.preprocessing.trajectory_rmsd import SourceAtomKey
from mania.run_config import RunPreflightError
from mania.run_plan import RunPlan
from mania.run_summary import ExploratoryRunSummary, RunSummary, overall_status


class ArtifactValidationError(ValueError):
    """Present artifacts fail their required technical contract; CLI exit 4."""


@dataclass(frozen=True)
class ValidatedRun:
    root: Path
    summary: RunSummary | ExploratoryRunSummary
    plan: RunPlan
    artifact_count: int


def _sasa_status_defaults(payload: Any) -> Any:
    """Only the approved default-1 addition is optional in old typed SASA rows."""
    import copy

    result = copy.deepcopy(payload)
    if isinstance(result, dict) and isinstance(result.get("methods"), list):
        for row in result["methods"]:
            if isinstance(row, dict) and row.get("method_id") == "sasa":
                options = row.get("effective_parameters")
                if isinstance(options, dict) and set(options) != {"enabled"}:
                    options.setdefault("frame_stride", 1)
    return result


def read_run_summary(root: str | Path) -> RunSummary | ExploratoryRunSummary:
    from mania.preprocessing.molecular_partner_metadata_io import read_strict_json

    path = require_input_file(safe_absolute(Path(root).absolute()) / "summary.json")
    payload = read_strict_json(path)
    if not isinstance(payload, dict):
        raise ArtifactValidationError("Summary requires a JSON object")
    model: Any = (
        ExploratoryRunSummary
        if payload.get("schema_version") == "mania.run_summary.v2"
        else RunSummary
    )
    summary = model.model_validate_json(path.read_bytes())
    if summary.model_dump(mode="json") != _sasa_status_defaults(payload):
        raise ArtifactValidationError("Summary requires complete exact fields")
    if summary.status != overall_status(summary.methods):
        raise ArtifactValidationError("Summary status contradicts method states")
    return cast(RunSummary | ExploratoryRunSummary, summary)


def validate_run_artifacts(root: str | Path) -> ValidatedRun:
    from mania.scientific_qualification import consumption

    try:
        summary = read_run_summary(root)
    except RunPreflightError:
        raise
    except (ValueError, OSError) as exc:
        raise ArtifactValidationError(f"Invalid result summary: {exc}") from exc
    with consumption(summary.mode, independent=True):
        return _validate_run_artifacts(root)


def _validate_run_artifacts(root: str | Path) -> ValidatedRun:
    """Validate integrity and bound typed artifacts, never biological approval."""
    from mania.artifact_inventory_io import read_artifact_inventory, stream_file_sha256
    from mania.preprocessing.molecular_partner_metadata_io import read_strict_json
    from mania.run_config_io import read_bound_run_config
    from mania.run_provenance_io import read_run_provenance
    from mania.runtime_metadata_io import read_runtime_metadata

    base = safe_absolute(Path(root).absolute())
    if not base.is_dir():
        raise RunPreflightError(
            "Validation requires an explicit existing result directory"
        )
    try:
        summary = read_run_summary(base)
        plan_path = require_input_file(base / "run_plan.json")
        payload = read_strict_json(plan_path)
        plan = RunPlan.model_validate_json(plan_path.read_bytes())
        if plan.model_dump(mode="json") != _sasa_status_defaults(payload):
            raise ArtifactValidationError("Plan requires complete exact fields")
        config = read_bound_run_config(base / "effective_config.yaml")
        provenance = read_run_provenance(
            require_input_file(base / summary.provenance_path)
        )
        runtime = read_runtime_metadata(
            require_input_file(base / summary.runtime_metadata_path)
        )
        inventory = read_artifact_inventory(
            require_input_file(base / summary.inventory_path)
        )
        if {summary.run_id, provenance.run_id, inventory.run_id, runtime.run_id} != {
            summary.run_id
        } or {provenance.workflow, inventory.workflow, runtime.workflow} != {
            "mania.run"
        }:
            raise ArtifactValidationError("Controller run/workflow identities disagree")
        if (
            summary.project != plan.project
            or summary.mode != plan.mode
            or summary.path_identity_map != plan.path_identity_map
            or summary.selected_extensions != plan.selected_extensions
            or config.model_dump(mode="json", exclude_unset=True)
            != plan.effective_parameters.model_dump(mode="json", exclude_unset=True)
        ):
            raise ArtifactValidationError(
                "Plan/config/summary identity or extension bindings differ"
            )
        if provenance.to_dict()["resolved_configuration"] != config.model_dump(
            mode="json", exclude_unset=True
        ):
            raise ArtifactValidationError(
                "Provenance configuration differs from executed plan"
            )
        from mania.output_paths import identity_paths

        expected_mapping = tuple(
            p.to_dict()
            for p in identity_paths(
                tuple(s.identity(config.project) for s in config.systems)
            )
        )
        if (
            tuple(p.model_dump(mode="json") for p in plan.path_identity_map)
            != expected_mapping
        ):
            raise ArtifactValidationError("Ordinal path/input identity mapping differs")
        successful = summary.status in ("completed", "completed_with_skips")
        if (provenance.status == "completed") != successful:
            raise ArtifactValidationError("Completion passport contradicts summary")
        owned = {base / summary.inventory_path}
        paths = set()
        inodes = set()
        by_path = {}
        from mania.preprocessing.run_execution import configured_input_files

        input_files = configured_input_files(config)
        original_config = (
            provenance.command[3] if len(provenance.command) >= 4 else None
        )
        if original_config and original_config != "Python-RunConfig":
            input_files = tuple(p for p in input_files if p != config._config_path) + (
                Path(original_config),
            )
        input_by_id = {
            f"input-{i:04d}": p
            for i, p in enumerate(tuple(dict.fromkeys(input_files)), 1)
        }
        for artifact in inventory.artifacts:
            if artifact.direction == "input":
                path = input_by_id.get(artifact.artifact_id)
                if (
                    path is None
                    or artifact.path
                    != f"inputs/i{artifact.artifact_id.removeprefix('input-')}/"
                    f"{path.name}"
                    or artifact.byte_size != require_input_file(path).stat().st_size
                    or artifact.sha256 != stream_file_sha256(path)
                ):
                    raise ArtifactValidationError(
                        "Configured source input descriptor/digest differs"
                    )
                continue
            try:
                path = require_input_file(base / artifact.path)
            except RunPreflightError as exc:
                raise ArtifactValidationError(
                    "Declared owned artifact is missing or unsafe"
                ) from exc
            if (
                path in paths
                or not path.is_relative_to(base)
                or path.stat().st_size != artifact.byte_size
            ):
                raise ArtifactValidationError(
                    "Inventory member/size/uniqueness mismatch"
                )
            inode = (path.stat().st_dev, path.stat().st_ino)
            if inode in inodes:
                raise ArtifactValidationError("Aliased result artifacts")
            paths.add(path)
            inodes.add(inode)
            owned.add(path)
            if (
                artifact.sha256 is not None
                and stream_file_sha256(path) != artifact.sha256
            ):
                raise ArtifactValidationError("Inventory member SHA256 mismatch")
            by_path[artifact.path] = artifact
        if (
            config.reproducibility.checksum_mode == "sha256"
            and inventory.input_artifact_count != len(input_by_id)
        ):
            raise ArtifactValidationError(
                "Reproducibility input inventory is incomplete"
            )
        actual = set()
        for path in base.rglob("*"):
            safe_absolute(path)
            if not path.is_dir():
                require_input_file(path)
                actual.add(path)
        if actual != owned:
            raise ArtifactValidationError("Unowned or missing result artifact")
        if len({a.path for a in summary.artifact_references}) != len(
            summary.artifact_references
        ):
            raise ArtifactValidationError("Duplicate summary artifact path")
        for reference in summary.artifact_references:
            path = require_input_file(base / reference.path)
            if reference.path != summary.inventory_path:
                entry = by_path.get(reference.path)
                if entry is None or entry.role != reference.role:
                    raise ArtifactValidationError(
                        "Summary reference lacks inventory ownership"
                    )
            if (
                reference.sha256 is not None
                and hashlib.sha256(path.read_bytes()).hexdigest() != reference.sha256
            ):
                raise ArtifactValidationError("Summary source/artifact SHA256 mismatch")
        for position in plan.path_identity_map:
            directory = base / position.directory / "preprocessing"
            methods = [
                s
                for s in summary.methods
                if s.identity == position.input_identity
                and (
                    s.status == "completed"
                    or (s.status == "not_applicable" and s.artifact_roles)
                )
            ]
            for method in methods:
                from mania.scientific_qualification import (
                    consume_run_path,
                    set_consumer,
                )

                set_consumer(method.method_id, position.input_identity)
                configured_system = next(
                    s
                    for s in config.systems
                    if s.identity(config.project) == position.input_identity
                )
                if (
                    configured_system.input_binding_path is not None
                    and method.method_id not in ("qc", "replay")
                ):
                    consume_run_path(
                        configured_system.input_binding_path,
                        position.input_identity,
                        direct=True,
                    )
                if (
                    method.method_id == "rmsd"
                    and getattr(method.effective_parameters, "fit_selection", None)
                    == "legacy_mapped_ca"
                ):
                    from mania_napi2b.profile import read_rmsd_evidence

                    metadata, _ = read_rmsd_evidence(directory)
                    old = metadata.dataset_identity
                    if (
                        old.dataset_id,
                        old.system_id,
                        old.trajectory_id,
                        old.replica_id,
                        old.engine,
                        old.condition,
                        old.variant_id,
                        old.disulfide_state,
                    ) != tuple(position.input_identity.to_dict().values()):
                        raise ArtifactValidationError(
                            "Legacy RMSD full source identity differs"
                        )
                elif method.method_id == "rmsd":
                    from mania.preprocessing.trajectory_rmsd_io import (
                        read_rmsd_measurement,
                    )

                    measurement = read_rmsd_measurement(directory)
                    if measurement.identity != position.input_identity:
                        raise ArtifactValidationError("RMSD source identity differs")
                    options = cast(Any, method.effective_parameters)
                    if (
                        getattr(getattr(options, "reference", None), "kind", None)
                        == "external"
                    ):
                        _, system = next(
                            (i, sys)
                            for i, sys in enumerate(config.systems)
                            if sys.identity(config.project) == position.input_identity
                        )
                        _, pairing = read_external_inputs(system, options, verify=True)
                        if (
                            pairing.identity != measurement.identity
                            or tuple(p.source for p in pairing.fit_pairs)
                            != measurement.fit_atoms
                            or tuple(p.source for p in pairing.evaluation_pairs)
                            != measurement.evaluation_atoms
                        ):
                            raise ArtifactValidationError(
                                "External source/reference correspondence differs"
                            )
                        for role, source in (
                            ("rmsd_external_coordinates", options.reference.path),
                            ("rmsd_atom_mapping", options.reference.atom_mapping_path),
                        ):
                            if (
                                directory / (role + ".json")
                            ).read_bytes() != source.read_bytes():
                                raise ArtifactValidationError(
                                    "Retained external atom authority bytes differ"
                                )
                        root = (
                            system.input_binding_path.parent
                            if system.input_binding_path
                            else Path(provenance.command[3]).parent
                        )
                        from mania.input_binding import verify_authority

                        for authority in measurement.authority:
                            verify_authority(root, authority, measurement.identity)
                elif method.method_id in ("rmsf", "sasa"):
                    _validate_atomic_measurement(
                        directory,
                        configured_system,
                        method,
                        config,
                        plan,
                        summary,
                        provenance,
                    )
                elif method.method_id == "physical_windows":
                    from mania.preprocessing.physical_time_execution_io import (
                        read_preprocessing_temporal_execution,
                    )
                    from mania.preprocessing.protein_edge_window_table_io import (
                        read_dataset_protein_edge_window_csv,
                    )
                    from mania.preprocessing.window_replay import replay_window_tables

                    temporal = read_preprocessing_temporal_execution(
                        directory / "temporal_execution.json"
                    )
                    table = read_dataset_protein_edge_window_csv(
                        directory / "protein_edges_by_window_source.csv"
                    )
                    if (
                        replay_window_tables(
                            directory / "observations", temporal
                        ).protein
                        != table
                    ):
                        raise ArtifactValidationError(
                            "Source window table differs from retained per-frame "
                            "evidence"
                        )
                elif method.method_id in ("lipid_contacts", "glycan_contacts"):
                    reader = (
                        read_protein_lipid_window_csv
                        if method.method_id == "lipid_contacts"
                        else read_protein_glycan_window_csv
                    )
                    layer = (
                        "lipid" if method.method_id == "lipid_contacts" else "glycan"
                    )
                    reader(directory / f"protein_{layer}_contacts_by_window_source.csv")
                elif method.method_id == "static_rin":
                    from mania.analysis.static_rin_comparison import (
                        _load_centrality_artifact,
                    )
                    from mania.analysis.static_rin_graph import build_static_rin_graph

                    graph = build_static_rin_graph(
                        directory / "residue_table.csv",
                        directory / "protein_contact_edges.csv",
                        edge_semantics_path=directory / "edge_semantics.json",
                    )
                    graph_path = base / position.directory / "analysis/graph.json"
                    if read_strict_json(graph_path) != graph.to_dict():
                        raise ArtifactValidationError(
                            "RIN graph source binding differs"
                        )
                    _load_centrality_artifact(
                        base
                        / position.directory
                        / f"analysis/centrality_{position.trajectory_token}.csv"
                    )
            qc_status = next(
                (
                    m
                    for m in summary.methods
                    if m.identity == position.input_identity
                    and m.method_id == "qc"
                    and "qc_decisions" in m.artifact_roles
                ),
                None,
            )
            if qc_status is not None:
                from mania.scientific_qualification import set_consumer

                set_consumer("qc", position.input_identity)
                from mania._dataset_qc_json import read_model
                from mania.dataset_qc_contract import QCDecisions
                from mania.preprocessing.run_execution import (
                    validate_selected_qc_policy,
                )

                options = cast(Any, qc_status.effective_parameters)
                bundle = execute_qc_sources(
                    options.evidence_manifest_path, policy_path=options.policy_path
                )
                if options.policy_path is None:
                    validate_selected_qc_policy(config.extensions, bundle.policy)
                expected = next(
                    d for d in bundle.decisions if d.identity == position.input_identity
                )
                if options.review_decisions_path is not None:
                    supplied = read_model(
                        options.review_decisions_path,
                        QCDecisions,
                        root=options.evidence_manifest_path.parent,
                    )
                    if (
                        supplied.identity != expected.identity
                        or supplied.reference != expected.reference
                        or supplied.parameters != expected.parameters
                        or len(supplied.records) != 1
                        or supplied.records[0].checks != expected.records[0].checks
                    ):
                        raise ArtifactValidationError(
                            "Reviewer decision source checks differ"
                        )
                    expected = supplied
                observed = cast(
                    QCDecisions,
                    read_closed_model(
                        base / position.directory / "qc/qc_decisions.json", QCDecisions
                    ),
                )
                if observed != expected:
                    raise ArtifactValidationError(
                        "QC output differs from actual bound sources"
                    )
            _validate_retained_analysis(base, position, methods)
            declared = {
                a.role
                for a in summary.artifact_references
                if a.path.startswith(position.directory + "/")
            }
            if any(not set(s.artifact_roles) <= declared for s in methods):
                raise ArtifactValidationError(
                    "Completed method lacks its declared artifact roles"
                )
        from mania.analysis.static_rin_comparison import (
            read_explicit_static_rin_comparison,
        )

        for index, comparison in enumerate(config.comparisons, 1):
            if any(
                s.method_id == "comparison"
                and s.identity == comparison.id
                and s.status == "completed"
                for s in summary.methods
            ):
                identifier = (
                    comparison.matching_path.relative_to(
                        Path(provenance.command[3]).parent
                    ).as_posix()
                    if config._config_path
                    else comparison.matching_path.name
                )
                from mania.scientific_qualification import set_consumer

                set_consumer("comparison", comparison.id)
                read_explicit_static_rin_comparison(
                    base / f"comparisons/g{index:04d}",
                    matching_path=comparison.matching_path,
                    matching_identifier=identifier,
                )
        for status in summary.methods:
            if status.method_id == "profile_outputs" and status.status == "completed":
                from mania.preprocessing.run_execution import selected_run_profile

                choice = next(
                    c for c in config.extensions if c.profile == status.identity
                )
                active = selected_run_profile(choice)
                from mania.scientific_qualification import set_consumer

                set_consumer("profile_outputs", status.identity)
                active.run_validator(
                    choice.options.qc_manifest_path,
                    release_path=choice.options.release_input_manifest_path,
                    directory=base / "profiles/p0001",
                    **(
                        {
                            "exploratory": True,
                            "run_id": summary.run_id,
                            "pbc_by_identity": tuple(
                                (s.identity(config.project), s.pbc.mode == "unverified")
                                for s in config.systems
                            ),
                        }
                        if config.mode == "exploratory"
                        else {}
                    ),
                )
        if summary.mode == "exploratory":
            _validate_exploratory_bindings(
                base, config, plan, summary, provenance, inventory
            )
            from mania.scientific_qualification import build_qualification

            qualification = build_qualification(
                plan, summary.methods, summary.artifact_references
            )
            if (
                not isinstance(summary, ExploratoryRunSummary)
                or qualification != summary.scientific_qualification
                or qualification
                != getattr(provenance, "scientific_qualification", None)
            ):
                raise ArtifactValidationError(
                    "Exploratory summary/provenance/source qualification differs"
                )
            if provenance.schema_version != "mania.run_provenance.v0.2":
                raise ArtifactValidationError("Exploratory provenance version differs")
        elif provenance.schema_version != "mania.run_provenance.v0.1":
            raise ArtifactValidationError("Strict mode provenance version differs")
        return ValidatedRun(base, summary, plan, len(inventory.artifacts))
    except RunPreflightError:
        raise
    except (OSError, ValueError, TypeError) as exc:
        raise ArtifactValidationError(f"Artifact validation failed: {exc}") from exc


def _serialized_rows(
    columns: tuple[str, ...], rows: object, formatter: object
) -> bytes:
    import csv
    import io
    from typing import Any, cast

    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for row in cast(Any, rows):
        writer.writerow(
            {key: cast(Any, formatter)(value) for key, value in row.to_dict().items()}
        )
    return stream.getvalue().encode("utf-8")


def _validate_retained_analysis(base: Path, position: object, methods: object) -> None:
    from typing import Any, cast

    from mania.analysis import (
        conformation_clustering,
        conformation_pca,
        contact_fingerprints,
        static_rin_communities,
        static_rin_graph,
        static_rin_metrics,
        temporal,
        temporal_rin_metrics,
        temporal_rin_windows,
    )

    p = cast(Any, position)
    requested = {s.method_id: s for s in cast(Any, methods)}
    preprocessing = base / p.directory / "preprocessing"
    analysis = base / p.directory / "analysis"

    def check(
        path: Path, columns: tuple[str, ...], rows: object, formatter: object
    ) -> None:
        if path.read_bytes() != _serialized_rows(columns, rows, formatter):
            raise ArtifactValidationError(
                "Retained source-derived scientific values/columns differ: " + path.name
            )

    if "static_rin" in requested:
        graph = static_rin_graph.build_static_rin_graph(
            preprocessing / "residue_table.csv",
            preprocessing / "protein_contact_edges.csv",
            edge_semantics_path=preprocessing / "edge_semantics.json",
        )
        metrics = static_rin_metrics.compute_static_rin_metrics(graph)
        check(
            analysis / f"centrality_{p.trajectory_token}.csv",
            static_rin_metrics.STATIC_RIN_METRICS_COLUMNS,
            metrics.node_metrics,
            static_rin_metrics._csv_value,
        )
        if "communities" in requested:
            result = static_rin_communities.compute_static_rin_communities(graph)
            check(
                analysis / f"communities_{p.trajectory_token}.csv",
                static_rin_communities.STATIC_RIN_COMMUNITIES_COLUMNS,
                result.assignments,
                static_rin_communities._csv_value,
            )
    if any(
        name in requested
        for name in ("temporal_rin", "fingerprints", "pca", "clustering")
    ):
        with (preprocessing / "protein_contacts_perframe.csv").open(
            encoding="utf-8", newline=""
        ) as stream:
            import csv

            # Its condition is the retained source routing label, not inferred
            # from filenames or biological identities.
            row = next(csv.DictReader(stream), None)
        source_condition = (
            row["condition"] if row is not None else p.input_identity.condition
        )
        if source_condition is None:
            raise ArtifactValidationError("Temporal source condition is unestablished")
        option = requested.get("temporal_rin")
        options = option.effective_parameters if option else None
        config = temporal.TemporalRinConfig(
            window_size=getattr(options, "window_size", 10),
            step_size=getattr(options, "step_size", 10),
            min_frequency=getattr(options, "min_frequency", 0.25),
        )
        inp = temporal.load_temporal_rin_input(
            preprocessing / "protein_contacts_perframe.csv",
            condition=source_condition,
            config=config,
        )
        if "temporal_rin" in requested:
            result_t = temporal_rin_metrics.compute_temporal_rin_metrics(
                temporal_rin_windows.build_temporal_rin_window_graphs(inp)
            )
            check(
                analysis / f"temporal_rin_{p.trajectory_token}.csv",
                temporal_rin_metrics.TEMPORAL_RIN_METRICS_COLUMNS,
                result_t.windows,
                temporal_rin_metrics._csv_value,
            )
        matrix = contact_fingerprints.build_contact_fingerprint_matrix(inp)
        projection = None
        if "pca" in requested:
            projection = conformation_pca.build_conformation_pca_projection(
                matrix,
                enable_pca=True,
                max_pca_components=requested["pca"].effective_parameters.max_components,
            )
            check(
                analysis / f"conformation_pca_{p.trajectory_token}.csv",
                conformation_pca.CONFORMATION_PCA_COLUMNS,
                projection.rows,
                conformation_pca._csv_value,
            )
        if "clustering" in requested:
            options = requested["clustering"].effective_parameters
            labels = conformation_clustering.build_conformation_clusters(
                matrix,
                clustering_basis=options.basis,
                pca_projection=projection,
                pca_components_for_clustering=options.pca_components,
                config=conformation_clustering.ConformationClusteringConfig(
                    max_k=options.max_k, max_iterations=options.max_iterations
                ),
            )
            check(
                analysis / f"conformation_labels_{p.trajectory_token}.csv",
                conformation_clustering.CONFORMATION_LABELS_COLUMNS,
                labels.rows,
                conformation_clustering._csv_value,
            )


# Four approved A/B/C input contracts use retained C05 evidence primitives.


class ReferenceAtomKey(_StrictModel):
    atom_index: Annotated[int, Field(ge=0)]
    chain_id: Text | None
    segment_id: Text | None
    resid: Text
    insertion_code: Text | None
    resname: Text
    atom_name: Text
    element: Text
    altloc: Text | None


class ExternalAtom(_StrictModel):
    atom: ReferenceAtomKey
    xyz_A: tuple[float, float, float]

    @model_validator(mode="after")
    def _finite(self) -> Self:
        import math

        if any(not math.isfinite(v) for v in self.xyz_A):
            raise ValueError("External coordinates must be finite")
        return self


class ExternalCoordinates(_StrictModel):
    schema_version: Literal["mania.rmsd_external_coordinates.v1"]
    kind: Literal["mania_rmsd_external_coordinates"]
    reference_id: Text
    unit: Literal["angstrom"]
    atoms: Annotated[tuple[ExternalAtom, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def _roster(self) -> Self:
        keys = [a.atom for a in self.atoms]
        if len(set(keys)) != len(keys) or len({a.atom_index for a in keys}) != len(
            keys
        ):
            raise ValueError("External atom roster must be unique")
        return self


class AtomPair(_StrictModel):
    source: SourceAtomKey
    reference: ReferenceAtomKey


class ExternalAtomMapping(_StrictModel):
    schema_version: Literal["mania.rmsd_atom_mapping.v1"]
    kind: Literal["mania_rmsd_atom_mapping"]
    identity: InputIdentity
    source_topology: FileEvidence
    reference: FileEvidence
    fit_pairs: Annotated[tuple[AtomPair, ...], Field(min_length=3)]
    evaluation_pairs: Annotated[tuple[AtomPair, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def _pairs(self) -> Self:
        for pairs in (self.fit_pairs, self.evaluation_pairs):
            if any(p.source.element != p.reference.element for p in pairs):
                raise ValueError(
                    "External atom correspondence elemental identity differs"
                )
            for side in ("source", "reference"):
                keys = [getattr(p, side) for p in pairs]
                if len(set(keys)) != len(keys) or len(
                    {a.atom_index for a in keys}
                ) != len(keys):
                    raise ValueError(
                        "Atom pairing must be one-to-one within each selection"
                    )
            if any(p.source.engine != self.identity.engine for p in pairs):
                raise ValueError("Atom pairing engine differs from source identity")
        return self


def read_closed_model(path: Path, model: Any) -> Any:
    """Exact UTF-8 JSON fields/types; no repair or legacy envelope fallback."""
    from mania.preprocessing.molecular_partner_metadata_io import read_strict_json

    path = require_input_file(safe_absolute(path))
    payload = read_strict_json(path)
    value = model.model_validate_json(path.read_bytes())
    if value.model_dump(mode="json") != payload:
        raise ValueError("Input document requires complete exact fields")
    return value


def bound_file(root: Path, evidence: FileEvidence, *, verify: bool) -> Path:
    path = require_input_file(safe_absolute(root / evidence.path))
    if (
        not path.is_relative_to(safe_absolute(root))
        or path.stat().st_size != evidence.size_bytes
    ):
        raise ValueError("Bound evidence path/size differs")
    if verify:
        evidence.verify(root)
    return path


def read_external_inputs(
    system: Any, options: Any, *, verify: bool
) -> tuple[ExternalCoordinates, ExternalAtomMapping]:
    mapping = cast(
        ExternalAtomMapping,
        read_closed_model(options.reference.atom_mapping_path, ExternalAtomMapping),
    )
    root = options.reference.atom_mapping_path.parent
    if (
        mapping.source_topology.role != "topology"
        or mapping.reference.role != "reference"
    ):
        raise ValueError(
            "External RMSD FileEvidence roles must bind topology and reference"
        )
    topology = bound_file(root, mapping.source_topology, verify=verify)
    reference_path = bound_file(root, mapping.reference, verify=verify)
    if topology != system.topology or reference_path != options.reference.path:
        raise ValueError("External RMSD topology/reference path differs from YAML")
    coordinates = cast(
        ExternalCoordinates, read_closed_model(reference_path, ExternalCoordinates)
    )
    atoms = {a.atom: a.xyz_A for a in coordinates.atoms}
    if any(
        p.reference not in atoms
        for p in (*mapping.fit_pairs, *mapping.evaluation_pairs)
    ):
        raise ValueError("Atom correspondence contains an unknown external key")
    return coordinates, mapping


class WindowInputBinding(_StrictModel):
    temporal_evidence: FileEvidence
    observation_directory: Text
    observation_evidence: tuple[FileEvidence, ...]
    mapping_evidence: FileEvidence
    reference_evidence: FileEvidence

    @model_validator(mode="after")
    def _directory(self) -> Self:
        portable_path(self.observation_directory)
        return self

    def reconstruct(self, root: Path, identity: InputIdentity) -> Any:
        from mania.canonical_reference_io import read_protein_reference
        from mania.canonical_residue_mapping_io import read_residue_mapping
        from mania.replica_aggregation_manifest import ReplicaWindowInput

        reference = read_protein_reference(
            bound_file(root, self.reference_evidence, verify=True)
        )
        mapping = read_residue_mapping(
            bound_file(root, self.mapping_evidence, verify=True), reference=reference
        )
        result = ReplicaWindowInput(
            identity,
            root,
            self.temporal_evidence,
            self.observation_directory,
            mapping,
            reference,
            self.observation_evidence,
            self.mapping_evidence,
            self.reference_evidence,
        )
        result.read_back()
        return result


class MetricSelectionBinding(_StrictModel):
    check_id: Text
    source: FileEvidence
    source_row_key: tuple[Any, ...]
    numeric_field: Text
    unit: Text | None

    @model_validator(mode="after")
    def _key(self) -> Self:
        import math

        if not self.source_row_key or any(
            type(v) not in (str, int, float, type(None))
            or type(v) is float
            and not math.isfinite(v)
            for v in self.source_row_key
        ):
            raise ValueError("Source row key requires the retained exact scalar tuple")
        return self

    def selection(self) -> Any:
        return (
            self.check_id,
            self.source,
            self.source_row_key,
            self.numeric_field,
            self.unit,
        )


class QCSourceMember(_StrictModel):
    identity: InputIdentity
    qc_evidence: FileEvidence
    window_input: WindowInputBinding
    metric_selections: tuple[MetricSelectionBinding, ...]


class QCSourceBindings(_StrictModel):
    schema_version: Literal["mania.qc_source_bindings.v1"]
    kind: Literal["mania_qc_source_bindings"]
    policy_evidence: FileEvidence
    group_evidence: FileEvidence
    members: Annotated[tuple[QCSourceMember, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def _members(self) -> Self:
        if len({m.identity for m in self.members}) != len(self.members):
            raise ValueError("Duplicate QC source identity")
        return self


def read_qc_source_bindings(
    path: Path, *, policy_path: Path | None = None, verify: bool = False
) -> QCSourceBindings:
    bindings = cast(QCSourceBindings, read_closed_model(path, QCSourceBindings))
    root = path.parent
    policy = bound_file(root, bindings.policy_evidence, verify=verify)
    if policy_path is not None and policy != policy_path:
        raise ValueError("QC policy source conflicts with YAML")
    bound_file(root, bindings.group_evidence, verify=verify)
    for m in bindings.members:
        files = (
            m.qc_evidence,
            m.window_input.temporal_evidence,
            m.window_input.mapping_evidence,
            m.window_input.reference_evidence,
            *m.window_input.observation_evidence,
            *(s.source for s in m.metric_selections),
        )
        for f in files:
            bound_file(root, f, verify=verify)
    return bindings


@dataclass(frozen=True)
class QCSourceExecution:
    bindings: QCSourceBindings
    policy: Any
    group: Any
    inputs: tuple[Any, ...]
    evidences: tuple[Any, ...]
    selections: tuple[Any, ...]
    hard: tuple[Any, ...]
    review: tuple[Any, ...]
    decisions: tuple[Any, ...]


def execute_qc_sources(
    path: Path, *, policy_path: Path | None = None
) -> QCSourceExecution:
    from mania._dataset_qc_json import read_model
    from mania.dataset_hard_qc import verify_hard_measurement_sources
    from mania.dataset_qc_contract import QCDecisions, QCPolicy
    from mania.dataset_qc_evidence_io import read_replica_hard_qc_evidence
    from mania.dataset_qc_summary import automatic_decision
    from mania.dataset_review_qc import evaluate_dataset_review_qc
    from mania.replica_aggregation_contract import ReplicaGroup

    bindings = read_qc_source_bindings(path, policy_path=policy_path, verify=True)
    root = path.parent
    policy = read_model(bindings.policy_evidence.verify(root), QCPolicy, root=root)
    group = read_model(bindings.group_evidence.verify(root), ReplicaGroup, root=root)
    if tuple(m.identity for m in bindings.members) != tuple(
        m.identity for m in group.members
    ):
        raise ValueError("QC source cohort order/member roster differs")
    inputs = tuple(
        m.window_input.reconstruct(root, m.identity) for m in bindings.members
    )
    evidence = tuple(
        read_replica_hard_qc_evidence(
            m.qc_evidence.verify(root), root=root, policy=policy
        )
        for m in bindings.members
    )
    selections = tuple(
        tuple(s.selection() for s in m.metric_selections) for m in bindings.members
    )
    hard = []
    for m, e, inp in zip(bindings.members, evidence, inputs, strict=True):
        if e.identity != m.identity:
            raise ValueError("QC scientific evidence identity differs")
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
        raw = None
        if raw_records:
            authority = [
                a
                for a in e.authority
                if (a.role, a.sha256, a.source_identity)
                == (
                    raw_records[0].evidence_role,
                    raw_records[0].evidence_sha256,
                    m.identity,
                )
            ]
            if len(authority) != 1:
                raise ValueError("Raw integrity authority is absent or ambiguous")
            f = require_input_file(safe_absolute(root / authority[0].path))
            raw = FileEvidence(
                role=authority[0].role,
                path=authority[0].path,
                size_bytes=f.stat().st_size,
                sha256=authority[0].sha256,
            )
        hard.append(
            verify_hard_measurement_sources(
                e, source=inp, policy=policy, raw_integrity=raw
            )
        )
    reviews = evaluate_dataset_review_qc(
        evidence,
        policy=policy,
        group=group,
        window_inputs=inputs,
        metric_selections=selections,
        hard_evaluations=tuple(hard),
    )
    decisions = []
    for e, h, r in zip(evidence, hard, reviews, strict=True):
        decision = automatic_decision(
            e.identity,
            tuple(
                sorted(
                    (*h, *r), key=lambda c: policy.required_check_ids.index(c.check_id)
                )
            ),
        )
        decisions.append(
            QCDecisions(
                schema_version="mania.qc_decisions.v1",
                kind="mania_qc_decisions",
                identity=e.identity,
                reference=e.reference,
                parameters=e.parameters,
                records=(decision,),
                authority=e.authority,
            )
        )
    return QCSourceExecution(
        bindings,
        policy,
        group,
        inputs,
        evidence,
        selections,
        tuple(hard),
        reviews,
        tuple(decisions),
    )


def _validate_exploratory_bindings(
    base: Path, config: Any, plan: Any, summary: Any, provenance: Any, inventory: Any
) -> None:
    """Cross-check execution, ownership and offline derived outputs, not authority."""
    import tempfile

    from mania.preprocessing import run_execution as adapters
    from mania.scientific_qualification import set_consumer

    if (
        plan.mode != config.mode
        or tuple(s.identity(config.project) for s in config.systems)
        != plan.input_identities
    ):
        raise ArtifactValidationError("Exploratory plan source roster/mode differs")
    if tuple((s.method_id, s.identity) for s in plan.methods) != tuple(
        (s.method_id, s.identity) for s in summary.methods
    ):
        raise ArtifactValidationError(
            "Exploratory final method roster/order differs from plan"
        )
    for requested, final in zip(plan.methods, summary.methods, strict=True):
        if (requested.prerequisites, requested.request_origin) != (
            final.prerequisites,
            final.request_origin,
        ):
            raise ArtifactValidationError("Method dependency/origin differs")
        if requested.status != "planned" and requested.status != final.status:
            raise ArtifactValidationError("Unrequested method status changed")
        if requested.status == "planned" and final.status in (
            "not_requested",
            "planned",
            "running",
        ):
            raise ArtifactValidationError(
                "Requested method has no final execution status"
            )
        if requested.method_id == "rg":
            for field in ("selection", "selection_origin", "include_failed_frames"):
                if getattr(requested.effective_parameters, field, None) != getattr(
                    final.effective_parameters, field, None
                ):
                    raise ArtifactValidationError(
                        "Rg request differs from resolved method"
                    )
        elif requested.effective_parameters != final.effective_parameters:
            raise ArtifactValidationError("Method parameters differ from executed plan")
    from mania.run_plan import _selected

    if plan.selected_extensions != _selected(config):
        raise ArtifactValidationError(
            "Exploratory selected extension/version/resources differ"
        )
    refs = summary.artifact_references
    marker = next((i for i, a in enumerate(refs) if a.role == "run_provenance"), None)
    if marker is None or tuple(
        (r.role, r.path) for r in provenance.artifact_references
    ) != tuple((r.role, r.path) for r in refs[:marker]):
        raise ArtifactValidationError(
            "Provenance output graph differs from published sources"
        )
    expected = {(r.role, r.path) for r in refs if r.path != summary.inventory_path} | {
        ("run_summary", "summary.json")
    }
    if expected != {
        (e.role, e.path) for e in inventory.artifacts if e.direction == "output"
    }:
        raise ArtifactValidationError(
            "Exploratory summary/inventory output coverage differs"
        )
    if any(r.sha256 is None for r in refs if r.path != summary.inventory_path):
        raise ArtifactValidationError("Exploratory owned output lacks its exact SHA256")
    from mania.scientific_qualification import planned_producer

    for reference in refs:
        declared = [
            a
            for a in plan.expected_artifacts
            if (a.role, a.path) == (reference.role, reference.path)
        ]
        if not declared or reference.schema_version != declared[0].schema_version:
            raise ArtifactValidationError(
                "Exploratory owned output schema/plan binding differs"
            )
    owned = {r.path for r in refs}
    completed = {
        (s.method_id, s.identity) for s in summary.methods if s.status == "completed"
    }
    for artifact in plan.expected_artifacts:
        if artifact.producer_method == "controller":
            continue
        producer = planned_producer(plan, artifact)
        if producer in completed and artifact.path not in owned:
            raise ArtifactValidationError(
                "Completed exploratory method lacks a required output"
            )
    warnings = {
        (i.code, i.message) for i in provenance.issues if i.severity == "warning"
    }
    if not any(code == "SCIENTIFIC_VALIDATION_NOT_PERFORMED" for code, _ in warnings):
        raise ArtifactValidationError("Exploratory provenance warning is missing")
    import json

    log_records = [
        json.loads(line) for line in (base / "run.log").read_text().splitlines()
    ]
    from mania.scientific_qualification import warning_records

    expected_warnings = warning_records(config, summary.scientific_qualification)
    if log_records[len(expected_warnings) :] != [
        s.model_dump(mode="json") for s in summary.methods
    ]:
        raise ArtifactValidationError("Exploratory log final method states differ")
    if tuple(log_records[: len(expected_warnings)]) != expected_warnings:
        raise ArtifactValidationError(
            "Exploratory log warnings differ from actual source scope"
        )
    for warning in expected_warnings:
        message = str(warning["message"]) + (
            " " + json.dumps(warning["input_identity"], sort_keys=True)
            if "input_identity" in warning
            else ""
        )
        if (warning["code"], message) not in warnings:
            raise ArtifactValidationError("Source-scoped provenance warning differs")
    with tempfile.TemporaryDirectory(prefix="mania-readback-") as temporary:
        staging = Path(temporary)
        for status in summary.methods:
            if status.status != "completed":
                continue
            set_consumer(status.method_id, status.identity)
            if status.method_id == "replica_aggregation":
                actual = adapters.execute_group_method(config, status, [], staging)
                for _, path, _ in actual:
                    if (
                        path.read_bytes()
                        != (base / path.relative_to(staging)).read_bytes()
                    ):
                        raise ArtifactValidationError(
                            "Replica values differ from actual source-bound statistics"
                        )
            if status.method_id == "replay":
                system = next(
                    s
                    for s in config.systems
                    if s.identity(config.project) == status.identity
                )
                execution = adapters.InputExecution(system, [status])
                execution.values["project"] = config.project
                directory = staging / "replay"
                directory.mkdir(exist_ok=True)
                adapters.execute_replay(
                    execution, status.effective_parameters, directory
                )
                position = next(
                    p
                    for p in plan.path_identity_map
                    if p.input_identity == status.identity
                )
                for _, path, _ in execution.artifacts:
                    if (
                        path.read_bytes()
                        != (
                            base / position.directory / "preprocessing" / path.name
                        ).read_bytes()
                    ):
                        raise ArtifactValidationError(
                            "Replay values differ from exact completed per-frame inputs"
                        )


def _validate_atomic_measurement(
    directory: Path,
    system: Any,
    method: Any,
    config: Any,
    plan: Any,
    summary: Any,
    provenance: Any,
) -> None:
    from mania.preprocessing import run_execution as adapters
    from mania.preprocessing.run_execution import InputExecution
    from mania.preprocessing.trajectory_rmsd import identity_digest
    from mania.preprocessing.trajectory_rmsf_io import read_rmsf_measurement
    from mania.preprocessing.trajectory_sasa_io import read_sasa_measurement
    from mania.run_config import merge_methods

    measurement: Any = (
        read_rmsf_measurement(directory)
        if method.method_id == "rmsf"
        else read_sasa_measurement(directory)
    )
    context = measurement.context
    adapters.validate_authorities(config)
    requested = next(
        (
            s
            for s in plan.methods
            if s.method_id == method.method_id and s.identity == method.identity
        ),
        None,
    )
    options: Any = merge_methods(config, system).get(method.method_id)
    if (
        requested is None
        or requested.effective_parameters != method.effective_parameters
        or options != measurement.options
        or method.effective_parameters != measurement.options
        or context.identity != method.identity
        or context.mode != config.mode
        or context.pbc != system.pbc
    ):
        raise ArtifactValidationError(
            "Atomic source/options/mode/PBC/plan/status differs"
        )
    roles = {Path(name).stem for name in measurement.csv_sha256} | {
        method.method_id + "_measurement"
    }
    if method.method_id == "rmsf" and measurement.reference_kind == "external":
        roles |= {"rmsf_external_coordinates", "rmsf_atom_mapping"}
    if set(method.artifact_roles) != roles or len(method.artifact_roles) != len(roles):
        raise ArtifactValidationError("Atomic method output role coverage differs")
    relative_directory = (
        next(
            p.directory
            for p in plan.path_identity_map
            if p.input_identity == method.identity
        )
        + "/preprocessing/"
    )
    for reference in summary.artifact_references:
        if (
            reference.path.startswith(relative_directory)
            and Path(reference.path).stem in roles
        ):
            expected = next(
                (
                    a
                    for a in plan.expected_artifacts
                    if a.path == reference.path
                    and a.role == reference.role
                    and a.producer_method == method.method_id
                ),
                None,
            )
            if expected is None or reference.schema_version != expected.schema_version:
                raise ArtifactValidationError(
                    "Unknown atomic artifact role/path/schema"
                )
    actual_roles = {
        a.role
        for a in summary.artifact_references
        if a.path.startswith(relative_directory) and a.role in roles
    }
    if actual_roles != roles:
        raise ArtifactValidationError("Missing atomic method output")
    root = (
        system.input_binding_path.parent
        if system.input_binding_path
        else Path(provenance.command[3]).parent
        if provenance.command[3] != "Python-RunConfig"
        else system.topology.parent
    )
    execution = InputExecution(system, [])
    execution.values.update(project=config.project, config_root=root)
    reference = options.reference if method.method_id == "rmsf" else None
    legacy_root = (
        None
        if all(a.path.startswith("atomic_sources/") for a in context.authority)
        else root
    )
    adapters._verify_atomic_sources(
        execution, context.authority, reference=reference, legacy_root=legacy_root
    )
    samples = context.samples
    sampling = getattr(measurement, "sampling", None)
    if sampling is not None:
        samples = sampling.global_samples
        position = next(
            p for p in plan.path_identity_map if p.input_identity == context.identity
        )
        execution.values["execution_condition"] = (
            system.condition
            if system.condition is not None
            else position.system_token + "_" + position.trajectory_token
        )
        loaded = adapters.load_runtime(
            system,
            lambda *args, **kwargs: None,
            execution_condition=execution.values["execution_condition"],
        )
        if loaded.runtime is None:
            raise ArtifactValidationError("SASA source sampling runtime is unavailable")
        atomic_runtime: Any = loaded.runtime.runtime_object
        try:
            adapters.prepare_sampling(execution, loaded)
            actual_global = adapters._atomic_samples(execution, atomic_runtime)
            if samples != actual_global or context.source_frame_count != len(
                atomic_runtime.trajectory
            ):
                raise ArtifactValidationError(
                    "SASA global sampling/header lineage differs"
                )
        finally:
            atomic_runtime.trajectory.runtime.trajectory.close()
        adapters._verify_atomic_sources(
            execution, context.authority, reference=reference, legacy_root=legacy_root
        )
    if system.physical_time is None:
        frames = system.frames
        expected_indexes = frames.indexes
        if expected_indexes is None:
            expected_indexes = tuple(
                range(
                    frames.start,
                    min(
                        frames.stop or context.source_frame_count,
                        context.source_frame_count,
                    ),
                    frames.stride,
                )
            )
            if frames.max_frames is not None:
                expected_indexes = expected_indexes[: frames.max_frames]
        if tuple(s.runtime_frame_index for s in samples) != expected_indexes or any(
            s.requested_time_ps is not None or s.state != "observed" for s in samples
        ):
            raise ArtifactValidationError("Atomic actual frame selector differs")
    else:
        from mania.preprocessing.physical_time_sampling import (
            _matches,
            _requested_times,
        )

        physical = system.physical_time
        targets = _requested_times(
            physical.production_start_ns,
            physical.production_end_ns,
            physical.frame_stride_ps,
        )
        if (
            context.sampling_kind != "physical"
            or tuple(s.requested_time_ps for s in samples) != targets
            or any(
                s.state == "observed"
                and not _matches(s.actual_time_ps, s.requested_time_ps)
                for s in samples
            )
        ):
            raise ArtifactValidationError("Atomic physical-time lineage differs")
    if method.method_id == "rmsf" and measurement.reference_kind == "external":
        coordinates, pairing = read_external_inputs(system, options, verify=True)
        if (
            pairing.identity != context.identity
            or tuple(p.source for p in pairing.fit_pairs) != measurement.fit_atoms
            or tuple(p.source for p in pairing.evaluation_pairs)
            != measurement.evaluation_atoms
        ):
            raise ArtifactValidationError("RMSF ordered external mapping differs")
        values = {a.atom: a.xyz_A for a in coordinates.atoms}
        if (
            identity_digest([values[p.reference] for p in pairing.fit_pairs])
            != measurement.reference_coordinate_sha256
        ):
            raise ArtifactValidationError("External RMSF reference coordinates differ")
        for role, source in (
            ("rmsf_external_coordinates", options.reference.path),
            ("rmsf_atom_mapping", options.reference.atom_mapping_path),
        ):
            if (directory / (role + ".json")).read_bytes() != cast(
                Path, source
            ).read_bytes():
                raise ArtifactValidationError(
                    "Retained RMSF external source bytes differ"
                )
