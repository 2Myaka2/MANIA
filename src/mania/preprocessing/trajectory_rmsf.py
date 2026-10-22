"""Streaming float64 atomic RMSF about the post-fit mean, divisor N."""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any

from mania.preprocessing.trajectory_rmsd import SourceAtomKey, _roster, identity_digest

np = importlib.import_module("numpy")


def xyz_float64(value: Any, count: int) -> Any:
    xyz = np.array(value, dtype=np.float64, copy=True)
    if count < 1 or xyz.shape != (count, 3) or not np.isfinite(xyz).all():
        raise ValueError("Expected nonempty finite float64 corresponding xyz")
    return xyz


def fit_coordinates(value: Any, count: int) -> Any:
    xyz = xyz_float64(value, count)
    if count < 3 or len(np.unique(xyz, axis=0)) != count:
        raise ValueError("Fit requires at least three unique atom positions")
    with np.errstate(over="raise", invalid="raise"):
        centered = xyz - xyz.mean(axis=0, dtype=np.float64)
        singular = np.linalg.svd(centered, compute_uv=False)
        threshold = max(count, 3) * np.finfo(np.float64).eps * singular[0]
    if not np.isfinite(singular).all() or singular[1] <= threshold:
        raise ValueError("Fit coordinates have rank below two at the frozen threshold")
    return xyz


@dataclass(frozen=True)
class RigidTransform:
    source_center: Any
    reference_center: Any
    rotation: Any

    def apply(self, evaluation: Any) -> Any:
        xyz = xyz_float64(evaluation, len(evaluation))
        with np.errstate(over="raise", invalid="raise"):
            result = (xyz - self.source_center) @ self.rotation + self.reference_center
        if not np.isfinite(result).all():
            raise ValueError("Nonfinite aligned evaluation coordinates")
        return result


def proper_transform(fit: Any, reference_fit: Any) -> RigidTransform:
    """Independently implement the retained proper Kabsch mathematical path."""
    x = fit_coordinates(fit, len(reference_fit))
    y = fit_coordinates(reference_fit, len(reference_fit))
    xc, yc = x.mean(axis=0, dtype=np.float64), y.mean(axis=0, dtype=np.float64)
    with np.errstate(over="raise", invalid="raise"):
        u, _, vt = np.linalg.svd((x - xc).T @ (y - yc))
        correction = np.eye(3, dtype=np.float64)
        correction[2, 2] = 1.0 if np.linalg.det(u @ vt) >= 0 else -1.0
        rotation = u @ correction @ vt
    if not np.isfinite(rotation).all():
        raise ValueError("Nonfinite proper Kabsch rotation")
    return RigidTransform(xc, yc, rotation)


class RMSFAccumulator:
    """Keep one reference and atom-wise Welford state, never trajectory xyz."""

    def __init__(
        self,
        fit_atoms: tuple[SourceAtomKey, ...],
        evaluation_atoms: tuple[SourceAtomKey, ...],
        *,
        reference_fit: Any = None,
        reference_source: int | None = None,
    ) -> None:
        _roster(fit_atoms, 3)
        _roster(evaluation_atoms, 1)
        self.fit_atoms, self.evaluation_atoms = fit_atoms, evaluation_atoms
        self.reference = (
            None
            if reference_fit is None
            else fit_coordinates(reference_fit, len(fit_atoms))
        )
        self.reference_source = reference_source
        self.count = 0
        self.mean = np.zeros((len(evaluation_atoms), 3), dtype=np.float64)
        self.m2 = np.zeros_like(self.mean)

    @property
    def reference_sha256(self) -> str:
        if self.reference is None:
            raise ValueError("No observed alignment reference")
        return identity_digest(self.reference.tolist())

    def add(
        self,
        fit: Any,
        evaluation: Any,
        *,
        source_frame_index: int,
        fit_atoms: tuple[SourceAtomKey, ...],
        evaluation_atoms: tuple[SourceAtomKey, ...],
    ) -> None:
        if (fit_atoms, evaluation_atoms) != (self.fit_atoms, self.evaluation_atoms):
            raise ValueError("Changed ordered source atom correspondence")
        x = fit_coordinates(fit, len(fit_atoms))
        a = xyz_float64(evaluation, len(evaluation_atoms))
        if self.reference is None:
            self.reference = x.copy()
            self.reference_source = source_frame_index
        aligned = proper_transform(x, self.reference).apply(a)
        with np.errstate(over="raise", invalid="raise"):
            count = self.count + 1
            delta = aligned - self.mean
            mean = self.mean + delta / count
            m2 = self.m2 + delta * (aligned - mean)
        if not np.isfinite(mean).all() or not np.isfinite(m2).all() or (m2 < 0).any():
            raise ValueError("Invalid float64 RMSF accumulation")
        self.count, self.mean, self.m2 = count, mean, m2

    def values(self) -> Any:
        if self.count < 2:
            raise ValueError("RMSF requires at least two genuine observed frames")
        return np.sqrt(np.sum(self.m2, axis=1, dtype=np.float64) / self.count)
