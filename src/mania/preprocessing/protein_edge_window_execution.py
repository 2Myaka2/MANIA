"""Join retained Dataset temporal bindings to already computed protein contacts."""

from mania.preprocessing.physical_time_execution import (
    PreprocessingConditionTemporalExecution,
    PreprocessingTemporalExecution,
)
from mania.preprocessing.protein_edge_window_table import (
    DatasetProteinEdgeWindowTable,
    DatasetProteinEdgeWindowTableError,
    DatasetProteinEdgeWindowTableInput,
    build_dataset_protein_edge_window_table,
)
from mania.preprocessing.protein_edge_windows import (
    ProteinEdgeWindowAggregationError,
    aggregate_protein_edges_by_window,
)
from mania.preprocessing.trajectory_contacts import (
    PreprocessingConditionContactsResult,
    PreprocessingManifestContactsResult,
)


class PreprocessingProteinEdgeWindowExecutionError(ValueError):
    """Retained execution/contact evidence cannot form a source table."""


def build_preprocessing_protein_edge_window_source_table(
    temporal_execution: PreprocessingTemporalExecution,
    contacts_result: PreprocessingManifestContactsResult,
) -> DatasetProteinEdgeWindowTable:
    """Route by execution condition after binding; retain replica identity unchanged."""
    for value, model, name in (
        (temporal_execution, PreprocessingTemporalExecution, "temporal_execution"),
        (contacts_result, PreprocessingManifestContactsResult, "contacts_result"),
    ):
        if type(value) is not model:
            raise PreprocessingProteinEdgeWindowExecutionError(
                f"{name} must be exact {model.__name__}"
            )
    conditions: dict[str, PreprocessingConditionContactsResult] = {}
    for result in contacts_result.condition_results:
        if type(result) is not PreprocessingConditionContactsResult:
            raise PreprocessingProteinEdgeWindowExecutionError(
                "Contact conditions must be exact PreprocessingConditionContactsResult"
            )
        if result.condition_name in conditions:
            raise PreprocessingProteinEdgeWindowExecutionError(
                "Contact execution conditions must be unique"
            )
        conditions[result.condition_name] = result
    inputs = []
    try:
        for binding in temporal_execution.bindings:
            if type(binding) is not PreprocessingConditionTemporalExecution:
                raise PreprocessingProteinEdgeWindowExecutionError(
                    "Temporal bindings must be exact condition executions"
                )
            matching_result = conditions.get(binding.execution_condition)
            if matching_result is None:
                raise PreprocessingProteinEdgeWindowExecutionError(
                    "Each Dataset temporal binding requires one contact condition"
                )
            aggregation = aggregate_protein_edges_by_window(
                binding.sampling_plan,
                binding.window_plan,
                contacts_result=matching_result,
            )
            inputs.append(DatasetProteinEdgeWindowTableInput(binding, aggregation))
        return build_dataset_protein_edge_window_table(tuple(inputs))
    except (ProteinEdgeWindowAggregationError, DatasetProteinEdgeWindowTableError):
        raise PreprocessingProteinEdgeWindowExecutionError(
            "Retained Dataset protein contacts or window evidence are invalid"
        ) from None


__all__ = [
    "PreprocessingProteinEdgeWindowExecutionError",
    "build_preprocessing_protein_edge_window_source_table",
]
