"""Dependency-free preprocessing graph workflow planning contracts."""

from __future__ import annotations

import importlib
import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any, Protocol, cast

from mania.preprocessing.input_manifest import PreprocessingInputManifest
from mania.preprocessing.path_validation import (
    PreprocessingPathValidationReport,
)
from mania.preprocessing.trajectory_frame_sampling import (
    PreprocessingFrameSamplingOptions,
)

if TYPE_CHECKING:
    from mania.preprocessing.trajectory_contacts import (
        ContactProgressCallback,
        PreprocessingContactComputationLimits,
        PreprocessingContactDetectionOptions,
    )

_CURRENT_REFERENCE_SEMANTICS = "MANIA_analysis_v1_2"
_DEFAULT_RUN_NAME = "preprocessing_graph_export"

_OPTION_BOOL_FIELDS = (
    "overwrite",
    "include_rg",
    "include_contacts",
    "include_graph_export",
    "include_diagnostics",
    "enable_reference_comparison",
)
_OPTION_REFERENCE_PATH_FIELDS = (
    "reference_nodes_csv_path",
    "reference_edges_csv_path",
    "reference_graph_json_path",
)
_OUTPUT_LAYOUT_PATH_FIELDS = (
    "output_dir",
    "rg_timeseries_csv_path",
    "contacts_perframe_csv_path",
    "contact_edges_csv_path",
    "graph_nodes_csv_path",
    "graph_edges_csv_path",
    "graph_json_path",
    "diagnostics_report_json_path",
    "reference_comparison_json_path",
)
_FOUNDATIONAL_STEPS = (
    "load_manifest",
    "validate_manifest_paths",
    "load_condition_runtimes",
)
_GRAPH_EXPORT_STEPS = (
    "build_graph_mapping",
    "write_graph_nodes_csv",
    "write_graph_edges_csv",
    "validate_graph_csvs",
    "write_graph_json",
    "build_graph_export_bundle",
)
_DIAGNOSTICS_STEPS = (
    "run_graph_diagnostics",
    "build_graph_diagnostics_report",
)
_REFERENCE_COMPARISON_STEPS = (
    "validate_reference_comparison_input",
    "compare_reference_graph_artifacts",
)
_MANIFEST_LOAD_EXCEPTION_NAMES = (
    "FileNotFoundError",
    "IsADirectoryError",
    "ValueError",
)
_MANIFEST_CONTRACT_EXCEPTION_NAME = "ValidationError"


def _default_contact_computation_limits(
) -> PreprocessingContactComputationLimits:
    contacts_module = importlib.import_module(
        "mania.preprocessing.trajectory_contacts"
    )
    limits_type = cast(
        Any,
        contacts_module,
    ).PreprocessingContactComputationLimits
    return cast("PreprocessingContactComputationLimits", limits_type())


def _default_contact_detection_options(
) -> PreprocessingContactDetectionOptions:
    contacts_module = importlib.import_module(
        "mania.preprocessing.trajectory_contacts"
    )
    options_type = cast(
        Any,
        contacts_module,
    ).PreprocessingContactDetectionOptions
    return cast("PreprocessingContactDetectionOptions", options_type())


class _ManifestLoader(Protocol):
    def __call__(self, path: str | Path) -> PreprocessingInputManifest: ...


class _ManifestPathValidator(Protocol):
    def __call__(
        self,
        manifest: PreprocessingInputManifest,
        *,
        base_dir: str | Path | None = None,
        check_output_root: bool = False,
    ) -> PreprocessingPathValidationReport: ...


class _ManifestRuntimeLoader(Protocol):
    def __call__(
        self,
        manifest: PreprocessingInputManifest,
        *,
        base_dir: str | Path | None = None,
    ) -> object: ...


class _ManifestRgComputer(Protocol):
    def __call__(
        self,
        manifest_result: object,
        *,
        frame_sampling: object | None = None,
    ) -> object: ...


class _ManifestContactsComputer(Protocol):
    def __call__(
        self,
        manifest_result: object,
        *,
        options: object | None = None,
        computation_limits: object | None = None,
        frame_sampling: object | None = None,
        progress_callback: object | None = None,
    ) -> object: ...


class _RgTimeseriesCsvWriter(Protocol):
    def __call__(self, rg_result: object, output_path: str | Path) -> object: ...


class _ContactEdgesCsvWriter(Protocol):
    def __call__(
        self,
        contacts_result: object,
        output_path: str | Path,
    ) -> object: ...


class _ContactsPerframeCsvWriter(Protocol):
    def __call__(
        self,
        contacts_result: object,
        output_path: str | Path,
    ) -> object: ...


class _RgTimeseriesCsvValidator(Protocol):
    def __call__(self, csv_path: str | Path) -> object: ...


class _ContactEdgesCsvValidator(Protocol):
    def __call__(self, csv_path: str | Path) -> object: ...


class _ContactsPerframeCsvValidator(Protocol):
    def __call__(self, csv_path: str | Path) -> object: ...


class _ScientificCsvWriter(Protocol):
    def __call__(
        self,
        source_result: object,
        output_path: str | Path,
    ) -> object: ...


class _ScientificCsvValidator(Protocol):
    def __call__(self, csv_path: str | Path) -> object: ...


class _ResidueTablesCsvWriter(Protocol):
    def __call__(self, mapping_result: object, output_dir: str | Path) -> object: ...


class _ProteinContactArtifactsCsvWriter(Protocol):
    def __call__(self, contacts_result: object, output_dir: str | Path) -> object: ...


class _ManifestArtifactsWriter(Protocol):
    def __call__(
        self,
        mapping_result: object,
        output_dir: str | Path,
        *,
        residue_tables: object | None = None,
        protein_contacts: object | None = None,
    ) -> object: ...


class _GraphExportMappingBuilder(Protocol):
    def __call__(self, contacts_result: object) -> object: ...


class _GraphNodesCsvWriter(Protocol):
    def __call__(self, mapping_result: object, output_path: str | Path) -> object: ...


class _GraphEdgesCsvWriter(Protocol):
    def __call__(self, mapping_result: object, output_path: str | Path) -> object: ...


class _GraphCsvValidator(Protocol):
    def __call__(
        self,
        nodes_csv_path: str | Path,
        edges_csv_path: str | Path,
    ) -> object: ...


class _GraphJsonWriter(Protocol):
    def __call__(
        self,
        nodes_csv_path: str | Path,
        edges_csv_path: str | Path,
        output_path: str | Path,
    ) -> object: ...


class _GraphExportBundleBuilder(Protocol):
    def __call__(
        self,
        nodes_csv_path: str | Path,
        edges_csv_path: str | Path,
        graph_json_path: str | Path,
    ) -> object: ...


class _GraphDiagnosticsRunner(Protocol):
    def __call__(
        self,
        nodes_csv_path: str | Path,
        edges_csv_path: str | Path,
        graph_json_path: str | Path,
    ) -> object: ...


class _GraphDiagnosticsReportBuilder(Protocol):
    def __call__(self, diagnostics_result: object) -> object: ...


class _GraphReferenceComparisonOptionsBuilder(Protocol):
    def __call__(
        self,
        *,
        reference_semantics: str = _CURRENT_REFERENCE_SEMANTICS,
        condition: str | None = None,
    ) -> object: ...


class _GraphReferenceComparisonInputBuilder(Protocol):
    def __call__(
        self,
        *,
        generated_nodes_csv_path: Path,
        generated_edges_csv_path: Path,
        generated_graph_json_path: Path,
        reference_nodes_csv_path: Path,
        reference_edges_csv_path: Path,
        reference_graph_json_path: Path,
        options: object,
    ) -> object: ...


class _GraphReferenceComparator(Protocol):
    def __call__(self, comparison_input: object) -> object: ...


@dataclass(frozen=True)
class PreprocessingGraphWorkflowOptions:
    """Run options for future preprocessing graph export orchestration."""

    manifest_path: Path
    output_dir: Path
    run_name: str = _DEFAULT_RUN_NAME
    overwrite: bool = False
    include_rg: bool = True
    include_contacts: bool = True
    include_graph_export: bool = True
    include_diagnostics: bool = True
    enable_reference_comparison: bool = False
    reference_nodes_csv_path: Path | None = None
    reference_edges_csv_path: Path | None = None
    reference_graph_json_path: Path | None = None
    reference_semantics: str = _CURRENT_REFERENCE_SEMANTICS
    frame_sampling: PreprocessingFrameSamplingOptions = field(
        default_factory=PreprocessingFrameSamplingOptions
    )
    contact_detection_options: PreprocessingContactDetectionOptions = field(
        default_factory=_default_contact_detection_options
    )
    contact_computation_limits: PreprocessingContactComputationLimits = field(
        default_factory=_default_contact_computation_limits
    )

    def __post_init__(self) -> None:
        _require_path(self.manifest_path, "manifest_path")
        _require_path(self.output_dir, "output_dir")
        object.__setattr__(
            self,
            "run_name",
            _non_empty_string(self.run_name, "run_name"),
        )
        for field_name in _OPTION_BOOL_FIELDS:
            _require_bool(getattr(self, field_name), field_name)
        for field_name in _OPTION_REFERENCE_PATH_FIELDS:
            _require_optional_path(getattr(self, field_name), field_name)
        object.__setattr__(
            self,
            "reference_semantics",
            _non_empty_string(self.reference_semantics, "reference_semantics"),
        )
        _require_frame_sampling(self.frame_sampling, "frame_sampling")
        _require_contact_detection_options(
            self.contact_detection_options,
            "contact_detection_options",
        )
        _require_contact_computation_limits(
            self.contact_computation_limits,
            "contact_computation_limits",
        )

    def to_dict(self) -> dict[str, object]:
        """Return JSON-safe workflow options."""
        return {
            "manifest_path": str(self.manifest_path),
            "output_dir": str(self.output_dir),
            "run_name": self.run_name,
            "overwrite": self.overwrite,
            "include_rg": self.include_rg,
            "include_contacts": self.include_contacts,
            "include_graph_export": self.include_graph_export,
            "include_diagnostics": self.include_diagnostics,
            "enable_reference_comparison": self.enable_reference_comparison,
            "reference_nodes_csv_path": _optional_path_string(
                self.reference_nodes_csv_path
            ),
            "reference_edges_csv_path": _optional_path_string(
                self.reference_edges_csv_path
            ),
            "reference_graph_json_path": _optional_path_string(
                self.reference_graph_json_path
            ),
            "reference_semantics": self.reference_semantics,
            "frame_sampling": self.frame_sampling.to_dict(),
            "contact_detection_options": (
                _contact_detection_options_payload(
                    self.contact_detection_options
                )
            ),
            "contact_computation_limits": (
                _contact_computation_limits_payload(
                    self.contact_computation_limits
                )
            ),
        }


@dataclass(frozen=True)
class PreprocessingGraphWorkflowOutputLayout:
    """Deterministic planned output paths for future workflow execution."""

    output_dir: Path
    run_name: str
    rg_timeseries_csv_path: Path
    contacts_perframe_csv_path: Path
    contact_edges_csv_path: Path
    graph_nodes_csv_path: Path
    graph_edges_csv_path: Path
    graph_json_path: Path
    diagnostics_report_json_path: Path
    reference_comparison_json_path: Path

    def __post_init__(self) -> None:
        for field_name in _OUTPUT_LAYOUT_PATH_FIELDS:
            _require_path(getattr(self, field_name), field_name)
        object.__setattr__(
            self,
            "run_name",
            _non_empty_string(self.run_name, "run_name"),
        )

    def to_dict(self) -> dict[str, object]:
        """Return JSON-safe output layout metadata."""
        return {
            "output_dir": str(self.output_dir),
            "run_name": self.run_name,
            "rg_timeseries_csv_path": str(self.rg_timeseries_csv_path),
            "contacts_perframe_csv_path": str(
                self.contacts_perframe_csv_path
            ),
            "contact_edges_csv_path": str(self.contact_edges_csv_path),
            "graph_nodes_csv_path": str(self.graph_nodes_csv_path),
            "graph_edges_csv_path": str(self.graph_edges_csv_path),
            "graph_json_path": str(self.graph_json_path),
            "diagnostics_report_json_path": str(
                self.diagnostics_report_json_path
            ),
            "reference_comparison_json_path": str(
                self.reference_comparison_json_path
            ),
        }


@dataclass(frozen=True)
class PreprocessingGraphWorkflowIssue:
    """One deterministic workflow planning issue."""

    kind: str
    message: str
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
            "field",
            _optional_non_empty_string(self.field, "field"),
        )
        object.__setattr__(
            self,
            "value",
            _optional_non_empty_string(self.value, "value"),
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe issue dictionary."""
        return {
            "kind": self.kind,
            "message": self.message,
            "field": self.field,
            "value": self.value,
        }


@dataclass(frozen=True)
class PreprocessingGraphWorkflowManifestReadinessIssue:
    """One deterministic local manifest readiness issue."""

    kind: str
    message: str
    field: str | None = None
    condition_name: str | None = None
    path: Path | None = None
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
            "field",
            _optional_non_empty_string(self.field, "field"),
        )
        object.__setattr__(
            self,
            "condition_name",
            _optional_non_empty_string(
                self.condition_name,
                "condition_name",
            ),
        )
        _require_optional_path(self.path, "path")
        object.__setattr__(
            self,
            "value",
            _optional_non_empty_string(self.value, "value"),
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe readiness issue dictionary."""
        return {
            "kind": self.kind,
            "message": self.message,
            "field": self.field,
            "condition_name": self.condition_name,
            "path": _optional_path_string(self.path),
            "value": self.value,
        }


@dataclass(frozen=True)
class PreprocessingGraphWorkflowManifestReadinessResult:
    """Local manifest readiness metadata before workflow runtime loading."""

    manifest_path: Path
    manifest_loaded: bool
    manifest_paths_valid: bool
    condition_names: tuple[str, ...]
    expected_condition_count: int | None = None
    input_paths: tuple[Path, ...] = ()
    issues: tuple[PreprocessingGraphWorkflowManifestReadinessIssue, ...] = ()

    def __post_init__(self) -> None:
        _require_path(self.manifest_path, "manifest_path")
        _require_bool(self.manifest_loaded, "manifest_loaded")
        _require_bool(self.manifest_paths_valid, "manifest_paths_valid")
        if not isinstance(self.condition_names, tuple):
            raise ValueError("condition_names must be a tuple of strings")
        object.__setattr__(
            self,
            "condition_names",
            tuple(
                _non_empty_string(condition_name, "condition_names")
                for condition_name in self.condition_names
            ),
        )
        if self.expected_condition_count is not None:
            _require_non_negative_int(
                self.expected_condition_count,
                "expected_condition_count",
            )
        if not isinstance(self.input_paths, tuple):
            raise ValueError("input_paths must be a tuple of Path")
        for input_path in self.input_paths:
            _require_path(input_path, "input_paths")
        if not isinstance(self.issues, tuple):
            raise ValueError(
                "issues must be a tuple of "
                "PreprocessingGraphWorkflowManifestReadinessIssue"
            )
        for issue in self.issues:
            if not isinstance(
                issue,
                PreprocessingGraphWorkflowManifestReadinessIssue,
            ):
                raise ValueError(
                    "issues must contain "
                    "PreprocessingGraphWorkflowManifestReadinessIssue"
                )

    @property
    def passed(self) -> bool:
        """Return whether the manifest is ready for later runtime loading."""
        return (
            self.manifest_loaded
            and self.manifest_paths_valid
            and self.issues == ()
        )

    @property
    def issue_count(self) -> int:
        """Return the number of readiness issues."""
        return len(self.issues)

    @property
    def condition_count(self) -> int:
        """Return the number of manifest conditions reported."""
        return len(self.condition_names)

    @property
    def input_path_count(self) -> int:
        """Return the number of manifest-declared local input paths checked."""
        return len(self.input_paths)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe readiness result dictionary."""
        return {
            "manifest_path": str(self.manifest_path),
            "manifest_loaded": self.manifest_loaded,
            "manifest_paths_valid": self.manifest_paths_valid,
            "condition_names": list(self.condition_names),
            "condition_count": self.condition_count,
            "expected_condition_count": self.expected_condition_count,
            "input_paths": [str(input_path) for input_path in self.input_paths],
            "input_path_count": self.input_path_count,
            "issues": [issue.to_dict() for issue in self.issues],
            "issue_count": self.issue_count,
            "passed": self.passed,
        }


@dataclass(frozen=True)
class PreprocessingGraphWorkflowRuntimeLoadingIssue:
    """One deterministic workflow runtime loading issue."""

    kind: str
    message: str
    field: str | None = None
    condition_name: str | None = None
    path: Path | None = None
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
            "field",
            _optional_non_empty_string(self.field, "field"),
        )
        object.__setattr__(
            self,
            "condition_name",
            _optional_non_empty_string(
                self.condition_name,
                "condition_name",
            ),
        )
        _require_optional_path(self.path, "path")
        object.__setattr__(
            self,
            "value",
            _optional_non_empty_string(self.value, "value"),
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe runtime loading issue dictionary."""
        return {
            "kind": self.kind,
            "message": self.message,
            "field": self.field,
            "condition_name": self.condition_name,
            "path": _optional_path_string(self.path),
            "value": self.value,
        }


@dataclass(frozen=True)
class PreprocessingGraphWorkflowRuntimeLoadingResult:
    """Manifest-driven runtime loading metadata for future orchestration."""

    manifest_path: Path
    manifest_readiness: PreprocessingGraphWorkflowManifestReadinessResult
    condition_names: tuple[str, ...]
    expected_condition_names: tuple[str, ...] | None
    runtime_load_result: object | None = None
    issues: tuple[PreprocessingGraphWorkflowRuntimeLoadingIssue, ...] = ()

    def __post_init__(self) -> None:
        _require_path(self.manifest_path, "manifest_path")
        if not isinstance(
            self.manifest_readiness,
            PreprocessingGraphWorkflowManifestReadinessResult,
        ):
            raise ValueError(
                "manifest_readiness must be "
                "PreprocessingGraphWorkflowManifestReadinessResult"
            )
        if not isinstance(self.condition_names, tuple):
            raise ValueError("condition_names must be a tuple of strings")
        object.__setattr__(
            self,
            "condition_names",
            tuple(
                _non_empty_string(condition_name, "condition_names")
                for condition_name in self.condition_names
            ),
        )
        if self.expected_condition_names is not None:
            if not isinstance(self.expected_condition_names, tuple):
                raise ValueError(
                    "expected_condition_names must be None or a tuple of "
                    "strings"
                )
            object.__setattr__(
                self,
                "expected_condition_names",
                tuple(
                    _non_empty_string(
                        condition_name,
                        "expected_condition_names",
                    )
                    for condition_name in self.expected_condition_names
                ),
            )
        if not isinstance(self.issues, tuple):
            raise ValueError(
                "issues must be a tuple of "
                "PreprocessingGraphWorkflowRuntimeLoadingIssue"
            )
        for issue in self.issues:
            if not isinstance(
                issue,
                PreprocessingGraphWorkflowRuntimeLoadingIssue,
            ):
                raise ValueError(
                    "issues must contain "
                    "PreprocessingGraphWorkflowRuntimeLoadingIssue"
                )

    @property
    def passed(self) -> bool:
        """Return whether readiness and runtime loading both passed."""
        return (
            self.manifest_readiness.passed
            and self.runtime_load_result is not None
            and self._expected_conditions_loaded
            and self.issues == ()
        )

    @property
    def issue_count(self) -> int:
        """Return the number of wrapper runtime loading issues."""
        return len(self.issues)

    @property
    def condition_count(self) -> int:
        """Return the number of loaded condition runtimes reported."""
        return len(self.condition_names)

    @property
    def runtime_loaded(self) -> bool:
        """Return whether a Stage 11 manifest runtime result is retained."""
        return self.runtime_load_result is not None

    @property
    def _expected_conditions_loaded(self) -> bool:
        expected_names = self.expected_condition_names
        if expected_names is None:
            return True
        loaded_names = set(self.condition_names)
        return all(
            expected_condition_name in loaded_names
            for expected_condition_name in expected_names
        )

    def to_dict(self) -> dict[str, object]:
        """Return JSON-safe metadata without serializing runtime objects."""
        return {
            "manifest_path": str(self.manifest_path),
            "manifest_readiness": self.manifest_readiness.to_dict(),
            "condition_names": list(self.condition_names),
            "expected_condition_names": (
                list(self.expected_condition_names)
                if self.expected_condition_names is not None
                else None
            ),
            "runtime_loaded": self.runtime_loaded,
            "runtime_load_result_type": _runtime_load_result_type(
                self.runtime_load_result
            ),
            "condition_count": self.condition_count,
            "issue_count": self.issue_count,
            "issues": [issue.to_dict() for issue in self.issues],
            "passed": self.passed,
        }


@dataclass(frozen=True)
class PreprocessingGraphWorkflowComputationIssue:
    """One deterministic workflow computation issue."""

    kind: str
    message: str
    stage: str | None = None
    condition_name: str | None = None
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
            "stage",
            _optional_non_empty_string(self.stage, "stage"),
        )
        object.__setattr__(
            self,
            "condition_name",
            _optional_non_empty_string(
                self.condition_name,
                "condition_name",
            ),
        )
        object.__setattr__(
            self,
            "field",
            _optional_non_empty_string(self.field, "field"),
        )
        object.__setattr__(
            self,
            "value",
            _optional_non_empty_string(self.value, "value"),
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe computation issue dictionary."""
        return {
            "kind": self.kind,
            "message": self.message,
            "stage": self.stage,
            "condition_name": self.condition_name,
            "field": self.field,
            "value": self.value,
        }


@dataclass(frozen=True)
class PreprocessingGraphWorkflowComputationResult:
    """In-memory Stage 15.4 Rg and contacts orchestration result."""

    runtime_loading: PreprocessingGraphWorkflowRuntimeLoadingResult
    condition_names: tuple[str, ...]
    include_rg: bool
    include_contacts: bool
    frame_sampling: PreprocessingFrameSamplingOptions = field(
        default_factory=PreprocessingFrameSamplingOptions
    )
    contact_detection_options: PreprocessingContactDetectionOptions = field(
        default_factory=_default_contact_detection_options
    )
    contact_computation_limits: PreprocessingContactComputationLimits = field(
        default_factory=_default_contact_computation_limits
    )
    rg_result: object | None = None
    contacts_result: object | None = None
    issues: tuple[PreprocessingGraphWorkflowComputationIssue, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(
            self.runtime_loading,
            PreprocessingGraphWorkflowRuntimeLoadingResult,
        ):
            raise ValueError(
                "runtime_loading must be "
                "PreprocessingGraphWorkflowRuntimeLoadingResult"
            )
        if not isinstance(self.condition_names, tuple):
            raise ValueError("condition_names must be a tuple of strings")
        object.__setattr__(
            self,
            "condition_names",
            tuple(
                _non_empty_string(condition_name, "condition_names")
                for condition_name in self.condition_names
            ),
        )
        _require_bool(self.include_rg, "include_rg")
        _require_bool(self.include_contacts, "include_contacts")
        _require_frame_sampling(self.frame_sampling, "frame_sampling")
        _require_contact_detection_options(
            self.contact_detection_options,
            "contact_detection_options",
        )
        _require_contact_computation_limits(
            self.contact_computation_limits,
            "contact_computation_limits",
        )
        if not isinstance(self.issues, tuple):
            raise ValueError(
                "issues must be a tuple of "
                "PreprocessingGraphWorkflowComputationIssue"
            )
        for issue in self.issues:
            if not isinstance(
                issue,
                PreprocessingGraphWorkflowComputationIssue,
            ):
                raise ValueError(
                    "issues must contain "
                    "PreprocessingGraphWorkflowComputationIssue"
                )

    @property
    def passed(self) -> bool:
        """Return whether runtime loading and requested computations passed."""
        return (
            self.runtime_loading.passed
            and (not self.include_rg or self.rg_computed)
            and (not self.include_contacts or self.contacts_computed)
            and self.issues == ()
        )

    @property
    def issue_count(self) -> int:
        """Return the number of computation issues."""
        return len(self.issues)

    @property
    def condition_count(self) -> int:
        """Return the number of covered condition names."""
        return len(self.condition_names)

    @property
    def rg_computed(self) -> bool:
        """Return whether an Rg result object is retained."""
        return self.rg_result is not None

    @property
    def contacts_computed(self) -> bool:
        """Return whether a contacts result object is retained."""
        return self.contacts_result is not None

    def to_dict(self) -> dict[str, object]:
        """Return JSON-safe metadata without raw runtime or result objects."""
        return {
            "runtime_loading": self.runtime_loading.to_dict(),
            "condition_names": list(self.condition_names),
            "include_rg": self.include_rg,
            "include_contacts": self.include_contacts,
            "frame_sampling": self.frame_sampling.to_dict(),
            "contact_detection_options": (
                _contact_detection_options_payload(
                    self.contact_detection_options
                )
            ),
            "contact_computation_limits": (
                _contact_computation_limits_payload(
                    self.contact_computation_limits
                )
            ),
            "rg_computed": self.rg_computed,
            "contacts_computed": self.contacts_computed,
            "rg_result_type": _object_type(self.rg_result),
            "contacts_result_type": _object_type(self.contacts_result),
            "condition_count": self.condition_count,
            "issue_count": self.issue_count,
            "issues": [issue.to_dict() for issue in self.issues],
            "passed": self.passed,
        }


@dataclass(frozen=True)
class PreprocessingGraphWorkflowGraphExportIssue:
    """One deterministic Stage 15.5 graph export orchestration issue."""

    kind: str
    message: str
    stage: str | None = None
    field: str | None = None
    path: Path | None = None
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
            "stage",
            _optional_non_empty_string(self.stage, "stage"),
        )
        object.__setattr__(
            self,
            "field",
            _optional_non_empty_string(self.field, "field"),
        )
        _require_optional_path(self.path, "path")
        object.__setattr__(
            self,
            "value",
            _optional_non_empty_string(self.value, "value"),
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe graph export issue dictionary."""
        return {
            "kind": self.kind,
            "message": self.message,
            "stage": self.stage,
            "field": self.field,
            "path": _optional_path_string(self.path),
            "value": self.value,
        }


@dataclass(frozen=True)
class PreprocessingGraphWorkflowGraphExportResult:
    """In-memory Stage 15.5 graph export orchestration result."""

    computation: PreprocessingGraphWorkflowComputationResult
    output_layout: PreprocessingGraphWorkflowOutputLayout
    graph_nodes_csv_path: Path
    graph_edges_csv_path: Path
    graph_json_path: Path
    mapping_result: object | None = None
    nodes_csv_write_result: object | None = None
    edges_csv_write_result: object | None = None
    csv_validation_result: object | None = None
    graph_json_write_result: object | None = None
    graph_export_bundle_result: object | None = None
    issues: tuple[PreprocessingGraphWorkflowGraphExportIssue, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(
            self.computation,
            PreprocessingGraphWorkflowComputationResult,
        ):
            raise ValueError(
                "computation must be "
                "PreprocessingGraphWorkflowComputationResult"
            )
        if not isinstance(
            self.output_layout,
            PreprocessingGraphWorkflowOutputLayout,
        ):
            raise ValueError(
                "output_layout must be "
                "PreprocessingGraphWorkflowOutputLayout"
            )
        _require_path(self.graph_nodes_csv_path, "graph_nodes_csv_path")
        _require_path(self.graph_edges_csv_path, "graph_edges_csv_path")
        _require_path(self.graph_json_path, "graph_json_path")
        if not isinstance(self.issues, tuple):
            raise ValueError(
                "issues must be a tuple of "
                "PreprocessingGraphWorkflowGraphExportIssue"
            )
        for issue in self.issues:
            if not isinstance(
                issue,
                PreprocessingGraphWorkflowGraphExportIssue,
            ):
                raise ValueError(
                    "issues must contain "
                    "PreprocessingGraphWorkflowGraphExportIssue"
                )

    @property
    def mapping_built(self) -> bool:
        """Return whether graph mapping was built successfully."""
        return _stage_result_passed(self.mapping_result)

    @property
    def nodes_csv_written(self) -> bool:
        """Return whether backend graph nodes.csv was written successfully."""
        return _stage_result_passed(self.nodes_csv_write_result)

    @property
    def edges_csv_written(self) -> bool:
        """Return whether backend graph edges.csv was written successfully."""
        return _stage_result_passed(self.edges_csv_write_result)

    @property
    def csv_validated(self) -> bool:
        """Return whether backend graph CSV validation passed."""
        return _stage_result_passed(self.csv_validation_result)

    @property
    def graph_json_written(self) -> bool:
        """Return whether backend graph.json was written successfully."""
        return _stage_result_passed(self.graph_json_write_result)

    @property
    def bundle_built(self) -> bool:
        """Return whether the graph export bundle was built successfully."""
        return _stage_result_passed(self.graph_export_bundle_result)

    @property
    def issue_count(self) -> int:
        """Return the number of graph export orchestration issues."""
        return len(self.issues)

    @property
    def passed(self) -> bool:
        """Return whether graph export orchestration completed cleanly."""
        return (
            self.mapping_result is not None
            and self.mapping_built
            and self.nodes_csv_write_result is not None
            and self.nodes_csv_written
            and self.edges_csv_write_result is not None
            and self.edges_csv_written
            and self.csv_validation_result is not None
            and self.csv_validated
            and self.graph_json_write_result is not None
            and self.graph_json_written
            and self.graph_export_bundle_result is not None
            and self.bundle_built
            and self.issues == ()
        )

    def to_dict(self) -> dict[str, object]:
        """Return JSON-safe metadata without raw Stage 14 result internals."""
        return {
            "computation": self.computation.to_dict(),
            "output_layout": self.output_layout.to_dict(),
            "graph_nodes_csv_path": str(self.graph_nodes_csv_path),
            "graph_edges_csv_path": str(self.graph_edges_csv_path),
            "graph_json_path": str(self.graph_json_path),
            "mapping_built": self.mapping_built,
            "nodes_csv_written": self.nodes_csv_written,
            "edges_csv_written": self.edges_csv_written,
            "csv_validated": self.csv_validated,
            "graph_json_written": self.graph_json_written,
            "bundle_built": self.bundle_built,
            "mapping_result_type": _object_type(self.mapping_result),
            "nodes_csv_write_result_type": _object_type(
                self.nodes_csv_write_result
            ),
            "edges_csv_write_result_type": _object_type(
                self.edges_csv_write_result
            ),
            "csv_validation_result_type": _object_type(
                self.csv_validation_result
            ),
            "graph_json_write_result_type": _object_type(
                self.graph_json_write_result
            ),
            "graph_export_bundle_result_type": _object_type(
                self.graph_export_bundle_result
            ),
            "issue_count": self.issue_count,
            "issues": [issue.to_dict() for issue in self.issues],
            "passed": self.passed,
        }


@dataclass(frozen=True)
class PreprocessingGraphWorkflowScientificCsvExportIssue:
    """One deterministic optional scientific CSV export issue."""

    kind: str
    message: str
    export_name: str | None = None
    stage: str | None = None
    field: str | None = None
    path: Path | None = None
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
            "export_name",
            _optional_non_empty_string(self.export_name, "export_name"),
        )
        object.__setattr__(
            self,
            "stage",
            _optional_non_empty_string(self.stage, "stage"),
        )
        object.__setattr__(
            self,
            "field",
            _optional_non_empty_string(self.field, "field"),
        )
        _require_optional_path(self.path, "path")
        object.__setattr__(
            self,
            "value",
            _optional_non_empty_string(self.value, "value"),
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe scientific CSV export issue dictionary."""
        return {
            "kind": self.kind,
            "message": self.message,
            "export_name": self.export_name,
            "stage": self.stage,
            "field": self.field,
            "path": _optional_path_string(self.path),
            "value": self.value,
        }


@dataclass(frozen=True)
class PreprocessingGraphWorkflowScientificCsvExportResult:
    """Optional scientific CSV side-effect export result."""

    computation: PreprocessingGraphWorkflowComputationResult
    output_layout: PreprocessingGraphWorkflowOutputLayout
    export_rg_timeseries: bool
    export_contact_edges: bool
    export_contacts_perframe: bool
    rg_timeseries_csv_path: Path | None = None
    contact_edges_csv_path: Path | None = None
    contacts_perframe_csv_path: Path | None = None
    rg_timeseries_write_result: object | None = None
    contact_edges_write_result: object | None = None
    contacts_perframe_write_result: object | None = None
    rg_timeseries_validation_result: object | None = None
    contact_edges_validation_result: object | None = None
    contacts_perframe_validation_result: object | None = None
    issues: tuple[
        PreprocessingGraphWorkflowScientificCsvExportIssue,
        ...,
    ] = ()

    def __post_init__(self) -> None:
        if not isinstance(
            self.computation,
            PreprocessingGraphWorkflowComputationResult,
        ):
            raise ValueError(
                "computation must be PreprocessingGraphWorkflowComputationResult"
            )
        if not isinstance(
            self.output_layout,
            PreprocessingGraphWorkflowOutputLayout,
        ):
            raise ValueError(
                "output_layout must be PreprocessingGraphWorkflowOutputLayout"
            )
        for field_name in (
            "export_rg_timeseries",
            "export_contact_edges",
            "export_contacts_perframe",
        ):
            _require_bool(getattr(self, field_name), field_name)
        for field_name in (
            "rg_timeseries_csv_path",
            "contact_edges_csv_path",
            "contacts_perframe_csv_path",
        ):
            _require_optional_path(getattr(self, field_name), field_name)
        if not isinstance(self.issues, tuple):
            raise ValueError(
                "issues must be a tuple of "
                "PreprocessingGraphWorkflowScientificCsvExportIssue"
            )
        for issue in self.issues:
            if not isinstance(
                issue,
                PreprocessingGraphWorkflowScientificCsvExportIssue,
            ):
                raise ValueError(
                    "issues must contain "
                    "PreprocessingGraphWorkflowScientificCsvExportIssue"
                )

    @property
    def skipped(self) -> bool:
        """Return whether no optional scientific CSV export was requested."""
        return not any(self.requested_exports.values())

    @property
    def requested_exports(self) -> dict[str, bool]:
        """Return the requested optional scientific CSV export switches."""
        return {
            "rg_timeseries": self.export_rg_timeseries,
            "contact_edges": self.export_contact_edges,
            "contacts_perframe": self.export_contacts_perframe,
        }

    @property
    def rg_timeseries_written(self) -> bool:
        """Return whether the Rg timeseries CSV writer passed."""
        return _stage_result_passed(self.rg_timeseries_write_result)

    @property
    def contact_edges_written(self) -> bool:
        """Return whether the aggregate contact edges CSV writer passed."""
        return _stage_result_passed(self.contact_edges_write_result)

    @property
    def contacts_perframe_written(self) -> bool:
        """Return whether the contacts per-frame CSV writer passed."""
        return _stage_result_passed(self.contacts_perframe_write_result)

    @property
    def issue_count(self) -> int:
        """Return the number of scientific CSV export issues."""
        return len(self.issues)

    @property
    def passed(self) -> bool:
        """Return whether requested optional scientific CSV exports passed."""
        if self.skipped:
            return self.issues == ()
        return (
            self.issues == ()
            and (
                not self.export_rg_timeseries
                or (
                    self.rg_timeseries_written
                    and _stage_result_passed(
                        self.rg_timeseries_validation_result
                    )
                )
            )
            and (
                not self.export_contact_edges
                or (
                    self.contact_edges_written
                    and _stage_result_passed(
                        self.contact_edges_validation_result
                    )
                )
            )
            and (
                not self.export_contacts_perframe
                or (
                    self.contacts_perframe_written
                    and _stage_result_passed(
                        self.contacts_perframe_validation_result
                    )
                )
            )
        )

    def to_dict(self) -> dict[str, object]:
        """Return JSON-safe optional scientific CSV export metadata."""
        return {
            "stage": "scientific_csv_export",
            "passed": self.passed,
            "skipped": self.skipped,
            "requested_exports": self.requested_exports,
            "rg_timeseries_written": self.rg_timeseries_written,
            "contact_edges_written": self.contact_edges_written,
            "contacts_perframe_written": self.contacts_perframe_written,
            "paths": _scientific_csv_export_paths_payload(self),
            "validation": {
                "rg_timeseries": (
                    _scientific_validation_payload(
                        self.rg_timeseries_validation_result
                    )
                    if self.export_rg_timeseries
                    else None
                ),
                "contact_edges": (
                    _scientific_validation_payload(
                        self.contact_edges_validation_result
                    )
                    if self.export_contact_edges
                    else None
                ),
                "contacts_perframe": (
                    _scientific_validation_payload(
                        self.contacts_perframe_validation_result
                    )
                    if self.export_contacts_perframe
                    else None
                ),
            },
            "issues": [issue.to_dict() for issue in self.issues],
            "issue_count": self.issue_count,
        }


@dataclass(frozen=True)
class PreprocessingGraphWorkflowAnalysisInputExportIssue:
    """One deterministic analysis-ready artifact export issue."""

    kind: str
    message: str
    stage: str | None = None
    field: str | None = None
    path: Path | None = None
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
            "stage",
            _optional_non_empty_string(self.stage, "stage"),
        )
        object.__setattr__(
            self,
            "field",
            _optional_non_empty_string(self.field, "field"),
        )
        _require_optional_path(self.path, "path")
        object.__setattr__(
            self,
            "value",
            _optional_non_empty_string(self.value, "value"),
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe analysis input export issue dictionary."""
        return {
            "kind": self.kind,
            "message": self.message,
            "stage": self.stage,
            "field": self.field,
            "path": _optional_path_string(self.path),
            "value": self.value,
        }


@dataclass(frozen=True)
class PreprocessingGraphWorkflowAnalysisInputExportResult:
    """Root-level analysis-ready Stage 20 preprocessing export result."""

    graph_export: PreprocessingGraphWorkflowGraphExportResult
    output_dir: Path
    residue_tables_result: object | None = None
    protein_contacts_result: object | None = None
    manifest_artifacts_result: object | None = None
    issues: tuple[
        PreprocessingGraphWorkflowAnalysisInputExportIssue,
        ...,
    ] = ()

    def __post_init__(self) -> None:
        if not isinstance(
            self.graph_export,
            PreprocessingGraphWorkflowGraphExportResult,
        ):
            raise ValueError(
                "graph_export must be PreprocessingGraphWorkflowGraphExportResult"
            )
        _require_path(self.output_dir, "output_dir")
        if not isinstance(self.issues, tuple):
            raise ValueError(
                "issues must be a tuple of "
                "PreprocessingGraphWorkflowAnalysisInputExportIssue"
            )
        for issue in self.issues:
            if not isinstance(
                issue,
                PreprocessingGraphWorkflowAnalysisInputExportIssue,
            ):
                raise ValueError(
                    "issues must contain "
                    "PreprocessingGraphWorkflowAnalysisInputExportIssue"
                )

    @property
    def requested(self) -> bool:
        """Return whether this result represents a requested export."""
        return True

    @property
    def skipped(self) -> bool:
        """Return whether this requested export was skipped."""
        return False

    @property
    def residue_tables_written(self) -> bool:
        """Return whether residue table writing passed."""
        return _stage_result_passed(self.residue_tables_result)

    @property
    def protein_contacts_written(self) -> bool:
        """Return whether protein contact artifact writing passed."""
        return _stage_result_passed(self.protein_contacts_result)

    @property
    def manifests_written(self) -> bool:
        """Return whether manifest artifact writing passed."""
        return _stage_result_passed(self.manifest_artifacts_result)

    @property
    def issue_count(self) -> int:
        """Return the number of analysis input export issues."""
        return len(self.issues)

    @property
    def passed(self) -> bool:
        """Return whether every requested analysis-ready artifact was written."""
        return (
            self.graph_export.passed
            and self.residue_tables_result is not None
            and self.residue_tables_written
            and self.protein_contacts_result is not None
            and self.protein_contacts_written
            and self.manifest_artifacts_result is not None
            and self.manifests_written
            and self.issues == ()
        )

    def to_dict(self) -> dict[str, object]:
        """Return compact JSON-safe analysis input export metadata."""
        return {
            "stage": "analysis_input_export",
            "requested": self.requested,
            "skipped": self.skipped,
            "passed": self.passed,
            "output_dir": str(self.output_dir),
            "residue_tables": _json_safe_result_payload(
                self.residue_tables_result
            ),
            "protein_contacts": _json_safe_result_payload(
                self.protein_contacts_result
            ),
            "manifests": _json_safe_result_payload(
                self.manifest_artifacts_result
            ),
            "issues": [issue.to_dict() for issue in self.issues],
            "issue_count": self.issue_count,
        }


@dataclass(frozen=True)
class PreprocessingGraphWorkflowDiagnosticsIssue:
    """One deterministic Stage 15.6 diagnostics orchestration issue."""

    kind: str
    message: str
    stage: str | None = None
    field: str | None = None
    path: Path | None = None
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
            "stage",
            _optional_non_empty_string(self.stage, "stage"),
        )
        object.__setattr__(
            self,
            "field",
            _optional_non_empty_string(self.field, "field"),
        )
        _require_optional_path(self.path, "path")
        object.__setattr__(
            self,
            "value",
            _optional_non_empty_string(self.value, "value"),
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe diagnostics orchestration issue dictionary."""
        return {
            "kind": self.kind,
            "message": self.message,
            "stage": self.stage,
            "field": self.field,
            "path": _optional_path_string(self.path),
            "value": self.value,
        }


@dataclass(frozen=True)
class PreprocessingGraphWorkflowDiagnosticsResult:
    """In-memory Stage 15.6 diagnostics orchestration result."""

    graph_export: PreprocessingGraphWorkflowGraphExportResult
    diagnostics_run_result: object | None = None
    diagnostics_report: object | None = None
    diagnostics_report_json_path: Path | None = None
    diagnostics_report_json_written: bool = False
    issues: tuple[PreprocessingGraphWorkflowDiagnosticsIssue, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(
            self.graph_export,
            PreprocessingGraphWorkflowGraphExportResult,
        ):
            raise ValueError(
                "graph_export must be "
                "PreprocessingGraphWorkflowGraphExportResult"
            )
        _require_optional_path(
            self.diagnostics_report_json_path,
            "diagnostics_report_json_path",
        )
        _require_bool(
            self.diagnostics_report_json_written,
            "diagnostics_report_json_written",
        )
        if not isinstance(self.issues, tuple):
            raise ValueError(
                "issues must be a tuple of "
                "PreprocessingGraphWorkflowDiagnosticsIssue"
            )
        for issue in self.issues:
            if not isinstance(
                issue,
                PreprocessingGraphWorkflowDiagnosticsIssue,
            ):
                raise ValueError(
                    "issues must contain "
                    "PreprocessingGraphWorkflowDiagnosticsIssue"
                )

    @property
    def diagnostics_ran(self) -> bool:
        """Return whether a Stage 14 diagnostics run result is retained."""
        return self.diagnostics_run_result is not None

    @property
    def diagnostics_passed(self) -> bool:
        """Return whether the retained diagnostics run result passed."""
        return _stage_result_passed(self.diagnostics_run_result)

    @property
    def diagnostics_report_built(self) -> bool:
        """Return whether an in-memory diagnostics report is retained."""
        return self.diagnostics_report is not None

    @property
    def issue_count(self) -> int:
        """Return the number of diagnostics orchestration issues."""
        return len(self.issues)

    @property
    def passed(self) -> bool:
        """Return whether diagnostics orchestration completed cleanly."""
        return (
            self.graph_export.passed
            and self.diagnostics_ran
            and self.diagnostics_passed
            and self.diagnostics_report_built
            and (
                self.diagnostics_report_json_path is None
                or self.diagnostics_report_json_written
            )
            and self.issues == ()
        )

    def to_dict(self) -> dict[str, object]:
        """Return JSON-safe metadata without raw diagnostics internals."""
        return {
            "graph_export": self.graph_export.to_dict(),
            "diagnostics_ran": self.diagnostics_ran,
            "diagnostics_passed": self.diagnostics_passed,
            "diagnostics_report_built": self.diagnostics_report_built,
            "diagnostics_report_json_path": _optional_path_string(
                self.diagnostics_report_json_path
            ),
            "diagnostics_report_json_written": (
                self.diagnostics_report_json_written
            ),
            "diagnostics_run": _diagnostics_run_payload(
                self.diagnostics_run_result
            ),
            "diagnostics_run_result_type": _object_type(
                self.diagnostics_run_result
            ),
            "diagnostics_report_type": _object_type(self.diagnostics_report),
            "issue_count": self.issue_count,
            "issues": [issue.to_dict() for issue in self.issues],
            "passed": self.passed,
        }


@dataclass(frozen=True)
class PreprocessingGraphWorkflowReferenceComparisonIssue:
    """One deterministic Stage 15.7 reference comparison issue."""

    kind: str
    message: str
    stage: str | None = None
    field: str | None = None
    path: Path | None = None
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
            "stage",
            _optional_non_empty_string(self.stage, "stage"),
        )
        object.__setattr__(
            self,
            "field",
            _optional_non_empty_string(self.field, "field"),
        )
        _require_optional_path(self.path, "path")
        object.__setattr__(
            self,
            "value",
            _optional_non_empty_string(self.value, "value"),
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe reference comparison issue dictionary."""
        return {
            "kind": self.kind,
            "message": self.message,
            "stage": self.stage,
            "field": self.field,
            "path": _optional_path_string(self.path),
            "value": self.value,
        }


@dataclass(frozen=True)
class PreprocessingGraphWorkflowReferenceComparisonResult:
    """In-memory Stage 15.7 reference comparison orchestration result."""

    graph_export: PreprocessingGraphWorkflowGraphExportResult
    options: PreprocessingGraphWorkflowOptions
    output_layout: PreprocessingGraphWorkflowOutputLayout
    reference_comparison_enabled: bool
    reference_comparison_skipped: bool = False
    reference_comparison_input: object | None = None
    reference_comparison_result: object | None = None
    reference_comparison_json_path: Path | None = None
    reference_comparison_json_written: bool = False
    issues: tuple[PreprocessingGraphWorkflowReferenceComparisonIssue, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(
            self.graph_export,
            PreprocessingGraphWorkflowGraphExportResult,
        ):
            raise ValueError(
                "graph_export must be "
                "PreprocessingGraphWorkflowGraphExportResult"
            )
        if not isinstance(self.options, PreprocessingGraphWorkflowOptions):
            raise ValueError(
                "options must be PreprocessingGraphWorkflowOptions"
            )
        if not isinstance(
            self.output_layout,
            PreprocessingGraphWorkflowOutputLayout,
        ):
            raise ValueError(
                "output_layout must be "
                "PreprocessingGraphWorkflowOutputLayout"
            )
        _require_bool(
            self.reference_comparison_enabled,
            "reference_comparison_enabled",
        )
        _require_bool(
            self.reference_comparison_skipped,
            "reference_comparison_skipped",
        )
        _require_optional_path(
            self.reference_comparison_json_path,
            "reference_comparison_json_path",
        )
        _require_bool(
            self.reference_comparison_json_written,
            "reference_comparison_json_written",
        )
        if not isinstance(self.issues, tuple):
            raise ValueError(
                "issues must be a tuple of "
                "PreprocessingGraphWorkflowReferenceComparisonIssue"
            )
        for issue in self.issues:
            if not isinstance(
                issue,
                PreprocessingGraphWorkflowReferenceComparisonIssue,
            ):
                raise ValueError(
                    "issues must contain "
                    "PreprocessingGraphWorkflowReferenceComparisonIssue"
                )

    @property
    def graph_export_passed(self) -> bool:
        """Return whether the Stage 15.5 graph export result passed."""
        return self.graph_export.passed

    @property
    def reference_paths_provided(self) -> bool:
        """Return whether all explicit reference artifact paths are present."""
        return _missing_reference_path_fields(self.options) == ()

    @property
    def reference_comparison_ran(self) -> bool:
        """Return whether the accepted Stage 14 comparison result is retained."""
        return self.reference_comparison_result is not None

    @property
    def reference_comparison_passed(self) -> bool:
        """Return whether the retained Stage 14 comparison result passed."""
        return _stage_result_passed(self.reference_comparison_result)

    @property
    def issue_count(self) -> int:
        """Return the number of reference comparison orchestration issues."""
        return len(self.issues)

    @property
    def passed(self) -> bool:
        """Return whether reference comparison orchestration completed cleanly."""
        if self.reference_comparison_skipped:
            return (
                not self.reference_comparison_enabled
                and self.reference_comparison_result is None
                and not self.reference_comparison_json_written
                and self.issues == ()
            )
        return (
            self.reference_comparison_enabled
            and self.graph_export_passed
            and self.reference_paths_provided
            and self.reference_comparison_ran
            and self.reference_comparison_passed
            and (
                self.reference_comparison_json_path is None
                or self.reference_comparison_json_written
            )
            and self.issues == ()
        )

    def to_dict(self) -> dict[str, object]:
        """Return JSON-safe metadata without raw comparison internals."""
        return {
            "graph_export": self.graph_export.to_dict(),
            "options": self.options.to_dict(),
            "output_layout": self.output_layout.to_dict(),
            "reference_comparison_enabled": (
                self.reference_comparison_enabled
            ),
            "reference_comparison_skipped": (
                self.reference_comparison_skipped
            ),
            "graph_export_passed": self.graph_export_passed,
            "reference_paths_provided": self.reference_paths_provided,
            "reference_comparison_ran": self.reference_comparison_ran,
            "reference_comparison_passed": self.reference_comparison_passed,
            "reference_comparison_json_path": _optional_path_string(
                self.reference_comparison_json_path
            ),
            "reference_comparison_json_written": (
                self.reference_comparison_json_written
            ),
            "reference_comparison_input_type": _object_type(
                self.reference_comparison_input
            ),
            "reference_comparison_result_type": _object_type(
                self.reference_comparison_result
            ),
            "comparison_metadata": _reference_comparison_metadata(
                self.reference_comparison_result
            ),
            "issue_count": self.issue_count,
            "issues": [issue.to_dict() for issue in self.issues],
            "passed": self.passed,
        }


@dataclass(frozen=True)
class PreprocessingGraphWorkflowPlan:
    """In-memory plan for future preprocessing graph export orchestration."""

    options: PreprocessingGraphWorkflowOptions
    output_layout: PreprocessingGraphWorkflowOutputLayout
    planned_steps: tuple[str, ...]
    issues: tuple[PreprocessingGraphWorkflowIssue, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.options, PreprocessingGraphWorkflowOptions):
            raise ValueError(
                "options must be PreprocessingGraphWorkflowOptions"
            )
        if not isinstance(
            self.output_layout,
            PreprocessingGraphWorkflowOutputLayout,
        ):
            raise ValueError(
                "output_layout must be "
                "PreprocessingGraphWorkflowOutputLayout"
            )
        if not isinstance(self.planned_steps, tuple):
            raise ValueError("planned_steps must be a tuple of strings")
        object.__setattr__(
            self,
            "planned_steps",
            tuple(
                _non_empty_string(step, "planned_steps")
                for step in self.planned_steps
            ),
        )
        if not isinstance(self.issues, tuple):
            raise ValueError(
                "issues must be a tuple of PreprocessingGraphWorkflowIssue"
            )
        for issue in self.issues:
            if not isinstance(issue, PreprocessingGraphWorkflowIssue):
                raise ValueError(
                    "issues must contain PreprocessingGraphWorkflowIssue"
                )

    @property
    def passed(self) -> bool:
        """Return whether the workflow plan has no planning issues."""
        return self.issues == ()

    @property
    def issue_count(self) -> int:
        """Return the number of planning issues."""
        return len(self.issues)

    @property
    def planned_step_count(self) -> int:
        """Return the number of planned step names."""
        return len(self.planned_steps)

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-safe workflow plan dictionary."""
        return {
            "options": self.options.to_dict(),
            "output_layout": self.output_layout.to_dict(),
            "planned_steps": list(self.planned_steps),
            "planned_step_count": self.planned_step_count,
            "issues": [issue.to_dict() for issue in self.issues],
            "issue_count": self.issue_count,
            "passed": self.passed,
        }


def build_preprocessing_graph_workflow_plan(
    options: PreprocessingGraphWorkflowOptions,
) -> PreprocessingGraphWorkflowPlan:
    """Build an in-memory workflow plan without executing any step."""
    if not isinstance(options, PreprocessingGraphWorkflowOptions):
        raise ValueError("options must be PreprocessingGraphWorkflowOptions")

    output_layout = _build_output_layout(options)
    planned_steps = _build_planned_steps(options)
    issues = _build_planning_issues(options)

    return PreprocessingGraphWorkflowPlan(
        options=options,
        output_layout=output_layout,
        planned_steps=planned_steps,
        issues=issues,
    )


def check_preprocessing_graph_workflow_manifest_readiness(
    manifest_path: str | Path,
    *,
    expected_condition_names: Iterable[str] | None = ("normal", "tumor"),
) -> PreprocessingGraphWorkflowManifestReadinessResult:
    """Check local manifest readiness without loading runtime objects."""
    normalized_manifest_path = Path(manifest_path)
    expected_names = _normalize_expected_condition_names(
        expected_condition_names
    )
    expected_count = (
        None if expected_names is None else len(expected_names)
    )

    if not normalized_manifest_path.exists():
        return PreprocessingGraphWorkflowManifestReadinessResult(
            manifest_path=normalized_manifest_path,
            manifest_loaded=False,
            manifest_paths_valid=False,
            condition_names=(),
            expected_condition_count=expected_count,
            issues=(
                PreprocessingGraphWorkflowManifestReadinessIssue(
                    kind="manifest_path_missing",
                    message=(
                        "Manifest path does not exist: "
                        f"{normalized_manifest_path}"
                    ),
                    field="manifest_path",
                    path=normalized_manifest_path,
                ),
            ),
        )

    if normalized_manifest_path.is_dir():
        return PreprocessingGraphWorkflowManifestReadinessResult(
            manifest_path=normalized_manifest_path,
            manifest_loaded=False,
            manifest_paths_valid=False,
            condition_names=(),
            expected_condition_count=expected_count,
            issues=(
                PreprocessingGraphWorkflowManifestReadinessIssue(
                    kind="manifest_path_is_directory",
                    message=(
                        "Manifest path is a directory: "
                        f"{normalized_manifest_path}"
                    ),
                    field="manifest_path",
                    path=normalized_manifest_path,
                ),
            ),
        )

    try:
        manifest = _manifest_loader()(normalized_manifest_path)
    except Exception as exc:
        return PreprocessingGraphWorkflowManifestReadinessResult(
            manifest_path=normalized_manifest_path,
            manifest_loaded=False,
            manifest_paths_valid=False,
            condition_names=(),
            expected_condition_count=expected_count,
            issues=(
                _manifest_load_issue(normalized_manifest_path, exc),
            ),
        )

    condition_names = manifest.condition_names()

    try:
        validation_report = _manifest_path_validator()(
            manifest,
            base_dir=normalized_manifest_path.parent,
        )
    except Exception as exc:
        return PreprocessingGraphWorkflowManifestReadinessResult(
            manifest_path=normalized_manifest_path,
            manifest_loaded=True,
            manifest_paths_valid=False,
            condition_names=condition_names,
            expected_condition_count=expected_count,
            issues=(
                PreprocessingGraphWorkflowManifestReadinessIssue(
                    kind="unexpected_error",
                    message=(
                        "Manifest path validation failed unexpectedly: "
                        f"{exc.__class__.__name__}"
                    ),
                    field="manifest_paths",
                ),
            ),
        )

    issues = list(_path_validation_issues(validation_report))
    input_paths = tuple(
        checked_path.path for checked_path in validation_report.checked_paths
    )
    if expected_names is not None:
        issues.extend(
            _condition_readiness_issues(
                condition_names=condition_names,
                expected_condition_names=expected_names,
            )
        )

    return PreprocessingGraphWorkflowManifestReadinessResult(
        manifest_path=normalized_manifest_path,
        manifest_loaded=True,
        manifest_paths_valid=validation_report.passed,
        condition_names=condition_names,
        expected_condition_count=expected_count,
        input_paths=input_paths,
        issues=tuple(issues),
    )


def load_preprocessing_graph_workflow_condition_runtimes(
    manifest_path: str | Path,
    *,
    expected_condition_names: Iterable[str] | None = ("normal", "tumor"),
) -> PreprocessingGraphWorkflowRuntimeLoadingResult:
    """Load manifest condition runtimes after Stage 15.2 readiness passes."""
    normalized_manifest_path = Path(manifest_path)
    expected_names = _normalize_expected_condition_names(
        expected_condition_names
    )
    readiness = check_preprocessing_graph_workflow_manifest_readiness(
        normalized_manifest_path,
        expected_condition_names=expected_names,
    )

    if not readiness.passed:
        return PreprocessingGraphWorkflowRuntimeLoadingResult(
            manifest_path=normalized_manifest_path,
            manifest_readiness=readiness,
            condition_names=(),
            expected_condition_names=expected_names,
            issues=(
                PreprocessingGraphWorkflowRuntimeLoadingIssue(
                    kind="manifest_readiness_failed",
                    message=(
                        "Manifest readiness failed; runtime loading was not "
                        "attempted."
                    ),
                    field="manifest_path",
                    path=normalized_manifest_path,
                ),
            ),
        )

    try:
        manifest = _manifest_loader()(normalized_manifest_path)
        runtime_load_result = _manifest_runtime_loader()(
            manifest,
            base_dir=normalized_manifest_path.parent,
        )
    except Exception as exc:
        return PreprocessingGraphWorkflowRuntimeLoadingResult(
            manifest_path=normalized_manifest_path,
            manifest_readiness=readiness,
            condition_names=(),
            expected_condition_names=expected_names,
            issues=(
                PreprocessingGraphWorkflowRuntimeLoadingIssue(
                    kind="runtime_load_failed",
                    message=(
                        "Manifest runtime loading failed unexpectedly: "
                        f"{exc.__class__.__name__}."
                    ),
                    field="condition_runtime",
                ),
            ),
        )

    condition_names, issues = _runtime_loading_metadata_issues(
        runtime_load_result,
        expected_names,
    )

    return PreprocessingGraphWorkflowRuntimeLoadingResult(
        manifest_path=normalized_manifest_path,
        manifest_readiness=readiness,
        condition_names=condition_names,
        expected_condition_names=expected_names,
        runtime_load_result=runtime_load_result,
        issues=issues,
    )


def compute_preprocessing_graph_workflow_rg_contacts(
    runtime_loading: PreprocessingGraphWorkflowRuntimeLoadingResult,
    *,
    include_rg: bool = True,
    include_contacts: bool = True,
    contact_options: PreprocessingContactDetectionOptions | None = None,
    contact_computation_limits: PreprocessingContactComputationLimits | None = None,
    frame_sampling: PreprocessingFrameSamplingOptions | None = None,
    progress_callback: ContactProgressCallback | None = None,
) -> PreprocessingGraphWorkflowComputationResult:
    """Orchestrate accepted manifest-level Rg and contacts computations."""
    if not isinstance(
        runtime_loading,
        PreprocessingGraphWorkflowRuntimeLoadingResult,
    ):
        raise ValueError(
            "runtime_loading must be "
            "PreprocessingGraphWorkflowRuntimeLoadingResult"
        )
    _require_bool(include_rg, "include_rg")
    _require_bool(include_contacts, "include_contacts")
    selected_frame_sampling = _frame_sampling_options(frame_sampling)
    selected_contact_options = _contact_detection_options(contact_options)
    selected_contact_limits = _contact_computation_limits(
        contact_computation_limits
    )

    condition_names = runtime_loading.condition_names
    issues: list[PreprocessingGraphWorkflowComputationIssue] = []
    rg_result: object | None = None
    contacts_result: object | None = None
    runtime_result = runtime_loading.runtime_load_result

    if runtime_result is None:
        if _runtime_loading_metadata_passed_without_raw_result(
            runtime_loading
        ):
            issues.append(
                PreprocessingGraphWorkflowComputationIssue(
                    kind="runtime_load_result_missing",
                    message=(
                        "Runtime loading metadata passed but no raw runtime "
                        "result exists."
                    ),
                    stage="runtime_loading",
                    field="runtime_load_result",
                )
            )
        else:
            issues.append(
                PreprocessingGraphWorkflowComputationIssue(
                    kind="runtime_loading_failed",
                    message=(
                        "Runtime loading did not pass; computations were not "
                        "attempted."
                    ),
                    stage="runtime_loading",
                    field="runtime_loading",
                )
            )
        return PreprocessingGraphWorkflowComputationResult(
            runtime_loading=runtime_loading,
            condition_names=condition_names,
            include_rg=include_rg,
            include_contacts=include_contacts,
            frame_sampling=selected_frame_sampling,
            contact_detection_options=selected_contact_options,
            contact_computation_limits=selected_contact_limits,
            issues=tuple(issues),
        )

    if not runtime_loading.passed:
        issues.append(
            PreprocessingGraphWorkflowComputationIssue(
                kind="runtime_loading_failed",
                message=(
                    "Runtime loading did not pass; computations were not "
                    "attempted."
                ),
                stage="runtime_loading",
                field="runtime_loading",
            )
        )
        return PreprocessingGraphWorkflowComputationResult(
            runtime_loading=runtime_loading,
            condition_names=condition_names,
            include_rg=include_rg,
            include_contacts=include_contacts,
            frame_sampling=selected_frame_sampling,
            contact_detection_options=selected_contact_options,
            contact_computation_limits=selected_contact_limits,
            issues=tuple(issues),
        )

    if not include_rg and not include_contacts:
        issues.append(
            PreprocessingGraphWorkflowComputationIssue(
                kind="no_computation_targets_enabled",
                message="At least one computation target must be enabled.",
                field="computation_targets",
            )
        )
        return PreprocessingGraphWorkflowComputationResult(
            runtime_loading=runtime_loading,
            condition_names=condition_names,
            include_rg=include_rg,
            include_contacts=include_contacts,
            frame_sampling=selected_frame_sampling,
            contact_detection_options=selected_contact_options,
            contact_computation_limits=selected_contact_limits,
            issues=tuple(issues),
        )

    if include_rg:
        try:
            if frame_sampling is None:
                rg_result = _manifest_rg_computer()(runtime_result)
            else:
                rg_result = _manifest_rg_computer()(
                    runtime_result,
                    frame_sampling=selected_frame_sampling,
                )
        except Exception as exc:
            issues.append(
                _computation_exception_issue(
                    kind="rg_computation_failed",
                    stage="rg",
                    field="rg_result",
                    exc=exc,
                )
            )
        else:
            _append_failed_computation_issue(
                result=rg_result,
                kind="rg_computation_failed",
                stage="rg",
                field="rg_result",
                issues=issues,
            )

    if include_contacts:
        try:
            contact_kwargs: dict[str, object] = {}
            if not _contact_detection_options_are_default(
                selected_contact_options
            ):
                contact_kwargs["options"] = selected_contact_options
            if not _contact_computation_limits_are_default(
                selected_contact_limits
            ):
                contact_kwargs["computation_limits"] = selected_contact_limits
            if frame_sampling is not None:
                contact_kwargs["frame_sampling"] = selected_frame_sampling
            if progress_callback is not None:
                contact_kwargs["progress_callback"] = progress_callback
            contacts_result = _manifest_contacts_computer()(
                runtime_result,
                **contact_kwargs,
            )
        except Exception as exc:
            issues.append(
                _computation_exception_issue(
                    kind="contacts_computation_failed",
                    stage="contacts",
                    field="contacts_result",
                    exc=exc,
                )
            )
        else:
            _append_failed_computation_issue(
                result=contacts_result,
                kind="contacts_computation_failed",
                stage="contacts",
                field="contacts_result",
                issues=issues,
            )

    return PreprocessingGraphWorkflowComputationResult(
        runtime_loading=runtime_loading,
        condition_names=condition_names,
        include_rg=include_rg,
        include_contacts=include_contacts,
        frame_sampling=selected_frame_sampling,
        contact_detection_options=selected_contact_options,
        contact_computation_limits=selected_contact_limits,
        rg_result=rg_result,
        contacts_result=contacts_result,
        issues=tuple(issues),
    )


def export_preprocessing_graph_workflow_artifacts(
    computation: PreprocessingGraphWorkflowComputationResult,
    output_layout: PreprocessingGraphWorkflowOutputLayout,
    *,
    create_parent_directories: bool = True,
) -> PreprocessingGraphWorkflowGraphExportResult:
    """Orchestrate Stage 14 graph export APIs from a Stage 15.4 result."""
    if not isinstance(
        computation,
        PreprocessingGraphWorkflowComputationResult,
    ):
        raise ValueError(
            "computation must be PreprocessingGraphWorkflowComputationResult"
        )
    if not isinstance(output_layout, PreprocessingGraphWorkflowOutputLayout):
        raise ValueError(
            "output_layout must be PreprocessingGraphWorkflowOutputLayout"
        )
    _require_bool(create_parent_directories, "create_parent_directories")

    if not computation.passed:
        return _graph_export_result(
            computation,
            output_layout,
            issues=(
                PreprocessingGraphWorkflowGraphExportIssue(
                    kind="computation_failed",
                    message=(
                        "Stage 15.4 computation did not pass; graph export "
                        "was not attempted."
                    ),
                    stage="computation",
                    field="computation",
                ),
            ),
        )

    if not computation.contacts_computed or computation.contacts_result is None:
        return _graph_export_result(
            computation,
            output_layout,
            issues=(
                PreprocessingGraphWorkflowGraphExportIssue(
                    kind="contacts_result_missing",
                    message=(
                        "Stage 15.4 computation did not retain a contacts "
                        "result for graph export."
                    ),
                    stage="contacts",
                    field="contacts_result",
                ),
            ),
        )

    contacts_issue = _contacts_result_invalid_issue(computation.contacts_result)
    if contacts_issue is not None:
        return _graph_export_result(
            computation,
            output_layout,
            issues=(contacts_issue,),
        )

    layout_issue = _graph_output_layout_issue(output_layout)
    if layout_issue is not None:
        return _graph_export_result(
            computation,
            output_layout,
            issues=(layout_issue,),
        )

    graph_directory = output_layout.graph_nodes_csv_path.parent
    if create_parent_directories:
        try:
            graph_directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return _graph_export_result(
                computation,
                output_layout,
                issues=(
                    PreprocessingGraphWorkflowGraphExportIssue(
                        kind="graph_output_directory_failed",
                        message=(
                            "Graph output directory could not be created: "
                            f"{exc.__class__.__name__}."
                        ),
                        stage="graph_export",
                        field="graph_directory",
                        path=graph_directory,
                    ),
                ),
            )

    try:
        mapping_result = _graph_export_mapping_builder()(
            computation.contacts_result
        )
    except Exception as exc:
        return _graph_export_result(
            computation,
            output_layout,
            issues=(
                _graph_export_exception_issue(
                    kind="graph_mapping_failed",
                    stage="graph_mapping",
                    field="contacts_result",
                    exc=exc,
                ),
            ),
        )
    if not _stage_result_passed(mapping_result):
        return _graph_export_result(
            computation,
            output_layout,
            mapping_result=mapping_result,
            issues=(
                _graph_export_failed_issue(
                    kind="graph_mapping_failed",
                    stage="graph_mapping",
                    field="mapping_result",
                    result=mapping_result,
                ),
            ),
        )

    try:
        nodes_csv_write_result = _graph_nodes_csv_writer()(
            mapping_result,
            output_layout.graph_nodes_csv_path,
        )
    except Exception as exc:
        return _graph_export_result(
            computation,
            output_layout,
            mapping_result=mapping_result,
            issues=(
                _graph_export_exception_issue(
                    kind="graph_nodes_csv_write_failed",
                    stage="graph_nodes_csv",
                    field="graph_nodes_csv_path",
                    path=output_layout.graph_nodes_csv_path,
                    exc=exc,
                ),
            ),
        )
    if not _stage_result_passed(nodes_csv_write_result):
        return _graph_export_result(
            computation,
            output_layout,
            mapping_result=mapping_result,
            nodes_csv_write_result=nodes_csv_write_result,
            issues=(
                _graph_export_failed_issue(
                    kind="graph_nodes_csv_write_failed",
                    stage="graph_nodes_csv",
                    field="nodes_csv_write_result",
                    path=output_layout.graph_nodes_csv_path,
                    result=nodes_csv_write_result,
                ),
            ),
        )

    try:
        edges_csv_write_result = _graph_edges_csv_writer()(
            mapping_result,
            output_layout.graph_edges_csv_path,
        )
    except Exception as exc:
        return _graph_export_result(
            computation,
            output_layout,
            mapping_result=mapping_result,
            nodes_csv_write_result=nodes_csv_write_result,
            issues=(
                _graph_export_exception_issue(
                    kind="graph_edges_csv_write_failed",
                    stage="graph_edges_csv",
                    field="graph_edges_csv_path",
                    path=output_layout.graph_edges_csv_path,
                    exc=exc,
                ),
            ),
        )
    if not _stage_result_passed(edges_csv_write_result):
        return _graph_export_result(
            computation,
            output_layout,
            mapping_result=mapping_result,
            nodes_csv_write_result=nodes_csv_write_result,
            edges_csv_write_result=edges_csv_write_result,
            issues=(
                _graph_export_failed_issue(
                    kind="graph_edges_csv_write_failed",
                    stage="graph_edges_csv",
                    field="edges_csv_write_result",
                    path=output_layout.graph_edges_csv_path,
                    result=edges_csv_write_result,
                ),
            ),
        )

    try:
        csv_validation_result = _graph_csv_validator()(
            output_layout.graph_nodes_csv_path,
            output_layout.graph_edges_csv_path,
        )
    except Exception as exc:
        return _graph_export_result(
            computation,
            output_layout,
            mapping_result=mapping_result,
            nodes_csv_write_result=nodes_csv_write_result,
            edges_csv_write_result=edges_csv_write_result,
            issues=(
                _graph_export_exception_issue(
                    kind="graph_csv_validation_failed",
                    stage="graph_csv_validation",
                    field="graph_csv_paths",
                    exc=exc,
                ),
            ),
        )
    if not _stage_result_passed(csv_validation_result):
        return _graph_export_result(
            computation,
            output_layout,
            mapping_result=mapping_result,
            nodes_csv_write_result=nodes_csv_write_result,
            edges_csv_write_result=edges_csv_write_result,
            csv_validation_result=csv_validation_result,
            issues=(
                _graph_export_failed_issue(
                    kind="graph_csv_validation_failed",
                    stage="graph_csv_validation",
                    field="csv_validation_result",
                    result=csv_validation_result,
                ),
            ),
        )

    try:
        graph_json_write_result = _graph_json_writer()(
            output_layout.graph_nodes_csv_path,
            output_layout.graph_edges_csv_path,
            output_layout.graph_json_path,
        )
    except Exception as exc:
        return _graph_export_result(
            computation,
            output_layout,
            mapping_result=mapping_result,
            nodes_csv_write_result=nodes_csv_write_result,
            edges_csv_write_result=edges_csv_write_result,
            csv_validation_result=csv_validation_result,
            issues=(
                _graph_export_exception_issue(
                    kind="graph_json_write_failed",
                    stage="graph_json",
                    field="graph_json_path",
                    path=output_layout.graph_json_path,
                    exc=exc,
                ),
            ),
        )
    if not _stage_result_passed(graph_json_write_result):
        return _graph_export_result(
            computation,
            output_layout,
            mapping_result=mapping_result,
            nodes_csv_write_result=nodes_csv_write_result,
            edges_csv_write_result=edges_csv_write_result,
            csv_validation_result=csv_validation_result,
            graph_json_write_result=graph_json_write_result,
            issues=(
                _graph_export_failed_issue(
                    kind="graph_json_write_failed",
                    stage="graph_json",
                    field="graph_json_write_result",
                    path=output_layout.graph_json_path,
                    result=graph_json_write_result,
                ),
            ),
        )

    try:
        graph_export_bundle_result = _graph_export_bundle_builder()(
            output_layout.graph_nodes_csv_path,
            output_layout.graph_edges_csv_path,
            output_layout.graph_json_path,
        )
    except Exception as exc:
        return _graph_export_result(
            computation,
            output_layout,
            mapping_result=mapping_result,
            nodes_csv_write_result=nodes_csv_write_result,
            edges_csv_write_result=edges_csv_write_result,
            csv_validation_result=csv_validation_result,
            graph_json_write_result=graph_json_write_result,
            issues=(
                _graph_export_exception_issue(
                    kind="graph_bundle_failed",
                    stage="graph_export_bundle",
                    field="graph_export_bundle_result",
                    exc=exc,
                ),
            ),
        )
    if not _stage_result_passed(graph_export_bundle_result):
        return _graph_export_result(
            computation,
            output_layout,
            mapping_result=mapping_result,
            nodes_csv_write_result=nodes_csv_write_result,
            edges_csv_write_result=edges_csv_write_result,
            csv_validation_result=csv_validation_result,
            graph_json_write_result=graph_json_write_result,
            graph_export_bundle_result=graph_export_bundle_result,
            issues=(
                _graph_export_failed_issue(
                    kind="graph_bundle_failed",
                    stage="graph_export_bundle",
                    field="graph_export_bundle_result",
                    result=graph_export_bundle_result,
                ),
            ),
        )

    return _graph_export_result(
        computation,
        output_layout,
        mapping_result=mapping_result,
        nodes_csv_write_result=nodes_csv_write_result,
        edges_csv_write_result=edges_csv_write_result,
        csv_validation_result=csv_validation_result,
        graph_json_write_result=graph_json_write_result,
        graph_export_bundle_result=graph_export_bundle_result,
    )


def export_preprocessing_graph_workflow_scientific_csvs(
    computation_result: PreprocessingGraphWorkflowComputationResult,
    output_layout: PreprocessingGraphWorkflowOutputLayout,
    *,
    export_rg_timeseries: bool = False,
    export_contact_edges: bool = False,
    export_contacts_perframe: bool = False,
) -> PreprocessingGraphWorkflowScientificCsvExportResult:
    """Export requested scientific CSV side artifacts from Stage 15.4 results."""
    if not isinstance(
        computation_result,
        PreprocessingGraphWorkflowComputationResult,
    ):
        raise ValueError(
            "computation_result must be "
            "PreprocessingGraphWorkflowComputationResult"
        )
    if not isinstance(output_layout, PreprocessingGraphWorkflowOutputLayout):
        raise ValueError(
            "output_layout must be PreprocessingGraphWorkflowOutputLayout"
        )
    for field_name, value in (
        ("export_rg_timeseries", export_rg_timeseries),
        ("export_contact_edges", export_contact_edges),
        ("export_contacts_perframe", export_contacts_perframe),
    ):
        _require_bool(value, field_name)

    if not any(
        (
            export_rg_timeseries,
            export_contact_edges,
            export_contacts_perframe,
        )
    ):
        return _scientific_csv_export_result(
            computation_result,
            output_layout,
            export_rg_timeseries=export_rg_timeseries,
            export_contact_edges=export_contact_edges,
            export_contacts_perframe=export_contacts_perframe,
        )

    issues: list[PreprocessingGraphWorkflowScientificCsvExportIssue] = []
    rg_timeseries_write_result: object | None = None
    contact_edges_write_result: object | None = None
    contacts_perframe_write_result: object | None = None
    rg_timeseries_validation_result: object | None = None
    contact_edges_validation_result: object | None = None
    contacts_perframe_validation_result: object | None = None

    if export_rg_timeseries:
        rg_timeseries_write_result, rg_timeseries_validation_result = (
            _export_rg_timeseries_scientific_csv(
                computation_result,
                output_layout,
                issues,
            )
        )

    if export_contact_edges or export_contacts_perframe:
        contacts_result_issue = _contacts_scientific_source_result_issue(
            computation_result.contacts_result
        )
        if contacts_result_issue is not None:
            issues.append(contacts_result_issue)
        else:
            if export_contact_edges:
                contact_edges_write_result, contact_edges_validation_result = (
                    _export_contact_edges_scientific_csv(
                        computation_result,
                        output_layout,
                        issues,
                    )
                )
            if export_contacts_perframe:
                (
                    contacts_perframe_write_result,
                    contacts_perframe_validation_result,
                ) = _export_contacts_perframe_scientific_csv(
                    computation_result,
                    output_layout,
                    issues,
                )

    return _scientific_csv_export_result(
        computation_result,
        output_layout,
        export_rg_timeseries=export_rg_timeseries,
        export_contact_edges=export_contact_edges,
        export_contacts_perframe=export_contacts_perframe,
        rg_timeseries_write_result=rg_timeseries_write_result,
        contact_edges_write_result=contact_edges_write_result,
        contacts_perframe_write_result=contacts_perframe_write_result,
        rg_timeseries_validation_result=rg_timeseries_validation_result,
        contact_edges_validation_result=contact_edges_validation_result,
        contacts_perframe_validation_result=contacts_perframe_validation_result,
        issues=tuple(issues),
    )


def export_preprocessing_graph_workflow_analysis_inputs(
    graph_export: PreprocessingGraphWorkflowGraphExportResult,
    output_dir: str | Path | None = None,
) -> PreprocessingGraphWorkflowAnalysisInputExportResult:
    """Write root-level Stage 20 artifacts accepted by ``mania analyze``."""
    if not isinstance(
        graph_export,
        PreprocessingGraphWorkflowGraphExportResult,
    ):
        raise ValueError(
            "graph_export must be PreprocessingGraphWorkflowGraphExportResult"
        )
    selected_output_dir = (
        graph_export.output_layout.output_dir
        if output_dir is None
        else Path(output_dir)
    )

    if not graph_export.passed:
        return _analysis_input_export_result(
            graph_export,
            selected_output_dir,
            issues=(
                PreprocessingGraphWorkflowAnalysisInputExportIssue(
                    kind="graph_export_failed",
                    message=(
                        "Stage 15.5 graph export did not pass; analysis-ready "
                        "artifact export was not attempted."
                    ),
                    stage="graph_export",
                    field="graph_export",
                ),
            ),
        )

    mapping_result = graph_export.mapping_result
    if mapping_result is None or not _stage_result_passed(mapping_result):
        return _analysis_input_export_result(
            graph_export,
            selected_output_dir,
            issues=(
                PreprocessingGraphWorkflowAnalysisInputExportIssue(
                    kind="mapping_result_missing",
                    message=(
                        "Graph export did not retain a passed mapping result "
                        "for analysis-ready artifact export."
                    ),
                    stage="graph_export",
                    field="mapping_result",
                    value=_object_type(mapping_result),
                ),
            ),
        )

    contacts_result = graph_export.computation.contacts_result
    if contacts_result is None or not _stage_result_passed(contacts_result):
        return _analysis_input_export_result(
            graph_export,
            selected_output_dir,
            issues=(
                PreprocessingGraphWorkflowAnalysisInputExportIssue(
                    kind="contacts_result_missing",
                    message=(
                        "Computation did not retain a passed contacts result "
                        "for analysis-ready artifact export."
                    ),
                    stage="computation",
                    field="contacts_result",
                    value=_object_type(contacts_result),
                ),
            ),
        )

    try:
        residue_tables_result = _residue_tables_csv_writer()(
            mapping_result,
            selected_output_dir,
        )
    except Exception as exc:
        return _analysis_input_export_result(
            graph_export,
            selected_output_dir,
            issues=(
                _analysis_input_exception_issue(
                    kind="residue_table_export_failed",
                    stage="residue_tables",
                    field="residue_tables_result",
                    output_dir=selected_output_dir,
                    exc=exc,
                ),
            ),
        )
    if not _stage_result_passed(residue_tables_result):
        return _analysis_input_export_result(
            graph_export,
            selected_output_dir,
            residue_tables_result=residue_tables_result,
            issues=(
                _analysis_input_failed_issue(
                    kind="residue_table_export_failed",
                    stage="residue_tables",
                    field="residue_tables_result",
                    output_dir=selected_output_dir,
                    result=residue_tables_result,
                ),
            ),
        )

    try:
        protein_contacts_result = _protein_contact_artifacts_csv_writer()(
            contacts_result,
            selected_output_dir,
        )
    except Exception as exc:
        return _analysis_input_export_result(
            graph_export,
            selected_output_dir,
            residue_tables_result=residue_tables_result,
            issues=(
                _analysis_input_exception_issue(
                    kind="protein_contact_export_failed",
                    stage="protein_contacts",
                    field="protein_contacts_result",
                    output_dir=selected_output_dir,
                    exc=exc,
                ),
            ),
        )
    if not _stage_result_passed(protein_contacts_result):
        return _analysis_input_export_result(
            graph_export,
            selected_output_dir,
            residue_tables_result=residue_tables_result,
            protein_contacts_result=protein_contacts_result,
            issues=(
                _analysis_input_failed_issue(
                    kind="protein_contact_export_failed",
                    stage="protein_contacts",
                    field="protein_contacts_result",
                    output_dir=selected_output_dir,
                    result=protein_contacts_result,
                ),
            ),
        )

    try:
        manifest_artifacts_result = _manifest_artifacts_writer()(
            mapping_result,
            selected_output_dir,
            residue_tables=residue_tables_result,
            protein_contacts=protein_contacts_result,
        )
    except Exception as exc:
        return _analysis_input_export_result(
            graph_export,
            selected_output_dir,
            residue_tables_result=residue_tables_result,
            protein_contacts_result=protein_contacts_result,
            issues=(
                _analysis_input_exception_issue(
                    kind="manifest_artifact_export_failed",
                    stage="manifests",
                    field="manifest_artifacts_result",
                    output_dir=selected_output_dir,
                    exc=exc,
                ),
            ),
        )
    if not _stage_result_passed(manifest_artifacts_result):
        return _analysis_input_export_result(
            graph_export,
            selected_output_dir,
            residue_tables_result=residue_tables_result,
            protein_contacts_result=protein_contacts_result,
            manifest_artifacts_result=manifest_artifacts_result,
            issues=(
                _analysis_input_failed_issue(
                    kind="manifest_artifact_export_failed",
                    stage="manifests",
                    field="manifest_artifacts_result",
                    output_dir=selected_output_dir,
                    result=manifest_artifacts_result,
                ),
            ),
        )

    return _analysis_input_export_result(
        graph_export,
        selected_output_dir,
        residue_tables_result=residue_tables_result,
        protein_contacts_result=protein_contacts_result,
        manifest_artifacts_result=manifest_artifacts_result,
    )


def run_preprocessing_graph_workflow_diagnostics(
    graph_export: PreprocessingGraphWorkflowGraphExportResult,
    *,
    write_report_json: bool = True,
    create_parent_directories: bool = True,
) -> PreprocessingGraphWorkflowDiagnosticsResult:
    """Orchestrate Stage 14 diagnostics APIs from a Stage 15.5 result."""
    if not isinstance(
        graph_export,
        PreprocessingGraphWorkflowGraphExportResult,
    ):
        raise ValueError(
            "graph_export must be "
            "PreprocessingGraphWorkflowGraphExportResult"
        )
    _require_bool(write_report_json, "write_report_json")
    _require_bool(create_parent_directories, "create_parent_directories")

    if not graph_export.passed:
        return _diagnostics_result(
            graph_export,
            diagnostics_report_json_path=(
                graph_export.output_layout.diagnostics_report_json_path
                if write_report_json
                else None
            ),
            issues=(
                PreprocessingGraphWorkflowDiagnosticsIssue(
                    kind="graph_export_failed",
                    message=(
                        "Stage 15.5 graph export did not pass; diagnostics "
                        "were not attempted."
                    ),
                    stage="graph_export",
                    field="graph_export",
                ),
            ),
        )

    layout_issue = _diagnostics_output_layout_issue(graph_export.output_layout)
    if layout_issue is not None:
        return _diagnostics_result(
            graph_export,
            diagnostics_report_json_path=(
                graph_export.output_layout.diagnostics_report_json_path
                if write_report_json
                else None
            ),
            issues=(layout_issue,),
        )

    artifact_issue = _graph_artifact_path_issue(graph_export)
    if artifact_issue is not None:
        return _diagnostics_result(
            graph_export,
            diagnostics_report_json_path=(
                graph_export.output_layout.diagnostics_report_json_path
                if write_report_json
                else None
            ),
            issues=(artifact_issue,),
        )

    try:
        diagnostics_run_result = _graph_diagnostics_runner()(
            graph_export.graph_nodes_csv_path,
            graph_export.graph_edges_csv_path,
            graph_export.graph_json_path,
        )
    except Exception as exc:
        return _diagnostics_result(
            graph_export,
            diagnostics_report_json_path=(
                graph_export.output_layout.diagnostics_report_json_path
                if write_report_json
                else None
            ),
            issues=(
                _diagnostics_exception_issue(
                    kind="diagnostics_run_failed",
                    stage="graph_diagnostics",
                    field="diagnostics_run_result",
                    exc=exc,
                ),
            ),
        )
    diagnostics_run_passed = _stage_result_passed_status(
        diagnostics_run_result
    )
    if diagnostics_run_passed is None:
        return _diagnostics_result(
            graph_export,
            diagnostics_run_result=diagnostics_run_result,
            diagnostics_report_json_path=(
                graph_export.output_layout.diagnostics_report_json_path
                if write_report_json
                else None
            ),
            issues=(
                _diagnostics_failed_issue(
                    kind="diagnostics_run_failed",
                    stage="graph_diagnostics",
                    field="diagnostics_run_result",
                    result=diagnostics_run_result,
                ),
            ),
        )
    issues: tuple[PreprocessingGraphWorkflowDiagnosticsIssue, ...] = ()
    if not diagnostics_run_passed:
        issues = (
            _diagnostics_failed_issue(
                kind="diagnostics_checks_failed",
                stage="graph_diagnostics",
                field="diagnostics_run_result",
                result=diagnostics_run_result,
            ),
        )

    try:
        diagnostics_report = _graph_diagnostics_report_builder()(
            diagnostics_run_result
        )
    except Exception as exc:
        return _diagnostics_result(
            graph_export,
            diagnostics_run_result=diagnostics_run_result,
            diagnostics_report_json_path=(
                graph_export.output_layout.diagnostics_report_json_path
                if write_report_json
                else None
            ),
            issues=(
                *issues,
                _diagnostics_exception_issue(
                    kind="diagnostics_report_failed",
                    stage="graph_diagnostics_report",
                    field="diagnostics_report",
                    exc=exc,
                ),
            ),
        )

    report_path = (
        graph_export.output_layout.diagnostics_report_json_path
        if write_report_json
        else None
    )
    if report_path is None:
        return _diagnostics_result(
            graph_export,
            diagnostics_run_result=diagnostics_run_result,
            diagnostics_report=diagnostics_report,
            issues=issues,
        )

    try:
        _write_diagnostics_report_json(
            diagnostics_report,
            report_path,
            create_parent_directories=create_parent_directories,
        )
    except Exception as exc:
        return _diagnostics_result(
            graph_export,
            diagnostics_run_result=diagnostics_run_result,
            diagnostics_report=diagnostics_report,
            diagnostics_report_json_path=report_path,
            issues=(
                *issues,
                PreprocessingGraphWorkflowDiagnosticsIssue(
                    kind="diagnostics_report_json_write_failed",
                    message=(
                        "Diagnostics report JSON could not be written: "
                        f"{exc.__class__.__name__}."
                    ),
                    stage="diagnostics_report_json",
                    field="diagnostics_report_json_path",
                    path=report_path,
                ),
            ),
        )

    return _diagnostics_result(
        graph_export,
        diagnostics_run_result=diagnostics_run_result,
        diagnostics_report=diagnostics_report,
        diagnostics_report_json_path=report_path,
        diagnostics_report_json_written=True,
        issues=issues,
    )


def compare_preprocessing_graph_workflow_reference_artifacts(
    graph_export: PreprocessingGraphWorkflowGraphExportResult,
    options: PreprocessingGraphWorkflowOptions,
    output_layout: PreprocessingGraphWorkflowOutputLayout,
    *,
    write_report_json: bool = True,
    create_parent_directories: bool = True,
) -> PreprocessingGraphWorkflowReferenceComparisonResult:
    """Optionally orchestrate Stage 14 reference graph comparison."""
    if not isinstance(
        graph_export,
        PreprocessingGraphWorkflowGraphExportResult,
    ):
        raise ValueError(
            "graph_export must be "
            "PreprocessingGraphWorkflowGraphExportResult"
        )
    if not isinstance(options, PreprocessingGraphWorkflowOptions):
        raise ValueError(
            "options must be PreprocessingGraphWorkflowOptions"
        )
    if not isinstance(output_layout, PreprocessingGraphWorkflowOutputLayout):
        raise ValueError(
            "output_layout must be PreprocessingGraphWorkflowOutputLayout"
        )
    _require_bool(write_report_json, "write_report_json")
    _require_bool(create_parent_directories, "create_parent_directories")

    if not options.enable_reference_comparison:
        return _reference_comparison_result(
            graph_export,
            options,
            output_layout,
            reference_comparison_enabled=False,
            reference_comparison_skipped=True,
        )

    report_path = (
        output_layout.reference_comparison_json_path
        if write_report_json
        else None
    )

    missing_fields = _missing_reference_path_fields(options)
    if missing_fields:
        return _reference_comparison_result(
            graph_export,
            options,
            output_layout,
            reference_comparison_enabled=True,
            reference_comparison_json_path=report_path,
            issues=(
                PreprocessingGraphWorkflowReferenceComparisonIssue(
                    kind="reference_paths_required",
                    message=(
                        "reference comparison requires explicit reference "
                        "artifact paths: "
                        + ", ".join(missing_fields)
                        + "."
                    ),
                    stage="reference_comparison_input",
                    field="reference_paths",
                    value=",".join(missing_fields),
                ),
            ),
        )

    if not graph_export.passed:
        return _reference_comparison_result(
            graph_export,
            options,
            output_layout,
            reference_comparison_enabled=True,
            reference_comparison_json_path=report_path,
            issues=(
                PreprocessingGraphWorkflowReferenceComparisonIssue(
                    kind="graph_export_failed",
                    message=(
                        "Stage 15.5 graph export did not pass; reference "
                        "comparison was not attempted."
                    ),
                    stage="graph_export",
                    field="graph_export",
                ),
            ),
        )

    layout_issue = _reference_comparison_output_layout_issue(output_layout)
    if layout_issue is not None:
        return _reference_comparison_result(
            graph_export,
            options,
            output_layout,
            reference_comparison_enabled=True,
            reference_comparison_json_path=report_path,
            issues=(layout_issue,),
        )

    artifact_issue = _reference_graph_artifact_path_issue(graph_export)
    if artifact_issue is not None:
        return _reference_comparison_result(
            graph_export,
            options,
            output_layout,
            reference_comparison_enabled=True,
            reference_comparison_json_path=report_path,
            issues=(artifact_issue,),
        )

    comparison_options = _graph_reference_comparison_options_builder()(
        reference_semantics=options.reference_semantics
    )
    comparison_input = _graph_reference_comparison_input_builder()(
        generated_nodes_csv_path=graph_export.graph_nodes_csv_path,
        generated_edges_csv_path=graph_export.graph_edges_csv_path,
        generated_graph_json_path=graph_export.graph_json_path,
        reference_nodes_csv_path=cast(Path, options.reference_nodes_csv_path),
        reference_edges_csv_path=cast(Path, options.reference_edges_csv_path),
        reference_graph_json_path=cast(Path, options.reference_graph_json_path),
        options=comparison_options,
    )

    try:
        comparison_result = _graph_reference_comparator()(comparison_input)
    except Exception as exc:
        return _reference_comparison_result(
            graph_export,
            options,
            output_layout,
            reference_comparison_enabled=True,
            reference_comparison_input=comparison_input,
            reference_comparison_json_path=report_path,
            issues=(
                _reference_comparison_exception_issue(
                    kind="reference_comparison_failed",
                    stage="reference_comparison",
                    field="reference_comparison_result",
                    exc=exc,
                ),
            ),
        )

    result = _reference_comparison_result(
        graph_export,
        options,
        output_layout,
        reference_comparison_enabled=True,
        reference_comparison_input=comparison_input,
        reference_comparison_result=comparison_result,
        reference_comparison_json_path=report_path,
        issues=(
            ()
            if _stage_result_passed(comparison_result)
            else (
                _reference_comparison_failed_issue(
                    kind="reference_comparison_mismatch",
                    stage="reference_comparison",
                    field="reference_comparison_result",
                    result=comparison_result,
                ),
            )
        ),
    )

    if result.issues:
        return result

    if report_path is None:
        return result

    written_result = _reference_comparison_result(
        graph_export,
        options,
        output_layout,
        reference_comparison_enabled=True,
        reference_comparison_input=comparison_input,
        reference_comparison_result=comparison_result,
        reference_comparison_json_path=report_path,
        reference_comparison_json_written=True,
        issues=result.issues,
    )
    try:
        _write_reference_comparison_report_json(
            written_result,
            report_path,
            create_parent_directories=create_parent_directories,
        )
    except Exception as exc:
        return _reference_comparison_result(
            graph_export,
            options,
            output_layout,
            reference_comparison_enabled=True,
            reference_comparison_input=comparison_input,
            reference_comparison_result=comparison_result,
            reference_comparison_json_path=report_path,
            issues=result.issues
            + (
                PreprocessingGraphWorkflowReferenceComparisonIssue(
                    kind="reference_comparison_json_write_failed",
                    message=(
                        "Reference comparison JSON could not be written: "
                        f"{exc.__class__.__name__}."
                    ),
                    stage="reference_comparison_json",
                    field="reference_comparison_json_path",
                    path=report_path,
                ),
            ),
        )

    return written_result


def _reference_comparison_result(
    graph_export: PreprocessingGraphWorkflowGraphExportResult,
    options: PreprocessingGraphWorkflowOptions,
    output_layout: PreprocessingGraphWorkflowOutputLayout,
    *,
    reference_comparison_enabled: bool,
    reference_comparison_skipped: bool = False,
    reference_comparison_input: object | None = None,
    reference_comparison_result: object | None = None,
    reference_comparison_json_path: Path | None = None,
    reference_comparison_json_written: bool = False,
    issues: tuple[
        PreprocessingGraphWorkflowReferenceComparisonIssue,
        ...,
    ] = (),
) -> PreprocessingGraphWorkflowReferenceComparisonResult:
    return PreprocessingGraphWorkflowReferenceComparisonResult(
        graph_export=graph_export,
        options=options,
        output_layout=output_layout,
        reference_comparison_enabled=reference_comparison_enabled,
        reference_comparison_skipped=reference_comparison_skipped,
        reference_comparison_input=reference_comparison_input,
        reference_comparison_result=reference_comparison_result,
        reference_comparison_json_path=reference_comparison_json_path,
        reference_comparison_json_written=reference_comparison_json_written,
        issues=issues,
    )


def _diagnostics_result(
    graph_export: PreprocessingGraphWorkflowGraphExportResult,
    *,
    diagnostics_run_result: object | None = None,
    diagnostics_report: object | None = None,
    diagnostics_report_json_path: Path | None = None,
    diagnostics_report_json_written: bool = False,
    issues: tuple[PreprocessingGraphWorkflowDiagnosticsIssue, ...] = (),
) -> PreprocessingGraphWorkflowDiagnosticsResult:
    return PreprocessingGraphWorkflowDiagnosticsResult(
        graph_export=graph_export,
        diagnostics_run_result=diagnostics_run_result,
        diagnostics_report=diagnostics_report,
        diagnostics_report_json_path=diagnostics_report_json_path,
        diagnostics_report_json_written=diagnostics_report_json_written,
        issues=issues,
    )


def _graph_export_result(
    computation: PreprocessingGraphWorkflowComputationResult,
    output_layout: PreprocessingGraphWorkflowOutputLayout,
    *,
    mapping_result: object | None = None,
    nodes_csv_write_result: object | None = None,
    edges_csv_write_result: object | None = None,
    csv_validation_result: object | None = None,
    graph_json_write_result: object | None = None,
    graph_export_bundle_result: object | None = None,
    issues: tuple[PreprocessingGraphWorkflowGraphExportIssue, ...] = (),
) -> PreprocessingGraphWorkflowGraphExportResult:
    return PreprocessingGraphWorkflowGraphExportResult(
        computation=computation,
        output_layout=output_layout,
        graph_nodes_csv_path=output_layout.graph_nodes_csv_path,
        graph_edges_csv_path=output_layout.graph_edges_csv_path,
        graph_json_path=output_layout.graph_json_path,
        mapping_result=mapping_result,
        nodes_csv_write_result=nodes_csv_write_result,
        edges_csv_write_result=edges_csv_write_result,
        csv_validation_result=csv_validation_result,
        graph_json_write_result=graph_json_write_result,
        graph_export_bundle_result=graph_export_bundle_result,
        issues=issues,
    )


def _scientific_csv_export_result(
    computation: PreprocessingGraphWorkflowComputationResult,
    output_layout: PreprocessingGraphWorkflowOutputLayout,
    *,
    export_rg_timeseries: bool,
    export_contact_edges: bool,
    export_contacts_perframe: bool,
    rg_timeseries_write_result: object | None = None,
    contact_edges_write_result: object | None = None,
    contacts_perframe_write_result: object | None = None,
    rg_timeseries_validation_result: object | None = None,
    contact_edges_validation_result: object | None = None,
    contacts_perframe_validation_result: object | None = None,
    issues: tuple[
        PreprocessingGraphWorkflowScientificCsvExportIssue,
        ...,
    ] = (),
) -> PreprocessingGraphWorkflowScientificCsvExportResult:
    return PreprocessingGraphWorkflowScientificCsvExportResult(
        computation=computation,
        output_layout=output_layout,
        export_rg_timeseries=export_rg_timeseries,
        export_contact_edges=export_contact_edges,
        export_contacts_perframe=export_contacts_perframe,
        rg_timeseries_csv_path=(
            output_layout.rg_timeseries_csv_path
            if export_rg_timeseries
            else None
        ),
        contact_edges_csv_path=(
            output_layout.contact_edges_csv_path
            if export_contact_edges
            else None
        ),
        contacts_perframe_csv_path=(
            output_layout.contacts_perframe_csv_path
            if export_contacts_perframe
            else None
        ),
        rg_timeseries_write_result=rg_timeseries_write_result,
        contact_edges_write_result=contact_edges_write_result,
        contacts_perframe_write_result=contacts_perframe_write_result,
        rg_timeseries_validation_result=rg_timeseries_validation_result,
        contact_edges_validation_result=contact_edges_validation_result,
        contacts_perframe_validation_result=contacts_perframe_validation_result,
        issues=issues,
    )


def _analysis_input_export_result(
    graph_export: PreprocessingGraphWorkflowGraphExportResult,
    output_dir: Path,
    *,
    residue_tables_result: object | None = None,
    protein_contacts_result: object | None = None,
    manifest_artifacts_result: object | None = None,
    issues: tuple[
        PreprocessingGraphWorkflowAnalysisInputExportIssue,
        ...,
    ] = (),
) -> PreprocessingGraphWorkflowAnalysisInputExportResult:
    return PreprocessingGraphWorkflowAnalysisInputExportResult(
        graph_export=graph_export,
        output_dir=output_dir,
        residue_tables_result=residue_tables_result,
        protein_contacts_result=protein_contacts_result,
        manifest_artifacts_result=manifest_artifacts_result,
        issues=issues,
    )


def _build_output_layout(
    options: PreprocessingGraphWorkflowOptions,
) -> PreprocessingGraphWorkflowOutputLayout:
    output_dir = options.output_dir
    return PreprocessingGraphWorkflowOutputLayout(
        output_dir=output_dir,
        run_name=options.run_name,
        rg_timeseries_csv_path=output_dir / "rg" / "rg_timeseries.csv",
        contacts_perframe_csv_path=(
            output_dir / "contacts" / "contacts_perframe.csv"
        ),
        contact_edges_csv_path=output_dir / "contacts" / "contact_edges.csv",
        graph_nodes_csv_path=output_dir / "graph" / "nodes.csv",
        graph_edges_csv_path=output_dir / "graph" / "edges.csv",
        graph_json_path=output_dir / "graph" / "graph.json",
        diagnostics_report_json_path=(
            output_dir / "reports" / "graph_diagnostics_report.json"
        ),
        reference_comparison_json_path=(
            output_dir / "reports" / "graph_reference_comparison.json"
        ),
    )


def _build_planned_steps(
    options: PreprocessingGraphWorkflowOptions,
) -> tuple[str, ...]:
    planned_steps: list[str] = list(_FOUNDATIONAL_STEPS)

    if options.include_rg:
        planned_steps.append("compute_rg")
    if options.include_contacts:
        planned_steps.append("compute_contacts")
    if options.include_graph_export:
        planned_steps.extend(_GRAPH_EXPORT_STEPS)
    if options.include_diagnostics and options.include_graph_export:
        planned_steps.extend(_DIAGNOSTICS_STEPS)
    if (
        options.enable_reference_comparison
        and options.include_graph_export
    ):
        planned_steps.extend(_REFERENCE_COMPARISON_STEPS)

    return tuple(planned_steps)


def _build_planning_issues(
    options: PreprocessingGraphWorkflowOptions,
) -> tuple[PreprocessingGraphWorkflowIssue, ...]:
    issues: list[PreprocessingGraphWorkflowIssue] = []

    if options.include_graph_export and not options.include_contacts:
        issues.append(
            PreprocessingGraphWorkflowIssue(
                kind="stage_disabled",
                field="include_contacts",
                value=str(options.include_contacts),
                message=(
                    "graph export depends on contacts; enable contacts or "
                    "disable graph export."
                ),
            )
        )

    if options.include_diagnostics and not options.include_graph_export:
        issues.append(
            PreprocessingGraphWorkflowIssue(
                kind="stage_disabled",
                field="include_graph_export",
                value=str(options.include_graph_export),
                message=(
                    "diagnostics depend on graph export; enable graph export "
                    "or disable diagnostics."
                ),
            )
        )

    if (
        options.enable_reference_comparison
        and not options.include_graph_export
    ):
        issues.append(
            PreprocessingGraphWorkflowIssue(
                kind="stage_disabled",
                field="include_graph_export",
                value=str(options.include_graph_export),
                message=(
                    "reference comparison depends on graph export; enable "
                    "graph export or disable reference comparison."
                ),
            )
        )

    if options.enable_reference_comparison:
        missing_fields = _missing_reference_path_fields(options)
        if missing_fields:
            issues.append(
                PreprocessingGraphWorkflowIssue(
                    kind="reference_paths_required",
                    field="reference_paths",
                    value=",".join(missing_fields),
                    message=(
                        "reference comparison requires explicit reference "
                        "artifact paths: "
                        + ", ".join(missing_fields)
                        + "."
                    ),
                )
            )

    if _all_workflow_targets_disabled(options):
        issues.append(
            PreprocessingGraphWorkflowIssue(
                kind="no_workflow_targets_enabled",
                field="workflow_targets",
                message="At least one workflow target must be enabled.",
            )
        )

    return tuple(issues)


def _missing_reference_path_fields(
    options: PreprocessingGraphWorkflowOptions,
) -> tuple[str, ...]:
    return tuple(
        field_name
        for field_name in _OPTION_REFERENCE_PATH_FIELDS
        if getattr(options, field_name) is None
    )


def _all_workflow_targets_disabled(
    options: PreprocessingGraphWorkflowOptions,
) -> bool:
    return (
        not options.include_rg
        and not options.include_contacts
        and not options.include_graph_export
        and not options.include_diagnostics
        and not options.enable_reference_comparison
    )


def _require_path(value: object, field_name: str) -> None:
    if not isinstance(value, Path):
        raise ValueError(f"{field_name} must be Path")


def _require_optional_path(value: object, field_name: str) -> None:
    if value is not None and not isinstance(value, Path):
        raise ValueError(f"{field_name} must be None or Path")


def _require_bool(value: object, field_name: str) -> None:
    if not isinstance(value, bool):
        raise ValueError(f"{field_name} must be a bool")


def _require_frame_sampling(value: object, field_name: str) -> None:
    if not isinstance(value, PreprocessingFrameSamplingOptions):
        raise ValueError(
            f"{field_name} must be PreprocessingFrameSamplingOptions"
        )


def _contact_computation_limits_type() -> type[object]:
    contacts_module = importlib.import_module(
        "mania.preprocessing.trajectory_contacts"
    )
    return cast(
        type[object],
        cast(Any, contacts_module).PreprocessingContactComputationLimits,
    )


def _contact_detection_options_type() -> type[object]:
    contacts_module = importlib.import_module(
        "mania.preprocessing.trajectory_contacts"
    )
    return cast(
        type[object],
        cast(Any, contacts_module).PreprocessingContactDetectionOptions,
    )


def _require_contact_detection_options(
    value: object,
    field_name: str,
) -> None:
    if not isinstance(value, _contact_detection_options_type()):
        raise ValueError(
            f"{field_name} must be PreprocessingContactDetectionOptions"
        )


def _contact_detection_options(
    value: PreprocessingContactDetectionOptions | None,
) -> PreprocessingContactDetectionOptions:
    if value is None:
        return _default_contact_detection_options()
    _require_contact_detection_options(value, "contact_detection_options")
    return value


def _contact_detection_options_payload(value: object) -> dict[str, object]:
    _require_contact_detection_options(value, "contact_detection_options")
    payload = cast(Any, value).to_dict(include_contact_selection=True)
    if not isinstance(payload, dict):
        raise ValueError("contact_detection_options.to_dict() must be a dict")
    return cast(dict[str, object], payload)


def _contact_detection_options_are_default(value: object) -> bool:
    _require_contact_detection_options(value, "contact_detection_options")
    return value == _default_contact_detection_options()


def _require_contact_computation_limits(
    value: object,
    field_name: str,
) -> None:
    if not isinstance(value, _contact_computation_limits_type()):
        raise ValueError(
            f"{field_name} must be PreprocessingContactComputationLimits"
        )


def _contact_computation_limits(
    value: PreprocessingContactComputationLimits | None,
) -> PreprocessingContactComputationLimits:
    if value is None:
        return _default_contact_computation_limits()
    _require_contact_computation_limits(value, "contact_computation_limits")
    return value


def _contact_computation_limits_payload(value: object) -> dict[str, object]:
    _require_contact_computation_limits(value, "contact_computation_limits")
    payload = cast(Any, value).to_dict()
    if not isinstance(payload, dict):
        raise ValueError("contact_computation_limits.to_dict() must be a dict")
    return cast(dict[str, object], payload)


def _contact_computation_limits_are_default(value: object) -> bool:
    _require_contact_computation_limits(value, "contact_computation_limits")
    return value == _default_contact_computation_limits()


def _frame_sampling_options(
    value: PreprocessingFrameSamplingOptions | None,
) -> PreprocessingFrameSamplingOptions:
    if value is None:
        return PreprocessingFrameSamplingOptions()
    _require_frame_sampling(value, "frame_sampling")
    return value


def _non_empty_string(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a non-empty string")
    stripped = value.strip()
    if stripped == "":
        raise ValueError(f"{field_name} must be a non-empty string")
    return stripped


def _optional_non_empty_string(
    value: object,
    field_name: str,
) -> str | None:
    if value is None:
        return None
    return _non_empty_string(value, field_name)


def _optional_path_string(value: Path | None) -> str | None:
    if value is None:
        return None
    return str(value)


def _require_non_negative_int(value: object, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative int")


def _normalize_expected_condition_names(
    expected_condition_names: Iterable[str] | None,
) -> tuple[str, ...] | None:
    if expected_condition_names is None:
        return None
    normalized_names: list[str] = []
    for condition_name in expected_condition_names:
        normalized_names.append(
            _non_empty_string(
                condition_name,
                "expected_condition_names",
            )
        )
    return tuple(normalized_names)


def _manifest_loader() -> _ManifestLoader:
    module = _import_preprocessing_module("input_" + "manifest")
    return cast(
        _ManifestLoader,
        getattr(module, "load_" + "preprocessing_input_manifest"),
    )


def _manifest_path_validator() -> _ManifestPathValidator:
    module = _import_preprocessing_module("path_" + "validation")
    return cast(
        _ManifestPathValidator,
        getattr(module, "validate_" + "preprocessing_manifest_paths"),
    )


def _manifest_runtime_loader() -> _ManifestRuntimeLoader:
    module = _import_preprocessing_module("trajectory_" + "manifest_loader")
    return cast(
        _ManifestRuntimeLoader,
        getattr(module, "load_" + "manifest_condition_runtimes"),
    )


def _manifest_rg_computer() -> _ManifestRgComputer:
    module = _import_preprocessing_module("trajectory_" + "rg")
    return cast(
        _ManifestRgComputer,
        getattr(module, "compute_" + "manifest_rg"),
    )


def _manifest_contacts_computer() -> _ManifestContactsComputer:
    module = _import_preprocessing_module("trajectory_" + "contacts")
    return cast(
        _ManifestContactsComputer,
        getattr(module, "compute_" + "manifest_contacts"),
    )


def _rg_timeseries_csv_writer() -> _RgTimeseriesCsvWriter:
    module = _import_preprocessing_module("trajectory_" + "rg_export")
    return cast(
        _RgTimeseriesCsvWriter,
        module.write_rg_timeseries_csv,
    )


def _contact_edges_csv_writer() -> _ContactEdgesCsvWriter:
    module = _import_preprocessing_module("trajectory_" + "contacts_export")
    return cast(
        _ContactEdgesCsvWriter,
        getattr(module, "write_contact_" + "edges_csv"),
    )


def _contacts_perframe_csv_writer() -> _ContactsPerframeCsvWriter:
    module = _import_preprocessing_module("trajectory_" + "contacts_export")
    return cast(
        _ContactsPerframeCsvWriter,
        module.write_contacts_perframe_csv,
    )


def _rg_timeseries_csv_validator() -> _RgTimeseriesCsvValidator:
    module = _import_preprocessing_module(
        "trajectory_" + "rg_export_validation"
    )
    return cast(
        _RgTimeseriesCsvValidator,
        module.validate_rg_timeseries_csv,
    )


def _contact_edges_csv_validator() -> _ContactEdgesCsvValidator:
    module = _import_preprocessing_module(
        "trajectory_" + "contacts_export_validation"
    )
    return cast(
        _ContactEdgesCsvValidator,
        module.validate_contact_edges_csv,
    )


def _contacts_perframe_csv_validator() -> _ContactsPerframeCsvValidator:
    module = _import_preprocessing_module(
        "trajectory_" + "contacts_export_validation"
    )
    return cast(
        _ContactsPerframeCsvValidator,
        module.validate_contacts_perframe_csv,
    )


def _residue_tables_csv_writer() -> _ResidueTablesCsvWriter:
    module = _import_preprocessing_module(
        "trajectory_" + "residue_table_export"
    )
    return cast(
        _ResidueTablesCsvWriter,
        module.write_preprocessing_residue_tables_csv,
    )


def _protein_contact_artifacts_csv_writer() -> _ProteinContactArtifactsCsvWriter:
    module = _import_preprocessing_module(
        "trajectory_" + "protein_contact_export"
    )
    return cast(
        _ProteinContactArtifactsCsvWriter,
        module.write_preprocessing_protein_contact_artifacts_csv,
    )


def _manifest_artifacts_writer() -> _ManifestArtifactsWriter:
    module = _import_preprocessing_module(
        "trajectory_" + "preprocessing_manifests"
    )
    return cast(
        _ManifestArtifactsWriter,
        module.write_preprocessing_manifest_artifacts,
    )


def _graph_export_mapping_builder() -> _GraphExportMappingBuilder:
    module = _import_preprocessing_module("trajectory_" + "graph_export")
    return cast(
        _GraphExportMappingBuilder,
        getattr(module, "build_" + "preprocessing_graph_export_mapping"),
    )


def _graph_nodes_csv_writer() -> _GraphNodesCsvWriter:
    module = _import_preprocessing_module("trajectory_" + "graph_export")
    return cast(
        _GraphNodesCsvWriter,
        getattr(module, "write_" + "preprocessing_graph_nodes_csv"),
    )


def _graph_edges_csv_writer() -> _GraphEdgesCsvWriter:
    module = _import_preprocessing_module("trajectory_" + "graph_export")
    return cast(
        _GraphEdgesCsvWriter,
        getattr(module, "write_preprocessing_graph_" + "edges_csv"),
    )


def _graph_csv_validator() -> _GraphCsvValidator:
    module = _import_preprocessing_module("trajectory_" + "graph_export")
    return cast(
        _GraphCsvValidator,
        getattr(module, "validate_" + "preprocessing_graph_csvs"),
    )


def _graph_json_writer() -> _GraphJsonWriter:
    module = _import_preprocessing_module("trajectory_" + "graph_export")
    return cast(
        _GraphJsonWriter,
        getattr(module, "write_" + "preprocessing_graph_json"),
    )


def _graph_export_bundle_builder() -> _GraphExportBundleBuilder:
    module = _import_preprocessing_module("trajectory_" + "graph_export")
    return cast(
        _GraphExportBundleBuilder,
        getattr(module, "build_" + "preprocessing_graph_export_bundle"),
    )


def _graph_diagnostics_runner() -> _GraphDiagnosticsRunner:
    module = _import_preprocessing_module("trajectory_" + "graph_diagnostics")
    return cast(
        _GraphDiagnosticsRunner,
        getattr(module, "run_" + "preprocessing_graph_diagnostics"),
    )


def _graph_diagnostics_report_builder() -> _GraphDiagnosticsReportBuilder:
    module = _import_preprocessing_module("trajectory_" + "graph_diagnostics")
    return cast(
        _GraphDiagnosticsReportBuilder,
        getattr(module, "build_" + "preprocessing_graph_diagnostics_report"),
    )


def _graph_reference_comparison_options_builder(
) -> _GraphReferenceComparisonOptionsBuilder:
    module = _import_preprocessing_module(
        "trajectory_" + "graph_reference_comparison"
    )
    return cast(
        _GraphReferenceComparisonOptionsBuilder,
        module.PreprocessingGraphReferenceComparisonOptions,
    )


def _graph_reference_comparison_input_builder(
) -> _GraphReferenceComparisonInputBuilder:
    module = _import_preprocessing_module(
        "trajectory_" + "graph_reference_comparison"
    )
    return cast(
        _GraphReferenceComparisonInputBuilder,
        module.PreprocessingGraphReferenceComparisonInput,
    )


def _graph_reference_comparator() -> _GraphReferenceComparator:
    module = _import_preprocessing_module(
        "trajectory_" + "graph_reference_comparison"
    )
    return cast(
        _GraphReferenceComparator,
        getattr(
            module,
            "compare_" + "preprocessing_graph_reference_artifacts",
        ),
    )


def _import_preprocessing_module(module_name: str) -> ModuleType:
    return importlib.import_module(f"mania.preprocessing.{module_name}")


def _runtime_loading_metadata_issues(
    runtime_load_result: object,
    expected_condition_names: tuple[str, ...] | None,
) -> tuple[
    tuple[str, ...],
    tuple[PreprocessingGraphWorkflowRuntimeLoadingIssue, ...],
]:
    issues: list[PreprocessingGraphWorkflowRuntimeLoadingIssue] = []
    condition_names = _loaded_condition_names(runtime_load_result, issues)
    _append_runtime_result_status_issue(runtime_load_result, issues)

    if expected_condition_names is not None:
        if len(condition_names) != len(expected_condition_names):
            issues.append(
                PreprocessingGraphWorkflowRuntimeLoadingIssue(
                    kind="condition_count_mismatch",
                    message=(
                        "Loaded condition count does not match the expected "
                        "condition count."
                    ),
                    field="conditions",
                    value=(
                        f"expected={len(expected_condition_names)},"
                        f"actual={len(condition_names)}"
                    ),
                )
            )
        loaded_names = set(condition_names)
        for expected_condition_name in expected_condition_names:
            if expected_condition_name not in loaded_names:
                issues.append(
                    PreprocessingGraphWorkflowRuntimeLoadingIssue(
                        kind="expected_condition_not_loaded",
                        message=(
                            "Expected condition runtime was not loaded: "
                            f"{expected_condition_name}"
                        ),
                        field="condition_runtime",
                        condition_name=expected_condition_name,
                    )
                )

    return condition_names, tuple(issues)


def _loaded_condition_names(
    runtime_load_result: object,
    issues: list[PreprocessingGraphWorkflowRuntimeLoadingIssue],
) -> tuple[str, ...]:
    names = getattr(runtime_load_result, "loaded_condition_names", None)
    if not isinstance(names, tuple):
        issues.append(
            PreprocessingGraphWorkflowRuntimeLoadingIssue(
                kind="runtime_load_result_invalid",
                message=(
                    "Stage 11 runtime load result does not expose loaded "
                    "condition names as a tuple."
                ),
                field="loaded_condition_names",
                value=_runtime_load_result_type(runtime_load_result),
            )
        )
        return ()

    condition_names: list[str] = []
    for condition_name in names:
        try:
            condition_names.append(
                _non_empty_string(condition_name, "loaded_condition_names")
            )
        except ValueError:
            issues.append(
                PreprocessingGraphWorkflowRuntimeLoadingIssue(
                    kind="runtime_load_result_invalid",
                    message=(
                        "Stage 11 runtime load result contains an invalid "
                        "loaded condition name."
                    ),
                    field="loaded_condition_names",
                    value=_runtime_load_result_type(runtime_load_result),
                )
            )
            return ()
    return tuple(condition_names)


def _append_runtime_result_status_issue(
    runtime_load_result: object,
    issues: list[PreprocessingGraphWorkflowRuntimeLoadingIssue],
) -> None:
    passed = getattr(runtime_load_result, "passed", None)
    if not isinstance(passed, bool):
        issues.append(
            PreprocessingGraphWorkflowRuntimeLoadingIssue(
                kind="runtime_load_result_invalid",
                message=(
                    "Stage 11 runtime load result does not expose a boolean "
                    "passed status."
                ),
                field="passed",
                value=_runtime_load_result_type(runtime_load_result),
            )
        )
        return
    if not passed:
        issues.append(
            PreprocessingGraphWorkflowRuntimeLoadingIssue(
                kind="runtime_load_failed",
                message="Stage 11 manifest runtime loading did not pass.",
                field="condition_runtime",
                value=_runtime_load_result_type(runtime_load_result),
            )
        )


def _runtime_load_result_type(runtime_load_result: object | None) -> str | None:
    return _object_type(runtime_load_result)


def _runtime_loading_metadata_passed_without_raw_result(
    runtime_loading: PreprocessingGraphWorkflowRuntimeLoadingResult,
) -> bool:
    return (
        runtime_loading.manifest_readiness.passed
        and runtime_loading.runtime_load_result is None
        and runtime_loading._expected_conditions_loaded
        and runtime_loading.issues == ()
    )


def _object_type(value: object | None) -> str | None:
    if value is None:
        return None
    cls = value.__class__
    return f"{cls.__module__}.{cls.__qualname__}"


def _stage_result_passed(result: object | None) -> bool:
    return getattr(result, "passed", None) is True


def _stage_result_passed_status(result: object | None) -> bool | None:
    passed = getattr(result, "passed", None)
    if isinstance(passed, bool):
        return passed
    return None


def _json_safe_result_payload(result: object | None) -> dict[str, object] | None:
    if result is None:
        return None
    to_dict = getattr(result, "to_dict", None)
    if not callable(to_dict):
        return {"passed": _stage_result_passed(result)}
    payload = to_dict()
    if not isinstance(payload, dict):
        return {"passed": _stage_result_passed(result)}
    safe_payload = _json_safe_value(payload)
    if isinstance(safe_payload, dict):
        return cast(dict[str, object], safe_payload)
    return {"passed": _stage_result_passed(result)}


def _analysis_input_failed_issue(
    *,
    kind: str,
    stage: str,
    field: str,
    output_dir: Path,
    result: object,
) -> PreprocessingGraphWorkflowAnalysisInputExportIssue:
    return PreprocessingGraphWorkflowAnalysisInputExportIssue(
        kind=kind,
        message=f"Analysis input {stage} export step did not pass.",
        stage=stage,
        field=field,
        path=output_dir,
        value=_object_type(result),
    )


def _analysis_input_exception_issue(
    *,
    kind: str,
    stage: str,
    field: str,
    output_dir: Path,
    exc: Exception,
) -> PreprocessingGraphWorkflowAnalysisInputExportIssue:
    return PreprocessingGraphWorkflowAnalysisInputExportIssue(
        kind=kind,
        message=(
            f"Analysis input {stage} export step failed unexpectedly: "
            f"{exc.__class__.__name__}."
        ),
        stage=stage,
        field=field,
        path=output_dir,
    )


def _export_rg_timeseries_scientific_csv(
    computation_result: PreprocessingGraphWorkflowComputationResult,
    output_layout: PreprocessingGraphWorkflowOutputLayout,
    issues: list[PreprocessingGraphWorkflowScientificCsvExportIssue],
) -> tuple[object | None, object | None]:
    path = output_layout.rg_timeseries_csv_path
    layout_issue = _scientific_output_layout_issue(
        output_layout,
        field_name="rg_timeseries_csv_path",
        actual_path=path,
        expected_path=output_layout.output_dir / "rg" / "rg_timeseries.csv",
        export_name="rg_timeseries",
    )
    if layout_issue is not None:
        issues.append(layout_issue)
        return None, None

    source_issue = _scientific_source_result_issue(
        computation_result.rg_result,
        export_name="rg_timeseries",
        field="rg_result",
        missing_kind="rg_result_missing",
        failed_kind="rg_result_failed",
        invalid_kind="rg_result_invalid",
    )
    if source_issue is not None:
        issues.append(source_issue)
        return None, None

    return _write_and_validate_scientific_csv(
        computation_result.rg_result,
        path,
        export_name="rg_timeseries",
        writer=_rg_timeseries_csv_writer(),
        validator=_rg_timeseries_csv_validator(),
        write_failed_kind="rg_timeseries_write_failed",
        validation_failed_kind="rg_timeseries_validation_failed",
        issues=issues,
    )


def _export_contact_edges_scientific_csv(
    computation_result: PreprocessingGraphWorkflowComputationResult,
    output_layout: PreprocessingGraphWorkflowOutputLayout,
    issues: list[PreprocessingGraphWorkflowScientificCsvExportIssue],
) -> tuple[object | None, object | None]:
    path = output_layout.contact_edges_csv_path
    layout_issue = _scientific_output_layout_issue(
        output_layout,
        field_name="contact_edges_csv_path",
        actual_path=path,
        expected_path=output_layout.output_dir / "contacts" / "contact_edges.csv",
        export_name="contact_edges",
    )
    if layout_issue is not None:
        issues.append(layout_issue)
        return None, None

    return _write_and_validate_scientific_csv(
        computation_result.contacts_result,
        path,
        export_name="contact_edges",
        writer=_contact_edges_csv_writer(),
        validator=_contact_edges_csv_validator(),
        write_failed_kind="contact_edges_write_failed",
        validation_failed_kind="contact_edges_validation_failed",
        issues=issues,
    )


def _export_contacts_perframe_scientific_csv(
    computation_result: PreprocessingGraphWorkflowComputationResult,
    output_layout: PreprocessingGraphWorkflowOutputLayout,
    issues: list[PreprocessingGraphWorkflowScientificCsvExportIssue],
) -> tuple[object | None, object | None]:
    path = output_layout.contacts_perframe_csv_path
    layout_issue = _scientific_output_layout_issue(
        output_layout,
        field_name="contacts_perframe_csv_path",
        actual_path=path,
        expected_path=(
            output_layout.output_dir / "contacts" / "contacts_perframe.csv"
        ),
        export_name="contacts_perframe",
    )
    if layout_issue is not None:
        issues.append(layout_issue)
        return None, None

    return _write_and_validate_scientific_csv(
        computation_result.contacts_result,
        path,
        export_name="contacts_perframe",
        writer=_contacts_perframe_csv_writer(),
        validator=_contacts_perframe_csv_validator(),
        write_failed_kind="contacts_perframe_write_failed",
        validation_failed_kind="contacts_perframe_validation_failed",
        issues=issues,
    )


def _write_and_validate_scientific_csv(
    source_result: object,
    output_path: Path,
    *,
    export_name: str,
    writer: object,
    validator: object,
    write_failed_kind: str,
    validation_failed_kind: str,
    issues: list[PreprocessingGraphWorkflowScientificCsvExportIssue],
) -> tuple[object | None, object | None]:
    parent_issue = _scientific_parent_directory_issue(
        output_path,
        export_name=export_name,
    )
    if parent_issue is not None:
        issues.append(parent_issue)
        return None, None

    csv_writer = cast(_ScientificCsvWriter, writer)
    try:
        write_result = csv_writer(source_result, output_path)
    except Exception as exc:
        issues.append(
            _scientific_exception_issue(
                kind=write_failed_kind,
                export_name=export_name,
                stage="write",
                field="write_result",
                path=output_path,
                exc=exc,
            )
        )
        return None, None

    if not _stage_result_passed(write_result):
        issues.append(
            _scientific_failed_issue(
                kind=write_failed_kind,
                export_name=export_name,
                stage="write",
                field="write_result",
                path=output_path,
                result=write_result,
            )
        )
        return write_result, None

    csv_validator = cast(_ScientificCsvValidator, validator)
    try:
        validation_result = csv_validator(output_path)
    except Exception as exc:
        issues.append(
            _scientific_exception_issue(
                kind=validation_failed_kind,
                export_name=export_name,
                stage="validation",
                field="validation_result",
                path=output_path,
                exc=exc,
            )
        )
        return write_result, None

    if not _stage_result_passed(validation_result):
        issues.append(
            _scientific_failed_issue(
                kind=validation_failed_kind,
                export_name=export_name,
                stage="validation",
                field="validation_result",
                path=output_path,
                result=validation_result,
            )
        )

    return write_result, validation_result


def _contacts_scientific_source_result_issue(
    contacts_result: object | None,
) -> PreprocessingGraphWorkflowScientificCsvExportIssue | None:
    return _scientific_source_result_issue(
        contacts_result,
        export_name="contacts",
        field="contacts_result",
        missing_kind="contacts_result_missing",
        failed_kind="contacts_result_failed",
        invalid_kind="contacts_result_invalid",
    )


def _scientific_source_result_issue(
    source_result: object | None,
    *,
    export_name: str,
    field: str,
    missing_kind: str,
    failed_kind: str,
    invalid_kind: str,
) -> PreprocessingGraphWorkflowScientificCsvExportIssue | None:
    if source_result is None:
        return PreprocessingGraphWorkflowScientificCsvExportIssue(
            kind=missing_kind,
            message=(
                "Stage 15.4 computation did not retain the required result "
                f"for optional {export_name} CSV export."
            ),
            export_name=export_name,
            stage="computation",
            field=field,
        )

    passed = getattr(source_result, "passed", None)
    if not isinstance(passed, bool):
        return PreprocessingGraphWorkflowScientificCsvExportIssue(
            kind=invalid_kind,
            message=(
                "Stage 15.4 computation result does not expose a boolean "
                "passed status for optional scientific CSV export."
            ),
            export_name=export_name,
            stage="computation",
            field=f"{field}.passed",
            value=_object_type(source_result),
        )
    if not passed:
        return PreprocessingGraphWorkflowScientificCsvExportIssue(
            kind=failed_kind,
            message=(
                "Stage 15.4 computation result did not pass; optional "
                f"{export_name} CSV export was not attempted."
            ),
            export_name=export_name,
            stage="computation",
            field=field,
            value=_object_type(source_result),
        )
    return None


def _scientific_output_layout_issue(
    output_layout: PreprocessingGraphWorkflowOutputLayout,
    *,
    field_name: str,
    actual_path: Path,
    expected_path: Path,
    export_name: str,
) -> PreprocessingGraphWorkflowScientificCsvExportIssue | None:
    if actual_path == expected_path:
        return None
    return PreprocessingGraphWorkflowScientificCsvExportIssue(
        kind="output_layout_invalid",
        message=(
            "Scientific CSV export output layout does not match the Stage "
            "15.1 optional scientific artifact boundary."
        ),
        export_name=export_name,
        stage="output_layout",
        field=field_name,
        path=actual_path,
        value=str(expected_path),
    )


def _scientific_parent_directory_issue(
    output_path: Path,
    *,
    export_name: str,
) -> PreprocessingGraphWorkflowScientificCsvExportIssue | None:
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return PreprocessingGraphWorkflowScientificCsvExportIssue(
            kind=f"{export_name}_output_directory_failed",
            message=(
                "Scientific CSV output parent directory could not be created: "
                f"{exc.__class__.__name__}."
            ),
            export_name=export_name,
            stage="write",
            field="output_path.parent",
            path=output_path.parent,
        )
    return None


def _scientific_failed_issue(
    *,
    kind: str,
    export_name: str,
    stage: str,
    field: str,
    result: object,
    path: Path,
) -> PreprocessingGraphWorkflowScientificCsvExportIssue:
    return PreprocessingGraphWorkflowScientificCsvExportIssue(
        kind=kind,
        message=f"Scientific CSV {export_name} {stage} step did not pass.",
        export_name=export_name,
        stage=stage,
        field=field,
        path=path,
        value=_object_type(result),
    )


def _scientific_exception_issue(
    *,
    kind: str,
    export_name: str,
    stage: str,
    field: str,
    exc: Exception,
    path: Path,
) -> PreprocessingGraphWorkflowScientificCsvExportIssue:
    return PreprocessingGraphWorkflowScientificCsvExportIssue(
        kind=kind,
        message=(
            f"Scientific CSV {export_name} {stage} step failed unexpectedly: "
            f"{exc.__class__.__name__}."
        ),
        export_name=export_name,
        stage=stage,
        field=field,
        path=path,
    )


def _scientific_csv_export_paths_payload(
    result: PreprocessingGraphWorkflowScientificCsvExportResult,
) -> dict[str, object]:
    if result.skipped:
        return {}
    return {
        "rg_timeseries_csv": _optional_path_string(
            result.rg_timeseries_csv_path
        ),
        "contact_edges_csv": _optional_path_string(
            result.contact_edges_csv_path
        ),
        "contacts_perframe_csv": _optional_path_string(
            result.contacts_perframe_csv_path
        ),
    }


def _scientific_validation_payload(
    validation_result: object | None,
) -> dict[str, object] | None:
    if validation_result is None:
        return None
    to_dict = getattr(validation_result, "to_dict", None)
    if not callable(to_dict):
        return {"passed": _stage_result_passed(validation_result)}
    payload = to_dict()
    if not isinstance(payload, dict):
        return {"passed": _stage_result_passed(validation_result)}
    safe_payload = _json_safe_value(payload)
    if isinstance(safe_payload, dict):
        return cast(dict[str, object], safe_payload)
    return {"passed": _stage_result_passed(validation_result)}


def _json_safe_value(value: object) -> object:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {
            str(key): _json_safe_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _diagnostics_run_payload(
    diagnostics_run_result: object | None,
) -> dict[str, object] | None:
    if diagnostics_run_result is None:
        return None
    to_dict = getattr(diagnostics_run_result, "to_dict", None)
    if not callable(to_dict):
        return None
    payload = to_dict()
    if not isinstance(payload, dict):
        return None
    allowed_keys = {
        "nodes_csv_path",
        "edges_csv_path",
        "graph_json_path",
        "passed",
        "node_count",
        "edge_count",
        "detected_conditions",
        "check_count",
        "failed_check_count",
        "issue_count",
        "checks",
        "issues",
    }
    return {
        str(key): value
        for key, value in payload.items()
        if isinstance(key, str) and key in allowed_keys
    }


def _contacts_result_invalid_issue(
    contacts_result: object,
) -> PreprocessingGraphWorkflowGraphExportIssue | None:
    passed = getattr(contacts_result, "passed", None)
    if passed is None:
        return None
    if not isinstance(passed, bool):
        return PreprocessingGraphWorkflowGraphExportIssue(
            kind="contacts_result_invalid",
            message=(
                "Contacts result exposes an invalid passed status for graph "
                "export."
            ),
            stage="contacts",
            field="contacts_result.passed",
            value=_object_type(contacts_result),
        )
    if not passed:
        return PreprocessingGraphWorkflowGraphExportIssue(
            kind="contacts_result_invalid",
            message="Contacts result did not pass; graph export was not attempted.",
            stage="contacts",
            field="contacts_result",
            value=_object_type(contacts_result),
        )
    return None


def _graph_output_layout_issue(
    output_layout: PreprocessingGraphWorkflowOutputLayout,
) -> PreprocessingGraphWorkflowGraphExportIssue | None:
    expected_graph_dir = output_layout.output_dir / "graph"
    expected_paths = {
        "graph_nodes_csv_path": expected_graph_dir / "nodes.csv",
        "graph_edges_csv_path": expected_graph_dir / "edges.csv",
        "graph_json_path": expected_graph_dir / "graph.json",
    }
    for field_name, expected_path in expected_paths.items():
        actual_path = getattr(output_layout, field_name)
        if actual_path != expected_path:
            return PreprocessingGraphWorkflowGraphExportIssue(
                kind="output_layout_invalid",
                message=(
                    "Graph export output layout does not match the Stage "
                    "15.1 graph artifact boundary."
                ),
                stage="output_layout",
                field=field_name,
                path=actual_path,
                value=str(expected_path),
            )
    return None


def _graph_export_failed_issue(
    *,
    kind: str,
    stage: str,
    field: str,
    result: object,
    path: Path | None = None,
) -> PreprocessingGraphWorkflowGraphExportIssue:
    return PreprocessingGraphWorkflowGraphExportIssue(
        kind=kind,
        message=f"Stage 14 {stage} step did not pass.",
        stage=stage,
        field=field,
        path=path,
        value=_object_type(result),
    )


def _graph_export_exception_issue(
    *,
    kind: str,
    stage: str,
    field: str,
    exc: Exception,
    path: Path | None = None,
) -> PreprocessingGraphWorkflowGraphExportIssue:
    return PreprocessingGraphWorkflowGraphExportIssue(
        kind=kind,
        message=f"Stage 14 {stage} step failed unexpectedly: {exc.__class__.__name__}.",
        stage=stage,
        field=field,
        path=path,
    )


def _diagnostics_output_layout_issue(
    output_layout: PreprocessingGraphWorkflowOutputLayout,
) -> PreprocessingGraphWorkflowDiagnosticsIssue | None:
    expected_path = (
        output_layout.output_dir
        / "reports"
        / "graph_diagnostics_report.json"
    )
    actual_path = output_layout.diagnostics_report_json_path
    if actual_path != expected_path:
        return PreprocessingGraphWorkflowDiagnosticsIssue(
            kind="output_layout_invalid",
            message=(
                "Diagnostics report output layout does not match the Stage "
                "15.1 report artifact boundary."
            ),
            stage="output_layout",
            field="diagnostics_report_json_path",
            path=actual_path,
            value=str(expected_path),
        )
    return None


def _graph_artifact_path_issue(
    graph_export: PreprocessingGraphWorkflowGraphExportResult,
) -> PreprocessingGraphWorkflowDiagnosticsIssue | None:
    expected_paths = {
        "graph_nodes_csv_path": graph_export.output_layout.graph_nodes_csv_path,
        "graph_edges_csv_path": graph_export.output_layout.graph_edges_csv_path,
        "graph_json_path": graph_export.output_layout.graph_json_path,
    }
    for field_name, expected_path in expected_paths.items():
        actual_path = getattr(graph_export, field_name)
        if actual_path != expected_path:
            return PreprocessingGraphWorkflowDiagnosticsIssue(
                kind="graph_artifact_missing",
                message=(
                    "Stage 15.5 graph artifact path metadata was not "
                    "available at the planned output layout path."
                ),
                stage="graph_export",
                field=field_name,
                path=actual_path,
                value=str(expected_path),
            )
    return None


def _diagnostics_failed_issue(
    *,
    kind: str,
    stage: str,
    field: str,
    result: object,
) -> PreprocessingGraphWorkflowDiagnosticsIssue:
    return PreprocessingGraphWorkflowDiagnosticsIssue(
        kind=kind,
        message=f"Stage 14 {stage} step did not pass.",
        stage=stage,
        field=field,
        value=_object_type(result),
    )


def _diagnostics_exception_issue(
    *,
    kind: str,
    stage: str,
    field: str,
    exc: Exception,
) -> PreprocessingGraphWorkflowDiagnosticsIssue:
    return PreprocessingGraphWorkflowDiagnosticsIssue(
        kind=kind,
        message=f"Stage 14 {stage} step failed unexpectedly: {exc.__class__.__name__}.",
        stage=stage,
        field=field,
    )


def _reference_comparison_output_layout_issue(
    output_layout: PreprocessingGraphWorkflowOutputLayout,
) -> PreprocessingGraphWorkflowReferenceComparisonIssue | None:
    expected_path = (
        output_layout.output_dir
        / "reports"
        / "graph_reference_comparison.json"
    )
    actual_path = output_layout.reference_comparison_json_path
    if actual_path != expected_path:
        return PreprocessingGraphWorkflowReferenceComparisonIssue(
            kind="output_layout_invalid",
            message=(
                "Reference comparison output layout does not match the Stage "
                "15.1 report artifact boundary."
            ),
            stage="output_layout",
            field="reference_comparison_json_path",
            path=actual_path,
            value=str(expected_path),
        )
    return None


def _reference_graph_artifact_path_issue(
    graph_export: PreprocessingGraphWorkflowGraphExportResult,
) -> PreprocessingGraphWorkflowReferenceComparisonIssue | None:
    expected_paths = {
        "graph_nodes_csv_path": graph_export.output_layout.graph_nodes_csv_path,
        "graph_edges_csv_path": graph_export.output_layout.graph_edges_csv_path,
        "graph_json_path": graph_export.output_layout.graph_json_path,
    }
    for field_name, expected_path in expected_paths.items():
        actual_path = getattr(graph_export, field_name)
        if actual_path != expected_path:
            return PreprocessingGraphWorkflowReferenceComparisonIssue(
                kind="graph_artifact_missing",
                message=(
                    "Stage 15.5 graph artifact path metadata was not "
                    "available at the planned output layout path."
                ),
                stage="graph_export",
                field=field_name,
                path=actual_path,
                value=str(expected_path),
            )
    return None


def _reference_comparison_failed_issue(
    *,
    kind: str,
    stage: str,
    field: str,
    result: object,
) -> PreprocessingGraphWorkflowReferenceComparisonIssue:
    return PreprocessingGraphWorkflowReferenceComparisonIssue(
        kind=kind,
        message=f"Stage 14 {stage} step did not pass.",
        stage=stage,
        field=field,
        value=_object_type(result),
    )


def _reference_comparison_exception_issue(
    *,
    kind: str,
    stage: str,
    field: str,
    exc: Exception,
) -> PreprocessingGraphWorkflowReferenceComparisonIssue:
    return PreprocessingGraphWorkflowReferenceComparisonIssue(
        kind=kind,
        message=f"Stage 14 {stage} step failed unexpectedly: {exc.__class__.__name__}.",
        stage=stage,
        field=field,
    )


def _reference_comparison_metadata(
    comparison_result: object | None,
) -> dict[str, object]:
    input_validation = getattr(comparison_result, "input_validation", None)
    return {
        "reference_semantics": _optional_string_attr(
            comparison_result,
            "reference_semantics",
        ),
        "generated_condition": _optional_string_attr(
            comparison_result,
            "generated_condition",
        ),
        "reference_condition": _optional_string_attr(
            comparison_result,
            "reference_condition",
        ),
        "generated_schema_version": _optional_string_attr(
            comparison_result,
            "generated_schema_version",
        ),
        "reference_schema_version": _optional_string_attr(
            comparison_result,
            "reference_schema_version",
        ),
        "target_count": _optional_non_negative_int_attr(
            comparison_result,
            "target_count",
        ),
        "failed_target_count": _optional_non_negative_int_attr(
            comparison_result,
            "failed_target_count",
        ),
        "mismatch_count": _optional_non_negative_int_attr(
            comparison_result,
            "mismatch_count",
        ),
        "input_validation_passed": _optional_bool_attr(
            input_validation,
            "passed",
        ),
        "input_validation_issue_count": _optional_non_negative_int_attr(
            input_validation,
            "issue_count",
        ),
        "generated_node_count": _optional_non_negative_int_attr(
            input_validation,
            "generated_node_count",
        ),
        "generated_edge_count": _optional_non_negative_int_attr(
            input_validation,
            "generated_edge_count",
        ),
        "reference_node_count": _optional_non_negative_int_attr(
            input_validation,
            "reference_node_count",
        ),
        "reference_edge_count": _optional_non_negative_int_attr(
            input_validation,
            "reference_edge_count",
        ),
    }


def _optional_string_attr(value: object | None, attr_name: str) -> str | None:
    attr_value = getattr(value, attr_name, None)
    if isinstance(attr_value, str):
        return attr_value
    return None


def _optional_bool_attr(value: object | None, attr_name: str) -> bool | None:
    attr_value = getattr(value, attr_name, None)
    if isinstance(attr_value, bool):
        return attr_value
    return None


def _optional_non_negative_int_attr(
    value: object | None,
    attr_name: str,
) -> int | None:
    attr_value = getattr(value, attr_name, None)
    if (
        not isinstance(attr_value, bool)
        and isinstance(attr_value, int)
        and attr_value >= 0
    ):
        return attr_value
    return None


def _write_diagnostics_report_json(
    diagnostics_report: object,
    output_path: Path,
    *,
    create_parent_directories: bool,
) -> None:
    to_dict = getattr(diagnostics_report, "to_dict", None)
    if not callable(to_dict):
        raise ValueError("diagnostics_report must expose to_dict")
    if create_parent_directories:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = to_dict()
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_reference_comparison_report_json(
    reference_comparison: PreprocessingGraphWorkflowReferenceComparisonResult,
    output_path: Path,
    *,
    create_parent_directories: bool,
) -> None:
    if create_parent_directories:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = reference_comparison.to_dict()
    output_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _append_failed_computation_issue(
    *,
    result: object | None,
    kind: str,
    stage: str,
    field: str,
    issues: list[PreprocessingGraphWorkflowComputationIssue],
) -> None:
    if result is None:
        issues.append(
            PreprocessingGraphWorkflowComputationIssue(
                kind="computation_result_invalid",
                message=(
                    "Computation returned no result object for requested "
                    f"{stage} stage."
                ),
                stage=stage,
                field=field,
            )
        )
        return

    passed = getattr(result, "passed", None)
    if not isinstance(passed, bool):
        issues.append(
            PreprocessingGraphWorkflowComputationIssue(
                kind="computation_result_invalid",
                message=(
                    "Computation result does not expose a boolean passed "
                    "status."
                ),
                stage=stage,
                field="passed",
                value=_object_type(result),
            )
        )
        return

    if not passed:
        issues.append(
            PreprocessingGraphWorkflowComputationIssue(
                kind=kind,
                message=f"{stage} computation did not pass.",
                stage=stage,
                field=field,
                value=_object_type(result),
            )
        )


def _computation_exception_issue(
    *,
    kind: str,
    stage: str,
    field: str,
    exc: Exception,
) -> PreprocessingGraphWorkflowComputationIssue:
    return PreprocessingGraphWorkflowComputationIssue(
        kind=kind,
        message=(
            f"{stage} computation failed unexpectedly: "
            f"{exc.__class__.__name__}."
        ),
        stage=stage,
        field=field,
    )


def _manifest_load_issue(
    manifest_path: Path,
    exc: Exception,
) -> PreprocessingGraphWorkflowManifestReadinessIssue:
    exception_name = exc.__class__.__name__
    if exception_name == _MANIFEST_CONTRACT_EXCEPTION_NAME:
        kind = "manifest_contract_invalid"
        message = "Manifest does not conform to the preprocessing contract."
    elif exception_name in _MANIFEST_LOAD_EXCEPTION_NAMES:
        kind = "manifest_load_failed"
        message = f"Manifest could not be loaded: {exception_name}."
    else:
        kind = "unexpected_error"
        message = f"Manifest readiness failed unexpectedly: {exception_name}."
    return PreprocessingGraphWorkflowManifestReadinessIssue(
        kind=kind,
        message=message,
        field="manifest_path",
        path=manifest_path,
    )


def _path_validation_issues(
    validation_report: PreprocessingPathValidationReport,
) -> tuple[PreprocessingGraphWorkflowManifestReadinessIssue, ...]:
    issues: list[PreprocessingGraphWorkflowManifestReadinessIssue] = []
    for path_issue in validation_report.issues:
        if path_issue.kind == "missing":
            kind = "local_path_missing"
            message = f"Declared local file path does not exist: {path_issue.path}"
        elif path_issue.kind in {"not_file", "not_directory"}:
            kind = "local_path_is_directory"
            message = f"Declared local path has the wrong type: {path_issue.path}"
        else:
            kind = "manifest_path_validation_failed"
            message = f"Declared local path failed validation: {path_issue.path}"
        issues.append(
            PreprocessingGraphWorkflowManifestReadinessIssue(
                kind=kind,
                message=message,
                field=path_issue.field,
                condition_name=path_issue.condition,
                path=path_issue.path,
            )
        )
    return tuple(issues)


def _condition_readiness_issues(
    *,
    condition_names: tuple[str, ...],
    expected_condition_names: tuple[str, ...],
) -> tuple[PreprocessingGraphWorkflowManifestReadinessIssue, ...]:
    issues: list[PreprocessingGraphWorkflowManifestReadinessIssue] = []
    if len(condition_names) != len(expected_condition_names):
        issues.append(
            PreprocessingGraphWorkflowManifestReadinessIssue(
                kind="condition_count_mismatch",
                message=(
                    "Manifest condition count does not match the expected "
                    "condition count."
                ),
                field="conditions",
                value=(
                    f"expected={len(expected_condition_names)},"
                    f"actual={len(condition_names)}"
                ),
            )
        )
    existing_names = set(condition_names)
    for expected_condition_name in expected_condition_names:
        if expected_condition_name not in existing_names:
            issues.append(
                PreprocessingGraphWorkflowManifestReadinessIssue(
                    kind="condition_missing",
                    message=(
                        "Expected condition is missing from manifest: "
                        f"{expected_condition_name}"
                    ),
                    field="conditions",
                    condition_name=expected_condition_name,
                )
            )
    return tuple(issues)


__all__ = [
    "PreprocessingGraphWorkflowAnalysisInputExportIssue",
    "PreprocessingGraphWorkflowAnalysisInputExportResult",
    "PreprocessingGraphWorkflowManifestReadinessIssue",
    "PreprocessingGraphWorkflowManifestReadinessResult",
    "PreprocessingGraphWorkflowIssue",
    "PreprocessingGraphWorkflowOptions",
    "PreprocessingGraphWorkflowOutputLayout",
    "PreprocessingGraphWorkflowPlan",
    "PreprocessingGraphWorkflowRuntimeLoadingIssue",
    "PreprocessingGraphWorkflowRuntimeLoadingResult",
    "build_preprocessing_graph_workflow_plan",
    "check_preprocessing_graph_workflow_manifest_readiness",
    "export_preprocessing_graph_workflow_analysis_inputs",
    "load_preprocessing_graph_workflow_condition_runtimes",
]
