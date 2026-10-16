"""Offline fixed Dataset-v1 controls, 20-artifact IO and complete reconstruction."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal, TypeVar

from pydantic import BeforeValidator, Field, model_validator

from mania.artifact_inventory import ArtifactInventory, ArtifactInventoryEntry
from mania.artifact_inventory_io import (
    read_artifact_inventory,
    write_artifact_inventory,
)
from mania.canonical_reference import InputIdentity
from mania.input_binding import FileEvidence, member, portable_path
from mania.preprocessing.molecular_partner_metadata_io import (
    SpecializedArtifactWriteResult,
    exact_fields,
    json_array,
    read_strict_json,
    write_atomic_text,
)
from mania.preprocessing.temporal_policy import (
    INCLUSIVE_BOUNDARY_PROFILE,
    LEGACY_BOUNDARY_PROFILE,
    BoundaryProfile,
    require_boundary_profile,
)
from mania.run_config import Digest, RunModel, Text, _ordered
from mania.run_provenance import PortableArtifactReference, RunProvenance
from mania.run_provenance_io import read_run_provenance
from mania.scientific_qualification import SCIENCE_WARNING, NeverAuthoritative
from mania_napi2b.publication import (
    DatasetReleaseMetadataTables,
    DatasetReleaseScientificTables,
    ReplicaKey,
    SystemKey,
    build_dataset_release_contact_definition,
    build_dataset_release_software_versions,
    validate_complete_tables,
)
from mania_napi2b.publication_authority import AuthoritativePublicationMetric
from mania_napi2b.tables import (
    DATASET_RELEASE_CANONICAL_REFERENCE_ID,
    DATASET_RELEASE_CANONICAL_REFERENCE_SHA256,
    DATASET_RELEASE_VERSION,
    METADATA_TABLE_IDS,
    PRODUCTION_EXECUTION_DAG,
    PUBLICATION_ARTIFACT_REGISTRY,
    PUBLICATION_TABLE_SPECS,
    DatasetReleaseTable,
    publication_csv_bytes,
    read_publication_csv,
    require_portable_publication_path,
    write_publication_csv,
)

if TYPE_CHECKING:
    from mania_napi2b.publication_authority import DatasetSources

"""Stage 33 release controls and publication manifest; no scientific execution."""

DATASET_RELEASE_EXPORT_MANIFEST_SCHEMA_VERSION = (
    "mania.dataset_release_export_manifest.v0.1"
)

DATASET_RELEASE_EXPORT_MANIFEST_KIND = "mania_dataset_release_export_manifest"

DATASET_RELEASE_MANIFEST_SCHEMA_VERSION = "mania.dataset_release_manifest.v0.1"

DATASET_RELEASE_MANIFEST_KIND = "mania_dataset_release_manifest"

EXPORT_MANIFEST_FILENAME = "dataset_release_export_manifest.json"

RELEASE_MANIFEST_PATH = "release/dataset_manifest.json"

RELEASE_INVENTORY_PATH = "release/artifact_inventory.json"

RELEASE_PROVENANCE_PATH = "release/provenance.json"


def require_text(value: object) -> None:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError("Expected nonempty stripped text")


def require_path(value: str) -> None:
    require_portable_publication_path(value)
    if "$" in value or "%" in value:
        raise ValueError("Environment substitutions are forbidden in release paths")


def require_keys(values: tuple[Any, ...], size: int) -> None:
    if type(values) is not tuple:
        raise ValueError("Expected immutable publication selections")
    for key in values:
        if type(key) is not tuple or len(key) != size:
            raise ValueError("Expected exact full publication key")
        for value in key:
            require_text(value)
    if len(set(values)) != len(values):
        raise ValueError("Duplicate publication selection")


def require_models(values: tuple[Any, ...], model: type) -> None:
    if type(values) is not tuple or any(type(v) is not model for v in values):
        raise ValueError("Expected immutable exact release bindings")
    for value in values:
        replace(value)
    if len(set(values)) != len(values):
        raise ValueError("Duplicate release binding")


@dataclass(frozen=True)
class ReleaseInputBinding:
    artifact_id: str
    path: str

    def __post_init__(self) -> None:
        require_text(self.artifact_id)
        require_path(self.path)


@dataclass(frozen=True)
class ReleaseUpstreamRun:
    provenance_path: str
    inventory_path: str
    input_bindings: tuple[ReleaseInputBinding, ...]

    def __post_init__(self) -> None:
        require_path(self.provenance_path)
        require_path(self.inventory_path)
        require_models(self.input_bindings, ReleaseInputBinding)
        if len({b.artifact_id for b in self.input_bindings}) != len(
            self.input_bindings
        ):
            raise ValueError("Duplicate upstream input artifact ID")
        object.__setattr__(
            self,
            "input_bindings",
            tuple(sorted(self.input_bindings, key=lambda b: b.artifact_id)),
        )


@dataclass(frozen=True)
class ReleaseCanonicalBinding:
    family: str
    path: str
    replica_keys: tuple[ReplicaKey, ...]

    def __post_init__(self) -> None:
        if type(self.family) is not str or self.family not in (
            "protein",
            "lipid",
            "glycan",
        ):
            raise ValueError("Unknown canonical input family")
        require_path(self.path)
        require_keys(self.replica_keys, 4)
        if not self.replica_keys:
            raise ValueError("Canonical artifacts require explicit replica coverage")
        object.__setattr__(self, "replica_keys", tuple(sorted(self.replica_keys)))


@dataclass(frozen=True)
class ReleaseAnnotationBinding:
    dataset_id: str
    system_id: str
    path: str

    def __post_init__(self) -> None:
        require_text(self.dataset_id)
        require_text(self.system_id)
        require_path(self.path)


@dataclass(frozen=True)
class DatasetReleaseExportManifest:
    dataset_id: str
    stage32_run: ReleaseUpstreamRun
    stage31_run: ReleaseUpstreamRun
    decision_set_path: str
    qc_summary_path: str
    qc_derived_manifest_path: str
    aggregation_manifest_used_path: str
    protein_aggregate_path: str | None
    lipid_aggregate_path: str | None
    glycan_aggregate_path: str | None
    canonical_bindings: tuple[ReleaseCanonicalBinding, ...]
    temporal_evidence_paths: tuple[str, ...]
    annotation_bindings: tuple[ReleaseAnnotationBinding, ...]
    publication_inputs_path: str
    scientific_release_replica_keys: tuple[ReplicaKey, ...]
    annotation_publication_system_keys: tuple[SystemKey, ...]
    schema_version: str = field(
        init=False,
        default=DATASET_RELEASE_EXPORT_MANIFEST_SCHEMA_VERSION,
    )
    kind: str = field(init=False, default=DATASET_RELEASE_EXPORT_MANIFEST_KIND)

    def __post_init__(self) -> None:
        require_text(self.dataset_id)
        for item in fields(self):
            if not item.init and (
                type(getattr(self, item.name)) is not type(item.default)
                or getattr(self, item.name) != item.default
            ):
                raise ValueError("Incorrect fixed release control contract")
        for name in ("stage32_run", "stage31_run"):
            value = getattr(self, name)
            if type(value) is not ReleaseUpstreamRun:
                raise ValueError("Expected explicit upstream run evidence")
            replace(value)
        for item in fields(self):
            if item.name.endswith("_path"):
                value = getattr(self, item.name)
                if value is not None:
                    require_path(value)
                elif "aggregate" not in item.name:
                    raise ValueError("Required release authority path is missing")
        require_models(self.canonical_bindings, ReleaseCanonicalBinding)
        require_models(self.annotation_bindings, ReleaseAnnotationBinding)
        if type(self.temporal_evidence_paths) is not tuple:
            raise ValueError("Expected explicit temporal path tuple")
        for path in self.temporal_evidence_paths:
            require_path(path)
        if len(set(self.temporal_evidence_paths)) != len(self.temporal_evidence_paths):
            raise ValueError("Duplicate temporal path")
        require_keys(self.scientific_release_replica_keys, 4)
        require_keys(self.annotation_publication_system_keys, 2)
        if any(
            key[0] != self.dataset_id
            for key in (
                *self.scientific_release_replica_keys,
                *self.annotation_publication_system_keys,
                *(k for b in self.canonical_bindings for k in b.replica_keys),
            )
        ) or any(b.dataset_id != self.dataset_id for b in self.annotation_bindings):
            raise ValueError("Release bindings must belong to the declared Dataset")
        if len({b.path for b in self.canonical_bindings}) != len(
            self.canonical_bindings
        ):
            raise ValueError("Canonical paths must be unique")
        if len({(b.dataset_id, b.system_id) for b in self.annotation_bindings}) != len(
            self.annotation_bindings
        ):
            raise ValueError("Annotation system bindings must be unique")
        for name in (
            "scientific_release_replica_keys",
            "annotation_publication_system_keys",
            "temporal_evidence_paths",
        ):
            object.__setattr__(self, name, tuple(sorted(getattr(self, name))))
        object.__setattr__(
            self,
            "canonical_bindings",
            tuple(
                sorted(
                    self.canonical_bindings,
                    key=lambda b: (b.family, b.path),
                )
            ),
        )
        object.__setattr__(
            self,
            "annotation_bindings",
            tuple(
                sorted(
                    self.annotation_bindings,
                    key=lambda b: (b.dataset_id, b.system_id),
                )
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class DatasetReleaseManifest:
    dataset_id: str
    authoritative_stage32_decision_source: str
    authoritative_qc_derived_stage31_manifest_source: str
    authoritative_stage31_aggregation_source: str
    boundary_profile: BoundaryProfile = LEGACY_BOUNDARY_PROFILE
    schema_version: str = field(
        init=False, default=DATASET_RELEASE_MANIFEST_SCHEMA_VERSION
    )
    kind: str = field(init=False, default=DATASET_RELEASE_MANIFEST_KIND)
    release_version: str = field(init=False, default=DATASET_RELEASE_VERSION)
    canonical_reference_id: str = field(
        init=False,
        default=DATASET_RELEASE_CANONICAL_REFERENCE_ID,
    )
    canonical_reference_sequence_sha256: str = field(
        init=False,
        default=DATASET_RELEASE_CANONICAL_REFERENCE_SHA256,
    )
    production_execution_dag: tuple[str, ...] = field(
        init=False,
        default=PRODUCTION_EXECUTION_DAG,
    )
    release_table_count: int = field(init=False, default=17)
    release_json_count: int = field(init=False, default=3)
    upstream_reference_base: str = field(
        init=False,
        default="export_control_manifest_parent",
    )
    export_control_manifest_source: str = field(
        init=False,
        default=f"inputs/{EXPORT_MANIFEST_FILENAME}",
    )

    def __post_init__(self) -> None:
        require_boundary_profile(self.boundary_profile)
        version = (
            DATASET_RELEASE_MANIFEST_SCHEMA_VERSION
            if self.boundary_profile == LEGACY_BOUNDARY_PROFILE
            else "mania.dataset_release_manifest.v0.2"
        )
        object.__setattr__(self, "schema_version", version)
        require_text(self.dataset_id)
        for item in fields(self):
            value = getattr(self, item.name)
            if item.name.endswith("_source"):
                require_path(value)
            if not item.init and (
                type(value) is not type(item.default)
                or value != (version if item.name == "schema_version" else item.default)
            ):
                raise ValueError("Release manifest frozen contract mismatch")

    def to_dict(self) -> dict[str, object]:
        values = asdict(self)
        if self.boundary_profile == LEGACY_BOUNDARY_PROFILE:
            values.pop("boundary_profile")
        return {
            **values,
            "publication_artifacts": [
                a.to_dict() for a in PUBLICATION_ARTIFACT_REGISTRY.artifacts
            ],
        }


"""Strict deterministic release JSON, using accepted atomic UTF-8 persistence."""

_Model = TypeVar("_Model", DatasetReleaseExportManifest, DatasetReleaseManifest)


def release_json_text(payload: object) -> str:
    return (
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    )


def model_fields(data: Any, model: type) -> dict[str, Any]:
    values = exact_fields(data, {f.name for f in fields(model)})
    for item in fields(model):
        if not item.init:
            expected = json.loads(release_json_text(item.default))
            value = values.pop(item.name)
            if type(value) is not type(expected) or value != expected:
                raise ValueError("Incorrect fixed release contract field")
    return values


def _keys(value: Any) -> tuple[tuple[Any, ...], ...]:
    return tuple(tuple(json_array(key)) for key in json_array(value))


def _run(data: Any) -> ReleaseUpstreamRun:
    values = model_fields(data, ReleaseUpstreamRun)
    values["input_bindings"] = tuple(
        ReleaseInputBinding(**model_fields(v, ReleaseInputBinding))
        for v in json_array(values["input_bindings"])
    )
    return ReleaseUpstreamRun(**values)


def read_dataset_release_export_manifest(
    path: str | Path,
) -> DatasetReleaseExportManifest:
    try:
        values = model_fields(read_strict_json(path), DatasetReleaseExportManifest)
        for name in ("stage32_run", "stage31_run"):
            values[name] = _run(values[name])
        canonical = []
        for value in json_array(values["canonical_bindings"]):
            binding = model_fields(value, ReleaseCanonicalBinding)
            binding["replica_keys"] = _keys(binding["replica_keys"])
            canonical.append(ReleaseCanonicalBinding(**binding))
        values["canonical_bindings"] = tuple(canonical)
        values["annotation_bindings"] = tuple(
            ReleaseAnnotationBinding(**model_fields(v, ReleaseAnnotationBinding))
            for v in json_array(values["annotation_bindings"])
        )
        values["temporal_evidence_paths"] = tuple(
            json_array(values["temporal_evidence_paths"])
        )
        for name in (
            "scientific_release_replica_keys",
            "annotation_publication_system_keys",
        ):
            values[name] = _keys(values[name])
        return DatasetReleaseExportManifest(**values)
    except (OSError, ValueError, TypeError, OverflowError, RecursionError):
        raise ValueError(
            "Invalid or unreadable release export control manifest"
        ) from None


def read_dataset_release_manifest(path: str | Path) -> DatasetReleaseManifest:
    try:
        data = read_strict_json(path)
        if type(data) is not dict:
            raise ValueError("Expected exact release manifest object")
        if data.get("schema_version") == "mania.dataset_release_manifest.v0.2":
            if data.get("boundary_profile") != INCLUSIVE_BOUNDARY_PROFILE:
                raise ValueError("Invalid release boundary profile")
            data["schema_version"] = DatasetReleaseManifest.__dataclass_fields__[
                "schema_version"
            ].default
        else:
            if "boundary_profile" in data:
                raise ValueError("Legacy release must not declare a boundary profile")
            data["boundary_profile"] = LEGACY_BOUNDARY_PROFILE
        data = exact_fields(
            data,
            {
                *(f.name for f in fields(DatasetReleaseManifest)),
                "publication_artifacts",
            },
        )
        registry = data.pop("publication_artifacts")
        model = DatasetReleaseManifest(**model_fields(data, DatasetReleaseManifest))
        # JSON representations also distinguish true/1 and exact nested field sets.
        if release_json_text(registry) != release_json_text(
            model.to_dict()["publication_artifacts"]
        ):
            raise ValueError("Incorrect frozen publication artifact registry")
        return model
    except (OSError, ValueError, TypeError, OverflowError, RecursionError):
        raise ValueError("Invalid or unreadable publication dataset manifest") from None


def _write(
    model: _Model, path: str | Path, overwrite: bool
) -> SpecializedArtifactWriteResult:
    model.__post_init__()
    if type(overwrite) is not bool:
        raise ValueError("overwrite must be boolean")
    return write_atomic_text(
        release_json_text(model.to_dict()),
        Path(path),
        overwrite=overwrite,
    )


def write_dataset_release_export_manifest(
    model: DatasetReleaseExportManifest,
    path: str | Path,
    *,
    overwrite: bool = False,
) -> SpecializedArtifactWriteResult:
    if type(model) is not DatasetReleaseExportManifest:
        raise ValueError("Expected exact release export control manifest")
    return _write(model, path, overwrite)


def write_dataset_release_manifest(
    model: DatasetReleaseManifest,
    path: str | Path,
    *,
    overwrite: bool = False,
) -> SpecializedArtifactWriteResult:
    if type(model) is not DatasetReleaseManifest:
        raise ValueError("Expected exact publication dataset manifest")
    return _write(model, path, overwrite)


"""One narrow control for supplied contact, software and metric publication data."""

PUBLICATION_INPUT_SCHEMA_VERSION = "mania.dataset_release_publication_input.v0.1"

PUBLICATION_INPUT_KIND = "mania_dataset_release_publication_input"


@dataclass(frozen=True)
class DatasetReleasePublicationInputs:
    contact_definitions: tuple[DatasetReleaseTable, ...]
    software_versions: DatasetReleaseTable
    metrics: tuple[AuthoritativePublicationMetric, ...]
    metric_source_value_fields: tuple[str, ...]


def publication_inputs_from_payload(data: Any) -> DatasetReleasePublicationInputs:
    data = exact_fields(
        data,
        {
            "schema_version",
            "kind",
            "contact_definitions",
            "software_versions",
            "metrics",
        },
    )
    if data["schema_version"] != PUBLICATION_INPUT_SCHEMA_VERSION or (
        data["kind"] != PUBLICATION_INPUT_KIND
    ):
        raise ValueError("Incorrect publication input contract")
    contacts = []
    for definition in json_array(data["contact_definitions"]):
        values = exact_fields(
            definition,
            {
                "replica_key",
                "contact_definition_id",
                "contact_layer",
                "interaction_type",
                "parameters",
                "source_artifact_role",
                "source_artifact_path",
                "units",
            },
        )
        values["replica_key"] = tuple(json_array(values["replica_key"]))
        if type(values["units"]) is not dict or any(
            type(k) is not str or type(v) is not str or not v
            for k, v in values["units"].items()
        ):
            raise ValueError("Explicit contact units must be a text mapping")
        contacts.append(build_dataset_release_contact_definition(**values))
    software = build_dataset_release_software_versions(
        json_array(data["software_versions"])
    )
    metrics = []
    source_fields = []
    for row in json_array(data["metrics"]):
        values = exact_fields(
            row,
            {f.name for f in fields(AuthoritativePublicationMetric)}
            | {"source_value_field"},
        )
        source_field = values.pop("source_value_field")
        require_text(source_field)
        source_fields.append(source_field)
        metrics.append(AuthoritativePublicationMetric(**values))
    return DatasetReleasePublicationInputs(
        tuple(contacts), software, tuple(metrics), tuple(source_fields)
    )


def read_dataset_release_publication_inputs(
    path: str | Path,
) -> DatasetReleasePublicationInputs:
    try:
        return publication_inputs_from_payload(read_strict_json(path))
    except (OSError, ValueError, TypeError, OverflowError, RecursionError):
        raise ValueError("Invalid or unreadable explicit publication inputs") from None


def write_dataset_release_publication_inputs(
    payload: dict[str, Any],
    path: str | Path,
    *,
    overwrite: bool = False,
) -> SpecializedArtifactWriteResult:
    publication_inputs_from_payload(payload)
    if type(overwrite) is not bool:
        raise ValueError("overwrite must be boolean")
    return write_atomic_text(
        release_json_text(payload), Path(path), overwrite=overwrite
    )


@dataclass(frozen=True)
class ReconstructedDataset:
    manifest: DatasetReleaseManifest
    metadata: DatasetReleaseMetadataTables
    science: DatasetReleaseScientificTables
    inventory: ArtifactInventory
    provenance: RunProvenance

    @property
    def tables(self) -> tuple[DatasetReleaseTable, ...]:
        return (*self.metadata.tables, *self.science.tables)


def _artifact_descriptor(root: Path, path: str, role: str) -> FileEvidence:
    target = member(root, path)
    return FileEvidence(
        role=role,
        path=path,
        size_bytes=target.stat().st_size,
        sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
    )


def _reject_existing_outputs(root: Path) -> None:
    for artifact in PUBLICATION_ARTIFACT_REGISTRY.artifacts:
        path = root / artifact.relative_path
        if path.exists() or path.is_symlink():
            raise FileExistsError(path)
        parent = path.parent
        while parent != root:
            if parent.is_symlink():
                raise ValueError("Output parent cannot be a symlink")
            parent = parent.parent


def write_dataset(
    sources: DatasetSources,
    destination: Path,
    *,
    provenance: RunProvenance,
) -> ReconstructedDataset:
    """Verify complete source authority before the first artifact write.

    All identity/timestamps/reviewer information is supplied. This coordinate-free
    writer serializes completed values; it is not an operational FAIR dispatcher.
    """
    control, metadata, science = sources.validate()
    validate_complete_tables(metadata, science)
    destination = destination.absolute()
    destination.mkdir(parents=True, exist_ok=True)
    _reject_existing_outputs(destination)
    if provenance.status != "completed" or provenance.workflow != "dataset_release":
        raise ValueError("Explicit completed Dataset serialization provenance required")
    manifest = DatasetReleaseManifest(
        control.dataset_id,
        control.decision_set_path,
        control.qc_derived_manifest_path,
        control.stage31_run.provenance_path,
        boundary_profile=metadata.boundary_profile,
    )
    for table in (*metadata.tables, *science.tables):
        path = destination / table.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        write_publication_csv(table, path)
    path = destination / RELEASE_MANIFEST_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    if not write_dataset_release_manifest(manifest, path).passed:
        raise ValueError("Dataset manifest write failed")
    control_path = destination / manifest.export_control_manifest_source
    control_path.parent.mkdir(parents=True, exist_ok=True)
    if not write_dataset_release_export_manifest(control, control_path).passed:
        raise ValueError("Retained release control write failed")
    refs = tuple(
        PortableArtifactReference(t.table_id, t.relative_path)
        for t in (*metadata.tables, *science.tables)
    ) + (
        PortableArtifactReference("dataset_manifest", RELEASE_MANIFEST_PATH),
        PortableArtifactReference(
            "export_control", manifest.export_control_manifest_source
        ),
    )
    if provenance.artifact_references != refs:
        raise ValueError(
            "Serialization provenance must bind the exact output/control roster"
        )
    result = write_atomic_text(
        json.dumps(
            provenance.to_dict(),
            indent=2,
            sort_keys=False,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n",
        destination / RELEASE_PROVENANCE_PATH,
        overwrite=False,
    )
    if not result.passed:
        raise ValueError("Release provenance write failed")
    entries = []
    for n, reference in enumerate(
        (*refs, PortableArtifactReference("provenance", RELEASE_PROVENANCE_PATH))
    ):
        descriptor = _artifact_descriptor(destination, reference.path, reference.role)
        entries.append(
            ArtifactInventoryEntry(
                "release-" + str(n),
                "input" if reference.role == "export_control" else "output",
                descriptor.role,
                descriptor.path,
                "csv" if reference.path.endswith(".csv") else "json",
                descriptor.size_bytes,
                descriptor.sha256,
            )
        )
    inventory = ArtifactInventory(
        provenance.run_id,
        provenance.workflow,
        RELEASE_INVENTORY_PATH,
        "sha256",
        tuple(entries),
    )
    if not write_artifact_inventory(inventory, destination).passed:
        raise ValueError("Release inventory write failed")
    return reconstruct_dataset(destination, sources=sources)


def reconstruct_dataset(root: Path, *, sources: DatasetSources) -> ReconstructedDataset:
    """Strict offline read-back plus exact scientific and lineage cross-checks."""
    manifest = read_dataset_release_manifest(member(root, RELEASE_MANIFEST_PATH))
    control = read_dataset_release_export_manifest(
        member(root, manifest.export_control_manifest_source)
    )
    expected_control, expected_metadata, expected_science = sources.validate()
    if control != expected_control:
        raise ValueError("Reconstruction source control differs")
    expected_manifest = DatasetReleaseManifest(
        control.dataset_id,
        control.decision_set_path,
        control.qc_derived_manifest_path,
        control.stage31_run.provenance_path,
        boundary_profile=expected_metadata.boundary_profile,
    )
    if manifest != expected_manifest:
        raise ValueError("Reconstruction source lineage manifest differs")
    tables = {}
    for spec in PUBLICATION_TABLE_SPECS:
        path = member(root, spec.relative_path)
        table = read_publication_csv(spec.table_id, path)
        if path.read_bytes() != publication_csv_bytes(table):
            raise ValueError("Noncanonical fixed CSV bytes/order/number representation")
        tables[spec.table_id] = table
    metadata = DatasetReleaseMetadataTables(
        *(tables[n] for n in METADATA_TABLE_IDS),
        boundary_profile=manifest.boundary_profile,
    )
    science = DatasetReleaseScientificTables(
        *(tables[f.name] for f in fields(DatasetReleaseScientificTables))
    )
    validate_complete_tables(metadata, science)
    if metadata != expected_metadata or science != expected_science:
        raise ValueError(
            "Reconstructed metadata/scientific values differ from source authority"
        )
    inventory = read_artifact_inventory(member(root, RELEASE_INVENTORY_PATH))
    provenance = read_run_provenance(member(root, RELEASE_PROVENANCE_PATH))
    if (
        (
            inventory.run_id,
            inventory.workflow,
            inventory.inventory_path,
            inventory.checksum_mode,
        )
        != (provenance.run_id, "dataset_release", RELEASE_INVENTORY_PATH, "sha256")
        or provenance.status != "completed"
        or provenance.workflow != "dataset_release"
    ):
        raise ValueError("Release inventory/provenance identity differs")
    expected_paths = {spec.relative_path for spec in PUBLICATION_TABLE_SPECS} | {
        RELEASE_MANIFEST_PATH,
        RELEASE_PROVENANCE_PATH,
        manifest.export_control_manifest_source,
    }
    if {e.path for e in inventory.artifacts} != expected_paths:
        raise ValueError("Release inventory complete member roster differs")
    for entry in inventory.artifacts:
        descriptor = _artifact_descriptor(root, entry.path, entry.role)
        if (entry.byte_size, entry.sha256) != (
            descriptor.size_bytes,
            descriptor.sha256,
        ):
            raise ValueError("Reconstruction missing/stale artifact SHA256/size")
    refs = tuple(
        PortableArtifactReference(t.table_id, t.relative_path)
        for t in (*metadata.tables, *science.tables)
    ) + (
        PortableArtifactReference("dataset_manifest", RELEASE_MANIFEST_PATH),
        PortableArtifactReference(
            "export_control", manifest.export_control_manifest_source
        ),
    )
    if provenance.artifact_references != refs:
        raise ValueError("Reconstruction provenance roster differs")
    if (
        len(PUBLICATION_TABLE_SPECS) != 17
        or len(PUBLICATION_ARTIFACT_REGISTRY.artifacts) != 20
    ):
        raise ValueError("Fixed 17CSV+3JSON registry differs")
    return ReconstructedDataset(manifest, metadata, science, inventory, provenance)


# A separate non-authoritative packaging contract. No official Dataset-v1 seal.

PREVIEW_SCHEMA = "mania_napi2b.dataset_exploratory_preview.v1"
PREVIEW_PATH = "preview/preview_manifest.json"


class PreviewTable(RunModel):
    table_id: Text
    path: Annotated[str, BeforeValidator(portable_path)]
    size_bytes: Annotated[int, Field(ge=0)]
    sha256: Digest


class DatasetExploratoryPreview(RunModel):
    schema_version: Literal["mania_napi2b.dataset_exploratory_preview.v1"] = (
        "mania_napi2b.dataset_exploratory_preview.v1"
    )
    kind: Literal["mania_napi2b_dataset_exploratory_preview"] = (
        "mania_napi2b_dataset_exploratory_preview"
    )
    workflow: Literal["dataset_exploratory_preview"] = "dataset_exploratory_preview"
    run_id: Text
    profile_id: Literal["napi2b.dataset.v1"] = "napi2b.dataset.v1"
    dataset_id: Text
    status: Literal["completed"] = "completed"
    scientific_validation_status: Literal["SCIENTIFIC_VALIDATION_NOT_PERFORMED"] = (
        SCIENCE_WARNING
    )
    authoritative_release_eligible: NeverAuthoritative = False
    source_identities: Annotated[
        tuple[InputIdentity, ...], BeforeValidator(_ordered), Field(min_length=1)
    ]
    source_evidence: Annotated[
        tuple[FileEvidence, ...], BeforeValidator(_ordered), Field(min_length=1)
    ]
    inherited_pbc_unverified: bool
    tables: Annotated[tuple[PreviewTable, ...], BeforeValidator(_ordered)]

    @model_validator(mode="after")
    def _registry(self) -> DatasetExploratoryPreview:
        if len(set(self.source_identities)) != len(self.source_identities):
            raise ValueError("Duplicate preview source identity")
        if len({(e.role, e.path) for e in self.source_evidence}) != len(
            self.source_evidence
        ):
            raise ValueError("Duplicate preview source evidence")
        if tuple((t.table_id, t.path) for t in self.tables) != tuple(
            (spec.table_id, _preview_table_path(spec.table_id))
            for spec in PUBLICATION_TABLE_SPECS
        ):
            raise ValueError("Preview requires the complete ordered 17-table registry")
        return self


def _preview_table_path(table_id: str) -> str:
    portable_path(table_id)
    if "/" in table_id or table_id in (".", ".."):
        raise ValueError("Preview table ID cannot safely name its approved path")
    return "preview/tables/" + table_id + ".csv"


def preview_artifacts() -> tuple[tuple[str, str, str | None], ...]:
    return tuple(
        (s.table_id, _preview_table_path(s.table_id), None)
        for s in PUBLICATION_TABLE_SPECS
    ) + (("preview_manifest", PREVIEW_PATH, PREVIEW_SCHEMA),)


def _preview_expected(
    sources: DatasetSources,
    *,
    run_id: str,
    source_identities: tuple[InputIdentity, ...],
    source_evidence: tuple[FileEvidence, ...],
    inherited_pbc_unverified: bool,
) -> tuple[DatasetExploratoryPreview, dict[str, bytes]]:
    control, metadata, science = sources.validate(preview=True)
    validate_complete_tables(metadata, science)
    if source_identities != tuple(h[1].identity for h in sources.handoffs):
        raise ValueError(
            "Preview source identities differ from actual complete sources"
        )
    for descriptor in source_evidence:
        descriptor.verify(sources.workspace)
    values = {
        t.table_id: publication_csv_bytes(t)
        for t in (*metadata.tables, *science.tables)
    }
    tables = tuple(
        PreviewTable(
            table_id=s.table_id,
            path=_preview_table_path(s.table_id),
            size_bytes=len(values[s.table_id]),
            sha256=hashlib.sha256(values[s.table_id]).hexdigest(),
        )
        for s in PUBLICATION_TABLE_SPECS
    )
    return DatasetExploratoryPreview(
        run_id=run_id,
        dataset_id=control.dataset_id,
        source_identities=source_identities,
        source_evidence=source_evidence,
        inherited_pbc_unverified=inherited_pbc_unverified,
        tables=tables,
    ), values


def write_dataset_preview(
    sources: DatasetSources,
    destination: Path,
    *,
    run_id: str,
    source_identities: tuple[InputIdentity, ...],
    source_evidence: tuple[FileEvidence, ...],
    inherited_pbc_unverified: bool,
) -> DatasetExploratoryPreview:
    manifest, values = _preview_expected(
        sources,
        run_id=run_id,
        source_identities=source_identities,
        source_evidence=source_evidence,
        inherited_pbc_unverified=inherited_pbc_unverified,
    )
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("Preview destination must have no existing outputs")
    for table in manifest.tables:
        path = destination / table.path
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(values[table.table_id])
    result = write_atomic_text(
        json.dumps(
            manifest.model_dump(mode="json"),
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n",
        destination / PREVIEW_PATH,
        overwrite=False,
    )
    if not result.passed:
        raise ValueError("Preview manifest publication failed")
    return read_dataset_preview(
        destination,
        sources=sources,
        run_id=run_id,
        source_identities=source_identities,
        source_evidence=source_evidence,
        inherited_pbc_unverified=inherited_pbc_unverified,
    )


def read_dataset_preview(
    root: Path,
    *,
    sources: DatasetSources,
    run_id: str,
    source_identities: tuple[InputIdentity, ...],
    source_evidence: tuple[FileEvidence, ...],
    inherited_pbc_unverified: bool,
) -> DatasetExploratoryPreview:
    path = member(root, PREVIEW_PATH)
    payload = read_strict_json(path)
    manifest = DatasetExploratoryPreview.model_validate_json(path.read_bytes())
    if manifest.model_dump(mode="json") != payload:
        raise ValueError("Preview requires complete exact closed fields")
    expected, values = _preview_expected(
        sources,
        run_id=run_id,
        source_identities=source_identities,
        source_evidence=source_evidence,
        inherited_pbc_unverified=inherited_pbc_unverified,
    )
    if manifest != expected:
        raise ValueError("Preview source/run/PBC binding or table digest differs")
    for table in manifest.tables:
        actual = member(root, table.path)
        if actual.read_bytes() != values[table.table_id]:
            raise ValueError(
                "Preview scientific values differ from unchanged source methods"
            )
        # Exact bytes of the fully validated source model prove the frozen
        # headers, typed rows, PK/FK and scientific relationships at preview paths.
    from mania.output_paths import safe_absolute

    actual_paths = set()
    for file in root.rglob("*"):
        safe_absolute(file)
        if not file.is_dir():
            actual_paths.add(file.relative_to(root).as_posix())
    if actual_paths != {PREVIEW_PATH, *(t.path for t in manifest.tables)}:
        raise ValueError("Unowned, missing or official release artifacts in preview")
    return manifest
