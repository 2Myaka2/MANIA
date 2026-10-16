"""Per-condition Stage 20.B protein contact artifact export."""

from __future__ import annotations

import csv
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from mania.preprocessing.trajectory_contact_accumulator import (
    InteractionAccumulator,
    InteractionAggregateResult,
)
from mania.preprocessing.trajectory_contacts import (
    PreprocessingConditionContactsResult,
    PreprocessingContactPairResult,
    PreprocessingManifestContactsResult,
)

PROTEIN_CONTACT_EDGE_COLUMNS = (
    "condition",
    "residue_index_i",
    "resid_i",
    "resname_i",
    "segment_id_i",
    "residue_index_j",
    "resid_j",
    "resname_j",
    "segment_id_j",
    "edge_type",
    "contact_frame_count",
    "sampled_frame_count",
    "contact_freq",
    "mean_dist_A",
    "std_dist_A",
    "weight",
)
PROTEIN_CONTACT_PERFRAME_COLUMNS = (
    "condition",
    "frame_index",
    "time_ps",
    "residue_index_i",
    "resid_i",
    "resname_i",
    "segment_id_i",
    "residue_index_j",
    "resid_j",
    "resname_j",
    "segment_id_j",
    "edge_type",
    "distance_A",
)


@dataclass(frozen=True)
class PreprocessingProteinContactArtifact:
    """The two Stage 20.B CSV artifacts written for one condition."""

    condition: str
    edge_path: Path
    perframe_path: Path
    edge_rows_written: int
    perframe_rows_written: int

    def to_dict(self) -> dict[str, object]:
        """Return JSON-safe artifact metadata."""
        return {
            "condition": self.condition,
            "edge_path": str(self.edge_path),
            "perframe_path": str(self.perframe_path),
            "edge_rows_written": self.edge_rows_written,
            "perframe_rows_written": self.perframe_rows_written,
        }


@dataclass(frozen=True)
class PreprocessingProteinContactCsvWriteIssue:
    """One deterministic Stage 20.B artifact write issue."""

    kind: str
    message: str
    condition: str | None = None
    path: Path | None = None

    def to_dict(self) -> dict[str, object]:
        """Return JSON-safe issue metadata."""
        return {
            "kind": self.kind,
            "message": self.message,
            "condition": self.condition,
            "path": str(self.path) if self.path is not None else None,
        }


@dataclass(frozen=True)
class PreprocessingProteinContactCsvWriteResult:
    """Summary of one per-condition Stage 20.B export attempt."""

    output_dir: Path
    artifacts: tuple[PreprocessingProteinContactArtifact, ...] = ()
    issues: tuple[PreprocessingProteinContactCsvWriteIssue, ...] = ()

    @property
    def passed(self) -> bool:
        """Return whether every requested artifact pair was written."""
        return self.issues == ()

    @property
    def edge_paths_by_condition(self) -> dict[str, Path]:
        """Return aggregate edge paths keyed by original condition name."""
        return {
            artifact.condition: artifact.edge_path
            for artifact in self.artifacts
        }

    @property
    def perframe_paths_by_condition(self) -> dict[str, Path]:
        """Return per-frame paths keyed by original condition name."""
        return {
            artifact.condition: artifact.perframe_path
            for artifact in self.artifacts
        }

    def to_dict(self) -> dict[str, object]:
        """Return JSON-safe result metadata."""
        return {
            "output_dir": str(self.output_dir),
            "passed": self.passed,
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "issues": [issue.to_dict() for issue in self.issues],
        }


@dataclass(frozen=True)
class _ResidueIdentity:
    residue_index: int
    resid: int | str | None
    resname: str
    segment_id: str | None


@dataclass(frozen=True)
class _Observation:
    frame_index: int
    time_ps: float | None
    residue_i: _ResidueIdentity
    residue_j: _ResidueIdentity
    edge_type: str
    distance_A: float


def write_preprocessing_protein_contact_artifacts_csv(
    contacts_result: (
        PreprocessingManifestContactsResult
        | PreprocessingConditionContactsResult
    ),
    output_dir: str | Path,
) -> PreprocessingProteinContactCsvWriteResult:
    """Write Stage 20.B aggregate and per-frame CSVs for each condition."""
    try:
        path = Path(output_dir)
    except TypeError:
        return _failed_result(
            Path(""),
            kind="invalid_output_dir",
            message="output_dir must be a string or Path.",
        )
    if isinstance(output_dir, str) and not output_dir.strip():
        return _failed_result(
            path,
            kind="invalid_output_dir",
            message="output_dir must not be empty.",
        )

    condition_results = _condition_results(contacts_result)
    if condition_results is None:
        return _failed_result(
            path,
            kind="invalid_input",
            message=(
                "contacts_result must be a condition or manifest contacts "
                "result."
            ),
        )
    if path.exists() and not path.is_dir():
        return _failed_result(
            path,
            kind="output_dir_is_file",
            message="Protein contact output directory is an existing file.",
            issue_path=path,
        )

    prepared: list[
        tuple[
            PreprocessingConditionContactsResult,
            str,
            list[dict[str, object]],
            list[dict[str, object]],
        ]
    ] = []
    filename_conditions: dict[str, str] = {}
    for condition_result in sorted(
        condition_results,
        key=lambda result: result.condition_name,
    ):
        condition = condition_result.condition_name
        if condition_result.options.contact_selection != "protein":
            return _failed_result(
                path,
                kind="non_protein_contact_selection",
                message=(
                    "Stage 20.B artifacts require contact_selection='protein'."
                ),
                condition=condition,
            )
        if not condition_result.passed:
            return _failed_result(
                path,
                kind="condition_result_failed",
                message="Condition contacts result did not pass.",
                condition=condition,
            )
        try:
            component = _condition_filename_component(condition)
            edge_rows, perframe_rows = _artifact_rows(condition_result)
        except ValueError as error:
            return _failed_result(
                path,
                kind="invalid_contact_identity",
                message=str(error),
                condition=condition,
            )
        previous = filename_conditions.get(component)
        if previous is not None and previous != condition:
            return _failed_result(
                path,
                kind="condition_filename_collision",
                message="Condition names produce colliding contact filenames.",
                condition=condition,
            )
        filename_conditions[component] = condition
        prepared.append(
            (condition_result, component, edge_rows, perframe_rows)
        )

    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        return _failed_result(
            path,
            kind="output_dir_creation_failed",
            message="Protein contact output directory could not be created.",
            issue_path=path,
        )

    artifacts: list[PreprocessingProteinContactArtifact] = []
    for condition_result, component, edge_rows, perframe_rows in prepared:
        edge_path = path / f"protein_contact_edges_undirected_{component}.csv"
        perframe_path = path / f"contacts_perframe_{component}.csv"
        try:
            _write_csv(edge_path, PROTEIN_CONTACT_EDGE_COLUMNS, edge_rows)
            _write_csv(
                perframe_path,
                PROTEIN_CONTACT_PERFRAME_COLUMNS,
                perframe_rows,
            )
        except (OSError, csv.Error):
            return PreprocessingProteinContactCsvWriteResult(
                output_dir=path,
                artifacts=tuple(artifacts),
                issues=(
                    PreprocessingProteinContactCsvWriteIssue(
                        kind="write_failed",
                        message="Protein contact CSV file could not be written.",
                        condition=condition_result.condition_name,
                    ),
                ),
            )
        artifacts.append(
            PreprocessingProteinContactArtifact(
                condition=condition_result.condition_name,
                edge_path=edge_path,
                perframe_path=perframe_path,
                edge_rows_written=len(edge_rows),
                perframe_rows_written=len(perframe_rows),
            )
        )

    return PreprocessingProteinContactCsvWriteResult(
        output_dir=path,
        artifacts=tuple(artifacts),
    )


def _condition_results(
    contacts_result: object,
) -> tuple[PreprocessingConditionContactsResult, ...] | None:
    if isinstance(contacts_result, PreprocessingManifestContactsResult):
        return contacts_result.condition_results
    if isinstance(contacts_result, PreprocessingConditionContactsResult):
        return (contacts_result,)
    return None


def _artifact_rows(
    condition_result: PreprocessingConditionContactsResult,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    observations: dict[tuple[int, int, str, int], _Observation] = {}
    residue_identities: dict[int | str, _ResidueIdentity] = {}
    for frame in sorted(
        condition_result.frame_results,
        key=lambda result: result.frame_index,
    ):
        for contact in frame.contacts:
            observation = _observation(
                frame.frame_index,
                frame.time_ps,
                contact,
            )
            _remember_identity(residue_identities, observation.residue_i)
            _remember_identity(residue_identities, observation.residue_j)
            key = (
                observation.residue_i.residue_index,
                observation.residue_j.residue_index,
                observation.edge_type,
                observation.frame_index,
            )
            previous = observations.get(key)
            if previous is None or observation.distance_A < previous.distance_A:
                observations[key] = observation

    ordered_observations = sorted(
        observations.values(),
        key=lambda item: (
            item.frame_index,
            item.residue_i.residue_index,
            item.residue_j.residue_index,
            item.edge_type,
        ),
    )
    accumulator = InteractionAccumulator()
    for observation in ordered_observations:
        accumulator.add(
            condition_name=condition_result.condition_name,
            frame_index=observation.frame_index,
            resid_i=observation.residue_i.residue_index,
            resid_j=observation.residue_j.residue_index,
            edge_type=observation.edge_type,
            distance_A=observation.distance_A,
        )
    aggregates = accumulator.finalize(frame_count=condition_result.frame_count)
    edge_rows = [
        _edge_row(aggregate, residue_identities)
        for aggregate in aggregates
    ]
    perframe_rows = [
        _perframe_row(condition_result.condition_name, observation)
        for observation in ordered_observations
    ]
    return edge_rows, perframe_rows


def _observation(
    frame_index: int,
    time_ps: float | None,
    contact: PreprocessingContactPairResult,
) -> _Observation:
    source = _ResidueIdentity(
        residue_index=contact.source_residue_index,
        resid=contact.source_residue_id,
        resname=contact.source_resname,
        segment_id=contact.source_segid,
    )
    target = _ResidueIdentity(
        residue_index=contact.target_residue_index,
        resid=contact.target_residue_id,
        resname=contact.target_resname,
        segment_id=contact.target_segid,
    )
    residue_i, residue_j = (
        (target, source)
        if target.residue_index < source.residue_index
        else (source, target)
    )
    if contact.distance_unit.lower() not in ("angstrom", "a", "å"):
        raise ValueError("Protein contact distances must use angstrom units.")
    return _Observation(
        frame_index=frame_index,
        time_ps=time_ps,
        residue_i=residue_i,
        residue_j=residue_j,
        edge_type=contact.edge_type,
        distance_A=contact.minimum_distance,
    )


def _remember_identity(
    identities: dict[int | str, _ResidueIdentity],
    identity: _ResidueIdentity,
) -> None:
    previous = identities.setdefault(identity.residue_index, identity)
    if previous != identity:
        raise ValueError(
            "A residue_index maps to inconsistent resid/resname/segment_id "
            "values."
        )


def _edge_row(
    aggregate: InteractionAggregateResult,
    identities: dict[int | str, _ResidueIdentity],
) -> dict[str, object]:
    residue_i = identities[aggregate.resid_i]
    residue_j = identities[aggregate.resid_j]
    row = _identity_row(aggregate.condition_name, residue_i, residue_j)
    row.update(
        {
            "edge_type": aggregate.edge_type,
            "contact_frame_count": aggregate.observed_frame_count,
            "sampled_frame_count": aggregate.sampled_frame_count,
            "contact_freq": aggregate.contact_freq,
            "mean_dist_A": aggregate.mean_dist_A,
            "std_dist_A": aggregate.std_dist_A,
            "weight": aggregate.contact_freq,
        }
    )
    return row


def _perframe_row(
    condition: str,
    observation: _Observation,
) -> dict[str, object]:
    row = _identity_row(
        condition,
        observation.residue_i,
        observation.residue_j,
    )
    row.update(
        {
            "frame_index": observation.frame_index,
            "time_ps": _optional_csv_value(observation.time_ps),
            "edge_type": observation.edge_type,
            "distance_A": observation.distance_A,
        }
    )
    return row


def _identity_row(
    condition: str,
    residue_i: _ResidueIdentity,
    residue_j: _ResidueIdentity,
) -> dict[str, object]:
    return {
        "condition": condition,
        "residue_index_i": residue_i.residue_index,
        "resid_i": _optional_csv_value(residue_i.resid),
        "resname_i": residue_i.resname,
        "segment_id_i": _optional_csv_value(residue_i.segment_id),
        "residue_index_j": residue_j.residue_index,
        "resid_j": _optional_csv_value(residue_j.resid),
        "resname_j": residue_j.resname,
        "segment_id_j": _optional_csv_value(residue_j.segment_id),
    }


def _condition_filename_component(condition: str) -> str:
    component = re.sub(r"[^A-Za-z0-9_.-]+", "_", condition).strip("._")
    if not component:
        raise ValueError(
            "Condition must contain a filename-safe character for contact export."
        )
    return component


def _write_csv(
    output_path: Path,
    columns: tuple[str, ...],
    rows: list[dict[str, object]],
) -> None:
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as csv_file:
            temporary_path = Path(csv_file.name)
            writer = csv.DictWriter(
                csv_file,
                fieldnames=columns,
                lineterminator="\n",
            )
            writer.writeheader()
            writer.writerows(rows)
        temporary_path.replace(output_path)
    except (OSError, csv.Error):
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


def _optional_csv_value(value: object | None) -> object:
    return "" if value is None else value


def _failed_result(
    output_dir: Path,
    *,
    kind: str,
    message: str,
    condition: str | None = None,
    issue_path: Path | None = None,
) -> PreprocessingProteinContactCsvWriteResult:
    return PreprocessingProteinContactCsvWriteResult(
        output_dir=output_dir,
        issues=(
            PreprocessingProteinContactCsvWriteIssue(
                kind=kind,
                message=message,
                condition=condition,
                path=issue_path,
            ),
        ),
    )


__all__ = [
    "PROTEIN_CONTACT_EDGE_COLUMNS",
    "PROTEIN_CONTACT_PERFRAME_COLUMNS",
    "PreprocessingProteinContactArtifact",
    "PreprocessingProteinContactCsvWriteIssue",
    "PreprocessingProteinContactCsvWriteResult",
    "write_preprocessing_protein_contact_artifacts_csv",
]
