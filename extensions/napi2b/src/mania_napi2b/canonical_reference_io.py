"""Strict local Stage 30.A reference loading; no remote retrieval or refresh."""

import json
from dataclasses import fields
from importlib.resources import files
from pathlib import Path
from typing import Any

from mania_napi2b.canonical_reference import CanonicalProteinReference


class CanonicalReferenceReadError(ValueError):
    """Invalid, missing, or unreadable local canonical reference payload."""


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise ValueError("Non-finite JSON constant")


def _parse_reference(text: str) -> CanonicalProteinReference:
    data = json.loads(text, object_pairs_hook=_object, parse_constant=_constant)
    contract_fields = fields(CanonicalProteinReference)
    if type(data) is not dict or set(data) != {item.name for item in contract_fields}:
        raise ValueError("Invalid canonical reference fields")
    for item in contract_fields:
        if not item.init:
            value = data.pop(item.name)
            if type(value) is not str or value != item.default:
                raise ValueError("Unsupported canonical reference contract")
    return CanonicalProteinReference(**data)


def read_canonical_reference(path: str | Path) -> CanonicalProteinReference:
    """Read a strict UTF-8 JSON file under the NaPi2b-only 30.A contract."""
    try:
        return _parse_reference(Path(path).read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, OverflowError, RecursionError):
        raise CanonicalReferenceReadError(
            "Invalid or unreadable canonical reference."
        ) from None


def load_default_napi2b_canonical_reference() -> CanonicalProteinReference:
    """Load only the packaged reference; a missing/corrupt resource is an error."""
    try:
        resource = files("mania_napi2b").joinpath(
            "data", "canonical", "slc34a2_o95436_reference.json"
        )
        return _parse_reference(resource.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, OverflowError, RecursionError):
        raise CanonicalReferenceReadError(
            "Invalid or unreadable packaged NaPi2b canonical reference."
        ) from None


__all__ = [
    "CanonicalReferenceReadError",
    "load_default_napi2b_canonical_reference",
    "read_canonical_reference",
]
