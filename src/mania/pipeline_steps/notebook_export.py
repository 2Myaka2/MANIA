"""Pipeline step wrapper for notebook contract export."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from mania.adapters.notebook_export import (
    NotebookContractSubsetExportResult,
    export_notebook_contract_subset,
)


@dataclass(frozen=True)
class NotebookContractExportPipelineStepResult:
    """Structured result from the notebook contract export pipeline step."""

    source_dir: Path
    output_dir: Path
    conditions: tuple[str, ...]
    written_paths: tuple[Path, ...]
    run_meta_path: Path

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable pipeline step result."""
        return {
            "source_dir": str(self.source_dir),
            "output_dir": str(self.output_dir),
            "conditions": list(self.conditions),
            "written_paths": [str(path) for path in self.written_paths],
            "run_meta_path": str(self.run_meta_path),
        }


def run_notebook_contract_export_pipeline_step(
    source_dir: str | Path,
    output_dir: str | Path,
    *,
    conditions: Iterable[str] | None = None,
    frame_time_ps: float,
) -> NotebookContractExportPipelineStepResult:
    """Export notebook artifacts as a thin pipeline step."""
    normalized_source_dir = Path(source_dir)
    normalized_output_dir = Path(output_dir)
    normalized_conditions = (
        None if conditions is None else _normalize_conditions(conditions)
    )
    export_result = export_notebook_contract_subset(
        source_dir=normalized_source_dir,
        output_dir=normalized_output_dir,
        conditions=normalized_conditions,
        frame_time_ps=frame_time_ps,
    )
    run_meta_path = normalized_output_dir / "run_meta.json"

    return NotebookContractExportPipelineStepResult(
        source_dir=normalized_source_dir,
        output_dir=normalized_output_dir,
        conditions=_resolve_conditions(
            export_result,
            run_meta_path=run_meta_path,
            explicit_conditions=normalized_conditions,
        ),
        written_paths=export_result.paths,
        run_meta_path=run_meta_path,
    )


def _normalize_conditions(conditions: Iterable[str]) -> tuple[str, ...]:
    if isinstance(conditions, str):
        raise ValueError("Conditions must be an iterable of names")

    normalized_conditions: list[str] = []
    seen_conditions: set[str] = set()
    for condition in conditions:
        if not isinstance(condition, str):
            raise ValueError(f"Condition names must be strings: {condition!r}")
        normalized = condition.strip()
        if normalized == "":
            raise ValueError("Condition name must not be empty")
        if normalized in seen_conditions:
            raise ValueError(
                f"Duplicate condition name after normalization: {normalized!r}"
            )
        normalized_conditions.append(normalized)
        seen_conditions.add(normalized)
    return tuple(normalized_conditions)


def _resolve_conditions(
    export_result: NotebookContractSubsetExportResult,
    *,
    run_meta_path: Path,
    explicit_conditions: tuple[str, ...] | None,
) -> tuple[str, ...]:
    resolved_conditions = export_result.conditions_result.conditions
    if resolved_conditions:
        return resolved_conditions
    if run_meta_path.is_file():
        return _read_conditions_from_run_meta(run_meta_path)
    if explicit_conditions is not None:
        return explicit_conditions
    return _read_conditions_from_run_meta(run_meta_path)


def _read_conditions_from_run_meta(run_meta_path: Path) -> tuple[str, ...]:
    payload = json.loads(run_meta_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Run metadata must be an object: {run_meta_path}")
    conditions = payload.get("conditions")
    if not isinstance(conditions, list):
        raise ValueError(f"Run metadata conditions must be a list: {run_meta_path}")
    return _normalize_conditions(conditions)


__all__ = [
    "NotebookContractExportPipelineStepResult",
    "run_notebook_contract_export_pipeline_step",
]
