"""Strict generic RMSD persistence and source-exact portable-path helpers."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Annotated, Any

from pydantic import Field, model_validator

from mania.canonical_reference import Digest
from mania.canonical_reference import _StrictModel as StrictModel
from mania.preprocessing.molecular_partner_metadata_io import (
    read_strict_json,
    write_atomic_text,
)
from mania.preprocessing.trajectory_rmsd import RMSDMeasurement

COLUMNS = (
    "requested_sample_index",
    "requested_time_ps",
    "state",
    "runtime_frame_index",
    "source_frame_index",
    "prepared_frame_index",
    "actual_time_ps",
    "time_delta_ps",
    "rmsd_A",
)


def rmsd_timeseries_text(measurement: RMSDMeasurement) -> str:
    measurement = RMSDMeasurement.model_validate(measurement.model_dump())
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(COLUMNS)
    for row in measurement.rows:
        values = row.to_dict()
        writer.writerow(
            [
                ""
                if values[k] is None
                else format(values[k], ".17g")
                if type(values[k]) is float
                else values[k]
                for k in COLUMNS
            ]
        )
    return stream.getvalue()


def write_rmsd_measurement(measurement: RMSDMeasurement, output_root: Path) -> None:
    measurement = RMSDMeasurement.model_validate(measurement.model_dump())
    names = ("rmsd_timeseries.csv", "rmsd_measurement.json")
    if any((output_root / n).exists() for n in names):
        raise ValueError("Existing RMSD evidence is immutable")
    texts = (
        rmsd_timeseries_text(measurement),
        json.dumps(
            measurement.to_dict(),
            ensure_ascii=True,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n",
    )
    for name, text in zip(names, texts, strict=True):
        if not write_atomic_text(text, output_root / name, overwrite=False).passed:
            raise ValueError("RMSD artifact write failed")


def read_rmsd_measurement(output_root: Path) -> RMSDMeasurement:
    data = read_strict_json(portable_member(output_root, "rmsd_measurement.json"))
    measurement = RMSDMeasurement.model_validate_json(json.dumps(data, allow_nan=False))
    if measurement.to_dict() != data:
        raise ValueError("RMSD schema requires complete exact fields")
    if (
        portable_member(output_root, "rmsd_timeseries.csv").read_bytes()
        != rmsd_timeseries_text(measurement).encode()
    ):
        raise ValueError("RMSD CSV identity/order/precision mismatch")
    return measurement


def _require_text(value: object, name: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be a non-empty stripped string")


def _require_portable_path(value: str, name: str) -> None:
    _require_text(value, name)
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or PureWindowsPath(value).drive
        or "\\" in value
        or "://" in value
        or "\0" in value
        or any(part in (".", "..") for part in value.split("/"))
        or path.as_posix() != value
    ):
        raise ValueError(f"{name} must be a normalized portable relative POSIX path")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def portable_member(root: Path, path: str) -> Path:
    _require_portable_path(path, "member")
    target = root / path
    if any(p.is_symlink() for p in (target, *target.parents)) or (
        not target.resolve().is_relative_to(root.resolve())
    ):
        raise ValueError("Handoff member must be a contained physical regular file")
    return target


# Shared retained file-evidence types; scientific RMSD methods are unchanged.


class FileBinding(StrictModel):
    artifact_id: str
    path: str | None
    byte_size: Annotated[int, Field(ge=0)]
    sha256: Digest
    format: str

    @model_validator(mode="after")
    def portable(self) -> FileBinding:
        if self.path is not None:
            _require_portable_path(self.path, "binding path")
        if not self.artifact_id or not self.format:
            raise ValueError("Binding needs artifact ID and format")
        return self


def bind_file(path: Path, artifact_id: str, portable: str | None = None) -> FileBinding:
    return FileBinding(
        artifact_id=artifact_id,
        path=portable,
        byte_size=path.stat().st_size,
        sha256=file_sha256(path),
        format=path.suffix.removeprefix(".").lower(),
    )


def atomic_json(path: Path, value: Any) -> None:
    result = write_atomic_text(
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False)
        + "\n",
        path,
        overwrite=False,
    )
    if not result.passed:
        raise ValueError(f"Protected atomic artifact write failed: {path}")
