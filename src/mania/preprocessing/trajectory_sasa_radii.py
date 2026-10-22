"""Owner-approved Bondi eight-element registry; no element inference or fallback."""

from __future__ import annotations

from types import MappingProxyType
from typing import Any

from mania.preprocessing.trajectory_rmsd import identity_digest

RADII = MappingProxyType(
    {
        "H": 1.20,
        "C": 1.70,
        "N": 1.55,
        "O": 1.52,
        "P": 1.80,
        "S": 1.80,
        "Na": 2.27,
        "Cl": 1.75,
    }
)
DOIS = ("10.1021/j100785a001", "10.1021/jp8111556", "10.1021/jp953141+")
REGISTRY_ID = "mania.sasa.bondi8.v1"


def registry_record() -> dict[str, Any]:
    """Return an independent, canonically hashable literature record.

    Mantina (2009), Tables 7/12, Bondi columns, corroborate C/N/O/P/S/Na/Cl.
    Original Bondi H=1.20 is retained, not the later Rowland–Taylor H=1.10.
    Na=2.27 and Cl=1.75 are Bondi values, not Mantina's new model values.
    """
    return {
        "id": REGISTRY_ID,
        "version": 1,
        "unit": "angstrom",
        "entries": [[k, v] for k, v in RADII.items()],
        "dois": list(DOIS),
    }


REGISTRY_SHA256 = identity_digest(registry_record())


def radii_for(elements: tuple[str, ...]) -> tuple[float, ...]:
    if not elements or any(type(e) is not str or e not in RADII for e in elements):
        unsupported = tuple(e for e in elements if type(e) is not str or e not in RADII)
        raise ValueError(
            "Selected elements require exact approved source-backed radii; "
            f"unsupported selected values: {unsupported!r}"
        )
    return tuple(RADII[e] for e in elements)
