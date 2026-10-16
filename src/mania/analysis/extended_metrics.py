"""MANIA-only Stage 24.D extended analysis manifest."""

from __future__ import annotations

import json
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from mania.analysis.conformation_clustering import (
    CONFORMATION_CLUSTERING_ALGORITHM_FINGERPRINT,
    CONFORMATION_CLUSTERING_ALGORITHM_PCA,
    CONFORMATION_CLUSTERING_BASIS_PCA,
    CONFORMATION_CLUSTERING_INPUT_SOURCE_FINGERPRINT,
    CONFORMATION_CLUSTERING_INPUT_SOURCE_PCA,
    CONFORMATION_CLUSTERING_STATUS_COMPUTED,
)
from mania.analysis.conformation_pca import (
    CONFORMATION_PCA_STATUS_COMPUTED,
    CONFORMATION_PCA_STATUS_FAILED,
    CONFORMATION_PCA_STATUS_UNAVAILABLE,
)

if TYPE_CHECKING:
    from mania.analysis.orchestration import (
        AnalyzeConditionResult,
        AnalyzeDiagnosticIssue,
        AnalyzeRunResult,
    )

EXTENDED_METRICS_SCHEMA_VERSION = "mania.extended_metrics.v0.1"
EXTENDED_METRICS_KIND = "mania_analysis_manifest"
EXTENDED_METRICS_STAGE = "24.D"
EXTENDED_METRICS_FILENAME = "extended_metrics.json"

MANIFEST_STATUS_COMPUTED = "computed"
MANIFEST_STATUS_NOT_REQUESTED = "not_requested"
MANIFEST_STATUS_SKIPPED = "skipped"
MANIFEST_STATUS_NOT_APPLICABLE = "not_applicable"
MANIFEST_STATUS_UNAVAILABLE = "unavailable"
MANIFEST_STATUS_FAILED = "failed"

EXTENDED_METRICS_LIMITATIONS = (
    "api_frontend_integration_not_implemented",
    "fingerprint_and_pca_clustering_are_distinct",
    "full_statistical_parity_unavailable",
    "louvain_unavailable",
    "notebook_pca_parity_not_claimed",
    "pca_clustering_uses_internal_deterministic_kmeans",
    "wania_integration_not_implemented",
)


class ExtendedMetricsError(ValueError):
    """Raised when the Stage 24.D manifest cannot be built or written."""


def build_extended_metrics_manifest(
    result: AnalyzeRunResult,
) -> dict[str, object]:
    """Build a compact JSON-safe manifest from current-run analysis state."""
    return {
        "schema_version": EXTENDED_METRICS_SCHEMA_VERSION,
        "kind": EXTENDED_METRICS_KIND,
        "stage": EXTENDED_METRICS_STAGE,
        "conditions": list(result.request.conditions),
        "configuration": {
            "pca_enabled": result.request.enable_pca,
            "clustering_basis": result.request.clustering_basis,
            "pca_components_for_clustering": (
                result.request.pca_components_for_clustering
            ),
        },
        "condition_results": [
            _condition_result_to_manifest(condition_result, result)
            for condition_result in result.condition_results
        ],
        "run_results": _run_results_to_manifest(result),
        "diagnostics": {
            "passed": True,
            "issues": [
                _diagnostic_issue_to_manifest(issue, result)
                for issue in result.diagnostics_issues
            ],
        },
        "limitations": list(EXTENDED_METRICS_LIMITATIONS),
    }


def write_extended_metrics_manifest(result: AnalyzeRunResult) -> Path:
    """Write ``analysis/extended_metrics.json`` deterministically."""
    output_path = result.analysis_root / EXTENDED_METRICS_FILENAME
    payload = build_extended_metrics_manifest(result)
    _validate_manifest_artifact_references(payload)
    encoded = (
        json.dumps(payload, allow_nan=False, indent=2, sort_keys=True) + "\n"
    )
    temporary_path: Path | None = None
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as json_file:
            temporary_path = Path(json_file.name)
            json_file.write(encoded)
        temporary_path.replace(output_path)
    except OSError as error:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise ExtendedMetricsError(
            f"extended metrics manifest could not be written: {output_path.name}"
        ) from error
    return output_path


def _condition_result_to_manifest(
    condition_result: AnalyzeConditionResult,
    result: AnalyzeRunResult,
) -> dict[str, object]:
    return {
        "condition": condition_result.condition,
        "analyses": {
            "static_rin": {
                "status": MANIFEST_STATUS_COMPUTED,
                "artifacts": {
                    "graph": _owned_artifact_reference(
                        condition_result.graph_json,
                        result,
                    ),
                },
            },
            "centrality": {
                "status": MANIFEST_STATUS_COMPUTED,
                "artifacts": {
                    "centrality": _owned_artifact_reference(
                        condition_result.centrality_csv,
                        result,
                    ),
                },
            },
            "communities": {
                "status": MANIFEST_STATUS_COMPUTED,
                "algorithm": "greedy_modularity_unweighted",
                "artifacts": {
                    "communities": _owned_artifact_reference(
                        condition_result.communities_csv,
                        result,
                    ),
                },
            },
            "region_enrichment": _region_enrichment_summary(
                condition_result,
                result,
            ),
            "temporal_rin": _temporal_rin_summary(condition_result, result),
            "conformation_pca": _pca_summary(condition_result, result),
            "conformation_clustering": _clustering_summary(
                condition_result,
                result,
            ),
        },
    }


def _region_enrichment_summary(
    condition_result: AnalyzeConditionResult,
    result: AnalyzeRunResult,
) -> dict[str, object]:
    status = _region_enrichment_manifest_status(
        condition_result.region_enrichment_status
    )
    summary: dict[str, object] = {
        "status": status,
        "method": "fisher_exact_two_sided",
        "artifacts": {
            "region_enrichment": _owned_artifact_reference(
                condition_result.region_enrichment_csv,
                result,
            ),
        },
    }
    if status != MANIFEST_STATUS_COMPUTED:
        summary["reason"] = condition_result.region_enrichment_status
    return summary


def _temporal_rin_summary(
    condition_result: AnalyzeConditionResult,
    result: AnalyzeRunResult,
) -> dict[str, object]:
    status = _computed_or_skipped(condition_result.temporal_status)
    summary: dict[str, object] = {
        "status": status,
        "artifacts": {
            "temporal_rin": _owned_artifact_reference(
                condition_result.temporal_rin_csv,
                result,
            ),
        },
    }
    if status != MANIFEST_STATUS_COMPUTED:
        summary["reason"] = condition_result.temporal_status
    return summary


def _pca_summary(
    condition_result: AnalyzeConditionResult,
    result: AnalyzeRunResult,
) -> dict[str, object]:
    status = _pca_manifest_status(
        condition_result.pca_status,
        pca_enabled=result.request.enable_pca,
    )
    summary: dict[str, object] = {
        "enabled": result.request.enable_pca,
        "status": status,
        "max_components": condition_result.pca_max_components,
        "computed_component_count": condition_result.pca_n_components,
        "exported_component_count": (
            condition_result.pca_exported_component_count
        ),
        "artifacts": {
            "conformation_pca": _owned_artifact_reference(
                condition_result.conformation_pca_csv,
                result,
            ),
        },
    }
    if status == MANIFEST_STATUS_COMPUTED:
        summary["backend"] = "numpy_svd"
        summary["n_components"] = condition_result.pca_n_components
    else:
        summary["reason"] = (
            "pca_not_requested"
            if status == MANIFEST_STATUS_NOT_REQUESTED
            else condition_result.pca_status
        )
    return summary


def _clustering_summary(
    condition_result: AnalyzeConditionResult,
    result: AnalyzeRunResult,
) -> dict[str, object]:
    status = _computed_or_skipped(condition_result.clustering_status)
    summary: dict[str, object] = {
        "status": status,
        "basis": result.request.clustering_basis,
        "algorithm": condition_result.clustering_algorithm,
        "input_source": condition_result.clustering_input_source,
        "pca_status": condition_result.clustering_pca_status,
        "pca_used_for_clustering": condition_result.pca_used_for_clustering,
        "pca_components_requested": (
            result.request.pca_components_for_clustering
        ),
        "pca_components_used": (
            condition_result.pca_components_used_for_clustering
        ),
        "artifacts": {
            "conformation_labels": _owned_artifact_reference(
                condition_result.conformation_labels_csv,
                result,
            ),
        },
    }
    if status == MANIFEST_STATUS_COMPUTED:
        summary["selected_k"] = condition_result.clustering_selected_k
    else:
        summary["reason"] = condition_result.clustering_status
    return summary


def _run_results_to_manifest(result: AnalyzeRunResult) -> dict[str, object]:
    if len(result.condition_results) < 2:
        status = MANIFEST_STATUS_NOT_APPLICABLE
        reason = "single_condition"
    else:
        status = MANIFEST_STATUS_COMPUTED
        reason = None
    cross_condition: dict[str, object] = {
        "status": status,
        "artifacts": {
            "comparison": _owned_artifact_reference(result.comparison_csv, result),
            "stats": _owned_artifact_reference(result.stats_csv, result),
        },
    }
    if reason is not None:
        cross_condition["reason"] = reason
    return {"cross_condition": cross_condition}


def _diagnostic_issue_to_manifest(
    issue: AnalyzeDiagnosticIssue,
    result: AnalyzeRunResult,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "code": issue.kind,
        "message": issue.message,
        "scope": "condition" if issue.condition is not None else "run",
    }
    if issue.condition is not None:
        payload["condition"] = issue.condition
    if issue.path is not None:
        path = Path(issue.path)
        try:
            payload["artifact"] = _relative_path(path, result.request.output_root)
        except ExtendedMetricsError:
            pass
    return payload


def _region_enrichment_manifest_status(status: str) -> str:
    if status == MANIFEST_STATUS_COMPUTED:
        return MANIFEST_STATUS_COMPUTED
    if status == "skipped_no_region_labels":
        return MANIFEST_STATUS_UNAVAILABLE
    return MANIFEST_STATUS_SKIPPED


def _pca_manifest_status(status: str, *, pca_enabled: bool) -> str:
    if status == CONFORMATION_PCA_STATUS_COMPUTED:
        return MANIFEST_STATUS_COMPUTED
    if not pca_enabled and status == CONFORMATION_PCA_STATUS_UNAVAILABLE:
        return MANIFEST_STATUS_NOT_REQUESTED
    if status == CONFORMATION_PCA_STATUS_FAILED:
        return MANIFEST_STATUS_FAILED
    return MANIFEST_STATUS_SKIPPED


def _computed_or_skipped(status: str) -> str:
    if status == CONFORMATION_CLUSTERING_STATUS_COMPUTED:
        return MANIFEST_STATUS_COMPUTED
    return MANIFEST_STATUS_SKIPPED


def _owned_artifact_reference(path: Path, result: AnalyzeRunResult) -> str:
    if path not in result.current_run_artifacts:
        raise ExtendedMetricsError(f"artifact is not owned by current run: {path}")
    reference = _relative_path(path, result.request.output_root)
    if not reference.startswith("analysis/"):
        raise ExtendedMetricsError(
            f"artifact reference must be under analysis/: {reference}"
        )
    return reference


def _relative_path(path: Path, output_root: Path) -> str:
    try:
        relative = path.resolve(strict=False).relative_to(
            output_root.resolve(strict=False)
        )
    except ValueError as error:
        raise ExtendedMetricsError(
            f"artifact path is outside output root: {path}"
        ) from error
    if relative.is_absolute() or ".." in relative.parts:
        raise ExtendedMetricsError(f"unsafe artifact reference: {relative}")
    reference = relative.as_posix()
    if (
        reference.startswith("../")
        or reference == ".."
        or "://" in reference
        or reference.startswith("/")
    ):
        raise ExtendedMetricsError(f"unsafe artifact reference: {reference}")
    return reference


def _validate_manifest_artifact_references(payload: Mapping[str, object]) -> None:
    for key, value in _walk_mapping(payload):
        if key == "artifacts":
            if not isinstance(value, Mapping):
                raise ExtendedMetricsError("artifacts must be a JSON object")
            for artifact_path in value.values():
                if not isinstance(artifact_path, str):
                    raise ExtendedMetricsError("artifact references must be strings")
                if (
                    not artifact_path.startswith("analysis/")
                    or artifact_path.startswith("../")
                    or "/../" in artifact_path
                    or artifact_path.startswith("/")
                    or "://" in artifact_path
                ):
                    raise ExtendedMetricsError(
                        f"unsafe artifact reference: {artifact_path}"
                    )


def _walk_mapping(value: object) -> tuple[tuple[str, object], ...]:
    items: list[tuple[str, object]] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            if isinstance(key, str):
                items.append((key, child))
            items.extend(_walk_mapping(child))
    elif isinstance(value, list):
        for child in value:
            items.extend(_walk_mapping(child))
    return tuple(items)


def clustering_metadata_for_basis(
    basis: str,
    *,
    pca_status: str = CONFORMATION_PCA_STATUS_UNAVAILABLE,
) -> tuple[str, str, str]:
    """Return stable clustering method metadata for the requested basis."""
    if basis == CONFORMATION_CLUSTERING_BASIS_PCA:
        return (
            CONFORMATION_CLUSTERING_ALGORITHM_PCA,
            CONFORMATION_CLUSTERING_INPUT_SOURCE_PCA,
            CONFORMATION_PCA_STATUS_COMPUTED,
        )
    return (
        CONFORMATION_CLUSTERING_ALGORITHM_FINGERPRINT,
        CONFORMATION_CLUSTERING_INPUT_SOURCE_FINGERPRINT,
        pca_status,
    )


__all__ = [
    "EXTENDED_METRICS_FILENAME",
    "EXTENDED_METRICS_KIND",
    "EXTENDED_METRICS_LIMITATIONS",
    "EXTENDED_METRICS_SCHEMA_VERSION",
    "EXTENDED_METRICS_STAGE",
    "ExtendedMetricsError",
    "build_extended_metrics_manifest",
    "clustering_metadata_for_basis",
    "write_extended_metrics_manifest",
]
