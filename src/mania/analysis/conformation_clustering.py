"""Deterministic Stage 22.F clustering of binary contact fingerprints."""

from __future__ import annotations

import csv
import math
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from mania.analysis.conformation_pca import (
    CONFORMATION_PCA_STATUS_COMPUTED,
    CONFORMATION_PCA_STATUS_CONSTANT_MATRIX,
    CONFORMATION_PCA_STATUS_EMPTY_INPUT,
    CONFORMATION_PCA_STATUS_FAILED,
    CONFORMATION_PCA_STATUS_NO_FEATURES,
    CONFORMATION_PCA_STATUS_ONE_FRAME,
    CONFORMATION_PCA_STATUS_UNAVAILABLE,
    ConformationPcaProjection,
    ConformationPcaRow,
)
from mania.analysis.contact_fingerprints import ContactFingerprintMatrix

CONFORMATION_CLUSTERING_K_MAX = 10
CONFORMATION_CLUSTERING_BASIS_FINGERPRINT = "fingerprint"
CONFORMATION_CLUSTERING_BASIS_PCA = "pca"
CONFORMATION_CLUSTERING_BASES = (
    CONFORMATION_CLUSTERING_BASIS_FINGERPRINT,
    CONFORMATION_CLUSTERING_BASIS_PCA,
)
CONFORMATION_CLUSTERING_ALGORITHM_FINGERPRINT = "deterministic_kmeans_fingerprint"
CONFORMATION_CLUSTERING_ALGORITHM_PCA = "deterministic_kmeans_pca"
CONFORMATION_CLUSTERING_INPUT_SOURCE_FINGERPRINT = "contact_fingerprint_matrix"
CONFORMATION_CLUSTERING_INPUT_SOURCE_PCA = "conformation_pca_coordinates"
CONFORMATION_CLUSTERING_PCA_STATUS_NOT_USED = "pca_unavailable"
CONFORMATION_CLUSTERING_NOTEBOOK_PARITY_FINGERPRINT = "not_pca_kmeans_parity"
CONFORMATION_CLUSTERING_NOTEBOOK_PARITY_PCA = (
    "notebook_pca_kmeans_parity_not_claimed"
)
CONFORMATION_CLUSTERING_ALGORITHM = CONFORMATION_CLUSTERING_ALGORITHM_FINGERPRINT
CONFORMATION_CLUSTERING_INPUT_SOURCE = CONFORMATION_CLUSTERING_INPUT_SOURCE_FINGERPRINT
CONFORMATION_CLUSTERING_PCA_STATUS = CONFORMATION_CLUSTERING_PCA_STATUS_NOT_USED
CONFORMATION_CLUSTERING_NOTEBOOK_PARITY = (
    CONFORMATION_CLUSTERING_NOTEBOOK_PARITY_FINGERPRINT
)

CONFORMATION_CLUSTERING_STATUS_COMPUTED = "computed"
CONFORMATION_CLUSTERING_STATUS_EMPTY_INPUT = "empty_input"
CONFORMATION_CLUSTERING_STATUS_NO_FEATURES = "no_features"
CONFORMATION_CLUSTERING_STATUS_INSUFFICIENT_FRAMES = "insufficient_frames"
CONFORMATION_CLUSTERING_STATUS_CONSTANT_MATRIX = "constant_matrix"
CONFORMATION_CLUSTERING_STATUS_NO_VALID_K = "no_valid_k"

CONFORMATION_CLUSTERING_CANDIDATE_VALID = "valid"
CONFORMATION_CLUSTERING_CANDIDATE_EMPTY_CLUSTER = "empty_cluster"

CONFORMATION_LABELS_COLUMNS = (
    "condition",
    "row_index",
    "frame_index",
    "time_ps",
    "state_id",
    "cluster_label",
    "selected_k",
    "silhouette_score",
    "is_representative",
    "distance_to_centroid",
    "algorithm",
    "input_source",
    "pca_status",
    "notebook_parity",
    "status",
    "notes",
)

_FINGERPRINT_NOTE = (
    "clustered directly from binary contact fingerprints; "
    "PCA coordinates unavailable; notebook PCA-to-k-means parity not claimed"
)
_FINGERPRINT_COMPUTED_PCA_NOTE = (
    "clustered directly from binary contact fingerprints; "
    "PCA was computed but not used for clustering; "
    "notebook PCA-to-k-means parity not applicable to fingerprint mode"
)
_FINGERPRINT_SKIPPED_PCA_NOTE = (
    "clustered directly from binary contact fingerprints; "
    "PCA status retained but not used for clustering; "
    "notebook PCA-to-k-means parity not applicable to fingerprint mode"
)
_SKIPPED_FINGERPRINT_NOTE = (
    "clustering input is binary contact fingerprints; "
    "PCA coordinates unavailable; notebook PCA-to-k-means parity not claimed"
)
_SKIPPED_FINGERPRINT_COMPUTED_PCA_NOTE = (
    "clustering input is binary contact fingerprints; "
    "PCA was computed but not used for clustering; "
    "notebook PCA-to-k-means parity not applicable to fingerprint mode"
)
_SKIPPED_FINGERPRINT_SKIPPED_PCA_NOTE = (
    "clustering input is binary contact fingerprints; "
    "PCA status retained but not used for clustering; "
    "notebook PCA-to-k-means parity not applicable to fingerprint mode"
)
_PCA_NOTE = (
    "clustered from computed PCA frame-score coordinates; "
    "PCA clustering implemented; exact notebook parity not claimed"
)
_SKIPPED_PCA_NOTE = (
    "clustering input is computed PCA frame-score coordinates; "
    "PCA clustering implemented; exact notebook parity not claimed"
)
_STATUSES = {
    CONFORMATION_CLUSTERING_STATUS_COMPUTED,
    CONFORMATION_CLUSTERING_STATUS_EMPTY_INPUT,
    CONFORMATION_CLUSTERING_STATUS_NO_FEATURES,
    CONFORMATION_CLUSTERING_STATUS_INSUFFICIENT_FRAMES,
    CONFORMATION_CLUSTERING_STATUS_CONSTANT_MATRIX,
    CONFORMATION_CLUSTERING_STATUS_NO_VALID_K,
}
_PCA_STATUSES = {
    CONFORMATION_PCA_STATUS_COMPUTED,
    CONFORMATION_PCA_STATUS_CONSTANT_MATRIX,
    CONFORMATION_PCA_STATUS_EMPTY_INPUT,
    CONFORMATION_PCA_STATUS_FAILED,
    CONFORMATION_PCA_STATUS_NO_FEATURES,
    CONFORMATION_PCA_STATUS_ONE_FRAME,
    CONFORMATION_PCA_STATUS_UNAVAILABLE,
}

ConformationClusteringBasis = Literal["fingerprint", "pca"]

_Vector = tuple[int | float, ...]
_Centroid = tuple[float, ...]


class ConformationClusteringError(ValueError):
    """Raised when fingerprints cannot form a clustering artifact."""


@dataclass(frozen=True)
class ConformationClusteringConfig:
    """Dependency-free k-means limits."""

    max_k: int = CONFORMATION_CLUSTERING_K_MAX
    max_iterations: int = 100

    def __post_init__(self) -> None:
        if type(self.max_k) is not int or self.max_k < 2:
            raise ConformationClusteringError("max_k must be an integer >= 2")
        if type(self.max_iterations) is not int or self.max_iterations < 1:
            raise ConformationClusteringError(
                "max_iterations must be a positive integer"
            )


@dataclass(frozen=True)
class ConformationClusteringCandidate:
    """Auditable result for one candidate k."""

    k: int
    silhouette_score: float | None
    status: str
    n_iterations: int
    converged: bool


@dataclass(frozen=True)
class ConformationLabelRow:
    """One fingerprint frame and its optional selected conformation state."""

    condition: str
    row_index: int
    frame_index: int
    time_ps: float | None
    state_id: int | None
    cluster_label: str | None
    selected_k: int | None
    silhouette_score: float | None
    is_representative: bool | None
    distance_to_centroid: float | None
    algorithm: str
    input_source: str
    pca_status: str
    notebook_parity: str
    status: str
    notes: str

    def to_dict(self) -> dict[str, object]:
        """Return one row in stable artifact column order."""
        return {
            column: getattr(self, column) for column in CONFORMATION_LABELS_COLUMNS
        }


@dataclass(frozen=True)
class ConformationClustering:
    """Selected clustering and artifact rows for one condition."""

    condition: str
    rows: tuple[ConformationLabelRow, ...]
    candidates: tuple[ConformationClusteringCandidate, ...]
    selected_k: int | None
    silhouette_score: float | None
    status: str
    notes: str


@dataclass(frozen=True)
class _KmeansResult:
    assignments: tuple[int, ...]
    centroids: tuple[_Centroid, ...]
    status: str
    n_iterations: int
    converged: bool


@dataclass(frozen=True)
class _ClusteringMetadata:
    algorithm: str
    input_source: str
    pca_status: str
    notebook_parity: str
    computed_note: str
    skipped_note: str


def build_conformation_clusters(
    fingerprints: ContactFingerprintMatrix,
    *,
    clustering_basis: ConformationClusteringBasis = "fingerprint",
    pca_projection: ConformationPcaProjection | None = None,
    pca_components_for_clustering: int | None = None,
    config: ConformationClusteringConfig | None = None,
) -> ConformationClustering:
    """Cluster frames from the selected conformation feature basis.

    Fingerprint clustering remains the default and ignores any supplied PCA
    projection. PCA clustering is explicit opt-in and uses only computed
    in-memory PCA frame-score coordinates.
    """
    if not isinstance(fingerprints, ContactFingerprintMatrix):
        raise TypeError("fingerprints must be a ContactFingerprintMatrix")
    clustering_config = config or ConformationClusteringConfig()
    if not isinstance(clustering_config, ConformationClusteringConfig):
        raise TypeError("config must be a ConformationClusteringConfig")
    _validate_clustering_basis(clustering_basis)
    _validate_fingerprints(fingerprints)

    metadata = _metadata_for_basis(
        clustering_basis,
        pca_projection=pca_projection,
    )
    values = _clustering_values(
        fingerprints,
        clustering_basis=clustering_basis,
        pca_projection=pca_projection,
        pca_components_for_clustering=pca_components_for_clustering,
    )
    n_frames, n_features = fingerprints.shape
    n_vector_features = len(values[0]) if values else n_features
    if not n_frames:
        return _skipped_clustering(
            fingerprints,
            CONFORMATION_CLUSTERING_STATUS_EMPTY_INPUT,
            "fingerprint matrix contains no frames",
            metadata=metadata,
        )
    if not n_vector_features:
        return _skipped_clustering(
            fingerprints,
            CONFORMATION_CLUSTERING_STATUS_NO_FEATURES,
            _no_features_reason(clustering_basis),
            metadata=metadata,
        )
    if n_frames < 3:
        return _skipped_clustering(
            fingerprints,
            CONFORMATION_CLUSTERING_STATUS_INSUFFICIENT_FRAMES,
            "at least three frames are required for silhouette selection",
            metadata=metadata,
        )
    if len(set(values)) == 1:
        return _skipped_clustering(
            fingerprints,
            CONFORMATION_CLUSTERING_STATUS_CONSTANT_MATRIX,
            _constant_matrix_reason(clustering_basis),
            metadata=metadata,
        )

    candidate_results: dict[int, _KmeansResult] = {}
    candidates: list[ConformationClusteringCandidate] = []
    maximum_k = min(clustering_config.max_k, n_frames - 1)
    for k in range(2, maximum_k + 1):
        result = _run_kmeans(
            values,
            tuple(frame.frame_index for frame in fingerprints.frames),
            k=k,
            max_iterations=clustering_config.max_iterations,
        )
        if result.status == CONFORMATION_CLUSTERING_CANDIDATE_EMPTY_CLUSTER:
            candidates.append(
                ConformationClusteringCandidate(
                    k=k,
                    silhouette_score=None,
                    status=result.status,
                    n_iterations=result.n_iterations,
                    converged=result.converged,
                )
            )
            continue
        score = _silhouette_score(values, result.assignments)
        candidate_results[k] = result
        candidates.append(
            ConformationClusteringCandidate(
                k=k,
                silhouette_score=score,
                status=CONFORMATION_CLUSTERING_CANDIDATE_VALID,
                n_iterations=result.n_iterations,
                converged=result.converged,
            )
        )

    valid_candidates = tuple(
        candidate
        for candidate in candidates
        if candidate.status == CONFORMATION_CLUSTERING_CANDIDATE_VALID
        and candidate.silhouette_score is not None
    )
    if not valid_candidates:
        return _skipped_clustering(
            fingerprints,
            CONFORMATION_CLUSTERING_STATUS_NO_VALID_K,
            "no candidate k produced valid non-empty clusters",
            candidates=tuple(candidates),
            metadata=metadata,
        )

    selected = valid_candidates[0]
    assert selected.silhouette_score is not None
    for candidate in valid_candidates[1:]:
        assert candidate.silhouette_score is not None
        if candidate.silhouette_score > selected.silhouette_score:
            selected = candidate
    selected_score = selected.silhouette_score
    assert selected_score is not None
    result = candidate_results[selected.k]
    rows = _computed_rows(
        fingerprints,
        values,
        result,
        selected_k=selected.k,
        silhouette_score=selected_score,
        metadata=metadata,
    )
    clustering = ConformationClustering(
        condition=fingerprints.condition,
        rows=rows,
        candidates=tuple(candidates),
        selected_k=selected.k,
        silhouette_score=selected_score,
        status=CONFORMATION_CLUSTERING_STATUS_COMPUTED,
        notes=metadata.computed_note,
    )
    _validate_clustering(clustering)
    return clustering


def write_conformation_labels_csv(
    clustering: ConformationClustering,
    output_dir: str | Path,
) -> Path:
    """Write ``conformation_labels_{condition}.csv`` atomically and stably."""
    if not isinstance(clustering, ConformationClustering):
        raise TypeError("clustering must be a ConformationClustering")
    _validate_clustering(clustering)
    component = re.sub(r"[^A-Za-z0-9_.-]+", "_", clustering.condition).strip(
        "._"
    )
    if not component:
        raise ConformationClusteringError(
            "condition must contain a filename-safe character"
        )
    directory = Path(output_dir)
    if directory.exists() and not directory.is_dir():
        raise ConformationClusteringError(
            "conformation labels output is not a directory"
        )
    output_path = directory / f"conformation_labels_{component}.csv"
    temporary_path: Path | None = None
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=directory,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as csv_file:
            temporary_path = Path(csv_file.name)
            writer = csv.DictWriter(
                csv_file,
                fieldnames=CONFORMATION_LABELS_COLUMNS,
                lineterminator="\n",
            )
            writer.writeheader()
            for row in clustering.rows:
                writer.writerow(
                    {key: _csv_value(value) for key, value in row.to_dict().items()}
                )
        temporary_path.replace(output_path)
    except (OSError, csv.Error) as error:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise ConformationClusteringError(
            f"conformation labels could not be written: {output_path}"
        ) from error
    return output_path


def _validate_clustering_basis(clustering_basis: object) -> None:
    if clustering_basis not in CONFORMATION_CLUSTERING_BASES:
        raise ConformationClusteringError(
            "clustering_basis must be 'fingerprint' or 'pca'"
        )


def _metadata_for_basis(
    clustering_basis: ConformationClusteringBasis,
    *,
    pca_projection: ConformationPcaProjection | None,
) -> _ClusteringMetadata:
    if clustering_basis == CONFORMATION_CLUSTERING_BASIS_FINGERPRINT:
        if pca_projection is not None and not isinstance(
            pca_projection,
            ConformationPcaProjection,
        ):
            raise TypeError("pca_projection must be a ConformationPcaProjection")
        pca_status = (
            CONFORMATION_CLUSTERING_PCA_STATUS_NOT_USED
            if pca_projection is None
            else pca_projection.status
        )
        if pca_status == CONFORMATION_PCA_STATUS_COMPUTED:
            computed_note = _FINGERPRINT_COMPUTED_PCA_NOTE
            skipped_note = _SKIPPED_FINGERPRINT_COMPUTED_PCA_NOTE
        elif pca_status == CONFORMATION_CLUSTERING_PCA_STATUS_NOT_USED:
            computed_note = _FINGERPRINT_NOTE
            skipped_note = _SKIPPED_FINGERPRINT_NOTE
        else:
            computed_note = _FINGERPRINT_SKIPPED_PCA_NOTE
            skipped_note = _SKIPPED_FINGERPRINT_SKIPPED_PCA_NOTE
        return _ClusteringMetadata(
            algorithm=CONFORMATION_CLUSTERING_ALGORITHM_FINGERPRINT,
            input_source=CONFORMATION_CLUSTERING_INPUT_SOURCE_FINGERPRINT,
            pca_status=pca_status,
            notebook_parity=CONFORMATION_CLUSTERING_NOTEBOOK_PARITY_FINGERPRINT,
            computed_note=computed_note,
            skipped_note=skipped_note,
        )
    return _ClusteringMetadata(
        algorithm=CONFORMATION_CLUSTERING_ALGORITHM_PCA,
        input_source=CONFORMATION_CLUSTERING_INPUT_SOURCE_PCA,
        pca_status=CONFORMATION_PCA_STATUS_COMPUTED,
        notebook_parity=CONFORMATION_CLUSTERING_NOTEBOOK_PARITY_PCA,
        computed_note=_PCA_NOTE,
        skipped_note=_SKIPPED_PCA_NOTE,
    )


def _clustering_values(
    fingerprints: ContactFingerprintMatrix,
    *,
    clustering_basis: ConformationClusteringBasis,
    pca_projection: ConformationPcaProjection | None,
    pca_components_for_clustering: int | None,
) -> tuple[_Vector, ...]:
    if clustering_basis == CONFORMATION_CLUSTERING_BASIS_FINGERPRINT:
        if pca_components_for_clustering is not None:
            raise ConformationClusteringError(
                "pca_components_for_clustering requires clustering_basis='pca'"
            )
        return fingerprints.values

    if pca_projection is None:
        raise ConformationClusteringError(
            "clustering_basis='pca' requires pca_projection"
        )
    if not isinstance(pca_projection, ConformationPcaProjection):
        raise TypeError("pca_projection must be a ConformationPcaProjection")
    component_count = _pca_component_count(
        pca_projection,
        pca_components_for_clustering,
    )
    _validate_pca_projection_alignment(
        fingerprints,
        pca_projection,
        component_count=component_count,
    )
    score_vectors = _pca_score_vectors(pca_projection)
    return tuple(
        tuple(
            score_vector[component_index]
            for component_index in range(component_count)
        )
        for score_vector in score_vectors
    )


def _pca_component_count(
    projection: ConformationPcaProjection,
    requested_components: int | None,
) -> int:
    if projection.status != CONFORMATION_PCA_STATUS_COMPUTED:
        raise ConformationClusteringError(
            "PCA clustering requires a computed PCA projection"
        )
    if projection.n_components < 1:
        raise ConformationClusteringError(
            "PCA clustering requires at least one computed PCA component"
        )
    if requested_components is None:
        return projection.n_components
    if type(requested_components) is not int:
        raise ConformationClusteringError(
            "pca_components_for_clustering must be an integer"
        )
    if requested_components < 1:
        raise ConformationClusteringError(
            "pca_components_for_clustering must be >= 1"
        )
    if requested_components > projection.n_components:
        raise ConformationClusteringError(
            "pca_components_for_clustering must be <= projection.n_components"
        )
    return requested_components


def _validate_pca_projection_alignment(
    fingerprints: ContactFingerprintMatrix,
    projection: ConformationPcaProjection,
    *,
    component_count: int,
) -> None:
    n_frames, n_features = fingerprints.shape
    if projection.condition != fingerprints.condition:
        raise ConformationClusteringError(
            "PCA projection condition does not match fingerprints"
        )
    if projection.n_frames != len(projection.rows):
        raise ConformationClusteringError(
            "PCA projection n_frames does not match rows"
        )
    if projection.n_frames != n_frames:
        raise ConformationClusteringError(
            "PCA frame count does not match fingerprints"
        )
    if projection.n_features != n_features:
        raise ConformationClusteringError(
            "PCA feature count does not match fingerprints"
        )
    score_vectors = _pca_score_vectors(projection)
    if len(score_vectors) != projection.n_frames:
        raise ConformationClusteringError(
            "PCA internal score count does not match rows"
        )

    frame_indexes: set[int] = set()
    for row_index, row in enumerate(projection.rows):
        if row.frame_index in frame_indexes:
            raise ConformationClusteringError("duplicate PCA frame identity")
        frame_indexes.add(row.frame_index)
        score_vector = score_vectors[row_index]
        if len(score_vector) != projection.n_components:
            raise ConformationClusteringError(
                "PCA internal score dimensionality does not match"
            )
        for component_index in range(component_count):
            if component_index >= len(score_vector):
                raise ConformationClusteringError(
                    "unavailable PCA component requested"
                )
            value = score_vector[component_index]
            if not isinstance(value, float) or not math.isfinite(value):
                raise ConformationClusteringError(
                    "PCA clustering coordinates must be finite"
                )

    for frame, row in zip(fingerprints.frames, projection.rows, strict=True):
        if row.condition != projection.condition:
            raise ConformationClusteringError(
                "PCA row condition does not match projection"
            )
        if row.row_index != frame.row_index:
            raise ConformationClusteringError(
                "PCA row_index does not match fingerprint frame order"
            )
        if row.frame_index != frame.frame_index:
            raise ConformationClusteringError(
                "PCA frame_index does not match fingerprint frame order"
            )
        if (
            row.time_ps is not None
            and frame.time_ps is not None
            and row.time_ps != frame.time_ps
        ):
            raise ConformationClusteringError(
                "PCA time_ps conflicts with fingerprint frame"
            )
        if (
            row.n_components != projection.n_components
            or row.n_features != projection.n_features
            or row.n_frames != projection.n_frames
            or row.status != projection.status
        ):
            raise ConformationClusteringError(
                "PCA row metadata does not match projection"
            )
        for component_index in range(min(component_count, 3)):
            _pca_exported_coordinate(row, component_index)


def _pca_score_vectors(
    projection: ConformationPcaProjection,
) -> tuple[tuple[float, ...], ...]:
    if projection.score_vectors:
        return projection.score_vectors
    if projection.n_components > 3:
        raise ConformationClusteringError(
            "PCA clustering requires internal score vectors for components above PC3"
        )
    return tuple(
        tuple(
            _pca_exported_coordinate(row, component_index)
            for component_index in range(projection.n_components)
        )
        for row in projection.rows
    )


def _pca_exported_coordinate(
    row: ConformationPcaRow,
    component_index: int,
) -> float:
    if component_index == 0:
        value = row.pc1
    elif component_index == 1:
        value = row.pc2
    elif component_index == 2:
        value = row.pc3
    else:
        raise ConformationClusteringError("unavailable PCA export component requested")
    if not isinstance(value, float) or not math.isfinite(value):
        raise ConformationClusteringError(
            "PCA clustering coordinates must be finite"
        )
    return value


def _no_features_reason(clustering_basis: ConformationClusteringBasis) -> str:
    if clustering_basis == CONFORMATION_CLUSTERING_BASIS_PCA:
        return "PCA clustering contains no retained components"
    return "fingerprint matrix contains no features"


def _constant_matrix_reason(clustering_basis: ConformationClusteringBasis) -> str:
    if clustering_basis == CONFORMATION_CLUSTERING_BASIS_PCA:
        return "all PCA clustering rows are identical"
    return "all fingerprint rows are identical"


def _run_kmeans(
    values: tuple[_Vector, ...],
    frame_indexes: tuple[int, ...],
    *,
    k: int,
    max_iterations: int,
) -> _KmeansResult:
    centroids = _initialize_centroids(values, frame_indexes, k)
    previous_assignments: tuple[int, ...] | None = None
    for iteration in range(1, max_iterations + 1):
        assignments = tuple(
            min(
                range(k),
                key=lambda cluster: _squared_distance(row, centroids[cluster]),
            )
            for row in values
        )
        if len(set(assignments)) != k:
            return _KmeansResult(
                assignments=(),
                centroids=(),
                status=CONFORMATION_CLUSTERING_CANDIDATE_EMPTY_CLUSTER,
                n_iterations=iteration,
                converged=False,
            )
        centroids = _updated_centroids(values, assignments, k)
        if assignments == previous_assignments:
            return _KmeansResult(
                assignments=assignments,
                centroids=centroids,
                status=CONFORMATION_CLUSTERING_CANDIDATE_VALID,
                n_iterations=iteration,
                converged=True,
            )
        previous_assignments = assignments
    assert previous_assignments is not None
    return _KmeansResult(
        assignments=previous_assignments,
        centroids=centroids,
        status=CONFORMATION_CLUSTERING_CANDIDATE_VALID,
        n_iterations=max_iterations,
        converged=False,
    )


def _initialize_centroids(
    values: tuple[_Vector, ...],
    frame_indexes: tuple[int, ...],
    k: int,
) -> tuple[_Centroid, ...]:
    first = min(
        range(len(values)),
        key=lambda index: (values[index], frame_indexes[index]),
    )
    chosen = [first]
    while len(chosen) < k:
        remaining = (index for index in range(len(values)) if index not in chosen)
        next_index = min(
            remaining,
            key=lambda index: (
                -min(
                    _squared_distance(values[index], values[chosen_index])
                    for chosen_index in chosen
                ),
                frame_indexes[index],
            ),
        )
        chosen.append(next_index)
    return tuple(tuple(float(value) for value in values[index]) for index in chosen)


def _updated_centroids(
    values: tuple[_Vector, ...],
    assignments: tuple[int, ...],
    k: int,
) -> tuple[_Centroid, ...]:
    n_features = len(values[0])
    members = tuple(
        tuple(index for index, label in enumerate(assignments) if label == cluster)
        for cluster in range(k)
    )
    return tuple(
        tuple(
            math.fsum(values[index][column] for index in cluster_members)
            / len(cluster_members)
            for column in range(n_features)
        )
        for cluster_members in members
    )


def _silhouette_score(
    values: tuple[_Vector, ...], assignments: tuple[int, ...]
) -> float:
    clusters = tuple(sorted(set(assignments)))
    n_frames = len(values)
    if not (2 <= len(clusters) <= n_frames - 1):
        raise ConformationClusteringError("silhouette labels are not valid")
    members = {
        cluster: tuple(
            index for index, assigned in enumerate(assignments) if assigned == cluster
        )
        for cluster in clusters
    }
    samples: list[float] = []
    for index, own_cluster in enumerate(assignments):
        own_members = tuple(
            member for member in members[own_cluster] if member != index
        )
        if not own_members:
            samples.append(0.0)
            continue
        a = math.fsum(
            _euclidean_distance(values[index], values[member])
            for member in own_members
        ) / len(own_members)
        b = min(
            math.fsum(
                _euclidean_distance(values[index], values[member])
                for member in members[cluster]
            )
            / len(members[cluster])
            for cluster in clusters
            if cluster != own_cluster
        )
        denominator = max(a, b)
        samples.append(0.0 if denominator == 0.0 else (b - a) / denominator)
    return math.fsum(samples) / n_frames


def _computed_rows(
    fingerprints: ContactFingerprintMatrix,
    values: tuple[_Vector, ...],
    result: _KmeansResult,
    *,
    selected_k: int,
    silhouette_score: float,
    metadata: _ClusteringMetadata,
) -> tuple[ConformationLabelRow, ...]:
    members = {
        cluster: tuple(
            index
            for index, assigned in enumerate(result.assignments)
            if assigned == cluster
        )
        for cluster in range(selected_k)
    }
    ordered_clusters = tuple(
        sorted(
            members,
            key=lambda cluster: min(
                fingerprints.frames[index].frame_index for index in members[cluster]
            ),
        )
    )
    state_by_cluster = {
        cluster: state_id
        for state_id, cluster in enumerate(ordered_clusters, start=1)
    }
    representatives = {
        cluster: min(
            members[cluster],
            key=lambda index: (
                _squared_distance(values[index], result.centroids[cluster]),
                fingerprints.frames[index].frame_index,
            ),
        )
        for cluster in ordered_clusters
    }
    rows = []
    for index, frame in enumerate(fingerprints.frames):
        cluster = result.assignments[index]
        state_id = state_by_cluster[cluster]
        rows.append(
            ConformationLabelRow(
                condition=fingerprints.condition,
                row_index=frame.row_index,
                frame_index=frame.frame_index,
                time_ps=frame.time_ps,
                state_id=state_id,
                cluster_label=f"state_{state_id}",
                selected_k=selected_k,
                silhouette_score=silhouette_score,
                is_representative=index == representatives[cluster],
                distance_to_centroid=_squared_distance(
                    values[index], result.centroids[cluster]
                ),
                algorithm=metadata.algorithm,
                input_source=metadata.input_source,
                pca_status=metadata.pca_status,
                notebook_parity=metadata.notebook_parity,
                status=CONFORMATION_CLUSTERING_STATUS_COMPUTED,
                notes=metadata.computed_note,
            )
        )
    return tuple(rows)


def _skipped_clustering(
    fingerprints: ContactFingerprintMatrix,
    status: str,
    reason: str,
    *,
    candidates: tuple[ConformationClusteringCandidate, ...] = (),
    metadata: _ClusteringMetadata,
) -> ConformationClustering:
    notes = f"{reason}; {metadata.skipped_note}"
    rows = tuple(
        ConformationLabelRow(
            condition=fingerprints.condition,
            row_index=frame.row_index,
            frame_index=frame.frame_index,
            time_ps=frame.time_ps,
            state_id=None,
            cluster_label=None,
            selected_k=None,
            silhouette_score=None,
            is_representative=None,
            distance_to_centroid=None,
            algorithm=metadata.algorithm,
            input_source=metadata.input_source,
            pca_status=metadata.pca_status,
            notebook_parity=metadata.notebook_parity,
            status=status,
            notes=notes,
        )
        for frame in fingerprints.frames
    )
    clustering = ConformationClustering(
        condition=fingerprints.condition,
        rows=rows,
        candidates=candidates,
        selected_k=None,
        silhouette_score=None,
        status=status,
        notes=notes,
    )
    _validate_clustering(clustering)
    return clustering


def _validate_fingerprints(fingerprints: ContactFingerprintMatrix) -> None:
    n_frames, n_features = fingerprints.shape
    if len(fingerprints.values) != n_frames:
        raise ConformationClusteringError(
            "fingerprint row count does not match frames"
        )
    frame_indexes: set[int] = set()
    for row_index, (frame, values) in enumerate(
        zip(fingerprints.frames, fingerprints.values, strict=True)
    ):
        if frame.condition != fingerprints.condition:
            raise ConformationClusteringError(
                "fingerprint frame condition does not match matrix"
            )
        if frame.row_index != row_index:
            raise ConformationClusteringError(
                "fingerprint frame row_index must match deterministic row order"
            )
        if frame.frame_index in frame_indexes:
            raise ConformationClusteringError(
                "fingerprint frame_index values must be unique"
            )
        frame_indexes.add(frame.frame_index)
        if len(values) != n_features:
            raise ConformationClusteringError(
                "fingerprint column count does not match features"
            )
        if any(type(value) is not int or value not in (0, 1) for value in values):
            raise ConformationClusteringError(
                "fingerprint values must be binary integers"
            )
    for column_index, feature in enumerate(fingerprints.features):
        if feature.condition != fingerprints.condition:
            raise ConformationClusteringError(
                "fingerprint feature condition does not match matrix"
            )
        if feature.column_index != column_index:
            raise ConformationClusteringError(
                "fingerprint feature column_index must match deterministic order"
            )


def _validate_clustering(clustering: ConformationClustering) -> None:
    if clustering.status not in _STATUSES:
        raise ConformationClusteringError("unsupported conformation status")
    if clustering.status == CONFORMATION_CLUSTERING_STATUS_EMPTY_INPUT:
        if clustering.rows:
            raise ConformationClusteringError("empty input must not contain rows")
    expected_metadata: tuple[str, str, str, str] | None = None
    for expected_row_index, row in enumerate(clustering.rows):
        if row.condition != clustering.condition:
            raise ConformationClusteringError(
                "conformation row condition does not match"
            )
        if row.row_index != expected_row_index:
            raise ConformationClusteringError(
                "conformation row_index must match deterministic row order"
            )
        if (
            row.status != clustering.status
            or row.notes != clustering.notes
        ):
            raise ConformationClusteringError(
                "conformation row metadata does not match clustering"
            )
        _validate_row_mode_metadata(row)
        row_metadata = (
            row.algorithm,
            row.input_source,
            row.pca_status,
            row.notebook_parity,
        )
        if expected_metadata is None:
            expected_metadata = row_metadata
        elif row_metadata != expected_metadata:
            raise ConformationClusteringError(
                "conformation rows must use one clustering basis"
            )
    if clustering.status == CONFORMATION_CLUSTERING_STATUS_COMPUTED:
        if clustering.selected_k is None or clustering.silhouette_score is None:
            raise ConformationClusteringError(
                "computed clustering must contain k and silhouette"
            )
        for row in clustering.rows:
            if (
                row.state_id is None
                or row.cluster_label is None
                or row.selected_k != clustering.selected_k
                or row.silhouette_score != clustering.silhouette_score
                or row.is_representative is None
                or row.distance_to_centroid is None
            ):
                raise ConformationClusteringError(
                    "computed row is missing clustering values"
                )
        state_ids = {row.state_id for row in clustering.rows}
        if state_ids != set(range(1, clustering.selected_k + 1)):
            raise ConformationClusteringError("computed state IDs are not consecutive")
        for state_id in state_ids:
            if sum(
                row.state_id == state_id and row.is_representative is True
                for row in clustering.rows
            ) != 1:
                raise ConformationClusteringError(
                    "each state must have exactly one representative"
                )
    else:
        if clustering.selected_k is not None or clustering.silhouette_score is not None:
            raise ConformationClusteringError(
                "skipped clustering must not contain selected values"
            )
        for row in clustering.rows:
            optional_values = (
                row.state_id,
                row.cluster_label,
                row.selected_k,
                row.silhouette_score,
                row.is_representative,
                row.distance_to_centroid,
            )
            if any(value is not None for value in optional_values):
                raise ConformationClusteringError(
                    "skipped row must not contain invented clustering values"
                )


def _squared_distance(
    left: tuple[int | float, ...], right: tuple[int | float, ...]
) -> float:
    return math.fsum((left[index] - right[index]) ** 2 for index in range(len(left)))


def _euclidean_distance(left: _Vector, right: _Vector) -> float:
    return math.sqrt(_squared_distance(left, right))


def _csv_value(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ConformationClusteringError("CSV numerical values must be finite")
        return format(value, ".15g")
    return value


def _validate_row_mode_metadata(row: ConformationLabelRow) -> None:
    if row.algorithm == CONFORMATION_CLUSTERING_ALGORITHM_FINGERPRINT:
        if row.input_source != CONFORMATION_CLUSTERING_INPUT_SOURCE_FINGERPRINT:
            raise ConformationClusteringError(
                "conformation row metadata does not match clustering basis"
            )
        if row.pca_status not in _PCA_STATUSES:
            raise ConformationClusteringError(
                "unsupported fingerprint clustering PCA status"
            )
        if (
            row.notebook_parity
            != CONFORMATION_CLUSTERING_NOTEBOOK_PARITY_FINGERPRINT
        ):
            raise ConformationClusteringError(
                "conformation row metadata does not match clustering basis"
            )
        return
    elif row.algorithm == CONFORMATION_CLUSTERING_ALGORITHM_PCA:
        expected = (
            CONFORMATION_CLUSTERING_INPUT_SOURCE_PCA,
            CONFORMATION_PCA_STATUS_COMPUTED,
            CONFORMATION_CLUSTERING_NOTEBOOK_PARITY_PCA,
        )
    else:
        raise ConformationClusteringError(
            "unsupported conformation clustering algorithm"
        )
    if (row.input_source, row.pca_status, row.notebook_parity) != expected:
        raise ConformationClusteringError(
            "conformation row metadata does not match clustering basis"
        )


__all__ = [
    "CONFORMATION_CLUSTERING_ALGORITHM",
    "CONFORMATION_CLUSTERING_ALGORITHM_FINGERPRINT",
    "CONFORMATION_CLUSTERING_ALGORITHM_PCA",
    "CONFORMATION_CLUSTERING_BASES",
    "CONFORMATION_CLUSTERING_BASIS_FINGERPRINT",
    "CONFORMATION_CLUSTERING_BASIS_PCA",
    "CONFORMATION_CLUSTERING_CANDIDATE_EMPTY_CLUSTER",
    "CONFORMATION_CLUSTERING_CANDIDATE_VALID",
    "CONFORMATION_CLUSTERING_INPUT_SOURCE",
    "CONFORMATION_CLUSTERING_INPUT_SOURCE_FINGERPRINT",
    "CONFORMATION_CLUSTERING_INPUT_SOURCE_PCA",
    "CONFORMATION_CLUSTERING_K_MAX",
    "CONFORMATION_CLUSTERING_NOTEBOOK_PARITY",
    "CONFORMATION_CLUSTERING_NOTEBOOK_PARITY_FINGERPRINT",
    "CONFORMATION_CLUSTERING_NOTEBOOK_PARITY_PCA",
    "CONFORMATION_CLUSTERING_PCA_STATUS",
    "CONFORMATION_CLUSTERING_PCA_STATUS_NOT_USED",
    "CONFORMATION_CLUSTERING_STATUS_COMPUTED",
    "CONFORMATION_CLUSTERING_STATUS_CONSTANT_MATRIX",
    "CONFORMATION_CLUSTERING_STATUS_EMPTY_INPUT",
    "CONFORMATION_CLUSTERING_STATUS_INSUFFICIENT_FRAMES",
    "CONFORMATION_CLUSTERING_STATUS_NO_FEATURES",
    "CONFORMATION_CLUSTERING_STATUS_NO_VALID_K",
    "CONFORMATION_LABELS_COLUMNS",
    "ConformationClustering",
    "ConformationClusteringBasis",
    "ConformationClusteringCandidate",
    "ConformationClusteringConfig",
    "ConformationClusteringError",
    "ConformationLabelRow",
    "build_conformation_clusters",
    "write_conformation_labels_csv",
]
