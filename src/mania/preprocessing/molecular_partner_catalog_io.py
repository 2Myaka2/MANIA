"""Persist topology-local partner evidence per authoritative Dataset binding."""

import json
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mania.dataset_identity import DatasetTrajectorySpec
from mania.preprocessing.molecular_partner_entities import (
    IdentifiedMolecularPartner,
    MolecularPartnerCatalog,
    SourceTopologyBond,
    SourceTopologyResidue,
    TopologyConnectivityStatus,
    _require_records,
    _require_text,
)
from mania.preprocessing.molecular_partner_metadata_io import (
    SpecializedArtifactValidationReport,
    SpecializedArtifactWriteResult,
    exact_fields,
    json_array,
    read_strict_json,
    reconstruct_record,
    write_atomic_text,
)
from mania.preprocessing.physical_time_execution_io import _spec

if TYPE_CHECKING:
    from mania.preprocessing.physical_time_execution import (
        PreprocessingTemporalExecution,
    )
    from mania.preprocessing.specialized_contact_window_tables import (
        ProteinGlycanWindowTable,
        ProteinLipidWindowTable,
    )

PREPROCESSING_MOLECULAR_PARTNER_CATALOG_FILENAME = "molecular_partner_catalog.json"
PREPROCESSING_MOLECULAR_PARTNER_CATALOG_SCHEMA_VERSION = (
    "mania.preprocessing_molecular_partner_catalog.v0.1"
)
PREPROCESSING_MOLECULAR_PARTNER_CATALOG_KIND = (
    "mania_preprocessing_molecular_partner_catalog"
)


@dataclass(frozen=True)
class MolecularPartnerCatalogBinding:
    execution_condition: str
    dataset_spec: DatasetTrajectorySpec
    topology_connectivity_status: TopologyConnectivityStatus
    partner_catalog: MolecularPartnerCatalog

    def __post_init__(self) -> None:
        _require_text(self.execution_condition, "execution_condition")
        if type(self.dataset_spec) is not DatasetTrajectorySpec:
            raise ValueError("dataset_spec must be exact DatasetTrajectorySpec")
        if self.dataset_spec.identity.condition not in (None, self.execution_condition):
            raise ValueError("Dataset condition must match execution condition")
        if self.topology_connectivity_status not in ("available", "unavailable"):
            raise ValueError("Invalid topology connectivity status")
        if type(self.partner_catalog) is not MolecularPartnerCatalog:
            raise ValueError("partner_catalog must be exact MolecularPartnerCatalog")
        for partner in self.partner_catalog.partners:
            if self.topology_connectivity_status == "unavailable":
                if partner.identification_mode != "explicit_mapping":
                    raise ValueError(
                        "Unavailable connectivity requires explicit grouping"
                    )
                if (
                    partner.partner_kind == "glycan"
                    and partner.linkage_evidence != "external_metadata"
                ):
                    raise ValueError(
                        "Unavailable connectivity requires external linkage"
                    )
            elif partner.linkage_evidence == "external_metadata":
                raise ValueError("External linkage requires unavailable connectivity")

    def to_dict(self) -> dict[str, object]:
        return {
            "execution_condition": self.execution_condition,
            "dataset_spec": self.dataset_spec.to_dict(),
            "topology_connectivity_status": self.topology_connectivity_status,
            "partner_catalog": self.partner_catalog.to_dict(),
        }


@dataclass(frozen=True)
class PreprocessingMolecularPartnerCatalog:
    bindings: tuple[MolecularPartnerCatalogBinding, ...]
    schema_version: str = field(
        init=False, default=PREPROCESSING_MOLECULAR_PARTNER_CATALOG_SCHEMA_VERSION
    )
    kind: str = field(init=False, default=PREPROCESSING_MOLECULAR_PARTNER_CATALOG_KIND)

    def __post_init__(self) -> None:
        _require_records(self.bindings, MolecularPartnerCatalogBinding, "bindings")
        if not self.bindings:
            raise ValueError("Catalog requires at least one metadata-bearing binding")
        for keys in (
            [b.execution_condition for b in self.bindings],
            [b.dataset_spec.identity.replica_key for b in self.bindings],
        ):
            if len(set(keys)) != len(keys):
                raise ValueError("Catalog binding identities must be unique")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "bindings": [b.to_dict() for b in self.bindings],
        }


class MolecularPartnerCatalogReadError(ValueError):
    """Invalid or unreadable persisted catalog evidence."""


def _partner(value: Any) -> IdentifiedMolecularPartner:
    values = exact_fields(value, {f.name for f in fields(IdentifiedMolecularPartner)})
    for name in ("component_residue_indexes", "component_atom_indexes"):
        values[name] = tuple(json_array(values[name]))
    values["components"] = tuple(
        reconstruct_record(r, SourceTopologyResidue)
        for r in json_array(values["components"])
    )
    if values["carrier_link_bond"] is not None:
        values["carrier_link_bond"] = reconstruct_record(
            values["carrier_link_bond"], SourceTopologyBond
        )
    return IdentifiedMolecularPartner(**values)


def read_molecular_partner_catalog(
    path: str | Path,
) -> PreprocessingMolecularPartnerCatalog:
    try:
        data = exact_fields(
            read_strict_json(path),
            {f.name for f in fields(PreprocessingMolecularPartnerCatalog)},
        )
        bindings = []
        for raw in json_array(data["bindings"]):
            values = exact_fields(
                raw, {f.name for f in fields(MolecularPartnerCatalogBinding)}
            )
            values["dataset_spec"] = _spec(values["dataset_spec"])
            catalog = exact_fields(
                values["partner_catalog"],
                {
                    "partners",
                    "partner_count",
                    "lipid_partner_count",
                    "glycan_partner_count",
                },
            )
            parsed = MolecularPartnerCatalog(
                tuple(_partner(p) for p in json_array(catalog["partners"]))
            )
            for name in (
                "partner_count",
                "lipid_partner_count",
                "glycan_partner_count",
            ):
                if type(catalog[name]) is not int or catalog[name] != getattr(
                    parsed, name
                ):
                    raise ValueError("Invalid catalog counts")
            values["partner_catalog"] = parsed
            bindings.append(MolecularPartnerCatalogBinding(**values))
        result = PreprocessingMolecularPartnerCatalog(tuple(bindings))
        if result.to_dict() != data:
            raise ValueError("Invalid catalog serialization")
        return result
    except (OSError, TypeError, ValueError, OverflowError, RecursionError):
        raise MolecularPartnerCatalogReadError(
            "Invalid or unreadable molecular partner catalog."
        ) from None


def write_molecular_partner_catalog(
    catalog: PreprocessingMolecularPartnerCatalog,
    output_dir: str | Path,
    *,
    overwrite: bool = False,
) -> SpecializedArtifactWriteResult:
    if type(catalog) is not PreprocessingMolecularPartnerCatalog:
        raise ValueError("catalog must be exact PreprocessingMolecularPartnerCatalog")
    payload = (
        json.dumps(catalog.to_dict(), indent=2, ensure_ascii=False, allow_nan=False)
        + "\n"
    )
    return write_atomic_text(
        payload,
        Path(output_dir) / PREPROCESSING_MOLECULAR_PARTNER_CATALOG_FILENAME,
        overwrite=overwrite,
    )


def validate_molecular_partner_catalog(
    path: str | Path,
) -> SpecializedArtifactValidationReport:
    try:
        read_molecular_partner_catalog(path)
    except MolecularPartnerCatalogReadError as exc:
        return SpecializedArtifactValidationReport(Path(path), str(exc))
    return SpecializedArtifactValidationReport(Path(path))


def cross_check_specialized_source_tables(
    catalog: PreprocessingMolecularPartnerCatalog,
    temporal: "PreprocessingTemporalExecution",
    lipid_table: "ProteinLipidWindowTable",
    glycan_table: "ProteinGlycanWindowTable",
    metadata_conditions: tuple[str, ...],
) -> None:
    """Check retained identity and temporal/partner evidence, without MD file I/O."""
    from mania.preprocessing.specialized_contact_window_tables import (
        ProteinGlycanWindowRow,
        dataset_window_values,
    )

    expected = tuple(
        b for b in temporal.bindings if b.execution_condition in metadata_conditions
    )
    if len(expected) != len(metadata_conditions) or tuple(
        (b.execution_condition, b.dataset_spec) for b in catalog.bindings
    ) != tuple((b.execution_condition, b.dataset_spec) for b in expected):
        raise ValueError(
            "Catalog must match exactly the metadata-bearing Dataset bindings"
        )
    bindings = {b.dataset_spec.identity.replica_key: b for b in expected}
    partners = {
        b.dataset_spec.identity.replica_key: {
            p.partner_id: p for p in b.partner_catalog.partners
        }
        for b in catalog.bindings
    }
    for table, kind in ((lipid_table, "lipid"), (glycan_table, "glycan")):
        for row in table.rows:
            binding = bindings.get(row.replica_key)
            if binding is None:
                raise ValueError("Unknown specialized Dataset replica")
            window = next(
                (
                    w
                    for w in binding.window_plan.windows
                    if w.window_id == row.window_id
                ),
                None,
            )
            if window is None or any(
                getattr(row, name) != value
                for name, value in dataset_window_values(binding, window).items()
            ):
                raise ValueError("Specialized Dataset/window evidence mismatch")
            partner = partners[row.replica_key].get(row.partner_id)
            if partner is None or partner.partner_kind != kind:
                raise ValueError("Unknown specialized partner ID or kind")
            for name in ("partner_name", "component_residue_indexes"):
                if getattr(row, f"{kind}_{name}") != getattr(partner, name):
                    raise ValueError("Specialized partner membership mismatch")
            if any(
                row.protein_residue_index in p.component_residue_indexes
                for p in partners[row.replica_key].values()
            ):
                raise ValueError("Protein must not overlap molecular partners")
            if isinstance(row, ProteinGlycanWindowRow):
                for name in (
                    "carrier_residue_index",
                    "first_sugar_residue_index",
                    "linkage_evidence",
                ):
                    if getattr(row, name) != getattr(partner, name):
                        raise ValueError("Glycan linkage evidence mismatch")
                carrier_atom = sugar_atom = None
                if partner.carrier_link_bond is not None:
                    a, b = (
                        partner.carrier_link_bond.atom_index_a,
                        partner.carrier_link_bond.atom_index_b,
                    )
                    first = next(
                        r
                        for r in partner.components
                        if r.residue_index == partner.first_sugar_residue_index
                    )
                    sugar_atom, carrier_atom = (
                        (a, b) if a in first.atom_indexes else (b, a)
                    )
                if (
                    row.carrier_link_atom_index,
                    row.first_sugar_link_atom_index,
                ) != (carrier_atom, sugar_atom):
                    raise ValueError("Glycan atom linkage evidence mismatch")
