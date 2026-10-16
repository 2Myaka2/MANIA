"""Bind explicit Dataset identities to execution without interpreting physical time."""

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from mania.dataset_identity import (
    DATASET_TRAJECTORY_SPEC_KIND,
    DATASET_TRAJECTORY_SPEC_SCHEMA_VERSION,
    DatasetTrajectorySpec,
)
from mania.dataset_parameter_table import (
    DatasetParameterTableReadError,
    read_dataset_parameter_table_csv,
)
from mania.preprocessing.input_manifest import PreprocessingInputManifest
from mania.preprocessing.temporal_policy import PreprocessingTemporalPolicy

PREPROCESSING_DATASET_CONTEXT_PROFILE_SCHEMA_VERSION = (
    "mania.preprocessing_dataset_context.v0.2"
)

PREPROCESSING_DATASET_CONTEXT_SCHEMA_VERSION = (
    "mania.preprocessing_dataset_context.v0.1"
)
PREPROCESSING_DATASET_CONTEXT_KIND = "mania_preprocessing_dataset_context"

PreprocessingDatasetBindingSource = Literal[
    "inline_manifest",
    "parameter_table",
    "inline_and_parameter_table",
]


class PreprocessingDatasetBindingError(ValueError):
    """An explicit Dataset binding cannot be resolved consistently."""


class PreprocessingDatasetBinding(BaseModel):
    """One portable resolved specification, separate from runtime inputs."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    execution_condition: str
    source: PreprocessingDatasetBindingSource
    dataset_spec: DatasetTrajectorySpec

    @field_validator("execution_condition", mode="before")
    @classmethod
    def validate_condition(cls, value: object) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("execution_condition must be a non-empty string")
        return value.strip()

    @model_validator(mode="after")
    def validate_spec(self) -> Self:
        if type(self.dataset_spec) is not DatasetTrajectorySpec:
            raise ValueError("dataset_spec must be DatasetTrajectorySpec")
        condition = self.dataset_spec.identity.condition
        if condition is not None and condition != self.execution_condition:
            raise ValueError(
                "Dataset scientific condition must equal execution condition"
            )
        return self

    def to_dict(self) -> dict[str, object]:
        return {
            "execution_condition": self.execution_condition,
            "source": self.source,
            "dataset_spec": self.dataset_spec.to_dict(),
        }


class PreprocessingDatasetContext(BaseModel):
    """Ordered portable metadata; no local paths or derived sampling values."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    bindings: tuple[PreprocessingDatasetBinding, ...] = Field(min_length=1)
    temporal_policy: PreprocessingTemporalPolicy | None = None

    @field_validator("bindings")
    @classmethod
    def validate_unique_bindings(
        cls, value: tuple[PreprocessingDatasetBinding, ...]
    ) -> tuple[PreprocessingDatasetBinding, ...]:
        conditions = [binding.execution_condition for binding in value]
        keys = [binding.dataset_spec.identity.replica_key for binding in value]
        if len(set(conditions)) != len(conditions):
            raise ValueError("Dataset execution conditions must be unique")
        if len(set(keys)) != len(keys):
            raise ValueError("Dataset replica keys must be unique")
        return value

    @property
    def schema_version(self) -> str:
        return (
            PREPROCESSING_DATASET_CONTEXT_SCHEMA_VERSION
            if self.temporal_policy is None
            else PREPROCESSING_DATASET_CONTEXT_PROFILE_SCHEMA_VERSION
        )

    @property
    def kind(self) -> str:
        return PREPROCESSING_DATASET_CONTEXT_KIND

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "bindings": [binding.to_dict() for binding in self.bindings],
            **(
                {"temporal_policy": self.temporal_policy.model_dump(mode="json")}
                if self.temporal_policy is not None
                else {}
            ),
        }

    @classmethod
    def from_dict(cls, value: object) -> Self:
        """Strictly reconstruct the versioned portable serialization."""
        try:
            if not isinstance(value, dict):
                raise ValueError
            explicit = value.get("schema_version") == (
                PREPROCESSING_DATASET_CONTEXT_PROFILE_SCHEMA_VERSION
            )
            if set(value) != (
                {
                    "schema_version",
                    "kind",
                    "bindings",
                }
                | ({"temporal_policy"} if explicit else set())
            ):
                raise ValueError
            if (
                value["schema_version"]
                not in (
                    PREPROCESSING_DATASET_CONTEXT_SCHEMA_VERSION,
                    PREPROCESSING_DATASET_CONTEXT_PROFILE_SCHEMA_VERSION,
                )
                or value["kind"] != PREPROCESSING_DATASET_CONTEXT_KIND
                or not isinstance(value["bindings"], list)
            ):
                raise ValueError
            bindings = []
            for item in value["bindings"]:
                if not isinstance(item, dict) or set(item) != {
                    "execution_condition",
                    "source",
                    "dataset_spec",
                }:
                    raise ValueError
                spec = item["dataset_spec"]
                if not isinstance(spec, dict) or set(spec) != {
                    "schema_version",
                    "kind",
                    "identity",
                    "temporal",
                }:
                    raise ValueError
                if (
                    spec["schema_version"] != DATASET_TRAJECTORY_SPEC_SCHEMA_VERSION
                    or spec["kind"] != DATASET_TRAJECTORY_SPEC_KIND
                ):
                    raise ValueError
                bindings.append(
                    PreprocessingDatasetBinding.model_validate(
                        {
                            **item,
                            "dataset_spec": {
                                "identity": spec["identity"],
                                "temporal": spec["temporal"],
                            },
                        }
                    )
                )
            context = cls(
                bindings=tuple(bindings),
                temporal_policy=(
                    PreprocessingTemporalPolicy.model_validate(value["temporal_policy"])
                    if explicit
                    else None
                ),
            )
            if context.to_dict() != value:
                raise ValueError
            return context
        except (TypeError, ValueError):
            raise PreprocessingDatasetBindingError("Invalid Dataset context.") from None


@dataclass(frozen=True)
class PreprocessingDatasetResolution:
    """Execution-only bridge; the local path has no portable serialization."""

    context: PreprocessingDatasetContext | None
    parameter_table_local_path: Path | None

    def __post_init__(self) -> None:
        if (
            self.context is not None
            and type(self.context) is not PreprocessingDatasetContext
        ):
            raise ValueError("context must be PreprocessingDatasetContext or None")
        uses_table = self.context is not None and any(
            binding.source != "inline_manifest" for binding in self.context.bindings
        )
        if uses_table:
            if not isinstance(self.parameter_table_local_path, Path):
                raise ValueError(
                    "Table-backed context requires a local parameter table path"
                )
        elif self.parameter_table_local_path is not None:
            raise ValueError("Local parameter table path requires table-backed context")


def resolve_preprocessing_dataset_context(
    manifest: PreprocessingInputManifest,
    *,
    base_dir: str | Path | None = None,
) -> PreprocessingDatasetResolution:
    """Resolve only exact replica keys, preserving requested parameters and order."""
    table_path = manifest.dataset_parameter_table_path
    table_specs: dict[tuple[str, str, str, str], DatasetTrajectorySpec] = {}
    if table_path is not None:
        if not table_path.is_absolute():
            if base_dir is None:
                raise PreprocessingDatasetBindingError(
                    "Relative Dataset parameter table path requires explicit base_dir."
                )
            table_path = Path(base_dir) / table_path
        try:
            table = read_dataset_parameter_table_csv(table_path)
        except DatasetParameterTableReadError:
            raise PreprocessingDatasetBindingError(
                "Dataset parameter table could not be read or validated."
            ) from None
        table_specs = {spec.identity.replica_key: spec for spec in table.specs}

    bindings = []
    for config in manifest.conditions:
        inline = config.dataset_spec
        reference = config.dataset_ref
        if inline is None and reference is None:
            continue
        if reference is not None and (
            table_path is None
            or (
                inline is not None
                and reference.replica_key != inline.identity.replica_key
            )
        ):
            raise PreprocessingDatasetBindingError(
                "Dataset reference requires a table and a matching inline replica_key."
            )
        source: PreprocessingDatasetBindingSource = "inline_manifest"
        if table_path is None:
            assert inline is not None
            spec = inline
        else:
            if inline is not None:
                key = inline.identity.replica_key
            else:
                assert reference is not None
                key = reference.replica_key
            if key not in table_specs:
                raise PreprocessingDatasetBindingError(
                    f"Dataset parameter table has no row for replica_key {key!r}."
                )
            spec = table_specs[key]
            source = "parameter_table"
            if inline is not None:
                if spec.to_dict() != inline.to_dict():
                    raise PreprocessingDatasetBindingError(
                        "Inline Dataset spec conflicts with parameter table "
                        f"for replica_key {key!r}."
                    )
                source = "inline_and_parameter_table"
        if (
            spec.identity.condition is not None
            and spec.identity.condition != config.condition
        ):
            raise PreprocessingDatasetBindingError(
                "Dataset scientific condition must equal execution condition."
            )
        bindings.append(
            PreprocessingDatasetBinding(
                execution_condition=config.condition,
                source=source,
                dataset_spec=spec,
            )
        )
    context = (
        PreprocessingDatasetContext(
            bindings=tuple(bindings), temporal_policy=manifest.temporal_policy
        )
        if bindings
        else None
    )
    return PreprocessingDatasetResolution(context, table_path)


__all__ = [
    "PREPROCESSING_DATASET_CONTEXT_SCHEMA_VERSION",
    "PREPROCESSING_DATASET_CONTEXT_KIND",
    "PreprocessingDatasetBindingSource",
    "PreprocessingDatasetBinding",
    "PreprocessingDatasetContext",
    "PreprocessingDatasetResolution",
    "PreprocessingDatasetBindingError",
    "resolve_preprocessing_dataset_context",
]
