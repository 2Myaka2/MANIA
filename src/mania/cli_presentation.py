"""Console views of existing plans and observations; no scientific authority."""

from __future__ import annotations

import json
import time
from collections import Counter
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, TextIO

if TYPE_CHECKING:
    from mania.run_config import Frames, System
    from mania.run_plan import RunPlan
    from mania.workflow import RunResult


SUCCESS = {"completed", "completed_with_skips"}


def text(value: object) -> str:
    """Keep configuration labels and paths on plain, safe terminal lines."""
    return "".join(c if c.isprintable() else repr(c)[1:-1] for c in str(value))


def identity_key(value: Any) -> str:
    if hasattr(value, "to_dict"):
        value = value.to_dict()
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def requested_frames(system: System) -> int | None:
    """An arithmetic request bound, never a measured trajectory population."""
    if system.physical_time is not None:
        return None
    f = system.frames
    if f.indexes is not None:
        return len(f.indexes)
    if f.stop is None:
        return None
    count = (f.stop - f.start + f.stride - 1) // f.stride
    return min(count, f.max_frames) if f.max_frames is not None else count


def frame_request(frames: Frames) -> str:
    if frames.indexes is not None:
        return (
            f"{len(frames.indexes)} requested indexes (zero-based, "
            f"first {frames.indexes[0]}, last {frames.indexes[-1]})"
        )
    result = f"start={frames.start}, stop={frames.stop}, stride={frames.stride}"
    if frames.max_frames is not None:
        result += f", max_frames={frames.max_frames}"
    result += " (zero-based; stop exclusive)"
    if frames.stop is not None:
        count = (frames.stop - frames.start + frames.stride - 1) // frames.stride
        if frames.max_frames is not None:
            count = min(count, frames.max_frames)
        last = frames.start + (count - 1) * frames.stride
        result += f"; requested {frames.start}..{last}, maximum {count} frames"
    else:
        result += "; frame count unknown"
    return result


def warning_line(warning: dict[str, object]) -> str:
    context = warning.get("input_identity")
    if isinstance(context, dict):
        context = " / ".join(
            str(context[k])
            for k in ("system_id", "trajectory_id", "replica_id")
            if k in context
        )
    suffix = f" ({text(context)})" if context else ""
    return f"WARNING [{text(warning['code'])}]: {text(warning['message'])}{suffix}"


def format_plan(plan: RunPlan) -> str:
    from mania.scientific_qualification import warning_records

    config = plan.effective_parameters
    by_identity: dict[str, list[Any]] = {}
    for method in plan.methods:
        by_identity.setdefault(identity_key(method.identity), []).append(method)
    lines = [f"MANIA dry-run: {text(plan.project)} | mode: {plan.mode}"]
    for position, system in zip(plan.path_identity_map, config.systems, strict=True):
        lines.extend(
            [
                f"Input: {text(system.id)} / {text(system.trajectory_id)} / "
                f"{text(system.replica_id)} | engine: {system.engine}",
                f"  Topology: {text(system.topology)}",
                *(f"  Trajectory: {text(p)}" for p in system.trajectories),
                f"  Frames requested: {frame_request(system.frames)}",
            ]
        )
        if system.physical_time is not None:
            p = system.physical_time
            lines.append(
                f"  Physical-time request: {p.production_start_ns}.."
                f"{p.production_end_ns} ns, stride {p.frame_stride_ps} ps; "
                "selected source frame count unknown"
            )
        lines.append("  Actual frame availability is checked during execution.")
        for method in by_identity[identity_key(position.input_identity)]:
            if method.status == "not_requested":
                continue
            lines.append("  " + _method_line(method))
    for method in plan.methods:
        if isinstance(method.identity, str) and method.status != "not_requested":
            lines.append(f"Group {text(method.identity)}: {_method_line(method)}")
    for extension in plan.selected_extensions:
        lines.append(
            f"Extension: {extension.distribution}=={extension.version}; "
            f"profile {extension.profile}"
        )
    lines.append(
        f"Output: {text(config.output.root)} | overwrite: "
        f"{str(config.output.overwrite).lower()} (ownership checks apply)"
    )
    warnings = warning_records(config) if config.mode == "exploratory" else ()
    lines.extend(warning_line(w) for w in warnings)
    seen_conditions: set[tuple[str, str]] = set()
    for condition in plan.unverified_conditions:
        relevant = {
            m.method_id
            for m in by_identity.get(identity_key(condition.input_identity), ())
            if m.status == "planned"
        }
        if condition.property == "rg_eligibility" and "rg" not in relevant:
            continue
        if not relevant - {"qc", "replay"}:
            continue
        key = condition.property, condition.reason
        if key in seen_conditions:
            continue
        seen_conditions.add(key)
        if condition.reason == "PBC_UNVERIFIED":
            continue  # Already rendered once with its stable warning code.
        lines.append(f"Unverified {text(condition.property)}: {text(condition.reason)}")
    state = (
        "READY WITH WARNINGS"
        if warnings or any(m.status == "missing_optional_input" for m in plan.methods)
        else "READY"
    )
    lines.append(
        f"{state}: configuration and planning checks only; no trajectory "
        "calculations, full coordinate validation or scientific approval."
    )
    return "\n".join(lines)


def _method_line(method: Any) -> str:
    options = method.effective_parameters.model_dump(mode="json", exclude_none=True)
    values = []
    for key, value in options.items():
        if key == "enabled" or isinstance(value, (dict, list)):
            continue
        if key == "cutoff_distance":
            values.append(f"cutoff {value} angstrom")
        elif key != "distance_unit":
            values.append(f"{key}={text(value)}")
    if method.method_id == "rmsf" and "reference" in options:
        import json

        values.append(
            "reference=" + text(json.dumps(options["reference"], sort_keys=True))
        )
    if method.method_id == "sasa" and "variants" in options:
        values.append("variants=" + text(",".join(options["variants"])))
    if method.method_id in ("rmsf", "sasa"):
        values.append(text(method.message))
    details = "; ".join(values)
    state = method.status
    origin = " (dependency)" if method.request_origin == "dependency" else ""
    reason = f"; {text(method.reason_code)}" if method.reason_code else ""
    return (
        f"{method.method_id}{origin}: {state}"
        + (f"; {details}" if details else "")
        + reason
    )


class ProgressRenderer:
    """O(inputs + methods) state; advancing source indexes count frame_done only.

    Contact source indexes are strictly increasing in the retained backend. A
    repeated/older observation cannot advance this presentation counter. The
    request range is never materialized, including for arbitrarily large stops.
    """

    def __init__(
        self, stream: TextIO, *, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.stream, self.clock = stream, clock
        self.started = clock()
        self.last_update = self.started
        self.tty = stream.isatty()
        self.width = 0
        self.disabled = False
        self.units: set[tuple[str, ...]] = set()
        self.done: set[tuple[str, ...]] = set()
        self.systems: dict[str, System] = {}
        self.frames: dict[str, tuple[int, int]] = {}
        self.active = ""
        self.stage = "Planning and checking prerequisites"
        self.contacts = False
        self.successful = False

    @property
    def elapsed(self) -> float:
        return max(0.0, self.clock() - self.started)

    def __call__(self, event: Any) -> None:
        from mania.preprocessing.trajectory_contacts import (
            PreprocessingContactProgressEvent,
        )

        if isinstance(event, PreprocessingContactProgressEvent):
            if event.stage != "frame_done" or not self.contacts:
                return
            if event.frame_index is None:
                return
            previous, count = self.frames.get(self.active, (-1, 0))
            if event.frame_index <= previous:
                return
            self.frames[self.active] = (event.frame_index, count + 1)
            self._render(force=False)
            return
        if not isinstance(event, dict):
            return
        kind = event.get("event")
        if kind == "plan_ready":
            plan = event["plan"]
            self.units = {("preflight",), ("provenance",), ("finalization",)}
            coordinate_keys = {
                identity_key(s.identity)
                for s in plan.methods
                if s.status == "planned" and s.method_id not in {"replay", "qc"}
            }
            for position, system in zip(
                plan.path_identity_map, plan.effective_parameters.systems, strict=True
            ):
                key = identity_key(position.input_identity)
                self.systems[key] = system
                if key in coordinate_keys:
                    self.units.add(("load", key))
            self.units.update(
                ("method", s.method_id, identity_key(s.identity))
                for s in plan.methods
                if s.status == "planned"
            )
            self._complete(("preflight",))
            self.stage = "Planning and prerequisites complete"
        elif kind == "load_done":
            self._complete(("load", identity_key(event["identity"])))
            self.stage = "Input loading and sampling complete"
        elif kind == "method_done":
            status = event["method"]
            self._complete(("method", status.method_id, identity_key(status.identity)))
            self.stage = f"{status.method_id}: {status.status}"
        elif kind == "publication_started":
            self.contacts = False
            self.stage = "Publishing results, provenance, summary and inventory"
        elif kind == "provenance_done":
            self._complete(("provenance",))
            self.stage = "Provenance published"
        elif kind == "finalized":
            self.stage = "Artifacts finalized"
            # CLI finish() confirms successful return before displaying 100%.
        elif "stage" in event:
            stage = event["stage"]
            if stage == "frame":
                return  # Decoder reads/cancellation checks are not completed work.
            self.active = identity_key(event.get("identity"))
            self.contacts = stage == "contacts"
            label = event.get("identity", {})
            if isinstance(label, dict):
                label = " / ".join(
                    str(label[k])
                    for k in ("system_id", "trajectory_id", "replica_id")
                    if k in label
                )
            self.stage = (
                f"Loading input: {text(label)}"
                if stage == "load"
                else f"{text(stage)}: {text(label)}"
            )
        else:
            return
        self._render(force=True)
        if kind == "method_done":
            self.contacts = False

    def _complete(self, key: tuple[str, ...]) -> None:
        if key in self.units:
            self.done.add(key)

    def _render(self, *, force: bool) -> None:
        if self.disabled:
            return
        now = self.clock()
        if not force and now - self.last_update < 1.0:
            return
        self.last_update = now
        completed = len(self.done)
        progress = "in progress"
        if self.units:
            percent = 100 * completed // len(self.units)
            percent = min(percent, 100 if self.successful else 99)
            progress = f"{percent}% planned work units ({completed}/{len(self.units)})"
        detail = ""
        if self.contacts and self.active in self.frames:
            count = self.frames[self.active][1]
            total = requested_frames(self.systems[self.active])
            if total is not None and count <= total:
                detail = f"; frames completed {count}/{total} requested maximum"
            else:
                detail = f"; {count} frames completed, total unknown"
        line = f"[{self.elapsed:.1f}s] {progress} | {self.stage}{detail}"
        try:
            if self.tty:
                self.stream.write("\r" + line.ljust(self.width))
                self.width = len(line)
            else:
                self.stream.write(line + "\n")
            self.stream.flush()
        except OSError:
            self.disabled = True  # A closed console cannot alter scientific results.

    def finish(self, result: RunResult, *, exit_code: int = 0) -> str:
        state = result.summary.status
        self.successful = state in SUCCESS and exit_code == 0
        if self.successful:
            self._complete(("finalization",))
        self.stage = state if not exit_code else f"stopped (exit {exit_code}): {state}"
        self.contacts = False
        self._render(force=True)
        if self.tty and not self.disabled:
            self.stream.write("\n")
        counts = Counter(
            s.status for s in result.summary.methods if s.status != "not_requested"
        )
        methods = ", ".join(f"{value} {key}" for key, value in sorted(counts.items()))
        frames = sum(len(e.observed_frames) for e in result.inputs)
        observation = (
            f"{frames} observed source frames (summed per input)"
            if frames
            else "observed source frame count unavailable"
        )
        lines = [
            f"MANIA run {self.stage}; elapsed {self.elapsed:.1f}s",
            f"Methods: {methods}",
            f"Frames: {observation}",
            f"Output: {text(result.output_root)}; "
            f"{len(result.summary.artifact_references)} recorded artifacts",
        ]
        issues = [
            f"{s.method_id}={s.status}"
            for s in result.summary.methods
            if s.status not in {"not_requested", "completed"}
        ]
        if issues:
            lines.append("Method details: " + "; ".join(issues))
        qualification = getattr(result.summary, "scientific_qualification", None)
        if qualification is not None:
            lines.extend(
                [
                    "Scientific qualification: SCIENTIFIC_VALIDATION_NOT_PERFORMED",
                    "authoritative_release_eligible=false",
                ]
            )
        else:
            lines.append("Technical execution status grants no scientific approval.")
        return "\n".join(lines)
