"""Deterministic Stage 22.E contact-fingerprint PCA artifact contract."""

from __future__ import annotations

import csv
import importlib
import math
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from mania.analysis.contact_fingerprints import ContactFingerprintMatrix

CONFORMATION_PCA_STATUS_COMPUTED = "computed"
CONFORMATION_PCA_STATUS_EMPTY_INPUT = "empty_input"
CONFORMATION_PCA_STATUS_ONE_FRAME = "one_frame"
CONFORMATION_PCA_STATUS_NO_FEATURES = "no_features"
CONFORMATION_PCA_STATUS_CONSTANT_MATRIX = "constant_matrix"
CONFORMATION_PCA_STATUS_UNAVAILABLE = "pca_unavailable"
CONFORMATION_PCA_STATUS_FAILED = "pca_failed"
CONFORMATION_PCA_DEFAULT_MAX_COMPONENTS = 10
CONFORMATION_PCA_EXPORTED_COMPONENT_LIMIT = 3

_NON_COMPUTED_STATUSES = {
    CONFORMATION_PCA_STATUS_EMPTY_INPUT,
    CONFORMATION_PCA_STATUS_ONE_FRAME,
    CONFORMATION_PCA_STATUS_NO_FEATURES,
    CONFORMATION_PCA_STATUS_CONSTANT_MATRIX,
    CONFORMATION_PCA_STATUS_UNAVAILABLE,
    CONFORMATION_PCA_STATUS_FAILED,
}
_STATUSES = _NON_COMPUTED_STATUSES | {CONFORMATION_PCA_STATUS_COMPUTED}

CONFORMATION_PCA_COLUMNS = (
    "condition",
    "row_index",
    "frame_index",
    "time_ps",
    "pc1",
    "pc2",
    "pc3",
    "explained_variance_ratio_pc1",
    "explained_variance_ratio_pc2",
    "explained_variance_ratio_pc3",
    "n_components",
    "n_features",
    "n_frames",
    "status",
    "notes",
)


class ConformationPcaError(ValueError):
    """Raised when a fingerprint matrix cannot form the PCA artifact contract."""


class _PcaComputationFailed(ValueError):
    """Raised when NumPy cannot produce finite deterministic PCA values."""


@dataclass(frozen=True)
class ConformationPcaRow:
    """Projection metadata and optional coordinates for one fingerprint frame."""

    condition: str
    row_index: int
    frame_index: int
    time_ps: float | None
    pc1: float | None
    pc2: float | None
    pc3: float | None
    explained_variance_ratio_pc1: float | None
    explained_variance_ratio_pc2: float | None
    explained_variance_ratio_pc3: float | None
    n_components: int
    n_features: int
    n_frames: int
    status: str
    notes: str

    def to_dict(self) -> dict[str, object]:
        """Return one row in stable artifact column order."""
        return {
            column: getattr(self, column) for column in CONFORMATION_PCA_COLUMNS
        }


@dataclass(frozen=True)
class ConformationPcaProjection:
    """Stage 22.E projection result for one condition."""

    condition: str
    rows: tuple[ConformationPcaRow, ...]
    n_components: int
    n_features: int
    n_frames: int
    status: str
    notes: str
    max_components: int = CONFORMATION_PCA_DEFAULT_MAX_COMPONENTS
    score_vectors: tuple[tuple[float, ...], ...] = ()
    explained_variance_ratios: tuple[float, ...] = ()

    @property
    def computed_component_count(self) -> int:
        """Return the actual internal component count."""
        if self.status != CONFORMATION_PCA_STATUS_COMPUTED:
            return 0
        return self.n_components

    @property
    def exported_component_count(self) -> int:
        """Return the public CSV component count."""
        return min(
            CONFORMATION_PCA_EXPORTED_COMPONENT_LIMIT,
            self.computed_component_count,
        )


@dataclass(frozen=True)
class _ComputedPcaValues:
    scores: tuple[tuple[float, ...], ...]
    explained_variance_ratios: tuple[float, ...]
    n_components: int


def build_conformation_pca_projection(
    fingerprints: ContactFingerprintMatrix,
    *,
    enable_pca: bool = False,
    max_pca_components: int = CONFORMATION_PCA_DEFAULT_MAX_COMPONENTS,
) -> ConformationPcaProjection:
    """Build a truthful PCA artifact result from accepted Stage 22.D values.

    PCA computation is opt-in. With ``enable_pca=False`` the Stage 22.E
    non-degenerate fallback remains ``pca_unavailable`` with blank numerical
    fields. With ``enable_pca=True`` non-degenerate fingerprints are centered
    and projected with NumPy SVD.
    """
    if not isinstance(fingerprints, ContactFingerprintMatrix):
        raise TypeError("fingerprints must be a ContactFingerprintMatrix")
    if type(enable_pca) is not bool:
        raise TypeError("enable_pca must be a bool")
    _validate_max_pca_components(max_pca_components)
    _validate_fingerprints(fingerprints)

    n_frames, n_features = fingerprints.shape
    if not n_frames:
        return _skipped_projection(
            fingerprints,
            CONFORMATION_PCA_STATUS_EMPTY_INPUT,
            "fingerprint matrix contains no frames",
            max_components=max_pca_components,
        )
    if not n_features:
        return _skipped_projection(
            fingerprints,
            CONFORMATION_PCA_STATUS_NO_FEATURES,
            "fingerprint matrix contains no features",
            max_components=max_pca_components,
        )
    if n_frames == 1:
        return _skipped_projection(
            fingerprints,
            CONFORMATION_PCA_STATUS_ONE_FRAME,
            "PCA requires at least two frames",
            max_components=max_pca_components,
        )
    if _total_centered_sum_of_squares(fingerprints.values) == 0.0:
        return _skipped_projection(
            fingerprints,
            CONFORMATION_PCA_STATUS_CONSTANT_MATRIX,
            "centered fingerprint matrix has zero total variance",
            max_components=max_pca_components,
        )
    if not enable_pca:
        return _skipped_projection(
            fingerprints,
            CONFORMATION_PCA_STATUS_UNAVAILABLE,
            "PCA computation was not requested; enable_pca=False",
            max_components=max_pca_components,
        )

    try:
        computed = _compute_pca_values(
            fingerprints,
            max_components=max_pca_components,
        )
    except (
        FloatingPointError,
        ImportError,
        ModuleNotFoundError,
        _PcaComputationFailed,
    ):
        return _skipped_projection(
            fingerprints,
            CONFORMATION_PCA_STATUS_FAILED,
            "PCA computation failed during NumPy SVD",
            max_components=max_pca_components,
        )

    rows = []
    ratios = _exported_components(computed.explained_variance_ratios)
    for row_index, frame in enumerate(fingerprints.frames):
        scores = _exported_components(computed.scores[row_index])
        rows.append(
            ConformationPcaRow(
                condition=fingerprints.condition,
                row_index=frame.row_index,
                frame_index=frame.frame_index,
                time_ps=frame.time_ps,
                pc1=scores[0],
                pc2=scores[1],
                pc3=scores[2],
                explained_variance_ratio_pc1=ratios[0],
                explained_variance_ratio_pc2=ratios[1],
                explained_variance_ratio_pc3=ratios[2],
                n_components=computed.n_components,
                n_features=n_features,
                n_frames=n_frames,
                status=CONFORMATION_PCA_STATUS_COMPUTED,
                notes="computed with centered NumPy SVD; notebook parity not claimed",
            )
        )
    projection = ConformationPcaProjection(
        condition=fingerprints.condition,
        rows=tuple(rows),
        n_components=computed.n_components,
        n_features=n_features,
        n_frames=n_frames,
        status=CONFORMATION_PCA_STATUS_COMPUTED,
        notes="computed with centered NumPy SVD; notebook parity not claimed",
        max_components=max_pca_components,
        score_vectors=computed.scores,
        explained_variance_ratios=computed.explained_variance_ratios,
    )
    _validate_projection(projection)
    return projection


def _skipped_projection(
    fingerprints: ContactFingerprintMatrix,
    status: str,
    notes: str,
    *,
    max_components: int = CONFORMATION_PCA_DEFAULT_MAX_COMPONENTS,
) -> ConformationPcaProjection:
    n_frames, n_features = fingerprints.shape
    rows = tuple(
        ConformationPcaRow(
            condition=fingerprints.condition,
            row_index=frame.row_index,
            frame_index=frame.frame_index,
            time_ps=frame.time_ps,
            pc1=None,
            pc2=None,
            pc3=None,
            explained_variance_ratio_pc1=None,
            explained_variance_ratio_pc2=None,
            explained_variance_ratio_pc3=None,
            n_components=0,
            n_features=n_features,
            n_frames=n_frames,
            status=status,
            notes=notes,
        )
        for frame in fingerprints.frames
    )
    projection = ConformationPcaProjection(
        condition=fingerprints.condition,
        rows=rows,
        n_components=0,
        n_features=n_features,
        n_frames=n_frames,
        status=status,
        notes=notes,
        max_components=max_components,
    )
    _validate_projection(projection)
    return projection


def write_conformation_pca_csv(
    projection: ConformationPcaProjection,
    output_dir: str | Path,
) -> Path:
    """Write ``conformation_pca_{condition}.csv`` atomically and stably."""
    if not isinstance(projection, ConformationPcaProjection):
        raise TypeError("projection must be a ConformationPcaProjection")
    _validate_projection(projection)
    component = re.sub(r"[^A-Za-z0-9_.-]+", "_", projection.condition).strip(
        "._"
    )
    if not component:
        raise ConformationPcaError(
            "condition must contain a filename-safe character"
        )
    directory = Path(output_dir)
    if directory.exists() and not directory.is_dir():
        raise ConformationPcaError("conformation PCA output is not a directory")
    output_path = directory / f"conformation_pca_{component}.csv"
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
                fieldnames=CONFORMATION_PCA_COLUMNS,
                lineterminator="\n",
            )
            writer.writeheader()
            for row in projection.rows:
                writer.writerow(
                    {key: _csv_value(value) for key, value in row.to_dict().items()}
                )
        temporary_path.replace(output_path)
    except (OSError, csv.Error) as error:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise ConformationPcaError(
            f"conformation PCA could not be written: {output_path}"
        ) from error
    return output_path


def _validate_fingerprints(fingerprints: ContactFingerprintMatrix) -> None:
    n_frames, n_features = fingerprints.shape
    if len(fingerprints.values) != n_frames:
        raise ConformationPcaError("fingerprint row count does not match frames")
    for row_index, (frame, values) in enumerate(
        zip(fingerprints.frames, fingerprints.values, strict=True)
    ):
        if frame.condition != fingerprints.condition:
            raise ConformationPcaError(
                "fingerprint frame condition does not match matrix"
            )
        if frame.row_index != row_index:
            raise ConformationPcaError(
                "fingerprint frame row_index must match deterministic row order"
            )
        if len(values) != n_features:
            raise ConformationPcaError(
                "fingerprint column count does not match features"
            )
        if any(type(value) is not int or value not in (0, 1) for value in values):
            raise ConformationPcaError("fingerprint values must be binary integers")
    for column_index, feature in enumerate(fingerprints.features):
        if feature.condition != fingerprints.condition:
            raise ConformationPcaError(
                "fingerprint feature condition does not match matrix"
            )
        if feature.column_index != column_index:
            raise ConformationPcaError(
                "fingerprint feature column_index must match deterministic order"
            )


def _validate_max_pca_components(max_pca_components: object) -> None:
    if type(max_pca_components) is not int or max_pca_components < 1:
        raise ConformationPcaError("max_pca_components must be an integer >= 1")


def _total_centered_sum_of_squares(
    values: tuple[tuple[int, ...], ...],
) -> float:
    n_frames = len(values)
    n_features = len(values[0])
    means = tuple(
        math.fsum(row[column] for row in values) / n_frames
        for column in range(n_features)
    )
    return math.fsum(
        (value - means[column]) ** 2
        for row in values
        for column, value in enumerate(row)
    )


def _compute_pca_values(
    fingerprints: ContactFingerprintMatrix,
    *,
    max_components: int,
) -> _ComputedPcaValues:
    np = _numpy()
    n_frames, n_features = fingerprints.shape
    matrix = np.asarray(fingerprints.values, dtype=np.float64)
    if matrix.shape != (n_frames, n_features):
        raise _PcaComputationFailed("unexpected fingerprint matrix shape")
    if not bool(np.isfinite(matrix).all()):
        raise _PcaComputationFailed("fingerprint matrix contains non-finite values")

    with np.errstate(all="raise"):
        centered = matrix - matrix.mean(axis=0, keepdims=True)
    if not bool(np.isfinite(centered).all()):
        raise _PcaComputationFailed("centered matrix contains non-finite values")

    try:
        u, singular_values, loadings = np.linalg.svd(centered, full_matrices=False)
    except np.linalg.LinAlgError as error:
        raise _PcaComputationFailed("NumPy SVD failed") from error
    if not (
        bool(np.isfinite(u).all())
        and bool(np.isfinite(singular_values).all())
        and bool(np.isfinite(loadings).all())
    ):
        raise _PcaComputationFailed("SVD returned non-finite values")

    if singular_values.size == 0:
        raise _PcaComputationFailed("SVD returned no singular values")
    with np.errstate(all="raise"):
        total_variance_numerator = float(np.sum(singular_values * singular_values))
    if not math.isfinite(total_variance_numerator) or total_variance_numerator <= 0.0:
        raise _PcaComputationFailed("centered matrix has no finite variance")

    numerical_rank = _numerical_rank(np, singular_values, n_frames, n_features)
    n_components = min(max_components, n_frames - 1, n_features, numerical_rank)
    if n_components <= 0:
        raise _PcaComputationFailed("centered matrix has insufficient rank")

    with np.errstate(all="raise"):
        scores = u[:, :n_components] * singular_values[:n_components]
    for component_index in range(n_components):
        loading = loadings[component_index]
        pivot = int(np.argmax(np.abs(loading)))
        if float(loading[pivot]) < 0.0:
            loadings[component_index, :] *= -1.0
            scores[:, component_index] *= -1.0
    if not bool(np.isfinite(scores).all()):
        raise _PcaComputationFailed("PCA scores contain non-finite values")

    explained_variance_ratios = tuple(
        _finite_float(
            float(
                (
                    singular_values[component_index]
                    * singular_values[component_index]
                )
                / total_variance_numerator
            )
        )
        for component_index in range(n_components)
    )
    score_rows = tuple(
        tuple(
            _finite_float(float(scores[row_index, component_index]))
            for component_index in range(n_components)
        )
        for row_index in range(n_frames)
    )
    return _ComputedPcaValues(
        scores=score_rows,
        explained_variance_ratios=explained_variance_ratios,
        n_components=n_components,
    )


def _numpy() -> Any:
    return cast(Any, importlib.import_module("numpy"))


def _numerical_rank(
    np: Any,
    singular_values: Any,
    n_frames: int,
    n_features: int,
) -> int:
    largest = float(singular_values[0])
    if largest <= 0.0:
        return 0
    tolerance = max(n_frames, n_features) * float(np.finfo(np.float64).eps) * largest
    return int(np.sum(singular_values > tolerance))


def _finite_float(value: float) -> float:
    if not math.isfinite(value):
        raise _PcaComputationFailed("non-finite PCA value")
    if value == 0.0:
        return 0.0
    return value


def _exported_components(values: tuple[float, ...]) -> tuple[float | None, ...]:
    exported = values[:CONFORMATION_PCA_EXPORTED_COMPONENT_LIMIT]
    return exported + (None,) * (
        CONFORMATION_PCA_EXPORTED_COMPONENT_LIMIT - len(exported)
    )


def _validate_projection(projection: ConformationPcaProjection) -> None:
    if projection.n_frames != len(projection.rows):
        raise ConformationPcaError("projection n_frames does not match rows")
    if projection.status not in _STATUSES:
        raise ConformationPcaError("unsupported conformation PCA status")
    _validate_max_pca_components(projection.max_components)
    if projection.status in _NON_COMPUTED_STATUSES:
        _validate_non_computed_projection(projection)
        return
    if not 1 <= projection.n_components <= projection.max_components:
        raise ConformationPcaError(
            "computed PCA projection must have at least one component within "
            "max_components"
        )
    if projection.n_components > projection.n_frames - 1:
        raise ConformationPcaError(
            "computed PCA component count exceeds frame bound"
        )
    if projection.n_components > projection.n_features:
        raise ConformationPcaError(
            "computed PCA component count exceeds feature bound"
        )
    if len(projection.score_vectors) != projection.n_frames:
        raise ConformationPcaError(
            "computed PCA projection must retain one internal score vector per frame"
        )
    if len(projection.explained_variance_ratios) != projection.n_components:
        raise ConformationPcaError(
            "computed PCA projection must retain one variance ratio per component"
        )
    for ratio in projection.explained_variance_ratios:
        if not isinstance(ratio, float) or not math.isfinite(ratio):
            raise ConformationPcaError(
                "computed PCA explained-variance ratios must be finite"
            )
        if ratio < 0.0 or ratio > 1.0:
            raise ConformationPcaError(
                "computed PCA explained-variance ratios must be in [0, 1]"
            )
    for score_vector in projection.score_vectors:
        if len(score_vector) != projection.n_components:
            raise ConformationPcaError(
                "computed PCA score vector dimensionality does not match"
            )
        for score in score_vector:
            _validate_present_float(score)
    for expected_row_index, row in enumerate(projection.rows):
        _validate_row_metadata(projection, row, expected_row_index)
        coordinates = (row.pc1, row.pc2, row.pc3)
        ratios = (
            row.explained_variance_ratio_pc1,
            row.explained_variance_ratio_pc2,
            row.explained_variance_ratio_pc3,
        )
        score_vector = projection.score_vectors[expected_row_index]
        for component_index in range(CONFORMATION_PCA_EXPORTED_COMPONENT_LIMIT):
            if component_index < projection.exported_component_count:
                _validate_present_float(coordinates[component_index])
                _validate_present_float(ratios[component_index])
                if coordinates[component_index] != score_vector[component_index]:
                    raise ConformationPcaError(
                        "exported PCA coordinate does not match internal score"
                    )
                if (
                    ratios[component_index]
                    != projection.explained_variance_ratios[component_index]
                ):
                    raise ConformationPcaError(
                        "exported PCA ratio does not match internal variance ratio"
                    )
            elif (
                coordinates[component_index] is not None
                or ratios[component_index] is not None
            ):
                raise ConformationPcaError(
                    "unavailable PCA components must remain blank"
                )


def _validate_non_computed_projection(
    projection: ConformationPcaProjection,
) -> None:
    if projection.n_components != 0:
        raise ConformationPcaError(
            "non-computed PCA projection must have zero components"
        )
    if projection.score_vectors or projection.explained_variance_ratios:
        raise ConformationPcaError(
            "non-computed PCA projection must not contain internal scores"
        )
    for expected_row_index, row in enumerate(projection.rows):
        _validate_row_metadata(projection, row, expected_row_index)
        numerical_fields = (
            row.pc1,
            row.pc2,
            row.pc3,
            row.explained_variance_ratio_pc1,
            row.explained_variance_ratio_pc2,
            row.explained_variance_ratio_pc3,
        )
        if any(value is not None for value in numerical_fields):
            raise ConformationPcaError(
                "non-computed PCA projection must not contain numerical values"
            )


def _validate_row_metadata(
    projection: ConformationPcaProjection,
    row: ConformationPcaRow,
    expected_row_index: int,
) -> None:
    if row.condition != projection.condition:
        raise ConformationPcaError("projection row condition does not match")
    if row.row_index != expected_row_index:
        raise ConformationPcaError(
            "projection row_index must match deterministic row order"
        )
    if (
        row.n_components != projection.n_components
        or row.n_features != projection.n_features
        or row.n_frames != projection.n_frames
        or row.status != projection.status
        or row.notes != projection.notes
    ):
        raise ConformationPcaError(
            "projection row metadata does not match projection"
        )


def _validate_present_float(value: float | None) -> None:
    if not isinstance(value, float) or not math.isfinite(value):
        raise ConformationPcaError("computed PCA numerical values must be finite")


def _csv_value(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ConformationPcaError("CSV numerical values must be finite")
        if value == 0.0:
            value = 0.0
        return format(value, ".15g")
    return value


__all__ = [
    "CONFORMATION_PCA_COLUMNS",
    "CONFORMATION_PCA_DEFAULT_MAX_COMPONENTS",
    "CONFORMATION_PCA_EXPORTED_COMPONENT_LIMIT",
    "CONFORMATION_PCA_STATUS_COMPUTED",
    "CONFORMATION_PCA_STATUS_CONSTANT_MATRIX",
    "CONFORMATION_PCA_STATUS_EMPTY_INPUT",
    "CONFORMATION_PCA_STATUS_FAILED",
    "CONFORMATION_PCA_STATUS_NO_FEATURES",
    "CONFORMATION_PCA_STATUS_ONE_FRAME",
    "CONFORMATION_PCA_STATUS_UNAVAILABLE",
    "ConformationPcaError",
    "ConformationPcaProjection",
    "ConformationPcaRow",
    "build_conformation_pca_projection",
    "write_conformation_pca_csv",
]
