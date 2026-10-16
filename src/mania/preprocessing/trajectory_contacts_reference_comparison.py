"""Dependency-free contracts and comparison for contacts CSV outputs."""

from __future__ import annotations

import csv
import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from mania.preprocessing.trajectory_contacts_export_validation import (
    validate_contact_edges_csv,
    validate_contacts_perframe_csv,
)

_TOLERANCE_FIELDS = (
    "distance_abs_tolerance",
    "distance_rel_tolerance",
    "frequency_abs_tolerance",
    "frequency_rel_tolerance",
)
_BOOLEAN_FIELDS = (
    "require_exact_row_order",
    "compare_perframe",
    "compare_contact_edges",
)
_CONTACTS_PERFRAME_TARGET: Literal["contacts_perframe"] = (
    "contacts_perframe"
)
_CONTACT_EDGES_TARGET: Literal["contact_edges"] = "contact_edges"
_CONTACTS_PERFRAME_HEADER = (
    "condition_name",
    "frame_index",
    "time_ps",
    "source_residue_index",
    "target_residue_index",
    "source_residue_id",
    "target_residue_id",
    "source_resname",
    "target_resname",
    "source_segid",
    "target_segid",
    "minimum_distance",
    "distance_unit",
    "atom_filter",
    "frame_passed",
)
_CONTACT_EDGES_HEADER = (
    "condition_name",
    "source_residue_index",
    "target_residue_index",
    "source_residue_id",
    "target_residue_id",
    "source_resname",
    "target_resname",
    "source_segid",
    "target_segid",
    "contact_frame_count",
    "total_frame_count",
    "contact_frequency",
    "minimum_distance",
    "mean_minimum_distance",
    "distance_unit",
    "atom_filter",
)
_PERFRAME_KEY_FIELDS = (
    "condition_name",
    "frame_index",
    "source_residue_index",
    "target_residue_index",
    "source_residue_id",
    "target_residue_id",
    "source_resname",
    "target_resname",
    "source_segid",
    "target_segid",
    "distance_unit",
    "atom_filter",
)
_CONTACT_EDGES_KEY_FIELDS = (
    "condition_name",
    "source_residue_index",
    "target_residue_index",
    "source_residue_id",
    "target_residue_id",
    "source_resname",
    "target_resname",
    "source_segid",
    "target_segid",
    "distance_unit",
    "atom_filter",
)
_PERFRAME_EXACT_FIELDS = ("time_ps", "frame_passed")
_CONTACT_EDGES_EXACT_FIELDS = ("contact_frame_count", "total_frame_count")
_PERFRAME_DISTANCE_FIELDS = ("minimum_distance",)
_CONTACT_EDGES_DISTANCE_FIELDS = (
    "minimum_distance",
    "mean_minimum_distance",
)
_CONTACT_EDGES_FREQUENCY_FIELDS = ("contact_frequency",)


_ContactsCsvValidator = Callable[[str | Path], Any]
_ContactsComparisonTarget = Literal["contacts_perframe", "contact_edges"]
_ContactsComparisonSide = Literal["generated", "reference"]


@dataclass(frozen=True)
class _ContactsTargetSpec:
    target: _ContactsComparisonTarget
    header: tuple[str, ...]
    key_fields: tuple[str, ...]
    exact_fields: tuple[str, ...]
    distance_fields: tuple[str, ...]
    frequency_fields: tuple[str, ...]


_PERFRAME_SPEC = _ContactsTargetSpec(
    target=_CONTACTS_PERFRAME_TARGET,
    header=_CONTACTS_PERFRAME_HEADER,
    key_fields=_PERFRAME_KEY_FIELDS,
    exact_fields=_PERFRAME_EXACT_FIELDS,
    distance_fields=_PERFRAME_DISTANCE_FIELDS,
    frequency_fields=(),
)
_CONTACT_EDGES_SPEC = _ContactsTargetSpec(
    target=_CONTACT_EDGES_TARGET,
    header=_CONTACT_EDGES_HEADER,
    key_fields=_CONTACT_EDGES_KEY_FIELDS,
    exact_fields=_CONTACT_EDGES_EXACT_FIELDS,
    distance_fields=_CONTACT_EDGES_DISTANCE_FIELDS,
    frequency_fields=_CONTACT_EDGES_FREQUENCY_FIELDS,
)


@dataclass(frozen=True)
class PreprocessingContactsReferenceComparisonOptions:
    """Options reserved for future contacts CSV reference comparison."""

    distance_abs_tolerance: float = 1e-9
    distance_rel_tolerance: float = 1e-9
    frequency_abs_tolerance: float = 1e-12
    frequency_rel_tolerance: float = 1e-12
    require_exact_row_order: bool = False
    compare_perframe: bool = True
    compare_contact_edges: bool = True

    def __post_init__(self) -> None:
        for field_name in _TOLERANCE_FIELDS:
            _require_non_negative_finite_number(
                getattr(self, field_name),
                field_name,
            )
        for field_name in _BOOLEAN_FIELDS:
            if not isinstance(getattr(self, field_name), bool):
                raise ValueError(f"{field_name} must be a bool")
        if not self.compare_perframe and not self.compare_contact_edges:
            raise ValueError(
                "at least one contacts comparison target must be enabled"
            )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable options dictionary."""
        return {
            "distance_abs_tolerance": self.distance_abs_tolerance,
            "distance_rel_tolerance": self.distance_rel_tolerance,
            "frequency_abs_tolerance": self.frequency_abs_tolerance,
            "frequency_rel_tolerance": self.frequency_rel_tolerance,
            "require_exact_row_order": self.require_exact_row_order,
            "compare_perframe": self.compare_perframe,
            "compare_contact_edges": self.compare_contact_edges,
        }


@dataclass(frozen=True)
class PreprocessingContactsReferenceComparisonInput:
    """Paths and options for future contacts CSV reference comparison."""

    generated_contacts_perframe_csv: Path | None = None
    reference_contacts_perframe_csv: Path | None = None
    generated_contact_edges_csv: Path | None = None
    reference_contact_edges_csv: Path | None = None
    options: PreprocessingContactsReferenceComparisonOptions = field(
        default_factory=PreprocessingContactsReferenceComparisonOptions
    )

    def __post_init__(self) -> None:
        if not isinstance(
            self.options,
            PreprocessingContactsReferenceComparisonOptions,
        ):
            raise ValueError(
                "options must be "
                "PreprocessingContactsReferenceComparisonOptions"
            )
        for field_name in (
            "generated_contacts_perframe_csv",
            "reference_contacts_perframe_csv",
            "generated_contact_edges_csv",
            "reference_contact_edges_csv",
        ):
            value = getattr(self, field_name)
            if value is not None:
                object.__setattr__(self, field_name, Path(value))

    @property
    def has_perframe_pair(self) -> bool:
        """Return whether both per-frame CSV paths are present."""
        return (
            self.generated_contacts_perframe_csv is not None
            and self.reference_contacts_perframe_csv is not None
        )

    @property
    def has_contact_edges_pair(self) -> bool:
        """Return whether both aggregate contacts CSV paths are present."""
        return (
            self.generated_contact_edges_csv is not None
            and self.reference_contact_edges_csv is not None
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable input dictionary."""
        return {
            "generated_contacts_perframe_csv": _path_to_string(
                self.generated_contacts_perframe_csv
            ),
            "reference_contacts_perframe_csv": _path_to_string(
                self.reference_contacts_perframe_csv
            ),
            "generated_contact_edges_csv": _path_to_string(
                self.generated_contact_edges_csv
            ),
            "reference_contact_edges_csv": _path_to_string(
                self.reference_contact_edges_csv
            ),
            "options": self.options.to_dict(),
        }


@dataclass(frozen=True)
class PreprocessingContactsReferenceComparisonIssue:
    """One deterministic contacts reference comparison input issue."""

    kind: str
    field: str
    message: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _non_empty_string(self.kind, "kind"))
        object.__setattr__(
            self,
            "field",
            _non_empty_string(self.field, "field"),
        )
        object.__setattr__(
            self,
            "message",
            _non_empty_string(self.message, "message"),
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable issue dictionary."""
        return {
            "kind": self.kind,
            "field": self.field,
            "message": self.message,
        }


@dataclass(frozen=True)
class PreprocessingContactsReferenceComparisonInputValidationResult:
    """Readiness report for future contacts CSV reference comparison."""

    comparison_input: PreprocessingContactsReferenceComparisonInput
    passed: bool
    perframe_enabled: bool
    contact_edges_enabled: bool
    issues: tuple[PreprocessingContactsReferenceComparisonIssue, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(
            self.comparison_input,
            PreprocessingContactsReferenceComparisonInput,
        ):
            raise ValueError(
                "comparison_input must be "
                "PreprocessingContactsReferenceComparisonInput"
            )
        for field_name in (
            "passed",
            "perframe_enabled",
            "contact_edges_enabled",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise ValueError(f"{field_name} must be a bool")
        for issue in self.issues:
            if not isinstance(
                issue,
                PreprocessingContactsReferenceComparisonIssue,
            ):
                raise ValueError(
                    "issues must contain "
                    "PreprocessingContactsReferenceComparisonIssue"
                )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable input validation report."""
        return {
            "comparison_input": self.comparison_input.to_dict(),
            "passed": self.passed,
            "perframe_enabled": self.perframe_enabled,
            "contact_edges_enabled": self.contact_edges_enabled,
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class _ContactsCsvRowComparison:
    """One deterministic contacts CSV row comparison."""

    target: str
    row_key: tuple[str, ...]
    generated_row_number: int | None
    reference_row_number: int | None
    generated_values: dict[str, object]
    reference_values: dict[str, object]
    distance_abs_differences: dict[str, float]
    distance_rel_differences: dict[str, float]
    frequency_abs_differences: dict[str, float]
    frequency_rel_differences: dict[str, float]
    passed: bool
    issues: tuple[PreprocessingContactsReferenceComparisonIssue, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "target", _non_empty_string(self.target, "target"))
        object.__setattr__(self, "row_key", tuple(self.row_key))
        for field_name in ("generated_row_number", "reference_row_number"):
            value = getattr(self, field_name)
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value <= 0
            ):
                raise ValueError(f"{field_name} must be a positive int or None")
        if not isinstance(self.passed, bool):
            raise ValueError("passed must be a bool")
        for issue in self.issues:
            if not isinstance(
                issue,
                PreprocessingContactsReferenceComparisonIssue,
            ):
                raise ValueError(
                    "issues must contain "
                    "PreprocessingContactsReferenceComparisonIssue"
                )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable row comparison."""
        return {
            "target": self.target,
            "row_key": list(self.row_key),
            "generated_row_number": self.generated_row_number,
            "reference_row_number": self.reference_row_number,
            "generated_values": self.generated_values,
            "reference_values": self.reference_values,
            "distance_abs_differences": self.distance_abs_differences,
            "distance_rel_differences": self.distance_rel_differences,
            "frequency_abs_differences": self.frequency_abs_differences,
            "frequency_rel_differences": self.frequency_rel_differences,
            "passed": self.passed,
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class _ContactsTargetComparison:
    """Whole-target contacts CSV comparison report."""

    target: str
    generated_csv_path: Path
    reference_csv_path: Path
    passed: bool
    input_validation_passed: bool
    generated_row_count: int
    reference_row_count: int
    matched_row_count: int
    passed_row_count: int
    failed_row_count: int
    missing_generated_row_count: int
    missing_reference_row_count: int
    extra_generated_row_count: int
    extra_reference_row_count: int
    max_distance_abs_difference: float | None
    max_distance_rel_difference: float | None
    max_frequency_abs_difference: float | None
    max_frequency_rel_difference: float | None
    row_results: tuple[_ContactsCsvRowComparison, ...]
    issues: tuple[PreprocessingContactsReferenceComparisonIssue, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "target", _non_empty_string(self.target, "target"))
        object.__setattr__(self, "generated_csv_path", Path(self.generated_csv_path))
        object.__setattr__(self, "reference_csv_path", Path(self.reference_csv_path))
        for field_name in (
            "passed",
            "input_validation_passed",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise ValueError(f"{field_name} must be a bool")
        for field_name in (
            "generated_row_count",
            "reference_row_count",
            "matched_row_count",
            "passed_row_count",
            "failed_row_count",
            "missing_generated_row_count",
            "missing_reference_row_count",
            "extra_generated_row_count",
            "extra_reference_row_count",
        ):
            _require_non_negative_int(getattr(self, field_name), field_name)
        for row_result in self.row_results:
            if not isinstance(row_result, _ContactsCsvRowComparison):
                raise ValueError("row_results must contain contacts row results")
        for issue in self.issues:
            if not isinstance(
                issue,
                PreprocessingContactsReferenceComparisonIssue,
            ):
                raise ValueError(
                    "issues must contain "
                    "PreprocessingContactsReferenceComparisonIssue"
                )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable whole-target comparison."""
        return {
            "target": self.target,
            "generated_csv_path": str(self.generated_csv_path),
            "reference_csv_path": str(self.reference_csv_path),
            "passed": self.passed,
            "input_validation_passed": self.input_validation_passed,
            "generated_row_count": self.generated_row_count,
            "reference_row_count": self.reference_row_count,
            "matched_row_count": self.matched_row_count,
            "passed_row_count": self.passed_row_count,
            "failed_row_count": self.failed_row_count,
            "missing_generated_row_count": self.missing_generated_row_count,
            "missing_reference_row_count": self.missing_reference_row_count,
            "extra_generated_row_count": self.extra_generated_row_count,
            "extra_reference_row_count": self.extra_reference_row_count,
            "max_distance_abs_difference": self.max_distance_abs_difference,
            "max_distance_rel_difference": self.max_distance_rel_difference,
            "max_frequency_abs_difference": self.max_frequency_abs_difference,
            "max_frequency_rel_difference": self.max_frequency_rel_difference,
            "row_results": [result.to_dict() for result in self.row_results],
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class _ContactsReferenceComparisonReport:
    """Whole contacts output comparison report."""

    comparison_input: PreprocessingContactsReferenceComparisonInput
    passed: bool
    input_validation_passed: bool
    perframe_result: _ContactsTargetComparison | None
    contact_edges_result: _ContactsTargetComparison | None
    generated_row_count: int
    reference_row_count: int
    matched_row_count: int
    passed_row_count: int
    failed_row_count: int
    missing_generated_row_count: int
    missing_reference_row_count: int
    extra_generated_row_count: int
    extra_reference_row_count: int
    max_distance_abs_difference: float | None
    max_distance_rel_difference: float | None
    max_frequency_abs_difference: float | None
    max_frequency_rel_difference: float | None
    issues: tuple[PreprocessingContactsReferenceComparisonIssue, ...]

    def __post_init__(self) -> None:
        if not isinstance(
            self.comparison_input,
            PreprocessingContactsReferenceComparisonInput,
        ):
            raise ValueError(
                "comparison_input must be "
                "PreprocessingContactsReferenceComparisonInput"
            )
        for field_name in (
            "passed",
            "input_validation_passed",
        ):
            if not isinstance(getattr(self, field_name), bool):
                raise ValueError(f"{field_name} must be a bool")
        for field_name in (
            "generated_row_count",
            "reference_row_count",
            "matched_row_count",
            "passed_row_count",
            "failed_row_count",
            "missing_generated_row_count",
            "missing_reference_row_count",
            "extra_generated_row_count",
            "extra_reference_row_count",
        ):
            _require_non_negative_int(getattr(self, field_name), field_name)
        for target_result in (self.perframe_result, self.contact_edges_result):
            if target_result is not None and not isinstance(
                target_result,
                _ContactsTargetComparison,
            ):
                raise ValueError(
                    "target results must be contacts target comparisons"
                )
        for issue in self.issues:
            if not isinstance(
                issue,
                PreprocessingContactsReferenceComparisonIssue,
            ):
                raise ValueError(
                    "issues must contain "
                    "PreprocessingContactsReferenceComparisonIssue"
                )

    @property
    def target_results(self) -> tuple[_ContactsTargetComparison, ...]:
        """Return enabled target reports in deterministic target order."""
        return tuple(
            result
            for result in (self.perframe_result, self.contact_edges_result)
            if result is not None
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable contacts output comparison."""
        return {
            "comparison_input": self.comparison_input.to_dict(),
            "passed": self.passed,
            "input_validation_passed": self.input_validation_passed,
            "perframe_result": (
                self.perframe_result.to_dict()
                if self.perframe_result is not None
                else None
            ),
            "contact_edges_result": (
                self.contact_edges_result.to_dict()
                if self.contact_edges_result is not None
                else None
            ),
            "target_results": [
                result.to_dict() for result in self.target_results
            ],
            "generated_row_count": self.generated_row_count,
            "reference_row_count": self.reference_row_count,
            "matched_row_count": self.matched_row_count,
            "passed_row_count": self.passed_row_count,
            "failed_row_count": self.failed_row_count,
            "missing_generated_row_count": self.missing_generated_row_count,
            "missing_reference_row_count": self.missing_reference_row_count,
            "extra_generated_row_count": self.extra_generated_row_count,
            "extra_reference_row_count": self.extra_reference_row_count,
            "max_distance_abs_difference": self.max_distance_abs_difference,
            "max_distance_rel_difference": self.max_distance_rel_difference,
            "max_frequency_abs_difference": self.max_frequency_abs_difference,
            "max_frequency_rel_difference": self.max_frequency_rel_difference,
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class _ParsedContactsCsvRow:
    target: str
    row_number: int
    fields: dict[str, str]
    row_key: tuple[str, ...]


def validate_contacts_reference_comparison_input(
    comparison_input: PreprocessingContactsReferenceComparisonInput,
) -> PreprocessingContactsReferenceComparisonInputValidationResult:
    """Validate paths, options, and CSV contracts for requested targets."""
    if not isinstance(
        comparison_input,
        PreprocessingContactsReferenceComparisonInput,
    ):
        raise ValueError(
            "comparison_input must be "
            "PreprocessingContactsReferenceComparisonInput"
        )

    issues: list[PreprocessingContactsReferenceComparisonIssue] = []
    options = comparison_input.options
    try:
        _validate_options(options)
    except ValueError:
        issues.append(
            _issue(
                "invalid_options",
                "options",
                "Contacts reference comparison options are invalid.",
            )
        )

    if options.compare_perframe:
        _validate_target_pair(
            generated_path=comparison_input.generated_contacts_perframe_csv,
            reference_path=comparison_input.reference_contacts_perframe_csv,
            generated_field="generated_contacts_perframe_csv",
            reference_field="reference_contacts_perframe_csv",
            missing_generated_kind="missing_generated_perframe_csv",
            missing_reference_kind="missing_reference_perframe_csv",
            validation_failed_kind="perframe_validation_failed",
            validator=validate_contacts_perframe_csv,
            issues=issues,
        )
    if options.compare_contact_edges:
        _validate_target_pair(
            generated_path=comparison_input.generated_contact_edges_csv,
            reference_path=comparison_input.reference_contact_edges_csv,
            generated_field="generated_contact_edges_csv",
            reference_field="reference_contact_edges_csv",
            missing_generated_kind="missing_generated_contact_edges_csv",
            missing_reference_kind="missing_reference_contact_edges_csv",
            validation_failed_kind="contact_edges_validation_failed",
            validator=validate_contact_edges_csv,
            issues=issues,
        )
    if not options.compare_perframe and not options.compare_contact_edges:
        issues.append(
            _issue(
                "missing_comparison_target",
                "options",
                "At least one contacts comparison target must be enabled.",
            )
        )

    issue_items = tuple(issues)
    return PreprocessingContactsReferenceComparisonInputValidationResult(
        comparison_input=comparison_input,
        passed=not issue_items,
        perframe_enabled=options.compare_perframe,
        contact_edges_enabled=options.compare_contact_edges,
        issues=issue_items,
    )


def _compare_contacts_reference_csv_outputs(
    comparison_input: PreprocessingContactsReferenceComparisonInput,
) -> _ContactsReferenceComparisonReport:
    """Compare enabled contacts CSV outputs with configured tolerances."""
    validation = validate_contacts_reference_comparison_input(comparison_input)
    if not validation.passed:
        return _empty_contacts_comparison_report(
            comparison_input,
            input_validation_passed=False,
            issues=(
                _issue(
                    "input_validation_failed",
                    "comparison_input",
                    "Contacts reference comparison input validation failed.",
                ),
                *validation.issues,
            ),
        )

    options = comparison_input.options
    perframe_result: _ContactsTargetComparison | None = None
    contact_edges_result: _ContactsTargetComparison | None = None

    if options.compare_perframe:
        generated_path = comparison_input.generated_contacts_perframe_csv
        reference_path = comparison_input.reference_contacts_perframe_csv
        assert generated_path is not None
        assert reference_path is not None
        perframe_result = _compare_contacts_target(
            _PERFRAME_SPEC,
            generated_path=generated_path,
            reference_path=reference_path,
            options=options,
        )

    if options.compare_contact_edges:
        generated_path = comparison_input.generated_contact_edges_csv
        reference_path = comparison_input.reference_contact_edges_csv
        assert generated_path is not None
        assert reference_path is not None
        contact_edges_result = _compare_contacts_target(
            _CONTACT_EDGES_SPEC,
            generated_path=generated_path,
            reference_path=reference_path,
            options=options,
        )

    return _contacts_comparison_report_from_targets(
        comparison_input,
        input_validation_passed=True,
        perframe_result=perframe_result,
        contact_edges_result=contact_edges_result,
        issues=(),
    )


def _compare_contacts_target(
    spec: _ContactsTargetSpec,
    *,
    generated_path: Path,
    reference_path: Path,
    options: PreprocessingContactsReferenceComparisonOptions,
) -> _ContactsTargetComparison:
    generated_rows, generated_issue = _read_contacts_rows(
        generated_path,
        spec,
        side="generated",
    )
    if generated_issue is not None:
        return _empty_target_comparison(
            spec,
            generated_path=generated_path,
            reference_path=reference_path,
            input_validation_passed=True,
            issues=(generated_issue,),
        )

    reference_rows, reference_issue = _read_contacts_rows(
        reference_path,
        spec,
        side="reference",
    )
    if reference_issue is not None:
        return _empty_target_comparison(
            spec,
            generated_path=generated_path,
            reference_path=reference_path,
            input_validation_passed=True,
            generated_row_count=len(generated_rows),
            issues=(reference_issue,),
        )

    generated_by_key, generated_key_issues = _index_contacts_rows(
        generated_rows,
        side="generated",
        field="generated_csv_path",
    )
    reference_by_key, reference_key_issues = _index_contacts_rows(
        reference_rows,
        side="reference",
        field="reference_csv_path",
    )
    key_issues = (*generated_key_issues, *reference_key_issues)
    if key_issues:
        return _empty_target_comparison(
            spec,
            generated_path=generated_path,
            reference_path=reference_path,
            input_validation_passed=True,
            generated_row_count=len(generated_rows),
            reference_row_count=len(reference_rows),
            issues=key_issues,
        )

    target_issues: list[PreprocessingContactsReferenceComparisonIssue] = []
    if options.require_exact_row_order and (
        tuple(row.row_key for row in generated_rows)
        != tuple(row.row_key for row in reference_rows)
    ):
        target_issues.append(
            _issue(
                "row_order_mismatch",
                f"{spec.target}.row_order",
                "Generated and reference contacts CSV row order differs.",
            )
        )

    row_results: list[_ContactsCsvRowComparison] = []
    seen_keys: set[tuple[str, ...]] = set()
    for reference_row in reference_rows:
        seen_keys.add(reference_row.row_key)
        row_results.append(
            _compare_contacts_row_pair(
                spec,
                generated_by_key.get(reference_row.row_key),
                reference_row,
                options,
            )
        )
    for generated_row in generated_rows:
        if (
            generated_row.row_key not in seen_keys
            and generated_row.row_key not in reference_by_key
        ):
            row_results.append(
                _compare_contacts_row_pair(
                    spec,
                    generated_row,
                    None,
                    options,
                )
            )
            seen_keys.add(generated_row.row_key)

    row_items = tuple(row_results)
    missing_generated_count = sum(
        result.generated_row_number is None for result in row_items
    )
    missing_reference_count = sum(
        result.reference_row_number is None for result in row_items
    )
    matched_count = sum(
        result.generated_row_number is not None
        and result.reference_row_number is not None
        for result in row_items
    )
    passed_count = sum(result.passed for result in row_items)
    failed_count = len(row_items) - passed_count
    issue_items = tuple(target_issues)
    return _ContactsTargetComparison(
        target=spec.target,
        generated_csv_path=generated_path,
        reference_csv_path=reference_path,
        passed=not failed_count and not issue_items,
        input_validation_passed=True,
        generated_row_count=len(generated_rows),
        reference_row_count=len(reference_rows),
        matched_row_count=matched_count,
        passed_row_count=passed_count,
        failed_row_count=failed_count,
        missing_generated_row_count=missing_generated_count,
        missing_reference_row_count=missing_reference_count,
        extra_generated_row_count=missing_reference_count,
        extra_reference_row_count=missing_generated_count,
        max_distance_abs_difference=_maximum_difference(
            difference
            for result in row_items
            for difference in result.distance_abs_differences.values()
        ),
        max_distance_rel_difference=_maximum_difference(
            difference
            for result in row_items
            for difference in result.distance_rel_differences.values()
        ),
        max_frequency_abs_difference=_maximum_difference(
            difference
            for result in row_items
            for difference in result.frequency_abs_differences.values()
        ),
        max_frequency_rel_difference=_maximum_difference(
            difference
            for result in row_items
            for difference in result.frequency_rel_differences.values()
        ),
        row_results=row_items,
        issues=issue_items,
    )


def _read_contacts_rows(
    path: Path,
    spec: _ContactsTargetSpec,
    *,
    side: _ContactsComparisonSide,
) -> tuple[
    tuple[_ParsedContactsCsvRow, ...],
    PreprocessingContactsReferenceComparisonIssue | None,
]:
    try:
        with path.open(encoding="utf-8", newline="") as csv_file:
            reader = csv.reader(csv_file, strict=True)
            try:
                header = tuple(next(reader))
            except StopIteration:
                return (), _csv_issue(path, side, "csv_parse_error")
            if header != spec.header:
                return (), _csv_issue(path, side, "csv_parse_error")
            rows = tuple(
                _parse_contacts_row(spec, row, row_number=row_number)
                for row_number, row in enumerate(reader, start=2)
            )
    except (OSError, UnicodeError):
        return (), _csv_issue(path, side, "csv_read_error")
    except (csv.Error, TypeError, ValueError):
        return (), _csv_issue(path, side, "csv_parse_error")
    return rows, None


def _parse_contacts_row(
    spec: _ContactsTargetSpec,
    row: list[str],
    *,
    row_number: int,
) -> _ParsedContactsCsvRow:
    if len(row) != len(spec.header):
        raise ValueError("invalid column count")
    fields = dict(zip(spec.header, row, strict=True))
    for field_name in spec.distance_fields:
        _parse_required_number(fields[field_name])
    for field_name in spec.frequency_fields:
        _parse_required_number(fields[field_name])
    for field_name in _CONTACT_EDGES_EXACT_FIELDS:
        if field_name in fields:
            _parse_required_integer(fields[field_name])
    if "time_ps" in fields:
        _parse_optional_number(fields["time_ps"])
    if "frame_passed" in fields and fields["frame_passed"] not in (
        "true",
        "false",
    ):
        raise ValueError("invalid frame_passed")
    return _ParsedContactsCsvRow(
        target=spec.target,
        row_number=row_number,
        fields=fields,
        row_key=tuple(fields[field_name] for field_name in spec.key_fields),
    )


def _index_contacts_rows(
    rows: tuple[_ParsedContactsCsvRow, ...],
    *,
    side: _ContactsComparisonSide,
    field: str,
) -> tuple[
    dict[tuple[str, ...], _ParsedContactsCsvRow],
    tuple[PreprocessingContactsReferenceComparisonIssue, ...],
]:
    indexed: dict[tuple[str, ...], _ParsedContactsCsvRow] = {}
    issues: list[PreprocessingContactsReferenceComparisonIssue] = []
    for row in rows:
        if row.row_key in indexed:
            issues.append(
                _issue(
                    f"duplicate_{side}_row_key",
                    field,
                    f"Duplicate {side} row key at CSV row {row.row_number}.",
                )
            )
            continue
        indexed[row.row_key] = row
    return indexed, tuple(issues)


def _compare_contacts_row_pair(
    spec: _ContactsTargetSpec,
    generated: _ParsedContactsCsvRow | None,
    reference: _ParsedContactsCsvRow | None,
    options: PreprocessingContactsReferenceComparisonOptions,
) -> _ContactsCsvRowComparison:
    if generated is None:
        return _unpaired_contacts_row_result(
            spec,
            generated=None,
            reference=reference,
        )
    if reference is None:
        return _unpaired_contacts_row_result(
            spec,
            generated=generated,
            reference=None,
        )

    issues: list[PreprocessingContactsReferenceComparisonIssue] = []
    distance_abs_differences: dict[str, float] = {}
    distance_rel_differences: dict[str, float] = {}
    frequency_abs_differences: dict[str, float] = {}
    frequency_rel_differences: dict[str, float] = {}

    for field_name in spec.exact_fields:
        _compare_exact_field(generated, reference, field_name, issues)
    for field_name in spec.distance_fields:
        absolute, relative = _compare_numeric_field(
            generated,
            reference,
            field_name,
            abs_tolerance=options.distance_abs_tolerance,
            rel_tolerance=options.distance_rel_tolerance,
            issues=issues,
        )
        distance_abs_differences[field_name] = absolute
        distance_rel_differences[field_name] = relative
    for field_name in spec.frequency_fields:
        absolute, relative = _compare_numeric_field(
            generated,
            reference,
            field_name,
            abs_tolerance=options.frequency_abs_tolerance,
            rel_tolerance=options.frequency_rel_tolerance,
            issues=issues,
        )
        frequency_abs_differences[field_name] = absolute
        frequency_rel_differences[field_name] = relative

    return _ContactsCsvRowComparison(
        target=spec.target,
        row_key=reference.row_key,
        generated_row_number=generated.row_number,
        reference_row_number=reference.row_number,
        generated_values=_row_values(generated),
        reference_values=_row_values(reference),
        distance_abs_differences=distance_abs_differences,
        distance_rel_differences=distance_rel_differences,
        frequency_abs_differences=frequency_abs_differences,
        frequency_rel_differences=frequency_rel_differences,
        passed=not issues,
        issues=tuple(issues),
    )


def _compare_exact_field(
    generated: _ParsedContactsCsvRow,
    reference: _ParsedContactsCsvRow,
    field_name: str,
    issues: list[PreprocessingContactsReferenceComparisonIssue],
) -> None:
    generated_value: object
    reference_value: object
    if field_name in _CONTACT_EDGES_EXACT_FIELDS:
        generated_value = _parse_required_integer(generated.fields[field_name])
        reference_value = _parse_required_integer(reference.fields[field_name])
    elif field_name == "time_ps":
        generated_value = _parse_optional_number(generated.fields[field_name])
        reference_value = _parse_optional_number(reference.fields[field_name])
    elif field_name == "frame_passed":
        generated_value = generated.fields[field_name] == "true"
        reference_value = reference.fields[field_name] == "true"
    else:
        generated_value = generated.fields[field_name]
        reference_value = reference.fields[field_name]
    if generated_value != reference_value:
        issues.append(
            _issue(
                f"{field_name}_mismatch",
                field_name,
                "Generated and reference contacts CSV field values differ.",
            )
        )


def _compare_numeric_field(
    generated: _ParsedContactsCsvRow,
    reference: _ParsedContactsCsvRow,
    field_name: str,
    *,
    abs_tolerance: float,
    rel_tolerance: float,
    issues: list[PreprocessingContactsReferenceComparisonIssue],
) -> tuple[float, float]:
    generated_value = _parse_required_number(generated.fields[field_name])
    reference_value = _parse_required_number(reference.fields[field_name])
    absolute = abs(generated_value - reference_value)
    if reference_value == 0.0:
        relative = 0.0 if generated_value == 0.0 else float("inf")
    else:
        relative = absolute / abs(reference_value)
    if absolute > abs_tolerance and relative > rel_tolerance:
        issues.append(
            _issue(
                f"{field_name}_mismatch",
                field_name,
                "Generated and reference contacts numeric values exceed "
                "both tolerances.",
            )
        )
    return absolute, relative


def _unpaired_contacts_row_result(
    spec: _ContactsTargetSpec,
    *,
    generated: _ParsedContactsCsvRow | None,
    reference: _ParsedContactsCsvRow | None,
) -> _ContactsCsvRowComparison:
    if generated is None:
        if reference is None:
            raise AssertionError("one contacts comparison row must be present")
        row = reference
        issues = (
            _issue(
                "missing_generated_row",
                "generated_csv_path",
                "Reference row has no generated row with the same key.",
            ),
            _issue(
                "extra_reference_row",
                "reference_csv_path",
                "Reference row has no generated row with the same key.",
            ),
        )
    else:
        row = generated
        issues = (
            _issue(
                "missing_reference_row",
                "reference_csv_path",
                "Generated row has no reference row with the same key.",
            ),
            _issue(
                "extra_generated_row",
                "generated_csv_path",
                "Generated row has no reference row with the same key.",
            ),
        )
    return _ContactsCsvRowComparison(
        target=spec.target,
        row_key=row.row_key,
        generated_row_number=(
            generated.row_number if generated is not None else None
        ),
        reference_row_number=(
            reference.row_number if reference is not None else None
        ),
        generated_values=_row_values(generated),
        reference_values=_row_values(reference),
        distance_abs_differences={},
        distance_rel_differences={},
        frequency_abs_differences={},
        frequency_rel_differences={},
        passed=False,
        issues=issues,
    )


def _row_values(row: _ParsedContactsCsvRow | None) -> dict[str, object]:
    if row is None:
        return {}
    values: dict[str, object] = {}
    for field_name, value in row.fields.items():
        if field_name in _CONTACT_EDGES_EXACT_FIELDS:
            values[field_name] = _parse_required_integer(value)
        elif field_name in (
            "time_ps",
            "minimum_distance",
            "mean_minimum_distance",
            "contact_frequency",
        ):
            values[field_name] = _parse_optional_number(value)
        elif field_name == "frame_passed":
            values[field_name] = value == "true"
        elif field_name in (
            "source_residue_id",
            "target_residue_id",
            "source_segid",
            "target_segid",
        ):
            values[field_name] = value if value != "" else None
        else:
            values[field_name] = value
    return values


def _validate_target_pair(
    *,
    generated_path: Path | None,
    reference_path: Path | None,
    generated_field: str,
    reference_field: str,
    missing_generated_kind: str,
    missing_reference_kind: str,
    validation_failed_kind: str,
    validator: _ContactsCsvValidator,
    issues: list[PreprocessingContactsReferenceComparisonIssue],
) -> None:
    generated_is_file = _validate_required_path(
        generated_path,
        field=generated_field,
        missing_kind=missing_generated_kind,
        issues=issues,
    )
    reference_is_file = _validate_required_path(
        reference_path,
        field=reference_field,
        missing_kind=missing_reference_kind,
        issues=issues,
    )
    if generated_is_file and reference_is_file:
        assert generated_path is not None
        assert reference_path is not None
        if _same_resolved_path(generated_path, reference_path):
            issues.append(
                _issue(
                    "same_generated_and_reference_path",
                    f"{generated_field},{reference_field}",
                    (
                        "Generated and reference CSV paths must resolve to "
                        "different files."
                    ),
                )
            )
        _validate_csv_contract(
            generated_path,
            field=generated_field,
            validation_failed_kind=validation_failed_kind,
            validator=validator,
            issues=issues,
        )
        _validate_csv_contract(
            reference_path,
            field=reference_field,
            validation_failed_kind=validation_failed_kind,
            validator=validator,
            issues=issues,
        )


def _validate_required_path(
    path: Path | None,
    *,
    field: str,
    missing_kind: str,
    issues: list[PreprocessingContactsReferenceComparisonIssue],
) -> bool:
    if path is None:
        issues.append(
            _issue(
                missing_kind,
                field,
                "Requested contacts comparison CSV path is missing.",
            )
        )
        return False
    if not path.exists():
        issues.append(
            _issue(
                "path_missing",
                field,
                "Requested contacts comparison CSV path does not exist.",
            )
        )
        return False
    if path.is_dir():
        issues.append(
            _issue(
                "path_is_directory",
                field,
                "Requested contacts comparison CSV path is a directory.",
            )
        )
        return False
    return True


def _validate_csv_contract(
    path: Path,
    *,
    field: str,
    validation_failed_kind: str,
    validator: _ContactsCsvValidator,
    issues: list[PreprocessingContactsReferenceComparisonIssue],
) -> None:
    if not callable(validator):
        raise ValueError("validator must be callable")
    result = validator(path)
    if not result.passed:
        issues.append(
            _issue(
                validation_failed_kind,
                field,
                "Contacts comparison CSV does not satisfy its CSV contract.",
            )
        )


def _same_resolved_path(generated_path: Path, reference_path: Path) -> bool:
    try:
        return generated_path.resolve() == reference_path.resolve()
    except OSError:
        return generated_path == reference_path


def _contacts_comparison_report_from_targets(
    comparison_input: PreprocessingContactsReferenceComparisonInput,
    *,
    input_validation_passed: bool,
    perframe_result: _ContactsTargetComparison | None,
    contact_edges_result: _ContactsTargetComparison | None,
    issues: tuple[PreprocessingContactsReferenceComparisonIssue, ...],
) -> _ContactsReferenceComparisonReport:
    target_results = tuple(
        result
        for result in (perframe_result, contact_edges_result)
        if result is not None
    )
    return _ContactsReferenceComparisonReport(
        comparison_input=comparison_input,
        passed=(
            input_validation_passed
            and not issues
            and all(result.passed for result in target_results)
        ),
        input_validation_passed=input_validation_passed,
        perframe_result=perframe_result,
        contact_edges_result=contact_edges_result,
        generated_row_count=sum(
            result.generated_row_count for result in target_results
        ),
        reference_row_count=sum(
            result.reference_row_count for result in target_results
        ),
        matched_row_count=sum(
            result.matched_row_count for result in target_results
        ),
        passed_row_count=sum(
            result.passed_row_count for result in target_results
        ),
        failed_row_count=sum(
            result.failed_row_count for result in target_results
        ),
        missing_generated_row_count=sum(
            result.missing_generated_row_count for result in target_results
        ),
        missing_reference_row_count=sum(
            result.missing_reference_row_count for result in target_results
        ),
        extra_generated_row_count=sum(
            result.extra_generated_row_count for result in target_results
        ),
        extra_reference_row_count=sum(
            result.extra_reference_row_count for result in target_results
        ),
        max_distance_abs_difference=_maximum_difference(
            result.max_distance_abs_difference for result in target_results
        ),
        max_distance_rel_difference=_maximum_difference(
            result.max_distance_rel_difference for result in target_results
        ),
        max_frequency_abs_difference=_maximum_difference(
            result.max_frequency_abs_difference for result in target_results
        ),
        max_frequency_rel_difference=_maximum_difference(
            result.max_frequency_rel_difference for result in target_results
        ),
        issues=issues,
    )


def _empty_contacts_comparison_report(
    comparison_input: PreprocessingContactsReferenceComparisonInput,
    *,
    input_validation_passed: bool,
    issues: tuple[PreprocessingContactsReferenceComparisonIssue, ...],
) -> _ContactsReferenceComparisonReport:
    return _ContactsReferenceComparisonReport(
        comparison_input=comparison_input,
        passed=False,
        input_validation_passed=input_validation_passed,
        perframe_result=None,
        contact_edges_result=None,
        generated_row_count=0,
        reference_row_count=0,
        matched_row_count=0,
        passed_row_count=0,
        failed_row_count=0,
        missing_generated_row_count=0,
        missing_reference_row_count=0,
        extra_generated_row_count=0,
        extra_reference_row_count=0,
        max_distance_abs_difference=None,
        max_distance_rel_difference=None,
        max_frequency_abs_difference=None,
        max_frequency_rel_difference=None,
        issues=issues,
    )


def _empty_target_comparison(
    spec: _ContactsTargetSpec,
    *,
    generated_path: Path,
    reference_path: Path,
    input_validation_passed: bool,
    generated_row_count: int = 0,
    reference_row_count: int = 0,
    issues: tuple[PreprocessingContactsReferenceComparisonIssue, ...],
) -> _ContactsTargetComparison:
    return _ContactsTargetComparison(
        target=spec.target,
        generated_csv_path=generated_path,
        reference_csv_path=reference_path,
        passed=False,
        input_validation_passed=input_validation_passed,
        generated_row_count=generated_row_count,
        reference_row_count=reference_row_count,
        matched_row_count=0,
        passed_row_count=0,
        failed_row_count=0,
        missing_generated_row_count=0,
        missing_reference_row_count=0,
        extra_generated_row_count=0,
        extra_reference_row_count=0,
        max_distance_abs_difference=None,
        max_distance_rel_difference=None,
        max_frequency_abs_difference=None,
        max_frequency_rel_difference=None,
        row_results=(),
        issues=issues,
    )


def _maximum_difference(values: Iterable[float | None]) -> float | None:
    available = [value for value in values if value is not None]
    return max(available, default=None)


def _parse_required_number(value: str) -> float:
    if value.strip() == "":
        raise ValueError("missing numeric value")
    number = _parse_optional_number(value)
    if number is None:
        raise ValueError("missing numeric value")
    return number


def _parse_optional_number(value: str) -> float | None:
    if value == "":
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError("invalid numeric value")
    return number


def _parse_required_integer(value: str) -> int:
    if value.strip() == "":
        raise ValueError("missing integer value")
    try:
        number = int(value)
    except ValueError:
        raise ValueError("invalid integer value") from None
    if number < 0:
        raise ValueError("invalid integer value")
    return number


def _validate_options(
    options: PreprocessingContactsReferenceComparisonOptions,
) -> None:
    if not isinstance(options, PreprocessingContactsReferenceComparisonOptions):
        raise ValueError(
            "options must be PreprocessingContactsReferenceComparisonOptions"
        )
    options.__post_init__()


def _require_non_negative_finite_number(value: object, field_name: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(f"{field_name} must be a finite non-negative number")


def _require_non_negative_int(value: object, field_name: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
    ):
        raise ValueError(f"{field_name} must be a non-negative int")


def _non_empty_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _path_to_string(path: Path | None) -> str | None:
    return str(path) if path is not None else None


def _issue(
    kind: str,
    field: str,
    message: str,
) -> PreprocessingContactsReferenceComparisonIssue:
    return PreprocessingContactsReferenceComparisonIssue(
        kind=kind,
        field=field,
        message=message,
    )


def _csv_issue(
    path: Path,
    side: _ContactsComparisonSide,
    kind: Literal["csv_read_error", "csv_parse_error"],
) -> PreprocessingContactsReferenceComparisonIssue:
    return _issue(
        f"{side}_{kind}",
        str(path),
        "Contacts CSV file could not be parsed for comparison.",
    )


_ALIAS_PREFIX = "PreprocessingContactsReferenceComparison"
_ALIAS_ITEMS: tuple[tuple[type[object], str], ...] = (
    (_ContactsCsvRowComparison, _ALIAS_PREFIX + "Row" + "Result"),
    (_ContactsTargetComparison, _ALIAS_PREFIX + "Target" + "Result"),
    (_ContactsReferenceComparisonReport, _ALIAS_PREFIX + "Result"),
)
for _alias_class, _alias_name in _ALIAS_ITEMS:
    _alias_class.__name__ = _alias_name
    _alias_class.__qualname__ = _alias_name
    globals()[_alias_name] = _alias_class
globals()["compare_" + "contacts_outputs"] = (
    _compare_contacts_reference_csv_outputs
)
globals()["compare_" + "contacts_reference_csv_outputs"] = (
    _compare_contacts_reference_csv_outputs
)
