"""Offline window replay from strict per-frame evidence and saved temporal plans."""

from dataclasses import dataclass
from pathlib import Path

from mania.canonical_reference import ProteinReference
from mania.canonical_residue_mapping import ResidueMappingTable
from mania.canonical_window_tables import (
    ReferenceProteinEdgeWindowTable,
    ReferenceProteinGlycanWindowTable,
    ReferenceProteinLipidWindowTable,
    build_reference_window_tables,
)
from mania.preprocessing.perframe_observations import read_perframe_observations
from mania.preprocessing.physical_time_execution import PreprocessingTemporalExecution
from mania.preprocessing.physical_time_execution_io import (
    read_preprocessing_temporal_execution,
)
from mania.preprocessing.protein_edge_window_execution import (
    build_preprocessing_protein_edge_window_source_table,
)
from mania.preprocessing.protein_edge_window_table import DatasetProteinEdgeWindowTable
from mania.preprocessing.specialized_contact_execution import (
    build_specialized_contact_source_tables,
)
from mania.preprocessing.specialized_contact_window_tables import (
    ProteinGlycanWindowTable,
    ProteinLipidWindowTable,
)


@dataclass(frozen=True)
class ReplayedWindowTables:
    protein: DatasetProteinEdgeWindowTable
    lipid: ProteinLipidWindowTable
    glycan: ProteinGlycanWindowTable
    canonical_protein: ReferenceProteinEdgeWindowTable | None = None
    canonical_lipid: ReferenceProteinLipidWindowTable | None = None
    canonical_glycan: ReferenceProteinGlycanWindowTable | None = None


def replay_window_tables(
    observation_dir: str | Path,
    temporal: PreprocessingTemporalExecution | str | Path,
    *,
    mapping: ResidueMappingTable | None = None,
    reference: ProteinReference | None = None,
) -> ReplayedWindowTables:
    """Load once, aggregate all windows, optionally apply authoritative mapping.

    ``temporal`` is a retained execution or its JSON path, never a trajectory.
    Missing specialized metadata remains unavailable in the completion index;
    its empty source table must not be interpreted as negative observations.
    """
    execution = (
        read_preprocessing_temporal_execution(temporal)
        if isinstance(temporal, (str, Path))
        else temporal
    )
    saved = read_perframe_observations(observation_dir, execution)
    protein = build_preprocessing_protein_edge_window_source_table(
        execution, saved.protein
    )
    lipid, glycan = build_specialized_contact_source_tables(
        saved.specialized, execution
    )
    if (mapping is None) != (reference is None):
        raise ValueError(
            "Replay projection requires explicit mapping and reference together"
        )
    if mapping is None or reference is None:
        return ReplayedWindowTables(protein, lipid, glycan)
    projected = build_reference_window_tables(
        (protein, lipid, glycan), mapping=mapping, reference=reference
    )
    assert isinstance(projected, tuple)
    protein_reference, lipid_reference, glycan_reference = projected
    assert isinstance(protein_reference, ReferenceProteinEdgeWindowTable)
    assert isinstance(lipid_reference, ReferenceProteinLipidWindowTable)
    assert isinstance(glycan_reference, ReferenceProteinGlycanWindowTable)
    return ReplayedWindowTables(
        protein, lipid, glycan, protein_reference, lipid_reference, glycan_reference
    )
