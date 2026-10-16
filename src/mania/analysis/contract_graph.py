"""Lightweight graph core for backend contract CSV artifacts."""

from __future__ import annotations

import csv
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from mania.constants import EDGE_COLUMNS, NODE_COLUMNS


class ContractGraphError(Exception):
    """Raised when contract graph CSV inputs are invalid."""


@dataclass(frozen=True)
class ContractNode:
    """Node loaded from a contract nodes.csv row."""

    id: str
    row: Mapping[str, str]


@dataclass(frozen=True)
class ContractEdge:
    """Edge loaded from a contract edges.csv row."""

    source: str
    target: str
    edge_type: str
    row: Mapping[str, str]


@dataclass(frozen=True)
class ContractGraph:
    """In-memory undirected graph loaded from backend contract CSVs."""

    condition: str
    nodes: Mapping[str, ContractNode]
    edges: tuple[ContractEdge, ...]
    adjacency: Mapping[str, frozenset[str]]

    @property
    def n_nodes(self) -> int:
        """Return the number of graph nodes."""
        return len(self.nodes)

    @property
    def n_edges(self) -> int:
        """Return the number of graph edge rows."""
        return len(self.edges)

    @property
    def node_ids(self) -> tuple[str, ...]:
        """Return node IDs in nodes.csv row order."""
        return tuple(self.nodes.keys())

    def neighbors(self, node_id: str) -> frozenset[str]:
        """Return neighbors for a known node."""
        if node_id not in self.adjacency:
            raise ContractGraphError(f"Unknown node ID: {node_id!r}")
        return self.adjacency[node_id]

    def degree(self, node_id: str) -> int:
        """Return the undirected adjacency degree for a known node."""
        return len(self.neighbors(node_id))

    def has_node(self, node_id: str) -> bool:
        """Return whether a node ID exists in the graph."""
        return node_id in self.nodes

    def isolated_node_ids(self) -> tuple[str, ...]:
        """Return isolated node IDs in nodes.csv row order."""
        return tuple(
            node_id for node_id in self.node_ids if not self.adjacency[node_id]
        )


def load_contract_graph(
    nodes_path: str | Path,
    edges_path: str | Path,
    *,
    condition: str,
) -> ContractGraph:
    """Load a lightweight undirected graph from contract nodes.csv and edges.csv."""
    node_rows = _read_csv_rows(
        nodes_path,
        required_columns=NODE_COLUMNS,
        artifact_label="nodes.csv",
    )
    edge_rows = _read_csv_rows(
        edges_path,
        required_columns=EDGE_COLUMNS,
        artifact_label="edges.csv",
    )

    if not node_rows:
        raise ContractGraphError("nodes.csv must contain at least one node row")

    nodes = _build_nodes(node_rows, condition=condition)
    edges = _build_edges(edge_rows, nodes=nodes, condition=condition)
    adjacency = _build_adjacency(nodes, edges)

    return ContractGraph(
        condition=condition,
        nodes=MappingProxyType(nodes),
        edges=edges,
        adjacency=MappingProxyType(adjacency),
    )


def load_contract_graph_from_condition_dir(
    condition_dir: str | Path,
    *,
    condition: str,
) -> ContractGraph:
    """Load a contract graph from a per-condition artifact directory."""
    root = Path(condition_dir)
    return load_contract_graph(
        root / "nodes.csv",
        root / "edges.csv",
        condition=condition,
    )


def _read_csv_rows(
    path: str | Path,
    *,
    required_columns: Sequence[str],
    artifact_label: str,
) -> list[dict[str, str]]:
    csv_path = Path(path)
    try:
        with csv_path.open(encoding="utf-8", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            fieldnames = reader.fieldnames
            if fieldnames is None:
                raise ContractGraphError(f"{artifact_label} is missing a header")
            missing_columns = tuple(
                column for column in required_columns if column not in fieldnames
            )
            if missing_columns:
                missing = ", ".join(missing_columns)
                raise ContractGraphError(
                    f"{artifact_label} is missing required columns: {missing}"
                )
            return [_normalize_row(row, fieldnames) for row in reader]
    except FileNotFoundError as exc:
        raise ContractGraphError(f"Missing {artifact_label}: {csv_path}") from exc


def _normalize_row(
    row: Mapping[str, str | None],
    fieldnames: Sequence[str],
) -> dict[str, str]:
    return {
        column: value if (value := row.get(column)) is not None else ""
        for column in fieldnames
    }


def _build_nodes(
    rows: Sequence[Mapping[str, str]],
    *,
    condition: str,
) -> dict[str, ContractNode]:
    nodes: dict[str, ContractNode] = {}
    for row_number, row in enumerate(rows, start=2):
        node_id = _require_non_empty(row, "resid", "node resid", row_number)
        _require_condition(row, condition, "node", row_number)
        if node_id in nodes:
            raise ContractGraphError(
                f"Duplicate node resid at row {row_number}: {node_id}"
            )
        nodes[node_id] = ContractNode(
            id=node_id,
            row=MappingProxyType(dict(row)),
        )
    return nodes


def _build_edges(
    rows: Sequence[Mapping[str, str]],
    *,
    nodes: Mapping[str, ContractNode],
    condition: str,
) -> tuple[ContractEdge, ...]:
    edges: list[ContractEdge] = []
    for row_number, row in enumerate(rows, start=2):
        source = _require_non_empty(row, "resid_i", "edge resid_i", row_number)
        target = _require_non_empty(row, "resid_j", "edge resid_j", row_number)
        edge_type = _require_non_empty(row, "edge_type", "edge_type", row_number)
        _require_condition(row, condition, "edge", row_number)
        if source not in nodes:
            raise ContractGraphError(
                f"Edge at row {row_number} references missing node: {source}"
            )
        if target not in nodes:
            raise ContractGraphError(
                f"Edge at row {row_number} references missing node: {target}"
            )
        edges.append(
            ContractEdge(
                source=source,
                target=target,
                edge_type=edge_type,
                row=MappingProxyType(dict(row)),
            )
        )
    return tuple(edges)


def _build_adjacency(
    nodes: Mapping[str, ContractNode],
    edges: Sequence[ContractEdge],
) -> dict[str, frozenset[str]]:
    adjacency_sets: dict[str, set[str]] = {node_id: set() for node_id in nodes}
    for edge in edges:
        adjacency_sets[edge.source].add(edge.target)
        adjacency_sets[edge.target].add(edge.source)
    return {
        node_id: frozenset(neighbors)
        for node_id, neighbors in adjacency_sets.items()
    }


def _require_non_empty(
    row: Mapping[str, str],
    column: str,
    label: str,
    row_number: int,
) -> str:
    value = row[column].strip()
    if value == "":
        raise ContractGraphError(f"Empty {label} at row {row_number}")
    return value


def _require_condition(
    row: Mapping[str, str],
    expected_condition: str,
    row_label: str,
    row_number: int,
) -> None:
    actual_condition = row["condition"]
    if actual_condition != expected_condition:
        raise ContractGraphError(
            f"{row_label.capitalize()} condition mismatch at row {row_number}: "
            f"expected {expected_condition!r}, got {actual_condition!r}"
        )


__all__ = [
    "ContractEdge",
    "ContractGraph",
    "ContractGraphError",
    "ContractNode",
    "load_contract_graph",
    "load_contract_graph_from_condition_dir",
]
