"""Software identity with lazy, best-effort source-checkout metadata."""

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from mania import _version

SOFTWARE_NAME = "MANIA"
DISTRIBUTION_NAME = "mania-wania"


@dataclass(frozen=True)
class SoftwareIdentity:
    """Package version and optional identity of the containing source checkout."""

    software_name: str
    distribution_name: str
    version: str
    commit_sha: str | None
    commit_source: Literal["git_checkout", "unavailable"]
    working_tree_status: Literal["clean", "dirty", "unavailable"]

    def to_dict(self) -> dict[str, object]:
        """Return JSON-safe fields without paths or runtime environment details."""
        return {
            "software_name": self.software_name,
            "distribution_name": self.distribution_name,
            "version": self.version,
            "commit_sha": self.commit_sha,
            "commit_source": self.commit_source,
            "working_tree_status": self.working_tree_status,
        }


def _run_git(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=root,
            # Caller Git overrides must not select another repository or index.
            env={
                "GIT_OPTIONAL_LOCKS": "0",
                **{
                    key: value
                    for key, value in os.environ.items()
                    if not key.startswith("GIT_")
                },
            },
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError):
        return None
    return result.stdout if result.returncode == 0 else None


def _checkout_root() -> Path | None:
    try:
        module_path = Path(__file__).resolve()
        if module_path.parts[-3:] != ("src", "mania", "software_identity.py"):
            return None
        root = module_path.parents[2]
        metadata = root / ".git"
        # A linked worktree uses a .git file instead of a directory.
        if not (metadata.is_dir() or metadata.is_file()):
            return None
        output = _run_git(root, "rev-parse", "--show-toplevel")
        if output is None:
            return None
        top_level = output.removesuffix("\n")
        if not top_level or any(char in top_level for char in "\r\n\0"):
            return None
        top_level_path = Path(top_level)
        if top_level_path.is_absolute() and top_level_path.resolve() == root:
            return root
    except (OSError, ValueError, RuntimeError):
        return None
    return None


def get_software_identity() -> SoftwareIdentity:
    """Inspect this module's checkout, falling back honestly when unavailable."""
    commit_sha = None
    commit_source: Literal["git_checkout", "unavailable"] = "unavailable"
    working_tree_status: Literal["clean", "dirty", "unavailable"] = "unavailable"
    root = _checkout_root()
    if root is not None:
        output = _run_git(root, "rev-parse", "--verify", "HEAD")
        sha = output.removesuffix("\n") if output is not None else ""
        if re.fullmatch(r"[0-9a-fA-F]{40}", sha):
            commit_sha = sha.lower()
            commit_source = "git_checkout"
            status = _run_git(root, "status", "--porcelain=v1", "--untracked-files=all")
            if status is not None:
                working_tree_status = "dirty" if status else "clean"
    return SoftwareIdentity(
        software_name=SOFTWARE_NAME,
        distribution_name=DISTRIBUTION_NAME,
        version=_version.__version__,
        commit_sha=commit_sha,
        commit_source=commit_source,
        working_tree_status=working_tree_status,
    )
