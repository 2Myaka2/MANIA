"""Generic ordered occupancy vectors and source-exact sample statistics."""

from decimal import Context, Decimal, localcontext
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from mania.canonical_reference import Digest, InputIdentity, Text
from mania.canonical_reference import _StrictModel as StrictModel
from mania.preprocessing.temporal_policy import BoundaryProfile


class ReplicaWindowRow(StrictModel):
    group_id: Text
    layer: Literal["protein", "lipid", "glycan"]
    window_id: Text
    window_index: Annotated[int, Field(ge=0)]
    requested_production_start_ns: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    requested_production_end_ns: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    requested_window_start_ns: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    requested_window_end_ns: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    right_endpoint_inclusive: bool
    window_length_ns: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    window_step_ns: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    overlap_percent: Annotated[float, Field(ge=0, lt=100, allow_inf_nan=False)]
    boundary_profile: BoundaryProfile
    reference_id: Text
    reference_sha256: Digest
    reference_chain_i: Text
    reference_position_i: Annotated[int, Field(ge=1)]
    reference_resname_i: Text
    reference_chain_j: Text | None
    reference_position_j: Annotated[int, Field(ge=1)] | None
    reference_resname_j: Text | None
    group_partner_id: Text | None
    partner_name: Text | None
    edge_type: Text | None
    contributing_replica_keys: tuple[InputIdentity, ...]
    occupancy_values: tuple[
        Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)], ...
    ]
    mean_occupancy: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
    std_occupancy: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None
    median_occupancy: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
    n_replicates_available: Annotated[int, Field(ge=1)]
    n_replicates_supporting: Annotated[int, Field(ge=1)]
    support_fraction: Annotated[float, Field(gt=0, le=1, allow_inf_nan=False)]

    @model_validator(mode="after")
    def _row(self) -> Self:
        n = len(self.occupancy_values)
        keys = [i.model_dump_json() for i in self.contributing_replica_keys]
        if n != self.n_replicates_available or len(keys) != n or len(set(keys)) != n:
            raise ValueError(
                "Occupancy vector must match unique ordered available members"
            )
        expected = occupancy_statistics(self.occupancy_values)
        if tuple(getattr(self, k) for k in expected) != tuple(expected.values()):
            raise ValueError("Statistics differ from the source occupancy vector")
        endpoint = (
            self.reference_chain_j,
            self.reference_position_j,
            self.reference_resname_j,
        )
        if self.layer == "protein":
            if (
                any(v is None for v in endpoint)
                or self.group_partner_id is not None
                or self.partner_name is not None
                or self.edge_type is None
            ):
                raise ValueError("Protein endpoints and partner nullability disagree")
            if (self.reference_chain_i, self.reference_position_i) == (
                self.reference_chain_j,
                self.reference_position_j,
            ):
                raise ValueError("Forbidden reference self-loop")
        elif (
            any(v is not None for v in endpoint)
            or self.group_partner_id is None
            or self.partner_name is None
            or self.edge_type is not None
        ):
            raise ValueError("Specialized partner and endpoint nullability disagree")
        return self


def occupancy_statistics(values: tuple[float, ...]) -> dict[str, float | int | None]:
    """Pinned Stage 31 sorted Decimal(str) accumulation in Context(prec=50)."""
    from math import isfinite

    if not values or any(
        type(v) not in (float, int) or not isfinite(v) or not 0 <= v <= 1
        for v in values
    ):
        raise ValueError("A nonempty finite occupancy vector is required")
    with localcontext(Context(prec=50)):
        ordered = sorted(Decimal(str(v)) for v in values)
        n = len(ordered)
        mean = sum(ordered, Decimal(0)) / Decimal(n)
        middle = n // 2
        median = (
            ordered[middle]
            if n % 2
            else (ordered[middle - 1] + ordered[middle]) / Decimal(2)
        )
        supporting = sum(v > 0 for v in ordered)
        variance = (
            sum(((v - mean) ** 2 for v in ordered), Decimal(0)) / Decimal(n - 1)
            if n >= 2
            else None
        )
        return {
            "mean_occupancy": float(mean),
            "std_occupancy": float(variance.sqrt()) if variance is not None else None,
            "median_occupancy": float(median),
            "n_replicates_available": n,
            "n_replicates_supporting": supporting,
            "support_fraction": float(Decimal(supporting) / Decimal(n)),
        }


class ReplicaWindowTable(StrictModel):
    # Internal carrier; CSV fields are the approved mania.replica_windows.v1 contract.
    rows: tuple[ReplicaWindowRow, ...]

    @model_validator(mode="after")
    def _identities(self) -> Self:
        keys = [
            (
                r.group_id,
                r.layer,
                r.window_id,
                r.window_index,
                r.reference_chain_i,
                r.reference_position_i,
                r.reference_chain_j,
                r.reference_position_j,
                r.group_partner_id,
                r.edge_type,
            )
            for r in self.rows
        ]
        if len(set(keys)) != len(keys):
            raise ValueError("Duplicate aggregate identity")
        return self
