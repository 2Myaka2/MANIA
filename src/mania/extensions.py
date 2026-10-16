"""Explicit, immutable plan-scoped contributions for extension API v1.

The candidate boundary uses exact distribution version pins. Enumeration reads
installed metadata only; extension code executes only after explicit selection.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from importlib import metadata
from types import MappingProxyType

from mania._version import __version__

EXTENSION_API_VERSION = "mania.extension_api.v1"


class ExtensionError(ValueError):
    """Missing, incompatible or conflicting explicitly selected extension."""


def _text(value: object) -> None:
    if type(value) is not str or not value or value != value.strip():
        raise ExtensionError("Extension identifiers must be nonempty stripped strings")


@dataclass(frozen=True)
class ExtensionMetadata:
    id: str
    distribution: str
    version: str
    api_version: str
    core_version_spec: str
    profile_ids: tuple[str, ...]
    schema_ids: tuple[str, ...]
    method_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for value in (
            self.id,
            self.distribution,
            self.version,
            self.api_version,
            self.core_version_spec,
        ):
            _text(value)
        if self.api_version != EXTENSION_API_VERSION:
            raise ExtensionError("Unsupported extension API")
        if self.core_version_spec != f"=={__version__}":
            raise ExtensionError("Extension core version skew")
        for ids in (self.profile_ids, self.schema_ids, self.method_ids):
            if type(ids) is not tuple or len(set(ids)) != len(ids):
                raise ExtensionError("Duplicate or mutable declared identifiers")
            for value in ids:
                _text(value)
        if not self.profile_ids:
            raise ExtensionError("Extension must declare a profile")
        if any(not schema.endswith((".v1", ".v0.1")) for schema in self.schema_ids):
            raise ExtensionError("Unsupported schema version for extension API v1")


@dataclass(frozen=True)
class ExtensionContribution:
    metadata: ExtensionMetadata
    profile_id: str
    reference_factories: Mapping[str, Callable[..., object]]
    policy_factories: Mapping[str, Callable[..., object]]
    schema_validators: Mapping[str, Callable[..., object]]
    method_callables: Mapping[str, Callable[..., object]]

    def __post_init__(self) -> None:
        if type(self.metadata) is not ExtensionMetadata:
            raise ExtensionError("Exact extension metadata required")
        self.metadata.__post_init__()
        if self.profile_id not in self.metadata.profile_ids:
            raise ExtensionError("Undeclared selected profile")
        seen: set[str] = set()
        for name in (
            "reference_factories",
            "policy_factories",
            "schema_validators",
            "method_callables",
        ):
            values = getattr(self, name)
            if not isinstance(values, Mapping):
                raise ExtensionError("Contribution registrations require mappings")
            copy = dict(values)
            for key, value in copy.items():
                _text(key)
                if not callable(value) or key in seen:
                    raise ExtensionError(
                        "Invalid or conflicting contribution identifier"
                    )
                seen.add(key)
            object.__setattr__(self, name, MappingProxyType(copy))
        if not set(self.schema_validators).issubset(self.metadata.schema_ids):
            raise ExtensionError("Undeclared schema validator")
        if not set(self.method_callables).issubset(self.metadata.method_ids):
            raise ExtensionError("Undeclared method callable")


def enumerate_extension_metadata() -> tuple[tuple[str, str, str, str], ...]:
    """Return entry-point ID/distribution/version/target without importing it."""
    result = []
    for entry in metadata.entry_points(group="mania.extensions"):
        if entry.dist is None:
            raise ExtensionError("Entry point has no installed distribution")
        result.append(
            (entry.name, entry.dist.metadata["Name"], entry.dist.version, entry.value)
        )
    return tuple(result)


def load_selected_extension(
    id: str,
    version_spec: str,
    profile_id: str,
) -> ExtensionContribution:
    """Load one requested, exactly pinned candidate profile, without global state."""
    for value in (id, version_spec, profile_id):
        _text(value)
    selected = [
        entry
        for entry in metadata.entry_points(group="mania.extensions")
        if entry.name == id
    ]
    if len(selected) != 1:
        raise ExtensionError("Selected extension is missing or duplicate")
    entry = selected[0]
    dist = entry.dist
    if dist is None or version_spec != f"=={dist.version}":
        raise ExtensionError(
            "Selected extension requires an exact matching version pin"
        )
    if metadata.version("mania-wania") != __version__:
        raise ExtensionError("Installed core version skew")
    requires = dist.requires or []
    if requires != [f"mania-wania=={__version__}"]:
        raise ExtensionError("Extension must depend exactly on the installed core")
    # The explicitly selected entry point is trusted Python. No other entry
    # point is loaded, including when this selected factory is invalid.
    factory = entry.load()
    contributions = factory()
    if type(contributions) is not tuple or not contributions:
        raise ExtensionError("Extension must return immutable profile contributions")
    profiles: set[str] = set()
    chosen = None
    expected_metadata = None
    for contribution in contributions:
        if type(contribution) is not ExtensionContribution:
            raise ExtensionError("Invalid contribution type")
        contribution.__post_init__()
        declared = contribution.metadata
        if (
            declared.id != id
            or declared.distribution != dist.metadata["Name"]
            or declared.version != dist.version
        ):
            raise ExtensionError("Installed and declared extension identities conflict")
        if expected_metadata is not None and declared != expected_metadata:
            raise ExtensionError("Conflicting metadata across profiles")
        expected_metadata = declared
        if contribution.profile_id in profiles:
            raise ExtensionError("Duplicate profile contributions")
        profiles.add(contribution.profile_id)
        if contribution.profile_id == profile_id:
            chosen = contribution
    if chosen is None:
        raise ExtensionError("Requested profile is unavailable")
    return chosen
