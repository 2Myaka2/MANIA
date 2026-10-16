"""Immutable bounded plans, source defaults and explicit method dependencies."""

from __future__ import annotations

import hashlib
from importlib import metadata
from pathlib import Path
from typing import Annotated, Any, Literal, cast

from pydantic import BeforeValidator, Field, field_serializer, field_validator

from mania.canonical_reference import InputIdentity
from mania.extensions import ExtensionError, load_selected_extension
from mania.method_status import MethodID, MethodStatus, unknown_rg
from mania.output_paths import (
    identity_paths,
    protected_product_roots,
    require_input_file,
    validate_output_root,
)
from mania.run_config import (
    METHOD_IDS,
    QC,
    Clustering,
    Method,
    RunConfig,
    RunConfigError,
    RunModel,
    RunPreflightError,
    System,
    _ordered,
    merge_methods,
)


class PathIdentity(RunModel):
    system_token: str
    trajectory_token: str
    input_identity: InputIdentity

    @property
    def directory(self) -> str:
        return f"systems/{self.system_token}/{self.trajectory_token}"


class SelectedExtension(RunModel):
    id: Literal["napi2b"]
    distribution: Literal["mania-napi2b"]
    version: Literal["0.2.0a1", "0.2.0a2", "0.2.0a3", "0.2.0"]
    profile: Literal["napi2b.legacy.v1", "napi2b.dataset.v1"]
    api_version: Literal["mania.extension_api.v1"]
    resource_digests: dict[str, str]

    @field_validator("resource_digests")
    @classmethod
    def _resources(cls, value: dict[str, str]) -> dict[str, str]:
        import re

        if set(value) != {
            "mania_napi2b/data/canonical/slc34a2_o95436_reference.json",
            "mania_napi2b/data/publication/contact_definition_authority_v1.json",
        } or any(re.fullmatch(r"[0-9a-f]{64}", v) is None for v in value.values()):
            raise ValueError(
                "Selected resources require exact names and SHA256 digests"
            )
        return value


class ExpectedArtifact(RunModel):
    role: str
    path: str
    schema_version: str | None
    producer_method: MethodID | Literal["controller"]

    @field_validator("path")
    @classmethod
    def _portable(cls, value: str) -> str:
        from mania.input_binding import portable_path

        return portable_path(value)


class UnverifiedCondition(RunModel):
    property: str
    input_identity: InputIdentity
    reason: str


class ResourceEstimate(RunModel):
    frame_count: Annotated[int, Field(ge=0)] | None = None
    hash_io_bytes: Annotated[int, Field(ge=0)] | None = None
    output_bytes: Annotated[int, Field(ge=0)] | None = None


class RunPlan(RunModel):
    schema_version: Literal["mania.run_plan.v1"] = "mania.run_plan.v1"
    kind: Literal["mania_run_plan"] = "mania_run_plan"
    project: str
    mode: Literal["basic", "custom", "full", "exploratory"]
    input_identities: Annotated[tuple[InputIdentity, ...], BeforeValidator(_ordered)]
    path_identity_map: Annotated[tuple[PathIdentity, ...], BeforeValidator(_ordered)]
    methods: Annotated[tuple[MethodStatus, ...], BeforeValidator(_ordered)]
    effective_parameters: RunConfig
    selected_extensions: Annotated[
        tuple[SelectedExtension, ...], BeforeValidator(_ordered)
    ]
    expected_artifacts: Annotated[
        tuple[ExpectedArtifact, ...], BeforeValidator(_ordered)
    ]
    unverified_conditions: Annotated[
        tuple[UnverifiedCondition, ...], BeforeValidator(_ordered)
    ]
    resource_estimate: ResourceEstimate

    @field_serializer("effective_parameters")
    def _configuration(self, value: RunConfig) -> dict[str, object]:
        return value.model_dump(mode="json", exclude_unset=True)

    def to_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json")


DEPENDENCIES: dict[str, tuple[str, ...]] = {
    "static_rin": ("contacts",),
    "communities": ("static_rin",),
    "region_enrichment": ("communities",),
    "typed_interactions": ("contacts",),
    "temporal_rin": ("contacts",),
    "fingerprints": ("contacts",),
    "pca": ("fingerprints",),
    "clustering": ("fingerprints",),
    "physical_windows": ("contacts",),
    "lipid_contacts": ("physical_windows",),
    "glycan_contacts": ("physical_windows",),
}
REPLICA_FILENAMES = {
    "protein": "protein_edges_by_window_replica_aggregation.csv",
    "lipid": "protein_lipid_contacts_by_window_replica_aggregation.csv",
    "glycan": "protein_glycan_contacts_by_window_replica_aggregation.csv",
}
GROUP_METHODS = {"comparison", "replica_aggregation", "profile_outputs"}
DEFAULT_SOURCES = {
    "contacts": (
        "trajectory_contacts.PreprocessingContactDetectionOptions; run preset protein"
    ),
    "static_rin": (
        "analysis.static_rin_graph / static_rin_metrics; retained "
        "edge priority and weights"
    ),
    "communities": (
        "analysis.static_rin_communities; retained deterministic greedy modularity"
    ),
    "temporal_rin": "analysis.temporal.TemporalRinConfig",
    "fingerprints": (
        "analysis.contact_fingerprints; retained ordered binary feature basis"
    ),
    "pca": "analysis.conformation_pca; explicitly enabled reduced centered float64 SVD",
    "clustering": (
        "analysis.conformation_clustering; retained k/iteration/basis defaults"
    ),
    "physical_windows": (
        "preprocessing.physical_time_sampling/windows; supplied physical options"
    ),
    "lipid_contacts": (
        "preprocessing.protein_lipid_contacts; retained 6.0 angstrom definitions"
    ),
    "glycan_contacts": (
        "preprocessing.protein_glycan_contacts; retained 4.5 "
        "angstrom/covalent definitions"
    ),
}


def _origin(
    config: RunConfig, system: System, name: str
) -> Literal["preset", "explicit", "dependency"]:
    if getattr(config.methods, name) is not None or (
        system.method_overrides is not None
        and getattr(system.method_overrides, name) is not None
    ):
        return "explicit"
    return "preset"


def _missing(
    config: RunConfig, system: System, name: str, option: Method
) -> str | None:
    if name in ("physical_windows", "lipid_contacts", "glycan_contacts"):
        if system.physical_time is None or system.physical_time.windows is None:
            return "physical_time.windows is required"
        if system.variant_id is None:
            return "retained source-window identity requires a supplied variant_id"
    if name in ("lipid_contacts", "glycan_contacts") and system.partners_path is None:
        return (
            "supplied partners_path is required; absent metadata is not inapplicability"
        )
    if name == "region_enrichment":
        path = getattr(option, "annotations_path", None) or system.annotations_path
        if path is None:
            return "supplied region annotations are required"
        if system.reference is None or system.mapping_path is None:
            return "generic annotations require explicit reference and source mapping"
    if name == "qc" and isinstance(option, QC):
        if option.evidence_manifest_path is None:
            return "explicit source-bound QC evidence is required"
        if option.policy_path is None and not config.extensions:
            return "explicit QC policy is required"
    return None


def _input_statuses(config: RunConfig, system: System) -> tuple[MethodStatus, ...]:
    options = merge_methods(config, system)
    origins = {name: _origin(config, system, name) for name in options}
    if config.mode in ("basic", "full"):
        for name in ("contacts", "static_rin"):
            if not options[name].enabled:
                raise RunConfigError(
                    f"{config.mode} requires {name}; "
                    "use Custom for another scientific request"
                )
    # Annotation is an applicable Full candidate only with supplied data. The
    # explicit option validator remains strict; no incomplete explicit request.
    if (
        config.mode == "full"
        and "region_enrichment" not in options
        and system.annotations_path is not None
    ):
        options["region_enrichment"] = Method()
        origins["region_enrichment"] = "preset"
    auto_rg = config.mode in ("basic", "full") and "rg" not in options
    if auto_rg:
        options["rg"] = Method()
        origins["rg"] = "preset"
    # Unavailable optional preset methods do not enable scientific dependencies.
    unavailable = {
        name: _missing(config, system, name, option)
        for name, option in options.items()
        if option.enabled
    }
    for name, reason in unavailable.items():
        if reason and origins[name] == "explicit":
            raise RunPreflightError(
                f"{system.id}/{system.trajectory_id}: {name}: {reason}"
            )
    pending = [
        name
        for name, option in options.items()
        if option.enabled and not unavailable.get(name)
    ]
    while pending:
        name = pending.pop()
        deps = DEPENDENCIES.get(name, ())
        if (
            name == "clustering"
            and isinstance(options[name], Clustering)
            and cast(Clustering, options[name]).basis == "pca"
        ):
            deps = (*deps, "pca")
        for dependency in deps:
            if dependency in options and not options[dependency].enabled:
                raise RunConfigError(
                    f"{name} requires explicitly disabled {dependency}"
                )
            if dependency not in options:
                from mania.run_config import PCA, Contacts

                models = {"contacts": Contacts, "pca": PCA}
                options[dependency] = models.get(dependency, Method)()
                origins[dependency] = "dependency"
                pending.append(dependency)
    if (
        options.get("static_rin", Method(enabled=False)).enabled
        and getattr(options.get("contacts"), "selection", None) != "protein"
    ):
        raise RunConfigError("Protein static RIN requires contacts.selection=protein")
    identity = system.identity(config.project)
    statuses = []
    for name in METHOD_IDS:
        if name in GROUP_METHODS:
            continue
        option = options.get(name, Method(enabled=False))
        origin = origins.get(name, "explicit")
        reason = unavailable.get(name)
        state: Literal["planned", "not_requested", "missing_optional_input"] = (
            "planned" if option.enabled else "not_requested"
        )
        if reason:
            state = "missing_optional_input"
        parameters: Any = option
        if name == "rg" and option.enabled:
            parameters = unknown_rg(
                getattr(option, "selection", None) or "protein",
                automatic=auto_rg,
                include_failed_frames=getattr(option, "include_failed_frames", True),
            )
        deps = DEPENDENCIES.get(name, ())
        if (
            name == "clustering"
            and isinstance(option, Clustering)
            and option.basis == "pca"
        ):
            deps = (*deps, "pca")
        statuses.append(
            MethodStatus(
                method_id=cast(MethodID, name),
                identity=identity,
                request_origin=origin,
                status=state,
                reason_code="missing_optional_input"
                if reason
                else ("not_requested" if not option.enabled else None),
                message=reason
                or (
                    "Default source: "
                    + DEFAULT_SOURCES.get(
                        name, "supplied explicit options/retained API"
                    )
                ),
                prerequisites=cast(tuple[MethodID, ...], deps),
                effective_parameters=parameters,
                artifact_roles=(),
            )
        )
    return tuple(statuses)


def _selected(config: RunConfig) -> tuple[SelectedExtension, ...]:
    selected = []
    for choice in config.extensions:
        try:
            contribution = load_selected_extension(
                choice.id, choice.version, choice.profile
            )
            dist = metadata.distribution(contribution.metadata.distribution)
            resources = {}
            for item in dist.files or ():
                name = str(item)
                if name.startswith("mania_napi2b/data/") and name.endswith(".json"):
                    path = require_input_file(Path(str(dist.locate_file(item))))
                    resources[name] = hashlib.sha256(path.read_bytes()).hexdigest()
            if set(resources) != {
                "mania_napi2b/data/canonical/slc34a2_o95436_reference.json",
                "mania_napi2b/data/publication/contact_definition_authority_v1.json",
            }:
                raise ExtensionError(
                    "Selected profile resource inventory is incomplete or unexpected"
                )
            selected.append(
                SelectedExtension(
                    id=choice.id,
                    distribution=cast(Any, contribution.metadata.distribution),
                    version=cast(Any, contribution.metadata.version),
                    profile=choice.profile,
                    api_version=cast(Any, contribution.metadata.api_version),
                    resource_digests=resources,
                )
            )
        except (ExtensionError, metadata.PackageNotFoundError) as exc:
            raise RunPreflightError(str(exc)) from exc
    return tuple(selected)


def build_run_plan(config: RunConfig) -> RunPlan:
    from mania.scientific_qualification import consumption

    if type(config) is not RunConfig:
        raise RunConfigError("A validated RunConfig is required")
    with consumption(config.mode):
        return _build_run_plan(config)


def _build_run_plan(config: RunConfig) -> RunPlan:
    """Validate bounded inputs and scope; never calculate or create outputs."""
    from mania.run_config_io import _bind, _paths

    if type(config) is not RunConfig:
        raise RunConfigError("A validated RunConfig is required")
    # Revalidate direct Python construction, including unchecked model copies.
    source_config_path = config._config_path
    config = RunConfig.model_validate(_bind(config, Path.cwd()))
    config._config_path = source_config_path
    inputs = tuple(
        p
        for name in type(config).model_fields
        if name != "output"
        for p in _paths(getattr(config, name))
    )
    for path in inputs:
        require_input_file(path)
    validate_output_root(
        config.output.root,
        inputs=inputs,
        overwrite=config.output.overwrite,
        protected_roots=protected_product_roots(),
    )
    selected = _selected(config)
    from mania.preprocessing.run_execution import validate_authorities

    validate_authorities(config)
    identities = tuple(s.identity(config.project) for s in config.systems)
    mapping = tuple(
        PathIdentity(
            system_token=p.system_token,
            trajectory_token=p.trajectory_token,
            input_identity=p.input_identity,
        )
        for p in identity_paths(identities)
    )
    statuses = tuple(
        status
        for system in config.systems
        for status in _input_statuses(config, system)
    )
    groups = []
    for method_id, definitions in (
        ("comparison", config.comparisons),
        ("replica_aggregation", config.replica_groups),
    ):
        option = getattr(config.methods, method_id)
        considered = bool(definitions) and config.mode == "full"
        explicit = option is not None and option.enabled
        if explicit and not definitions:
            raise RunPreflightError(f"{method_id} requires explicit group definitions")
        if considered and option is not None and not option.enabled:
            considered = False
        if not (considered or explicit):
            continue
        for definition in definitions:
            groups.append(
                MethodStatus(
                    method_id=cast(MethodID, method_id),
                    identity=definition.id,
                    request_origin="explicit" if explicit else "preset",
                    status="planned",
                    effective_parameters=option or Method(),
                    message="Explicit source/group authority; no grouping by labels",
                )
            )
    profile = config.methods.profile_outputs
    if profile is not None and profile.enabled:
        choice = next(
            (x for x in config.extensions if x.profile == "napi2b.dataset.v1"), None
        )
        if choice is None or choice.options.release_input_manifest_path is None:
            raise RunPreflightError(
                "Profile outputs require selected dataset profile and "
                "release_input_manifest_path"
            )
        groups.append(
            MethodStatus(
                method_id="profile_outputs",
                identity=choice.profile,
                request_origin="explicit",
                status="planned",
                effective_parameters=profile,
            )
        )
    statuses = (*statuses, *groups)
    unverified = tuple(
        UnverifiedCondition(property=prop, input_identity=identity, reason=reason)
        for identity in identities
        for prop, reason in (
            (
                "complete_frame_time_axis",
                (
                    "Header metadata cannot establish all selected "
                    "source-frame/time identities"
                ),
            ),
            (
                "coordinate_pbc_suitability",
                "No coordinate science or preparation is performed during planning",
            ),
            (
                "rg_eligibility",
                (
                    "Complete selection, masses/data and PBC require independent "
                    "runtime observations"
                ),
            ),
        )
    )
    if config.mode == "exploratory":
        unverified += tuple(
            UnverifiedCondition(
                property="pbc",
                input_identity=s.identity(config.project),
                reason="PBC_UNVERIFIED",
            )
            for s in config.systems
            if s.pbc.mode == "unverified"
        )
    retention = any(
        s.status == "planned"
        and s.method_id
        in (
            "temporal_rin",
            "fingerprints",
            "pca",
            "clustering",
            "physical_windows",
            "lipid_contacts",
            "glycan_contacts",
            "replay",
            "replica_aggregation",
        )
        for s in statuses
    )
    effective = config.model_copy(
        update={
            "output": config.output.model_copy(
                update={"retain_perframe": config.output.retain_perframe or retention}
            )
        }
    )
    expected = _expected_artifacts(effective, mapping, statuses)
    hash_bytes = None
    if config.reproducibility.checksum_mode == "sha256":
        from mania.preprocessing.run_execution import configured_input_files

        hash_bytes = 2 * sum(p.stat().st_size for p in configured_input_files(config))
    return RunPlan(
        project=config.project,
        mode=config.mode,
        input_identities=identities,
        path_identity_map=mapping,
        methods=statuses,
        effective_parameters=effective,
        selected_extensions=selected,
        expected_artifacts=expected,
        unverified_conditions=unverified,
        resource_estimate=ResourceEstimate(hash_io_bytes=hash_bytes),
    )


def _expected_artifacts(
    config: RunConfig,
    mapping: tuple[PathIdentity, ...],
    statuses: tuple[MethodStatus, ...],
) -> tuple[ExpectedArtifact, ...]:
    records = [
        ExpectedArtifact(
            role=role, path=path, schema_version=schema, producer_method="controller"
        )
        for role, path, schema in (
            ("effective_config", "effective_config.yaml", "mania.run_config.v1"),
            ("run_plan", "run_plan.json", "mania.run_plan.v1"),
            (
                "run_summary",
                "summary.json",
                "mania.run_summary.v2"
                if config.mode == "exploratory"
                else "mania.run_summary.v1",
            ),
            ("run_log", "run.log", None),
            (
                "run_provenance",
                "provenance/run_provenance.json",
                "mania.run_provenance.v0.2"
                if config.mode == "exploratory"
                else "mania.run_provenance.v0.1",
            ),
            (
                "artifact_inventory",
                "provenance/artifact_inventory.json",
                "mania.artifact_inventory.v0.1",
            ),
            (
                "runtime_metadata",
                "provenance/runtime_metadata.json",
                "mania.runtime_metadata.v0.1",
            ),
        )
    ]
    families = {
        "contacts": (
            ("contact_edges", "preprocessing/contact_edges.csv", None),
            ("protein_contact_edges", "preprocessing/protein_contact_edges.csv", None),
            ("edge_semantics", "preprocessing/edge_semantics.json", None),
        ),
        "static_rin": (
            ("residue_table", "preprocessing/residue_table.csv", None),
            ("static_rin_graph", "analysis/graph.json", "mania.static_rin_graph.v0.1"),
            ("centrality", "analysis/centrality_{token}.csv", None),
        ),
        "communities": (("communities", "analysis/communities_{token}.csv", None),),
        "region_enrichment": (
            ("region_enrichment", "analysis/region_enrichment_{token}.csv", None),
        ),
        "typed_interactions": (
            (
                "protein_contacts_perframe",
                "preprocessing/protein_contacts_perframe.csv",
                None,
            ),
        ),
        "replay": (
            (
                "replayed_protein_windows",
                "preprocessing/protein_edges_by_window_source.csv",
                None,
            ),
        ),
        "rg": (("rg_timeseries", "preprocessing/rg_timeseries.csv", None),),
        "rmsd": (
            ("rmsd_timeseries", "preprocessing/rmsd_timeseries.csv", None),
            (
                "rmsd_measurement",
                "preprocessing/rmsd_measurement.json",
                "mania.rmsd.v1",
            ),
        ),
        "temporal_rin": (("temporal_rin", "analysis/temporal_rin_{token}.csv", None),),
        "pca": (("pca", "analysis/conformation_pca_{token}.csv", None),),
        "clustering": (
            ("clustering", "analysis/conformation_labels_{token}.csv", None),
        ),
        "physical_windows": (
            (
                "temporal_execution",
                "preprocessing/temporal_execution.json",
                "mania.preprocessing_temporal_execution.v0.1",
            ),
            (
                "protein_windows",
                "preprocessing/protein_edges_by_window_source.csv",
                "mania.dataset_protein_edges_by_window_source.v0.1",
            ),
        ),
        "lipid_contacts": (
            (
                "lipid_windows",
                "preprocessing/protein_lipid_contacts_by_window_source.csv",
                None,
            ),
        ),
        "glycan_contacts": (
            (
                "glycan_windows",
                "preprocessing/protein_glycan_contacts_by_window_source.csv",
                None,
            ),
        ),
        "qc": (("qc_decisions", "qc/qc_decisions.json", "mania.qc_decisions.v1"),),
    }
    for position in mapping:
        selected = [
            s
            for s in statuses
            if s.identity == position.input_identity and s.status == "planned"
        ]
        for status in selected:
            artifacts = families.get(status.method_id, ())
            if (
                status.method_id == "rmsd"
                and getattr(status.effective_parameters, "fit_selection", None)
                == "legacy_mapped_ca"
            ):
                artifacts = (
                    (
                        "legacy_rmsd_timeseries",
                        "preprocessing/protein_rmsd_timeseries.csv",
                        None,
                    ),
                    (
                        "legacy_rmsd_measurement",
                        "preprocessing/protein_rmsd_measurement.json",
                        "mania.protein_rmsd_measurement.v0.1",
                    ),
                    (
                        "temporal_execution",
                        "preprocessing/temporal_execution.json",
                        "mania.preprocessing_temporal_execution.v0.1",
                    ),
                )
            for role, relative, schema in artifacts:
                records.append(
                    ExpectedArtifact(
                        role=role,
                        path=position.directory
                        + "/"
                        + relative.format(token=position.trajectory_token),
                        schema_version=schema,
                        producer_method=status.method_id,
                    )
                )
    if config.output.retain_perframe:
        for position in mapping:
            if any(
                s.identity == position.input_identity
                and s.method_id == "contacts"
                and s.status == "planned"
                for s in statuses
            ):
                path = (
                    position.directory + "/preprocessing/protein_contacts_perframe.csv"
                )
                if not any(r.path == path for r in records):
                    records.append(
                        ExpectedArtifact(
                            role="protein_contacts_perframe",
                            path=path,
                            schema_version=None,
                            producer_method="contacts",
                        )
                    )
    for position, system in zip(mapping, config.systems, strict=True):
        planned = {
            s.method_id
            for s in statuses
            if s.identity == position.input_identity and s.status == "planned"
        }

        def add(
            role: str,
            relative: str,
            schema: str | None,
            producer: MethodID,
            directory: str = position.directory,
        ) -> None:
            path = directory + "/preprocessing/" + relative
            if not any(r.path == path for r in records):
                records.append(
                    ExpectedArtifact(
                        role=role,
                        path=path,
                        schema_version=schema,
                        producer_method=producer,
                    )
                )

        if "physical_windows" in planned:
            from mania.preprocessing.perframe_observations import (
                PERFRAME_COMPLETION_FILENAME,
                PERFRAME_COMPLETION_VERSION,
                PROTEIN_GLYCAN_PERFRAME_VERSION,
                PROTEIN_LIPID_PERFRAME_VERSION,
                PROTEIN_PERFRAME_PATH,
                SPECIALIZED_PERFRAME_FILES,
            )

            add(
                "perframe_completion",
                "observations/" + PERFRAME_COMPLETION_FILENAME,
                PERFRAME_COMPLETION_VERSION,
                "physical_windows",
            )
            add(
                "contacts_perframe",
                "observations/" + PROTEIN_PERFRAME_PATH,
                None,
                "physical_windows",
            )
            if planned & {"lipid_contacts", "glycan_contacts"}:
                for layer, schema in (
                    ("lipid", PROTEIN_LIPID_PERFRAME_VERSION),
                    ("glycan", PROTEIN_GLYCAN_PERFRAME_VERSION),
                ):
                    add(
                        "protein_" + layer + "_perframe",
                        "observations/" + SPECIALIZED_PERFRAME_FILES[layer],
                        schema,
                        "physical_windows",
                    )
                add(
                    "molecular_partner_catalog",
                    "observations/molecular_partner_catalog.json",
                    "mania.molecular_partner_catalog.v0.1",
                    "physical_windows",
                )
            if (
                system.physical_time
                and system.physical_time.windows
                and system.physical_time.windows.boundary_profile
                == "mania.window_boundaries.inclusive.v1"
            ):
                records[:] = [
                    r.model_copy(
                        update={
                            "schema_version": (
                                "mania.preprocessing_temporal_execution.v0.2"
                            )
                        }
                    )
                    if r.path
                    == position.directory + "/preprocessing/temporal_execution.json"
                    else r
                    for r in records
                ]
        legacy = any(
            s.identity == position.input_identity
            and s.method_id == "rmsd"
            and getattr(s.effective_parameters, "fit_selection", None)
            == "legacy_mapped_ca"
            for s in statuses
        )
        if (
            system.reference is not None
            and system.mapping_path is not None
            and not legacy
        ):
            for layer, producer in (
                ("protein", "physical_windows"),
                ("lipid", "lipid_contacts"),
                ("glycan", "glycan_contacts"),
            ):
                if producer in planned:
                    add(
                        layer + "_reference_windows",
                        layer + "_reference_windows.csv",
                        "mania.reference_windows.v1",
                        producer,
                    )
                    if system.annotations_path is not None:
                        add(
                            layer + "_annotated_reference_windows",
                            layer + "_annotated_reference_windows.csv",
                            "mania.annotated_reference_windows.v1",
                            producer,
                        )
    definition: Any
    for method, definitions, folder in (
        ("comparison", config.comparisons, "comparisons"),
        ("replica_aggregation", config.replica_groups, "replicas"),
    ):
        for index, definition in enumerate(definitions, 1):
            if any(
                s.method_id == method
                and s.identity == definition.id
                and s.status == "planned"
                for s in statuses
            ):
                names = (
                    (
                        (
                            "comparison",
                            "comparison.csv",
                            "mania.static_rin_comparison.v1",
                        ),
                        ("stats", "stats.csv", "mania.static_rin_stats.v1"),
                    )
                    if method == "comparison"
                    else (
                        (
                            "replica_aggregation",
                            REPLICA_FILENAMES[definition.layer],
                            "mania.replica_windows.v1",
                        ),
                    )
                )
                for role, name, schema in names:
                    records.append(
                        ExpectedArtifact(
                            role=role,
                            path=f"{folder}/g{index:04d}/{name}",
                            schema_version=schema,
                            producer_method=cast(MethodID, method),
                        )
                    )
    for position in mapping:
        for status in statuses:
            if (
                status.identity == position.input_identity
                and status.method_id == "rmsd"
                and status.status == "planned"
                and getattr(
                    getattr(status.effective_parameters, "reference", None),
                    "kind",
                    None,
                )
                == "external"
            ):
                for role in ("rmsd_external_coordinates", "rmsd_atom_mapping"):
                    records.append(
                        ExpectedArtifact(
                            role=role,
                            path=position.directory
                            + "/preprocessing/"
                            + role
                            + ".json",
                            schema_version="mania." + role + ".v1",
                            producer_method="rmsd",
                        )
                    )
    if any(
        s.method_id == "profile_outputs" and s.status == "planned" for s in statuses
    ):
        from mania.preprocessing.run_execution import selected_run_profile

        choice = next(c for c in config.extensions if c.profile == "napi2b.dataset.v1")
        active = selected_run_profile(choice)
        for role, path, schema in active.run_artifacts(
            **({"exploratory": True} if config.mode == "exploratory" else {})
        ):
            records.append(
                ExpectedArtifact(
                    role=role,
                    path="profiles/p0001/" + path,
                    schema_version=schema,
                    producer_method="profile_outputs",
                )
            )
    if config.mode == "exploratory" and config.output.retain_perframe:
        records = [
            r.model_copy(update={"producer_method": "contacts"})
            if r.role == "protein_contacts_perframe"
            else r
            for r in records
        ]
    return tuple(records)
