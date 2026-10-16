"""Deterministic node metrics for the Stage 21.A static RIN graph."""

from __future__ import annotations

import csv
import json
import math
import re
import tempfile
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from mania.analysis.static_rin_graph import (
    STATIC_RIN_GRAPH_SCHEMA_VERSION,
    StaticRinGraph,
)

STATIC_RIN_METRICS_COLUMNS = (
    "condition",
    "node_id",
    "residue_index",
    "resid",
    "resname",
    "segment_id",
    "degree",
    "strength",
    "betweenness",
    "closeness",
    "eigenvector",
    "pagerank",
    "kcore",
)


class StaticRinMetricsError(ValueError):
    """Raised when accepted static RIN metrics cannot be computed or written."""


@dataclass(frozen=True)
class StaticRinNodeMetrics:
    """Deterministic Stage 21.B metrics and identity for one analysis node."""

    condition: str
    node_id: str
    residue_index: int
    resid: str
    resname: str
    segment_id: str | None
    degree: int
    strength: float | None
    betweenness: float
    closeness: float
    eigenvector: float | None
    pagerank: float | None
    kcore: int

    def to_dict(self) -> dict[str, object]:
        """Return one CSV-ready row without changing missing values."""
        return {
            column: getattr(self, column) for column in STATIC_RIN_METRICS_COLUMNS
        }


@dataclass(frozen=True)
class StaticRinMetrics:
    """Per-condition node metrics computed from one Stage 21.A graph."""

    condition: str
    node_metrics: tuple[StaticRinNodeMetrics, ...]

    @property
    def by_node_id(self) -> Mapping[str, StaticRinNodeMetrics]:
        """Return metrics keyed by the accepted Stage 21.A node ID."""
        return {row.node_id: row for row in self.node_metrics}


@dataclass(frozen=True)
class _MetricNode:
    id: str
    condition: str
    residue_index: int
    resid: str
    resname: str
    segment_id: str | None


@dataclass(frozen=True)
class _MetricEdge:
    id: str
    condition: str
    source: str
    target: str
    weight: float | None


@dataclass(frozen=True)
class _MetricGraph:
    condition: str
    nodes: tuple[_MetricNode, ...]
    edges: tuple[_MetricEdge, ...]


def compute_static_rin_metrics(graph: StaticRinGraph) -> StaticRinMetrics:
    """Compute Stage 21.B metrics from the accepted in-memory graph."""
    if not isinstance(graph, StaticRinGraph):
        raise TypeError("graph must be a StaticRinGraph")
    return _compute_metrics(_graph_from_mapping(graph.to_dict()))


def compute_static_rin_metrics_from_graph_json(
    graph_json: str | Path | Mapping[str, object],
) -> StaticRinMetrics:
    """Load an accepted Stage 21.A ``graph.json`` and compute node metrics."""
    payload = _load_graph_payload(graph_json)
    return _compute_metrics(_graph_from_mapping(payload))


def write_static_rin_metrics_csv(
    metrics: StaticRinMetrics,
    output_dir: str | Path,
) -> Path:
    """Write ``centrality_{condition}.csv`` deterministically and atomically."""
    if not isinstance(metrics, StaticRinMetrics):
        raise TypeError("metrics must be StaticRinMetrics")
    component = re.sub(r"[^A-Za-z0-9_.-]+", "_", metrics.condition).strip("._")
    if not component:
        raise StaticRinMetricsError(
            "condition must contain a filename-safe character"
        )
    directory = Path(output_dir)
    if directory.exists() and not directory.is_dir():
        raise StaticRinMetricsError("static RIN metrics output is not a directory")
    output_path = directory / f"centrality_{component}.csv"
    temporary_path: Path | None = None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=directory,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as csv_file:
            temporary_path = Path(csv_file.name)
            writer = csv.DictWriter(
                csv_file,
                fieldnames=STATIC_RIN_METRICS_COLUMNS,
                lineterminator="\n",
            )
            writer.writeheader()
            for row in metrics.node_metrics:
                writer.writerow(
                    {
                        key: _csv_value(value)
                        for key, value in row.to_dict().items()
                    }
                )
        temporary_path.replace(output_path)
    except (OSError, csv.Error) as error:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise StaticRinMetricsError(
            f"static RIN metrics could not be written: {output_path}"
        ) from error
    return output_path


def _load_graph_payload(
    graph_json: str | Path | Mapping[str, object],
) -> Mapping[str, object]:
    if isinstance(graph_json, Mapping):
        return graph_json
    path = Path(graph_json)
    try:
        payload: object = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise StaticRinMetricsError(
            f"missing Stage 21.A static RIN graph: {path}"
        ) from error
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise StaticRinMetricsError(
            f"Stage 21.A static RIN graph could not be read: {path}"
        ) from error
    if not isinstance(payload, Mapping):
        raise StaticRinMetricsError("static RIN graph JSON must be an object")
    return cast(Mapping[str, object], payload)


def _graph_from_mapping(payload: Mapping[str, object]) -> _MetricGraph:
    if payload.get("schema_version") != STATIC_RIN_GRAPH_SCHEMA_VERSION:
        raise StaticRinMetricsError("unsupported static RIN graph schema_version")
    if payload.get("directed") is not False:
        raise StaticRinMetricsError("static RIN graph must be undirected")
    condition = _required_text(payload.get("condition"), "graph condition")
    raw_nodes = _record_sequence(payload.get("nodes"), "graph nodes")
    raw_edges = _record_sequence(payload.get("edges"), "graph edges")
    if not raw_nodes:
        raise StaticRinMetricsError("static RIN graph must contain at least one node")
    if payload.get("n_nodes") != len(raw_nodes):
        raise StaticRinMetricsError("static RIN graph n_nodes does not match nodes")
    if payload.get("n_edges") != len(raw_edges):
        raise StaticRinMetricsError("static RIN graph n_edges does not match edges")

    nodes_by_id: dict[str, _MetricNode] = {}
    residue_indexes: set[int] = set()
    for index, record in enumerate(raw_nodes):
        if not isinstance(record, Mapping):
            raise StaticRinMetricsError(f"graph node {index} must be an object")
        node_condition = _required_text(
            record.get("condition"), f"graph node {index} condition"
        )
        residue_index = _required_int(
            record.get("residue_index"), f"graph node {index} residue_index"
        )
        node_id = _required_text(record.get("id"), f"graph node {index} id")
        if node_condition != condition:
            raise StaticRinMetricsError("graph node condition does not match graph")
        if node_id != f"{condition}:{residue_index}":
            raise StaticRinMetricsError("graph node ID is not the accepted format")
        if node_id in nodes_by_id or residue_index in residue_indexes:
            raise StaticRinMetricsError("static RIN graph contains duplicate nodes")
        nodes_by_id[node_id] = _MetricNode(
            id=node_id,
            condition=condition,
            residue_index=residue_index,
            resid=_required_text(record.get("resid"), f"graph node {index} resid"),
            resname=_required_text(
                record.get("resname"), f"graph node {index} resname"
            ),
            segment_id=_optional_text(record.get("segment_id")),
        )
        residue_indexes.add(residue_index)

    edges: list[_MetricEdge] = []
    edge_ids: set[str] = set()
    pairs: set[tuple[str, str]] = set()
    for index, record in enumerate(raw_edges):
        if not isinstance(record, Mapping):
            raise StaticRinMetricsError(f"graph edge {index} must be an object")
        edge_condition = _required_text(
            record.get("condition"), f"graph edge {index} condition"
        )
        source = _required_text(record.get("source"), f"graph edge {index} source")
        target = _required_text(record.get("target"), f"graph edge {index} target")
        edge_id = _required_text(record.get("id"), f"graph edge {index} id")
        primary_type = _required_text(
            record.get("primary_edge_type"),
            f"graph edge {index} primary_edge_type",
        )
        if edge_condition != condition:
            raise StaticRinMetricsError("graph edge condition does not match graph")
        if source not in nodes_by_id or target not in nodes_by_id or source == target:
            raise StaticRinMetricsError("graph edge endpoints are invalid")
        source_index = nodes_by_id[source].residue_index
        target_index = nodes_by_id[target].residue_index
        if target_index < source_index:
            raise StaticRinMetricsError("graph edge endpoints are not normalized")
        if edge_id != f"{condition}:{source_index}--{target_index}:{primary_type}":
            raise StaticRinMetricsError("graph edge ID is not the accepted format")
        pair = (source, target)
        if edge_id in edge_ids or pair in pairs:
            raise StaticRinMetricsError("static RIN graph contains duplicate edges")
        weight = _optional_weight(record.get("weight"), f"graph edge {index} weight")
        contact_freq = _optional_weight(
            record.get("contact_freq"), f"graph edge {index} contact_freq"
        )
        if weight != contact_freq:
            raise StaticRinMetricsError("graph edge weight must equal contact_freq")
        edges.append(_MetricEdge(edge_id, condition, source, target, weight))
        edge_ids.add(edge_id)
        pairs.add(pair)

    return _MetricGraph(
        condition=condition,
        nodes=tuple(
            sorted(nodes_by_id.values(), key=lambda node: (node.residue_index, node.id))
        ),
        edges=tuple(sorted(edges, key=lambda edge: edge.id)),
    )


def _compute_metrics(graph: _MetricGraph) -> StaticRinMetrics:
    node_ids = tuple(node.id for node in graph.nodes)
    adjacency_sets = {node_id: set[str]() for node_id in node_ids}
    numeric_weights = {node_id: list[float]() for node_id in node_ids}
    incident_counts = {node_id: 0 for node_id in node_ids}
    for edge in graph.edges:
        adjacency_sets[edge.source].add(edge.target)
        adjacency_sets[edge.target].add(edge.source)
        incident_counts[edge.source] += 1
        incident_counts[edge.target] += 1
        if edge.weight is not None:
            numeric_weights[edge.source].append(edge.weight)
            numeric_weights[edge.target].append(edge.weight)
    adjacency = {
        node_id: frozenset(sorted(neighbors))
        for node_id, neighbors in adjacency_sets.items()
    }
    strengths = {
        node_id: (
            math.fsum(numeric_weights[node_id])
            if numeric_weights[node_id]
            else 0.0 if incident_counts[node_id] == 0 else None
        )
        for node_id in node_ids
    }
    betweenness = _betweenness_centrality(adjacency)
    closeness = _closeness_centrality(adjacency)
    eigenvector = _optional_iterative_metric(
        node_ids, lambda: _eigenvector_centrality(adjacency)
    )
    pagerank = _optional_iterative_metric(node_ids, lambda: _pagerank(adjacency))
    kcore = _core_numbers(adjacency)
    return StaticRinMetrics(
        condition=graph.condition,
        node_metrics=tuple(
            StaticRinNodeMetrics(
                condition=graph.condition,
                node_id=node.id,
                residue_index=node.residue_index,
                resid=node.resid,
                resname=node.resname,
                segment_id=node.segment_id,
                degree=len(adjacency[node.id]),
                strength=strengths[node.id],
                betweenness=betweenness[node.id],
                closeness=closeness[node.id],
                eigenvector=eigenvector[node.id],
                pagerank=pagerank[node.id],
                kcore=kcore[node.id],
            )
            for node in graph.nodes
        ),
    )


def _optional_iterative_metric(
    node_ids: Sequence[str],
    computation: Callable[[], Mapping[str, float]],
) -> dict[str, float | None]:
    try:
        values = computation()
    except ArithmeticError:
        return {node_id: None for node_id in node_ids}
    return {node_id: values[node_id] for node_id in node_ids}


def _betweenness_centrality(
    adjacency: Mapping[str, frozenset[str]],
) -> dict[str, float]:
    nodes = tuple(sorted(adjacency))
    values = {node: 0.0 for node in nodes}
    for source in nodes:
        stack: list[str] = []
        predecessors = {node: list[str]() for node in nodes}
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
                    dependency[predecessor] += path_counts[predecessor] * coefficient
            if node != source:
                values[node] += dependency[node]
    if len(nodes) > 2:
        scale = 1.0 / ((len(nodes) - 1) * (len(nodes) - 2))
        return {node: value * scale for node, value in values.items()}
    return values


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
        values[source] = (
            (reachable / total_distance) * (reachable / (node_count - 1))
            if total_distance > 0 and node_count > 1
            else 0.0
        )
    return values


def _eigenvector_centrality(
    adjacency: Mapping[str, frozenset[str]],
    *,
    max_iterations: int = 5000,
    tolerance: float = 1e-12,
) -> dict[str, float]:
    nodes = tuple(sorted(adjacency))
    values = {node: 1.0 / len(nodes) for node in nodes}
    for _ in range(max_iterations):
        previous = values
        values = previous.copy()
        for node in nodes:
            for neighbor in sorted(adjacency[node]):
                values[neighbor] += previous[node]
        norm = math.sqrt(math.fsum(value * value for value in values.values())) or 1.0
        values = {node: value / norm for node, value in values.items()}
        if math.fsum(abs(values[node] - previous[node]) for node in nodes) < (
            len(nodes) * tolerance
        ):
            return values
    raise ArithmeticError("eigenvector centrality did not converge")


def _pagerank(
    adjacency: Mapping[str, frozenset[str]],
    *,
    damping: float = 0.85,
    max_iterations: int = 1000,
    tolerance: float = 1e-12,
) -> dict[str, float]:
    nodes = tuple(sorted(adjacency))
    node_count = len(nodes)
    values = {node: 1.0 / node_count for node in nodes}
    base = (1.0 - damping) / node_count
    for _ in range(max_iterations):
        previous = values
        dangling = damping * math.fsum(
            previous[node] for node in nodes if not adjacency[node]
        ) / node_count
        values = {node: base + dangling for node in nodes}
        for node in nodes:
            if adjacency[node]:
                contribution = damping * previous[node] / len(adjacency[node])
                for neighbor in sorted(adjacency[node]):
                    values[neighbor] += contribution
        if math.fsum(abs(values[node] - previous[node]) for node in nodes) < (
            node_count * tolerance
        ):
            return values
    raise ArithmeticError("PageRank did not converge")


def _core_numbers(adjacency: Mapping[str, frozenset[str]]) -> dict[str, int]:
    remaining = set(adjacency)
    values: dict[str, int] = {}
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
        values[node] = current_core
        remaining.remove(node)
    return values


def _record_sequence(value: object, label: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise StaticRinMetricsError(f"{label} must be an array")
    return value


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StaticRinMetricsError(f"{label} must be a non-empty string")
    return value.strip()


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise StaticRinMetricsError(
            "optional graph text fields must be strings or null"
        )
    return value or None


def _required_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise StaticRinMetricsError(f"{label} must be an integer")
    return value


def _optional_weight(value: object, label: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StaticRinMetricsError(f"{label} must be numeric or null")
    numeric = float(value)
    if not math.isfinite(numeric) or not 0.0 <= numeric <= 1.0:
        raise StaticRinMetricsError(f"{label} must be between 0 and 1")
    return numeric


def _csv_value(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, float):
        return format(value, ".15g")
    return value


__all__ = [
    "STATIC_RIN_METRICS_COLUMNS",
    "StaticRinMetrics",
    "StaticRinMetricsError",
    "StaticRinNodeMetrics",
    "compute_static_rin_metrics",
    "compute_static_rin_metrics_from_graph_json",
    "write_static_rin_metrics_csv",
]
