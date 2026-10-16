"""Dependency-free geometry helpers for typed trajectory interactions."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TypeAlias

Coordinate: TypeAlias = tuple[float, float, float]

AROMATIC_PI_PARALLEL_MAX_ANGLE_DEG = 30.0
AROMATIC_PI_TSHAPED_MIN_ANGLE_DEG = 60.0
AROMATIC_PI_TSHAPED_MAX_ANGLE_DEG = 120.0
# MANIA_preprocessing_v1_2 uses 7.0 Å for aromatic ring centroids.
AROMATIC_PI_MAX_CENTROID_DISTANCE_A = 7.0
CATION_PI_MAX_DISTANCE_A = 6.0

_JACOBI_MAX_ITERATIONS = 32
_GEOMETRY_TOLERANCE = 1e-12


@dataclass(frozen=True)
class AromaticRingGeometry:
    """Centroid and deterministic unit normal for one aromatic ring."""

    centroid: Coordinate
    normal: Coordinate


@dataclass(frozen=True)
class AromaticPiGeometry:
    """Accepted aromatic π–π geometry for one ring pair."""

    distance_A: float
    normal_angle_deg: float
    mode: str


def build_aromatic_ring_geometry(
    coordinates: tuple[Coordinate, ...],
) -> AromaticRingGeometry | None:
    """Return best-fit-plane ring geometry, or ``None`` when degenerate."""
    if len(coordinates) < 3:
        return None
    if any(
        len(coordinate) != 3
        or any(not math.isfinite(value) for value in coordinate)
        for coordinate in coordinates
    ):
        return None

    coordinate_count = len(coordinates)
    centroid: Coordinate = (
        sum(coordinate[0] for coordinate in coordinates) / coordinate_count,
        sum(coordinate[1] for coordinate in coordinates) / coordinate_count,
        sum(coordinate[2] for coordinate in coordinates) / coordinate_count,
    )
    centered = tuple(
        tuple(coordinate[axis] - centroid[axis] for axis in range(3))
        for coordinate in coordinates
    )
    covariance = [
        [
            sum(vector[row] * vector[column] for vector in centered)
            for column in range(3)
        ]
        for row in range(3)
    ]
    eigenvalues, eigenvectors = _symmetric_eigendecomposition(covariance)
    ordered_indexes = sorted(range(3), key=lambda index: eigenvalues[index])
    largest_eigenvalue = eigenvalues[ordered_indexes[-1]]
    second_eigenvalue = eigenvalues[ordered_indexes[1]]
    if (
        largest_eigenvalue <= _GEOMETRY_TOLERANCE
        or second_eigenvalue
        <= _GEOMETRY_TOLERANCE * max(1.0, largest_eigenvalue)
    ):
        return None

    normal_index = ordered_indexes[0]
    normal: Coordinate = (
        eigenvectors[0][normal_index],
        eigenvectors[1][normal_index],
        eigenvectors[2][normal_index],
    )
    normalized = _normalized_vector(normal)
    if normalized is None:
        return None
    return AromaticRingGeometry(
        centroid=(centroid[0], centroid[1], centroid[2]),
        normal=_deterministic_vector_sign(normalized),
    )


def sign_invariant_normal_angle_deg(
    first_normal: Coordinate,
    second_normal: Coordinate,
) -> float | None:
    """Return the acute axis angle; opposite normal signs are equivalent."""
    first = _normalized_vector(first_normal)
    second = _normalized_vector(second_normal)
    if first is None or second is None:
        return None
    cosine = abs(sum(left * right for left, right in zip(first, second, strict=True)))
    return math.degrees(math.acos(max(0.0, min(1.0, cosine))))


def classify_aromatic_pi_angle(normal_angle_deg: float) -> str | None:
    """Classify a sign-invariant ring-normal angle."""
    if not math.isfinite(normal_angle_deg) or normal_angle_deg < 0:
        return None
    if normal_angle_deg < AROMATIC_PI_PARALLEL_MAX_ANGLE_DEG:
        return "parallel"
    if (
        AROMATIC_PI_TSHAPED_MIN_ANGLE_DEG
        <= normal_angle_deg
        <= AROMATIC_PI_TSHAPED_MAX_ANGLE_DEG
    ):
        return "t_shaped"
    return None


def detect_aromatic_pi_geometry(
    first_ring: AromaticRingGeometry,
    second_ring: AromaticRingGeometry,
) -> AromaticPiGeometry | None:
    """Return accepted aromatic π–π geometry for two rings."""
    distance = coordinate_distance(first_ring.centroid, second_ring.centroid)
    if distance > AROMATIC_PI_MAX_CENTROID_DISTANCE_A:
        return None
    angle = sign_invariant_normal_angle_deg(
        first_ring.normal,
        second_ring.normal,
    )
    if angle is None:
        return None
    mode = classify_aromatic_pi_angle(angle)
    if mode is None:
        return None
    return AromaticPiGeometry(
        distance_A=distance,
        normal_angle_deg=angle,
        mode=mode,
    )


def detect_cation_pi_distance(
    cation_center: Coordinate,
    ring_centroid: Coordinate,
) -> float | None:
    """Return cation-to-centroid distance when strictly below 6.0 Å."""
    distance = coordinate_distance(cation_center, ring_centroid)
    if distance >= CATION_PI_MAX_DISTANCE_A:
        return None
    return distance


def coordinate_distance(first: Coordinate, second: Coordinate) -> float:
    """Return Euclidean distance between two 3D coordinates."""
    return math.sqrt(
        sum(
            (left - right) ** 2
            for left, right in zip(first, second, strict=True)
        )
    )


def coordinate_angle_deg(
    first: Coordinate,
    vertex: Coordinate,
    third: Coordinate,
) -> float | None:
    """Return the angle formed at ``vertex``, or ``None`` if degenerate."""
    first_vector: Coordinate = (
        first[0] - vertex[0],
        first[1] - vertex[1],
        first[2] - vertex[2],
    )
    third_vector: Coordinate = (
        third[0] - vertex[0],
        third[1] - vertex[1],
        third[2] - vertex[2],
    )
    first_normalized = _normalized_vector(first_vector)
    third_normalized = _normalized_vector(third_vector)
    if first_normalized is None or third_normalized is None:
        return None
    cosine = sum(
        left * right
        for left, right in zip(first_normalized, third_normalized, strict=True)
    )
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def _normalized_vector(vector: Coordinate) -> Coordinate | None:
    if any(not math.isfinite(value) for value in vector):
        return None
    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude <= _GEOMETRY_TOLERANCE:
        return None
    return (
        vector[0] / magnitude,
        vector[1] / magnitude,
        vector[2] / magnitude,
    )


def _deterministic_vector_sign(vector: Coordinate) -> Coordinate:
    pivot = max(range(3), key=lambda index: (abs(vector[index]), -index))
    if vector[pivot] < 0:
        return -vector[0], -vector[1], -vector[2]
    return vector


def _symmetric_eigendecomposition(
    matrix: list[list[float]],
) -> tuple[tuple[float, float, float], list[list[float]]]:
    """Diagonalize one real symmetric 3×3 matrix with Jacobi rotations."""
    values = [row[:] for row in matrix]
    vectors = [
        [1.0 if row == column else 0.0 for column in range(3)]
        for row in range(3)
    ]
    off_diagonal_pairs = ((0, 1), (0, 2), (1, 2))
    for _ in range(_JACOBI_MAX_ITERATIONS):
        row, column = max(
            off_diagonal_pairs,
            key=lambda pair: abs(values[pair[0]][pair[1]]),
        )
        off_diagonal = values[row][column]
        if abs(off_diagonal) <= _GEOMETRY_TOLERANCE:
            break
        tau = (
            values[column][column] - values[row][row]
        ) / (2.0 * off_diagonal)
        tangent = (
            1.0
            if tau == 0.0
            else math.copysign(
                1.0 / (abs(tau) + math.sqrt(1.0 + tau * tau)),
                tau,
            )
        )
        cosine = 1.0 / math.sqrt(1.0 + tangent * tangent)
        sine = tangent * cosine

        row_value = values[row][row]
        column_value = values[column][column]
        values[row][row] = (
            cosine * cosine * row_value
            - 2.0 * sine * cosine * off_diagonal
            + sine * sine * column_value
        )
        values[column][column] = (
            sine * sine * row_value
            + 2.0 * sine * cosine * off_diagonal
            + cosine * cosine * column_value
        )
        values[row][column] = 0.0
        values[column][row] = 0.0

        for axis in range(3):
            if axis in (row, column):
                continue
            row_axis = values[row][axis]
            column_axis = values[column][axis]
            values[row][axis] = cosine * row_axis - sine * column_axis
            values[axis][row] = values[row][axis]
            values[column][axis] = sine * row_axis + cosine * column_axis
            values[axis][column] = values[column][axis]

        for axis in range(3):
            vector_row = vectors[axis][row]
            vector_column = vectors[axis][column]
            vectors[axis][row] = cosine * vector_row - sine * vector_column
            vectors[axis][column] = sine * vector_row + cosine * vector_column

    eigenvalues = (
        max(0.0, values[0][0]),
        max(0.0, values[1][1]),
        max(0.0, values[2][2]),
    )
    return eigenvalues, vectors


__all__ = [
    "AROMATIC_PI_MAX_CENTROID_DISTANCE_A",
    "AROMATIC_PI_PARALLEL_MAX_ANGLE_DEG",
    "AROMATIC_PI_TSHAPED_MAX_ANGLE_DEG",
    "AROMATIC_PI_TSHAPED_MIN_ANGLE_DEG",
    "CATION_PI_MAX_DISTANCE_A",
    "AromaticPiGeometry",
    "AromaticRingGeometry",
    "build_aromatic_ring_geometry",
    "classify_aromatic_pi_angle",
    "coordinate_angle_deg",
    "coordinate_distance",
    "detect_aromatic_pi_geometry",
    "detect_cation_pi_distance",
    "sign_invariant_normal_angle_deg",
]
