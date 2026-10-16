"""Manifest skeleton helpers for MANIA exports."""

from __future__ import annotations

from dataclasses import dataclass

from mania import __version__
from mania.constants import (
    CROSS_CONDITION_ARTIFACTS,
    PER_CONDITION_ARTIFACTS,
    SCHEMA_VERSION,
)
from mania.pipeline import PipelinePlan


@dataclass(frozen=True)
class Manifest:
    """Immutable summary of a future MANIA export manifest."""

    schema_version: str
    mania_version: str
    project_name: str
    run_id: str
    run_mode: str
    conditions: tuple[str, ...]
    per_condition_artifacts: tuple[str, ...]
    cross_condition_artifacts: tuple[str, ...]


def build_manifest(plan: PipelinePlan) -> Manifest:
    """Build a manifest skeleton from a pipeline plan without filesystem I/O."""
    return Manifest(
        schema_version=SCHEMA_VERSION,
        mania_version=__version__,
        project_name=plan.project_name,
        run_id=plan.run_id,
        run_mode=plan.run_mode,
        conditions=plan.conditions,
        per_condition_artifacts=PER_CONDITION_ARTIFACTS,
        cross_condition_artifacts=CROSS_CONDITION_ARTIFACTS,
    )


def manifest_to_dict(manifest: Manifest) -> dict[str, object]:
    """Return a JSON-serializable dictionary for a manifest skeleton."""
    return {
        "schema_version": manifest.schema_version,
        "mania_version": manifest.mania_version,
        "project_name": manifest.project_name,
        "run_id": manifest.run_id,
        "run_mode": manifest.run_mode,
        "conditions": list(manifest.conditions),
        "per_condition_artifacts": list(manifest.per_condition_artifacts),
        "cross_condition_artifacts": list(manifest.cross_condition_artifacts),
    }


def format_manifest_summary(manifest: Manifest) -> str:
    """Format a manifest skeleton as a stable human-readable message."""
    return "\n".join(
        [
            "MANIA manifest skeleton",
            f"Project: {manifest.project_name}",
            f"Run ID: {manifest.run_id}",
            f"Run mode: {manifest.run_mode}",
            f"Conditions: {', '.join(manifest.conditions)}",
            f"Schema version: {manifest.schema_version}",
        ]
    )


__all__ = [
    "Manifest",
    "build_manifest",
    "format_manifest_summary",
    "manifest_to_dict",
]
