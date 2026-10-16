"""Explicit fixed profile prerequisites and opt-in legacy mapped-C-alpha RMSD."""

from __future__ import annotations

import csv
import hashlib
import importlib
import importlib.metadata
import io
import json
import platform
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from mania.biological_annotations import SystemAnnotations
from mania.canonical_reference import InputIdentity, _StrictModel
from mania.canonical_reference import Text as BindingText
from mania.dataset_identity import DatasetTrajectoryIdentity
from mania.extensions import ExtensionContribution, ExtensionMetadata
from mania.input_binding import FileEvidence
from mania.preprocessing.molecular_partner_metadata_io import (
    read_strict_json,
    write_atomic_text,
)
from mania.preprocessing.physical_time_execution import (
    PreprocessingConditionTemporalExecution,
)
from mania.preprocessing.physical_time_execution_io import (
    read_preprocessing_temporal_execution,
)
from mania.preprocessing.trajectory_rmsd import (
    coordinates_float64 as coordinates_float64,
)
from mania.preprocessing.trajectory_rmsd import (
    fitted_rmsd as fitted_rmsd,
)
from mania.preprocessing.trajectory_rmsd import (
    identity_digest,
)
from mania.preprocessing.trajectory_rmsd_io import (
    _require_portable_path,
    file_sha256,
    portable_member,
)
from mania.result_readers import WindowInputBinding
from mania.software_identity import get_software_identity
from mania_napi2b.biological_annotations import DatasetSystemBiologicalAnnotations
from mania_napi2b.canonical_reference import CanonicalProteinReference
from mania_napi2b.canonical_reference_io import load_default_napi2b_canonical_reference
from mania_napi2b.canonical_residue_mapping import (
    CANONICAL_RESIDUE_MAPPING_REFERENCE_ID,
    CANONICAL_RESIDUE_MAPPING_REFERENCE_SHA256,
    CanonicalResidueMappingTable,
    validate_canonical_residue_mapping_table,
)


def _reference(value: object) -> object:
    if type(value) is not CanonicalProteinReference:
        raise ValueError("Exact fixed reference required")
    value.__post_init__()
    return value


def _annotations(value: object) -> object:
    if type(value) is not DatasetSystemBiologicalAnnotations:
        raise ValueError("Exact complete fixed system annotations required")
    value.__post_init__()
    return value


def get_extension(
    *, include_legacy_rmsd: bool = False
) -> tuple[ExtensionContribution, ...]:
    """Return fresh immutable declarations, without executing scientific methods."""
    declared = ExtensionMetadata(
        id="napi2b",
        distribution="mania-napi2b",
        version="0.2.0",
        api_version="mania.extension_api.v1",
        core_version_spec="==0.2.0",
        profile_ids=("napi2b.legacy.v1", "napi2b.dataset.v1"),
        schema_ids=(
            "mania.canonical_reference.v0.1",
            "mania.canonical_residue_mapping.v0.1",
            "mania.dataset_system_biological_annotations.v0.1",
        ),
        method_ids=(CONTRACT_ID,) if include_legacy_rmsd else (),
    )
    return tuple(
        ExtensionContribution(
            metadata=declared,
            profile_id=profile,
            reference_factories={
                "uniprotkb:O95436-1:sequence-v3": (
                    load_default_napi2b_canonical_reference
                ),
            },
            policy_factories={},
            schema_validators={
                "mania.canonical_reference.v0.1": _reference,
                "mania.canonical_residue_mapping.v0.1": (
                    validate_canonical_residue_mapping_table
                ),
                "mania.dataset_system_biological_annotations.v0.1": _annotations,
            },
            method_callables=(
                {CONTRACT_ID: create_legacy_rmsd_accumulator}
                if include_legacy_rmsd and profile == "napi2b.legacy.v1"
                else {}
            ),
        )
        for profile in declared.profile_ids
    )


CONTRACT_ID = "mania.production_ca_rmsd.v1"


ALGORITHM_ID = "kabsch_equal_weight_proper_rotation_float64_v1"


METHOD = {
    "algorithm_id": ALGORITHM_ID,
    "weights": "equal",
    "center": "arithmetic_centroid",
    "rotation": "proper_only",
    "reflection": "forbidden",
    "dtype": "float64",
    "coordinate_unit": "angstrom",
    "time_unit": "ps",
    "formula": "sqrt(sum_i(||X_centered_i @ R - reference_centered_i||^2)/N)",
    "convention": "row_vectors",
    "rank_policy": "at_least_3_atoms; rank_at_least_2; tolerance=eps*max(shape)*smax",
    "serializer_precision": ".17g",
    "nonfinite_policy": "fail",
    "automatic_drift_classification": False,
}


Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


Index = Annotated[int, Field(ge=0)]


Text = Annotated[str, Field(min_length=1)]


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, frozen=True, allow_inf_nan=False
    )


class SelectedAtom(StrictModel):
    canonical_residue_number: Annotated[int, Field(ge=1, le=690)]
    canonical_resname: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
    source_engine: Literal["gromacs", "namd"]
    source_chain_id: str | None
    source_resid: Text
    source_resname: Text
    topology_residue_index: Index
    topology_atom_index: Index
    topology_atom_id: int | None
    atom_name: Literal["CA"] = "CA"
    element: Literal["C"] = "C"
    source_segid: str | None
    source_chainID: str | None


class AtomSelection(StrictModel):
    selection_id: Digest
    ordering: Literal["canonical_residue_number"] = "canonical_residue_number"
    atom_count: Annotated[int, Field(ge=3)]
    canonical_reference_id: str
    canonical_reference_sequence_sha256: Digest
    selected_identity_sha256: Digest
    not_represented_canonical_positions: list[int]
    atoms: list[SelectedAtom]

    @model_validator(mode="after")
    def validate_roster(self) -> AtomSelection:
        if self.canonical_reference_id != CANONICAL_RESIDUE_MAPPING_REFERENCE_ID or (
            self.canonical_reference_sequence_sha256
            != CANONICAL_RESIDUE_MAPPING_REFERENCE_SHA256
        ):
            raise ValueError("Canonical reference mismatch")
        positions = [a.canonical_residue_number for a in self.atoms]
        if positions != sorted(set(positions)) or len(positions) != self.atom_count:
            raise ValueError("Duplicate, reordered or incomplete canonical atom roster")
        if len({a.topology_atom_index for a in self.atoms}) != self.atom_count or (
            len({a.topology_residue_index for a in self.atoms}) != self.atom_count
        ):
            raise ValueError("Duplicate topology atom/residue identity")
        digest = identity_digest([a.model_dump(mode="json") for a in self.atoms])
        if digest != self.selection_id or digest != self.selected_identity_sha256:
            raise ValueError("Changed selection identity")
        if self.not_represented_canonical_positions != [
            i for i in range(1, 691) if i not in positions
        ]:
            raise ValueError("Absent canonical positions disagree with present roster")
        return self


def optional_attribute(obj: Any, name: str) -> Any:
    try:
        return getattr(obj, name)
    except (AttributeError, LookupError):
        return None


def validate_selection_mapping(
    selection: AtomSelection, mapping: CanonicalResidueMappingTable
) -> None:
    """Check every retained atom against its exact explicit source mapping."""
    from mania_napi2b.canonical_reference_io import (
        load_default_napi2b_canonical_reference,
    )
    from mania_napi2b.canonical_residue_mapping import (
        validate_canonical_residue_mapping_table,
    )

    validate_canonical_residue_mapping_table(
        mapping, reference=load_default_napi2b_canonical_reference()
    )
    records = {r.source_key: r for r in mapping.mappings}
    for atom in selection.atoms:
        mapped = records.get(
            (
                atom.source_engine,
                atom.source_chain_id,
                atom.source_resid,
                atom.source_resname,
            )
        )
        if (
            mapped is None
            or mapped.mapping_status != "mapped"
            or (
                mapped.canonical_residue_number != atom.canonical_residue_number
                or mapped.canonical_resname != atom.canonical_resname
                or atom.source_segid != atom.source_chain_id
            )
        ):
            raise ValueError(
                "RMSD atom roster disagrees with explicit canonical mapping"
            )


def atom_identity(atom: Any, mapped: Any, engine: str) -> SelectedAtom:
    residue = atom.residue
    segid = optional_attribute(residue, "segid") or None
    chain = optional_attribute(atom, "chainID") or None
    atom_id = optional_attribute(atom, "id")
    return SelectedAtom(
        canonical_residue_number=mapped.canonical_residue_number,
        canonical_resname=mapped.canonical_resname,
        source_engine=mapped.source_engine,
        source_chain_id=segid,
        source_resid=str(residue.resid),
        source_resname=str(residue.resname),
        topology_residue_index=int(residue.ix),
        topology_atom_index=int(atom.index),
        topology_atom_id=int(atom_id) if atom_id is not None else None,
        source_segid=segid,
        source_chainID=chain,
    )


def select_mapped_ca_atoms(
    universe: Any,
    mapping: CanonicalResidueMappingTable,
    engine: str,
) -> tuple[AtomSelection, tuple[Any, ...]]:
    """Bind every present protein residue by its complete source namespace."""
    records = {r.source_key: r for r in mapping.mappings}
    selected = []
    for residue in universe.select_atoms("protein").residues:
        key = (
            engine,
            optional_attribute(residue, "segid") or None,
            str(residue.resid),
            str(residue.resname),
        )
        mapped = records.get(key)
        if mapped is None or mapped.mapping_status != "mapped":
            raise ValueError(f"Incomplete explicit protein mapping: {key}")
        candidates = [a for a in residue.atoms if a.name == "CA"]
        if (
            len(candidates) != 1
            or str(optional_attribute(candidates[0], "element")).upper() != "C"
        ):
            raise ValueError("Every mapped present residue requires one CA carbon")
        atom = candidates[0]
        selected.append((atom_identity(atom, mapped, engine), atom))
    selected.sort(key=lambda pair: pair[0].canonical_residue_number)
    atoms = [pair[0] for pair in selected]
    digest = identity_digest([a.model_dump(mode="json") for a in atoms])
    positions = {a.canonical_residue_number for a in atoms}
    selection = AtomSelection(
        selection_id=digest,
        selected_identity_sha256=digest,
        atom_count=len(atoms),
        canonical_reference_id=mapping.canonical_reference_id,
        canonical_reference_sequence_sha256=mapping.canonical_reference_sequence_sha256,
        not_represented_canonical_positions=[
            i for i in range(1, 691) if i not in positions
        ],
        atoms=atoms,
    )
    validate_selection_mapping(selection, mapping)
    return selection, tuple(pair[1] for pair in selected)


class RMSDSample(StrictModel):
    requested_sample_index: Index
    requested_time_ps: Annotated[float, Field(ge=0)]
    state: Literal["missing", "resolved"]
    runtime_frame_index: Index | None
    source_frame_index: Index | None
    prepared_frame_index: Index | None
    actual_time_ps: Annotated[float, Field(ge=0)] | None
    time_delta_ps: float | None
    rmsd_A: Annotated[float, Field(ge=0)] | None

    @model_validator(mode="after")
    def state_partition(self) -> RMSDSample:
        fields = (
            self.runtime_frame_index,
            self.source_frame_index,
            self.prepared_frame_index,
            self.actual_time_ps,
            self.time_delta_ps,
            self.rmsd_A,
        )
        if self.state == "missing" and any(v is not None for v in fields):
            raise ValueError("Missing requested sample cannot contain a measurement")
        if self.state == "resolved" and any(v is None for v in fields):
            raise ValueError("Resolved sample requires complete measurement identity")
        if self.actual_time_ps is not None and (
            self.time_delta_ps != self.actual_time_ps - self.requested_time_ps
        ):
            raise ValueError("Actual/requested time delta mismatch")
        return self


@dataclass(frozen=True)
class SelectedFrameObservation:
    execution_condition: str
    sample: Any
    coordinates: Any
    atom_selection: AtomSelection


class RMSDAccumulator:
    """One fixed reference plus compact rows; never stores a coordinate trajectory."""

    def __init__(
        self,
        binding: PreprocessingConditionTemporalExecution,
        selection: AtomSelection,
        *,
        source_frame_map: tuple[int, ...],
    ) -> None:
        self.binding = binding
        self.selection = selection.model_copy(deep=True)
        self._fixed_selection = selection.model_copy(deep=True)
        plan = binding.sampling_plan
        if not plan.selected_samples:
            raise ValueError("RMSD requires at least one resolved production sample")
        if (
            len(source_frame_map) != plan.source_frame_count
            or any(type(i) is not int or i < 0 for i in source_frame_map)
            or list(source_frame_map) != sorted(set(source_frame_map))
        ):
            raise ValueError("Prepared-to-source frame map mismatch")
        self.source_frame_map = source_frame_map
        # The reference identity is fixed before traversal, never the first arrival.
        self.reference_sample = plan.selected_samples[0]
        self.reference: Any = None
        self.reference_coordinate_sha256: str | None = None
        self.rows: list[RMSDSample] = []
        self.resolved_count = 0

    def observe(self, observation: SelectedFrameObservation) -> None:
        if observation.execution_condition != self.binding.execution_condition or (
            observation.atom_selection != self._fixed_selection
            or self.selection != self._fixed_selection
        ):
            raise ValueError("Changed RMSD execution/atom roster identity")
        expected = self.binding.sampling_plan.selected_samples
        if self.resolved_count >= len(expected) or (
            observation.sample != expected[self.resolved_count]
        ):
            raise ValueError("Changed/reordered/duplicate RMSD sample roster")
        xyz = coordinates_float64(observation.coordinates, self.selection.atom_count)
        if self.reference is None:
            self.reference = xyz.copy()
            self.reference.setflags(write=False)
            self.reference_coordinate_sha256 = hashlib.sha256(
                xyz.astype("<f8", copy=False).tobytes(order="C")
            ).hexdigest()
        sample = observation.sample
        frame = sample.source_frame_index
        self.rows.append(
            RMSDSample(
                requested_sample_index=sample.requested_sample_index,
                requested_time_ps=sample.requested_time_ps,
                state="resolved",
                runtime_frame_index=frame,
                source_frame_index=self.source_frame_map[frame],
                prepared_frame_index=frame,
                actual_time_ps=sample.actual_time_ps,
                time_delta_ps=sample.time_delta_ps,
                rmsd_A=fitted_rmsd(xyz, self.reference),
            )
        )
        self.resolved_count += 1

    def finalize(self) -> list[RMSDSample]:
        if self.resolved_count != len(self.binding.sampling_plan.selected_samples):
            raise ValueError("Incomplete resolved RMSD observation roster")
        missing = [
            RMSDSample(
                requested_sample_index=s.requested_sample_index,
                requested_time_ps=s.requested_time_ps,
                state="missing",
                runtime_frame_index=None,
                source_frame_index=None,
                prepared_frame_index=None,
                actual_time_ps=None,
                time_delta_ps=None,
                rmsd_A=None,
            )
            for s in self.binding.sampling_plan.missing_samples
        ]
        return sorted([*self.rows, *missing], key=lambda s: s.requested_sample_index)

    def selected_frame_observer(
        self,
        atoms: tuple[Any, ...],
        universe: Any = None,
    ) -> Any:
        """Copy only the selected coordinates from the already loaded contact frame."""
        np = importlib.import_module("numpy")
        by_frame = {
            s.source_frame_index: s for s in self.binding.sampling_plan.selected_samples
        }

        topology_counts = (
            (len(universe.atoms), len(universe.residues))
            if universe is not None
            else None
        )

        def observer(condition: str, frame: int, actual_time: float | None) -> None:
            if topology_counts is not None and topology_counts != (
                len(universe.atoms),
                len(universe.residues),
            ):
                raise ValueError("Changed live topology atom/residue roster")
            sample = by_frame[frame]
            if actual_time != sample.actual_time_ps:
                raise ValueError("Loaded contact time differs from resolved sample")
            if any(
                a.name != "CA" or str(optional_attribute(a, "element")).upper() != "C"
                for a in atoms
            ):
                raise ValueError("Changed live CA carbon selection")
            if any(
                len(
                    [
                        candidate
                        for candidate in a.residue.atoms
                        if candidate.name == "CA"
                    ]
                )
                != 1
                for a in atoms
            ):
                raise ValueError("Changed live C-alpha candidate roster")
            current = [
                atom_identity(a, record, record.source_engine)
                for a, record in zip(atoms, self.selection.atoms, strict=True)
            ]
            if current != self.selection.atoms:
                raise ValueError("Changed live topology/atom identity")
            self.observe(
                SelectedFrameObservation(
                    condition,
                    sample,
                    [np.array(a.position, dtype=np.float64, copy=True) for a in atoms],
                    self.selection,
                )
            )

        return observer

    @property
    def identity(self) -> DatasetTrajectoryIdentity:
        return self.binding.dataset_spec.identity


TIMESERIES_FILENAME = "protein_rmsd_timeseries.csv"


MEASUREMENT_FILENAME = "protein_rmsd_measurement.json"


RMSD_ROLES = ("protein_rmsd_timeseries", "protein_rmsd_measurement")


COLUMNS = (
    "dataset_id",
    "system_id",
    "trajectory_id",
    "replica_id",
    "engine",
    "variant_id",
    "condition",
    "scope_id",
    "requested_sample_index",
    "requested_time_ps",
    "state",
    "runtime_frame_index",
    "source_frame_index",
    "prepared_frame_index",
    "actual_time_ps",
    "time_delta_ps",
    "rmsd_A",
    "reference_requested_sample_index",
    "selection_id",
    "measurement_contract_id",
)


class FileBinding(StrictModel):
    artifact_id: str
    path: str | None
    byte_size: Annotated[int, Field(ge=0)]
    sha256: Digest
    format: str

    @model_validator(mode="after")
    def portable(self) -> FileBinding:
        if self.path is not None:
            _require_portable_path(self.path, "binding path")
        if not self.artifact_id or not self.format:
            raise ValueError("Binding needs artifact ID and format")
        return self


def bind_file(path: Path, artifact_id: str, portable: str | None = None) -> FileBinding:
    return FileBinding(
        artifact_id=artifact_id,
        path=portable,
        byte_size=path.stat().st_size,
        sha256=file_sha256(path),
        format=path.suffix.removeprefix(".").lower(),
    )


class RMSDScope(StrictModel):
    scope_id: Literal["production"] = "production"
    stabilization_included: Literal[False] = False
    temporal_execution: FileBinding
    execution_binding: dict[str, Any]


class RMSDReference(StrictModel):
    policy: Literal["first_resolved_requested_production_sample"]
    sample: RMSDSample
    prepared_trajectory_sha256: Digest
    selected_coordinate_sha256: Digest


class RMSDTable(StrictModel):
    artifact_id: Literal["output:protein_rmsd_timeseries"]
    path: Literal["protein_rmsd_timeseries.csv"]
    byte_size: Annotated[int, Field(gt=0)]
    sha256: Digest
    row_count: Annotated[int, Field(gt=0)]


class RMSDCompleteness(StrictModel):
    evidence_state: Literal["complete"]
    temporal_coverage_state: Literal["complete", "partial"]
    requested_count: Annotated[int, Field(gt=0)]
    resolved_count: Annotated[int, Field(gt=0)]
    missing_count: Annotated[int, Field(ge=0)]
    measured_count: Annotated[int, Field(gt=0)]
    resolved_measurement_count_matches: Literal[True]
    missing_requested_sample_indexes: list[int]
    reference_first_request_missing: bool

    @field_validator("resolved_measurement_count_matches", mode="before")
    @classmethod
    def exact_completion_bool(cls, value: Any) -> bool:
        if value is not True:
            raise ValueError("RMSD completion requires an exact true JSON bool")
        return True


class RMSDSoftwareIdentity(StrictModel):
    software_name: Literal["MANIA"]
    distribution_name: Literal["mania-wania"]
    version: Annotated[str, Field(min_length=1)]
    commit_sha: Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")] | None
    commit_source: Literal["git_checkout", "unavailable"]
    working_tree_status: Literal["clean", "dirty", "unavailable"]

    @model_validator(mode="after")
    def checkout_identity(self) -> RMSDSoftwareIdentity:
        if (self.commit_sha is None) != (self.commit_source == "unavailable"):
            raise ValueError("RMSD software checkout identity mismatch")
        return self


class RMSDImplementation(StrictModel):
    software_identity: dict[str, Any]
    python: str
    numpy: str
    mdanalysis: str | None
    algorithm_source_sha256: Digest
    persistence_source_sha256: Digest
    producer_build_sha256: Digest
    source_module: Literal["mania.preprocessing.trajectory_rmsd.fitted_rmsd"]

    @model_validator(mode="after")
    def build_identity(self) -> RMSDImplementation:
        RMSDSoftwareIdentity.model_validate(self.software_identity)
        if set(self.software_identity) != {
            "software_name",
            "distribution_name",
            "version",
            "commit_sha",
            "commit_source",
            "working_tree_status",
        }:
            raise ValueError("Software identity requires exact MANIA fields")
        if self.producer_build_sha256 != identity_digest(
            {
                "algorithm": self.algorithm_source_sha256,
                "persistence": self.persistence_source_sha256,
            }
        ):
            raise ValueError("Software source/build identity mismatch")
        return self


class LegacyRMSDMeasurement(StrictModel):
    schema_version: Literal["mania.protein_rmsd_measurement.v0.1"]
    kind: Literal["mania_protein_rmsd_measurement"]
    measurement_contract_id: Literal["mania.production_ca_rmsd.v1"]
    dataset_identity: DatasetTrajectoryIdentity
    execution_condition: str
    scope: RMSDScope
    reference: RMSDReference
    atom_selection: AtomSelection
    method: dict[str, Any]
    source_bindings: dict[str, FileBinding]
    implementation: RMSDImplementation
    table: RMSDTable
    completeness: RMSDCompleteness
    limitations: list[str]

    @model_validator(mode="after")
    def contract(self) -> LegacyRMSDMeasurement:
        expected = {
            **METHOD,
            "alignment_selection_id": self.atom_selection.selection_id,
            "measurement_selection_id": self.atom_selection.selection_id,
        }
        if (
            self.method != expected
            or type(self.method.get("automatic_drift_classification")) is not bool
        ):
            raise ValueError("RMSD method mismatch")
        if set(self.source_bindings) != {
            "topology",
            "mapping",
            "prepared_trajectory",
            "raw_trajectory",
            "preparation_report",
        }:
            raise ValueError(
                "RMSD requires exact topology/mapping/preparation bindings"
            )
        if self.reference.prepared_trajectory_sha256 != (
            self.source_bindings["prepared_trajectory"].sha256
        ):
            raise ValueError("Reference prepared trajectory lineage mismatch")
        if self.dataset_identity.condition not in (None, self.execution_condition):
            raise ValueError("RMSD replica/execution condition mismatch")
        if any(
            a.source_engine != self.dataset_identity.engine
            for a in self.atom_selection.atoms
        ):
            raise ValueError("Atom roster engine differs from Dataset replica")
        return self


def implementation_identity() -> RMSDImplementation:
    np = importlib.import_module("numpy")

    from mania.preprocessing import trajectory_rmsd
    from mania.preprocessing.scientific_runtime import get_mdanalysis_status

    algorithm = file_sha256(Path(trajectory_rmsd.__file__))
    persistence = file_sha256(Path(__file__))
    mda = get_mdanalysis_status().version
    return RMSDImplementation(
        software_identity=get_software_identity().to_dict(),
        python=platform.python_version(),
        numpy=np.__version__,
        mdanalysis=mda,
        algorithm_source_sha256=algorithm,
        persistence_source_sha256=persistence,
        producer_build_sha256=identity_digest(
            {"algorithm": algorithm, "persistence": persistence}
        ),
        source_module="mania.preprocessing.trajectory_rmsd.fitted_rmsd",
    )


def completeness(rows: list[RMSDSample]) -> RMSDCompleteness:
    missing = [s.requested_sample_index for s in rows if s.state == "missing"]
    resolved = len(rows) - len(missing)
    return RMSDCompleteness(
        evidence_state="complete",
        temporal_coverage_state="partial" if missing else "complete",
        requested_count=len(rows),
        resolved_count=resolved,
        missing_count=len(missing),
        measured_count=resolved,
        resolved_measurement_count_matches=True,
        missing_requested_sample_indexes=missing,
        reference_first_request_missing=rows[0].state == "missing",
    )


def timeseries_text(
    rows: list[RMSDSample],
    identity: DatasetTrajectoryIdentity,
    selection_id: str,
    reference_index: int,
) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(COLUMNS)
    for row in rows:
        values = {
            **identity.model_dump(mode="json"),
            **row.model_dump(mode="json"),
            "scope_id": "production",
            "selection_id": selection_id,
            "reference_requested_sample_index": reference_index,
            "measurement_contract_id": CONTRACT_ID,
        }
        writer.writerow(
            [
                ""
                if values[key] is None
                else format(values[key], ".17g")
                if type(values[key]) is float
                else values[key]
                for key in COLUMNS
            ]
        )
    return output.getvalue()


def atomic_json(path: Path, value: Any) -> None:
    result = write_atomic_text(
        json.dumps(
            value,
            sort_keys=True,
            indent=2,
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n",
        path,
        overwrite=False,
    )
    if not result.passed:
        raise ValueError(f"Protected atomic artifact write failed: {path}")


def write_rmsd_evidence(
    accumulator: RMSDAccumulator,
    output_root: Path,
    *,
    source_bindings: dict[str, FileBinding],
    implementation: RMSDImplementation | None = None,
) -> LegacyRMSDMeasurement:
    rows = accumulator.finalize()
    csv_path = output_root / TIMESERIES_FILENAME
    json_path = output_root / MEASUREMENT_FILENAME
    if csv_path.exists() or json_path.exists():
        raise ValueError("Existing RMSD evidence is immutable")
    result = write_atomic_text(
        timeseries_text(
            rows,
            accumulator.identity,
            accumulator.selection.selection_id,
            accumulator.reference_sample.requested_sample_index,
        ),
        csv_path,
        overwrite=False,
    )
    if not result.passed:
        raise ValueError("Atomic RMSD CSV write failed")
    reference = next(s for s in rows if s.state == "resolved")
    assert accumulator.reference_coordinate_sha256 is not None
    metadata = LegacyRMSDMeasurement(
        schema_version="mania.protein_rmsd_measurement.v0.1",
        kind="mania_protein_rmsd_measurement",
        measurement_contract_id="mania.production_ca_rmsd.v1",
        dataset_identity=accumulator.identity,
        execution_condition=accumulator.binding.execution_condition,
        scope=RMSDScope(
            temporal_execution=bind_file(
                output_root / "temporal_execution.json",
                "output:temporal_execution",
                "temporal_execution.json",
            ),
            execution_binding=accumulator.binding.to_dict(),
        ),
        reference=RMSDReference(
            policy="first_resolved_requested_production_sample",
            sample=reference,
            prepared_trajectory_sha256=source_bindings["prepared_trajectory"].sha256,
            selected_coordinate_sha256=accumulator.reference_coordinate_sha256,
        ),
        atom_selection=accumulator.selection,
        method={
            **METHOD,
            "alignment_selection_id": accumulator.selection.selection_id,
            "measurement_selection_id": accumulator.selection.selection_id,
        },
        source_bindings=source_bindings,
        implementation=implementation or implementation_identity(),
        table=RMSDTable(
            artifact_id="output:protein_rmsd_timeseries",
            path="protein_rmsd_timeseries.csv",
            byte_size=csv_path.stat().st_size,
            sha256=file_sha256(csv_path),
            row_count=len(rows),
        ),
        completeness=completeness(rows),
        limitations=[
            "production_only; stabilization_excluded",
            "same_trajectory_fixed_reference",
            "scientific_pbc_status=unresolved",
            "source_coordinate_precision_retained_in_preparation_report",
            "no_automatic_drift_classification",
            "coordinates_required_for_recomputation",
        ],
    )
    atomic_json(json_path, metadata.model_dump(mode="json"))
    read_rmsd_evidence(output_root)
    return metadata


def validate_sample_roster(
    metadata: LegacyRMSDMeasurement,
    rows: list[RMSDSample],
    binding: PreprocessingConditionTemporalExecution,
) -> None:
    if metadata.scope.execution_binding != binding.to_dict() or (
        metadata.dataset_identity != binding.dataset_spec.identity
        or metadata.execution_condition != binding.execution_condition
    ):
        raise ValueError("RMSD temporal/replica lineage mismatch")
    samples: list[Any] = sorted(
        [
            *binding.sampling_plan.selected_samples,
            *binding.sampling_plan.missing_samples,
        ],
        key=lambda s: s.requested_sample_index,
    )
    if len(rows) != len(samples) or len(rows) != metadata.table.row_count:
        raise ValueError("Missing/duplicate RMSD rows")
    selected = {
        s.requested_sample_index: s for s in binding.sampling_plan.selected_samples
    }
    for row, sample in zip(rows, samples, strict=True):
        if (row.requested_sample_index, row.requested_time_ps) != (
            sample.requested_sample_index,
            sample.requested_time_ps,
        ):
            raise ValueError("Reordered/changed RMSD requested sample roster")
        resolved = selected.get(row.requested_sample_index)
        if (row.state == "resolved") != (resolved is not None):
            raise ValueError("RMSD missing/resolved partition mismatch")
        if resolved is not None and (
            row.runtime_frame_index != resolved.source_frame_index
            or row.prepared_frame_index != resolved.source_frame_index
            or row.actual_time_ps != resolved.actual_time_ps
            or row.time_delta_ps != resolved.time_delta_ps
        ):
            raise ValueError("Resolved RMSD frame/time lineage mismatch")
    if metadata.reference.sample != next(s for s in rows if s.state == "resolved"):
        raise ValueError("RMSD reference must be first resolved requested sample")
    if metadata.completeness != completeness(rows):
        raise ValueError("RMSD completion mismatch")


def read_rmsd_evidence(
    output_root: Path,
    *,
    expected_bindings: dict[str, FileBinding] | None = None,
    expected_implementation: RMSDImplementation | None = None,
) -> tuple[LegacyRMSDMeasurement, list[RMSDSample]]:
    raw_metadata = read_strict_json(output_root / MEASUREMENT_FILENAME)
    metadata = LegacyRMSDMeasurement.model_validate(raw_metadata)
    if metadata.model_dump(mode="json") != raw_metadata:
        raise ValueError("RMSD schema requires all exact fields without normalization")
    if expected_bindings is not None and metadata.source_bindings != expected_bindings:
        raise ValueError("Changed RMSD topology/mapping/prepared/source lineage")
    if expected_implementation is not None and (
        metadata.implementation != expected_implementation
    ):
        raise ValueError("Changed RMSD implementation/software identity")
    csv_path = portable_member(output_root, metadata.table.path)
    if csv_path.stat().st_size != metadata.table.byte_size or (
        file_sha256(csv_path) != metadata.table.sha256
    ):
        raise ValueError("RMSD CSV binding mismatch")
    rows = []
    with csv_path.open(encoding="utf-8", newline="") as stream:
        reader = csv.reader(stream)
        if tuple(next(reader, ())) != COLUMNS:
            raise ValueError("RMSD CSV requires exact ordered columns")
        for fields in reader:
            if len(fields) != len(COLUMNS):
                raise ValueError("Malformed RMSD CSV row")
            data = dict(zip(COLUMNS, fields, strict=True))
            row: dict[str, Any] = {}
            for name in RMSDSample.model_fields:
                raw = data[name]
                if name == "state":
                    row[name] = raw
                elif not raw:
                    row[name] = None
                elif name.endswith("index"):
                    if not raw.isascii() or not raw.isdecimal() or str(int(raw)) != raw:
                        raise ValueError(
                            "RMSD indexes require canonical nonnegative ints"
                        )
                    row[name] = int(raw)
                else:
                    row[name] = float(raw)
            rows.append(RMSDSample.model_validate(row))
    expected_text = timeseries_text(
        rows,
        metadata.dataset_identity,
        metadata.atom_selection.selection_id,
        metadata.reference.sample.requested_sample_index,
    )
    if csv_path.read_bytes() != expected_text.encode("utf-8"):
        raise ValueError("RMSD CSV identity/contract/representation mismatch")
    temporal_binding = metadata.scope.temporal_execution
    temporal_path = portable_member(output_root, temporal_binding.path or "")
    if (
        bind_file(temporal_path, temporal_binding.artifact_id, temporal_binding.path)
        != temporal_binding
    ):
        raise ValueError("Changed RMSD temporal artifact binding")
    temporal = read_preprocessing_temporal_execution(temporal_path)
    matches = [
        b
        for b in temporal.bindings
        if b.execution_condition == metadata.execution_condition
    ]
    if len(matches) != 1:
        raise ValueError("RMSD requires exact unique temporal binding")
    validate_sample_roster(metadata, rows, matches[0])
    return metadata, rows


def create_legacy_rmsd_accumulator(
    binding: PreprocessingConditionTemporalExecution,
    *,
    universe: Any,
    mapping: CanonicalResidueMappingTable,
    source_frame_map: tuple[int, ...],
) -> RMSDAccumulator:
    """Explicit selected legacy contribution; no automatic input/reference choice."""
    selection, _ = select_mapped_ca_atoms(
        universe, mapping, binding.dataset_spec.identity.engine
    )
    return RMSDAccumulator(binding, selection, source_frame_map=source_frame_map)


@dataclass(frozen=True)
class RunProfile:
    profile_id: str
    policy_factory: Any
    dataset_writer: Any
    dataset_reader: Any
    legacy_rmsd_factory: Any
    bindings_reader: Any = None
    run_executor: Any = None
    run_validator: Any = None
    run_artifacts: Any = None


def activate_run_profile(profile_id: str) -> RunProfile:
    """Fresh plan-scoped retained callables; no process-wide activation."""
    if profile_id not in ("napi2b.legacy.v1", "napi2b.dataset.v1"):
        raise ValueError("Unknown explicitly selected run profile")
    from mania_napi2b.tables import napi2b_qc_policy

    if profile_id == "napi2b.dataset.v1":
        from mania_napi2b.publication_io import reconstruct_dataset, write_dataset

        return RunProfile(
            profile_id,
            napi2b_qc_policy,
            write_dataset,
            reconstruct_dataset,
            create_legacy_rmsd_accumulator,
            read_dataset_run_bindings,
            execute_dataset_run,
            validate_dataset_run,
            dataset_run_artifacts,
        )
    return RunProfile(
        profile_id, napi2b_qc_policy, None, None, create_legacy_rmsd_accumulator
    )


# Selected-only C06 envelope; existing runtime tuple representations introduce
# no new scientific fields into the C05 models.


class DatasetSourceBindings(_StrictModel):
    schema_version: Literal["mania_napi2b.dataset_sources_bindings.v1"]
    kind: Literal["mania_napi2b_dataset_sources_bindings"]
    qc_sources: FileEvidence
    control_evidence: FileEvidence
    policy_evidence: FileEvidence
    handoffs: tuple[
        tuple[
            FileEvidence,
            WindowInputBinding,
            SystemAnnotations | None,
            BindingText | None,
        ],
        ...,
    ]
    qc_evidence_files: tuple[FileEvidence, ...]
    qc_decision_files: tuple[FileEvidence, ...]
    group_files: tuple[FileEvidence, ...]
    fixed_mappings: tuple[tuple[InputIdentity, FileEvidence], ...]
    canonical_sources: tuple[
        tuple[InputIdentity, Literal["protein", "lipid", "glycan"], FileEvidence], ...
    ]
    annotated_sources: tuple[
        tuple[InputIdentity, Literal["protein", "lipid", "glycan"], FileEvidence], ...
    ]
    fixed_qc_files: tuple[FileEvidence, ...]
    publication_input_evidence: FileEvidence

    @model_validator(mode="after")
    def _rosters(self) -> Self:
        if not self.handoffs or len({i for i, _ in self.fixed_mappings}) != len(
            self.fixed_mappings
        ):
            raise ValueError("Missing handoff or duplicate fixed mapping identity")
        for roster in (self.canonical_sources, self.annotated_sources):
            if len({(identity, layer) for identity, layer, _ in roster}) != len(roster):
                raise ValueError("Duplicate source identity/layer binding")
        return self


def read_dataset_run_bindings(
    path: Path, *, release_path: Path, verify: bool = False
) -> Any:
    from mania.result_readers import (
        bound_file,
        read_closed_model,
        read_qc_source_bindings,
    )
    from mania_napi2b.publication_io import read_dataset_release_publication_inputs

    document = cast(
        DatasetSourceBindings, read_closed_model(path, DatasetSourceBindings)
    )
    root = path.parent
    qc_path = bound_file(root, document.qc_sources, verify=verify)
    if qc_path.parent != root:
        raise ValueError(
            "C05 DatasetSources requires one explicit shared authority root"
        )
    qc = read_qc_source_bindings(qc_path, verify=verify)
    if qc.policy_evidence != document.policy_evidence:
        raise ValueError("Generic/profile policy FileEvidence differs")
    if (
        bound_file(root, document.publication_input_evidence, verify=verify)
        != release_path
    ):
        raise ValueError("Publication input path conflicts with selected YAML")
    read_dataset_release_publication_inputs(release_path)
    for descriptor in (
        document.control_evidence,
        document.policy_evidence,
        *document.qc_evidence_files,
        *document.qc_decision_files,
        *document.group_files,
        *document.fixed_qc_files,
        *(f for _, f in document.fixed_mappings),
        *(f for _, _, f in document.canonical_sources),
        *(f for _, _, f in document.annotated_sources),
        *(h[0] for h in document.handoffs),
    ):
        bound_file(root, descriptor, verify=verify)
    if tuple(m.qc_evidence for m in qc.members) != document.qc_evidence_files:
        raise ValueError("Generic/profile scientific QC file roster differs")
    return document


def reconstruct_run_sources(
    path: Path,
    *,
    release_path: Path,
    qc_requests: tuple[Any, ...] = (),
    preview: bool = False,
) -> Any:
    from mania.result_readers import bound_file, execute_qc_sources
    from mania_napi2b.biological_annotations import DatasetSystemBiologicalAnnotations
    from mania_napi2b.canonical_residue_mapping_io import read_canonical_residue_mapping
    from mania_napi2b.publication import _decode_legacy
    from mania_napi2b.publication_authority import DatasetSources
    from mania_napi2b.publication_io import read_dataset_release_export_manifest
    from mania_napi2b.tables import FixedWindowTable, read_fixed_window_csv

    document = read_dataset_run_bindings(path, release_path=release_path, verify=True)
    root = path.parent
    qc_path = document.qc_sources.verify(root)
    qc = execute_qc_sources(qc_path, policy_path=document.policy_evidence.verify(root))
    for identity, policy, evidence in qc_requests:
        if (
            identity not in tuple(m.identity for m in qc.bindings.members)
            or evidence != qc_path
            or policy is not None
            and policy != document.policy_evidence.verify(root)
        ):
            raise ValueError("Generic QC/selected profile input or policy conflicts")
    control = read_dataset_release_export_manifest(
        document.control_evidence.verify(root)
    )
    handoffs = []
    for descriptor, window, supplied_annotations, rmsd in document.handoffs:
        matches = [m for m in qc.bindings.members if m.window_input == window]
        if len(matches) != 1:
            raise ValueError("Handoff requires one exact declared QC window input")
        identity = matches[0].identity
        if (
            supplied_annotations is not None
            and supplied_annotations.identity != identity
        ):
            raise ValueError("Handoff annotation identity differs")
        handoffs.append(
            (descriptor, window.reconstruct(root, identity), supplied_annotations, rmsd)
        )
    if tuple(h[1].identity for h in handoffs) != tuple(
        m.identity for m in qc.bindings.members
    ):
        raise ValueError("Full scientific handoff/QC identity order differs")
    mappings = {
        i: read_canonical_residue_mapping(bound_file(root, f, verify=True))
        for i, f in document.fixed_mappings
    }
    if set(mappings) != set(i.identity for i in qc.inputs):
        raise ValueError(
            "Fixed mappings must cover exactly the explicit source identities"
        )

    def fixed(roster: Any, annotated: bool) -> tuple[Any, ...]:
        result = []
        for identity, layer, descriptor in roster:
            inp = next((i for i in qc.inputs if i.identity == identity), None)
            if inp is None:
                raise ValueError(
                    "Fixed source identity is absent from scientific cohort"
                )
            temporal, replay = inp.read_back()
            annotations = None
            if annotated:
                candidates = [
                    a
                    for a in control.annotation_bindings
                    if (a.dataset_id, a.system_id)
                    == (identity.project, identity.system_id)
                ]
                if len(candidates) != 1:
                    raise ValueError(
                        "Explicit fixed annotation source unavailable or ambiguous"
                    )
                annotation_path = require_regular_source(root, candidates[0].path)
                annotations = _decode_legacy(
                    read_strict_json(annotation_path),
                    DatasetSystemBiologicalAnnotations,
                )
            table = FixedWindowTable(
                getattr(replay, "canonical_" + layer),
                mappings[identity],
                annotations,
                temporal,
            )
            read_fixed_window_csv(descriptor.verify(root), expected=table)
            result.append((descriptor, table))
        return tuple(result)

    sources = DatasetSources(
        root,
        document.control_evidence,
        document.policy_evidence,
        tuple(handoffs),
        document.qc_evidence_files,
        document.qc_decision_files,
        qc.selections,
        document.group_files,
        fixed(document.canonical_sources, False),
        fixed(document.annotated_sources, True),
        document.fixed_qc_files,
        document.publication_input_evidence,
    )
    sources.validate(preview=preview)
    return sources


def require_regular_source(root: Path, relative: str) -> Path:
    from mania.input_binding import portable_path
    from mania.output_paths import require_input_file, safe_absolute

    portable_path(relative)
    return require_input_file(safe_absolute(root / relative))


def dataset_run_artifacts(
    *, exploratory: bool = False
) -> tuple[tuple[str, str, str | None], ...]:
    if exploratory:
        from mania_napi2b.publication_io import preview_artifacts

        return preview_artifacts()
    from mania_napi2b.publication_io import EXPORT_MANIFEST_FILENAME
    from mania_napi2b.tables import PUBLICATION_ARTIFACT_REGISTRY

    return tuple(
        (
            "profile_inventory"
            if a.artifact_id == "artifact_inventory"
            else a.artifact_id,
            a.relative_path,
            None,
        )
        for a in PUBLICATION_ARTIFACT_REGISTRY.artifacts
    ) + (("export_control", "inputs/" + EXPORT_MANIFEST_FILENAME, None),)


def execute_dataset_run(
    path: Path,
    *,
    release_path: Path,
    directory: Path,
    qc_requests: tuple[Any, ...] = (),
    exploratory: bool = False,
    run_id: str | None = None,
    pbc_by_identity: tuple[tuple[InputIdentity, bool], ...] = (),
) -> list[tuple[str, Path, str | None]]:
    if exploratory:
        return execute_dataset_preview(
            path,
            release_path=release_path,
            directory=directory,
            qc_requests=qc_requests,
            run_id=run_id,
            pbc_by_identity=pbc_by_identity,
        )
    from datetime import UTC, datetime

    from mania.run_provenance import PortableArtifactReference, RunProvenance
    from mania_napi2b.publication_io import (
        EXPORT_MANIFEST_FILENAME,
        RELEASE_MANIFEST_PATH,
        write_dataset,
    )

    sources = reconstruct_run_sources(
        path, release_path=release_path, qc_requests=qc_requests
    )
    _, metadata, science = sources.validate()
    refs = tuple(
        PortableArtifactReference(t.table_id, t.relative_path)
        for t in (*metadata.tables, *science.tables)
    ) + (
        PortableArtifactReference("dataset_manifest", RELEASE_MANIFEST_PATH),
        PortableArtifactReference(
            "export_control", "inputs/" + EXPORT_MANIFEST_FILENAME
        ),
    )
    started = datetime.now(UTC)
    provenance = RunProvenance(
        "c06-" + uuid.uuid4().hex,
        "dataset_release",
        "completed",
        started,
        datetime.now(UTC),
        get_software_identity(),
        ("mania", "run", "explicit_selected_profile"),
        {},
        (),
        artifact_references=refs,
    )
    write_dataset(sources, directory, provenance=provenance)
    validate_dataset_run(path, release_path=release_path, directory=directory)
    return [
        (role, directory / relative, schema)
        for role, relative, schema in dataset_run_artifacts()
    ]


def validate_dataset_run(
    path: Path,
    *,
    release_path: Path,
    directory: Path,
    exploratory: bool = False,
    run_id: str | None = None,
    pbc_by_identity: tuple[tuple[InputIdentity, bool], ...] = (),
) -> Any:
    if exploratory:
        return validate_dataset_preview(
            path,
            release_path=release_path,
            directory=directory,
            run_id=run_id,
            pbc_by_identity=pbc_by_identity,
        )
    from mania_napi2b.publication_io import reconstruct_dataset

    return reconstruct_dataset(
        directory, sources=reconstruct_run_sources(path, release_path=release_path)
    )


def _preview_sources(
    path: Path, release_path: Path, qc_requests: tuple[Any, ...] = ()
) -> tuple[Any, tuple[InputIdentity, ...], tuple[FileEvidence, ...]]:
    from mania.scientific_qualification import declare_sources
    from mania_napi2b.publication_io import _artifact_descriptor

    document = read_dataset_run_bindings(path, release_path=release_path, verify=True)
    sources = reconstruct_run_sources(
        path, release_path=release_path, qc_requests=qc_requests, preview=True
    )
    identities = tuple(h[1].identity for h in sources.handoffs)
    declare_sources(identities)
    descriptors = [
        document.qc_sources,
        document.control_evidence,
        document.policy_evidence,
        *document.qc_evidence_files,
        *document.qc_decision_files,
        *document.group_files,
        *document.fixed_qc_files,
        *(f for _, f in document.fixed_mappings),
        *(f for _, _, f in document.canonical_sources),
        *(f for _, _, f in document.annotated_sources),
        *(h[0] for h in document.handoffs),
        document.publication_input_evidence,
        _artifact_descriptor(path.parent, path.name, "profile_source_bindings"),
    ]
    # Retain every actually read source dependency, including the complete
    # source-window and upstream inventory graphs already strictly validated.
    from mania_napi2b.publication_authority import _verify_upstream
    from mania_napi2b.publication_io import read_dataset_release_export_manifest

    for _, inp, _, _ in sources.handoffs:
        descriptors.extend(
            (
                inp.temporal_evidence,
                inp.mapping_evidence,
                inp.reference_evidence,
                *inp.observation_evidence,
            )
        )
    control = read_dataset_release_export_manifest(
        document.control_evidence.verify(path.parent)
    )
    for upstream in (control.stage32_run, control.stage31_run):
        descriptors.extend(
            (
                _artifact_descriptor(
                    path.parent, upstream.provenance_path, "upstream_provenance"
                ),
                _artifact_descriptor(
                    path.parent, upstream.inventory_path, "upstream_inventory"
                ),
            )
        )
        inventory = _verify_upstream(path.parent, upstream)
        mapped = {b.artifact_id: b.path for b in upstream.input_bindings}
        descriptors.extend(
            _artifact_descriptor(
                path.parent,
                mapped.get(e.artifact_id, e.path) if e.direction == "input" else e.path,
                e.role,
            )
            for e in inventory.artifacts
        )
    from mania.canonical_reference import AuthorityBinding
    from mania.handoff import HandoffManifest
    from mania_napi2b.publication_authority import _authority_bytes
    from mania_napi2b.publication_io import read_dataset_release_publication_inputs

    for descriptor, _, _, _ in sources.handoffs:
        handoff = HandoffManifest.model_validate_json(
            descriptor.verify(path.parent).read_bytes()
        )
        descriptors.extend(handoff.required_evidence)
        descriptors.extend(
            (
                _artifact_descriptor(
                    path.parent, handoff.binding.path, handoff.binding.role
                ),
                _artifact_descriptor(
                    path.parent, handoff.completion.marker_path, "run_provenance"
                ),
            )
        )
    descriptors.extend(
        _artifact_descriptor(path.parent, a.path, "biological_annotations")
        for a in control.annotation_bindings
    )
    published = read_dataset_release_publication_inputs(
        document.publication_input_evidence.verify(path.parent)
    )
    pbc_fields = json.loads(_authority_bytes())["pbc_path_fields"]
    raw_publication = read_strict_json(
        document.publication_input_evidence.verify(path.parent)
    )
    for definition in raw_publication["contact_definitions"]:
        descriptors.append(
            _artifact_descriptor(
                path.parent,
                definition["source_artifact_path"],
                definition["source_artifact_role"],
            )
        )
        pbc = definition["parameters"]["pbc_correction_status"]
        descriptors.extend(
            _artifact_descriptor(path.parent, pbc[name], name) for name in pbc_fields
        )
    for record in published.software_versions.records():
        descriptors.append(
            _artifact_descriptor(
                path.parent,
                cast(str, record["source_artifact_path"]),
                cast(str, record["source_artifact_role"]),
            )
        )
    for metric in published.metrics:
        descriptors.append(
            _artifact_descriptor(
                path.parent, metric.source_artifact_path, metric.source_artifact_role
            )
        )

    # Traverse only recognized workspace-bound authority contracts. Documentary
    # payloads and run-root-relative qualification records are not reinterpreted.
    schemas = {
        "mania.input_binding.v1",
        "mania.handoff.v1",
        "mania.qc_source_bindings.v1",
        "mania.qc_evidence.v1",
        "mania.qc_decisions.v1",
        "mania.replica_group.v1",
        "mania.reference.v1",
        "mania.residue_mapping.v1",
        "mania.annotations.v1",
        "mania_napi2b.dataset_sources_bindings.v1",
    }
    expanded = set()
    cursor = 0
    while cursor < len(descriptors):
        descriptor = descriptors[cursor]
        cursor += 1
        if descriptor.path in expanded or not descriptor.path.endswith(".json"):
            continue
        expanded.add(descriptor.path)
        payload = read_strict_json(descriptor.verify(path.parent))
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") not in schemas
        ):
            continue

        def bindings(value: Any) -> None:
            if isinstance(value, dict):
                if set(value) == {"role", "path", "size_bytes", "sha256"}:
                    descriptors.append(FileEvidence.model_validate(value))
                elif set(value) == {"role", "path", "sha256", "source_identity"}:
                    authority = AuthorityBinding.model_validate(value)
                    evidence = _artifact_descriptor(
                        path.parent, authority.path, authority.role
                    )
                    if evidence.sha256 != authority.sha256:
                        raise ValueError("Preview transitive source authority differs")
                    descriptors.append(evidence)
                else:
                    for child in value.values():
                        bindings(child)
            elif isinstance(value, list):
                for child in value:
                    bindings(child)

        bindings(payload)
    seen = set()
    evidence: list[FileEvidence] = []
    for descriptor in descriptors:
        key = descriptor.role, descriptor.path
        if key in seen:
            if next(e for e in evidence if (e.role, e.path) == key) != descriptor:
                raise ValueError("Conflicting preview source evidence")
            continue
        descriptor.verify(path.parent)
        evidence.append(descriptor)
        seen.add(key)
    return sources, identities, tuple(evidence)


def execute_dataset_preview(
    path: Path,
    *,
    release_path: Path,
    directory: Path,
    qc_requests: tuple[Any, ...],
    run_id: str | None,
    pbc_by_identity: tuple[tuple[InputIdentity, bool], ...],
) -> list[tuple[str, Path, str | None]]:
    from mania.scientific_qualification import preview_pbc
    from mania_napi2b.publication_io import write_dataset_preview

    if run_id is None:
        raise ValueError("Preview requires the real controller run identity")
    sources, identities, evidence = _preview_sources(path, release_path, qc_requests)
    write_dataset_preview(
        sources,
        directory,
        run_id=run_id,
        source_identities=identities,
        source_evidence=evidence,
        inherited_pbc_unverified=preview_pbc(identities, pbc_by_identity),
    )
    validate_dataset_preview(
        path,
        release_path=release_path,
        directory=directory,
        run_id=run_id,
        pbc_by_identity=pbc_by_identity,
    )
    return [
        (role, directory / relative, schema)
        for role, relative, schema in dataset_run_artifacts(exploratory=True)
    ]


def validate_dataset_preview(
    path: Path,
    *,
    release_path: Path,
    directory: Path,
    run_id: str | None,
    pbc_by_identity: tuple[tuple[InputIdentity, bool], ...],
) -> Any:
    from mania.scientific_qualification import preview_pbc
    from mania_napi2b.publication_io import read_dataset_preview

    if run_id is None:
        raise ValueError("Preview read-back requires the bound controller run identity")
    sources, identities, evidence = _preview_sources(path, release_path)
    return read_dataset_preview(
        directory,
        sources=sources,
        run_id=run_id,
        source_identities=identities,
        source_evidence=evidence,
        inherited_pbc_unverified=preview_pbc(identities, pbc_by_identity),
    )
