"""File loading helpers for pipeline workflow configs."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import yaml

from mania.pipeline_steps.config import NotebookExportGraphDiagnosticsWorkflowConfig
from mania.pipeline_steps.notebook_export_diagnostics import (
    NotebookExportGraphDiagnosticsPipelineResult,
)
from mania.pipeline_steps.workflow_runner import (
    run_notebook_export_graph_diagnostics_pipeline_from_config,
)


def load_notebook_export_graph_diagnostics_workflow_config(
    path: str | Path,
) -> NotebookExportGraphDiagnosticsWorkflowConfig:
    """Load a notebook export graph diagnostics workflow config file."""
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(config_path)
    if not config_path.is_file():
        raise ValueError(f"Workflow config path is not a file: {config_path}")

    payload = _load_config_payload(config_path)
    if not isinstance(payload, Mapping):
        raise ValueError("Workflow config file must contain an object")

    return NotebookExportGraphDiagnosticsWorkflowConfig.model_validate(dict(payload))


def run_notebook_export_graph_diagnostics_pipeline_from_config_file(
    path: str | Path,
) -> NotebookExportGraphDiagnosticsPipelineResult:
    """Load config from a file and run the composed workflow explicitly."""
    config = load_notebook_export_graph_diagnostics_workflow_config(path)
    return run_notebook_export_graph_diagnostics_pipeline_from_config(config)


def _load_config_payload(path: Path) -> object:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    if suffix in {".yaml", ".yml"}:
        with path.open("r", encoding="utf-8") as config_file:
            return yaml.safe_load(config_file)
    raise ValueError(f"Unsupported workflow config suffix: {path.suffix}")


__all__ = [
    "load_notebook_export_graph_diagnostics_workflow_config",
    "run_notebook_export_graph_diagnostics_pipeline_from_config_file",
]
