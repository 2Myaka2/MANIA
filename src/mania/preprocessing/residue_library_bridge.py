"""Bridge preprocessing manifest options to the residue-library layer."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mania.preprocessing.input_manifest import ResidueLibraryInputConfig
from mania.residue_library import (
    ResidueLibrary,
    extend_residue_library,
    load_residue_library,
)


class PreprocessingResidueLibraryBridgeError(ValueError):
    """Raised for deterministic preprocessing residue-library bridge errors."""


@dataclass(frozen=True)
class ResolvedResidueLibraryManifestOptions:
    """Residue-library manifest options with explicit path resolution."""

    library_path: Path
    custom_residues_path: Path | None
    skip_resnames: tuple[str, ...]
    allow_user_overrides: bool

    def to_dict(self) -> dict[str, object]:
        """Return JSON-serializable resolved residue-library options."""
        return {
            "library_path": str(self.library_path),
            "custom_residues_path": (
                str(self.custom_residues_path)
                if self.custom_residues_path is not None
                else None
            ),
            "skip_resnames": list(self.skip_resnames),
            "allow_user_overrides": self.allow_user_overrides,
        }


def resolve_residue_library_manifest_paths(
    options: ResidueLibraryInputConfig,
    *,
    base_dir: str | Path | None = None,
) -> ResolvedResidueLibraryManifestOptions:
    """Resolve manifest residue-library paths against an explicit base."""
    if options.library_path is None:
        raise PreprocessingResidueLibraryBridgeError(
            "residue_library.library_path is required for bridge loading"
        )

    path_base = Path(base_dir) if base_dir is not None else None
    return ResolvedResidueLibraryManifestOptions(
        library_path=_resolve_path(options.library_path, path_base),
        custom_residues_path=(
            _resolve_path(options.custom_residues_path, path_base)
            if options.custom_residues_path is not None
            else None
        ),
        skip_resnames=tuple(options.skip_resnames),
        allow_user_overrides=options.allow_user_overrides,
    )


def load_residue_library_from_manifest_options(
    options: ResidueLibraryInputConfig,
    *,
    base_dir: str | Path | None = None,
) -> ResidueLibrary:
    """Load and optionally extend a library from preprocessing options."""
    resolved = resolve_residue_library_manifest_paths(options, base_dir=base_dir)
    library = load_residue_library(resolved.library_path)

    if resolved.custom_residues_path is None:
        return library

    custom_library = load_residue_library(resolved.custom_residues_path)
    return extend_residue_library(
        library,
        custom_library.residues,
        allow_override_existing=resolved.allow_user_overrides,
    )


def _resolve_path(path: Path, base_dir: Path | None) -> Path:
    if path.is_absolute() or base_dir is None:
        return path
    return base_dir / path


__all__ = [
    "PreprocessingResidueLibraryBridgeError",
    "ResolvedResidueLibraryManifestOptions",
    "load_residue_library_from_manifest_options",
    "resolve_residue_library_manifest_paths",
]
