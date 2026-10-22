"""Closed RMSF evidence and shared source/sample serialization primitives."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, Literal, Self, TypeVar, cast

from pydantic import BeforeValidator, Field, model_validator

from mania.canonical_reference import AuthorityBinding, InputIdentity
from mania.preprocessing.molecular_partner_metadata_io import read_strict_json
from mania.preprocessing.trajectory_rmsd import SourceAtomKey, _roster, identity_digest
from mania.preprocessing.trajectory_rmsd_io import atomic_json, portable_member
from mania.run_config import PBC, RMSF, Digest, RunModel, _ordered

ATOM_COLUMNS = tuple(SourceAtomKey.model_fields)
SAMPLE_COLUMNS = (
    "requested_sample_index",
    "requested_time_ps",
    "state",
    "runtime_frame_index",
    "source_frame_index",
    "prepared_frame_index",
    "actual_time_ps",
    "time_delta_ps",
    "reason",
)
RESIDUE_COLUMNS = (
    "engine",
    "chain_id",
    "segment_id",
    "resid",
    "insertion_code",
    "resname",
)
Finite = Annotated[float, Field(allow_inf_nan=False)]
Nonnegative = Annotated[float, Field(ge=0, allow_inf_nan=False)]
Vector = Annotated[tuple[Finite, Finite, Finite], BeforeValidator(_ordered)]
NonnegativeVector = Annotated[
    tuple[Nonnegative, Nonnegative, Nonnegative], BeforeValidator(_ordered)
]


class Sample(RunModel):
    requested_sample_index: Annotated[int, Field(ge=0)]
    requested_time_ps: Nonnegative | None
    state: Literal["observed", "missing", "invalid"]
    runtime_frame_index: Annotated[int, Field(ge=0)] | None
    source_frame_index: Annotated[int, Field(ge=0)] | None
    prepared_frame_index: Annotated[int, Field(ge=0)] | None
    actual_time_ps: Nonnegative | None
    time_delta_ps: Finite | None
    reason: str | None

    @model_validator(mode="after")
    def _state(self) -> Self:
        actual = (
            self.runtime_frame_index,
            self.source_frame_index,
            self.prepared_frame_index,
            self.actual_time_ps,
            self.time_delta_ps,
        )
        if self.state != "observed":
            if (
                any(v is not None for v in actual)
                or not self.reason
                or not self.reason.strip()
            ):
                raise ValueError(
                    "Missing/invalid samples require null actual values and reason"
                )
        else:
            if (
                self.runtime_frame_index is None
                or self.source_frame_index is None
                or self.reason is not None
            ):
                raise ValueError(
                    "Observed samples require source frame identity "
                    "and no failure reason"
                )
            expected = (
                None
                if self.actual_time_ps is None or self.requested_time_ps is None
                else self.actual_time_ps - self.requested_time_ps
            )
            if self.time_delta_ps != expected:
                raise ValueError("Actual/requested time delta differs")
        return self


class MeasurementContext(RunModel):
    identity: InputIdentity
    mode: Literal["basic", "custom", "full", "exploratory"]
    pbc: PBC
    sampling_kind: Literal["frame", "physical"]
    source_frame_count: Annotated[int, Field(gt=0)]
    authority: Annotated[tuple[AuthorityBinding, ...], BeforeValidator(_ordered)]
    samples: Annotated[tuple[Sample, ...], BeforeValidator(_ordered)]
    scientific_validation_status: Literal["SCIENTIFIC_VALIDATION_NOT_PERFORMED"] = (
        "SCIENTIFIC_VALIDATION_NOT_PERFORMED"
    )
    authoritative_release_eligible: Literal[False] = False
    pbc_status: Literal["PBC_UNVERIFIED"] | None

    @model_validator(mode="after")
    def _context(self) -> Self:
        if (self.pbc_status == "PBC_UNVERIFIED") != (self.pbc.mode == "unverified"):
            raise ValueError("PBC marker differs from declared source")
        if self.pbc.mode == "unverified" and self.mode != "exploratory":
            raise ValueError("Unverified PBC is exploratory only")
        if (
            not self.samples
            or [s.requested_sample_index for s in self.samples]
            != list(range(len(self.samples)))
            or any(s.state == "invalid" for s in self.samples)
        ):
            raise ValueError(
                "Measurement needs the complete ordered valid/missing "
                "requested sample roster"
            )
        observed = [s for s in self.samples if s.state == "observed"]
        indexes = [cast(int, s.runtime_frame_index) for s in observed]
        if (
            not indexes
            or indexes != sorted(set(indexes))
            or any(i is None or i >= self.source_frame_count for i in indexes)
        ):
            raise ValueError(
                "Observed frames must be unique ordered actual source indexes"
            )
        if self.sampling_kind == "physical" and any(
            s.requested_time_ps is None
            or (s.state == "observed" and s.actual_time_ps is None)
            for s in self.samples
        ):
            raise ValueError(
                "Physical sampling requires genuine requested/actual time identities"
            )
        if not {"topology", "trajectory"} <= {a.role for a in self.authority} or any(
            a.source_identity != self.identity for a in self.authority
        ):
            raise ValueError(
                "Exact topology/trajectory source authorities are required"
            )
        if len({(a.role, a.path) for a in self.authority}) != len(self.authority):
            raise ValueError("Duplicate method source authority")
        return self

    @property
    def observed_count(self) -> int:
        return sum(s.state == "observed" for s in self.samples)


def roster_digest(atoms: tuple[SourceAtomKey, ...]) -> str:
    return identity_digest([a.to_dict() for a in atoms])


def validate_roster(
    atoms: tuple[SourceAtomKey, ...], identity: InputIdentity, minimum: int = 1
) -> None:
    _roster(atoms, minimum)
    if any(a.engine != identity.engine for a in atoms) or tuple(
        a.atom_index for a in atoms
    ) != tuple(sorted(a.atom_index for a in atoms)):
        raise ValueError("Atom roster must preserve the exact ordered source identity")


class AtomStatistics(RunModel):
    atom: SourceAtomKey
    mean_A: Vector
    m2_A2: NonnegativeVector


class RMSFMeasurement(RunModel):
    schema_version: Literal["mania.rmsf_measurement.v1"] = "mania.rmsf_measurement.v1"
    kind: Literal["mania_rmsf_measurement"] = "mania_rmsf_measurement"
    context: MeasurementContext
    options: RMSF
    fit_atoms: Annotated[tuple[SourceAtomKey, ...], BeforeValidator(_ordered)]
    evaluation_atoms: Annotated[tuple[SourceAtomKey, ...], BeforeValidator(_ordered)]
    fit_identity_sha256: Digest
    evaluation_identity_sha256: Digest
    reference_kind: Literal["first_selected", "external"]
    reference_source: Annotated[int, Field(ge=0)] | AuthorityBinding
    reference_coordinate_sha256: Digest
    reference_fit_A: Annotated[tuple[Vector, ...], BeforeValidator(_ordered)]
    observed_frame_count: Annotated[int, Field(ge=2)]
    atoms: Annotated[tuple[AtomStatistics, ...], BeforeValidator(_ordered)]
    precision: Literal["float64"] = "float64"
    rotation: Literal["proper_Kabsch"] = "proper_Kabsch"
    weighting: Literal["equal"] = "equal"
    divisor: Literal["N"] = "N"
    unit: Literal["angstrom"] = "angstrom"
    csv_sha256: dict[str, Digest] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _measurement(self) -> Self:
        validate_roster(self.fit_atoms, self.context.identity, 3)
        validate_roster(self.evaluation_atoms, self.context.identity)
        from mania.preprocessing.trajectory_rmsf import fit_coordinates

        fit_coordinates(self.reference_fit_A, len(self.fit_atoms))
        if (
            len(self.reference_fit_A) != len(self.fit_atoms)
            or identity_digest(self.reference_fit_A) != self.reference_coordinate_sha256
        ):
            raise ValueError("RMSF reference coordinates/digest/fit population differ")
        if (
            self.fit_identity_sha256 != roster_digest(self.fit_atoms)
            or self.evaluation_identity_sha256 != roster_digest(self.evaluation_atoms)
            or tuple(a.atom for a in self.atoms) != self.evaluation_atoms
            or self.observed_frame_count != self.context.observed_count
            or not self.options.enabled
            or self.reference_kind != self.options.reference.kind
        ):
            raise ValueError("RMSF selection/options/N/digest contract differs")
        if self.reference_kind == "first_selected":
            first = self.context.samples[0]
            if (
                first.state != "observed"
                or type(self.reference_source) is not int
                or self.reference_source != first.source_frame_index
            ):
                raise ValueError(
                    "The actual first requested frame must remain "
                    "the alignment reference"
                )
        elif (
            not isinstance(self.reference_source, AuthorityBinding)
            or self.reference_source.source_identity != self.context.identity
            or self.reference_source not in self.context.authority
        ):
            raise ValueError(
                "External RMSF reference requires genuine source-bound authority"
            )
        if self.csv_sha256 and set(self.csv_sha256) != {
            "rmsf_atoms.csv",
            "rmsf_samples.csv",
        }:
            raise ValueError("Unknown or missing RMSF CSV role")
        return self

    @property
    def rmsf_A(self) -> tuple[float, ...]:
        return tuple(
            math.sqrt(sum(a.m2_A2) / self.observed_frame_count) for a in self.atoms
        )


def csv_text(columns: tuple[str, ...], rows: Any) -> str:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow(
            ""
            if row[k] is None
            else format(row[k], ".17g")
            if type(row[k]) is float
            else row[k]
            for k in columns
        )
    return stream.getvalue()


def rmsf_texts(measurement: RMSFMeasurement) -> dict[str, str]:
    rows = [
        dict(
            **a.to_dict(),
            rmsf_A=value,
            observed_frame_count=measurement.observed_frame_count,
        )
        for a, value in zip(
            measurement.evaluation_atoms, measurement.rmsf_A, strict=True
        )
    ]
    return {
        "rmsf_atoms.csv": csv_text(
            (*ATOM_COLUMNS, "rmsf_A", "observed_frame_count"), rows
        ),
        "rmsf_samples.csv": csv_text(
            SAMPLE_COLUMNS, [s.model_dump() for s in measurement.context.samples]
        ),
    }


Measurement = TypeVar("Measurement", bound=RunModel)


def write_family(
    measurement: Measurement, directory: Path, filename: str, texts: dict[str, str]
) -> Measurement:
    from mania.preprocessing.molecular_partner_metadata_io import write_atomic_text

    if any((directory / name).exists() for name in (*texts, filename)):
        raise ValueError("Existing scientific method artifacts are immutable")
    hashes = {
        name: hashlib.sha256(value.encode()).hexdigest()
        for name, value in texts.items()
    }
    sealed = type(measurement).model_validate(
        {**measurement.model_dump(), "csv_sha256": hashes}
    )
    for name, value in texts.items():
        if not write_atomic_text(value, directory / name, overwrite=False).passed:
            raise ValueError("Method CSV serialization failed")
    atomic_json(directory / filename, sealed.model_dump(mode="json"))
    return sealed


def read_family(
    directory: Path,
    filename: str,
    model: type[Measurement],
    render: Callable[[Measurement], dict[str, str]],
) -> Measurement:
    data = read_strict_json(portable_member(directory, filename))
    result = model.model_validate_json(json.dumps(data, allow_nan=False))
    if result.model_dump(mode="json") != data:
        raise ValueError("Method JSON requires complete exact closed fields")
    texts = render(result)
    if result.model_dump()["csv_sha256"] != {
        name: hashlib.sha256(value.encode()).hexdigest()
        for name, value in texts.items()
    }:
        raise ValueError("Method CSV validation digests differ from semantic values")
    for name, value in texts.items():
        if portable_member(directory, name).read_bytes() != value.encode():
            raise ValueError(
                "Method CSV schema/identity/sample/measurement/mean differs"
            )
    return result


def write_rmsf_measurement(
    measurement: RMSFMeasurement, directory: Path
) -> RMSFMeasurement:
    checked = RMSFMeasurement.model_validate(measurement.model_dump())
    return write_family(
        checked, directory, "rmsf_measurement.json", rmsf_texts(checked)
    )


def read_rmsf_measurement(directory: Path) -> RMSFMeasurement:
    return read_family(directory, "rmsf_measurement.json", RMSFMeasurement, rmsf_texts)
