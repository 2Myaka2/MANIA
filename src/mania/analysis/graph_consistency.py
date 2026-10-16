"""Topology consistency checks for contract graphs."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from mania.analysis.contract_graph import ContractGraph
from mania.analysis.graph_metrics import (
    GraphMetricsError,
    GraphTopologyMetrics,
    compute_graph_topology_metrics,
)


class GraphConsistencyError(Exception):
    """Raised when graph consistency checks cannot be completed."""


@dataclass(frozen=True)
class GraphMetricMismatch:
    """Mismatch between exported and computed topology metrics."""

    node_id: str
    metric: str
    expected: float
    actual: float
    abs_diff: float
    abs_tol: float
    message: str


@dataclass(frozen=True)
class GraphTopologyConsistencyReport:
    """Structured graph topology consistency report."""

    condition: str
    n_nodes: int
    checked_metrics: tuple[str, ...]
    mismatches: tuple[GraphMetricMismatch, ...]

    @property
    def passed(self) -> bool:
        """Return whether all checked metrics matched."""
        return not self.mismatches

    @property
    def n_mismatches(self) -> int:
        """Return the number of mismatches."""
        return len(self.mismatches)

    def mismatches_by_metric(self, metric: str) -> tuple[GraphMetricMismatch, ...]:
        """Return mismatches for one semantic metric name."""
        return tuple(
            mismatch for mismatch in self.mismatches if mismatch.metric == metric
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable report dictionary."""
        return {
            "condition": self.condition,
            "n_nodes": self.n_nodes,
            "checked_metrics": list(self.checked_metrics),
            "passed": self.passed,
            "n_mismatches": self.n_mismatches,
            "mismatches": [
                {
                    "node_id": mismatch.node_id,
                    "metric": mismatch.metric,
                    "expected": mismatch.expected,
                    "actual": mismatch.actual,
                    "abs_diff": mismatch.abs_diff,
                    "abs_tol": mismatch.abs_tol,
                    "message": mismatch.message,
                }
                for mismatch in self.mismatches
            ],
        }


def check_graph_topology_consistency(
    graph: ContractGraph,
    *,
    abs_tol: float = 1e-6,
    degree_column: str = "degree",
    strength_column: str = "strength",
    weight_column: str = "contact_freq",
) -> GraphTopologyConsistencyReport:
    """Compare exported node topology columns with computed graph metrics."""
    _validate_abs_tol(abs_tol)
    topology_metrics = _compute_topology_metrics(graph, weight_column)
    mismatches: list[GraphMetricMismatch] = []

    for node_id in graph.node_ids:
        node_row = graph.nodes[node_id].row
        node_metrics = topology_metrics.get(node_id)

        degree_expected = _parse_exported_metric(
            node_row,
            degree_column,
            metric="degree",
            node_id=node_id,
        )
        _append_mismatch(
            mismatches,
            node_id=node_id,
            metric="degree",
            expected=degree_expected,
            actual=float(node_metrics.degree),
            abs_tol=abs_tol,
        )

        strength_expected = _parse_exported_metric(
            node_row,
            strength_column,
            metric="strength",
            node_id=node_id,
        )
        _append_mismatch(
            mismatches,
            node_id=node_id,
            metric="strength",
            expected=strength_expected,
            actual=node_metrics.strength,
            abs_tol=abs_tol,
        )

    return GraphTopologyConsistencyReport(
        condition=graph.condition,
        n_nodes=graph.n_nodes,
        checked_metrics=("degree", "strength"),
        mismatches=tuple(mismatches),
    )


def write_graph_topology_consistency_report(
    report: GraphTopologyConsistencyReport,
    path: str | Path,
) -> Path:
    """Write a topology consistency report as JSON and return the output path."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path


def _validate_abs_tol(abs_tol: float) -> None:
    if not math.isfinite(abs_tol) or abs_tol < 0.0:
        raise GraphConsistencyError(f"Invalid abs_tol: {abs_tol!r}")


def _compute_topology_metrics(
    graph: ContractGraph,
    weight_column: str,
) -> GraphTopologyMetrics:
    try:
        return compute_graph_topology_metrics(graph, weight_column=weight_column)
    except GraphMetricsError as exc:
        raise GraphConsistencyError(
            f"Invalid topology metric input: {exc}"
        ) from exc


def _parse_exported_metric(
    row: Mapping[str, str],
    column: str,
    *,
    metric: str,
    node_id: str,
) -> float:
    if column not in row:
        raise GraphConsistencyError(
            f"Missing exported {metric} column {column!r} for node {node_id!r}"
        )
    raw_value = row[column].strip()
    if raw_value == "":
        raise GraphConsistencyError(
            f"Empty exported {metric} value in column {column!r} "
            f"for node {node_id!r}"
        )
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise GraphConsistencyError(
            f"Invalid exported {metric} value {raw_value!r} "
            f"in column {column!r} for node {node_id!r}"
        ) from exc
    if not math.isfinite(value):
        raise GraphConsistencyError(
            f"Non-finite exported {metric} value {raw_value!r} "
            f"in column {column!r} for node {node_id!r}"
        )
    return value


def _append_mismatch(
    mismatches: list[GraphMetricMismatch],
    *,
    node_id: str,
    metric: str,
    expected: float,
    actual: float,
    abs_tol: float,
) -> None:
    abs_diff = abs(expected - actual)
    if abs_diff <= abs_tol:
        return
    message = (
        f"{metric} mismatch for node {node_id}: expected {expected}, "
        f"actual {actual}, abs_diff {abs_diff} exceeds abs_tol {abs_tol}"
    )
    mismatches.append(
        GraphMetricMismatch(
            node_id=node_id,
            metric=metric,
            expected=expected,
            actual=actual,
            abs_diff=abs_diff,
            abs_tol=abs_tol,
            message=message,
        )
    )


__all__ = [
    "GraphConsistencyError",
    "GraphMetricMismatch",
    "GraphTopologyConsistencyReport",
    "check_graph_topology_consistency",
    "write_graph_topology_consistency_report",
]
