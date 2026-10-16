"""Stage 22.B window-level contact frequency and RIN construction."""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass

from mania.analysis.temporal import (
    TemporalContactRow,
    TemporalRinConfig,
    TemporalRinInput,
    TemporalWindow,
)
from mania.constants import EDGE_TYPE_PRIORITY

_EDGE_TYPE_PRIORITY_INDEX = {
    edge_type: index for index, edge_type in enumerate(EDGE_TYPE_PRIORITY)
}

TEMPORAL_RIN_STATUS_COMPUTED = "computed"
TEMPORAL_RIN_STATUS_EMPTY_INPUT = "empty_input"
TEMPORAL_RIN_STATUS_EMPTY_WINDOW = "empty_window"
TEMPORAL_RIN_STATUS_NO_CONTACTS_PASSING_THRESHOLD = (
    "no_contacts_passing_threshold"
)


@dataclass(frozen=True)
class TemporalRinWindowNode:
    """One residue incident to a passing edge in a temporal window."""

    id: str
    condition: str
    residue_index: int
    resid: str
    resname: str
    segment_id: str | None

    def to_dict(self) -> dict[str, object]:
        """Return the node as a JSON-safe dictionary."""
        return {
            "id": self.id,
            "condition": self.condition,
            "residue_index": self.residue_index,
            "resid": self.resid,
            "resname": self.resname,
            "segment_id": self.segment_id,
        }


@dataclass(frozen=True)
class TemporalRinWindowInteraction:
    """One typed residue-pair observation retained in a temporal window."""

    edge_type: str
    observed_frame_count: int
    sampled_frame_count: int
    window_contact_freq: float
    mean_dist_A: float | None
    std_dist_A: float | None
    min_dist_A: float | None
    max_dist_A: float | None

    @property
    def contact_freq(self) -> float:
        """Return the window-scoped contact frequency."""
        return self.window_contact_freq

    @property
    def weight(self) -> float:
        """Return the accepted window edge weight."""
        return self.window_contact_freq

    def to_dict(self) -> dict[str, object]:
        """Return the typed interaction as a JSON-safe dictionary."""
        return {
            "edge_type": self.edge_type,
            "observed_frame_count": self.observed_frame_count,
            "sampled_frame_count": self.sampled_frame_count,
            "window_contact_freq": self.window_contact_freq,
            "contact_freq": self.contact_freq,
            "weight": self.weight,
            "mean_dist_A": self.mean_dist_A,
            "std_dist_A": self.std_dist_A,
            "min_dist_A": self.min_dist_A,
            "max_dist_A": self.max_dist_A,
        }


@dataclass(frozen=True)
class TemporalRinWindowEdge:
    """One deterministic undirected residue-pair edge in a temporal window."""

    id: str
    condition: str
    window_id: int
    source: str
    target: str
    residue_index_i: int
    resid_i: str
    resname_i: str
    segment_id_i: str | None
    residue_index_j: int
    resid_j: str
    resname_j: str
    segment_id_j: str | None
    primary_edge_type: str
    all_edge_types: tuple[str, ...]
    interactions: tuple[TemporalRinWindowInteraction, ...]

    @property
    def primary_interaction(self) -> TemporalRinWindowInteraction:
        """Return the passing interaction selected by edge-type priority."""
        return self.interactions[0]

    @property
    def observed_frame_count(self) -> int:
        """Return the primary interaction's observed sampled-frame count."""
        return self.primary_interaction.observed_frame_count

    @property
    def sampled_frame_count(self) -> int:
        """Return the primary interaction's frequency denominator."""
        return self.primary_interaction.sampled_frame_count

    @property
    def window_contact_freq(self) -> float:
        """Return the primary interaction's window contact frequency."""
        return self.primary_interaction.window_contact_freq

    @property
    def contact_freq(self) -> float:
        """Return the primary interaction's window-scoped frequency."""
        return self.primary_interaction.contact_freq

    @property
    def weight(self) -> float:
        """Return the primary interaction's window contact frequency."""
        return self.primary_interaction.weight

    def to_dict(self) -> dict[str, object]:
        """Return the edge as a JSON-safe dictionary."""
        primary = self.primary_interaction
        return {
            "id": self.id,
            "condition": self.condition,
            "window_id": self.window_id,
            "source": self.source,
            "target": self.target,
            "residue_index_i": self.residue_index_i,
            "resid_i": self.resid_i,
            "resname_i": self.resname_i,
            "segment_id_i": self.segment_id_i,
            "residue_index_j": self.residue_index_j,
            "resid_j": self.resid_j,
            "resname_j": self.resname_j,
            "segment_id_j": self.segment_id_j,
            "edge_type": self.primary_edge_type,
            "primary_edge_type": self.primary_edge_type,
            "all_edge_types": list(self.all_edge_types),
            "n_edge_types": len(self.all_edge_types),
            "observed_frame_count": primary.observed_frame_count,
            "sampled_frame_count": primary.sampled_frame_count,
            "window_contact_freq": primary.window_contact_freq,
            "contact_freq": primary.contact_freq,
            "weight": primary.weight,
            "mean_dist_A": primary.mean_dist_A,
            "std_dist_A": primary.std_dist_A,
            "min_dist_A": primary.min_dist_A,
            "max_dist_A": primary.max_dist_A,
            "interactions": [
                interaction.to_dict() for interaction in self.interactions
            ],
        }


@dataclass(frozen=True)
class TemporalRinWindowGraph:
    """One in-memory Stage 22.B RIN graph for an accepted temporal window."""

    condition: str
    window_id: int
    frame_start: int
    frame_end: int
    sampled_frame_count: int
    active_frame_count: int
    frame_indexes: tuple[int, ...]
    status: str
    nodes: tuple[TemporalRinWindowNode, ...]
    edges: tuple[TemporalRinWindowEdge, ...]

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic in-memory graph representation."""
        return {
            "condition": self.condition,
            "window_id": self.window_id,
            "frame_start": self.frame_start,
            "frame_end": self.frame_end,
            "sampled_frame_count": self.sampled_frame_count,
            "active_frame_count": self.active_frame_count,
            "frame_indexes": list(self.frame_indexes),
            "status": self.status,
            "directed": False,
            "n_nodes": len(self.nodes),
            "n_edges": len(self.edges),
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
        }


@dataclass(frozen=True)
class TemporalRinWindowGraphBundle:
    """All in-memory Stage 22.B window graphs for one temporal input."""

    condition: str
    config: TemporalRinConfig
    status: str
    windows: tuple[TemporalRinWindowGraph, ...]

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic in-memory bundle representation."""
        return {
            "condition": self.condition,
            "config": self.config.to_dict(),
            "status": self.status,
            "window_count": len(self.windows),
            "windows": [window.to_dict() for window in self.windows],
        }


@dataclass(frozen=True)
class _ResidueIdentity:
    residue_index: int
    resid: str
    resname: str
    segment_id: str | None


def build_temporal_rin_window_graphs(
    temporal_input: TemporalRinInput,
) -> TemporalRinWindowGraphBundle:
    """Build one deterministic in-memory RIN graph per accepted window.

    Frequencies are grouped by window, normalized residue pair, and edge type.
    The denominator is always the window's ``sampled_frame_count``. Filtering
    is inclusive: typed contacts are retained when their frequency is greater
    than or equal to ``config.min_frequency``.
    """
    if not isinstance(temporal_input, TemporalRinInput):
        raise TypeError("temporal_input must be a TemporalRinInput")

    rows_by_frame: dict[int, list[TemporalContactRow]] = defaultdict(list)
    for row in temporal_input.rows:
        rows_by_frame[row.frame_index].append(row)

    window_graphs = tuple(
        _build_window_graph(
            temporal_input.condition,
            temporal_input.config,
            window,
            tuple(
                row
                for frame_index in window.frame_indexes
                for row in rows_by_frame.get(frame_index, ())
            ),
        )
        for window in temporal_input.windows
    )
    return TemporalRinWindowGraphBundle(
        condition=temporal_input.condition,
        config=temporal_input.config,
        status=(
            TEMPORAL_RIN_STATUS_COMPUTED
            if window_graphs
            else TEMPORAL_RIN_STATUS_EMPTY_INPUT
        ),
        windows=window_graphs,
    )


def _build_window_graph(
    condition: str,
    config: TemporalRinConfig,
    window: TemporalWindow,
    rows: tuple[TemporalContactRow, ...],
) -> TemporalRinWindowGraph:
    grouped: dict[
        tuple[int, int], dict[str, list[TemporalContactRow]]
    ] = defaultdict(lambda: defaultdict(list))
    identities: dict[int, _ResidueIdentity] = {}
    for row in rows:
        endpoint_i, endpoint_j = _normalized_endpoints(row)
        pair = (endpoint_i.residue_index, endpoint_j.residue_index)
        grouped[pair][row.edge_type].append(row)
        identities[endpoint_i.residue_index] = endpoint_i
        identities[endpoint_j.residue_index] = endpoint_j

    passing: dict[
        tuple[int, int], dict[str, TemporalRinWindowInteraction]
    ] = {}
    for pair in sorted(grouped):
        interactions: dict[str, TemporalRinWindowInteraction] = {}
        for edge_type in sorted(grouped[pair], key=_edge_type_priority_key):
            interaction = _summarize_typed_contact(
                edge_type,
                grouped[pair][edge_type],
                window.contact_frequency_denominator,
            )
            if interaction.window_contact_freq >= config.min_frequency:
                interactions[edge_type] = interaction
        if interactions:
            passing[pair] = interactions

    active_indexes = {
        residue_index for pair in passing for residue_index in pair
    }
    nodes = tuple(
        _window_node(condition, identities[residue_index])
        for residue_index in sorted(active_indexes)
    )
    nodes_by_index = {node.residue_index: node for node in nodes}
    edges = tuple(
        _window_edge(
            condition,
            window.window_id,
            pair,
            interactions,
            nodes_by_index,
        )
        for pair, interactions in sorted(passing.items())
    )

    if edges:
        status = TEMPORAL_RIN_STATUS_COMPUTED
    elif rows:
        status = TEMPORAL_RIN_STATUS_NO_CONTACTS_PASSING_THRESHOLD
    else:
        status = TEMPORAL_RIN_STATUS_EMPTY_WINDOW
    return TemporalRinWindowGraph(
        condition=condition,
        window_id=window.window_id,
        frame_start=window.frame_start,
        frame_end=window.frame_end,
        sampled_frame_count=window.sampled_frame_count,
        active_frame_count=len({row.frame_index for row in rows}),
        frame_indexes=window.frame_indexes,
        status=status,
        nodes=nodes,
        edges=edges,
    )


def _summarize_typed_contact(
    edge_type: str,
    rows: list[TemporalContactRow],
    sampled_frame_count: int,
) -> TemporalRinWindowInteraction:
    observed_frame_count = len({row.frame_index for row in rows})
    distances = [row.distance_A for row in rows if row.distance_A is not None]
    if distances:
        mean_dist_A = statistics.fmean(distances)
        std_dist_A = statistics.pstdev(distances)
        min_dist_A = min(distances)
        max_dist_A = max(distances)
    else:
        mean_dist_A = None
        std_dist_A = None
        min_dist_A = None
        max_dist_A = None
    return TemporalRinWindowInteraction(
        edge_type=edge_type,
        observed_frame_count=observed_frame_count,
        sampled_frame_count=sampled_frame_count,
        window_contact_freq=observed_frame_count / sampled_frame_count,
        mean_dist_A=mean_dist_A,
        std_dist_A=std_dist_A,
        min_dist_A=min_dist_A,
        max_dist_A=max_dist_A,
    )


def _normalized_endpoints(
    row: TemporalContactRow,
) -> tuple[_ResidueIdentity, _ResidueIdentity]:
    endpoint_i = _ResidueIdentity(
        residue_index=row.residue_index_i,
        resid=row.resid_i,
        resname=row.resname_i,
        segment_id=row.segment_id_i,
    )
    endpoint_j = _ResidueIdentity(
        residue_index=row.residue_index_j,
        resid=row.resid_j,
        resname=row.resname_j,
        segment_id=row.segment_id_j,
    )
    if endpoint_j.residue_index < endpoint_i.residue_index:
        return endpoint_j, endpoint_i
    return endpoint_i, endpoint_j


def _window_node(
    condition: str,
    identity: _ResidueIdentity,
) -> TemporalRinWindowNode:
    return TemporalRinWindowNode(
        id=f"{condition}:{identity.residue_index}",
        condition=condition,
        residue_index=identity.residue_index,
        resid=identity.resid,
        resname=identity.resname,
        segment_id=identity.segment_id,
    )


def _window_edge(
    condition: str,
    window_id: int,
    pair: tuple[int, int],
    interactions_by_type: dict[str, TemporalRinWindowInteraction],
    nodes_by_index: dict[int, TemporalRinWindowNode],
) -> TemporalRinWindowEdge:
    residue_index_i, residue_index_j = pair
    node_i = nodes_by_index[residue_index_i]
    node_j = nodes_by_index[residue_index_j]
    all_edge_types = tuple(
        sorted(interactions_by_type, key=_edge_type_priority_key)
    )
    primary_edge_type = all_edge_types[0]
    return TemporalRinWindowEdge(
        id=(
            f"{condition}:{window_id}:{residue_index_i}--{residue_index_j}:"
            f"{primary_edge_type}"
        ),
        condition=condition,
        window_id=window_id,
        source=node_i.id,
        target=node_j.id,
        residue_index_i=residue_index_i,
        resid_i=node_i.resid,
        resname_i=node_i.resname,
        segment_id_i=node_i.segment_id,
        residue_index_j=residue_index_j,
        resid_j=node_j.resid,
        resname_j=node_j.resname,
        segment_id_j=node_j.segment_id,
        primary_edge_type=primary_edge_type,
        all_edge_types=all_edge_types,
        interactions=tuple(
            interactions_by_type[edge_type] for edge_type in all_edge_types
        ),
    )


def _edge_type_priority_key(edge_type: str) -> tuple[int, str]:
    return (_EDGE_TYPE_PRIORITY_INDEX[edge_type], edge_type)


__all__ = [
    "TEMPORAL_RIN_STATUS_COMPUTED",
    "TEMPORAL_RIN_STATUS_EMPTY_INPUT",
    "TEMPORAL_RIN_STATUS_EMPTY_WINDOW",
    "TEMPORAL_RIN_STATUS_NO_CONTACTS_PASSING_THRESHOLD",
    "TemporalRinWindowEdge",
    "TemporalRinWindowGraph",
    "TemporalRinWindowGraphBundle",
    "TemporalRinWindowInteraction",
    "TemporalRinWindowNode",
    "build_temporal_rin_window_graphs",
]
