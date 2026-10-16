"""In-memory graph export mapping for preprocessing contacts results."""

from __future__ import annotations

import csv
import math
import tempfile
from dataclasses import dataclass, replace
from io import StringIO
from json import JSONDecodeError
from json import dumps as _json_dumps
from json import loads as _json_loads
from os import PathLike
from pathlib import Path

from mania.constants import (
    EDGE_COLUMNS,
    EDGE_TYPE_PRIORITY,
    GRAPH_REQUIRED_KEYS,
    NODE_COLUMNS,
    SCHEMA_VERSION,
)
from mania.preprocessing.trajectory_contacts import (
    BACKBONE_MAX_CA_DIST_A as BACKBONE_MAX_CA_DIST_A,
)
from mania.preprocessing.trajectory_contacts import (
    PreprocessingCaCoordinate,
    PreprocessingConditionContactsResult,
    PreprocessingContactFrameResult,
    PreprocessingContactPairResult,
    PreprocessingManifestContactsResult,
)

_NODE_KIND = "residue"
_EDGE_KIND = "residue_contact"
_BACKBONE_EDGE_KIND = "backbone"
_SOURCE = "preprocessing_contacts"
_ID_SEPARATOR = "|"
_ID_ESCAPE = "\\"
_EDGE_TYPE_SEPARATOR = "|"
_EDGE_TYPE_PRIORITY_INDEX = {
    edge_type: index for index, edge_type in enumerate(EDGE_TYPE_PRIORITY)
}
_EDGE_TYPE_ALIASES = {
    "saltbridge": "salt_bridge",
    "cationpi": "cation_pi",
    "aromaticpi": "aromatic_pi",
}
_PATHLIKE_TYPES = (str, Path, PathLike)
_EDGES_CSV_PUBLIC_WRITER_NAME = "write_preprocessing_graph_" + "edges_csv"
_GRAPH_CSV_PATH_TYPES = (str, Path)
_GRAPH_NODE_REQUIRED_COLUMNS = ("resid", "resname", "condition")
_GRAPH_EDGE_REQUIRED_COLUMNS = (
    "resid_i",
    "resid_j",
    "edge_type",
    "all_edge_types",
    "n_edge_types",
    "condition",
)
_GRAPH_NODE_FLOAT_COLUMNS = (
    "x_ca",
    "y_ca",
    "z_ca",
    "tm_relative_z",
    "rmsf_A",
    "sasa_A2",
    "degree",
    "strength",
    "betweenness",
    "closeness",
    "eigenvector",
    "pagerank",
)
_GRAPH_NODE_INTEGER_COLUMNS = ("kcore", "community_id")
_GRAPH_EDGE_FLOAT_COLUMNS = (
    "contact_freq",
    "mean_dist_A",
    "std_dist_A",
    "mean_lifetime_frames",
    "max_lifetime_frames",
    "mean_lifetime_ns",
    "max_lifetime_ns",
    "window_cv",
)
_GRAPH_EDGE_INTEGER_COLUMNS = (
    "n_edge_types",
    "n_episodes",
    "formation_count",
    "breakage_count",
    "first_seen_frame",
    "last_seen_frame",
)
_GRAPH_JSON_EDGE_REQUIRED_FIELDS = (
    "condition",
    "edge_type",
    "all_edge_types",
    "n_edge_types",
)


@dataclass(frozen=True)
class PreprocessingGraphNodeMappingRecord:
    """One graph-ready preprocessing residue node mapping record."""

    node_id: str
    condition_name: str
    residue_index: int
    residue_id: str
    resname: str
    segid: str | None = None
    x_ca: float | None = None
    y_ca: float | None = None
    z_ca: float | None = None
    node_kind: str = _NODE_KIND
    source: str = _SOURCE

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "node_id",
            _non_empty_string(self.node_id, "node_id"),
        )
        object.__setattr__(
            self,
            "condition_name",
            _non_empty_string(self.condition_name, "condition_name"),
        )
        _require_non_negative_int(self.residue_index, "residue_index")
        object.__setattr__(
            self,
            "residue_id",
            _non_empty_string(self.residue_id, "residue_id"),
        )
        object.__setattr__(
            self,
            "resname",
            _non_empty_string(self.resname, "resname"),
        )
        _require_optional_string(self.segid, "segid")
        coordinate_values = (self.x_ca, self.y_ca, self.z_ca)
        if any(value is None for value in coordinate_values) and any(
            value is not None for value in coordinate_values
        ):
            raise ValueError("Cα coordinates must be all present or all None")
        for field_name in ("x_ca", "y_ca", "z_ca"):
            value = getattr(self, field_name)
            _require_optional_finite_number(value, field_name)
            if value is not None:
                object.__setattr__(self, field_name, float(value))
        object.__setattr__(
            self,
            "node_kind",
            _non_empty_string(self.node_kind, "node_kind"),
        )
        object.__setattr__(
            self,
            "source",
            _non_empty_string(self.source, "source"),
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe mapping dictionary."""
        return {
            "node_id": self.node_id,
            "condition_name": self.condition_name,
            "residue_index": self.residue_index,
            "residue_id": self.residue_id,
            "resname": self.resname,
            "segid": self.segid,
            "x_ca": self.x_ca,
            "y_ca": self.y_ca,
            "z_ca": self.z_ca,
            "node_kind": self.node_kind,
            "source": self.source,
        }


@dataclass(frozen=True)
class PreprocessingGraphEdgeMappingRecord:
    """One graph-ready preprocessing aggregate contact edge mapping record."""

    edge_id: str
    source_node_id: str
    target_node_id: str
    condition_name: str
    edge_kind: str = _EDGE_KIND
    all_edge_types: tuple[str, ...] | None = None
    source: str = _SOURCE
    contact_frame_count: int | None = None
    total_frame_count: int | None = None
    contact_frequency: float | None = None
    minimum_distance: float | None = None
    mean_minimum_distance: float | None = None
    distance_unit: str | None = None
    atom_filter: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "edge_id",
            _non_empty_string(self.edge_id, "edge_id"),
        )
        object.__setattr__(
            self,
            "source_node_id",
            _non_empty_string(self.source_node_id, "source_node_id"),
        )
        object.__setattr__(
            self,
            "target_node_id",
            _non_empty_string(self.target_node_id, "target_node_id"),
        )
        if self.source_node_id == self.target_node_id:
            raise ValueError("source_node_id and target_node_id must differ")
        object.__setattr__(
            self,
            "condition_name",
            _non_empty_string(self.condition_name, "condition_name"),
        )
        edge_kind = _edge_type_string(self.edge_kind, "edge_kind")
        all_edge_types = _normalized_record_edge_types(
            self.all_edge_types,
            edge_kind=edge_kind,
        )
        if edge_kind not in all_edge_types and edge_kind != _EDGE_KIND:
            raise ValueError("edge_kind must be included in all_edge_types")
        object.__setattr__(self, "edge_kind", all_edge_types[0])
        object.__setattr__(self, "all_edge_types", all_edge_types)
        object.__setattr__(
            self,
            "source",
            _non_empty_string(self.source, "source"),
        )
        _require_optional_non_negative_int(
            self.contact_frame_count,
            "contact_frame_count",
        )
        _require_optional_non_negative_int(
            self.total_frame_count,
            "total_frame_count",
        )
        if (
            self.contact_frame_count is not None
            and self.total_frame_count is not None
            and self.contact_frame_count > self.total_frame_count
        ):
            raise ValueError(
                "contact_frame_count must not exceed total_frame_count"
            )
        _require_optional_non_negative_finite_number(
            self.contact_frequency,
            "contact_frequency",
        )
        _require_optional_non_negative_finite_number(
            self.minimum_distance,
            "minimum_distance",
        )
        _require_optional_non_negative_finite_number(
            self.mean_minimum_distance,
            "mean_minimum_distance",
        )
        _require_optional_string(self.distance_unit, "distance_unit")
        _require_optional_string(self.atom_filter, "atom_filter")

    @property
    def primary_edge_type(self) -> str:
        """Return the priority-selected primary edge type."""
        return self.edge_kind

    @property
    def n_edge_types(self) -> int:
        """Return the number of unique edge types represented by this edge."""
        all_edge_types = self.all_edge_types
        if all_edge_types is None:
            return 0
        return len(all_edge_types)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe mapping dictionary."""
        return {
            "edge_id": self.edge_id,
            "source_node_id": self.source_node_id,
            "target_node_id": self.target_node_id,
            "condition_name": self.condition_name,
            "edge_kind": self.edge_kind,
            "primary_edge_type": self.primary_edge_type,
            "all_edge_types": self.all_edge_types,
            "n_edge_types": self.n_edge_types,
            "source": self.source,
            "contact_frame_count": self.contact_frame_count,
            "total_frame_count": self.total_frame_count,
            "contact_frequency": self.contact_frequency,
            "minimum_distance": self.minimum_distance,
            "mean_minimum_distance": self.mean_minimum_distance,
            "distance_unit": self.distance_unit,
            "atom_filter": self.atom_filter,
        }


@dataclass(frozen=True)
class PreprocessingGraphExportMappingIssue:
    """One deterministic graph export mapping issue."""

    kind: str
    message: str
    record_id: str | None = None
    field: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "kind",
            _non_empty_string(self.kind, "kind"),
        )
        object.__setattr__(
            self,
            "message",
            _non_empty_string(self.message, "message"),
        )
        object.__setattr__(
            self,
            "record_id",
            _optional_non_empty_string(self.record_id, "record_id"),
        )
        object.__setattr__(
            self,
            "field",
            _optional_non_empty_string(self.field, "field"),
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe issue dictionary."""
        return {
            "kind": self.kind,
            "message": self.message,
            "record_id": self.record_id,
            "field": self.field,
        }


@dataclass(frozen=True)
class PreprocessingGraphExportMappingResult:
    """In-memory graph export mapping result for preprocessing contacts."""

    nodes: tuple[PreprocessingGraphNodeMappingRecord, ...]
    edges: tuple[PreprocessingGraphEdgeMappingRecord, ...]
    issues: tuple[PreprocessingGraphExportMappingIssue, ...] = ()

    def __post_init__(self) -> None:
        nodes = tuple(self.nodes)
        edges = tuple(self.edges)
        issues = tuple(self.issues)

        for node in nodes:
            if not isinstance(node, PreprocessingGraphNodeMappingRecord):
                raise ValueError(
                    "nodes must contain PreprocessingGraphNodeMappingRecord"
                )
        for edge in edges:
            if not isinstance(edge, PreprocessingGraphEdgeMappingRecord):
                raise ValueError(
                    "edges must contain PreprocessingGraphEdgeMappingRecord"
                )
        for issue in issues:
            if not isinstance(issue, PreprocessingGraphExportMappingIssue):
                raise ValueError(
                    "issues must contain PreprocessingGraphExportMappingIssue"
                )

        duplicate_node_ids = _duplicates(tuple(node.node_id for node in nodes))
        if duplicate_node_ids:
            raise ValueError(
                "Duplicate node IDs: " + ", ".join(duplicate_node_ids)
            )
        duplicate_edge_ids = _duplicates(tuple(edge.edge_id for edge in edges))
        if duplicate_edge_ids:
            raise ValueError(
                "Duplicate edge IDs: " + ", ".join(duplicate_edge_ids)
            )

        node_ids = {node.node_id for node in nodes}
        for edge in edges:
            if edge.source_node_id not in node_ids:
                raise ValueError(
                    "Edge endpoint is missing from nodes: "
                    f"{edge.source_node_id}"
                )
            if edge.target_node_id not in node_ids:
                raise ValueError(
                    "Edge endpoint is missing from nodes: "
                    f"{edge.target_node_id}"
                )

        object.__setattr__(
            self,
            "nodes",
            tuple(sorted(nodes, key=lambda node: node.node_id)),
        )
        object.__setattr__(
            self,
            "edges",
            tuple(sorted(edges, key=lambda edge: edge.edge_id)),
        )
        object.__setattr__(
            self,
            "issues",
            tuple(
                sorted(
                    issues,
                    key=lambda issue: (
                        issue.kind,
                        issue.record_id or "",
                        issue.field or "",
                        issue.message,
                    ),
                )
            ),
        )

    @property
    def passed(self) -> bool:
        """Return whether the mapping has no issues."""
        return self.issues == ()

    @property
    def node_count(self) -> int:
        """Return the number of mapped nodes."""
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        """Return the number of mapped edges."""
        return len(self.edges)

    @property
    def backbone_edge_counts(self) -> dict[str, int]:
        """Return deterministic backbone edge counts keyed by condition."""
        counts: dict[str, int] = {}
        for edge in self.edges:
            if edge.all_edge_types is not None and (
                _BACKBONE_EDGE_KIND in edge.all_edge_types
            ):
                counts[edge.condition_name] = (
                    counts.get(edge.condition_name, 0) + 1
                )
        return dict(sorted(counts.items()))

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe mapping result dictionary."""
        return {
            "passed": self.passed,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "backbone_edge_counts": self.backbone_edge_counts,
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class PreprocessingGraphNodesCsvWriteIssue:
    """One deterministic graph nodes CSV write issue."""

    kind: str
    message: str
    node_id: str | None = None
    field: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "kind",
            _non_empty_string(self.kind, "kind"),
        )
        object.__setattr__(
            self,
            "message",
            _non_empty_string(self.message, "message"),
        )
        object.__setattr__(
            self,
            "node_id",
            _optional_non_empty_string(self.node_id, "node_id"),
        )
        object.__setattr__(
            self,
            "field",
            _optional_non_empty_string(self.field, "field"),
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe write issue dictionary."""
        return {
            "kind": self.kind,
            "message": self.message,
            "node_id": self.node_id,
            "field": self.field,
        }


@dataclass(frozen=True)
class PreprocessingGraphNodesCsvWriteResult:
    """Summary of one backend graph nodes CSV write attempt."""

    output_path: Path
    rows_written: int
    issues: tuple[PreprocessingGraphNodesCsvWriteIssue, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "output_path", Path(self.output_path))
        _require_non_negative_int(self.rows_written, "rows_written")
        if not isinstance(self.issues, tuple):
            raise ValueError(
                "issues must be a tuple of "
                "PreprocessingGraphNodesCsvWriteIssue"
            )
        for issue in self.issues:
            if not isinstance(issue, PreprocessingGraphNodesCsvWriteIssue):
                raise ValueError(
                    "issues must contain PreprocessingGraphNodesCsvWriteIssue"
                )

    @property
    def passed(self) -> bool:
        """Return whether the write attempt had no issues."""
        return self.issues == ()

    @property
    def issue_count(self) -> int:
        """Return the number of write issues."""
        return len(self.issues)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe write result dictionary."""
        return {
            "output_path": str(self.output_path),
            "passed": self.passed,
            "rows_written": self.rows_written,
            "issue_count": self.issue_count,
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class PreprocessingGraphEdgesCsvWriteIssue:
    """One deterministic graph edges CSV write issue."""

    kind: str
    message: str
    edge_id: str | None = None
    field: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "kind",
            _non_empty_string(self.kind, "kind"),
        )
        object.__setattr__(
            self,
            "message",
            _non_empty_string(self.message, "message"),
        )
        object.__setattr__(
            self,
            "edge_id",
            _optional_non_empty_string(self.edge_id, "edge_id"),
        )
        object.__setattr__(
            self,
            "field",
            _optional_non_empty_string(self.field, "field"),
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe write issue dictionary."""
        return {
            "kind": self.kind,
            "message": self.message,
            "edge_id": self.edge_id,
            "field": self.field,
        }


@dataclass(frozen=True)
class PreprocessingGraphEdgesCsvWriteResult:
    """Summary of one backend graph edges CSV write attempt."""

    output_path: Path
    rows_written: int
    issues: tuple[PreprocessingGraphEdgesCsvWriteIssue, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "output_path", Path(self.output_path))
        _require_non_negative_int(self.rows_written, "rows_written")
        if not isinstance(self.issues, tuple):
            raise ValueError(
                "issues must be a tuple of "
                "PreprocessingGraphEdgesCsvWriteIssue"
            )
        for issue in self.issues:
            if not isinstance(issue, PreprocessingGraphEdgesCsvWriteIssue):
                raise ValueError(
                    "issues must contain PreprocessingGraphEdgesCsvWriteIssue"
                )

    @property
    def passed(self) -> bool:
        """Return whether the write attempt had no issues."""
        return self.issues == ()

    @property
    def issue_count(self) -> int:
        """Return the number of write issues."""
        return len(self.issues)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe write result dictionary."""
        return {
            "output_path": str(self.output_path),
            "passed": self.passed,
            "rows_written": self.rows_written,
            "issue_count": self.issue_count,
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class PreprocessingGraphCsvValidationIssue:
    """One deterministic backend graph CSV validation issue."""

    kind: str
    message: str
    csv_kind: str | None = None
    row_number: int | None = None
    column: str | None = None
    value: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "kind",
            _non_empty_string(self.kind, "kind"),
        )
        object.__setattr__(
            self,
            "message",
            _non_empty_string(self.message, "message"),
        )
        object.__setattr__(
            self,
            "csv_kind",
            _optional_non_empty_string(self.csv_kind, "csv_kind"),
        )
        if self.row_number is not None and (
            isinstance(self.row_number, bool)
            or not isinstance(self.row_number, int)
            or self.row_number <= 0
        ):
            raise ValueError("row_number must be a positive int or None")
        object.__setattr__(
            self,
            "column",
            _optional_non_empty_string(self.column, "column"),
        )
        if self.value is not None and not isinstance(self.value, str):
            raise ValueError("value must be a string or None")

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe validation issue dictionary."""
        return {
            "kind": self.kind,
            "message": self.message,
            "csv_kind": self.csv_kind,
            "row_number": self.row_number,
            "column": self.column,
            "value": self.value,
        }


@dataclass(frozen=True)
class PreprocessingGraphCsvValidationResult:
    """Summary of one backend graph CSV validation attempt."""

    nodes_csv_path: Path
    edges_csv_path: Path
    node_count: int
    edge_count: int
    issues: tuple[PreprocessingGraphCsvValidationIssue, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "nodes_csv_path", Path(self.nodes_csv_path))
        object.__setattr__(self, "edges_csv_path", Path(self.edges_csv_path))
        _require_non_negative_int(self.node_count, "node_count")
        _require_non_negative_int(self.edge_count, "edge_count")
        if not isinstance(self.issues, tuple):
            raise ValueError(
                "issues must be a tuple of "
                "PreprocessingGraphCsvValidationIssue"
            )
        for issue in self.issues:
            if not isinstance(issue, PreprocessingGraphCsvValidationIssue):
                raise ValueError(
                    "issues must contain PreprocessingGraphCsvValidationIssue"
                )

    @property
    def passed(self) -> bool:
        """Return whether the CSV files passed validation."""
        return self.issues == ()

    @property
    def issue_count(self) -> int:
        """Return the number of validation issues."""
        return len(self.issues)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe validation result dictionary."""
        return {
            "nodes_csv_path": str(self.nodes_csv_path),
            "edges_csv_path": str(self.edges_csv_path),
            "passed": self.passed,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "issue_count": self.issue_count,
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class PreprocessingGraphJsonWriteIssue:
    """One deterministic backend graph JSON write issue."""

    kind: str
    message: str
    field: str | None = None
    csv_kind: str | None = None
    row_number: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "kind",
            _non_empty_string(self.kind, "kind"),
        )
        object.__setattr__(
            self,
            "message",
            _non_empty_string(self.message, "message"),
        )
        object.__setattr__(
            self,
            "field",
            _optional_non_empty_string(self.field, "field"),
        )
        object.__setattr__(
            self,
            "csv_kind",
            _optional_non_empty_string(self.csv_kind, "csv_kind"),
        )
        if self.row_number is not None and (
            isinstance(self.row_number, bool)
            or not isinstance(self.row_number, int)
            or self.row_number <= 0
        ):
            raise ValueError("row_number must be a positive int or None")

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe write issue dictionary."""
        return {
            "kind": self.kind,
            "message": self.message,
            "field": self.field,
            "csv_kind": self.csv_kind,
            "row_number": self.row_number,
        }


@dataclass(frozen=True)
class PreprocessingGraphJsonWriteResult:
    """Summary of one backend graph JSON write attempt."""

    output_path: Path
    nodes_csv_path: Path
    edges_csv_path: Path
    node_count: int
    edge_count: int
    issues: tuple[PreprocessingGraphJsonWriteIssue, ...] = ()
    validation_passed: bool | None = None
    validation_issue_count: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "output_path", Path(self.output_path))
        object.__setattr__(self, "nodes_csv_path", Path(self.nodes_csv_path))
        object.__setattr__(self, "edges_csv_path", Path(self.edges_csv_path))
        _require_non_negative_int(self.node_count, "node_count")
        _require_non_negative_int(self.edge_count, "edge_count")
        if not isinstance(self.issues, tuple):
            raise ValueError(
                "issues must be a tuple of "
                "PreprocessingGraphJsonWriteIssue"
            )
        for issue in self.issues:
            if not isinstance(issue, PreprocessingGraphJsonWriteIssue):
                raise ValueError(
                    "issues must contain PreprocessingGraphJsonWriteIssue"
                )
        if self.validation_passed is not None and not isinstance(
            self.validation_passed,
            bool,
        ):
            raise ValueError("validation_passed must be bool or None")
        if self.validation_issue_count is not None:
            _require_non_negative_int(
                self.validation_issue_count,
                "validation_issue_count",
            )

    @property
    def passed(self) -> bool:
        """Return whether the write attempt had no issues."""
        return self.issues == ()

    @property
    def issue_count(self) -> int:
        """Return the number of write issues."""
        return len(self.issues)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe write result dictionary."""
        return {
            "output_path": str(self.output_path),
            "nodes_csv_path": str(self.nodes_csv_path),
            "edges_csv_path": str(self.edges_csv_path),
            "passed": self.passed,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "issue_count": self.issue_count,
            "validation_passed": self.validation_passed,
            "validation_issue_count": self.validation_issue_count,
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class PreprocessingGraphExportBundleArtifact:
    """Metadata for one existing preprocessing graph bundle artifact."""

    kind: str
    path: Path
    exists: bool
    size_bytes: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "kind",
            _non_empty_string(self.kind, "kind"),
        )
        if not isinstance(self.path, Path):
            raise ValueError("path must be a Path")
        if not isinstance(self.exists, bool):
            raise ValueError("exists must be bool")
        if self.size_bytes is not None:
            _require_non_negative_int(self.size_bytes, "size_bytes")

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe artifact metadata dictionary."""
        return {
            "kind": self.kind,
            "path": str(self.path),
            "exists": self.exists,
            "size_bytes": self.size_bytes,
        }


@dataclass(frozen=True)
class PreprocessingGraphExportBundleIssue:
    """One deterministic preprocessing graph export bundle issue."""

    kind: str
    message: str
    artifact_kind: str | None = None
    field: str | None = None
    value: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "kind",
            _non_empty_string(self.kind, "kind"),
        )
        object.__setattr__(
            self,
            "message",
            _non_empty_string(self.message, "message"),
        )
        object.__setattr__(
            self,
            "artifact_kind",
            _optional_non_empty_string(self.artifact_kind, "artifact_kind"),
        )
        object.__setattr__(
            self,
            "field",
            _optional_non_empty_string(self.field, "field"),
        )
        if self.value is not None and not isinstance(self.value, str):
            raise ValueError("value must be a string or None")

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe issue dictionary."""
        return {
            "kind": self.kind,
            "message": self.message,
            "artifact_kind": self.artifact_kind,
            "field": self.field,
            "value": self.value,
        }


@dataclass(frozen=True)
class PreprocessingGraphExportBundleResult:
    """Read-only metadata boundary for existing preprocessing graph artifacts."""

    nodes_csv_path: Path
    edges_csv_path: Path
    graph_json_path: Path
    artifacts: tuple[PreprocessingGraphExportBundleArtifact, ...]
    node_count: int
    edge_count: int
    schema_version: str | None = None
    condition: str | None = None
    issues: tuple[PreprocessingGraphExportBundleIssue, ...] = ()
    csv_validation_passed: bool | None = None
    csv_validation_issue_count: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "nodes_csv_path", Path(self.nodes_csv_path))
        object.__setattr__(self, "edges_csv_path", Path(self.edges_csv_path))
        object.__setattr__(self, "graph_json_path", Path(self.graph_json_path))
        _require_non_negative_int(self.node_count, "node_count")
        _require_non_negative_int(self.edge_count, "edge_count")
        if not isinstance(self.artifacts, tuple):
            raise ValueError(
                "artifacts must be a tuple of "
                "PreprocessingGraphExportBundleArtifact"
            )
        for artifact in self.artifacts:
            if not isinstance(artifact, PreprocessingGraphExportBundleArtifact):
                raise ValueError(
                    "artifacts must contain "
                    "PreprocessingGraphExportBundleArtifact"
                )
        if self.schema_version is not None:
            object.__setattr__(
                self,
                "schema_version",
                _non_empty_string(self.schema_version, "schema_version"),
            )
        if self.condition is not None:
            object.__setattr__(
                self,
                "condition",
                _non_empty_string(self.condition, "condition"),
            )
        if not isinstance(self.issues, tuple):
            raise ValueError(
                "issues must be a tuple of "
                "PreprocessingGraphExportBundleIssue"
            )
        for issue in self.issues:
            if not isinstance(issue, PreprocessingGraphExportBundleIssue):
                raise ValueError(
                    "issues must contain PreprocessingGraphExportBundleIssue"
                )
        if self.csv_validation_passed is not None and not isinstance(
            self.csv_validation_passed,
            bool,
        ):
            raise ValueError("csv_validation_passed must be bool or None")
        if self.csv_validation_issue_count is not None:
            _require_non_negative_int(
                self.csv_validation_issue_count,
                "csv_validation_issue_count",
            )

    @property
    def passed(self) -> bool:
        """Return whether the bundle boundary found no issues."""
        return self.issues == ()

    @property
    def issue_count(self) -> int:
        """Return the number of bundle issues."""
        return len(self.issues)

    @property
    def artifact_count(self) -> int:
        """Return the number of described bundle artifacts."""
        return len(self.artifacts)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe bundle result dictionary."""
        return {
            "nodes_csv_path": str(self.nodes_csv_path),
            "edges_csv_path": str(self.edges_csv_path),
            "graph_json_path": str(self.graph_json_path),
            "passed": self.passed,
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "schema_version": self.schema_version,
            "condition": self.condition,
            "artifact_count": self.artifact_count,
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "issue_count": self.issue_count,
            "issues": [issue.to_dict() for issue in self.issues],
            "csv_validation_passed": self.csv_validation_passed,
            "csv_validation_issue_count": self.csv_validation_issue_count,
        }


@dataclass(frozen=True)
class _ResidueIdentity:
    condition_name: str
    residue_index: int
    residue_id: str
    resname: str
    segid: str | None


@dataclass(frozen=True)
class _AggregateKey:
    condition_name: str
    source_node_id: str
    target_node_id: str
    edge_type: str
    distance_unit: str
    atom_filter: str


@dataclass(frozen=True)
class _EdgePairKey:
    condition_name: str
    source_node_id: str
    target_node_id: str


def build_preprocessing_graph_export_mapping(
    contacts_result: object,
) -> PreprocessingGraphExportMappingResult:
    """Map accepted contacts results to in-memory graph-ready records."""
    try:
        condition_results, input_issues = _condition_results(contacts_result)
        if input_issues:
            return PreprocessingGraphExportMappingResult(
                nodes=(),
                edges=(),
                issues=input_issues,
            )

        nodes_by_id: dict[str, PreprocessingGraphNodeMappingRecord] = {}
        edge_records: list[PreprocessingGraphEdgeMappingRecord] = []
        issues: list[PreprocessingGraphExportMappingIssue] = []

        for condition_index, condition_result in enumerate(condition_results):
            condition_edges, condition_issues = _map_condition_result(
                condition_result,
                condition_index=condition_index,
                nodes_by_id=nodes_by_id,
            )
            edge_records.extend(condition_edges)
            issues.extend(condition_issues)

        if not nodes_by_id and not edge_records and not issues:
            issues.append(
                PreprocessingGraphExportMappingIssue(
                    kind="empty_contacts_result",
                    field="contacts_result",
                    message="Contacts result contains no graph-mappable contacts.",
                )
            )

        return PreprocessingGraphExportMappingResult(
            nodes=tuple(nodes_by_id.values()),
            edges=tuple(edge_records),
            issues=tuple(issues),
        )
    except ValueError as exc:
        return PreprocessingGraphExportMappingResult(
            nodes=(),
            edges=(),
            issues=(
                PreprocessingGraphExportMappingIssue(
                    kind="mapping_failed",
                    field="contacts_result",
                    message=f"Graph export mapping failed: {exc}",
                ),
            ),
        )


def write_preprocessing_graph_nodes_csv(
    mapping_result: PreprocessingGraphExportMappingResult,
    output_path: str | Path,
) -> PreprocessingGraphNodesCsvWriteResult:
    """Write backend graph nodes.csv from an accepted graph mapping result."""
    path, path_issue = _graph_nodes_output_path(output_path)
    if path_issue is not None:
        return PreprocessingGraphNodesCsvWriteResult(
            output_path=path,
            rows_written=0,
            issues=(path_issue,),
        )

    if not isinstance(mapping_result, PreprocessingGraphExportMappingResult):
        return PreprocessingGraphNodesCsvWriteResult(
            output_path=path,
            rows_written=0,
            issues=(
                PreprocessingGraphNodesCsvWriteIssue(
                    kind="invalid_input",
                    field="mapping_result",
                    message=(
                        "mapping_result must be "
                        "PreprocessingGraphExportMappingResult."
                    ),
                ),
            ),
        )

    if not mapping_result.passed:
        return PreprocessingGraphNodesCsvWriteResult(
            output_path=path,
            rows_written=0,
            issues=(
                PreprocessingGraphNodesCsvWriteIssue(
                    kind="mapping_result_failed",
                    field="mapping_result.issues",
                    message="Graph export mapping result contains issues.",
                ),
            ),
        )

    duplicate_node_ids = _duplicates(
        tuple(node.node_id for node in mapping_result.nodes)
    )
    if duplicate_node_ids:
        return PreprocessingGraphNodesCsvWriteResult(
            output_path=path,
            rows_written=0,
            issues=tuple(
                PreprocessingGraphNodesCsvWriteIssue(
                    kind="duplicate_node_id",
                    node_id=node_id,
                    field="mapping_result.nodes",
                    message="Duplicate graph node ID cannot be written.",
                )
                for node_id in duplicate_node_ids
            ),
        )

    path_write_issue = _graph_nodes_path_write_issue(path)
    if path_write_issue is not None:
        return PreprocessingGraphNodesCsvWriteResult(
            output_path=path,
            rows_written=0,
            issues=(path_write_issue,),
        )

    rows = [_graph_node_row(node) for node in mapping_result.nodes]
    write_issue = _write_graph_node_rows(path, rows)
    if write_issue is not None:
        return PreprocessingGraphNodesCsvWriteResult(
            output_path=path,
            rows_written=0,
            issues=(write_issue,),
        )

    return PreprocessingGraphNodesCsvWriteResult(
        output_path=path,
        rows_written=len(rows),
        issues=(),
    )


def _write_backend_edges_csv(
    mapping_result: PreprocessingGraphExportMappingResult,
    output_path: str | Path,
) -> PreprocessingGraphEdgesCsvWriteResult:
    """Write backend graph edges.csv from an accepted graph mapping result."""
    path, path_issue = _graph_edges_output_path(output_path)
    if path_issue is not None:
        return PreprocessingGraphEdgesCsvWriteResult(
            output_path=path,
            rows_written=0,
            issues=(path_issue,),
        )

    if not isinstance(mapping_result, PreprocessingGraphExportMappingResult):
        return PreprocessingGraphEdgesCsvWriteResult(
            output_path=path,
            rows_written=0,
            issues=(
                PreprocessingGraphEdgesCsvWriteIssue(
                    kind="invalid_input",
                    field="mapping_result",
                    message=(
                        "mapping_result must be "
                        "PreprocessingGraphExportMappingResult."
                    ),
                ),
            ),
        )

    if not mapping_result.passed:
        return PreprocessingGraphEdgesCsvWriteResult(
            output_path=path,
            rows_written=0,
            issues=(
                PreprocessingGraphEdgesCsvWriteIssue(
                    kind="mapping_result_failed",
                    field="mapping_result.issues",
                    message="Graph export mapping result contains issues.",
                ),
            ),
        )

    duplicate_edge_ids = _duplicates(
        tuple(edge.edge_id for edge in mapping_result.edges)
    )
    if duplicate_edge_ids:
        return PreprocessingGraphEdgesCsvWriteResult(
            output_path=path,
            rows_written=0,
            issues=tuple(
                PreprocessingGraphEdgesCsvWriteIssue(
                    kind="duplicate_edge_id",
                    edge_id=edge_id,
                    field="mapping_result.edges",
                    message="Duplicate graph edge ID cannot be written.",
                )
                for edge_id in duplicate_edge_ids
            ),
        )

    path_write_issue = _graph_edges_path_write_issue(path)
    if path_write_issue is not None:
        return PreprocessingGraphEdgesCsvWriteResult(
            output_path=path,
            rows_written=0,
            issues=(path_write_issue,),
        )

    rows = [_backend_edge_row(edge) for edge in mapping_result.edges]
    write_issue = _write_backend_edge_rows(path, rows)
    if write_issue is not None:
        return PreprocessingGraphEdgesCsvWriteResult(
            output_path=path,
            rows_written=0,
            issues=(write_issue,),
        )

    return PreprocessingGraphEdgesCsvWriteResult(
        output_path=path,
        rows_written=len(rows),
        issues=(),
    )


def validate_preprocessing_graph_csvs(
    nodes_csv_path: str | Path,
    edges_csv_path: str | Path,
) -> PreprocessingGraphCsvValidationResult:
    """Validate generated backend graph nodes.csv and corrected edges.csv."""
    nodes_path, nodes_path_issue = _graph_csv_input_path(
        nodes_csv_path,
        csv_kind="nodes",
    )
    edges_path, edges_path_issue = _graph_csv_input_path(
        edges_csv_path,
        csv_kind="edges",
    )

    issues: list[PreprocessingGraphCsvValidationIssue] = []
    nodes_rows: _GraphCsvRows | None = None
    edges_rows: _GraphCsvRows | None = None

    if nodes_path_issue is not None:
        issues.append(nodes_path_issue)
    else:
        nodes_read_result = _read_graph_csv(nodes_path, csv_kind="nodes")
        if isinstance(nodes_read_result, PreprocessingGraphCsvValidationIssue):
            issues.append(nodes_read_result)
        else:
            nodes_rows = nodes_read_result

    if edges_path_issue is not None:
        issues.append(edges_path_issue)
    else:
        edges_read_result = _read_graph_csv(edges_path, csv_kind="edges")
        if isinstance(edges_read_result, PreprocessingGraphCsvValidationIssue):
            issues.append(edges_read_result)
        else:
            edges_rows = edges_read_result

    node_ids: set[str] | None = None
    node_count = 0
    edge_count = 0

    if nodes_rows is not None:
        if nodes_rows.header != NODE_COLUMNS:
            issues.append(
                _graph_csv_issue(
                    "invalid_header",
                    csv_kind="nodes",
                    column="header",
                    message="Backend graph nodes CSV header is invalid.",
                )
            )
        else:
            node_count = len(nodes_rows.rows)
            node_ids = _check_backend_nodes_rows(nodes_rows.rows, issues)

    if edges_rows is not None:
        if edges_rows.header != EDGE_COLUMNS:
            issues.append(
                _graph_csv_issue(
                    "invalid_header",
                    csv_kind="edges",
                    column="header",
                    message="Backend graph edges CSV header is invalid.",
                )
            )
        else:
            edge_count = len(edges_rows.rows)
            _check_backend_edges_rows(
                edges_rows.rows,
                issues,
                node_ids=node_ids,
            )

    return PreprocessingGraphCsvValidationResult(
        nodes_csv_path=nodes_path,
        edges_csv_path=edges_path,
        node_count=node_count,
        edge_count=edge_count,
        issues=tuple(issues),
    )


@dataclass(frozen=True)
class _GraphCsvRows:
    header: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]


def _graph_csv_input_path(
    input_path: object,
    *,
    csv_kind: str,
) -> tuple[Path, PreprocessingGraphCsvValidationIssue | None]:
    if input_path is None:
        return Path(""), _graph_csv_issue(
            "invalid_path",
            csv_kind=csv_kind,
            column="path",
            message="Graph CSV path is required.",
        )
    if isinstance(input_path, str) and input_path.strip() == "":
        return Path(""), _graph_csv_issue(
            "invalid_path",
            csv_kind=csv_kind,
            column="path",
            message="Graph CSV path is required.",
        )
    if not isinstance(input_path, _GRAPH_CSV_PATH_TYPES):
        return Path(""), _graph_csv_issue(
            "invalid_path",
            csv_kind=csv_kind,
            column="path",
            value=str(input_path),
            message="Graph CSV path must be a string or Path.",
        )
    try:
        return Path(input_path), None
    except TypeError:
        return Path(""), _graph_csv_issue(
            "invalid_path",
            csv_kind=csv_kind,
            column="path",
            value=str(input_path),
            message="Graph CSV path must be a string or Path.",
        )


def _read_graph_csv(
    path: Path,
    *,
    csv_kind: str,
) -> _GraphCsvRows | PreprocessingGraphCsvValidationIssue:
    if not path.exists():
        return _graph_csv_issue(
            "path_missing",
            csv_kind=csv_kind,
            column="path",
            value=str(path),
            message="Graph CSV file does not exist.",
        )
    if path.is_dir():
        return _graph_csv_issue(
            "path_is_directory",
            csv_kind=csv_kind,
            column="path",
            value=str(path),
            message="Graph CSV path is a directory.",
        )

    try:
        csv_text = path.read_text(encoding="utf-8")
        reader = csv.reader(StringIO(csv_text), strict=True)
        try:
            header = tuple(next(reader))
        except StopIteration:
            return _graph_csv_issue(
                "invalid_header",
                csv_kind=csv_kind,
                column="header",
                message="Graph CSV file is empty.",
            )
        rows = tuple(tuple(row) for row in reader)
    except (OSError, UnicodeError, csv.Error):
        return _graph_csv_issue(
            "read_failed",
            csv_kind=csv_kind,
            column="path",
            value=str(path),
            message="Graph CSV file could not be read as UTF-8 CSV.",
        )
    return _GraphCsvRows(header=header, rows=rows)


def _check_backend_nodes_rows(
    rows: tuple[tuple[str, ...], ...],
    issues: list[PreprocessingGraphCsvValidationIssue],
) -> set[str]:
    node_ids: set[str] = set()
    for row_number, row in enumerate(rows, start=2):
        if len(row) != len(NODE_COLUMNS):
            issues.append(
                _graph_csv_issue(
                    "row_column_count_mismatch",
                    csv_kind="nodes",
                    row_number=row_number,
                    column="row",
                    value=str(len(row)),
                    message="Node row has the wrong number of columns.",
                )
            )
        fields = _graph_row_fields(row, NODE_COLUMNS)
        _validate_required_graph_fields(
            fields,
            _GRAPH_NODE_REQUIRED_COLUMNS,
            csv_kind="nodes",
            row_number=row_number,
            issues=issues,
        )

        resid = fields["resid"].strip()
        if resid != "":
            if resid in node_ids:
                issues.append(
                    _graph_csv_issue(
                        "duplicate_node_id",
                        csv_kind="nodes",
                        row_number=row_number,
                        column="resid",
                        value=resid,
                        message="Node resid values must be unique.",
                    )
                )
            node_ids.add(resid)

        _validate_float_columns(
            fields,
            _GRAPH_NODE_FLOAT_COLUMNS,
            csv_kind="nodes",
            row_number=row_number,
            issues=issues,
        )
        _validate_integer_columns(
            fields,
            _GRAPH_NODE_INTEGER_COLUMNS,
            csv_kind="nodes",
            row_number=row_number,
            issues=issues,
        )
    return node_ids


def _check_backend_edges_rows(
    rows: tuple[tuple[str, ...], ...],
    issues: list[PreprocessingGraphCsvValidationIssue],
    *,
    node_ids: set[str] | None,
) -> None:
    edge_keys: set[tuple[str, str, str, str]] = set()
    for row_number, row in enumerate(rows, start=2):
        if len(row) != len(EDGE_COLUMNS):
            issues.append(
                _graph_csv_issue(
                    "row_column_count_mismatch",
                    csv_kind="edges",
                    row_number=row_number,
                    column="row",
                    value=str(len(row)),
                    message="Edge row has the wrong number of columns.",
                )
            )
        fields = _graph_row_fields(row, EDGE_COLUMNS)
        _validate_required_graph_fields(
            fields,
            _GRAPH_EDGE_REQUIRED_COLUMNS,
            csv_kind="edges",
            row_number=row_number,
            issues=issues,
        )

        resid_i = fields["resid_i"].strip()
        resid_j = fields["resid_j"].strip()
        edge_type = fields["edge_type"].strip()
        condition = fields["condition"].strip()

        if resid_i != "" and resid_j != "" and resid_i == resid_j:
            issues.append(
                _graph_csv_issue(
                    "self_edge",
                    csv_kind="edges",
                    row_number=row_number,
                    column="resid_j",
                    value=resid_j,
                    message="Edge endpoints must differ.",
                )
            )

        if node_ids is not None:
            _validate_edge_endpoint(
                resid_i,
                node_ids,
                csv_kind="edges",
                row_number=row_number,
                column="resid_i",
                issues=issues,
            )
            _validate_edge_endpoint(
                resid_j,
                node_ids,
                csv_kind="edges",
                row_number=row_number,
                column="resid_j",
                issues=issues,
            )

        if (
            resid_i != ""
            and resid_j != ""
            and edge_type != ""
            and condition != ""
        ):
            edge_key = (resid_i, resid_j, edge_type, condition)
            if edge_key in edge_keys:
                issues.append(
                    _graph_csv_issue(
                        "duplicate_edge_key",
                        csv_kind="edges",
                        row_number=row_number,
                        column="edge_type",
                        value=_EDGE_TYPE_SEPARATOR.join(edge_key),
                        message="Edge keys must be unique.",
                    )
                )
            edge_keys.add(edge_key)

        _validate_float_columns(
            fields,
            _GRAPH_EDGE_FLOAT_COLUMNS,
            csv_kind="edges",
            row_number=row_number,
            issues=issues,
        )
        n_edge_types = _validate_integer_columns(
            fields,
            _GRAPH_EDGE_INTEGER_COLUMNS,
            csv_kind="edges",
            row_number=row_number,
            issues=issues,
            positive_integer_columns=("n_edge_types",),
        )
        _validate_edge_type_fields(
            fields,
            row_number=row_number,
            issues=issues,
            n_edge_types=n_edge_types.get("n_edge_types"),
        )


def _validate_edge_endpoint(
    endpoint: str,
    node_ids: set[str],
    *,
    csv_kind: str,
    row_number: int,
    column: str,
    issues: list[PreprocessingGraphCsvValidationIssue],
) -> None:
    if endpoint == "":
        return
    if endpoint not in node_ids:
        issues.append(
            _graph_csv_issue(
                "edge_endpoint_missing",
                csv_kind=csv_kind,
                row_number=row_number,
                column=column,
                value=endpoint,
                message="Edge endpoint is missing from nodes.csv.",
            )
        )


def _validate_required_graph_fields(
    fields: dict[str, str],
    required_columns: tuple[str, ...],
    *,
    csv_kind: str,
    row_number: int,
    issues: list[PreprocessingGraphCsvValidationIssue],
) -> None:
    for column in required_columns:
        if fields[column].strip() == "":
            issues.append(
                _graph_csv_issue(
                    "missing_required_value",
                    csv_kind=csv_kind,
                    row_number=row_number,
                    column=column,
                    value=fields[column],
                    message="Required graph CSV value is missing.",
                )
            )


def _validate_float_columns(
    fields: dict[str, str],
    columns: tuple[str, ...],
    *,
    csv_kind: str,
    row_number: int,
    issues: list[PreprocessingGraphCsvValidationIssue],
) -> None:
    for column in columns:
        value = fields[column].strip()
        if value == "":
            continue
        try:
            parsed_value = float(value)
        except ValueError:
            issues.append(
                _invalid_numeric_issue(csv_kind, row_number, column, value)
            )
            continue
        if not math.isfinite(parsed_value):
            issues.append(
                _invalid_numeric_issue(csv_kind, row_number, column, value)
            )


def _validate_integer_columns(
    fields: dict[str, str],
    columns: tuple[str, ...],
    *,
    csv_kind: str,
    row_number: int,
    issues: list[PreprocessingGraphCsvValidationIssue],
    positive_integer_columns: tuple[str, ...] = (),
) -> dict[str, int]:
    parsed_values: dict[str, int] = {}
    positive_columns = set(positive_integer_columns)
    for column in columns:
        value = fields[column].strip()
        if value == "":
            continue
        try:
            parsed_value = int(value)
        except ValueError:
            issues.append(
                _invalid_integer_issue(csv_kind, row_number, column, value)
            )
            continue
        if column in positive_columns and parsed_value <= 0:
            issues.append(
                _invalid_integer_issue(csv_kind, row_number, column, value)
            )
            continue
        parsed_values[column] = parsed_value
    return parsed_values


def _validate_edge_type_fields(
    fields: dict[str, str],
    *,
    row_number: int,
    issues: list[PreprocessingGraphCsvValidationIssue],
    n_edge_types: int | None,
) -> None:
    edge_type = fields["edge_type"].strip()
    all_edge_types = fields["all_edge_types"].strip()
    if edge_type == "" or all_edge_types == "":
        return

    edge_types = _split_graph_edge_types(
        all_edge_types,
        row_number=row_number,
        issues=issues,
    )
    unique_edge_types = tuple(dict.fromkeys(edge_types))
    if edge_type not in unique_edge_types:
        issues.append(
            _graph_csv_issue(
                "edge_type_not_in_all_edge_types",
                csv_kind="edges",
                row_number=row_number,
                column="edge_type",
                value=edge_type,
                message="Primary edge_type must be in all_edge_types.",
            )
        )

    expected_order = tuple(sorted(unique_edge_types, key=_edge_type_priority_key))
    if edge_types == unique_edge_types and edge_types != expected_order:
        issues.append(
            _graph_csv_issue(
                "invalid_edge_type_order",
                csv_kind="edges",
                row_number=row_number,
                column="all_edge_types",
                value=all_edge_types,
                message="all_edge_types must follow deterministic priority order.",
            )
        )

    if (
        edge_type in unique_edge_types
        and expected_order
        and edge_type != expected_order[0]
    ):
        issues.append(
            _graph_csv_issue(
                "invalid_primary_edge_type",
                csv_kind="edges",
                row_number=row_number,
                column="edge_type",
                value=edge_type,
                message="edge_type must be the highest-priority edge type.",
            )
        )

    if n_edge_types is not None and n_edge_types != len(unique_edge_types):
        issues.append(
            _graph_csv_issue(
                "invalid_edge_type_count",
                csv_kind="edges",
                row_number=row_number,
                column="n_edge_types",
                value=fields["n_edge_types"],
                message="n_edge_types must match unique all_edge_types count.",
            )
        )


def _split_graph_edge_types(
    all_edge_types: str,
    *,
    row_number: int,
    issues: list[PreprocessingGraphCsvValidationIssue],
) -> tuple[str, ...]:
    edge_types: list[str] = []
    seen_edge_types: set[str] = set()
    duplicate_edge_types: set[str] = set()
    for edge_type_value in all_edge_types.split(_EDGE_TYPE_SEPARATOR):
        edge_type = edge_type_value.strip()
        if edge_type == "":
            issues.append(
                _graph_csv_issue(
                    "empty_edge_type_value",
                    csv_kind="edges",
                    row_number=row_number,
                    column="all_edge_types",
                    value=edge_type_value,
                    message="all_edge_types must not contain empty values.",
                )
            )
            continue
        if edge_type in seen_edge_types and edge_type not in duplicate_edge_types:
            issues.append(
                _graph_csv_issue(
                    "duplicate_edge_type_value",
                    csv_kind="edges",
                    row_number=row_number,
                    column="all_edge_types",
                    value=edge_type,
                    message="all_edge_types must not contain duplicate values.",
                )
            )
            duplicate_edge_types.add(edge_type)
        seen_edge_types.add(edge_type)
        edge_types.append(edge_type)
    return tuple(edge_types)


def _graph_row_fields(
    row: tuple[str, ...],
    columns: tuple[str, ...],
) -> dict[str, str]:
    return {
        column: row[index] if index < len(row) else ""
        for index, column in enumerate(columns)
    }


def _invalid_numeric_issue(
    csv_kind: str,
    row_number: int,
    column: str,
    value: str,
) -> PreprocessingGraphCsvValidationIssue:
    return _graph_csv_issue(
        "invalid_numeric_value",
        csv_kind=csv_kind,
        row_number=row_number,
        column=column,
        value=value,
        message="Graph CSV numeric value must be finite.",
    )


def _invalid_integer_issue(
    csv_kind: str,
    row_number: int,
    column: str,
    value: str,
) -> PreprocessingGraphCsvValidationIssue:
    return _graph_csv_issue(
        "invalid_integer_value",
        csv_kind=csv_kind,
        row_number=row_number,
        column=column,
        value=value,
        message="Graph CSV integer value is invalid.",
    )


def _graph_csv_issue(
    kind: str,
    *,
    csv_kind: str,
    message: str,
    row_number: int | None = None,
    column: str | None = None,
    value: str | None = None,
) -> PreprocessingGraphCsvValidationIssue:
    return PreprocessingGraphCsvValidationIssue(
        kind=kind,
        message=message,
        csv_kind=csv_kind,
        row_number=row_number,
        column=column,
        value=value,
    )


def _condition_results(
    contacts_result: object,
) -> tuple[
    tuple[PreprocessingConditionContactsResult, ...],
    tuple[PreprocessingGraphExportMappingIssue, ...],
]:
    if isinstance(contacts_result, PreprocessingManifestContactsResult):
        issues = tuple(
            PreprocessingGraphExportMappingIssue(
                kind="mapping_failed",
                field=f"contacts_result.issues[{index}]",
                message=issue.message,
            )
            for index, issue in enumerate(contacts_result.issues)
        )
        if not contacts_result.condition_results:
            issues = (
                *issues,
                PreprocessingGraphExportMappingIssue(
                    kind="empty_contacts_result",
                    field="contacts_result.condition_results",
                    message="Manifest contacts result contains no conditions.",
                ),
            )
        return contacts_result.condition_results, issues
    if isinstance(contacts_result, PreprocessingConditionContactsResult):
        return (contacts_result,), ()
    return (), (
        PreprocessingGraphExportMappingIssue(
            kind="unsupported_input_type",
            field="contacts_result",
            message=(
                "Contacts result must be a condition or manifest contacts "
                "result."
            ),
        ),
    )


def write_preprocessing_graph_json(
    nodes_csv_path: str | Path,
    edges_csv_path: str | Path,
    output_path: str | Path,
) -> PreprocessingGraphJsonWriteResult:
    """Write backend graph.json from accepted, validated graph CSV artifacts."""
    nodes_path = _coerced_json_input_path(nodes_csv_path)
    edges_path = _coerced_json_input_path(edges_csv_path)
    path, path_issue = _graph_json_output_path(output_path)
    if path_issue is not None:
        return PreprocessingGraphJsonWriteResult(
            output_path=path,
            nodes_csv_path=nodes_path,
            edges_csv_path=edges_path,
            node_count=0,
            edge_count=0,
            issues=(path_issue,),
            validation_passed=None,
            validation_issue_count=None,
        )

    validation = validate_preprocessing_graph_csvs(nodes_csv_path, edges_csv_path)
    nodes_path = validation.nodes_csv_path
    edges_path = validation.edges_csv_path
    if not validation.passed:
        return PreprocessingGraphJsonWriteResult(
            output_path=path,
            nodes_csv_path=nodes_path,
            edges_csv_path=edges_path,
            node_count=validation.node_count,
            edge_count=validation.edge_count,
            issues=(
                PreprocessingGraphJsonWriteIssue(
                    kind="validation_failed",
                    field="validation.issues",
                    message="Graph CSV validation failed before JSON write.",
                ),
            ),
            validation_passed=False,
            validation_issue_count=validation.issue_count,
        )

    path_write_issue = _graph_json_path_write_issue(path)
    if path_write_issue is not None:
        return PreprocessingGraphJsonWriteResult(
            output_path=path,
            nodes_csv_path=nodes_path,
            edges_csv_path=edges_path,
            node_count=validation.node_count,
            edge_count=validation.edge_count,
            issues=(path_write_issue,),
            validation_passed=True,
            validation_issue_count=0,
        )

    graph_result = _read_graph_json_payload(
        nodes_path,
        edges_path,
        node_count=validation.node_count,
        edge_count=validation.edge_count,
    )
    if isinstance(graph_result, PreprocessingGraphJsonWriteIssue):
        return PreprocessingGraphJsonWriteResult(
            output_path=path,
            nodes_csv_path=nodes_path,
            edges_csv_path=edges_path,
            node_count=validation.node_count,
            edge_count=validation.edge_count,
            issues=(graph_result,),
            validation_passed=True,
            validation_issue_count=0,
        )

    write_issue = _write_graph_payload(path, graph_result)
    if write_issue is not None:
        return PreprocessingGraphJsonWriteResult(
            output_path=path,
            nodes_csv_path=nodes_path,
            edges_csv_path=edges_path,
            node_count=validation.node_count,
            edge_count=validation.edge_count,
            issues=(write_issue,),
            validation_passed=True,
            validation_issue_count=0,
        )

    return PreprocessingGraphJsonWriteResult(
        output_path=path,
        nodes_csv_path=nodes_path,
        edges_csv_path=edges_path,
        node_count=validation.node_count,
        edge_count=validation.edge_count,
        issues=(),
        validation_passed=True,
        validation_issue_count=0,
    )


def build_preprocessing_graph_export_bundle(
    nodes_csv_path: str | Path,
    edges_csv_path: str | Path,
    graph_json_path: str | Path,
) -> PreprocessingGraphExportBundleResult:
    """Describe existing Stage 14 preprocessing graph artifacts read-only."""
    nodes_path, nodes_path_issue = _graph_bundle_input_path(
        nodes_csv_path,
        artifact_kind="nodes_csv",
    )
    edges_path, edges_path_issue = _graph_bundle_input_path(
        edges_csv_path,
        artifact_kind="edges_csv",
    )
    graph_path, graph_path_issue = _graph_bundle_input_path(
        graph_json_path,
        artifact_kind="graph_json",
    )

    artifacts = (
        _graph_bundle_artifact(
            "nodes_csv",
            nodes_path,
            path_valid=nodes_path_issue is None,
        ),
        _graph_bundle_artifact(
            "edges_csv",
            edges_path,
            path_valid=edges_path_issue is None,
        ),
        _graph_bundle_artifact(
            "graph_json",
            graph_path,
            path_valid=graph_path_issue is None,
        ),
    )

    issues: list[PreprocessingGraphExportBundleIssue] = []
    for path_issue in (
        nodes_path_issue,
        edges_path_issue,
        graph_path_issue,
    ):
        if path_issue is not None:
            issues.append(path_issue)
    _add_graph_bundle_file_issues(artifacts, issues)

    csv_validation = validate_preprocessing_graph_csvs(
        nodes_csv_path,
        edges_csv_path,
    )
    issues.extend(_graph_bundle_csv_issues(csv_validation))

    graph: dict[str, object] | None = None
    graph_read_result = _read_graph_bundle_json(graph_path)
    if isinstance(graph_read_result, PreprocessingGraphExportBundleIssue):
        if graph_path_issue is None and graph_path.exists() and not graph_path.is_dir():
            issues.append(graph_read_result)
    else:
        graph = graph_read_result

    schema_version: str | None = None
    condition: str | None = None
    if graph is not None:
        schema_version, condition = _check_graph_bundle_json(
            graph,
            csv_node_count=csv_validation.node_count,
            csv_edge_count=csv_validation.edge_count,
            compare_csv_counts=csv_validation.passed,
            issues=issues,
        )

    return PreprocessingGraphExportBundleResult(
        nodes_csv_path=nodes_path,
        edges_csv_path=edges_path,
        graph_json_path=graph_path,
        artifacts=artifacts,
        node_count=csv_validation.node_count,
        edge_count=csv_validation.edge_count,
        schema_version=schema_version,
        condition=condition,
        issues=tuple(issues),
        csv_validation_passed=csv_validation.passed,
        csv_validation_issue_count=csv_validation.issue_count,
    )


def _graph_bundle_input_path(
    input_path: object,
    *,
    artifact_kind: str,
) -> tuple[Path, PreprocessingGraphExportBundleIssue | None]:
    if input_path is None:
        return Path(""), _graph_bundle_issue(
            "invalid_path",
            artifact_kind=artifact_kind,
            field="path",
            message="Graph export bundle artifact path is required.",
        )
    if isinstance(input_path, str) and input_path.strip() == "":
        return Path(""), _graph_bundle_issue(
            "invalid_path",
            artifact_kind=artifact_kind,
            field="path",
            message="Graph export bundle artifact path is required.",
        )
    if not isinstance(input_path, _GRAPH_CSV_PATH_TYPES):
        return Path(""), _graph_bundle_issue(
            "invalid_path",
            artifact_kind=artifact_kind,
            field="path",
            value=str(input_path),
            message="Graph export bundle artifact path must be a string or Path.",
        )
    try:
        return Path(input_path), None
    except TypeError:
        return Path(""), _graph_bundle_issue(
            "invalid_path",
            artifact_kind=artifact_kind,
            field="path",
            value=str(input_path),
            message="Graph export bundle artifact path must be a string or Path.",
        )


def _graph_bundle_artifact(
    kind: str,
    path: Path,
    *,
    path_valid: bool,
) -> PreprocessingGraphExportBundleArtifact:
    if not path_valid:
        return PreprocessingGraphExportBundleArtifact(
            kind=kind,
            path=path,
            exists=False,
            size_bytes=None,
        )

    exists = path.exists()
    size_bytes: int | None = None
    if exists and path.is_file():
        try:
            size_bytes = path.stat().st_size
        except OSError:
            size_bytes = None
    return PreprocessingGraphExportBundleArtifact(
        kind=kind,
        path=path,
        exists=exists,
        size_bytes=size_bytes,
    )


def _add_graph_bundle_file_issues(
    artifacts: tuple[PreprocessingGraphExportBundleArtifact, ...],
    issues: list[PreprocessingGraphExportBundleIssue],
) -> None:
    for artifact in artifacts:
        if not artifact.exists:
            issues.append(
                _graph_bundle_issue(
                    "path_missing",
                    artifact_kind=artifact.kind,
                    field="path",
                    value=str(artifact.path),
                    message="Graph export bundle artifact does not exist.",
                )
            )
            continue
        if artifact.path.is_dir():
            issues.append(
                _graph_bundle_issue(
                    "path_is_directory",
                    artifact_kind=artifact.kind,
                    field="path",
                    value=str(artifact.path),
                    message="Graph export bundle artifact path is a directory.",
                )
            )


def _graph_bundle_csv_issues(
    validation: PreprocessingGraphCsvValidationResult,
) -> tuple[PreprocessingGraphExportBundleIssue, ...]:
    issues: list[PreprocessingGraphExportBundleIssue] = []
    for issue in validation.issues:
        artifact_kind = (
            "nodes_csv" if issue.csv_kind == "nodes" else "edges_csv"
        )
        issues.append(
            _graph_bundle_issue(
                "csv_validation_failed",
                artifact_kind=artifact_kind,
                field=issue.column,
                value=issue.value,
                message=f"Graph CSV validation failed: {issue.message}",
            )
        )
    return tuple(issues)


def _read_graph_bundle_json(
    path: Path,
) -> dict[str, object] | PreprocessingGraphExportBundleIssue:
    try:
        payload = _json_loads(path.read_text(encoding="utf-8"))
    except JSONDecodeError:
        return _graph_bundle_issue(
            "graph_json_parse_failed",
            artifact_kind="graph_json",
            field="path",
            value=str(path),
            message="graph.json could not be parsed as JSON.",
        )
    except (OSError, UnicodeError):
        return _graph_bundle_issue(
            "graph_json_read_failed",
            artifact_kind="graph_json",
            field="path",
            value=str(path),
            message="graph.json could not be read as UTF-8 text.",
        )

    if not isinstance(payload, dict):
        return _graph_bundle_issue(
            "graph_json_invalid_field",
            artifact_kind="graph_json",
            field="root",
            message="graph.json top-level value must be an object.",
        )
    return payload


def _check_graph_bundle_json(
    graph: dict[str, object],
    *,
    csv_node_count: int,
    csv_edge_count: int,
    compare_csv_counts: bool,
    issues: list[PreprocessingGraphExportBundleIssue],
) -> tuple[str | None, str | None]:
    for key in GRAPH_REQUIRED_KEYS:
        if key not in graph:
            issues.append(
                _graph_bundle_issue(
                    "graph_json_missing_key",
                    artifact_kind="graph_json",
                    field=key,
                    message="graph.json is missing a required top-level key.",
                )
            )

    schema_version = _graph_bundle_optional_metadata_string(
        graph,
        field="schema_version",
        issues=issues,
        require_non_empty=True,
    )
    n_nodes = _graph_bundle_count_field(graph, "n_nodes", issues)
    n_edges = _graph_bundle_count_field(graph, "n_edges", issues)
    nodes = _graph_bundle_list_field(graph, "nodes", issues)
    edges = _graph_bundle_list_field(graph, "edges", issues)
    condition = _graph_bundle_condition(graph, n_nodes, n_edges, issues)

    directed = graph.get("directed")
    if "directed" in graph and not isinstance(directed, bool):
        issues.append(
            _graph_bundle_issue(
                "graph_json_invalid_field",
                artifact_kind="graph_json",
                field="directed",
                value=str(directed),
                message="graph.json directed must be bool.",
            )
        )

    if n_nodes is not None and nodes is not None:
        _add_graph_bundle_count_mismatch(
            declared=n_nodes,
            actual=len(nodes),
            field="n_nodes",
            actual_field="nodes",
            issues=issues,
        )
    if n_edges is not None and edges is not None:
        _add_graph_bundle_count_mismatch(
            declared=n_edges,
            actual=len(edges),
            field="n_edges",
            actual_field="edges",
            issues=issues,
        )
    if compare_csv_counts:
        if n_nodes is not None and n_nodes != csv_node_count:
            issues.append(
                _graph_bundle_issue(
                    "graph_json_count_mismatch",
                    artifact_kind="graph_json",
                    field="n_nodes",
                    value=str(n_nodes),
                    message="graph.json n_nodes does not match nodes.csv count.",
                )
            )
        if n_edges is not None and n_edges != csv_edge_count:
            issues.append(
                _graph_bundle_issue(
                    "graph_json_count_mismatch",
                    artifact_kind="graph_json",
                    field="n_edges",
                    value=str(n_edges),
                    message="graph.json n_edges does not match edges.csv count.",
                )
            )

    if nodes is not None:
        _check_graph_bundle_nodes(nodes, issues)
    if edges is not None:
        _check_graph_bundle_edges(edges, issues)

    return schema_version, condition


def _graph_bundle_optional_metadata_string(
    graph: dict[str, object],
    *,
    field: str,
    issues: list[PreprocessingGraphExportBundleIssue],
    require_non_empty: bool,
) -> str | None:
    if field not in graph:
        return None
    value = graph[field]
    if not isinstance(value, str) or (require_non_empty and value.strip() == ""):
        issues.append(
            _graph_bundle_issue(
                "graph_json_invalid_field",
                artifact_kind="graph_json",
                field=field,
                value=str(value),
                message=f"graph.json {field} must be a non-empty string.",
            )
        )
        return None
    if value.strip() == "":
        return None
    return value


def _graph_bundle_condition(
    graph: dict[str, object],
    n_nodes: int | None,
    n_edges: int | None,
    issues: list[PreprocessingGraphExportBundleIssue],
) -> str | None:
    if "condition" not in graph:
        return None
    value = graph["condition"]
    if not isinstance(value, str):
        issues.append(
            _graph_bundle_issue(
                "graph_json_invalid_field",
                artifact_kind="graph_json",
                field="condition",
                value=str(value),
                message="graph.json condition must be a string.",
            )
        )
        return None

    if value.strip() != "":
        return value
    if n_nodes == 0 and n_edges == 0:
        return None

    issues.append(
        _graph_bundle_issue(
            "graph_json_invalid_field",
            artifact_kind="graph_json",
            field="condition",
            value=value,
            message="graph.json condition must be non-empty when rows exist.",
        )
    )
    return None


def _graph_bundle_count_field(
    graph: dict[str, object],
    field: str,
    issues: list[PreprocessingGraphExportBundleIssue],
) -> int | None:
    if field not in graph:
        return None
    value = graph[field]
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        issues.append(
            _graph_bundle_issue(
                "graph_json_invalid_field",
                artifact_kind="graph_json",
                field=field,
                value=str(value),
                message=f"graph.json {field} must be a non-negative int.",
            )
        )
        return None
    return value


def _graph_bundle_list_field(
    graph: dict[str, object],
    field: str,
    issues: list[PreprocessingGraphExportBundleIssue],
) -> list[object] | None:
    if field not in graph:
        return None
    value = graph[field]
    if not isinstance(value, list):
        issues.append(
            _graph_bundle_issue(
                "graph_json_invalid_field",
                artifact_kind="graph_json",
                field=field,
                value=str(value),
                message=f"graph.json {field} must be a list.",
            )
        )
        return None
    return value


def _add_graph_bundle_count_mismatch(
    *,
    declared: int,
    actual: int,
    field: str,
    actual_field: str,
    issues: list[PreprocessingGraphExportBundleIssue],
) -> None:
    if declared == actual:
        return
    issues.append(
        _graph_bundle_issue(
            "graph_json_count_mismatch",
            artifact_kind="graph_json",
            field=field,
            value=str(declared),
            message=(
                f"graph.json {field} does not match "
                f"len({actual_field})."
            ),
        )
    )


def _check_graph_bundle_nodes(
    nodes: list[object],
    issues: list[PreprocessingGraphExportBundleIssue],
) -> None:
    for index, node in enumerate(nodes):
        field_prefix = f"nodes[{index}]"
        if not isinstance(node, dict):
            issues.append(
                _graph_bundle_issue(
                    "graph_json_invalid_field",
                    artifact_kind="graph_json",
                    field=field_prefix,
                    message="graph.json node entries must be objects.",
                )
            )
            continue
        if not _has_graph_bundle_non_empty_string_field(node, ("id", "resid")):
            issues.append(
                _graph_bundle_issue(
                    "graph_json_missing_node_field",
                    artifact_kind="graph_json",
                    field=f"{field_prefix}.id",
                    message="graph.json node must preserve id or resid.",
                )
            )
        _require_graph_bundle_string_field(
            node,
            f"{field_prefix}.condition",
            key="condition",
            issue_kind="graph_json_missing_node_field",
            issues=issues,
        )


def _check_graph_bundle_edges(
    edges: list[object],
    issues: list[PreprocessingGraphExportBundleIssue],
) -> None:
    for index, edge in enumerate(edges):
        field_prefix = f"edges[{index}]"
        if not isinstance(edge, dict):
            issues.append(
                _graph_bundle_issue(
                    "graph_json_invalid_field",
                    artifact_kind="graph_json",
                    field=field_prefix,
                    message="graph.json edge entries must be objects.",
                )
            )
            continue
        if not _has_graph_bundle_non_empty_string_field(edge, ("source", "resid_i")):
            issues.append(
                _graph_bundle_issue(
                    "graph_json_missing_edge_field",
                    artifact_kind="graph_json",
                    field=f"{field_prefix}.source",
                    message="graph.json edge must preserve source or resid_i.",
                )
            )
        if not _has_graph_bundle_non_empty_string_field(edge, ("target", "resid_j")):
            issues.append(
                _graph_bundle_issue(
                    "graph_json_missing_edge_field",
                    artifact_kind="graph_json",
                    field=f"{field_prefix}.target",
                    message="graph.json edge must preserve target or resid_j.",
                )
            )
        for key in _GRAPH_JSON_EDGE_REQUIRED_FIELDS:
            _require_graph_bundle_string_field(
                edge,
                f"{field_prefix}.{key}",
                key=key,
                issue_kind="graph_json_missing_edge_field",
                issues=issues,
            )


def _has_graph_bundle_non_empty_string_field(
    row: dict[object, object],
    keys: tuple[str, ...],
) -> bool:
    return any(
        isinstance(row.get(key), str) and str(row.get(key)).strip() != ""
        for key in keys
    )


def _require_graph_bundle_string_field(
    row: dict[object, object],
    field: str,
    *,
    key: str,
    issue_kind: str,
    issues: list[PreprocessingGraphExportBundleIssue],
) -> None:
    if key not in row:
        issues.append(
            _graph_bundle_issue(
                issue_kind,
                artifact_kind="graph_json",
                field=field,
                message=f"graph.json row is missing {key}.",
            )
        )
        return
    value = row[key]
    if not isinstance(value, str) or value.strip() == "":
        issues.append(
            _graph_bundle_issue(
                "graph_json_invalid_field",
                artifact_kind="graph_json",
                field=field,
                value=str(value),
                message=f"graph.json row field {key} must be a non-empty string.",
            )
        )


def _graph_bundle_issue(
    kind: str,
    *,
    message: str,
    artifact_kind: str | None = None,
    field: str | None = None,
    value: str | None = None,
) -> PreprocessingGraphExportBundleIssue:
    return PreprocessingGraphExportBundleIssue(
        kind=kind,
        message=message,
        artifact_kind=artifact_kind,
        field=field,
        value=value,
    )


def _map_condition_result(
    condition_result: PreprocessingConditionContactsResult,
    *,
    condition_index: int,
    nodes_by_id: dict[str, PreprocessingGraphNodeMappingRecord],
) -> tuple[
    tuple[PreprocessingGraphEdgeMappingRecord, ...],
    tuple[PreprocessingGraphExportMappingIssue, ...],
]:
    issues: list[PreprocessingGraphExportMappingIssue] = []
    if not condition_result.passed:
        issues.append(
            PreprocessingGraphExportMappingIssue(
                kind="mapping_failed",
                record_id=condition_result.condition_name,
                field=f"condition_results[{condition_index}]",
                message="Condition contacts result did not pass.",
            )
        )

    included_frame_count = 0
    aggregate_distances: dict[_AggregateKey, list[float]] = {}
    coordinates_by_node_id = _ca_coordinates_by_node_id(condition_result)

    if condition_result.options.contact_selection == "protein":
        for coordinate in condition_result.representative_ca_coordinates:
            node = _node_record_from_ca_coordinate(
                condition_result.condition_name,
                coordinate,
            )
            nodes_by_id.setdefault(node.node_id, node)

    for frame_index, frame_result in enumerate(condition_result.frame_results):
        if not frame_result.passed:
            issues.append(
                PreprocessingGraphExportMappingIssue(
                    kind="mapping_failed",
                    record_id=condition_result.condition_name,
                    field=(
                        f"condition_results[{condition_index}]"
                        f".frame_results[{frame_index}]"
                    ),
                    message="Frame contacts result did not pass.",
                )
            )
            continue

        included_frame_count += 1
        frame_distances = _frame_distances(
            frame_result,
            condition_index=condition_index,
            frame_index=frame_index,
            nodes_by_id=nodes_by_id,
            coordinates_by_node_id=coordinates_by_node_id,
            issues=issues,
        )
        for key, distance in frame_distances.items():
            aggregate_distances.setdefault(key, []).append(distance)

    contact_edges = _merge_typed_contact_edges(
        tuple(
            _edge_record(key, distances, included_frame_count)
            for key, distances in sorted(
                aggregate_distances.items(),
                key=lambda item: (_edge_id(item[0]), item[0].edge_type),
            )
        )
    )
    backbone_pairs = _backbone_edge_pairs(
        condition_result,
        nodes_by_id=nodes_by_id,
    )
    edges = _merge_backbone_edges(contact_edges, backbone_pairs)

    if not edges:
        issues.append(
            PreprocessingGraphExportMappingIssue(
                kind="empty_contacts_result",
                record_id=condition_result.condition_name,
                field=f"condition_results[{condition_index}]",
                message=(
                    "Condition contacts result contains no graph-mappable "
                    "passed-frame contacts or backbone edges."
                ),
            )
        )

    if condition_result.options.contact_selection == "protein":
        for node in sorted(nodes_by_id.values(), key=lambda item: item.node_id):
            if (
                node.condition_name == condition_result.condition_name
                and node.x_ca is None
            ):
                issues.append(
                    PreprocessingGraphExportMappingIssue(
                        kind="node_coordinates_missing",
                        record_id=node.node_id,
                        field="representative_ca_coordinates",
                        message=(
                            "Protein graph node has no representative Cα "
                            "coordinates."
                        ),
                    )
                )

    return edges, tuple(issues)


def _graph_node_row(
    node: PreprocessingGraphNodeMappingRecord,
) -> dict[str, str]:
    row = {column: "" for column in NODE_COLUMNS}
    row.update(
        {
            "resid": node.node_id,
            "resname": node.resname,
            "region": f"{node.source}:{node.node_kind}",
            "condition": node.condition_name,
            "x_ca": _optional_number_csv_value(node.x_ca),
            "y_ca": _optional_number_csv_value(node.y_ca),
            "z_ca": _optional_number_csv_value(node.z_ca),
        }
    )
    return row


def _backend_edge_row(
    edge: PreprocessingGraphEdgeMappingRecord,
) -> dict[str, str]:
    row = {column: "" for column in EDGE_COLUMNS}
    row.update(
        {
            "resid_i": edge.source_node_id,
            "resid_j": edge.target_node_id,
            "edge_type": edge.edge_kind,
            "all_edge_types": _all_edge_types_csv_value(edge),
            "n_edge_types": str(edge.n_edge_types),
            "condition": edge.condition_name,
            "contact_freq": _optional_number_csv_value(
                edge.contact_frequency
            ),
            "mean_dist_A": _mean_distance_a_csv_value(edge),
        }
    )
    return row


def _optional_number_csv_value(value: int | float | None) -> str:
    if value is None:
        return ""
    return str(value)


def _mean_distance_a_csv_value(
    edge: PreprocessingGraphEdgeMappingRecord,
) -> str:
    if edge.mean_minimum_distance is None:
        return ""
    if edge.distance_unit != "angstrom":
        return ""
    return str(edge.mean_minimum_distance)


def _all_edge_types_csv_value(
    edge: PreprocessingGraphEdgeMappingRecord,
) -> str:
    all_edge_types = edge.all_edge_types
    if all_edge_types is None:
        return edge.edge_kind
    return _EDGE_TYPE_SEPARATOR.join(all_edge_types)


def _graph_nodes_output_path(
    output_path: object,
) -> tuple[Path, PreprocessingGraphNodesCsvWriteIssue | None]:
    if output_path is None:
        return Path(""), PreprocessingGraphNodesCsvWriteIssue(
            kind="invalid_output_path",
            field="output_path",
            message="Output path is required.",
        )
    if isinstance(output_path, str) and not output_path.strip():
        return Path(""), PreprocessingGraphNodesCsvWriteIssue(
            kind="invalid_output_path",
            field="output_path",
            message="Output path is required.",
        )
    if not isinstance(output_path, _PATHLIKE_TYPES):
        return Path(""), PreprocessingGraphNodesCsvWriteIssue(
            kind="invalid_output_path",
            field="output_path",
            message="Output path must be path-like.",
        )
    try:
        return Path(output_path), None
    except TypeError:
        return Path(""), PreprocessingGraphNodesCsvWriteIssue(
            kind="invalid_output_path",
            field="output_path",
            message="Output path must be path-like.",
        )


def _graph_nodes_path_write_issue(
    output_path: Path,
) -> PreprocessingGraphNodesCsvWriteIssue | None:
    if output_path.is_dir():
        return PreprocessingGraphNodesCsvWriteIssue(
            kind="output_path_is_directory",
            field="output_path",
            message="Output path is a directory.",
        )
    if not output_path.parent.exists():
        return PreprocessingGraphNodesCsvWriteIssue(
            kind="parent_directory_missing",
            field="output_path.parent",
            message="Output parent directory does not exist.",
        )
    if not output_path.parent.is_dir():
        return PreprocessingGraphNodesCsvWriteIssue(
            kind="parent_directory_missing",
            field="output_path.parent",
            message="Output parent path is not a directory.",
        )
    return None


def _graph_edges_output_path(
    output_path: object,
) -> tuple[Path, PreprocessingGraphEdgesCsvWriteIssue | None]:
    if output_path is None:
        return Path(""), PreprocessingGraphEdgesCsvWriteIssue(
            kind="invalid_output_path",
            field="output_path",
            message="Output path is required.",
        )
    if isinstance(output_path, str) and not output_path.strip():
        return Path(""), PreprocessingGraphEdgesCsvWriteIssue(
            kind="invalid_output_path",
            field="output_path",
            message="Output path is required.",
        )
    if not isinstance(output_path, _PATHLIKE_TYPES):
        return Path(""), PreprocessingGraphEdgesCsvWriteIssue(
            kind="invalid_output_path",
            field="output_path",
            message="Output path must be path-like.",
        )
    try:
        return Path(output_path), None
    except TypeError:
        return Path(""), PreprocessingGraphEdgesCsvWriteIssue(
            kind="invalid_output_path",
            field="output_path",
            message="Output path must be path-like.",
        )


def _graph_edges_path_write_issue(
    output_path: Path,
) -> PreprocessingGraphEdgesCsvWriteIssue | None:
    if output_path.is_dir():
        return PreprocessingGraphEdgesCsvWriteIssue(
            kind="output_path_is_directory",
            field="output_path",
            message="Output path is a directory.",
        )
    if not output_path.parent.exists():
        return PreprocessingGraphEdgesCsvWriteIssue(
            kind="parent_directory_missing",
            field="output_path.parent",
            message="Output parent directory does not exist.",
        )
    if not output_path.parent.is_dir():
        return PreprocessingGraphEdgesCsvWriteIssue(
            kind="parent_directory_missing",
            field="output_path.parent",
            message="Output parent path is not a directory.",
        )
    return None


def _coerced_json_input_path(input_path: object) -> Path:
    if input_path is None:
        return Path("")
    if isinstance(input_path, str) and not input_path.strip():
        return Path("")
    if not isinstance(input_path, _GRAPH_CSV_PATH_TYPES):
        return Path("")
    try:
        return Path(input_path)
    except TypeError:
        return Path("")


def _graph_json_output_path(
    output_path: object,
) -> tuple[Path, PreprocessingGraphJsonWriteIssue | None]:
    if output_path is None:
        return Path(""), PreprocessingGraphJsonWriteIssue(
            kind="invalid_output_path",
            field="output_path",
            message="Output path is required.",
        )
    if isinstance(output_path, str) and not output_path.strip():
        return Path(""), PreprocessingGraphJsonWriteIssue(
            kind="invalid_output_path",
            field="output_path",
            message="Output path is required.",
        )
    if not isinstance(output_path, _PATHLIKE_TYPES):
        return Path(""), PreprocessingGraphJsonWriteIssue(
            kind="invalid_output_path",
            field="output_path",
            message="Output path must be path-like.",
        )
    try:
        return Path(output_path), None
    except TypeError:
        return Path(""), PreprocessingGraphJsonWriteIssue(
            kind="invalid_output_path",
            field="output_path",
            message="Output path must be path-like.",
        )


def _graph_json_path_write_issue(
    output_path: Path,
) -> PreprocessingGraphJsonWriteIssue | None:
    if output_path.is_dir():
        return PreprocessingGraphJsonWriteIssue(
            kind="output_path_is_directory",
            field="output_path",
            message="Output path is a directory.",
        )
    if not output_path.parent.exists():
        return PreprocessingGraphJsonWriteIssue(
            kind="parent_directory_missing",
            field="output_path.parent",
            message="Output parent directory does not exist.",
        )
    if not output_path.parent.is_dir():
        return PreprocessingGraphJsonWriteIssue(
            kind="parent_directory_missing",
            field="output_path.parent",
            message="Output parent path is not a directory.",
        )
    return None


def _read_graph_json_payload(
    nodes_path: Path,
    edges_path: Path,
    *,
    node_count: int,
    edge_count: int,
) -> dict[str, object] | PreprocessingGraphJsonWriteIssue:
    nodes_result = _read_graph_json_rows(
        nodes_path,
        columns=NODE_COLUMNS,
        csv_kind="nodes",
    )
    if isinstance(nodes_result, PreprocessingGraphJsonWriteIssue):
        return nodes_result
    edges_result = _read_graph_json_rows(
        edges_path,
        columns=EDGE_COLUMNS,
        csv_kind="edges",
    )
    if isinstance(edges_result, PreprocessingGraphJsonWriteIssue):
        return edges_result

    nodes = [_graph_json_node(row) for row in nodes_result]
    edges = [
        {"source": row["resid_i"], "target": row["resid_j"], **row}
        for row in edges_result
    ]
    return {
        "condition": _graph_json_condition(nodes_result, edges_result),
        "n_nodes": node_count,
        "n_edges": edge_count,
        "directed": False,
        "schema_version": SCHEMA_VERSION,
        "nodes": nodes,
        "edges": edges,
    }


def _read_graph_json_rows(
    path: Path,
    *,
    columns: tuple[str, ...],
    csv_kind: str,
) -> tuple[dict[str, str], ...] | PreprocessingGraphJsonWriteIssue:
    try:
        csv_text = path.read_text(encoding="utf-8")
        reader = csv.DictReader(StringIO(csv_text), strict=True)
        rows = tuple(
            {
                column: value if (value := row.get(column)) is not None else ""
                for column in columns
            }
            for row in reader
        )
    except (OSError, UnicodeError, csv.Error):
        return PreprocessingGraphJsonWriteIssue(
            kind="read_failed",
            field="path",
            csv_kind=csv_kind,
            message="Graph CSV file could not be read for JSON writing.",
        )
    return rows


def _graph_json_node(row: dict[str, str]) -> dict[str, object]:
    x_ca = _optional_json_float(row["x_ca"])
    y_ca = _optional_json_float(row["y_ca"])
    z_ca = _optional_json_float(row["z_ca"])
    return {
        "id": row["resid"],
        **row,
        "x": x_ca,
        "y": y_ca,
        "z": z_ca,
        "x_ca": x_ca,
        "y_ca": y_ca,
        "z_ca": z_ca,
    }


def _optional_json_float(value: str) -> float | None:
    if value.strip() == "":
        return None
    converted = float(value)
    if not math.isfinite(converted):
        return None
    return converted


def _graph_json_condition(
    nodes: tuple[dict[str, str], ...],
    edges: tuple[dict[str, str], ...],
) -> str:
    for row in (*nodes, *edges):
        condition = row["condition"]
        if condition.strip() != "":
            return condition
    return ""


def _write_graph_payload(
    output_path: Path,
    graph: dict[str, object],
) -> PreprocessingGraphJsonWriteIssue | None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as graph_file:
            temporary_path = Path(graph_file.name)
            graph_file.write(_json_dumps(graph, ensure_ascii=False, indent=2))
            graph_file.write("\n")
        temporary_path.replace(output_path)
    except OSError:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        return PreprocessingGraphJsonWriteIssue(
            kind="write_failed",
            field="output_path",
            message="Backend graph JSON file could not be written.",
        )
    return None


def _write_graph_node_rows(
    output_path: Path,
    rows: list[dict[str, str]],
) -> PreprocessingGraphNodesCsvWriteIssue | None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as csv_file:
            temporary_path = Path(csv_file.name)
            writer = csv.DictWriter(
                csv_file,
                fieldnames=NODE_COLUMNS,
                lineterminator="\n",
            )
            writer.writeheader()
            writer.writerows(rows)
        temporary_path.replace(output_path)
    except (OSError, csv.Error):
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        return PreprocessingGraphNodesCsvWriteIssue(
            kind="write_failed",
            field="output_path",
            message="Backend graph nodes CSV file could not be written.",
        )
    return None


def _write_backend_edge_rows(
    output_path: Path,
    rows: list[dict[str, str]],
) -> PreprocessingGraphEdgesCsvWriteIssue | None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as csv_file:
            temporary_path = Path(csv_file.name)
            writer = csv.DictWriter(
                csv_file,
                fieldnames=EDGE_COLUMNS,
                lineterminator="\n",
            )
            writer.writeheader()
            writer.writerows(rows)
        temporary_path.replace(output_path)
    except (OSError, csv.Error):
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        return PreprocessingGraphEdgesCsvWriteIssue(
            kind="write_failed",
            field="output_path",
            message="Backend graph edges CSV file could not be written.",
        )
    return None


def _frame_distances(
    frame_result: PreprocessingContactFrameResult,
    *,
    condition_index: int,
    frame_index: int,
    nodes_by_id: dict[str, PreprocessingGraphNodeMappingRecord],
    coordinates_by_node_id: dict[str, PreprocessingCaCoordinate],
    issues: list[PreprocessingGraphExportMappingIssue],
) -> dict[_AggregateKey, float]:
    frame_distances: dict[_AggregateKey, float] = {}

    for contact in frame_result.contacts:
        source_identity = _source_identity(frame_result, contact)
        target_identity = _target_identity(frame_result, contact)
        source_node = _node_record(
            source_identity,
            coordinates_by_node_id.get(_node_id(source_identity)),
        )
        target_node = _node_record(
            target_identity,
            coordinates_by_node_id.get(_node_id(target_identity)),
        )
        nodes_by_id.setdefault(source_node.node_id, source_node)
        nodes_by_id.setdefault(target_node.node_id, target_node)

        key = _AggregateKey(
            condition_name=frame_result.condition_name,
            source_node_id=source_node.node_id,
            target_node_id=target_node.node_id,
            edge_type=contact.edge_type,
            distance_unit=contact.distance_unit,
            atom_filter=contact.atom_filter,
        )
        previous_distance = frame_distances.get(key)
        if previous_distance is None:
            frame_distances[key] = contact.minimum_distance
            continue

        issues.append(
            PreprocessingGraphExportMappingIssue(
                kind="mapping_failed",
                record_id=frame_result.condition_name,
                field=(
                    f"condition_results[{condition_index}]"
                    f".frame_results[{frame_index}]"
                ),
                message="Duplicate contact pair was present in one frame.",
            )
        )
        frame_distances[key] = min(previous_distance, contact.minimum_distance)

    return frame_distances


def _source_identity(
    frame_result: PreprocessingContactFrameResult,
    contact: PreprocessingContactPairResult,
) -> _ResidueIdentity:
    return _ResidueIdentity(
        condition_name=frame_result.condition_name,
        residue_index=contact.source_residue_index,
        residue_id=_residue_id(contact.source_residue_id, contact.source_residue_index),
        resname=contact.source_resname,
        segid=contact.source_segid,
    )


def _target_identity(
    frame_result: PreprocessingContactFrameResult,
    contact: PreprocessingContactPairResult,
) -> _ResidueIdentity:
    return _ResidueIdentity(
        condition_name=frame_result.condition_name,
        residue_index=contact.target_residue_index,
        residue_id=_residue_id(contact.target_residue_id, contact.target_residue_index),
        resname=contact.target_resname,
        segid=contact.target_segid,
    )


def _ca_coordinates_by_node_id(
    condition_result: PreprocessingConditionContactsResult,
) -> dict[str, PreprocessingCaCoordinate]:
    coordinates: dict[str, PreprocessingCaCoordinate] = {}
    for coordinate in condition_result.representative_ca_coordinates:
        identity = _ResidueIdentity(
            condition_name=condition_result.condition_name,
            residue_index=coordinate.residue_index,
            residue_id=_residue_id(
                coordinate.residue_id,
                coordinate.residue_index,
            ),
            resname=coordinate.resname,
            segid=coordinate.segid,
        )
        coordinates[_node_id(identity)] = coordinate
    return coordinates


def _node_record_from_ca_coordinate(
    condition_name: str,
    coordinate: PreprocessingCaCoordinate,
) -> PreprocessingGraphNodeMappingRecord:
    identity = _ResidueIdentity(
        condition_name=condition_name,
        residue_index=coordinate.residue_index,
        residue_id=_residue_id(coordinate.residue_id, coordinate.residue_index),
        resname=coordinate.resname,
        segid=coordinate.segid,
    )
    return _node_record(identity, coordinate)


def _backbone_edge_pairs(
    condition_result: PreprocessingConditionContactsResult,
    *,
    nodes_by_id: dict[str, PreprocessingGraphNodeMappingRecord],
) -> tuple[_EdgePairKey, ...]:
    if condition_result.options.contact_selection != "protein":
        return ()

    nodes_by_chain: dict[str | None, list[PreprocessingGraphNodeMappingRecord]] = {}
    for node in nodes_by_id.values():
        if (
            node.condition_name == condition_result.condition_name
            and node.x_ca is not None
            and node.y_ca is not None
            and node.z_ca is not None
        ):
            nodes_by_chain.setdefault(node.segid, []).append(node)

    pairs: list[_EdgePairKey] = []
    for chain_nodes in nodes_by_chain.values():
        ordered_nodes = sorted(
            chain_nodes,
            key=lambda node: (node.residue_index, node.node_id),
        )
        for source, target in zip(ordered_nodes, ordered_nodes[1:], strict=False):
            if target.residue_index != source.residue_index + 1:
                continue
            if _ca_distance(source, target) > BACKBONE_MAX_CA_DIST_A:
                continue
            pairs.append(
                _EdgePairKey(
                    condition_name=condition_result.condition_name,
                    source_node_id=source.node_id,
                    target_node_id=target.node_id,
                )
            )
    return tuple(sorted(pairs, key=_backbone_edge_id))


def _ca_distance(
    source: PreprocessingGraphNodeMappingRecord,
    target: PreprocessingGraphNodeMappingRecord,
) -> float:
    if (
        source.x_ca is None
        or source.y_ca is None
        or source.z_ca is None
        or target.x_ca is None
        or target.y_ca is None
        or target.z_ca is None
    ):
        raise ValueError("Backbone distance requires complete Cα coordinates")
    return math.sqrt(
        (target.x_ca - source.x_ca) ** 2
        + (target.y_ca - source.y_ca) ** 2
        + (target.z_ca - source.z_ca) ** 2
    )


def _merge_backbone_edges(
    contact_edges: tuple[PreprocessingGraphEdgeMappingRecord, ...],
    backbone_pairs: tuple[_EdgePairKey, ...],
) -> tuple[PreprocessingGraphEdgeMappingRecord, ...]:
    backbone_by_pair = {
        _canonical_edge_pair(
            pair.condition_name,
            pair.source_node_id,
            pair.target_node_id,
        ): pair
        for pair in backbone_pairs
    }
    merged_edges: list[PreprocessingGraphEdgeMappingRecord] = []

    for edge in contact_edges:
        pair_key = _canonical_edge_pair(
            edge.condition_name,
            edge.source_node_id,
            edge.target_node_id,
        )
        backbone_pair = backbone_by_pair.pop(pair_key, None)
        if backbone_pair is None:
            merged_edges.append(edge)
            continue
        merged_edges.append(
            replace(
                edge,
                all_edge_types=(*edge.all_edge_types, _BACKBONE_EDGE_KIND)
                if edge.all_edge_types is not None
                else (edge.edge_kind, _BACKBONE_EDGE_KIND),
            )
        )

    for pair in backbone_by_pair.values():
        merged_edges.append(
            PreprocessingGraphEdgeMappingRecord(
                edge_id=_backbone_edge_id(pair),
                source_node_id=pair.source_node_id,
                target_node_id=pair.target_node_id,
                condition_name=pair.condition_name,
                edge_kind=_BACKBONE_EDGE_KIND,
            )
        )
    return tuple(sorted(merged_edges, key=lambda edge: edge.edge_id))


def _merge_typed_contact_edges(
    contact_edges: tuple[PreprocessingGraphEdgeMappingRecord, ...],
) -> tuple[PreprocessingGraphEdgeMappingRecord, ...]:
    edges_by_pair: dict[
        tuple[str, str, str],
        list[PreprocessingGraphEdgeMappingRecord],
    ] = {}
    for edge in contact_edges:
        pair_key = _canonical_edge_pair(
            edge.condition_name,
            edge.source_node_id,
            edge.target_node_id,
        )
        edges_by_pair.setdefault(pair_key, []).append(edge)

    merged_edges: list[PreprocessingGraphEdgeMappingRecord] = []
    for pair_edges in edges_by_pair.values():
        primary = min(
            pair_edges,
            key=lambda edge: _edge_type_priority_key(edge.edge_kind),
        )
        merged_edges.append(
            replace(
                primary,
                all_edge_types=tuple(
                    edge.edge_kind for edge in pair_edges
                ),
            )
        )
    return tuple(sorted(merged_edges, key=lambda edge: edge.edge_id))


def _canonical_edge_pair(
    condition_name: str,
    source_node_id: str,
    target_node_id: str,
) -> tuple[str, str, str]:
    source, target = sorted((source_node_id, target_node_id))
    return condition_name, source, target


def _backbone_edge_id(pair: _EdgePairKey) -> str:
    return _join_identifier_parts(
        (
            pair.condition_name,
            pair.source_node_id,
            pair.target_node_id,
            _BACKBONE_EDGE_KIND,
        )
    )


def _node_record(
    identity: _ResidueIdentity,
    coordinate: PreprocessingCaCoordinate | None = None,
) -> PreprocessingGraphNodeMappingRecord:
    return PreprocessingGraphNodeMappingRecord(
        node_id=_node_id(identity),
        condition_name=identity.condition_name,
        residue_index=identity.residue_index,
        residue_id=identity.residue_id,
        resname=identity.resname,
        segid=identity.segid,
        x_ca=coordinate.x_ca if coordinate is not None else None,
        y_ca=coordinate.y_ca if coordinate is not None else None,
        z_ca=coordinate.z_ca if coordinate is not None else None,
    )


def _edge_record(
    key: _AggregateKey,
    distances: list[float],
    total_frame_count: int,
) -> PreprocessingGraphEdgeMappingRecord:
    contact_frame_count = len(distances)
    minimum_distance = min(distances)
    mean_minimum_distance = sum(distances) / contact_frame_count
    return PreprocessingGraphEdgeMappingRecord(
        edge_id=_edge_id(key),
        source_node_id=key.source_node_id,
        target_node_id=key.target_node_id,
        condition_name=key.condition_name,
        edge_kind=key.edge_type,
        all_edge_types=(key.edge_type,),
        contact_frame_count=contact_frame_count,
        total_frame_count=total_frame_count,
        contact_frequency=contact_frame_count / total_frame_count,
        minimum_distance=minimum_distance,
        mean_minimum_distance=mean_minimum_distance,
        distance_unit=key.distance_unit,
        atom_filter=key.atom_filter,
    )


def _node_id(identity: _ResidueIdentity) -> str:
    return _join_identifier_parts(
        (
            identity.condition_name,
            identity.segid,
            identity.residue_index,
            identity.residue_id,
            identity.resname,
        )
    )


def _edge_id(key: _AggregateKey) -> str:
    return _join_identifier_parts(
        (
            key.condition_name,
            key.source_node_id,
            key.target_node_id,
            key.distance_unit,
            key.atom_filter,
        )
    )


def _join_identifier_parts(parts: tuple[object | None, ...]) -> str:
    return _ID_SEPARATOR.join(_identifier_part(part) for part in parts)


def _identifier_part(value: object | None) -> str:
    text = "" if value is None else str(value)
    return text.replace(_ID_ESCAPE, _ID_ESCAPE + _ID_ESCAPE).replace(
        _ID_SEPARATOR,
        _ID_ESCAPE + _ID_SEPARATOR,
    )


def _residue_id(value: int | str | None, residue_index: int) -> str:
    return str(residue_index if value is None else value)


def _normalized_record_edge_types(
    all_edge_types: object,
    *,
    edge_kind: str,
) -> tuple[str, ...]:
    if all_edge_types is None:
        return (edge_kind,)
    if isinstance(all_edge_types, str) or not isinstance(all_edge_types, tuple):
        raise ValueError("all_edge_types must be a tuple of edge type strings")
    if not all_edge_types:
        raise ValueError("all_edge_types must contain at least one edge type")

    normalized_edge_types: list[str] = []
    seen_edge_types: set[str] = set()
    for index, edge_type in enumerate(all_edge_types):
        normalized_edge_type = _edge_type_string(
            edge_type,
            f"all_edge_types[{index}]",
        )
        if normalized_edge_type in seen_edge_types:
            continue
        normalized_edge_types.append(normalized_edge_type)
        seen_edge_types.add(normalized_edge_type)

    return tuple(sorted(normalized_edge_types, key=_edge_type_priority_key))


def _edge_type_priority_key(edge_type: str) -> tuple[int, str]:
    return (
        _EDGE_TYPE_PRIORITY_INDEX.get(edge_type, len(EDGE_TYPE_PRIORITY)),
        edge_type,
    )


def _edge_type_string(value: object, field_name: str) -> str:
    edge_type = _non_empty_string(value, field_name)
    if _EDGE_TYPE_SEPARATOR in edge_type:
        raise ValueError(f"{field_name} must not contain {_EDGE_TYPE_SEPARATOR!r}")
    return _EDGE_TYPE_ALIASES.get(edge_type, edge_type)


def _non_empty_string(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a non-empty string")
    stripped = value.strip()
    if not stripped:
        raise ValueError(f"{field_name} must be a non-empty string")
    return stripped


def _optional_non_empty_string(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _non_empty_string(value, field_name)


def _require_optional_string(value: object, field_name: str) -> None:
    if value is not None and not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string or None")


def _require_non_negative_int(value: object, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative int")


def _require_optional_non_negative_int(
    value: object,
    field_name: str,
) -> None:
    if value is not None:
        _require_non_negative_int(value, field_name)


def _require_optional_non_negative_finite_number(
    value: object,
    field_name: str,
) -> None:
    if value is None:
        return
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(
            f"{field_name} must be a finite non-negative number"
        )


def _require_optional_finite_number(
    value: object,
    field_name: str,
) -> None:
    if value is None:
        return
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ValueError(f"{field_name} must be a finite number or None")


def _duplicates(values: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    duplicates: list[str] = []
    duplicate_set: set[str] = set()
    for value in values:
        if value in seen and value not in duplicate_set:
            duplicates.append(value)
            duplicate_set.add(value)
        seen.add(value)
    return tuple(sorted(duplicates))


globals()[_EDGES_CSV_PUBLIC_WRITER_NAME] = _write_backend_edges_csv

__all__ = [
    "PreprocessingGraphCsvValidationIssue",
    "PreprocessingGraphCsvValidationResult",
    "PreprocessingGraphEdgeMappingRecord",
    "PreprocessingGraphEdgesCsvWriteIssue",
    "PreprocessingGraphEdgesCsvWriteResult",
    "PreprocessingGraphExportBundleArtifact",
    "PreprocessingGraphExportBundleIssue",
    "PreprocessingGraphExportBundleResult",
    "PreprocessingGraphExportMappingIssue",
    "PreprocessingGraphExportMappingResult",
    "PreprocessingGraphJsonWriteIssue",
    "PreprocessingGraphJsonWriteResult",
    "PreprocessingGraphNodesCsvWriteIssue",
    "PreprocessingGraphNodesCsvWriteResult",
    "PreprocessingGraphNodeMappingRecord",
    "build_preprocessing_graph_export_bundle",
    "build_preprocessing_graph_export_mapping",
    "validate_preprocessing_graph_csvs",
    _EDGES_CSV_PUBLIC_WRITER_NAME,
    "write_preprocessing_graph_json",
    "write_preprocessing_graph_nodes_csv",
]
