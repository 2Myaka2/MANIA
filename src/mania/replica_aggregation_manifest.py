"""Read-back-backed inputs for explicit generic groups; no execution dispatcher."""

from dataclasses import dataclass
from pathlib import Path

from mania.canonical_reference import InputIdentity, ProteinReference
from mania.canonical_residue_mapping import ResidueMappingTable
from mania.input_binding import FileEvidence
from mania.preprocessing.physical_time_execution import (
    PreprocessingConditionTemporalExecution,
)
from mania.preprocessing.physical_time_execution_io import (
    read_preprocessing_temporal_execution,
)
from mania.preprocessing.window_replay import ReplayedWindowTables, replay_window_tables
from mania.replica_aggregation_contract import ReplicaGroup


@dataclass(frozen=True)
class ReplicaWindowInput:
    identity: InputIdentity
    root: Path
    temporal_evidence: FileEvidence
    observation_directory: str
    mapping: ResidueMappingTable
    reference: ProteinReference
    observation_evidence: tuple[FileEvidence, ...]
    mapping_evidence: FileEvidence
    reference_evidence: FileEvidence

    def read_back(
        self,
    ) -> tuple[PreprocessingConditionTemporalExecution, ReplayedWindowTables]:
        from mania.input_binding import portable_path

        portable_path(self.observation_directory)
        base = self.root.resolve(strict=True)
        directory = (base / self.observation_directory).resolve(strict=True)
        if not directory.is_relative_to(base) or not directory.is_dir():
            raise ValueError("Observation directory escapes declared input root")
        roles = [e.role for e in self.observation_evidence]
        if len(set(roles)) != len(roles) or not {
            "perframe_completion",
            "contacts_perframe",
        } <= set(roles):
            raise ValueError(
                "Complete per-frame file evidence is required for sparse zeros"
            )
        for e in self.observation_evidence:
            path = e.verify(base)
            if not path.is_relative_to(directory):
                raise ValueError(
                    "Observation evidence must bind its declared directory"
                )
        temporal = read_preprocessing_temporal_execution(
            self.temporal_evidence.verify(base)
        )
        if len(temporal.bindings) != 1:
            raise ValueError("One explicit member temporal binding is required")
        binding = temporal.bindings[0]
        old = binding.dataset_spec.identity
        identity = InputIdentity(
            project=old.dataset_id,
            system_id=old.system_id,
            trajectory_id=old.trajectory_id,
            replica_id=old.replica_id,
            engine=old.engine,
            condition=old.condition,
            variant_id=old.variant_id,
            disulfide_state=old.disulfide_state,
        )
        if identity != self.identity or self.mapping.identity != self.identity:
            raise ValueError("Input, mapping and temporal identities differ")
        from mania.canonical_reference_io import read_protein_reference
        from mania.canonical_residue_mapping_io import read_residue_mapping
        from mania.input_binding import verify_authority

        if (
            read_protein_reference(self.reference_evidence.verify(base))
            != self.reference
            or read_residue_mapping(
                self.mapping_evidence.verify(base), reference=self.reference
            )
            != self.mapping
        ):
            raise ValueError(
                "Supplied source reference/mapping content differs from bound bytes"
            )
        for authority in self.mapping.authority:
            verify_authority(base, authority, authority.source_identity)
        self.reference._require_verified()
        self.mapping.validate_reference(self.reference)
        from mania.preprocessing.molecular_partner_metadata_io import read_strict_json

        completion = read_strict_json(directory / "perframe_completion.json")
        if completion["specialized_conditions"]:
            expected = {
                "molecular_partner_catalog": "molecular_partner_catalog.json",
                "protein_lipid_perframe": "protein_lipid_perframe.json",
                "protein_glycan_perframe": "protein_glycan_perframe.json",
            }
            by_role = {e.role: e for e in self.observation_evidence}
            for role, name in expected.items():
                if (
                    role not in by_role
                    or by_role[role].path != self.observation_directory + "/" + name
                ):
                    raise ValueError(
                        "Scientific reader dependency lacks exact source hash/path: "
                        + role
                    )
                by_role[role].verify(base)
        replay = replay_window_tables(
            directory, temporal, mapping=self.mapping, reference=self.reference
        )
        return binding, replay


def validate_group_inputs(
    group: ReplicaGroup, inputs: tuple[ReplicaWindowInput, ...]
) -> tuple[
    tuple[
        ReplicaWindowInput,
        PreprocessingConditionTemporalExecution,
        ReplayedWindowTables,
    ],
    ...,
]:
    ReplicaGroup.model_validate(group.model_dump())
    keys = [i.identity.model_dump_json() for i in inputs]
    expected = [
        m.identity.model_dump_json()
        for m in group.members
        if m.availability == "available"
    ]
    if keys != expected:
        raise ValueError(
            "Inputs must follow exactly the complete available member roster"
        )
    result = []
    for i in inputs:
        if i.reference.reference != group.reference:
            raise ValueError("Input/group reference mismatch")
        required = (
            i.temporal_evidence,
            i.mapping_evidence,
            i.reference_evidence,
            *i.observation_evidence,
        )
        for e in required:
            if not any(
                a.source_identity == i.identity
                and (a.role, a.path, a.sha256) == (e.role, e.path, e.sha256)
                for a in group.authority
            ):
                raise ValueError("Source evidence is not bound to group authority")
        result.append((i, *i.read_back()))
    return tuple(result)
