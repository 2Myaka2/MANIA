"""Strict offline readers for explicitly supplied generic authority documents."""

import json
from pathlib import Path
from typing import Any, TypeVar

from mania.canonical_reference import ProteinReference, _StrictModel

_Model = TypeVar("_Model", bound=_StrictModel)


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise ValueError("Non-finite JSON constant")


def _read_model(path: str | Path, model: type[_Model]) -> _Model:
    if not isinstance(path, (str, Path)) or path == "":
        raise ValueError("An explicit JSON path is required")
    try:
        data = json.loads(
            Path(path).read_text(encoding="utf-8"),
            object_pairs_hook=_object,
            parse_constant=_constant,
        )
        # JSON validation permits ordered arrays for immutable tuple fields;
        # strict scalar validation still rejects coercion and bool-as-integer.
        return model.model_validate_json(json.dumps(data, allow_nan=False))
    except (OSError, ValueError, TypeError, OverflowError, RecursionError):
        raise ValueError("Invalid or unreadable supplied authority document") from None


def read_protein_reference(path: str | Path) -> ProteinReference:
    return _read_model(path, ProteinReference)


def __getattr__(name: str) -> object:
    if name in (
        "CanonicalReferenceReadError",
        "load_default_napi2b_canonical_reference",
        "read_canonical_reference",
    ):
        raise ImportError(
            "Fixed NaPi2b API moved to mania_napi2b.canonical_reference_io; "
            "install mania-napi2b and explicitly select a profile."
        )
    raise AttributeError(name)
