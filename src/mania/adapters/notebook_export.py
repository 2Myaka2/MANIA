"""Minimal notebook export adapters."""

import csv
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from mania.constants import (
    CENTRALITY_COLUMNS,
    COMMUNITIES_COLUMNS,
    EDGE_COLUMNS,
    EDGE_TYPE_PRIORITY,
    GRAPH_REQUIRED_KEYS,
    NODE_COLUMNS,
    RG_TIMESERIES_COLUMNS,
    SCHEMA_VERSION,
)
from mania.validation.artifacts import (
    ArtifactValidationError,
    validate_condition_column,
    validate_csv_artifact_schema,
)
from mania.validation.graph import GraphValidationError, validate_graph_json
from mania.validation.manifest import (
    ManifestValidationError,
    load_manifest_json,
    validate_global_features,
)

NOTEBOOK_RG_COLUMNS = ("frame", "rg_A", "condition")
RESIDUE_TABLE_COLUMNS = NODE_COLUMNS[:11]
EDGE_MULTI_TYPE_COLUMNS = ("all_edge_types", "n_edge_types")
NOTEBOOK_EDGE_REQUIRED_COLUMNS = tuple(
    column for column in EDGE_COLUMNS if column not in EDGE_MULTI_TYPE_COLUMNS
)
EDGE_TYPE_SEPARATOR = "|"
EDGE_TYPE_PRIORITY_INDEX = {
    edge_type: index for index, edge_type in enumerate(EDGE_TYPE_PRIORITY)
}


class NotebookExportAdapterError(Exception):
    """Raised when notebook export adaptation fails."""


@dataclass(frozen=True)
class ConditionExportResult:
    """Paths produced by exporting one condition from notebook-like artifacts."""

    condition: str
    rg_timeseries_path: Path
    centrality_path: Path
    communities_path: Path
    nodes_path: Path
    edges_path: Path
    graph_path: Path

    @property
    def paths(self) -> tuple[Path, ...]:
        """Return generated artifact paths in deterministic export order."""
        return (
            self.rg_timeseries_path,
            self.centrality_path,
            self.communities_path,
            self.nodes_path,
            self.edges_path,
            self.graph_path,
        )


@dataclass(frozen=True)
class MultiConditionExportResult:
    """Results produced by exporting multiple conditions."""

    conditions: tuple[str, ...]
    condition_results: Mapping[str, ConditionExportResult]

    @property
    def paths(self) -> tuple[Path, ...]:
        """Return generated artifact paths by condition and artifact order."""
        paths: list[Path] = []
        for condition in self.conditions:
            paths.extend(self.condition_results[condition].paths)
        return tuple(paths)


@dataclass(frozen=True)
class NotebookContractSubsetExportResult:
    """Paths produced by exporting the supported notebook contract subset."""

    run_meta_path: Path
    conditions_result: MultiConditionExportResult

    @property
    def paths(self) -> tuple[Path, ...]:
        """Return generated paths with run metadata first."""
        return (self.run_meta_path, *self.conditions_result.paths)


def export_notebook_contract_subset(
    source_dir: str | Path,
    output_dir: str | Path,
    conditions: Iterable[str] | None = None,
    *,
    frame_time_ps: float,
) -> NotebookContractSubsetExportResult:
    """Export the currently supported notebook-to-backend contract subset."""
    selected_conditions = tuple(conditions) if conditions is not None else None
    run_meta_path = export_run_meta(
        source_dir=source_dir,
        output_dir=output_dir,
        conditions=selected_conditions,
    )
    export_conditions_arg = (
        _read_run_meta_conditions(run_meta_path)
        if selected_conditions is None
        else selected_conditions
    )
    conditions_result = export_conditions(
        source_dir=source_dir,
        output_dir=output_dir,
        conditions=export_conditions_arg,
        frame_time_ps=frame_time_ps,
    )
    return NotebookContractSubsetExportResult(
        run_meta_path=run_meta_path,
        conditions_result=conditions_result,
    )


def export_conditions(
    source_dir: str | Path,
    output_dir: str | Path,
    conditions: Iterable[str],
    *,
    frame_time_ps: float,
) -> MultiConditionExportResult:
    """Export all currently supported artifacts for multiple conditions."""
    normalized_conditions = _normalize_conditions(conditions)
    condition_results = {
        condition: export_condition(
            source_dir=source_dir,
            output_dir=output_dir,
            condition=condition,
            frame_time_ps=frame_time_ps,
        )
        for condition in normalized_conditions
    }
    return MultiConditionExportResult(
        conditions=normalized_conditions,
        condition_results=condition_results,
    )


def export_run_meta(
    source_dir: str | Path,
    output_dir: str | Path,
    conditions: Iterable[str] | None = None,
) -> Path:
    """Export minimal backend run metadata from a notebook manifest."""
    manifest_path = Path(source_dir) / "mania_manifest.json"
    if not manifest_path.is_file():
        raise NotebookExportAdapterError(f"Missing notebook manifest: {manifest_path}")

    selected_conditions = (
        _normalize_conditions(conditions) if conditions is not None else None
    )
    try:
        validation = validate_global_features(
            manifest_path,
            expected_conditions=selected_conditions,
        )
        manifest = load_manifest_json(manifest_path)
    except ManifestValidationError as exc:
        raise NotebookExportAdapterError(
            f"Invalid notebook manifest: {manifest_path}"
        ) from exc

    output_conditions = (
        selected_conditions
        if selected_conditions is not None
        else validation.conditions
    )
    global_features = manifest.get("global_features")
    if not isinstance(global_features, dict):
        raise NotebookExportAdapterError(
            f"Notebook manifest must contain global_features: {manifest_path}"
        )

    selected_features: dict[str, object] = {}
    for condition in output_conditions:
        if condition not in global_features:
            raise NotebookExportAdapterError(
                f"Missing global features for condition {condition!r}"
            )
        selected_features[condition] = global_features[condition]

    payload = {
        "schema_version": SCHEMA_VERSION,
        "conditions": list(output_conditions),
        "global_features": selected_features,
        "source_manifest": "mania_manifest.json",
    }

    output_path = Path(output_dir) / "run_meta.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise NotebookExportAdapterError(
            f"Failed to write run metadata: {output_path}"
        ) from exc
    return output_path


def export_condition(
    source_dir: str | Path,
    output_dir: str | Path,
    condition: str,
    *,
    frame_time_ps: float,
) -> ConditionExportResult:
    """Export all currently supported artifacts for one condition."""
    rg_timeseries_path = export_rg_timeseries(
        source_dir,
        output_dir,
        condition,
        frame_time_ps=frame_time_ps,
    )
    centrality_path = export_centrality(source_dir, output_dir, condition)
    communities_path = export_communities(source_dir, output_dir, condition)
    nodes_path = export_nodes(source_dir, output_dir, condition)
    edges_path = export_edges(source_dir, output_dir, condition)
    graph_path = export_graph(output_dir, condition)

    return ConditionExportResult(
        condition=condition,
        rg_timeseries_path=rg_timeseries_path,
        centrality_path=centrality_path,
        communities_path=communities_path,
        nodes_path=nodes_path,
        edges_path=edges_path,
        graph_path=graph_path,
    )


def export_rg_timeseries(
    source_dir: str | Path,
    output_dir: str | Path,
    condition: str,
    *,
    frame_time_ps: float,
) -> Path:
    """Export notebook-like Rg timeseries to the backend contract layout."""
    frame_time = _validate_frame_time_ps(frame_time_ps)
    input_path = Path(source_dir) / f"rg_timeseries_{condition}.csv"
    if not input_path.is_file():
        raise NotebookExportAdapterError(f"Missing Rg timeseries input: {input_path}")

    rows = _read_notebook_rg_rows(input_path, condition, frame_time)

    output_path = Path(output_dir) / condition / "rg_timeseries.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=RG_TIMESERIES_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    try:
        validate_csv_artifact_schema(output_path, "rg_timeseries.csv")
        validate_condition_column(output_path, condition)
    except ArtifactValidationError as exc:
        raise NotebookExportAdapterError(
            f"Output Rg timeseries failed validation: {output_path}"
        ) from exc

    return output_path


def export_centrality(
    source_dir: str | Path,
    output_dir: str | Path,
    condition: str,
) -> Path:
    """Export notebook-like centrality rows to the backend contract layout."""
    return _export_contract_csv_table(
        source_dir=source_dir,
        output_dir=output_dir,
        condition=condition,
        input_name=f"centrality_{condition}.csv",
        output_name="centrality.csv",
        output_columns=CENTRALITY_COLUMNS,
    )


def export_communities(
    source_dir: str | Path,
    output_dir: str | Path,
    condition: str,
) -> Path:
    """Export notebook-like community rows to the backend contract layout."""
    return _export_contract_csv_table(
        source_dir=source_dir,
        output_dir=output_dir,
        condition=condition,
        input_name=f"communities_{condition}.csv",
        output_name="communities.csv",
        output_columns=COMMUNITIES_COLUMNS,
    )


def export_nodes(
    source_dir: str | Path,
    output_dir: str | Path,
    condition: str,
) -> Path:
    """Export backend nodes from notebook-like residue and metric tables."""
    source_path = Path(source_dir)
    residue_path = source_path / f"residue_table_{condition}.csv"
    centrality_path = source_path / f"centrality_{condition}.csv"
    communities_path = source_path / f"communities_{condition}.csv"

    residue_rows = _read_required_rows(
        residue_path,
        condition,
        RESIDUE_TABLE_COLUMNS,
    )
    centrality_rows = _read_required_rows(
        centrality_path,
        condition,
        CENTRALITY_COLUMNS,
    )
    communities_rows = _read_required_rows(
        communities_path,
        condition,
        COMMUNITIES_COLUMNS,
    )

    centrality_by_resid = _index_rows_by_resid(centrality_rows, centrality_path)
    communities_by_resid = _index_rows_by_resid(communities_rows, communities_path)
    residue_by_resid = _index_rows_by_resid(residue_rows, residue_path)
    residue_ids = set(residue_by_resid)

    _validate_join_coverage(
        residue_ids,
        set(centrality_by_resid),
        "centrality",
        centrality_path,
    )
    _validate_join_coverage(
        residue_ids,
        set(communities_by_resid),
        "communities",
        communities_path,
    )

    rows = _build_node_rows(residue_rows, centrality_by_resid, communities_by_resid)
    output_path = Path(output_dir) / condition / "nodes.csv"
    _write_contract_rows(output_path, NODE_COLUMNS, rows)
    _validate_output_csv(output_path, "nodes.csv", condition)
    return output_path


def export_edges(
    source_dir: str | Path,
    output_dir: str | Path,
    condition: str,
) -> Path:
    """Export backend edges from notebook-like contact edge rows."""
    input_path = Path(source_dir) / f"protein_contact_edges_undirected_{condition}.csv"
    rows = _read_required_rows(input_path, condition, NOTEBOOK_EDGE_REQUIRED_COLUMNS)
    _validate_unique_undirected_edges(rows, input_path)

    output_rows = _build_edge_rows(rows)
    output_path = Path(output_dir) / condition / "edges.csv"
    _write_contract_rows(output_path, EDGE_COLUMNS, output_rows)
    _validate_output_csv(output_path, "edges.csv", condition)
    return output_path


def export_graph(output_dir: str | Path, condition: str) -> Path:
    """Export a per-condition backend graph from contract nodes and edges CSVs."""
    condition_dir = Path(output_dir) / condition
    nodes_path = condition_dir / "nodes.csv"
    edges_path = condition_dir / "edges.csv"

    _validate_contract_csv_for_graph(nodes_path, "nodes.csv", condition)
    _validate_contract_csv_for_graph(edges_path, "edges.csv", condition)

    nodes = _load_graph_nodes(nodes_path)
    edges = _load_graph_edges(edges_path, {node["id"] for node in nodes})

    graph = {
        "condition": condition,
        "n_nodes": len(nodes),
        "n_edges": len(edges),
        "directed": False,
        "schema_version": SCHEMA_VERSION,
        "nodes": nodes,
        "edges": edges,
    }
    missing_keys = [key for key in GRAPH_REQUIRED_KEYS if key not in graph]
    if missing_keys:
        raise NotebookExportAdapterError(
            f"Graph payload is missing keys: {', '.join(missing_keys)}"
        )

    graph_path = condition_dir / "graph.json"
    _write_graph_json(graph_path, graph)
    try:
        validate_graph_json(graph_path, expected_condition=condition)
    except GraphValidationError as exc:
        raise NotebookExportAdapterError(
            f"Output graph failed validation: {graph_path}"
        ) from exc
    return graph_path


def _export_contract_csv_table(
    source_dir: str | Path,
    output_dir: str | Path,
    condition: str,
    *,
    input_name: str,
    output_name: str,
    output_columns: Sequence[str],
) -> Path:
    input_path = Path(source_dir) / input_name
    if not input_path.is_file():
        raise NotebookExportAdapterError(f"Missing notebook export input: {input_path}")

    rows = _read_contract_like_rows(input_path, condition, output_columns)

    output_path = Path(output_dir) / condition / output_name
    _write_contract_rows(output_path, output_columns, rows)
    _validate_output_csv(output_path, output_name, condition)
    return output_path


def _read_run_meta_conditions(run_meta_path: Path) -> tuple[str, ...]:
    try:
        with run_meta_path.open(encoding="utf-8") as run_meta_file:
            payload = json.load(run_meta_file)
    except (OSError, json.JSONDecodeError) as exc:
        raise NotebookExportAdapterError(
            f"Failed to read exported run metadata: {run_meta_path}"
        ) from exc

    if not isinstance(payload, dict):
        raise NotebookExportAdapterError(
            f"Exported run metadata must be a JSON object: {run_meta_path}"
        )
    conditions = payload.get("conditions")
    if not isinstance(conditions, list) or not all(
        isinstance(condition, str) for condition in conditions
    ):
        raise NotebookExportAdapterError(
            f"Exported run metadata contains invalid conditions: {run_meta_path}"
        )
    return tuple(conditions)


def _normalize_conditions(conditions: Iterable[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_condition in conditions:
        if not isinstance(raw_condition, str):
            raise NotebookExportAdapterError(
                f"Condition names must be strings: {raw_condition!r}"
            )
        condition = raw_condition.strip()
        if condition == "":
            raise NotebookExportAdapterError("Condition name must not be empty")
        if condition in seen:
            raise NotebookExportAdapterError(
                f"Duplicate condition name after normalization: {condition!r}"
            )
        seen.add(condition)
        normalized.append(condition)
    return tuple(normalized)


def _read_contract_like_rows(
    input_path: Path,
    condition: str,
    output_columns: Sequence[str],
) -> list[dict[str, str]]:
    with input_path.open(encoding="utf-8", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        _validate_required_header(reader.fieldnames, output_columns, input_path)

        rows: list[dict[str, str]] = []
        for row_number, row in enumerate(reader, start=2):
            if _is_empty_data_row(row):
                continue

            row_condition = _validate_row_condition(
                row,
                condition,
                input_path,
                row_number,
            )
            rows.append(
                {
                    column: row[column] if row[column] is not None else ""
                    for column in output_columns
                }
            )
            rows[-1]["condition"] = row_condition

    if not rows:
        raise NotebookExportAdapterError(f"No data rows found: {input_path}")
    return rows


def _read_contract_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        return [
            {
                column: value if value is not None else ""
                for column, value in row.items()
            }
            for row in reader
            if not _is_empty_data_row(row)
        ]


def _validate_contract_csv_for_graph(
    path: Path,
    artifact_name: str,
    condition: str,
) -> None:
    if not path.is_file():
        raise NotebookExportAdapterError(f"Missing graph input CSV: {path}")
    try:
        validate_csv_artifact_schema(path, artifact_name)
        validate_condition_column(path, condition)
    except ArtifactValidationError as exc:
        raise NotebookExportAdapterError(f"Invalid graph input CSV: {path}") from exc


def _load_graph_nodes(nodes_path: Path) -> list[dict[str, str]]:
    nodes: list[dict[str, str]] = []
    node_ids: set[str] = set()
    for row in _read_contract_csv_rows(nodes_path):
        resid = row.get("resid", "")
        if resid.strip() == "":
            raise NotebookExportAdapterError(f"Missing node resid in {nodes_path}")
        if resid in node_ids:
            raise NotebookExportAdapterError(
                f"Duplicate graph node id {resid!r} in {nodes_path}"
            )
        node_ids.add(resid)
        nodes.append({"id": resid, **row})

    if not nodes:
        raise NotebookExportAdapterError(f"No graph nodes found: {nodes_path}")
    return nodes


def _load_graph_edges(
    edges_path: Path,
    node_ids: set[str],
) -> list[dict[str, str]]:
    edges: list[dict[str, str]] = []
    for row in _read_contract_csv_rows(edges_path):
        resid_i = row.get("resid_i", "")
        resid_j = row.get("resid_j", "")
        if resid_i.strip() == "":
            raise NotebookExportAdapterError(f"Missing edge resid_i in {edges_path}")
        if resid_j.strip() == "":
            raise NotebookExportAdapterError(f"Missing edge resid_j in {edges_path}")
        if resid_i not in node_ids:
            raise NotebookExportAdapterError(
                f"Edge source {resid_i!r} is missing from nodes: {edges_path}"
            )
        if resid_j not in node_ids:
            raise NotebookExportAdapterError(
                f"Edge target {resid_j!r} is missing from nodes: {edges_path}"
            )
        edges.append({"source": resid_i, "target": resid_j, **row})
    return edges


def _write_graph_json(path: Path, graph: dict[str, object]) -> None:
    path.write_text(
        json.dumps(graph, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _read_required_rows(
    input_path: Path,
    condition: str,
    required_columns: Sequence[str],
) -> list[dict[str, str]]:
    if not input_path.is_file():
        raise NotebookExportAdapterError(f"Missing notebook export input: {input_path}")

    with input_path.open(encoding="utf-8", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        _validate_required_header(reader.fieldnames, required_columns, input_path)

        rows: list[dict[str, str]] = []
        for row_number, row in enumerate(reader, start=2):
            if _is_empty_data_row(row):
                continue

            _validate_row_condition(row, condition, input_path, row_number)
            _validate_required_values(row, required_columns, input_path, row_number)
            rows.append(
                {
                    column: value if value is not None else ""
                    for column, value in row.items()
                }
            )

    if not rows:
        raise NotebookExportAdapterError(f"No data rows found: {input_path}")
    return rows


def _validate_required_values(
    row: dict[str, str | None],
    required_columns: Sequence[str],
    input_path: Path,
    row_number: int,
) -> None:
    for column in required_columns:
        value = row.get(column)
        if value is None or value.strip() == "":
            raise NotebookExportAdapterError(
                f"Missing required value {column!r} at row {row_number}: {input_path}"
            )


def _index_rows_by_resid(
    rows: Sequence[dict[str, str]],
    input_path: Path,
) -> dict[str, dict[str, str]]:
    indexed: dict[str, dict[str, str]] = {}
    for row in rows:
        resid = row["resid"]
        if resid in indexed:
            raise NotebookExportAdapterError(
                f"Duplicate resid {resid!r} in {input_path}"
            )
        indexed[resid] = row
    return indexed


def _validate_join_coverage(
    residue_ids: set[str],
    joined_ids: set[str],
    table_name: str,
    input_path: Path,
) -> None:
    missing_ids = sorted(residue_ids - joined_ids)
    if missing_ids:
        raise NotebookExportAdapterError(
            f"Missing {table_name} rows for resid values in {input_path}: "
            f"{', '.join(missing_ids)}"
        )

    extra_ids = sorted(joined_ids - residue_ids)
    if extra_ids:
        raise NotebookExportAdapterError(
            f"Unmatched {table_name} rows in {input_path}: {', '.join(extra_ids)}"
        )


def _build_node_rows(
    residue_rows: Sequence[dict[str, str]],
    centrality_by_resid: dict[str, dict[str, str]],
    communities_by_resid: dict[str, dict[str, str]],
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for residue_row in residue_rows:
        resid = residue_row["resid"]
        centrality_row = centrality_by_resid[resid]
        community_row = communities_by_resid[resid]
        rows.append(
            {
                "resid": residue_row["resid"],
                "resname": residue_row["resname"],
                "region": residue_row["region"],
                "condition": residue_row["condition"],
                "x_ca": residue_row["x_ca"],
                "y_ca": residue_row["y_ca"],
                "z_ca": residue_row["z_ca"],
                "tm_relative_z": residue_row["tm_relative_z"],
                "rmsf_A": residue_row["rmsf_A"],
                "sasa_A2": residue_row["sasa_A2"],
                "ss": residue_row["ss"],
                "degree": centrality_row["degree"],
                "strength": centrality_row["strength"],
                "betweenness": centrality_row["betweenness"],
                "closeness": centrality_row["closeness"],
                "eigenvector": centrality_row["eigenvector"],
                "pagerank": centrality_row["pagerank"],
                "kcore": centrality_row["kcore"],
                "community_id": community_row["community_id"],
            }
        )
    return rows


def _build_edge_rows(rows: Sequence[dict[str, str]]) -> list[dict[str, str]]:
    return [_build_edge_row(row) for row in rows]


def _build_edge_row(row: dict[str, str]) -> dict[str, str]:
    all_edge_types = _edge_types_from_row(row)
    output_row = {
        column: row.get(column, "") if row.get(column) is not None else ""
        for column in EDGE_COLUMNS
    }
    output_row["edge_type"] = all_edge_types[0]
    output_row["all_edge_types"] = EDGE_TYPE_SEPARATOR.join(all_edge_types)
    output_row["n_edge_types"] = str(len(all_edge_types))
    return output_row


def _edge_types_from_row(row: dict[str, str]) -> tuple[str, ...]:
    raw_all_edge_types = row.get("all_edge_types", "").strip()
    if raw_all_edge_types == "":
        return (row["edge_type"],)
    edge_types = tuple(
        edge_type.strip()
        for edge_type in raw_all_edge_types.split(EDGE_TYPE_SEPARATOR)
        if edge_type.strip() != ""
    )
    if not edge_types:
        return (row["edge_type"],)
    return tuple(sorted(set(edge_types), key=_edge_type_priority_key))


def _edge_type_priority_key(edge_type: str) -> tuple[int, str]:
    return (
        EDGE_TYPE_PRIORITY_INDEX.get(edge_type, len(EDGE_TYPE_PRIORITY)),
        edge_type,
    )


def _validate_unique_undirected_edges(
    rows: Sequence[dict[str, str]],
    input_path: Path,
) -> None:
    seen: set[tuple[str, str, str, str]] = set()
    for row in rows:
        key = _edge_key(row)
        if key in seen:
            raise NotebookExportAdapterError(
                f"Duplicate undirected edge in {input_path}: {key!r}"
            )
        seen.add(key)


def _edge_key(row: dict[str, str]) -> tuple[str, str, str, str]:
    resid_a, resid_b = sorted((row["resid_i"], row["resid_j"]))
    return resid_a, resid_b, row["edge_type"], row["condition"]


def _read_notebook_rg_rows(
    input_path: Path,
    condition: str,
    frame_time_ps: float,
) -> list[dict[str, str]]:
    with input_path.open(encoding="utf-8", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        _validate_notebook_rg_header(reader.fieldnames, input_path)

        rows: list[dict[str, str]] = []
        for row_number, row in enumerate(reader, start=2):
            if _is_empty_data_row(row):
                continue

            row_condition = _validate_row_condition(
                row,
                condition,
                input_path,
                row_number,
            )

            frame = row.get("frame")
            frame_value = _parse_frame(frame, input_path, row_number)

            rg_value = row.get("rg_A")
            _validate_rg_value(rg_value, input_path, row_number)

            rows.append(
                {
                    "frame": frame if frame is not None else "",
                    "time_ps": _format_time_ps(frame_value * frame_time_ps),
                    "rg_A": rg_value if rg_value is not None else "",
                    "condition": row_condition,
                }
            )

    return rows


def _validate_frame_time_ps(frame_time_ps: object) -> float:
    if isinstance(frame_time_ps, bool) or not isinstance(frame_time_ps, int | float):
        raise NotebookExportAdapterError(
            f"frame_time_ps must be a positive finite number: {frame_time_ps!r}"
        )
    frame_time = float(frame_time_ps)
    if not math.isfinite(frame_time) or frame_time <= 0:
        raise NotebookExportAdapterError(
            f"frame_time_ps must be a positive finite number: {frame_time_ps!r}"
        )
    return frame_time


def _validate_notebook_rg_header(
    fieldnames: Sequence[str] | None,
    input_path: Path,
) -> None:
    _validate_required_header(fieldnames, NOTEBOOK_RG_COLUMNS, input_path)


def _validate_required_header(
    fieldnames: Sequence[str] | None,
    required_columns: Sequence[str],
    input_path: Path,
) -> None:
    if fieldnames is None:
        raise NotebookExportAdapterError(f"CSV file is empty: {input_path}")

    missing_columns = [
        column for column in required_columns if column not in fieldnames
    ]
    if missing_columns:
        missing_text = ", ".join(missing_columns)
        raise NotebookExportAdapterError(
            f"Missing notebook export columns in {input_path}: {missing_text}"
        )


def _validate_row_condition(
    row: dict[str, str | None],
    condition: str,
    input_path: Path,
    row_number: int,
) -> str:
    row_condition = row.get("condition")
    if row_condition is None or row_condition.strip() == "":
        raise NotebookExportAdapterError(
            f"Missing condition value at row {row_number}: {input_path}"
        )
    if row_condition != condition:
        raise NotebookExportAdapterError(
            "Mismatched condition value at "
            f"row {row_number}: expected {condition!r}, got {row_condition!r}"
        )
    return row_condition


def _write_contract_rows(
    output_path: Path,
    output_columns: Sequence[str],
    rows: Sequence[dict[str, str]],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=output_columns)
        writer.writeheader()
        writer.writerows(rows)


def _validate_output_csv(
    output_path: Path,
    artifact_name: str,
    condition: str,
) -> None:
    try:
        validate_csv_artifact_schema(output_path, artifact_name)
        validate_condition_column(output_path, condition)
    except ArtifactValidationError as exc:
        raise NotebookExportAdapterError(
            f"Output artifact failed validation: {output_path}"
        ) from exc


def _parse_frame(frame: str | None, input_path: Path, row_number: int) -> int:
    if frame is None or frame.strip() == "":
        raise NotebookExportAdapterError(
            f"Missing frame value at row {row_number}: {input_path}"
        )
    try:
        return int(frame)
    except ValueError as exc:
        raise NotebookExportAdapterError(
            f"Invalid frame value at row {row_number}: {frame!r}"
        ) from exc


def _validate_rg_value(
    rg_value: str | None,
    input_path: Path,
    row_number: int,
) -> None:
    if rg_value is None or rg_value.strip() == "":
        raise NotebookExportAdapterError(
            f"Missing rg_A value at row {row_number}: {input_path}"
        )
    try:
        parsed = float(rg_value)
    except ValueError as exc:
        raise NotebookExportAdapterError(
            f"Invalid rg_A value at row {row_number}: {rg_value!r}"
        ) from exc
    if not math.isfinite(parsed):
        raise NotebookExportAdapterError(
            f"Non-finite rg_A value at row {row_number}: {rg_value!r}"
        )


def _format_time_ps(time_ps: float) -> str:
    if time_ps.is_integer():
        return str(int(time_ps))
    return format(time_ps, "g")


def _is_empty_data_row(row: dict[str, str | None]) -> bool:
    return all(value is None or value.strip() == "" for value in row.values())


__all__ = [
    "ConditionExportResult",
    "MultiConditionExportResult",
    "NotebookContractSubsetExportResult",
    "NotebookExportAdapterError",
    "export_centrality",
    "export_condition",
    "export_conditions",
    "export_communities",
    "export_edges",
    "export_graph",
    "export_nodes",
    "export_notebook_contract_subset",
    "export_rg_timeseries",
    "export_run_meta",
]
