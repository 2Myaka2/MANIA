"""MANIA backend contract-subset comparison helpers."""

from __future__ import annotations

import math
from collections.abc import Iterable
from pathlib import Path

from mania.comparison.reference import (
    COMPARISON_MODE_CSV_EXACT,
    COMPARISON_MODE_CSV_NUMERIC_TOLERANCE,
    COMPARISON_MODE_JSON_EXACT,
    ArtifactComparisonSpec,
    CSVNumericToleranceComparisonConfig,
    ReferenceComparisonReport,
    compare_artifact_sets,
)

CONTRACT_SUBSET_ROOT_ARTIFACTS = ("run_meta.json",)

CONTRACT_SUBSET_PER_CONDITION_CSV_ARTIFACTS = (
    "rg_timeseries.csv",
    "centrality.csv",
    "communities.csv",
    "nodes.csv",
    "edges.csv",
)

CONTRACT_SUBSET_PER_CONDITION_JSON_ARTIFACTS = ("graph.json",)

DEFAULT_CONTRACT_SUBSET_ABS_TOL = 1e-6

RG_TIMESERIES_KEY_COLUMNS = ("condition", "frame")
RG_TIMESERIES_NUMERIC_COLUMNS = ("time_ps", "rg_A")
RG_TIMESERIES_TEXT_COLUMNS = ()

CENTRALITY_KEY_COLUMNS = ("condition", "resid")
CENTRALITY_NUMERIC_COLUMNS = (
    "degree",
    "strength",
    "betweenness",
    "closeness",
    "eigenvector",
    "pagerank",
    "kcore",
)
CENTRALITY_TEXT_COLUMNS = ()

COMMUNITIES_KEY_COLUMNS = ("condition", "resid")
COMMUNITIES_NUMERIC_COLUMNS = ("community_id", "community_size")
COMMUNITIES_TEXT_COLUMNS = ("algorithm",)

NODES_KEY_COLUMNS = ("condition", "resid")
NODES_NUMERIC_COLUMNS = (
    "x_ca",
    "y_ca",
    "z_ca",
    "tm_relative_z",
    "rmsf_A",
    "sasa_A2",
    "degree",
    "strength",
    "betweenness",
    "closeness",
    "eigenvector",
    "pagerank",
    "kcore",
    "community_id",
)
NODES_TEXT_COLUMNS = (
    "resname",
    "region",
    "ss",
)

EDGES_KEY_COLUMNS = ("condition", "resid_i", "resid_j", "edge_type")
EDGES_NUMERIC_COLUMNS = (
    "n_edge_types",
    "contact_freq",
    "mean_dist_A",
    "std_dist_A",
    "n_episodes",
    "mean_lifetime_frames",
    "max_lifetime_frames",
    "mean_lifetime_ns",
    "max_lifetime_ns",
    "formation_count",
    "breakage_count",
    "first_seen_frame",
    "last_seen_frame",
    "window_cv",
)
EDGES_TEXT_COLUMNS = ("all_edge_types",)

_NUMERIC_TOLERANCE_CSV_PROFILES = {
    "rg_timeseries.csv": (
        RG_TIMESERIES_KEY_COLUMNS,
        RG_TIMESERIES_NUMERIC_COLUMNS,
        RG_TIMESERIES_TEXT_COLUMNS,
    ),
    "centrality.csv": (
        CENTRALITY_KEY_COLUMNS,
        CENTRALITY_NUMERIC_COLUMNS,
        CENTRALITY_TEXT_COLUMNS,
    ),
    "communities.csv": (
        COMMUNITIES_KEY_COLUMNS,
        COMMUNITIES_NUMERIC_COLUMNS,
        COMMUNITIES_TEXT_COLUMNS,
    ),
    "nodes.csv": (
        NODES_KEY_COLUMNS,
        NODES_NUMERIC_COLUMNS,
        NODES_TEXT_COLUMNS,
    ),
    "edges.csv": (
        EDGES_KEY_COLUMNS,
        EDGES_NUMERIC_COLUMNS,
        EDGES_TEXT_COLUMNS,
    ),
}


class ContractSubsetComparisonError(Exception):
    """Raised when contract-subset comparison helpers receive invalid input."""


def build_contract_subset_comparison_specs(
    conditions: Iterable[str],
) -> tuple[ArtifactComparisonSpec, ...]:
    """Build ordered comparison specs for the supported backend contract subset."""
    normalized_conditions = _normalize_conditions(conditions)
    specs = [
        ArtifactComparisonSpec(
            artifact,
            COMPARISON_MODE_JSON_EXACT,
        )
        for artifact in CONTRACT_SUBSET_ROOT_ARTIFACTS
    ]

    for condition in normalized_conditions:
        specs.extend(
            ArtifactComparisonSpec(
                (Path(condition) / artifact).as_posix(),
                COMPARISON_MODE_CSV_EXACT,
            )
            for artifact in CONTRACT_SUBSET_PER_CONDITION_CSV_ARTIFACTS
        )
        specs.extend(
            ArtifactComparisonSpec(
                (Path(condition) / artifact).as_posix(),
                COMPARISON_MODE_JSON_EXACT,
            )
            for artifact in CONTRACT_SUBSET_PER_CONDITION_JSON_ARTIFACTS
        )

    return tuple(specs)


def build_contract_subset_numeric_tolerance_specs(
    conditions: Iterable[str],
    *,
    abs_tol: float = DEFAULT_CONTRACT_SUBSET_ABS_TOL,
) -> tuple[ArtifactComparisonSpec, ...]:
    """Build ordered numeric-tolerant specs for the backend contract subset."""
    _validate_abs_tol(abs_tol)
    normalized_conditions = _normalize_conditions(conditions)
    specs = [
        ArtifactComparisonSpec(
            artifact,
            COMPARISON_MODE_JSON_EXACT,
        )
        for artifact in CONTRACT_SUBSET_ROOT_ARTIFACTS
    ]

    for condition in normalized_conditions:
        specs.extend(
            _numeric_tolerance_csv_spec(condition, artifact, abs_tol)
            for artifact in CONTRACT_SUBSET_PER_CONDITION_CSV_ARTIFACTS
        )
        specs.extend(
            ArtifactComparisonSpec(
                (Path(condition) / artifact).as_posix(),
                COMPARISON_MODE_JSON_EXACT,
            )
            for artifact in CONTRACT_SUBSET_PER_CONDITION_JSON_ARTIFACTS
        )

    return tuple(specs)


def compare_contract_subset(
    expected_root: str | Path,
    actual_root: str | Path,
    conditions: Iterable[str],
) -> ReferenceComparisonReport:
    """Compare expected and actual directories for the supported contract subset."""
    specs = build_contract_subset_comparison_specs(conditions)
    return compare_artifact_sets(expected_root, actual_root, specs)


def compare_contract_subset_numeric_tolerance(
    expected_root: str | Path,
    actual_root: str | Path,
    conditions: Iterable[str],
    *,
    abs_tol: float = DEFAULT_CONTRACT_SUBSET_ABS_TOL,
) -> ReferenceComparisonReport:
    """Compare contract-subset directories with tolerant CSV numeric values."""
    specs = build_contract_subset_numeric_tolerance_specs(
        conditions,
        abs_tol=abs_tol,
    )
    return compare_artifact_sets(expected_root, actual_root, specs)


def _normalize_conditions(conditions: Iterable[str]) -> tuple[str, ...]:
    if isinstance(conditions, str):
        raise ContractSubsetComparisonError(
            "Conditions must be an iterable of condition names, not a string"
        )

    normalized_conditions: list[str] = []
    seen_conditions: set[str] = set()

    for condition in conditions:
        if not isinstance(condition, str):
            raise ContractSubsetComparisonError(
                f"Condition names must be strings: {condition!r}"
            )
        normalized_condition = condition.strip()
        if normalized_condition == "":
            raise ContractSubsetComparisonError("Condition names must not be empty")
        if normalized_condition in seen_conditions:
            raise ContractSubsetComparisonError(
                f"Duplicate condition name: {normalized_condition!r}"
            )
        normalized_conditions.append(normalized_condition)
        seen_conditions.add(normalized_condition)

    return tuple(normalized_conditions)


def _numeric_tolerance_csv_spec(
    condition: str,
    artifact: str,
    abs_tol: float,
) -> ArtifactComparisonSpec:
    key_columns, numeric_columns, text_columns = _NUMERIC_TOLERANCE_CSV_PROFILES[
        artifact
    ]
    return ArtifactComparisonSpec(
        (Path(condition) / artifact).as_posix(),
        COMPARISON_MODE_CSV_NUMERIC_TOLERANCE,
        numeric_tolerance=CSVNumericToleranceComparisonConfig(
            key_columns=key_columns,
            numeric_columns=numeric_columns,
            abs_tol=abs_tol,
            text_columns=text_columns,
        ),
    )


def _validate_abs_tol(abs_tol: float) -> None:
    if abs_tol < 0 or not math.isfinite(abs_tol):
        raise ContractSubsetComparisonError(
            "Absolute tolerance must be a finite non-negative number"
        )


__all__ = [
    "CENTRALITY_KEY_COLUMNS",
    "CENTRALITY_NUMERIC_COLUMNS",
    "CENTRALITY_TEXT_COLUMNS",
    "COMMUNITIES_KEY_COLUMNS",
    "COMMUNITIES_NUMERIC_COLUMNS",
    "COMMUNITIES_TEXT_COLUMNS",
    "CONTRACT_SUBSET_PER_CONDITION_CSV_ARTIFACTS",
    "CONTRACT_SUBSET_PER_CONDITION_JSON_ARTIFACTS",
    "CONTRACT_SUBSET_ROOT_ARTIFACTS",
    "ContractSubsetComparisonError",
    "DEFAULT_CONTRACT_SUBSET_ABS_TOL",
    "EDGES_KEY_COLUMNS",
    "EDGES_NUMERIC_COLUMNS",
    "EDGES_TEXT_COLUMNS",
    "NODES_KEY_COLUMNS",
    "NODES_NUMERIC_COLUMNS",
    "NODES_TEXT_COLUMNS",
    "RG_TIMESERIES_KEY_COLUMNS",
    "RG_TIMESERIES_NUMERIC_COLUMNS",
    "RG_TIMESERIES_TEXT_COLUMNS",
    "build_contract_subset_comparison_specs",
    "build_contract_subset_numeric_tolerance_specs",
    "compare_contract_subset",
    "compare_contract_subset_numeric_tolerance",
]
