"""Typed source-to-reference projection; metrics retain their source authority."""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any, ClassVar, cast

from mania.canonical_reference import (
    InputIdentity,
    ProteinReference,
    ReferenceResidueKey,
)
from mania.canonical_residue_mapping import ResidueMappingRecord, ResidueMappingTable
from mania.preprocessing.protein_edge_window_table import (
    DatasetProteinEdgeWindowRow,
    DatasetProteinEdgeWindowTable,
)
from mania.preprocessing.specialized_contact_window_tables import (
    ProteinGlycanWindowRow,
    ProteinGlycanWindowTable,
    ProteinLipidWindowRow,
    ProteinLipidWindowTable,
)

SCHEMA_VERSION = "mania.reference_windows.v1"


def _values(row: Any) -> dict[str, Any]:
    return {f.name: getattr(row, f.name) for f in fields(row) if f.init}


def _identity(row: Any) -> InputIdentity:
    return InputIdentity(
        project=row.dataset_id,
        system_id=row.system_id,
        trajectory_id=row.trajectory_id,
        replica_id=row.replica_id,
        engine=row.engine,
        condition=row.condition,
        variant_id=row.variant_id,
        disulfide_state=row.disulfide_state,
    )


def _mapped(
    row: Any, prefix: str, mapping: ResidueMappingTable
) -> ResidueMappingRecord:
    if _identity(row) != mapping.identity:
        raise ValueError("Source table/mapping identity mismatch")
    namespace = getattr(row, prefix + "chain_id")
    matches = [
        r
        for r in mapping.records
        if r.source.engine == row.engine
        and (
            r.source.segment_id
            if r.source.namespace_kind == "segment"
            else r.source.chain_id
        )
        == namespace
        and r.source.resid == getattr(row, prefix + "resid")
        and r.source.resname == getattr(row, prefix + "resname")
    ]
    # Source tables have a limited namespace; never guess additional key fields.
    if len(matches) != 1 or matches[0].mapping_status != "mapped":
        raise ValueError("An unambiguous explicit mapped full source key is required")
    return matches[0]


def _reference_values(
    row: Any, mapping: ResidueMappingTable, reference: ProteinReference, layer: str
) -> dict[str, Any]:
    values = _values(row)
    values.update(
        reference_id=reference.reference.reference_id,
        reference_sha256=reference.reference.reference_sha256,
    )
    for prefix, side in (
        (("source_", "i"), ("target_", "j"))
        if layer == "protein"
        else (("protein_", "i"),)
    ):
        record = _mapped(row, prefix, mapping)
        if record.reference_chain_id is None or record.reference_position is None:
            raise ValueError("Missing mapped reference key")
        residue = reference.residue_at(
            ReferenceResidueKey(
                reference_chain_id=record.reference_chain_id,
                reference_position=record.reference_position,
            )
        )
        if record.reference_resname != residue.resname:
            raise ValueError("Mapped reference chemistry mismatch")
        values.update(
            {
                f"reference_chain_{side}": record.reference_chain_id,
                f"reference_position_{side}": record.reference_position,
                f"reference_resname_{side}": record.reference_resname,
            }
        )
    if layer == "protein":
        order = {c.chain_id: i for i, c in enumerate(reference.reference.chains)}
        first = (order[values["reference_chain_i"]], values["reference_position_i"])
        second = (order[values["reference_chain_j"]], values["reference_position_j"])
        if first == second:
            raise ValueError("Reference edge self-loop")
        if first > second:
            for suffix in ("residue_index", "chain_id", "resid", "resname"):
                a, b = "source_" + suffix, "target_" + suffix
                values[a], values[b] = values[b], values[a]
            for prefix in (
                "reference_chain_",
                "reference_position_",
                "reference_resname_",
            ):
                a, b = prefix + "i", prefix + "j"
                values[a], values[b] = values[b], values[a]
    return values


def _validate_row(row: Any, source_type: type[Any]) -> None:
    values = {f.name: getattr(row, f.name) for f in fields(source_type)}
    if (
        source_type is DatasetProteinEdgeWindowRow
        and values["source_residue_index"] > values["target_residue_index"]
    ):
        for suffix in ("residue_index", "chain_id", "resid", "resname"):
            a, b = "source_" + suffix, "target_" + suffix
            values[a], values[b] = values[b], values[a]
    source_type(**values)
    import re

    if (
        type(row.reference_id) is not str
        or not row.reference_id
        or row.reference_id != row.reference_id.strip()
        or re.fullmatch(r"[0-9a-f]{64}", row.reference_sha256) is None
    ):
        raise ValueError("Invalid explicit reference binding")
    for side in ("i", "j") if source_type is DatasetProteinEdgeWindowRow else ("i",):
        if (
            type(getattr(row, f"reference_position_{side}")) is not int
            or getattr(row, f"reference_position_{side}") < 1
        ):
            raise ValueError("Invalid reference position")
        for field in ("chain", "resname"):
            value = getattr(row, f"reference_{field}_{side}")
            if type(value) is not str or not value or value != value.strip():
                raise ValueError("Invalid reference chain/chemistry")


@dataclass(frozen=True)
class ReferenceProteinEdgeWindowRow(DatasetProteinEdgeWindowRow):
    reference_id: str
    reference_sha256: str
    reference_chain_i: str
    reference_position_i: int
    reference_resname_i: str
    reference_chain_j: str
    reference_position_j: int
    reference_resname_j: str

    def __post_init__(self) -> None:
        _validate_row(self, DatasetProteinEdgeWindowRow)


@dataclass(frozen=True)
class ReferenceProteinLipidWindowRow(ProteinLipidWindowRow):
    reference_id: str
    reference_sha256: str
    reference_chain_i: str
    reference_position_i: int
    reference_resname_i: str

    def __post_init__(self) -> None:
        _validate_row(self, ProteinLipidWindowRow)


@dataclass(frozen=True)
class ReferenceProteinGlycanWindowRow(ProteinGlycanWindowRow):
    reference_id: str
    reference_sha256: str
    reference_chain_i: str
    reference_position_i: int
    reference_resname_i: str

    def __post_init__(self) -> None:
        _validate_row(self, ProteinGlycanWindowRow)


@dataclass(frozen=True)
class _ReferenceWindowTable:
    rows: tuple[Any, ...]
    source_table: Any
    mapping: ResidueMappingTable
    reference: ProteinReference
    layer: ClassVar[str]
    row_type: ClassVar[type[Any]]
    source_type: ClassVar[type[Any]]
    schema_version: ClassVar[str] = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if (
            type(self.reference) is not ProteinReference
            or type(self.mapping) is not ResidueMappingTable
        ):
            raise ValueError(
                "Validated generic reference and explicit mapping are required"
            )
        self.reference._require_verified()
        # Revalidate supplied bindings; no model_construct/copy bypass is evidence.
        mapping = ResidueMappingTable.model_validate(self.mapping.model_dump())
        mapping.validate_reference(self.reference)
        if (
            type(self.source_table) is not self.source_type
            or type(self.rows) is not tuple
        ):
            raise ValueError("Exact typed source and reference rows are required")
        self.source_table.__post_init__()
        expected = tuple(
            self.row_type(**_reference_values(r, mapping, self.reference, self.layer))
            for r in self.source_table.rows
        )
        expected = tuple(sorted(expected, key=self._order))
        if (
            any(type(r) is not self.row_type for r in self.rows)
            or self.rows != expected
        ):
            raise ValueError(
                "Reference projection must retain exact source values and bindings"
            )
        identities = [self._order(r) for r in self.rows]
        if len(set(identities)) != len(identities):
            raise ValueError("Reference window identity collision")

    def _order(self, row: Any) -> tuple[Any, ...]:
        chains = {c.chain_id: i for i, c in enumerate(self.reference.reference.chains)}
        base = (
            row.dataset_id,
            row.system_id,
            row.trajectory_id,
            row.replica_id,
            row.window_index,
        )
        if self.layer == "protein":
            return (
                *base,
                row.edge_type,
                chains[row.reference_chain_i],
                row.reference_position_i,
                chains[row.reference_chain_j],
                row.reference_position_j,
            )
        return (
            *base,
            chains[row.reference_chain_i],
            row.reference_position_i,
            getattr(row, self.layer + "_partner_id"),
        )

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "rows": [_values(r) for r in self.rows],
        }


@dataclass(frozen=True)
class ReferenceProteinEdgeWindowTable(_ReferenceWindowTable):
    layer = "protein"
    row_type = ReferenceProteinEdgeWindowRow
    source_type = DatasetProteinEdgeWindowTable


@dataclass(frozen=True)
class ReferenceProteinLipidWindowTable(_ReferenceWindowTable):
    layer = "lipid"
    row_type = ReferenceProteinLipidWindowRow
    source_type = ProteinLipidWindowTable


@dataclass(frozen=True)
class ReferenceProteinGlycanWindowTable(_ReferenceWindowTable):
    layer = "glycan"
    row_type = ReferenceProteinGlycanWindowRow
    source_type = ProteinGlycanWindowTable


ReferenceWindowTable = (
    ReferenceProteinEdgeWindowTable
    | ReferenceProteinLipidWindowTable
    | ReferenceProteinGlycanWindowTable
)
SourceWindowTable = (
    DatasetProteinEdgeWindowTable | ProteinLipidWindowTable | ProteinGlycanWindowTable
)


def build_reference_window_tables(
    source_tables: SourceWindowTable | tuple[SourceWindowTable, ...],
    *,
    mapping: ResidueMappingTable,
    reference: ProteinReference,
) -> ReferenceWindowTable | tuple[ReferenceWindowTable, ...]:
    """Project one typed family or an ordered tuple; no sparse completion claim."""
    if (
        type(mapping) is not ResidueMappingTable
        or type(reference) is not ProteinReference
    ):
        raise ValueError(
            "Explicit mapping and validated generic reference are required"
        )
    mapping.validate_reference(reference)
    if isinstance(source_tables, tuple):
        return tuple(_build_table(t, mapping, reference) for t in source_tables)
    return _build_table(source_tables, mapping, reference)


def _build_table(
    source: SourceWindowTable, mapping: ResidueMappingTable, reference: ProteinReference
) -> ReferenceWindowTable:
    models = {
        DatasetProteinEdgeWindowTable: ReferenceProteinEdgeWindowTable,
        ProteinLipidWindowTable: ReferenceProteinLipidWindowTable,
        ProteinGlycanWindowTable: ReferenceProteinGlycanWindowTable,
    }
    model = models.get(type(source))
    if model is None:
        raise ValueError("Exact protein/lipid/glycan source table required")
    source.__post_init__()
    rows = tuple(
        model.row_type(**_reference_values(r, mapping, reference, model.layer))
        for r in source.rows
    )
    # Sorting uses verified reference chain order, not guessed chain spelling.
    shell = object.__new__(model)
    object.__setattr__(shell, "reference", reference)
    rows = tuple(sorted(rows, key=shell._order))
    return cast(ReferenceWindowTable, model(rows, source, mapping, reference))
