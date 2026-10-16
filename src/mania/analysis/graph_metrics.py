"""Lightweight graph metrics for backend graph artifacts."""

from __future__ import annotations

import json
import math
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from mania.analysis.contract_graph import ContractEdge, ContractGraph

_ANALYSIS_METRIC_NAMES = (
    "degree",
    "strength",
    "betweenness",
    "closeness",
    "eigenvector",
    "pagerank",
    "kcore",
)
_PRESERVED_NODE_FIELDS = (
    "id",
    "resid",
    "resname",
    "chain_id",
    "region",
    "ss",
    "rmsf_A",
    "sasa_A2",
    "x",
    "y",
    "z",
    "x_ca",
    "y_ca",
    "z_ca",
)
_FATAL_ISSUE_KINDS = {
    "analysis_graph_empty",
    "analysis_graph_invalid",
    "analysis_metric_failed",
    "community_detection_failed",
}


class GraphMetricsError(Exception):
    """Raised when graph topology metrics cannot be computed."""


@dataclass(frozen=True)
class NodeTopologyMetrics:
    """Topology metrics for one graph node."""

    node_id: str
    degree: int
    strength: float


@dataclass(frozen=True)
class GraphTopologyMetrics:
    """Per-node topology metrics for a contract graph."""

    condition: str
    node_metrics: tuple[NodeTopologyMetrics, ...]

    @property
    def node_ids(self) -> tuple[str, ...]:
        """Return node IDs in graph node order."""
        return tuple(metric.node_id for metric in self.node_metrics)

    @property
    def by_node_id(self) -> Mapping[str, NodeTopologyMetrics]:
        """Return metrics keyed by node ID."""
        return {metric.node_id: metric for metric in self.node_metrics}

    def get(self, node_id: str) -> NodeTopologyMetrics:
        """Return metrics for a known node ID."""
        metrics = self.by_node_id
        if node_id not in metrics:
            raise GraphMetricsError(f"Unknown node ID: {node_id!r}")
        return metrics[node_id]

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable metrics dictionary."""
        return {
            "condition": self.condition,
            "node_metrics": [
                {
                    "node_id": metric.node_id,
                    "degree": metric.degree,
                    "strength": metric.strength,
                }
                for metric in self.node_metrics
            ],
        }


@dataclass(frozen=True)
class AnalysisGraphMetricsOptions:
    """Options for condition-specific backend graph analysis."""

    weight_field: str = "contact_freq"
    compute_communities: bool = True
    louvain_seed: int = 42

    def __post_init__(self) -> None:
        if not isinstance(self.weight_field, str) or not self.weight_field.strip():
            raise ValueError("weight_field must be a non-empty string")
        if not isinstance(self.compute_communities, bool):
            raise ValueError("compute_communities must be a boolean")
        if isinstance(self.louvain_seed, bool) or not isinstance(
            self.louvain_seed, int
        ):
            raise ValueError("louvain_seed must be an integer")


@dataclass(frozen=True)
class AnalysisGraphMetricsIssue:
    """Deterministic issue produced while analyzing a graph artifact."""

    kind: str
    message: str
    condition: str | None = None
    details: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.kind, str) or not self.kind.strip():
            raise ValueError("kind must be a non-empty string")
        if not isinstance(self.message, str) or not self.message.strip():
            raise ValueError("message must be a non-empty string")
        if self.condition is not None and (
            not isinstance(self.condition, str) or not self.condition.strip()
        ):
            raise ValueError("condition must be None or a non-empty string")
        if not isinstance(self.details, Mapping):
            raise ValueError("details must be a mapping")

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe issue dictionary."""
        return {
            "kind": self.kind,
            "message": self.message,
            "condition": self.condition,
            "details": {
                key: _json_safe_scalar(value)
                for key, value in sorted(self.details.items())
            },
        }


@dataclass(frozen=True)
class AnalysisGraphMetricsResult:
    """Condition-specific analysis rows and their deterministic report."""

    passed: bool
    metrics_by_condition: dict[str, list[dict[str, object]]]
    communities_by_condition: dict[str, list[dict[str, object]]]
    report: dict[str, object]
    issues: tuple[AnalysisGraphMetricsIssue, ...]

    def to_dict(self) -> dict[str, object]:
        """Return the complete result as JSON-safe built-in containers."""
        return {
            "passed": self.passed,
            "metrics_by_condition": self.metrics_by_condition,
            "communities_by_condition": self.communities_by_condition,
            "report": self.report,
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class _AnalysisNode:
    id: str
    attributes: Mapping[str, object]


@dataclass(frozen=True)
class _AnalysisEdge:
    source: str
    target: str
    attributes: Mapping[str, object]


@dataclass(frozen=True)
class _ConditionGraph:
    condition: str
    nodes: tuple[_AnalysisNode, ...]
    edges: tuple[_AnalysisEdge, ...]
    adjacency: Mapping[str, frozenset[str]]


def compute_analysis_graph_metrics_from_graph_json(
    graph_json: str | Path | Mapping[str, object],
    *,
    options: AnalysisGraphMetricsOptions | None = None,
) -> AnalysisGraphMetricsResult:
    """Compute analysis v1.3-style metrics from an accepted graph artifact."""
    active_options = options or AnalysisGraphMetricsOptions()
    graphs, issues = _load_condition_graphs(graph_json)
    metrics_by_condition: dict[str, list[dict[str, object]]] = {}
    communities_by_condition: dict[str, list[dict[str, object]]] = {}
    conditions_summary: dict[str, object] = {}
    community_algorithms: list[str] = []

    for condition, graph in sorted(graphs.items()):
        if not graph.nodes:
            metrics_by_condition[condition] = []
            communities_by_condition[condition] = []
            conditions_summary[condition] = {
                "node_count": 0,
                "edge_count": len(graph.edges),
                "community_count": 0,
                "modularity": None,
            }
            continue

        metric_values, metric_issues = _compute_condition_metrics(
            graph,
            weight_field=active_options.weight_field,
        )
        issues.extend(metric_issues)

        community_by_node: dict[str, int | None] = {
            node.id: None for node in graph.nodes
        }
        community_rows: list[dict[str, object]] = []
        modularity: float | None = None
        algorithm = "disabled"
        community_count = 0
        if active_options.compute_communities:
            try:
                communities, algorithm, fallback_used = _detect_communities(
                    graph,
                    seed=active_options.louvain_seed,
                )
                community_algorithms.append(algorithm)
                if fallback_used:
                    issues.append(
                        AnalysisGraphMetricsIssue(
                            kind="community_detection_fallback",
                            condition=condition,
                            message=(
                                "NetworkX Louvain is unavailable under the "
                                "current dependency boundary; deterministic "
                                "greedy modularity was used."
                            ),
                            details={"algorithm": algorithm},
                        )
                    )
                community_by_node, community_rows = _community_output_rows(
                    graph,
                    communities,
                    algorithm=algorithm,
                )
                community_count = len(communities)
                modularity = _modularity(graph.adjacency, communities)
            except Exception:
                issues.append(
                    AnalysisGraphMetricsIssue(
                        kind="community_detection_failed",
                        condition=condition,
                        message="Community detection failed for the condition.",
                    )
                )

        metrics_by_condition[condition] = [
            _metric_output_row(
                node,
                condition=condition,
                metric_values=metric_values,
                community=community_by_node[node.id],
            )
            for node in graph.nodes
        ]
        communities_by_condition[condition] = community_rows
        conditions_summary[condition] = {
            "node_count": len(graph.nodes),
            "edge_count": len(graph.edges),
            "community_count": community_count,
            "modularity": modularity,
        }

    ordered_issues = tuple(sorted(issues, key=_issue_sort_key))
    passed = not any(issue.kind in _FATAL_ISSUE_KINDS for issue in ordered_issues)
    if active_options.compute_communities:
        unique_algorithms = sorted(set(community_algorithms))
        community_algorithm = (
            unique_algorithms[0]
            if len(unique_algorithms) == 1
            else "mixed" if unique_algorithms else "unavailable"
        )
    else:
        community_algorithm = "disabled"
    report: dict[str, object] = {
        "passed": passed,
        "conditions": sorted(graphs),
        "metrics": list(_ANALYSIS_METRIC_NAMES),
        "community_detection": {
            "algorithm": community_algorithm,
            "seed": active_options.louvain_seed,
        },
        "conditions_summary": conditions_summary,
        "issues": [issue.to_dict() for issue in ordered_issues],
    }
    return AnalysisGraphMetricsResult(
        passed=passed,
        metrics_by_condition=metrics_by_condition,
        communities_by_condition=communities_by_condition,
        report=report,
        issues=ordered_issues,
    )


def _load_condition_graphs(
    graph_json: str | Path | Mapping[str, object],
) -> tuple[dict[str, _ConditionGraph], list[AnalysisGraphMetricsIssue]]:
    payload, load_issue = _load_graph_payload(graph_json)
    if load_issue is not None:
        return {}, [load_issue]
    assert payload is not None

    issues: list[AnalysisGraphMetricsIssue] = []
    default_condition = _non_empty_text(payload.get("condition"))
    raw_nodes = _record_sequence(payload.get("nodes"))
    raw_edges = _record_sequence(payload.get("edges"))
    if raw_nodes is None or raw_edges is None:
        issues.append(
            AnalysisGraphMetricsIssue(
                kind="analysis_graph_invalid",
                condition=default_condition,
                message="Graph nodes and edges must be JSON arrays of objects.",
            )
        )
        return {}, issues
    if not raw_nodes:
        issues.append(
            AnalysisGraphMetricsIssue(
                kind="analysis_graph_empty",
                condition=default_condition,
                message="Graph contains no nodes.",
            )
        )
        if default_condition is None:
            return {}, issues
        return {
            default_condition: _ConditionGraph(
                condition=default_condition,
                nodes=(),
                edges=(),
                adjacency={},
            )
        }, issues

    nodes_by_condition: dict[str, dict[str, _AnalysisNode]] = {}
    node_conditions: dict[str, set[str]] = {}
    for index, record in enumerate(raw_nodes):
        if not isinstance(record, Mapping):
            issues.append(
                _invalid_record_issue("node", index, default_condition)
            )
            continue
        condition = _non_empty_text(record.get("condition")) or default_condition
        node_id = _record_identifier(record, ("node_id", "id", "resid"))
        if condition is None or node_id is None:
            issues.append(
                _invalid_record_issue("node", index, condition or default_condition)
            )
            continue
        condition_nodes = nodes_by_condition.setdefault(condition, {})
        if node_id in condition_nodes:
            issues.append(
                AnalysisGraphMetricsIssue(
                    kind="analysis_graph_invalid",
                    condition=condition,
                    message="Graph contains a duplicate node identifier.",
                    details={"node_id": node_id},
                )
            )
            continue
        condition_nodes[node_id] = _AnalysisNode(node_id, dict(record))
        node_conditions.setdefault(node_id, set()).add(condition)

    edges_by_condition: dict[str, list[_AnalysisEdge]] = {
        condition: [] for condition in nodes_by_condition
    }
    for index, record in enumerate(raw_edges):
        if not isinstance(record, Mapping):
            issues.append(
                _invalid_record_issue("edge", index, default_condition)
            )
            continue
        source = _record_identifier(record, ("source", "resid_i"))
        target = _record_identifier(record, ("target", "resid_j"))
        inferred_condition = _edge_condition(
            source,
            target,
            node_conditions=node_conditions,
        )
        condition = (
            _non_empty_text(record.get("condition"))
            or inferred_condition
            or default_condition
        )
        edge_nodes = nodes_by_condition.get(condition or "")
        if (
            source is None
            or target is None
            or condition is None
            or edge_nodes is None
            or source not in edge_nodes
            or target not in edge_nodes
        ):
            issues.append(
                _invalid_record_issue("edge", index, condition or default_condition)
            )
            continue
        edges_by_condition[condition].append(
            _AnalysisEdge(source, target, dict(record))
        )

    graphs: dict[str, _ConditionGraph] = {}
    for condition, condition_nodes in sorted(nodes_by_condition.items()):
        adjacency_sets: dict[str, set[str]] = {
            node_id: set() for node_id in condition_nodes
        }
        edges = edges_by_condition[condition]
        for edge in edges:
            adjacency_sets[edge.source].add(edge.target)
            adjacency_sets[edge.target].add(edge.source)
        graphs[condition] = _ConditionGraph(
            condition=condition,
            nodes=tuple(
                condition_nodes[node_id] for node_id in sorted(condition_nodes)
            ),
            edges=tuple(edges),
            adjacency={
                node_id: frozenset(neighbors)
                for node_id, neighbors in sorted(adjacency_sets.items())
            },
        )
    return graphs, issues


def _load_graph_payload(
    graph_json: str | Path | Mapping[str, object],
) -> tuple[Mapping[str, object] | None, AnalysisGraphMetricsIssue | None]:
    if isinstance(graph_json, Mapping):
        return graph_json, None
    try:
        loaded: object = json.loads(Path(graph_json).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError):
        return None, AnalysisGraphMetricsIssue(
            kind="analysis_graph_invalid",
            message="Graph JSON could not be read as an object.",
        )
    if not isinstance(loaded, Mapping):
        return None, AnalysisGraphMetricsIssue(
            kind="analysis_graph_invalid",
            message="Graph JSON top level must be an object.",
        )
    return cast(Mapping[str, object], loaded), None


def _record_sequence(value: object) -> Sequence[object] | None:
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return value
    return None


def _record_identifier(
    record: Mapping[object, object],
    fields: Sequence[str],
) -> str | None:
    for field_name in fields:
        value = record.get(field_name)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, int) and not isinstance(value, bool):
            return str(value)
    return None


def _non_empty_text(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _edge_condition(
    source: str | None,
    target: str | None,
    *,
    node_conditions: Mapping[str, set[str]],
) -> str | None:
    if source is None or target is None:
        return None
    shared = node_conditions.get(source, set()) & node_conditions.get(target, set())
    return next(iter(shared)) if len(shared) == 1 else None


def _invalid_record_issue(
    record_kind: str,
    index: int,
    condition: str | None,
) -> AnalysisGraphMetricsIssue:
    return AnalysisGraphMetricsIssue(
        kind="analysis_graph_invalid",
        condition=condition,
        message=f"Graph {record_kind} record is invalid.",
        details={"index": index},
    )


def _compute_condition_metrics(
    graph: _ConditionGraph,
    *,
    weight_field: str,
) -> tuple[
    dict[str, dict[str, int | float | None]],
    list[AnalysisGraphMetricsIssue],
]:
    issues: list[AnalysisGraphMetricsIssue] = []
    node_ids = tuple(node.id for node in graph.nodes)
    strengths = {node_id: 0.0 for node_id in node_ids}
    missing_weight_count = 0
    for edge in graph.edges:
        weight = _optional_numeric_weight(edge.attributes.get(weight_field))
        if weight is None:
            weight = 0.0
            missing_weight_count += 1
        strengths[edge.source] += weight
        if edge.target != edge.source:
            strengths[edge.target] += weight
    if missing_weight_count:
        issues.append(
            AnalysisGraphMetricsIssue(
                kind="analysis_weight_field_missing",
                condition=graph.condition,
                message=(
                    "Missing or non-numeric edge weights used the documented "
                    "0.0 strength fallback."
                ),
                details={
                    "edge_count": missing_weight_count,
                    "weight_field": weight_field,
                },
            )
        )

    values: dict[str, dict[str, int | float | None]] = {
        "degree": {
            node_id: len(graph.adjacency[node_id]) for node_id in node_ids
        },
        "strength": {node_id: value for node_id, value in strengths.items()},
    }
    computations: tuple[
        tuple[str, Callable[[], Mapping[str, int | float]]], ...
    ] = (
        ("betweenness", lambda: _betweenness_centrality(graph.adjacency)),
        ("closeness", lambda: _closeness_centrality(graph.adjacency)),
        ("eigenvector", lambda: _eigenvector_centrality(graph.adjacency)),
        ("pagerank", lambda: _pagerank(graph.adjacency)),
        ("kcore", lambda: _core_numbers(graph.adjacency)),
    )
    for metric_name, computation in computations:
        try:
            values[metric_name] = dict(computation())
        except Exception:
            values[metric_name] = {node_id: None for node_id in node_ids}
            issues.append(
                AnalysisGraphMetricsIssue(
                    kind="analysis_metric_failed",
                    condition=graph.condition,
                    message=f"Metric {metric_name} failed for the condition.",
                    details={"metric": metric_name},
                )
            )
    return values, issues


def _optional_numeric_weight(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        numeric = float(value) if isinstance(value, (int, float, str)) else math.nan
    except ValueError:
        return None
    return numeric if math.isfinite(numeric) else None


def _betweenness_centrality(
    adjacency: Mapping[str, frozenset[str]],
) -> dict[str, float]:
    nodes = tuple(sorted(adjacency))
    betweenness = {node: 0.0 for node in nodes}
    for source in nodes:
        stack: list[str] = []
        predecessors: dict[str, list[str]] = {node: [] for node in nodes}
        path_counts = {node: 0.0 for node in nodes}
        path_counts[source] = 1.0
        distance = {node: -1 for node in nodes}
        distance[source] = 0
        queue: deque[str] = deque((source,))
        while queue:
            node = queue.popleft()
            stack.append(node)
            for neighbor in sorted(adjacency[node]):
                if distance[neighbor] < 0:
                    queue.append(neighbor)
                    distance[neighbor] = distance[node] + 1
                if distance[neighbor] == distance[node] + 1:
                    path_counts[neighbor] += path_counts[node]
                    predecessors[neighbor].append(node)
        dependency = {node: 0.0 for node in nodes}
        while stack:
            node = stack.pop()
            if path_counts[node]:
                coefficient = (1.0 + dependency[node]) / path_counts[node]
                for predecessor in predecessors[node]:
                    dependency[predecessor] += (
                        path_counts[predecessor] * coefficient
                    )
            if node != source:
                betweenness[node] += dependency[node]
    if len(nodes) > 2:
        scale = 1.0 / ((len(nodes) - 1) * (len(nodes) - 2))
        betweenness = {
            node: value * scale for node, value in betweenness.items()
        }
    return betweenness


def _closeness_centrality(
    adjacency: Mapping[str, frozenset[str]],
) -> dict[str, float]:
    node_count = len(adjacency)
    values: dict[str, float] = {}
    for source in sorted(adjacency):
        distances = {source: 0}
        queue: deque[str] = deque((source,))
        while queue:
            node = queue.popleft()
            for neighbor in sorted(adjacency[node]):
                if neighbor not in distances:
                    distances[neighbor] = distances[node] + 1
                    queue.append(neighbor)
        reachable = len(distances) - 1
        total_distance = sum(distances.values())
        if total_distance > 0 and node_count > 1:
            values[source] = (reachable / total_distance) * (
                reachable / (node_count - 1)
            )
        else:
            values[source] = 0.0
    return values


def _eigenvector_centrality(
    adjacency: Mapping[str, frozenset[str]],
    *,
    max_iterations: int = 5000,
    tolerance: float = 1e-6,
) -> dict[str, float]:
    nodes = tuple(sorted(adjacency))
    values = {node: 1.0 / len(nodes) for node in nodes}
    for _ in range(max_iterations):
        previous = values
        values = previous.copy()
        for node in nodes:
            for neighbor in adjacency[node]:
                values[neighbor] += previous[node]
        norm = math.sqrt(sum(value * value for value in values.values())) or 1.0
        values = {node: value / norm for node, value in values.items()}
        if sum(abs(values[node] - previous[node]) for node in nodes) < (
            len(nodes) * tolerance
        ):
            return values
    raise ArithmeticError("eigenvector centrality did not converge")


def _pagerank(
    adjacency: Mapping[str, frozenset[str]],
    *,
    damping: float = 0.85,
    max_iterations: int = 100,
    tolerance: float = 1e-6,
) -> dict[str, float]:
    nodes = tuple(sorted(adjacency))
    node_count = len(nodes)
    values = {node: 1.0 / node_count for node in nodes}
    base = (1.0 - damping) / node_count
    for _ in range(max_iterations):
        previous = values
        dangling = damping * sum(
            previous[node] for node in nodes if not adjacency[node]
        ) / node_count
        values = {node: base + dangling for node in nodes}
        for node in nodes:
            if adjacency[node]:
                contribution = damping * previous[node] / len(adjacency[node])
                for neighbor in adjacency[node]:
                    values[neighbor] += contribution
        if sum(abs(values[node] - previous[node]) for node in nodes) < (
            node_count * tolerance
        ):
            return values
    raise ArithmeticError("PageRank did not converge")


def _core_numbers(
    adjacency: Mapping[str, frozenset[str]],
) -> dict[str, int]:
    remaining = set(adjacency)
    core_numbers: dict[str, int] = {}
    current_core = 0
    while remaining:
        node = min(
            remaining,
            key=lambda candidate: (
                sum(neighbor in remaining for neighbor in adjacency[candidate]),
                candidate,
            ),
        )
        remaining_degree = sum(
            neighbor in remaining for neighbor in adjacency[node]
        )
        current_core = max(current_core, remaining_degree)
        core_numbers[node] = current_core
        remaining.remove(node)
    return core_numbers


def _detect_communities(
    graph: _ConditionGraph,
    *,
    seed: int,
) -> tuple[list[set[str]], str, bool]:
    _ = seed
    return _greedy_modularity_communities(graph.adjacency), "greedy_modularity", True


def _greedy_modularity_communities(
    adjacency: Mapping[str, frozenset[str]],
) -> list[set[str]]:
    nodes = tuple(sorted(adjacency))
    simple_edges = _simple_edges(adjacency)
    edge_count = len(simple_edges)
    if edge_count == 0:
        return [{node} for node in nodes]

    communities = {index: {node} for index, node in enumerate(nodes)}
    membership = {node: index for index, node in enumerate(nodes)}
    degrees = {node: len(adjacency[node]) for node in nodes}
    while True:
        degree_sums = {
            community_id: sum(degrees[node] for node in members)
            for community_id, members in communities.items()
        }
        between_counts: dict[tuple[int, int], int] = {}
        for source, target in simple_edges:
            source_community = membership[source]
            target_community = membership[target]
            if source_community == target_community:
                continue
            pair = (
                min(source_community, target_community),
                max(source_community, target_community),
            )
            between_counts[pair] = between_counts.get(pair, 0) + 1

        best_pair: tuple[int, int] | None = None
        best_gain = 0.0
        best_tie_key: tuple[tuple[str, ...], tuple[str, ...]] | None = None
        for pair, edges_between in between_counts.items():
            left, right = pair
            gain = (edges_between / edge_count) - (
                (degree_sums[left] * degree_sums[right])
                / (2.0 * edge_count * edge_count)
            )
            left_members = tuple(sorted(communities[left]))
            right_members = tuple(sorted(communities[right]))
            member_keys = (
                (left_members, right_members)
                if left_members < right_members
                else (right_members, left_members)
            )
            if gain > best_gain + 1e-12 or (
                math.isclose(gain, best_gain, abs_tol=1e-12)
                and gain > 1e-12
                and (best_tie_key is None or member_keys < best_tie_key)
            ):
                best_pair = pair
                best_gain = gain
                best_tie_key = member_keys
        if best_pair is None or best_gain <= 1e-12:
            break
        left, right = best_pair
        keep, remove = (
            (left, right)
            if tuple(sorted(communities[left]))
            < tuple(sorted(communities[right]))
            else (right, left)
        )
        communities[keep].update(communities.pop(remove))
        for node in communities[keep]:
            membership[node] = keep
    return sorted(
        communities.values(),
        key=lambda community: tuple(sorted(community)),
    )


def _simple_edges(
    adjacency: Mapping[str, frozenset[str]],
) -> list[tuple[str, str]]:
    return [
        (source, target)
        for source in sorted(adjacency)
        for target in sorted(adjacency[source])
        if source < target
    ]


def _modularity(
    adjacency: Mapping[str, frozenset[str]],
    communities: Sequence[set[str]],
) -> float:
    simple_edges = _simple_edges(adjacency)
    edge_count = len(simple_edges)
    if edge_count == 0:
        return 0.0
    value = 0.0
    for community in communities:
        internal_edges = sum(
            source in community and target in community
            for source, target in simple_edges
        )
        degree_sum = sum(len(adjacency[node]) for node in community)
        value += (internal_edges / edge_count) - (
            degree_sum / (2.0 * edge_count)
        ) ** 2
    return value


def _community_output_rows(
    graph: _ConditionGraph,
    communities: Sequence[set[str]],
    *,
    algorithm: str,
) -> tuple[dict[str, int | None], list[dict[str, object]]]:
    by_node: dict[str, int | None] = {node.id: None for node in graph.nodes}
    community_sizes: dict[int, int] = {}
    for community_id, community in enumerate(communities, start=1):
        community_sizes[community_id] = len(community)
        for node_id in community:
            by_node[node_id] = community_id
    rows: list[dict[str, object]] = []
    for node in graph.nodes:
        assigned_community = by_node[node.id]
        rows.append(
            {
                "condition": graph.condition,
                "community": assigned_community,
                "community_id": assigned_community,
                "community_size": (
                    community_sizes[assigned_community]
                    if assigned_community is not None
                    else None
                ),
                "algorithm": algorithm,
                "node_id": node.id,
                "id": _json_safe_scalar(node.attributes.get("id")),
                "resid": _json_safe_scalar(node.attributes.get("resid")),
            }
        )
    return by_node, rows


def _metric_output_row(
    node: _AnalysisNode,
    *,
    condition: str,
    metric_values: Mapping[str, Mapping[str, int | float | None]],
    community: int | None,
) -> dict[str, object]:
    row: dict[str, object] = {"condition": condition, "node_id": node.id}
    row.update(
        {
            field_name: _json_safe_scalar(node.attributes.get(field_name))
            for field_name in _PRESERVED_NODE_FIELDS
        }
    )
    row.update(
        {
            metric_name: metric_values[metric_name][node.id]
            for metric_name in _ANALYSIS_METRIC_NAMES
        }
    )
    row["community"] = community
    row["community_id"] = community
    return row


def _json_safe_scalar(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    return str(value)


def _issue_sort_key(
    issue: AnalysisGraphMetricsIssue,
) -> tuple[str, str, str, str]:
    details = json.dumps(issue.to_dict()["details"], sort_keys=True)
    return issue.condition or "", issue.kind, issue.message, details


def compute_graph_topology_metrics(
    graph: ContractGraph,
    *,
    weight_column: str = "contact_freq",
) -> GraphTopologyMetrics:
    """Compute unweighted degree and weighted strength for each graph node."""
    strengths = {node_id: 0.0 for node_id in graph.node_ids}

    for edge in graph.edges:
        weight = _parse_edge_weight(edge, weight_column)
        strengths[edge.source] += weight
        if edge.target != edge.source:
            strengths[edge.target] += weight

    node_metrics = tuple(
        NodeTopologyMetrics(
            node_id=node_id,
            degree=graph.degree(node_id),
            strength=strengths[node_id],
        )
        for node_id in graph.node_ids
    )
    return GraphTopologyMetrics(
        condition=graph.condition,
        node_metrics=node_metrics,
    )


def write_graph_topology_metrics(
    metrics: GraphTopologyMetrics,
    path: str | Path,
) -> Path:
    """Write graph topology metrics as JSON and return the output path."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(metrics.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path


def _parse_edge_weight(edge: ContractEdge, weight_column: str) -> float:
    if weight_column not in edge.row:
        raise GraphMetricsError(
            f"Missing weight column {weight_column!r} for edge "
            f"{edge.source!r}-{edge.target!r}"
        )
    raw_value = edge.row[weight_column].strip()
    if raw_value == "":
        raise GraphMetricsError(
            f"Empty weight value {weight_column!r} for edge "
            f"{edge.source!r}-{edge.target!r}"
        )
    try:
        weight = float(raw_value)
    except ValueError as exc:
        raise GraphMetricsError(
            f"Invalid weight value {raw_value!r} in column {weight_column!r}"
        ) from exc
    if not math.isfinite(weight):
        raise GraphMetricsError(
            f"Non-finite weight value {raw_value!r} in column {weight_column!r}"
        )
    return weight


__all__ = [
    "AnalysisGraphMetricsIssue",
    "AnalysisGraphMetricsOptions",
    "AnalysisGraphMetricsResult",
    "GraphMetricsError",
    "GraphTopologyMetrics",
    "NodeTopologyMetrics",
    "compute_analysis_graph_metrics_from_graph_json",
    "compute_graph_topology_metrics",
    "write_graph_topology_metrics",
]
