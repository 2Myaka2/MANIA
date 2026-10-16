"""Explicit fit/evaluation RMSD and source-exact same-set numerical helpers."""

from __future__ import annotations

import hashlib
import importlib
import json
from dataclasses import dataclass
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from mania.canonical_reference import (
    AuthorityBinding,
    InputIdentity,
    Text,
    _StrictModel,
)


def identity_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode()
    ).hexdigest()


class SourceAtomKey(_StrictModel):
    engine: Literal["gromacs", "namd"]
    chain_id: Text | None
    segment_id: Text | None
    resid: Text
    insertion_code: Text | None
    resname: Text
    atom_name: Text
    element: Text
    atom_index: int = Field(ge=0)
    altloc: Text | None


def _roster(atoms: tuple[SourceAtomKey, ...], minimum: int) -> None:
    if (
        type(atoms) is not tuple
        or len(atoms) < minimum
        or any(type(a) is not SourceAtomKey for a in atoms)
        or len(set(atoms)) != len(atoms)
        or len({a.atom_index for a in atoms}) != len(atoms)
    ):
        raise ValueError("Explicit unique ordered atom correspondence is required")


def _evaluation_coordinates(value: Any, count: int) -> Any:
    np = importlib.import_module("numpy")
    try:
        xyz = np.array(value, dtype=np.float64, copy=True)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("Malformed evaluation coordinates") from exc
    if count < 1 or xyz.shape != (count, 3) or not np.isfinite(xyz).all():
        raise ValueError("Evaluation requires at least one finite corresponding atom")
    return xyz


def fit_evaluation_rmsd(
    fit: Any, reference_fit: Any, evaluation: Any, reference_evaluation: Any
) -> float:
    """Derive the proper transform only from fit; never refit evaluation."""
    np = importlib.import_module("numpy")
    x = coordinates_float64(fit, len(reference_fit))
    y = coordinates_float64(reference_fit, len(reference_fit))
    a = _evaluation_coordinates(evaluation, len(reference_evaluation))
    b = _evaluation_coordinates(reference_evaluation, len(reference_evaluation))
    x_center = x.mean(axis=0)
    y_center = y.mean(axis=0)
    u, _, vt = np.linalg.svd((x - x_center).T @ (y - y_center))
    correction = np.eye(3, dtype=np.float64)
    correction[2, 2] = 1.0 if np.linalg.det(u @ vt) >= 0 else -1.0
    rotation = u @ correction @ vt
    delta = (a - x_center) @ rotation + y_center - b
    result = float(np.sqrt(np.sum(delta * delta, dtype=np.float64) / len(b)))
    if not np.isfinite(result) or result < 0:
        raise ValueError("Nonfinite evaluation RMSD")
    return result


class RMSDRow(_StrictModel):
    requested_sample_index: int = Field(ge=0)
    requested_time_ps: float | None = Field(ge=0)
    state: Literal["missing", "resolved"]
    runtime_frame_index: int | None = Field(ge=0)
    source_frame_index: int | None = Field(ge=0)
    prepared_frame_index: int | None = Field(ge=0)
    actual_time_ps: float | None = Field(ge=0)
    time_delta_ps: float | None
    rmsd_A: float | None = Field(ge=0)

    @model_validator(mode="after")
    def _state(self) -> Self:
        import math

        values = (
            self.requested_time_ps,
            self.actual_time_ps,
            self.time_delta_ps,
            self.rmsd_A,
        )
        if any(v is not None and not math.isfinite(v) for v in values):
            raise ValueError("RMSD numeric fields must be finite")
        observed = (
            self.runtime_frame_index,
            self.source_frame_index,
            self.prepared_frame_index,
            self.actual_time_ps,
            self.time_delta_ps,
            self.rmsd_A,
        )
        if self.state == "missing" and any(v is not None for v in observed):
            raise ValueError("Missing sample measurements must be null")
        if self.state == "resolved":
            if (
                self.runtime_frame_index is None
                or self.source_frame_index is None
                or self.rmsd_A is None
            ):
                raise ValueError(
                    "Resolved sample requires frame identity and measurement"
                )
            if self.actual_time_ps is None or self.requested_time_ps is None:
                if self.time_delta_ps is not None:
                    raise ValueError("Unavailable time cannot have a delta")
            elif self.time_delta_ps != self.actual_time_ps - self.requested_time_ps:
                raise ValueError("RMSD time delta mismatch")
        return self


class _RMSDParameters(_StrictModel):
    rotation: Literal["proper_Kabsch"]
    weighting: Literal["equal"]
    unit: Literal["angstrom"]


class RMSDMeasurement(_StrictModel):
    schema_version: Literal["mania.rmsd.v1"]
    kind: Literal["mania_rmsd_measurement"]
    identity: InputIdentity
    sampling_kind: Literal["frame", "physical"]
    fit_atoms: tuple[SourceAtomKey, ...]
    evaluation_atoms: tuple[SourceAtomKey, ...]
    fit_identity_sha256: str
    evaluation_identity_sha256: str
    reference_kind: Literal["first_selected", "external"]
    reference_source: int | AuthorityBinding
    reference_coordinate_sha256: str
    parameters: _RMSDParameters
    rows: tuple[RMSDRow, ...]
    authority: tuple[AuthorityBinding, ...]

    @model_validator(mode="after")
    def _contract(self) -> Self:
        import re

        _roster(self.fit_atoms, 3)
        _roster(self.evaluation_atoms, 1)
        for name, atoms in (
            ("fit_identity_sha256", self.fit_atoms),
            ("evaluation_identity_sha256", self.evaluation_atoms),
        ):
            if getattr(self, name) != identity_digest([a.to_dict() for a in atoms]):
                raise ValueError("RMSD ordered identity digest mismatch")
        if re.fullmatch(r"[0-9a-f]{64}", self.reference_coordinate_sha256) is None:
            raise ValueError("Invalid reference coordinate digest")
        if any(
            a.engine != self.identity.engine
            for a in (*self.fit_atoms, *self.evaluation_atoms)
        ):
            raise ValueError("RMSD atom/trajectory engine mismatch")
        indexes = [r.requested_sample_index for r in self.rows]
        if not indexes or indexes != sorted(set(indexes)):
            raise ValueError("RMSD rows must be nonempty, unique and ordered")
        resolved = [r for r in self.rows if r.state == "resolved"]
        if not resolved:
            raise ValueError("RMSD requires an observed sample")
        if self.sampling_kind == "physical" and any(
            r.requested_time_ps is None
            or (
                r.state == "resolved"
                and any(v is None for v in (r.actual_time_ps, r.time_delta_ps))
            )
            for r in self.rows
        ):
            raise ValueError("Physical RMSD requires complete time identity")
        if self.reference_kind == "first_selected":
            if (
                type(self.reference_source) is not int
                or self.reference_source != resolved[0].source_frame_index
            ):
                raise ValueError(
                    "First-selected reference requires its explicit source frame"
                )
        elif (
            type(self.reference_source) is not AuthorityBinding
            or self.reference_source.source_identity is None
        ):
            raise ValueError(
                "External reference requires explicit source-bound authority"
            )
        if not any(a.source_identity == self.identity for a in self.authority) or any(
            a.source_identity is not None and a.source_identity != self.identity
            for a in self.authority
        ):
            raise ValueError("RMSD requires exact trajectory authority")
        return self


@dataclass(frozen=True)
class RMSDCoordinates:
    fit_atoms: tuple[SourceAtomKey, ...]
    evaluation_atoms: tuple[SourceAtomKey, ...]
    fit: Any
    evaluation: Any


@dataclass(frozen=True)
class RMSDFrame:
    row: RMSDRow
    coordinates: RMSDCoordinates | None


def measure_rmsd(
    frames: tuple[RMSDFrame, ...],
    *,
    identity: InputIdentity,
    fit_selection: tuple[SourceAtomKey, ...],
    evaluation_selection: tuple[SourceAtomKey, ...],
    reference: RMSDCoordinates | Literal["first_selected"],
    reference_source: int | AuthorityBinding,
    sampling_kind: Literal["frame", "physical"],
    authority: tuple[AuthorityBinding, ...],
) -> RMSDMeasurement:
    """Measure explicit matched sets; input row rmsd_A is a placeholder of 0.0."""
    _roster(fit_selection, 3)
    _roster(evaluation_selection, 1)
    if (
        type(frames) is not tuple
        or not frames
        or any(type(f) is not RMSDFrame for f in frames)
    ):
        raise ValueError("Explicit ordered RMSD frames are required")
    first = next((f for f in frames if f.row.state == "resolved"), None)
    if first is None:
        raise ValueError("RMSD requires a resolved frame")
    kind: Literal["first_selected", "external"] = (
        "first_selected" if isinstance(reference, str) else "external"
    )
    if isinstance(reference, str):
        if reference != "first_selected":
            raise ValueError("Unknown explicit reference choice")
        ref = first.coordinates
    else:
        ref = reference
    if type(ref) is not RMSDCoordinates:
        raise ValueError("Explicit reference coordinates are required")

    def matched(c: RMSDCoordinates) -> None:
        if c.fit_atoms != fit_selection or c.evaluation_atoms != evaluation_selection:
            raise ValueError("Changed ordered fit/evaluation correspondence")

    matched(ref)
    rf = coordinates_float64(ref.fit, len(fit_selection))
    reval = _evaluation_coordinates(ref.evaluation, len(evaluation_selection))
    coordinate_digest = hashlib.sha256(
        rf.astype("<f8", copy=False).tobytes(order="C")
        + reval.astype("<f8", copy=False).tobytes(order="C")
    ).hexdigest()
    rows = []
    for f in frames:
        RMSDRow.model_validate(f.row.model_dump())
        if f.row.state == "missing":
            if f.coordinates is not None:
                raise ValueError("Missing frame cannot contain coordinates")
            rows.append(f.row)
        else:
            if type(f.coordinates) is not RMSDCoordinates or f.row.rmsd_A != 0.0:
                raise ValueError(
                    "Resolved frame requires coordinates and zero placeholder"
                )
            matched(f.coordinates)
            value = fit_evaluation_rmsd(
                f.coordinates.fit, rf, f.coordinates.evaluation, reval
            )
            rows.append(RMSDRow.model_validate({**f.row.model_dump(), "rmsd_A": value}))
    return RMSDMeasurement(
        schema_version="mania.rmsd.v1",
        kind="mania_rmsd_measurement",
        identity=identity,
        sampling_kind=sampling_kind,
        fit_atoms=fit_selection,
        evaluation_atoms=evaluation_selection,
        fit_identity_sha256=identity_digest([a.to_dict() for a in fit_selection]),
        evaluation_identity_sha256=identity_digest(
            [a.to_dict() for a in evaluation_selection]
        ),
        reference_kind=kind,
        reference_source=reference_source,
        reference_coordinate_sha256=coordinate_digest,
        parameters=_RMSDParameters(
            rotation="proper_Kabsch", weighting="equal", unit="angstrom"
        ),
        rows=tuple(rows),
        authority=authority,
    )


def coordinates_float64(value: Any, atom_count: int) -> Any:
    np = importlib.import_module("numpy")
    try:
        xyz = np.array(value, dtype=np.float64, copy=True)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Malformed RMSD coordinates") from exc
    if xyz.shape != (atom_count, 3) or atom_count < 3 or not np.isfinite(xyz).all():
        raise ValueError("RMSD needs finite N x 3 coordinates and at least 3 atoms")
    centered = xyz - xyz.mean(axis=0)
    if not np.isfinite(centered).all() or np.linalg.matrix_rank(centered) < 2:
        raise ValueError("Rigid alignment requires at least two independent axes")
    return xyz


def fitted_rmsd(coordinates: Any, reference: Any) -> float:
    """SVD Kabsch with a determinant +1 row-vector rotation, in angstrom."""
    np = importlib.import_module("numpy")
    try:
        count = len(reference)
    except TypeError as exc:
        raise ValueError("Malformed RMSD reference") from exc
    x = coordinates_float64(coordinates, count)
    y = coordinates_float64(reference, count)
    x -= x.mean(axis=0)
    y -= y.mean(axis=0)
    u, _, vt = np.linalg.svd(x.T @ y)
    correction = np.eye(3, dtype=np.float64)
    correction[2, 2] = 1.0 if np.linalg.det(u @ vt) >= 0 else -1.0
    rotation = u @ correction @ vt
    delta = x @ rotation - y
    result = float(np.sqrt(np.sum(delta * delta, dtype=np.float64) / count))
    if not np.isfinite(result) or result < 0:
        raise ValueError("Nonfinite fitted RMSD")
    return result
