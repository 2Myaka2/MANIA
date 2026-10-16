"""Closed exploratory qualification and explicitly scoped source consumption.

Execution success is technical. These records never grant scientific authority.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Literal, Self, cast

from pydantic import BeforeValidator, model_validator

from mania.canonical_reference import InputIdentity
from mania.input_binding import FileEvidence, portable_path
from mania.method_status import MethodID, MethodState
from mania.run_config import RunModel, Text, _ordered

SCIENCE_WARNING: Literal["SCIENTIFIC_VALIDATION_NOT_PERFORMED"] = (
    "SCIENTIFIC_VALIDATION_NOT_PERFORMED"
)
PortablePath = Annotated[str, BeforeValidator(portable_path)]
Identities = Annotated[tuple[InputIdentity, ...], BeforeValidator(_ordered)]
References = Annotated[tuple[Text, ...], BeforeValidator(_ordered)]
Paths = Annotated[tuple[PortablePath, ...], BeforeValidator(_ordered)]


def _false(value: object) -> object:
    if type(value) is not bool or value:
        raise ValueError("Exploratory results cannot qualify for authoritative release")
    return value


NeverAuthoritative = Annotated[Literal[False], BeforeValidator(_false)]


def _unique(items: Sequence[object]) -> None:
    if len(set(items)) != len(items):
        raise ValueError("Duplicate qualification identity, reference or path")


class SourceScope(RunModel):
    input_identity: InputIdentity
    pbc_mode: Literal["nonperiodic", "prepared", "unverified"]
    pbc_status: Literal["PBC_UNVERIFIED"] | None
    upstream_ref_ids: References
    inherited_pbc_unverified: bool

    @model_validator(mode="after")
    def _pbc(self) -> Self:
        if (self.pbc_status == "PBC_UNVERIFIED") != (self.pbc_mode == "unverified"):
            raise ValueError("PBC marker contradicts the actual declared PBC mode")
        _unique(self.upstream_ref_ids)
        return self


class UpstreamRunScope(RunModel):
    ref_id: Text
    run_id: Text
    mode: Literal["basic", "custom", "full", "exploratory"]
    summary: FileEvidence
    provenance: FileEvidence
    scientific_validation_status: Literal["SCIENTIFIC_VALIDATION_NOT_PERFORMED"] | None
    inherited_pbc_unverified: bool

    @model_validator(mode="after")
    def _status(self) -> Self:
        if (self.scientific_validation_status == SCIENCE_WARNING) != (
            self.mode == "exploratory"
        ):
            raise ValueError("Upstream science marker contradicts actual source mode")
        if (self.summary.role, self.provenance.role) != (
            "run_summary",
            "run_provenance",
        ):
            raise ValueError("Upstream evidence roles differ")
        return self


class MethodScope(RunModel):
    method_id: MethodID
    identity: InputIdentity | Text
    execution_status: MethodState
    source_identities: Identities
    upstream_ref_ids: References
    artifact_paths: Paths
    inherited_pbc_unverified: bool
    scientific_validation_status: Literal["SCIENTIFIC_VALIDATION_NOT_PERFORMED"] = (
        SCIENCE_WARNING
    )
    authoritative_release_eligible: NeverAuthoritative = False

    @model_validator(mode="after")
    def _final(self) -> Self:
        if self.execution_status in ("planned", "running"):
            raise ValueError("Qualification requires final method states")
        for values in (
            self.source_identities,
            self.upstream_ref_ids,
            self.artifact_paths,
        ):
            _unique(values)
        return self


class ArtifactScope(RunModel):
    role: Text
    path: PortablePath
    producer_method: MethodID
    producer_identity: InputIdentity | Text
    source_identities: Identities
    upstream_ref_ids: References
    inherited_pbc_unverified: bool
    scientific_validation_status: Literal["SCIENTIFIC_VALIDATION_NOT_PERFORMED"] = (
        SCIENCE_WARNING
    )
    authoritative_release_eligible: NeverAuthoritative = False

    @model_validator(mode="after")
    def _sources(self) -> Self:
        _unique(self.source_identities)
        _unique(self.upstream_ref_ids)
        return self


class ScientificQualificationV1(RunModel):
    schema_version: Literal["mania.scientific_qualification.v1"] = (
        "mania.scientific_qualification.v1"
    )
    kind: Literal["mania_scientific_qualification"] = "mania_scientific_qualification"
    mode: Literal["exploratory"] = "exploratory"
    scientific_validation_status: Literal["SCIENTIFIC_VALIDATION_NOT_PERFORMED"] = (
        SCIENCE_WARNING
    )
    authoritative_release_eligible: NeverAuthoritative = False
    source_scopes: Annotated[tuple[SourceScope, ...], BeforeValidator(_ordered)]
    upstream_runs: Annotated[tuple[UpstreamRunScope, ...], BeforeValidator(_ordered)]
    method_scopes: Annotated[tuple[MethodScope, ...], BeforeValidator(_ordered)]
    artifact_scopes: Annotated[tuple[ArtifactScope, ...], BeforeValidator(_ordered)]

    @model_validator(mode="after")
    def _lineage(self) -> Self:
        _unique(tuple(s.input_identity for s in self.source_scopes))
        _unique(tuple(s.ref_id for s in self.upstream_runs))
        _unique(tuple((s.method_id, s.identity) for s in self.method_scopes))
        _unique(tuple(s.path for s in self.artifact_scopes))
        sources = {s.input_identity: s for s in self.source_scopes}
        upstream = {s.ref_id: s for s in self.upstream_runs}
        methods = {(s.method_id, s.identity): s for s in self.method_scopes}
        for source in self.source_scopes:
            if not set(source.upstream_ref_ids) <= set(
                upstream
            ) or source.inherited_pbc_unverified != any(
                upstream[r].inherited_pbc_unverified for r in source.upstream_ref_ids
            ):
                raise ValueError("Source upstream PBC lineage differs")
        scopes: tuple[MethodScope | ArtifactScope, ...] = (
            *self.method_scopes,
            *self.artifact_scopes,
        )
        for scope in scopes:
            if not set(scope.source_identities) <= set(sources) or not set(
                scope.upstream_ref_ids
            ) <= set(upstream):
                raise ValueError("Unknown source or upstream qualification reference")
            inherited = any(
                sources[i].pbc_mode == "unverified"
                or sources[i].inherited_pbc_unverified
                for i in scope.source_identities
            ) or any(
                upstream[r].inherited_pbc_unverified for r in scope.upstream_ref_ids
            )
            if scope.inherited_pbc_unverified != inherited:
                raise ValueError("Derived PBC marker contradicts complete lineage")
        for artifact in self.artifact_scopes:
            producer = methods.get(
                (artifact.producer_method, artifact.producer_identity)
            )
            if producer is None or artifact.path not in producer.artifact_paths:
                raise ValueError("Artifact lacks its unique declared method producer")
            if (artifact.source_identities, artifact.upstream_ref_ids) != (
                producer.source_identities,
                producer.upstream_ref_ids,
            ):
                raise ValueError("Artifact lineage differs from its producer")
        for producer in self.method_scopes:
            if producer.artifact_paths != tuple(
                a.path
                for a in self.artifact_scopes
                if (a.producer_method, a.producer_identity)
                == (producer.method_id, producer.identity)
            ):
                raise ValueError("Method artifact coverage or order differs")
        return self


@dataclass
class _ConsumedRun:
    root: Path
    summary: Any
    identity: InputIdentity
    pbc_unverified: bool
    consumers: set[tuple[str, object]] = field(default_factory=set)
    direct: bool = False
    snapshot: dict[str, str] = field(default_factory=dict)
    summary_evidence: FileEvidence | None = None
    provenance_evidence: FileEvidence | None = None


@dataclass
class _Consumption:
    mode: str
    consumer: tuple[str, object] | None = None
    runs: dict[tuple[Path, InputIdentity, bool], _ConsumedRun] = field(
        default_factory=dict
    )
    declared_sources: dict[tuple[str, object], tuple[InputIdentity, ...]] = field(
        default_factory=dict
    )
    dependencies: dict[Path, dict[str, str]] = field(default_factory=dict)


_CONSUMPTION: ContextVar[_Consumption | None] = ContextVar(
    "mania_scientific_consumption", default=None
)
_READING: ContextVar[tuple[Path, ...]] = ContextVar(
    "mania_upstream_read_stack", default=()
)


@contextmanager
def consumption(mode: str, *, independent: bool = False) -> Iterator[None]:
    current = _CONSUMPTION.get()
    if not independent and current is not None and current.mode == mode:
        yield
        return
    child = _Consumption(mode)
    token = _CONSUMPTION.set(child)
    try:
        yield
    finally:
        if current is not None:
            current.dependencies.update(child.dependencies)
            current.dependencies.update(
                {r.root: r.snapshot for r in child.runs.values()}
            )
        _CONSUMPTION.reset(token)


def set_consumer(method: str, identity: InputIdentity | str) -> None:
    current = _CONSUMPTION.get()
    if current is not None:
        current.consumer = method, identity


def consume_provenance(
    path: Path,
    identity: InputIdentity,
    *,
    artifact: Path | None = None,
    direct: bool = False,
    verify_science: bool = True,
) -> None:
    """Default refusal; exploratory opt-in still requires full source read-back."""
    from mania.result_readers import read_run_summary, validate_run_artifacts
    from mania.run_provenance_io import read_run_provenance

    provenance = read_run_provenance(path)
    qualification = getattr(provenance, "scientific_qualification", None)
    current = _CONSUMPTION.get()
    if qualification is not None and (current is None or current.mode != "exploratory"):
        raise ValueError(
            "Exploratory upstream is ineligible for authoritative "
            "scientific consumption"
        )
    roots = [p for p in path.parents if (p / "summary.json").is_file()]
    root = next(
        (r for r in roots if r / read_run_summary(r).provenance_path == path), None
    )
    if root is None:
        if qualification is not None:
            raise ValueError(
                "Exploratory upstream requires its complete source-bound result root"
            )
        return
    if not verify_science:
        header = read_run_summary(root)
        if (
            header.run_id != provenance.run_id
            or getattr(header, "scientific_qualification", None) != qualification
        ):
            raise ValueError(
                "Upstream header/provenance identity or qualification differs"
            )
        if identity not in tuple(p.input_identity for p in header.path_identity_map):
            raise ValueError("Upstream header source identity differs")
        return
    active = _READING.get()
    if root in active:
        raise ValueError("Cyclic upstream result dependency")
    token = _READING.set((*active, root))
    try:
        verified = validate_run_artifacts(root)
    finally:
        _READING.reset(token)
    summary = verified.summary
    if identity not in verified.plan.input_identities:
        raise ValueError("Upstream full input identity differs")
    inherited = False
    if qualification is not None:
        if artifact is not None:
            scopes = [
                a for a in qualification.artifact_scopes if root / a.path == artifact
            ]
            if len(scopes) != 1 or identity not in scopes[0].source_identities:
                raise ValueError(
                    "Consumed artifact lacks its exact source qualification"
                )
            inherited = scopes[0].inherited_pbc_unverified
        else:
            inherited = any(
                m.inherited_pbc_unverified
                for m in qualification.method_scopes
                if identity in m.source_identities
            )
    if current is not None:
        key = root, identity, inherited
        entry = current.runs.get(key)
        if entry is None:
            entry = current.runs[key] = _ConsumedRun(root, summary, identity, inherited)
            entry.snapshot = _root_fingerprint(root)
            expected_paths = {a.path for a in summary.artifact_references} | {
                "summary.json"
            }
            if set(entry.snapshot) != expected_paths:
                raise ValueError("Source root changed during validation")
            entry.summary_evidence = _evidence(root, "run_summary", "summary.json")
            entry.provenance_evidence = _evidence(
                root, "run_provenance", summary.provenance_path
            )
        entry.pbc_unverified |= inherited
        entry.direct |= direct
        if current.consumer is not None:
            entry.consumers.add(current.consumer)


def consume_run_path(
    path: Path, identity: InputIdentity, *, direct: bool = False
) -> None:
    """Use actual owned ancestry when present; retained standalone contracts remain."""
    from mania.result_readers import read_run_summary

    for root in path.parents:
        if (root / "summary.json").is_file():
            summary = read_run_summary(root)
            consume_provenance(
                root / summary.provenance_path, identity, artifact=path, direct=direct
            )
            return
        if (root / "run_plan.json").is_file():
            raise ValueError("Controller source root lacks its required summary")


def _evidence(root: Path, role: str, relative: str) -> FileEvidence:
    from mania.input_binding import member

    path = member(root, relative)
    return FileEvidence(
        role=role,
        path=relative,
        size_bytes=path.stat().st_size,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
    )


def declare_sources(identities: tuple[InputIdentity, ...]) -> None:
    current = _CONSUMPTION.get()
    if current is not None and current.consumer is not None:
        current.declared_sources[current.consumer] = identities


def preview_pbc(
    identities: tuple[InputIdentity, ...],
    pbc_by_identity: tuple[tuple[InputIdentity, bool], ...],
) -> bool:
    current = _CONSUMPTION.get()
    return any(
        flag for identity, flag in pbc_by_identity if identity in identities
    ) or bool(
        current is not None
        and any(
            r.pbc_unverified
            for r in current.runs.values()
            if current.consumer in r.consumers
        )
    )


def _method_sources(plan: Any, status: Any) -> tuple[InputIdentity, ...]:
    if status.status in ("not_requested", "missing_optional_input"):
        return ()
    if isinstance(status.identity, InputIdentity):
        return (status.identity,)
    current = _CONSUMPTION.get()
    key = status.method_id, status.identity
    if current is not None and key in current.declared_sources:
        return tuple(
            i for i in current.declared_sources[key] if i in plan.input_identities
        )
    config = plan.effective_parameters
    definitions = (
        config.comparisons
        if status.method_id == "comparison"
        else config.replica_groups
    )
    if status.method_id in ("comparison", "replica_aggregation"):
        group = next(d for d in definitions if d.id == status.identity)
        return tuple(
            next(
                s.identity(config.project)
                for s in config.systems
                if (s.id, s.trajectory_id, s.replica_id)
                == (m.system_id, m.trajectory_id, m.replica_id)
            )
            for m in group.members
        )
    return ()


def planned_producer(
    plan: Any, reference: Any
) -> tuple[str, InputIdentity | str] | None:
    """Resolve declared plan ownership through its explicit ordinal identity map."""
    declared = [
        a
        for a in plan.expected_artifacts
        if (a.role, a.path) == (reference.role, reference.path)
    ]
    if not declared:
        raise ValueError("Actual artifact has no approved plan role/path")
    artifact = declared[0]
    if artifact.producer_method == "controller":
        return None
    for p in plan.path_identity_map:
        if artifact.path.startswith(p.directory + "/"):
            return artifact.producer_method, p.input_identity
    for method, definitions, folder in (
        ("comparison", plan.effective_parameters.comparisons, "comparisons"),
        ("replica_aggregation", plan.effective_parameters.replica_groups, "replicas"),
    ):
        for index, definition in enumerate(definitions, 1):
            if (
                artifact.path.startswith(f"{folder}/g{index:04d}/")
                and artifact.producer_method == method
            ):
                return method, definition.id
    if artifact.producer_method == "profile_outputs":
        return "profile_outputs", "napi2b.dataset.v1"
    raise ValueError("Plan artifact has no exact producer identity")


def build_qualification(
    plan: Any, methods: Sequence[Any], artifacts: Sequence[Any]
) -> ScientificQualificationV1:
    current = _CONSUMPTION.get()
    entries = (
        sorted(
            (r for r in current.runs.values() if r.consumers or r.direct),
            key=lambda r: (str(r.root), r.identity.model_dump_json(), r.pbc_unverified),
        )
        if current is not None
        else []
    )
    upstream = tuple(
        UpstreamRunScope(
            ref_id=f"u{i:04d}",
            run_id=r.summary.run_id,
            mode=r.summary.mode,
            summary=r.summary_evidence
            or _evidence(r.root, "run_summary", "summary.json"),
            provenance=r.provenance_evidence
            or _evidence(r.root, "run_provenance", r.summary.provenance_path),
            scientific_validation_status=SCIENCE_WARNING
            if r.summary.mode == "exploratory"
            else None,
            inherited_pbc_unverified=r.pbc_unverified,
        )
        for i, r in enumerate(entries, 1)
    )
    sources = tuple(
        SourceScope(
            input_identity=s.identity(plan.project),
            pbc_mode=s.pbc.mode,
            pbc_status="PBC_UNVERIFIED" if s.pbc.mode == "unverified" else None,
            upstream_ref_ids=tuple(
                u.ref_id
                for r, u in zip(entries, upstream, strict=True)
                if r.direct and r.identity == s.identity(plan.project)
            ),
            inherited_pbc_unverified=any(
                r.pbc_unverified
                for r in entries
                if r.direct and r.identity == s.identity(plan.project)
            ),
        )
        for s in plan.effective_parameters.systems
    )
    owned = [(a, planned_producer(plan, a)) for a in artifacts]
    method_scopes = []
    for status in methods:
        key = status.method_id, status.identity
        direct = _method_sources(plan, status)
        refs = tuple(
            u.ref_id
            for r, u in zip(entries, upstream, strict=True)
            if key in r.consumers
        )
        inherited = any(
            s.pbc_mode == "unverified" or s.inherited_pbc_unverified
            for s in sources
            if s.input_identity in direct
        )
        inherited |= any(
            u.inherited_pbc_unverified for u in upstream if u.ref_id in refs
        )
        method_scopes.append(
            MethodScope(
                method_id=status.method_id,
                identity=status.identity,
                execution_status=status.status,
                source_identities=direct,
                upstream_ref_ids=refs,
                artifact_paths=tuple(
                    a.path for a, producer in owned if producer == key
                ),
                inherited_pbc_unverified=inherited,
            )
        )
    by_method = {(m.method_id, m.identity): m for m in method_scopes}
    artifact_scopes = []
    for artifact, producer in owned:
        if producer is None:
            continue
        method = by_method[cast(Any, producer)]
        artifact_scopes.append(
            ArtifactScope(
                role=artifact.role,
                path=artifact.path,
                producer_method=method.method_id,
                producer_identity=method.identity,
                source_identities=method.source_identities,
                upstream_ref_ids=method.upstream_ref_ids,
                inherited_pbc_unverified=method.inherited_pbc_unverified,
            )
        )
    return ScientificQualificationV1(
        source_scopes=sources,
        upstream_runs=upstream,
        method_scopes=tuple(method_scopes),
        artifact_scopes=tuple(artifact_scopes),
    )


def _root_fingerprint(root: Path) -> dict[str, str]:
    from mania.output_paths import require_input_file, safe_absolute

    return {
        p.relative_to(root).as_posix(): hashlib.sha256(
            require_input_file(safe_absolute(p)).read_bytes()
        ).hexdigest()
        for p in root.rglob("*")
        if not p.is_dir()
    }


def changed_upstreams() -> tuple[str, ...]:
    current = _CONSUMPTION.get()
    if current is None:
        return ()
    snapshots = dict(current.dependencies)
    snapshots.update({r.root: r.snapshot for r in current.runs.values()})
    changed = []
    for root, before in snapshots.items():
        try:
            if _root_fingerprint(root) != before:
                changed.append(str(root))
        except (OSError, ValueError):
            changed.append(str(root))
    return tuple(changed)


def warning_records(
    config: Any, qualification: ScientificQualificationV1 | None = None
) -> tuple[dict[str, object], ...]:
    inherited = (
        tuple(
            {
                "severity": "warning",
                "code": "PBC_UNVERIFIED",
                "message": (
                    f"Inherited unverified PBC from source binding {u.ref_id} "
                    f"(run {u.run_id})."
                ),
            }
            for u in qualification.upstream_runs
            if u.inherited_pbc_unverified
        )
        if qualification is not None
        else ()
    )
    return (
        {
            "severity": "warning",
            "code": SCIENCE_WARNING,
            "message": (
                "Exploratory execution is scientifically unverified "
                "and ineligible for authoritative FAIR release."
            ),
        },
        *(
            {
                "severity": "warning",
                "code": "PBC_UNVERIFIED",
                "input_identity": s.identity(config.project).to_dict(),
                "message": s.pbc.declaration,
            }
            for s in config.systems
            if s.pbc.mode == "unverified"
        ),
        *inherited,
    )
