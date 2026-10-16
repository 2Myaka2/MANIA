"""Explicit fixed window facade and retained Dataset-v1 logical table primitives.

These low-level serializers do not establish a scientific Dataset release.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, fields, replace
from decimal import Decimal
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Literal, TypeAlias, cast

from mania.canonical_window_tables import ReferenceWindowTable
from mania.dataset_qc_contract import QCPolicy
from mania.preprocessing.molecular_partner_metadata_io import write_atomic_text
from mania.preprocessing.physical_time_execution import (
    PreprocessingConditionTemporalExecution,
)
from mania.preprocessing.protein_edge_window_table_io import _serialize
from mania.preprocessing.temporal_policy import LEGACY_BOUNDARY_PROFILE
from mania_napi2b.biological_annotations import DatasetSystemBiologicalAnnotations
from mania_napi2b.canonical_reference import (
    NAPI2B_CANONICAL_ISOFORM_ID,
    NAPI2B_CANONICAL_SEQUENCE_LENGTH,
    NAPI2B_CANONICAL_SEQUENCE_SHA256,
    NAPI2B_UNIPROT_SEQUENCE_VERSION,
)
from mania_napi2b.canonical_reference_io import load_default_napi2b_canonical_reference
from mania_napi2b.canonical_residue_mapping import (
    CanonicalResidueMappingTable,
    validate_canonical_residue_mapping_table,
)

# Selected pinned dataset_release_contract logical contracts only.


DATASET_RELEASE_CONTRACT_SCHEMA_VERSION = "mania.dataset_release_contract.v0.1"
DATASET_RELEASE_VERSION = "1.0"
DATASET_RELEASE_CANONICAL_REFERENCE_ID = (
    f"uniprotkb:{NAPI2B_CANONICAL_ISOFORM_ID}:"
    f"sequence-v{NAPI2B_UNIPROT_SEQUENCE_VERSION}"
)
DATASET_RELEASE_CANONICAL_REFERENCE_SHA256 = NAPI2B_CANONICAL_SEQUENCE_SHA256
CANONICAL_NODE_COUNT = NAPI2B_CANONICAL_SEQUENCE_LENGTH
CANONICAL_RESIDUE_RANGE = (1, CANONICAL_NODE_COUNT)
PublicationArtifactClass = Literal["control", "audit", "publication"]
PublicationLogicalType = Literal["string", "integer", "number", "boolean"]
PublicationEncoding = Literal["csv", "json", "parquet"]
PUBLICATION_ARTIFACT_CLASSES = ("control", "audit", "publication")
PUBLICATION_LOGICAL_TYPES = ("string", "integer", "number", "boolean")
DEVELOPMENT_ORDER = ("27", "28", "29", "30", "31", "32", "33")
PRODUCTION_DAG_ID = "mania.dataset_production.v1.0"
PRODUCTION_EXECUTION_DAG = (
    "stage27_30_per_replica_science",
    "stage32_authoritative_qc_decisions",
    "stage32_qc_derived_stage31_manifest",
    "stage31_replica_aggregation",
    "stage33_publication",
)
AGGREGATE_PUBLICATION_REQUIRED_LINEAGE = (
    "authoritative_stage32_dataset_qc_decision_set",
    "accepted_qc_derived_stage31_aggregation_manifest",
    "stage31_aggregation_run_from_that_manifest",
)
PUBLICATION_POPULATION_RULES = (
    "Historical/provenance population differs from scientific release population.",
    (
        "All production candidate replicas remain in simula"
        "tions, QC and provenance, including excluded repli"
        "cas with their decision reasons and evidence linka"
        "ge."
    ),
    (
        "included_in_replica_aggregation is true only for f"
        "inal QC-derived Stage 31 member state available; e"
        "xcluded and technically unavailable members are fa"
        "lse."
    ),
    (
        "included_in_scientific_release is true only when r"
        "elease_decision is available and required per-repl"
        "ica scientific evidence exists for the publication"
        " layer."
    ),
    (
        "Science and metrics contain only eligible data; mi"
        "ssing technical science does not become QC exclusi"
        "on. Excluded replicas never enter the denominator."
    ),
    (
        "Simulations booleans summarize eligible contributi"
        "ons: true requires at least one eligible layer/win"
        "dow; per-layer eligibility remains authoritative f"
        "or each scientific row. They never grant eligibili"
        "ty to another layer/window."
    ),
    (
        "A technically valid pre-QC Stage 31 aggregate is n"
        "ot publication-authoritative. Stage 33.D must veri"
        "fy all three aggregate lineage requirements."
    ),
)
SERIALIZATION_RULES = (
    "The logical publication model is authoritative; serialization is not science.",
    "CSV is mandatory for every table; JSON is mandatory for hierarchical releases.",
    (
        "Parquet is an optional adapter over the same valid"
        "ated logical table model. CSV works without a Parq"
        "uet backend; an explicit unsupported Parquet reque"
        "st must fail with a clear deterministic optional-a"
        "dapter error."
    ),
    (
        "CSV and optional Parquet must reconstruct equal lo"
        "gical models. A future narrow optional Arrow-capab"
        "le dependency is preferred over a dataframe librar"
        "y for serialization; no such dependency is require"
        "d or added in 33.A."
    ),
    (
        "Logical null is None; CSV uses a blank cell, JSON "
        "null, Parquet native null. Strings None, null, NA "
        "and N/A are never missing-value sentinels. Nullabl"
        "e text uses nonempty supplied strings so blank CSV"
        " cells remain unambiguous; typed contact parameter"
        "s distinguish an empty string using parameter_kind"
        "."
    ),
    "CSV booleans are lowercase true/false, never 0/1 or yes/no.",
    (
        "No rounding or recalculation of occupancy, support"
        "_fraction, lifetime, distance, mean, median, stand"
        "ard deviation or coverage; numbers round-trip loss"
        "lessly."
    ),
    (
        "Adapters cannot recanonicalize source IDs, reevalu"
        "ate QC, override decisions or change scientific in"
        "clusion/exclusion. Nonfinite numbers are forbidden"
        "."
    ),
)
SCIENTIFIC_PUBLICATION_RULES = (
    (
        "Canonical names match the pinned Stage 30 referenc"
        "e at positions 1..690. T330M publishes canonical 3"
        "30 THR; source MET need not equal canonical THR."
    ),
    (
        "Annotation absence means false only under complete"
        "_for_system authority; supplied glycosylation and "
        "variant source/verifier evidence is preserved."
    ),
    (
        "Protein edges remain sparse. Stage 33 creates no a"
        "ll-pairs zero edges; available sparse absence and "
        "zero materialization remain Stage 31 science."
    ),
    (
        "Specialized partner IDs are topology-local per rep"
        "lica. Positive-frame-only distance means/minima an"
        "d accepted episodes/lifetimes are copied unchanged"
        "."
    ),
    (
        "Glycan carrier-first-sugar covalent observations e"
        "xcluded by Stage 29/30 remain audit evidence and n"
        "ever reenter ordinary contact summaries."
    ),
    (
        "partner_correspondence_id is an aggregation corres"
        "pondence identifier, not canonical lipid/glycan, c"
        "hemical registry or cross-system molecule identity"
        "."
    ),
    (
        "Specialized aggregates contain only six occupancy/"
        "support statistics: no distance, lifetime, contact"
        "-frame totals or edge_weight."
    ),
    (
        "Metrics use explicit accepted names without a clos"
        "ed vocabulary or recomputation; excluded-replica r"
        "eview metrics remain QC/audit evidence."
    ),
    (
        "Requested production/window definitions differ fro"
        "m effective observations; window_id alone is never"
        " physical identity. Missing samples are not negati"
        "ves."
    ),
)
CONTACT_DEFINITION_REQUIRED_PARAMETERS = (
    "atom_selections",
    "distance_definition",
    "cutoff",
    "type_specific_parameters",
    "pbc_correction_status",
    "occupancy_denominator_semantics",
    "episode_continuity_semantics",
    "gap_tolerance",
    "lifetime_semantics",
    "specialized_distance_semantics",
)


def _text(value: object, field: str) -> None:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError(f"{field} must be a nonempty stripped string")


def _names(value: tuple[str, ...], field: str, *, allow_empty: bool = False) -> None:
    if type(value) is not tuple or (not value and (not allow_empty)):
        raise ValueError(f"{field} must be an immutable tuple")
    for name in value:
        _text(name, field)
    if len(set(value)) != len(value):
        raise ValueError(f"{field} must not contain duplicates")


def _path(value: str) -> None:
    _text(value, "relative_path")
    if any(
        part in ("", ".", "..") or part.startswith("~") for part in value.split("/")
    ) or any(char in value for char in "\\:\x00\r\n\t"):
        raise ValueError("Paths must be portable forward-slash relative paths")


@dataclass(frozen=True)
class PublicationColumnSpec:
    name: str
    logical_type: PublicationLogicalType
    nullable: bool
    description: str

    def __post_init__(self) -> None:
        _text(self.name, "name")
        _text(self.description, "description")
        if self.logical_type not in PUBLICATION_LOGICAL_TYPES:
            raise ValueError("Invalid logical type")
        if type(self.nullable) is not bool:
            raise ValueError("nullable must be boolean")

    def to_dict(self) -> dict[str, object]:
        return dict(
            name=self.name,
            logical_type=self.logical_type,
            nullable=self.nullable,
            description=self.description,
        )


@dataclass(frozen=True)
class PublicationForeignKeySpec:
    local_columns: tuple[str, ...]
    target_table: str
    target_columns: tuple[str, ...]

    def __post_init__(self) -> None:
        _names(self.local_columns, "local_columns")
        _text(self.target_table, "target_table")
        _names(self.target_columns, "target_columns")
        if len(self.local_columns) != len(self.target_columns):
            raise ValueError("Foreign-key arity must match")

    def to_dict(self) -> dict[str, object]:
        return dict(
            local_columns=list(self.local_columns),
            target_table=self.target_table,
            target_columns=list(self.target_columns),
        )


@dataclass(frozen=True)
class PublicationTableSpec:
    table_id: str
    relative_path: str
    artifact_class: PublicationArtifactClass
    columns: tuple[PublicationColumnSpec, ...]
    primary_key: tuple[str, ...]
    foreign_keys: tuple[PublicationForeignKeySpec, ...]
    required: bool

    def __post_init__(self) -> None:
        _text(self.table_id, "table_id")
        _path(self.relative_path)
        if self.artifact_class not in PUBLICATION_ARTIFACT_CLASSES:
            raise ValueError("Invalid artifact class")
        if type(self.required) is not bool:
            raise ValueError("required must be boolean")
        if (
            type(self.columns) is not tuple
            or not self.columns
            or any(type(column) is not PublicationColumnSpec for column in self.columns)
        ):
            raise ValueError("columns must be a nonempty tuple of column specs")
        names = tuple(column.name for column in self.columns)
        _names(names, "columns")
        _names(self.primary_key, "primary_key")
        if not set(self.primary_key) <= set(names):
            raise ValueError("Primary-key column absent from schema")
        if any(c.nullable for c in self.columns if c.name in self.primary_key):
            raise ValueError("Primary-key columns cannot be nullable")
        if type(self.foreign_keys) is not tuple or any(
            type(fk) is not PublicationForeignKeySpec for fk in self.foreign_keys
        ):
            raise ValueError("foreign_keys must be a tuple of foreign-key specs")
        if len(set(self.foreign_keys)) != len(self.foreign_keys):
            raise ValueError("Duplicate foreign keys")
        if any(not set(fk.local_columns) <= set(names) for fk in self.foreign_keys):
            raise ValueError("Foreign-key local column absent from schema")

    def to_dict(self) -> dict[str, object]:
        return dict(
            table_id=self.table_id,
            relative_path=self.relative_path,
            artifact_class=self.artifact_class,
            columns=[c.to_dict() for c in self.columns],
            primary_key=list(self.primary_key),
            foreign_keys=[fk.to_dict() for fk in self.foreign_keys],
            required=self.required,
        )


@dataclass(frozen=True)
class PublicationJSONSpec:
    """Required logical roles/fields, not the final hierarchical wire schema."""

    required_fields: tuple[str, ...]
    description: str

    def __post_init__(self) -> None:
        _names(self.required_fields, "required_fields")
        _text(self.description, "description")

    def to_dict(self) -> dict[str, object]:
        return dict(
            required_fields=list(self.required_fields), description=self.description
        )


@dataclass(frozen=True)
class PublicationArtifactSpec:
    artifact_id: str
    relative_path: str
    artifact_class: PublicationArtifactClass
    logical_schema: PublicationTableSpec | PublicationJSONSpec
    mandatory_encoding: PublicationEncoding
    optional_encodings: tuple[PublicationEncoding, ...] = ()
    required_lineage: tuple[str, ...] = ()
    required: bool = True

    def __post_init__(self) -> None:
        _text(self.artifact_id, "artifact_id")
        _path(self.relative_path)
        if self.artifact_class not in PUBLICATION_ARTIFACT_CLASSES:
            raise ValueError("Invalid artifact class")
        if type(self.required) is not bool:
            raise ValueError("required must be boolean")
        _names(self.required_lineage, "required_lineage", allow_empty=True)
        _names(self.optional_encodings, "optional_encodings", allow_empty=True)
        schema = self.logical_schema
        if type(schema) is PublicationTableSpec:
            if (
                self.artifact_id,
                self.relative_path,
                self.artifact_class,
                self.required,
            ) != (
                schema.table_id,
                schema.relative_path,
                schema.artifact_class,
                schema.required,
            ):
                raise ValueError("Artifact and table identity must agree")
            if self.mandatory_encoding != "csv" or self.optional_encodings not in (
                (),
                ("parquet",),
            ):
                raise ValueError("Tables require CSV with optional Parquet only")
        elif type(schema) is PublicationJSONSpec:
            if self.mandatory_encoding != "json" or self.optional_encodings:
                raise ValueError("Hierarchical release artifacts require JSON")
        else:
            raise ValueError("Invalid logical schema")
        if not self.relative_path.endswith(f".{self.mandatory_encoding}"):
            raise ValueError("Path suffix must match mandatory encoding")

    def to_dict(self) -> dict[str, object]:
        return dict(
            artifact_id=self.artifact_id,
            relative_path=self.relative_path,
            artifact_class=self.artifact_class,
            logical_schema=self.logical_schema.to_dict(),
            mandatory_encoding=self.mandatory_encoding,
            optional_encodings=list(self.optional_encodings),
            required_lineage=list(self.required_lineage),
            required=self.required,
        )


@dataclass(frozen=True)
class PublicationArtifactRegistry:
    artifacts: tuple[PublicationArtifactSpec, ...]

    def __post_init__(self) -> None:
        if (
            type(self.artifacts) is not tuple
            or not self.artifacts
            or any(type(a) is not PublicationArtifactSpec for a in self.artifacts)
        ):
            raise ValueError("artifacts must be a nonempty tuple of artifact specs")
        _names(tuple(a.artifact_id for a in self.artifacts), "artifact IDs/table IDs")
        _names(tuple(a.relative_path for a in self.artifacts), "relative paths")
        object.__setattr__(
            self,
            "artifacts",
            tuple(sorted(self.artifacts, key=lambda artifact: artifact.relative_path)),
        )
        tables = {
            a.artifact_id: a.logical_schema
            for a in self.artifacts
            if isinstance(a.logical_schema, PublicationTableSpec)
        }
        for table in tables.values():
            local = {c.name: c for c in table.columns}
            for fk in table.foreign_keys:
                target = tables.get(fk.target_table)
                if target is None or fk.target_columns != target.primary_key:
                    raise ValueError(
                        "Foreign key must reference an existing primary key"
                    )
                remote = {c.name: c for c in target.columns}
                if any(
                    (
                        local[a].logical_type != remote[b].logical_type
                        for a, b in zip(
                            fk.local_columns, fk.target_columns, strict=True
                        )
                    )
                ):
                    raise ValueError("Foreign-key logical types must match")

    @property
    def tables(self) -> tuple[PublicationTableSpec, ...]:
        return tuple(
            a.logical_schema
            for a in self.artifacts
            if isinstance(a.logical_schema, PublicationTableSpec)
        )

    def to_dict(self) -> dict[str, object]:
        return {"artifacts": [a.to_dict() for a in self.artifacts]}


def _column(
    name: str,
    kind: PublicationLogicalType = "string",
    *,
    nullable: bool = False,
    description: str,
) -> PublicationColumnSpec:
    return PublicationColumnSpec(name, kind, nullable, description)


def _strings(
    names: tuple[str, ...], description: str, *, nullable: bool = False
) -> tuple[PublicationColumnSpec, ...]:
    return tuple(_column(n, nullable=nullable, description=description) for n in names)


def _numbers(
    names: tuple[str, ...],
    *,
    kind: PublicationLogicalType = "number",
    nullable: bool = False,
    description: str,
) -> tuple[PublicationColumnSpec, ...]:
    return tuple(
        _column(n, kind, nullable=nullable, description=description) for n in names
    )


SYSTEM_KEY = ("dataset_id", "system_id")
REPLICA_KEY = (*SYSTEM_KEY, "trajectory_id", "replica_id")
WINDOW_KEY = (*REPLICA_KEY, "window_id", "window_index")
NODE_KEY = ("canonical_reference_id", "canonical_residue_number")
_SYSTEM = _strings(SYSTEM_KEY, "Authoritative Dataset system identity.")
_REPLICA = _strings(REPLICA_KEY, "Full production candidate replica identity.")
_IDENTITY_LABELS = (
    *_strings(("engine", "variant_id"), "Accepted system metadata; never inferred."),
    *_strings(
        ("condition", "disulfide_state"),
        "Accepted nullable system metadata.",
        nullable=True,
    ),
)
_REFERENCE = _column(
    "canonical_reference_id", description="Pinned Stage 30 reference ID."
)
_REFERENCE_HASH = _column(
    "canonical_reference_sequence_sha256",
    description="Pinned Stage 30 sequence SHA256.",
)
_WINDOW_LABELS = (
    _column("window_id", description="Window label; not physical identity alone."),
    _column("window_index", "integer", description="Accepted window schedule index."),
)
_REQUESTED_BOUNDS = _numbers(
    ("requested_window_start_ns", "requested_window_end_ns"),
    description="Requested physical window boundary in ns, not observed coverage.",
)
_ENDPOINT = _column(
    "right_endpoint_inclusive",
    "boolean",
    description="Accepted requested right-boundary inclusion rule.",
)
_PRODUCTION = _numbers(
    ("requested_production_start_ns", "requested_production_end_ns"),
    description="Requested production interval boundary in ns.",
)
_SCHEDULE = _numbers(
    ("window_length_ns", "window_step_ns", "overlap_percent"),
    description="Unmodified requested physical window schedule.",
)
_WINDOW_DEFINITION = (
    *_WINDOW_LABELS,
    *_PRODUCTION,
    *_REQUESTED_BOUNDS,
    _ENDPOINT,
    *_SCHEDULE,
)
_SCIENCE_WINDOW = (
    *_WINDOW_LABELS,
    *_REQUESTED_BOUNDS,
    _ENDPOINT,
    *_numbers(
        ("effective_window_start_ns", "effective_window_end_ns"),
        description="Accepted actual observed window endpoints in ns.",
    ),
    *_numbers(
        ("requested_sample_count", "resolved_frame_count", "missing_sample_count"),
        kind="integer",
        description="Accepted sampling counts; denominator is resolved.",
    ),
    _column(
        "coverage_fraction",
        "number",
        description="Accepted observed sampling coverage.",
    ),
)
_PER_REPLICA = (*_REPLICA, *_IDENTITY_LABELS, *_SCIENCE_WINDOW, _REFERENCE)
_QC_DECISION = (
    *_strings(
        ("qc_status", "release_decision", "decision_mode"),
        "Authoritative Stage 32 decision; copied without reevaluation.",
    ),
    *_strings(
        ("decision_reason_code", "human_readable_reason"),
        "Authoritative decision reason; absent for PASS.",
        nullable=True,
    ),
)
_CANONICAL_RESIDUE = (
    _column(
        "canonical_residue_number", "integer", description="Stage 30 position 1..690."
    ),
    _column(
        "canonical_resname", description="Pinned canonical name, including THR at 330."
    ),
)
_EDGE = (
    _column(
        "source_canonical_residue_number",
        "integer",
        description="Canonical graph source endpoint; never source topology identity.",
    ),
    _column(
        "source_canonical_resname", description="Pinned source endpoint residue name."
    ),
    _column(
        "target_canonical_residue_number",
        "integer",
        description="Canonical graph target endpoint; never source topology identity.",
    ),
    _column(
        "target_canonical_resname", description="Pinned target endpoint residue name."
    ),
    _column("edge_type", description="Accepted protein interaction type."),
)
_EPISODES = (
    _column(
        "n_contact_frames",
        "integer",
        description="Accepted positive resolved-frame count.",
    ),
    _column(
        "occupancy",
        "number",
        description="Accepted n_contact_frames / resolved_frame_count.",
    ),
    _column(
        "n_contact_episodes",
        "integer",
        description="Accepted continuous episode count.",
    ),
    *_numbers(
        ("mean_episode_length_ns", "max_episode_length_ns"),
        description="Accepted episode durations from actual positive endpoint times.",
    ),
)
_DISTANCES = _numbers(
    ("distance_mean_A", "distance_min_A"),
    description="Accepted distance over contact-positive frames only, in Å.",
)
_STATISTICS = (
    _column(
        "mean_occupancy", "number", description="Accepted Stage 31 occupancy mean."
    ),
    _column(
        "std_occupancy",
        "number",
        nullable=True,
        description="Accepted sample SD; null for fewer than two available replicas.",
    ),
    _column(
        "median_occupancy", "number", description="Accepted Stage 31 occupancy median."
    ),
    *_numbers(
        ("n_replicates_available", "n_replicates_supporting"),
        kind="integer",
        description="Accepted available denominator / positive support counts.",
    ),
    _column(
        "support_fraction",
        "number",
        description="Accepted supporting / available fraction.",
    ),
)


def _fk(
    target: str, columns: tuple[str, ...], target_columns: tuple[str, ...] | None = None
) -> PublicationForeignKeySpec:
    return PublicationForeignKeySpec(columns, target, target_columns or columns)


_SYSTEM_FK = _fk("systems", SYSTEM_KEY)
_REPLICA_FK = _fk("simulations", REPLICA_KEY)
_WINDOW_FK = _fk("time_windows", WINDOW_KEY)
_NODE_FK = _fk("nodes", NODE_KEY)
_EDGE_FKS = tuple(
    _fk(
        "nodes",
        ("canonical_reference_id", f"{side}_canonical_residue_number"),
        NODE_KEY,
    )
    for side in ("source", "target")
)


def _table(
    table_id: str,
    folder: str,
    columns: tuple[PublicationColumnSpec, ...],
    key: tuple[str, ...],
    fks: tuple[PublicationForeignKeySpec, ...] = (),
    *,
    aggregate: bool = False,
) -> PublicationArtifactSpec:
    path = f"{folder}/{table_id}.csv"
    table = PublicationTableSpec(table_id, path, "publication", columns, key, fks, True)
    return PublicationArtifactSpec(
        table_id,
        path,
        "publication",
        table,
        "csv",
        ("parquet",),
        AGGREGATE_PUBLICATION_REQUIRED_LINEAGE if aggregate else (),
    )


def _specialized(kind: Literal["lipid", "glycan"]) -> PublicationArtifactSpec:
    partner = f"{kind}_partner_id"
    return _table(
        f"protein_{kind}_contacts_by_window",
        "science",
        (
            *_PER_REPLICA,
            *_CANONICAL_RESIDUE,
            _column(
                partner,
                description="Topology-local partner ID scoped to full replica key.",
            ),
            _column(f"{kind}_partner_name", description="Supplied local partner name."),
            *_EPISODES,
            *_DISTANCES,
        ),
        (*WINDOW_KEY, "canonical_reference_id", "canonical_residue_number", partner),
        (_REPLICA_FK, _WINDOW_FK, _NODE_FK),
    )


def _aggregate(kind: Literal["protein", "lipid", "glycan"]) -> PublicationArtifactSpec:
    entity: tuple[PublicationColumnSpec, ...]
    entity_key: tuple[str, ...]
    if kind == "protein":
        name = "protein_edges_by_window_replica_aggregation"
        entity = _EDGE
        entity_key = (
            "source_canonical_residue_number",
            "target_canonical_residue_number",
            "edge_type",
        )
        fks = _EDGE_FKS
    else:
        name = f"protein_{kind}_contacts_by_window_replica_aggregation"
        entity = (
            *_CANONICAL_RESIDUE,
            _column(
                "partner_correspondence_id",
                description=(
                    "Aggregation correspondence only; not canonical/che"
                    "mical/cross-system ID."
                ),
            ),
            _column(
                "partner_name", description="Accepted correspondence partner name."
            ),
        )
        entity_key = ("canonical_residue_number", "partner_correspondence_id")
        fks = (_NODE_FK,)
    return _table(
        name,
        "aggregates",
        (
            *_SYSTEM,
            *_IDENTITY_LABELS,
            *_WINDOW_DEFINITION,
            _REFERENCE,
            *entity,
            *_STATISTICS,
        ),
        (
            *SYSTEM_KEY,
            "engine",
            *(c.name for c in _WINDOW_DEFINITION),
            "canonical_reference_id",
            *entity_key,
        ),
        (_SYSTEM_FK, *fks),
        aggregate=True,
    )


_TABLE_ARTIFACTS = (
    _table("systems", "metadata", (*_SYSTEM, *_IDENTITY_LABELS), SYSTEM_KEY),
    _table(
        "simulations",
        "metadata",
        (
            *_REPLICA,
            *_IDENTITY_LABELS,
            *_QC_DECISION,
            _column(
                "aggregation_availability_status",
                nullable=True,
                description=(
                    "Final QC-derived Stage 31 availability; null when "
                    "no final member state exists."
                ),
            ),
            _column(
                "aggregation_availability_reason",
                nullable=True,
                description="Accepted technical/QC availability reason.",
            ),
            _column(
                "included_in_scientific_release",
                "boolean",
                description=(
                    "Available release decision and required science ex"
                    "ists for the included layer."
                ),
            ),
            _column(
                "included_in_replica_aggregation",
                "boolean",
                description=(
                    "True only for contributions with final QC-derived "
                    "member state available."
                ),
            ),
        ),
        REPLICA_KEY,
        (_SYSTEM_FK, _fk("quality_control", REPLICA_KEY)),
    ),
    _table(
        "time_windows",
        "metadata",
        (
            *_REPLICA,
            *_WINDOW_DEFINITION,
            _column(
                "frame_stride_ps",
                "number",
                description="Accepted requested sampling stride.",
            ),
            *_numbers(
                (
                    "expected_sample_count",
                    "resolved_sample_count",
                    "missing_sample_count",
                ),
                kind="integer",
                description="Requested/resolved/missing sample evidence.",
            ),
            _column(
                "coverage_fraction",
                "number",
                description="Accepted sampling coverage fraction.",
            ),
            *_numbers(
                ("effective_start_ns", "effective_end_ns"),
                nullable=True,
                description="Observed endpoints only where accepted evidence exists.",
            ),
        ),
        WINDOW_KEY,
        (_REPLICA_FK,),
    ),
    _table(
        "contact_definitions",
        "metadata",
        (
            *_REPLICA,
            _column(
                "contact_definition_id", description="Definition ID scoped to replica."
            ),
            _column(
                "contact_layer",
                description="protein-protein, protein-lipid or protein-glycan.",
            ),
            _column(
                "interaction_type", description="Accepted interaction/contact type."
            ),
            _column(
                "parameter_path",
                description=(
                    "Escaped slash-separated parameter path; $ is root,"
                    " array positions are zero-based."
                ),
            ),
            _column(
                "parameter_kind",
                description=(
                    "string/integer/number/boolean/null/object/array; p"
                    "reserves empty containers."
                ),
            ),
            _column(
                "string_value",
                nullable=True,
                description="Exact string scalar, when applicable.",
            ),
            _column(
                "integer_value",
                "integer",
                nullable=True,
                description="Exact integer scalar.",
            ),
            _column(
                "number_value",
                "number",
                nullable=True,
                description="Unrounded numeric scalar.",
            ),
            _column(
                "boolean_value", "boolean", nullable=True, description="Boolean scalar."
            ),
            _column(
                "unit",
                nullable=True,
                description="Authoritative parameter unit where applicable.",
            ),
            _column(
                "source_artifact_role",
                description="Authoritative definition/configuration role.",
            ),
            _column(
                "source_artifact_path",
                description="Portable source evidence reference.",
            ),
        ),
        (*REPLICA_KEY, "contact_definition_id", "parameter_path"),
        (_REPLICA_FK,),
    ),
    _table(
        "software_versions",
        "metadata",
        (
            _column("dataset_id", description="Dataset identity."),
            *_strings(
                ("component_role", "component_name"),
                "MANIA/WANIA package, Python/runtime package or MD engine component.",
            ),
            _column(
                "version",
                nullable=True,
                description="Authoritative version; unknown stays null.",
            ),
            _column(
                "run_id",
                nullable=True,
                description="Authoritative source run identity if present.",
            ),
            _column(
                "source_artifact_role",
                description="Software/runtime/engine evidence role.",
            ),
            _column(
                "source_artifact_path",
                description="Portable source evidence reference.",
            ),
        ),
        ("dataset_id", "source_artifact_path", "component_role", "component_name"),
    ),
    _table(
        "quality_control",
        "metadata",
        (
            *_REPLICA,
            _column("hard_qc_status", description="Accepted Stage 32 hard-QC status."),
            _column(
                "review_qc_status",
                nullable=True,
                description="Null for hard-failed replicas.",
            ),
            *_QC_DECISION,
            *_strings(
                ("reviewer", "decision_note"),
                "Manual decision provenance; automatic is null.",
                nullable=True,
            ),
            *_numbers(
                ("hard_fail_count", "review_finding_count", "total_check_count"),
                kind="integer",
                description="Accepted decision summary counts.",
            ),
        ),
        REPLICA_KEY,
        (_REPLICA_FK,),
    ),
    _table(
        "quality_control_findings",
        "metadata",
        (
            *_REPLICA,
            _column("check_id", description="Accepted check identity, including PASS."),
            _column("status", description="Accepted finding status."),
            *_strings(
                ("reason_code", "human_readable_reason"),
                "Accepted finding explanation, null where accepted for PASS.",
                nullable=True,
            ),
        ),
        (*REPLICA_KEY, "check_id"),
        (_fk("quality_control", REPLICA_KEY),),
    ),
    _table(
        "quality_control_evidence",
        "metadata",
        (
            *_REPLICA,
            *_strings(
                ("check_id", "evidence_id", "evidence_type"),
                "Structured evidence identity and accepted type.",
            ),
            *_strings(
                (
                    "artifact_role",
                    "artifact_path",
                    "window_id",
                    "metric_name",
                    "observed_value",
                    "expected_or_threshold",
                    "details",
                ),
                (
                    "Accepted nullable evidence text; artifact_path is "
                    "portable, never absolute."
                ),
                nullable=True,
            ),
            _column(
                "used_for_decision",
                "boolean",
                description=(
                    "Membership in accepted decision_evidence_ids; no reevaluation."
                ),
            ),
        ),
        (*REPLICA_KEY, "check_id", "evidence_id"),
        (_fk("quality_control_findings", (*REPLICA_KEY, "check_id")),),
    ),
    _table(
        "nodes",
        "canonical",
        (_REFERENCE, _REFERENCE_HASH, *_CANONICAL_RESIDUE),
        NODE_KEY,
    ),
    _table(
        "residue_annotations",
        "canonical",
        (
            *_SYSTEM,
            _REFERENCE,
            *_CANONICAL_RESIDUE,
            _column("annotation_scope", description="Must be complete_for_system."),
            *(
                _column(
                    n,
                    "boolean",
                    description="Accepted reference-derived region membership.",
                )
                for n in ("is_ecd", "is_mx35_region")
            ),
            _column(
                "is_glycosylation_site",
                "boolean",
                description="Supplied complete-system flag.",
            ),
            _column(
                "glycosylation_present_in_topology",
                "boolean",
                nullable=True,
                description="Supplied topology presence; null outside a site.",
            ),
            *_strings(
                ("glycan_name", "glycosylation_source", "glycosylation_verifier"),
                "Supplied glycosylation annotation evidence.",
                nullable=True,
            ),
            *(
                _column(
                    n, "boolean", description="Supplied complete-system variant flag."
                )
                for n in ("is_disulfide_variant_site", "is_cysteine_variant_site")
            ),
            *_strings(
                (
                    "disulfide_variant_source",
                    "disulfide_variant_verifier",
                    "cysteine_variant_source",
                    "cysteine_variant_verifier",
                ),
                (
                    "Authoritative Stage 30 variant site source/verifie"
                    "r; null outside site."
                ),
                nullable=True,
            ),
        ),
        (*SYSTEM_KEY, "canonical_residue_number"),
        (_SYSTEM_FK, _NODE_FK),
    ),
    _table(
        "protein_edges_by_window",
        "science",
        (
            *_PER_REPLICA,
            *_EDGE,
            *_EPISODES,
            _column(
                "edge_weight",
                "number",
                description="Accepted protein edge weight equals occupancy.",
            ),
        ),
        (
            *WINDOW_KEY,
            "canonical_reference_id",
            "source_canonical_residue_number",
            "target_canonical_residue_number",
            "edge_type",
        ),
        (_REPLICA_FK, _WINDOW_FK, *_EDGE_FKS),
    ),
    _specialized("lipid"),
    _specialized("glycan"),
    _aggregate("protein"),
    _aggregate("lipid"),
    _aggregate("glycan"),
    _table(
        "metrics",
        "metrics",
        (
            *_REPLICA,
            _column(
                "metric_id",
                description=(
                    "Deterministic source-record/metric identity scoped"
                    " to replica; no UUID or clock."
                ),
            ),
            _column(
                "window_id", nullable=True, description="Null for a non-window metric."
            ),
            _column(
                "window_index",
                "integer",
                nullable=True,
                description="Null together with window_id for a non-window metric.",
            ),
            _column(
                "metric_name",
                description="Explicit authoritative name; no closed vocabulary.",
            ),
            _column(
                "metric_value",
                "number",
                nullable=True,
                description=(
                    "Accepted value without recomputation; null only if"
                    " accepted upstream."
                ),
            ),
            _column(
                "unit", nullable=True, description="Supplied authoritative metric unit."
            ),
            _column(
                "source_artifact_role",
                description="Authoritative scientific metric source role.",
            ),
            _column(
                "source_artifact_path",
                description="Portable scientific source reference.",
            ),
            _column(
                "source_record_key",
                description="Deterministic row/record locator in the accepted source.",
            ),
        ),
        (*REPLICA_KEY, "metric_id"),
        (_REPLICA_FK, _WINDOW_FK),
    ),
)
_JSON_ARTIFACTS = tuple(
    (
        PublicationArtifactSpec(
            name,
            f"release/{name}.json",
            "publication",
            PublicationJSONSpec(required_fields, description),
            "json",
        )
        for name, required_fields, description in (
            (
                "dataset_manifest",
                (
                    "release_schema_version",
                    "dataset_release_version",
                    "dataset_id",
                    "canonical_reference_id",
                    "canonical_reference_sequence_sha256",
                    "production_dag_id",
                    "publication_artifacts",
                    "authoritative_stage32_qc_decision_source",
                    "authoritative_qc_derived_stage31_manifest_source",
                    "authoritative_stage31_aggregation_run_source",
                ),
                (
                    "Release identity, registry/references and mandator"
                    "y QC-derived aggregation authority."
                ),
            ),
            (
                "artifact_inventory",
                ("release_schema_version", "dataset_id", "artifacts"),
                (
                    "Portable inventory of release artifacts with class"
                    "es, encodings and lineage references; existing gen"
                    "eric inventory schemas remain unchanged."
                ),
            ),
            (
                "provenance",
                (
                    "release_schema_version",
                    "dataset_id",
                    "production_dag_id",
                    "production_execution_dag",
                    "candidate_replica_lineage",
                    "qc_decision_source",
                    "qc_derived_aggregation_manifest_source",
                    "aggregation_run_source",
                    "publication_artifact_lineage",
                ),
                (
                    "Actual order 27–30 -> 32 -> QC-derived 31 -> 31 ag"
                    "gregation -> 33 publication; all candidates, inclu"
                    "ding excluded replicas, retain portable evidence l"
                    "inkage. Stage 33.D decides audit packaging/referen"
                    "ce policy; generic provenance is unchanged."
                ),
            ),
        )
    )
)
PUBLICATION_ARTIFACT_REGISTRY = PublicationArtifactRegistry(
    (*_TABLE_ARTIFACTS, *_JSON_ARTIFACTS)
)
PUBLICATION_TABLE_SPECS = PUBLICATION_ARTIFACT_REGISTRY.tables
PUBLICATION_TABLE_PATHS = tuple(t.relative_path for t in PUBLICATION_TABLE_SPECS)
REQUIRED_RELEASE_JSON_PATHS = tuple(
    a.relative_path
    for a in PUBLICATION_ARTIFACT_REGISTRY.artifacts
    if a.mandatory_encoding == "json"
)


def dataset_release_contract_to_dict() -> dict[str, object]:
    """Return detached, deterministic JSON-safe schema data; never publication data."""
    return {
        "schema_version": DATASET_RELEASE_CONTRACT_SCHEMA_VERSION,
        "dataset_release_version": DATASET_RELEASE_VERSION,
        "canonical_reference_id": DATASET_RELEASE_CANONICAL_REFERENCE_ID,
        "canonical_reference_sequence_sha256": (
            DATASET_RELEASE_CANONICAL_REFERENCE_SHA256
        ),
        "canonical_node_count": CANONICAL_NODE_COUNT,
        "canonical_residue_range": list(CANONICAL_RESIDUE_RANGE),
        "artifact_classes": list(PUBLICATION_ARTIFACT_CLASSES),
        "logical_types": list(PUBLICATION_LOGICAL_TYPES),
        "development_order": list(DEVELOPMENT_ORDER),
        "production_dag_id": PRODUCTION_DAG_ID,
        "production_execution_dag": list(PRODUCTION_EXECUTION_DAG),
        "aggregate_required_lineage": list(AGGREGATE_PUBLICATION_REQUIRED_LINEAGE),
        "population_rules": list(PUBLICATION_POPULATION_RULES),
        "serialization_rules": list(SERIALIZATION_RULES),
        "scientific_rules": list(SCIENTIFIC_PUBLICATION_RULES),
        "contact_definition_required_parameters": list(
            CONTACT_DEFINITION_REQUIRED_PARAMETERS
        ),
        "registry": PUBLICATION_ARTIFACT_REGISTRY.to_dict(),
    }


# Selected pinned dataset_release_csv logical contracts only.


PublicationScalar: TypeAlias = str | int | Decimal | bool | None
PublicationRow: TypeAlias = tuple[PublicationScalar, ...]
METADATA_TABLE_IDS = (
    "systems",
    "simulations",
    "time_windows",
    "contact_definitions",
    "software_versions",
    "quality_control",
    "quality_control_findings",
    "quality_control_evidence",
    "nodes",
    "residue_annotations",
)


class DatasetReleaseCSVError(ValueError):
    """Invalid publication schema, logical row, or CSV operation."""


def publication_table_spec(table_id: str) -> PublicationTableSpec:
    """Return only an exact frozen Stage 33.A tabular publication descriptor."""
    for spec in PUBLICATION_TABLE_SPECS:
        if spec.table_id == table_id:
            return spec
    raise DatasetReleaseCSVError("Unsupported publication table ID")


def require_portable_publication_path(value: str) -> None:
    """Validate supplied evidence lexically, without resolving or rewriting it."""
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or any(p in ("", ".", "..") for p in value.split("/"))
        or any(c in value for c in "\\:~$%")
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise DatasetReleaseCSVError("Evidence must use a portable relative path")


def publication_number(value: object) -> Decimal:
    """Exact numeric value, independent of the caller's Decimal context.

    Binary floats become their exact decimal expansion (not rounded display
    strings). Reading that expansion restores the same logical value and float.
    Removing insignificant trailing zeros does not use Decimal arithmetic.
    """
    if type(value) is float:
        number = Decimal.from_float(value)
    elif type(value) is int:
        number = Decimal(value)
    elif isinstance(value, Decimal):
        number = value
    else:
        raise DatasetReleaseCSVError("Expected an integer, float or Decimal number")
    if not number.is_finite():
        raise DatasetReleaseCSVError("Publication numbers must be finite")
    sign, digits, exponent = number.as_tuple()
    if not isinstance(exponent, int):
        raise DatasetReleaseCSVError("Invalid numeric exponent")
    if not number:
        return Decimal((sign, (0,), 0))
    while len(digits) > 1 and digits[-1] == 0:
        digits, exponent = (digits[:-1], exponent + 1)
    return Decimal((sign, digits, exponent))


def _scalar(
    value: object, column: PublicationColumnSpec, *, empty: bool
) -> PublicationScalar:
    if value is None:
        if not column.nullable:
            raise DatasetReleaseCSVError(f"{column.name} is not nullable")
        return None
    if column.logical_type == "number":
        return publication_number(value)
    expected = {"string": str, "integer": int, "boolean": bool}[column.logical_type]
    if type(value) is not expected:
        raise DatasetReleaseCSVError(f"Invalid logical type for {column.name}")
    if isinstance(value, str):
        if not value and (not empty):
            raise DatasetReleaseCSVError(f"Empty text is ambiguous for {column.name}")
        if column.name.endswith("artifact_path"):
            require_portable_publication_path(value)
        return value
    if isinstance(value, (int, bool)):
        return value
    raise DatasetReleaseCSVError("Invalid scalar")


def _contact_scalar(record: Mapping[str, PublicationScalar]) -> None:
    kind = record["parameter_kind"]
    if kind not in (
        "string",
        "integer",
        "number",
        "boolean",
        "null",
        "object",
        "array",
    ):
        raise DatasetReleaseCSVError("Invalid contact parameter kind")
    if record["contact_layer"] not in (
        "protein-protein",
        "protein-lipid",
        "protein-glycan",
    ):
        raise DatasetReleaseCSVError("Invalid contact layer")
    for name in ("string", "integer", "number", "boolean"):
        if (record[f"{name}_value"] is not None) != (name == kind):
            raise DatasetReleaseCSVError("Contact scalar must match parameter_kind")


def _contact_trees(records: tuple[dict[str, PublicationScalar], ...]) -> None:
    """Validate the frozen parameter-tree encoding without evaluating definitions."""
    groups: dict[
        tuple[PublicationScalar, ...], dict[str, dict[str, PublicationScalar]]
    ] = {}
    for record in records:
        key = tuple(record[n] for n in (*REPLICA_KEY, "contact_definition_id"))
        path = record["parameter_path"]
        assert isinstance(path, str)
        if path != "$" and (not path.startswith("$/")) or re.search("~(?![01])", path):
            raise DatasetReleaseCSVError("Invalid escaped contact parameter path")
        groups.setdefault(key, {})[path] = record
    for tree in groups.values():
        root = tree.get("$")
        if (
            root is None
            or root["parameter_kind"] != "object"
            or any(
                f"$/{name}" not in tree
                for name in CONTACT_DEFINITION_REQUIRED_PARAMETERS
            )
        ):
            raise DatasetReleaseCSVError(
                "Contact tree lacks its required parameter roots"
            )
        children: dict[str, list[str]] = {}
        for path, record in tree.items():
            if any(
                record[n] != root[n]
                for n in (
                    "contact_layer",
                    "interaction_type",
                    "source_artifact_role",
                    "source_artifact_path",
                )
            ):
                raise DatasetReleaseCSVError(
                    "Contact definition identity/evidence disagrees"
                )
            if path == "$":
                continue
            parent, child = path.rsplit("/", 1)
            if parent not in tree or tree[parent]["parameter_kind"] not in (
                "object",
                "array",
            ):
                raise DatasetReleaseCSVError(
                    "Contact parameter must have a container parent"
                )
            children.setdefault(parent, []).append(child)
        for parent, names in children.items():
            if tree[parent]["parameter_kind"] == "array" and set(names) != {
                str(i) for i in range(len(names))
            }:
                raise DatasetReleaseCSVError("Contact array indexes must be contiguous")


@dataclass(frozen=True)
class DatasetReleaseTable:
    """Immutable scalar rows, normalized and sorted under the frozen descriptor.

    Empty tables are valid at this low level. Release builders enforce their
    stronger populations separately. No filesystem access occurs here.
    """

    spec: PublicationTableSpec
    rows: tuple[PublicationRow, ...]

    def __post_init__(self) -> None:
        if type(
            self.spec
        ) is not PublicationTableSpec or self.spec != publication_table_spec(
            self.spec.table_id
        ):
            raise DatasetReleaseCSVError("Table must use the frozen Stage 33.A schema")
        if type(self.rows) is not tuple:
            raise DatasetReleaseCSVError("Rows must be an immutable tuple")
        names = tuple(c.name for c in self.spec.columns)
        normalized = []
        keys = set()
        for row in self.rows:
            if type(row) is not tuple or len(row) != len(names):
                raise DatasetReleaseCSVError("Row must have the exact column count")
            raw = dict(zip(names, row, strict=True))
            values = tuple(
                (
                    _scalar(
                        value,
                        column,
                        empty=self.table_id == "contact_definitions"
                        and column.name == "string_value"
                        and (raw["parameter_kind"] == "string"),
                    )
                    for column, value in zip(self.spec.columns, row, strict=True)
                )
            )
            record = dict(zip(names, values, strict=True))
            if self.table_id == "contact_definitions":
                _contact_scalar(record)
            key = tuple(record[n] for n in self.spec.primary_key)
            if key in keys:
                raise DatasetReleaseCSVError(f"Duplicate {self.table_id} primary key")
            keys.add(key)
            normalized.append(values)
        order = (
            (*REPLICA_KEY, "window_index", "window_id")
            if self.table_id == "time_windows"
            else self.spec.primary_key
        )
        indexes = tuple(names.index(n) for n in order)
        object.__setattr__(
            self,
            "rows",
            tuple(sorted(normalized, key=lambda r: tuple(r[i] for i in indexes))),
        )
        if self.table_id == "contact_definitions":
            _contact_trees(self.records())

    @property
    def table_id(self) -> str:
        return self.spec.table_id

    @property
    def relative_path(self) -> str:
        return self.spec.relative_path

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def schema_identity(self) -> str:
        return DATASET_RELEASE_CONTRACT_SCHEMA_VERSION

    def records(self) -> tuple[dict[str, PublicationScalar], ...]:
        """Independent dictionaries for audit/projection; stored rows stay immutable."""
        names = tuple(c.name for c in self.spec.columns)
        return tuple(dict(zip(names, r, strict=True)) for r in self.rows)

    def to_dict(self) -> dict[str, object]:
        """Deterministic audit view; numeric values remain exact Decimal scalars."""
        return dict(
            table_id=self.table_id,
            relative_path=self.relative_path,
            schema_identity=self.schema_identity,
            row_count=self.row_count,
            schema=self.spec.to_dict(),
            rows=list(self.records()),
        )


def build_publication_table(
    table_id: str, records: Iterable[Mapping[str, object]]
) -> DatasetReleaseTable:
    if table_id == "metrics":
        raise DatasetReleaseCSVError(
            "Metric projection requires exact upstream source authority; "
            "use the explicitly bound publication_authority adapter"
        )
    return _logical_publication_table(table_id, records)


def _logical_publication_table(
    table_id: str, records: Iterable[Mapping[str, object]]
) -> DatasetReleaseTable:
    spec = publication_table_spec(table_id)
    names = tuple(c.name for c in spec.columns)
    rows = []
    for record in records:
        if set(record) != set(names):
            raise DatasetReleaseCSVError("Record fields must equal the frozen schema")
        rows.append(tuple(record[n] for n in names))
    return DatasetReleaseTable(spec, cast(tuple[PublicationRow, ...], tuple(rows)))


def publication_csv_bytes(table: DatasetReleaseTable) -> bytes:
    if type(table) is not DatasetReleaseTable:
        raise DatasetReleaseCSVError("Expected a publication table")
    validated = DatasetReleaseTable(table.spec, table.rows)
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, delimiter=",", lineterminator="\n")
    writer.writerow(c.name for c in validated.spec.columns)
    for row in validated.rows:
        writer.writerow(
            ""
            if v is None
            else ("true" if v else "false")
            if type(v) is bool
            else str(v)
            for v in row
        )
    return stream.getvalue().encode("utf-8")


def _bound_path(table_id: str, path: str | Path) -> Path:
    expected = PurePosixPath(publication_table_spec(table_id).relative_path).parts
    target = Path(path)
    if ".." in target.parts or target.parts[-len(expected) :] != expected:
        raise DatasetReleaseCSVError("Path must end with the exact publication path")
    return target


def write_publication_csv(
    table: DatasetReleaseTable, path: str | Path, *, overwrite: bool = False
) -> Path:
    """Atomically write just the requested artifact using repository conventions."""
    target = _bound_path(table.table_id, path)
    result = write_atomic_text(
        publication_csv_bytes(table).decode("utf-8"), target, overwrite=overwrite
    )
    if not result.passed:
        raise DatasetReleaseCSVError(result.error)
    return target


def _decode(cell: str, column: PublicationColumnSpec, *, empty: bool) -> object:
    if cell == "" and column.nullable and (not empty):
        return None
    if column.logical_type == "string":
        return cell
    if column.logical_type == "boolean" and cell in ("true", "false"):
        return cell == "true"
    if column.logical_type == "integer" and re.fullmatch("0|-?[1-9][0-9]*", cell):
        return int(cell)
    if column.logical_type == "number" and re.fullmatch(
        "-?(?:0|[1-9][0-9]*)(?:\\.[0-9]+)?(?:[eE][+-]?[0-9]+)?", cell
    ):
        return Decimal(cell)
    raise DatasetReleaseCSVError(f"Invalid CSV logical type for {column.name}")


def read_publication_csv(table_id: str, path: str | Path) -> DatasetReleaseTable:
    """Reconstruct a normalized model with exact headers, types, and unique PKs."""
    spec = publication_table_spec(table_id)
    try:
        with _bound_path(table_id, path).open(encoding="utf-8", newline="") as stream:
            reader = csv.reader(stream, delimiter=",", strict=True)
            names = tuple(c.name for c in spec.columns)
            if tuple(next(reader, ())) != names:
                raise DatasetReleaseCSVError("CSV header must equal the frozen schema")
            records = []
            for cells in reader:
                if len(cells) != len(names):
                    raise DatasetReleaseCSVError("CSV row has the wrong column count")
                raw = dict(zip(names, cells, strict=True))
                records.append(
                    {
                        c.name: _decode(
                            v,
                            c,
                            empty=table_id == "contact_definitions"
                            and c.name == "string_value"
                            and (raw["parameter_kind"] == "string"),
                        )
                        for c, v in zip(spec.columns, cells, strict=True)
                    }
                )
        return _logical_publication_table(table_id, records)
    except (OSError, UnicodeError, csv.Error, ArithmeticError) as exc:
        raise DatasetReleaseCSVError("Invalid or unreadable publication CSV") from exc


# Selected pinned dataset_release_canonical logical contracts only.


class DatasetReleaseCanonicalError(ValueError):
    """Missing complete-system authority or invalid annotation selection."""


def build_dataset_release_nodes() -> DatasetReleaseTable:
    """Use only the accepted packaged reference API, never observed residues."""
    reference = load_default_napi2b_canonical_reference()
    return build_publication_table(
        "nodes",
        (
            dict(
                canonical_reference_id=reference.reference_id,
                canonical_reference_sequence_sha256=reference.sequence_sha256,
                canonical_residue_number=r.canonical_residue_number,
                canonical_resname=r.canonical_resname,
            )
            for r in reference.residues()
        ),
    )


def build_dataset_release_residue_annotations(
    metadata: tuple[DatasetSystemBiologicalAnnotations, ...],
    *,
    annotation_publication_system_keys: Iterable[tuple[str, str]],
) -> DatasetReleaseTable:
    selected = tuple(annotation_publication_system_keys)
    if any(
        type(k) is not tuple
        or len(k) != 2
        or any(type(v) is not str or not v.strip() for v in k)
        for k in selected
    ) or len(set(selected)) != len(selected):
        raise DatasetReleaseCanonicalError(
            "Selected system keys must be exact and unique"
        )
    if type(metadata) is not tuple or any(
        type(m) is not DatasetSystemBiologicalAnnotations for m in metadata
    ):
        raise DatasetReleaseCanonicalError("Expected accepted Stage 30 system metadata")
    by_key = {}
    for item in metadata:
        replace(item)
        key = (item.dataset_id, item.system_id)
        if key in by_key:
            raise DatasetReleaseCanonicalError("Duplicate annotation system metadata")
        by_key[key] = item
    if not set(selected) <= by_key.keys():
        raise DatasetReleaseCanonicalError(
            "Selected system lacks complete_for_system metadata"
        )
    reference = load_default_napi2b_canonical_reference()
    rows: list[dict[str, object]] = []
    for key in sorted(selected):
        system = by_key[key]
        variants = {
            "disulfide": {
                s.canonical_residue_number: s for s in system.disulfide_variant_sites
            },
            "cysteine": {
                s.canonical_residue_number: s for s in system.cysteine_variant_sites
            },
        }
        for residue in reference.residues():
            number = residue.canonical_residue_number
            row: dict[str, object] = dict(
                dataset_id=key[0],
                system_id=key[1],
                canonical_reference_id=reference.reference_id,
                annotation_scope=system.annotation_scope,
                **asdict(system.annotation_for_residue(number)),
            )
            for kind, sites in variants.items():
                site = sites.get(number)
                row[f"{kind}_variant_source"] = site.source if site else None
                row[f"{kind}_variant_verifier"] = site.verifier if site else None
            rows.append(row)
    return build_publication_table("residue_annotations", rows)


FIXED_WINDOW_COLUMNS = {
    "protein": (
        "dataset_id",
        "system_id",
        "trajectory_id",
        "variant_id",
        "engine",
        "condition",
        "replica_id",
        "disulfide_state",
        "window_id",
        "window_index",
        "requested_window_start_ns",
        "requested_window_end_ns",
        "right_endpoint_inclusive",
        "effective_window_start_ns",
        "effective_window_end_ns",
        "requested_sample_count",
        "resolved_frame_count",
        "missing_sample_count",
        "coverage_fraction",
        "source_residue_index",
        "source_chain_id",
        "source_resid",
        "source_resname",
        "source_canonical_residue_number",
        "source_canonical_resname",
        "target_residue_index",
        "target_chain_id",
        "target_resid",
        "target_resname",
        "target_canonical_residue_number",
        "target_canonical_resname",
        "edge_type",
        "n_contact_frames",
        "occupancy",
        "n_contact_episodes",
        "mean_episode_length_ns",
        "max_episode_length_ns",
        "edge_weight",
    ),
    "lipid": (
        "dataset_id",
        "system_id",
        "trajectory_id",
        "variant_id",
        "engine",
        "condition",
        "replica_id",
        "disulfide_state",
        "window_id",
        "window_index",
        "requested_window_start_ns",
        "requested_window_end_ns",
        "right_endpoint_inclusive",
        "effective_window_start_ns",
        "effective_window_end_ns",
        "requested_sample_count",
        "resolved_frame_count",
        "missing_sample_count",
        "coverage_fraction",
        "protein_residue_index",
        "protein_chain_id",
        "protein_resid",
        "protein_resname",
        "canonical_residue_number",
        "canonical_resname",
        "lipid_partner_id",
        "lipid_partner_name",
        "lipid_component_residue_indexes",
        "n_contact_frames",
        "occupancy",
        "n_contact_episodes",
        "mean_episode_length_ns",
        "max_episode_length_ns",
        "distance_mean_A",
        "distance_min_A",
    ),
    "glycan": (
        "dataset_id",
        "system_id",
        "trajectory_id",
        "variant_id",
        "engine",
        "condition",
        "replica_id",
        "disulfide_state",
        "window_id",
        "window_index",
        "requested_window_start_ns",
        "requested_window_end_ns",
        "right_endpoint_inclusive",
        "effective_window_start_ns",
        "effective_window_end_ns",
        "requested_sample_count",
        "resolved_frame_count",
        "missing_sample_count",
        "coverage_fraction",
        "protein_residue_index",
        "protein_chain_id",
        "protein_resid",
        "protein_resname",
        "canonical_residue_number",
        "canonical_resname",
        "glycan_partner_id",
        "glycan_partner_name",
        "glycan_component_residue_indexes",
        "carrier_residue_index",
        "first_sugar_residue_index",
        "linkage_evidence",
        "carrier_link_atom_index",
        "first_sugar_link_atom_index",
        "n_contact_frames",
        "occupancy",
        "n_contact_episodes",
        "mean_episode_length_ns",
        "max_episode_length_ns",
        "distance_mean_A",
        "distance_min_A",
    ),
}


def napi2b_qc_policy(
    *,
    required_check_ids: tuple[str, ...],
    required_evidence_roles: tuple[str, ...],
    review_cohort_keys: tuple[str, ...],
) -> QCPolicy:
    """Explicit fixed policy selection; generic evaluation has no numeric defaults."""
    return QCPolicy(
        schema_version="mania.qc_policy.v1",
        kind="mania_qc_policy",
        policy_id="napi2b.dataset.v1",
        required_check_ids=required_check_ids,
        required_evidence_roles=required_evidence_roles,
        coverage_fraction=0.95
        if "production_frame_coverage" in required_check_ids
        else None,
        empty_window_fraction=0.01
        if "protein_edge_empty_window_fraction" in required_check_ids
        else None,
        mad_multiplier=3.0
        if any(c.startswith("mad:") for c in required_check_ids)
        else None,
        review_cohort_keys=review_cohort_keys,
        decision_contract="fail_excluded_review_pending_external_resolution",
    )


@dataclass(frozen=True)
class FixedWindowTable:
    generic: ReferenceWindowTable
    fixed_mapping: CanonicalResidueMappingTable
    annotations: DatasetSystemBiologicalAnnotations | None
    temporal: PreprocessingConditionTemporalExecution

    def __post_init__(self) -> None:
        self.generic.__post_init__()
        self.temporal.__post_init__()
        old = self.temporal.dataset_spec.identity
        ident = self.generic.mapping.identity
        if (
            old.dataset_id,
            old.system_id,
            old.trajectory_id,
            old.replica_id,
            old.engine,
            old.condition,
            old.variant_id,
            old.disulfide_state,
        ) != (
            ident.project,
            ident.system_id,
            ident.trajectory_id,
            ident.replica_id,
            ident.engine,
            ident.condition,
            ident.variant_id,
            ident.disulfide_state,
        ):
            raise ValueError("Fixed temporal/source identity differs")
        for row in self.generic.rows:
            window_matches = [
                w
                for w in self.temporal.window_plan.windows
                if (w.window_id, w.window_index) == (row.window_id, row.window_index)
            ]
            if len(window_matches) != 1 or (
                window_matches[0].requested_start_ns,
                window_matches[0].requested_end_ns,
                window_matches[0].right_endpoint_inclusive,
            ) != (
                row.requested_window_start_ns,
                row.requested_window_end_ns,
                row.right_endpoint_inclusive,
            ):
                raise ValueError("Fixed table physical window authority differs")
        reference = load_default_napi2b_canonical_reference()
        validate_canonical_residue_mapping_table(
            self.fixed_mapping, reference=reference
        )
        chains = self.generic.reference.reference.chains
        if (
            len(chains) != 1
            or chains[0].sequence != reference.sequence
            or chains[0].sequence_sha256 != reference.sequence_sha256
        ):
            raise ValueError(
                "Generic roster is not the separately pinned fixed sequence"
            )
        if [r.resname for r in self.generic.reference.records] != [
            r.canonical_resname for r in reference.residues()
        ]:
            raise ValueError("Fixed residue chemistry differs")
        for r in self.generic.mapping.records:
            s = r.source
            namespace = s.segment_id if s.namespace_kind == "segment" else s.chain_id
            matches = [
                m
                for m in self.fixed_mapping.mappings
                if m.source_key == (s.engine, namespace, s.resid, s.resname)
            ]
            if len(matches) != 1 or matches[0].mapping_status != r.mapping_status:
                raise ValueError("Generic/fixed source mapping bindings differ")
            if r.mapping_status == "mapped" and (
                matches[0].canonical_residue_number,
                matches[0].canonical_resname,
            ) != (r.reference_position, r.reference_resname):
                raise ValueError("Generic/fixed canonical mapping target differs")
        if self.annotations is not None:
            self.annotations.__post_init__()
            i = self.generic.mapping.identity
            if (self.annotations.dataset_id, self.annotations.system_id) != (
                i.project,
                i.system_id,
            ):
                raise ValueError("Fixed annotation system differs")

    @property
    def schema_version(self) -> str:
        name = {
            "protein": "protein_edges",
            "lipid": "protein_lipid_contacts",
            "glycan": "protein_glycan_contacts",
        }[self.generic.layer]
        prefix = (
            "mania.canonical_annotated_"
            if self.annotations is not None
            else "mania.canonical_"
        )
        version = (
            "v0.2"
            if any(
                self.temporal.window_plan.boundary_profile != LEGACY_BOUNDARY_PROFILE
                for r in self.generic.rows
            )
            else "v0.1"
        )
        return prefix + name + "_by_window." + version

    @property
    def columns(self) -> tuple[str, ...]:
        columns = FIXED_WINDOW_COLUMNS[self.generic.layer]
        if self.annotations is not None:
            annotation_names = tuple(
                DatasetSystemBiologicalAnnotations.annotation_for_residue(
                    self.annotations, 1
                ).__dataclass_fields__
            )
            names = tuple(
                n
                for n in annotation_names
                if n not in ("canonical_residue_number", "canonical_resname")
            )
            columns += (
                tuple(
                    p + n
                    for p in ("source_", "target_")
                    if self.generic.layer == "protein"
                    for n in names
                )
                if self.generic.layer == "protein"
                else names
            )
        if any(
            self.temporal.window_plan.boundary_profile != LEGACY_BOUNDARY_PROFILE
            for r in self.generic.rows
        ):
            columns += ("boundary_profile",)
        return columns

    def records(self) -> tuple[Mapping[str, Any], ...]:
        self.__post_init__()
        rows = []
        for source in self.generic.rows:
            d = {f.name: getattr(source, f.name) for f in fields(source) if f.init}
            d["boundary_profile"] = self.temporal.window_plan.boundary_profile
            for side, prefix in (
                (("i", "source_"), ("j", "target_"))
                if self.generic.layer == "protein"
                else (("i", ""),)
            ):
                number = d["reference_position_" + side]
                d[prefix + "canonical_residue_number"] = number
                d[prefix + "canonical_resname"] = d["reference_resname_" + side]
                if self.annotations is not None:
                    a = asdict(self.annotations.annotation_for_residue(number))
                    d.update(
                        {
                            prefix + k: v
                            for k, v in a.items()
                            if k
                            not in ("canonical_residue_number", "canonical_resname")
                        }
                    )
            rows.append({n: d[n] for n in self.columns})
        if self.generic.layer == "protein":
            rows.sort(
                key=lambda r: (
                    r["dataset_id"],
                    r["system_id"],
                    r["trajectory_id"],
                    r["replica_id"],
                    r["window_index"],
                    r["edge_type"],
                    r["source_canonical_residue_number"],
                    r["target_canonical_residue_number"],
                )
            )
        return tuple(MappingProxyType(r) for r in rows)


def fixed_window_csv_bytes(table: FixedWindowTable) -> bytes:
    table.__post_init__()
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(table.columns)
    for r in table.records():
        writer.writerow(
            ";".join(str(i) for i in r[n])
            if n.endswith("component_residue_indexes")
            else _serialize(r[n])
            for n in table.columns
        )
    return stream.getvalue().encode()


def write_fixed_window_csv(
    table: FixedWindowTable, path: Path, *, overwrite: bool = False
) -> None:
    result = write_atomic_text(
        fixed_window_csv_bytes(table).decode(), path, overwrite=overwrite
    )
    if not result.passed:
        raise ValueError(result.error)


def read_fixed_window_csv(
    path: Path, *, expected: FixedWindowTable
) -> FixedWindowTable:
    """Read back against explicit authoritative generic source and fixed mappings."""
    if path.read_bytes() != fixed_window_csv_bytes(expected):
        raise ValueError(
            "Fixed CSV columns/values/order/bindings differ from supplied source"
        )
    return expected
