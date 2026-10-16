"""Run metadata skeleton helpers for MANIA exports."""

from __future__ import annotations

from dataclasses import dataclass

from mania import __version__
from mania.constants import SCHEMA_VERSION
from mania.pipeline import PipelinePlan


@dataclass(frozen=True)
class RunMeta:
    """Immutable summary of a future MANIA run metadata file."""

    schema_version: str
    mania_version: str
    project_name: str
    run_id: str
    run_mode: str
    conditions: tuple[str, ...]
    output_dir: str


def build_run_meta(plan: PipelinePlan) -> RunMeta:
    """Build run metadata from a pipeline plan without filesystem I/O."""
    return RunMeta(
        schema_version=SCHEMA_VERSION,
        mania_version=__version__,
        project_name=plan.project_name,
        run_id=plan.run_id,
        run_mode=plan.run_mode,
        conditions=plan.conditions,
        output_dir=plan.output_dir,
    )


def run_meta_to_dict(run_meta: RunMeta) -> dict[str, object]:
    """Return a JSON-serializable dictionary for run metadata."""
    return {
        "schema_version": run_meta.schema_version,
        "mania_version": run_meta.mania_version,
        "project_name": run_meta.project_name,
        "run_id": run_meta.run_id,
        "run_mode": run_meta.run_mode,
        "conditions": list(run_meta.conditions),
        "output_dir": run_meta.output_dir,
    }


def format_run_meta_summary(run_meta: RunMeta) -> str:
    """Format run metadata as a stable human-readable message."""
    return "\n".join(
        [
            "MANIA run metadata skeleton",
            f"Project: {run_meta.project_name}",
            f"Run ID: {run_meta.run_id}",
            f"Run mode: {run_meta.run_mode}",
            f"Conditions: {', '.join(run_meta.conditions)}",
            f"Output directory: {run_meta.output_dir}",
            f"Schema version: {run_meta.schema_version}",
        ]
    )


__all__ = [
    "RunMeta",
    "build_run_meta",
    "format_run_meta_summary",
    "run_meta_to_dict",
]
