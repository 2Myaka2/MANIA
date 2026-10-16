"""Explicit RMSD/empty-window review and source raw-MAD cohort comparisons."""

from decimal import Context, Decimal, localcontext
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mania.dataset_measurement_review import MetricSourceSelection
    from mania.replica_aggregation_contract import ReplicaGroup
    from mania.replica_aggregation_manifest import ReplicaWindowInput

from mania.dataset_qc_contract import (
    REVIEW_CHECK_IDS,
    QCCheckResult,
    QCEvidence,
    QCPolicy,
    validate_policy_evidence,
)


def _median(values: tuple[Decimal, ...]) -> Decimal:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / Decimal(2)


def mad_reviews(
    values: tuple[float | int, ...], *, multiplier: float
) -> tuple[bool, ...]:
    from math import isfinite

    if (
        not values
        or any(type(v) not in (float, int) or not isfinite(v) for v in values)
        or type(multiplier) not in (float, int)
        or not isfinite(multiplier)
        or multiplier < 0
    ):
        raise ValueError(
            "MAD requires a nonempty finite cohort and explicit multiplier"
        )
    decimals = tuple(Decimal(str(v)) for v in values)
    precision = max(
        50,
        max(v.adjusted() for v in decimals)
        - min(int(v.as_tuple().exponent) for v in decimals)
        + 8,
    )
    with localcontext(Context(prec=precision)):
        median = _median(decimals)
        mad = _median(tuple(abs(v - median) for v in decimals))
        if len(decimals) == 1:
            return (False,)
        if mad == 0:
            return tuple(v != median for v in decimals)
        lower = median - Decimal(str(multiplier)) * mad
        upper = median + Decimal(str(multiplier)) * mad
        return tuple(v < lower or v > upper for v in decimals)


def evaluate_dataset_review_qc(
    evidences: tuple[QCEvidence, ...],
    *,
    policy: QCPolicy,
    group: "ReplicaGroup | None" = None,
    window_inputs: tuple["ReplicaWindowInput", ...] = (),
    metric_selections: tuple[tuple["MetricSourceSelection", ...], ...] = (),
    hard_evaluations: tuple[tuple[QCCheckResult, ...], ...] = (),
) -> tuple[tuple[QCCheckResult, ...], ...]:
    if not evidences:
        raise ValueError("Review requires explicit evidence")
    identities = [e.identity.model_dump_json() for e in evidences]
    if len(set(identities)) != len(identities):
        raise ValueError("Duplicate review identity")
    results: list[list[QCCheckResult]] = [[] for _ in evidences]
    mad_results: dict[tuple[int, str], bool] = {}
    has_mad = any(c.startswith("mad:") for c in policy.required_check_ids)
    if has_mad:
        if (
            group is None
            or len(window_inputs) != len(evidences)
            or len(metric_selections) != len(evidences)
            or len(hard_evaluations) != len(evidences)
        ):
            raise ValueError(
                "Dataset MAD review blocked: complete typed source/cohort/har"
                "d evidence is required"
            )
        from mania.dataset_hard_qc import evaluate_replica_hard_qc
        from mania.dataset_measurement_review import validate_window_measurements

        expected = tuple(m.identity for m in group.members)
        if (
            tuple(e.identity for e in evidences) != expected
            or tuple(i.identity for i in window_inputs) != expected
        ):
            raise ValueError("Incomplete source metric cohort/member roster")
        eligible = []
        keys = {}
        for n, (e, source, selections, hard) in enumerate(
            zip(
                evidences,
                window_inputs,
                metric_selections,
                hard_evaluations,
                strict=True,
            )
        ):
            temporal, _ = source.read_back()
            if hard != evaluate_replica_hard_qc(
                e, policy=policy, source_sampling=temporal.sampling_plan
            ):
                raise ValueError("MAD eligibility differs from actual hard evaluations")
            if any(c.status == "FAIL" for c in hard):
                continue
            keys[n] = validate_window_measurements(
                e, policy=policy, source=source, group=group, selections=selections
            )
            eligible.append(n)
        for check in (c for c in policy.required_check_ids if c.startswith("mad:")):
            if len({keys[n][check] for n in eligible}) > 1:
                raise ValueError(
                    "Incompatible source metric cohort/window/reference/unit/identity"
                )
            if eligible:
                assert policy.mad_multiplier is not None
                values = tuple(
                    next(r.value for r in evidences[n].records if r.check_id == check)
                    for n in eligible
                )
                if any(type(v) not in (int, float) for v in values):
                    raise ValueError("Incomplete source metric cohort")
                from typing import cast

                flags = mad_reviews(
                    cast(tuple[float | int, ...], values),
                    multiplier=policy.mad_multiplier,
                )
                mad_results.update(
                    {(n, check): flag for n, flag in zip(eligible, flags, strict=True)}
                )
    for index, e in enumerate(evidences):
        validate_policy_evidence(policy, e)
        if hard_evaluations and any(
            c.status == "FAIL" for c in hard_evaluations[index]
        ):
            continue
        for r in e.records:
            if r.check_id not in REVIEW_CHECK_IDS and not r.check_id.startswith("mad:"):
                continue
            if r.check_id.startswith("mad:"):
                if (index, r.check_id) not in mad_results:
                    continue  # Pinned FAIR excludes hard-FAIL members from review.
                review = mad_results[(index, r.check_id)]
            elif r.state == "missing":
                review = True
            elif r.state == "not_applicable":
                review = False
            elif r.check_id == "rmsd_drift":
                review = r.value is True
            elif r.check_id == "protein_edge_empty_window_fraction":
                if (
                    not isinstance(r.value, (int, float))
                    or isinstance(r.value, bool)
                    or not 0 <= r.value <= 1
                    or policy.empty_window_fraction is None
                ):
                    raise ValueError(
                        "Empty windows require explicit finite fraction and policy"
                    )
                review = Decimal(str(r.value)) > Decimal(
                    str(policy.empty_window_fraction)
                )
            else:
                raise ValueError("Unsupported review evidence")
            if (
                r.state in ("positive", "negative")
                and (r.state == "negative") != review
            ):
                raise ValueError("Contradictory review evidence state")
            results[index].append(
                QCCheckResult(
                    check_id=r.check_id,
                    severity="review",
                    status="REVIEW" if review else "PASS",
                    value=r.value,
                    evidence_role=r.evidence_role,
                    evidence_sha256=r.evidence_sha256,
                )
            )
    return tuple(
        tuple(sorted(rows, key=lambda r: policy.required_check_ids.index(r.check_id)))
        for rows in results
    )
