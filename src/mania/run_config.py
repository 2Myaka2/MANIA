"""Closed owner-approved run YAML models, separate from retained legacy config."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal, Self, cast

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    PlainValidator,
    PrivateAttr,
    SerializerFunctionWrapHandler,
    StringConstraints,
    model_serializer,
    model_validator,
)

from mania.canonical_reference import InputIdentity
from mania.input_binding import WindowRequest

Text = Annotated[str, StringConstraints(min_length=1, pattern=r"^\S(?:.*\S)?$")]
PositiveInt = Annotated[int, Field(gt=0)]
Index = Annotated[int, Field(ge=0)]
FinitePositive = Annotated[float, Field(gt=0, allow_inf_nan=False)]
Frequency = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class RunConfigError(ValueError):
    """Invalid closed schema; maps to CLI exit 2."""


class RunPreflightError(ValueError):
    """Missing or unsafe required input/authority; maps to CLI exit 3."""


def _path(value: object) -> Path:
    if not isinstance(value, (str, Path)):
        raise ValueError("A local Path/string is required")
    text = str(value)
    if (
        not text
        or text != text.strip()
        or any(c in text for c in ("~", "$", "%", "*", "?", "[", "]", "\\", ":"))
        or any(ord(c) < 32 or ord(c) == 127 for c in text)
    ):
        raise ValueError("Paths require literal nonempty local names")
    path = Path(value)
    if ".." in path.parts:
        raise ValueError("Paths require local Path/string without traversal")
    return path


LocalPath = Annotated[Path, PlainValidator(_path)]


def _ordered(value: object) -> object:
    if type(value) is list:
        return tuple(value)
    if type(value) is not tuple:
        raise ValueError("An ordered list/tuple is required")
    return value


class RunModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, frozen=True, revalidate_instances="never"
    )


class Frames(RunModel):
    start: Index = 0
    stop: PositiveInt | None = None
    stride: PositiveInt = 1
    max_frames: PositiveInt | None = None
    indexes: Annotated[tuple[Index, ...], BeforeValidator(_ordered)] | None = None

    @model_validator(mode="after")
    def _selector(self) -> Self:
        if self.stop is not None and self.stop <= self.start:
            raise ValueError("Frame stop must exceed start")
        if self.indexes is not None and (
            not self.indexes
            or tuple(sorted(set(self.indexes))) != self.indexes
            or (self.start, self.stop, self.stride, self.max_frames)
            != (0, None, 1, None)
        ):
            raise ValueError("Indexes require increasing unique exclusive selection")
        return self


class PhysicalTime(RunModel):
    production_start_ns: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    production_end_ns: FinitePositive
    frame_stride_ps: FinitePositive
    windows: WindowRequest | None = None

    @model_validator(mode="after")
    def _interval(self) -> Self:
        if self.production_end_ns <= self.production_start_ns:
            raise ValueError("Production end must exceed start")
        return self


class PBC(RunModel):
    mode: Literal["nonperiodic", "prepared", "unverified"]
    preparation_evidence_path: LocalPath | None = None
    declaration: Text

    @model_validator(mode="after")
    def _evidence(self) -> Self:
        if self.mode == "prepared" and self.preparation_evidence_path is None:
            raise ValueError("Prepared coordinates require supplied evidence")
        if (
            self.mode in ("nonperiodic", "unverified")
            and self.preparation_evidence_path is not None
        ):
            raise ValueError("Nonperiodic declaration conflicts with prepared evidence")
        return self


class Reference(RunModel):
    reference_path: LocalPath
    sha256: Digest | None = None


class NAMDAuthority(RunModel):
    elements_path: LocalPath
    time_path: LocalPath


class Output(RunModel):
    root: LocalPath
    overwrite: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    retain_perframe: bool = False


class Method(RunModel):
    enabled: bool = True


class Contacts(Method):
    selection: Literal["protein", "all"] = "protein"
    atom_filter: Literal["heavy"] = "heavy"
    cutoff_distance: FinitePositive = 4.5
    distance_unit: Literal["angstrom"] = "angstrom"
    skip_resnames: Annotated[tuple[Text, ...], BeforeValidator(_ordered)] = ()
    min_frequency: Frequency = 0.0

    @model_validator(mode="after")
    def _names(self) -> Self:
        if len(set(self.skip_resnames)) != len(self.skip_resnames):
            raise ValueError("Duplicate skip residue names")
        return self


class RegionEnrichment(Method):
    annotations_path: LocalPath | None = None

    @model_validator(mode="after")
    def _authority(self) -> Self:
        if self.enabled and self.annotations_path is None:
            raise ValueError("Explicit region enrichment requires annotations_path")
        return self


class Rg(Method):
    selection: Text | None = None
    include_failed_frames: bool = True

    @model_validator(mode="after")
    def _explicit(self) -> Self:
        if self.enabled and self.selection is None:
            raise ValueError("Explicit Rg requires selection")
        return self


class RMSDReference(RunModel):
    kind: Literal["first_selected", "external"]
    path: LocalPath | None = None
    atom_mapping_path: LocalPath | None = None

    @model_serializer(mode="wrap")
    def _wire_reference(
        self, handler: SerializerFunctionWrapHandler
    ) -> dict[str, object]:
        if self.kind == "first_selected":
            return {"kind": "first_selected"}
        return cast(dict[str, object], handler(self))

    @model_validator(mode="after")
    def _source(self) -> Self:
        supplied = (self.path is not None, self.atom_mapping_path is not None)
        if self.kind == "external" and supplied != (True, True):
            raise ValueError("External RMSD requires reference and atom mapping paths")
        if self.kind == "first_selected" and self.model_fields_set != {"kind"}:
            raise ValueError("first_selected reference accepts only kind")
        return self


class RMSD(Method):
    fit_selection: Text | None = None
    evaluation_selection: Text | None = None
    reference: RMSDReference | None = None

    @model_validator(mode="after")
    def _explicit(self) -> Self:
        if self.enabled and any(
            v is None
            for v in (self.fit_selection, self.evaluation_selection, self.reference)
        ):
            raise ValueError("Explicit RMSD requires fit, evaluation and reference")
        return self


class TemporalRin(Method):
    window_size: PositiveInt = 10
    step_size: PositiveInt = 10
    min_frequency: Frequency = 0.25


class PCA(Method):
    max_components: PositiveInt = 10


class Clustering(Method):
    basis: Literal["fingerprint", "pca"] = "fingerprint"
    max_k: Annotated[int, Field(ge=2)] = 10
    max_iterations: PositiveInt = 100
    pca_components: PositiveInt | None = None

    @model_validator(mode="after")
    def _basis(self) -> Self:
        if self.basis == "fingerprint" and self.pca_components is not None:
            raise ValueError("pca_components conflicts with fingerprint basis")
        return self


class Replay(Method):
    completion_path: LocalPath | None = None
    execution_plan_path: LocalPath | None = None

    @model_validator(mode="after")
    def _sources(self) -> Self:
        if self.enabled and (
            self.completion_path is None or self.execution_plan_path is None
        ):
            raise ValueError("Replay requires completion and execution plan paths")
        return self


class QC(Method):
    policy_path: LocalPath | None = None
    evidence_manifest_path: LocalPath | None = None
    review_decisions_path: LocalPath | None = None

    @model_validator(mode="after")
    def _evidence(self) -> Self:
        if self.enabled and self.evidence_manifest_path is None:
            raise ValueError("Explicit QC requires evidence_manifest_path")
        return self


class RMSF(Method):
    atom_selection: Text = "protein and name CA"
    fit_selection: Text = "protein and name CA"
    reference: RMSDReference = Field(
        default_factory=lambda: RMSDReference(kind="first_selected")
    )


def _probe_real(value: object) -> object:
    if type(value) not in (int, float):
        raise ValueError("Probe requires a finite real, never bool")
    return value


def _rationale(value: object) -> object:
    if value is not None and (type(value) is not str or not value.strip()):
        raise ValueError("Environment rationale must contain non-whitespace text")
    return value


class SASA(Method):
    frame_stride: Annotated[int, Field(gt=0, strict=True)] = 1
    target_selection: Text = "protein"
    variants: Annotated[
        tuple[Literal["isolated", "with_environment"], ...], BeforeValidator(_ordered)
    ] = ("isolated",)
    environment_selection: Text | None = None
    environment_rationale: Annotated[str | None, BeforeValidator(_rationale)] = None
    probe_radius_A: Annotated[
        float, BeforeValidator(_probe_real), Field(ge=0.5, le=3.0, allow_inf_nan=False)
    ] = 1.4
    include_hydrogens: bool = False

    @model_validator(mode="after")
    def _environment(self) -> Self:
        if not self.variants or len(set(self.variants)) != len(self.variants):
            raise ValueError("SASA requires nonempty unique variants")
        if (
            self.enabled
            and "with_environment" in self.variants
            and (
                self.environment_selection is None or self.environment_rationale is None
            )
        ):
            raise ValueError(
                "with_environment requires explicit selection "
                "and environment_rationale; "
                "selected ions require an explanation of their inclusion"
            )
        return self


class Methods(RunModel):
    @model_validator(mode="before")
    @classmethod
    def _option_object(cls, value: object) -> object:
        if isinstance(value, dict) and any(option is None for option in value.values()):
            raise ValueError("Supplied methods require a typed options object")
        if isinstance(value, cls) and any(
            getattr(value, name) is None for name in value.model_fields_set
        ):
            raise ValueError("Supplied methods require a typed options object")
        return value

    contacts: Contacts | None = None
    static_rin: Method | None = None
    communities: Method | None = None
    region_enrichment: RegionEnrichment | None = None
    rg: Rg | None = None
    rmsd: RMSD | None = None
    rmsf: RMSF | None = None
    sasa: SASA | None = None
    typed_interactions: Method | None = None
    temporal_rin: TemporalRin | None = None
    fingerprints: Method | None = None
    pca: PCA | None = None
    clustering: Clustering | None = None
    physical_windows: Method | None = None
    lipid_contacts: Method | None = None
    glycan_contacts: Method | None = None
    replay: Replay | None = None
    comparison: Method | None = None
    replica_aggregation: Method | None = None
    qc: QC | None = None
    profile_outputs: Method | None = None


class System(RunModel):
    id: Text
    trajectory_id: Text
    replica_id: Text
    condition: Text | None = None
    variant_id: Text | None = None
    disulfide_state: Text | None = None
    engine: Literal["gromacs", "namd"]
    topology: LocalPath
    trajectories: Annotated[
        tuple[LocalPath, ...], BeforeValidator(_ordered), Field(min_length=1)
    ]
    pbc: PBC
    frames: Frames = Field(default_factory=Frames)
    physical_time: PhysicalTime | None = None
    reference: Reference | None = None
    mapping_path: LocalPath | None = None
    annotations_path: LocalPath | None = None
    partners_path: LocalPath | None = None
    namd_authority: NAMDAuthority | None = None
    input_binding_path: LocalPath | None = None
    fasta_path: LocalPath | None = None
    method_overrides: Methods | None = None

    @model_validator(mode="after")
    def _requests(self) -> Self:
        if self.physical_time is not None and "frames" in self.model_fields_set:
            raise ValueError("Explicit frame and physical-time selectors conflict")
        if len(set(self.trajectories)) != len(self.trajectories):
            raise ValueError("Duplicate trajectory path")
        if self.engine == "namd" and (len(self.trajectories) != 1):
            raise RunPreflightError(
                "NAMD requires element/time authority and one bound DCD"
            )
        if self.engine == "gromacs" and self.namd_authority is not None:
            raise ValueError("NAMD authority conflicts with engine")
        return self

    def identity(self, project: str) -> InputIdentity:
        return InputIdentity(
            project=project,
            system_id=self.id,
            trajectory_id=self.trajectory_id,
            replica_id=self.replica_id,
            engine=self.engine,
            condition=self.condition,
            variant_id=self.variant_id,
            disulfide_state=self.disulfide_state,
        )


class ExtensionOptions(RunModel):
    release_input_manifest_path: LocalPath | None = None
    qc_manifest_path: LocalPath | None = None


class Extension(RunModel):
    id: Literal["napi2b"]
    version: Literal["==0.2.0a1", "==0.2.0a2", "==0.2.0a3", "==0.2.0"]
    profile: Literal["napi2b.legacy.v1", "napi2b.dataset.v1"]
    options: ExtensionOptions = Field(default_factory=ExtensionOptions)


class Member(RunModel):
    system_id: Text
    trajectory_id: Text
    replica_id: Text


Members = Annotated[tuple[Member, ...], BeforeValidator(_ordered)]


class Comparison(RunModel):
    id: Text
    members: Annotated[Members, Field(min_length=2)]
    matching_path: LocalPath
    annotations_path: LocalPath | None = None


class ReplicaGroup(RunModel):
    id: Text
    members: Annotated[Members, Field(min_length=1)]
    reference_id: Text
    layer: Literal["protein", "lipid", "glycan"]
    availability_path: LocalPath
    correspondence_path: LocalPath | None = None
    qc_decisions_path: LocalPath | None = None

    @model_validator(mode="after")
    def _partners(self) -> Self:
        if self.layer != "protein" and self.correspondence_path is None:
            raise ValueError("Specialized replica layer requires correspondence")
        return self


class Reproducibility(RunModel):
    checksum_mode: Literal["none", "sha256"] = "none"
    input_checksum_manifest_path: LocalPath | None = None


class RunConfig(RunModel):
    """Strict public config; no execution or implicit scientific activation."""

    _config_path: Path | None = PrivateAttr(default=None)
    schema_version: Literal["mania.run_config.v1"]
    project: Text
    mode: Literal["basic", "custom", "full", "exploratory"] = "basic"
    systems: Annotated[
        tuple[System, ...], BeforeValidator(_ordered), Field(min_length=1)
    ]
    output: Output
    methods: Methods = Field(default_factory=Methods)
    extensions: Annotated[tuple[Extension, ...], BeforeValidator(_ordered)] = ()
    comparisons: Annotated[tuple[Comparison, ...], BeforeValidator(_ordered)] = ()
    replica_groups: Annotated[tuple[ReplicaGroup, ...], BeforeValidator(_ordered)] = ()
    reproducibility: Reproducibility = Field(default_factory=Reproducibility)

    @model_validator(mode="after")
    def _identities(self) -> Self:
        identities = {(s.id, s.trajectory_id, s.replica_id) for s in self.systems}
        if len(identities) != len(self.systems):
            raise ValueError("Duplicate composite input identity")
        if len({e.id for e in self.extensions}) != len(self.extensions):
            raise ValueError("Duplicate selected extension")
        for groups in (self.comparisons, self.replica_groups):
            if len({g.id for g in groups}) != len(groups):
                raise ValueError("Duplicate group identity")
            for group in groups:
                members = [
                    (m.system_id, m.trajectory_id, m.replica_id) for m in group.members
                ]
                if len(set(members)) != len(members) or not set(members) <= identities:
                    raise ValueError("Duplicate or unknown group member")
        selected_policy = bool(self.extensions)
        explicit_enabled = False
        for system in self.systems:
            if system.pbc.mode == "unverified" and self.mode != "exploratory":
                raise ValueError("Unverified PBC requires exploratory mode")
            merged = merge_methods(self, system)
            explicit_enabled |= any(
                v is not None and v.enabled for v in merged.values()
            )
            # Source-bound QC/replay and group serialization do not open coordinates.
            coordinates = any(
                value is not None
                and value.enabled
                and name
                not in (
                    "qc",
                    "replay",
                    "comparison",
                    "replica_aggregation",
                    "profile_outputs",
                )
                for name, value in merged.items()
            )
            if (
                system.engine == "namd"
                and coordinates
                and system.namd_authority is None
            ):
                raise RunPreflightError(
                    "NAMD requires element/time authority and one bound DCD"
                )
            qc = merged.get("qc")
            if (
                isinstance(qc, QC)
                and qc.enabled
                and qc.policy_path is None
                and not selected_policy
            ):
                raise ValueError("Generic QC requires explicit policy_path")
            profile = merged.get("profile_outputs")
            if (
                profile is not None
                and profile.enabled
                and not any(e.profile == "napi2b.dataset.v1" for e in self.extensions)
            ):
                raise ValueError("profile_outputs requires explicit dataset profile")
        if self.mode in ("custom", "exploratory") and not explicit_enabled:
            raise ValueError(
                "Custom requires an explicit enabled method"
                if self.mode == "custom"
                else "Exploratory requires an enabled effective method"
            )
        return self


def load_run_config(path: str | Path) -> RunConfig:
    """Read strict YAML and bind local paths relative to its own directory."""
    from mania.run_config_io import load_run_config as load

    return load(path)


METHOD_IDS = tuple(Methods.model_fields)


def merge_methods(config: RunConfig, system: System) -> dict[str, Method]:
    """Merge only declared fields; defaults come from the existing typed models."""
    result: dict[str, Method] = {}
    if config.mode in ("basic", "full", "exploratory"):
        result.update(contacts=Contacts(), static_rin=Method())
    if config.mode == "full":
        result.update(
            rmsf=RMSF(),
            sasa=SASA(),
            communities=Method(),
            typed_interactions=Method(),
            temporal_rin=TemporalRin(),
            fingerprints=Method(),
            pca=PCA(),
            clustering=Clustering(),
            physical_windows=Method(),
            lipid_contacts=Method(),
            glycan_contacts=Method(),
        )
    for options in (config.methods, system.method_overrides):
        if options is None:
            continue
        for name, value in options:
            if value is None:
                continue
            previous = result.get(name)
            values = previous.model_dump() if previous is not None else {}
            values.update(value.model_dump(exclude_unset=True))
            result[name] = type(value).model_validate(values)
    return result
