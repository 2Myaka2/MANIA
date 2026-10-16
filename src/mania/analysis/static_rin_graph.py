"""Static analysis RIN graph construction from accepted Stage 20 artifacts."""

from __future__ import annotations

import csv
import json
import math
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from mania.constants import EDGE_TYPE_PRIORITY
from mania.preprocessing.trajectory_protein_contact_export import (
    PROTEIN_CONTACT_EDGE_COLUMNS,
)
from mania.preprocessing.trajectory_residue_table_export import (
    RESIDUE_TABLE_COLUMNS,
)

STATIC_RIN_GRAPH_SCHEMA_VERSION = "mania.static_rin_graph.v0.1"

_EDGE_TYPE_PRIORITY_INDEX = {
    edge_type: index for index, edge_type in enumerate(EDGE_TYPE_PRIORITY)
}


class StaticRinGraphError(ValueError):
    """Raised when Stage 20 artifacts cannot form a static analysis graph."""


@dataclass(frozen=True)
class StaticRinNode:
    """One Stage 20.A residue represented as an analysis graph node."""

    id: str
    condition: str
    residue_index: int
    resid: str
    resname: str
    segment_id: str | None
    region: str | None
    x_ca: float | None
    y_ca: float | None
    z_ca: float | None
    tm_relative_z: float | None
    rmsf_A: float | None
    sasa_A2: float | None
    ss: str | None

    def to_dict(self) -> dict[str, object]:
        """Return the node as a JSON-safe dictionary."""
        return {
            "id": self.id,
            "condition": self.condition,
            "residue_index": self.residue_index,
            "resid": self.resid,
            "resname": self.resname,
            "segment_id": self.segment_id,
            "region": self.region,
            "x_ca": self.x_ca,
            "y_ca": self.y_ca,
            "z_ca": self.z_ca,
            "tm_relative_z": self.tm_relative_z,
            "rmsf_A": self.rmsf_A,
            "sasa_A2": self.sasa_A2,
            "ss": self.ss,
        }


@dataclass(frozen=True)
class StaticRinInteraction:
    """One typed Stage 20.B aggregate retained on a residue-pair edge."""

    edge_type: str
    contact_frame_count: int | None
    sampled_frame_count: int | None
    contact_freq: float | None
    mean_dist_A: float | None
    std_dist_A: float | None

    @property
    def weight(self) -> float | None:
        """Return the accepted static edge weight without inventing a value."""
        return self.contact_freq

    def to_dict(self) -> dict[str, object]:
        """Return the typed observation as a JSON-safe dictionary."""
        return {
            "edge_type": self.edge_type,
            "contact_frame_count": self.contact_frame_count,
            "sampled_frame_count": self.sampled_frame_count,
            "contact_freq": self.contact_freq,
            "weight": self.weight,
            "mean_dist_A": self.mean_dist_A,
            "std_dist_A": self.std_dist_A,
        }


@dataclass(frozen=True)
class StaticRinEdge:
    """One deterministic undirected residue-pair analysis edge."""

    id: str
    condition: str
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
    interactions: tuple[StaticRinInteraction, ...]

    @property
    def primary_interaction(self) -> StaticRinInteraction:
        """Return the interaction selected by the central edge priority."""
        return self.interactions[0]

    def to_dict(self) -> dict[str, object]:
        """Return the edge as a JSON-safe dictionary."""
        primary = self.primary_interaction
        return {
            "id": self.id,
            "condition": self.condition,
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
            "contact_frame_count": primary.contact_frame_count,
            "sampled_frame_count": primary.sampled_frame_count,
            "contact_freq": primary.contact_freq,
            "weight": primary.weight,
            "mean_dist_A": primary.mean_dist_A,
            "std_dist_A": primary.std_dist_A,
            "interactions": [
                interaction.to_dict() for interaction in self.interactions
            ],
        }


@dataclass(frozen=True)
class StaticRinGraph:
    """One per-condition static analysis graph built from Stage 20 artifacts."""

    condition: str
    nodes: tuple[StaticRinNode, ...]
    edges: tuple[StaticRinEdge, ...]
    source_artifacts: Mapping[str, str]

    def to_dict(self) -> dict[str, object]:
        """Return the deterministic portable graph payload."""
        return {
            "schema_version": STATIC_RIN_GRAPH_SCHEMA_VERSION,
            "artifact": "MANIA static analysis RIN graph",
            "condition": self.condition,
            "directed": False,
            "n_nodes": len(self.nodes),
            "n_edges": len(self.edges),
            "edge_priority": list(EDGE_TYPE_PRIORITY),
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
            "metadata": {
                "stage": "21.A",
                "node_id_format": "{condition}:{residue_index}",
                "edge_id_format": (
                    "{condition}:{residue_index_i}--{residue_index_j}:"
                    "{primary_edge_type}"
                ),
                "missing_contact_freq_behavior": (
                    "contact_freq and weight are null"
                ),
                "source_artifacts": {
                    key: value
                    for key, value in sorted(self.source_artifacts.items())
                },
            },
        }


@dataclass(frozen=True)
class _EndpointIdentity:
    residue_index: int
    resid: str
    resname: str
    segment_id: str | None


def build_static_rin_graph(
    residue_table_path: str | Path,
    protein_contact_edges_path: str | Path,
    *,
    edge_semantics_path: str | Path | None = None,
    mania_manifest_path: str | Path | None = None,
    residue_library_path: str | Path | None = None,
) -> StaticRinGraph:
    """Build one static analysis graph from accepted Stage 20 artifacts."""
    residue_path = Path(residue_table_path)
    edge_path = Path(protein_contact_edges_path)
    residue_rows = _read_csv_rows(
        residue_path,
        required_columns=RESIDUE_TABLE_COLUMNS,
        artifact_label="Stage 20 residue table",
    )
    edge_rows = _read_csv_rows(
        edge_path,
        required_columns=PROTEIN_CONTACT_EDGE_COLUMNS,
        artifact_label="Stage 20 protein contact edges",
    )
    if not residue_rows:
        raise StaticRinGraphError(
            "Stage 20 residue table must contain at least one row"
        )

    condition = _single_condition(residue_rows, "residue table")
    if edge_rows:
        edge_condition = _single_condition(edge_rows, "protein contact edges")
        if edge_condition != condition:
            raise StaticRinGraphError(
                "Stage 20 residue and protein contact conditions do not match"
            )

    source_artifacts = {
        "residue_table": residue_path.name,
        "protein_contact_edges": edge_path.name,
    }
    if edge_semantics_path is not None:
        semantics_path = Path(edge_semantics_path)
        semantics = _read_json_object(semantics_path, "edge semantics")
        if semantics.get("edge_priority") != list(EDGE_TYPE_PRIORITY):
            raise StaticRinGraphError(
                "edge_semantics.json priority does not match EDGE_TYPE_PRIORITY"
            )
        source_artifacts["edge_semantics"] = semantics_path.name
    if mania_manifest_path is not None:
        manifest_path = Path(mania_manifest_path)
        manifest = _read_json_object(manifest_path, "MANIA manifest")
        _require_manifest_condition(manifest, condition)
        source_artifacts["mania_manifest"] = manifest_path.name
    if residue_library_path is not None:
        library_path = Path(residue_library_path)
        library = _read_json_object(library_path, "MANIA residue library")
        _require_library_condition(library, condition)
        source_artifacts["residue_library"] = library_path.name

    nodes = _build_nodes(residue_rows, condition)
    edges = _build_edges(edge_rows, condition, nodes)
    return StaticRinGraph(
        condition=condition,
        nodes=nodes,
        edges=edges,
        source_artifacts=source_artifacts,
    )


def write_static_rin_graph_json(
    graph: StaticRinGraph,
    output_path: str | Path,
) -> Path:
    """Write a static analysis graph deterministically and atomically."""
    if not isinstance(graph, StaticRinGraph):
        raise TypeError("graph must be a StaticRinGraph")
    path = Path(output_path)
    if path.exists() and path.is_dir():
        raise StaticRinGraphError("static RIN graph output path is a directory")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as json_file:
                temporary_path = Path(json_file.name)
                json.dump(
                    graph.to_dict(),
                    json_file,
                    indent=2,
                    sort_keys=True,
                    allow_nan=False,
                )
                json_file.write("\n")
            temporary_path.replace(path)
        except (OSError, TypeError, ValueError):
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise
    except OSError as error:
        raise StaticRinGraphError(
            f"static RIN graph could not be written: {path}"
        ) from error
    return path


def _read_csv_rows(
    path: Path,
    *,
    required_columns: Sequence[str],
    artifact_label: str,
) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            fieldnames = reader.fieldnames
            if fieldnames is None:
                raise StaticRinGraphError(f"{artifact_label} is missing a header")
            missing = [
                column for column in required_columns if column not in fieldnames
            ]
            if missing:
                raise StaticRinGraphError(
                    f"{artifact_label} is missing required columns: "
                    + ", ".join(missing)
                )
            return [
                {
                    column: value if value is not None else ""
                    for column, value in row.items()
                    if column is not None
                }
                for row in reader
            ]
    except FileNotFoundError as error:
        raise StaticRinGraphError(f"missing {artifact_label}: {path}") from error
    except (OSError, csv.Error) as error:
        raise StaticRinGraphError(
            f"{artifact_label} could not be read: {path}"
        ) from error


def _read_json_object(path: Path, artifact_label: str) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise StaticRinGraphError(f"missing {artifact_label}: {path}") from error
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise StaticRinGraphError(
            f"{artifact_label} could not be read as JSON: {path}"
        ) from error
    if not isinstance(payload, dict):
        raise StaticRinGraphError(f"{artifact_label} must be a JSON object")
    return payload


def _single_condition(rows: Sequence[Mapping[str, str]], label: str) -> str:
    conditions = {row["condition"].strip() for row in rows}
    if "" in conditions:
        raise StaticRinGraphError(f"{label} contains an empty condition")
    if len(conditions) != 1:
        raise StaticRinGraphError(f"{label} must contain exactly one condition")
    return next(iter(conditions))


def _build_nodes(
    rows: Sequence[Mapping[str, str]],
    condition: str,
) -> tuple[StaticRinNode, ...]:
    nodes_by_index: dict[int, StaticRinNode] = {}
    for row_number, row in enumerate(rows, start=2):
        residue_index = _required_int(
            row["residue_index"], "residue_index", row_number
        )
        resid = _required_text(row["resid"], "resid", row_number)
        resname = _required_text(row["resname"], "resname", row_number)
        if residue_index in nodes_by_index:
            raise StaticRinGraphError(
                f"duplicate residue_index at row {row_number}: {residue_index}"
            )
        nodes_by_index[residue_index] = StaticRinNode(
            id=_node_id(condition, residue_index),
            condition=condition,
            residue_index=residue_index,
            resid=resid,
            resname=resname,
            segment_id=_optional_text(row["segment_id"]),
            region=_optional_text(row["region"]),
            x_ca=_optional_float(row["x_ca"], "x_ca", row_number),
            y_ca=_optional_float(row["y_ca"], "y_ca", row_number),
            z_ca=_optional_float(row["z_ca"], "z_ca", row_number),
            tm_relative_z=_optional_float(
                row["tm_relative_z"], "tm_relative_z", row_number
            ),
            rmsf_A=_optional_float(row["rmsf_A"], "rmsf_A", row_number),
            sasa_A2=_optional_float(row["sasa_A2"], "sasa_A2", row_number),
            ss=_optional_text(row["ss"]),
        )
    return tuple(nodes_by_index[index] for index in sorted(nodes_by_index))


def _build_edges(
    rows: Sequence[Mapping[str, str]],
    condition: str,
    nodes: Sequence[StaticRinNode],
) -> tuple[StaticRinEdge, ...]:
    nodes_by_index = {node.residue_index: node for node in nodes}
    grouped: dict[tuple[int, int], dict[str, StaticRinInteraction]] = {}
    for row_number, row in enumerate(rows, start=2):
        endpoint_i = _edge_endpoint(row, "i", row_number)
        endpoint_j = _edge_endpoint(row, "j", row_number)
        if endpoint_i.residue_index == endpoint_j.residue_index:
            raise StaticRinGraphError(
                f"self edge is not allowed at row {row_number}"
            )
        _validate_endpoint(endpoint_i, nodes_by_index, row_number)
        _validate_endpoint(endpoint_j, nodes_by_index, row_number)
        if endpoint_j.residue_index < endpoint_i.residue_index:
            endpoint_i, endpoint_j = endpoint_j, endpoint_i

        edge_type = _required_text(row["edge_type"], "edge_type", row_number)
        if edge_type not in _EDGE_TYPE_PRIORITY_INDEX:
            raise StaticRinGraphError(
                f"unsupported Stage 20 edge_type at row {row_number}: {edge_type}"
            )
        contact_freq = _optional_float(
            row["contact_freq"], "contact_freq", row_number
        )
        if contact_freq is not None and not 0.0 <= contact_freq <= 1.0:
            raise StaticRinGraphError(
                f"contact_freq must be between 0 and 1 at row {row_number}"
            )
        source_weight = _optional_float(row["weight"], "weight", row_number)
        if contact_freq is None and source_weight is not None:
            raise StaticRinGraphError(
                f"weight requires contact_freq at row {row_number}"
            )
        if (
            contact_freq is not None
            and source_weight is not None
            and not math.isclose(contact_freq, source_weight, abs_tol=1e-12)
        ):
            raise StaticRinGraphError(
                f"weight must equal contact_freq at row {row_number}"
            )
        interaction = StaticRinInteraction(
            edge_type=edge_type,
            contact_frame_count=_optional_int(
                row["contact_frame_count"], "contact_frame_count", row_number
            ),
            sampled_frame_count=_optional_int(
                row["sampled_frame_count"], "sampled_frame_count", row_number
            ),
            contact_freq=contact_freq,
            mean_dist_A=_optional_non_negative_float(
                row["mean_dist_A"], "mean_dist_A", row_number
            ),
            std_dist_A=_optional_non_negative_float(
                row["std_dist_A"], "std_dist_A", row_number
            ),
        )
        pair = (endpoint_i.residue_index, endpoint_j.residue_index)
        interactions = grouped.setdefault(pair, {})
        if edge_type in interactions:
            raise StaticRinGraphError(
                f"duplicate residue-pair edge_type at row {row_number}: "
                f"{pair} {edge_type}"
            )
        interactions[edge_type] = interaction

    edges: list[StaticRinEdge] = []
    for residue_index_i, residue_index_j in sorted(grouped):
        node_i = nodes_by_index[residue_index_i]
        node_j = nodes_by_index[residue_index_j]
        interactions_by_type = grouped[(residue_index_i, residue_index_j)]
        all_edge_types = tuple(
            sorted(interactions_by_type, key=_edge_type_priority_key)
        )
        primary_edge_type = all_edge_types[0]
        ordered_interactions = tuple(
            interactions_by_type[edge_type] for edge_type in all_edge_types
        )
        edges.append(
            StaticRinEdge(
                id=_edge_id(
                    condition,
                    residue_index_i,
                    residue_index_j,
                    primary_edge_type,
                ),
                condition=condition,
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
                interactions=ordered_interactions,
            )
        )
    return tuple(edges)


def _edge_endpoint(
    row: Mapping[str, str],
    suffix: str,
    row_number: int,
) -> _EndpointIdentity:
    return _EndpointIdentity(
        residue_index=_required_int(
            row[f"residue_index_{suffix}"],
            f"residue_index_{suffix}",
            row_number,
        ),
        resid=_required_text(row[f"resid_{suffix}"], f"resid_{suffix}", row_number),
        resname=_required_text(
            row[f"resname_{suffix}"], f"resname_{suffix}", row_number
        ),
        segment_id=_optional_text(row[f"segment_id_{suffix}"]),
    )


def _validate_endpoint(
    endpoint: _EndpointIdentity,
    nodes_by_index: Mapping[int, StaticRinNode],
    row_number: int,
) -> None:
    node = nodes_by_index.get(endpoint.residue_index)
    if node is None:
        raise StaticRinGraphError(
            f"edge at row {row_number} references missing residue_index: "
            f"{endpoint.residue_index}"
        )
    expected = (node.resid, node.resname, node.segment_id)
    actual = (endpoint.resid, endpoint.resname, endpoint.segment_id)
    if actual != expected:
        raise StaticRinGraphError(
            f"edge identity does not match residue table at row {row_number}"
        )


def _require_manifest_condition(
    manifest: Mapping[str, object], condition: str
) -> None:
    conditions = manifest.get("conditions")
    if not isinstance(conditions, list) or condition not in conditions:
        raise StaticRinGraphError(
            "mania_manifest.json does not report the graph condition"
        )


def _require_library_condition(
    library: Mapping[str, object], condition: str
) -> None:
    condition_rows = library.get("conditions")
    if not isinstance(condition_rows, list) or not any(
        isinstance(row, dict) and row.get("condition") == condition
        for row in condition_rows
    ):
        raise StaticRinGraphError(
            "mania_residue_library.json does not report the graph condition"
        )


def _required_text(value: str, field: str, row_number: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise StaticRinGraphError(f"empty {field} at row {row_number}")
    return normalized


def _optional_text(value: str) -> str | None:
    normalized = value.strip()
    return normalized or None


def _required_int(value: str, field: str, row_number: int) -> int:
    parsed = _optional_int(value, field, row_number)
    if parsed is None:
        raise StaticRinGraphError(f"empty {field} at row {row_number}")
    return parsed


def _optional_int(value: str, field: str, row_number: int) -> int | None:
    normalized = value.strip()
    if not normalized:
        return None
    try:
        parsed = int(normalized)
    except ValueError as error:
        raise StaticRinGraphError(
            f"invalid integer {field} at row {row_number}"
        ) from error
    if parsed < 0:
        raise StaticRinGraphError(
            f"{field} must be non-negative at row {row_number}"
        )
    return parsed


def _optional_float(value: str, field: str, row_number: int) -> float | None:
    normalized = value.strip()
    if not normalized:
        return None
    try:
        parsed = float(normalized)
    except ValueError as error:
        raise StaticRinGraphError(
            f"invalid numeric {field} at row {row_number}"
        ) from error
    if not math.isfinite(parsed):
        raise StaticRinGraphError(f"non-finite {field} at row {row_number}")
    return parsed


def _optional_non_negative_float(
    value: str,
    field: str,
    row_number: int,
) -> float | None:
    parsed = _optional_float(value, field, row_number)
    if parsed is not None and parsed < 0:
        raise StaticRinGraphError(
            f"{field} must be non-negative at row {row_number}"
        )
    return parsed


def _node_id(condition: str, residue_index: int) -> str:
    return f"{condition}:{residue_index}"


def _edge_id(
    condition: str,
    residue_index_i: int,
    residue_index_j: int,
    primary_edge_type: str,
) -> str:
    return (
        f"{condition}:{residue_index_i}--{residue_index_j}:"
        f"{primary_edge_type}"
    )


def _edge_type_priority_key(edge_type: str) -> tuple[int, str]:
    return (_EDGE_TYPE_PRIORITY_INDEX[edge_type], edge_type)


__all__ = [
    "STATIC_RIN_GRAPH_SCHEMA_VERSION",
    "StaticRinEdge",
    "StaticRinGraph",
    "StaticRinGraphError",
    "StaticRinInteraction",
    "StaticRinNode",
    "build_static_rin_graph",
    "write_static_rin_graph_json",
]
