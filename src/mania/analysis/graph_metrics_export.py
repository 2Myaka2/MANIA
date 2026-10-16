"""CSV and JSON artifact writer for analysis graph metrics."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path

from mania.analysis.graph_metrics import AnalysisGraphMetricsResult

METRICS_COLUMNS = (
    "condition",
    "node_id",
    "id",
    "resid",
    "resname",
    "chain_id",
    "region",
    "ss",
    "rmsf_A",
    "sasa_A2",
    "x",
    "y",
    "z",
    "x_ca",
    "y_ca",
    "z_ca",
    "degree",
    "strength",
    "betweenness",
    "closeness",
    "eigenvector",
    "pagerank",
    "kcore",
    "community",
    "community_id",
)
COMMUNITIES_COLUMNS = (
    "condition",
    "community",
    "community_id",
    "community_size",
    "algorithm",
    "node_id",
    "id",
    "resid",
)


@dataclass(frozen=True)
class AnalysisGraphMetricsArtifacts:
    """Paths written for one analysis graph metrics result."""

    output_dir: Path
    metrics_paths: dict[str, Path]
    communities_paths: dict[str, Path]
    report_path: Path

    def to_dict(self) -> dict[str, object]:
        """Return artifact paths in a JSON-safe representation."""
        return {
            "output_dir": str(self.output_dir),
            "metrics_paths": {
                condition: str(path)
                for condition, path in sorted(self.metrics_paths.items())
            },
            "communities_paths": {
                condition: str(path)
                for condition, path in sorted(self.communities_paths.items())
            },
            "report_path": str(self.report_path),
        }


def write_analysis_graph_metrics_artifacts(
    result: AnalysisGraphMetricsResult,
    output_dir: str | Path,
) -> AnalysisGraphMetricsArtifacts:
    """Write per-condition CSVs and the JSON report under an analysis dir."""
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    metrics_paths: dict[str, Path] = {}
    communities_paths: dict[str, Path] = {}
    filename_components: dict[str, str] = {}

    for condition in sorted(result.metrics_by_condition):
        component = _condition_filename_component(condition)
        previous = filename_components.get(component)
        if previous is not None and previous != condition:
            raise ValueError("condition names produce colliding artifact filenames")
        filename_components[component] = condition
        metrics_path = path / f"metrics_{component}.csv"
        communities_path = path / f"communities_{component}.csv"
        _write_csv(
            metrics_path,
            METRICS_COLUMNS,
            result.metrics_by_condition[condition],
        )
        _write_csv(
            communities_path,
            COMMUNITIES_COLUMNS,
            result.communities_by_condition.get(condition, []),
        )
        metrics_paths[condition] = metrics_path
        communities_paths[condition] = communities_path

    report_path = path / "analysis_metrics_report.json"
    report_path.write_text(
        json.dumps(
            result.report,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return AnalysisGraphMetricsArtifacts(
        output_dir=path,
        metrics_paths=metrics_paths,
        communities_paths=communities_paths,
        report_path=report_path,
    )


def _condition_filename_component(condition: str) -> str:
    component = re.sub(r"[^A-Za-z0-9_.-]+", "_", condition).strip("._")
    if not component:
        raise ValueError("condition must contain a filename-safe character")
    return component


def _write_csv(
    path: Path,
    columns: tuple[str, ...],
    rows: list[dict[str, object]],
) -> None:
    with path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=columns,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    column: "" if row.get(column) is None else row.get(column)
                    for column in columns
                }
            )


__all__ = [
    "AnalysisGraphMetricsArtifacts",
    "COMMUNITIES_COLUMNS",
    "METRICS_COLUMNS",
    "write_analysis_graph_metrics_artifacts",
]
