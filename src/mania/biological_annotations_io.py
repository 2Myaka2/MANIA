"""Strict supplied annotations, never inferred biology or default authority."""

from pathlib import Path

from mania.biological_annotations import SystemAnnotations
from mania.canonical_reference import ProteinReference
from mania.canonical_reference_io import _read_model


def read_system_annotations(
    path: str | Path,
    *,
    reference: ProteinReference,
) -> SystemAnnotations:
    annotations = _read_model(path, SystemAnnotations)
    annotations.validate_reference(reference)
    return annotations


def __getattr__(name: str) -> object:
    if name in (
        "BIOLOGICAL_ANNOTATION_FILENAME",
        "BIOLOGICAL_ANNOTATION_KIND",
        "BIOLOGICAL_ANNOTATION_SCHEMA_VERSION",
        "BiologicalAnnotationReadError",
        "BiologicalAnnotationValidationReport",
        "read_dataset_system_biological_annotations",
        "validate_dataset_system_biological_annotations",
        "write_dataset_system_biological_annotations",
    ):
        raise ImportError(
            "Fixed NaPi2b API moved to mania_napi2b.biological_annotations_io; "
            "install mania-napi2b and explicitly select a profile."
        )
    raise AttributeError(name)
