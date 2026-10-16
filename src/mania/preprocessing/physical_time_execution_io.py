"""Strict model reconstruction and atomic persistence of temporal execution."""

import json
import os
import stat
import tempfile
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

from mania.dataset_identity import (
    DATASET_TRAJECTORY_SPEC_KIND,
    DATASET_TRAJECTORY_SPEC_SCHEMA_VERSION,
    DatasetTrajectorySpec,
)
from mania.preprocessing.physical_time_execution import (
    PREPROCESSING_TEMPORAL_EXECUTION_FILENAME,
    PREPROCESSING_TEMPORAL_EXECUTION_KIND,
    PREPROCESSING_TEMPORAL_EXECUTION_PROFILE_SCHEMA_VERSION,
    PREPROCESSING_TEMPORAL_EXECUTION_SCHEMA_VERSION,
    PreprocessingConditionTemporalExecution,
    PreprocessingTemporalExecution,
)
from mania.preprocessing.physical_time_sampling import (
    MissingPhysicalTimeSample,
    PhysicalTimeSamplingIssue,
    ResolvedPhysicalTimeSample,
    ResolvedPhysicalTimeSamplingPlan,
)
from mania.preprocessing.physical_time_windows import (
    PHYSICAL_TIME_WINDOW_PROFILE_SCHEMA_VERSION,
    PHYSICAL_TIME_WINDOW_SCHEMA_VERSION,
    PhysicalTimeWindowPlanningIssue,
    ResolvedPhysicalTimeWindow,
    ResolvedPhysicalTimeWindowPlan,
)
from mania.preprocessing.temporal_policy import (
    INCLUSIVE_BOUNDARY_PROFILE,
    LEGACY_BOUNDARY_PROFILE,
)


class PreprocessingTemporalExecutionReadError(ValueError):
    """Stored execution is unreadable or inconsistent with its temporal contract."""


def _json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key.")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError("Non-finite JSON constant.")


def _fields(value: Any, model: type[Any]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        item.name for item in fields(model)
    }:
        raise ValueError("Invalid object fields.")
    return value.copy()


def _array(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError("Expected a JSON array.")
    return value


def _model(value: Any, model: type[Any]) -> Any:
    if model is ResolvedPhysicalTimeWindowPlan:
        if not isinstance(value, dict):
            raise ValueError("Invalid window plan")
        value = value.copy()
        version = value.get("schema_version")
        if version == PHYSICAL_TIME_WINDOW_SCHEMA_VERSION:
            if "boundary_profile" in value:
                raise ValueError("Legacy schema cannot contain a profile field")
            value["boundary_profile"] = LEGACY_BOUNDARY_PROFILE
        elif version == PHYSICAL_TIME_WINDOW_PROFILE_SCHEMA_VERSION:
            if value.get("boundary_profile") != INCLUSIVE_BOUNDARY_PROFILE:
                raise ValueError("Invalid explicit window profile")
        else:
            raise ValueError("Unknown window plan version")
    values = _fields(value, model)
    for item in fields(model):
        if not item.init:
            actual = values.pop(item.name)
            if (
                model is ResolvedPhysicalTimeWindowPlan
                and item.name == "schema_version"
            ):
                continue  # Exact version/profile pair checked above.
            if type(actual) is not type(item.default) or actual != item.default:
                raise ValueError("Invalid fixed contract field.")
    nested: dict[str, type[Any]] = {}
    if model is ResolvedPhysicalTimeSamplingPlan:
        nested = {
            "selected_samples": ResolvedPhysicalTimeSample,
            "missing_samples": MissingPhysicalTimeSample,
            "issues": PhysicalTimeSamplingIssue,
        }
    elif model is ResolvedPhysicalTimeWindowPlan:
        nested = {
            "windows": ResolvedPhysicalTimeWindow,
            "issues": PhysicalTimeWindowPlanningIssue,
        }
    elif model is ResolvedPhysicalTimeWindow:
        for name in (
            "requested_sample_indexes",
            "selected_requested_sample_indexes",
            "missing_requested_sample_indexes",
            "source_frame_indexes",
        ):
            values[name] = tuple(_array(values[name]))
    for name, nested_model in nested.items():
        values[name] = tuple(_model(v, nested_model) for v in _array(values[name]))
    return model(**values)


def _spec(value: Any) -> DatasetTrajectorySpec:
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "kind",
        "identity",
        "temporal",
    }:
        raise ValueError("Invalid Dataset specification fields.")
    if (
        value["schema_version"] != DATASET_TRAJECTORY_SPEC_SCHEMA_VERSION
        or value["kind"] != DATASET_TRAJECTORY_SPEC_KIND
    ):
        raise ValueError("Unsupported Dataset specification.")
    spec = DatasetTrajectorySpec.model_validate(
        {"identity": value["identity"], "temporal": value["temporal"]}
    )
    if spec.to_dict() != value:
        raise ValueError("Invalid Dataset specification serialization.")
    return spec


def read_preprocessing_temporal_execution(
    path: str | Path,
) -> PreprocessingTemporalExecution:
    """Strictly reconstruct retained plans without running either resolver."""
    if not isinstance(path, (str, Path)) or path == "":
        raise PreprocessingTemporalExecutionReadError(
            "path must be a Path or non-empty string."
        )
    try:
        target = Path(path)
        if not stat.S_ISREG(target.stat().st_mode):
            raise ValueError("Expected a regular file.")
        with target.open(encoding="utf-8") as stream:
            data = json.load(
                stream,
                object_pairs_hook=_json_object,
                parse_constant=_reject_json_constant,
            )
        if not isinstance(data, dict) or set(data) != {
            "schema_version",
            "kind",
            "status",
            "bindings",
        }:
            raise ValueError("Invalid root fields.")
        if (
            data["schema_version"]
            not in (
                PREPROCESSING_TEMPORAL_EXECUTION_SCHEMA_VERSION,
                PREPROCESSING_TEMPORAL_EXECUTION_PROFILE_SCHEMA_VERSION,
            )
            or data["kind"] != PREPROCESSING_TEMPORAL_EXECUTION_KIND
        ):
            raise ValueError("Unsupported temporal execution contract.")
        bindings = []
        for binding in _array(data["bindings"]):
            values = _fields(binding, PreprocessingConditionTemporalExecution)
            values["dataset_spec"] = _spec(values["dataset_spec"])
            values["sampling_plan"] = _model(
                values["sampling_plan"], ResolvedPhysicalTimeSamplingPlan
            )
            values["window_plan"] = _model(
                values["window_plan"], ResolvedPhysicalTimeWindowPlan
            )
            bindings.append(PreprocessingConditionTemporalExecution(**values))
        execution = PreprocessingTemporalExecution(tuple(bindings))
        if execution.to_dict() != data:
            raise ValueError("Invalid temporal execution serialization.")
        return execution
    except (OSError, TypeError, ValueError, OverflowError, RecursionError):
        raise PreprocessingTemporalExecutionReadError(
            "Invalid or unreadable temporal execution artifact."
        ) from None


@dataclass(frozen=True)
class PreprocessingTemporalExecutionWriteResult:
    """Internal write outcome; local paths stay outside the portable model."""

    output_path: Path
    written: bool
    error: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.output_path, Path):
            raise ValueError("output_path must be a Path")
        if type(self.written) is not bool:
            raise ValueError("written must be a bool")
        if self.error is not None and (
            not isinstance(self.error, str)
            or not self.error
            or self.error != self.error.strip()
        ):
            raise ValueError("error must be a non-empty stripped string")
        if self.written != (self.error is None):
            raise ValueError("written must be true exactly when error is absent")

    @property
    def passed(self) -> bool:
        return self.written and self.error is None

    def to_dict(self) -> dict[str, object]:
        return {
            "output_path": str(self.output_path),
            "written": self.written,
            "error": self.error,
            "passed": self.passed,
        }


def write_preprocessing_temporal_execution(
    execution: PreprocessingTemporalExecution,
    output_root: str | Path,
    *,
    overwrite: bool = False,
) -> PreprocessingTemporalExecutionWriteResult:
    """Publish complete UTF-8 JSON atomically, without inspecting artifacts."""
    if type(execution) is not PreprocessingTemporalExecution:
        raise ValueError("execution must be PreprocessingTemporalExecution")
    if type(overwrite) is not bool:
        raise ValueError("overwrite must be a bool")
    if not isinstance(output_root, (str, Path)) or output_root == "":
        raise ValueError("output_root must be a Path or non-empty string")
    target = Path(output_root) / PREPROCESSING_TEMPORAL_EXECUTION_FILENAME
    directory = target.parent
    temporary: Path | None = None
    error: str | None = None
    try:
        if not overwrite and os.path.lexists(target):
            return PreprocessingTemporalExecutionWriteResult(
                target, False, "Target already exists."
            )
        payload = (
            json.dumps(
                execution.to_dict(),
                indent=2,
                sort_keys=False,
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        )
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=directory,
            prefix=f".{PREPROCESSING_TEMPORAL_EXECUTION_FILENAME}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
        if overwrite:
            os.replace(temporary, target)
        else:
            # Atomic publication without clobbering a concurrently created target.
            os.link(temporary, target)
    except FileExistsError:
        error = "Target already exists."
    except OSError:
        error = "Filesystem write failed."
    except (TypeError, ValueError, OverflowError, RecursionError):
        error = "JSON serialization failed."
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                error = "Temporary file cleanup failed."
    return PreprocessingTemporalExecutionWriteResult(target, error is None, error)
