"""Condition-level graph diagnostics orchestration."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from mania.analysis.contract_graph import (
    ContractGraph,
    ContractGraphError,
    load_contract_graph_from_condition_dir,
)
from mania.analysis.graph_consistency import (
    GraphConsistencyError,
    GraphTopologyConsistencyReport,
    check_graph_topology_consistency,
    write_graph_topology_consistency_report,
)
from mania.analysis.graph_metrics import (
    GraphMetricsError,
    GraphTopologyMetrics,
    compute_graph_topology_metrics,
    write_graph_topology_metrics,
)
from mania.analysis.graph_qc import (
    GraphQCError,
    GraphQCReport,
    compute_graph_qc,
    write_graph_qc_report,
)


class GraphDiagnosticsError(Exception):
    """Raised when condition graph diagnostics cannot be completed."""


@dataclass(frozen=True)
class ConditionGraphDiagnostics:
    """Condition-level graph diagnostics result."""

    condition: str
    graph: ContractGraph
    qc_report: GraphQCReport
    topology_metrics: GraphTopologyMetrics
    topology_consistency: GraphTopologyConsistencyReport

    @property
    def passed_basic_qc(self) -> bool:
        """Return whether basic graph QC passed."""
        return self.qc_report.passed_basic_qc

    @property
    def passed_topology_consistency(self) -> bool:
        """Return whether topology consistency checks passed."""
        return self.topology_consistency.passed

    @property
    def passed(self) -> bool:
        """Return whether all condition graph diagnostics passed."""
        return self.passed_basic_qc and self.passed_topology_consistency

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable diagnostics dictionary."""
        return {
            "condition": self.condition,
            "n_nodes": self.graph.n_nodes,
            "n_edges": self.graph.n_edges,
            "passed": self.passed,
            "passed_basic_qc": self.passed_basic_qc,
            "passed_topology_consistency": self.passed_topology_consistency,
            "qc_report": self.qc_report.to_dict(),
            "topology_metrics": self.topology_metrics.to_dict(),
            "topology_consistency": self.topology_consistency.to_dict(),
        }


@dataclass(frozen=True)
class MultiConditionGraphDiagnostics:
    """Multi-condition graph diagnostics result."""

    conditions: tuple[str, ...]
    condition_diagnostics: Mapping[str, ConditionGraphDiagnostics]

    @property
    def passed(self) -> bool:
        """Return whether all condition diagnostics passed."""
        return all(
            self.condition_diagnostics[condition].passed
            for condition in self.conditions
        )

    @property
    def passed_conditions(self) -> tuple[str, ...]:
        """Return condition names with passing diagnostics in input order."""
        return tuple(
            condition
            for condition in self.conditions
            if self.condition_diagnostics[condition].passed
        )

    @property
    def failed_conditions(self) -> tuple[str, ...]:
        """Return condition names with failing diagnostics in input order."""
        return tuple(
            condition
            for condition in self.conditions
            if not self.condition_diagnostics[condition].passed
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable diagnostics dictionary."""
        return {
            "conditions": list(self.conditions),
            "passed": self.passed,
            "passed_conditions": list(self.passed_conditions),
            "failed_conditions": list(self.failed_conditions),
            "condition_diagnostics": {
                condition: self.condition_diagnostics[condition].to_dict()
                for condition in self.conditions
            },
        }


@dataclass(frozen=True)
class ConditionGraphDiagnosticsSummary:
    """Compact condition-level graph diagnostics summary."""

    condition: str
    n_nodes: int
    n_edges: int
    n_components: int
    largest_component_size: int
    n_isolated_nodes: int
    n_self_loops: int
    n_duplicate_undirected_edge_keys: int
    n_topology_mismatches: int
    passed_basic_qc: bool
    passed_topology_consistency: bool
    passed: bool

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable summary dictionary."""
        return {
            "condition": self.condition,
            "n_nodes": self.n_nodes,
            "n_edges": self.n_edges,
            "n_components": self.n_components,
            "largest_component_size": self.largest_component_size,
            "n_isolated_nodes": self.n_isolated_nodes,
            "n_self_loops": self.n_self_loops,
            "n_duplicate_undirected_edge_keys": (
                self.n_duplicate_undirected_edge_keys
            ),
            "n_topology_mismatches": self.n_topology_mismatches,
            "passed_basic_qc": self.passed_basic_qc,
            "passed_topology_consistency": self.passed_topology_consistency,
            "passed": self.passed,
        }


@dataclass(frozen=True)
class MultiConditionGraphDiagnosticsSummary:
    """Compact multi-condition graph diagnostics summary."""

    conditions: tuple[str, ...]
    condition_summaries: Mapping[str, ConditionGraphDiagnosticsSummary]

    @property
    def passed(self) -> bool:
        """Return whether all condition summaries passed."""
        return all(
            self.condition_summaries[condition].passed
            for condition in self.conditions
        )

    @property
    def passed_conditions(self) -> tuple[str, ...]:
        """Return condition names with passing summaries in input order."""
        return tuple(
            condition
            for condition in self.conditions
            if self.condition_summaries[condition].passed
        )

    @property
    def failed_conditions(self) -> tuple[str, ...]:
        """Return condition names with failing summaries in input order."""
        return tuple(
            condition
            for condition in self.conditions
            if not self.condition_summaries[condition].passed
        )

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable summary dictionary."""
        return {
            "conditions": list(self.conditions),
            "passed": self.passed,
            "passed_conditions": list(self.passed_conditions),
            "failed_conditions": list(self.failed_conditions),
            "condition_summaries": {
                condition: self.condition_summaries[condition].to_dict()
                for condition in self.conditions
            },
        }


@dataclass(frozen=True)
class OutputGraphDiagnosticsRun:
    """Run-and-write output graph diagnostics result."""

    diagnostics: MultiConditionGraphDiagnostics
    written_paths: tuple[Path, ...]

    @property
    def passed(self) -> bool:
        """Return whether output graph diagnostics passed."""
        return self.diagnostics.passed

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable run dictionary."""
        return {
            "passed": self.passed,
            "diagnostics": self.diagnostics.to_dict(),
            "written_paths": [str(path) for path in self.written_paths],
        }


@dataclass(frozen=True)
class OutputGraphDiagnosticsReportBundle:
    """Run-and-write output graph diagnostics report bundle."""

    diagnostics: MultiConditionGraphDiagnostics
    summary: MultiConditionGraphDiagnosticsSummary
    written_paths: tuple[Path, ...]

    @property
    def passed(self) -> bool:
        """Return whether output graph diagnostics passed."""
        return self.diagnostics.passed

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable report bundle dictionary."""
        return {
            "passed": self.passed,
            "diagnostics": self.diagnostics.to_dict(),
            "summary": self.summary.to_dict(),
            "written_paths": [str(path) for path in self.written_paths],
        }


def run_condition_graph_diagnostics(
    condition_dir: str | Path,
    *,
    condition: str,
    abs_tol: float = 1e-6,
    weight_column: str = "contact_freq",
    degree_column: str = "degree",
    strength_column: str = "strength",
) -> ConditionGraphDiagnostics:
    """Run graph diagnostics for one condition artifact directory."""
    normalized_condition = _normalize_condition(condition)
    condition_path = _validate_condition_dir(condition_dir)
    graph = _load_graph(condition_path, normalized_condition)

    qc_report = _compute_qc(graph)
    topology_metrics = _compute_topology_metrics(graph, weight_column)
    topology_consistency = _check_topology_consistency(
        graph,
        abs_tol=abs_tol,
        weight_column=weight_column,
        degree_column=degree_column,
        strength_column=strength_column,
    )

    return ConditionGraphDiagnostics(
        condition=normalized_condition,
        graph=graph,
        qc_report=qc_report,
        topology_metrics=topology_metrics,
        topology_consistency=topology_consistency,
    )


def run_multi_condition_graph_diagnostics(
    output_root: str | Path,
    conditions: Iterable[str],
    *,
    abs_tol: float = 1e-6,
    weight_column: str = "contact_freq",
    degree_column: str = "degree",
    strength_column: str = "strength",
) -> MultiConditionGraphDiagnostics:
    """Run graph diagnostics for multiple condition artifact directories."""
    root = _validate_output_root(output_root)
    normalized_conditions = _normalize_conditions(conditions)
    condition_diagnostics: dict[str, ConditionGraphDiagnostics] = {}

    for condition in normalized_conditions:
        condition_diagnostics[condition] = run_condition_graph_diagnostics(
            root / condition,
            condition=condition,
            abs_tol=abs_tol,
            weight_column=weight_column,
            degree_column=degree_column,
            strength_column=strength_column,
        )

    return MultiConditionGraphDiagnostics(
        conditions=normalized_conditions,
        condition_diagnostics=MappingProxyType(condition_diagnostics),
    )


def run_output_graph_diagnostics(
    output_root: str | Path,
    *,
    conditions: Iterable[str] | None = None,
    abs_tol: float = 1e-6,
    weight_column: str = "contact_freq",
    degree_column: str = "degree",
    strength_column: str = "strength",
) -> MultiConditionGraphDiagnostics:
    """Run graph diagnostics, reading conditions from run_meta.json by default."""
    root = Path(output_root)
    selected_conditions = (
        _read_conditions_from_run_meta(_validate_output_root(root))
        if conditions is None
        else conditions
    )
    return run_multi_condition_graph_diagnostics(
        root,
        selected_conditions,
        abs_tol=abs_tol,
        weight_column=weight_column,
        degree_column=degree_column,
        strength_column=strength_column,
    )


def run_and_write_output_graph_diagnostics(
    output_root: str | Path,
    diagnostics_output_dir: str | Path,
    *,
    conditions: Iterable[str] | None = None,
    abs_tol: float = 1e-6,
    weight_column: str = "contact_freq",
    degree_column: str = "degree",
    strength_column: str = "strength",
) -> OutputGraphDiagnosticsRun:
    """Run output graph diagnostics and write the diagnostics bundle."""
    diagnostics = run_output_graph_diagnostics(
        output_root,
        conditions=conditions,
        abs_tol=abs_tol,
        weight_column=weight_column,
        degree_column=degree_column,
        strength_column=strength_column,
    )
    try:
        written_paths = write_multi_condition_graph_diagnostics_bundle(
            diagnostics,
            diagnostics_output_dir,
        )
    except OSError as exc:
        raise GraphDiagnosticsError(
            f"Could not write graph diagnostics bundle: {exc}"
        ) from exc

    return OutputGraphDiagnosticsRun(
        diagnostics=diagnostics,
        written_paths=written_paths,
    )


def run_and_write_output_graph_diagnostics_report_bundle(
    output_root: str | Path,
    diagnostics_output_dir: str | Path,
    *,
    conditions: Iterable[str] | None = None,
    abs_tol: float = 1e-6,
    weight_column: str = "contact_freq",
    degree_column: str = "degree",
    strength_column: str = "strength",
) -> OutputGraphDiagnosticsReportBundle:
    """Run output graph diagnostics and write detailed and summary reports."""
    diagnostics = run_output_graph_diagnostics(
        output_root,
        conditions=conditions,
        abs_tol=abs_tol,
        weight_column=weight_column,
        degree_column=degree_column,
        strength_column=strength_column,
    )
    try:
        diagnostics_paths = write_multi_condition_graph_diagnostics_bundle(
            diagnostics,
            diagnostics_output_dir,
        )
    except OSError as exc:
        raise GraphDiagnosticsError(
            f"Could not write graph diagnostics bundle: {exc}"
        ) from exc

    summary = summarize_multi_condition_graph_diagnostics(diagnostics)
    summary_path = write_multi_condition_graph_diagnostics_summary(
        summary,
        diagnostics_output_dir,
    )

    return OutputGraphDiagnosticsReportBundle(
        diagnostics=diagnostics,
        summary=summary,
        written_paths=(*diagnostics_paths, summary_path),
    )


def summarize_condition_graph_diagnostics(
    diagnostics: ConditionGraphDiagnostics,
) -> ConditionGraphDiagnosticsSummary:
    """Summarize existing condition graph diagnostics."""
    return ConditionGraphDiagnosticsSummary(
        condition=diagnostics.condition,
        n_nodes=diagnostics.graph.n_nodes,
        n_edges=diagnostics.graph.n_edges,
        n_components=diagnostics.qc_report.n_components,
        largest_component_size=diagnostics.qc_report.largest_component_size,
        n_isolated_nodes=diagnostics.qc_report.n_isolated_nodes,
        n_self_loops=len(diagnostics.qc_report.self_loop_edges),
        n_duplicate_undirected_edge_keys=len(
            diagnostics.qc_report.duplicate_undirected_edge_keys
        ),
        n_topology_mismatches=diagnostics.topology_consistency.n_mismatches,
        passed_basic_qc=diagnostics.passed_basic_qc,
        passed_topology_consistency=diagnostics.passed_topology_consistency,
        passed=diagnostics.passed,
    )


def summarize_multi_condition_graph_diagnostics(
    diagnostics: MultiConditionGraphDiagnostics,
) -> MultiConditionGraphDiagnosticsSummary:
    """Summarize existing multi-condition graph diagnostics."""
    condition_summaries: dict[str, ConditionGraphDiagnosticsSummary] = {}
    for condition in diagnostics.conditions:
        try:
            condition_diagnostics = diagnostics.condition_diagnostics[condition]
        except KeyError as exc:
            raise GraphDiagnosticsError(
                f"Missing condition diagnostics for condition: {condition!r}"
            ) from exc
        condition_summaries[condition] = summarize_condition_graph_diagnostics(
            condition_diagnostics
        )

    return MultiConditionGraphDiagnosticsSummary(
        conditions=diagnostics.conditions,
        condition_summaries=MappingProxyType(condition_summaries),
    )


def write_multi_condition_graph_diagnostics_summary(
    summary: MultiConditionGraphDiagnosticsSummary,
    output_dir: str | Path,
) -> Path:
    """Write a compact multi-condition graph diagnostics summary JSON."""
    output_root = Path(output_dir)
    output_path = output_root / "multi_condition_graph_diagnostics_summary.json"
    try:
        output_root.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(summary.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        raise GraphDiagnosticsError(
            f"Could not write graph diagnostics summary: {exc}"
        ) from exc
    return output_path


def write_condition_graph_diagnostics(
    diagnostics: ConditionGraphDiagnostics,
    output_dir: str | Path,
) -> Path:
    """Write combined condition graph diagnostics JSON and return its path."""
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    output_path = output_root / "graph_diagnostics.json"
    output_path.write_text(
        json.dumps(diagnostics.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path


def write_multi_condition_graph_diagnostics(
    diagnostics: MultiConditionGraphDiagnostics,
    output_dir: str | Path,
) -> Path:
    """Write combined multi-condition graph diagnostics JSON."""
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    output_path = output_root / "multi_condition_graph_diagnostics.json"
    output_path.write_text(
        json.dumps(diagnostics.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output_path


def write_condition_graph_diagnostics_bundle(
    diagnostics: ConditionGraphDiagnostics,
    output_dir: str | Path,
) -> tuple[Path, ...]:
    """Write combined and lower-level condition graph diagnostics reports."""
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    return (
        write_condition_graph_diagnostics(diagnostics, output_root),
        write_graph_qc_report(diagnostics.qc_report, output_root / "graph_qc.json"),
        write_graph_topology_metrics(
            diagnostics.topology_metrics,
            output_root / "graph_topology_metrics.json",
        ),
        write_graph_topology_consistency_report(
            diagnostics.topology_consistency,
            output_root / "graph_topology_consistency.json",
        ),
    )


def write_multi_condition_graph_diagnostics_bundle(
    diagnostics: MultiConditionGraphDiagnostics,
    output_dir: str | Path,
) -> tuple[Path, ...]:
    """Write multi-condition and per-condition graph diagnostics reports."""
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = [
        write_multi_condition_graph_diagnostics(diagnostics, output_root)
    ]
    for condition in diagnostics.conditions:
        paths.extend(
            write_condition_graph_diagnostics_bundle(
                diagnostics.condition_diagnostics[condition],
                output_root / condition,
            )
        )
    return tuple(paths)


def _normalize_condition(condition: str) -> str:
    normalized = condition.strip()
    if normalized == "":
        raise GraphDiagnosticsError("Condition must be non-empty")
    return normalized


def _normalize_conditions(conditions: Iterable[str]) -> tuple[str, ...]:
    if isinstance(conditions, str):
        raise GraphDiagnosticsError("Conditions must be an iterable of names")

    normalized_conditions: list[str] = []
    seen_conditions: set[str] = set()
    for condition in conditions:
        if not isinstance(condition, str):
            raise GraphDiagnosticsError(
                f"Condition names must be strings: {condition!r}"
            )
        normalized = _normalize_condition(condition)
        if normalized in seen_conditions:
            raise GraphDiagnosticsError(f"Duplicate condition: {normalized!r}")
        normalized_conditions.append(normalized)
        seen_conditions.add(normalized)
    return tuple(normalized_conditions)


def _validate_output_root(output_root: str | Path) -> Path:
    root = Path(output_root)
    if not root.exists():
        raise GraphDiagnosticsError(f"Missing output root: {root}")
    if not root.is_dir():
        raise GraphDiagnosticsError(f"Output root is not a directory: {root}")
    return root


def _read_conditions_from_run_meta(output_root: Path) -> tuple[str, ...]:
    run_meta_path = output_root / "run_meta.json"
    if not run_meta_path.is_file():
        raise GraphDiagnosticsError(f"Missing run metadata: {run_meta_path}")
    try:
        payload = json.loads(run_meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GraphDiagnosticsError(
            f"Invalid run metadata JSON: {run_meta_path}"
        ) from exc
    if not isinstance(payload, dict):
        raise GraphDiagnosticsError(f"Run metadata must be an object: {run_meta_path}")
    if "conditions" not in payload:
        raise GraphDiagnosticsError(
            f"Run metadata is missing conditions: {run_meta_path}"
        )
    conditions = payload["conditions"]
    if not isinstance(conditions, list):
        raise GraphDiagnosticsError("Run metadata conditions must be a list")
    return _normalize_conditions(conditions)


def _validate_condition_dir(condition_dir: str | Path) -> Path:
    condition_path = Path(condition_dir)
    if not condition_path.exists():
        raise GraphDiagnosticsError(f"Missing condition directory: {condition_path}")
    if not condition_path.is_dir():
        raise GraphDiagnosticsError(
            f"Condition path is not a directory: {condition_path}"
        )
    return condition_path


def _load_graph(condition_dir: Path, condition: str) -> ContractGraph:
    try:
        return load_contract_graph_from_condition_dir(
            condition_dir,
            condition=condition,
        )
    except ContractGraphError as exc:
        raise GraphDiagnosticsError(f"Could not load contract graph: {exc}") from exc


def _compute_qc(graph: ContractGraph) -> GraphQCReport:
    try:
        return compute_graph_qc(graph)
    except GraphQCError as exc:
        raise GraphDiagnosticsError(f"Could not compute graph QC: {exc}") from exc


def _compute_topology_metrics(
    graph: ContractGraph,
    weight_column: str,
) -> GraphTopologyMetrics:
    try:
        return compute_graph_topology_metrics(graph, weight_column=weight_column)
    except GraphMetricsError as exc:
        raise GraphDiagnosticsError(
            f"Could not compute graph topology metrics: {exc}"
        ) from exc


def _check_topology_consistency(
    graph: ContractGraph,
    *,
    abs_tol: float,
    weight_column: str,
    degree_column: str,
    strength_column: str,
) -> GraphTopologyConsistencyReport:
    try:
        return check_graph_topology_consistency(
            graph,
            abs_tol=abs_tol,
            weight_column=weight_column,
            degree_column=degree_column,
            strength_column=strength_column,
        )
    except GraphConsistencyError as exc:
        raise GraphDiagnosticsError(
            f"Could not check graph topology consistency: {exc}"
        ) from exc


__all__ = [
    "ConditionGraphDiagnostics",
    "ConditionGraphDiagnosticsSummary",
    "GraphDiagnosticsError",
    "MultiConditionGraphDiagnostics",
    "MultiConditionGraphDiagnosticsSummary",
    "OutputGraphDiagnosticsReportBundle",
    "OutputGraphDiagnosticsRun",
    "run_condition_graph_diagnostics",
    "run_and_write_output_graph_diagnostics_report_bundle",
    "run_and_write_output_graph_diagnostics",
    "run_multi_condition_graph_diagnostics",
    "run_output_graph_diagnostics",
    "summarize_condition_graph_diagnostics",
    "summarize_multi_condition_graph_diagnostics",
    "write_condition_graph_diagnostics",
    "write_condition_graph_diagnostics_bundle",
    "write_multi_condition_graph_diagnostics",
    "write_multi_condition_graph_diagnostics_bundle",
    "write_multi_condition_graph_diagnostics_summary",
]
