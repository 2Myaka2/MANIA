"""Pipeline step wrapper for graph diagnostics."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from mania.analysis.graph_diagnostics import (
    run_and_write_output_graph_diagnostics_report_bundle,
)


@dataclass(frozen=True)
class GraphDiagnosticsPipelineStepResult:
    """Structured result from the graph diagnostics pipeline step."""

    output_root: Path
    diagnostics_output_dir: Path
    conditions: tuple[str, ...]
    passed: bool
    written_paths: tuple[Path, ...]
    summary_path: Path | None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable pipeline step result."""
        return {
            "output_root": str(self.output_root),
            "diagnostics_output_dir": str(self.diagnostics_output_dir),
            "conditions": list(self.conditions),
            "passed": self.passed,
            "written_paths": [str(path) for path in self.written_paths],
            "summary_path": (
                None if self.summary_path is None else str(self.summary_path)
            ),
        }


def run_graph_diagnostics_pipeline_step(
    output_root: str | Path,
    diagnostics_output_dir: str | Path,
    *,
    conditions: Iterable[str] | None = None,
    abs_tol: float = 1e-6,
    weight_column: str = "contact_freq",
    degree_column: str = "degree",
    strength_column: str = "strength",
) -> GraphDiagnosticsPipelineStepResult:
    """Run graph diagnostics as a thin pipeline step."""
    normalized_output_root = Path(output_root)
    normalized_diagnostics_output_dir = Path(diagnostics_output_dir)
    report_bundle = run_and_write_output_graph_diagnostics_report_bundle(
        output_root=normalized_output_root,
        diagnostics_output_dir=normalized_diagnostics_output_dir,
        conditions=conditions,
        abs_tol=abs_tol,
        weight_column=weight_column,
        degree_column=degree_column,
        strength_column=strength_column,
    )
    summary_path = next(
        (
            path
            for path in report_bundle.written_paths
            if path.name == "multi_condition_graph_diagnostics_summary.json"
        ),
        None,
    )

    return GraphDiagnosticsPipelineStepResult(
        output_root=normalized_output_root,
        diagnostics_output_dir=normalized_diagnostics_output_dir,
        conditions=report_bundle.diagnostics.conditions,
        passed=report_bundle.passed,
        written_paths=report_bundle.written_paths,
        summary_path=summary_path,
    )


__all__ = [
    "GraphDiagnosticsPipelineStepResult",
    "run_graph_diagnostics_pipeline_step",
]
