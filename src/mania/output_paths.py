"""Read-only admission of output paths and deterministic scientific identity tokens."""

from __future__ import annotations

import os
import stat
import tomllib
from dataclasses import dataclass
from pathlib import Path

from mania.canonical_reference import InputIdentity
from mania.run_config import RunPreflightError


@dataclass(frozen=True)
class IdentityPath:
    system_token: str
    trajectory_token: str
    input_identity: InputIdentity

    def to_dict(self) -> dict[str, object]:
        return {
            "system_token": self.system_token,
            "trajectory_token": self.trajectory_token,
            "input_identity": self.input_identity.to_dict(),
        }


def identity_paths(identities: tuple[InputIdentity, ...]) -> tuple[IdentityPath, ...]:
    """Keep first-seen order; never place scientific IDs in filenames."""
    systems: dict[tuple[str, str], str] = {}
    counts: dict[str, int] = {}
    seen: set[tuple[str, str, str, str]] = set()
    result = []
    for identity in identities:
        key = (
            identity.project,
            identity.system_id,
            identity.trajectory_id,
            identity.replica_id,
        )
        if key in seen:
            raise RunPreflightError("Duplicate composite input identity")
        seen.add(key)
        system = (identity.project, identity.system_id)
        if system not in systems:
            systems[system] = f"s{len(systems) + 1:04d}"
        token = systems[system]
        counts[token] = counts.get(token, 0) + 1
        result.append(IdentityPath(token, f"t{counts[token]:04d}", identity))
    return tuple(result)


def safe_absolute(path: Path) -> Path:
    """Reject symlink components before resolution, including dangling links."""
    if not path.is_absolute() or ".." in path.parts:
        raise RunPreflightError("A bound absolute path without traversal is required")
    for part in (*reversed(path.parents), path):
        if part.is_symlink():
            raise RunPreflightError(f"Symlink path component: {part}")
        if part != path and part.exists() and not part.is_dir():
            raise RunPreflightError(f"Parent path is not a directory: {part}")
    return path.resolve(strict=False)


def require_input_file(path: Path) -> Path:
    safe = safe_absolute(path)
    try:
        mode = safe.stat().st_mode
    except OSError as exc:
        raise RunPreflightError(f"Missing required file: {safe}") from exc
    if not stat.S_ISREG(mode):
        raise RunPreflightError(f"Required input is not a regular file: {safe}")
    return safe


def validate_output_root(
    root: Path,
    *,
    inputs: tuple[Path, ...],
    overwrite: bool = False,
    protected_roots: tuple[Path, ...] = (),
) -> tuple[Path, ...]:
    """Admit a root without writes; return only validated prior owned files.

    A later controller must recheck paths and replace only these declared files.
    This check does not delete, create, resume or scientifically approve a run.
    """
    base = safe_absolute(root)
    for source in (
        *inputs,
        *protected_roots,
        *protected_product_roots(),
        *_source_roots(base),
    ):
        bound = safe_absolute(source)
        if base.is_relative_to(bound) or bound.is_relative_to(base):
            raise RunPreflightError(f"Output overlaps input/protected path: {bound}")
    if not base.exists():
        return ()
    if not base.is_dir():
        raise RunPreflightError("Output root is not a directory")
    contents = tuple(base.iterdir())
    if not contents:
        return ()
    if not overwrite:
        raise RunPreflightError("Output exists; overwrite is false")
    from mania.artifact_inventory_io import read_artifact_inventory, stream_file_sha256
    from mania.run_provenance_io import read_run_provenance

    inventory_path = base / "provenance/artifact_inventory.json"
    provenance_path = base / "provenance/run_provenance.json"
    try:
        inventory = read_artifact_inventory(require_input_file(inventory_path))
        provenance = read_run_provenance(require_input_file(provenance_path))
        if (
            inventory.workflow != "mania.run"
            or provenance.workflow != inventory.workflow
            or provenance.run_id != inventory.run_id
            or inventory.inventory_path != "provenance/artifact_inventory.json"
        ):
            raise ValueError("Ownership run/workflow binding mismatch")
        owned = {inventory_path}
        inode_paths: dict[tuple[int, int], Path] = {}
        for path in (inventory_path, *inputs):
            state = path.stat()
            inode_paths[(state.st_dev, state.st_ino)] = path
        for artifact in inventory.artifacts:
            if artifact.direction != "output":
                continue
            path = require_input_file(base / artifact.path)
            if (
                not path.is_relative_to(base)
                or path.stat().st_size != artifact.byte_size
            ):
                raise ValueError("Owned artifact path/size mismatch")
            if (
                artifact.sha256 is not None
                and stream_file_sha256(path) != artifact.sha256
            ):
                raise ValueError("Owned artifact hash mismatch")
            state = path.stat()
            inode = (state.st_dev, state.st_ino)
            if inode in inode_paths and inode_paths[inode] != path:
                raise ValueError("Owned-output alias collision")
            inode_paths[inode] = path
            owned.add(path)
        if provenance_path not in owned:
            raise ValueError("Provenance is not owned by the inventory")
        actual = set()
        for path in base.rglob("*"):
            safe_absolute(path)
            if path.is_dir():
                if _is_source_checkout(path):
                    raise ValueError("Output contains a protected MANIA source tree")
                continue
            if not stat.S_ISREG(path.stat().st_mode):
                raise ValueError("Output contains a nonregular artifact")
            actual.add(path)
        if actual != owned:
            raise ValueError("Output contains unowned or missing files")
        return tuple(sorted(owned))
    except (OSError, ValueError) as exc:
        raise RunPreflightError(f"Unsafe owned-output overwrite: {exc}") from exc


def _is_source_checkout(root: Path) -> bool:
    """Recognize MANIA source from package metadata and code, never from Git alone."""
    metadata = root / "pyproject.toml"
    code = root / "src/mania"
    if not metadata.is_file() or not all(
        (code / name).is_file() for name in ("__init__.py", "_version.py", "cli.py")
    ):
        return False
    try:
        project = tomllib.loads(metadata.read_text(encoding="utf-8")).get("project")
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise RunPreflightError("Cannot identify potential MANIA source tree") from exc
    return isinstance(project, dict) and project.get("name") == "mania-wania"


def _source_roots(path: Path) -> tuple[Path, ...]:
    return tuple(root for root in (path, *path.parents) if _is_source_checkout(root))


def _additional_protected_roots() -> tuple[Path, ...]:
    value = os.environ.get("MANIA_PROTECTED_ROOTS")
    if value is None:
        return ()
    roots = []
    for entry in value.split(os.pathsep):
        if not entry or any(ord(c) < 32 or ord(c) == 127 for c in entry):
            raise RunPreflightError("Invalid MANIA_PROTECTED_ROOTS directory entry")
        try:
            root = safe_absolute(Path(entry))
            if not root.is_dir():
                raise RunPreflightError(
                    "MANIA_PROTECTED_ROOTS requires existing directories"
                )
        except (OSError, ValueError) as exc:
            raise RunPreflightError("Invalid MANIA_PROTECTED_ROOTS directory") from exc
        if root not in roots:
            roots.append(root)
    return tuple(roots)


def protected_product_roots() -> tuple[Path, ...]:
    """Protect installed code, its verified source tree and declared local roots.

    MANIA_PROTECTED_ROOTS is an optional path-separator-delimited directory list.
    Unrelated archives need an explicit declaration; Git alone is no protection
    signal. Invalid declarations fail admission rather than dropping a guard.
    """
    package = Path(__file__).resolve().parent
    return (package, *_source_roots(package), *_additional_protected_roots())
