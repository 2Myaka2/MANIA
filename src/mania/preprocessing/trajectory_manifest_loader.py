"""Compose condition runtime loading across one preprocessing manifest."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeAlias

from mania.preprocessing import trajectory_loader, trajectory_runtime
from mania.preprocessing.input_manifest import PreprocessingInputManifest

PreprocessingConditionLoadResult: TypeAlias = (
    trajectory_runtime.PreprocessingConditionLoadResult
)
PreprocessingConditionRuntimeInput: TypeAlias = (
    trajectory_runtime.PreprocessingConditionRuntimeInput
)
load_single_condition_runtime = trajectory_loader.load_single_condition_runtime


@dataclass(frozen=True)
class PreprocessingManifestLoadIssue:
    """One unexpected manifest-level loading issue."""

    kind: Literal[
        "no_conditions",
        "condition_input_error",
        "condition_load_error",
    ]
    condition_name: str | None
    field: str
    message: str

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable issue dictionary."""
        return {
            "kind": self.kind,
            "condition_name": self.condition_name,
            "field": self.field,
            "message": self.message,
        }


@dataclass(frozen=True)
class PreprocessingManifestLoadResult:
    """Aggregate loading result for manifest conditions."""

    condition_results: tuple[PreprocessingConditionLoadResult, ...]
    issues: tuple[PreprocessingManifestLoadIssue, ...] = ()

    @property
    def passed(self) -> bool:
        """Return whether every available condition loaded successfully."""
        return (
            self.issues == ()
            and bool(self.condition_results)
            and all(result.passed for result in self.condition_results)
        )

    @property
    def loaded_condition_names(self) -> tuple[str, ...]:
        """Return successfully loaded condition names in manifest order."""
        return tuple(
            result.condition_name
            for result in self.condition_results
            if result.passed
        )

    @property
    def failed_condition_names(self) -> tuple[str, ...]:
        """Return unsuccessful condition names in manifest order."""
        return tuple(
            result.condition_name
            for result in self.condition_results
            if not result.passed
        )

    def result_for_condition(
        self,
        condition_name: str,
    ) -> PreprocessingConditionLoadResult | None:
        """Return one exact-name condition result when available."""
        for result in self.condition_results:
            if result.condition_name == condition_name:
                return result
        return None

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable aggregate result."""
        return {
            "passed": self.passed,
            "condition_results": [
                result.to_dict() for result in self.condition_results
            ],
            "issues": [issue.to_dict() for issue in self.issues],
            "loaded_condition_names": list(self.loaded_condition_names),
            "failed_condition_names": list(self.failed_condition_names),
        }


def load_manifest_condition_runtimes(
    manifest: PreprocessingInputManifest,
    *,
    base_dir: str | Path | None = None,
) -> PreprocessingManifestLoadResult:
    """Load every manifest condition while preserving partial failures."""
    condition_names = manifest.condition_names()
    if not condition_names:
        return PreprocessingManifestLoadResult(
            condition_results=(),
            issues=(
                PreprocessingManifestLoadIssue(
                    kind="no_conditions",
                    condition_name=None,
                    field="conditions",
                    message="No manifest conditions are available to load.",
                ),
            ),
        )

    condition_results: list[PreprocessingConditionLoadResult] = []
    issues: list[PreprocessingManifestLoadIssue] = []

    for condition_name in condition_names:
        condition = manifest.get_condition(condition_name)
        try:
            runtime_input = (
                PreprocessingConditionRuntimeInput.from_manifest_condition(
                    condition_name,
                    condition,
                    base_dir=base_dir,
                )
            )
        except Exception:
            issues.append(
                PreprocessingManifestLoadIssue(
                    kind="condition_input_error",
                    condition_name=condition_name,
                    field="conditions",
                    message=(
                        "Could not build runtime input for manifest condition."
                    ),
                )
            )
            continue

        try:
            if condition.namd_element_control_path is not None:
                from mania.preprocessing.namd_runtime import NAMDControlPaths

                assert condition.namd_time_control_path is not None
                control_base = Path(base_dir) if base_dir is not None else Path.cwd()
                condition_result = load_single_condition_runtime(
                    runtime_input,
                    namd_authority=NAMDControlPaths(
                        control_base / condition.namd_element_control_path,
                        control_base / condition.namd_time_control_path,
                    ),
                )
            else:
                condition_result = load_single_condition_runtime(runtime_input)
        except Exception:
            issues.append(
                PreprocessingManifestLoadIssue(
                    kind="condition_load_error",
                    condition_name=condition_name,
                    field="condition_runtime",
                    message="The condition loader raised an unexpected error.",
                )
            )
            continue

        condition_results.append(condition_result)

    return PreprocessingManifestLoadResult(
        condition_results=tuple(condition_results),
        issues=tuple(issues),
    )


__all__ = [
    "PreprocessingManifestLoadIssue",
    "PreprocessingManifestLoadResult",
    "load_manifest_condition_runtimes",
]
