"""Stage 22.C temporal graph metrics and deterministic CSV export."""

from __future__ import annotations

import csv
import math
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from mania.analysis.static_rin_communities import (
    STATIC_RIN_COMMUNITY_ALGORITHM,
    compute_static_rin_communities,
)
from mania.analysis.static_rin_graph import (
    StaticRinEdge,
    StaticRinGraph,
    StaticRinInteraction,
    StaticRinNode,
)
from mania.analysis.static_rin_metrics import compute_static_rin_metrics
from mania.analysis.temporal_rin_windows import (
    TEMPORAL_RIN_STATUS_COMPUTED,
    TEMPORAL_RIN_STATUS_EMPTY_WINDOW,
    TEMPORAL_RIN_STATUS_NO_CONTACTS_PASSING_THRESHOLD,
    TemporalRinWindowEdge,
    TemporalRinWindowGraph,
    TemporalRinWindowGraphBundle,
)

TEMPORAL_RIN_STATUS_SKIPPED_NO_NODES = "skipped_no_nodes"
TEMPORAL_RIN_STATUS_SKIPPED_NO_EDGES = "skipped_no_edges"

TEMPORAL_RIN_METRICS_COLUMNS = (
    "condition",
    "window_id",
    "frame_start",
    "frame_end",
    "sampled_frame_count",
    "active_frame_count",
    "n_nodes",
    "n_edges",
    "density",
    "mean_degree",
    "mean_strength",
    "betweenness_mean",
    "betweenness_max",
    "closeness_mean",
    "modularity",
    "n_communities",
    "community_algorithm",
    "status",
    "notes",
)

_EMPTY_STATUSES = {
    TEMPORAL_RIN_STATUS_EMPTY_WINDOW,
    TEMPORAL_RIN_STATUS_NO_CONTACTS_PASSING_THRESHOLD,
}


class TemporalRinMetricsError(ValueError):
    """Raised when temporal graph metrics cannot be computed or written."""


@dataclass(frozen=True)
class TemporalRinWindowMetrics:
    """One deterministic metrics summary for an accepted temporal window."""

    condition: str
    window_id: int
    frame_start: int
    frame_end: int
    sampled_frame_count: int
    active_frame_count: int
    n_nodes: int
    n_edges: int
    density: float | None
    mean_degree: float | None
    mean_strength: float | None
    betweenness_mean: float | None
    betweenness_max: float | None
    closeness_mean: float | None
    modularity: float | None
    n_communities: int | None
    community_algorithm: str | None
    status: str
    notes: str

    def to_dict(self) -> dict[str, object]:
        """Return one row in the accepted temporal artifact column order."""
        return {
            column: getattr(self, column)
            for column in TEMPORAL_RIN_METRICS_COLUMNS
        }


@dataclass(frozen=True)
class TemporalRinMetrics:
    """All Stage 22.C temporal metrics for one condition."""

    condition: str
    windows: tuple[TemporalRinWindowMetrics, ...]


def compute_temporal_rin_metrics(
    window_graphs: TemporalRinWindowGraphBundle,
) -> TemporalRinMetrics:
    """Compute per-window metrics from accepted Stage 22.B graph structures.

    ``active_frame_count`` is the Stage 22.B count of sampled frames containing
    at least one accepted contact row before ``TEMP_MIN_FREQ`` filtering.
    Betweenness, closeness, communities, and modularity are unweighted. Edge
    weights contribute only to strength through the primary interaction's
    ``window_contact_freq``.
    """
    if not isinstance(window_graphs, TemporalRinWindowGraphBundle):
        raise TypeError("window_graphs must be a TemporalRinWindowGraphBundle")

    ordered = sorted(
        window_graphs.windows,
        key=lambda graph: (graph.window_id, graph.frame_start, graph.frame_end),
    )
    window_ids = [graph.window_id for graph in ordered]
    if len(window_ids) != len(set(window_ids)):
        raise TemporalRinMetricsError("temporal window_id values must be unique")
    rows = tuple(
        _compute_window_metrics(graph, expected_condition=window_graphs.condition)
        for graph in ordered
    )
    return TemporalRinMetrics(condition=window_graphs.condition, windows=rows)


def write_temporal_rin_csv(
    metrics: TemporalRinMetrics,
    output_dir: str | Path,
) -> Path:
    """Write ``temporal_rin_{condition}.csv`` deterministically and atomically."""
    if not isinstance(metrics, TemporalRinMetrics):
        raise TypeError("metrics must be TemporalRinMetrics")
    component = re.sub(r"[^A-Za-z0-9_.-]+", "_", metrics.condition).strip("._")
    if not component:
        raise TemporalRinMetricsError(
            "condition must contain a filename-safe character"
        )
    directory = Path(output_dir)
    if directory.exists() and not directory.is_dir():
        raise TemporalRinMetricsError("temporal RIN output is not a directory")
    output_path = directory / f"temporal_rin_{component}.csv"
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
                fieldnames=TEMPORAL_RIN_METRICS_COLUMNS,
                lineterminator="\n",
            )
            writer.writeheader()
            for row in metrics.windows:
                writer.writerow(
                    {key: _csv_value(value) for key, value in row.to_dict().items()}
                )
        temporary_path.replace(output_path)
    except (OSError, csv.Error) as error:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise TemporalRinMetricsError(
            f"temporal RIN metrics could not be written: {output_path}"
        ) from error
    return output_path


def _compute_window_metrics(
    graph: TemporalRinWindowGraph,
    *,
    expected_condition: str,
) -> TemporalRinWindowMetrics:
    _validate_window(graph, expected_condition=expected_condition)
    n_nodes = len(graph.nodes)
    n_edges = len(graph.edges)
    if graph.status in _EMPTY_STATUSES:
        return _skipped_row(graph, graph.status)
    if not n_nodes:
        return _skipped_row(graph, TEMPORAL_RIN_STATUS_SKIPPED_NO_NODES)
    if not n_edges:
        return _skipped_row(graph, TEMPORAL_RIN_STATUS_SKIPPED_NO_EDGES)
    if graph.status != TEMPORAL_RIN_STATUS_COMPUTED:
        raise TemporalRinMetricsError(
            f"unsupported temporal window status: {graph.status}"
        )

    static_graph = _as_static_graph(graph)
    node_metrics = compute_static_rin_metrics(static_graph).node_metrics
    communities = compute_static_rin_communities(static_graph)
    strengths = [row.strength for row in node_metrics]
    mean_strength = (
        math.fsum(value for value in strengths if value is not None) / n_nodes
        if all(value is not None for value in strengths)
        else None
    )
    notes = (
        "mean_strength unavailable because at least one incident weight is missing"
        if mean_strength is None
        else ""
    )
    betweenness = [row.betweenness for row in node_metrics]
    closeness = [row.closeness for row in node_metrics]
    return TemporalRinWindowMetrics(
        condition=graph.condition,
        window_id=graph.window_id,
        frame_start=graph.frame_start,
        frame_end=graph.frame_end,
        sampled_frame_count=graph.sampled_frame_count,
        active_frame_count=graph.active_frame_count,
        n_nodes=n_nodes,
        n_edges=n_edges,
        density=(2.0 * n_edges) / (n_nodes * (n_nodes - 1)),
        mean_degree=math.fsum(row.degree for row in node_metrics) / n_nodes,
        mean_strength=mean_strength,
        betweenness_mean=math.fsum(betweenness) / n_nodes,
        betweenness_max=max(betweenness),
        closeness_mean=math.fsum(closeness) / n_nodes,
        modularity=communities.modularity,
        n_communities=communities.n_communities,
        community_algorithm=STATIC_RIN_COMMUNITY_ALGORITHM,
        status=TEMPORAL_RIN_STATUS_COMPUTED,
        notes=notes,
    )


def _skipped_row(
    graph: TemporalRinWindowGraph,
    status: str,
) -> TemporalRinWindowMetrics:
    notes = {
        TEMPORAL_RIN_STATUS_EMPTY_WINDOW: "no accepted contact rows in window",
        TEMPORAL_RIN_STATUS_NO_CONTACTS_PASSING_THRESHOLD: (
            "no typed contacts met min_frequency"
        ),
        TEMPORAL_RIN_STATUS_SKIPPED_NO_NODES: "window graph has no active nodes",
        TEMPORAL_RIN_STATUS_SKIPPED_NO_EDGES: "window graph has no passing edges",
    }[status]
    return TemporalRinWindowMetrics(
        condition=graph.condition,
        window_id=graph.window_id,
        frame_start=graph.frame_start,
        frame_end=graph.frame_end,
        sampled_frame_count=graph.sampled_frame_count,
        active_frame_count=graph.active_frame_count,
        n_nodes=len(graph.nodes),
        n_edges=len(graph.edges),
        density=None,
        mean_degree=None,
        mean_strength=None,
        betweenness_mean=None,
        betweenness_max=None,
        closeness_mean=None,
        modularity=None,
        n_communities=None,
        community_algorithm=None,
        status=status,
        notes=notes,
    )


def _validate_window(
    graph: TemporalRinWindowGraph,
    *,
    expected_condition: str,
) -> None:
    if graph.condition != expected_condition:
        raise TemporalRinMetricsError("temporal window condition does not match bundle")
    if graph.sampled_frame_count != len(graph.frame_indexes):
        raise TemporalRinMetricsError(
            "sampled_frame_count does not match window frame_indexes"
        )
    if not graph.frame_indexes:
        raise TemporalRinMetricsError("temporal window must contain sampled frames")
    if (graph.frame_start, graph.frame_end) != (
        graph.frame_indexes[0],
        graph.frame_indexes[-1],
    ):
        raise TemporalRinMetricsError(
            "inclusive frame boundaries do not match window frame_indexes"
        )
    if not 0 <= graph.active_frame_count <= graph.sampled_frame_count:
        raise TemporalRinMetricsError(
            "active_frame_count must be between zero and sampled_frame_count"
        )


def _as_static_graph(graph: TemporalRinWindowGraph) -> StaticRinGraph:
    return StaticRinGraph(
        condition=graph.condition,
        nodes=tuple(
            StaticRinNode(
                id=node.id,
                condition=node.condition,
                residue_index=node.residue_index,
                resid=node.resid,
                resname=node.resname,
                segment_id=node.segment_id,
                region=None,
                x_ca=None,
                y_ca=None,
                z_ca=None,
                tm_relative_z=None,
                rmsf_A=None,
                sasa_A2=None,
                ss=None,
            )
            for node in graph.nodes
        ),
        edges=tuple(_as_static_edge(edge) for edge in graph.edges),
        source_artifacts={},
    )


def _as_static_edge(edge: TemporalRinWindowEdge) -> StaticRinEdge:
    interactions = tuple(
        StaticRinInteraction(
            edge_type=interaction.edge_type,
            contact_frame_count=interaction.observed_frame_count,
            sampled_frame_count=interaction.sampled_frame_count,
            contact_freq=_optional_weight(interaction.window_contact_freq),
            mean_dist_A=interaction.mean_dist_A,
            std_dist_A=interaction.std_dist_A,
        )
        for interaction in edge.interactions
    )
    return StaticRinEdge(
        id=(
            f"{edge.condition}:{edge.residue_index_i}--{edge.residue_index_j}:"
            f"{edge.primary_edge_type}"
        ),
        condition=edge.condition,
        source=edge.source,
        target=edge.target,
        residue_index_i=edge.residue_index_i,
        resid_i=edge.resid_i,
        resname_i=edge.resname_i,
        segment_id_i=edge.segment_id_i,
        residue_index_j=edge.residue_index_j,
        resid_j=edge.resid_j,
        resname_j=edge.resname_j,
        segment_id_j=edge.segment_id_j,
        primary_edge_type=edge.primary_edge_type,
        all_edge_types=edge.all_edge_types,
        interactions=interactions,
    )


def _optional_weight(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TemporalRinMetricsError("window edge weight must be numeric or missing")
    numeric = float(value)
    if not math.isfinite(numeric) or not 0.0 <= numeric <= 1.0:
        raise TemporalRinMetricsError("window edge weight must be between zero and one")
    return numeric


def _csv_value(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, float):
        return format(value, ".15g")
    return value


__all__ = [
    "TEMPORAL_RIN_METRICS_COLUMNS",
    "TEMPORAL_RIN_STATUS_SKIPPED_NO_EDGES",
    "TEMPORAL_RIN_STATUS_SKIPPED_NO_NODES",
    "TemporalRinMetrics",
    "TemporalRinMetricsError",
    "TemporalRinWindowMetrics",
    "compute_temporal_rin_metrics",
    "write_temporal_rin_csv",
]
