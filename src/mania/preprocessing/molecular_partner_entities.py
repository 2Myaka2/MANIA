"""Pure source-topology contracts for Stage 29.A molecular partner identity.

Classification is supplied metadata. No names, coordinates, or biological
annotations are inferred. See docs/molecular_partner_identification_contract.md.
"""

from dataclasses import dataclass
from itertools import pairwise
from typing import Literal

MolecularPartnerKind = Literal["lipid", "glycan"]
MolecularPartnerIdentificationMode = Literal[
    "topology_connectivity", "explicit_mapping"
]
MolecularPartnerLinkageEvidence = Literal["topology_connectivity", "external_metadata"]
TopologyConnectivityStatus = Literal["available", "unavailable"]


def _require_index(value: object, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def _require_text(value: object, name: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be a non-empty stripped string")


def _require_indexes(value: tuple[int, ...], name: str) -> None:
    if not isinstance(value, tuple) or not value:
        raise ValueError(f"{name} must be a non-empty tuple")
    for index in value:
        _require_index(index, name)
    if any(b <= a for a, b in pairwise(value)):
        raise ValueError(f"{name} must be strictly increasing and unique")


def _require_records(value: object, record_type: type, name: str) -> None:
    if not isinstance(value, tuple) or any(
        type(item) is not record_type for item in value
    ):
        raise ValueError(
            f"{name} must be a tuple of exact {record_type.__name__} records"
        )


def _require_kind_name(kind: MolecularPartnerKind, name: str) -> None:
    if kind not in ("lipid", "glycan"):
        raise ValueError("partner_kind must be lipid or glycan")
    _require_text(name, "partner_name")


def _require_linkage_pair(
    kind: MolecularPartnerKind,
    indexes: tuple[int, ...],
    carrier: int | None,
    first_sugar: int | None,
) -> None:
    for name, value in (
        ("carrier_residue_index", carrier),
        ("first_sugar_residue_index", first_sugar),
    ):
        if value is not None:
            _require_index(value, name)
    if kind == "lipid" and (carrier is not None or first_sugar is not None):
        raise ValueError("lipid linkage fields must be None")
    if (carrier is None) != (first_sugar is None):
        raise ValueError(
            "carrier and first sugar must both be supplied or both be None"
        )
    if carrier is not None and carrier in indexes:
        raise ValueError("carrier must be outside component membership")
    if first_sugar is not None and first_sugar not in indexes:
        raise ValueError("first sugar must belong to component membership")


@dataclass(frozen=True)
class SourceTopologyResidue:
    """Source identity; residue_id and segid are not canonical/global identities."""

    residue_index: int
    residue_id: int | str | None
    resname: str
    segid: str | None
    atom_indexes: tuple[int, ...]

    def __post_init__(self) -> None:
        _require_index(self.residue_index, "residue_index")
        if isinstance(self.residue_id, bool) or (
            self.residue_id is not None and not isinstance(self.residue_id, (int, str))
        ):
            raise ValueError("residue_id must be an integer, string, or None")
        _require_text(self.resname, "resname")
        if self.segid is not None:
            _require_text(self.segid, "segid")
        _require_indexes(self.atom_indexes, "atom_indexes")

    def to_dict(self) -> dict[str, object]:
        return {
            "residue_index": self.residue_index,
            "residue_id": self.residue_id,
            "resname": self.resname,
            "segid": self.segid,
            "atom_indexes": list(self.atom_indexes),
        }


@dataclass(frozen=True)
class SourceTopologyBond:
    """One undirected bond, stored with its lower source atom index first."""

    atom_index_a: int
    atom_index_b: int

    def __post_init__(self) -> None:
        _require_index(self.atom_index_a, "atom_index_a")
        _require_index(self.atom_index_b, "atom_index_b")
        if self.atom_index_a == self.atom_index_b:
            raise ValueError("bond endpoints must differ")
        a, b = sorted((self.atom_index_a, self.atom_index_b))
        object.__setattr__(self, "atom_index_a", a)
        object.__setattr__(self, "atom_index_b", b)

    def to_dict(self) -> dict[str, object]:
        return {"atom_index_a": self.atom_index_a, "atom_index_b": self.atom_index_b}


@dataclass(frozen=True)
class MolecularPartnerTopology:
    """Caller explicitly declares whether the supplied bonds are authoritative."""

    residues: tuple[SourceTopologyResidue, ...]
    bonds: tuple[SourceTopologyBond, ...]
    connectivity_status: TopologyConnectivityStatus

    def __post_init__(self) -> None:
        _require_records(self.residues, SourceTopologyResidue, "residues")
        _require_records(self.bonds, SourceTopologyBond, "bonds")
        if self.connectivity_status not in ("available", "unavailable"):
            raise ValueError("connectivity_status must be available or unavailable")
        if self.connectivity_status == "unavailable" and self.bonds:
            raise ValueError("unavailable connectivity requires empty bonds")
        indexes = tuple(r.residue_index for r in self.residues)
        if indexes:
            _require_indexes(indexes, "residue indexes")
        atoms = tuple(a for r in self.residues for a in r.atom_indexes)
        if len(set(atoms)) != len(atoms):
            raise ValueError("atom membership must be unique across residues")
        atom_set = set(atoms)
        keys = tuple((b.atom_index_a, b.atom_index_b) for b in self.bonds)
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate topology bonds are forbidden")
        if any(b <= a for a, b in pairwise(keys)):
            raise ValueError("bonds must be ordered by canonical atom endpoints")
        if any(a not in atom_set or b not in atom_set for a, b in keys):
            raise ValueError("every bond endpoint must exist in a supplied residue")

    def to_dict(self) -> dict[str, object]:
        return {
            "residues": [r.to_dict() for r in self.residues],
            "bonds": [b.to_dict() for b in self.bonds],
            "connectivity_status": self.connectivity_status,
        }


@dataclass(frozen=True)
class MolecularPartnerComponentClassification:
    """Authoritative caller metadata classifies a component, not its grouping."""

    residue_index: int
    partner_kind: MolecularPartnerKind
    partner_name: str

    def __post_init__(self) -> None:
        _require_index(self.residue_index, "residue_index")
        _require_kind_name(self.partner_kind, self.partner_name)

    def to_dict(self) -> dict[str, object]:
        return {
            "residue_index": self.residue_index,
            "partner_kind": self.partner_kind,
            "partner_name": self.partner_name,
        }


@dataclass(frozen=True)
class ExplicitMolecularPartnerDefinition:
    """Exact grouping, optionally with caller-supplied glycan linkage evidence."""

    partner_id: str
    partner_kind: MolecularPartnerKind
    partner_name: str
    component_residue_indexes: tuple[int, ...]
    carrier_residue_index: int | None = None
    first_sugar_residue_index: int | None = None
    linkage_evidence: MolecularPartnerLinkageEvidence | None = None

    def __post_init__(self) -> None:
        _require_text(self.partner_id, "partner_id")
        _require_kind_name(self.partner_kind, self.partner_name)
        _require_indexes(self.component_residue_indexes, "component_residue_indexes")
        _require_linkage_pair(
            self.partner_kind,
            self.component_residue_indexes,
            self.carrier_residue_index,
            self.first_sugar_residue_index,
        )
        if self.linkage_evidence not in (
            None,
            "topology_connectivity",
            "external_metadata",
        ):
            raise ValueError("unsupported linkage_evidence")
        if self.linkage_evidence is not None and self.carrier_residue_index is None:
            raise ValueError("linkage_evidence requires carrier and first sugar")

    def to_dict(self) -> dict[str, object]:
        return {
            "partner_id": self.partner_id,
            "partner_kind": self.partner_kind,
            "partner_name": self.partner_name,
            "component_residue_indexes": list(self.component_residue_indexes),
            "carrier_residue_index": self.carrier_residue_index,
            "first_sugar_residue_index": self.first_sugar_residue_index,
            "linkage_evidence": self.linkage_evidence,
        }


@dataclass(frozen=True)
class IdentifiedMolecularPartner:
    """Successful source entity with complete, explicitly attributed evidence."""

    partner_id: str
    partner_kind: MolecularPartnerKind
    partner_name: str
    identification_mode: MolecularPartnerIdentificationMode
    component_residue_indexes: tuple[int, ...]
    component_atom_indexes: tuple[int, ...]
    components: tuple[SourceTopologyResidue, ...]
    carrier_residue_index: int | None
    first_sugar_residue_index: int | None
    carrier_link_bond: SourceTopologyBond | None
    linkage_evidence: MolecularPartnerLinkageEvidence | None = None

    def __post_init__(self) -> None:
        _require_text(self.partner_id, "partner_id")
        _require_kind_name(self.partner_kind, self.partner_name)
        if self.identification_mode not in (
            "topology_connectivity",
            "explicit_mapping",
        ):
            raise ValueError("unsupported identification_mode")
        _require_indexes(self.component_residue_indexes, "component_residue_indexes")
        _require_indexes(self.component_atom_indexes, "component_atom_indexes")
        _require_records(self.components, SourceTopologyResidue, "components")
        if self.component_residue_indexes != tuple(
            r.residue_index for r in self.components
        ):
            raise ValueError("component residue indexes must match components exactly")
        atoms = tuple(a for r in self.components for a in r.atom_indexes)
        if len(set(atoms)) != len(atoms):
            raise ValueError("component atom memberships must not overlap")
        if self.component_atom_indexes != tuple(sorted(atoms)):
            raise ValueError(
                "component atom indexes must equal exact component atom union"
            )
        _require_linkage_pair(
            self.partner_kind,
            self.component_residue_indexes,
            self.carrier_residue_index,
            self.first_sugar_residue_index,
        )
        if self.partner_kind == "lipid":
            if self.carrier_link_bond is not None or self.linkage_evidence is not None:
                raise ValueError("lipid linkage fields must be None")
            return
        if self.carrier_residue_index is None:
            raise ValueError("identified glycan requires carrier and first sugar")
        if self.linkage_evidence == "external_metadata":
            if (
                self.identification_mode != "explicit_mapping"
                or self.carrier_link_bond is not None
            ):
                raise ValueError(
                    "external linkage requires explicit mapping without a bond"
                )
            return
        if (
            self.linkage_evidence != "topology_connectivity"
            or type(self.carrier_link_bond) is not SourceTopologyBond
        ):
            raise ValueError(
                "identified glycan requires topology bond or explicit external evidence"
            )
        first = next(
            r
            for r in self.components
            if r.residue_index == self.first_sugar_residue_index
        )
        a, b = self.carrier_link_bond.atom_index_a, self.carrier_link_bond.atom_index_b
        if not (
            (a in first.atom_indexes and b not in self.component_atom_indexes)
            or (b in first.atom_indexes and a not in self.component_atom_indexes)
        ):
            raise ValueError(
                "carrier link bond must cross first sugar to outside components"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "partner_id": self.partner_id,
            "partner_kind": self.partner_kind,
            "partner_name": self.partner_name,
            "identification_mode": self.identification_mode,
            "component_residue_indexes": list(self.component_residue_indexes),
            "component_atom_indexes": list(self.component_atom_indexes),
            "components": [r.to_dict() for r in self.components],
            "carrier_residue_index": self.carrier_residue_index,
            "first_sugar_residue_index": self.first_sugar_residue_index,
            "carrier_link_bond": self.carrier_link_bond.to_dict()
            if self.carrier_link_bond
            else None,
            "linkage_evidence": self.linkage_evidence,
        }


@dataclass(frozen=True)
class MolecularPartnerCatalog:
    """Disjoint successful entities, ordered lipid then glycan, then partner_id."""

    partners: tuple[IdentifiedMolecularPartner, ...]

    def __post_init__(self) -> None:
        _require_records(self.partners, IdentifiedMolecularPartner, "partners")
        ids = tuple(p.partner_id for p in self.partners)
        if len(set(ids)) != len(ids):
            raise ValueError("partner IDs must be unique")
        keys = tuple((p.partner_kind == "glycan", p.partner_id) for p in self.partners)
        if any(b <= a for a, b in pairwise(keys)):
            raise ValueError(
                "partners must be ordered lipid then glycan, then partner_id"
            )
        for name in ("component_residue_indexes", "component_atom_indexes"):
            indexes = tuple(i for p in self.partners for i in getattr(p, name))
            if len(set(indexes)) != len(indexes):
                raise ValueError(f"partners must not overlap in {name}")

    @property
    def partner_count(self) -> int:
        return len(self.partners)

    @property
    def lipid_partner_count(self) -> int:
        return sum(p.partner_kind == "lipid" for p in self.partners)

    @property
    def glycan_partner_count(self) -> int:
        return sum(p.partner_kind == "glycan" for p in self.partners)

    def to_dict(self) -> dict[str, object]:
        return {
            "partners": [p.to_dict() for p in self.partners],
            "partner_count": self.partner_count,
            "lipid_partner_count": self.lipid_partner_count,
            "glycan_partner_count": self.glycan_partner_count,
        }


__all__ = [
    "ExplicitMolecularPartnerDefinition",
    "IdentifiedMolecularPartner",
    "MolecularPartnerCatalog",
    "MolecularPartnerComponentClassification",
    "MolecularPartnerIdentificationMode",
    "MolecularPartnerKind",
    "MolecularPartnerLinkageEvidence",
    "MolecularPartnerTopology",
    "SourceTopologyBond",
    "SourceTopologyResidue",
    "TopologyConnectivityStatus",
]
