"""Read an explicit mapping and bind it to its supplied reference."""

from pathlib import Path

from mania.canonical_reference import ProteinReference
from mania.canonical_reference_io import _read_model
from mania.canonical_residue_mapping import ResidueMappingTable


def read_residue_mapping(
    path: str | Path,
    *,
    reference: ProteinReference,
) -> ResidueMappingTable:
    table = _read_model(path, ResidueMappingTable)
    table.validate_reference(reference)
    return table


def __getattr__(name: str) -> object:
    if name in (
        "CANONICAL_RESIDUE_MAPPING_FILENAME",
        "CanonicalResidueMappingReadError",
        "CanonicalResidueMappingValidationIssue",
        "CanonicalResidueMappingValidationReport",
        "CanonicalResidueMappingWriteResult",
        "_CONTRACT",
        "_ROOT_FIELDS",
        "_ROW_FIELDS",
        "read_canonical_residue_mapping",
        "validate_canonical_residue_mapping",
        "write_canonical_residue_mapping",
    ):
        raise ImportError(
            "Fixed NaPi2b API moved to mania_napi2b.canonical_residue_mapping_io; "
            "install mania-napi2b and explicitly select a profile."
        )
    raise AttributeError(name)
