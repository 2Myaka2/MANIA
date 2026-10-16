"""Strict bounded QC document persistence; no scientific defaults."""

from pathlib import Path
from typing import TypeVar

from mania.canonical_reference import _StrictModel as StrictModel
from mania.input_binding import member, verify_authority
from mania.preprocessing.molecular_partner_metadata_io import (
    read_strict_json,
    write_atomic_text,
)

M = TypeVar("M", bound=StrictModel)


def read_model(path: Path, model: type[M], *, root: Path) -> M:
    relative = path.relative_to(root).as_posix()
    target = member(root, relative)
    read_strict_json(target)
    result = model.model_validate_json(target.read_bytes())
    for binding in getattr(result, "authority", ()):
        verify_authority(root, binding, binding.source_identity)
    return result


def model_bytes(value: StrictModel) -> bytes:
    import json

    value = type(value).model_validate(value.model_dump())
    return (
        json.dumps(
            value.model_dump(mode="json"), sort_keys=True, indent=2, allow_nan=False
        )
        + "\n"
    ).encode()


def write_model(path: Path, value: StrictModel, *, overwrite: bool = False) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(path)
    result = write_atomic_text(model_bytes(value).decode(), path, overwrite=overwrite)
    if not result.passed:
        raise ValueError(result.error)
