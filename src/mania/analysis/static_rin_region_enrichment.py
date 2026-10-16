"""Deterministic region enrichment for accepted static RIN communities."""

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

from mania.analysis.static_rin_communities import (
    STATIC_RIN_COMMUNITIES_COLUMNS,
    STATIC_RIN_COMMUNITY_ALGORITHM,
    StaticRinCommunities,
)
from mania.analysis.static_rin_graph import (
    STATIC_RIN_GRAPH_SCHEMA_VERSION,
    StaticRinGraph,
)

STATIC_RIN_REGION_ENRICHMENT_METHOD = "fisher_exact_two_sided"
STATIC_RIN_REGION_ENRICHMENT_COLUMNS = (
    "condition",
    "community_id",
    "community_size",
    "region",
    "region_count_in_community",
    "non_region_count_in_community",
    "region_count_outside_community",
    "non_region_count_outside_community",
    "odds_ratio",
    "p_value",
    "method",
    "status",
    "algorithm",
    "n_communities",
    "total_region_count",
    "labeled_node_count",
    "total_node_count",
    "notes",
)

STATUS_COMPUTED = "computed"
STATUS_SKIPPED_EMPTY_GRAPH = "skipped_empty_graph"
STATUS_SKIPPED_NO_REGION_LABELS = "skipped_no_region_labels"
STATUS_SKIPPED_INSUFFICIENT_GROUPS = "skipped_insufficient_groups"
STATUS_SKIPPED_INSUFFICIENT_CONTINGENCY = (
    "skipped_insufficient_contingency"
)


class StaticRinRegionEnrichmentError(ValueError):
    """Raised when accepted enrichment inputs cannot be consumed or written."""


@dataclass(frozen=True)
class StaticRinRegionEnrichmentRow:
    """One auditable community-by-region enrichment or skipped result."""

    condition: str
    community_id: int | None
    community_size: int | None
    region: str | None
    region_count_in_community: int | None
    non_region_count_in_community: int | None
    region_count_outside_community: int | None
    non_region_count_outside_community: int | None
    odds_ratio: float | None
    p_value: float | None
    method: str | None
    status: str
    algorithm: str | None
    n_communities: int
    total_region_count: int | None
    labeled_node_count: int
    total_node_count: int
    notes: str

    def to_dict(self) -> dict[str, object]:
        """Return one CSV-ready row without inventing missing values."""
        return {
            column: getattr(self, column)
            for column in STATIC_RIN_REGION_ENRICHMENT_COLUMNS
        }


@dataclass(frozen=True)
class StaticRinRegionEnrichment:
    """Per-condition Stage 21.D region enrichment results."""

    condition: str
    rows: tuple[StaticRinRegionEnrichmentRow, ...]


@dataclass(frozen=True)
class _RegionNode:
    id: str
    condition: str
    residue_index: int
    resid: str
    resname: str
    segment_id: str | None
    region: str | None


@dataclass(frozen=True)
class _CommunityRecord:
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


def compute_static_rin_region_enrichment(
    graph: StaticRinGraph,
    communities: StaticRinCommunities,
) -> StaticRinRegionEnrichment:
    """Compute enrichment from accepted in-memory Stage 21.A/21.C values."""
    if not isinstance(graph, StaticRinGraph):
        raise TypeError("graph must be a StaticRinGraph")
    if not isinstance(communities, StaticRinCommunities):
        raise TypeError("communities must be a StaticRinCommunities")
    nodes = _nodes_from_graph_mapping(graph.to_dict())
    records = tuple(
        _CommunityRecord(
            condition=assignment.condition,
            node_id=assignment.node_id,
            residue_index=assignment.residue_index,
            resid=assignment.resid,
            resname=assignment.resname,
            segment_id=assignment.segment_id,
            community_id=assignment.community_id,
            community_size=assignment.community_size,
            algorithm=assignment.algorithm,
            modularity=assignment.modularity,
            n_communities=assignment.n_communities,
        )
        for assignment in communities.assignments
    )
    return _compute_enrichment(graph.condition, nodes, records)


def compute_static_rin_region_enrichment_from_artifacts(
    graph_json: str | Path | Mapping[str, object],
    communities_csv: str | Path,
) -> StaticRinRegionEnrichment:
    """Load Stage 21.A/21.C artifacts and compute region enrichment."""
    payload = _load_graph_payload(graph_json)
    condition = _required_text(payload.get("condition"), "graph condition")
    nodes = _nodes_from_graph_mapping(payload)
    records = _load_community_records(Path(communities_csv))
    return _compute_enrichment(condition, nodes, records)


def write_static_rin_region_enrichment_csv(
    enrichment: StaticRinRegionEnrichment,
    output_dir: str | Path,
) -> Path:
    """Write ``region_enrichment_{condition}.csv`` atomically."""
    if not isinstance(enrichment, StaticRinRegionEnrichment):
        raise TypeError("enrichment must be a StaticRinRegionEnrichment")
    component = re.sub(
        r"[^A-Za-z0-9_.-]+", "_", enrichment.condition
    ).strip("._")
    if not component:
        raise StaticRinRegionEnrichmentError(
            "condition must contain a filename-safe character"
        )
    directory = Path(output_dir)
    if directory.exists() and not directory.is_dir():
        raise StaticRinRegionEnrichmentError(
            "static RIN region enrichment output is not a directory"
        )
    output_path = directory / f"region_enrichment_{component}.csv"
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
                fieldnames=STATIC_RIN_REGION_ENRICHMENT_COLUMNS,
                lineterminator="\n",
            )
            writer.writeheader()
            for row in enrichment.rows:
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
        raise StaticRinRegionEnrichmentError(
            f"static RIN region enrichment could not be written: {output_path}"
        ) from error
    return output_path


def _compute_enrichment(
    condition: str,
    nodes: Sequence[_RegionNode],
    records: Sequence[_CommunityRecord],
) -> StaticRinRegionEnrichment:
    _validate_community_records(condition, nodes, records)
    total_node_count = len(nodes)
    if not nodes:
        return StaticRinRegionEnrichment(
            condition=condition,
            rows=(
                _skipped_row(
                    condition=condition,
                    status=STATUS_SKIPPED_EMPTY_GRAPH,
                    notes="Stage 21.A graph contains no nodes.",
                    total_node_count=0,
                ),
            ),
        )

    record_by_node = {record.node_id: record for record in records}
    labeled_nodes = tuple(node for node in nodes if node.region is not None)
    algorithm = records[0].algorithm
    n_communities = records[0].n_communities
    if not labeled_nodes:
        return StaticRinRegionEnrichment(
            condition=condition,
            rows=(
                _skipped_row(
                    condition=condition,
                    status=STATUS_SKIPPED_NO_REGION_LABELS,
                    notes=(
                        "No non-empty Stage 21.A node region labels are "
                        "available."
                    ),
                    algorithm=algorithm,
                    n_communities=n_communities,
                    total_node_count=total_node_count,
                ),
            ),
        )

    regions = tuple(sorted({cast(str, node.region) for node in labeled_nodes}))
    community_ids = tuple(sorted({record.community_id for record in records}))
    labeled_node_count = len(labeled_nodes)
    rows: list[StaticRinRegionEnrichmentRow] = []
    for community_id in community_ids:
        community_records = tuple(
            record for record in records if record.community_id == community_id
        )
        community_size = community_records[0].community_size
        labeled_in_community = tuple(
            node
            for node in labeled_nodes
            if record_by_node[node.id].community_id == community_id
        )
        labeled_outside = tuple(
            node
            for node in labeled_nodes
            if record_by_node[node.id].community_id != community_id
        )
        for region in regions:
            a = sum(node.region == region for node in labeled_in_community)
            b = len(labeled_in_community) - a
            c = sum(node.region == region for node in labeled_outside)
            d = len(labeled_outside) - c
            total_region_count = a + c
            status: str
            notes: str
            odds_ratio: float | None = None
            p_value: float | None = None
            method: str | None = None
            if n_communities < 2:
                status = STATUS_SKIPPED_INSUFFICIENT_GROUPS
                notes = "At least two Stage 21.C communities are required."
            elif (
                len(regions) < 2
                or not labeled_in_community
                or not labeled_outside
                or total_region_count == 0
                or total_region_count == labeled_node_count
            ):
                status = STATUS_SKIPPED_INSUFFICIENT_CONTINGENCY
                notes = (
                    "Labeled nodes do not provide non-empty community, "
                    "outside-community, region, and non-region margins."
                )
            else:
                status = STATUS_COMPUTED
                notes = (
                    "Two-sided Fisher exact test over labeled Stage 21.A "
                    "nodes only; unlabeled nodes are excluded."
                )
                odds_ratio = _odds_ratio(a, b, c, d)
                p_value = _fisher_exact_two_sided(a, b, c, d)
                method = STATIC_RIN_REGION_ENRICHMENT_METHOD
            rows.append(
                StaticRinRegionEnrichmentRow(
                    condition=condition,
                    community_id=community_id,
                    community_size=community_size,
                    region=region,
                    region_count_in_community=a,
                    non_region_count_in_community=b,
                    region_count_outside_community=c,
                    non_region_count_outside_community=d,
                    odds_ratio=odds_ratio,
                    p_value=p_value,
                    method=method,
                    status=status,
                    algorithm=algorithm,
                    n_communities=n_communities,
                    total_region_count=total_region_count,
                    labeled_node_count=labeled_node_count,
                    total_node_count=total_node_count,
                    notes=notes,
                )
            )
    return StaticRinRegionEnrichment(condition=condition, rows=tuple(rows))


def _fisher_exact_two_sided(a: int, b: int, c: int, d: int) -> float:
    """Return the exact two-sided p-value for one non-degenerate 2x2 table."""
    row_in = a + b
    region_total = a + c
    total = a + b + c + d
    denominator = math.comb(total, row_in)
    observed_numerator = math.comb(region_total, a) * math.comb(
        total - region_total, row_in - a
    )
    lower = max(0, row_in - (total - region_total))
    upper = min(row_in, region_total)
    selected_numerators = (
        math.comb(region_total, value)
        * math.comb(total - region_total, row_in - value)
        for value in range(lower, upper + 1)
        if (
            math.comb(region_total, value)
            * math.comb(total - region_total, row_in - value)
            <= observed_numerator
        )
    )
    return min(1.0, math.fsum(value / denominator for value in selected_numerators))


def _odds_ratio(a: int, b: int, c: int, d: int) -> float | None:
    denominator = b * c
    if denominator == 0:
        return None
    return (a * d) / denominator


def _skipped_row(
    *,
    condition: str,
    status: str,
    notes: str,
    algorithm: str | None = None,
    n_communities: int = 0,
    total_node_count: int,
) -> StaticRinRegionEnrichmentRow:
    return StaticRinRegionEnrichmentRow(
        condition=condition,
        community_id=None,
        community_size=None,
        region=None,
        region_count_in_community=None,
        non_region_count_in_community=None,
        region_count_outside_community=None,
        non_region_count_outside_community=None,
        odds_ratio=None,
        p_value=None,
        method=None,
        status=status,
        algorithm=algorithm,
        n_communities=n_communities,
        total_region_count=None,
        labeled_node_count=0,
        total_node_count=total_node_count,
        notes=notes,
    )


def _load_graph_payload(
    graph_json: str | Path | Mapping[str, object],
) -> Mapping[str, object]:
    if isinstance(graph_json, Mapping):
        return graph_json
    path = Path(graph_json)
    try:
        payload: object = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise StaticRinRegionEnrichmentError(
            f"missing Stage 21.A static RIN graph: {path}"
        ) from error
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise StaticRinRegionEnrichmentError(
            f"Stage 21.A static RIN graph could not be read: {path}"
        ) from error
    if not isinstance(payload, Mapping):
        raise StaticRinRegionEnrichmentError(
            "static RIN graph JSON must be an object"
        )
    return cast(Mapping[str, object], payload)


def _nodes_from_graph_mapping(
    payload: Mapping[str, object],
) -> tuple[_RegionNode, ...]:
    if payload.get("schema_version") != STATIC_RIN_GRAPH_SCHEMA_VERSION:
        raise StaticRinRegionEnrichmentError(
            "unsupported static RIN graph schema_version"
        )
    if payload.get("directed") is not False:
        raise StaticRinRegionEnrichmentError("static RIN graph must be undirected")
    condition = _required_text(payload.get("condition"), "graph condition")
    raw_nodes = _record_sequence(payload.get("nodes"), "graph nodes")
    raw_edges = _record_sequence(payload.get("edges"), "graph edges")
    if payload.get("n_nodes") != len(raw_nodes):
        raise StaticRinRegionEnrichmentError(
            "static RIN graph n_nodes does not match nodes"
        )
    if payload.get("n_edges") != len(raw_edges):
        raise StaticRinRegionEnrichmentError(
            "static RIN graph n_edges does not match edges"
        )
    nodes_by_id: dict[str, _RegionNode] = {}
    residue_indexes: set[int] = set()
    for index, record in enumerate(raw_nodes):
        if not isinstance(record, Mapping):
            raise StaticRinRegionEnrichmentError(
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
            raise StaticRinRegionEnrichmentError(
                "graph node condition does not match graph"
            )
        if node_id != f"{condition}:{residue_index}":
            raise StaticRinRegionEnrichmentError(
                "graph node ID is not the accepted format"
            )
        if node_id in nodes_by_id or residue_index in residue_indexes:
            raise StaticRinRegionEnrichmentError(
                "static RIN graph contains duplicate nodes"
            )
        nodes_by_id[node_id] = _RegionNode(
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
            region=_optional_text(record.get("region")),
        )
        residue_indexes.add(residue_index)
    return tuple(
        sorted(nodes_by_id.values(), key=lambda node: (node.residue_index, node.id))
    )


def _load_community_records(path: Path) -> tuple[_CommunityRecord, ...]:
    try:
        with path.open(encoding="utf-8", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            missing = set(STATIC_RIN_COMMUNITIES_COLUMNS) - set(
                reader.fieldnames or ()
            )
            if missing:
                raise StaticRinRegionEnrichmentError(
                    "Stage 21.C communities CSV is missing columns: "
                    + ", ".join(sorted(missing))
                )
            records = tuple(
                _community_record_from_row(row, row_number)
                for row_number, row in enumerate(reader, start=2)
            )
    except FileNotFoundError as error:
        raise StaticRinRegionEnrichmentError(
            f"missing Stage 21.C communities artifact: {path}"
        ) from error
    except (OSError, csv.Error) as error:
        raise StaticRinRegionEnrichmentError(
            f"Stage 21.C communities artifact could not be read: {path}"
        ) from error
    return records


def _community_record_from_row(
    row: Mapping[str, str | None], row_number: int
) -> _CommunityRecord:
    def value(field: str) -> str:
        raw = row.get(field)
        return "" if raw is None else raw

    return _CommunityRecord(
        condition=_required_csv_text(value("condition"), "condition", row_number),
        node_id=_required_csv_text(value("node_id"), "node_id", row_number),
        residue_index=_required_csv_int(
            value("residue_index"), "residue_index", row_number
        ),
        resid=_required_csv_text(value("resid"), "resid", row_number),
        resname=_required_csv_text(value("resname"), "resname", row_number),
        segment_id=_optional_csv_text(value("segment_id")),
        community_id=_required_csv_int(
            value("community_id"), "community_id", row_number
        ),
        community_size=_required_csv_int(
            value("community_size"), "community_size", row_number
        ),
        algorithm=_required_csv_text(value("algorithm"), "algorithm", row_number),
        modularity=_required_csv_float(
            value("modularity"), "modularity", row_number
        ),
        n_communities=_required_csv_int(
            value("n_communities"), "n_communities", row_number
        ),
    )


def _validate_community_records(
    condition: str,
    nodes: Sequence[_RegionNode],
    records: Sequence[_CommunityRecord],
) -> None:
    if not nodes:
        if records:
            raise StaticRinRegionEnrichmentError(
                "empty graph must have an empty Stage 21.C communities artifact"
            )
        return
    if not records:
        raise StaticRinRegionEnrichmentError(
            "Stage 21.C communities must assign every graph node"
        )
    nodes_by_id = {node.id: node for node in nodes}
    records_by_id: dict[str, _CommunityRecord] = {}
    for record in records:
        if record.condition != condition:
            raise StaticRinRegionEnrichmentError(
                "community condition does not match graph"
            )
        node = nodes_by_id.get(record.node_id)
        if node is None or record.node_id in records_by_id:
            raise StaticRinRegionEnrichmentError(
                "community node identity does not match graph"
            )
        if (
            record.residue_index,
            record.resid,
            record.resname,
            record.segment_id,
        ) != (node.residue_index, node.resid, node.resname, node.segment_id):
            raise StaticRinRegionEnrichmentError(
                "community residue identity does not match graph"
            )
        records_by_id[record.node_id] = record
    if set(records_by_id) != set(nodes_by_id):
        raise StaticRinRegionEnrichmentError(
            "Stage 21.C communities must assign every graph node exactly once"
        )

    algorithms = {record.algorithm for record in records}
    modularities = {record.modularity for record in records}
    reported_counts = {record.n_communities for record in records}
    community_ids = {record.community_id for record in records}
    if algorithms != {STATIC_RIN_COMMUNITY_ALGORITHM}:
        raise StaticRinRegionEnrichmentError(
            "unsupported Stage 21.C community algorithm"
        )
    if len(modularities) != 1 or len(reported_counts) != 1:
        raise StaticRinRegionEnrichmentError(
            "Stage 21.C community metadata must be consistent"
        )
    n_communities = next(iter(reported_counts))
    if n_communities < 1 or community_ids != set(range(1, n_communities + 1)):
        raise StaticRinRegionEnrichmentError(
            "Stage 21.C community IDs or count are invalid"
        )
    for community_id in community_ids:
        group = tuple(
            record for record in records if record.community_id == community_id
        )
        if any(record.community_size != len(group) for record in group):
            raise StaticRinRegionEnrichmentError(
                "Stage 21.C community_size does not match assignments"
            )


def _record_sequence(value: object, label: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise StaticRinRegionEnrichmentError(f"{label} must be an array")
    return value


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StaticRinRegionEnrichmentError(f"{label} must be a non-empty string")
    return value.strip()


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise StaticRinRegionEnrichmentError(
            "optional graph text fields must be strings or null"
        )
    return value.strip() or None


def _required_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise StaticRinRegionEnrichmentError(
            f"{label} must be a non-negative integer"
        )
    return value


def _required_csv_text(value: str, field: str, row_number: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise StaticRinRegionEnrichmentError(
            f"empty {field} in communities row {row_number}"
        )
    return normalized


def _optional_csv_text(value: str) -> str | None:
    return value.strip() or None


def _required_csv_int(value: str, field: str, row_number: int) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise StaticRinRegionEnrichmentError(
            f"invalid {field} in communities row {row_number}"
        ) from error
    if parsed < 0:
        raise StaticRinRegionEnrichmentError(
            f"invalid {field} in communities row {row_number}"
        )
    return parsed


def _required_csv_float(value: str, field: str, row_number: int) -> float:
    try:
        parsed = float(value)
    except ValueError as error:
        raise StaticRinRegionEnrichmentError(
            f"invalid {field} in communities row {row_number}"
        ) from error
    if not math.isfinite(parsed):
        raise StaticRinRegionEnrichmentError(
            f"invalid {field} in communities row {row_number}"
        )
    return parsed


def _csv_value(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, float):
        return format(value, ".15g")
    return value


__all__ = [
    "STATIC_RIN_REGION_ENRICHMENT_COLUMNS",
    "STATIC_RIN_REGION_ENRICHMENT_METHOD",
    "STATUS_COMPUTED",
    "STATUS_SKIPPED_EMPTY_GRAPH",
    "STATUS_SKIPPED_INSUFFICIENT_CONTINGENCY",
    "STATUS_SKIPPED_INSUFFICIENT_GROUPS",
    "STATUS_SKIPPED_NO_REGION_LABELS",
    "StaticRinRegionEnrichment",
    "StaticRinRegionEnrichmentError",
    "StaticRinRegionEnrichmentRow",
    "compute_static_rin_region_enrichment",
    "compute_static_rin_region_enrichment_from_artifacts",
    "write_static_rin_region_enrichment_csv",
]
