"""Pipeline planning placeholders for MANIA."""

from __future__ import annotations

from dataclasses import dataclass

from mania.config import MANIAConfig


@dataclass(frozen=True)
class PipelinePlan:
    """Typed summary of a future MANIA pipeline run."""

    project_name: str
    run_id: str
    run_mode: str
    conditions: tuple[str, ...]
    output_dir: str


def build_pipeline_plan(config: MANIAConfig) -> PipelinePlan:
    """Build a lightweight plan without executing pipeline stages."""
    return PipelinePlan(
        project_name=config.project.name,
        run_id=config.project.run_id,
        run_mode=config.runtime.run_mode,
        conditions=tuple(config.systems),
        output_dir=str(config.runtime.output_dir),
    )


def format_pipeline_plan(plan: PipelinePlan) -> str:
    """Format a pipeline plan as a stable human-readable message."""
    return "\n".join(
        [
            "MANIA pipeline execution is not implemented yet.",
            f"Project: {plan.project_name}",
            f"Run ID: {plan.run_id}",
            f"Run mode: {plan.run_mode}",
            f"Conditions: {', '.join(plan.conditions)}",
            f"Output directory: {plan.output_dir}",
        ]
    )
