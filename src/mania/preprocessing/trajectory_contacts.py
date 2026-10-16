"""Dependency-free contracts and single-condition contact computation."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from numbers import Integral
from typing import Any, TypeAlias, cast

from mania.preprocessing import (
    trajectory_contact_accumulator,
    trajectory_contact_chemistry,
    trajectory_frame_sampling,
    trajectory_frame_selection,
    trajectory_manifest_loader,
    trajectory_runtime,
)

InteractionAccumulator: TypeAlias = (
    trajectory_contact_accumulator.InteractionAccumulator
)
InteractionAggregateResult: TypeAlias = (
    trajectory_contact_accumulator.InteractionAggregateResult
)

PreprocessingConditionLoadResult: TypeAlias = (
    trajectory_runtime.PreprocessingConditionLoadResult
)
PreprocessingManifestLoadResult: TypeAlias = (
    trajectory_manifest_loader.PreprocessingManifestLoadResult
)
PreprocessingFrameSamplingOptions: TypeAlias = (
    trajectory_frame_sampling.PreprocessingFrameSamplingOptions
)

_ATOM_FILTERS = ("heavy", "all")
_CONTACT_SELECTIONS = ("all", "protein")
_CONTACT_LEVEL = "residue"
_DISTANCE_DEFINITION = "minimum_selected_atom_distance"
_FRAME_SCOPE = "per_frame"
_PAIR_SCOPE = "distinct_residue_pair"
_RESIDUE_CONTACT_EDGE_TYPE = "residue_contact"
_BACKBONE_EDGE_TYPE = "backbone"
_CONTACT_PAIR_EDGE_TYPES = (
    _RESIDUE_CONTACT_EDGE_TYPE,
    "hbond",
    "disulfide",
    "vdw",
    "hydrophobic",
    "ionic",
    "salt_bridge",
    "aromatic_pi",
    "cation_pi",
)
BACKBONE_MAX_CA_DIST_A = 4.5
_CONTACT_RESULT_STATUSES = (
    "not_computed",
    "computed",
    "partial",
    "failed",
)
_CONTACT_PROGRESS_STAGES = (
    "condition_start",
    "condition_selection",
    "frame_start",
    "frame_candidates_built",
    "frame_limit_exceeded",
    "frame_done",
    "condition_done",
)
_BOOLEAN_OPTION_FIELDS = (
    "exclude_same_residue",
    "exclude_duplicate_pairs",
    "include_frame_index",
    "include_time_ps",
)
_TRAJECTORY_ATTRIBUTE = "trajectory"
_RESIDUES_ATTRIBUTE = "residues"
_ATOMS_ATTRIBUTE = "atoms"
_POSITION_ATTRIBUTE = "position"
_POSITIONS_ATTRIBUTE = "positions"
_TIME_ATTRIBUTE = "time"

_Coordinate = tuple[float, float, float]


def _require_positive_finite_number(value: object, field_name: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError(f"{field_name} must be a finite positive number")


def _normalize_unit(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("distance_unit must be a non-empty string")
    normalized = value.strip()
    if not normalized:
        raise ValueError("distance_unit must be a non-empty string")
    return normalized


def _normalize_skip_resnames(value: object) -> tuple[str, ...]:
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        raise ValueError("skip_resnames must be a list or tuple")

    normalized_resnames: list[str] = []
    seen_resnames: set[str] = set()
    for resname in value:
        if not isinstance(resname, str):
            raise ValueError("skip_resnames entries must be strings")
        normalized = resname.strip()
        if not normalized:
            raise ValueError("skip_resnames entries must not be empty")
        if normalized not in seen_resnames:
            normalized_resnames.append(normalized)
            seen_resnames.add(normalized)
    return tuple(normalized_resnames)


def _normalize_non_empty_string(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a non-empty string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must be a non-empty string")
    return normalized


def _normalize_contact_selection(value: object) -> str:
    normalized = _normalize_non_empty_string(value, "contact_selection")
    if normalized not in _CONTACT_SELECTIONS:
        raise ValueError("contact_selection must be 'all' or 'protein'")
    return normalized


def _normalize_optional_residue_id(
    value: object,
    field_name: str,
) -> int | str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError(f"{field_name} must be an int, string, or None")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return _normalize_non_empty_string(value, field_name)
    raise ValueError(f"{field_name} must be an int, string, or None")


def _normalize_optional_string(
    value: object,
    field_name: str,
) -> str | None:
    if value is None:
        return None
    return _normalize_non_empty_string(value, field_name)


def _require_non_negative_int(value: object, field_name: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
    ):
        raise ValueError(f"{field_name} must be a non-negative int")


def _require_optional_positive_int(value: object, field_name: str) -> None:
    if value is None:
        return
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
    ):
        raise ValueError(f"{field_name} must be a positive int or None")


def _require_non_negative_finite_number(
    value: object,
    field_name: str,
) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(
            f"{field_name} must be a finite non-negative number"
        )


def _require_optional_non_negative_finite_number(
    value: object,
    field_name: str,
) -> None:
    if value is not None:
        _require_non_negative_finite_number(value, field_name)


def _require_finite_number(value: object, field_name: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
    ):
        raise ValueError(f"{field_name} must be a finite number")


@dataclass(frozen=True)
class PreprocessingContactDefinition:
    """Serializable definition of the Stage 13 residue contact MVP."""

    contact_level: str = _CONTACT_LEVEL
    distance_definition: str = _DISTANCE_DEFINITION
    frame_scope: str = _FRAME_SCOPE
    pair_scope: str = _PAIR_SCOPE
    default_atom_filter: str = "heavy"
    default_cutoff_distance: float = 4.5
    distance_unit: str = "angstrom"

    def __post_init__(self) -> None:
        if self.contact_level != _CONTACT_LEVEL:
            raise ValueError("contact_level must be 'residue'")
        if self.distance_definition != _DISTANCE_DEFINITION:
            raise ValueError(
                "distance_definition must be "
                "'minimum_selected_atom_distance'"
            )
        if self.frame_scope != _FRAME_SCOPE:
            raise ValueError("frame_scope must be 'per_frame'")
        if self.pair_scope != _PAIR_SCOPE:
            raise ValueError("pair_scope must be 'distinct_residue_pair'")
        if self.default_atom_filter not in _ATOM_FILTERS:
            raise ValueError("default_atom_filter must be 'heavy' or 'all'")
        _require_positive_finite_number(
            self.default_cutoff_distance,
            "default_cutoff_distance",
        )
        object.__setattr__(
            self,
            "distance_unit",
            _normalize_unit(self.distance_unit),
        )

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic JSON-serializable definition dictionary."""
        return {
            "contact_level": self.contact_level,
            "distance_definition": self.distance_definition,
            "frame_scope": self.frame_scope,
            "pair_scope": self.pair_scope,
            "default_atom_filter": self.default_atom_filter,
            "default_cutoff_distance": self.default_cutoff_distance,
            "distance_unit": self.distance_unit,
        }


@dataclass(frozen=True)
class PreprocessingContactDetectionOptions:
    """Configuration reserved for future residue contact extraction."""

    cutoff_distance: float = 4.5
    distance_unit: str = "angstrom"
    atom_filter: str = "heavy"
    contact_level: str = _CONTACT_LEVEL
    contact_selection: str = "all"
    exclude_same_residue: bool = True
    exclude_duplicate_pairs: bool = True
    skip_resnames: tuple[str, ...] = ()
    include_frame_index: bool = True
    include_time_ps: bool = True

    def __post_init__(self) -> None:
        _require_positive_finite_number(
            self.cutoff_distance,
            "cutoff_distance",
        )
        object.__setattr__(
            self,
            "distance_unit",
            _normalize_unit(self.distance_unit),
        )
        if self.atom_filter not in _ATOM_FILTERS:
            raise ValueError("atom_filter must be 'heavy' or 'all'")
        if self.contact_level != _CONTACT_LEVEL:
            raise ValueError("contact_level must be 'residue'")
        contact_selection = _normalize_contact_selection(
            self.contact_selection
        )
        object.__setattr__(
            self,
            "contact_selection",
            contact_selection,
        )
        for field_name in _BOOLEAN_OPTION_FIELDS:
            if not isinstance(getattr(self, field_name), bool):
                raise ValueError(f"{field_name} must be a bool")
        object.__setattr__(
            self,
            "skip_resnames",
            _normalize_skip_resnames(self.skip_resnames),
        )

    def to_dict(
        self,
        *,
        include_contact_selection: bool = False,
    ) -> dict[str, object]:
        """Return a deterministic JSON-serializable options dictionary."""
        payload: dict[str, object] = {
            "cutoff_distance": self.cutoff_distance,
            "distance_unit": self.distance_unit,
            "atom_filter": self.atom_filter,
            "contact_level": self.contact_level,
            "exclude_same_residue": self.exclude_same_residue,
            "exclude_duplicate_pairs": self.exclude_duplicate_pairs,
            "skip_resnames": list(self.skip_resnames),
            "include_frame_index": self.include_frame_index,
            "include_time_ps": self.include_time_ps,
        }
        if include_contact_selection:
            payload["contact_selection"] = self.contact_selection
        return payload


@dataclass(frozen=True)
class PreprocessingContactComputationLimits:
    """Optional smoke/debug guards for per-frame contacts computation."""

    max_residue_pairs_per_frame: int | None = None
    max_atom_distance_evaluations_per_frame: int | None = None

    def __post_init__(self) -> None:
        _require_optional_positive_int(
            self.max_residue_pairs_per_frame,
            "max_residue_pairs_per_frame",
        )
        _require_optional_positive_int(
            self.max_atom_distance_evaluations_per_frame,
            "max_atom_distance_evaluations_per_frame",
        )

    def to_dict(self) -> dict[str, object]:
        """Return deterministic JSON-safe contact computation limits."""
        return {
            "max_residue_pairs_per_frame": (
                self.max_residue_pairs_per_frame
            ),
            "max_atom_distance_evaluations_per_frame": (
                self.max_atom_distance_evaluations_per_frame
            ),
        }


@dataclass(frozen=True)
class PreprocessingContactProgressEvent:
    """One lightweight contacts progress event."""

    condition_name: str
    frame_index: int | None
    stage: str
    message: str
    residue_count: int | None = None
    candidate_pair_count: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "condition_name",
            _normalize_non_empty_string(
                self.condition_name,
                "condition_name",
            ),
        )
        if self.frame_index is not None:
            _require_non_negative_int(self.frame_index, "frame_index")
        if self.stage not in _CONTACT_PROGRESS_STAGES:
            raise ValueError("stage must be a supported contacts stage")
        object.__setattr__(
            self,
            "message",
            _normalize_non_empty_string(self.message, "message"),
        )
        if self.residue_count is not None:
            _require_non_negative_int(self.residue_count, "residue_count")
        if self.candidate_pair_count is not None:
            _require_non_negative_int(
                self.candidate_pair_count,
                "candidate_pair_count",
            )


ContactProgressCallback: TypeAlias = Callable[
    [PreprocessingContactProgressEvent],
    None,
]


@dataclass(frozen=True)
class PreprocessingContactComputationIssue:
    """One deterministic contacts result or computation issue."""

    kind: str
    field: str
    message: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "kind",
            _normalize_non_empty_string(self.kind, "kind"),
        )
        object.__setattr__(
            self,
            "field",
            _normalize_non_empty_string(self.field, "field"),
        )
        object.__setattr__(
            self,
            "message",
            _normalize_non_empty_string(self.message, "message"),
        )

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic JSON-serializable issue dictionary."""
        return {
            "kind": self.kind,
            "field": self.field,
            "message": self.message,
        }


@dataclass(frozen=True)
class PreprocessingCaCoordinate:
    """Representative Cα coordinate for one selected residue."""

    residue_index: int
    residue_id: int | str | None
    resname: str
    segid: str | None
    x_ca: float
    y_ca: float
    z_ca: float

    def __post_init__(self) -> None:
        _require_non_negative_int(self.residue_index, "residue_index")
        object.__setattr__(
            self,
            "residue_id",
            _normalize_optional_residue_id(self.residue_id, "residue_id"),
        )
        object.__setattr__(
            self,
            "resname",
            _normalize_non_empty_string(self.resname, "resname"),
        )
        object.__setattr__(
            self,
            "segid",
            _normalize_optional_string(self.segid, "segid"),
        )
        for field_name in ("x_ca", "y_ca", "z_ca"):
            _require_finite_number(getattr(self, field_name), field_name)
            object.__setattr__(self, field_name, float(getattr(self, field_name)))

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic JSON-safe coordinate dictionary."""
        return {
            "residue_index": self.residue_index,
            "residue_id": self.residue_id,
            "resname": self.resname,
            "segid": self.segid,
            "x_ca": self.x_ca,
            "y_ca": self.y_ca,
            "z_ca": self.z_ca,
        }


@dataclass(frozen=True)
class PreprocessingContactPairResult:
    """One residue-residue contact observed in one frame."""

    source_residue_index: int
    target_residue_index: int
    source_resname: str
    target_resname: str
    minimum_distance: float
    distance_unit: str = "angstrom"
    atom_filter: str = "heavy"
    source_residue_id: int | str | None = None
    target_residue_id: int | str | None = None
    source_segid: str | None = None
    target_segid: str | None = None
    edge_type: str = _RESIDUE_CONTACT_EDGE_TYPE

    def __post_init__(self) -> None:
        _require_non_negative_int(
            self.source_residue_index,
            "source_residue_index",
        )
        _require_non_negative_int(
            self.target_residue_index,
            "target_residue_index",
        )
        if self.source_residue_index == self.target_residue_index:
            raise ValueError("source and target residue indexes must differ")
        object.__setattr__(
            self,
            "source_resname",
            _normalize_non_empty_string(
                self.source_resname,
                "source_resname",
            ),
        )
        object.__setattr__(
            self,
            "target_resname",
            _normalize_non_empty_string(
                self.target_resname,
                "target_resname",
            ),
        )
        _require_non_negative_finite_number(
            self.minimum_distance,
            "minimum_distance",
        )
        object.__setattr__(
            self,
            "distance_unit",
            _normalize_unit(self.distance_unit),
        )
        if self.atom_filter not in _ATOM_FILTERS:
            raise ValueError("atom_filter must be 'heavy' or 'all'")
        if self.edge_type not in _CONTACT_PAIR_EDGE_TYPES:
            raise ValueError(
                "edge_type must be a supported protein contact type"
            )
        object.__setattr__(
            self,
            "source_residue_id",
            _normalize_optional_residue_id(
                self.source_residue_id,
                "source_residue_id",
            ),
        )
        object.__setattr__(
            self,
            "target_residue_id",
            _normalize_optional_residue_id(
                self.target_residue_id,
                "target_residue_id",
            ),
        )
        object.__setattr__(
            self,
            "source_segid",
            _normalize_optional_string(self.source_segid, "source_segid"),
        )
        object.__setattr__(
            self,
            "target_segid",
            _normalize_optional_string(self.target_segid, "target_segid"),
        )

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic JSON-serializable contact pair."""
        payload: dict[str, object] = {
            "source_residue_index": self.source_residue_index,
            "target_residue_index": self.target_residue_index,
            "source_resname": self.source_resname,
            "target_resname": self.target_resname,
            "minimum_distance": self.minimum_distance,
            "distance_unit": self.distance_unit,
            "atom_filter": self.atom_filter,
            "source_residue_id": self.source_residue_id,
            "target_residue_id": self.target_residue_id,
            "source_segid": self.source_segid,
            "target_segid": self.target_segid,
        }
        if self.edge_type != _RESIDUE_CONTACT_EDGE_TYPE:
            payload["edge_type"] = self.edge_type
        return payload


@dataclass(frozen=True)
class PreprocessingBackboneObservation:
    """One structural backbone observation in one sampled frame."""

    source_residue_index: int
    target_residue_index: int
    source_resname: str
    target_resname: str
    ca_distance: float
    distance_unit: str = "angstrom"
    source_residue_id: int | str | None = None
    target_residue_id: int | str | None = None
    source_segid: str | None = None
    target_segid: str | None = None
    edge_type: str = _BACKBONE_EDGE_TYPE

    def __post_init__(self) -> None:
        _require_non_negative_int(
            self.source_residue_index,
            "source_residue_index",
        )
        _require_non_negative_int(
            self.target_residue_index,
            "target_residue_index",
        )
        if self.target_residue_index != self.source_residue_index + 1:
            raise ValueError("backbone residue indexes must be sequential")
        for field_name in ("source_resname", "target_resname"):
            object.__setattr__(
                self,
                field_name,
                _normalize_non_empty_string(
                    getattr(self, field_name),
                    field_name,
                ),
            )
        _require_non_negative_finite_number(
            self.ca_distance,
            "ca_distance",
        )
        object.__setattr__(
            self,
            "distance_unit",
            _normalize_unit(self.distance_unit),
        )
        for field_name in ("source_residue_id", "target_residue_id"):
            object.__setattr__(
                self,
                field_name,
                _normalize_optional_residue_id(
                    getattr(self, field_name),
                    field_name,
                ),
            )
        for field_name in ("source_segid", "target_segid"):
            object.__setattr__(
                self,
                field_name,
                _normalize_optional_string(
                    getattr(self, field_name),
                    field_name,
                ),
            )
        if self.source_segid != self.target_segid:
            raise ValueError("backbone residues must have the same chain id")
        if self.edge_type != _BACKBONE_EDGE_TYPE:
            raise ValueError("edge_type must be 'backbone'")

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic JSON-safe observation dictionary."""
        return {
            "source_residue_index": self.source_residue_index,
            "target_residue_index": self.target_residue_index,
            "source_resname": self.source_resname,
            "target_resname": self.target_resname,
            "ca_distance": self.ca_distance,
            "distance_unit": self.distance_unit,
            "source_residue_id": self.source_residue_id,
            "target_residue_id": self.target_residue_id,
            "source_segid": self.source_segid,
            "target_segid": self.target_segid,
            "edge_type": self.edge_type,
        }


@dataclass(frozen=True)
class PreprocessingContactFrameResult:
    """Contacts detected for one condition frame."""

    condition_name: str
    frame_index: int
    time_ps: float | None = None
    contacts: tuple[PreprocessingContactPairResult, ...] = ()
    backbone_observations: tuple[PreprocessingBackboneObservation, ...] = ()
    issues: tuple[PreprocessingContactComputationIssue, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "condition_name",
            _normalize_non_empty_string(
                self.condition_name,
                "condition_name",
            ),
        )
        _require_non_negative_int(self.frame_index, "frame_index")
        _require_optional_non_negative_finite_number(
            self.time_ps,
            "time_ps",
        )
        for contact in self.contacts:
            if not isinstance(contact, PreprocessingContactPairResult):
                raise ValueError(
                    "contacts must contain PreprocessingContactPairResult"
                )
        for observation in self.backbone_observations:
            if not isinstance(observation, PreprocessingBackboneObservation):
                raise ValueError(
                    "backbone_observations must contain "
                    "PreprocessingBackboneObservation"
                )
        for issue in self.issues:
            if not isinstance(issue, PreprocessingContactComputationIssue):
                raise ValueError(
                    "issues must contain "
                    "PreprocessingContactComputationIssue"
                )

    @property
    def contact_count(self) -> int:
        """Return the number of contact pairs in this frame."""
        return len(self.contacts)

    @property
    def passed(self) -> bool:
        """Return whether this frame has no contacts issues."""
        return self.issues == ()

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic JSON-serializable frame result."""
        return {
            "condition_name": self.condition_name,
            "frame_index": self.frame_index,
            "time_ps": self.time_ps,
            "contact_count": self.contact_count,
            "contacts": [contact.to_dict() for contact in self.contacts],
            "backbone_observation_count": len(self.backbone_observations),
            "backbone_observations": [
                observation.to_dict()
                for observation in self.backbone_observations
            ],
            "issues": [issue.to_dict() for issue in self.issues],
            "passed": self.passed,
        }


@dataclass(frozen=True)
class PreprocessingConditionContactsResult:
    """Aggregate contacts results for one condition."""

    condition_name: str
    options: PreprocessingContactDetectionOptions
    computation_limits: PreprocessingContactComputationLimits = field(
        default_factory=PreprocessingContactComputationLimits
    )
    representative_ca_coordinates: tuple[PreprocessingCaCoordinate, ...] = ()
    frame_results: tuple[PreprocessingContactFrameResult, ...] = ()
    interaction_aggregates: tuple[InteractionAggregateResult, ...] = ()
    issues: tuple[PreprocessingContactComputationIssue, ...] = ()
    status: str = "not_computed"

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "condition_name",
            _normalize_non_empty_string(
                self.condition_name,
                "condition_name",
            ),
        )
        if not isinstance(self.options, PreprocessingContactDetectionOptions):
            raise ValueError(
                "options must be PreprocessingContactDetectionOptions"
            )
        if not isinstance(
            self.computation_limits,
            PreprocessingContactComputationLimits,
        ):
            raise ValueError(
                "computation_limits must be "
                "PreprocessingContactComputationLimits"
            )
        coordinate_indexes: set[int] = set()
        for coordinate in self.representative_ca_coordinates:
            if not isinstance(coordinate, PreprocessingCaCoordinate):
                raise ValueError(
                    "representative_ca_coordinates must contain "
                    "PreprocessingCaCoordinate"
                )
            if coordinate.residue_index in coordinate_indexes:
                raise ValueError(
                    "representative Cα residue indexes must be unique"
                )
            coordinate_indexes.add(coordinate.residue_index)
        frame_indexes: set[int] = set()
        for frame_result in self.frame_results:
            if not isinstance(frame_result, PreprocessingContactFrameResult):
                raise ValueError(
                    "frame_results must contain "
                    "PreprocessingContactFrameResult"
                )
            if frame_result.condition_name != self.condition_name:
                raise ValueError(
                    "frame result condition_name must match condition result"
                )
            if frame_result.frame_index in frame_indexes:
                raise ValueError(
                    "frame result indexes must be unique within a condition"
                )
            frame_indexes.add(frame_result.frame_index)
        for aggregate in self.interaction_aggregates:
            if not isinstance(aggregate, InteractionAggregateResult):
                raise ValueError(
                    "interaction_aggregates must contain "
                    "InteractionAggregateResult"
                )
            if aggregate.condition_name != self.condition_name:
                raise ValueError(
                    "interaction aggregate condition_name must match "
                    "condition result"
                )
        for issue in self.issues:
            if not isinstance(issue, PreprocessingContactComputationIssue):
                raise ValueError(
                    "issues must contain "
                    "PreprocessingContactComputationIssue"
                )
        if self.status not in _CONTACT_RESULT_STATUSES:
            raise ValueError(
                "status must be not_computed, computed, partial, or failed"
            )

    @property
    def frame_count(self) -> int:
        """Return the number of frame results."""
        return len(self.frame_results)

    @property
    def contact_count(self) -> int:
        """Return the total number of contact pairs across frames."""
        return sum(frame.contact_count for frame in self.frame_results)

    @property
    def passed_frame_count(self) -> int:
        """Return the number of frame results without issues."""
        return sum(frame.passed for frame in self.frame_results)

    @property
    def failed_frame_count(self) -> int:
        """Return the number of frame results with issues."""
        return self.frame_count - self.passed_frame_count

    @property
    def passed(self) -> bool:
        """Return whether the condition was fully computed without issues."""
        return (
            self.status == "computed"
            and self.issues == ()
            and all(frame.passed for frame in self.frame_results)
        )

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic JSON-serializable condition result."""
        return {
            "condition_name": self.condition_name,
            "status": self.status,
            "options": self.options.to_dict(),
            "contact_computation_limits": (
                self.computation_limits.to_dict()
            ),
            "representative_ca_coordinates": [
                coordinate.to_dict()
                for coordinate in self.representative_ca_coordinates
            ],
            "frame_count": self.frame_count,
            "contact_count": self.contact_count,
            "passed_frame_count": self.passed_frame_count,
            "failed_frame_count": self.failed_frame_count,
            "frame_results": [
                frame_result.to_dict()
                for frame_result in self.frame_results
            ],
            "issues": [issue.to_dict() for issue in self.issues],
            "passed": self.passed,
        }


@dataclass(frozen=True)
class PreprocessingManifestContactsResult:
    """Aggregate contacts results for manifest conditions."""

    condition_results: tuple[PreprocessingConditionContactsResult, ...] = ()
    issues: tuple[PreprocessingContactComputationIssue, ...] = ()
    computation_limits: PreprocessingContactComputationLimits = field(
        default_factory=PreprocessingContactComputationLimits
    )

    def __post_init__(self) -> None:
        condition_names: set[str] = set()
        for condition_result in self.condition_results:
            if not isinstance(
                condition_result,
                PreprocessingConditionContactsResult,
            ):
                raise ValueError(
                    "condition_results must contain "
                    "PreprocessingConditionContactsResult"
                )
            if condition_result.condition_name in condition_names:
                raise ValueError("condition result names must be unique")
            condition_names.add(condition_result.condition_name)
        for issue in self.issues:
            if not isinstance(issue, PreprocessingContactComputationIssue):
                raise ValueError(
                    "issues must contain "
                    "PreprocessingContactComputationIssue"
                )
        if not isinstance(
            self.computation_limits,
            PreprocessingContactComputationLimits,
        ):
            raise ValueError(
                "computation_limits must be "
                "PreprocessingContactComputationLimits"
            )

    @property
    def condition_count(self) -> int:
        """Return the number of condition results."""
        return len(self.condition_results)

    @property
    def computed_condition_count(self) -> int:
        """Return the number of conditions with computed status."""
        return sum(
            result.status == "computed"
            for result in self.condition_results
        )

    @property
    def failed_condition_count(self) -> int:
        """Return the number of condition results that do not pass."""
        return sum(not result.passed for result in self.condition_results)

    @property
    def frame_count(self) -> int:
        """Return the total number of frame results."""
        return sum(result.frame_count for result in self.condition_results)

    @property
    def contact_count(self) -> int:
        """Return the total number of contact pairs."""
        return sum(result.contact_count for result in self.condition_results)

    @property
    def passed_frame_count(self) -> int:
        """Return the total number of passing frame results."""
        return sum(
            result.passed_frame_count for result in self.condition_results
        )

    @property
    def failed_frame_count(self) -> int:
        """Return the total number of failing frame results."""
        return sum(
            result.failed_frame_count for result in self.condition_results
        )

    @property
    def passed(self) -> bool:
        """Return whether every available condition passes."""
        return (
            self.issues == ()
            and bool(self.condition_results)
            and all(result.passed for result in self.condition_results)
        )

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic JSON-serializable manifest result."""
        return {
            "condition_count": self.condition_count,
            "computed_condition_count": self.computed_condition_count,
            "failed_condition_count": self.failed_condition_count,
            "frame_count": self.frame_count,
            "contact_count": self.contact_count,
            "passed_frame_count": self.passed_frame_count,
            "failed_frame_count": self.failed_frame_count,
            "contact_computation_limits": (
                self.computation_limits.to_dict()
            ),
            "condition_results": [
                condition_result.to_dict()
                for condition_result in self.condition_results
            ],
            "issues": [issue.to_dict() for issue in self.issues],
            "passed": self.passed,
        }


@dataclass(frozen=True)
class _ResidueCandidate:
    index: int
    resname: str
    residue_id: int | str | None
    segid: str | None
    coordinates: tuple[_Coordinate, ...]


@dataclass(frozen=True)
class ContactResidueAtomCacheEntry:
    """Stable residue metadata and filtered atoms used by contact frames."""

    residue_index: int
    residue_id: int | str | None
    resname: str | None
    segid: str | None
    atom_group: object | None
    all_atoms: tuple[object, ...]
    distance_atoms: tuple[object, ...]
    atom_indexes: tuple[int, ...]
    atom_count: int
    contact_eligible: bool
    issues: tuple[PreprocessingContactComputationIssue, ...] = ()

    def __post_init__(self) -> None:
        _require_non_negative_int(self.residue_index, "residue_index")
        _require_non_negative_int(self.atom_count, "atom_count")
        if self.atom_count != len(self.distance_atoms):
            raise ValueError("atom_count must match cached atoms")
        if len(self.atom_indexes) != len(self.distance_atoms):
            raise ValueError("atom_indexes must match cached atoms")
        if not isinstance(self.contact_eligible, bool):
            raise ValueError("contact_eligible must be a bool")

    @property
    def atoms(self) -> tuple[object, ...]:
        """Return atoms selected for residue distance calculations."""
        return self.distance_atoms


def build_atom_cache(
    residue_items: Iterable[object],
    *,
    options: PreprocessingContactDetectionOptions,
) -> tuple[ContactResidueAtomCacheEntry, ...]:
    """Cache selected residue atoms and stable metadata before frame iteration."""
    entries: list[ContactResidueAtomCacheEntry] = []
    for residue_index, residue in enumerate(residue_items):
        raw_resname, has_resname = _read_attribute(residue, "resname")
        resname = (
            str(raw_resname).strip()
            if has_resname and raw_resname is not None
            else None
        )
        if resname == "":
            resname = None

        issues: list[PreprocessingContactComputationIssue] = []
        if resname is None:
            issues.append(
                PreprocessingContactComputationIssue(
                    kind="contact_computation_error",
                    field=f"residues[{residue_index}].resname",
                    message=(
                        "Residue name is unavailable."
                        if not has_resname or raw_resname is None
                        else "Residue name is empty."
                    ),
                )
            )

        atom_group, has_atom_group = _read_attribute(
            residue,
            _ATOMS_ATTRIBUTE,
        )
        all_atoms: tuple[object, ...] = ()
        atom_iteration_failed = False
        if has_atom_group and atom_group is not None:
            try:
                all_atoms = tuple(cast(Iterable[object], atom_group))
            except Exception:
                atom_iteration_failed = True
                issues.append(
                    PreprocessingContactComputationIssue(
                        kind="contact_computation_error",
                        field=f"residues[{residue_index}]_atoms",
                        message="Residue atoms could not be iterated.",
                    )
                )
        else:
            atom_group = None

        cached_atoms: list[object] = []
        atom_indexes: list[int] = []
        for atom_index, atom in enumerate(all_atoms):
            if options.atom_filter == "heavy" and _is_hydrogen(atom):
                continue
            cached_atoms.append(atom)
            atom_indexes.append(atom_index)

        contact_eligible = (
            resname is not None
            and resname not in options.skip_resnames
            and not atom_iteration_failed
        )
        entries.append(
            ContactResidueAtomCacheEntry(
                residue_index=residue_index,
                residue_id=_residue_id(residue),
                resname=resname,
                segid=_segid(residue),
                atom_group=atom_group,
                all_atoms=all_atoms,
                distance_atoms=tuple(cached_atoms),
                atom_indexes=tuple(atom_indexes),
                atom_count=len(cached_atoms),
                contact_eligible=contact_eligible,
                issues=tuple(issues),
            )
        )
    return tuple(entries)


def compute_condition_contacts(
    condition_load_result: PreprocessingConditionLoadResult,
    *,
    options: PreprocessingContactDetectionOptions | None = None,
    computation_limits: PreprocessingContactComputationLimits | None = None,
    frame_sampling: PreprocessingFrameSamplingOptions | None = None,
    source_frame_indexes: tuple[int, ...] | None = None,
    progress_callback: ContactProgressCallback | None = None,
    selected_frame_observer: Callable[[str, int, float | None], None] | None = None,
) -> PreprocessingConditionContactsResult:
    """Compute per-frame contacts from one already loaded condition."""
    selected_options = options or PreprocessingContactDetectionOptions()
    selected_limits = _contact_computation_limits(computation_limits)
    if source_frame_indexes is not None and frame_sampling is not None:
        raise ValueError(
            "source_frame_indexes and frame_sampling are mutually exclusive"
        )
    selected_frame_sampling = _frame_sampling_options(frame_sampling)
    option_issue = _unsupported_options_issue(selected_options)
    if option_issue is not None:
        return _condition_contacts_result(
            condition_load_result.condition_name,
            selected_options,
            selected_limits,
            status="failed",
            issues=(option_issue,),
        )

    runtime = condition_load_result.runtime
    if condition_load_result.status == "loaded" and runtime is None:
        return _condition_contacts_result(
            condition_load_result.condition_name,
            selected_options,
            selected_limits,
            status="failed",
            issues=(_missing_runtime_issue(),),
        )
    if not condition_load_result.passed:
        issues = _condition_load_issues(condition_load_result)
        if runtime is None or runtime.runtime_object is None:
            issues.append(_missing_runtime_issue())
        return _condition_contacts_result(
            condition_load_result.condition_name,
            selected_options,
            selected_limits,
            status="failed",
            issues=tuple(issues),
        )

    if runtime is None or runtime.runtime_object is None:
        return _condition_contacts_result(
            condition_load_result.condition_name,
            selected_options,
            selected_limits,
            status="failed",
            issues=(_missing_runtime_issue(),),
        )

    runtime_object = runtime.runtime_object
    trajectory, has_trajectory = _read_attribute(
        runtime_object,
        _TRAJECTORY_ATTRIBUTE,
    )
    fatal_issues: list[PreprocessingContactComputationIssue] = []
    if not has_trajectory or trajectory is None:
        fatal_issues.append(
            PreprocessingContactComputationIssue(
                kind="missing_trajectory",
                field="runtime_object_trajectory",
                message="Runtime object has no usable trajectory.",
            )
        )
    if fatal_issues:
        return _condition_contacts_result(
            condition_load_result.condition_name,
            selected_options,
            selected_limits,
            status="failed",
            issues=tuple(fatal_issues),
        )

    residue_items, selection_issue = _selected_contact_residue_items(
        runtime_object,
        selected_options,
    )
    if selection_issue is not None:
        return _condition_contacts_result(
            condition_load_result.condition_name,
            selected_options,
            selected_limits,
            status="failed",
            issues=(selection_issue,),
        )

    atom_cache = build_atom_cache(
        residue_items,
        options=selected_options,
    )
    contact_atom_cache = tuple(
        entry for entry in atom_cache if entry.contact_eligible
    )
    candidate_pair_count = _candidate_pair_count(contact_atom_cache)
    atom_distance_evaluation_count = _atom_distance_evaluation_count(
        contact_atom_cache
    )
    frame_time_ps = _usable_non_negative_float(
        condition_load_result.runtime_input.frame_time_ps
    )
    frame_results: list[PreprocessingContactFrameResult] = []
    representative_ca_coordinates: tuple[PreprocessingCaCoordinate, ...] = ()
    representative_coordinates_captured = False
    condition_issues: list[PreprocessingContactComputationIssue] = []
    _emit_progress(
        progress_callback,
        PreprocessingContactProgressEvent(
            condition_name=condition_load_result.condition_name,
            frame_index=None,
            stage="condition_start",
            message="starting contacts computation",
            residue_count=len(residue_items),
        ),
    )
    _emit_progress(
        progress_callback,
        PreprocessingContactProgressEvent(
            condition_name=condition_load_result.condition_name,
            frame_index=None,
            stage="condition_selection",
            message=f"contact selection={selected_options.contact_selection}",
            residue_count=len(residue_items),
        ),
    )
    try:
        trajectory_iterator = iter(
            trajectory_frame_selection.iter_selected_trajectory_frames(
                cast(Iterable[object], trajectory), source_frame_indexes,
            )
            if source_frame_indexes is not None
            else trajectory_frame_sampling.iter_sampled_trajectory_frames(
                cast(Iterable[object], trajectory),
                selected_frame_sampling,
            )
        )
    except Exception:
        condition_issues.append(_frame_iteration_issue())
    else:
        while True:
            try:
                frame_index, timestep = next(trajectory_iterator)
            except StopIteration:
                break
            except Exception:
                condition_issues.append(_frame_iteration_issue())
                break

            if not representative_coordinates_captured:
                representative_ca_coordinates = _representative_ca_coordinates(
                    atom_cache
                )
                representative_coordinates_captured = True

            try:
                frame_result = _compute_contact_frame(
                    condition_name=condition_load_result.condition_name,
                    frame_index=frame_index,
                    timestep=timestep,
                    frame_time_ps=frame_time_ps,
                    atom_cache=atom_cache,
                    contact_atom_cache=contact_atom_cache,
                    candidate_pair_count=candidate_pair_count,
                    atom_distance_evaluation_count=(
                        atom_distance_evaluation_count
                    ),
                    options=selected_options,
                    computation_limits=selected_limits,
                    progress_callback=progress_callback,
                )
            except Exception:
                frame_result = PreprocessingContactFrameResult(
                    condition_name=condition_load_result.condition_name,
                    frame_index=frame_index,
                    time_ps=_frame_time(
                        timestep,
                        frame_index,
                        frame_time_ps,
                    ),
                    issues=(
                        PreprocessingContactComputationIssue(
                            kind="contact_computation_error",
                            field=f"frames[{frame_index}]",
                            message=(
                                "Contacts could not be computed for this "
                                "frame."
                            ),
                        ),
                    ),
                )
            if selected_frame_observer is not None:
                selected_frame_observer(
                    condition_load_result.condition_name,
                    frame_index,
                    frame_result.time_ps,
                )
            frame_results.append(frame_result)

    if not frame_results and not condition_issues:
        condition_issues.append(
            PreprocessingContactComputationIssue(
                kind="frame_iteration_error",
                field="runtime_object_trajectory",
                message="Runtime trajectory produced no frames.",
            )
        )

    if not frame_results:
        status = "failed"
    elif condition_issues or any(
        not frame_result.passed for frame_result in frame_results
    ):
        status = "partial"
    else:
        status = "computed"

    interaction_aggregates = (
        _finalize_condition_interactions(frame_results)
        if status == "computed"
        else ()
    )

    result = _condition_contacts_result(
        condition_load_result.condition_name,
        selected_options,
        selected_limits,
        status=status,
        representative_ca_coordinates=representative_ca_coordinates,
        frame_results=tuple(frame_results),
        interaction_aggregates=interaction_aggregates,
        issues=tuple(condition_issues),
    )
    _emit_progress(
        progress_callback,
        PreprocessingContactProgressEvent(
            condition_name=condition_load_result.condition_name,
            frame_index=None,
            stage="condition_done",
            message=f"contacts computation {status}",
            residue_count=len(residue_items),
        ),
    )
    return result


def _aggregate_manifest_contacts(
    manifest_load_result: PreprocessingManifestLoadResult,
    *,
    options: PreprocessingContactDetectionOptions | None = None,
    computation_limits: PreprocessingContactComputationLimits | None = None,
    frame_sampling: PreprocessingFrameSamplingOptions | None = None,
    source_frame_indexes_by_condition: Mapping[str, tuple[int, ...]] | None = None,
    progress_callback: ContactProgressCallback | None = None,
    selected_frame_observers: Mapping[str, Callable[[str, int, float | None], None]]
    | None = None,
) -> PreprocessingManifestContactsResult:
    """Compose condition contact results across one manifest load result."""
    selected_options = options or PreprocessingContactDetectionOptions()
    selected_limits = _contact_computation_limits(computation_limits)
    if source_frame_indexes_by_condition is not None:
        names = {
            result.condition_name for result in manifest_load_result.condition_results
        }
        if not set(source_frame_indexes_by_condition).issubset(names):
            raise ValueError("Explicit source selection contains unknown conditions")
    selected_frame_sampling = _frame_sampling_options(frame_sampling)
    condition_results: list[PreprocessingConditionContactsResult] = []
    for condition_load_result in manifest_load_result.condition_results:
        try:
            contact_kwargs: dict[str, Any] = {"options": selected_options}
            if computation_limits is not None:
                contact_kwargs["computation_limits"] = selected_limits
            if (
                source_frame_indexes_by_condition is not None
                and condition_load_result.condition_name
                in source_frame_indexes_by_condition
            ):
                contact_kwargs["source_frame_indexes"] = (
                    source_frame_indexes_by_condition[condition_load_result.condition_name]
                )
            elif frame_sampling is not None:
                contact_kwargs["frame_sampling"] = selected_frame_sampling
            if progress_callback is not None:
                contact_kwargs["progress_callback"] = progress_callback
            if selected_frame_observers is not None:
                contact_kwargs["selected_frame_observer"] = (
                    selected_frame_observers.get(condition_load_result.condition_name)
                )
            contact_result = compute_condition_contacts(
                condition_load_result,
                **contact_kwargs,
            )
        except Exception:
            contact_result = _unexpected_condition_contacts_result(
                condition_load_result,
                selected_options,
                selected_limits,
            )
        condition_results.append(contact_result)

    issues = tuple(
        PreprocessingContactComputationIssue(
            kind="manifest_load_issue",
            field=_manifest_load_issue_field(
                issue.condition_name,
                issue.field,
            ),
            message=issue.message,
        )
        for issue in manifest_load_result.issues
    )
    return PreprocessingManifestContactsResult(
        condition_results=tuple(condition_results),
        issues=issues,
        computation_limits=selected_limits,
    )


def _unexpected_condition_contacts_result(
    condition_load_result: PreprocessingConditionLoadResult,
    options: PreprocessingContactDetectionOptions,
    computation_limits: PreprocessingContactComputationLimits,
) -> PreprocessingConditionContactsResult:
    return PreprocessingConditionContactsResult(
        condition_name=condition_load_result.condition_name,
        options=options,
        computation_limits=computation_limits,
        frame_results=(),
        issues=(
            PreprocessingContactComputationIssue(
                kind="condition_contacts_error",
                field="compute_condition_contacts",
                message="Condition contacts computation failed unexpectedly.",
            ),
        ),
        status="failed",
    )


def _manifest_load_issue_field(
    condition_name: str | None,
    field: str,
) -> str:
    if condition_name is None:
        return field
    return f"conditions[{condition_name}].{field}"


_MANIFEST_CONTACTS_API_NAME = "compute_" + "manifest_contacts"
_aggregate_manifest_contacts.__name__ = _MANIFEST_CONTACTS_API_NAME
_aggregate_manifest_contacts.__qualname__ = _MANIFEST_CONTACTS_API_NAME
globals()[_MANIFEST_CONTACTS_API_NAME] = _aggregate_manifest_contacts


def _compute_contact_frame(
    *,
    condition_name: str,
    frame_index: int,
    timestep: object,
    frame_time_ps: float | None,
    atom_cache: tuple[ContactResidueAtomCacheEntry, ...],
    contact_atom_cache: tuple[ContactResidueAtomCacheEntry, ...],
    candidate_pair_count: int,
    atom_distance_evaluation_count: int,
    options: PreprocessingContactDetectionOptions,
    computation_limits: PreprocessingContactComputationLimits,
    progress_callback: ContactProgressCallback | None,
) -> PreprocessingContactFrameResult:
    _emit_progress(
        progress_callback,
        PreprocessingContactProgressEvent(
            condition_name=condition_name,
            frame_index=frame_index,
            stage="frame_start",
            message=f"selected residues={len(atom_cache)}",
            residue_count=len(atom_cache),
        ),
    )
    issues = [issue for entry in atom_cache for issue in entry.issues]
    _emit_progress(
        progress_callback,
        PreprocessingContactProgressEvent(
            condition_name=condition_name,
            frame_index=frame_index,
            stage="frame_candidates_built",
            message=f"candidate residue pairs={candidate_pair_count}",
            residue_count=len(contact_atom_cache),
            candidate_pair_count=candidate_pair_count,
        ),
    )
    limit_issue = _contact_frame_limit_issue(
        condition_name=condition_name,
        frame_index=frame_index,
        candidate_pair_count=candidate_pair_count,
        atom_distance_evaluation_count=atom_distance_evaluation_count,
        computation_limits=computation_limits,
    )
    if limit_issue is not None:
        issues.append(limit_issue)
        _emit_progress(
            progress_callback,
            PreprocessingContactProgressEvent(
                condition_name=condition_name,
                frame_index=frame_index,
                stage="frame_limit_exceeded",
                message=_contact_limit_progress_message(limit_issue),
                residue_count=len(contact_atom_cache),
                candidate_pair_count=candidate_pair_count,
            ),
        )
        return PreprocessingContactFrameResult(
            condition_name=condition_name,
            frame_index=frame_index,
            time_ps=_frame_time(timestep, frame_index, frame_time_ps),
            contacts=(),
            issues=tuple(issues),
        )

    candidates: list[_ResidueCandidate] = []
    for entry in contact_atom_cache:
        candidate, residue_issues = _residue_candidate(entry)
        issues.extend(residue_issues)
        candidates.append(candidate)

    contacts: list[PreprocessingContactPairResult] = []
    for source_offset, source in enumerate(candidates):
        for target in candidates[source_offset + 1 :]:
            try:
                minimum_distance = _minimum_distance(
                    source.coordinates,
                    target.coordinates,
                )
            except Exception:
                issues.append(
                    PreprocessingContactComputationIssue(
                        kind="distance_calculation_error",
                        field=(
                            f"residue_pairs[{source.index},{target.index}]"
                        ),
                        message=(
                            "Minimum residue-pair distance could not be "
                            "computed."
                        ),
                    )
                )
                continue
            if minimum_distance is None:
                continue
            if minimum_distance <= options.cutoff_distance:
                contacts.append(
                    PreprocessingContactPairResult(
                        source_residue_index=source.index,
                        target_residue_index=target.index,
                        source_resname=source.resname,
                        target_resname=target.resname,
                        minimum_distance=minimum_distance,
                        distance_unit=options.distance_unit,
                        atom_filter=options.atom_filter,
                        source_residue_id=source.residue_id,
                        target_residue_id=target.residue_id,
                        source_segid=source.segid,
                        target_segid=target.segid,
                    )
                )

    contacts.extend(
        _protein_rin_interaction_contacts(
            contact_atom_cache,
            options=options,
        )
    )
    contacts.sort(
        key=lambda contact: (
            contact.source_residue_index,
            contact.target_residue_index,
            contact.edge_type,
            contact.source_resname,
            contact.target_resname,
        )
    )
    backbone_observations = (
        _backbone_observations(atom_cache)
        if options.contact_selection == "protein"
        else ()
    )
    _emit_progress(
        progress_callback,
        PreprocessingContactProgressEvent(
            condition_name=condition_name,
            frame_index=frame_index,
            stage="frame_done",
            message=f"computed contacts={len(contacts)}",
            residue_count=len(candidates),
            candidate_pair_count=candidate_pair_count,
        ),
    )
    return PreprocessingContactFrameResult(
        condition_name=condition_name,
        frame_index=frame_index,
        time_ps=_frame_time(timestep, frame_index, frame_time_ps),
        contacts=tuple(contacts),
        backbone_observations=backbone_observations,
        issues=tuple(issues),
    )


def _candidate_pair_count(candidates: Sequence[object]) -> int:
    candidate_count = len(candidates)
    return candidate_count * (candidate_count - 1) // 2


def _finalize_condition_interactions(
    frame_results: list[PreprocessingContactFrameResult],
) -> tuple[InteractionAggregateResult, ...]:
    accumulator = InteractionAccumulator()
    for frame_result in frame_results:
        for contact in frame_result.contacts:
            accumulator.add(
                condition_name=frame_result.condition_name,
                frame_index=frame_result.frame_index,
                resid_i=contact.source_residue_index,
                resid_j=contact.target_residue_index,
                edge_type=contact.edge_type,
                distance_A=contact.minimum_distance,
            )
    return accumulator.finalize(frame_count=len(frame_results))


def _protein_rin_interaction_contacts(
    atom_cache: tuple[ContactResidueAtomCacheEntry, ...],
    *,
    options: PreprocessingContactDetectionOptions,
) -> tuple[PreprocessingContactPairResult, ...]:
    residue_candidates = tuple(
        _residue_chemistry_candidate(entry)
        for entry in atom_cache
        if entry.resname is not None
    )
    observations = (
        trajectory_contact_chemistry.detect_protein_rin_interactions(
            residue_candidates
        )
        if options.contact_selection == "protein"
        else trajectory_contact_chemistry.detect_pi_interactions(
            residue_candidates
        )
    )
    return tuple(
        PreprocessingContactPairResult(
            source_residue_index=observation.source.residue_index,
            target_residue_index=observation.target.residue_index,
            source_resname=observation.source.resname,
            target_resname=observation.target.resname,
            minimum_distance=observation.distance_A,
            distance_unit=options.distance_unit,
            atom_filter=options.atom_filter,
            edge_type=observation.edge_type,
            source_residue_id=observation.source.residue_id,
            target_residue_id=observation.target.residue_id,
            source_segid=observation.source.segid,
            target_segid=observation.target.segid,
        )
        for observation in observations
    )


def _residue_chemistry_candidate(
    entry: ContactResidueAtomCacheEntry,
) -> trajectory_contact_chemistry.ResidueChemistryCandidate:
    fallback_positions = (
        _atom_group_positions(entry.atom_group)
        if entry.atom_group is not None
        else None
    )
    coordinates_by_name: dict[str, _Coordinate] = {}
    heavy_coordinates_by_name: dict[str, _Coordinate] = {}
    donor_hydrogens_by_name: dict[str, tuple[_Coordinate, ...]] = {}
    for atom_index, atom in enumerate(entry.all_atoms):
        raw_name, has_name = _read_attribute(atom, "name")
        if not has_name or raw_name is None:
            continue
        atom_name = str(raw_name).strip().upper()
        if not atom_name or atom_name in coordinates_by_name:
            continue
        raw_position, has_position = _read_attribute(
            atom,
            _POSITION_ATTRIBUTE,
        )
        if (
            (not has_position or raw_position is None)
            and fallback_positions is not None
            and atom_index < len(fallback_positions)
        ):
            raw_position = fallback_positions[atom_index]
        if raw_position is None:
            continue
        coordinate = _coordinate(raw_position)
        if coordinate is not None:
            coordinates_by_name[atom_name] = coordinate
            if not _is_hydrogen(atom):
                heavy_coordinates_by_name[atom_name] = coordinate
            bonded_hydrogens = _bonded_hydrogen_coordinates(atom)
            if bonded_hydrogens:
                donor_hydrogens_by_name[atom_name] = bonded_hydrogens
    return trajectory_contact_chemistry.ResidueChemistryCandidate(
        residue_index=entry.residue_index,
        residue_id=entry.residue_id,
        resname=cast(str, entry.resname),
        segid=entry.segid,
        atom_coordinates=tuple(coordinates_by_name.items()),
        heavy_atom_coordinates=tuple(heavy_coordinates_by_name.items()),
        donor_hydrogen_coordinates=tuple(donor_hydrogens_by_name.items()),
    )


def _bonded_hydrogen_coordinates(atom: object) -> tuple[_Coordinate, ...]:
    bonds, has_bonds = _read_attribute(atom, "bonds")
    if not has_bonds or bonds is None:
        return ()
    coordinates: list[_Coordinate] = []
    try:
        bond_items = tuple(cast(Iterable[object], bonds))
    except Exception:
        return ()
    for bond in bond_items:
        partner_method = getattr(cast(Any, bond), "partner", None)
        if not callable(partner_method):
            continue
        try:
            partner = partner_method(atom)
        except Exception:
            continue
        if partner is None or not _is_hydrogen(partner):
            continue
        raw_position, has_position = _read_attribute(
            partner,
            _POSITION_ATTRIBUTE,
        )
        if not has_position or raw_position is None:
            continue
        coordinate = _coordinate(raw_position)
        if coordinate is not None and coordinate not in coordinates:
            coordinates.append(coordinate)
    return tuple(coordinates)


def _atom_distance_evaluation_count(
    atom_cache: Sequence[ContactResidueAtomCacheEntry],
) -> int:
    evaluation_count = 0
    for source_offset, source in enumerate(atom_cache):
        for target in atom_cache[source_offset + 1 :]:
            evaluation_count += source.atom_count * target.atom_count
    return evaluation_count


def _contact_frame_limit_issue(
    *,
    condition_name: str,
    frame_index: int,
    candidate_pair_count: int,
    atom_distance_evaluation_count: int,
    computation_limits: PreprocessingContactComputationLimits,
) -> PreprocessingContactComputationIssue | None:
    pair_limit = computation_limits.max_residue_pairs_per_frame
    if pair_limit is not None and candidate_pair_count > pair_limit:
        return PreprocessingContactComputationIssue(
            kind="contact_frame_limit_exceeded",
            field=f"frames[{frame_index}].candidate_residue_pairs",
            message=(
                "Contact computation skipped for condition "
                f"'{condition_name}' frame {frame_index} because estimated "
                f"residue pairs {candidate_pair_count} exceed "
                f"max_residue_pairs_per_frame={pair_limit}."
            ),
        )

    distance_limit = (
        computation_limits.max_atom_distance_evaluations_per_frame
    )
    if (
        distance_limit is not None
        and atom_distance_evaluation_count > distance_limit
    ):
        return PreprocessingContactComputationIssue(
            kind="contact_distance_evaluation_limit_exceeded",
            field=f"frames[{frame_index}].atom_distance_evaluations",
            message=(
                "Contact computation skipped for condition "
                f"'{condition_name}' frame {frame_index} because estimated "
                "atom distance evaluations "
                f"{atom_distance_evaluation_count} "
                "exceed "
                "max_atom_distance_evaluations_per_frame="
                f"{distance_limit}."
            ),
        )
    return None


def _contact_limit_progress_message(
    issue: PreprocessingContactComputationIssue,
) -> str:
    return issue.message


def _selected_contact_residue_items(
    runtime_object: object,
    options: PreprocessingContactDetectionOptions,
) -> tuple[tuple[object, ...], PreprocessingContactComputationIssue | None]:
    if options.contact_selection == "all":
        residues, has_residues = _read_attribute(
            runtime_object,
            _RESIDUES_ATTRIBUTE,
        )
        if not has_residues or residues is None:
            return (), PreprocessingContactComputationIssue(
                kind="missing_residues",
                field="runtime_object_residues",
                message="Runtime object has no usable residues collection.",
            )
        try:
            return tuple(cast(Iterable[object], residues)), None
        except Exception:
            return (), PreprocessingContactComputationIssue(
                kind="missing_residues",
                field="runtime_object_residues",
                message="Runtime residues could not be iterated.",
            )

    selector = getattr(cast(Any, runtime_object), "select_atoms", None)
    if not callable(selector):
        return (), _contact_selection_unavailable_issue(
            "Runtime object does not provide select_atoms."
        )

    try:
        selected_atoms = selector("protein")
    except Exception:
        return (), _contact_selection_unavailable_issue(
            "Runtime protein atom selection failed."
        )

    residues, has_residues = _read_attribute(
        selected_atoms,
        _RESIDUES_ATTRIBUTE,
    )
    if not has_residues or residues is None:
        return (), _contact_selection_unavailable_issue(
            "Protein atom selection has no usable residues collection."
        )

    try:
        residue_items = tuple(cast(Iterable[object], residues))
    except Exception:
        return (), _contact_selection_unavailable_issue(
            "Protein selection residues could not be iterated."
        )
    if not residue_items:
        return (), PreprocessingContactComputationIssue(
            kind="contact_selection_empty",
            field="runtime_object.select_atoms('protein').residues",
            message="Contact selection 'protein' returned no residues.",
        )
    return residue_items, None


def _contact_selection_unavailable_issue(
    message: str,
) -> PreprocessingContactComputationIssue:
    return PreprocessingContactComputationIssue(
        kind="contact_selection_unavailable",
        field="runtime_object.select_atoms",
        message=message,
    )


def _residue_candidate(
    entry: ContactResidueAtomCacheEntry,
) -> tuple[_ResidueCandidate, tuple[PreprocessingContactComputationIssue, ...]]:
    fallback_positions = (
        _atom_group_positions(entry.atom_group)
        if entry.atom_group is not None
        else None
    )
    coordinates: list[_Coordinate] = []
    issues: list[PreprocessingContactComputationIssue] = []
    for atom_index, atom in zip(
        entry.atom_indexes,
        entry.distance_atoms,
        strict=True,
    ):
        raw_position, has_position = _read_attribute(
            atom,
            _POSITION_ATTRIBUTE,
        )
        if (
            (not has_position or raw_position is None)
            and fallback_positions is not None
            and atom_index < len(fallback_positions)
        ):
            raw_position = fallback_positions[atom_index]
            has_position = True
        field = (
            f"residues[{entry.residue_index}]_atoms[{atom_index}]_position"
        )
        if not has_position or raw_position is None:
            issues.append(
                PreprocessingContactComputationIssue(
                    kind="missing_atom_position",
                    field=field,
                    message="Selected atom position is unavailable.",
                )
            )
            continue
        coordinate = _coordinate(raw_position)
        if coordinate is None:
            issues.append(
                PreprocessingContactComputationIssue(
                    kind="invalid_atom_position",
                    field=field,
                    message="Selected atom position must contain 3D values.",
                )
            )
            continue
        coordinates.append(coordinate)

    return _ResidueCandidate(
        index=entry.residue_index,
        resname=cast(str, entry.resname),
        residue_id=entry.residue_id,
        segid=entry.segid,
        coordinates=tuple(coordinates),
    ), tuple(issues)


def _representative_ca_coordinates(
    atom_cache: tuple[ContactResidueAtomCacheEntry, ...],
) -> tuple[PreprocessingCaCoordinate, ...]:
    coordinates: list[PreprocessingCaCoordinate] = []
    for entry in atom_cache:
        coordinate = _residue_ca_coordinate(entry)
        if coordinate is None or entry.resname is None:
            continue
        coordinates.append(
            PreprocessingCaCoordinate(
                residue_index=entry.residue_index,
                residue_id=entry.residue_id,
                resname=entry.resname,
                segid=entry.segid,
                x_ca=coordinate[0],
                y_ca=coordinate[1],
                z_ca=coordinate[2],
            )
        )
    return tuple(coordinates)


def _backbone_observations(
    atom_cache: tuple[ContactResidueAtomCacheEntry, ...],
) -> tuple[PreprocessingBackboneObservation, ...]:
    observations: list[PreprocessingBackboneObservation] = []
    for source, target in zip(atom_cache, atom_cache[1:], strict=False):
        if target.residue_index != source.residue_index + 1:
            continue
        if source.segid != target.segid:
            continue
        if source.resname is None or target.resname is None:
            continue
        source_coordinate = _residue_ca_coordinate(source)
        target_coordinate = _residue_ca_coordinate(target)
        if source_coordinate is None or target_coordinate is None:
            continue
        ca_distance = _coordinate_distance(
            source_coordinate,
            target_coordinate,
        )
        if ca_distance > BACKBONE_MAX_CA_DIST_A:
            continue
        observations.append(
            PreprocessingBackboneObservation(
                source_residue_index=source.residue_index,
                target_residue_index=target.residue_index,
                source_resname=source.resname,
                target_resname=target.resname,
                ca_distance=ca_distance,
                source_residue_id=source.residue_id,
                target_residue_id=target.residue_id,
                source_segid=source.segid,
                target_segid=target.segid,
            )
        )
    return tuple(observations)


def _residue_ca_coordinate(
    entry: ContactResidueAtomCacheEntry,
) -> _Coordinate | None:
    fallback_positions = (
        _atom_group_positions(entry.atom_group)
        if entry.atom_group is not None
        else None
    )
    for atom_index, atom in enumerate(entry.all_atoms):
        raw_name, has_name = _read_attribute(atom, "name")
        if (
            not has_name
            or raw_name is None
            or str(raw_name).strip().upper() != "CA"
        ):
            continue
        raw_position, has_position = _read_attribute(atom, _POSITION_ATTRIBUTE)
        if (
            (not has_position or raw_position is None)
            and fallback_positions is not None
            and atom_index < len(fallback_positions)
        ):
            raw_position = fallback_positions[atom_index]
        if raw_position is None:
            return None
        return _coordinate(raw_position)
    return None


def _minimum_distance(
    source_coordinates: tuple[_Coordinate, ...],
    target_coordinates: tuple[_Coordinate, ...],
) -> float | None:
    minimum: float | None = None
    for source in source_coordinates:
        for target in target_coordinates:
            distance = math.sqrt(
                (source[0] - target[0]) ** 2
                + (source[1] - target[1]) ** 2
                + (source[2] - target[2]) ** 2
            )
            if minimum is None or distance < minimum:
                minimum = distance
    return minimum


def _coordinate_distance(source: _Coordinate, target: _Coordinate) -> float:
    return math.sqrt(
        (source[0] - target[0]) ** 2
        + (source[1] - target[1]) ** 2
        + (source[2] - target[2]) ** 2
    )


def _coordinate(value: object) -> _Coordinate | None:
    if isinstance(value, (str, bytes)):
        return None
    try:
        items = tuple(cast(Iterable[object], value))
    except Exception:
        return None
    if len(items) != 3:
        return None
    converted: list[float] = []
    for item in items:
        if isinstance(item, bool):
            return None
        try:
            component = float(cast(Any, item))
        except Exception:
            return None
        if not math.isfinite(component):
            return None
        converted.append(component)
    return converted[0], converted[1], converted[2]


def _atom_group_positions(atom_group: object) -> tuple[object, ...] | None:
    raw_positions, has_positions = _read_attribute(
        atom_group,
        _POSITIONS_ATTRIBUTE,
    )
    if not has_positions or raw_positions is None:
        return None
    try:
        return tuple(cast(Iterable[object], raw_positions))
    except Exception:
        return None


def _is_hydrogen(atom: object) -> bool:
    raw_element, has_element = _read_attribute(atom, "element")
    if has_element and raw_element is not None:
        element = str(raw_element).strip().upper()
        if element == "H":
            return True

    raw_name, has_name = _read_attribute(atom, "name")
    if has_name and raw_name is not None:
        return str(raw_name).strip().upper().startswith("H")
    return False


def _residue_id(residue: object) -> int | str | None:
    value, present = _read_attribute(residue, "resid")
    if not present or value is None or isinstance(value, bool):
        return None
    if isinstance(value, Integral):
        return int(value)
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    return None


def _segid(residue: object) -> str | None:
    value, present = _read_attribute(residue, "segid")
    if not present or value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _frame_time(
    timestep: object,
    frame_index: int,
    frame_time_ps: float | None,
) -> float | None:
    raw_time, has_time = _read_attribute(timestep, _TIME_ATTRIBUTE)
    if has_time and raw_time is not None:
        time_ps = _usable_non_negative_float(raw_time)
        if time_ps is not None:
            return time_ps
    if frame_time_ps is None:
        return None
    return _usable_non_negative_float(frame_index * frame_time_ps)


def _usable_non_negative_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        converted = float(cast(Any, value))
    except Exception:
        return None
    if not math.isfinite(converted) or converted < 0:
        return None
    return converted


def _frame_sampling_options(
    value: PreprocessingFrameSamplingOptions | None,
) -> PreprocessingFrameSamplingOptions:
    if value is None:
        return PreprocessingFrameSamplingOptions()
    if not isinstance(value, PreprocessingFrameSamplingOptions):
        raise ValueError(
            "frame_sampling must be PreprocessingFrameSamplingOptions or None"
        )
    return value


def _contact_computation_limits(
    value: PreprocessingContactComputationLimits | None,
) -> PreprocessingContactComputationLimits:
    if value is None:
        return PreprocessingContactComputationLimits()
    if not isinstance(value, PreprocessingContactComputationLimits):
        raise ValueError(
            "computation_limits must be "
            "PreprocessingContactComputationLimits or None"
        )
    return value


def _emit_progress(
    progress_callback: ContactProgressCallback | None,
    event: PreprocessingContactProgressEvent,
) -> None:
    if progress_callback is None:
        return
    progress_callback(event)


def _read_attribute(value: object, name: str) -> tuple[object | None, bool]:
    try:
        return getattr(cast(Any, value), name), True
    except Exception:
        return None, False


def _unsupported_options_issue(
    options: PreprocessingContactDetectionOptions,
) -> PreprocessingContactComputationIssue | None:
    if options.contact_level != _CONTACT_LEVEL:
        return PreprocessingContactComputationIssue(
            kind="unsupported_contact_level",
            field="options.contact_level",
            message="Only residue-level contacts are supported.",
        )
    if options.atom_filter not in _ATOM_FILTERS:
        return PreprocessingContactComputationIssue(
            kind="unsupported_atom_filter",
            field="options.atom_filter",
            message="Only heavy and all atom filters are supported.",
        )
    if not options.exclude_duplicate_pairs:
        return PreprocessingContactComputationIssue(
            kind="unsupported_duplicate_pair_mode",
            field="options.exclude_duplicate_pairs",
            message="Directed duplicate contact pairs are not supported.",
        )
    return None


def _condition_load_issues(
    condition_load_result: PreprocessingConditionLoadResult,
) -> list[PreprocessingContactComputationIssue]:
    if condition_load_result.issues:
        return [
            PreprocessingContactComputationIssue(
                kind="condition_load_issue",
                field=issue.field,
                message=issue.message,
            )
            for issue in condition_load_result.issues
        ]
    return [
        PreprocessingContactComputationIssue(
            kind="condition_not_loaded",
            field="condition_load_result",
            message="Condition runtime is not loaded.",
        )
    ]


def _missing_runtime_issue() -> PreprocessingContactComputationIssue:
    return PreprocessingContactComputationIssue(
        kind="missing_runtime_object",
        field="runtime",
        message="Condition load result has no runtime object.",
    )


def _frame_iteration_issue() -> PreprocessingContactComputationIssue:
    return PreprocessingContactComputationIssue(
        kind="frame_iteration_error",
        field="runtime_object_trajectory",
        message="Runtime trajectory iteration failed.",
    )


def _condition_contacts_result(
    condition_name: str,
    options: PreprocessingContactDetectionOptions,
    computation_limits: PreprocessingContactComputationLimits,
    *,
    status: str,
    representative_ca_coordinates: tuple[PreprocessingCaCoordinate, ...] = (),
    frame_results: tuple[PreprocessingContactFrameResult, ...] = (),
    interaction_aggregates: tuple[InteractionAggregateResult, ...] = (),
    issues: tuple[PreprocessingContactComputationIssue, ...] = (),
) -> PreprocessingConditionContactsResult:
    return PreprocessingConditionContactsResult(
        condition_name=condition_name,
        options=options,
        computation_limits=computation_limits,
        representative_ca_coordinates=representative_ca_coordinates,
        frame_results=frame_results,
        interaction_aggregates=interaction_aggregates,
        issues=issues,
        status=status,
    )


__all__ = [
    "BACKBONE_MAX_CA_DIST_A",
    "ContactProgressCallback",
    "InteractionAccumulator",
    "InteractionAggregateResult",
    "PreprocessingConditionContactsResult",
    "PreprocessingCaCoordinate",
    "PreprocessingBackboneObservation",
    "PreprocessingContactComputationLimits",
    "PreprocessingContactComputationIssue",
    "PreprocessingContactDefinition",
    "PreprocessingContactDetectionOptions",
    "PreprocessingContactFrameResult",
    "PreprocessingContactPairResult",
    "PreprocessingContactProgressEvent",
    "PreprocessingFrameSamplingOptions",
    "PreprocessingManifestContactsResult",
    "compute_condition_contacts",
    _MANIFEST_CONTACTS_API_NAME,
]
