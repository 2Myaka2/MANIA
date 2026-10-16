"""Conservative cross-condition comparison of accepted static RIN metrics."""

from __future__ import annotations

import csv
import itertools
import json
import math
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal, Self, cast

from pydantic import Field, model_validator

from mania.analysis.static_rin_metrics import STATIC_RIN_METRICS_COLUMNS
from mania.canonical_reference import (
    AuthorityBinding,
    InputIdentity,
    ReferenceIdentity,
    ReferenceResidueKey,
    Text,
    _StrictModel,
)
from mania.canonical_residue_mapping import ResidueMappingTable

STATIC_RIN_COMPARISON_COLUMNS = (
    "comparison_id",
    "scope",
    "condition_a",
    "condition_b",
    "entity_key",
    "node_id_a",
    "node_id_b",
    "residue_index",
    "resid",
    "resname",
    "segment_id",
    "metric",
    "value_a",
    "value_b",
    "delta",
    "status",
    "source_artifact_a",
    "source_artifact_b",
    "notes",
)

STATIC_RIN_STATS_COLUMNS = (
    "comparison_id",
    "scope",
    "condition_a",
    "condition_b",
    "metric",
    "method",
    "n_a",
    "n_b",
    "matched_count",
    "unmatched_condition_a_count",
    "unmatched_condition_b_count",
    "missing_metric_count",
    "statistic",
    "effect_size",
    "ci_low",
    "ci_high",
    "p_value",
    "p_adjusted",
    "correction",
    "status",
    "notes",
)

STATIC_RIN_COMPARISON_METRICS = STATIC_RIN_METRICS_COLUMNS[6:]
STATIC_RIN_COMPARISON_METHODS = (
    "paired_delta_summary",
    "cohens_dz",
)
STATIC_RIN_DEFERRED_COMPARISON_SCOPES = (
    "edge_metrics",
    "communities",
    "region_enrichment",
)

COMPARISON_STATUS_COMPUTED = "computed"
COMPARISON_STATUS_SKIPPED_MISSING_METRIC = "skipped_missing_metric"
COMPARISON_STATUS_SKIPPED_UNMATCHED_CONDITION_A = "skipped_unmatched_condition_a"
COMPARISON_STATUS_SKIPPED_UNMATCHED_CONDITION_B = "skipped_unmatched_condition_b"
COMPARISON_STATUS_SKIPPED_IDENTITY_CONFLICT = "skipped_identity_conflict"
COMPARISON_STATUS_SKIPPED_INSUFFICIENT_DATA = "skipped_insufficient_data"
COMPARISON_STATUS_SKIPPED_UNDEFINED_VARIANCE = "skipped_undefined_variance"
COMPARISON_STATUS_SKIPPED_UNSUPPORTED_SCOPE = "skipped_unsupported_scope"


class StaticRinComparisonError(ValueError):
    """Raised when accepted Stage 21.B artifacts cannot be compared."""


@dataclass(frozen=True)
class StaticRinComparisonRow:
    """One entity-and-metric comparison row."""

    comparison_id: str
    scope: str
    condition_a: str
    condition_b: str
    entity_key: str
    node_id_a: str | None
    node_id_b: str | None
    residue_index: int
    resid: str | None
    resname: str | None
    segment_id: str | None
    metric: str
    value_a: float | None
    value_b: float | None
    delta: float | None
    status: str
    source_artifact_a: str
    source_artifact_b: str
    notes: str

    def to_dict(self) -> dict[str, object]:
        """Return one CSV-ready comparison row."""
        return {
            column: getattr(self, column) for column in STATIC_RIN_COMPARISON_COLUMNS
        }


@dataclass(frozen=True)
class StaticRinStatsRow:
    """One method-level statistical result or explicit skipped status."""

    comparison_id: str
    scope: str
    condition_a: str
    condition_b: str
    metric: str
    method: str
    n_a: int
    n_b: int
    matched_count: int
    unmatched_condition_a_count: int
    unmatched_condition_b_count: int
    missing_metric_count: int
    statistic: float | None
    effect_size: float | None
    ci_low: float | None
    ci_high: float | None
    p_value: float | None
    p_adjusted: float | None
    correction: str
    status: str
    notes: str

    def to_dict(self) -> dict[str, object]:
        """Return one CSV-ready statistics row."""
        return {column: getattr(self, column) for column in STATIC_RIN_STATS_COLUMNS}


@dataclass(frozen=True)
class StaticRinComparison:
    """Deterministic Stage 21.E comparison and method rows."""

    conditions: tuple[str, ...]
    comparison_rows: tuple[StaticRinComparisonRow, ...]
    stats_rows: tuple[StaticRinStatsRow, ...]


@dataclass(frozen=True)
class StaticRinComparisonArtifacts:
    """Paths to the two root-level Stage 21.E artifacts."""

    comparison_csv: Path
    stats_csv: Path


@dataclass(frozen=True)
class _NodeIdentity:
    residue_index: int
    resid: str
    resname: str
    segment_id: str | None

    @property
    def entity_key(self) -> str:
        return json.dumps(
            [self.residue_index, self.resid, self.resname, self.segment_id],
            ensure_ascii=False,
            separators=(",", ":"),
        )


@dataclass(frozen=True)
class _CentralityRow:
    condition: str
    node_id: str
    identity: _NodeIdentity
    metrics: Mapping[str, float | None]


@dataclass(frozen=True)
class _CentralityArtifact:
    condition: str
    source_name: str
    by_residue_index: Mapping[int, _CentralityRow]


@dataclass(frozen=True)
class _StatsContext:
    comparison_id: str
    condition_a: str
    condition_b: str
    metric: str
    n_a: int
    n_b: int
    matched_count: int
    unmatched_condition_a_count: int
    unmatched_condition_b_count: int
    missing_metric_count: int


def compare_static_rin_metrics_from_artifacts(
    centrality_csvs: Sequence[str | Path],
) -> StaticRinComparison:
    """Compare every lexical condition pair from accepted Stage 21.B CSVs."""
    if isinstance(centrality_csvs, (str, bytes)):
        raise TypeError("centrality_csvs must be a sequence of paths")
    artifacts = tuple(_load_centrality_artifact(Path(path)) for path in centrality_csvs)
    if len(artifacts) < 2:
        raise StaticRinComparisonError(
            "at least two Stage 21.B centrality artifacts are required"
        )
    by_condition: dict[str, _CentralityArtifact] = {}
    for artifact in artifacts:
        if artifact.condition in by_condition:
            raise StaticRinComparisonError(
                f"duplicate centrality condition: {artifact.condition}"
            )
        by_condition[artifact.condition] = artifact

    conditions = tuple(sorted(by_condition))
    comparisons: list[StaticRinComparisonRow] = []
    stats: list[StaticRinStatsRow] = []
    for condition_a, condition_b in itertools.combinations(conditions, 2):
        pair_comparisons, pair_stats = _compare_pair(
            by_condition[condition_a], by_condition[condition_b]
        )
        comparisons.extend(pair_comparisons)
        stats.extend(pair_stats)
    return StaticRinComparison(
        conditions=conditions,
        comparison_rows=tuple(comparisons),
        stats_rows=tuple(stats),
    )


def write_static_rin_comparison_artifacts(
    comparison: StaticRinComparison,
    output_dir: str | Path,
) -> StaticRinComparisonArtifacts:
    """Write deterministic root-level ``comparison.csv`` and ``stats.csv``."""
    if not isinstance(comparison, StaticRinComparison):
        raise TypeError("comparison must be a StaticRinComparison")
    directory = Path(output_dir)
    if directory.exists() and not directory.is_dir():
        raise StaticRinComparisonError(
            "static RIN comparison output is not a directory"
        )
    comparison_path = directory / "comparison.csv"
    stats_path = directory / "stats.csv"
    _write_csv(
        comparison_path,
        STATIC_RIN_COMPARISON_COLUMNS,
        tuple(row.to_dict() for row in comparison.comparison_rows),
    )
    _write_csv(
        stats_path,
        STATIC_RIN_STATS_COLUMNS,
        tuple(row.to_dict() for row in comparison.stats_rows),
    )
    return StaticRinComparisonArtifacts(comparison_path, stats_path)


def _compare_pair(
    artifact_a: _CentralityArtifact,
    artifact_b: _CentralityArtifact,
) -> tuple[list[StaticRinComparisonRow], list[StaticRinStatsRow]]:
    condition_a = artifact_a.condition
    condition_b = artifact_b.condition
    comparison_id = f"node_metrics:{condition_a}__{condition_b}"
    indexes_a = set(artifact_a.by_residue_index)
    indexes_b = set(artifact_b.by_residue_index)
    shared_indexes = indexes_a & indexes_b
    matched_indexes = tuple(
        sorted(
            index
            for index in shared_indexes
            if (
                artifact_a.by_residue_index[index].identity
                == artifact_b.by_residue_index[index].identity
            )
        )
    )
    conflict_indexes = tuple(sorted(shared_indexes - set(matched_indexes)))
    only_a_indexes = tuple(sorted(indexes_a - indexes_b))
    only_b_indexes = tuple(sorted(indexes_b - indexes_a))
    unmatched_a_count = len(only_b_indexes) + len(conflict_indexes)
    unmatched_b_count = len(only_a_indexes) + len(conflict_indexes)

    comparison_rows: list[StaticRinComparisonRow] = []
    for index in sorted(indexes_a | indexes_b):
        row_a = artifact_a.by_residue_index.get(index)
        row_b = artifact_b.by_residue_index.get(index)
        if index in conflict_indexes:
            assert row_a is not None and row_b is not None
            comparison_rows.extend(
                _identity_conflict_rows(
                    comparison_id, artifact_a, artifact_b, row_a, row_b
                )
            )
        elif row_a is None:
            assert row_b is not None
            comparison_rows.extend(
                _unmatched_rows(
                    comparison_id,
                    artifact_a,
                    artifact_b,
                    row_b,
                    missing_condition="a",
                )
            )
        elif row_b is None:
            comparison_rows.extend(
                _unmatched_rows(
                    comparison_id,
                    artifact_a,
                    artifact_b,
                    row_a,
                    missing_condition="b",
                )
            )
        else:
            comparison_rows.extend(
                _matched_rows(comparison_id, artifact_a, artifact_b, row_a, row_b)
            )

    stats_rows = _pair_stats_rows(
        comparison_id=comparison_id,
        artifact_a=artifact_a,
        artifact_b=artifact_b,
        matched_indexes=matched_indexes,
        conflict_count=len(conflict_indexes),
        unmatched_a_count=unmatched_a_count,
        unmatched_b_count=unmatched_b_count,
    )
    return comparison_rows, stats_rows


def _matched_rows(
    comparison_id: str,
    artifact_a: _CentralityArtifact,
    artifact_b: _CentralityArtifact,
    row_a: _CentralityRow,
    row_b: _CentralityRow,
) -> list[StaticRinComparisonRow]:
    identity = row_a.identity
    rows: list[StaticRinComparisonRow] = []
    for metric in STATIC_RIN_COMPARISON_METRICS:
        value_a = row_a.metrics[metric]
        value_b = row_b.metrics[metric]
        if value_a is None or value_b is None:
            status = COMPARISON_STATUS_SKIPPED_MISSING_METRIC
            delta = None
            notes = "At least one accepted Stage 21.B metric value is missing."
        else:
            status = COMPARISON_STATUS_COMPUTED
            delta = value_b - value_a
            notes = "delta = value_b - value_a for one exact residue identity match."
        rows.append(
            StaticRinComparisonRow(
                comparison_id=comparison_id,
                scope="node_metrics",
                condition_a=artifact_a.condition,
                condition_b=artifact_b.condition,
                entity_key=identity.entity_key,
                node_id_a=row_a.node_id,
                node_id_b=row_b.node_id,
                residue_index=identity.residue_index,
                resid=identity.resid,
                resname=identity.resname,
                segment_id=identity.segment_id,
                metric=metric,
                value_a=value_a,
                value_b=value_b,
                delta=delta,
                status=status,
                source_artifact_a=artifact_a.source_name,
                source_artifact_b=artifact_b.source_name,
                notes=notes,
            )
        )
    return rows


def _unmatched_rows(
    comparison_id: str,
    artifact_a: _CentralityArtifact,
    artifact_b: _CentralityArtifact,
    row: _CentralityRow,
    *,
    missing_condition: str,
) -> list[StaticRinComparisonRow]:
    identity = row.identity
    missing_a = missing_condition == "a"
    status = (
        COMPARISON_STATUS_SKIPPED_UNMATCHED_CONDITION_A
        if missing_a
        else COMPARISON_STATUS_SKIPPED_UNMATCHED_CONDITION_B
    )
    return [
        StaticRinComparisonRow(
            comparison_id=comparison_id,
            scope="node_metrics",
            condition_a=artifact_a.condition,
            condition_b=artifact_b.condition,
            entity_key=identity.entity_key,
            node_id_a=None if missing_a else row.node_id,
            node_id_b=row.node_id if missing_a else None,
            residue_index=identity.residue_index,
            resid=identity.resid,
            resname=identity.resname,
            segment_id=identity.segment_id,
            metric=metric,
            value_a=None if missing_a else row.metrics[metric],
            value_b=row.metrics[metric] if missing_a else None,
            delta=None,
            status=status,
            source_artifact_a=artifact_a.source_name,
            source_artifact_b=artifact_b.source_name,
            notes=(
                "Stable residue identity is absent from condition_a."
                if missing_a
                else "Stable residue identity is absent from condition_b."
            ),
        )
        for metric in STATIC_RIN_COMPARISON_METRICS
    ]


def _identity_conflict_rows(
    comparison_id: str,
    artifact_a: _CentralityArtifact,
    artifact_b: _CentralityArtifact,
    row_a: _CentralityRow,
    row_b: _CentralityRow,
) -> list[StaticRinComparisonRow]:
    index = row_a.identity.residue_index
    return [
        StaticRinComparisonRow(
            comparison_id=comparison_id,
            scope="node_metrics",
            condition_a=artifact_a.condition,
            condition_b=artifact_b.condition,
            entity_key=f"residue_index:{index}:identity_conflict",
            node_id_a=row_a.node_id,
            node_id_b=row_b.node_id,
            residue_index=index,
            resid=None,
            resname=None,
            segment_id=None,
            metric=metric,
            value_a=row_a.metrics[metric],
            value_b=row_b.metrics[metric],
            delta=None,
            status=COMPARISON_STATUS_SKIPPED_IDENTITY_CONFLICT,
            source_artifact_a=artifact_a.source_name,
            source_artifact_b=artifact_b.source_name,
            notes=(
                "The shared residue_index has conflicting resid, resname, or "
                "segment_id identity; values are not compared."
            ),
        )
        for metric in STATIC_RIN_COMPARISON_METRICS
    ]


def _pair_stats_rows(
    *,
    comparison_id: str,
    artifact_a: _CentralityArtifact,
    artifact_b: _CentralityArtifact,
    matched_indexes: Sequence[int],
    conflict_count: int,
    unmatched_a_count: int,
    unmatched_b_count: int,
) -> list[StaticRinStatsRow]:
    rows: list[StaticRinStatsRow] = []
    for metric in STATIC_RIN_COMPARISON_METRICS:
        values_a = [
            artifact_a.by_residue_index[index].metrics[metric]
            for index in matched_indexes
        ]
        values_b = [
            artifact_b.by_residue_index[index].metrics[metric]
            for index in matched_indexes
        ]
        complete_pairs = tuple(
            (value_a, value_b)
            for value_a, value_b in zip(values_a, values_b, strict=True)
            if value_a is not None and value_b is not None
        )
        deltas = tuple(value_b - value_a for value_a, value_b in complete_pairs)
        common = _StatsContext(
            comparison_id=comparison_id,
            condition_a=artifact_a.condition,
            condition_b=artifact_b.condition,
            metric=metric,
            n_a=sum(value is not None for value in values_a),
            n_b=sum(value is not None for value in values_b),
            matched_count=len(matched_indexes),
            unmatched_condition_a_count=unmatched_a_count,
            unmatched_condition_b_count=unmatched_b_count,
            missing_metric_count=len(matched_indexes) - len(complete_pairs),
        )
        rows.append(_paired_delta_stats_row(common, deltas, conflict_count))
        rows.append(_cohens_dz_stats_row(common, deltas, conflict_count))

    for scope in STATIC_RIN_DEFERRED_COMPARISON_SCOPES:
        rows.append(
            StaticRinStatsRow(
                comparison_id=comparison_id,
                scope=scope,
                condition_a=artifact_a.condition,
                condition_b=artifact_b.condition,
                metric="not_applicable",
                method="not_implemented",
                n_a=0,
                n_b=0,
                matched_count=0,
                unmatched_condition_a_count=0,
                unmatched_condition_b_count=0,
                missing_metric_count=0,
                statistic=None,
                effect_size=None,
                ci_low=None,
                ci_high=None,
                p_value=None,
                p_adjusted=None,
                correction="none",
                status=COMPARISON_STATUS_SKIPPED_UNSUPPORTED_SCOPE,
                notes=_deferred_scope_note(scope),
            )
        )
    return rows


def _paired_delta_stats_row(
    common: _StatsContext,
    deltas: Sequence[float],
    conflict_count: int,
) -> StaticRinStatsRow:
    statistic: float | None = None
    if conflict_count:
        status = COMPARISON_STATUS_SKIPPED_IDENTITY_CONFLICT
        notes = _conflict_stats_note(conflict_count)
    elif not deltas:
        status = COMPARISON_STATUS_SKIPPED_INSUFFICIENT_DATA
        notes = "At least one complete exact-identity metric pair is required."
    else:
        status = COMPARISON_STATUS_COMPUTED
        statistic = math.fsum(deltas) / len(deltas)
        notes = (
            "Arithmetic mean of paired deltas (value_b - value_a); missing "
            "metric pairs are excluded and counted."
        )
    return StaticRinStatsRow(
        comparison_id=common.comparison_id,
        scope="node_metrics",
        condition_a=common.condition_a,
        condition_b=common.condition_b,
        metric=common.metric,
        method="paired_delta_summary",
        n_a=common.n_a,
        n_b=common.n_b,
        matched_count=common.matched_count,
        unmatched_condition_a_count=common.unmatched_condition_a_count,
        unmatched_condition_b_count=common.unmatched_condition_b_count,
        missing_metric_count=common.missing_metric_count,
        statistic=statistic,
        effect_size=None,
        ci_low=None,
        ci_high=None,
        p_value=None,
        p_adjusted=None,
        correction="none",
        status=status,
        notes=notes,
    )


def _cohens_dz_stats_row(
    common: _StatsContext,
    deltas: Sequence[float],
    conflict_count: int,
) -> StaticRinStatsRow:
    effect_size: float | None = None
    if conflict_count:
        status = COMPARISON_STATUS_SKIPPED_IDENTITY_CONFLICT
        notes = _conflict_stats_note(conflict_count)
    elif len(deltas) < 2:
        status = COMPARISON_STATUS_SKIPPED_INSUFFICIENT_DATA
        notes = "Cohen's dz requires at least two complete paired differences."
    else:
        mean_delta = math.fsum(deltas) / len(deltas)
        variance = math.fsum((value - mean_delta) ** 2 for value in deltas) / (
            len(deltas) - 1
        )
        if variance == 0.0:
            status = COMPARISON_STATUS_SKIPPED_UNDEFINED_VARIANCE
            notes = (
                "Cohen's dz is undefined because paired differences have zero "
                "sample variance."
            )
        else:
            status = COMPARISON_STATUS_COMPUTED
            effect_size = mean_delta / math.sqrt(variance)
            notes = (
                "Cohen's dz = mean paired difference / sample standard "
                "deviation of paired differences."
            )
    return StaticRinStatsRow(
        comparison_id=common.comparison_id,
        scope="node_metrics",
        condition_a=common.condition_a,
        condition_b=common.condition_b,
        metric=common.metric,
        method="cohens_dz",
        n_a=common.n_a,
        n_b=common.n_b,
        matched_count=common.matched_count,
        unmatched_condition_a_count=common.unmatched_condition_a_count,
        unmatched_condition_b_count=common.unmatched_condition_b_count,
        missing_metric_count=common.missing_metric_count,
        statistic=None,
        effect_size=effect_size,
        ci_low=None,
        ci_high=None,
        p_value=None,
        p_adjusted=None,
        correction="none",
        status=status,
        notes=notes,
    )


def _conflict_stats_note(conflict_count: int) -> str:
    return (
        f"{conflict_count} shared residue_index value(s) have conflicting stable "
        "identity; no statistic is computed for this condition pair. Conflicts "
        "are included in both unmatched counts."
    )


def _deferred_scope_note(scope: str) -> str:
    if scope == "edge_metrics":
        return "Edge comparison is deferred; absent edges are not treated as zero."
    if scope == "communities":
        return "Community IDs are condition-local and are not matched."
    return (
        "Region enrichment comparison is deferred because condition-local "
        "community IDs are not stable cross-condition groups."
    )


def _load_centrality_artifact(path: Path) -> _CentralityArtifact:
    try:
        with path.open(encoding="utf-8", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            if reader.fieldnames != list(STATIC_RIN_METRICS_COLUMNS):
                raise StaticRinComparisonError(
                    f"Stage 21.B centrality columns do not match: {path}"
                )
            records = list(reader)
    except FileNotFoundError as error:
        raise StaticRinComparisonError(
            f"missing Stage 21.B centrality artifact: {path}"
        ) from error
    except (OSError, UnicodeError, csv.Error) as error:
        raise StaticRinComparisonError(
            f"Stage 21.B centrality artifact could not be read: {path}"
        ) from error
    if not records:
        raise StaticRinComparisonError(
            f"Stage 21.B centrality artifact contains no rows: {path}"
        )

    condition: str | None = None
    by_residue_index: dict[int, _CentralityRow] = {}
    identities: set[_NodeIdentity] = set()
    for row_number, record in enumerate(records, start=2):
        row_condition = _required_text(
            record["condition"], f"row {row_number} condition"
        )
        if condition is None:
            condition = row_condition
        elif row_condition != condition:
            raise StaticRinComparisonError(
                f"centrality condition is inconsistent at row {row_number}: {path}"
            )
        residue_index = _required_int(
            record["residue_index"], f"row {row_number} residue_index"
        )
        node_id = _required_text(record["node_id"], f"row {row_number} node_id")
        if node_id != f"{row_condition}:{residue_index}":
            raise StaticRinComparisonError(
                f"centrality node_id is not the accepted format at row {row_number}"
            )
        identity = _NodeIdentity(
            residue_index=residue_index,
            resid=_required_text(record["resid"], f"row {row_number} resid"),
            resname=_required_text(record["resname"], f"row {row_number} resname"),
            segment_id=record["segment_id"] or None,
        )
        if residue_index in by_residue_index or identity in identities:
            raise StaticRinComparisonError(
                f"duplicate centrality node identity at row {row_number}: {path}"
            )
        metrics = {
            metric: _optional_metric(
                record[metric],
                f"row {row_number} {metric}",
                integer=metric in {"degree", "kcore"},
            )
            for metric in STATIC_RIN_COMPARISON_METRICS
        }
        by_residue_index[residue_index] = _CentralityRow(
            condition=row_condition,
            node_id=node_id,
            identity=identity,
            metrics=metrics,
        )
        identities.add(identity)
    assert condition is not None
    return _CentralityArtifact(
        condition=condition,
        source_name=path.name,
        by_residue_index=by_residue_index,
    )


def _required_text(value: str | None, label: str) -> str:
    if value is None or not value.strip():
        raise StaticRinComparisonError(f"{label} must be a non-empty string")
    return value.strip()


def _required_int(value: str | None, label: str) -> int:
    try:
        if value is None or value.strip() != str(int(value)):
            raise ValueError
        return int(value)
    except ValueError as error:
        raise StaticRinComparisonError(f"{label} must be an integer") from error


def _optional_metric(
    value: str | None,
    label: str,
    *,
    integer: bool,
) -> float | None:
    if value is None or value == "":
        return None
    try:
        numeric = float(value)
    except ValueError as error:
        raise StaticRinComparisonError(f"{label} must be numeric or empty") from error
    if not math.isfinite(numeric):
        raise StaticRinComparisonError(f"{label} must be finite or empty")
    if integer and not numeric.is_integer():
        raise StaticRinComparisonError(f"{label} must be an integer or empty")
    return numeric


def _write_csv(
    path: Path,
    columns: Sequence[str],
    rows: Sequence[Mapping[str, object]],
) -> None:
    temporary_path: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as csv_file:
            temporary_path = Path(csv_file.name)
            writer = csv.DictWriter(
                csv_file,
                fieldnames=columns,
                lineterminator="\n",
            )
            writer.writeheader()
            for row in rows:
                writer.writerow({key: _csv_value(value) for key, value in row.items()})
        temporary_path.replace(path)
    except (OSError, csv.Error) as error:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise StaticRinComparisonError(
            f"static RIN comparison artifact could not be written: {path}"
        ) from error


def _csv_value(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, float):
        return format(value, ".15g")
    return value


__all__ = [
    "COMPARISON_STATUS_COMPUTED",
    "COMPARISON_STATUS_SKIPPED_IDENTITY_CONFLICT",
    "COMPARISON_STATUS_SKIPPED_INSUFFICIENT_DATA",
    "COMPARISON_STATUS_SKIPPED_MISSING_METRIC",
    "COMPARISON_STATUS_SKIPPED_UNDEFINED_VARIANCE",
    "COMPARISON_STATUS_SKIPPED_UNMATCHED_CONDITION_A",
    "COMPARISON_STATUS_SKIPPED_UNMATCHED_CONDITION_B",
    "COMPARISON_STATUS_SKIPPED_UNSUPPORTED_SCOPE",
    "STATIC_RIN_COMPARISON_COLUMNS",
    "STATIC_RIN_COMPARISON_METHODS",
    "STATIC_RIN_COMPARISON_METRICS",
    "STATIC_RIN_DEFERRED_COMPARISON_SCOPES",
    "STATIC_RIN_STATS_COLUMNS",
    "StaticRinComparison",
    "StaticRinComparisonArtifacts",
    "StaticRinComparisonError",
    "StaticRinComparisonRow",
    "StaticRinStatsRow",
    "compare_static_rin_metrics_from_artifacts",
    "write_static_rin_comparison_artifacts",
]


# Explicit v1 matching is an independent operation. Legacy constants, caller,
# serializers and statistical kernels above retain their exact behavior.
EXPLICIT_COMPARISON_COLUMNS = (
    "schema_version",
    "comparison_id",
    "pair_index",
    "scope",
    "match_state",
    "reason_code",
    "condition_a",
    "condition_b",
    "identity_a_project",
    "identity_a_system_id",
    "identity_a_trajectory_id",
    "identity_a_replica_id",
    "identity_a_engine",
    "identity_a_condition",
    "identity_a_variant_id",
    "identity_a_disulfide_state",
    "identity_b_project",
    "identity_b_system_id",
    "identity_b_trajectory_id",
    "identity_b_replica_id",
    "identity_b_engine",
    "identity_b_condition",
    "identity_b_variant_id",
    "identity_b_disulfide_state",
    "node_id_a",
    "residue_index_a",
    "resid_a",
    "resname_a",
    "segment_id_a",
    "node_id_b",
    "residue_index_b",
    "resid_b",
    "resname_b",
    "segment_id_b",
    "reference_id",
    "reference_sha256",
    "reference_chain_id",
    "reference_position",
    "metric",
    "value_a",
    "value_b",
    "delta",
    "status",
    "matching_path",
    "matching_sha256",
    "centrality_a_role",
    "centrality_a_path",
    "centrality_a_sha256",
    "centrality_b_role",
    "centrality_b_path",
    "centrality_b_sha256",
    "science_a_role",
    "science_a_path",
    "science_a_sha256",
    "science_b_role",
    "science_b_path",
    "science_b_sha256",
    "mapping_a_role",
    "mapping_a_path",
    "mapping_a_sha256",
    "mapping_b_role",
    "mapping_b_path",
    "mapping_b_sha256",
    "notes",
)
EXPLICIT_STATS_COLUMNS = (
    "schema_version",
    "comparison_id",
    "pair_index",
    "scope",
    "condition_a",
    "condition_b",
    "identity_a_project",
    "identity_a_system_id",
    "identity_a_trajectory_id",
    "identity_a_replica_id",
    "identity_a_engine",
    "identity_a_condition",
    "identity_a_variant_id",
    "identity_a_disulfide_state",
    "identity_b_project",
    "identity_b_system_id",
    "identity_b_trajectory_id",
    "identity_b_replica_id",
    "identity_b_engine",
    "identity_b_condition",
    "identity_b_variant_id",
    "identity_b_disulfide_state",
    "reference_id",
    "reference_sha256",
    "metric",
    "method",
    "n_a",
    "n_b",
    "matched_count",
    "unmatched_condition_a_count",
    "unmatched_condition_b_count",
    "missing_metric_count",
    "conflict_count",
    "statistic",
    "effect_size",
    "ci_low",
    "ci_high",
    "p_value",
    "p_adjusted",
    "correction",
    "status",
    "matching_path",
    "matching_sha256",
    "centrality_a_role",
    "centrality_a_path",
    "centrality_a_sha256",
    "centrality_b_role",
    "centrality_b_path",
    "centrality_b_sha256",
    "science_a_role",
    "science_a_path",
    "science_a_sha256",
    "science_b_role",
    "science_b_path",
    "science_b_sha256",
    "mapping_a_role",
    "mapping_a_path",
    "mapping_a_sha256",
    "mapping_b_role",
    "mapping_b_path",
    "mapping_b_sha256",
    "notes",
)


class StaticRinMatchingError(StaticRinComparisonError):
    """Invalid explicit binding, correspondence or scientific compatibility."""


@dataclass(frozen=True)
class ExplicitStaticRinComparison:
    matching_path: Path
    matching_identifier: str
    matching_sha256: str
    comparison_rows: tuple[Mapping[str, object], ...]
    stats_rows: tuple[Mapping[str, object], ...]


class _ExplicitNodeKey(_StrictModel):
    node_id: Text
    residue_index: Annotated[int, Field(ge=0)]
    resid: Text
    resname: Text
    segment_id: Text | None


class _ExplicitMember(_StrictModel):
    identity: InputIdentity
    centrality: AuthorityBinding
    science: AuthorityBinding
    reference: ReferenceIdentity | None
    residue_mapping: AuthorityBinding | None


class _ExplicitRecord(_StrictModel):
    state: Literal["matched", "a_only", "b_only", "conflict"]
    a: _ExplicitNodeKey | None
    b: _ExplicitNodeKey | None
    reference_key: ReferenceResidueKey | None
    reason_code: Text | None

    @model_validator(mode="after")
    def endpoints(self) -> Self:
        present = (self.a is not None, self.b is not None)
        if (
            present
            != {
                "matched": (True, True),
                "conflict": (True, True),
                "a_only": (True, False),
                "b_only": (False, True),
            }[self.state]
        ):
            raise ValueError("Illegal matching state/endpoints")
        if (self.reason_code is None) != (self.state == "matched"):
            raise ValueError(
                "Matched has null reason; unmatched/conflict needs a supplied "
                "nonblank reason"
            )
        return self


class _ExplicitPair(_StrictModel):
    a: Annotated[int, Field(ge=0)]
    b: Annotated[int, Field(ge=0)]
    mode: Literal["exact_source_identity", "common_reference"]
    records: tuple[_ExplicitRecord, ...]


class _ExplicitMatching(_StrictModel):
    schema_version: Literal["mania.static_rin_matching.v1"]
    kind: Literal["mania_static_rin_matching"]
    comparison_id: Text
    members: Annotated[tuple[_ExplicitMember, ...], Field(min_length=2)]
    pairs: tuple[_ExplicitPair, ...]


def _matching_models() -> tuple[type[_ExplicitMatching], type[_ExplicitNodeKey]]:
    return _ExplicitMatching, _ExplicitNodeKey


def _bound_member_file(
    root: Path, binding: AuthorityBinding, identity: InputIdentity, role: str
) -> Path:
    from mania.artifact_inventory_io import stream_file_sha256
    from mania.input_binding import portable_path
    from mania.output_paths import require_input_file

    portable_path(binding.path)
    if binding.role != role or binding.source_identity != identity:
        raise StaticRinMatchingError("Incorrect matching source role/identity")
    path = require_input_file(root / binding.path)
    if not path.is_relative_to(root) or stream_file_sha256(path) != binding.sha256:
        raise StaticRinMatchingError("Changed or escaping matching authority")
    return path


def _read_scientific_source(
    root: Path, member: _ExplicitMember, *, verify_values: bool
) -> tuple[_CentralityArtifact, Any, tuple[object, ...]]:
    """Prove protocol/population using existing bound v1 input/config passports.

    The binding contains the actual RIN inputs, graph, centrality, effective
    config and run provenance. No new 'compatible' flag or scientific schema.
    Value derivation is verified only in execution/read-back, never dry-run.
    """
    from mania.analysis.static_rin_graph import build_static_rin_graph
    from mania.analysis.static_rin_metrics import _csv_value as metric_cell
    from mania.analysis.static_rin_metrics import compute_static_rin_metrics
    from mania.input_binding import read_input_binding
    from mania.run_config import merge_methods
    from mania.run_config_io import read_bound_run_config
    from mania.run_provenance_io import read_run_provenance

    path = _bound_member_file(root, member.science, member.identity, "input_binding")
    if verify_values:
        binding = read_input_binding(path, root=root)
    else:
        from mania.input_binding import InputBinding
        from mania.preprocessing.molecular_partner_metadata_io import read_strict_json

        read_strict_json(path)
        binding = InputBinding.model_validate_json(path.read_bytes())
        for evidence in binding.files:
            from mania.output_paths import require_input_file

            location = require_input_file(root / evidence.path)
            if (
                not location.is_relative_to(root)
                or location.stat().st_size != evidence.size_bytes
            ):
                raise StaticRinMatchingError("Bound source size/path differs")
    if binding.identity != member.identity:
        raise StaticRinMatchingError("Scientific input identity mismatch")
    files = {f.role: f for f in binding.files}
    required = {
        "centrality",
        "static_rin_graph",
        "residue_table",
        "protein_contact_edges",
        "edge_semantics",
        "effective_config",
        "run_provenance",
    }
    if not required <= set(files):
        raise StaticRinMatchingError(
            "Bound scientific source lacks RIN/config/population evidence"
        )
    centrality = files["centrality"]
    if (centrality.path, centrality.sha256) != (
        member.centrality.path,
        member.centrality.sha256,
    ):
        raise StaticRinMatchingError("Centrality is not bound to the scientific source")
    config = read_bound_run_config(files["effective_config"].verify(root))
    systems = [
        s for s in config.systems if s.identity(config.project) == member.identity
    ]
    if len(systems) != 1:
        raise StaticRinMatchingError("Scientific config has no unique member identity")
    system = systems[0]
    options = merge_methods(config, system)
    if not options.get("static_rin") or not options["static_rin"].enabled:
        raise StaticRinMatchingError("Source does not declare computed static RIN")
    contacts = options.get("contacts")
    if (
        contacts is None
        or not contacts.enabled
        or getattr(contacts, "selection", None) != "protein"
    ):
        raise StaticRinMatchingError(
            "Source is not the approved protein contact/RIN protocol"
        )
    provenance = read_run_provenance(files["run_provenance"].verify(root))
    from mania.scientific_qualification import consume_provenance

    consume_provenance(
        files["run_provenance"].verify(root),
        member.identity,
        artifact=files["centrality"].verify(root),
        verify_science=verify_values,
    )
    if provenance.status != "completed":
        raise StaticRinMatchingError("Scientific source is incomplete/failed")
    if provenance.resolved_configuration != config.model_dump(
        mode="json", exclude_unset=True
    ):
        # The retained provenance freezes arrays as tuples. Compare its own
        # documented JSON projection, preserving all declared fields/values.
        if provenance.to_dict()["resolved_configuration"] != config.model_dump(
            mode="json", exclude_unset=True
        ):
            raise StaticRinMatchingError("Source config and executed provenance differ")
    with (root / member.centrality.path).open(encoding="utf-8", newline="") as stream:
        if tuple(next(csv.reader(stream), ())) != STATIC_RIN_METRICS_COLUMNS:
            raise StaticRinMatchingError(
                "Source centrality requires exact retained ordered columns"
            )
    artifact = _load_centrality_artifact(root / member.centrality.path)
    sampling = [
        s for s in provenance.sampling_by_condition if s.condition == artifact.condition
    ]
    if len(sampling) != 1 or sampling[0].effective is None:
        raise StaticRinMatchingError("RIN sampling population is not established")
    effective = sampling[0].effective
    count = effective.sampled_frame_count
    if count < 1:
        raise StaticRinMatchingError("RIN source has no sampled population")
    from mania.preprocessing.molecular_partner_metadata_io import read_strict_json

    semantics = read_strict_json(files["edge_semantics"].verify(root))
    from mania.preprocessing.trajectory_preprocessing_manifests import (
        build_edge_semantics_manifest,
    )

    if semantics != build_edge_semantics_manifest():
        raise StaticRinMatchingError(
            "Unknown/different interaction and graph-weight protocol"
        )
    if verify_values:
        graph = build_static_rin_graph(
            files["residue_table"].verify(root),
            files["protein_contact_edges"].verify(root),
            edge_semantics_path=files["edge_semantics"].verify(root),
        )
        graph_payload = read_strict_json(files["static_rin_graph"].verify(root))
        if graph.to_dict() != graph_payload:
            raise StaticRinMatchingError(
                "RIN graph differs from its bound scientific inputs"
            )
        metrics = compute_static_rin_metrics(graph)
        with (root / member.centrality.path).open(
            encoding="utf-8", newline=""
        ) as stream:
            actual = tuple(csv.DictReader(stream))
        expected = tuple(
            {k: str(metric_cell(v)) for k, v in row.to_dict().items()}
            for row in metrics.node_metrics
        )
        if actual != expected:
            raise StaticRinMatchingError(
                "Centrality values do not derive from the bound RIN graph"
            )
        for edge in graph.edges:
            if any(i.sampled_frame_count != count for i in edge.interactions):
                raise StaticRinMatchingError(
                    "RIN interaction denominator contradicts executed sampling"
                )
    from mania.input_binding import FrameRequest, PhysicalRequest

    temporal = system.physical_time
    request: FrameRequest | PhysicalRequest
    if temporal is None:
        request = FrameRequest(**system.frames.model_dump())
    else:
        request = PhysicalRequest(**temporal.model_dump())
    if binding.temporal_request != request:
        raise StaticRinMatchingError("Scientific frame/time request mismatch")
    # Engine/labels/IDs are source identity, not a metric-equivalence veto.
    # Actual protocol/weights/units, selected request and denominator are equal.
    signature = (
        contacts.model_dump_json(),
        options["static_rin"].model_dump_json(),
        request.model_dump_json()
        if isinstance(request, FrameRequest)
        else json.dumps(
            request.model_dump(mode="json", exclude={"windows"}), sort_keys=True
        ),
        effective.to_dict(),
        semantics,
    )
    return artifact, files, signature


def read_static_rin_matching(
    path: str | Path, *, verify_science: bool = True
) -> tuple[_ExplicitMatching, tuple[Any, ...], str]:
    from mania.artifact_inventory_io import stream_file_sha256
    from mania.canonical_reference_io import read_protein_reference
    from mania.canonical_residue_mapping_io import read_residue_mapping
    from mania.input_binding import verify_authority
    from mania.output_paths import require_input_file
    from mania.preprocessing.molecular_partner_metadata_io import read_strict_json

    source = require_input_file(Path(path).absolute())
    raw = source.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise StaticRinMatchingError("Matching JSON must be strict UTF-8 without BOM")
    # Reject duplicates before pydantic's typed JSON-array -> tuple conversion.
    read_strict_json(source)
    Model, _ = _matching_models()
    matching = Model.model_validate_json(raw)
    identities = [
        (
            m.identity.project,
            m.identity.system_id,
            m.identity.trajectory_id,
            m.identity.replica_id,
        )
        for m in matching.members
    ]
    if len(set(identities)) != len(identities):
        raise StaticRinMatchingError("Duplicate member identity")
    if [(p.a, p.b) for p in matching.pairs] != list(
        itertools.combinations(range(len(matching.members)), 2)
    ):
        raise StaticRinMatchingError(
            "Pairs must be complete in declared member-combination order"
        )
    root = source.parent
    contexts = []
    for member in matching.members:
        _bound_member_file(root, member.centrality, member.identity, "centrality")
        artifact, files, signature = _read_scientific_source(
            root, member, verify_values=verify_science
        )
        mapping = None
        reference = None
        if member.residue_mapping is not None:
            if member.reference is None or "reference" not in files:
                raise StaticRinMatchingError(
                    "Full verified reference evidence is required"
                )
            reference = read_protein_reference(files["reference"].verify(root))
            if reference.reference != member.reference:
                raise StaticRinMatchingError("Unverified/mismatched reference identity")
            path_mapping = _bound_member_file(
                root, member.residue_mapping, member.identity, "residue_mapping"
            )
            mapping = read_residue_mapping(path_mapping, reference=reference)
            if mapping.identity != member.identity:
                raise StaticRinMatchingError("Mapping source identity mismatch")
            for authority in mapping.authority:
                verify_authority(root, authority, member.identity)
        elif member.reference is not None:
            raise StaticRinMatchingError(
                "Reference-only/digest-only trust is insufficient"
            )
        contexts.append((artifact, signature, mapping, reference))
    for pair in matching.pairs:
        a, b = contexts[pair.a], contexts[pair.b]
        if a[1] != b[1]:
            raise StaticRinMatchingError(
                "Incompatible scientific RIN definition/options/population"
            )
        if pair.mode == "common_reference" and (
            a[2] is None
            or b[2] is None
            or a[3] is None
            or b[3] is None
            or a[3].reference != b[3].reference
        ):
            raise StaticRinMatchingError(
                "Common reference requires two complete verified equivalent "
                "references/mappings"
            )
        _validate_explicit_pair(pair, a, b)
    return matching, tuple(contexts), stream_file_sha256(source)


def _node_tuple(key: _ExplicitNodeKey) -> tuple[object, ...]:
    return key.node_id, key.residue_index, key.resid, key.resname, key.segment_id


def _reference_for_node(
    key: _ExplicitNodeKey, mapping: ResidueMappingTable | None
) -> tuple[str | None, int | None] | None:
    if mapping is None:
        raise StaticRinMatchingError("Mapping is required")
    # Segment-qualified, insertion-free source keys are fully represented by
    # the retained Stage21 source nodes. Other namespaces need real topology
    # evidence; never infer a chain or insertion code from an equal number.
    candidates = [
        r
        for r in mapping.records
        if r.source.resid == key.resid
        and r.source.resname == key.resname
        and r.source.segment_id == key.segment_id
    ]
    if len(candidates) != 1:
        raise StaticRinMatchingError("Ambiguous/missing source mapping")
    record = candidates[0]
    if (
        record.source.namespace_kind != "segment"
        or record.source.chain_id is not None
        or record.source.insertion_code is not None
    ):
        raise StaticRinMatchingError(
            "Chain/insertion mapping needs source topology authority; "
            "Stage21 node alone is insufficient"
        )
    if record.mapping_status != "mapped":
        return None
    return record.reference_chain_id, record.reference_position


def _validate_explicit_pair(pair: _ExplicitPair, a: Any, b: Any) -> None:
    seen_a: set[int] = set()
    seen_b: set[int] = set()
    source_a, source_b = a[0], b[0]
    records_by_node = {}
    for record in pair.records:
        for side, key, artifact, seen in (
            ("a", record.a, source_a, seen_a),
            ("b", record.b, source_b, seen_b),
        ):
            if key is None:
                continue
            row = artifact.by_residue_index.get(key.residue_index)
            expected = (
                None
                if row is None
                else (
                    row.node_id,
                    row.identity.residue_index,
                    row.identity.resid,
                    row.identity.resname,
                    row.identity.segment_id,
                )
            )
            if _node_tuple(key) != expected or key.residue_index in seen:
                raise StaticRinMatchingError(
                    "Unknown/altered/duplicate source node or many-to-one record"
                )
            seen.add(key.residue_index)
            records_by_node[(side, key.residue_index)] = record
        if pair.mode == "exact_source_identity":
            if record.reference_key is not None:
                raise StaticRinMatchingError(
                    "Exact source identity cannot fabricate a reference key"
                )
            if record.state == "matched":
                assert record.a is not None and record.b is not None
            if (
                record.state == "matched"
                and _node_tuple(cast(_ExplicitNodeKey, record.a))[1:]
                != _node_tuple(cast(_ExplicitNodeKey, record.b))[1:]
            ):
                raise StaticRinMatchingError("Matched exact source identities differ")
        elif record.state == "matched":
            assert record.a is not None and record.b is not None
            expected_a = _reference_for_node(record.a, a[2])
            expected_b = _reference_for_node(record.b, b[2])
            actual = (
                None
                if record.reference_key is None
                else (
                    record.reference_key.reference_chain_id,
                    record.reference_key.reference_position,
                )
            )
            if actual is None or actual != expected_a or actual != expected_b:
                raise StaticRinMatchingError(
                    "Matched nodes lack the same verified reference key"
                )
        elif record.reference_key is not None:
            side = a if record.a is not None else b
            key = record.a if record.a is not None else record.b
            assert key is not None
            actual = (
                record.reference_key.reference_chain_id,
                record.reference_key.reference_position,
            )
            if actual != _reference_for_node(key, side[2]):
                raise StaticRinMatchingError("Unmatched reference key is unverified")
    if seen_a != set(source_a.by_residue_index) or seen_b != set(
        source_b.by_residue_index
    ):
        raise StaticRinMatchingError(
            "Every node must appear exactly once on its own side"
        )
    if pair.mode == "exact_source_identity":
        for index in set(source_a.by_residue_index) & set(source_b.by_residue_index):
            ra, rb = records_by_node[("a", index)], records_by_node[("b", index)]
            same = (
                source_a.by_residue_index[index].identity
                == source_b.by_residue_index[index].identity
            )
            if not same and (ra is not rb or ra.state != "conflict"):
                raise StaticRinMatchingError(
                    "Known source identity conflict cannot be hidden as unmatched"
                )


def _explicit_context(
    matching: _ExplicitMatching, pair: _ExplicitPair, index: int, path: str, digest: str
) -> dict[str, object]:
    a, b = matching.members[pair.a], matching.members[pair.b]
    context = {
        "comparison_id": matching.comparison_id,
        "pair_index": index,
        "condition_a": None,
        "condition_b": None,
        "matching_path": path,
        "matching_sha256": digest,
        "reference_id": None,
        "reference_sha256": None,
    }
    for side, member in (("a", a), ("b", b)):
        context.update(
            {f"identity_{side}_{k}": v for k, v in member.identity.model_dump().items()}
        )
        for name, binding in (
            ("centrality", member.centrality),
            ("science", member.science),
            ("mapping", member.residue_mapping),
        ):
            context.update(
                {
                    f"{name}_{side}_{k}": getattr(binding, k)
                    if binding is not None
                    else None
                    for k in ("role", "path", "sha256")
                }
            )
    if pair.mode == "common_reference":
        assert a.reference is not None
        context.update(
            reference_id=a.reference.reference_id,
            reference_sha256=a.reference.reference_sha256,
        )
    return context


def compare_static_rin_metrics_explicit(
    matching_path: str | Path, *, matching_identifier: str | None = None
) -> ExplicitStaticRinComparison:
    from mania.input_binding import portable_path

    path = Path(matching_path).absolute()
    identifier = portable_path(matching_identifier or path.name)
    matching, contexts, digest = read_static_rin_matching(path)
    comparison_rows, stats_rows = [], []
    for index, pair in enumerate(matching.pairs):
        artifact_a, artifact_b = contexts[pair.a][0], contexts[pair.b][0]
        common = _explicit_context(matching, pair, index, identifier, digest)
        common.update(
            condition_a=artifact_a.condition, condition_b=artifact_b.condition
        )
        matched, conflicts = [], 0
        unmatched_a, unmatched_b = 0, 0
        for record in pair.records:
            row_a = (
                artifact_a.by_residue_index.get(record.a.residue_index)
                if record.a is not None
                else None
            )
            row_b = (
                artifact_b.by_residue_index.get(record.b.residue_index)
                if record.b is not None
                else None
            )
            if record.state == "matched":
                assert row_a is not None and row_b is not None
                legacy = _matched_rows(
                    matching.comparison_id, artifact_a, artifact_b, row_a, row_b
                )
                matched.append((row_a, row_b))
            elif record.state == "conflict":
                assert row_a is not None and row_b is not None
                legacy = _identity_conflict_rows(
                    matching.comparison_id, artifact_a, artifact_b, row_a, row_b
                )
                conflicts += 1
                unmatched_a += 1
                unmatched_b += 1
            else:
                present_row = row_a or row_b
                assert present_row is not None
                legacy = _unmatched_rows(
                    matching.comparison_id,
                    artifact_a,
                    artifact_b,
                    present_row,
                    missing_condition="b" if record.state == "a_only" else "a",
                )
                unmatched_b += record.state == "a_only"
                unmatched_a += record.state == "b_only"
            for old in legacy:
                row: dict[str, object] = {k: None for k in EXPLICIT_COMPARISON_COLUMNS}
                row.update(common)
                row.update(
                    schema_version="mania.static_rin_comparison.v1",
                    scope=old.scope,
                    match_state=record.state,
                    reason_code=record.reason_code,
                    metric=old.metric,
                    value_a=old.value_a,
                    value_b=old.value_b,
                    delta=old.delta,
                    status=old.status,
                    notes=old.notes
                    if pair.mode == "exact_source_identity"
                    else (
                        "Verified explicit common-reference correspondence; "
                        "retained paired-metric semantics."
                    ),
                )
                for side, key in (("a", record.a), ("b", record.b)):
                    if key is not None:
                        row.update(
                            {f"{k}_{side}": v for k, v in key.model_dump().items()}
                        )
                if record.reference_key is not None:
                    row.update(record.reference_key.model_dump())
                comparison_rows.append(row)
        for metric in STATIC_RIN_COMPARISON_METRICS:
            values_a = [a.metrics[metric] for a, _ in matched]
            values_b = [b.metrics[metric] for _, b in matched]
            complete = [
                (a, b)
                for a, b in zip(values_a, values_b, strict=True)
                if a is not None and b is not None
            ]
            deltas = tuple(b - a for a, b in complete)
            context = _StatsContext(
                matching.comparison_id,
                artifact_a.condition,
                artifact_b.condition,
                metric,
                sum(v is not None for v in values_a),
                sum(v is not None for v in values_b),
                len(matched),
                unmatched_a,
                unmatched_b,
                len(matched) - len(complete),
            )
            for old_stat in (
                _paired_delta_stats_row(context, deltas, conflicts),
                _cohens_dz_stats_row(context, deltas, conflicts),
            ):
                row = {k: None for k in EXPLICIT_STATS_COLUMNS}
                row.update(common)
                row.update({k: v for k, v in old_stat.to_dict().items() if k in row})
                row.update(
                    schema_version="mania.static_rin_stats.v1", conflict_count=conflicts
                )
                stats_rows.append(row)
        for scope in STATIC_RIN_DEFERRED_COMPARISON_SCOPES:
            row = {k: None for k in EXPLICIT_STATS_COLUMNS}
            row.update(common)
            row.update(
                schema_version="mania.static_rin_stats.v1",
                scope=scope,
                metric="not_applicable",
                method="not_implemented",
                n_a=0,
                n_b=0,
                matched_count=0,
                unmatched_condition_a_count=0,
                unmatched_condition_b_count=0,
                missing_metric_count=0,
                conflict_count=conflicts,
                correction="none",
                status=COMPARISON_STATUS_SKIPPED_UNSUPPORTED_SCOPE,
                notes=_deferred_scope_note(scope),
            )
            stats_rows.append(row)
    return ExplicitStaticRinComparison(
        path, identifier, digest, tuple(comparison_rows), tuple(stats_rows)
    )


def write_explicit_static_rin_comparison(
    comparison: ExplicitStaticRinComparison, output_dir: str | Path
) -> StaticRinComparisonArtifacts:
    directory = Path(output_dir)
    _write_csv(
        directory / "comparison.csv",
        EXPLICIT_COMPARISON_COLUMNS,
        comparison.comparison_rows,
    )
    _write_csv(directory / "stats.csv", EXPLICIT_STATS_COLUMNS, comparison.stats_rows)
    return StaticRinComparisonArtifacts(
        directory / "comparison.csv", directory / "stats.csv"
    )


def read_explicit_static_rin_comparison(
    output_dir: str | Path,
    *,
    matching_path: str | Path,
    matching_identifier: str | None = None,
) -> ExplicitStaticRinComparison:
    # Bound independent source reconstruction validates identities, counts,
    # null/zero, statuses and meaningful numeric values, not merely CSV shape.
    expected = compare_static_rin_metrics_explicit(
        matching_path, matching_identifier=matching_identifier
    )
    for name, columns, rows in (
        ("comparison.csv", EXPLICIT_COMPARISON_COLUMNS, expected.comparison_rows),
        ("stats.csv", EXPLICIT_STATS_COLUMNS, expected.stats_rows),
    ):
        import io

        stream = io.StringIO(newline="")
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: _csv_value(row[k]) for k in columns})
        path = Path(output_dir) / name
        if path.read_bytes() != stream.getvalue().encode("utf-8"):
            raise StaticRinMatchingError(
                "Invalid v1 comparison header/types/authority/values/representation: "
                + name
            )
    return expected
