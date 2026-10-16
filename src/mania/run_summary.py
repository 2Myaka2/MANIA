"""True result summaries; completion is derived from actual method states."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BeforeValidator, field_validator, model_validator

from mania.method_status import MethodStatus
from mania.run_config import Digest, RunModel, Text, _ordered
from mania.run_plan import PathIdentity, SelectedExtension
from mania.scientific_qualification import ScientificQualificationV1


class ArtifactReference(RunModel):
    role: str
    path: str
    schema_version: str | None
    sha256: Digest | None

    @field_validator("path")
    @classmethod
    def _portable(cls, value: str) -> str:
        from mania.input_binding import portable_path

        return portable_path(value)


class RunSummary(RunModel):
    schema_version: Literal["mania.run_summary.v1"] = "mania.run_summary.v1"
    kind: Literal["mania_run_summary"] = "mania_run_summary"
    project: str
    mode: Literal["basic", "custom", "full"]
    run_id: str
    status: Literal[
        "completed", "completed_with_skips", "pending_review", "failed", "cancelled"
    ]
    methods: Annotated[tuple[MethodStatus, ...], BeforeValidator(_ordered)]
    path_identity_map: Annotated[tuple[PathIdentity, ...], BeforeValidator(_ordered)]
    artifact_references: Annotated[
        tuple[ArtifactReference, ...], BeforeValidator(_ordered)
    ]
    selected_extensions: Annotated[
        tuple[SelectedExtension, ...], BeforeValidator(_ordered)
    ]
    provenance_path: str = "provenance/run_provenance.json"
    inventory_path: str = "provenance/artifact_inventory.json"
    runtime_metadata_path: str = "provenance/runtime_metadata.json"


class ExploratoryRunSummary(RunModel):
    schema_version: Literal["mania.run_summary.v2"] = "mania.run_summary.v2"
    kind: Literal["mania_run_summary"] = "mania_run_summary"
    project: Text
    mode: Literal["exploratory"]
    run_id: Text
    status: Literal[
        "completed", "completed_with_skips", "pending_review", "failed", "cancelled"
    ]
    methods: Annotated[tuple[MethodStatus, ...], BeforeValidator(_ordered)]
    path_identity_map: Annotated[tuple[PathIdentity, ...], BeforeValidator(_ordered)]
    artifact_references: Annotated[
        tuple[ArtifactReference, ...], BeforeValidator(_ordered)
    ]
    selected_extensions: Annotated[
        tuple[SelectedExtension, ...], BeforeValidator(_ordered)
    ]
    provenance_path: str = "provenance/run_provenance.json"
    inventory_path: str = "provenance/artifact_inventory.json"
    runtime_metadata_path: str = "provenance/runtime_metadata.json"

    scientific_qualification: ScientificQualificationV1

    @field_validator("provenance_path", "inventory_path", "runtime_metadata_path")
    @classmethod
    def _paths(cls, value: str) -> str:
        from mania.input_binding import portable_path

        return portable_path(value)

    @model_validator(mode="after")
    def _qualification_binding(self) -> ExploratoryRunSummary:
        qualification = self.scientific_qualification
        if tuple(s.input_identity for s in qualification.source_scopes) != tuple(
            p.input_identity for p in self.path_identity_map
        ):
            raise ValueError("Summary qualification source roster/order differs")
        if tuple(
            (s.method_id, s.identity, s.execution_status)
            for s in qualification.method_scopes
        ) != tuple((s.method_id, s.identity, s.status) for s in self.methods):
            raise ValueError("Summary qualification method roster/status differs")
        references = {(a.role, a.path) for a in self.artifact_references}
        if any(
            (a.role, a.path) not in references for a in qualification.artifact_scopes
        ):
            raise ValueError("Summary qualification contains an unowned artifact")
        return self


def overall_status(
    methods: tuple[MethodStatus, ...],
) -> Literal[
    "completed", "completed_with_skips", "pending_review", "failed", "cancelled"
]:
    states = {s.status for s in methods}
    if "failed" in states:
        return "failed"
    if "cancelled" in states:
        return "cancelled"
    if "pending_review" in states:
        return "pending_review"
    if states & {"planned", "running"}:
        raise ValueError("Unfinished requested methods cannot seal a completed run")
    if "missing_optional_input" in states or "not_applicable" in states:
        return "completed_with_skips"
    return "completed"


def write_summary(summary: RunSummary | ExploratoryRunSummary, root: Path) -> None:
    from mania.preprocessing.trajectory_rmsd_io import atomic_json

    atomic_json(root / "summary.json", summary.model_dump(mode="json"))
