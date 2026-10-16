"""Lightweight residue library loader for MANIA."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from json import JSONDecodeError
from pathlib import Path

EXPECTED_RESIDUE_LIBRARY_FORMAT = "MANIA_residue_library"
SUPPORTED_RESIDUE_LIBRARY_FORMAT_VERSION = "0.1"
QC_STATUS_OK = "ok"
QC_STATUS_SKIP = "skip"
QC_STATUS_NOT_FOUND = "not_found"
DEFAULT_SKIPPED_RESNAMES = frozenset({"CLA", "SOD", "TIP3"})

REQUIRED_TOP_LEVEL_KEYS = (
    "format",
    "format_version",
    "topology_files",
    "stats",
    "residues",
    "patches",
)
REQUIRED_RESIDUE_KEYS = (
    "resname",
    "block_type",
    "category",
    "source_file",
    "atoms",
)
REQUIRED_ATOM_KEYS = (
    "name",
    "type",
    "charge",
)
REQUIRED_PATCH_KEYS = (
    "name",
    "block_type",
    "category",
    "source_file",
)


class ResidueLibraryError(Exception):
    """Base exception for residue library loading errors."""


class ResidueLibraryFormatError(ResidueLibraryError):
    """Raised when a residue library has an unsupported file format."""


class ResidueLibraryValidationError(ResidueLibraryError):
    """Raised when a residue library has malformed content."""


class ResidueLibraryQCError(ResidueLibraryError):
    """Raised when residue library QC finds blocking errors."""


@dataclass(frozen=True)
class ResidueAtom:
    """Single atom record from a residue library entry."""

    name: str
    type: str
    charge: float | int


@dataclass(frozen=True)
class ResidueEntry:
    """Residue record from a residue library."""

    resname: str
    block_type: str
    category: str
    source_file: str
    atoms: tuple[ResidueAtom, ...]


@dataclass(frozen=True)
class PatchEntry:
    """Patch record from a residue library."""

    name: str
    block_type: str
    category: str
    source_file: str


@dataclass(frozen=True)
class ResidueLibrary:
    """Loaded residue library with normalized residue lookup helpers."""

    format: str
    format_version: str
    topology_files: tuple[str, ...]
    stats: Mapping[str, object]
    residues: Mapping[str, ResidueEntry]
    patches: Mapping[str, PatchEntry]

    def get_residue(self, resname: str) -> ResidueEntry | None:
        """Return a residue entry by normalized residue name."""
        return self.residues.get(normalize_resname(resname))

    def has_residue(self, resname: str) -> bool:
        """Return whether a residue exists in the library."""
        return self.get_residue(resname) is not None

    def classify_residue(self, resname: str) -> str | None:
        """Return the residue category, or None for unknown residues."""
        residue = self.get_residue(resname)
        if residue is None:
            return None
        return residue.category


@dataclass(frozen=True)
class ResidueQCRow:
    """Single residue-library QC result row."""

    resname: str
    status: str
    coverage: str
    block_type: str
    source_file: str
    conditions: tuple[str, ...]


@dataclass(frozen=True)
class ResidueQCReport:
    """Residue-library QC report."""

    rows: tuple[ResidueQCRow, ...]

    def has_errors(self) -> bool:
        """Return whether the report contains unknown residues."""
        return any(row.status == QC_STATUS_NOT_FOUND for row in self.rows)

    def unknown_resnames(self) -> tuple[str, ...]:
        """Return sorted normalized residue names that were not found."""
        return tuple(
            sorted(
                row.resname
                for row in self.rows
                if row.status == QC_STATUS_NOT_FOUND
            )
        )

    def status_counts(self) -> Mapping[str, int]:
        """Return row counts by QC status."""
        counts: dict[str, int] = {}
        for row in self.rows:
            counts[row.status] = counts.get(row.status, 0) + 1
        return counts


def normalize_resname(resname: str) -> str:
    """Normalize a residue name for library lookups."""
    return resname.strip().upper()


def load_residue_library(path: str | Path) -> ResidueLibrary:
    """Load and validate a MANIA residue library JSON file."""
    library_path = Path(path)
    try:
        payload = json.loads(library_path.read_text(encoding="utf-8"))
    except JSONDecodeError as exc:
        raise ResidueLibraryFormatError("Invalid residue library JSON") from exc

    if not isinstance(payload, dict):
        raise ResidueLibraryValidationError("Residue library must be a JSON object")

    _validate_required_keys(payload, REQUIRED_TOP_LEVEL_KEYS, "residue library")
    _validate_format(payload)

    topology_files = payload["topology_files"]
    stats = payload["stats"]
    residues = payload["residues"]
    patches = payload["patches"]

    if not isinstance(topology_files, list):
        raise ResidueLibraryValidationError("topology_files must be a list")
    if not all(isinstance(topology_file, str) for topology_file in topology_files):
        raise ResidueLibraryValidationError("topology_files entries must be strings")
    if not isinstance(stats, dict):
        raise ResidueLibraryValidationError("stats must be a mapping")
    if not isinstance(residues, dict):
        raise ResidueLibraryValidationError("residues must be a mapping")
    if not isinstance(patches, dict):
        raise ResidueLibraryValidationError("patches must be a mapping")

    return ResidueLibrary(
        format=payload["format"],
        format_version=payload["format_version"],
        topology_files=tuple(topology_files),
        stats=dict(stats),
        residues=_parse_residues(residues),
        patches=_parse_patches(patches),
    )


def extend_residue_library(
    library: ResidueLibrary,
    custom_residues: Mapping[str, ResidueEntry],
    *,
    allow_override_existing: bool = False,
) -> ResidueLibrary:
    """Return an effective residue library with in-memory custom residues."""
    effective_residues = dict(library.residues)
    effective_stats = dict(library.stats)
    normalized_custom_resnames: set[str] = set()
    custom_residues_added = 0

    for custom_key, custom_entry in custom_residues.items():
        if not isinstance(custom_key, str):
            raise ResidueLibraryValidationError("custom residue keys must be strings")
        if not isinstance(custom_entry, ResidueEntry):
            raise ResidueLibraryValidationError(
                "custom residue values must be ResidueEntry instances"
            )

        normalized_key = normalize_resname(custom_key)
        normalized_entry_resname = normalize_resname(custom_entry.resname)
        if normalized_key != normalized_entry_resname:
            raise ResidueLibraryValidationError(
                "custom residue key and resname must match after normalization"
            )
        if normalized_key in normalized_custom_resnames:
            raise ResidueLibraryValidationError(
                "custom residue keys must be unique after normalization"
            )

        exists_in_base_library = normalized_key in library.residues
        if exists_in_base_library and not allow_override_existing:
            raise ResidueLibraryValidationError(
                f"custom residue would override existing residue: {normalized_key}"
            )
        if not exists_in_base_library:
            custom_residues_added += 1

        normalized_custom_resnames.add(normalized_key)
        effective_residues[normalized_key] = ResidueEntry(
            resname=normalized_entry_resname,
            block_type=custom_entry.block_type,
            category=custom_entry.category,
            source_file=custom_entry.source_file,
            atoms=custom_entry.atoms,
        )

    effective_stats["custom_residues_added"] = custom_residues_added
    effective_stats["effective_residues_total"] = len(effective_residues)

    return ResidueLibrary(
        format=library.format,
        format_version=library.format_version,
        topology_files=library.topology_files,
        stats=effective_stats,
        residues=effective_residues,
        patches=dict(library.patches),
    )


def run_residue_library_qc(
    resnames_by_condition: Mapping[str, Iterable[str]],
    library: ResidueLibrary,
    *,
    skip_resnames: Iterable[str] = DEFAULT_SKIPPED_RESNAMES,
    fail_on_error: bool = True,
) -> ResidueQCReport:
    """Run residue-library coverage QC against the passed library."""
    skipped_resnames = {normalize_resname(resname) for resname in skip_resnames}
    conditions_by_resname: dict[str, set[str]] = {}

    for condition, resnames in resnames_by_condition.items():
        for resname in resnames:
            normalized_resname = normalize_resname(resname)
            conditions_by_resname.setdefault(normalized_resname, set()).add(condition)

    rows: list[ResidueQCRow] = []
    for resname in sorted(conditions_by_resname):
        conditions = tuple(sorted(conditions_by_resname[resname]))
        residue = library.get_residue(resname)
        if resname in skipped_resnames:
            rows.append(
                ResidueQCRow(
                    resname=resname,
                    status=QC_STATUS_SKIP,
                    coverage="skipped",
                    block_type="",
                    source_file="",
                    conditions=conditions,
                )
            )
        elif residue is not None:
            rows.append(
                ResidueQCRow(
                    resname=resname,
                    status=QC_STATUS_OK,
                    coverage="full",
                    block_type=residue.block_type,
                    source_file=residue.source_file,
                    conditions=conditions,
                )
            )
        else:
            rows.append(
                ResidueQCRow(
                    resname=resname,
                    status=QC_STATUS_NOT_FOUND,
                    coverage="missing",
                    block_type="",
                    source_file="",
                    conditions=conditions,
                )
            )

    report = ResidueQCReport(rows=tuple(rows))
    if fail_on_error and report.has_errors():
        unknown = ", ".join(report.unknown_resnames())
        raise ResidueLibraryQCError(f"Unknown residue names: {unknown}")
    return report


def write_residue_qc_report(
    report: ResidueQCReport,
    path: str | Path,
) -> None:
    """Write a residue-library QC report as CSV."""
    report_path = Path(path)
    with report_path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(
            (
                "resname",
                "status",
                "coverage",
                "block_type",
                "source_file",
                "conditions",
            )
        )
        for row in report.rows:
            writer.writerow(
                (
                    row.resname,
                    row.status,
                    row.coverage,
                    row.block_type,
                    row.source_file,
                    ",".join(row.conditions),
                )
            )


def _validate_format(payload: Mapping[str, object]) -> None:
    if payload["format"] != EXPECTED_RESIDUE_LIBRARY_FORMAT:
        raise ResidueLibraryFormatError("Unsupported residue library format")
    if payload["format_version"] != SUPPORTED_RESIDUE_LIBRARY_FORMAT_VERSION:
        raise ResidueLibraryFormatError("Unsupported residue library format version")


def _validate_required_keys(
    payload: Mapping[str, object],
    required_keys: tuple[str, ...],
    label: str,
) -> None:
    missing_keys = [key for key in required_keys if key not in payload]
    if missing_keys:
        missing = ", ".join(missing_keys)
        raise ResidueLibraryValidationError(f"Missing {label} keys: {missing}")


def _require_string(payload: Mapping[str, object], key: str, label: str) -> str:
    value = payload[key]
    if not isinstance(value, str):
        raise ResidueLibraryValidationError(f"{label}.{key} must be a string")
    return value


def _parse_residues(residues: Mapping[str, object]) -> dict[str, ResidueEntry]:
    parsed: dict[str, ResidueEntry] = {}
    for residue_key, residue_payload in residues.items():
        if not isinstance(residue_key, str):
            raise ResidueLibraryValidationError("residue keys must be strings")
        if not isinstance(residue_payload, dict):
            raise ResidueLibraryValidationError("residue entries must be mappings")
        _validate_required_keys(
            residue_payload,
            REQUIRED_RESIDUE_KEYS,
            f"residue {residue_key}",
        )
        atoms = residue_payload["atoms"]
        if not isinstance(atoms, list):
            raise ResidueLibraryValidationError("residue atoms must be a list")

        entry = ResidueEntry(
            resname=normalize_resname(
                _require_string(residue_payload, "resname", "residue")
            ),
            block_type=_require_string(residue_payload, "block_type", "residue"),
            category=_require_string(residue_payload, "category", "residue"),
            source_file=_require_string(residue_payload, "source_file", "residue"),
            atoms=tuple(_parse_atoms(atoms)),
        )
        normalized_key = normalize_resname(residue_key)
        if normalized_key != entry.resname:
            raise ResidueLibraryValidationError(
                "residue key and resname must match after normalization"
            )
        parsed[normalized_key] = entry
    return parsed


def _parse_atoms(atoms: list[object]) -> list[ResidueAtom]:
    parsed: list[ResidueAtom] = []
    for atom_payload in atoms:
        if not isinstance(atom_payload, dict):
            raise ResidueLibraryValidationError("atom entries must be mappings")
        _validate_required_keys(atom_payload, REQUIRED_ATOM_KEYS, "atom")
        charge = atom_payload["charge"]
        if not isinstance(charge, (float, int)):
            raise ResidueLibraryValidationError("atom.charge must be numeric")
        parsed.append(
            ResidueAtom(
                name=_require_string(atom_payload, "name", "atom"),
                type=_require_string(atom_payload, "type", "atom"),
                charge=charge,
            )
        )
    return parsed


def _parse_patches(patches: Mapping[str, object]) -> dict[str, PatchEntry]:
    parsed: dict[str, PatchEntry] = {}
    for patch_key, patch_payload in patches.items():
        if not isinstance(patch_key, str):
            raise ResidueLibraryValidationError("patch keys must be strings")
        if not isinstance(patch_payload, dict):
            raise ResidueLibraryValidationError("patch entries must be mappings")
        _validate_required_keys(
            patch_payload,
            REQUIRED_PATCH_KEYS,
            f"patch {patch_key}",
        )
        entry = PatchEntry(
            name=_require_string(patch_payload, "name", "patch"),
            block_type=_require_string(patch_payload, "block_type", "patch"),
            category=_require_string(patch_payload, "category", "patch"),
            source_file=_require_string(patch_payload, "source_file", "patch"),
        )
        parsed[entry.name] = entry
    return parsed


__all__ = [
    "DEFAULT_SKIPPED_RESNAMES",
    "EXPECTED_RESIDUE_LIBRARY_FORMAT",
    "QC_STATUS_NOT_FOUND",
    "QC_STATUS_OK",
    "QC_STATUS_SKIP",
    "SUPPORTED_RESIDUE_LIBRARY_FORMAT_VERSION",
    "PatchEntry",
    "ResidueAtom",
    "ResidueEntry",
    "ResidueLibrary",
    "ResidueLibraryError",
    "ResidueLibraryFormatError",
    "ResidueLibraryQCError",
    "ResidueLibraryValidationError",
    "ResidueQCReport",
    "ResidueQCRow",
    "extend_residue_library",
    "load_residue_library",
    "normalize_resname",
    "run_residue_library_qc",
    "write_residue_qc_report",
]
