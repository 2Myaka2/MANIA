"""Deterministic 3840-point float64 Shrake–Rupley target-only geometry."""

from __future__ import annotations

import hashlib
import importlib
import math
import struct
from collections.abc import Iterable
from functools import lru_cache
from itertools import product
from typing import Any, Literal

from mania.preprocessing.trajectory_sasa_radii import radii_for

np = importlib.import_module("numpy")

POINT_COUNT = 3840
GRID_ID: Literal["mania.sasa.fibonacci3840.v1"] = "mania.sasa.fibonacci3840.v1"
LEGACY_GRID_ID = "mania.sasa.fibonacci960.v1"
LEGACY_GRID_SHA256 = "89662d78956cad341fdeddaddc793c36e5971c733fe9e832e6442a81399132dd"


@lru_cache(maxsize=1)
def sphere_points() -> Any:
    values: list[float] = []
    for k in range(POINT_COUNT):
        z = 1.0 - 2.0 * (k + 0.5) / POINT_COUNT
        theta = k * math.pi * (3.0 - math.sqrt(5.0))
        radial = math.sqrt(max(0.0, 1.0 - z * z))
        values.extend((radial * math.cos(theta), radial * math.sin(theta), z))
    # Immutable bytes backing: callers cannot make the cached array writable.
    return np.frombuffer(
        struct.pack(f"<{3 * POINT_COUNT}d", *values), dtype="<f8"
    ).reshape(POINT_COUNT, 3)


def grid_sha256() -> str:
    return hashlib.sha256(sphere_points().tobytes(order="C")).hexdigest()


def _coordinates(value: Any, count: int) -> Any:
    xyz = np.array(value, dtype=np.float64, copy=True)
    if xyz.shape != (count, 3) or not np.isfinite(xyz).all():
        raise ValueError("SASA requires finite corresponding xyz")
    return xyz


def _probe(value: float) -> float:
    if (
        type(value) not in (float, int)
        or not math.isfinite(value)
        or not 0.5 <= value <= 3
    ):
        raise ValueError("Probe must be a finite real in inclusive [0.5,3.0] angstrom")
    return float(value)


def validate_centers(target: Any, environment: Any) -> Any:
    """Reject invalid/coincident geometry without adding a distance tolerance."""
    centers = np.concatenate((target, environment))
    if not np.isfinite(centers).all() or len(np.unique(centers, axis=0)) != len(
        centers
    ):
        raise ValueError("Invalid or coincident selected atom centers")
    return centers


def accessibility_counts(
    target: Any,
    elements: tuple[str, ...],
    *,
    environment: Any = None,
    environment_elements: tuple[str, ...] = (),
    probe_radius_A: float = 1.4,
    variants: tuple[str, ...] = ("isolated",),
    exhaustive: bool = False,
) -> dict[str, tuple[int, ...]]:
    """Exact candidate pruning changes no point, distance or occlusion threshold.

    A cell is at least the largest possible sum of two inflated radii wide;
    only its 27 adjacent cells can contain intersecting atom spheres. Test
    against every candidate using the frozen strict point inequality. The
    exhaustive switch is a verification path, not a sampling/resource fallback.
    """
    probe = _probe(probe_radius_A)
    if (
        not variants
        or len(set(variants)) != len(variants)
        or any(v not in ("isolated", "with_environment") for v in variants)
    ):
        raise ValueError("Unknown or duplicate SASA variant")
    radii = np.array(radii_for(elements), dtype=np.float64) + probe
    targets = _coordinates(target, len(elements))
    with_environment = "with_environment" in variants
    if with_environment and not environment_elements:
        raise ValueError("with_environment requires a nonempty explicit environment")
    extra = (
        _coordinates(environment, len(environment_elements))
        if with_environment
        else np.empty((0, 3), dtype=np.float64)
    )
    extra_radii = (
        np.array(radii_for(environment_elements), dtype=np.float64) + probe
        if with_environment
        else np.empty(0, dtype=np.float64)
    )
    centers = validate_centers(targets, extra)
    inflated = np.concatenate((radii, extra_radii))
    cell_width = 2.0 * float(inflated.max())
    cells: dict[tuple[int, ...], list[int]] = {}
    for index, xyz in enumerate(centers):
        key = tuple(math.floor(float(c) / cell_width) for c in xyz)
        cells.setdefault(key, []).append(index)
    results: dict[str, list[int]] = {v: [] for v in variants}
    offsets = tuple(product((-1, 0, 1), repeat=3))
    with np.errstate(over="raise", invalid="raise"):
        for i, center in enumerate(targets):
            points = center + radii[i] * sphere_points()
            if not np.isfinite(points).all():
                raise ValueError("Nonfinite inflated target sphere")
            candidates: Iterable[int]
            if exhaustive:
                candidates = range(len(centers))
            else:
                key = tuple(math.floor(float(c) / cell_width) for c in center)
                candidates = sorted(
                    j
                    for offset in offsets
                    for j in cells.get(
                        tuple(a + b for a, b in zip(key, offset, strict=True)), ()
                    )
                )
            accessible = np.ones(POINT_COUNT, dtype=bool)
            isolated = accessible.copy()
            for j in candidates:
                if j == i:
                    continue
                delta = points - centers[j]
                blocked = (
                    np.sum(delta * delta, axis=1, dtype=np.float64) < inflated[j] ** 2
                )
                accessible &= ~blocked
                if j < len(targets):
                    isolated &= ~blocked
            for variant in variants:
                mask = isolated if variant == "isolated" else accessible
                results[variant].append(int(np.count_nonzero(mask)))
    return {key: tuple(value) for key, value in results.items()}


def atom_areas(
    counts: tuple[int, ...], elements: tuple[str, ...], probe: float
) -> tuple[float, ...]:
    return _atom_areas_for_grid(counts, elements, probe, POINT_COUNT)


def _atom_areas_for_grid(
    counts: tuple[int, ...],
    elements: tuple[str, ...],
    probe: float,
    points_per_atom: int,
) -> tuple[float, ...]:
    """Derive production or identity-validated historical measurement areas."""
    if type(points_per_atom) is not int or points_per_atom not in (960, POINT_COUNT):
        raise ValueError("Unknown SASA grid count")
    radii = radii_for(elements)
    _probe(probe)
    if len(counts) != len(radii) or any(
        type(n) is not int or not 0 <= n <= points_per_atom for n in counts
    ):
        raise ValueError(
            f"SASA counts require one integer in [0,{points_per_atom}] per target atom"
        )
    return tuple(
        (n / points_per_atom) * (4.0 * math.pi * (r + probe) ** 2)
        for n, r in zip(counts, radii, strict=True)
    )
