"""Pure pre-canonical Dataset source rows for lipid and glycan window metrics."""

from dataclasses import asdict, dataclass
from typing import Any, ClassVar, get_args

from mania.dataset_identity import DatasetEngine
from mania.preprocessing.molecular_partner_entities import _require_index, _require_text
from mania.preprocessing.physical_time_execution import (
    PreprocessingConditionTemporalExecution,
)
from mania.preprocessing.physical_time_windows import ResolvedPhysicalTimeWindow
from mania.preprocessing.protein_edge_window_table import _effective_ns, _number
from mania.preprocessing.specialized_contact_windows import (
    METRIC_COLUMNS,
    ProteinGlycanWindowAggregation,
    ProteinGlycanWindowMetric,
    ProteinLipidWindowAggregation,
    ProteinLipidWindowMetric,
)

PROTEIN_LIPID_CONTACTS_BY_WINDOW_SOURCE_FILENAME = (
    "protein_lipid_contacts_by_window_source.csv"
)
PROTEIN_GLYCAN_CONTACTS_BY_WINDOW_SOURCE_FILENAME = (
    "protein_glycan_contacts_by_window_source.csv"
)
DATASET_COLUMNS = (
    "dataset_id",
    "system_id",
    "trajectory_id",
    "variant_id",
    "engine",
    "condition",
    "replica_id",
    "disulfide_state",
)
WINDOW_COLUMNS = (
    "window_id",
    "window_index",
    "requested_window_start_ns",
    "requested_window_end_ns",
    "right_endpoint_inclusive",
    "effective_window_start_ns",
    "effective_window_end_ns",
    "requested_sample_count",
    "resolved_frame_count",
    "missing_sample_count",
    "coverage_fraction",
)
PROTEIN_COLUMNS = (
    "protein_residue_index",
    "protein_chain_id",
    "protein_resid",
    "protein_resname",
)
LIPID_COLUMNS = (
    "lipid_partner_id",
    "lipid_partner_name",
    "lipid_component_residue_indexes",
)
GLYCAN_COLUMNS = (
    "glycan_partner_id",
    "glycan_partner_name",
    "glycan_component_residue_indexes",
    "carrier_residue_index",
    "first_sugar_residue_index",
    "linkage_evidence",
    "carrier_link_atom_index",
    "first_sugar_link_atom_index",
)


@dataclass(frozen=True)
class _SpecializedContactWindowRow:
    dataset_id: str
    system_id: str
    trajectory_id: str
    variant_id: str
    engine: str
    condition: str | None
    replica_id: str
    disulfide_state: str | None
    window_id: str
    window_index: int
    requested_window_start_ns: float
    requested_window_end_ns: float
    right_endpoint_inclusive: bool
    effective_window_start_ns: float
    effective_window_end_ns: float
    requested_sample_count: int
    resolved_frame_count: int
    missing_sample_count: int
    coverage_fraction: float
    protein_residue_index: int
    protein_chain_id: str | None
    protein_resid: str | None
    protein_resname: str
    n_contact_frames: int
    occupancy: float
    n_contact_episodes: int
    mean_episode_length_ns: float
    max_episode_length_ns: float
    distance_mean_A: float
    distance_min_A: float
    partner_kind: ClassVar[str]

    def __post_init__(self) -> None:
        for name in (
            *DATASET_COLUMNS,
            "protein_chain_id",
            "protein_resid",
            "protein_resname",
        ):
            value = getattr(self, name)
            if value is None and name in (
                "condition",
                "disulfide_state",
                "protein_chain_id",
                "protein_resid",
            ):
                continue
            _require_text(value, name)
            if name in (
                "condition",
                "disulfide_state",
                "protein_chain_id",
                "protein_resid",
            ) and value in ("None", "null", "NA"):
                raise ValueError("Nullable values must use None, not placeholder text")
        if self.engine not in get_args(DatasetEngine):
            raise ValueError("Unsupported Dataset engine")
        for name in (
            "window_index",
            "requested_sample_count",
            "resolved_frame_count",
            "missing_sample_count",
        ):
            _require_index(getattr(self, name), name)
        if type(self.right_endpoint_inclusive) is not bool:
            raise ValueError("right_endpoint_inclusive must be bool")
        for name in (
            "requested_window_start_ns",
            "requested_window_end_ns",
            "effective_window_start_ns",
            "effective_window_end_ns",
            "coverage_fraction",
            *METRIC_COLUMNS,
        ):
            if name not in ("n_contact_frames", "n_contact_episodes"):
                object.__setattr__(self, name, _number(getattr(self, name), name))
        if (
            self.requested_window_end_ns <= self.requested_window_start_ns
            or self.effective_window_end_ns < self.effective_window_start_ns
        ):
            raise ValueError("Invalid requested/effective window bounds")
        if (
            self.resolved_frame_count <= 0
            or self.requested_sample_count
            != self.resolved_frame_count + self.missing_sample_count
        ):
            raise ValueError("Invalid window counts for an observed row")
        if (
            self.coverage_fraction
            != self.resolved_frame_count / self.requested_sample_count
        ):
            raise ValueError("Coverage must use requested-frame denominator")
        values = {
            name: getattr(self, name)
            for name in (
                *METRIC_COLUMNS,
                "window_id",
                "window_index",
                "protein_residue_index",
                "protein_resname",
            )
        }
        values.update(
            protein_residue_id=self.protein_resid,
            protein_segid=self.protein_chain_id,
            n_resolved_frames_in_window=self.resolved_frame_count,
        )
        names = LIPID_COLUMNS if self.partner_kind == "lipid" else GLYCAN_COLUMNS
        values.update({name: getattr(self, name) for name in names})
        model = (
            ProteinLipidWindowMetric
            if self.partner_kind == "lipid"
            else ProteinGlycanWindowMetric
        )
        model(**values)

    @property
    def replica_key(self) -> tuple[str, str, str, str]:
        return self.dataset_id, self.system_id, self.trajectory_id, self.replica_id

    @property
    def partner_id(self) -> str:
        return str(getattr(self, f"{self.partner_kind}_partner_id"))

    @property
    def row_identity(self) -> tuple[str, str, str, str, str, int, str]:
        return (
            *self.replica_key,
            self.window_id,
            self.protein_residue_index,
            self.partner_id,
        )

    @property
    def row_order(self) -> tuple[str, str, str, str, int, int, str]:
        return (
            *self.replica_key,
            self.window_index,
            self.protein_residue_index,
            self.partner_id,
        )

    def to_dict(self) -> dict[str, Any]:
        values = asdict(self)
        name = f"{self.partner_kind}_component_residue_indexes"
        values[name] = list(values[name])
        return values


@dataclass(frozen=True)
class ProteinLipidWindowRow(_SpecializedContactWindowRow):
    lipid_partner_id: str
    lipid_partner_name: str
    lipid_component_residue_indexes: tuple[int, ...]
    partner_kind = "lipid"


@dataclass(frozen=True)
class ProteinGlycanWindowRow(_SpecializedContactWindowRow):
    glycan_partner_id: str
    glycan_partner_name: str
    glycan_component_residue_indexes: tuple[int, ...]
    carrier_residue_index: int
    first_sugar_residue_index: int
    linkage_evidence: str
    carrier_link_atom_index: int | None
    first_sugar_link_atom_index: int | None
    partner_kind = "glycan"


@dataclass(frozen=True)
class _SpecializedContactWindowTable:
    rows: tuple[ProteinLipidWindowRow | ProteinGlycanWindowRow, ...]
    row_type: ClassVar[type[_SpecializedContactWindowRow]]

    def __post_init__(self) -> None:
        if not isinstance(self.rows, tuple) or any(
            type(r) is not self.row_type for r in self.rows
        ):
            raise ValueError("Table rows must have exact layer row type")
        identities = tuple(r.row_identity for r in self.rows)
        if len(set(identities)) != len(identities):
            raise ValueError("Duplicate Dataset/window/protein/partner row identity")
        order = tuple(r.row_order for r in self.rows)
        if order != tuple(sorted(order)):
            raise ValueError(
                "Rows must follow deterministic Dataset/window/protein/partner order"
            )

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def to_dict(self) -> dict[str, object]:
        return {"row_count": self.row_count, "rows": [r.to_dict() for r in self.rows]}


@dataclass(frozen=True)
class ProteinLipidWindowTable(_SpecializedContactWindowTable):
    row_type = ProteinLipidWindowRow


@dataclass(frozen=True)
class ProteinGlycanWindowTable(_SpecializedContactWindowTable):
    row_type = ProteinGlycanWindowRow


def dataset_window_values(
    binding: PreprocessingConditionTemporalExecution, window: ResolvedPhysicalTimeWindow
) -> dict[str, Any]:
    values = {
        name: getattr(binding.dataset_spec.identity, name) for name in DATASET_COLUMNS
    }
    values.update(
        window_id=window.window_id,
        window_index=window.window_index,
        requested_window_start_ns=window.requested_start_ns,
        requested_window_end_ns=window.requested_end_ns,
        right_endpoint_inclusive=window.right_endpoint_inclusive,
        effective_window_start_ns=_effective_ns(window.effective_start_time_ps),
        effective_window_end_ns=_effective_ns(window.effective_end_time_ps),
        requested_sample_count=window.requested_sample_count,
        resolved_frame_count=window.sampled_frame_count,
        missing_sample_count=window.missing_sample_count,
        coverage_fraction=window.coverage_fraction,
    )
    return values


def _build_rows(
    inputs: Any, aggregation_type: type[Any], row_type: type[Any]
) -> tuple[Any, ...]:
    if not isinstance(inputs, tuple):
        raise ValueError("Inputs must be a tuple of temporal/aggregation pairs")
    rows = []
    keys = set()
    for binding, aggregation in inputs:
        if (
            type(binding) is not PreprocessingConditionTemporalExecution
            or type(aggregation) is not aggregation_type
        ):
            raise ValueError("Exact temporal binding and aggregation required")
        key = binding.dataset_spec.identity.replica_key
        if key in keys:
            raise ValueError("Duplicate Dataset replica key")
        keys.add(key)
        if binding.execution_condition != aggregation.execution_condition:
            raise ValueError("Execution conditions must match")
        status = (
            "complete"
            if binding.sampling_plan.status == binding.window_plan.status == "complete"
            else "partial"
        )
        if aggregation.status != status:
            raise ValueError("Aggregation status must match physical coverage")
        for window, statistics in zip(
            binding.window_plan.windows, aggregation.windows, strict=True
        ):
            for name, source_name in (
                ("window_id", "window_id"),
                ("window_index", "window_index"),
                ("requested_sample_count", "requested_sample_count"),
                ("resolved_frame_count", "sampled_frame_count"),
                ("missing_sample_count", "missing_sample_count"),
                ("coverage_fraction", "coverage_fraction"),
            ):
                if getattr(statistics, name) != getattr(window, source_name):
                    raise ValueError("Aggregation coverage must match temporal window")
            for metric in statistics.metrics:
                values = asdict(metric)
                values.pop("n_resolved_frames_in_window")
                resid = values.pop("protein_residue_id")
                values["protein_resid"] = str(resid) if resid is not None else None
                values["protein_chain_id"] = values.pop("protein_segid")
                values.update(dataset_window_values(binding, window))
                rows.append(row_type(**values))
    return tuple(sorted(rows, key=lambda row: row.row_order))


def build_protein_lipid_window_table(
    inputs: tuple[
        tuple[PreprocessingConditionTemporalExecution, ProteinLipidWindowAggregation],
        ...,
    ],
) -> ProteinLipidWindowTable:
    return ProteinLipidWindowTable(
        _build_rows(inputs, ProteinLipidWindowAggregation, ProteinLipidWindowRow)
    )


def build_protein_glycan_window_table(
    inputs: tuple[
        tuple[PreprocessingConditionTemporalExecution, ProteinGlycanWindowAggregation],
        ...,
    ],
) -> ProteinGlycanWindowTable:
    return ProteinGlycanWindowTable(
        _build_rows(inputs, ProteinGlycanWindowAggregation, ProteinGlycanWindowRow)
    )
