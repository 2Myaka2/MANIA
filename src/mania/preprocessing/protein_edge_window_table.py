"""Pure Stage 28.C source-indexed, canonical-ready Dataset table contract.

This candidate requires Stage 30 canonical mapping before Dataset publication.
Accepted Stage 28.B metrics are copied without episode recalculation.
"""

from dataclasses import asdict, dataclass, field
from decimal import Context, Decimal, localcontext
from math import isfinite
from typing import get_args

from mania.dataset_identity import DatasetEngine
from mania.preprocessing.physical_time_execution import (
    PreprocessingConditionTemporalExecution,
)
from mania.preprocessing.protein_edge_windows import (
    ProteinEdgeWindowAggregation,
    ProteinEdgeWindowAggregationError,
    ProteinEdgeWindowMetric,
)

DATASET_PROTEIN_EDGE_WINDOW_TABLE_SCHEMA_VERSION = (
    "mania.dataset_protein_edges_by_window_source.v0.1"
)
DATASET_PROTEIN_EDGE_WINDOW_TABLE_KIND = "mania_dataset_protein_edges_by_window_source"
DATASET_PROTEIN_EDGE_WINDOW_CSV_FILENAME = "protein_edges_by_window_source.csv"


class DatasetProteinEdgeWindowTableError(ValueError):
    """Invalid Dataset table identity, retained execution, or edge row."""


def _require_text(value: object, name: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise DatasetProteinEdgeWindowTableError(
            f"{name} must be a non-empty stripped string"
        )


def _require_index(value: object, name: str) -> None:
    if type(value) is not int or value < 0:
        raise DatasetProteinEdgeWindowTableError(
            f"{name} must be a non-negative integer"
        )


def _number(value: object, name: str) -> float:
    if not isinstance(value, bool) and isinstance(value, (int, float)):
        try:
            if isfinite(value) and value >= 0:
                return float(value)
        except OverflowError:
            pass
    raise DatasetProteinEdgeWindowTableError(f"{name} must be finite and non-negative")


@dataclass(frozen=True)
class DatasetProteinEdgeWindowTableInput:
    """Explicit execution/aggregation pair; scientific condition is not a key."""

    temporal_execution: PreprocessingConditionTemporalExecution
    aggregation: ProteinEdgeWindowAggregation

    def __post_init__(self) -> None:
        for value, model, name in (
            (
                self.temporal_execution,
                PreprocessingConditionTemporalExecution,
                "temporal_execution",
            ),
            (self.aggregation, ProteinEdgeWindowAggregation, "aggregation"),
        ):
            if type(value) is not model:
                raise DatasetProteinEdgeWindowTableError(
                    f"{name} must be exact {model.__name__}"
                )
        execution, aggregation = self.temporal_execution, self.aggregation
        if aggregation.execution_condition != execution.execution_condition:
            raise DatasetProteinEdgeWindowTableError("execution conditions must match")
        if any(
            status not in ("complete", "partial")
            for status in (
                aggregation.status,
                execution.sampling_plan.status,
                execution.window_plan.status,
            )
        ):
            raise DatasetProteinEdgeWindowTableError(
                "scientific state must not be failed"
            )
        windows = execution.window_plan.windows
        if aggregation.window_count != len(windows) or len(aggregation.windows) != len(
            windows
        ):
            raise DatasetProteinEdgeWindowTableError(
                "aggregation window count must match"
            )
        for statistics, window in zip(aggregation.windows, windows, strict=True):
            for name, temporal_name in (
                ("window_id", "window_id"),
                ("window_index", "window_index"),
                ("requested_sample_count", "requested_sample_count"),
                ("resolved_frame_count", "sampled_frame_count"),
                ("missing_sample_count", "missing_sample_count"),
                ("coverage_fraction", "coverage_fraction"),
            ):
                if getattr(statistics, name) != getattr(window, temporal_name):
                    raise DatasetProteinEdgeWindowTableError(
                        f"aggregation window {name} must match temporal execution"
                    )
            for edge in statistics.edges:
                if (edge.window_id, edge.window_index) != (
                    window.window_id,
                    window.window_index,
                ):
                    raise DatasetProteinEdgeWindowTableError(
                        "edge must belong to its exact parent window"
                    )
                if edge.n_resolved_frames_in_window != window.sampled_frame_count:
                    raise DatasetProteinEdgeWindowTableError(
                        "edge denominator must match temporal resolved frame count"
                    )


@dataclass(frozen=True)
class DatasetProteinEdgeWindowRow:
    """One observed edge, retaining source references for a future mapping join."""

    dataset_id: str
    system_id: str
    trajectory_id: str
    variant_id: str
    engine: str
    condition: str | None
    replica_id: str
    disulfide_state: str | None
    window_id: str
    window_index: int
    requested_window_start_ns: float
    requested_window_end_ns: float
    right_endpoint_inclusive: bool
    effective_window_start_ns: float
    effective_window_end_ns: float
    requested_sample_count: int
    resolved_frame_count: int
    missing_sample_count: int
    coverage_fraction: float
    source_residue_index: int
    target_residue_index: int
    source_chain_id: str | None
    target_chain_id: str | None
    source_resid: str | None
    target_resid: str | None
    source_resname: str
    target_resname: str
    edge_type: str
    n_contact_frames: int
    occupancy: float
    n_contact_episodes: int
    mean_episode_length_ns: float
    max_episode_length_ns: float
    edge_weight: float

    def __post_init__(self) -> None:
        for name in (
            "dataset_id",
            "system_id",
            "trajectory_id",
            "variant_id",
            "engine",
            "replica_id",
            "window_id",
            "source_resname",
            "target_resname",
            "edge_type",
        ):
            _require_text(getattr(self, name), name)
        if self.engine not in get_args(DatasetEngine):
            raise DatasetProteinEdgeWindowTableError(
                "engine must be an accepted normalized Dataset engine"
            )
        for name in (
            "condition",
            "disulfide_state",
            "source_chain_id",
            "target_chain_id",
            "source_resid",
            "target_resid",
        ):
            value = getattr(self, name)
            if value is not None:
                _require_text(value, name)
        for name in (
            "window_index",
            "requested_sample_count",
            "resolved_frame_count",
            "missing_sample_count",
            "source_residue_index",
            "target_residue_index",
            "n_contact_frames",
            "n_contact_episodes",
        ):
            _require_index(getattr(self, name), name)
        if type(self.right_endpoint_inclusive) is not bool:
            raise DatasetProteinEdgeWindowTableError(
                "right_endpoint_inclusive must be a bool"
            )
        for name in (
            "requested_window_start_ns",
            "requested_window_end_ns",
            "effective_window_start_ns",
            "effective_window_end_ns",
            "coverage_fraction",
            "occupancy",
            "mean_episode_length_ns",
            "max_episode_length_ns",
            "edge_weight",
        ):
            object.__setattr__(self, name, _number(getattr(self, name), name))
        if self.requested_window_end_ns <= self.requested_window_start_ns:
            raise DatasetProteinEdgeWindowTableError(
                "requested window end must exceed start"
            )
        if self.effective_window_end_ns < self.effective_window_start_ns:
            raise DatasetProteinEdgeWindowTableError(
                "effective window end must be at least start"
            )
        if self.requested_sample_count <= 0 or self.resolved_frame_count <= 0:
            raise DatasetProteinEdgeWindowTableError(
                "requested and resolved counts must be positive for an observed edge"
            )
        if self.requested_sample_count != (
            self.resolved_frame_count + self.missing_sample_count
        ):
            raise DatasetProteinEdgeWindowTableError(
                "requested count must equal resolved plus missing counts"
            )
        if not 0 < self.coverage_fraction <= 1 or self.coverage_fraction != (
            self.resolved_frame_count / self.requested_sample_count
        ):
            raise DatasetProteinEdgeWindowTableError(
                "coverage must equal resolved/requested count"
            )
        # Delegate metric validation to 28.B; no second scientific formula or
        # episode engine is introduced, and no returned metric replaces input.
        try:
            ProteinEdgeWindowMetric(
                window_id=self.window_id,
                window_index=self.window_index,
                source_residue_index=self.source_residue_index,
                target_residue_index=self.target_residue_index,
                source_residue_id=self.source_resid,
                target_residue_id=self.target_resid,
                source_resname=self.source_resname,
                target_resname=self.target_resname,
                source_segid=self.source_chain_id,
                target_segid=self.target_chain_id,
                edge_type=self.edge_type,
                n_resolved_frames_in_window=self.resolved_frame_count,
                n_contact_frames=self.n_contact_frames,
                occupancy=self.occupancy,
                n_contact_episodes=self.n_contact_episodes,
                mean_episode_length_ns=self.mean_episode_length_ns,
                max_episode_length_ns=self.max_episode_length_ns,
                edge_weight=self.edge_weight,
            )
        except ProteinEdgeWindowAggregationError as exc:
            raise DatasetProteinEdgeWindowTableError(str(exc)) from None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _replica_key(row: DatasetProteinEdgeWindowRow) -> tuple[str, str, str, str]:
    return row.dataset_id, row.system_id, row.trajectory_id, row.replica_id


def _row_identity(
    row: DatasetProteinEdgeWindowRow,
) -> tuple[str, str, str, str, str, int, int, str]:
    return (
        *_replica_key(row),
        row.window_id,
        row.source_residue_index,
        row.target_residue_index,
        row.edge_type,
    )


def _row_order(
    row: DatasetProteinEdgeWindowRow,
) -> tuple[str, str, str, str, int, str, int, int]:
    return (
        *_replica_key(row),
        row.window_index,
        row.edge_type,
        row.source_residue_index,
        row.target_residue_index,
    )


@dataclass(frozen=True)
class DatasetProteinEdgeWindowTable:
    """Deterministically ordered sparse table; an empty table is valid."""

    rows: tuple[DatasetProteinEdgeWindowRow, ...]
    schema_version: str = field(
        default=DATASET_PROTEIN_EDGE_WINDOW_TABLE_SCHEMA_VERSION,
        init=False,
    )
    kind: str = field(default=DATASET_PROTEIN_EDGE_WINDOW_TABLE_KIND, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.rows, tuple) or any(
            type(row) is not DatasetProteinEdgeWindowRow for row in self.rows
        ):
            raise DatasetProteinEdgeWindowTableError(
                "rows must be a tuple of exact DatasetProteinEdgeWindowRow records"
            )
        identities = tuple(_row_identity(row) for row in self.rows)
        if len(set(identities)) != len(identities):
            raise DatasetProteinEdgeWindowTableError("row identities must be unique")
        order = tuple(_row_order(row) for row in self.rows)
        if order != tuple(sorted(order)):
            raise DatasetProteinEdgeWindowTableError(
                "rows must follow deterministic Dataset/window/edge order"
            )

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "row_count": self.row_count,
            "rows": [row.to_dict() for row in self.rows],
        }


def _effective_ns(value: float | None) -> float:
    if value is None:
        raise DatasetProteinEdgeWindowTableError(
            "observed edges require effective selected-time bounds"
        )
    # Isolate precision/rounding/traps from the caller; divide the retained
    # actual time, including accepted representation noise, then convert once.
    with localcontext(Context(prec=28)):
        return float(Decimal(str(value)) / Decimal("1000"))


def build_dataset_protein_edge_window_table(
    inputs: tuple[DatasetProteinEdgeWindowTableInput, ...],
) -> DatasetProteinEdgeWindowTable:
    """Copy authoritative Dataset identity, temporal evidence, and 28.B metrics."""
    if not isinstance(inputs, tuple) or any(
        type(item) is not DatasetProteinEdgeWindowTableInput for item in inputs
    ):
        raise DatasetProteinEdgeWindowTableError(
            "inputs must be a tuple of exact DatasetProteinEdgeWindowTableInput records"
        )
    keys = tuple(
        item.temporal_execution.dataset_spec.identity.replica_key for item in inputs
    )
    if len(set(keys)) != len(keys):
        raise DatasetProteinEdgeWindowTableError(
            "input Dataset replica keys must be unique"
        )
    rows = []
    for item in inputs:
        execution = item.temporal_execution
        identity = execution.dataset_spec.identity
        for window, statistics in zip(
            execution.window_plan.windows,
            item.aggregation.windows,
            strict=True,
        ):
            for edge in statistics.edges:
                rows.append(
                    DatasetProteinEdgeWindowRow(
                        dataset_id=identity.dataset_id,
                        system_id=identity.system_id,
                        trajectory_id=identity.trajectory_id,
                        variant_id=identity.variant_id,
                        engine=identity.engine,
                        condition=identity.condition,
                        replica_id=identity.replica_id,
                        disulfide_state=identity.disulfide_state,
                        window_id=window.window_id,
                        window_index=window.window_index,
                        requested_window_start_ns=window.requested_start_ns,
                        requested_window_end_ns=window.requested_end_ns,
                        right_endpoint_inclusive=window.right_endpoint_inclusive,
                        effective_window_start_ns=_effective_ns(
                            window.effective_start_time_ps
                        ),
                        effective_window_end_ns=_effective_ns(
                            window.effective_end_time_ps
                        ),
                        requested_sample_count=statistics.requested_sample_count,
                        resolved_frame_count=statistics.resolved_frame_count,
                        missing_sample_count=statistics.missing_sample_count,
                        coverage_fraction=statistics.coverage_fraction,
                        source_residue_index=edge.source_residue_index,
                        target_residue_index=edge.target_residue_index,
                        source_chain_id=edge.source_segid,
                        target_chain_id=edge.target_segid,
                        source_resid=(
                            None
                            if edge.source_residue_id is None
                            else str(edge.source_residue_id)
                        ),
                        target_resid=(
                            None
                            if edge.target_residue_id is None
                            else str(edge.target_residue_id)
                        ),
                        source_resname=edge.source_resname,
                        target_resname=edge.target_resname,
                        edge_type=edge.edge_type,
                        n_contact_frames=edge.n_contact_frames,
                        occupancy=edge.occupancy,
                        n_contact_episodes=edge.n_contact_episodes,
                        mean_episode_length_ns=edge.mean_episode_length_ns,
                        max_episode_length_ns=edge.max_episode_length_ns,
                        edge_weight=edge.edge_weight,
                    )
                )
    return DatasetProteinEdgeWindowTable(tuple(sorted(rows, key=_row_order)))


__all__ = [
    "DATASET_PROTEIN_EDGE_WINDOW_CSV_FILENAME",
    "DATASET_PROTEIN_EDGE_WINDOW_TABLE_KIND",
    "DATASET_PROTEIN_EDGE_WINDOW_TABLE_SCHEMA_VERSION",
    "DatasetProteinEdgeWindowRow",
    "DatasetProteinEdgeWindowTable",
    "DatasetProteinEdgeWindowTableError",
    "DatasetProteinEdgeWindowTableInput",
    "build_dataset_protein_edge_window_table",
]
