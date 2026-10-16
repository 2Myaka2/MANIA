"""Deterministic Stage 20.D preprocessing semantics and provenance manifests."""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

from mania.constants import EDGE_TYPE_PRIORITY, SCHEMA_VERSION
from mania.preprocessing.trajectory_contact_chemistry import (
    DISULFIDE_MAX_SG_DISTANCE_A,
    HBOND_MAX_DONOR_ACCEPTOR_DISTANCE_A,
    HBOND_MIN_DONOR_HYDROGEN_ACCEPTOR_ANGLE_DEG,
    HYDROPHOBIC_MAX_CB_DISTANCE_A,
    IONIC_MAX_CHARGED_ATOM_DISTANCE_A,
    SALT_BRIDGE_MAX_CHARGED_ATOM_DISTANCE_A,
    VDW_MAX_HEAVY_ATOM_DISTANCE_A,
    VDW_MIN_HEAVY_ATOM_DISTANCE_A,
)
from mania.preprocessing.trajectory_graph_export import (
    BACKBONE_MAX_CA_DIST_A,
    PreprocessingGraphExportMappingResult,
    PreprocessingGraphNodeMappingRecord,
)
from mania.preprocessing.trajectory_interaction_geometry import (
    AROMATIC_PI_MAX_CENTROID_DISTANCE_A,
    AROMATIC_PI_PARALLEL_MAX_ANGLE_DEG,
    AROMATIC_PI_TSHAPED_MAX_ANGLE_DEG,
    AROMATIC_PI_TSHAPED_MIN_ANGLE_DEG,
    CATION_PI_MAX_DISTANCE_A,
)
from mania.preprocessing.trajectory_protein_contact_export import (
    PreprocessingProteinContactCsvWriteResult,
)
from mania.preprocessing.trajectory_residue_table_export import (
    RESIDUE_TABLE_COLUMNS,
    PreprocessingResidueTableCsvWriteResult,
)

EDGE_SEMANTICS_FILENAME = "edge_semantics.json"
MANIA_MANIFEST_FILENAME = "mania_manifest.json"
MANIA_RESIDUE_LIBRARY_FILENAME = "mania_residue_library.json"


@dataclass(frozen=True)
class PreprocessingManifestArtifactsWriteResult:
    """Summary of one Stage 20.D artifact write attempt."""

    output_dir: Path
    paths: tuple[Path, ...] = ()
    error: str | None = None

    @property
    def passed(self) -> bool:
        """Return whether all three manifests were written."""
        return self.error is None

    def to_dict(self) -> dict[str, object]:
        """Return JSON-safe result metadata."""
        return {
            "output_dir": str(self.output_dir),
            "passed": self.passed,
            "paths": [str(path) for path in self.paths],
            "error": self.error,
        }


def build_edge_semantics_manifest() -> dict[str, object]:
    """Describe the accepted Stage 20.C protein edge semantics."""
    semantics = {
        "backbone": _edge_semantic(
            "Sequential residue indexes in one segment with complete C-alpha "
            f"coordinates no more than {BACKBONE_MAX_CA_DIST_A} A apart.",
            {"max_ca_distance_A": BACKBONE_MAX_CA_DIST_A},
            limitations="Representative C-alpha geometry; not bond inference.",
        ),
        "hbond": _edge_semantic(
            "N/O donor-acceptor geometry with an explicit topology-bonded hydrogen.",
            {
                "max_donor_acceptor_distance_A": (
                    HBOND_MAX_DONOR_ACCEPTOR_DISTANCE_A
                ),
                "min_donor_hydrogen_acceptor_angle_deg": (
                    HBOND_MIN_DONOR_HYDROGEN_ACCEPTOR_ANGLE_DEG
                ),
            },
            limitations="No inferred hydrogen or distance-only fallback.",
        ),
        "disulfide": _edge_semantic(
            "CYS SG-SG distance at or below the cutoff.",
            {"max_sg_distance_A": DISULFIDE_MAX_SG_DISTANCE_A},
        ),
        "salt_bridge": _edge_semantic(
            "LYS NZ or ARG NH1/NH2 against ASP OD1/OD2 or GLU OE1/OE2.",
            {
                "max_charged_atom_distance_A": (
                    SALT_BRIDGE_MAX_CHARGED_ATOM_DISTANCE_A
                )
            },
            limitations="Historical 'saltbridge' spelling is only an input alias.",
        ),
        "ionic": _edge_semantic(
            "Supported positive and negative residue atom groups within cutoff.",
            {"max_charged_atom_distance_A": IONIC_MAX_CHARGED_ATOM_DISTANCE_A},
            limitations="Uses the explicit Stage 20.C charged residue atom groups.",
        ),
        "cation_pi": _edge_semantic(
            "LYS NZ or ARG CZ to a complete supported aromatic ring centroid.",
            {"max_distance_A_exclusive": CATION_PI_MAX_DISTANCE_A},
            limitations=(
                "Requires the supported named atoms and complete ring geometry."
            ),
        ),
        "aromatic_pi": _edge_semantic(
            "Supported complete aromatic rings with accepted centroid and "
            "angle geometry.",
            {
                "max_centroid_distance_A": AROMATIC_PI_MAX_CENTROID_DISTANCE_A,
                "parallel_angle_deg_exclusive_max": (
                    AROMATIC_PI_PARALLEL_MAX_ANGLE_DEG
                ),
                "t_shaped_angle_deg_inclusive": [
                    AROMATIC_PI_TSHAPED_MIN_ANGLE_DEG,
                    AROMATIC_PI_TSHAPED_MAX_ANGLE_DEG,
                ],
            },
            limitations="Requires complete, non-degenerate supported ring geometry.",
        ),
        "hydrophobic": _edge_semantic(
            "Accepted hydrophobic residue pairs with both CB atoms within cutoff.",
            {"max_cb_distance_A": HYDROPHOBIC_MAX_CB_DISTANCE_A},
            limitations="Missing CB atoms are skipped.",
        ),
        "vdw": _edge_semantic(
            "Minimum residue-pair heavy-atom distance in the inclusive window.",
            {
                "min_heavy_atom_distance_A": VDW_MIN_HEAVY_ATOM_DISTANCE_A,
                "max_heavy_atom_distance_A": VDW_MAX_HEAVY_ATOM_DISTANCE_A,
            },
        ),
        "residue_contact": _edge_semantic(
            "Generic sampled-frame residue contact from the configured "
            "contact detector.",
            {"threshold_source": "runtime contact definition"},
            limitations=(
                "The numeric threshold is run configuration, not a fixed semantic."
            ),
        ),
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact": EDGE_SEMANTICS_FILENAME,
        "scope": "Stage 20.C implemented protein-protein edge semantics",
        "edge_priority": list(EDGE_TYPE_PRIORITY),
        "edge_types": [
            {
                "name": edge_type,
                "canonical_backend_spelling": edge_type,
                "priority_rank": rank,
                **semantics[edge_type],
            }
            for rank, edge_type in enumerate(EDGE_TYPE_PRIORITY, start=1)
        ],
        "deferred_non_protein_edge_types": [
            "protein_lipid",
            "protein_glycan",
            "glycan_anchor",
            "protein_ligand",
        ],
    }


def build_preprocessing_residue_library(
    mapping_result: PreprocessingGraphExportMappingResult,
) -> dict[str, object]:
    """Build a Stage 20.A-aligned residue identity and QC artifact."""
    _require_mapping(mapping_result)
    conditions = sorted({node.condition_name for node in mapping_result.nodes})
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact": MANIA_RESIDUE_LIBRARY_FILENAME,
        "scope": "Stage 20.A residue identity inventory and per-run QC",
        "residue_table_columns": list(RESIDUE_TABLE_COLUMNS),
        "conditions": [
            _condition_residue_inventory(condition, mapping_result.nodes)
            for condition in conditions
        ],
        "limitations": [
            "This artifact does not compute missing structural attributes.",
            "This artifact is not a biological residue database.",
            "Non-protein inventory is outside Stage 20.D.",
        ],
    }


def build_preprocessing_run_manifest(
    mapping_result: PreprocessingGraphExportMappingResult,
    *,
    residue_tables: PreprocessingResidueTableCsvWriteResult | None = None,
    protein_contacts: PreprocessingProteinContactCsvWriteResult | None = None,
) -> dict[str, object]:
    """Build portable provenance for available Stage 20.A/B/D artifacts."""
    _require_mapping(mapping_result)
    artifacts = [
        _artifact(EDGE_SEMANTICS_FILENAME, "edge semantics", "20.D"),
        _artifact(MANIA_RESIDUE_LIBRARY_FILENAME, "residue identity and QC", "20.D"),
        _artifact(MANIA_MANIFEST_FILENAME, "preprocessing run provenance", "20.D"),
    ]
    if residue_tables is not None and residue_tables.passed:
        artifacts.extend(
            _artifact(path.name, "residue table", "20.A", condition)
            for condition, path in sorted(residue_tables.paths_by_condition.items())
        )
    if protein_contacts is not None and protein_contacts.passed:
        edge_paths = protein_contacts.edge_paths_by_condition.items()
        for condition, path in sorted(edge_paths):
            artifacts.append(
                _artifact(path.name, "protein contact edges", "20.B", condition)
            )
        perframe_paths = protein_contacts.perframe_paths_by_condition.items()
        for condition, path in sorted(perframe_paths):
            artifacts.append(
                _artifact(
                    path.name,
                    "per-frame protein contacts",
                    "20.B",
                    condition,
                )
            )
    conditions = sorted(
        {node.condition_name for node in mapping_result.nodes}
        | {
            str(artifact["condition"])
            for artifact in artifacts
            if "condition" in artifact
        }
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact": MANIA_MANIFEST_FILENAME,
        "conditions": conditions,
        "produced_artifacts": artifacts,
        "edge_semantics": EDGE_SEMANTICS_FILENAME,
        "residue_library_qc": MANIA_RESIDUE_LIBRARY_FILENAME,
        "provenance": {
            "contact_selection": (
                "protein"
                if protein_contacts is not None and protein_contacts.passed
                else None
            ),
            "frame_sampling": None,
            "sampled_frame_counts": None,
            "run_id": None,
        },
        "limitations": [
            "Unavailable run provenance is null rather than inferred.",
            "Artifact references are portable filenames, not source MD paths.",
            "These manifests are not required WANIA payload fields.",
        ],
    }


def write_preprocessing_manifest_artifacts(
    mapping_result: PreprocessingGraphExportMappingResult,
    output_dir: str | Path,
    *,
    residue_tables: PreprocessingResidueTableCsvWriteResult | None = None,
    protein_contacts: PreprocessingProteinContactCsvWriteResult | None = None,
) -> PreprocessingManifestArtifactsWriteResult:
    """Write ``edge_semantics.json`` and the two MANIA provenance artifacts."""
    try:
        path = Path(output_dir)
    except TypeError:
        return PreprocessingManifestArtifactsWriteResult(
            output_dir=Path(""), error="output_dir must be a string or Path"
        )
    if isinstance(output_dir, str) and not output_dir.strip():
        return PreprocessingManifestArtifactsWriteResult(
            output_dir=path, error="output_dir must not be empty"
        )
    try:
        _require_mapping(mapping_result)
        if path.exists() and not path.is_dir():
            raise ValueError("output_dir is an existing file")
        path.mkdir(parents=True, exist_ok=True)
        payloads = (
            (EDGE_SEMANTICS_FILENAME, build_edge_semantics_manifest()),
            (
                MANIA_RESIDUE_LIBRARY_FILENAME,
                build_preprocessing_residue_library(mapping_result),
            ),
            (
                MANIA_MANIFEST_FILENAME,
                build_preprocessing_run_manifest(
                    mapping_result,
                    residue_tables=residue_tables,
                    protein_contacts=protein_contacts,
                ),
            ),
        )
        paths = tuple(path / filename for filename, _ in payloads)
        for output_path, (_, payload) in zip(paths, payloads, strict=True):
            _write_json(output_path, payload)
    except (OSError, TypeError, ValueError) as error:
        return PreprocessingManifestArtifactsWriteResult(
            output_dir=path, error=str(error)
        )
    return PreprocessingManifestArtifactsWriteResult(output_dir=path, paths=paths)


def _edge_semantic(
    definition: str,
    detection_criteria: dict[str, object],
    *,
    limitations: str = "None beyond the accepted Stage 20.C criterion.",
) -> dict[str, object]:
    return {
        "definition": definition,
        "detection_criteria": detection_criteria,
        "protein_protein": True,
        "implemented": True,
        "known_limitations": limitations,
        "can_overlap_other_edge_types": True,
    }


def _condition_residue_inventory(
    condition: str,
    nodes: tuple[PreprocessingGraphNodeMappingRecord, ...],
) -> dict[str, object]:
    selected = sorted(
        (node for node in nodes if node.condition_name == condition),
        key=lambda node: (node.residue_index, node.node_id),
    )
    by_index: dict[int, list[PreprocessingGraphNodeMappingRecord]] = {}
    for node in selected:
        by_index.setdefault(node.residue_index, []).append(node)
    conflicts = []
    for residue_index, indexed_nodes in sorted(by_index.items()):
        identities = sorted(
            {
                (node.residue_id, node.resname, node.segid)
                for node in indexed_nodes
            },
            key=lambda item: (item[0], item[1], item[2] or ""),
        )
        if len(identities) > 1:
            conflicts.append(
                {
                    "residue_index": residue_index,
                    "identities": [
                        {"resid": resid, "resname": resname, "segment_id": segment}
                        for resid, resname, segment in identities
                    ],
                }
            )
    missing_coordinates = sum(node.x_ca is None for node in selected)
    missing_segments = sum(node.segid is None for node in selected)
    structural_fields = ("region", "tm_relative_z", "rmsf_A", "sasa_A2", "ss")
    warnings = []
    if conflicts:
        warnings.append("Conflicting identities share a residue_index.")
    if missing_coordinates:
        warnings.append("Some residues have missing C-alpha coordinates.")
    if missing_segments:
        warnings.append("Some residues have missing segment identifiers.")
    return {
        "condition": condition,
        "residue_count": len(selected),
        "residues": [_residue_record(node) for node in selected],
        "qc": {
            "passed": not conflicts,
            "conflicting_residue_identity_count": len(conflicts),
            "conflicting_residue_identities": conflicts,
            "missing_coordinate_count": missing_coordinates,
            "missing_segment_count": missing_segments,
            "missing_structural_attribute_counts": {
                field: len(selected) for field in structural_fields
            },
            "warnings": warnings,
        },
    }


def _residue_record(node: PreprocessingGraphNodeMappingRecord) -> dict[str, object]:
    return {
        "condition": node.condition_name,
        "residue_index": node.residue_index,
        "resid": node.residue_id,
        "resname": node.resname,
        "segment_id": node.segid,
        "region": None,
        "x_ca": node.x_ca,
        "y_ca": node.y_ca,
        "z_ca": node.z_ca,
        "tm_relative_z": None,
        "rmsf_A": None,
        "sasa_A2": None,
        "ss": None,
    }


def _artifact(
    filename: str,
    role: str,
    stage: str,
    condition: str | None = None,
) -> dict[str, object]:
    artifact: dict[str, object] = {
        "filename": Path(filename).name,
        "role": role,
        "stage": stage,
    }
    if condition is not None:
        artifact["condition"] = condition
    return artifact


def _require_mapping(mapping_result: object) -> None:
    if not isinstance(mapping_result, PreprocessingGraphExportMappingResult):
        raise TypeError("mapping_result must be PreprocessingGraphExportMappingResult")
    if not mapping_result.passed:
        raise ValueError("mapping_result contains issues")


def _write_json(path: Path, payload: dict[str, object]) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as output_file:
            temporary_path = Path(output_file.name)
            output_file.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        temporary_path.replace(path)
    except OSError:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise
