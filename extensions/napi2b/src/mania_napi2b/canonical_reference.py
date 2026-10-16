"""Frozen Stage 30.A NaPi2b target coordinates, independent of source topology.

This deliberately narrow contract pins O95436-1 sequence version 3. It does not
establish any association between source residue IDs and canonical positions.
"""

import hashlib
import re
from dataclasses import dataclass, field, fields
from datetime import date
from types import MappingProxyType

NAPI2B_CANONICAL_REFERENCE_SCHEMA_VERSION = "mania.canonical_reference.v0.1"
NAPI2B_CANONICAL_REFERENCE_KIND = "mania_canonical_protein_reference"
NAPI2B_UNIPROT_ACCESSION = "O95436"
NAPI2B_CANONICAL_ISOFORM_ID = "O95436-1"
NAPI2B_UNIPROT_ENTRY_NAME = "NPT2B_HUMAN"
NAPI2B_GENE_SYMBOL = "SLC34A2"
NAPI2B_CANONICAL_SEQUENCE_LENGTH = 690
NAPI2B_UNIPROT_SEQUENCE_VERSION = 3
NAPI2B_UNIPROT_SEQUENCE_MD5 = "16C21D07D36DC8B416EA72769F0B0280"
NAPI2B_CANONICAL_SEQUENCE_SHA256 = (
    "33ce6c59e28a7373fce51debe32cec8d891ef691c2e77a0655a74040da25eef9"
)

_RESNAMES = MappingProxyType(
    {
        "A": "ALA",
        "R": "ARG",
        "N": "ASN",
        "D": "ASP",
        "C": "CYS",
        "Q": "GLN",
        "E": "GLU",
        "G": "GLY",
        "H": "HIS",
        "I": "ILE",
        "L": "LEU",
        "K": "LYS",
        "M": "MET",
        "F": "PHE",
        "P": "PRO",
        "S": "SER",
        "T": "THR",
        "W": "TRP",
        "Y": "TYR",
        "V": "VAL",
    }
)

_PINNED_FIELDS = MappingProxyType(
    {
        "uniprot_accession": NAPI2B_UNIPROT_ACCESSION,
        "canonical_isoform_id": NAPI2B_CANONICAL_ISOFORM_ID,
        "uniprot_entry_name": NAPI2B_UNIPROT_ENTRY_NAME,
        "gene_symbol": NAPI2B_GENE_SYMBOL,
        "protein_name": "Sodium-dependent phosphate transport protein 2B",
        "organism_name": "Homo sapiens",
        "source_system": "UniProtKB/Swiss-Prot",
        "uniprot_sequence_version": NAPI2B_UNIPROT_SEQUENCE_VERSION,
        "uniprot_sequence_last_updated": "2010-11-30",
        "uniprot_sequence_md5": NAPI2B_UNIPROT_SEQUENCE_MD5,
        "sequence_sha256": NAPI2B_CANONICAL_SEQUENCE_SHA256,
        "sequence_length": NAPI2B_CANONICAL_SEQUENCE_LENGTH,
    }
)


def _require_position(value: object) -> None:
    if type(value) is not int or not 1 <= value <= NAPI2B_CANONICAL_SEQUENCE_LENGTH:
        raise ValueError("canonical_residue_number must be an integer in 1..690")


@dataclass(frozen=True)
class CanonicalResidueReference:
    """A canonical position and standard residue spelling, without annotations."""

    canonical_residue_number: int
    one_letter_code: str
    canonical_resname: str

    def __post_init__(self) -> None:
        _require_position(self.canonical_residue_number)
        if (
            type(self.one_letter_code) is not str
            or self.one_letter_code not in _RESNAMES
        ):
            raise ValueError(
                "one_letter_code must be one standard uppercase amino acid"
            )
        if (
            type(self.canonical_resname) is not str
            or self.canonical_resname != _RESNAMES[self.one_letter_code]
        ):
            raise ValueError(
                "canonical_resname must match the standard three-letter code"
            )

    def to_dict(self) -> dict[str, object]:
        """Return independent JSON scalars in declaration order."""
        return {item.name: getattr(self, item.name) for item in fields(self)}


@dataclass(frozen=True)
class CanonicalProteinReference:
    """Pinned NaPi2b reference; alternate proteins/isoforms are outside 30.A.

    Text must already be stripped and non-empty. Sequence bytes are never changed.
    The source URL is provenance text only, with no executable or lookup behavior.
    """

    uniprot_accession: str
    canonical_isoform_id: str
    uniprot_entry_name: str
    gene_symbol: str
    protein_name: str
    organism_name: str
    source_system: str
    source_record_url: str
    uniprot_sequence_version: int
    uniprot_sequence_last_updated: str
    uniprot_sequence_md5: str
    sequence_sha256: str
    sequence_length: int
    sequence: str
    schema_version: str = field(
        init=False, default=NAPI2B_CANONICAL_REFERENCE_SCHEMA_VERSION
    )
    kind: str = field(init=False, default=NAPI2B_CANONICAL_REFERENCE_KIND)

    def __post_init__(self) -> None:
        for item in fields(self):
            value = getattr(self, item.name)
            if item.name in ("uniprot_sequence_version", "sequence_length"):
                if type(value) is not int or value <= 0:
                    raise ValueError(f"{item.name} must be a positive integer")
            elif type(value) is not str or not value or value != value.strip():
                raise ValueError(f"{item.name} must be a non-empty stripped string")
        if not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}", self.uniprot_sequence_last_updated
        ):
            raise ValueError("uniprot_sequence_last_updated must be an ISO date")
        date.fromisoformat(self.uniprot_sequence_last_updated)
        if not re.fullmatch(r"[0-9A-Fa-f]{32}", self.uniprot_sequence_md5):
            raise ValueError(
                "uniprot_sequence_md5 must contain 32 hexadecimal characters"
            )
        if not re.fullmatch(r"[0-9a-f]{64}", self.sequence_sha256):
            raise ValueError("sequence_sha256 must contain 64 lowercase hex characters")
        if any(letter not in _RESNAMES for letter in self.sequence):
            raise ValueError(
                "sequence must contain only standard uppercase amino acids"
            )
        if self.sequence_length != len(self.sequence):
            raise ValueError("sequence_length must equal the sequence length")
        sequence_bytes = self.sequence.encode("ascii")
        # MD5 is an upstream sequence fingerprint, not a security primitive.
        if (
            hashlib.md5(sequence_bytes, usedforsecurity=False).hexdigest().upper()
            != self.uniprot_sequence_md5.upper()
        ):
            raise ValueError("sequence MD5 does not match uniprot_sequence_md5")
        if hashlib.sha256(sequence_bytes).hexdigest() != self.sequence_sha256:
            raise ValueError("sequence SHA256 does not match sequence_sha256")
        for name, expected in _PINNED_FIELDS.items():
            if getattr(self, name) != expected:
                raise ValueError(f"{name} must match the pinned NaPi2b reference")

    @property
    def reference_id(self) -> str:
        """Return a stable sequence identity without environmental metadata."""
        return (
            f"uniprotkb:{self.canonical_isoform_id}:"
            f"sequence-v{self.uniprot_sequence_version}"
        )

    def residue_at(self, canonical_residue_number: int) -> CanonicalResidueReference:
        """Look up a 1-based target position in the locally pinned sequence."""
        _require_position(canonical_residue_number)
        letter = self.sequence[canonical_residue_number - 1]
        return CanonicalResidueReference(
            canonical_residue_number, letter, _RESNAMES[letter]
        )

    def residues(self) -> tuple[CanonicalResidueReference, ...]:
        """Return all 690 canonical residues in ascending position order."""
        return tuple(self.residue_at(number) for number in range(1, 691))

    def to_dict(self) -> dict[str, object]:
        """Return independent JSON scalars in declaration order."""
        return {item.name: getattr(self, item.name) for item in fields(self)}


__all__ = [
    "CanonicalProteinReference",
    "CanonicalResidueReference",
    "NAPI2B_CANONICAL_ISOFORM_ID",
    "NAPI2B_CANONICAL_REFERENCE_KIND",
    "NAPI2B_CANONICAL_REFERENCE_SCHEMA_VERSION",
    "NAPI2B_CANONICAL_SEQUENCE_LENGTH",
    "NAPI2B_CANONICAL_SEQUENCE_SHA256",
    "NAPI2B_GENE_SYMBOL",
    "NAPI2B_UNIPROT_ACCESSION",
    "NAPI2B_UNIPROT_ENTRY_NAME",
    "NAPI2B_UNIPROT_SEQUENCE_MD5",
    "NAPI2B_UNIPROT_SEQUENCE_VERSION",
]
