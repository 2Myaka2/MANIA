"""Strict per-frame evidence persistence; no coordinates or trajectory readers.

The existing protein CSV is authoritative for protein observations. Its additive
completion index retains zero-contact frames and typed residue identities. The
specialized files retain the accepted frame-result contracts without rounding.
"""

import csv
import json
from collections.abc import Mapping
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any, cast

from mania.preprocessing.molecular_partner_catalog_io import (
    read_molecular_partner_catalog,
    write_molecular_partner_catalog,
)
from mania.preprocessing.molecular_partner_metadata_io import (
    exact_fields,
    json_array,
    read_strict_json,
    reconstruct_record,
    write_atomic_text,
)
from mania.preprocessing.physical_time_execution import PreprocessingTemporalExecution
from mania.preprocessing.physical_time_sampling import (
    MissingPhysicalTimeSample,
    ResolvedPhysicalTimeSample,
)
from mania.preprocessing.protein_glycan_contacts import (
    ProteinGlycanContactFrameResult,
    ProteinGlycanContactObservation,
)
from mania.preprocessing.protein_lipid_contacts import (
    ProteinLipidContactFrameResult,
    ProteinLipidContactObservation,
)
from mania.preprocessing.specialized_contact_execution import (
    PreprocessingSpecializedContactConditionResult,
    PreprocessingSpecializedContactExecution,
)
from mania.preprocessing.trajectory_contacts import (
    PreprocessingBackboneObservation,
    PreprocessingConditionContactsResult,
    PreprocessingContactDetectionOptions,
    PreprocessingContactFrameResult,
    PreprocessingContactPairResult,
    PreprocessingManifestContactsResult,
)
from mania.preprocessing.trajectory_contacts_export import (
    _TYPED_CSV_HEADER,
    _interaction_rows,
    write_contacts_perframe_csv,
)

PERFRAME_COMPLETION_VERSION = "mania.perframe_completion.v0.1"
PROTEIN_LIPID_PERFRAME_VERSION = "mania.protein_lipid_perframe.v0.1"
PROTEIN_GLYCAN_PERFRAME_VERSION = "mania.protein_glycan_perframe.v0.1"
PERFRAME_COMPLETION_FILENAME = "perframe_completion.json"
PROTEIN_PERFRAME_PATH = "contacts/contacts_perframe.csv"
SPECIALIZED_PERFRAME_FILES = {
    "lipid": "protein_lipid_perframe.json",
    "glycan": "protein_glycan_perframe.json",
}


class PerFrameObservationError(ValueError):
    """Observation evidence is incomplete, ambiguous, or inconsistent."""


@dataclass(frozen=True)
class PersistedPerFrameObservations:
    protein: PreprocessingManifestContactsResult
    specialized: PreprocessingSpecializedContactExecution
    prepared_frame_indexes: tuple[tuple[str, tuple[int, ...]], ...] = ()


def _equal(actual: Any, expected: Any) -> bool:
    """JSON structural equality that never accepts bool as an integer/count."""
    if type(expected) is dict:
        return (
            type(actual) is dict
            and actual.keys() == expected.keys()
            and all(_equal(actual[k], v) for k, v in expected.items())
        )
    if type(expected) is list:
        return (
            type(actual) is list
            and len(actual) == len(expected)
            and all(_equal(a, b) for a, b in zip(actual, expected, strict=True))
        )
    if isinstance(actual, bool) or isinstance(expected, bool):
        return type(actual) is type(expected) and actual == expected
    return type(actual) is type(expected) and bool(actual == expected)


def _require_equal(actual: Any, expected: Any, message: str) -> None:
    if not _equal(actual, expected):
        raise PerFrameObservationError(message)


def _count(value: Any) -> int:
    if type(value) is not int or value < 0:
        raise PerFrameObservationError(
            "Completion counts must be non-negative integers"
        )
    return value


def _residues(result: PreprocessingConditionContactsResult) -> list[dict[str, Any]]:
    residues: dict[int, dict[str, Any]] = {}
    for frame in result.frame_results:
        seen = set()
        for contact in cast(
            tuple[
                PreprocessingContactPairResult | PreprocessingBackboneObservation, ...
            ],
            (*frame.contacts, *frame.backbone_observations),
        ):
            key = (
                *sorted((contact.source_residue_index, contact.target_residue_index)),
                contact.edge_type,
            )
            if key in seen:
                raise PerFrameObservationError("Duplicate protein observation")
            seen.add(key)
            for side in ("source", "target"):
                record = {
                    name: getattr(contact, f"{side}_{name}")
                    for name in ("residue_index", "residue_id", "resname", "segid")
                }
                index = record["residue_index"]
                if index in residues:
                    _require_equal(residues[index], record, "Protein identity changed")
                residues[index] = record
    return [residues[i] for i in sorted(residues)]


def _specialized_frame(value: Any, kind: str) -> Any:
    model, observation = (
        (ProteinLipidContactFrameResult, ProteinLipidContactObservation)
        if kind == "lipid"
        else (ProteinGlycanContactFrameResult, ProteinGlycanContactObservation)
    )
    raw = exact_fields(value, {f.name for f in fields(model)})
    contacts = []
    for contact in json_array(raw["contacts"]):
        values = exact_fields(contact, {f.name for f in fields(observation)})
        name = f"{kind}_component_residue_indexes"
        values[name] = tuple(json_array(values[name]))
        contacts.append(observation(**values))
    raw["contacts"] = tuple(contacts)
    result = reconstruct_record(raw, model)
    _require_equal(value, result.to_dict(), "Invalid specialized frame serialization")
    return result


def _check_partner_evidence(
    result: PreprocessingSpecializedContactConditionResult,
) -> None:
    partners = {p.partner_id: p for p in result.partner_catalog.partners}
    components = {i for p in partners.values() for i in p.component_residue_indexes}
    identities: dict[int, tuple[Any, ...]] = {}
    for kind in ("lipid", "glycan"):
        frames = getattr(result, f"{kind}_frame_results")
        protein_counts = {f.protein_residue_count for f in frames}
        if len(protein_counts) > 1:
            raise PerFrameObservationError("Protein count changed between frames")
        for frame in frames:
            for contact in frame.contacts:
                partner = partners.get(getattr(contact, f"{kind}_partner_id"))
                if partner is None or partner.partner_kind != kind:
                    raise PerFrameObservationError("Unknown specialized partner")
                if contact.protein_residue_index in components:
                    raise PerFrameObservationError(
                        "Protein overlaps partner components"
                    )
                identity = (
                    contact.protein_residue_id,
                    contact.protein_resname,
                    contact.protein_segid,
                )
                if contact.protein_residue_index in identities:
                    _require_equal(
                        list(identities[contact.protein_residue_index]),
                        list(identity),
                        "Specialized protein identity changed",
                    )
                identities[contact.protein_residue_index] = identity
                for name in ("partner_name", "component_residue_indexes"):
                    if getattr(contact, f"{kind}_{name}") != getattr(partner, name):
                        raise PerFrameObservationError("Partner membership mismatch")
                if kind == "glycan":
                    for name in (
                        "carrier_residue_index",
                        "first_sugar_residue_index",
                        "linkage_evidence",
                    ):
                        if getattr(contact, name) != getattr(partner, name):
                            raise PerFrameObservationError("Glycan linkage mismatch")
                    carrier = sugar = None
                    if partner.carrier_link_bond is not None:
                        a = partner.carrier_link_bond.atom_index_a
                        b = partner.carrier_link_bond.atom_index_b
                        first = next(
                            r
                            for r in partner.components
                            if r.residue_index == partner.first_sugar_residue_index
                        )
                        sugar, carrier = (a, b) if a in first.atom_indexes else (b, a)
                    if (
                        contact.carrier_link_atom_index,
                        contact.first_sugar_link_atom_index,
                    ) != (carrier, sugar):
                        raise PerFrameObservationError("Glycan linkage atoms mismatch")


def _documents(
    temporal: PreprocessingTemporalExecution,
    observations: PersistedPerFrameObservations,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Validate complete coverage before publishing any completion marker."""
    protein, specialized = observations.protein, observations.specialized
    if not protein.passed:
        raise PerFrameObservationError("Protein computation must have passed")
    conditions = tuple(b.execution_condition for b in temporal.bindings)
    if tuple(c.condition_name for c in protein.condition_results) != conditions:
        raise PerFrameObservationError(
            "Protein conditions must exactly match temporal order"
        )
    specialized_by_name = {
        c.execution_condition: c for c in specialized.condition_results
    }
    if tuple(specialized_by_name) != tuple(
        c for c in conditions if c in specialized_by_name
    ):
        raise PerFrameObservationError(
            "Specialized conditions must match temporal order"
        )
    prepared = dict(observations.prepared_frame_indexes)
    if len(prepared) != len(
        observations.prepared_frame_indexes
    ) or not prepared.keys() <= set(conditions):
        raise PerFrameObservationError("Invalid prepared-frame condition roster")
    bindings = []
    layers: dict[str, dict[str, Any]] = {
        kind: {
            "schema_version": version,
            "kind": f"mania_protein_{kind}_perframe",
            "bindings": [],
            "completion": "complete",
        }
        for kind, version in (
            ("lipid", PROTEIN_LIPID_PERFRAME_VERSION),
            ("glycan", PROTEIN_GLYCAN_PERFRAME_VERSION),
        )
    }
    for binding, result in zip(
        temporal.bindings, protein.condition_results, strict=True
    ):
        if result.options.contact_selection != "protein":
            raise PerFrameObservationError("Protein-only contact selection required")
        selected = binding.sampling_plan.selected_samples
        prepared_indexes = prepared.get(binding.execution_condition)
        if prepared_indexes is not None:
            if (
                len(prepared_indexes) != len(selected)
                or any(type(i) is not int or i < 0 for i in prepared_indexes)
                or tuple(sorted(set(prepared_indexes))) != prepared_indexes
            ):
                raise PerFrameObservationError(
                    "Prepared indexes must cover selected samples uniquely"
                )
        prepared_by_source = dict(
            zip(
                binding.selected_source_frame_indexes,
                prepared_indexes or (),
                strict=prepared_indexes is not None,
            )
        )
        if (
            tuple(f.frame_index for f in result.frame_results)
            != binding.selected_source_frame_indexes
        ):
            raise PerFrameObservationError("Incomplete or unordered protein frame set")
        frames = {f.frame_index: f for f in result.frame_results}
        special = specialized_by_name.get(binding.execution_condition)
        special_frames: dict[str, dict[int, Any]] = {}
        if special is not None:
            if special.dataset_spec.identity != binding.dataset_spec.identity:
                raise PerFrameObservationError("Specialized Dataset identity mismatch")
            _check_partner_evidence(special)
            for kind in layers:
                count = getattr(special.partner_catalog, f"{kind}_partner_count")
                values = getattr(special, f"{kind}_frame_results")
                if tuple(f.frame_index for f in values) != (
                    binding.selected_source_frame_indexes if count else ()
                ):
                    raise PerFrameObservationError("Incomplete specialized frame set")
                special_frames[kind] = {f.frame_index: f for f in values}
                for selected_sample, frame in zip(
                    selected if count else (), values, strict=True
                ):
                    if frame.time_ps != selected_sample.actual_time_ps:
                        raise PerFrameObservationError(
                            "Specialized frame time mismatch"
                        )
                layers[kind]["bindings"].append(
                    {
                        "execution_condition": binding.execution_condition,
                        "frames": [f.to_dict() for f in values],
                        "frame_count": len(values),
                        "observation_count": sum(f.contact_count for f in values),
                    }
                )
        selected_by_index = {s.requested_sample_index: s for s in selected}
        requested = sorted(
            cast(
                tuple[ResolvedPhysicalTimeSample | MissingPhysicalTimeSample, ...],
                (*selected, *binding.sampling_plan.missing_samples),
            ),
            key=lambda s: s.requested_sample_index,
        )
        samples = []
        for request in requested:
            sample = selected_by_index.get(request.requested_sample_index)
            completion: dict[str, Any] = {}
            if sample is not None:
                frame = frames[sample.source_frame_index]
                completion["protein"] = {
                    "status": "complete",
                    "time_ps": frame.time_ps,
                    "contact_count": frame.contact_count,
                    "backbone_count": len(frame.backbone_observations),
                }
                for kind in layers:
                    if special is None:
                        completion[kind] = {"status": "unavailable"}
                    elif not getattr(special.partner_catalog, f"{kind}_partner_count"):
                        completion[kind] = {"status": "not_applicable"}
                    else:
                        sf = special_frames[kind][sample.source_frame_index]
                        completion[kind] = {
                            "status": "complete",
                            "contact_count": sf.contact_count,
                        }
            samples.append(
                {
                    "requested_sample_index": request.requested_sample_index,
                    "requested_time_ps": request.requested_time_ps,
                    "state": "resolved" if sample is not None else "missing",
                    "source_frame_index": sample.source_frame_index if sample else None,
                    "actual_time_ps": sample.actual_time_ps if sample else None,
                    "prepared_frame_index": prepared_by_source.get(
                        sample.source_frame_index
                    )
                    if sample
                    else None,
                    "completion": completion if sample is not None else None,
                }
            )
        bindings.append(
            {
                "execution_condition": binding.execution_condition,
                "dataset_identity": binding.dataset_spec.identity.to_dict(),
                "sampling_plan": binding.sampling_plan.to_dict(),
                "protein_options": result.options.to_dict(
                    include_contact_selection=True
                ),
                "protein_residues": _residues(result),
                "samples": samples,
            }
        )
    return {
        "schema_version": PERFRAME_COMPLETION_VERSION,
        "kind": "mania_perframe_completion",
        "completion": "complete",
        "specialized_conditions": list(specialized_by_name),
        "bindings": bindings,
        "protein_csv_row_count": sum(
            len(f.contacts) + len(f.backbone_observations)
            for c in protein.condition_results
            for f in c.frame_results
        ),
    }, layers


def write_perframe_observations(
    output_dir: str | Path,
    temporal: PreprocessingTemporalExecution,
    protein: PreprocessingManifestContactsResult,
    specialized: PreprocessingSpecializedContactExecution | None = None,
    *,
    overwrite: bool = False,
    prepared_frame_indexes: Mapping[str, tuple[int, ...]] | None = None,
) -> tuple[tuple[str, Path], ...]:
    """Write observations and publish completion last; never infer missing frames.

    Writes the accepted protein CSV using its existing writer. Existing identical
    protein/catalog files are reused, allowing integration with normal exports.
    """
    root = Path(output_dir)
    evidence = PersistedPerFrameObservations(
        protein,
        specialized or PreprocessingSpecializedContactExecution(()),
        tuple(
            (b.execution_condition, prepared_frame_indexes[b.execution_condition])
            for b in temporal.bindings
            if prepared_frame_indexes is not None
            and b.execution_condition in prepared_frame_indexes
        ),
    )
    if prepared_frame_indexes is not None and set(prepared_frame_indexes) != {
        c for c, _ in evidence.prepared_frame_indexes
    }:
        raise PerFrameObservationError("Unknown prepared-frame condition")
    index, layers = _documents(temporal, evidence)
    paths = [
        ("perframe_completion", root / PERFRAME_COMPLETION_FILENAME),
        ("contacts_perframe", root / PROTEIN_PERFRAME_PATH),
    ]
    if evidence.specialized.condition_results:
        paths.extend(
            (f"protein_{kind}_perframe", root / filename)
            for kind, filename in SPECIALIZED_PERFRAME_FILES.items()
        )
    # Completion is a commit marker: invalidate it before any authorized overwrite.
    if paths[0][1].exists():
        if not overwrite:
            raise PerFrameObservationError("Completion target already exists")
        paths[0][1].unlink()
    for role, path in paths[2:]:
        if path.exists() and not overwrite:
            raise PerFrameObservationError(f"{role} target already exists")
    protein_path = root / PROTEIN_PERFRAME_PATH
    protein_path.parent.mkdir(parents=True, exist_ok=True)
    if protein_path.exists() and not overwrite:
        with protein_path.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.reader(stream, strict=True))
        expected = [
            list(_TYPED_CSV_HEADER),
            *[
                list(row)
                for c in protein.condition_results
                for f in c.frame_results
                for row in _interaction_rows(f, include_edge_type=True)
            ],
        ]
        _require_equal(rows, expected, "Existing protein CSV differs")
    elif not write_contacts_perframe_csv(protein, protein_path).passed:
        raise PerFrameObservationError("Protein CSV write failed")
    if evidence.specialized.condition_results:
        catalog_path = root / "molecular_partner_catalog.json"
        catalog = evidence.specialized.catalog()
        if catalog_path.exists() and not overwrite:
            if read_molecular_partner_catalog(catalog_path) != catalog:
                raise PerFrameObservationError("Existing partner catalog differs")
        elif not write_molecular_partner_catalog(
            catalog, root, overwrite=overwrite
        ).passed:
            raise PerFrameObservationError("Partner catalog write failed")
        for kind, filename in SPECIALIZED_PERFRAME_FILES.items():
            _write_json(layers[kind], root / filename, overwrite)
    _write_json(index, root / PERFRAME_COMPLETION_FILENAME, overwrite)
    return tuple(paths)


def _write_json(value: dict[str, Any], path: Path, overwrite: bool) -> None:
    written = write_atomic_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        path,
        overwrite=overwrite,
    )
    if not written.passed:
        raise PerFrameObservationError(f"Observation write failed: {written.error}")


def _read_protein(
    index: dict[str, Any],
    root: Path,
    temporal: PreprocessingTemporalExecution,
) -> PreprocessingManifestContactsResult:
    with (root / PROTEIN_PERFRAME_PATH).open(encoding="utf-8", newline="") as stream:
        rows = list(csv.reader(stream, strict=True))
    if not rows or tuple(rows.pop(0)) != _TYPED_CSV_HEADER:
        raise PerFrameObservationError("Exact typed protein CSV header required")
    if len(rows) != _count(index["protein_csv_row_count"]):
        raise PerFrameObservationError("Incomplete protein CSV")
    offset = 0
    conditions = []
    for raw, binding in zip(
        json_array(index["bindings"]), temporal.bindings, strict=True
    ):
        residues = {r["residue_index"]: r for r in json_array(raw["protein_residues"])}
        options = exact_fields(
            raw["protein_options"],
            {f.name for f in fields(PreprocessingContactDetectionOptions)},
        )
        options["skip_resnames"] = tuple(json_array(options["skip_resnames"]))
        frames = []
        samples = json_array(raw["samples"])
        if len(samples) != binding.sampling_plan.requested_sample_count:
            raise PerFrameObservationError("Incomplete requested sample ledger")
        for sample in binding.sampling_plan.selected_samples:
            recorded = samples[sample.requested_sample_index]
            completion = recorded["completion"]["protein"]
            contact_count = _count(completion["contact_count"])
            backbone_count = _count(completion["backbone_count"])
            contacts, backbone = [], []
            count = contact_count + backbone_count
            for row in rows[offset : offset + count]:
                if len(row) != len(_TYPED_CSV_HEADER):
                    raise PerFrameObservationError("Invalid protein CSV cell count")
                cells = dict(zip(_TYPED_CSV_HEADER, row, strict=True))
                values: dict[str, Any] = {}
                for side in ("source", "target"):
                    residue = residues[int(cells[f"{side}_residue_index"])]
                    values.update(
                        {
                            f"{side}_{name}": residue[name]
                            for name in (
                                "residue_index",
                                "residue_id",
                                "resname",
                                "segid",
                            )
                        }
                    )
                values.update(
                    edge_type=cells["edge_type"], distance_unit=cells["distance_unit"]
                )
                distance_text = cells["minimum_distance"]
                distance = (
                    int(distance_text)
                    if distance_text.isdecimal()
                    else float(distance_text)
                )
                if cells["edge_type"] == "backbone":
                    backbone.append(
                        PreprocessingBackboneObservation(**values, ca_distance=distance)
                    )
                else:
                    contacts.append(
                        PreprocessingContactPairResult(
                            **values,
                            minimum_distance=distance,
                            atom_filter=cells["atom_filter"],
                        )
                    )
            frame = PreprocessingContactFrameResult(
                binding.execution_condition,
                sample.source_frame_index,
                completion["time_ps"],
                tuple(contacts),
                tuple(backbone),
            )
            expected = [
                list(row) for row in _interaction_rows(frame, include_edge_type=True)
            ]
            _require_equal(
                rows[offset : offset + count],
                expected,
                "Protein rows disagree with completed frame/identity",
            )
            if (len(contacts), len(backbone)) != (contact_count, backbone_count):
                raise PerFrameObservationError("Incomplete protein observations")
            offset += count
            frames.append(frame)
        conditions.append(
            PreprocessingConditionContactsResult(
                binding.execution_condition,
                PreprocessingContactDetectionOptions(**options),
                frame_results=tuple(frames),
                status="computed",
            )
        )
    if offset != len(rows):
        raise PerFrameObservationError("Unexpected protein observations")
    return PreprocessingManifestContactsResult(tuple(conditions))


def read_perframe_observations(
    output_dir: str | Path,
    temporal: PreprocessingTemporalExecution,
) -> PersistedPerFrameObservations:
    """Read a complete observation set against authoritative saved temporal plans.

    A different window schedule/profile is allowed only with exactly the same
    Dataset identity and sampling plan. No geometry or time matching is performed.
    """
    try:
        root = Path(output_dir)
        index = read_strict_json(root / PERFRAME_COMPLETION_FILENAME)
        protein = _read_protein(index, root, temporal)
        names = json_array(index["specialized_conditions"])
        layers = {}
        results = []
        if names:
            catalog = read_molecular_partner_catalog(
                root / "molecular_partner_catalog.json"
            )
            if list(b.execution_condition for b in catalog.bindings) != names:
                raise PerFrameObservationError("Specialized condition roster mismatch")
            for kind, filename in SPECIALIZED_PERFRAME_FILES.items():
                layers[kind] = read_strict_json(root / filename)
            for i, binding in enumerate(catalog.bindings):
                temporal_binding = next(
                    b
                    for b in temporal.bindings
                    if b.execution_condition == binding.execution_condition
                )
                if (
                    binding.dataset_spec.identity
                    != temporal_binding.dataset_spec.identity
                ):
                    raise PerFrameObservationError("Partner Dataset identity mismatch")
                results.append(
                    PreprocessingSpecializedContactConditionResult(
                        binding.execution_condition,
                        temporal_binding.dataset_spec,
                        binding.topology_connectivity_status,
                        binding.partner_catalog,
                        *[
                            tuple(
                                _specialized_frame(f, kind)
                                for f in json_array(
                                    layers[kind]["bindings"][i]["frames"]
                                )
                            )
                            for kind in ("lipid", "glycan")
                        ],
                    )
                )
        prepared = []
        for raw in json_array(index["bindings"]):
            indexes = tuple(
                s["prepared_frame_index"]
                for s in json_array(raw["samples"])
                if s["state"] == "resolved"
            )
            if any(i is not None for i in indexes):
                prepared.append((raw["execution_condition"], indexes))
        evidence = PersistedPerFrameObservations(
            protein,
            PreprocessingSpecializedContactExecution(tuple(results)),
            tuple(prepared),
        )
        expected_index, expected_layers = _documents(temporal, evidence)
        _require_equal(index, expected_index, "Completion/sampling evidence mismatch")
        for kind in layers:
            _require_equal(
                layers[kind],
                expected_layers[kind],
                "Incomplete or invalid specialized observation file",
            )
        return evidence
    except (
        OSError,
        csv.Error,
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        StopIteration,
        OverflowError,
        RecursionError,
    ) as exc:
        raise PerFrameObservationError(
            f"Invalid per-frame persistence: {exc}"
        ) from None
