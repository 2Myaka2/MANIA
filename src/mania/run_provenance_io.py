"""Atomic, standard-library-only persistence of an immutable run passport."""

import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass, fields
from datetime import datetime
from pathlib import Path
from typing import Any

from mania.run_provenance import (
    RUN_PROVENANCE_FILENAME,
    RUN_PROVENANCE_KIND,
    RUN_PROVENANCE_SCHEMA_VERSION,
    ConditionSamplingProvenance,
    EffectiveFrameSampling,
    ExploratoryRunProvenance,
    PortableArtifactReference,
    RequestedFrameSampling,
    RunProvenance,
    RunProvenanceIssue,
)
from mania.software_identity import SoftwareIdentity


class RunProvenanceReadError(ValueError):
    """A passport cannot be read as the supported provenance contract."""


def _provenance_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key.")
        result[key] = value
    return result


def _reject_provenance_json_constant(value: str) -> None:
    raise ValueError("Non-finite JSON constant.")


def _provenance_fields(value: Any, model: type[Any]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        item.name for item in fields(model)
    }:
        raise ValueError("Invalid object fields.")
    return value.copy()


def _provenance_array(value: Any) -> list[Any]:
    if not isinstance(value, list):
        raise ValueError("Expected a JSON array.")
    return value


def _read_software_identity(value: Any) -> SoftwareIdentity:
    values = _provenance_fields(value, SoftwareIdentity)
    # SoftwareIdentity has no __post_init__; enforce its serialized field contract here.
    for name in ("software_name", "distribution_name", "version"):
        text = values[name]
        if not isinstance(text, str) or not text or text != text.strip():
            raise ValueError("Invalid software identity text.")
    sha = values["commit_sha"]
    if sha is not None and (
        not isinstance(sha, str) or re.fullmatch(r"[0-9a-f]{40}", sha) is None
    ):
        raise ValueError("Invalid software commit SHA.")
    if values["commit_source"] not in ("git_checkout", "unavailable"):
        raise ValueError("Invalid software commit source.")
    if values["working_tree_status"] not in ("clean", "dirty", "unavailable"):
        raise ValueError("Invalid software working tree status.")
    return SoftwareIdentity(**values)


def _read_condition_sampling(value: Any) -> ConditionSamplingProvenance:
    values = _provenance_fields(value, ConditionSamplingProvenance)
    values["requested"] = RequestedFrameSampling(
        **_provenance_fields(values["requested"], RequestedFrameSampling)
    )
    if values["effective"] is not None:
        values["effective"] = EffectiveFrameSampling(
            **_provenance_fields(values["effective"], EffectiveFrameSampling)
        )
    return ConditionSamplingProvenance(**values)


def read_run_provenance(path: str | Path) -> RunProvenance:
    """Reconstruct a stored passport without recollecting runtime observations."""
    if not isinstance(path, (str, Path)) or path == "":
        raise RunProvenanceReadError("path must be a Path or non-empty string.")
    try:
        target = Path(path)
        if not stat.S_ISREG(target.stat().st_mode):
            raise RunProvenanceReadError("Run provenance must be a regular file.")
        with target.open(encoding="utf-8") as stream:
            data = json.load(
                stream,
                object_pairs_hook=_provenance_json_object,
                parse_constant=_reject_provenance_json_constant,
            )
    except RunProvenanceReadError:
        raise
    except FileNotFoundError:
        raise RunProvenanceReadError("Run provenance file is missing.") from None
    except OSError:
        raise RunProvenanceReadError("Run provenance file cannot be read.") from None
    except (ValueError, RecursionError):
        raise RunProvenanceReadError(
            "Run provenance is not valid UTF-8 JSON."
        ) from None
    if not isinstance(data, dict):
        raise RunProvenanceReadError("Run provenance root must be a JSON object.")
    if data.get("schema_version") not in (
        RUN_PROVENANCE_SCHEMA_VERSION,
        "mania.run_provenance.v0.2",
    ):
        raise RunProvenanceReadError("Unsupported run provenance schema_version.")
    if data.get("kind") != RUN_PROVENANCE_KIND:
        raise RunProvenanceReadError("Unsupported run provenance kind.")
    try:
        model = (
            ExploratoryRunProvenance
            if data["schema_version"] == "mania.run_provenance.v0.2"
            else RunProvenance
        )
        values = _provenance_fields(data, model)
        if model is ExploratoryRunProvenance:
            from mania.scientific_qualification import ScientificQualificationV1

            payload = values["scientific_qualification"]
            qualification = ScientificQualificationV1.model_validate_json(
                json.dumps(payload, allow_nan=False)
            )
            if qualification.model_dump(mode="json") != payload:
                raise ValueError("Qualification requires complete exact fields")
            values["scientific_qualification"] = qualification
        elif (
            values["workflow"] == "mania.run"
            and isinstance(values["resolved_configuration"], dict)
            and values["resolved_configuration"].get("mode") == "exploratory"
        ):
            raise ValueError("Exploratory provenance requires v0.2")
        values.pop("schema_version")
        values.pop("kind")
        for name in ("started_at_utc", "ended_at_utc"):
            if not isinstance(values[name], str):
                raise ValueError("Timestamp must be a string.")
            values[name] = datetime.fromisoformat(values[name])
        values["software_identity"] = _read_software_identity(
            values["software_identity"]
        )
        for name in ("command", "conditions"):
            values[name] = tuple(_provenance_array(values[name]))
        values["sampling_by_condition"] = tuple(
            _read_condition_sampling(item)
            for item in _provenance_array(values["sampling_by_condition"])
        )
        values["artifact_references"] = tuple(
            PortableArtifactReference(
                **_provenance_fields(item, PortableArtifactReference)
            )
            for item in _provenance_array(values["artifact_references"])
        )
        values["issues"] = tuple(
            RunProvenanceIssue(**_provenance_fields(item, RunProvenanceIssue))
            for item in _provenance_array(values["issues"])
        )
        return model(**values)
    except (TypeError, ValueError, OverflowError, RecursionError):
        raise RunProvenanceReadError("Invalid run provenance fields.") from None


@dataclass(frozen=True)
class RunProvenanceWriteResult:
    """Internal write outcome; local paths are not part of the passport."""

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


def write_run_provenance(
    provenance: RunProvenance,
    output_dir: str | Path,
    *,
    overwrite: bool = False,
) -> RunProvenanceWriteResult:
    """Publish complete UTF-8 JSON atomically, without inspecting artifacts."""
    if type(provenance) not in (RunProvenance, ExploratoryRunProvenance):
        raise ValueError("provenance must be RunProvenance")
    if type(overwrite) is not bool:
        raise ValueError("overwrite must be a bool")
    if not isinstance(output_dir, (str, Path)) or output_dir == "":
        raise ValueError("output_dir must be a Path or non-empty string")
    directory = Path(output_dir)
    target = directory / RUN_PROVENANCE_FILENAME
    temporary: Path | None = None
    error: str | None = None
    try:
        if not overwrite and os.path.lexists(target):
            return RunProvenanceWriteResult(target, False, "Target already exists.")
        payload = (
            json.dumps(
                provenance.to_dict(),
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
            prefix=f".{RUN_PROVENANCE_FILENAME}.",
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
    return RunProvenanceWriteResult(target, error is None, error)


__all__ = [
    "RunProvenanceReadError",
    "RunProvenanceWriteResult",
    "read_run_provenance",
    "write_run_provenance",
]
