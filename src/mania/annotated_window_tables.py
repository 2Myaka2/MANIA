"""Supplied generic annotations on immutable reference window projections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, cast

from mania.biological_annotations import SystemAnnotations
from mania.canonical_reference import ProteinReference, ReferenceResidueKey
from mania.canonical_window_tables import (
    ReferenceProteinEdgeWindowRow,
    ReferenceProteinEdgeWindowTable,
    ReferenceProteinGlycanWindowRow,
    ReferenceProteinGlycanWindowTable,
    ReferenceProteinLipidWindowRow,
    ReferenceProteinLipidWindowTable,
    ReferenceWindowTable,
    _identity,
    _values,
)

SCHEMA_VERSION = "mania.annotated_reference_windows.v1"


def _annotation_ids(value: tuple[str, ...] | None) -> None:
    if value is not None and (
        type(value) is not tuple
        or len(set(value)) != len(value)
        or any(type(v) is not str or not v or v != v.strip() for v in value)
    ):
        raise ValueError(
            "Annotation IDs must be ordered unique strings, empty or unknown"
        )


@dataclass(frozen=True)
class AnnotatedReferenceProteinEdgeWindowRow(ReferenceProteinEdgeWindowRow):
    annotation_ids_i: tuple[str, ...] | None
    annotation_ids_j: tuple[str, ...] | None

    def __post_init__(self) -> None:
        super().__post_init__()
        _annotation_ids(self.annotation_ids_i)
        _annotation_ids(self.annotation_ids_j)


@dataclass(frozen=True)
class AnnotatedReferenceProteinLipidWindowRow(ReferenceProteinLipidWindowRow):
    annotation_ids_i: tuple[str, ...] | None

    def __post_init__(self) -> None:
        super().__post_init__()
        _annotation_ids(self.annotation_ids_i)


@dataclass(frozen=True)
class AnnotatedReferenceProteinGlycanWindowRow(ReferenceProteinGlycanWindowRow):
    annotation_ids_i: tuple[str, ...] | None

    def __post_init__(self) -> None:
        super().__post_init__()
        _annotation_ids(self.annotation_ids_i)


def _annotate(row: Any, annotations: SystemAnnotations, layer: str) -> dict[str, Any]:
    if _identity(row) != annotations.identity:
        raise ValueError("Window/annotation source identity mismatch")
    values = _values(row)
    for side in ("i", "j") if layer == "protein" else ("i",):
        values["annotation_ids_" + side] = annotations.annotation_ids(
            ReferenceResidueKey(
                reference_chain_id=getattr(row, "reference_chain_" + side),
                reference_position=getattr(row, "reference_position_" + side),
            )
        )
    return values


@dataclass(frozen=True)
class _AnnotatedReferenceWindowTable:
    rows: tuple[Any, ...]
    reference_table: ReferenceWindowTable
    annotations: SystemAnnotations
    reference: ProteinReference
    layer: ClassVar[str]
    row_type: ClassVar[type[Any]]
    reference_type: ClassVar[type[Any]]
    schema_version: ClassVar[str] = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if (
            type(self.reference_table) is not self.reference_type
            or type(self.annotations) is not SystemAnnotations
            or type(self.reference) is not ProteinReference
        ):
            raise ValueError(
                "Exact reference table, annotations and generic reference required"
            )
        self.reference_table.__post_init__()
        if self.reference_table.reference != self.reference:
            raise ValueError("Changed annotation reference binding")
        annotations = SystemAnnotations.model_validate(self.annotations.model_dump())
        annotations.validate_reference(self.reference)
        expected = tuple(
            self.row_type(**_annotate(r, annotations, self.layer))
            for r in self.reference_table.rows
        )
        if (
            type(self.rows) is not tuple
            or any(type(r) is not self.row_type for r in self.rows)
            or self.rows != expected
        ):
            raise ValueError(
                "Annotation projection changed source/reference/scientific values"
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
class AnnotatedReferenceProteinEdgeWindowTable(_AnnotatedReferenceWindowTable):
    layer = "protein"
    row_type = AnnotatedReferenceProteinEdgeWindowRow
    reference_type = ReferenceProteinEdgeWindowTable


@dataclass(frozen=True)
class AnnotatedReferenceProteinLipidWindowTable(_AnnotatedReferenceWindowTable):
    layer = "lipid"
    row_type = AnnotatedReferenceProteinLipidWindowRow
    reference_type = ReferenceProteinLipidWindowTable


@dataclass(frozen=True)
class AnnotatedReferenceProteinGlycanWindowTable(_AnnotatedReferenceWindowTable):
    layer = "glycan"
    row_type = AnnotatedReferenceProteinGlycanWindowRow
    reference_type = ReferenceProteinGlycanWindowTable


AnnotatedReferenceWindowTable = (
    AnnotatedReferenceProteinEdgeWindowTable
    | AnnotatedReferenceProteinLipidWindowTable
    | AnnotatedReferenceProteinGlycanWindowTable
)


def build_annotated_reference_tables(
    reference_tables: ReferenceWindowTable | tuple[ReferenceWindowTable, ...],
    *,
    annotations: SystemAnnotations,
    reference: ProteinReference,
) -> AnnotatedReferenceWindowTable | tuple[AnnotatedReferenceWindowTable, ...]:
    if isinstance(reference_tables, tuple):
        return tuple(_build(t, annotations, reference) for t in reference_tables)
    return _build(reference_tables, annotations, reference)


def _build(
    table: ReferenceWindowTable,
    annotations: SystemAnnotations,
    reference: ProteinReference,
) -> AnnotatedReferenceWindowTable:
    models = {
        ReferenceProteinEdgeWindowTable: AnnotatedReferenceProteinEdgeWindowTable,
        ReferenceProteinLipidWindowTable: AnnotatedReferenceProteinLipidWindowTable,
        ReferenceProteinGlycanWindowTable: AnnotatedReferenceProteinGlycanWindowTable,
    }
    model = models.get(type(table))
    if model is None or type(annotations) is not SystemAnnotations:
        raise ValueError(
            "Typed generic reference table and supplied annotations required"
        )
    annotations.validate_reference(reference)
    rows = tuple(
        model.row_type(**_annotate(r, annotations, model.layer)) for r in table.rows
    )
    return cast(
        AnnotatedReferenceWindowTable, model(rows, table, annotations, reference)
    )
