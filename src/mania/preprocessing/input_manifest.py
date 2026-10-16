"""Input manifest models for future trajectory preprocessing."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from json import JSONDecodeError
from pathlib import Path
from typing import Any, Self

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer,
    model_validator,
)

from mania.dataset_identity import DatasetTrajectorySpec
from mania.preprocessing.temporal_policy import PreprocessingTemporalPolicy


class DatasetTrajectoryReference(BaseModel):
    """Exact table lookup identity; never a statistical grouping key."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset_id: str
    system_id: str
    trajectory_id: str
    replica_id: str

    @field_validator("*", mode="before")
    @classmethod
    def validate_identifier(cls, value: object) -> str:
        """Require actual stripped, non-empty strings while preserving case."""
        if not isinstance(value, str) or not value.strip():
            raise ValueError("Dataset reference identifiers must be non-empty strings")
        return value.strip()

    @property
    def replica_key(self) -> tuple[str, str, str, str]:
        return (self.dataset_id, self.system_id, self.trajectory_id, self.replica_id)


class TrajectoryInputConfig(BaseModel):
    """Raw simulation inputs declared for one analysis condition."""

    model_config = ConfigDict(frozen=True)

    condition: str
    topology_path: Path
    trajectory_paths: tuple[Path, ...]
    reference_structure_path: Path | None = None
    metadata: dict[str, str] = Field(default_factory=dict)
    dataset_spec: DatasetTrajectorySpec | None = None
    dataset_ref: DatasetTrajectoryReference | None = None
    molecular_partner_metadata_path: Path | None = None
    namd_element_control_path: Path | None = None
    namd_time_control_path: Path | None = None

    @model_serializer(mode="wrap")
    def serialize_execution_metadata(
        self, handler: SerializerFunctionWrapHandler
    ) -> dict[str, Any]:
        """Omit absent optional controls in direct and manifest serialization."""
        values: dict[str, Any] = handler(self)
        if self.molecular_partner_metadata_path is None:
            values.pop("molecular_partner_metadata_path", None)
        for name in (
            "dataset_spec", "dataset_ref",
            "namd_element_control_path", "namd_time_control_path",
        ):
            if getattr(self, name) is None:
                values.pop(name, None)
        return values

    @model_validator(mode="after")
    def validate_dataset_condition(self) -> Self:
        """Match supplied scientific labels without inferring unresolved labels."""
        if (self.namd_element_control_path is None) != (
            self.namd_time_control_path is None
        ):
            raise ValueError("NAMD element/time controls must be supplied together")
        if (self.namd_element_control_path is not None
                and self.dataset_spec is not None
                and self.dataset_spec.identity.engine != "namd"):
            raise ValueError("NAMD controls require NAMD Dataset identity")
        if self.dataset_spec is not None:
            scientific_condition = self.dataset_spec.identity.condition
            if (
                scientific_condition is not None
                and scientific_condition != self.condition
            ):
                raise ValueError(
                    "Dataset identity condition must equal the manifest condition"
                )
            if (
                self.dataset_ref is not None
                and self.dataset_ref.replica_key
                != self.dataset_spec.identity.replica_key
            ):
                raise ValueError(
                    "Dataset reference and inline spec replica_key must match"
                )
        return self

    @field_validator("condition")
    @classmethod
    def validate_condition(cls, value: str) -> str:
        """Strip and validate a condition name while preserving case."""
        normalized = value.strip()
        if normalized == "":
            raise ValueError("Condition name must not be empty")
        return normalized

    @field_validator(
        "topology_path",
        "reference_structure_path",
        "molecular_partner_metadata_path",
        "namd_element_control_path", "namd_time_control_path",
        mode="before",
    )
    @classmethod
    def validate_path(cls, value: object) -> object:
        """Reject empty string paths before Path conversion."""
        return _reject_empty_path(value)

    @field_validator("trajectory_paths", mode="before")
    @classmethod
    def validate_trajectory_paths(cls, value: object) -> tuple[object, ...]:
        """Require a non-empty list or tuple of non-empty paths."""
        if isinstance(value, str):
            raise ValueError("trajectory_paths must not be a plain string")
        if not isinstance(value, (list, tuple)):
            raise ValueError("trajectory_paths must be a list or tuple")
        if not value:
            raise ValueError("trajectory_paths must contain at least one path")
        return tuple(_reject_empty_path(path) for path in value)


class ResidueLibraryInputConfig(BaseModel):
    """Residue library inputs reserved for later loading and QC."""

    model_config = ConfigDict(frozen=True)

    library_path: Path | None = None
    custom_residues_path: Path | None = None
    skip_resnames: tuple[str, ...] = ()
    allow_user_overrides: bool = False

    @field_validator("library_path", "custom_residues_path", mode="before")
    @classmethod
    def validate_path(cls, value: object) -> object:
        """Reject empty string paths before Path conversion."""
        return _reject_empty_path(value)

    @field_validator("skip_resnames", mode="before")
    @classmethod
    def validate_skip_resnames(cls, value: object) -> tuple[str, ...]:
        """Normalize residue names and remove duplicates in input order."""
        if isinstance(value, str):
            raise ValueError("skip_resnames must not be a plain string")
        if not isinstance(value, (list, tuple)):
            raise ValueError("skip_resnames must be a list or tuple")

        normalized_resnames: list[str] = []
        seen_resnames: set[str] = set()
        for resname in value:
            if not isinstance(resname, str):
                raise ValueError("skip_resnames entries must be strings")
            normalized = resname.strip().upper()
            if normalized == "":
                raise ValueError("skip_resnames entries must not be empty")
            if normalized not in seen_resnames:
                normalized_resnames.append(normalized)
                seen_resnames.add(normalized)
        return tuple(normalized_resnames)


class PreprocessingInputManifest(BaseModel):
    """Validated raw-input declaration for future preprocessing."""

    model_config = ConfigDict(frozen=True)

    output_root: Path
    conditions: tuple[TrajectoryInputConfig, ...]
    residue_library: ResidueLibraryInputConfig = Field(
        default_factory=ResidueLibraryInputConfig
    )
    frame_time_ps: float | None = None
    dataset_parameter_table_path: Path | None = None
    temporal_policy: PreprocessingTemporalPolicy | None = None

    @model_serializer(mode="wrap")
    def serialize_temporal_policy(
        self, handler: SerializerFunctionWrapHandler
    ) -> dict[str, Any]:
        values: dict[str, Any] = handler(self)
        for name in ("temporal_policy", "dataset_parameter_table_path"):
            if getattr(self, name) is None:
                values.pop(name, None)
        return values

    @field_validator("output_root", "dataset_parameter_table_path", mode="before")
    @classmethod
    def validate_output_root(cls, value: object) -> object:
        """Reject an empty output root before Path conversion."""
        return _reject_empty_path(value)

    @field_validator("conditions", mode="before")
    @classmethod
    def validate_conditions_input(cls, value: object) -> object:
        """Reject string and empty condition collections."""
        if isinstance(value, str):
            raise ValueError("conditions must not be a plain string")
        if not isinstance(value, (list, tuple)):
            raise ValueError("conditions must be a list or tuple")
        if not value:
            raise ValueError("conditions must contain at least one condition")
        return value

    @field_validator("conditions")
    @classmethod
    def validate_unique_conditions(
        cls,
        value: tuple[TrajectoryInputConfig, ...],
    ) -> tuple[TrajectoryInputConfig, ...]:
        """Reject duplicate normalized condition names."""
        seen_conditions: set[str] = set()
        for condition_config in value:
            condition = condition_config.condition
            if condition in seen_conditions:
                raise ValueError(f"Duplicate condition name: {condition!r}")
            seen_conditions.add(condition)
        return value

    @field_validator("frame_time_ps")
    @classmethod
    def validate_frame_time_ps(cls, value: float | None) -> float | None:
        """Require positive finite frame time when it is provided."""
        if value is not None and (not math.isfinite(value) or value <= 0):
            raise ValueError("frame_time_ps must be finite and positive")
        return value

    @field_validator("conditions")
    @classmethod
    def validate_unique_replica_keys(
        cls,
        value: tuple[TrajectoryInputConfig, ...],
    ) -> tuple[TrajectoryInputConfig, ...]:
        """Reject duplicate effective identities among Dataset-aware entries."""
        seen_keys: set[tuple[str, str, str, str]] = set()
        for condition_config in value:
            if condition_config.dataset_spec is not None:
                key = condition_config.dataset_spec.identity.replica_key
            elif condition_config.dataset_ref is not None:
                key = condition_config.dataset_ref.replica_key
            else:
                continue
            if key in seen_keys:
                raise ValueError(f"Duplicate Dataset replica_key: {key!r}")
            seen_keys.add(key)
        return value

    @model_validator(mode="after")
    def validate_dataset_table_usage(self) -> Self:
        """References require a table; declared tables require Dataset-aware entries."""
        if self.frame_time_ps is not None and any(
            c.namd_time_control_path is not None for c in self.conditions
        ):
            raise ValueError("NAMD time authority conflicts with legacy frame_time_ps")
        if self.temporal_policy is not None and not any(
            c.dataset_spec is not None or c.dataset_ref is not None
            for c in self.conditions
        ):
            raise ValueError("Temporal policy requires Dataset context")
        if self.dataset_parameter_table_path is None:
            if any(config.dataset_ref is not None for config in self.conditions):
                raise ValueError("dataset_ref requires dataset_parameter_table_path")
        elif not any(
            config.dataset_spec is not None or config.dataset_ref is not None
            for config in self.conditions
        ):
            raise ValueError(
                "Dataset parameter table requires a Dataset-aware condition"
            )
        return self

    def condition_names(self) -> tuple[str, ...]:
        """Return condition names in manifest order."""
        return tuple(config.condition for config in self.conditions)

    def get_condition(self, condition: str) -> TrajectoryInputConfig:
        """Return one condition config using stripped, case-sensitive matching."""
        normalized = condition.strip()
        if normalized == "":
            raise KeyError(condition)
        for condition_config in self.conditions:
            if condition_config.condition == normalized:
                return condition_config
        raise KeyError(condition)

    def dataset_spec_for_condition(
        self, condition: str
    ) -> DatasetTrajectorySpec | None:
        """Return an optional spec using the existing condition lookup semantics."""
        return self.get_condition(condition).dataset_spec

    def dataset_specs(self) -> tuple[DatasetTrajectorySpec, ...]:
        """Return only supplied Dataset specs in manifest condition order."""
        return tuple(
            config.dataset_spec
            for config in self.conditions
            if config.dataset_spec is not None
        )

    def to_dict(self) -> dict[str, object]:
        """Preserve legacy fields and serialize supplied specs with their contract."""
        payload = self.model_dump(
            mode="json",
            exclude={
                "conditions": {
                    "__all__": {
                        "dataset_spec",
                        "dataset_ref",
                        "molecular_partner_metadata_path",
                    }
                },
                "dataset_parameter_table_path": True,
            },
        )
        for config, serialized in zip(
            self.conditions, payload["conditions"], strict=True
        ):
            if config.dataset_spec is not None:
                serialized["dataset_spec"] = config.dataset_spec.to_dict()
            if config.dataset_ref is not None:
                serialized["dataset_ref"] = config.dataset_ref.model_dump(mode="json")
            if config.molecular_partner_metadata_path is not None:
                serialized["molecular_partner_metadata_path"] = str(
                    config.molecular_partner_metadata_path
                )
        if self.dataset_parameter_table_path is not None:
            payload["dataset_parameter_table_path"] = str(
                self.dataset_parameter_table_path
            )
        return payload


def load_preprocessing_input_manifest(
    path: str | Path,
) -> PreprocessingInputManifest:
    """Load and validate a JSON or YAML preprocessing input manifest."""
    manifest_path = Path(path)
    if not manifest_path.exists():
        raise FileNotFoundError(manifest_path)
    if manifest_path.is_dir():
        raise IsADirectoryError(manifest_path)
    if not manifest_path.is_file():
        raise ValueError(f"Manifest path is not a file: {manifest_path}")

    try:
        payload = _load_manifest_payload(manifest_path)
    except (JSONDecodeError, yaml.YAMLError) as exc:
        raise ValueError(
            f"Invalid preprocessing input manifest: {manifest_path}"
        ) from exc

    if not isinstance(payload, Mapping):
        raise ValueError("Preprocessing input manifest must contain an object")

    return PreprocessingInputManifest.model_validate(dict(payload))


def _load_manifest_payload(path: Path) -> object:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    if suffix in {".yaml", ".yml"}:
        with path.open("r", encoding="utf-8") as manifest_file:
            return yaml.safe_load(manifest_file)
    raise ValueError(f"Unsupported preprocessing manifest suffix: {path.suffix}")


def _reject_empty_path(value: object) -> object:
    if isinstance(value, str) and value.strip() == "":
        raise ValueError("Path must not be empty")
    return value


__all__ = [
    "DatasetTrajectoryReference",
    "PreprocessingInputManifest",
    "ResidueLibraryInputConfig",
    "TrajectoryInputConfig",
    "load_preprocessing_input_manifest",
]
