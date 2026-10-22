"""Closed target-only SASA counts, derived tables and semantic readback."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Annotated, Any, Literal, Self

from pydantic import BeforeValidator, Field, model_validator

from mania.preprocessing.trajectory_rmsd import SourceAtomKey, identity_digest
from mania.preprocessing.trajectory_rmsf_io import (
    ATOM_COLUMNS,
    RESIDUE_COLUMNS,
    SAMPLE_COLUMNS,
    MeasurementContext,
    Sample,
    csv_text,
    read_family,
    roster_digest,
    validate_roster,
    write_family,
)
from mania.preprocessing.trajectory_sasa import (
    GRID_ID,
    LEGACY_GRID_ID,
    LEGACY_GRID_SHA256,
    POINT_COUNT,
    _atom_areas_for_grid,
    grid_sha256,
)
from mania.preprocessing.trajectory_sasa_radii import (
    RADII,
    REGISTRY_SHA256,
    registry_record,
)
from mania.run_config import SASA, Digest, RunModel, _ordered

CSV_FILES = tuple(
    "sasa_" + name + ".csv"
    for name in (
        "atom_frames",
        "residue_frames",
        "total_frames",
        "atom_means",
        "residue_means",
        "total_means",
    )
)


class SurfaceCounts(RunModel):
    variant: Literal["isolated", "with_environment"]
    requested_sample_index: Annotated[int, Field(ge=0)]
    accessible_points: (
        Annotated[
            tuple[Annotated[int, Field(ge=0, le=3840)], ...], BeforeValidator(_ordered)
        ]
        | None
    )


class SASASampling(RunModel):
    """One global requested roster; local SASA positions never renumber sources."""

    global_samples: Annotated[tuple[Sample, ...], BeforeValidator(_ordered)]
    selected_global_ordinals: Annotated[
        tuple[Annotated[int, Field(ge=0)], ...], BeforeValidator(_ordered)
    ]
    global_requested_count: Annotated[int, Field(gt=0)]
    requested_count: Annotated[int, Field(gt=0)]
    observed_count: Annotated[int, Field(gt=0)]
    processed_count: Annotated[int, Field(gt=0)]
    missing_count: Annotated[int, Field(ge=0)]
    invalid_count: Annotated[int, Field(ge=0)]
    failed_count: Literal[0]
    unavailable_time_reason: Literal["source_time_unavailable"] | None


class SASAMeasurement(RunModel):
    schema_version: Literal["mania.sasa_measurement.v1"] = "mania.sasa_measurement.v1"
    kind: Literal["mania_sasa_measurement"] = "mania_sasa_measurement"
    context: MeasurementContext
    options: SASA
    sampling: SASASampling | None = None
    target_atoms: Annotated[tuple[SourceAtomKey, ...], BeforeValidator(_ordered)]
    environment_atoms: Annotated[tuple[SourceAtomKey, ...], BeforeValidator(_ordered)]
    target_identity_sha256: Digest
    environment_identity_sha256: Digest
    radius_registry: dict[str, Any]
    radius_registry_sha256: Digest
    used_radii_A: dict[str, float]
    grid_id: Literal["mania.sasa.fibonacci960.v1", "mania.sasa.fibonacci3840.v1"] = (
        GRID_ID
    )
    points_per_atom: Literal[960, 3840] = 3840
    grid_sha256: Digest
    precision: Literal["float64"] = "float64"
    occlusion: Literal["distance_squared < inflated_radius_squared"] = (
        "distance_squared < inflated_radius_squared"
    )
    unit: Literal["angstrom_squared"] = "angstrom_squared"
    counts: Annotated[tuple[SurfaceCounts, ...], BeforeValidator(_ordered)]
    csv_sha256: dict[str, Digest] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _measurement(self) -> Self:
        validate_roster(self.target_atoms, self.context.identity)
        with_environment = "with_environment" in self.options.variants
        if with_environment:
            validate_roster(self.environment_atoms, self.context.identity)
        elif self.environment_atoms:
            raise ValueError(
                "Isolated-only SASA cannot silently include environment atoms"
            )
        if {a.atom_index for a in self.target_atoms} & {
            a.atom_index for a in self.environment_atoms
        }:
            raise ValueError("SASA target and environment source atoms overlap")
        elements = {a.element for a in (*self.target_atoms, *self.environment_atoms)}
        if (
            not elements <= RADII.keys()
            or not self.options.enabled
            or (not self.options.include_hydrogens and "H" in elements)
            or self.used_radii_A != {e: RADII[e] for e in sorted(elements)}
            or self.radius_registry != registry_record()
            or self.radius_registry_sha256 != REGISTRY_SHA256
            or identity_digest(self.radius_registry) != self.radius_registry_sha256
            or (self.grid_id, self.points_per_atom, self.grid_sha256)
            not in (
                (LEGACY_GRID_ID, 960, LEGACY_GRID_SHA256),
                (GRID_ID, POINT_COUNT, grid_sha256()),
            )
            or self.target_identity_sha256 != roster_digest(self.target_atoms)
            or self.environment_identity_sha256 != roster_digest(self.environment_atoms)
        ):
            raise ValueError("SASA source/radius/H/grid/options contract differs")
        if self.sampling is None:
            if self.options.frame_stride != 1:
                raise ValueError("Legacy SASA requires the complete stride=1 roster")
            if any(
                a.path.startswith("atomic_sources/") for a in self.context.authority
            ):
                raise ValueError("New atomic sources require SASA sampling lineage")
        else:
            sampling = self.sampling
            # Validate the full global roster under the unchanged context contract.
            MeasurementContext.model_validate(
                {**self.context.model_dump(), "samples": sampling.global_samples}
            )
            ordinals = tuple(
                range(0, len(sampling.global_samples), self.options.frame_stride)
            )
            local = tuple(
                sampling.global_samples[index].model_copy(
                    update={"requested_sample_index": i}
                )
                for i, index in enumerate(ordinals)
            )
            observed = sum(sample.state == "observed" for sample in local)
            if (
                sampling.selected_global_ordinals != ordinals
                or self.context.samples != local
                or sampling.global_requested_count != len(sampling.global_samples)
                or sampling.requested_count != len(local)
                or sampling.observed_count != observed
                or sampling.processed_count != observed
                or sampling.missing_count != sum(s.state == "missing" for s in local)
                or sampling.invalid_count != sum(s.state == "invalid" for s in local)
                or (sampling.unavailable_time_reason is not None)
                != any(
                    s.state == "observed" and s.actual_time_ps is None for s in local
                )
            ):
                raise ValueError(
                    "SASA global/local selection/count/time contract differs"
                )
        expected = [
            (v, s.requested_sample_index)
            for v in self.options.variants
            for s in self.context.samples
        ]
        if [(c.variant, c.requested_sample_index) for c in self.counts] != expected:
            raise ValueError("SASA requires every ordered variant/sample")
        by_key = {}
        for c in self.counts:
            observed = (
                self.context.samples[c.requested_sample_index].state == "observed"
            )
            if observed != (c.accessible_points is not None) or (
                c.accessible_points is not None
                and (
                    len(c.accessible_points) != len(self.target_atoms)
                    or any(n > self.points_per_atom for n in c.accessible_points)
                )
            ):
                raise ValueError("SASA missing/zero/target population differs")
            by_key[c.variant, c.requested_sample_index] = c.accessible_points
        if set(self.options.variants) == {"isolated", "with_environment"}:
            for sample in self.context.samples:
                a = by_key["isolated", sample.requested_sample_index]
                b = by_key["with_environment", sample.requested_sample_index]
                if (
                    a is not None
                    and b is not None
                    and any(y > x for x, y in zip(a, b, strict=True))
                ):
                    raise ValueError("Environment increased target atom accessibility")
        if self.csv_sha256 and set(self.csv_sha256) != set(CSV_FILES):
            raise ValueError("Unknown or missing SASA CSV role")
        return self


def sasa_texts(measurement: SASAMeasurement) -> dict[str, str]:
    atoms = measurement.target_atoms
    elements = tuple(a.element for a in atoms)
    residues: dict[tuple[Any, ...], list[int]] = {}
    for i, atom in enumerate(atoms):
        data = atom.to_dict()
        residues.setdefault(tuple(data[k] for k in RESIDUE_COLUMNS), []).append(i)
    atom_rows, residue_rows, total_rows = [], [], []
    atom_means, residue_means, total_means = [], [], []
    for variant in measurement.options.variants:
        observed_areas = []
        for c in measurement.counts:
            if c.variant != variant:
                continue
            sample = measurement.context.samples[c.requested_sample_index]
            prefix = dict(variant=variant, **sample.model_dump())
            if measurement.sampling is not None:
                prefix.update(
                    global_requested_sample_index=measurement.sampling.selected_global_ordinals[
                        c.requested_sample_index
                    ],
                    actual_time_reason="source_time_unavailable"
                    if sample.state == "observed" and sample.actual_time_ps is None
                    else sample.reason,
                )
            areas = (
                None
                if c.accessible_points is None
                else _atom_areas_for_grid(
                    c.accessible_points,
                    elements,
                    measurement.options.probe_radius_A,
                    measurement.points_per_atom,
                )
            )
            if areas is not None:
                observed_areas.append(areas)
            for i, atom in enumerate(atoms):
                atom_rows.append(
                    dict(
                        **prefix,
                        **atom.to_dict(),
                        accessible_points=None
                        if c.accessible_points is None
                        else c.accessible_points[i],
                        sasa_A2=None if areas is None else areas[i],
                    )
                )
            for key, indexes in residues.items():
                residue_rows.append(
                    dict(
                        **prefix,
                        **dict(zip(RESIDUE_COLUMNS, key, strict=True)),
                        sasa_A2=None
                        if areas is None
                        else math.fsum(areas[i] for i in indexes),
                    )
                )
            total_rows.append(
                dict(**prefix, sasa_A2=None if areas is None else math.fsum(areas))
            )
        count = len(observed_areas)
        means = tuple(
            math.fsum(a[i] for a in observed_areas) / count for i in range(len(atoms))
        )
        for atom, value in zip(atoms, means, strict=True):
            atom_means.append(
                dict(
                    variant=variant,
                    **atom.to_dict(),
                    observed_frame_count=count,
                    mean_sasa_A2=value,
                )
            )
        for key, indexes in residues.items():
            residue_means.append(
                dict(
                    variant=variant,
                    **dict(zip(RESIDUE_COLUMNS, key, strict=True)),
                    observed_frame_count=count,
                    mean_sasa_A2=math.fsum(means[i] for i in indexes),
                )
            )
        total_means.append(
            dict(
                variant=variant,
                observed_frame_count=count,
                mean_sasa_A2=math.fsum(means),
            )
        )
    frame_columns: tuple[str, ...] = SAMPLE_COLUMNS
    if measurement.sampling is not None:
        frame_columns = (
            "global_requested_sample_index",
            *SAMPLE_COLUMNS,
            "actual_time_reason",
        )
    definitions = (
        (
            ("variant", *frame_columns, *ATOM_COLUMNS, "accessible_points", "sasa_A2"),
            atom_rows,
        ),
        (("variant", *frame_columns, *RESIDUE_COLUMNS, "sasa_A2"), residue_rows),
        (("variant", *frame_columns, "sasa_A2"), total_rows),
        (
            ("variant", *ATOM_COLUMNS, "observed_frame_count", "mean_sasa_A2"),
            atom_means,
        ),
        (
            ("variant", *RESIDUE_COLUMNS, "observed_frame_count", "mean_sasa_A2"),
            residue_means,
        ),
        (("variant", "observed_frame_count", "mean_sasa_A2"), total_means),
    )
    return {
        name: csv_text(columns, rows)
        for name, (columns, rows) in zip(CSV_FILES, definitions, strict=True)
    }


def write_sasa_measurement(
    measurement: SASAMeasurement, directory: Path
) -> SASAMeasurement:
    checked = SASAMeasurement.model_validate(measurement.model_dump())
    return write_family(
        checked, directory, "sasa_measurement.json", sasa_texts(checked)
    )


def read_sasa_measurement(directory: Path) -> SASAMeasurement:
    from mania.preprocessing.molecular_partner_metadata_io import read_strict_json
    from mania.preprocessing.trajectory_rmsd_io import portable_member

    filename = "sasa_measurement.json"
    data = read_strict_json(portable_member(directory, filename))
    if "sampling" in data:
        return read_family(directory, filename, SASAMeasurement, sasa_texts)
    # The only legacy omission is the approved additive default-1 sampling data.
    if "frame_stride" in data.get("options", {}):
        raise ValueError("New SASA options require the complete sampling field")
    result = SASAMeasurement.model_validate_json(json.dumps(data, allow_nan=False))
    if result.grid_id != LEGACY_GRID_ID:
        raise ValueError("Only historical 960 SASA may omit sampling fields")
    serialized = result.model_dump(mode="json")
    serialized.pop("sampling")
    serialized["options"].pop("frame_stride")
    if serialized != data:
        raise ValueError("Legacy SASA requires complete exact original fields")
    texts = sasa_texts(result)
    if result.csv_sha256 != {
        name: hashlib.sha256(value.encode()).hexdigest()
        for name, value in texts.items()
    }:
        raise ValueError("Legacy SASA semantic CSV digests differ")
    for name, value in texts.items():
        if portable_member(directory, name).read_bytes() != value.encode():
            raise ValueError("Legacy SASA semantic CSV content differs")
    return result
