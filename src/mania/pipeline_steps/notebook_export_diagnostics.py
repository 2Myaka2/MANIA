"""Composed notebook export and graph diagnostics pipeline workflow."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from mania.pipeline_steps.graph_diagnostics import (
    GraphDiagnosticsPipelineStepResult,
    run_graph_diagnostics_pipeline_step,
)
from mania.pipeline_steps.notebook_export import (
    NotebookContractExportPipelineStepResult,
    run_notebook_contract_export_pipeline_step,
)


@dataclass(frozen=True)
class NotebookExportGraphDiagnosticsPipelineResult:
    """Structured result from notebook export followed by graph diagnostics."""

    export_result: NotebookContractExportPipelineStepResult
    diagnostics_result: GraphDiagnosticsPipelineStepResult

    @property
    def conditions(self) -> tuple[str, ...]:
        """Return pipeline conditions from the export step."""
        return self.export_result.conditions

    @property
    def passed(self) -> bool:
        """Return whether graph diagnostics passed."""
        return self.diagnostics_result.passed

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable composed pipeline result."""
        return {
            "conditions": list(self.conditions),
            "passed": self.passed,
            "export_result": self.export_result.to_dict(),
            "diagnostics_result": self.diagnostics_result.to_dict(),
        }


def run_notebook_export_graph_diagnostics_pipeline(
    source_dir: str | Path,
    output_dir: str | Path,
    diagnostics_output_dir: str | Path,
    *,
    conditions: Iterable[str] | None = None,
    frame_time_ps: float,
    abs_tol: float = 1e-6,
    weight_column: str = "contact_freq",
    degree_column: str = "degree",
    strength_column: str = "strength",
) -> NotebookExportGraphDiagnosticsPipelineResult:
    """Run notebook contract export, then graph diagnostics on its output."""
    export_result = run_notebook_contract_export_pipeline_step(
        source_dir=source_dir,
        output_dir=output_dir,
        conditions=conditions,
        frame_time_ps=frame_time_ps,
    )
    diagnostics_result = run_graph_diagnostics_pipeline_step(
        output_root=export_result.output_dir,
        diagnostics_output_dir=diagnostics_output_dir,
        conditions=export_result.conditions,
        abs_tol=abs_tol,
        weight_column=weight_column,
        degree_column=degree_column,
        strength_column=strength_column,
    )

    return NotebookExportGraphDiagnosticsPipelineResult(
        export_result=export_result,
        diagnostics_result=diagnostics_result,
    )


__all__ = [
    "NotebookExportGraphDiagnosticsPipelineResult",
    "run_notebook_export_graph_diagnostics_pipeline",
]
