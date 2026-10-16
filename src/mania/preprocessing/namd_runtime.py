"""Opt-in NAMD loader adapter, shared by planning and subsequent frame consumers."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mania.preprocessing.namd_authority import (
    DCDIdentity,
    ElementControl,
    RawFrameTime,
    TimeControl,
    read_control,
    validate_elements,
    validate_time,
)


@dataclass(frozen=True)
class NAMDControlPaths:
    elements: Path
    time: Path


def observe_dcd(reader: Any, path: Path) -> DCDIdentity:
    """Read only first five and last frames; never hash the trajectory."""
    header = reader._file.header
    old_frame = reader.ts.frame
    try:
        times = tuple(
            RawFrameTime(frame=i, time_ps=float(reader[i].time))
            for i in sorted({*range(min(5, len(reader))), len(reader) - 1})
        )
    finally:
        reader[old_frame]
    return DCDIdentity(
        path=str(path.resolve()),
        size_bytes=path.stat().st_size,
        atom_count=int(header["natoms"]),
        frame_count=len(reader),
        istart=int(header["istart"]),
        nsavc=int(header["nsavc"]),
        delta=float(header["delta"]),
        dt_ps=float(reader.dt),
        unit_cell=bool(header["is_periodic"]),
        remarks=header["remarks"],
        observed_times=times,
    )


@dataclass(frozen=True)
class _AuthoritativeTime:
    times: tuple[float, ...]

    def __call__(self, ts: Any) -> Any:
        # Absolute indexed assignment, never an accumulated offset or rounding.
        ts.time = self.times[ts.frame]
        return ts


def apply_namd_authority(
    universe: Any,
    psf: Path,
    dcd: Path,
    controls: NAMDControlPaths,
) -> None:
    """Validate everything before attaching explicit elements/time in memory."""
    if psf.suffix.lower() != ".psf" or dcd.suffix.lower() != ".dcd":
        raise ValueError("NAMD authority requires explicit PSF/DCD inputs")
    if getattr(universe.trajectory, "format", None) != "DCD":
        raise ValueError("NAMD authority requires a single DCD reader")
    if universe.trajectory.transformations:
        raise ValueError("Authority must be attached before trajectory transformations")
    if (
        Path(universe.filename).resolve() != psf.resolve()
        or Path(universe.trajectory.filename).resolve() != dcd.resolve()
    ):
        raise ValueError("Runtime source paths differ from authority inputs")
    elements = read_control(controls.elements, ElementControl)
    time = read_control(controls.time, TimeControl)
    lookup = validate_elements(elements, psf)
    times = validate_time(time, dcd)
    if observe_dcd(universe.trajectory, dcd) != time.dcd:
        raise ValueError("Stale DCD header/raw timing evidence")
    if (
        len(universe.atoms) != time.dcd.atom_count
        or dict(Counter(universe.atoms.types)) != elements.used_type_counts
    ):
        raise ValueError("Runtime PSF/DCD atom/type correspondence differs")
    assigned = [lookup[str(atom_type)] for atom_type in universe.atoms.types]
    existing = getattr(universe.atoms, "elements", None)
    if existing is not None and list(existing) != assigned:
        raise ValueError("Existing explicit elements conflict with NAMD control")
    if existing is None:
        universe.add_TopologyAttr("elements", assigned)
    universe.trajectory.add_transformations(_AuthoritativeTime(times))
