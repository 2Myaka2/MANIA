"""Deterministic communities for the accepted Stage 21.A static RIN graph."""

from __future__ import annotations

import csv
import json
import math
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from mania.analysis.static_rin_graph import (
    STATIC_RIN_GRAPH_SCHEMA_VERSION,
    StaticRinGraph,
)

STATIC_RIN_COMMUNITY_ALGORITHM = "greedy_modularity_unweighted"
STATIC_RIN_COMMUNITIES_COLUMNS = (
    "condition",
    "node_id",
    "residue_index",
    "resid",
    "resname",
    "segment_id",
    "community_id",
    "community_size",
    "algorithm",
    "modularity",
    "n_communities",
)


class StaticRinCommunitiesError(ValueError):
    """Raised when static RIN communities cannot be computed or written."""


@dataclass(frozen=True)
class StaticRinCommunityAssignment:
    """One deterministic Stage 21.C node-to-community assignment."""

    condition: str
    node_id: str
    residue_index: int
    resid: str
    resname: str
    segment_id: str | None
    community_id: int
    community_size: int
    algorithm: str
    modularity: float
    n_communities: int

    def to_dict(self) -> dict[str, object]:
        """Return one CSV-ready row without changing missing values."""
        return {
            column: getattr(self, column)
            for column in STATIC_RIN_COMMUNITIES_COLUMNS
        }


@dataclass(frozen=True)
class StaticRinCommunities:
    """Per-condition Stage 21.C assignments and community quality."""

    condition: str
    assignments: tuple[StaticRinCommunityAssignment, ...]
    algorithm: str
    modularity: float
    n_communities: int

    @property
    def by_node_id(self) -> Mapping[str, StaticRinCommunityAssignment]:
        """Return assignments keyed by the accepted Stage 21.A node ID."""
        return {assignment.node_id: assignment for assignment in self.assignments}


@dataclass(frozen=True)
class _CommunityNode:
    id: str
    condition: str
    residue_index: int
    resid: str
    resname: str
    segment_id: str | None


@dataclass(frozen=True)
class _CommunityEdge:
    id: str
    condition: str
    source: str
    target: str
    weight: float | None


@dataclass(frozen=True)
class _CommunityGraph:
    condition: str
    nodes: tuple[_CommunityNode, ...]
    edges: tuple[_CommunityEdge, ...]


def compute_static_rin_communities(
    graph: StaticRinGraph,
) -> StaticRinCommunities:
    """Compute Stage 21.C communities from the accepted in-memory graph."""
    if not isinstance(graph, StaticRinGraph):
        raise TypeError("graph must be a StaticRinGraph")
    return _compute_communities(_graph_from_mapping(graph.to_dict()))


def compute_static_rin_communities_from_graph_json(
    graph_json: str | Path | Mapping[str, object],
) -> StaticRinCommunities:
    """Load an accepted Stage 21.A ``graph.json`` and compute communities."""
    payload = _load_graph_payload(graph_json)
    return _compute_communities(_graph_from_mapping(payload))


def write_static_rin_communities_csv(
    communities: StaticRinCommunities,
    output_dir: str | Path,
) -> Path:
    """Write ``communities_{condition}.csv`` deterministically and atomically."""
    if not isinstance(communities, StaticRinCommunities):
        raise TypeError("communities must be StaticRinCommunities")
    component = re.sub(
        r"[^A-Za-z0-9_.-]+", "_", communities.condition
    ).strip("._")
    if not component:
        raise StaticRinCommunitiesError(
            "condition must contain a filename-safe character"
        )
    directory = Path(output_dir)
    if directory.exists() and not directory.is_dir():
        raise StaticRinCommunitiesError(
            "static RIN communities output is not a directory"
        )
    output_path = directory / f"communities_{component}.csv"
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
                fieldnames=STATIC_RIN_COMMUNITIES_COLUMNS,
                lineterminator="\n",
            )
            writer.writeheader()
            for assignment in communities.assignments:
                writer.writerow(
                    {
                        key: _csv_value(value)
                        for key, value in assignment.to_dict().items()
                    }
                )
        temporary_path.replace(output_path)
    except (OSError, csv.Error) as error:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise StaticRinCommunitiesError(
            f"static RIN communities could not be written: {output_path}"
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
        raise StaticRinCommunitiesError(
            f"missing Stage 21.A static RIN graph: {path}"
        ) from error
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise StaticRinCommunitiesError(
            f"Stage 21.A static RIN graph could not be read: {path}"
        ) from error
    if not isinstance(payload, Mapping):
        raise StaticRinCommunitiesError("static RIN graph JSON must be an object")
    return cast(Mapping[str, object], payload)


def _graph_from_mapping(payload: Mapping[str, object]) -> _CommunityGraph:
    if payload.get("schema_version") != STATIC_RIN_GRAPH_SCHEMA_VERSION:
        raise StaticRinCommunitiesError(
            "unsupported static RIN graph schema_version"
        )
    if payload.get("directed") is not False:
        raise StaticRinCommunitiesError("static RIN graph must be undirected")
    condition = _required_text(payload.get("condition"), "graph condition")
    raw_nodes = _record_sequence(payload.get("nodes"), "graph nodes")
    raw_edges = _record_sequence(payload.get("edges"), "graph edges")
    if not raw_nodes:
        raise StaticRinCommunitiesError(
            "static RIN graph must contain at least one node"
        )
    if payload.get("n_nodes") != len(raw_nodes):
        raise StaticRinCommunitiesError(
            "static RIN graph n_nodes does not match nodes"
        )
    if payload.get("n_edges") != len(raw_edges):
        raise StaticRinCommunitiesError(
            "static RIN graph n_edges does not match edges"
        )

    nodes_by_id: dict[str, _CommunityNode] = {}
    residue_indexes: set[int] = set()
    for index, record in enumerate(raw_nodes):
        if not isinstance(record, Mapping):
            raise StaticRinCommunitiesError(
                f"graph node {index} must be an object"
            )
        node_condition = _required_text(
            record.get("condition"), f"graph node {index} condition"
        )
        residue_index = _required_int(
            record.get("residue_index"), f"graph node {index} residue_index"
        )
        node_id = _required_text(record.get("id"), f"graph node {index} id")
        if node_condition != condition:
            raise StaticRinCommunitiesError(
                "graph node condition does not match graph"
            )
        if node_id != f"{condition}:{residue_index}":
            raise StaticRinCommunitiesError(
                "graph node ID is not the accepted format"
            )
        if node_id in nodes_by_id or residue_index in residue_indexes:
            raise StaticRinCommunitiesError(
                "static RIN graph contains duplicate nodes"
            )
        nodes_by_id[node_id] = _CommunityNode(
            id=node_id,
            condition=condition,
            residue_index=residue_index,
            resid=_required_text(
                record.get("resid"), f"graph node {index} resid"
            ),
            resname=_required_text(
                record.get("resname"), f"graph node {index} resname"
            ),
            segment_id=_optional_text(record.get("segment_id")),
        )
        residue_indexes.add(residue_index)

    edges: list[_CommunityEdge] = []
    edge_ids: set[str] = set()
    pairs: set[tuple[str, str]] = set()
    for index, record in enumerate(raw_edges):
        if not isinstance(record, Mapping):
            raise StaticRinCommunitiesError(
                f"graph edge {index} must be an object"
            )
        edge_condition = _required_text(
            record.get("condition"), f"graph edge {index} condition"
        )
        source = _required_text(
            record.get("source"), f"graph edge {index} source"
        )
        target = _required_text(
            record.get("target"), f"graph edge {index} target"
        )
        edge_id = _required_text(record.get("id"), f"graph edge {index} id")
        primary_type = _required_text(
            record.get("primary_edge_type"),
            f"graph edge {index} primary_edge_type",
        )
        if edge_condition != condition:
            raise StaticRinCommunitiesError(
                "graph edge condition does not match graph"
            )
        if source not in nodes_by_id or target not in nodes_by_id or source == target:
            raise StaticRinCommunitiesError("graph edge endpoints are invalid")
        source_index = nodes_by_id[source].residue_index
        target_index = nodes_by_id[target].residue_index
        if target_index < source_index:
            raise StaticRinCommunitiesError(
                "graph edge endpoints are not normalized"
            )
        if edge_id != f"{condition}:{source_index}--{target_index}:{primary_type}":
            raise StaticRinCommunitiesError(
                "graph edge ID is not the accepted format"
            )
        pair = (source, target)
        if edge_id in edge_ids or pair in pairs:
            raise StaticRinCommunitiesError(
                "static RIN graph contains duplicate edges"
            )
        weight = _optional_weight(
            record.get("weight"), f"graph edge {index} weight"
        )
        contact_freq = _optional_weight(
            record.get("contact_freq"),
            f"graph edge {index} contact_freq",
        )
        if weight != contact_freq:
            raise StaticRinCommunitiesError(
                "graph edge weight must equal contact_freq"
            )
        edges.append(_CommunityEdge(edge_id, condition, source, target, weight))
        edge_ids.add(edge_id)
        pairs.add(pair)

    return _CommunityGraph(
        condition=condition,
        nodes=tuple(
            sorted(
                nodes_by_id.values(),
                key=lambda node: (node.residue_index, node.id),
            )
        ),
        edges=tuple(sorted(edges, key=lambda edge: edge.id)),
    )


def _compute_communities(graph: _CommunityGraph) -> StaticRinCommunities:
    node_order = {
        node.id: (node.residue_index, node.id) for node in graph.nodes
    }
    adjacency_sets = {node.id: set[str]() for node in graph.nodes}
    for edge in graph.edges:
        adjacency_sets[edge.source].add(edge.target)
        adjacency_sets[edge.target].add(edge.source)
    adjacency = {
        node_id: frozenset(neighbors)
        for node_id, neighbors in adjacency_sets.items()
    }
    communities = _greedy_modularity_communities(adjacency, node_order)
    modularity = _modularity(adjacency, communities, node_order)
    community_by_node: dict[str, int] = {}
    community_sizes: dict[int, int] = {}
    for community_id, community in enumerate(communities, start=1):
        community_sizes[community_id] = len(community)
        for node_id in community:
            community_by_node[node_id] = community_id
    n_communities = len(communities)
    assignments = tuple(
        StaticRinCommunityAssignment(
            condition=graph.condition,
            node_id=node.id,
            residue_index=node.residue_index,
            resid=node.resid,
            resname=node.resname,
            segment_id=node.segment_id,
            community_id=community_by_node[node.id],
            community_size=community_sizes[community_by_node[node.id]],
            algorithm=STATIC_RIN_COMMUNITY_ALGORITHM,
            modularity=modularity,
            n_communities=n_communities,
        )
        for node in graph.nodes
    )
    return StaticRinCommunities(
        condition=graph.condition,
        assignments=assignments,
        algorithm=STATIC_RIN_COMMUNITY_ALGORITHM,
        modularity=modularity,
        n_communities=n_communities,
    )


def _greedy_modularity_communities(
    adjacency: Mapping[str, frozenset[str]],
    node_order: Mapping[str, tuple[int, str]],
) -> tuple[frozenset[str], ...]:
    nodes = tuple(sorted(adjacency, key=node_order.__getitem__))
    simple_edges = _simple_edges(adjacency, node_order)
    edge_count = len(simple_edges)
    if edge_count == 0:
        return tuple(frozenset((node,)) for node in nodes)

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
        best_tie_key: tuple[
            tuple[tuple[int, str], ...], tuple[tuple[int, str], ...]
        ] | None = None
        for pair, edges_between in between_counts.items():
            left, right = pair
            gain = (edges_between / edge_count) - (
                (degree_sums[left] * degree_sums[right])
                / (2.0 * edge_count * edge_count)
            )
            left_key = _community_order_key(communities[left], node_order)
            right_key = _community_order_key(communities[right], node_order)
            tie_key = (
                (left_key, right_key)
                if left_key < right_key
                else (right_key, left_key)
            )
            if gain > best_gain + 1e-12 or (
                math.isclose(
                    gain,
                    best_gain,
                    rel_tol=0.0,
                    abs_tol=1e-12,
                )
                and gain > 1e-12
                and (best_tie_key is None or tie_key < best_tie_key)
            ):
                best_pair = pair
                best_gain = gain
                best_tie_key = tie_key
        if best_pair is None or best_gain <= 1e-12:
            break
        left, right = best_pair
        left_key = _community_order_key(communities[left], node_order)
        right_key = _community_order_key(communities[right], node_order)
        keep, remove = (left, right) if left_key < right_key else (right, left)
        communities[keep].update(communities.pop(remove))
        for node in communities[keep]:
            membership[node] = keep
    return tuple(
        frozenset(community)
        for community in sorted(
            communities.values(),
            key=lambda members: _community_order_key(members, node_order),
        )
    )


def _community_order_key(
    community: set[str],
    node_order: Mapping[str, tuple[int, str]],
) -> tuple[tuple[int, str], ...]:
    return tuple(sorted(node_order[node] for node in community))


def _simple_edges(
    adjacency: Mapping[str, frozenset[str]],
    node_order: Mapping[str, tuple[int, str]],
) -> tuple[tuple[str, str], ...]:
    return tuple(
        (source, target)
        for source in sorted(adjacency, key=node_order.__getitem__)
        for target in sorted(adjacency[source], key=node_order.__getitem__)
        if node_order[source] < node_order[target]
    )


def _modularity(
    adjacency: Mapping[str, frozenset[str]],
    communities: Sequence[frozenset[str]],
    node_order: Mapping[str, tuple[int, str]],
) -> float:
    simple_edges = _simple_edges(adjacency, node_order)
    edge_count = len(simple_edges)
    if edge_count == 0:
        return 0.0
    terms: list[float] = []
    for community in communities:
        internal_edges = sum(
            source in community and target in community
            for source, target in simple_edges
        )
        degree_sum = sum(len(adjacency[node]) for node in community)
        terms.append(
            (internal_edges / edge_count)
            - (degree_sum / (2.0 * edge_count)) ** 2
        )
    value = math.fsum(terms)
    return 0.0 if abs(value) < 1e-15 else value


def _record_sequence(value: object, label: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise StaticRinCommunitiesError(f"{label} must be an array")
    return value


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StaticRinCommunitiesError(f"{label} must be a non-empty string")
    return value.strip()


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise StaticRinCommunitiesError(
            "optional graph text fields must be strings or null"
        )
    return value or None


def _required_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise StaticRinCommunitiesError(f"{label} must be an integer")
    return value


def _optional_weight(value: object, label: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StaticRinCommunitiesError(f"{label} must be numeric or null")
    numeric = float(value)
    if not math.isfinite(numeric) or not 0.0 <= numeric <= 1.0:
        raise StaticRinCommunitiesError(f"{label} must be between 0 and 1")
    return numeric


def _csv_value(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, float):
        return format(value, ".15g")
    return value


__all__ = [
    "STATIC_RIN_COMMUNITIES_COLUMNS",
    "STATIC_RIN_COMMUNITY_ALGORITHM",
    "StaticRinCommunities",
    "StaticRinCommunitiesError",
    "StaticRinCommunityAssignment",
    "compute_static_rin_communities",
    "compute_static_rin_communities_from_graph_json",
    "write_static_rin_communities_csv",
]
