"""Pure Stage 29.A grouping of explicitly classified molecular components."""

from itertools import pairwise

from mania.preprocessing.molecular_partner_entities import (
    ExplicitMolecularPartnerDefinition,
    IdentifiedMolecularPartner,
    MolecularPartnerCatalog,
    MolecularPartnerComponentClassification,
    MolecularPartnerIdentificationMode,
    MolecularPartnerKind,
    MolecularPartnerLinkageEvidence,
    MolecularPartnerTopology,
    SourceTopologyBond,
    SourceTopologyResidue,
)


class MolecularPartnerIdentificationError(ValueError):
    """Invalid metadata, inconsistent membership, or insufficient linkage evidence."""


def _validate_inputs(
    topology: MolecularPartnerTopology,
    protein_residue_indexes: tuple[int, ...],
    classifications: tuple[MolecularPartnerComponentClassification, ...],
    explicit_partners: tuple[ExplicitMolecularPartnerDefinition, ...],
) -> dict[int, MolecularPartnerComponentClassification]:
    if type(topology) is not MolecularPartnerTopology:
        raise MolecularPartnerIdentificationError(
            "topology must be a MolecularPartnerTopology"
        )
    if not isinstance(protein_residue_indexes, tuple):
        raise MolecularPartnerIdentificationError(
            "protein_residue_indexes must be a tuple"
        )
    if any(
        isinstance(i, bool) or not isinstance(i, int) or i < 0
        for i in protein_residue_indexes
    ):
        raise MolecularPartnerIdentificationError(
            "protein residue indexes must be non-negative integers"
        )
    if any(b <= a for a, b in pairwise(protein_residue_indexes)):
        raise MolecularPartnerIdentificationError(
            "protein residue indexes must be strictly increasing and unique"
        )
    residues = {r.residue_index for r in topology.residues}
    if not set(protein_residue_indexes) <= residues:
        raise MolecularPartnerIdentificationError(
            "every protein residue must exist in topology"
        )
    for records, cls, name in (
        (classifications, MolecularPartnerComponentClassification, "classifications"),
        (explicit_partners, ExplicitMolecularPartnerDefinition, "explicit_partners"),
    ):
        if not isinstance(records, tuple) or any(type(r) is not cls for r in records):
            raise MolecularPartnerIdentificationError(
                f"{name} must be a tuple of exact {cls.__name__} records"
            )
    by_residue: dict[int, MolecularPartnerComponentClassification] = {}
    protein = set(protein_residue_indexes)
    for classification in classifications:
        index = classification.residue_index
        if index not in residues:
            raise MolecularPartnerIdentificationError(
                "every classification residue must exist in topology"
            )
        if index in by_residue:
            raise MolecularPartnerIdentificationError(
                "each residue may have only one classification"
            )
        if index in protein:
            raise MolecularPartnerIdentificationError(
                "protein residues cannot be classified as lipid or glycan"
            )
        by_residue[index] = classification
    covered: set[int] = set()
    ids: set[str] = set()
    for definition in explicit_partners:
        if definition.partner_id in ids:
            raise MolecularPartnerIdentificationError(
                "explicit partner IDs must be unique"
            )
        ids.add(definition.partner_id)
        for index in definition.component_residue_indexes:
            if index not in residues:
                raise MolecularPartnerIdentificationError(
                    "every explicit component must exist in topology"
                )
            if index in covered:
                raise MolecularPartnerIdentificationError(
                    "explicit partner component memberships must not overlap"
                )
            component_classification = by_residue.get(index)
            if component_classification is None or (
                component_classification.partner_kind,
                component_classification.partner_name,
            ) != (definition.partner_kind, definition.partner_name):
                raise MolecularPartnerIdentificationError(
                    "every explicit component must have matching "
                    "kind/name classification"
                )
            covered.add(index)
    return by_residue


def _connected_groups(
    remaining: set[int],
    classifications: dict[int, MolecularPartnerComponentClassification],
    links: dict[int, list[tuple[int, SourceTopologyBond]]],
) -> list[tuple[int, ...]]:
    """Only same-kind classified residues participate; conflicting names fail."""
    groups = []
    unseen = remaining.copy()
    for seed in sorted(remaining):
        if seed not in unseen:
            continue
        unseen.remove(seed)
        group = {seed}
        pending = [seed]
        kind = classifications[seed].partner_kind
        while pending:
            for neighbor, _ in links[pending.pop()]:
                if (
                    neighbor in unseen
                    and classifications[neighbor].partner_kind == kind
                ):
                    unseen.remove(neighbor)
                    group.add(neighbor)
                    pending.append(neighbor)
        if len({classifications[i].partner_name for i in group}) != 1:
            raise MolecularPartnerIdentificationError(
                "connected components have conflicting partner names; "
                "explicit grouping required"
            )
        groups.append(tuple(sorted(group)))
    return groups


def _glycan_linkage(
    component_indexes: tuple[int, ...],
    protein: set[int],
    links: dict[int, list[tuple[int, SourceTopologyBond]]],
    connectivity_available: bool,
    definition: ExplicitMolecularPartnerDefinition | None,
) -> tuple[int, int, SourceTopologyBond | None, MolecularPartnerLinkageEvidence]:
    if definition is not None:
        carrier = definition.carrier_residue_index
        first = definition.first_sugar_residue_index
        if carrier is None or first is None:
            raise MolecularPartnerIdentificationError(
                "explicit glycan requires carrier and first sugar"
            )
        if carrier not in protein:
            raise MolecularPartnerIdentificationError(
                "glycan carrier must be an authoritative protein residue"
            )
        if not connectivity_available:
            if definition.linkage_evidence != "external_metadata":
                raise MolecularPartnerIdentificationError(
                    "unavailable connectivity requires explicit "
                    "external_metadata linkage evidence"
                )
            return carrier, first, None, "external_metadata"
        matching = [bond for neighbor, bond in links[first] if neighbor == carrier]
        if not matching:
            raise MolecularPartnerIdentificationError(
                "explicit carrier and first sugar must have a topology bond"
            )
        # The caller resolves the residue pair; preserve its lowest canonical
        # atom pair if several bonds support that same explicit linkage.
        bond = min(matching, key=lambda b: (b.atom_index_a, b.atom_index_b))
        return carrier, first, bond, "topology_connectivity"
    if not connectivity_available:
        raise MolecularPartnerIdentificationError(
            "glycan connectivity unavailable; explicit grouping "
            "and linkage evidence required"
        )
    candidates = [
        (neighbor, index, bond)
        for index in component_indexes
        for neighbor, bond in links[index]
        if neighbor in protein
    ]
    if len(candidates) != 1:
        raise MolecularPartnerIdentificationError(
            "automatic glycan requires exactly one unambiguous protein carrier bond; "
            "explicit mapping required"
        )
    carrier, first, bond = candidates[0]
    return carrier, first, bond, "topology_connectivity"


def _identify_group(
    partner_id: str,
    kind: MolecularPartnerKind,
    name: str,
    mode: MolecularPartnerIdentificationMode,
    indexes: tuple[int, ...],
    residues: dict[int, SourceTopologyResidue],
    protein: set[int],
    links: dict[int, list[tuple[int, SourceTopologyBond]]],
    connectivity_available: bool,
    definition: ExplicitMolecularPartnerDefinition | None = None,
) -> IdentifiedMolecularPartner:
    components = tuple(residues[i] for i in indexes)
    carrier: int | None = None
    first: int | None = None
    bond: SourceTopologyBond | None = None
    evidence: MolecularPartnerLinkageEvidence | None = None
    if kind == "glycan":
        carrier, first, bond, evidence = _glycan_linkage(
            indexes, protein, links, connectivity_available, definition
        )
    return IdentifiedMolecularPartner(
        partner_id,
        kind,
        name,
        mode,
        indexes,
        tuple(sorted(a for r in components for a in r.atom_indexes)),
        components,
        carrier,
        first,
        bond,
        evidence,
    )


def identify_molecular_partners(
    topology: MolecularPartnerTopology,
    *,
    protein_residue_indexes: tuple[int, ...],
    classifications: tuple[MolecularPartnerComponentClassification, ...],
    explicit_partners: tuple[ExplicitMolecularPartnerDefinition, ...] = (),
) -> MolecularPartnerCatalog:
    """Identify partners from supplied classification and grouping/linkage evidence.

    Protein indexes are authoritative carrier evidence, never inferred from names.
    Explicit definitions cover only their exact components. Remaining components
    use available topology connectivity (a lipid residue may stand alone).
    Generated IDs are topology-local, never canonical cross-system identities.
    """
    by_residue = _validate_inputs(
        topology, protein_residue_indexes, classifications, explicit_partners
    )
    residues = {r.residue_index: r for r in topology.residues}
    atom_owner = {a: r.residue_index for r in topology.residues for a in r.atom_indexes}
    links: dict[int, list[tuple[int, SourceTopologyBond]]] = {i: [] for i in residues}
    for bond in topology.bonds:
        a, b = atom_owner[bond.atom_index_a], atom_owner[bond.atom_index_b]
        if a != b:
            links[a].append((b, bond))
            links[b].append((a, bond))
    protein = set(protein_residue_indexes)
    available = topology.connectivity_status == "available"
    partners = []
    covered: set[int] = set()
    for definition in sorted(explicit_partners, key=lambda p: p.partner_id):
        partners.append(
            _identify_group(
                definition.partner_id,
                definition.partner_kind,
                definition.partner_name,
                "explicit_mapping",
                definition.component_residue_indexes,
                residues,
                protein,
                links,
                available,
                definition,
            )
        )
        covered.update(definition.component_residue_indexes)
    groups = _connected_groups(set(by_residue) - covered, by_residue, links)
    groups.sort(
        key=lambda indexes: (
            min(a for i in indexes for a in residues[i].atom_indexes),
            min(indexes),
        )
    )
    counters: dict[MolecularPartnerKind, int] = {"lipid": 0, "glycan": 0}
    ids = {p.partner_id for p in partners}
    for indexes in groups:
        classification = by_residue[indexes[0]]
        kind = classification.partner_kind
        counters[kind] += 1
        partner_id = f"{kind}_{counters[kind]:04d}"
        if partner_id in ids:
            raise MolecularPartnerIdentificationError(
                "generated partner ID conflicts with explicit partner ID"
            )
        ids.add(partner_id)
        partners.append(
            _identify_group(
                partner_id,
                kind,
                classification.partner_name,
                "topology_connectivity",
                indexes,
                residues,
                protein,
                links,
                available,
            )
        )
    return MolecularPartnerCatalog(
        tuple(
            sorted(partners, key=lambda p: (p.partner_kind == "glycan", p.partner_id))
        )
    )


__all__ = ["MolecularPartnerIdentificationError", "identify_molecular_partners"]
