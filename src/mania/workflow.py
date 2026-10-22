"""Public C06 controller over retained scientific APIs and owned result paths."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any

import yaml

from mania.method_status import MethodStatus, RgEffectiveParameters
from mania.output_paths import require_input_file, safe_absolute, validate_output_root
from mania.preprocessing import run_execution as adapters
from mania.preprocessing.trajectory_protein_contact_export import (
    PROTEIN_CONTACT_PERFRAME_COLUMNS,
    _artifact_rows,
    _write_csv,
)
from mania.run_config import RunConfig, RunConfigError, RunPreflightError
from mania.run_plan import RunPlan
from mania.run_plan import build_run_plan as build_run_plan
from mania.run_summary import (
    ArtifactReference,
    ExploratoryRunSummary,
    RunSummary,
    overall_status,
)
from mania.scientific_qualification import (
    build_qualification,
    changed_upstreams,
    consumption,
    set_consumer,
    warning_records,
)


@dataclass(frozen=True)
class RunResult:
    plan: RunPlan
    summary: RunSummary | ExploratoryRunSummary
    output_root: Path
    inputs: tuple[adapters.InputExecution, ...]


class RunExecutionError(RuntimeError):
    def __init__(self, message: str, result: RunResult, exit_code: int) -> None:
        super().__init__(message)
        self.result, self.exit_code = result, exit_code


class _OwnedWriter:
    def __init__(self, config: RunConfig) -> None:
        from mania.run_config_io import _paths

        self.root = safe_absolute(config.output.root)
        self.inputs = tuple(
            p
            for name in type(config).model_fields
            if name != "output"
            for p in _paths(getattr(config, name))
        )
        self.previous = set(
            validate_output_root(
                self.root, inputs=self.inputs, overwrite=config.output.overwrite
            )
        )
        self.states = {
            p: (p.stat(), hashlib.sha256(p.read_bytes()).hexdigest())
            for p in self.previous
        }
        self.written: set[Path] = set()
        self.root.mkdir(parents=True, exist_ok=True)
        self.root_identity = (self.root.stat().st_dev, self.root.stat().st_ino)

    def publish(self, source: Path, relative: str) -> Path:
        from mania.input_binding import portable_path

        if (self.root.stat().st_dev, self.root.stat().st_ino) != self.root_identity:
            raise RunPreflightError("Output root changed during execution")
        portable_path(relative)
        path = safe_absolute(self.root / relative)
        if path.exists():
            if path not in self.previous and path not in self.written:
                raise RunPreflightError("Refusing unowned output collision")
            before, digest = self.states[path]
            current = path.stat()
            if (
                current.st_dev,
                current.st_ino,
                current.st_size,
                current.st_mtime_ns,
            ) != (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
            ) or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise RunPreflightError(
                    "Owner changed a previous output during execution"
                )
        path.parent.mkdir(parents=True, exist_ok=True)
        safe_absolute(path)
        data = require_input_file(source).read_bytes()
        with tempfile.NamedTemporaryFile(
            dir=path.parent, prefix=".mania-", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        try:
            safe_absolute(path)
            if path in self.previous or path in self.written:
                os.replace(temporary, path)
            else:
                os.link(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        self.written.add(path)
        self.states[path] = (path.stat(), hashlib.sha256(path.read_bytes()).hexdigest())
        return path

    def remove_obsolete(self) -> None:
        for path in self.previous - self.written:
            safe_absolute(path)
            before, digest = self.states[path]
            current = path.stat()
            if (
                current.st_dev,
                current.st_ino,
                current.st_size,
                current.st_mtime_ns,
            ) != (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
            ) or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise RunPreflightError("Owner changed an obsolete owned output")
            path.unlink()


def _json(path: Path, data: Any) -> None:
    from mania.preprocessing.trajectory_rmsd_io import atomic_json

    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(path, data)


def _sampling(execution: adapters.InputExecution) -> Any:
    from mania.run_provenance import (
        ConditionSamplingProvenance,
        EffectiveFrameSampling,
        RequestedFrameSampling,
    )

    frames = execution.system.frames
    observed = execution.observed_frames
    effective = None
    if observed:
        # Exact uniformity only; no new scientific tolerance is introduced.
        times = [time for _, time in observed]
        differences = [
            b - a
            for a, b in zip(times, times[1:], strict=False)
            if a is not None and b is not None
        ]
        available = len(differences) == len(observed) - 1 and len(observed) > 1
        uniform = (
            available
            and differences[0] > 0
            and all(d == differences[0] for d in differences)
        )
        effective = EffectiveFrameSampling(
            execution.source_frame_count,
            len(observed),
            observed[0][0],
            observed[-1][0],
            times[0],
            times[-1],
            "uniform" if uniform else "non_uniform" if available else "unavailable",
            differences[0] if uniform else None,
        )
    return ConditionSamplingProvenance(
        execution.values["execution_condition"],
        RequestedFrameSampling(
            frames.start, frames.stop, frames.stride, frames.max_frames
        ),
        effective,
    )


def _provenance(
    config: RunConfig,
    run_id: str,
    started: datetime,
    ended: datetime,
    methods: tuple[MethodStatus, ...],
    artifacts: tuple[ArtifactReference, ...],
    sampling: tuple[Any, ...],
    conditions: tuple[str, ...],
    qualification: Any = None,
) -> Any:
    from mania.run_provenance import (
        PortableArtifactReference,
        RunProvenance,
        RunProvenanceIssue,
    )
    from mania.software_identity import get_software_identity

    successful = overall_status(methods) in ("completed", "completed_with_skips")
    issues = tuple(
        RunProvenanceIssue(
            "error" if s.status == "failed" else "warning",
            s.reason_code or s.status,
            s.message or s.status,
            stage=s.method_id,
        )
        for s in methods
        if s.status
        in (
            "failed",
            "cancelled",
            "pending_review",
            "missing_optional_input",
            "not_applicable",
        )
    )
    if config.mode == "full":
        issues += (
            RunProvenanceIssue(
                "warning",
                "full_method_expansion",
                "This development build adds applicable RMSF and isolated SASA to Full "
                "after historical 0.2.0; exact historical replay requires "
                "the recorded binary/runtime.",
                stage="plan",
            ),
        )
    issues += tuple(
        RunProvenanceIssue(
            "warning",
            "atomic_method_parameters",
            json.dumps(
                {
                    "method": s.method_id,
                    "options": s.effective_parameters.model_dump(mode="json"),
                },
                sort_keys=True,
            ),
            stage=s.method_id,
        )
        for s in methods
        if s.method_id in ("rmsf", "sasa") and s.status != "not_requested"
    )
    model: Any = RunProvenance
    extra: dict[str, Any] = {}
    if config.mode == "exploratory":
        from mania.run_provenance import ExploratoryRunProvenance

        model = ExploratoryRunProvenance
        extra["scientific_qualification"] = qualification
        issues += tuple(
            RunProvenanceIssue(
                "warning",
                str(w["code"]),
                str(w["message"])
                + (
                    " " + json.dumps(w["input_identity"], sort_keys=True)
                    if "input_identity" in w
                    else ""
                ),
                stage="exploratory",
                condition=None,
            )
            for w in warning_records(config, qualification)
        )
    return model(
        **extra,
        run_id=run_id,
        workflow="mania.run",
        status="completed" if successful else "failed",
        started_at_utc=started,
        ended_at_utc=ended,
        software_identity=get_software_identity(),
        command=(
            "mania",
            "run",
            "--config",
            str(config._config_path) if config._config_path else "Python-RunConfig",
        ),
        resolved_configuration=config.model_dump(mode="json", exclude_unset=True),
        conditions=conditions,
        sampling_by_condition=sampling,
        artifact_references=tuple(
            PortableArtifactReference(a.role, a.path) for a in artifacts
        ),
        issues=issues,
    )


def run(
    config: RunConfig, *, progress: Callable[[Any], None] | None = None
) -> RunResult:
    if type(config) is not RunConfig:
        raise RunConfigError("A validated RunConfig is required")
    with consumption(config.mode, independent=True):
        return _run(config, progress=progress)


def _with_sasa_frame_stride(config: RunConfig) -> RunConfig:
    """Record an explicit method's default without turning presets into requests."""
    from mania.run_config import SASA, merge_methods

    updates: dict[str, Any] = {}
    if config.methods.sasa is not None:
        option = config.methods.sasa
        if "frame_stride" not in option.model_fields_set:
            updates["methods"] = config.methods.model_copy(
                update={
                    "sasa": option.model_copy(
                        update={"frame_stride": option.frame_stride}
                    )
                }
            )
    systems = []
    for system in config.systems:
        overrides = system.method_overrides
        if overrides is not None and overrides.sasa is not None:
            option = overrides.sasa
            if "frame_stride" not in option.model_fields_set:
                effective = merge_methods(config, system)["sasa"]
                assert isinstance(effective, SASA)
                system = system.model_copy(
                    update={
                        "method_overrides": overrides.model_copy(
                            update={
                                "sasa": option.model_copy(
                                    update={"frame_stride": effective.frame_stride}
                                )
                            }
                        )
                    }
                )
        systems.append(system)
    if any(a is not b for a, b in zip(systems, config.systems, strict=True)):
        updates["systems"] = tuple(systems)
    return config.model_copy(update=updates) if updates else config


def _run(
    config: RunConfig, *, progress: Callable[[Any], None] | None = None
) -> RunResult:
    """Execute the validated request; failed/cancelled results remain structured."""
    plan = build_run_plan(_with_sasa_frame_stride(config))
    adapters.validate_execution_dependencies(plan)
    config = plan.effective_parameters
    started = datetime.now(UTC)
    run_id = uuid.uuid4().hex
    adapters.verify_input_checksum_manifest(config, execution=True)
    initial_inputs = (
        adapters.input_inventory(config, run_id)
        if config.reproducibility.checksum_mode == "sha256"
        else None
    )
    statuses = list(plan.methods)
    inputs: list[adapters.InputExecution] = []
    artifacts: list[ArtifactReference] = []
    writer = _OwnedWriter(config)
    exit_code = 0
    error: BaseException | None = None

    def notify(value: Any) -> None:
        if progress is not None:
            progress(value)

    with tempfile.TemporaryDirectory(prefix="mania-run-") as temporary:
        staging = Path(temporary)
        config_path = staging / "effective_config.yaml"
        config_path.write_text(
            (
                "# Full adds applicable RMSF and isolated SASA after "
                "historical 0.2.0 in this development build.\n"
                if config.mode == "full"
                else ""
            )
            + "".join(
                "# Effective methods.sasa.frame_stride: "
                + json.dumps(
                    {
                        "identity": row.identity.to_dict()
                        if not isinstance(row.identity, str)
                        else row.identity,
                        "frame_stride": row.effective_parameters.frame_stride,
                    },
                    sort_keys=True,
                )
                + "\n"
                for row in plan.methods
                if row.method_id == "sasa"
                and row.status != "not_requested"
                and hasattr(row.effective_parameters, "frame_stride")
            )
            + yaml.safe_dump(
                config.model_dump(mode="json", exclude_unset=True),
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        _json(staging / "run_plan.json", plan.to_dict())

        def publish(role: str, path: Path, schema: str | None = None) -> None:
            relative = path.relative_to(staging).as_posix()
            if config.mode == "exploratory":
                from mania.preprocessing.molecular_partner_metadata_io import (
                    read_strict_json,
                )

                expected = next(
                    (
                        a
                        for a in plan.expected_artifacts
                        if (a.role, a.path) == (role, relative)
                    ),
                    None,
                )
                if expected is None:
                    raise RunPreflightError("Unplanned exploratory artifact role/path")
                if schema is None and expected.schema_version is not None:
                    payload = read_strict_json(path)
                    if payload.get("schema_version") != expected.schema_version:
                        raise RunPreflightError(
                            "Exploratory producer schema differs from plan"
                        )
                    schema = expected.schema_version
                if schema != expected.schema_version:
                    raise RunPreflightError(
                        "Exploratory artifact schema differs from plan"
                    )
            existing = next((a for a in artifacts if a.path == relative), None)
            if existing is not None:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                if (
                    existing.sha256 != digest
                    or hashlib.sha256((writer.root / relative).read_bytes()).hexdigest()
                    != digest
                ):
                    raise RunPreflightError(
                        "A published artifact changed during execution"
                    )
                return
            target = writer.publish(path, relative)
            digest = hashlib.sha256(target.read_bytes()).hexdigest()
            artifacts.append(
                ArtifactReference(
                    role=role, path=relative, schema_version=schema, sha256=digest
                )
            )

        publish("effective_config", config_path, "mania.run_config.v1")
        publish("run_plan", staging / "run_plan.json", "mania.run_plan.v1")
        opened_runtimes: list[Any] = []
        try:
            notify({"event": "plan_ready", "plan": plan})
            for position, system in zip(
                plan.path_identity_map, config.systems, strict=True
            ):
                indices = [
                    i
                    for i, s in enumerate(statuses)
                    if s.identity == position.input_identity
                ]
                execution = adapters.InputExecution(
                    system, [statuses[i] for i in indices]
                )
                execution.values["mode"] = config.mode
                execution.values["project"] = config.project
                execution.values["selected_extensions"] = config.extensions
                execution.values["execution_condition"] = (
                    system.condition
                    if system.condition is not None
                    else position.system_token + "_" + position.trajectory_token
                )
                execution.values["trajectory_token"] = position.trajectory_token
                execution.values["config_root"] = (
                    config._config_path.parent
                    if config._config_path
                    else system.topology.parent
                )
                execution.values["published_preprocessing"] = (
                    writer.root / position.directory / "preprocessing"
                )
                inputs.append(execution)
                base = staging / position.directory
                preprocessing, analysis = base / "preprocessing", base / "analysis"
                preprocessing.mkdir(parents=True)
                analysis.mkdir()
                requested = {
                    s.method_id for s in execution.statuses if s.status == "planned"
                }
                coordinate_methods = requested - {"replay", "qc"}
                loaded = None
                if coordinate_methods:
                    from mania.scientific_qualification import consume_run_path

                    if system.input_binding_path is not None:
                        for s in execution.statuses:
                            if s.method_id in coordinate_methods:
                                set_consumer(s.method_id, position.input_identity)
                                consume_run_path(
                                    system.input_binding_path,
                                    position.input_identity,
                                    direct=True,
                                )
                    notify(
                        {"stage": "load", "identity": position.input_identity.to_dict()}
                    )
                    loaded = adapters.load_runtime(
                        system,
                        partial(
                            notify,
                            {
                                "stage": "frame",
                                "identity": position.input_identity.to_dict(),
                            },
                        ),
                        execution_condition=execution.values["execution_condition"],
                    )
                    if loaded.runtime is not None:
                        opened_runtimes.append(loaded.runtime.runtime_object)
                    adapters.prepare_sampling(execution, loaded)
                    notify({"event": "load_done", "identity": position.input_identity})
                order = (
                    "contacts",
                    "static_rin",
                    "communities",
                    "region_enrichment",
                    "typed_interactions",
                    "temporal_rin",
                    "fingerprints",
                    "pca",
                    "clustering",
                    "rg",
                    "rmsd",
                    "rmsf",
                    "sasa",
                    "physical_windows",
                    "lipid_contacts",
                    "glycan_contacts",
                    "replay",
                    "qc",
                )
                for method in order:
                    index = next(i for i in indices if statuses[i].method_id == method)
                    status = statuses[index]
                    if status.status != "planned":
                        continue
                    resolved_atomic = None
                    if method in ("rmsf", "sasa"):
                        assert loaded is not None
                        try:
                            resolved_atomic = adapters.resolve_atomic_method(
                                execution, loaded, method, status.effective_parameters
                            )
                        except adapters.AtomicEligibilityError as exc:
                            if status.request_origin != "preset":
                                raise
                            statuses[index] = status.model_copy(
                                update={
                                    "status": "missing_optional_input",
                                    "reason_code": method
                                    + "_eligibility_unestablished",
                                    "message": str(exc),
                                }
                            )
                            execution.statuses = [statuses[i] for i in indices]
                            notify({"event": "method_done", "method": statuses[index]})
                            continue
                    statuses[index] = status.model_copy(update={"status": "running"})
                    notify(
                        {"stage": method, "identity": position.input_identity.to_dict()}
                    )
                    set_consumer(method, position.input_identity)
                    before = len(execution.artifacts)
                    options = status.effective_parameters
                    if method == "rg":
                        assert (
                            loaded is not None
                            and loaded.runtime is not None
                            and isinstance(options, RgEffectiveParameters)
                        )
                        group, resolved = adapters.resolve_rg(
                            loaded.runtime.runtime_object, system, options
                        )
                        statuses[index] = statuses[index].model_copy(
                            update={"effective_parameters": resolved}
                        )
                        eligible = all(
                            getattr(resolved.eligibility, name).state == "established"
                            for name in (
                                "protein_selection",
                                "masses_and_input",
                                "pbc_suitability",
                            )
                        )
                        if (
                            config.mode == "exploratory"
                            and system.pbc.mode == "unverified"
                        ):
                            eligible = all(
                                getattr(resolved.eligibility, name).state
                                == "established"
                                for name in ("protein_selection", "masses_and_input")
                            )
                        if not eligible:
                            if status.request_origin == "preset":
                                statuses[index] = statuses[index].model_copy(
                                    update={
                                        "status": "missing_optional_input",
                                        "reason_code": "rg_eligibility_unestablished",
                                        "message": (
                                            "Automatic Rg eligibility is unestablished"
                                        ),
                                    }
                                )
                                notify(
                                    {"event": "method_done", "method": statuses[index]}
                                )
                                continue
                            raise RunPreflightError(
                                "Explicit Rg eligibility is unestablished"
                            )
                        adapters.execute_rg(
                            execution, loaded, group, resolved, preprocessing
                        )
                    elif method == "contacts":
                        assert loaded is not None
                        adapters.execute_contacts(
                            execution,
                            loaded,
                            options,
                            preprocessing,
                            config.output.retain_perframe,
                            progress,
                        )
                    elif method == "typed_interactions":
                        # The contact backend always retains all coexisting types;
                        # this request controls only their publication.
                        if not any(
                            r == "protein_contacts_perframe"
                            for r, _, _ in execution.artifacts
                        ):
                            _, rows = _artifact_rows(execution.values["contacts"])
                            path = preprocessing / "protein_contacts_perframe.csv"
                            _write_csv(path, PROTEIN_CONTACT_PERFRAME_COLUMNS, rows)
                            execution.artifacts.append(
                                ("protein_contacts_perframe", path, None)
                            )
                    elif method in (
                        "static_rin",
                        "communities",
                        "temporal_rin",
                        "fingerprints",
                        "pca",
                        "clustering",
                    ):
                        adapters.execute_analysis(
                            execution,
                            method,
                            options,
                            preprocessing,
                            analysis,
                            position.trajectory_token,
                        )
                    elif method == "rmsd":
                        assert loaded is not None
                        adapters.execute_rmsd(execution, loaded, options, preprocessing)
                    elif method == "rmsf":
                        assert resolved_atomic is not None
                        adapters.execute_rmsf(
                            execution, resolved_atomic, options, preprocessing
                        )
                    elif method == "sasa":
                        assert resolved_atomic is not None
                        adapters.execute_sasa(
                            execution, resolved_atomic, options, preprocessing
                        )
                    elif method in (
                        "physical_windows",
                        "lipid_contacts",
                        "glycan_contacts",
                    ):
                        assert loaded is not None and loaded.runtime is not None
                        adapters.execute_windows(
                            execution,
                            method,
                            loaded.runtime.runtime_object,
                            preprocessing,
                        )
                    elif method == "replay":
                        adapters.execute_replay(execution, options, preprocessing)
                    else:
                        adapters.execute_authoritative_method(
                            execution, method, options, preprocessing, analysis
                        )
                    new = execution.artifacts[before:]
                    for role, path, schema in new:
                        publish(role, path, schema)
                    method_state, method_reason = adapters.result_state(
                        execution, method
                    )
                    statuses[index] = statuses[index].model_copy(
                        update={
                            "status": method_state,
                            "reason_code": method_reason,
                            "artifact_roles": tuple(r for r, _, _ in new),
                            "message": (
                                "Full adds this applicable Core method "
                                "after historical 0.2.0. "
                                if method in ("rmsf", "sasa")
                                and status.request_origin == "preset"
                                else ""
                            )
                            + ("Retained API execution and serialization completed"),
                        }
                    )
                    execution.statuses = [statuses[i] for i in indices]
                    notify({"event": "method_done", "method": statuses[index]})
                if "physical_windows" in requested:
                    set_consumer("physical_windows", position.input_identity)
                    before = len(execution.artifacts)
                    adapters.retain_windows(execution, preprocessing)
                    for role, path, schema in execution.artifacts[before:]:
                        publish(role, path, schema)
            for index, status in enumerate(statuses):
                if status.status != "planned":
                    continue
                statuses[index] = status.model_copy(update={"status": "running"})
                notify({"stage": status.method_id, "identity": status.identity})
                set_consumer(status.method_id, status.identity)
                paths = adapters.execute_group_method(
                    config, status, inputs, staging, run_id=run_id
                )
                for role, path, schema in paths:
                    publish(role, path, schema)
                statuses[index] = status.model_copy(
                    update={
                        "status": "completed",
                        "artifact_roles": tuple(r for r, _, _ in paths),
                    }
                )
                notify({"event": "method_done", "method": statuses[index]})
            notify({"event": "publication_started"})
        except KeyboardInterrupt as exc:
            error, exit_code = exc, 130
        except RunPreflightError as exc:
            error, exit_code = exc, 3
        except Exception as exc:
            error, exit_code = exc, 4
        finally:
            for runtime in opened_runtimes:
                try:
                    runtime.trajectory.runtime.trajectory.close()
                except Exception as exc:
                    if error is None:
                        error, exit_code = exc, 4
        if error is not None:
            state = "cancelled" if exit_code == 130 else "failed"
            for index, status in enumerate(statuses):
                if status.status in ("planned", "running"):
                    statuses[index] = status.model_copy(
                        update={
                            "status": state,
                            "reason_code": "cancelled"
                            if exit_code == 130
                            else "execution_failed",
                            "message": str(error) or state,
                        }
                    )
            # Publish only actual regular partial artifacts, never fabricate a
            # completion marker or complete the failing method by file presence.
            for execution in inputs:
                for role, path, schema in execution.artifacts:
                    if path.is_file() and path.relative_to(staging).as_posix() not in {
                        a.path for a in artifacts
                    }:
                        publish(role, path, schema)
        ended = datetime.now(UTC)
        final_inputs = (
            adapters.input_inventory(config, run_id)
            if initial_inputs is not None
            else None
        )
        if (
            initial_inputs is not None
            and final_inputs is not None
            and final_inputs.artifacts != initial_inputs.artifacts
        ):
            exit_code = 4
            error = RuntimeError("Configured input changed during scientific execution")
            last = next(
                (
                    i
                    for i in reversed(range(len(statuses)))
                    if statuses[i].status == "completed"
                ),
                None,
            )
            if last is not None:
                statuses[last] = statuses[last].model_copy(
                    update={
                        "status": "failed",
                        "reason_code": "source_changed_during_execution",
                        "message": str(error),
                    }
                )
        if changed_upstreams():
            exit_code = 4
            error = RuntimeError("Bound upstream changed during execution")
            last = next(
                (
                    i
                    for i in reversed(range(len(statuses)))
                    if statuses[i].status == "completed"
                ),
                None,
            )
            if last is not None:
                statuses[last] = statuses[last].model_copy(
                    update={
                        "status": "failed",
                        "reason_code": "upstream_changed_during_execution",
                        "message": str(error),
                    }
                )
        states = tuple(statuses)
        for execution in inputs:
            identity = execution.system.identity(config.project)
            execution.statuses = [s for s in states if s.identity == identity]
        run_state = overall_status(states)
        if run_state == "pending_review":
            exit_code = 5
        elif run_state == "failed" and not exit_code:
            exit_code = 4
            error = RuntimeError("Required source QC checks failed")
        qualification = (
            build_qualification(plan, states, tuple(artifacts))
            if config.mode == "exploratory"
            else None
        )
        log = staging / "run.log"
        log.write_text(
            (
                "".join(
                    json.dumps(w, ensure_ascii=False, sort_keys=True) + "\n"
                    for w in warning_records(config, qualification)
                )
                if config.mode == "exploratory"
                else ""
            )
            + "".join(
                json.dumps(
                    s.model_dump(mode="json"), ensure_ascii=False, sort_keys=True
                )
                + "\n"
                for s in states
            ),
            encoding="utf-8",
        )
        publish("run_log", log)
        conditions = tuple(
            dict.fromkeys(e.values["execution_condition"] for e in inputs)
        )
        samples = tuple(_sampling(e) for e in inputs)
        # The retained passport has unique condition keys. Per-input source
        # passports carry repeated labels without conflating their populations.
        unique_sampling = tuple(
            s for s in samples if sum(x.condition == s.condition for x in samples) == 1
        )
        provenance = _provenance(
            config,
            run_id,
            started,
            ended,
            states,
            tuple(artifacts),
            unique_sampling,
            conditions,
            qualification,
        )
        _json(staging / "provenance/run_provenance.json", provenance.to_dict())
        publish(
            "run_provenance",
            staging / "provenance/run_provenance.json",
            provenance.schema_version,
        )
        from mania.runtime_metadata import (
            build_runtime_metadata,
            build_runtime_performance,
            collect_runtime_environment,
        )

        count = sum(len(e.observed_frames) for e in inputs)
        runtime = build_runtime_metadata(
            run_id=run_id,
            workflow="mania.run",
            scope="analysis",
            metadata_path="provenance/runtime_metadata.json",
            environment=collect_runtime_environment(),
            performance=build_runtime_performance(
                started_at_utc=started,
                ended_at_utc=ended,
                condition_count=len(inputs),
                sampled_frame_count=count,
            ),
        )
        _json(staging / "provenance/runtime_metadata.json", runtime.to_dict())
        publish(
            "runtime_metadata",
            staging / "provenance/runtime_metadata.json",
            runtime.schema_version,
        )
        artifacts.append(
            ArtifactReference(
                role="artifact_inventory",
                path="provenance/artifact_inventory.json",
                schema_version="mania.artifact_inventory.v0.1",
                sha256=None,
            )
        )
        summary_model: Any = (
            ExploratoryRunSummary if config.mode == "exploratory" else RunSummary
        )
        summary_extra = (
            {"scientific_qualification": qualification}
            if config.mode == "exploratory"
            else {}
        )
        summary = summary_model(
            **summary_extra,
            project=config.project,
            mode=config.mode,
            run_id=run_id,
            status=run_state,
            methods=states,
            path_identity_map=plan.path_identity_map,
            artifact_references=tuple(artifacts),
            selected_extensions=plan.selected_extensions,
        )
        _json(staging / "summary.json", summary.model_dump(mode="json"))
        from mania.artifact_inventory_io import (
            ArtifactInventoryFileSpec,
            build_artifact_inventory,
        )

        specs = tuple(
            ArtifactInventoryFileSpec(
                artifact_id=f"output-{i:04d}",
                direction="output",
                role=a.role,
                local_path=writer.root / a.path,
                path=a.path,
                format=Path(a.path).suffix.lstrip(".") or "text",
            )
            for i, a in enumerate(artifacts)
            if a.path != "provenance/artifact_inventory.json"
        )
        specs += (
            ArtifactInventoryFileSpec(
                "run-summary",
                "output",
                "run_summary",
                staging / "summary.json",
                "summary.json",
                "json",
            ),
        )
        inventory = build_artifact_inventory(
            run_id=run_id,
            workflow="mania.run",
            inventory_path="provenance/artifact_inventory.json",
            file_specs=specs,
            checksum_mode=config.reproducibility.checksum_mode,
        )
        if final_inputs is not None:
            inventory = replace(
                inventory, artifacts=(*final_inputs.artifacts, *inventory.artifacts)
            )
        _json(staging / "provenance/artifact_inventory.json", inventory.to_dict())
        writer.publish(
            staging / "provenance/artifact_inventory.json",
            "provenance/artifact_inventory.json",
        )
        writer.publish(staging / "summary.json", "summary.json")
        writer.remove_obsolete()
        result = RunResult(plan, summary, writer.root, tuple(inputs))
    try:
        notify({"event": "provenance_done"})
        notify({"event": "finalized", "status": result.summary.status})
    except KeyboardInterrupt as exc:
        raise RunExecutionError(
            "Cancelled after artifact finalization", result, 130
        ) from exc
    except Exception as exc:
        raise RunExecutionError(str(exc), result, 4) from exc
    if exit_code:
        raise RunExecutionError(
            str(error) if error is not None else "QC review remains pending",
            result,
            exit_code,
        )
    return result
