"""Per-condition residue table export from preprocessing graph mappings."""

from __future__ import annotations

import csv
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from mania.preprocessing.trajectory_graph_export import (
    PreprocessingGraphExportMappingResult,
    PreprocessingGraphNodeMappingRecord,
)

RESIDUE_TABLE_COLUMNS = (
    "condition",
    "residue_index",
    "resid",
    "resname",
    "segment_id",
    "region",
    "x_ca",
    "y_ca",
    "z_ca",
    "tm_relative_z",
    "rmsf_A",
    "sasa_A2",
    "ss",
)


@dataclass(frozen=True)
class PreprocessingResidueTableArtifact:
    """One written per-condition residue table artifact."""

    condition: str
    path: Path
    rows_written: int

    def to_dict(self) -> dict[str, object]:
        """Return JSON-safe artifact metadata."""
        return {
            "condition": self.condition,
            "path": str(self.path),
            "rows_written": self.rows_written,
        }


@dataclass(frozen=True)
class PreprocessingResidueTableCsvWriteIssue:
    """One deterministic residue table write issue."""

    kind: str
    message: str
    condition: str | None = None
    path: Path | None = None

    def to_dict(self) -> dict[str, object]:
        """Return JSON-safe issue metadata."""
        return {
            "kind": self.kind,
            "message": self.message,
            "condition": self.condition,
            "path": str(self.path) if self.path is not None else None,
        }


@dataclass(frozen=True)
class PreprocessingResidueTableCsvWriteResult:
    """Summary of one per-condition residue table export attempt."""

    output_dir: Path
    artifacts: tuple[PreprocessingResidueTableArtifact, ...] = ()
    issues: tuple[PreprocessingResidueTableCsvWriteIssue, ...] = ()

    @property
    def passed(self) -> bool:
        """Return whether all requested residue tables were written."""
        return self.issues == ()

    @property
    def rows_written(self) -> int:
        """Return the total number of residue rows written."""
        return sum(artifact.rows_written for artifact in self.artifacts)

    @property
    def paths_by_condition(self) -> dict[str, Path]:
        """Return written paths keyed by original condition identity."""
        return {
            artifact.condition: artifact.path for artifact in self.artifacts
        }

    def to_dict(self) -> dict[str, object]:
        """Return JSON-safe result metadata."""
        return {
            "output_dir": str(self.output_dir),
            "passed": self.passed,
            "rows_written": self.rows_written,
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "issues": [issue.to_dict() for issue in self.issues],
        }


def write_preprocessing_residue_tables_csv(
    mapping_result: PreprocessingGraphExportMappingResult,
    output_dir: str | Path,
) -> PreprocessingResidueTableCsvWriteResult:
    """Write ``residue_table_{condition}.csv`` files from graph nodes."""
    try:
        path = Path(output_dir)
    except TypeError:
        return _failed_result(
            Path(""),
            kind="invalid_output_dir",
            message="output_dir must be a string or Path.",
        )

    if isinstance(output_dir, str) and output_dir.strip() == "":
        return _failed_result(
            path,
            kind="invalid_output_dir",
            message="output_dir must not be empty.",
        )
    if not isinstance(mapping_result, PreprocessingGraphExportMappingResult):
        return _failed_result(
            path,
            kind="invalid_input",
            message=(
                "mapping_result must be "
                "PreprocessingGraphExportMappingResult."
            ),
        )
    if not mapping_result.passed:
        return _failed_result(
            path,
            kind="mapping_result_failed",
            message="Graph export mapping result contains issues.",
        )
    if path.exists() and not path.is_dir():
        return _failed_result(
            path,
            kind="output_dir_is_file",
            message="Residue table output directory is an existing file.",
            issue_path=path,
        )

    nodes_by_condition: dict[str, list[PreprocessingGraphNodeMappingRecord]] = {}
    for node in mapping_result.nodes:
        nodes_by_condition.setdefault(node.condition_name, []).append(node)

    output_paths: dict[str, Path] = {}
    filename_conditions: dict[str, str] = {}
    for condition in sorted(nodes_by_condition):
        try:
            component = _condition_filename_component(condition)
        except ValueError:
            return _failed_result(
                path,
                kind="invalid_condition_filename",
                message=(
                    "Condition must contain a filename-safe character for "
                    "residue table export."
                ),
                condition=condition,
            )
        previous = filename_conditions.get(component)
        if previous is not None and previous != condition:
            return _failed_result(
                path,
                kind="condition_filename_collision",
                message="Condition names produce colliding residue table filenames.",
                condition=condition,
            )
        filename_conditions[component] = condition
        output_paths[condition] = path / f"residue_table_{component}.csv"

    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        return _failed_result(
            path,
            kind="output_dir_creation_failed",
            message="Residue table output directory could not be created.",
            issue_path=path,
        )

    artifacts: list[PreprocessingResidueTableArtifact] = []
    for condition in sorted(nodes_by_condition):
        nodes = sorted(
            nodes_by_condition[condition],
            key=lambda node: (node.residue_index, node.node_id),
        )
        output_path = output_paths[condition]
        try:
            _write_residue_table(output_path, nodes)
        except (OSError, csv.Error):
            return PreprocessingResidueTableCsvWriteResult(
                output_dir=path,
                artifacts=tuple(artifacts),
                issues=(
                    PreprocessingResidueTableCsvWriteIssue(
                        kind="write_failed",
                        message="Residue table CSV file could not be written.",
                        condition=condition,
                        path=output_path,
                    ),
                ),
            )
        artifacts.append(
            PreprocessingResidueTableArtifact(
                condition=condition,
                path=output_path,
                rows_written=len(nodes),
            )
        )

    return PreprocessingResidueTableCsvWriteResult(
        output_dir=path,
        artifacts=tuple(artifacts),
    )


def _condition_filename_component(condition: str) -> str:
    component = re.sub(r"[^A-Za-z0-9_.-]+", "_", condition).strip("._")
    if not component:
        raise ValueError("condition must contain a filename-safe character")
    return component


def _write_residue_table(
    output_path: Path,
    nodes: list[PreprocessingGraphNodeMappingRecord],
) -> None:
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
                fieldnames=RESIDUE_TABLE_COLUMNS,
                lineterminator="\n",
            )
            writer.writeheader()
            writer.writerows(_residue_table_row(node) for node in nodes)
        temporary_path.replace(output_path)
    except (OSError, csv.Error):
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


def _residue_table_row(
    node: PreprocessingGraphNodeMappingRecord,
) -> dict[str, object]:
    row: dict[str, object] = {column: "" for column in RESIDUE_TABLE_COLUMNS}
    row.update(
        {
            "condition": node.condition_name,
            "residue_index": node.residue_index,
            "resid": node.residue_id,
            "resname": node.resname,
            "segment_id": node.segid or "",
            "x_ca": _optional_csv_value(node.x_ca),
            "y_ca": _optional_csv_value(node.y_ca),
            "z_ca": _optional_csv_value(node.z_ca),
        }
    )
    return row


def _optional_csv_value(value: object | None) -> object:
    return "" if value is None else value


def _failed_result(
    output_dir: Path,
    *,
    kind: str,
    message: str,
    condition: str | None = None,
    issue_path: Path | None = None,
) -> PreprocessingResidueTableCsvWriteResult:
    return PreprocessingResidueTableCsvWriteResult(
        output_dir=output_dir,
        issues=(
            PreprocessingResidueTableCsvWriteIssue(
                kind=kind,
                message=message,
                condition=condition,
                path=issue_path,
            ),
        ),
    )


__all__ = [
    "RESIDUE_TABLE_COLUMNS",
    "PreprocessingResidueTableArtifact",
    "PreprocessingResidueTableCsvWriteIssue",
    "PreprocessingResidueTableCsvWriteResult",
    "write_preprocessing_residue_tables_csv",
]
