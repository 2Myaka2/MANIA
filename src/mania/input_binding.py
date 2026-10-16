"""Strict supplied input identities and portable, verified file bindings."""

from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from mania.canonical_reference import (
    AuthorityBinding,
    Digest,
    InputIdentity,
    ProteinReference,
    ReferenceIdentity,
    Text,
)
from mania.canonical_reference import _StrictModel as StrictModel
from mania.preprocessing.molecular_partner_metadata_io import read_strict_json
from mania.preprocessing.temporal_policy import (
    BoundaryProfile,
    require_boundary_profile,
)
from mania.preprocessing.trajectory_rmsd_io import file_sha256


def portable_path(value: str) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or PurePosixPath(value).is_absolute()
        or PureWindowsPath(value).drive
        or any(p in ("", ".", "..") for p in value.split("/"))
        or any(c in value for c in ("\\", ":", "~", "$", "%"))
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise ValueError("An exact portable relative POSIX path is required")
    return value


def member(root: Path, path: str) -> Path:
    portable_path(path)
    base = root.resolve(strict=True)
    target = base / path
    resolved = target.resolve(strict=True)
    if not resolved.is_relative_to(base) or not resolved.is_file():
        raise ValueError("Evidence must be a regular file inside its declared root")
    return resolved


class FileEvidence(StrictModel):
    role: Text
    path: Text
    size_bytes: Annotated[int, Field(ge=0)]
    sha256: Digest

    @model_validator(mode="after")
    def _path(self) -> Self:
        portable_path(self.path)
        return self

    def verify(self, root: Path) -> Path:
        path = member(root, self.path)
        if path.stat().st_size != self.size_bytes or file_sha256(path) != self.sha256:
            raise ValueError(f"Missing or changed evidence: {self.role}")
        return path


class FrameRequest(StrictModel):
    start: Annotated[int, Field(ge=0)]
    stop: Annotated[int, Field(ge=1)] | None
    stride: Annotated[int, Field(ge=1)]
    max_frames: Annotated[int, Field(ge=1)] | None
    indexes: tuple[Annotated[int, Field(ge=0)], ...] | None

    @model_validator(mode="after")
    def _order(self) -> Self:
        if self.stop is not None and self.stop <= self.start:
            raise ValueError("Frame stop must exceed start")
        if self.indexes is not None and (
            not self.indexes
            or list(self.indexes) != sorted(set(self.indexes))
            or (self.start, self.stop, self.stride, self.max_frames)
            != (0, None, 1, None)
        ):
            raise ValueError(
                "Explicit indexes require a unique increasing exclusive selector"
            )
        return self


class WindowRequest(StrictModel):
    length_ns: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    step_ns: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    overlap_percent: Annotated[float, Field(ge=0, lt=100, allow_inf_nan=False)]
    boundary_profile: BoundaryProfile

    @model_validator(mode="after")
    def _window(self) -> Self:
        from math import isclose

        from mania.preprocessing.physical_time_windows import (
            WINDOW_OVERLAP_PERCENT_ABS_TOLERANCE,
            WINDOW_OVERLAP_PERCENT_REL_TOLERANCE,
        )

        require_boundary_profile(self.boundary_profile)
        if self.step_ns > self.length_ns or not isclose(
            self.overlap_percent,
            100 * (1 - self.step_ns / self.length_ns),
            rel_tol=WINDOW_OVERLAP_PERCENT_REL_TOLERANCE,
            abs_tol=WINDOW_OVERLAP_PERCENT_ABS_TOLERANCE,
        ):
            raise ValueError("Inconsistent physical window parameters")
        return self


class PhysicalRequest(StrictModel):
    production_start_ns: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    production_end_ns: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    frame_stride_ps: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    windows: WindowRequest | None

    @model_validator(mode="after")
    def _interval(self) -> Self:
        if self.production_end_ns <= self.production_start_ns:
            raise ValueError("Production end must exceed start")
        return self


class Preparation(StrictModel):
    mode: Literal["nonperiodic", "prepared"]
    protocol: Text
    atom_order_preserved: bool
    frame_order_preserved: bool
    raw_sha256: Digest
    prepared_sha256: Digest
    evidence_sha256: Digest
    reviewer: Text | None
    note: Text | None


class InputBinding(StrictModel):
    schema_version: Literal["mania.input_binding.v1"]
    kind: Literal["mania_input_binding"]
    identity: InputIdentity
    files: tuple[FileEvidence, ...]
    reference: ReferenceIdentity | None
    mapping_sha256: Digest | None
    temporal_request: FrameRequest | PhysicalRequest
    preparation: Preparation | None

    @model_validator(mode="after")
    def _roles(self) -> Self:
        roles = [f.role for f in self.files]
        paths = [f.path for f in self.files]
        if not roles or len(set(roles)) != len(roles) or len(set(paths)) != len(paths):
            raise ValueError("Files require unique roles and paths")
        if (self.reference is None) != (self.mapping_sha256 is None):
            raise ValueError("Reference and mapping bindings must pair")
        return self

    def verify(self, root: Path) -> None:
        files = {f.role: f for f in self.files}
        for f in self.files:
            f.verify(root)
        if self.reference is not None:
            from mania.canonical_residue_mapping_io import read_residue_mapping

            if not {"reference", "residue_mapping"} <= files.keys():
                raise ValueError("Reference and mapping content evidence is required")
            ref = ProteinReference.model_validate_json(
                files["reference"].verify(root).read_bytes()
            )
            if ref.reference != self.reference:
                raise ValueError("Reference content identity mismatch")
            mapping = read_residue_mapping(
                files["residue_mapping"].verify(root), reference=ref
            )
            mapping.validate_reference(ref)
            if (
                mapping.identity != self.identity
                or files["residue_mapping"].sha256 != self.mapping_sha256
            ):
                raise ValueError("Mapping content identity or digest mismatch")
        if self.preparation is not None:
            prep = self.preparation
            if (
                not {"raw_trajectory", "prepared_trajectory", "preparation_evidence"}
                <= files.keys()
            ):
                raise ValueError("Preparation requires exact supplied source evidence")
            if (
                files["raw_trajectory"].sha256,
                files["prepared_trajectory"].sha256,
                files["preparation_evidence"].sha256,
            ) != (prep.raw_sha256, prep.prepared_sha256, prep.evidence_sha256):
                raise ValueError("Preparation source hashes disagree")


def verify_authority(
    root: Path, binding: AuthorityBinding, identity: InputIdentity | None
) -> Path:
    if binding.source_identity != identity:
        raise ValueError("Authority source identity differs")
    path = member(root, binding.path)
    if file_sha256(path) != binding.sha256:
        raise ValueError("Authority digest differs")
    return path


def read_input_binding(path: Path, *, root: Path) -> InputBinding:
    if not path.resolve(strict=True).is_relative_to(root.resolve(strict=True)):
        raise ValueError("Input document outside declared root")
    result = InputBinding.model_validate_json(path.read_bytes())
    # Duplicate keys are rejected before Pydantic sees the JSON.
    read_strict_json(path)
    result.verify(root)
    return result
