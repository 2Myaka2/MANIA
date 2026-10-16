"""Input contract for future preprocessing graph reference comparison."""

from __future__ import annotations

import csv
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from io import StringIO
from json import JSONDecodeError
from json import dumps as _json_dumps
from json import loads as _json_loads
from pathlib import Path
from typing import cast

from mania.constants import EDGE_COLUMNS, NODE_COLUMNS
from mania.preprocessing.trajectory_graph_export import (
    PreprocessingGraphExportBundleIssue,
    PreprocessingGraphExportBundleResult,
    build_preprocessing_graph_export_bundle,
)

_CURRENT_REFERENCE_SEMANTICS = "MANIA_analysis_v1_2"
_BOOLEAN_FIELDS = (
    "require_matching_condition",
    "require_matching_schema_version",
    "compare_nodes",
    "compare_edges",
    "compare_graph_json",
)
_PATH_FIELDS = (
    "generated_nodes_csv_path",
    "generated_edges_csv_path",
    "generated_graph_json_path",
    "reference_nodes_csv_path",
    "reference_edges_csv_path",
    "reference_graph_json_path",
)
_GENERATED_ARTIFACT_FIELDS = {
    "nodes_csv": "generated_nodes_csv_path",
    "edges_csv": "generated_edges_csv_path",
    "graph_json": "generated_graph_json_path",
}
_REFERENCE_ARTIFACT_FIELDS = {
    "nodes_csv": "reference_nodes_csv_path",
    "edges_csv": "reference_edges_csv_path",
    "graph_json": "reference_graph_json_path",
}
_TARGET_ORDER = ("nodes_csv", "edges_csv", "graph_json")
_GRAPH_JSON_TOP_LEVEL_FIELDS = (
    "condition",
    "n_nodes",
    "n_edges",
    "directed",
    "schema_version",
)
_PASSTHROUGH_BUNDLE_ISSUES = frozenset(
    {
        "invalid_path",
        "path_missing",
        "path_is_directory",
    }
)


@dataclass(frozen=True)
class PreprocessingGraphReferenceComparisonOptions:
    """Options for future generated-vs-reference graph comparison."""

    reference_semantics: str = _CURRENT_REFERENCE_SEMANTICS
    condition: str | None = None
    require_matching_condition: bool = True
    require_matching_schema_version: bool = True
    compare_nodes: bool = True
    compare_edges: bool = True
    compare_graph_json: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "reference_semantics",
            _non_empty_string(self.reference_semantics, "reference_semantics"),
        )
        object.__setattr__(
            self,
            "condition",
            _optional_non_empty_string(self.condition, "condition"),
        )
        for field_name in _BOOLEAN_FIELDS:
            if not isinstance(getattr(self, field_name), bool):
                raise ValueError(f"{field_name} must be a bool")

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe options dictionary."""
        return {
            "reference_semantics": self.reference_semantics,
            "condition": self.condition,
            "require_matching_condition": self.require_matching_condition,
            "require_matching_schema_version": (
                self.require_matching_schema_version
            ),
            "compare_nodes": self.compare_nodes,
            "compare_edges": self.compare_edges,
            "compare_graph_json": self.compare_graph_json,
        }


@dataclass(frozen=True)
class PreprocessingGraphReferenceComparisonInput:
    """Explicit generated/reference graph artifact paths."""

    generated_nodes_csv_path: Path
    generated_edges_csv_path: Path
    generated_graph_json_path: Path
    reference_nodes_csv_path: Path
    reference_edges_csv_path: Path
    reference_graph_json_path: Path
    options: PreprocessingGraphReferenceComparisonOptions = field(
        default_factory=PreprocessingGraphReferenceComparisonOptions
    )

    def __post_init__(self) -> None:
        for field_name in _PATH_FIELDS:
            if not isinstance(getattr(self, field_name), Path):
                raise ValueError(f"{field_name} must be Path")
        if not isinstance(
            self.options,
            PreprocessingGraphReferenceComparisonOptions,
        ):
            raise ValueError(
                "options must be "
                "PreprocessingGraphReferenceComparisonOptions"
            )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe input dictionary."""
        return {
            "generated_nodes_csv_path": str(self.generated_nodes_csv_path),
            "generated_edges_csv_path": str(self.generated_edges_csv_path),
            "generated_graph_json_path": str(self.generated_graph_json_path),
            "reference_nodes_csv_path": str(self.reference_nodes_csv_path),
            "reference_edges_csv_path": str(self.reference_edges_csv_path),
            "reference_graph_json_path": str(self.reference_graph_json_path),
            "options": self.options.to_dict(),
        }


@dataclass(frozen=True)
class PreprocessingGraphReferenceComparisonIssue:
    """One deterministic graph reference comparison input issue."""

    kind: str
    message: str
    artifact_group: str | None = None
    artifact_kind: str | None = None
    field: str | None = None
    value: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _non_empty_string(self.kind, "kind"))
        object.__setattr__(
            self,
            "message",
            _non_empty_string(self.message, "message"),
        )
        object.__setattr__(
            self,
            "artifact_group",
            _optional_non_empty_string(self.artifact_group, "artifact_group"),
        )
        object.__setattr__(
            self,
            "artifact_kind",
            _optional_non_empty_string(self.artifact_kind, "artifact_kind"),
        )
        object.__setattr__(
            self,
            "field",
            _optional_non_empty_string(self.field, "field"),
        )
        if self.value is not None and not isinstance(self.value, str):
            raise ValueError("value must be a string or None")

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe issue dictionary."""
        return {
            "kind": self.kind,
            "message": self.message,
            "artifact_group": self.artifact_group,
            "artifact_kind": self.artifact_kind,
            "field": self.field,
            "value": self.value,
        }


@dataclass(frozen=True)
class PreprocessingGraphReferenceComparisonInputValidationResult:
    """Readiness report for future graph reference comparison."""

    comparison_input: PreprocessingGraphReferenceComparisonInput
    generated_node_count: int
    generated_edge_count: int
    reference_node_count: int
    reference_edge_count: int
    generated_condition: str | None = None
    reference_condition: str | None = None
    generated_schema_version: str | None = None
    reference_schema_version: str | None = None
    issues: tuple[PreprocessingGraphReferenceComparisonIssue, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(
            self.comparison_input,
            PreprocessingGraphReferenceComparisonInput,
        ):
            raise ValueError(
                "comparison_input must be "
                "PreprocessingGraphReferenceComparisonInput"
            )
        for field_name in (
            "generated_node_count",
            "generated_edge_count",
            "reference_node_count",
            "reference_edge_count",
        ):
            _require_non_negative_int(getattr(self, field_name), field_name)
        for field_name in (
            "generated_condition",
            "reference_condition",
            "generated_schema_version",
            "reference_schema_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _optional_non_empty_string(getattr(self, field_name), field_name),
            )
        if not isinstance(self.issues, tuple):
            raise ValueError(
                "issues must be a tuple of "
                "PreprocessingGraphReferenceComparisonIssue"
            )
        for issue in self.issues:
            if not isinstance(
                issue,
                PreprocessingGraphReferenceComparisonIssue,
            ):
                raise ValueError(
                    "issues must contain "
                    "PreprocessingGraphReferenceComparisonIssue"
                )

    @property
    def passed(self) -> bool:
        """Return whether validation found no issues."""
        return self.issues == ()

    @property
    def issue_count(self) -> int:
        """Return the number of validation issues."""
        return len(self.issues)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe validation report."""
        return {
            "comparison_input": self.comparison_input.to_dict(),
            "passed": self.passed,
            "issue_count": self.issue_count,
            "generated_node_count": self.generated_node_count,
            "generated_edge_count": self.generated_edge_count,
            "reference_node_count": self.reference_node_count,
            "reference_edge_count": self.reference_edge_count,
            "generated_condition": self.generated_condition,
            "reference_condition": self.reference_condition,
            "generated_schema_version": self.generated_schema_version,
            "reference_schema_version": self.reference_schema_version,
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class PreprocessingGraphReferenceComparisonMismatch:
    """One deterministic generated-vs-reference graph artifact mismatch."""

    kind: str
    message: str
    target: str
    key: str | None = None
    field: str | None = None
    generated_value: str | int | float | bool | None = None
    reference_value: str | int | float | bool | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _non_empty_string(self.kind, "kind"))
        object.__setattr__(
            self,
            "message",
            _non_empty_string(self.message, "message"),
        )
        object.__setattr__(
            self,
            "target",
            _non_empty_string(self.target, "target"),
        )
        object.__setattr__(
            self,
            "key",
            _optional_non_empty_string(self.key, "key"),
        )
        object.__setattr__(
            self,
            "field",
            _optional_non_empty_string(self.field, "field"),
        )
        _require_json_safe_scalar(self.generated_value, "generated_value")
        _require_json_safe_scalar(self.reference_value, "reference_value")

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe mismatch dictionary."""
        return {
            "kind": self.kind,
            "message": self.message,
            "target": self.target,
            "key": self.key,
            "field": self.field,
            "generated_value": self.generated_value,
            "reference_value": self.reference_value,
        }


@dataclass(frozen=True)
class PreprocessingGraphReferenceComparisonTargetResult:
    """Comparison result for one graph artifact target."""

    target: str
    enabled: bool
    passed: bool
    generated_count: int
    reference_count: int
    matched_count: int
    mismatches: tuple[PreprocessingGraphReferenceComparisonMismatch, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "target",
            _non_empty_string(self.target, "target"),
        )
        for field_name in ("enabled", "passed"):
            if not isinstance(getattr(self, field_name), bool):
                raise ValueError(f"{field_name} must be a bool")
        for field_name in (
            "generated_count",
            "reference_count",
            "matched_count",
        ):
            _require_non_negative_int(getattr(self, field_name), field_name)
        if not isinstance(self.mismatches, tuple):
            raise ValueError(
                "mismatches must be a tuple of "
                "PreprocessingGraphReferenceComparisonMismatch"
            )
        for mismatch in self.mismatches:
            if not isinstance(
                mismatch,
                PreprocessingGraphReferenceComparisonMismatch,
            ):
                raise ValueError(
                    "mismatches must contain "
                    "PreprocessingGraphReferenceComparisonMismatch"
                )

    @property
    def mismatch_count(self) -> int:
        """Return the number of mismatches for this target."""
        return len(self.mismatches)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe target comparison dictionary."""
        return {
            "target": self.target,
            "enabled": self.enabled,
            "passed": self.passed,
            "generated_count": self.generated_count,
            "reference_count": self.reference_count,
            "matched_count": self.matched_count,
            "mismatch_count": self.mismatch_count,
            "mismatches": [
                mismatch.to_dict() for mismatch in self.mismatches
            ],
        }


@dataclass(frozen=True)
class PreprocessingGraphReferenceComparisonResult:
    """Whole generated-vs-reference graph artifact comparison result."""

    comparison_input: PreprocessingGraphReferenceComparisonInput
    input_validation: PreprocessingGraphReferenceComparisonInputValidationResult
    target_results: tuple[PreprocessingGraphReferenceComparisonTargetResult, ...]
    mismatches: tuple[PreprocessingGraphReferenceComparisonMismatch, ...] = ()
    reference_semantics: str = _CURRENT_REFERENCE_SEMANTICS
    generated_condition: str | None = None
    reference_condition: str | None = None
    generated_schema_version: str | None = None
    reference_schema_version: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(
            self.comparison_input,
            PreprocessingGraphReferenceComparisonInput,
        ):
            raise ValueError(
                "comparison_input must be "
                "PreprocessingGraphReferenceComparisonInput"
            )
        if not isinstance(
            self.input_validation,
            PreprocessingGraphReferenceComparisonInputValidationResult,
        ):
            raise ValueError(
                "input_validation must be "
                "PreprocessingGraphReferenceComparisonInputValidationResult"
            )
        if not isinstance(self.target_results, tuple):
            raise ValueError(
                "target_results must be a tuple of "
                "PreprocessingGraphReferenceComparisonTargetResult"
            )
        for target_result in self.target_results:
            if not isinstance(
                target_result,
                PreprocessingGraphReferenceComparisonTargetResult,
            ):
                raise ValueError(
                    "target_results must contain "
                    "PreprocessingGraphReferenceComparisonTargetResult"
                )
        if not isinstance(self.mismatches, tuple):
            raise ValueError(
                "mismatches must be a tuple of "
                "PreprocessingGraphReferenceComparisonMismatch"
            )
        for mismatch in self.mismatches:
            if not isinstance(
                mismatch,
                PreprocessingGraphReferenceComparisonMismatch,
            ):
                raise ValueError(
                    "mismatches must contain "
                    "PreprocessingGraphReferenceComparisonMismatch"
                )
        object.__setattr__(
            self,
            "reference_semantics",
            _non_empty_string(self.reference_semantics, "reference_semantics"),
        )
        for field_name in (
            "generated_condition",
            "reference_condition",
            "generated_schema_version",
            "reference_schema_version",
        ):
            object.__setattr__(
                self,
                field_name,
                _optional_non_empty_string(getattr(self, field_name), field_name),
            )

    @property
    def passed(self) -> bool:
        """Return whether input validation and all enabled targets passed."""
        return self.input_validation.passed and all(
            (not target_result.enabled) or target_result.passed
            for target_result in self.target_results
        )

    @property
    def target_count(self) -> int:
        """Return the number of target result records."""
        return len(self.target_results)

    @property
    def failed_target_count(self) -> int:
        """Return the number of enabled target results that failed."""
        return sum(
            target_result.enabled and not target_result.passed
            for target_result in self.target_results
        )

    @property
    def mismatch_count(self) -> int:
        """Return the number of whole-comparison mismatches."""
        return len(self.mismatches)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe whole-comparison dictionary."""
        return {
            "comparison_input": self.comparison_input.to_dict(),
            "input_validation": self.input_validation.to_dict(),
            "passed": self.passed,
            "target_count": self.target_count,
            "failed_target_count": self.failed_target_count,
            "mismatch_count": self.mismatch_count,
            "target_results": [
                target_result.to_dict()
                for target_result in self.target_results
            ],
            "mismatches": [
                mismatch.to_dict() for mismatch in self.mismatches
            ],
            "reference_semantics": self.reference_semantics,
            "generated_condition": self.generated_condition,
            "reference_condition": self.reference_condition,
            "generated_schema_version": self.generated_schema_version,
            "reference_schema_version": self.reference_schema_version,
        }


def validate_preprocessing_graph_reference_comparison_input(
    comparison_input: PreprocessingGraphReferenceComparisonInput,
) -> PreprocessingGraphReferenceComparisonInputValidationResult:
    """Validate graph artifact readiness without comparing graph contents."""
    if not isinstance(
        comparison_input,
        PreprocessingGraphReferenceComparisonInput,
    ):
        raise ValueError(
            "comparison_input must be "
            "PreprocessingGraphReferenceComparisonInput"
        )

    issues: list[PreprocessingGraphReferenceComparisonIssue] = []
    options = comparison_input.options
    try:
        _validate_options(options)
    except ValueError:
        issues.append(
            PreprocessingGraphReferenceComparisonIssue(
                kind="invalid_options",
                message="Graph reference comparison options are invalid.",
                field="options",
            )
        )

    generated_bundle = build_preprocessing_graph_export_bundle(
        comparison_input.generated_nodes_csv_path,
        comparison_input.generated_edges_csv_path,
        comparison_input.generated_graph_json_path,
    )
    issues.extend(_bundle_issues(generated_bundle, artifact_group="generated"))

    reference_bundle = build_preprocessing_graph_export_bundle(
        comparison_input.reference_nodes_csv_path,
        comparison_input.reference_edges_csv_path,
        comparison_input.reference_graph_json_path,
    )
    issues.extend(_bundle_issues(reference_bundle, artifact_group="reference"))

    if options.reference_semantics != _CURRENT_REFERENCE_SEMANTICS:
        issues.append(
            PreprocessingGraphReferenceComparisonIssue(
                kind="reference_semantics_invalid",
                message="Graph reference semantics must be MANIA_analysis_v1_2.",
                field="options.reference_semantics",
                value=options.reference_semantics,
            )
        )

    if (
        not options.compare_nodes
        and not options.compare_edges
        and not options.compare_graph_json
    ):
        issues.append(
            PreprocessingGraphReferenceComparisonIssue(
                kind="comparison_target_disabled",
                message="At least one graph comparison target must be enabled.",
                field="options",
            )
        )

    _add_condition_issues(
        generated_condition=generated_bundle.condition,
        reference_condition=reference_bundle.condition,
        options=options,
        issues=issues,
    )
    _add_schema_version_issues(
        generated_schema_version=generated_bundle.schema_version,
        reference_schema_version=reference_bundle.schema_version,
        options=options,
        issues=issues,
    )

    return PreprocessingGraphReferenceComparisonInputValidationResult(
        comparison_input=comparison_input,
        generated_node_count=generated_bundle.node_count,
        generated_edge_count=generated_bundle.edge_count,
        reference_node_count=reference_bundle.node_count,
        reference_edge_count=reference_bundle.edge_count,
        generated_condition=generated_bundle.condition,
        reference_condition=reference_bundle.condition,
        generated_schema_version=generated_bundle.schema_version,
        reference_schema_version=reference_bundle.schema_version,
        issues=tuple(issues),
    )


def compare_preprocessing_graph_reference_artifacts(
    comparison_input: PreprocessingGraphReferenceComparisonInput,
) -> PreprocessingGraphReferenceComparisonResult:
    """Compare generated graph artifacts with reference graph artifacts."""
    input_validation = validate_preprocessing_graph_reference_comparison_input(
        comparison_input
    )
    if not input_validation.passed:
        mismatch = PreprocessingGraphReferenceComparisonMismatch(
            kind="input_validation_failed",
            message="Graph reference comparison input validation failed.",
            target="input",
        )
        return PreprocessingGraphReferenceComparisonResult(
            comparison_input=comparison_input,
            input_validation=input_validation,
            target_results=(),
            mismatches=(mismatch,),
            reference_semantics=comparison_input.options.reference_semantics,
            generated_condition=input_validation.generated_condition,
            reference_condition=input_validation.reference_condition,
            generated_schema_version=input_validation.generated_schema_version,
            reference_schema_version=input_validation.reference_schema_version,
        )

    options = comparison_input.options
    target_results = (
        (
            _compare_csv_target(
                target="nodes_csv",
                generated_path=comparison_input.generated_nodes_csv_path,
                reference_path=comparison_input.reference_nodes_csv_path,
                columns=NODE_COLUMNS,
                key_fields=("resid",),
            )
            if options.compare_nodes
            else _disabled_target_result(
                "nodes_csv",
                generated_count=input_validation.generated_node_count,
                reference_count=input_validation.reference_node_count,
            )
        ),
        (
            _compare_csv_target(
                target="edges_csv",
                generated_path=comparison_input.generated_edges_csv_path,
                reference_path=comparison_input.reference_edges_csv_path,
                columns=EDGE_COLUMNS,
                key_fields=("resid_i", "resid_j", "edge_type", "condition"),
            )
            if options.compare_edges
            else _disabled_target_result(
                "edges_csv",
                generated_count=input_validation.generated_edge_count,
                reference_count=input_validation.reference_edge_count,
            )
        ),
        (
            _compare_graph_json_target(
                comparison_input.generated_graph_json_path,
                comparison_input.reference_graph_json_path,
            )
            if options.compare_graph_json
            else _disabled_target_result(
                "graph_json",
                generated_count=(
                    input_validation.generated_node_count
                    + input_validation.generated_edge_count
                ),
                reference_count=(
                    input_validation.reference_node_count
                    + input_validation.reference_edge_count
                ),
            )
        ),
    )
    mismatches = tuple(
        mismatch
        for target_result in target_results
        for mismatch in target_result.mismatches
    )
    return PreprocessingGraphReferenceComparisonResult(
        comparison_input=comparison_input,
        input_validation=input_validation,
        target_results=target_results,
        mismatches=mismatches,
        reference_semantics=options.reference_semantics,
        generated_condition=input_validation.generated_condition,
        reference_condition=input_validation.reference_condition,
        generated_schema_version=input_validation.generated_schema_version,
        reference_schema_version=input_validation.reference_schema_version,
    )


def _compare_csv_target(
    *,
    target: str,
    generated_path: Path,
    reference_path: Path,
    columns: tuple[str, ...],
    key_fields: tuple[str, ...],
) -> PreprocessingGraphReferenceComparisonTargetResult:
    generated_rows, generated_issue = _read_csv_rows(
        generated_path,
        target=target,
        columns=columns,
    )
    if generated_issue is not None:
        return _target_result(
            target,
            enabled=True,
            generated_count=0,
            reference_count=0,
            matched_count=0,
            mismatches=(generated_issue,),
        )
    reference_rows, reference_issue = _read_csv_rows(
        reference_path,
        target=target,
        columns=columns,
    )
    if reference_issue is not None:
        return _target_result(
            target,
            enabled=True,
            generated_count=len(generated_rows),
            reference_count=0,
            matched_count=0,
            mismatches=(reference_issue,),
        )

    generated_by_key = _index_csv_rows(generated_rows, key_fields)
    reference_by_key = _index_csv_rows(reference_rows, key_fields)
    generated_keys = set(generated_by_key)
    reference_keys = set(reference_by_key)
    shared_keys = generated_keys & reference_keys

    mismatches: list[PreprocessingGraphReferenceComparisonMismatch] = []
    if len(generated_rows) != len(reference_rows):
        mismatches.append(
            _mismatch(
                "count_mismatch",
                target,
                "Generated and reference row counts differ.",
                field="row_count",
                generated_value=len(generated_rows),
                reference_value=len(reference_rows),
            )
        )

    for key in sorted(reference_keys - generated_keys):
        mismatches.append(
            _mismatch(
                "missing_generated_row",
                target,
                "Reference row has no generated row with the same key.",
                key=key,
            )
        )
    for key in sorted(generated_keys - reference_keys):
        mismatches.append(
            _mismatch(
                "extra_generated_row",
                target,
                "Generated row has no reference row with the same key.",
                key=key,
            )
        )
    for key in sorted(shared_keys):
        generated_row = generated_by_key[key]
        reference_row = reference_by_key[key]
        for field_name in columns:
            generated_value = generated_row[field_name]
            reference_value = reference_row[field_name]
            if generated_value != reference_value:
                mismatches.append(
                    _mismatch(
                        "field_value_mismatch",
                        target,
                        "Generated and reference CSV field values differ.",
                        key=key,
                        field=field_name,
                        generated_value=generated_value,
                        reference_value=reference_value,
                    )
                )

    return _target_result(
        target,
        enabled=True,
        generated_count=len(generated_rows),
        reference_count=len(reference_rows),
        matched_count=len(shared_keys),
        mismatches=tuple(mismatches),
    )


def _compare_graph_json_target(
    generated_path: Path,
    reference_path: Path,
) -> PreprocessingGraphReferenceComparisonTargetResult:
    target = "graph_json"
    generated_graph, generated_issue = _read_graph_json(generated_path)
    if generated_issue is not None:
        return _target_result(
            target,
            enabled=True,
            generated_count=0,
            reference_count=0,
            matched_count=0,
            mismatches=(generated_issue,),
        )
    reference_graph, reference_issue = _read_graph_json(reference_path)
    if reference_issue is not None:
        return _target_result(
            target,
            enabled=True,
            generated_count=_graph_json_item_count(generated_graph),
            reference_count=0,
            matched_count=0,
            mismatches=(reference_issue,),
        )

    generated_nodes, generated_nodes_issue = _graph_json_objects(
        generated_graph,
        collection="nodes",
        target=target,
    )
    generated_edges, generated_edges_issue = _graph_json_objects(
        generated_graph,
        collection="edges",
        target=target,
    )
    reference_nodes, reference_nodes_issue = _graph_json_objects(
        reference_graph,
        collection="nodes",
        target=target,
    )
    reference_edges, reference_edges_issue = _graph_json_objects(
        reference_graph,
        collection="edges",
        target=target,
    )
    structural_issues = tuple(
        issue
        for issue in (
            generated_nodes_issue,
            generated_edges_issue,
            reference_nodes_issue,
            reference_edges_issue,
        )
        if issue is not None
    )
    if structural_issues:
        return _target_result(
            target,
            enabled=True,
            generated_count=_graph_json_item_count(generated_graph),
            reference_count=_graph_json_item_count(reference_graph),
            matched_count=0,
            mismatches=structural_issues,
        )

    generated_count = len(generated_nodes) + len(generated_edges)
    reference_count = len(reference_nodes) + len(reference_edges)
    mismatches: list[PreprocessingGraphReferenceComparisonMismatch] = []
    for field_name in _GRAPH_JSON_TOP_LEVEL_FIELDS:
        generated_value = generated_graph.get(field_name)
        reference_value = reference_graph.get(field_name)
        if generated_value != reference_value:
            mismatches.append(
                _mismatch(
                    "json_top_level_mismatch",
                    target,
                    "Generated and reference graph.json metadata differ.",
                    field=field_name,
                    generated_value=_json_mismatch_value(generated_value),
                    reference_value=_json_mismatch_value(reference_value),
                )
            )

    if generated_count != reference_count:
        mismatches.append(
            _mismatch(
                "count_mismatch",
                target,
                "Generated and reference graph.json item counts differ.",
                field="item_count",
                generated_value=generated_count,
                reference_value=reference_count,
            )
        )

    node_mismatches, matched_nodes = _compare_json_collection(
        target=target,
        collection="nodes",
        generated_items=generated_nodes,
        reference_items=reference_nodes,
        key_function=_json_node_key,
    )
    edge_mismatches, matched_edges = _compare_json_collection(
        target=target,
        collection="edges",
        generated_items=generated_edges,
        reference_items=reference_edges,
        key_function=_json_edge_key,
    )
    mismatches.extend(node_mismatches)
    mismatches.extend(edge_mismatches)

    return _target_result(
        target,
        enabled=True,
        generated_count=generated_count,
        reference_count=reference_count,
        matched_count=matched_nodes + matched_edges,
        mismatches=tuple(mismatches),
    )


def _disabled_target_result(
    target: str,
    *,
    generated_count: int,
    reference_count: int,
) -> PreprocessingGraphReferenceComparisonTargetResult:
    return PreprocessingGraphReferenceComparisonTargetResult(
        target=target,
        enabled=False,
        passed=True,
        generated_count=generated_count,
        reference_count=reference_count,
        matched_count=0,
        mismatches=(),
    )


def _target_result(
    target: str,
    *,
    enabled: bool,
    generated_count: int,
    reference_count: int,
    matched_count: int,
    mismatches: tuple[PreprocessingGraphReferenceComparisonMismatch, ...],
) -> PreprocessingGraphReferenceComparisonTargetResult:
    return PreprocessingGraphReferenceComparisonTargetResult(
        target=target,
        enabled=enabled,
        passed=mismatches == (),
        generated_count=generated_count,
        reference_count=reference_count,
        matched_count=matched_count,
        mismatches=mismatches,
    )


def _read_csv_rows(
    path: Path,
    *,
    target: str,
    columns: tuple[str, ...],
) -> tuple[
    tuple[dict[str, str], ...],
    PreprocessingGraphReferenceComparisonMismatch | None,
]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return (), _mismatch(
            "read_failed",
            target,
            "Graph CSV artifact could not be read.",
            field="path",
            generated_value=str(path),
        )

    try:
        reader = csv.reader(StringIO(text), strict=True)
        header = tuple(next(reader))
        if header != columns:
            raise ValueError("invalid CSV header")
        rows: list[dict[str, str]] = []
        for row in reader:
            if len(row) != len(columns):
                raise ValueError("invalid CSV row column count")
            rows.append(dict(zip(columns, row, strict=True)))
    except StopIteration:
        return (), _mismatch(
            "parse_failed",
            target,
            "Graph CSV artifact is empty.",
            field="path",
            generated_value=str(path),
        )
    except (csv.Error, TypeError, ValueError):
        return (), _mismatch(
            "parse_failed",
            target,
            "Graph CSV artifact could not be parsed.",
            field="path",
            generated_value=str(path),
        )
    return tuple(rows), None


def _index_csv_rows(
    rows: tuple[dict[str, str], ...],
    key_fields: tuple[str, ...],
) -> dict[str, dict[str, str]]:
    return {
        _row_key(row, key_fields): row
        for row in rows
    }


def _row_key(row: dict[str, str], key_fields: tuple[str, ...]) -> str:
    return "|".join(row[field_name] for field_name in key_fields)


def _read_graph_json(
    path: Path,
) -> tuple[
    dict[str, object],
    PreprocessingGraphReferenceComparisonMismatch | None,
]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return {}, _mismatch(
            "read_failed",
            "graph_json",
            "graph.json artifact could not be read.",
            field="path",
            generated_value=str(path),
        )
    try:
        payload = cast(object, _json_loads(text))
    except JSONDecodeError:
        return {}, _mismatch(
            "parse_failed",
            "graph_json",
            "graph.json artifact could not be parsed.",
            field="path",
            generated_value=str(path),
        )
    if not isinstance(payload, dict):
        return {}, _mismatch(
            "parse_failed",
            "graph_json",
            "graph.json top-level value is not an object.",
            field="root",
            generated_value=str(path),
        )
    return cast(dict[str, object], payload), None


def _graph_json_objects(
    graph: dict[str, object],
    *,
    collection: str,
    target: str,
) -> tuple[
    tuple[dict[str, object], ...],
    PreprocessingGraphReferenceComparisonMismatch | None,
]:
    value = graph.get(collection)
    if not isinstance(value, list):
        return (), _mismatch(
            "parse_failed",
            target,
            f"graph.json {collection} collection is not a list.",
            field=collection,
        )
    items: list[dict[str, object]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            return (), _mismatch(
                "parse_failed",
                target,
                f"graph.json {collection} item is not an object.",
                key=f"{collection}:{index}",
            )
        items.append(cast(dict[str, object], item))
    return tuple(items), None


def _graph_json_item_count(graph: dict[str, object]) -> int:
    count = 0
    for collection in ("nodes", "edges"):
        value = graph.get(collection)
        if isinstance(value, list):
            count += len(value)
    return count


def _compare_json_collection(
    *,
    target: str,
    collection: str,
    generated_items: tuple[dict[str, object], ...],
    reference_items: tuple[dict[str, object], ...],
    key_function: Callable[[dict[str, object]], str | None],
) -> tuple[tuple[PreprocessingGraphReferenceComparisonMismatch, ...], int]:
    generated_by_key, generated_key_issues = _index_json_items(
        generated_items,
        collection=collection,
        target=target,
        key_function=key_function,
        side="generated",
    )
    reference_by_key, reference_key_issues = _index_json_items(
        reference_items,
        collection=collection,
        target=target,
        key_function=key_function,
        side="reference",
    )
    if generated_key_issues or reference_key_issues:
        return (*generated_key_issues, *reference_key_issues), 0

    generated_keys = set(generated_by_key)
    reference_keys = set(reference_by_key)
    shared_keys = generated_keys & reference_keys
    mismatches: list[PreprocessingGraphReferenceComparisonMismatch] = []

    for key in sorted(reference_keys - generated_keys):
        mismatches.append(
            _mismatch(
                "json_missing_generated_item",
                target,
                "Reference graph.json item has no generated item with "
                "the same key.",
                key=f"{collection}:{key}",
            )
        )
    for key in sorted(generated_keys - reference_keys):
        mismatches.append(
            _mismatch(
                "json_extra_generated_item",
                target,
                "Generated graph.json item has no reference item with "
                "the same key.",
                key=f"{collection}:{key}",
            )
        )
    for key in sorted(shared_keys):
        generated_item = generated_by_key[key]
        reference_item = reference_by_key[key]
        field_names = sorted(set(generated_item) | set(reference_item))
        for field_name in field_names:
            generated_value = generated_item.get(field_name)
            reference_value = reference_item.get(field_name)
            if generated_value != reference_value:
                mismatches.append(
                    _mismatch(
                        "json_field_value_mismatch",
                        target,
                        "Generated and reference graph.json field values differ.",
                        key=f"{collection}:{key}",
                        field=field_name,
                        generated_value=_json_mismatch_value(generated_value),
                        reference_value=_json_mismatch_value(reference_value),
                    )
                )
    return tuple(mismatches), len(shared_keys)


def _index_json_items(
    items: tuple[dict[str, object], ...],
    *,
    collection: str,
    target: str,
    key_function: Callable[[dict[str, object]], str | None],
    side: str,
) -> tuple[
    dict[str, dict[str, object]],
    tuple[PreprocessingGraphReferenceComparisonMismatch, ...],
]:
    indexed: dict[str, dict[str, object]] = {}
    issues: list[PreprocessingGraphReferenceComparisonMismatch] = []
    for index, item in enumerate(items):
        key = key_function(item)
        if key is None:
            issues.append(
                _mismatch(
                    "parse_failed",
                    target,
                    f"graph.json {side} {collection} item key is invalid.",
                    key=f"{collection}:{index}",
                )
            )
            continue
        if key in indexed:
            issues.append(
                _mismatch(
                    "parse_failed",
                    target,
                    f"graph.json {side} {collection} item key is duplicated.",
                    key=f"{collection}:{key}",
                )
            )
            continue
        indexed[key] = item
    return indexed, tuple(issues)


def _json_node_key(item: dict[str, object]) -> str | None:
    node_id = _json_key_value(item.get("id"))
    if node_id is not None:
        return node_id
    return _json_key_value(item.get("resid"))


def _json_edge_key(item: dict[str, object]) -> str | None:
    endpoint_fields = (
        ("source", "target")
        if "source" in item and "target" in item
        else ("resid_i", "resid_j")
    )
    key_fields = (
        endpoint_fields[0],
        endpoint_fields[1],
        "edge_type",
        "condition",
    )
    values = tuple(_json_key_value(item.get(field_name)) for field_name in key_fields)
    if any(value is None for value in values):
        return None
    return "|".join(value for value in values if value is not None)


def _json_key_value(value: object) -> str | None:
    if isinstance(value, str):
        return value if value.strip() != "" else None
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return str(value)
    return None


def _json_mismatch_value(value: object) -> str | int | float | bool | None:
    if _is_json_safe_scalar(value):
        return cast(str | int | float | bool | None, value)
    return _json_dumps(value, sort_keys=True)


def _mismatch(
    kind: str,
    target: str,
    message: str,
    *,
    key: str | None = None,
    field: str | None = None,
    generated_value: str | int | float | bool | None = None,
    reference_value: str | int | float | bool | None = None,
) -> PreprocessingGraphReferenceComparisonMismatch:
    return PreprocessingGraphReferenceComparisonMismatch(
        kind=kind,
        message=message,
        target=target,
        key=key,
        field=field,
        generated_value=generated_value,
        reference_value=reference_value,
    )


def _validate_options(
    options: object,
) -> None:
    if not isinstance(options, PreprocessingGraphReferenceComparisonOptions):
        raise ValueError(
            "options must be PreprocessingGraphReferenceComparisonOptions"
        )
    PreprocessingGraphReferenceComparisonOptions(
        reference_semantics=options.reference_semantics,
        condition=options.condition,
        require_matching_condition=options.require_matching_condition,
        require_matching_schema_version=options.require_matching_schema_version,
        compare_nodes=options.compare_nodes,
        compare_edges=options.compare_edges,
        compare_graph_json=options.compare_graph_json,
    )


def _bundle_issues(
    bundle: PreprocessingGraphExportBundleResult,
    *,
    artifact_group: str,
) -> tuple[PreprocessingGraphReferenceComparisonIssue, ...]:
    artifact_fields = (
        _GENERATED_ARTIFACT_FIELDS
        if artifact_group == "generated"
        else _REFERENCE_ARTIFACT_FIELDS
    )
    return tuple(
        _bundle_issue_to_comparison_issue(
            issue,
            artifact_group=artifact_group,
            field=artifact_fields.get(issue.artifact_kind or ""),
        )
        for issue in bundle.issues
    )


def _bundle_issue_to_comparison_issue(
    issue: PreprocessingGraphExportBundleIssue,
    *,
    artifact_group: str,
    field: str | None,
) -> PreprocessingGraphReferenceComparisonIssue:
    if issue.kind in _PASSTHROUGH_BUNDLE_ISSUES:
        kind = issue.kind
    else:
        kind = f"{artifact_group}_bundle_invalid"
    return PreprocessingGraphReferenceComparisonIssue(
        kind=kind,
        message=(
            f"{artifact_group} graph export bundle issue: {issue.message}"
        ),
        artifact_group=artifact_group,
        artifact_kind=issue.artifact_kind,
        field=field or issue.field,
        value=issue.value,
    )


def _add_condition_issues(
    *,
    generated_condition: str | None,
    reference_condition: str | None,
    options: PreprocessingGraphReferenceComparisonOptions,
    issues: list[PreprocessingGraphReferenceComparisonIssue],
) -> None:
    if options.require_matching_condition:
        if generated_condition is None or reference_condition is None:
            issues.append(
                PreprocessingGraphReferenceComparisonIssue(
                    kind="condition_missing",
                    message=(
                        "Generated and reference graph conditions are required."
                    ),
                    field="condition",
                )
            )
        elif generated_condition != reference_condition:
            issues.append(
                PreprocessingGraphReferenceComparisonIssue(
                    kind="condition_mismatch",
                    message="Generated and reference graph conditions differ.",
                    field="condition",
                    value=f"{generated_condition}|{reference_condition}",
                )
            )

    expected_condition = options.condition
    if expected_condition is not None:
        if (
            generated_condition != expected_condition
            or reference_condition != expected_condition
        ):
            issues.append(
                PreprocessingGraphReferenceComparisonIssue(
                    kind="condition_mismatch",
                    message="Graph artifacts do not match the requested condition.",
                    field="options.condition",
                    value=expected_condition,
                )
            )


def _add_schema_version_issues(
    *,
    generated_schema_version: str | None,
    reference_schema_version: str | None,
    options: PreprocessingGraphReferenceComparisonOptions,
    issues: list[PreprocessingGraphReferenceComparisonIssue],
) -> None:
    if not options.require_matching_schema_version:
        return
    if (
        generated_schema_version is None
        or reference_schema_version is None
        or generated_schema_version != reference_schema_version
    ):
        issues.append(
            PreprocessingGraphReferenceComparisonIssue(
                kind="schema_version_mismatch",
                message="Generated and reference graph schema versions differ.",
                field="schema_version",
                value=(
                    f"{generated_schema_version}|{reference_schema_version}"
                ),
            )
        )


def _non_empty_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or value.strip() == "":
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _optional_non_empty_string(
    value: object,
    field_name: str,
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or value.strip() == "":
        raise ValueError(f"{field_name} must be None or a non-empty string")
    return value


def _require_json_safe_scalar(value: object, field_name: str) -> None:
    if not _is_json_safe_scalar(value):
        raise ValueError(f"{field_name} must be a JSON-safe scalar value")


def _is_json_safe_scalar(value: object) -> bool:
    if value is None or isinstance(value, (str, bool, int)):
        return True
    return isinstance(value, float) and math.isfinite(value)


def _require_non_negative_int(value: object, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative int")


__all__ = [
    "PreprocessingGraphReferenceComparisonInput",
    "PreprocessingGraphReferenceComparisonInputValidationResult",
    "PreprocessingGraphReferenceComparisonIssue",
    "PreprocessingGraphReferenceComparisonMismatch",
    "PreprocessingGraphReferenceComparisonOptions",
    "PreprocessingGraphReferenceComparisonResult",
    "PreprocessingGraphReferenceComparisonTargetResult",
    "compare_preprocessing_graph_reference_artifacts",
    "validate_preprocessing_graph_reference_comparison_input",
]
