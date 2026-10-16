"""Deterministic protein residue-interaction chemistry."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from mania.preprocessing.trajectory_interaction_geometry import (
    AromaticRingGeometry,
    Coordinate,
    build_aromatic_ring_geometry,
    coordinate_angle_deg,
    coordinate_distance,
    detect_aromatic_pi_geometry,
    detect_cation_pi_distance,
)

_AROMATIC_RING_ATOMS = {
    "PHE": ("CG", "CD1", "CD2", "CE1", "CE2", "CZ"),
    "TYR": ("CG", "CD1", "CD2", "CE1", "CE2", "CZ"),
    "TRP": (
        "CG",
        "CD1",
        "CD2",
        "NE1",
        "CE2",
        "CE3",
        "CZ2",
        "CZ3",
        "CH2",
    ),
    "HIS": ("CG", "ND1", "CD2", "CE1", "NE2"),
    "HID": ("CG", "ND1", "CD2", "CE1", "NE2"),
    "HIE": ("CG", "ND1", "CD2", "CE1", "NE2"),
    "HIP": ("CG", "ND1", "CD2", "CE1", "NE2"),
}
_CATION_CENTER_ATOMS = {
    "LYS": "NZ",
    "ARG": "CZ",
}
_PI_EDGE_TYPES = ("aromatic_pi", "cation_pi")
_PROTEIN_RIN_EDGE_TYPES = (
    "hbond",
    "disulfide",
    "vdw",
    "hydrophobic",
    "ionic",
    "salt_bridge",
)

HBOND_MAX_DONOR_ACCEPTOR_DISTANCE_A = 3.5
HBOND_MIN_DONOR_HYDROGEN_ACCEPTOR_ANGLE_DEG = 120.0
DISULFIDE_MAX_SG_DISTANCE_A = 2.2
VDW_MIN_HEAVY_ATOM_DISTANCE_A = 3.0
VDW_MAX_HEAVY_ATOM_DISTANCE_A = 4.5
HYDROPHOBIC_MAX_CB_DISTANCE_A = 5.0
IONIC_MAX_CHARGED_ATOM_DISTANCE_A = 6.0
SALT_BRIDGE_MAX_CHARGED_ATOM_DISTANCE_A = 4.0

_HYDROPHOBIC_RESNAMES = frozenset(
    {"ALA", "VAL", "ILE", "LEU", "MET", "PHE", "TRP", "PRO", "TYR"}
)
_POSITIVE_CHARGED_ATOMS = {
    "LYS": ("NZ",),
    "ARG": ("NH1", "NH2"),
    "HIS": ("ND1", "NE2"),
    "HID": ("ND1", "NE2"),
    "HIE": ("ND1", "NE2"),
    "HIP": ("ND1", "NE2"),
}
_NEGATIVE_CHARGED_ATOMS = {
    "ASP": ("OD1", "OD2"),
    "GLU": ("OE1", "OE2"),
}
_SALT_BRIDGE_POSITIVE_ATOMS = {
    "LYS": ("NZ",),
    "ARG": ("NH1", "NH2"),
}
_SALT_BRIDGE_NEGATIVE_ATOMS = _NEGATIVE_CHARGED_ATOMS


@dataclass(frozen=True)
class ResidueChemistryCandidate:
    """Selected residue identity and its available named coordinates."""

    residue_index: int
    residue_id: int | str | None
    resname: str
    segid: str | None
    atom_coordinates: tuple[tuple[str, Coordinate], ...]
    heavy_atom_coordinates: tuple[tuple[str, Coordinate], ...] | None = None
    donor_hydrogen_coordinates: tuple[tuple[str, tuple[Coordinate, ...]], ...] = ()


@dataclass(frozen=True)
class AromaticRingCandidate:
    """One supported residue with a complete aromatic ring."""

    residue: ResidueChemistryCandidate
    geometry: AromaticRingGeometry


@dataclass(frozen=True)
class CationCenterCandidate:
    """One supported residue with a deterministic cation center."""

    residue: ResidueChemistryCandidate
    center: Coordinate


@dataclass(frozen=True)
class PiInteractionObservation:
    """One typed residue-pair interaction observed in one frame."""

    source: ResidueChemistryCandidate
    target: ResidueChemistryCandidate
    edge_type: str
    distance_A: float
    aromatic_pi_mode: str | None = None

    def __post_init__(self) -> None:
        if self.source.residue_index >= self.target.residue_index:
            raise ValueError("source residue index must precede target")
        if self.edge_type not in _PI_EDGE_TYPES:
            raise ValueError("edge_type must be aromatic_pi or cation_pi")


@dataclass(frozen=True)
class ProteinRinInteractionObservation:
    """One non-π typed protein interaction observed in one frame."""

    source: ResidueChemistryCandidate
    target: ResidueChemistryCandidate
    edge_type: str
    distance_A: float

    def __post_init__(self) -> None:
        if self.source.residue_index >= self.target.residue_index:
            raise ValueError("source residue index must precede target")
        if self.edge_type not in _PROTEIN_RIN_EDGE_TYPES:
            raise ValueError("edge_type must be a supported protein RIN type")


def build_aromatic_ring_candidate(
    residue: ResidueChemistryCandidate,
) -> AromaticRingCandidate | None:
    """Build a complete supported aromatic ring, skipping incomplete data."""
    required_names = _AROMATIC_RING_ATOMS.get(residue.resname.upper())
    if required_names is None:
        return None
    coordinates_by_name = dict(residue.atom_coordinates)
    if any(name not in coordinates_by_name for name in required_names):
        return None
    geometry = build_aromatic_ring_geometry(
        tuple(coordinates_by_name[name] for name in required_names)
    )
    if geometry is None:
        return None
    return AromaticRingCandidate(residue=residue, geometry=geometry)


def build_cation_center_candidate(
    residue: ResidueChemistryCandidate,
) -> CationCenterCandidate | None:
    """Return LYS NZ or ARG CZ as the supported cation center."""
    center_name = _CATION_CENTER_ATOMS.get(residue.resname.upper())
    if center_name is None:
        return None
    coordinates_by_name = dict(residue.atom_coordinates)
    center = coordinates_by_name.get(center_name)
    if center is None:
        return None
    return CationCenterCandidate(residue=residue, center=center)


def detect_pi_interactions(
    residues: tuple[ResidueChemistryCandidate, ...],
) -> tuple[PiInteractionObservation, ...]:
    """Detect aromatic π–π and cation-π contacts for selected residues."""
    ring_candidates: list[AromaticRingCandidate] = []
    cation_candidates: list[CationCenterCandidate] = []
    for residue in residues:
        ring_candidate = build_aromatic_ring_candidate(residue)
        if ring_candidate is not None:
            ring_candidates.append(ring_candidate)
        cation_candidate = build_cation_center_candidate(residue)
        if cation_candidate is not None:
            cation_candidates.append(cation_candidate)
    rings = tuple(ring_candidates)
    cations = tuple(cation_candidates)
    observations = [*_aromatic_pi_observations(rings)]
    observations.extend(_cation_pi_observations(cations, rings))
    return tuple(
        sorted(
            observations,
            key=lambda item: (
                item.source.residue_index,
                item.target.residue_index,
                item.edge_type,
                item.distance_A,
            ),
        )
    )


def detect_protein_rin_interactions(
    residues: tuple[ResidueChemistryCandidate, ...],
) -> tuple[PiInteractionObservation | ProteinRinInteractionObservation, ...]:
    """Detect all supported typed protein interactions in one sampled frame.

    Hydrogen bonds require an explicit donor-to-hydrogen relationship supplied
    by the runtime topology. No hydrogen coordinates are inferred.
    """
    observations: list[PiInteractionObservation | ProteinRinInteractionObservation] = (
        list(detect_pi_interactions(residues))
    )
    observations.extend(_hbond_observations(residues))
    observations.extend(_pairwise_rin_observations(residues))
    return tuple(
        sorted(
            observations,
            key=lambda item: (
                item.source.residue_index,
                item.target.residue_index,
                item.edge_type,
                item.distance_A,
            ),
        )
    )


def _hbond_observations(
    residues: tuple[ResidueChemistryCandidate, ...],
) -> tuple[ProteinRinInteractionObservation, ...]:
    observations_by_pair: dict[tuple[int, int], ProteinRinInteractionObservation] = {}
    for donor_residue in residues:
        donor_hydrogens = dict(donor_residue.donor_hydrogen_coordinates)
        for donor_name, donor_coordinate in donor_residue.atom_coordinates:
            hydrogens = donor_hydrogens.get(donor_name, ())
            if not hydrogens or not _is_nitrogen_or_oxygen(donor_name):
                continue
            for acceptor_residue in residues:
                if donor_residue.residue_index == acceptor_residue.residue_index:
                    continue
                for (
                    acceptor_name,
                    acceptor_coordinate,
                ) in acceptor_residue.atom_coordinates:
                    if not _is_nitrogen_or_oxygen(acceptor_name):
                        continue
                    distance = coordinate_distance(
                        donor_coordinate,
                        acceptor_coordinate,
                    )
                    if distance > HBOND_MAX_DONOR_ACCEPTOR_DISTANCE_A:
                        continue
                    if not any(
                        (
                            angle := coordinate_angle_deg(
                                donor_coordinate,
                                hydrogen_coordinate,
                                acceptor_coordinate,
                            )
                        )
                        is not None
                        and angle >= HBOND_MIN_DONOR_HYDROGEN_ACCEPTOR_ANGLE_DEG
                        for hydrogen_coordinate in hydrogens
                    ):
                        continue
                    source, target = _canonical_residues(
                        donor_residue,
                        acceptor_residue,
                    )
                    _remember_shortest_observation(
                        observations_by_pair,
                        ProteinRinInteractionObservation(
                            source=source,
                            target=target,
                            edge_type="hbond",
                            distance_A=distance,
                        ),
                    )
    return tuple(observations_by_pair.values())


def _pairwise_rin_observations(
    residues: tuple[ResidueChemistryCandidate, ...],
) -> tuple[ProteinRinInteractionObservation, ...]:
    observations: list[ProteinRinInteractionObservation] = []
    for source_offset, source in enumerate(residues):
        for target in residues[source_offset + 1 :]:
            source, target = _canonical_residues(source, target)
            for edge_type, distance in _pair_semantics(source, target):
                observations.append(
                    ProteinRinInteractionObservation(
                        source=source,
                        target=target,
                        edge_type=edge_type,
                        distance_A=distance,
                    )
                )
    return tuple(observations)


def _pair_semantics(
    source: ResidueChemistryCandidate,
    target: ResidueChemistryCandidate,
) -> tuple[tuple[str, float], ...]:
    detected: list[tuple[str, float]] = []
    source_atoms = dict(source.atom_coordinates)
    target_atoms = dict(target.atom_coordinates)

    if source.resname.upper() == target.resname.upper() == "CYS":
        sg_distance = _named_atom_distance(source_atoms, target_atoms, "SG", "SG")
        if sg_distance is not None and sg_distance <= DISULFIDE_MAX_SG_DISTANCE_A:
            detected.append(("disulfide", sg_distance))

    heavy_distance = _minimum_coordinate_distance(
        _heavy_coordinates(source),
        _heavy_coordinates(target),
    )
    if (
        heavy_distance is not None
        and VDW_MIN_HEAVY_ATOM_DISTANCE_A
        <= heavy_distance
        <= VDW_MAX_HEAVY_ATOM_DISTANCE_A
    ):
        detected.append(("vdw", heavy_distance))

    if (
        source.resname.upper() in _HYDROPHOBIC_RESNAMES
        and target.resname.upper() in _HYDROPHOBIC_RESNAMES
    ):
        cb_distance = _named_atom_distance(source_atoms, target_atoms, "CB", "CB")
        if cb_distance is not None and cb_distance <= HYDROPHOBIC_MAX_CB_DISTANCE_A:
            detected.append(("hydrophobic", cb_distance))

    ionic_distance = _opposite_charge_distance(
        source,
        target,
        positive_atoms=_POSITIVE_CHARGED_ATOMS,
        negative_atoms=_NEGATIVE_CHARGED_ATOMS,
    )
    if (
        ionic_distance is not None
        and ionic_distance <= IONIC_MAX_CHARGED_ATOM_DISTANCE_A
    ):
        detected.append(("ionic", ionic_distance))

    salt_bridge_distance = _opposite_charge_distance(
        source,
        target,
        positive_atoms=_SALT_BRIDGE_POSITIVE_ATOMS,
        negative_atoms=_SALT_BRIDGE_NEGATIVE_ATOMS,
    )
    if (
        salt_bridge_distance is not None
        and salt_bridge_distance <= SALT_BRIDGE_MAX_CHARGED_ATOM_DISTANCE_A
    ):
        detected.append(("salt_bridge", salt_bridge_distance))
    return tuple(detected)


def _heavy_coordinates(
    residue: ResidueChemistryCandidate,
) -> tuple[Coordinate, ...]:
    if residue.heavy_atom_coordinates is not None:
        return tuple(coordinate for _, coordinate in residue.heavy_atom_coordinates)
    return tuple(
        coordinate
        for atom_name, coordinate in residue.atom_coordinates
        if not _is_hydrogen_name(atom_name)
    )


def _opposite_charge_distance(
    source: ResidueChemistryCandidate,
    target: ResidueChemistryCandidate,
    *,
    positive_atoms: Mapping[str, tuple[str, ...]],
    negative_atoms: Mapping[str, tuple[str, ...]],
) -> float | None:
    source_name = source.resname.upper()
    target_name = target.resname.upper()
    if source_name in positive_atoms and target_name in negative_atoms:
        positive, negative = source, target
    elif target_name in positive_atoms and source_name in negative_atoms:
        positive, negative = target, source
    else:
        return None
    positive_coordinates = _available_named_coordinates(
        positive,
        positive_atoms[positive.resname.upper()],
    )
    negative_coordinates = _available_named_coordinates(
        negative,
        negative_atoms[negative.resname.upper()],
    )
    return _minimum_coordinate_distance(
        positive_coordinates,
        negative_coordinates,
    )


def _available_named_coordinates(
    residue: ResidueChemistryCandidate,
    names: tuple[str, ...],
) -> tuple[Coordinate, ...]:
    coordinates = dict(residue.atom_coordinates)
    return tuple(coordinates[name] for name in names if name in coordinates)


def _named_atom_distance(
    source_atoms: dict[str, Coordinate],
    target_atoms: dict[str, Coordinate],
    source_name: str,
    target_name: str,
) -> float | None:
    source_coordinate = source_atoms.get(source_name)
    target_coordinate = target_atoms.get(target_name)
    if source_coordinate is None or target_coordinate is None:
        return None
    return coordinate_distance(source_coordinate, target_coordinate)


def _minimum_coordinate_distance(
    source_coordinates: tuple[Coordinate, ...],
    target_coordinates: tuple[Coordinate, ...],
) -> float | None:
    if not source_coordinates or not target_coordinates:
        return None
    return min(
        coordinate_distance(source, target)
        for source in source_coordinates
        for target in target_coordinates
    )


def _remember_shortest_observation(
    observations: dict[tuple[int, int], ProteinRinInteractionObservation],
    observation: ProteinRinInteractionObservation,
) -> None:
    key = (observation.source.residue_index, observation.target.residue_index)
    previous = observations.get(key)
    if previous is None or observation.distance_A < previous.distance_A:
        observations[key] = observation


def _is_nitrogen_or_oxygen(atom_name: str) -> bool:
    stripped = atom_name.lstrip("0123456789").upper()
    return stripped.startswith(("N", "O"))


def _is_hydrogen_name(atom_name: str) -> bool:
    return atom_name.lstrip("0123456789").upper().startswith("H")


def _aromatic_pi_observations(
    rings: tuple[AromaticRingCandidate, ...],
) -> tuple[PiInteractionObservation, ...]:
    observations: list[PiInteractionObservation] = []
    for source_offset, source_ring in enumerate(rings):
        for target_ring in rings[source_offset + 1 :]:
            geometry = detect_aromatic_pi_geometry(
                source_ring.geometry,
                target_ring.geometry,
            )
            if geometry is None:
                continue
            source, target = _canonical_residues(
                source_ring.residue,
                target_ring.residue,
            )
            observations.append(
                PiInteractionObservation(
                    source=source,
                    target=target,
                    edge_type="aromatic_pi",
                    distance_A=geometry.distance_A,
                    aromatic_pi_mode=geometry.mode,
                )
            )
    return tuple(observations)


def _cation_pi_observations(
    cations: tuple[CationCenterCandidate, ...],
    rings: tuple[AromaticRingCandidate, ...],
) -> tuple[PiInteractionObservation, ...]:
    observations_by_pair: dict[
        tuple[int, int],
        PiInteractionObservation,
    ] = {}
    for cation in cations:
        for ring in rings:
            if cation.residue.residue_index == ring.residue.residue_index:
                continue
            distance = detect_cation_pi_distance(
                cation.center,
                ring.geometry.centroid,
            )
            if distance is None:
                continue
            source, target = _canonical_residues(
                cation.residue,
                ring.residue,
            )
            key = (source.residue_index, target.residue_index)
            observation = PiInteractionObservation(
                source=source,
                target=target,
                edge_type="cation_pi",
                distance_A=distance,
            )
            previous = observations_by_pair.get(key)
            if previous is None or distance < previous.distance_A:
                observations_by_pair[key] = observation
    return tuple(observations_by_pair.values())


def _canonical_residues(
    first: ResidueChemistryCandidate,
    second: ResidueChemistryCandidate,
) -> tuple[ResidueChemistryCandidate, ResidueChemistryCandidate]:
    if second.residue_index < first.residue_index:
        return second, first
    return first, second


__all__ = [
    "AromaticRingCandidate",
    "CationCenterCandidate",
    "PiInteractionObservation",
    "ProteinRinInteractionObservation",
    "ResidueChemistryCandidate",
    "build_aromatic_ring_candidate",
    "build_cation_center_candidate",
    "detect_pi_interactions",
    "detect_protein_rin_interactions",
]
