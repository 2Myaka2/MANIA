"""Pure Stage 29.B protein-lipid geometry on caller-supplied coordinates in Å.

No box input or internal minimum-image correction: coordinates must already
satisfy the external PBC preprocessing contract. No unit conversion is performed.
Only explicit non-hydrogen atoms participate; accepted Stage 29.A membership is
authoritative. Frame time is informational, not an episode/lifetime clock.
See docs/protein_lipid_contact_contract.md.
"""

from dataclasses import dataclass, field
from itertools import pairwise
from math import hypot, isfinite

from mania.preprocessing.molecular_partner_entities import (
    MolecularPartnerCatalog,
    MolecularPartnerTopology,
)

PROTEIN_LIPID_CONTACT_SCHEMA_VERSION = "mania.protein_lipid_contacts.v0.1"
PROTEIN_LIPID_CONTACT_KIND = "mania_protein_lipid_contacts"
PROTEIN_LIPID_CONTACT_CUTOFF_A = 6.0
PROTEIN_LIPID_DISTANCE_UNIT = "angstrom"
PROTEIN_LIPID_DISTANCE_DEFINITION = "minimum_heavy_atom_distance"


class ProteinLipidContactComputationError(ValueError):
    """Invalid frame geometry, source evidence, or contact result."""


def _require_index(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProteinLipidContactComputationError(
            f"{name} must be a non-negative integer"
        )


def _require_finite(value: object, name: str) -> None:
    valid = False
    if not isinstance(value, bool) and isinstance(value, (int, float)):
        try:
            valid = isfinite(value)
        except OverflowError:
            pass
    if not valid:
        raise ProteinLipidContactComputationError(f"{name} must be a finite number")


def _require_text(value: object, name: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ProteinLipidContactComputationError(
            f"{name} must be a non-empty stripped string"
        )


def _require_indexes(value: tuple[int, ...], name: str) -> None:
    if not isinstance(value, tuple) or not value:
        raise ProteinLipidContactComputationError(f"{name} must be a non-empty tuple")
    for index in value:
        _require_index(index, name)
    if any(b <= a for a, b in pairwise(value)):
        raise ProteinLipidContactComputationError(
            f"{name} must be strictly increasing and unique"
        )


def _require_frame(frame_index: int, time_ps: float | None) -> None:
    _require_index(frame_index, "frame_index")
    if time_ps is not None:
        _require_finite(time_ps, "time_ps")
        if time_ps < 0:
            raise ProteinLipidContactComputationError("time_ps must be non-negative")


@dataclass(frozen=True)
class SourceAtomFrameCoordinate:
    """Source atom identity and Cartesian Å coordinates with explicit atom typing."""

    atom_index: int
    x_A: float
    y_A: float
    z_A: float
    is_hydrogen: bool

    def __post_init__(self) -> None:
        _require_index(self.atom_index, "atom_index")
        for name in ("x_A", "y_A", "z_A"):
            _require_finite(getattr(self, name), name)
        if type(self.is_hydrogen) is not bool:
            raise ProteinLipidContactComputationError("is_hydrogen must be exact bool")

    def to_dict(self) -> dict[str, object]:
        return {
            "atom_index": self.atom_index,
            "x_A": self.x_A,
            "y_A": self.y_A,
            "z_A": self.z_A,
            "is_hydrogen": self.is_hydrogen,
        }


@dataclass(frozen=True)
class ProteinLipidContactFrameInput:
    """One complete frame for the explicit protein set and catalog lipid partners."""

    frame_index: int
    time_ps: float | None
    topology: MolecularPartnerTopology
    partner_catalog: MolecularPartnerCatalog
    protein_residue_indexes: tuple[int, ...]
    atom_coordinates: tuple[SourceAtomFrameCoordinate, ...]

    def __post_init__(self) -> None:
        _require_frame(self.frame_index, self.time_ps)
        if type(self.topology) is not MolecularPartnerTopology:
            raise ProteinLipidContactComputationError(
                "topology must be an exact MolecularPartnerTopology"
            )
        if type(self.partner_catalog) is not MolecularPartnerCatalog:
            raise ProteinLipidContactComputationError(
                "partner_catalog must be an exact MolecularPartnerCatalog"
            )
        _require_indexes(self.protein_residue_indexes, "protein_residue_indexes")
        residues = {r.residue_index: r for r in self.topology.residues}
        protein = set(self.protein_residue_indexes)
        if not protein <= residues.keys():
            raise ProteinLipidContactComputationError(
                "every protein residue must exist in topology"
            )

        # Check every catalog component, including glycans, without reidentifying
        # partners or requiring coordinates for non-lipid components.
        for partner in self.partner_catalog.partners:
            if not set(partner.component_residue_indexes) <= residues.keys():
                raise ProteinLipidContactComputationError(
                    "every partner component residue must exist in topology"
                )
            if protein.intersection(partner.component_residue_indexes):
                raise ProteinLipidContactComputationError(
                    "partner components must not overlap protein residues"
                )
            components = tuple(residues[i] for i in partner.component_residue_indexes)
            if partner.component_atom_indexes != tuple(
                sorted(a for r in components for a in r.atom_indexes)
            ):
                raise ProteinLipidContactComputationError(
                    "partner component atom union must match topology"
                )
            if partner.components != components:
                raise ProteinLipidContactComputationError(
                    "partner component source evidence must match topology"
                )

        if not isinstance(self.atom_coordinates, tuple) or any(
            type(c) is not SourceAtomFrameCoordinate for c in self.atom_coordinates
        ):
            raise ProteinLipidContactComputationError(
                "atom_coordinates must be a tuple of exact SourceAtomFrameCoordinate "
                "records"
            )
        indexes = tuple(c.atom_index for c in self.atom_coordinates)
        if any(b <= a for a, b in pairwise(indexes)):
            raise ProteinLipidContactComputationError(
                "coordinate atom indexes must be strictly increasing and unique"
            )
        supplied = set(indexes)
        topology_atoms = {a for r in self.topology.residues for a in r.atom_indexes}
        if not supplied <= topology_atoms:
            raise ProteinLipidContactComputationError(
                "every coordinate atom index must exist in topology"
            )
        required = {
            a for i in self.protein_residue_indexes for a in residues[i].atom_indexes
        }
        required.update(
            a
            for p in self.partner_catalog.partners
            if p.partner_kind == "lipid"
            for a in p.component_atom_indexes
        )
        if not required <= supplied:
            raise ProteinLipidContactComputationError(
                "coordinates are required for every protein and lipid partner atom"
            )


@dataclass(frozen=True)
class ProteinLipidContactObservation:
    """One positive protein-residue × accepted lipid-partner contact in one frame."""

    frame_index: int
    time_ps: float | None
    protein_residue_index: int
    protein_residue_id: int | str | None
    protein_resname: str
    protein_segid: str | None
    lipid_partner_id: str
    lipid_partner_name: str
    lipid_component_residue_indexes: tuple[int, ...]
    minimum_distance_A: float

    def __post_init__(self) -> None:
        _require_frame(self.frame_index, self.time_ps)
        _require_index(self.protein_residue_index, "protein_residue_index")
        if isinstance(self.protein_residue_id, bool) or (
            self.protein_residue_id is not None
            and not isinstance(self.protein_residue_id, (int, str))
        ):
            raise ProteinLipidContactComputationError(
                "protein_residue_id must be an integer, string, or None"
            )
        _require_text(self.protein_resname, "protein_resname")
        if self.protein_segid is not None:
            _require_text(self.protein_segid, "protein_segid")
        _require_text(self.lipid_partner_id, "lipid_partner_id")
        _require_text(self.lipid_partner_name, "lipid_partner_name")
        _require_indexes(
            self.lipid_component_residue_indexes, "lipid_component_residue_indexes"
        )
        if self.protein_residue_index in self.lipid_component_residue_indexes:
            raise ProteinLipidContactComputationError(
                "lipid components must not overlap the protein residue"
            )
        _require_finite(self.minimum_distance_A, "minimum_distance_A")
        if not 0 <= self.minimum_distance_A <= PROTEIN_LIPID_CONTACT_CUTOFF_A:
            raise ProteinLipidContactComputationError(
                "minimum_distance_A must be between 0 and 6.0 inclusive"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "frame_index": self.frame_index,
            "time_ps": self.time_ps,
            "protein_residue_index": self.protein_residue_index,
            "protein_residue_id": self.protein_residue_id,
            "protein_resname": self.protein_resname,
            "protein_segid": self.protein_segid,
            "lipid_partner_id": self.lipid_partner_id,
            "lipid_partner_name": self.lipid_partner_name,
            "lipid_component_residue_indexes": list(
                self.lipid_component_residue_indexes
            ),
            "minimum_distance_A": self.minimum_distance_A,
        }


@dataclass(frozen=True)
class ProteinLipidContactFrameResult:
    """Sparse positives and evaluated-pair counts for one valid frame."""

    schema_version: str = field(
        init=False, default=PROTEIN_LIPID_CONTACT_SCHEMA_VERSION
    )
    kind: str = field(init=False, default=PROTEIN_LIPID_CONTACT_KIND)
    cutoff_A: float = field(init=False, default=PROTEIN_LIPID_CONTACT_CUTOFF_A)
    distance_unit: str = field(init=False, default=PROTEIN_LIPID_DISTANCE_UNIT)
    distance_definition: str = field(
        init=False, default=PROTEIN_LIPID_DISTANCE_DEFINITION
    )
    frame_index: int
    time_ps: float | None
    protein_residue_count: int
    lipid_partner_count: int
    evaluated_pair_count: int
    contact_count: int
    contacts: tuple[ProteinLipidContactObservation, ...]

    def __post_init__(self) -> None:
        _require_frame(self.frame_index, self.time_ps)
        for name in (
            "protein_residue_count",
            "lipid_partner_count",
            "evaluated_pair_count",
            "contact_count",
        ):
            _require_index(getattr(self, name), name)
        if self.protein_residue_count == 0:
            raise ProteinLipidContactComputationError(
                "protein_residue_count must be positive"
            )
        if (
            self.evaluated_pair_count
            != self.protein_residue_count * self.lipid_partner_count
        ):
            raise ProteinLipidContactComputationError(
                "evaluated_pair_count must equal "
                "protein_residue_count * lipid_partner_count"
            )
        if not isinstance(self.contacts, tuple) or any(
            type(c) is not ProteinLipidContactObservation for c in self.contacts
        ):
            raise ProteinLipidContactComputationError(
                "contacts must be a tuple of exact "
                "ProteinLipidContactObservation records"
            )
        if (
            self.contact_count != len(self.contacts)
            or self.contact_count > self.evaluated_pair_count
        ):
            raise ProteinLipidContactComputationError(
                "contact_count must equal contacts length "
                "and not exceed evaluated_pair_count"
            )
        if any(
            (c.frame_index, c.time_ps) != (self.frame_index, self.time_ps)
            for c in self.contacts
        ):
            raise ProteinLipidContactComputationError(
                "all contacts must belong to the result frame and time"
            )
        keys = tuple(
            (c.protein_residue_index, c.lipid_partner_id) for c in self.contacts
        )
        if any(b <= a for a, b in pairwise(keys)):
            raise ProteinLipidContactComputationError(
                "contacts must be unique and ordered by "
                "protein_residue_index, lipid_partner_id"
            )
        if (
            len({c.protein_residue_index for c in self.contacts})
            > self.protein_residue_count
            or len({c.lipid_partner_id for c in self.contacts})
            > self.lipid_partner_count
        ):
            raise ProteinLipidContactComputationError(
                "observed protein and lipid identities must not exceed declared counts"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "cutoff_A": self.cutoff_A,
            "distance_unit": self.distance_unit,
            "distance_definition": self.distance_definition,
            "frame_index": self.frame_index,
            "time_ps": self.time_ps,
            "protein_residue_count": self.protein_residue_count,
            "lipid_partner_count": self.lipid_partner_count,
            "evaluated_pair_count": self.evaluated_pair_count,
            "contact_count": self.contact_count,
            "contacts": [c.to_dict() for c in self.contacts],
        }


def _heavy_coordinates(
    indexes: tuple[int, ...],
    coordinates: dict[int, SourceAtomFrameCoordinate],
    name: str,
) -> tuple[SourceAtomFrameCoordinate, ...]:
    heavy = tuple(
        coordinates[i] for i in indexes if coordinates[i].is_hydrogen is False
    )
    if not heavy:
        raise ProteinLipidContactComputationError(
            f"{name} must have at least one heavy atom"
        )
    return heavy


def _finite_float_bounds(
    heavy: tuple[SourceAtomFrameCoordinate, ...],
) -> tuple[float, float, float, float, float, float] | None:
    """Bound only native floats whose pairwise differences/norms stay finite."""
    # Mixed int/float subtraction can round differently from integer bounds.
    # Extreme finite coordinates must retain the original nonfinite-minimum
    # errors. With |coordinate| <= max_float/4, even the 3D norm stays finite.
    if any(
        type(value) is not float or not isfinite(4.0 * value)
        for atom in heavy
        for value in (atom.x_A, atom.y_A, atom.z_A)
    ):
        return None
    return (
        min(a.x_A for a in heavy),
        max(a.x_A for a in heavy),
        min(a.y_A for a in heavy),
        max(a.y_A for a in heavy),
        min(a.z_A for a in heavy),
        max(a.z_A for a in heavy),
    )


def compute_protein_lipid_contacts(
    frame: ProteinLipidContactFrameInput,
) -> ProteinLipidContactFrameResult:
    """Evaluate every supplied protein residue × catalog lipid, at fixed 6.0 Å.

    No PBC correction or unit conversion. Hydrogen status must be explicit.
    An invalid heavy-atom representation fails even when there are no lipids.
    """
    if type(frame) is not ProteinLipidContactFrameInput:
        raise ProteinLipidContactComputationError(
            "frame must be an exact ProteinLipidContactFrameInput"
        )
    residues = {r.residue_index: r for r in frame.topology.residues}
    coordinates = {c.atom_index: c for c in frame.atom_coordinates}
    protein_heavy = {
        i: _heavy_coordinates(residues[i].atom_indexes, coordinates, "protein residue")
        for i in frame.protein_residue_indexes
    }
    lipids = sorted(
        (p for p in frame.partner_catalog.partners if p.partner_kind == "lipid"),
        key=lambda p: p.partner_id,
    )
    lipid_heavy = {
        p.partner_id: _heavy_coordinates(
            p.component_atom_indexes, coordinates, "lipid partner"
        )
        for p in lipids
    }
    protein_bounds = {i: _finite_float_bounds(a) for i, a in protein_heavy.items()}
    lipid_bounds = {i: _finite_float_bounds(a) for i, a in lipid_heavy.items()}
    contacts = []
    for index in frame.protein_residue_indexes:
        residue = residues[index]
        protein_box = protein_bounds[index]
        for lipid in lipids:
            lipid_box = lipid_bounds[lipid.partner_id]
            # Reject only when an axis proves every heavy-heavy distance > 6 Å.
            # Surviving pairs retain the exact original minimum and atom order.
            if (
                protein_box is not None
                and lipid_box is not None
                and (
                    lipid_box[0] - protein_box[1] > PROTEIN_LIPID_CONTACT_CUTOFF_A
                    or protein_box[0] - lipid_box[1] > PROTEIN_LIPID_CONTACT_CUTOFF_A
                    or lipid_box[2] - protein_box[3] > PROTEIN_LIPID_CONTACT_CUTOFF_A
                    or protein_box[2] - lipid_box[3] > PROTEIN_LIPID_CONTACT_CUTOFF_A
                    or lipid_box[4] - protein_box[5] > PROTEIN_LIPID_CONTACT_CUTOFF_A
                    or protein_box[4] - lipid_box[5] > PROTEIN_LIPID_CONTACT_CUTOFF_A
                )
            ):
                continue
            # hypot computes sqrt(dx² + dy² + dz²) without intermediate squaring
            # overflow/underflow. Every heavy-heavy pair participates in the minimum.
            minimum = min(
                hypot(b.x_A - a.x_A, b.y_A - a.y_A, b.z_A - a.z_A)
                for a in protein_heavy[index]
                for b in lipid_heavy[lipid.partner_id]
            )
            _require_finite(minimum, "computed minimum_distance_A")
            if minimum <= PROTEIN_LIPID_CONTACT_CUTOFF_A:
                contacts.append(
                    ProteinLipidContactObservation(
                        frame.frame_index,
                        frame.time_ps,
                        residue.residue_index,
                        residue.residue_id,
                        residue.resname,
                        residue.segid,
                        lipid.partner_id,
                        lipid.partner_name,
                        lipid.component_residue_indexes,
                        minimum,
                    )
                )
    protein_count = len(frame.protein_residue_indexes)
    return ProteinLipidContactFrameResult(
        frame.frame_index,
        frame.time_ps,
        protein_count,
        len(lipids),
        protein_count * len(lipids),
        len(contacts),
        tuple(contacts),
    )


__all__ = [
    "PROTEIN_LIPID_CONTACT_CUTOFF_A",
    "PROTEIN_LIPID_CONTACT_KIND",
    "PROTEIN_LIPID_CONTACT_SCHEMA_VERSION",
    "PROTEIN_LIPID_DISTANCE_DEFINITION",
    "PROTEIN_LIPID_DISTANCE_UNIT",
    "ProteinLipidContactComputationError",
    "ProteinLipidContactFrameInput",
    "ProteinLipidContactFrameResult",
    "ProteinLipidContactObservation",
    "SourceAtomFrameCoordinate",
    "compute_protein_lipid_contacts",
]
