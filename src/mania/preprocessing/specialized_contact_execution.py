"""Runtime-only adapter: one selected-frame pass serves both specialized layers."""

from dataclasses import dataclass
from numbers import Integral
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from mania.preprocessing.input_manifest import PreprocessingInputManifest
from mania.preprocessing.molecular_partner_catalog_io import (
    MolecularPartnerCatalogBinding,
    PreprocessingMolecularPartnerCatalog,
)
from mania.preprocessing.molecular_partner_entities import (
    MolecularPartnerTopology,
    SourceTopologyBond,
    SourceTopologyResidue,
)
from mania.preprocessing.molecular_partner_identification import (
    identify_molecular_partners,
)
from mania.preprocessing.molecular_partner_metadata_io import (
    MolecularPartnerMetadata,
    read_molecular_partner_metadata,
)
from mania.preprocessing.physical_time_execution import (
    PreprocessingConditionTemporalExecution,
    PreprocessingTemporalExecution,
)
from mania.preprocessing.protein_glycan_contacts import (
    ProteinGlycanContactFrameInput,
    ProteinGlycanContactFrameResult,
    compute_protein_glycan_contacts,
)
from mania.preprocessing.protein_lipid_contacts import (
    ProteinLipidContactFrameInput,
    ProteinLipidContactFrameResult,
    SourceAtomFrameCoordinate,
    compute_protein_lipid_contacts,
)
from mania.preprocessing.trajectory_contacts import (
    PreprocessingContactDetectionOptions,
    _selected_contact_residue_items,
)
from mania.preprocessing.trajectory_frame_selection import (
    iter_selected_trajectory_frames,
)
from mania.preprocessing.trajectory_graph_workflow import (
    PreprocessingGraphWorkflowRuntimeLoadingResult,
)
from mania.preprocessing.trajectory_manifest_loader import (
    PreprocessingManifestLoadResult,
)

if TYPE_CHECKING:
    from mania.preprocessing.specialized_contact_window_tables import (
        ProteinGlycanWindowTable,
        ProteinLipidWindowTable,
    )


class MolecularPartnerIdentificationExecutionError(ValueError):
    """Runtime topology or authoritative identity is unavailable."""


class SpecializedContactComputationError(ValueError):
    """Specialized geometry could not be fully computed."""


@dataclass(frozen=True)
class PreprocessingSpecializedContactConditionResult(MolecularPartnerCatalogBinding):
    lipid_frame_results: tuple[ProteinLipidContactFrameResult, ...]
    glycan_frame_results: tuple[ProteinGlycanContactFrameResult, ...]

    def __post_init__(self) -> None:
        super().__post_init__()
        for kind, results, model in (
            ("lipid", self.lipid_frame_results, ProteinLipidContactFrameResult),
            ("glycan", self.glycan_frame_results, ProteinGlycanContactFrameResult),
        ):
            if not isinstance(results, tuple) or any(
                type(f) is not model for f in results
            ):
                raise ValueError("Invalid specialized frame result types")
            count = getattr(self.partner_catalog, f"{kind}_partner_count")
            if not count and results:
                raise ValueError("Absent partner kind must have no scientific frames")
            indexes = tuple(f.frame_index for f in results)
            if indexes != tuple(sorted(set(indexes))):
                raise ValueError("Scientific frame results must be unique and ordered")
            if any(getattr(f, f"{kind}_partner_count") != count for f in results):
                raise ValueError("Scientific partner count must match catalog")

    def catalog_binding(self) -> MolecularPartnerCatalogBinding:
        return MolecularPartnerCatalogBinding(
            self.execution_condition,
            self.dataset_spec,
            self.topology_connectivity_status,
            self.partner_catalog,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            **super().to_dict(),
            "lipid_frame_results": [f.to_dict() for f in self.lipid_frame_results],
            "glycan_frame_results": [f.to_dict() for f in self.glycan_frame_results],
        }


@dataclass(frozen=True)
class PreprocessingSpecializedContactExecution:
    condition_results: tuple[PreprocessingSpecializedContactConditionResult, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.condition_results, tuple) or any(
            type(c) is not PreprocessingSpecializedContactConditionResult
            for c in self.condition_results
        ):
            raise ValueError("Invalid specialized condition results")
        if self.condition_results:
            self.catalog()

    def catalog(self) -> PreprocessingMolecularPartnerCatalog:
        return PreprocessingMolecularPartnerCatalog(
            tuple(c.catalog_binding() for c in self.condition_results)
        )

    def to_dict(self) -> dict[str, object]:
        return {"condition_results": [c.to_dict() for c in self.condition_results]}


def _index(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or value < 0:
        raise ValueError("Source topology index must be a non-negative integer")
    return int(value)


def _optional(runtime: Any, name: str) -> Any:
    try:
        return getattr(runtime, name, None)
    except Exception:
        return None


def adapt_molecular_partner_topology(
    runtime: Any,
) -> tuple[MolecularPartnerTopology, tuple[int, ...]]:
    """Enumerated source residues and accepted selection; never inspect coordinates."""
    try:
        residues = tuple(runtime.residues)
        source = []
        for index, residue in enumerate(residues):
            # Source resindex is topology ordering, independent of resid.
            if _index(residue.ix) != index:
                raise ValueError(
                    "Runtime residue index must match source topology ordering"
                )
            resid = _optional(residue, "resid")
            if isinstance(resid, Integral) and not isinstance(resid, bool):
                resid = int(resid)
            segid = _optional(residue, "segid") or None
            source.append(
                SourceTopologyResidue(
                    index,
                    resid,
                    residue.resname,
                    segid,
                    tuple(sorted(_index(a.index) for a in residue.atoms)),
                )
            )
        selected, issue = _selected_contact_residue_items(
            runtime, PreprocessingContactDetectionOptions(contact_selection="protein")
        )
        if issue is not None:
            raise ValueError("Accepted protein selection unavailable")
        selected_runtime = cast(tuple[Any, ...], selected)
        protein = tuple(sorted({_index(r.ix) for r in selected_runtime}))
        if not protein or any(i >= len(source) for i in protein):
            raise ValueError("Protein membership cannot be established")
        for residue in selected_runtime:
            if (
                tuple(sorted(_index(a.index) for a in residue.atoms))
                != source[_index(residue.ix)].atom_indexes
            ):
                raise ValueError(
                    "Protein selection must match source topology membership"
                )
        # Successful empty bond collection is distinct from unavailable bond access.
        try:
            runtime_bonds = tuple(runtime.bonds)
            if any(bool(_optional(b, "is_guessed")) for b in runtime_bonds):
                raise ValueError("Guessed bonds are not authoritative connectivity")
            bond_indexes = tuple(tuple(b.indices) for b in runtime_bonds)
        except Exception:
            topology = MolecularPartnerTopology(tuple(source), (), "unavailable")
        else:
            bonds = tuple(
                sorted(
                    (SourceTopologyBond(_index(a), _index(b)) for a, b in bond_indexes),
                    key=lambda b: (b.atom_index_a, b.atom_index_b),
                )
            )
            topology = MolecularPartnerTopology(tuple(source), bonds, "available")
        return topology, protein
    except Exception:
        raise MolecularPartnerIdentificationExecutionError(
            "Authoritative topology or protein membership is unavailable or invalid."
        ) from None


# Valid chemical element symbols, not residue/force-field classifications. Values
# must come from topology metadata; names, masses and force-field types are unused.
_ELEMENTS = frozenset(
    (
        "H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni "
        "Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe "
        "Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au "
        "Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf "
        "Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og"
    ).split()
)


def authoritative_is_hydrogen(atom: Any, *, runtime: Any = None) -> bool:
    number = _optional(atom, "atomic_number")
    element = _optional(atom, "element")
    topology = _optional(runtime, "_topology")
    elements = _optional(topology, "elements")
    numbers = _optional(topology, "atomicnumbers")
    if bool(_optional(elements, "is_guessed")):
        element = None
    if bool(_optional(numbers, "is_guessed")):
        number = None
    evidence = []
    if number is not None:
        if (
            isinstance(number, bool)
            or not isinstance(number, Integral)
            or not 1 <= int(number) <= 118
        ):
            raise ValueError("Invalid atomic-number metadata")
        evidence.append(number == 1)
    if element is not None:
        if not isinstance(element, str) or element.capitalize() not in _ELEMENTS:
            raise ValueError("Invalid topology element metadata")
        evidence.append(element.capitalize() == "H")
    if not evidence or any(value != evidence[0] for value in evidence):
        raise ValueError(
            "Authoritative hydrogen/heavy identity is missing or contradictory"
        )
    return bool(evidence[0])


def execute_specialized_contact_condition(
    runtime: Any,
    binding: PreprocessingConditionTemporalExecution,
    metadata: MolecularPartnerMetadata,
) -> PreprocessingSpecializedContactConditionResult:
    topology, protein = adapt_molecular_partner_topology(runtime)
    try:
        catalog = identify_molecular_partners(
            topology,
            protein_residue_indexes=protein,
            classifications=metadata.classifications,
            explicit_partners=metadata.explicit_partners,
        )
    except Exception:
        raise MolecularPartnerIdentificationExecutionError(
            "Molecular partner evidence is inconsistent."
        ) from None
    lipids: list[ProteinLipidContactFrameResult] = []
    glycans: list[ProteinGlycanContactFrameResult] = []
    if catalog.partner_count:
        try:
            required = {
                a
                for r in topology.residues
                if r.residue_index in protein
                for a in r.atom_indexes
            }
            required.update(
                a for p in catalog.partners for a in p.component_atom_indexes
            )
            atoms = {
                _index(a.index): a
                for r in runtime.residues
                for a in r.atoms
                if _index(a.index) in required
            }
            hydrogen = {
                i: authoritative_is_hydrogen(atoms[i], runtime=runtime)
                for i in sorted(required)
            }
            times = {
                s.source_frame_index: s.actual_time_ps
                for s in binding.sampling_plan.selected_samples
            }
            for index, _ in iter_selected_trajectory_frames(
                runtime.trajectory, binding.selected_source_frame_indexes
            ):
                coordinates_list = []
                for i in sorted(required):
                    x, y, z = (float(v) for v in atoms[i].position)
                    coordinates_list.append(
                        SourceAtomFrameCoordinate(i, x, y, z, hydrogen[i])
                    )
                coordinates = tuple(coordinates_list)
                # Retained Stage 27 time is informational for frame geometry.
                time = times[index]
                if catalog.lipid_partner_count:
                    lipids.append(
                        compute_protein_lipid_contacts(
                            ProteinLipidContactFrameInput(
                                index, time, topology, catalog, protein, coordinates
                            )
                        )
                    )
                if catalog.glycan_partner_count:
                    glycans.append(
                        compute_protein_glycan_contacts(
                            ProteinGlycanContactFrameInput(
                                index, time, topology, catalog, protein, coordinates
                            )
                        )
                    )
        except Exception:
            raise SpecializedContactComputationError(
                "Specialized frame geometry or atom identity is invalid."
            ) from None
    result = PreprocessingSpecializedContactConditionResult(
        binding.execution_condition,
        binding.dataset_spec,
        topology.connectivity_status,
        catalog,
        tuple(lipids),
        tuple(glycans),
    )
    for count, frames in (
        (catalog.lipid_partner_count, result.lipid_frame_results),
        (catalog.glycan_partner_count, result.glycan_frame_results),
    ):
        if (
            count
            and tuple(f.frame_index for f in frames)
            != binding.selected_source_frame_indexes
        ):
            raise SpecializedContactComputationError(
                "Scientific frames must exactly cover Stage 27 selection."
            )
    return result


def read_specialized_metadata_inputs(
    manifest: PreprocessingInputManifest,
    temporal: PreprocessingTemporalExecution,
    *,
    base_dir: Path,
) -> tuple[tuple[str, Path, MolecularPartnerMetadata], ...]:
    inputs = []
    for binding in temporal.bindings:
        path = manifest.get_condition(
            binding.execution_condition
        ).molecular_partner_metadata_path
        if path is not None:
            local = path if path.is_absolute() else base_dir / path
            inputs.append(
                (
                    binding.execution_condition,
                    local,
                    read_molecular_partner_metadata(local),
                )
            )
    return tuple(inputs)


def execute_preprocessing_specialized_contacts(
    runtime_loading: PreprocessingGraphWorkflowRuntimeLoadingResult,
    temporal: PreprocessingTemporalExecution,
    inputs: tuple[tuple[str, Path, MolecularPartnerMetadata], ...],
) -> PreprocessingSpecializedContactExecution:
    loaded = runtime_loading.runtime_load_result
    if not isinstance(loaded, PreprocessingManifestLoadResult):
        raise MolecularPartnerIdentificationExecutionError(
            "Authoritative loaded runtimes required."
        )
    results = []
    for condition, _, metadata in inputs:
        binding = next(
            b for b in temporal.bindings if b.execution_condition == condition
        )
        result = loaded.result_for_condition(condition) if loaded is not None else None
        if result is None or not result.passed or result.runtime is None:
            raise MolecularPartnerIdentificationExecutionError(
                "Loaded Dataset runtime is required."
            )
        results.append(
            execute_specialized_contact_condition(
                result.runtime.runtime_object, binding, metadata
            )
        )
    return PreprocessingSpecializedContactExecution(tuple(results))


def build_specialized_contact_source_tables(
    execution: PreprocessingSpecializedContactExecution,
    temporal: PreprocessingTemporalExecution,
) -> tuple["ProteinLipidWindowTable", "ProteinGlycanWindowTable"]:
    """Join retained frames to their authoritative temporal binding without I/O."""
    from mania.preprocessing.specialized_contact_window_tables import (
        build_protein_glycan_window_table,
        build_protein_lipid_window_table,
    )
    from mania.preprocessing.specialized_contact_windows import (
        aggregate_protein_glycan_contacts_by_window,
        aggregate_protein_lipid_contacts_by_window,
    )

    lipid_inputs, glycan_inputs = [], []
    conditions = {b.execution_condition: b for b in temporal.bindings}
    for result in execution.condition_results:
        binding = conditions[result.execution_condition]
        if result.dataset_spec != binding.dataset_spec:
            raise ValueError(
                "Specialized Dataset specification must match temporal binding"
            )
        lipid_inputs.append(
            (
                binding,
                aggregate_protein_lipid_contacts_by_window(
                    binding.sampling_plan,
                    binding.window_plan,
                    execution_condition=result.execution_condition,
                    frame_results=result.lipid_frame_results,
                    partner_count=result.partner_catalog.lipid_partner_count,
                ),
            )
        )
        glycan_inputs.append(
            (
                binding,
                aggregate_protein_glycan_contacts_by_window(
                    binding.sampling_plan,
                    binding.window_plan,
                    execution_condition=result.execution_condition,
                    frame_results=result.glycan_frame_results,
                    partner_count=result.partner_catalog.glycan_partner_count,
                ),
            )
        )
    return build_protein_lipid_window_table(
        tuple(lipid_inputs)
    ), build_protein_glycan_window_table(tuple(glycan_inputs))
