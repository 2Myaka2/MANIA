"""Config-driven runners for pipeline step workflows."""

from __future__ import annotations

from typing import Any, cast

from mania.pipeline_steps.config import NotebookExportGraphDiagnosticsWorkflowConfig
from mania.pipeline_steps.notebook_export_diagnostics import (
    NotebookExportGraphDiagnosticsPipelineResult,
    run_notebook_export_graph_diagnostics_pipeline,
)


def run_notebook_export_graph_diagnostics_pipeline_from_config(
    config: NotebookExportGraphDiagnosticsWorkflowConfig,
) -> NotebookExportGraphDiagnosticsPipelineResult:
    """Run the composed notebook export diagnostics workflow from config."""
    if not isinstance(config, NotebookExportGraphDiagnosticsWorkflowConfig):
        raise TypeError(
            "config must be a NotebookExportGraphDiagnosticsWorkflowConfig"
        )

    kwargs = cast(dict[str, Any], config.to_pipeline_kwargs())
    return run_notebook_export_graph_diagnostics_pipeline(**kwargs)


__all__ = ["run_notebook_export_graph_diagnostics_pipeline_from_config"]
