"""Lightweight backend graph JSON validators for MANIA."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from json import JSONDecodeError
from pathlib import Path

from mania.constants import GRAPH_REQUIRED_KEYS
from mania.validation.artifacts import ArtifactValidationError


class GraphValidationError(ArtifactValidationError):
    """Raised when a graph JSON artifact fails validation."""


@dataclass(frozen=True)
class GraphValidationResult:
    """Result of validating a backend graph JSON artifact."""

    path: Path
    condition: str | None
    n_nodes_declared: int | None
    n_edges_declared: int | None
    node_ids: tuple[str, ...]
    edge_count: int
    missing_keys: tuple[str, ...]
    duplicate_node_ids: tuple[str, ...]

    @property
    def is_valid(self) -> bool:
        """Return whether the graph satisfies structural contract checks."""
        return (
            not self.missing_keys
            and not self.duplicate_node_ids
            and self.n_nodes_declared is not None
            and self.n_edges_declared is not None
            and self.n_nodes_declared == len(self.node_ids)
            and self.n_edges_declared == self.edge_count
        )


def load_graph_json(path: str | Path) -> Mapping[str, object]:
    """Load a backend graph JSON object."""
    graph_path = Path(path)
    try:
        payload = json.loads(graph_path.read_text(encoding="utf-8"))
    except JSONDecodeError as exc:
        raise GraphValidationError(f"Invalid graph JSON: {graph_path}") from exc
    if not isinstance(payload, dict):
        raise GraphValidationError(f"Graph JSON must be an object: {graph_path}")
    return payload


def validate_graph_json(
    path: str | Path,
    *,
    expected_condition: str | None = None,
    combined_graph: bool = False,
    require_condition_scoped_ids: bool | None = None,
) -> GraphValidationResult:
    """Validate backend graph JSON shape against the MANIA contract."""
    graph_path = Path(path)
    payload = load_graph_json(graph_path)
    missing_keys = tuple(key for key in GRAPH_REQUIRED_KEYS if key not in payload)
    if missing_keys:
        missing = ", ".join(missing_keys)
        raise GraphValidationError(f"Missing graph keys: {missing}")

    condition = str(payload["condition"])
    if expected_condition is not None and condition != expected_condition:
        raise GraphValidationError(
            f"Graph condition {condition!r} does not match {expected_condition!r}"
        )

    n_nodes = _require_int(payload["n_nodes"], "n_nodes")
    n_edges = _require_int(payload["n_edges"], "n_edges")
    nodes = _require_list(payload["nodes"], "nodes")
    edges = _require_list(payload["edges"], "edges")

    node_ids = _parse_node_ids(nodes)
    duplicate_node_ids = _duplicate_values(node_ids)
    if duplicate_node_ids:
        duplicates = ", ".join(duplicate_node_ids)
        raise GraphValidationError(f"Duplicate graph node IDs: {duplicates}")

    _validate_edges(edges)
    edge_count = len(edges)

    if n_nodes != len(node_ids):
        raise GraphValidationError(
            f"Declared n_nodes {n_nodes} does not match actual {len(node_ids)}"
        )
    if n_edges != edge_count:
        raise GraphValidationError(
            f"Declared n_edges {n_edges} does not match actual {edge_count}"
        )

    scoped_ids_required = (
        combined_graph
        if require_condition_scoped_ids is None
        else require_condition_scoped_ids
    )
    if scoped_ids_required:
        unscoped_node_ids = tuple(node_id for node_id in node_ids if ":" not in node_id)
        if unscoped_node_ids:
            unscoped = ", ".join(unscoped_node_ids)
            raise GraphValidationError(f"Node IDs must be condition-scoped: {unscoped}")

    result = GraphValidationResult(
        path=graph_path,
        condition=condition,
        n_nodes_declared=n_nodes,
        n_edges_declared=n_edges,
        node_ids=node_ids,
        edge_count=edge_count,
        missing_keys=missing_keys,
        duplicate_node_ids=duplicate_node_ids,
    )
    if not result.is_valid:
        raise GraphValidationError(f"Invalid graph JSON: {graph_path}")
    return result


def _require_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise GraphValidationError(f"Graph {label} must be an integer")
    return value


def _require_list(value: object, label: str) -> list[object]:
    if not isinstance(value, list):
        raise GraphValidationError(f"Graph {label} must be a list")
    return value


def _parse_node_ids(nodes: list[object]) -> tuple[str, ...]:
    node_ids: list[str] = []
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            raise GraphValidationError(f"Graph node at index {index} must be an object")
        if "id" not in node:
            raise GraphValidationError(f"Graph node at index {index} is missing id")
        node_ids.append(str(node["id"]))
    return tuple(node_ids)


def _validate_edges(edges: list[object]) -> None:
    for index, edge in enumerate(edges):
        if not isinstance(edge, dict):
            raise GraphValidationError(f"Graph edge at index {index} must be an object")


def _duplicate_values(values: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    duplicates: list[str] = []
    duplicate_set: set[str] = set()
    for value in values:
        if value in seen and value not in duplicate_set:
            duplicates.append(value)
            duplicate_set.add(value)
        seen.add(value)
    return tuple(duplicates)


__all__ = [
    "GraphValidationError",
    "GraphValidationResult",
    "load_graph_json",
    "validate_graph_json",
]
