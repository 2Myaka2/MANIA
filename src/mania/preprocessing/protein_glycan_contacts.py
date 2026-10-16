"""Pure Stage 29.C protein-glycan geometry on caller-supplied coordinates in Å.

No box input or internal minimum-image correction: coordinates must already
satisfy the external PBC preprocessing contract. No unit conversion is performed.
Only explicit non-hydrogen atoms participate; accepted Stage 29.A membership is
authoritative. Frame time is informational, not an episode/lifetime clock.
Raw carrier geometry is retained with explicit future-summary exclusion evidence.
See docs/protein_glycan_contact_contract.md.
"""

from dataclasses import dataclass, field
from itertools import pairwise
from math import hypot, isfinite

from mania.preprocessing.molecular_partner_entities import (
    IdentifiedMolecularPartner,
    MolecularPartnerCatalog,
    MolecularPartnerTopology,
    SourceTopologyResidue,
)
from mania.preprocessing.protein_lipid_contacts import SourceAtomFrameCoordinate

PROTEIN_GLYCAN_CONTACT_SCHEMA_VERSION = "mania.protein_glycan_contacts.v0.1"
PROTEIN_GLYCAN_CONTACT_KIND = "mania_protein_glycan_contacts"
PROTEIN_GLYCAN_CONTACT_CUTOFF_A = 4.5
PROTEIN_GLYCAN_DISTANCE_UNIT = "angstrom"
PROTEIN_GLYCAN_DISTANCE_DEFINITION = "minimum_heavy_atom_distance"
PROTEIN_GLYCAN_COVALENT_EXCLUSION_REASON = "covalent_carrier_first_sugar_linkage"


class ProteinGlycanContactComputationError(ValueError):
    """Invalid frame geometry, source evidence, or contact result."""


def _require_index(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProteinGlycanContactComputationError(
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
        raise ProteinGlycanContactComputationError(f"{name} must be a finite number")


def _require_text(value: object, name: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ProteinGlycanContactComputationError(
            f"{name} must be a non-empty stripped string"
        )


def _require_indexes(value: tuple[int, ...], name: str) -> None:
    if not isinstance(value, tuple) or not value:
        raise ProteinGlycanContactComputationError(f"{name} must be a non-empty tuple")
    for index in value:
        _require_index(index, name)
    if any(b <= a for a, b in pairwise(value)):
        raise ProteinGlycanContactComputationError(
            f"{name} must be strictly increasing and unique"
        )


def _require_frame(frame_index: int, time_ps: float | None) -> None:
    _require_index(frame_index, "frame_index")
    if time_ps is not None:
        _require_finite(time_ps, "time_ps")
        if time_ps < 0:
            raise ProteinGlycanContactComputationError("time_ps must be non-negative")


def _linkage_evidence(
    partner: IdentifiedMolecularPartner,
    topology: MolecularPartnerTopology,
    residues: dict[int, SourceTopologyResidue],
    protein: tuple[int, ...],
) -> tuple[int, int, str, int | None, int | None]:
    """Check accepted linkage against supplied topology; never identify or repair."""
    carrier = partner.carrier_residue_index
    first = partner.first_sugar_residue_index
    _require_index(carrier, "carrier_residue_index")
    _require_index(first, "first_sugar_residue_index")
    if carrier is None or carrier not in residues:
        raise ProteinGlycanContactComputationError("carrier must exist in topology")
    if carrier not in protein:
        raise ProteinGlycanContactComputationError(
            "carrier must belong to protein_residue_indexes"
        )
    if (
        first is None
        or first not in residues
        or first not in partner.component_residue_indexes
    ):
        raise ProteinGlycanContactComputationError(
            "first sugar must exist in topology and belong to glycan components"
        )
    bond = partner.carrier_link_bond
    evidence = partner.linkage_evidence
    if evidence == "external_metadata":
        if (
            partner.identification_mode != "explicit_mapping"
            or topology.connectivity_status != "unavailable"
            or bond is not None
        ):
            raise ProteinGlycanContactComputationError(
                "external linkage requires explicit mapping, unavailable "
                "connectivity, and no bond"
            )
        return carrier, first, evidence, None, None
    if (
        evidence != "topology_connectivity"
        or topology.connectivity_status != "available"
        or bond is None
        or bond not in topology.bonds
    ):
        raise ProteinGlycanContactComputationError(
            "topology linkage requires the accepted carrier bond in topology"
        )
    a, b = bond.atom_index_a, bond.atom_index_b
    if a in residues[carrier].atom_indexes and b in residues[first].atom_indexes:
        return carrier, first, evidence, a, b
    if b in residues[carrier].atom_indexes and a in residues[first].atom_indexes:
        return carrier, first, evidence, b, a
    raise ProteinGlycanContactComputationError(
        "carrier bond endpoints must belong to carrier and first sugar"
    )


@dataclass(frozen=True)
class ProteinGlycanContactFrameInput:
    """One complete frame for the explicit protein set and catalog glycan partners."""

    frame_index: int
    time_ps: float | None
    topology: MolecularPartnerTopology
    partner_catalog: MolecularPartnerCatalog
    protein_residue_indexes: tuple[int, ...]
    atom_coordinates: tuple[SourceAtomFrameCoordinate, ...]

    def __post_init__(self) -> None:
        _require_frame(self.frame_index, self.time_ps)
        if type(self.topology) is not MolecularPartnerTopology:
            raise ProteinGlycanContactComputationError(
                "topology must be an exact MolecularPartnerTopology"
            )
        if type(self.partner_catalog) is not MolecularPartnerCatalog:
            raise ProteinGlycanContactComputationError(
                "partner_catalog must be an exact MolecularPartnerCatalog"
            )
        _require_indexes(self.protein_residue_indexes, "protein_residue_indexes")
        residues = {r.residue_index: r for r in self.topology.residues}
        protein = set(self.protein_residue_indexes)
        if not protein <= residues.keys():
            raise ProteinGlycanContactComputationError(
                "every protein residue must exist in topology"
            )

        # Check every catalog component, including lipids, without reidentifying
        # partners or requiring coordinates for non-glycan components.
        for partner in self.partner_catalog.partners:
            if not set(partner.component_residue_indexes) <= residues.keys():
                raise ProteinGlycanContactComputationError(
                    "every partner component residue must exist in topology"
                )
            if protein.intersection(partner.component_residue_indexes):
                raise ProteinGlycanContactComputationError(
                    "partner components must not overlap protein residues"
                )
            components = tuple(residues[i] for i in partner.component_residue_indexes)
            if partner.component_atom_indexes != tuple(
                sorted(a for r in components for a in r.atom_indexes)
            ):
                raise ProteinGlycanContactComputationError(
                    "partner component atom union must match topology"
                )
            if partner.components != components:
                raise ProteinGlycanContactComputationError(
                    "partner component source evidence must match topology"
                )
            if partner.partner_kind == "glycan":
                _linkage_evidence(
                    partner, self.topology, residues, self.protein_residue_indexes
                )

        if not isinstance(self.atom_coordinates, tuple) or any(
            type(c) is not SourceAtomFrameCoordinate for c in self.atom_coordinates
        ):
            raise ProteinGlycanContactComputationError(
                "atom_coordinates must be a tuple of exact SourceAtomFrameCoordinate "
                "records"
            )
        indexes = tuple(c.atom_index for c in self.atom_coordinates)
        if any(b <= a for a, b in pairwise(indexes)):
            raise ProteinGlycanContactComputationError(
                "coordinate atom indexes must be strictly increasing and unique"
            )
        supplied = set(indexes)
        topology_atoms = {a for r in self.topology.residues for a in r.atom_indexes}
        if not supplied <= topology_atoms:
            raise ProteinGlycanContactComputationError(
                "every coordinate atom index must exist in topology"
            )
        required = {
            a for i in self.protein_residue_indexes for a in residues[i].atom_indexes
        }
        required.update(
            a
            for p in self.partner_catalog.partners
            if p.partner_kind == "glycan"
            for a in p.component_atom_indexes
        )
        if not required <= supplied:
            raise ProteinGlycanContactComputationError(
                "coordinates are required for every protein and glycan partner atom"
            )


@dataclass(frozen=True)
class ProteinGlycanContactObservation:
    """One positive protein-residue × accepted glycan-partner contact in one frame."""

    frame_index: int
    time_ps: float | None
    protein_residue_index: int
    protein_residue_id: int | str | None
    protein_resname: str
    protein_segid: str | None
    glycan_partner_id: str
    glycan_partner_name: str
    glycan_component_residue_indexes: tuple[int, ...]
    carrier_residue_index: int
    first_sugar_residue_index: int
    linkage_evidence: str
    carrier_link_atom_index: int | None
    first_sugar_link_atom_index: int | None
    standard_summary_excluded: bool
    standard_summary_exclusion_reason: str | None
    minimum_distance_A: float

    def __post_init__(self) -> None:
        _require_frame(self.frame_index, self.time_ps)
        _require_index(self.protein_residue_index, "protein_residue_index")
        if isinstance(self.protein_residue_id, bool) or (
            self.protein_residue_id is not None
            and not isinstance(self.protein_residue_id, (int, str))
        ):
            raise ProteinGlycanContactComputationError(
                "protein_residue_id must be an integer, string, or None"
            )
        _require_text(self.protein_resname, "protein_resname")
        if self.protein_segid is not None:
            _require_text(self.protein_segid, "protein_segid")
        _require_text(self.glycan_partner_id, "glycan_partner_id")
        _require_text(self.glycan_partner_name, "glycan_partner_name")
        _require_indexes(
            self.glycan_component_residue_indexes, "glycan_component_residue_indexes"
        )
        if self.protein_residue_index in self.glycan_component_residue_indexes:
            raise ProteinGlycanContactComputationError(
                "glycan components must not overlap the protein residue"
            )
        _require_index(self.carrier_residue_index, "carrier_residue_index")
        _require_index(self.first_sugar_residue_index, "first_sugar_residue_index")
        if self.carrier_residue_index in self.glycan_component_residue_indexes:
            raise ProteinGlycanContactComputationError(
                "carrier must be outside glycan components"
            )
        if self.first_sugar_residue_index not in self.glycan_component_residue_indexes:
            raise ProteinGlycanContactComputationError(
                "first sugar must belong to glycan components"
            )
        atoms = (self.carrier_link_atom_index, self.first_sugar_link_atom_index)
        if self.linkage_evidence == "topology_connectivity":
            for name, atom in zip(
                ("carrier_link_atom_index", "first_sugar_link_atom_index"),
                atoms,
                strict=True,
            ):
                _require_index(atom, name)
            if atoms[0] == atoms[1]:
                raise ProteinGlycanContactComputationError(
                    "carrier and first sugar link atoms must differ"
                )
        elif self.linkage_evidence == "external_metadata":
            if atoms != (None, None):
                raise ProteinGlycanContactComputationError(
                    "external linkage atom evidence must be None"
                )
        else:
            raise ProteinGlycanContactComputationError("unsupported linkage_evidence")
        excluded = self.protein_residue_index == self.carrier_residue_index
        reason = PROTEIN_GLYCAN_COVALENT_EXCLUSION_REASON if excluded else None
        if (
            self.standard_summary_excluded is not excluded
            or self.standard_summary_exclusion_reason != reason
        ):
            raise ProteinGlycanContactComputationError(
                "standard summary exclusion must exactly match carrier linkage"
            )
        _require_finite(self.minimum_distance_A, "minimum_distance_A")
        if not 0 <= self.minimum_distance_A <= PROTEIN_GLYCAN_CONTACT_CUTOFF_A:
            raise ProteinGlycanContactComputationError(
                "minimum_distance_A must be between 0 and 4.5 inclusive"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "frame_index": self.frame_index,
            "time_ps": self.time_ps,
            "protein_residue_index": self.protein_residue_index,
            "protein_residue_id": self.protein_residue_id,
            "protein_resname": self.protein_resname,
            "protein_segid": self.protein_segid,
            "glycan_partner_id": self.glycan_partner_id,
            "glycan_partner_name": self.glycan_partner_name,
            "glycan_component_residue_indexes": list(
                self.glycan_component_residue_indexes
            ),
            "carrier_residue_index": self.carrier_residue_index,
            "first_sugar_residue_index": self.first_sugar_residue_index,
            "linkage_evidence": self.linkage_evidence,
            "carrier_link_atom_index": self.carrier_link_atom_index,
            "first_sugar_link_atom_index": self.first_sugar_link_atom_index,
            "standard_summary_excluded": self.standard_summary_excluded,
            "standard_summary_exclusion_reason": self.standard_summary_exclusion_reason,
            "minimum_distance_A": self.minimum_distance_A,
        }


@dataclass(frozen=True)
class ProteinGlycanContactFrameResult:
    """Sparse positives and evaluated-pair counts for one valid frame."""

    schema_version: str = field(
        init=False, default=PROTEIN_GLYCAN_CONTACT_SCHEMA_VERSION
    )
    kind: str = field(init=False, default=PROTEIN_GLYCAN_CONTACT_KIND)
    cutoff_A: float = field(init=False, default=PROTEIN_GLYCAN_CONTACT_CUTOFF_A)
    distance_unit: str = field(init=False, default=PROTEIN_GLYCAN_DISTANCE_UNIT)
    distance_definition: str = field(
        init=False, default=PROTEIN_GLYCAN_DISTANCE_DEFINITION
    )
    frame_index: int
    time_ps: float | None
    protein_residue_count: int
    glycan_partner_count: int
    evaluated_pair_count: int
    contact_count: int
    excluded_contact_count: int
    contacts: tuple[ProteinGlycanContactObservation, ...]

    def __post_init__(self) -> None:
        _require_frame(self.frame_index, self.time_ps)
        for name in (
            "protein_residue_count",
            "glycan_partner_count",
            "evaluated_pair_count",
            "contact_count",
            "excluded_contact_count",
        ):
            _require_index(getattr(self, name), name)
        if self.protein_residue_count == 0:
            raise ProteinGlycanContactComputationError(
                "protein_residue_count must be positive"
            )
        if (
            self.evaluated_pair_count
            != self.protein_residue_count * self.glycan_partner_count
        ):
            raise ProteinGlycanContactComputationError(
                "evaluated_pair_count must equal "
                "protein_residue_count * glycan_partner_count"
            )
        if not isinstance(self.contacts, tuple) or any(
            type(c) is not ProteinGlycanContactObservation for c in self.contacts
        ):
            raise ProteinGlycanContactComputationError(
                "contacts must be a tuple of exact "
                "ProteinGlycanContactObservation records"
            )
        if (
            self.contact_count != len(self.contacts)
            or self.contact_count > self.evaluated_pair_count
        ):
            raise ProteinGlycanContactComputationError(
                "contact_count must equal contacts length "
                "and not exceed evaluated_pair_count"
            )
        if self.excluded_contact_count != sum(
            c.standard_summary_excluded for c in self.contacts
        ):
            raise ProteinGlycanContactComputationError(
                "excluded_contact_count must equal the number of excluded contacts"
            )
        if any(
            (c.frame_index, c.time_ps) != (self.frame_index, self.time_ps)
            for c in self.contacts
        ):
            raise ProteinGlycanContactComputationError(
                "all contacts must belong to the result frame and time"
            )
        keys = tuple(
            (c.protein_residue_index, c.glycan_partner_id) for c in self.contacts
        )
        if any(b <= a for a, b in pairwise(keys)):
            raise ProteinGlycanContactComputationError(
                "contacts must be unique and ordered by "
                "protein_residue_index, glycan_partner_id"
            )
        if (
            len({c.protein_residue_index for c in self.contacts})
            > self.protein_residue_count
            or len({c.glycan_partner_id for c in self.contacts})
            > self.glycan_partner_count
        ):
            raise ProteinGlycanContactComputationError(
                "observed protein and glycan identities must not exceed declared counts"
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
            "glycan_partner_count": self.glycan_partner_count,
            "evaluated_pair_count": self.evaluated_pair_count,
            "contact_count": self.contact_count,
            "excluded_contact_count": self.excluded_contact_count,
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
        raise ProteinGlycanContactComputationError(
            f"{name} must have at least one heavy atom"
        )
    return heavy


def compute_protein_glycan_contacts(
    frame: ProteinGlycanContactFrameInput,
) -> ProteinGlycanContactFrameResult:
    """Evaluate every supplied protein residue × catalog glycan, at fixed 4.5 Å.

    No PBC correction or unit conversion. Hydrogen status must be explicit.
    An invalid heavy-atom representation fails even when there are no glycans.
    """
    if type(frame) is not ProteinGlycanContactFrameInput:
        raise ProteinGlycanContactComputationError(
            "frame must be an exact ProteinGlycanContactFrameInput"
        )
    residues = {r.residue_index: r for r in frame.topology.residues}
    coordinates = {c.atom_index: c for c in frame.atom_coordinates}
    protein_heavy = {
        i: _heavy_coordinates(residues[i].atom_indexes, coordinates, "protein residue")
        for i in frame.protein_residue_indexes
    }
    glycans = sorted(
        (p for p in frame.partner_catalog.partners if p.partner_kind == "glycan"),
        key=lambda p: p.partner_id,
    )
    glycan_heavy = {
        p.partner_id: _heavy_coordinates(
            p.component_atom_indexes, coordinates, "glycan partner"
        )
        for p in glycans
    }
    linkage = {
        p.partner_id: _linkage_evidence(
            p, frame.topology, residues, frame.protein_residue_indexes
        )
        for p in glycans
    }
    contacts = []
    for index in frame.protein_residue_indexes:
        residue = residues[index]
        for glycan in glycans:
            # hypot computes sqrt(dx² + dy² + dz²) without intermediate squaring
            # overflow/underflow. Every heavy-heavy pair participates in the minimum.
            minimum = min(
                hypot(b.x_A - a.x_A, b.y_A - a.y_A, b.z_A - a.z_A)
                for a in protein_heavy[index]
                for b in glycan_heavy[glycan.partner_id]
            )
            _require_finite(minimum, "computed minimum_distance_A")
            if minimum <= PROTEIN_GLYCAN_CONTACT_CUTOFF_A:
                carrier, first, evidence, carrier_atom, sugar_atom = linkage[
                    glycan.partner_id
                ]
                excluded = index == carrier
                contacts.append(
                    ProteinGlycanContactObservation(
                        frame.frame_index,
                        frame.time_ps,
                        residue.residue_index,
                        residue.residue_id,
                        residue.resname,
                        residue.segid,
                        glycan.partner_id,
                        glycan.partner_name,
                        glycan.component_residue_indexes,
                        carrier,
                        first,
                        evidence,
                        carrier_atom,
                        sugar_atom,
                        excluded,
                        PROTEIN_GLYCAN_COVALENT_EXCLUSION_REASON if excluded else None,
                        minimum,
                    )
                )
    protein_count = len(frame.protein_residue_indexes)
    return ProteinGlycanContactFrameResult(
        frame.frame_index,
        frame.time_ps,
        protein_count,
        len(glycans),
        protein_count * len(glycans),
        len(contacts),
        sum(c.standard_summary_excluded for c in contacts),
        tuple(contacts),
    )


__all__ = [
    "PROTEIN_GLYCAN_CONTACT_CUTOFF_A",
    "PROTEIN_GLYCAN_CONTACT_KIND",
    "PROTEIN_GLYCAN_CONTACT_SCHEMA_VERSION",
    "PROTEIN_GLYCAN_COVALENT_EXCLUSION_REASON",
    "PROTEIN_GLYCAN_DISTANCE_DEFINITION",
    "PROTEIN_GLYCAN_DISTANCE_UNIT",
    "ProteinGlycanContactComputationError",
    "ProteinGlycanContactFrameInput",
    "ProteinGlycanContactFrameResult",
    "ProteinGlycanContactObservation",
    "compute_protein_glycan_contacts",
]
