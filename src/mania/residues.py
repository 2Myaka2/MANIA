"""Residue registry placeholders for MANIA.

Final lipid, glycan, and glycolipid residue names are provided later by the
domain expert. The current registries are intentionally empty.
"""

LIPID_RESIDUES: frozenset[str] = frozenset()
GLYCAN_RESIDUES: frozenset[str] = frozenset()
GLYCOLIPID_RESIDUES: frozenset[str] = frozenset()

ALL_LIPIDS: frozenset[str] = LIPID_RESIDUES | GLYCOLIPID_RESIDUES
ALL_GLYCANS: frozenset[str] = GLYCAN_RESIDUES | GLYCOLIPID_RESIDUES
ALL_GLYCOLIPIDS: frozenset[str] = GLYCOLIPID_RESIDUES

EDGE_TYPE_PROTEIN_GLYCOLIPID = "protein_glycolipid"

__all__ = [
    "ALL_GLYCANS",
    "ALL_GLYCOLIPIDS",
    "ALL_LIPIDS",
    "EDGE_TYPE_PROTEIN_GLYCOLIPID",
    "GLYCAN_RESIDUES",
    "GLYCOLIPID_RESIDUES",
    "LIPID_RESIDUES",
    "classify_nonprotein_residue",
    "is_glycan_residue",
    "is_glycolipid_residue",
    "is_lipid_residue",
    "normalize_resname",
]


def normalize_resname(resname: str) -> str:
    """Normalize a residue name for registry lookups."""
    return resname.strip().upper()


def is_lipid_residue(resname: str) -> bool:
    """Return whether a residue is registered as a lipid."""
    return normalize_resname(resname) in LIPID_RESIDUES


def is_glycan_residue(resname: str) -> bool:
    """Return whether a residue is registered as a glycan."""
    return normalize_resname(resname) in GLYCAN_RESIDUES


def is_glycolipid_residue(resname: str) -> bool:
    """Return whether a residue is registered as a glycolipid."""
    return normalize_resname(resname) in GLYCOLIPID_RESIDUES


def classify_nonprotein_residue(resname: str) -> str | None:
    """Classify a non-protein residue without duplicate RIN classification."""
    if is_glycolipid_residue(resname):
        return "glycolipid"
    if is_lipid_residue(resname):
        return "lipid"
    if is_glycan_residue(resname):
        return "glycan"
    return None
