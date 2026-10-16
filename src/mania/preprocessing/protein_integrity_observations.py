"""Producer observations only: no coordinate transformation or PBC verdict."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from mania.canonical_reference import Digest
from mania.canonical_reference import _StrictModel as StrictModel
from mania.dataset_identity import DatasetTrajectoryIdentity
from mania.preprocessing.molecular_partner_metadata_io import read_strict_json
from mania.preprocessing.trajectory_rmsd_io import FileBinding, atomic_json, bind_file


class IntegrityFrame(StrictModel):
    prepared_frame_index: Annotated[int, Field(ge=0)]
    source_frame_index: Annotated[int, Field(ge=0)]
    time_ps: Annotated[float, Field(ge=0)]
    protein_center_error_A: Annotated[float, Field(ge=0)]
    bond_representation_max_error_A: Annotated[float, Field(ge=0)] | None
    complete_fragment_fractional_min: float | None
    complete_fragment_fractional_max: float | None


class ProteinIntegrityObservations(StrictModel):
    schema_version: Literal["mania.protein_integrity_observations.v0.1"]
    kind: Literal["mania_protein_integrity_observations"]
    dataset_identity: DatasetTrajectoryIdentity
    scientific_pbc_status: Literal["unresolved"] = "unresolved"
    protocol: str
    preparation_report: FileBinding
    source_bindings: dict[str, FileBinding]
    atom_order_preserved: bool
    frame_order_preserved: bool
    exact_time_identity: bool
    cells_preserved: bool
    full_axis_preserved: bool
    observation_tolerance_A: Annotated[float, Field(gt=0)]
    protein_atom_identity_sha256: Digest | None
    protein_fragment_ids: list[int]
    protein_remains_broken: bool | None
    protein_integrity_assessment_source: str | None
    observations: list[IntegrityFrame]
    limitations: list[str]

    @model_validator(mode="after")
    def lineage(self) -> ProteinIntegrityObservations:
        if set(self.source_bindings) != {
            "topology",
            "raw_trajectory",
            "prepared_trajectory",
        }:
            raise ValueError("Protein integrity requires exact coordinate lineage")
        if not self.observations or [
            f.prepared_frame_index for f in self.observations
        ] != (list(range(len(self.observations)))):
            raise ValueError("Integrity evidence requires complete prepared frame map")
        indexes = [f.source_frame_index for f in self.observations]
        if indexes != sorted(set(indexes)):
            raise ValueError("Changed/reordered integrity source frame map")
        if self.full_axis_preserved and indexes != list(range(len(indexes))):
            raise ValueError("Full-axis preservation requires identity frame map")
        if self.protein_remains_broken is not None and (
            not self.protein_integrity_assessment_source
        ):
            raise ValueError("Explicit integrity bool requires a supplied authority")
        return self


def normalize_preparation_observations(
    identity: DatasetTrajectoryIdentity,
    report_path: Path,
    frames_path: Path,
    *,
    source_bindings: dict[str, FileBinding],
    report_portable_path: str,
    observation_tolerance_A: float,
) -> ProteinIntegrityObservations:
    """Keep the exact report immutable and retain only supported observations."""
    report = read_strict_json(report_path)
    frames = read_strict_json(frames_path)
    if report.get("trajectory_id") != identity.trajectory_id or (
        report.get("status") != "passed"
    ):
        raise ValueError("Preparation report replica/completion mismatch")
    if len(frames) != report["prepared_frames"]:
        raise ValueError("Preparation observations omit prepared frames")
    producer = report.get("protein_integrity_observations", {})
    observations = [
        IntegrityFrame(
            prepared_frame_index=f["prepared_frame_index"],
            source_frame_index=f["source_frame_index"],
            time_ps=float(f["time_ps"]),
            protein_center_error_A=float(f["protein_center_error_A"]),
            bond_representation_max_error_A=f.get("bond_representation_max_error_A"),
            complete_fragment_fractional_min=f.get("complete_fragment_fractional_min"),
            complete_fragment_fractional_max=f.get("complete_fragment_fractional_max"),
        )
        for f in frames
    ]
    if [f.source_frame_index for f in observations] != report["source_frame_indexes"]:
        raise ValueError("Preparation report/frame map mismatch")
    for role, key in (
        ("raw_trajectory", "source_xtc"),
        ("prepared_trajectory", "prepared_xtc"),
    ):
        original = report[key]
        bound = source_bindings[role]
        if (original["sha256"], original["size_bytes"]) != (
            bound.sha256,
            bound.byte_size,
        ):
            raise ValueError("Preparation source/prepared binding mismatch")
    return ProteinIntegrityObservations(
        schema_version="mania.protein_integrity_observations.v0.1",
        kind="mania_protein_integrity_observations",
        dataset_identity=identity,
        protocol=report["protocol"],
        preparation_report=bind_file(
            report_path, "evidence:preparation_report", report_portable_path
        ),
        source_bindings=source_bindings,
        atom_order_preserved=report["atom_order_preserved"],
        frame_order_preserved=report["frame_order_preserved"],
        exact_time_identity=report["exact_time_identity"],
        cells_preserved=report["cells_preserved"],
        full_axis_preserved=report["full_axis_preserved"],
        observation_tolerance_A=observation_tolerance_A,
        protein_atom_identity_sha256=producer.get("protein_atom_identity_sha256"),
        protein_fragment_ids=producer.get("protein_fragment_ids", []),
        protein_remains_broken=producer.get("protein_remains_broken"),
        protein_integrity_assessment_source=producer.get("assessment_source"),
        observations=observations,
        limitations=[
            "protocol_approval_is_distinct_from_trajectory_QC",
            "successful_contacts_do_not_establish_integrity",
            "missing_observations_are_not_inferred",
        ],
    )


def write_protein_integrity(path: Path, evidence: ProteinIntegrityObservations) -> None:
    atomic_json(path, evidence.model_dump(mode="json"))


def read_protein_integrity(path: Path) -> ProteinIntegrityObservations:
    return ProteinIntegrityObservations.model_validate(read_strict_json(path))


def validate_protein_integrity(
    evidence: ProteinIntegrityObservations,
    report_path: Path,
    frames_path: Path,
) -> None:
    expected = normalize_preparation_observations(
        evidence.dataset_identity,
        report_path,
        frames_path,
        source_bindings=evidence.source_bindings,
        report_portable_path=evidence.preparation_report.path or "",
        observation_tolerance_A=evidence.observation_tolerance_A,
    )
    if evidence != expected:
        raise ValueError(
            "Normalized integrity differs from immutable producer evidence"
        )
