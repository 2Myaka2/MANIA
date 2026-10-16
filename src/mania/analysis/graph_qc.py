"""Lightweight graph QC metrics for contract graphs."""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from mania.analysis.contract_graph import ContractGraph


class GraphQCError(Exception):
    """Raised when graph QC is used with invalid inputs."""


@dataclass(frozen=True)
class GraphComponent:
    """Connected component summary."""

    component_id: int
    node_ids: tuple[str, ...]
    size: int


@dataclass(frozen=True)
class GraphQCReport:
    """Basic quality-control report for a contract graph."""

    condition: str
    n_nodes: int
    n_edges: int
    n_isolated_nodes: int
    isolated_node_ids: tuple[str, ...]
    n_components: int
    components: tuple[GraphComponent, ...]
    largest_component_size: int
    self_loop_edges: tuple[tuple[str, str, str], ...]
    duplicate_undirected_edge_keys: tuple[tuple[str, str, str], ...]

    @property
    def has_isolated_nodes(self) -> bool:
        """Return whether the graph has isolated nodes."""
        return self.n_isolated_nodes > 0

    @property
    def has_self_loops(self) -> bool:
        """Return whether the graph has self-loop edge rows."""
        return bool(self.self_loop_edges)

    @property
    def has_duplicate_edges(self) -> bool:
        """Return whether duplicate undirected edge keys were found."""
        return bool(self.duplicate_undirected_edge_keys)

    @property
    def passed_basic_qc(self) -> bool:
        """Return whether basic graph QC passed."""
        return (
            not self.has_isolated_nodes
            and not self.has_self_loops
            and not self.has_duplicate_edges
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable report dictionary."""
        return {
            "condition": self.condition,
            "n_nodes": self.n_nodes,
            "n_edges": self.n_edges,
            "n_isolated_nodes": self.n_isolated_nodes,
            "isolated_node_ids": list(self.isolated_node_ids),
            "n_components": self.n_components,
            "components": [
                {
                    "component_id": component.component_id,
                    "node_ids": list(component.node_ids),
                    "size": component.size,
                }
                for component in self.components
            ],
            "largest_component_size": self.largest_component_size,
            "self_loop_edges": [
                list(edge_key) for edge_key in self.self_loop_edges
            ],
            "duplicate_undirected_edge_keys": [
                list(edge_key) for edge_key in self.duplicate_undirected_edge_keys
            ],
            "has_isolated_nodes": self.has_isolated_nodes,
            "has_self_loops": self.has_self_loops,
            "has_duplicate_edges": self.has_duplicate_edges,
            "passed_basic_qc": self.passed_basic_qc,
        }


def compute_graph_qc(graph: ContractGraph) -> GraphQCReport:
    """Compute basic QC metrics for a contract graph."""
    components = _connected_components(graph)
    isolated_node_ids = graph.isolated_node_ids()
    self_loop_edges = _self_loop_edges(graph)
    duplicate_undirected_edge_keys = _duplicate_undirected_edge_keys(graph)

    return GraphQCReport(
        condition=graph.condition,
        n_nodes=graph.n_nodes,
        n_edges=graph.n_edges,
        n_isolated_nodes=len(isolated_node_ids),
        isolated_node_ids=isolated_node_ids,
        n_components=len(components),
        components=components,
        largest_component_size=max(
            (component.size for component in components),
            default=0,
        ),
        self_loop_edges=self_loop_edges,
        duplicate_undirected_edge_keys=duplicate_undirected_edge_keys,
    )


def write_graph_qc_report(report: GraphQCReport, path: str | Path) -> Path:
    """Write a graph QC report as JSON and return the output path."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path


def _connected_components(graph: ContractGraph) -> tuple[GraphComponent, ...]:
    visited: set[str] = set()
    components: list[GraphComponent] = []

    for start_node_id in graph.node_ids:
        if start_node_id in visited:
            continue

        reached = _reachable_node_ids(graph, start_node_id)
        visited.update(reached)
        component_node_ids = tuple(
            node_id for node_id in graph.node_ids if node_id in reached
        )
        components.append(
            GraphComponent(
                component_id=len(components) + 1,
                node_ids=component_node_ids,
                size=len(component_node_ids),
            )
        )

    return tuple(components)


def _reachable_node_ids(graph: ContractGraph, start_node_id: str) -> set[str]:
    reached: set[str] = {start_node_id}
    queue: deque[str] = deque([start_node_id])

    while queue:
        node_id = queue.popleft()
        for neighbor_id in graph.node_ids:
            if neighbor_id not in graph.neighbors(node_id):
                continue
            if neighbor_id in reached:
                continue
            reached.add(neighbor_id)
            queue.append(neighbor_id)

    return reached


def _self_loop_edges(graph: ContractGraph) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        (edge.source, edge.target, edge.edge_type)
        for edge in graph.edges
        if edge.source == edge.target
    )


def _duplicate_undirected_edge_keys(
    graph: ContractGraph,
) -> tuple[tuple[str, str, str], ...]:
    seen: set[tuple[str, str, str]] = set()
    duplicates: list[tuple[str, str, str]] = []
    duplicate_set: set[tuple[str, str, str]] = set()

    for edge in graph.edges:
        key = (
            min(edge.source, edge.target),
            max(edge.source, edge.target),
            edge.edge_type,
        )
        if key in seen and key not in duplicate_set:
            duplicates.append(key)
            duplicate_set.add(key)
        seen.add(key)

    return tuple(duplicates)


__all__ = [
    "GraphComponent",
    "GraphQCError",
    "GraphQCReport",
    "compute_graph_qc",
    "write_graph_qc_report",
]
