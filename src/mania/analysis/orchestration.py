"""Stage 24.C orchestration for accepted MANIA analysis artifacts."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from mania.analysis.conformation_clustering import (
    CONFORMATION_CLUSTERING_BASES,
    CONFORMATION_CLUSTERING_BASIS_FINGERPRINT,
    CONFORMATION_CLUSTERING_BASIS_PCA,
    ConformationClustering,
    ConformationClusteringBasis,
    build_conformation_clusters,
    write_conformation_labels_csv,
)
from mania.analysis.conformation_pca import (
    CONFORMATION_PCA_STATUS_FAILED,
    ConformationPcaProjection,
    build_conformation_pca_projection,
    write_conformation_pca_csv,
)
from mania.analysis.contact_fingerprints import (
    ContactFingerprintMatrix,
    build_contact_fingerprint_matrix,
)
from mania.analysis.extended_metrics import (
    clustering_metadata_for_basis,
    write_extended_metrics_manifest,
)
from mania.analysis.static_rin_communities import (
    StaticRinCommunities,
    compute_static_rin_communities,
    write_static_rin_communities_csv,
)
from mania.analysis.static_rin_comparison import (
    StaticRinComparison,
    compare_static_rin_metrics_from_artifacts,
    write_static_rin_comparison_artifacts,
)
from mania.analysis.static_rin_graph import (
    StaticRinGraph,
    build_static_rin_graph,
    write_static_rin_graph_json,
)
from mania.analysis.static_rin_metrics import (
    StaticRinMetrics,
    compute_static_rin_metrics,
    write_static_rin_metrics_csv,
)
from mania.analysis.static_rin_region_enrichment import (
    StaticRinRegionEnrichment,
    compute_static_rin_region_enrichment,
    write_static_rin_region_enrichment_csv,
)
from mania.analysis.temporal import (
    TemporalRinInput,
    load_temporal_rin_input,
)
from mania.analysis.temporal_rin_metrics import (
    TemporalRinMetrics,
    compute_temporal_rin_metrics,
    write_temporal_rin_csv,
)
from mania.analysis.temporal_rin_windows import (
    TemporalRinWindowGraphBundle,
    build_temporal_rin_window_graphs,
)

ANALYZE_STAGE = "24.C"
ANALYZE_COMMAND = "analyze"

_ANALYSIS_DIRNAME = "analysis"
_CONDITION_COMPONENT_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_EDGE_SEMANTICS_FILENAME = "edge_semantics.json"
_MANIA_MANIFEST_FILENAME = "mania_manifest.json"
_MANIA_RESIDUE_LIBRARY_FILENAME = "mania_residue_library.json"


class AnalyzeError(ValueError):
    """Raised when ``mania analyze`` cannot complete safely."""


@dataclass(frozen=True)
class AnalyzeRequest:
    """Validated inputs for Stage 24.C analysis orchestration."""

    input_root: Path
    output_root: Path
    conditions: tuple[str, ...]
    enable_pca: bool = False
    clustering_basis: ConformationClusteringBasis = "fingerprint"
    pca_components_for_clustering: int | None = None


@dataclass(frozen=True)
class AnalyzeSkip:
    """One honest nonfatal skipped orchestration step."""

    stage: str
    reason: str
    condition: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic JSON-safe summary."""
        return {
            "condition": self.condition,
            "reason": self.reason,
            "stage": self.stage,
        }


@dataclass(frozen=True)
class AnalyzeDiagnosticIssue:
    """One deterministic diagnostic issue for a completed run summary."""

    kind: str
    message: str
    condition: str | None = None
    path: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic JSON-safe summary."""
        return {
            "condition": self.condition,
            "kind": self.kind,
            "message": self.message,
            "path": self.path,
        }


@dataclass(frozen=True)
class AnalyzeConditionResult:
    """Per-condition Stage 24.C artifact summary."""

    condition: str
    graph_json: Path
    centrality_csv: Path
    communities_csv: Path
    region_enrichment_csv: Path
    temporal_rin_csv: Path
    conformation_pca_csv: Path
    conformation_labels_csv: Path
    temporal_status: str
    region_enrichment_status: str
    pca_status: str
    pca_n_components: int
    clustering_status: str
    clustering_algorithm: str
    clustering_input_source: str
    clustering_pca_status: str
    clustering_selected_k: int | None
    pca_components_used_for_clustering: int | None
    pca_max_components: int
    pca_exported_component_count: int
    pca_used_for_clustering: bool

    @property
    def artifacts(self) -> tuple[Path, ...]:
        """Return artifacts in accepted per-condition write order."""
        return (
            self.graph_json,
            self.centrality_csv,
            self.communities_csv,
            self.region_enrichment_csv,
            self.temporal_rin_csv,
            self.conformation_pca_csv,
            self.conformation_labels_csv,
        )


@dataclass(frozen=True)
class AnalyzeRunResult:
    """Completed Stage 24.C/24.D run summary."""

    request: AnalyzeRequest
    analysis_root: Path
    condition_results: tuple[AnalyzeConditionResult, ...]
    comparison_csv: Path
    stats_csv: Path
    extended_metrics_json: Path | None = None
    skipped: tuple[AnalyzeSkip, ...] = ()
    diagnostics_issues: tuple[AnalyzeDiagnosticIssue, ...] = ()

    @property
    def current_run_artifacts(self) -> tuple[Path, ...]:
        """Return current-run scientific artifacts before the manifest."""
        condition_artifacts = tuple(
            artifact
            for result in self.condition_results
            for artifact in result.artifacts
        )
        return condition_artifacts + (self.comparison_csv, self.stats_csv)

    @property
    def artifacts(self) -> tuple[Path, ...]:
        """Return all owned artifacts in deterministic order."""
        if self.extended_metrics_json is None:
            return self.current_run_artifacts
        return self.current_run_artifacts + (self.extended_metrics_json,)

    def to_summary(self) -> dict[str, object]:
        """Return the compact deterministic stdout JSON payload."""
        return {
            "artifacts": {
                "count": len(self.artifacts),
                "written": [
                    _portable_artifact_path(path, self.request.output_root)
                    for path in self.artifacts
                ],
            },
            "clustering": {
                "basis": self.request.clustering_basis,
                "pca_components_for_clustering": (
                    self.request.pca_components_for_clustering
                ),
            },
            "command": ANALYZE_COMMAND,
            "condition_results": [
                {
                    "artifacts": [
                        _portable_artifact_path(path, self.request.output_root)
                        for path in result.artifacts
                    ],
                    "clustering_status": result.clustering_status,
                    "condition": result.condition,
                    "pca_status": result.pca_status,
                    "temporal_status": result.temporal_status,
                }
                for result in self.condition_results
            ],
            "conditions": list(self.request.conditions),
            "diagnostics": {
                "issues": [
                    issue.to_dict() for issue in self.diagnostics_issues
                ],
            },
            "passed": True,
            "pca": {
                "enabled": self.request.enable_pca,
            },
            "skipped": [skip.to_dict() for skip in self.skipped],
            "stage": ANALYZE_STAGE,
        }


@dataclass(frozen=True)
class _ConditionInputPaths:
    condition: str
    residue_table: Path
    protein_contact_edges: Path
    contacts_perframe: Path
    edge_semantics: Path | None
    mania_manifest: Path | None
    mania_residue_library: Path | None


@dataclass(frozen=True)
class _ConditionComputation:
    condition: str
    graph: StaticRinGraph
    metrics: StaticRinMetrics
    communities: StaticRinCommunities
    enrichment: StaticRinRegionEnrichment
    temporal_input: TemporalRinInput
    window_graphs: TemporalRinWindowGraphBundle
    temporal_metrics: TemporalRinMetrics
    fingerprints: ContactFingerprintMatrix
    pca_projection: ConformationPcaProjection
    clustering: ConformationClustering


def run_analysis(request: AnalyzeRequest) -> AnalyzeRunResult:
    """Run accepted Stage 21/22 analysis over existing Stage 20 artifacts."""
    _validate_request(request)
    condition_paths = tuple(
        _condition_input_paths(request.input_root, condition)
        for condition in request.conditions
    )
    computations = tuple(
        _compute_condition(paths, request=request) for paths in condition_paths
    )
    analysis_root = _analysis_root(request.output_root)
    _validate_owned_output_dirs(analysis_root, request.conditions)
    condition_results = tuple(
        _write_condition_artifacts(
            computation,
            analysis_root,
            request=request,
        )
        for computation in computations
    )
    comparison_csv, stats_csv, comparison_skip = _write_comparison_artifacts(
        request,
        analysis_root,
        condition_results,
    )
    skipped = () if comparison_skip is None else (comparison_skip,)
    result = AnalyzeRunResult(
        request=request,
        analysis_root=analysis_root,
        condition_results=condition_results,
        comparison_csv=comparison_csv,
        stats_csv=stats_csv,
        skipped=skipped,
    )
    manifest_path = write_extended_metrics_manifest(result)
    return replace(result, extended_metrics_json=manifest_path)


def _validate_request(request: AnalyzeRequest) -> None:
    if not isinstance(request, AnalyzeRequest):
        raise TypeError("request must be an AnalyzeRequest")
    if not isinstance(request.input_root, Path):
        raise AnalyzeError("input_root must be a pathlib.Path")
    if not isinstance(request.output_root, Path):
        raise AnalyzeError("output_root must be a pathlib.Path")
    if not isinstance(request.conditions, tuple):
        raise AnalyzeError("conditions must be a tuple of strings")
    if type(request.enable_pca) is not bool:
        raise AnalyzeError("enable_pca must be a bool")
    if request.clustering_basis not in CONFORMATION_CLUSTERING_BASES:
        raise AnalyzeError("clustering_basis must be 'fingerprint' or 'pca'")
    _validate_pca_component_option(request)
    _validate_input_root(request.input_root)
    _validate_output_root(request.output_root)
    _validate_conditions(request.conditions)
    if (
        request.clustering_basis == CONFORMATION_CLUSTERING_BASIS_PCA
        and not request.enable_pca
    ):
        raise AnalyzeError("clustering_basis='pca' requires enable_pca=True")
    if (
        request.clustering_basis == CONFORMATION_CLUSTERING_BASIS_FINGERPRINT
        and request.pca_components_for_clustering is not None
    ):
        raise AnalyzeError(
            "pca_components_for_clustering requires clustering_basis='pca'"
        )


def _validate_pca_component_option(request: AnalyzeRequest) -> None:
    value = request.pca_components_for_clustering
    if value is None:
        return
    if type(value) is not int:
        raise AnalyzeError("pca_components_for_clustering must be an integer")
    if value < 1:
        raise AnalyzeError("pca_components_for_clustering must be >= 1")


def _validate_input_root(input_root: Path) -> None:
    if not input_root.exists():
        raise AnalyzeError(f"input root does not exist: {input_root}")
    if not input_root.is_dir():
        raise AnalyzeError(f"input root is not a directory: {input_root}")


def _validate_output_root(output_root: Path) -> None:
    if output_root.exists() and not output_root.is_dir():
        raise AnalyzeError(f"output root is not a directory: {output_root}")
    current = output_root
    missing: list[Path] = []
    while not current.exists():
        missing.append(current)
        parent = current.parent
        if parent == current:
            break
        current = parent
    if current.exists() and not current.is_dir():
        raise AnalyzeError(f"output root parent is not a directory: {current}")
    analysis_root = _analysis_root(output_root)
    if analysis_root.exists() and not analysis_root.is_dir():
        raise AnalyzeError(f"analysis output path is not a directory: {analysis_root}")
    if missing:
        return


def _validate_conditions(conditions: tuple[str, ...]) -> None:
    if not conditions:
        raise AnalyzeError("at least one condition is required")
    seen: set[str] = set()
    for condition in conditions:
        _validate_condition(condition)
        if condition in seen:
            raise AnalyzeError(f"duplicate condition: {condition}")
        seen.add(condition)


def _validate_condition(condition: object) -> None:
    if not isinstance(condition, str):
        raise AnalyzeError("condition names must be strings")
    if not condition:
        raise AnalyzeError("condition names must be non-empty")
    if condition.strip() != condition:
        raise AnalyzeError(f"unsafe condition name: {condition!r}")
    path = Path(condition)
    if path.is_absolute() or len(path.parts) != 1 or condition in {".", ".."}:
        raise AnalyzeError(f"unsafe condition name: {condition!r}")
    try:
        _condition_filename_component(condition)
    except AnalyzeError as error:
        raise AnalyzeError(f"unsafe condition name: {condition!r}") from error


def _condition_input_paths(input_root: Path, condition: str) -> _ConditionInputPaths:
    manifest_refs = _manifest_condition_artifact_paths(input_root, condition)
    component = _condition_filename_component(condition)
    residue_table = manifest_refs.get(
        "residue_table",
        input_root / f"residue_table_{component}.csv",
    )
    protein_contact_edges = manifest_refs.get(
        "protein_contact_edges",
        input_root / f"protein_contact_edges_undirected_{component}.csv",
    )
    contacts_perframe = manifest_refs.get(
        "contacts_perframe",
        input_root / f"contacts_perframe_{component}.csv",
    )
    required = {
        "residue_table": residue_table,
        "protein_contact_edges": protein_contact_edges,
        "contacts_perframe": contacts_perframe,
    }
    for label, path in required.items():
        _require_file(path, label=label, condition=condition)
    edge_semantics = _optional_root_file(input_root / _EDGE_SEMANTICS_FILENAME)
    mania_manifest = _optional_root_file(input_root / _MANIA_MANIFEST_FILENAME)
    mania_residue_library = _optional_root_file(
        input_root / _MANIA_RESIDUE_LIBRARY_FILENAME
    )
    return _ConditionInputPaths(
        condition=condition,
        residue_table=residue_table,
        protein_contact_edges=protein_contact_edges,
        contacts_perframe=contacts_perframe,
        edge_semantics=edge_semantics,
        mania_manifest=mania_manifest,
        mania_residue_library=mania_residue_library,
    )


def _condition_filename_component(condition: str) -> str:
    component = re.sub(r"[^A-Za-z0-9_.-]+", "_", condition).strip("._")
    if not component:
        raise AnalyzeError("condition must contain a filename-safe character")
    if not _CONDITION_COMPONENT_RE.fullmatch(component):
        raise AnalyzeError("condition must contain a filename-safe character")
    return component


def _manifest_condition_artifact_paths(
    input_root: Path,
    condition: str,
) -> dict[str, Path]:
    manifest_path = input_root / _MANIA_MANIFEST_FILENAME
    if not manifest_path.exists():
        return {}
    if not manifest_path.is_file():
        raise AnalyzeError(
            f"optional root artifact is not a file: {manifest_path.name}"
        )
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AnalyzeError(
            f"mania_manifest.json could not be read: {error.__class__.__name__}"
        ) from error
    if not isinstance(payload, dict):
        raise AnalyzeError("mania_manifest.json must contain a JSON object")
    produced = payload.get("produced_artifacts")
    if produced is None:
        return {}
    if not isinstance(produced, list):
        raise AnalyzeError("mania_manifest.json produced_artifacts must be a list")

    by_label: dict[str, Path] = {}
    role_to_label = {
        "residue table": "residue_table",
        "protein contact edges": "protein_contact_edges",
        "per-frame protein contacts": "contacts_perframe",
    }
    for item in produced:
        if not isinstance(item, dict) or item.get("condition") != condition:
            continue
        role = item.get("role")
        label = role_to_label.get(role) if isinstance(role, str) else None
        if label is None:
            continue
        filename = item.get("filename")
        if not isinstance(filename, str) or not filename:
            raise AnalyzeError(
                "mania_manifest.json artifact filename must be a non-empty string"
            )
        path = Path(filename)
        if path.is_absolute() or path.name != filename:
            raise AnalyzeError(
                "mania_manifest.json artifact filename must be portable"
            )
        if label in by_label:
            raise AnalyzeError(
                "mania_manifest.json contains duplicate artifact references "
                f"for condition {condition!r}"
            )
        by_label[label] = input_root / filename
    return by_label


def _require_file(path: Path, *, label: str, condition: str) -> None:
    if not path.exists():
        raise AnalyzeError(
            f"missing required {label} artifact for condition "
            f"{condition!r}: {path.name}"
        )
    if not path.is_file():
        raise AnalyzeError(
            f"required {label} artifact is not a file for condition "
            f"{condition!r}: {path.name}"
        )


def _optional_root_file(path: Path) -> Path | None:
    if not path.exists():
        return None
    if not path.is_file():
        raise AnalyzeError(f"optional root artifact is not a file: {path.name}")
    return path


def _compute_condition(
    paths: _ConditionInputPaths,
    *,
    request: AnalyzeRequest,
) -> _ConditionComputation:
    try:
        graph = build_static_rin_graph(
            paths.residue_table,
            paths.protein_contact_edges,
            edge_semantics_path=paths.edge_semantics,
            mania_manifest_path=paths.mania_manifest,
            residue_library_path=paths.mania_residue_library,
        )
        if graph.condition != paths.condition:
            raise AnalyzeError(
                "condition/artifact mismatch: expected "
                f"{paths.condition!r}, got {graph.condition!r}"
            )
        metrics = compute_static_rin_metrics(graph)
        communities = compute_static_rin_communities(graph)
        enrichment = compute_static_rin_region_enrichment(graph, communities)
        temporal_input = load_temporal_rin_input(
            paths.contacts_perframe,
            condition=paths.condition,
        )
        window_graphs = build_temporal_rin_window_graphs(temporal_input)
        temporal_metrics = compute_temporal_rin_metrics(window_graphs)
        fingerprints = build_contact_fingerprint_matrix(temporal_input)
        pca_projection = build_conformation_pca_projection(
            fingerprints,
            enable_pca=request.enable_pca,
        )
        _validate_requested_pca_projection(
            pca_projection,
            request=request,
            condition=paths.condition,
        )
        pca_projection_for_clustering = (
            pca_projection
            if request.clustering_basis == CONFORMATION_CLUSTERING_BASIS_PCA
            else pca_projection
        )
        clustering = build_conformation_clusters(
            fingerprints,
            clustering_basis=request.clustering_basis,
            pca_projection=pca_projection_for_clustering,
            pca_components_for_clustering=(
                request.pca_components_for_clustering
            ),
        )
    except AnalyzeError:
        raise
    except (OSError, TypeError, ValueError) as error:
        raise AnalyzeError(
            f"analysis failed for condition {paths.condition!r}: {error}"
        ) from error
    return _ConditionComputation(
        condition=paths.condition,
        graph=graph,
        metrics=metrics,
        communities=communities,
        enrichment=enrichment,
        temporal_input=temporal_input,
        window_graphs=window_graphs,
        temporal_metrics=temporal_metrics,
        fingerprints=fingerprints,
        pca_projection=pca_projection,
        clustering=clustering,
    )


def _validate_owned_output_dirs(
    analysis_root: Path,
    conditions: tuple[str, ...],
) -> None:
    if analysis_root.exists() and not analysis_root.is_dir():
        raise AnalyzeError(f"analysis output path is not a directory: {analysis_root}")
    for condition in conditions:
        condition_root = analysis_root / condition
        if condition_root.exists() and not condition_root.is_dir():
            raise AnalyzeError(
                f"condition output path is not a directory: {condition_root}"
            )


def _write_condition_artifacts(
    computation: _ConditionComputation,
    analysis_root: Path,
    *,
    request: AnalyzeRequest,
) -> AnalyzeConditionResult:
    condition_root = analysis_root / computation.condition
    try:
        graph_json = write_static_rin_graph_json(
            computation.graph,
            condition_root / "graph.json",
        )
        centrality_csv = write_static_rin_metrics_csv(
            computation.metrics,
            condition_root,
        )
        communities_csv = write_static_rin_communities_csv(
            computation.communities,
            condition_root,
        )
        region_enrichment_csv = write_static_rin_region_enrichment_csv(
            computation.enrichment,
            condition_root,
        )
        temporal_rin_csv = write_temporal_rin_csv(
            computation.temporal_metrics,
            condition_root,
        )
        conformation_pca_csv = write_conformation_pca_csv(
            computation.pca_projection,
            condition_root,
        )
        conformation_labels_csv = write_conformation_labels_csv(
            computation.clustering,
            condition_root,
        )
    except (OSError, TypeError, ValueError) as error:
        raise AnalyzeError(
            f"analysis artifact write failed for condition "
            f"{computation.condition!r}: {error}"
        ) from error
    (
        clustering_algorithm,
        clustering_input_source,
        clustering_pca_status,
    ) = clustering_metadata_for_basis(
        request.clustering_basis,
        pca_status=computation.pca_projection.status,
    )
    pca_components_used_for_clustering = (
        _pca_components_used_for_clustering(computation, request=request)
    )
    return AnalyzeConditionResult(
        condition=computation.condition,
        graph_json=graph_json,
        centrality_csv=centrality_csv,
        communities_csv=communities_csv,
        region_enrichment_csv=region_enrichment_csv,
        temporal_rin_csv=temporal_rin_csv,
        conformation_pca_csv=conformation_pca_csv,
        conformation_labels_csv=conformation_labels_csv,
        temporal_status=computation.window_graphs.status,
        region_enrichment_status=_region_enrichment_status(computation.enrichment),
        pca_status=computation.pca_projection.status,
        pca_n_components=computation.pca_projection.n_components,
        clustering_status=computation.clustering.status,
        clustering_algorithm=clustering_algorithm,
        clustering_input_source=clustering_input_source,
        clustering_pca_status=clustering_pca_status,
        clustering_selected_k=computation.clustering.selected_k,
        pca_components_used_for_clustering=pca_components_used_for_clustering,
        pca_max_components=computation.pca_projection.max_components,
        pca_exported_component_count=(
            computation.pca_projection.exported_component_count
        ),
        pca_used_for_clustering=(
            request.clustering_basis == CONFORMATION_CLUSTERING_BASIS_PCA
        ),
    )


def _write_comparison_artifacts(
    request: AnalyzeRequest,
    analysis_root: Path,
    condition_results: tuple[AnalyzeConditionResult, ...],
) -> tuple[Path, Path, AnalyzeSkip | None]:
    skip: AnalyzeSkip | None = None
    if len(condition_results) < 2:
        comparison = StaticRinComparison(
            conditions=request.conditions,
            comparison_rows=(),
            stats_rows=(),
        )
        skip = AnalyzeSkip(
            stage="cross_condition_comparison",
            reason="requires at least two conditions",
        )
    else:
        centrality_paths = tuple(
            result.centrality_csv for result in condition_results
        )
        try:
            comparison = compare_static_rin_metrics_from_artifacts(
                centrality_paths
            )
        except (OSError, TypeError, ValueError) as error:
            raise AnalyzeError(
                f"cross-condition comparison failed: {error}"
            ) from error
    try:
        artifacts = write_static_rin_comparison_artifacts(
            comparison,
            analysis_root,
        )
    except (OSError, TypeError, ValueError) as error:
        raise AnalyzeError(
            f"cross-condition comparison artifact write failed: {error}"
        ) from error
    return artifacts.comparison_csv, artifacts.stats_csv, skip


def _region_enrichment_status(enrichment: StaticRinRegionEnrichment) -> str:
    statuses = tuple(row.status for row in enrichment.rows)
    if "computed" in statuses:
        return "computed"
    if statuses:
        return statuses[0]
    return "skipped_empty_graph"


def _pca_components_used_for_clustering(
    computation: _ConditionComputation,
    *,
    request: AnalyzeRequest,
) -> int | None:
    if request.clustering_basis != CONFORMATION_CLUSTERING_BASIS_PCA:
        return None
    if computation.pca_projection.n_components <= 0:
        return None
    return (
        request.pca_components_for_clustering
        if request.pca_components_for_clustering is not None
        else computation.pca_projection.n_components
    )


def _validate_requested_pca_projection(
    projection: ConformationPcaProjection,
    *,
    request: AnalyzeRequest,
    condition: str,
) -> None:
    if not request.enable_pca:
        return
    if projection.status == CONFORMATION_PCA_STATUS_FAILED:
        raise AnalyzeError(
            "requested PCA computation failed for condition "
            f"{condition!r}: {projection.status}"
        )


def _analysis_root(output_root: Path) -> Path:
    return output_root / _ANALYSIS_DIRNAME


def _portable_artifact_path(path: Path, output_root: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(
            output_root.resolve(strict=False)
        ).as_posix()
    except ValueError:
        return path.name


def summary_to_json_payload(result: AnalyzeRunResult) -> Mapping[str, Any]:
    """Return the stdout summary payload for callers that need a mapping."""
    return result.to_summary()


__all__ = [
    "ANALYZE_COMMAND",
    "ANALYZE_STAGE",
    "AnalyzeConditionResult",
    "AnalyzeDiagnosticIssue",
    "AnalyzeError",
    "AnalyzeRequest",
    "AnalyzeRunResult",
    "AnalyzeSkip",
    "run_analysis",
    "summary_to_json_payload",
]
