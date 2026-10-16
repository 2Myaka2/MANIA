"""Optional scientific runtime boundary for future preprocessing loaders."""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
from dataclasses import dataclass
from types import ModuleType

MDANALYSIS_PACKAGE_NAME = "MD" + "Analysis"
MDANALYSIS_IMPORT_NAME = MDANALYSIS_PACKAGE_NAME
MDANALYSIS_INSTALL_HINT = (
    'Install it with pip install ".[md]" or pip install ".[science]".'
)


class PreprocessingOptionalDependencyError(RuntimeError):
    """Raised when optional preprocessing runtime support is unavailable."""


@dataclass(frozen=True)
class OptionalScientificDependencyStatus:
    """Availability details for one optional scientific dependency."""

    package_name: str
    import_name: str
    available: bool
    version: str | None = None
    install_hint: str = ""

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable dependency status."""
        return {
            "package_name": self.package_name,
            "import_name": self.import_name,
            "available": self.available,
            "version": self.version,
            "install_hint": self.install_hint,
        }


def get_mdanalysis_status() -> OptionalScientificDependencyStatus:
    """Return deterministic availability details for the MD runtime."""
    available = _find_mdanalysis_spec() is not None
    version: str | None = None
    if available:
        try:
            version = importlib.metadata.version(MDANALYSIS_PACKAGE_NAME)
        except importlib.metadata.PackageNotFoundError:
            pass

    return OptionalScientificDependencyStatus(
        package_name=MDANALYSIS_PACKAGE_NAME,
        import_name=MDANALYSIS_IMPORT_NAME,
        available=available,
        version=version,
        install_hint=MDANALYSIS_INSTALL_HINT,
    )


def is_mdanalysis_available() -> bool:
    """Return whether the MD runtime can be discovered without importing it."""
    return get_mdanalysis_status().available


def require_mdanalysis() -> ModuleType:
    """Lazily import the MD runtime or raise a project-specific error."""
    try:
        return importlib.import_module(MDANALYSIS_IMPORT_NAME)
    except ModuleNotFoundError as exc:
        if exc.name != MDANALYSIS_IMPORT_NAME:
            raise
        raise PreprocessingOptionalDependencyError(
            f"{MDANALYSIS_PACKAGE_NAME} is needed for future "
            "topology/trajectory loading. "
            f"{MDANALYSIS_INSTALL_HINT} "
            "The default/core install intentionally does not require it."
        ) from exc


def _find_mdanalysis_spec() -> importlib.machinery.ModuleSpec | None:
    try:
        return importlib.util.find_spec(MDANALYSIS_IMPORT_NAME)
    except (ImportError, ValueError):
        return None


__all__ = [
    "OptionalScientificDependencyStatus",
    "PreprocessingOptionalDependencyError",
    "get_mdanalysis_status",
    "is_mdanalysis_available",
    "require_mdanalysis",
]
