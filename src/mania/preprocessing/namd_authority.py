"""Explicit, source-bound NAMD controls; no element or physical-time guessing."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from decimal import Context, Decimal, localcontext
from pathlib import Path
from typing import Annotated, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

Text = Annotated[str, Field(min_length=1)]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
PositiveInt = Annotated[int, Field(gt=0)]
Element = Literal["H", "C", "N", "O", "P", "S", "Na", "Cl"]


class AuthorityModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class SourceIdentity(AuthorityModel):
    path: Text
    size_bytes: PositiveInt
    sha256: Digest


class SourceRecord(AuthorityModel):
    source: SourceIdentity
    line: PositiveInt
    text: Text


class TypeDefinition(SourceRecord):
    atom_type: Text
    mass: Text
    element_token: str | None


class ReviewedAssignment(AuthorityModel):
    atom_type: Text
    element: Element
    status: Literal["accepted", "unresolved", "rejected"]
    rationale: Text
    evidence: tuple[SourceRecord, ...] = Field(min_length=1)


class ElementEntry(AuthorityModel):
    atom_type: Text
    element: Element
    authority_kind: Literal["direct_definition", "reviewed_explicit_assignment"]
    status: Literal["accepted"]
    definitions: tuple[TypeDefinition, ...] = Field(min_length=1)
    review: ReviewedAssignment | None


class ElementControl(AuthorityModel):
    schema_version: Literal["mania.namd_atom_type_elements.v1"]
    engine: Literal["NAMD"]
    psf: SourceIdentity
    source_directory: Text
    sources: tuple[SourceIdentity, ...] = Field(min_length=1)
    used_type_counts: dict[Text, PositiveInt]
    entries: tuple[ElementEntry, ...] = Field(min_length=1)


class RawFrameTime(AuthorityModel):
    frame: Annotated[int, Field(ge=0)]
    time_ps: Annotated[float, Field(allow_inf_nan=False)]


class DCDIdentity(AuthorityModel):
    path: Text
    size_bytes: PositiveInt
    atom_count: PositiveInt
    frame_count: PositiveInt
    istart: Annotated[int, Field(ge=0)]
    nsavc: PositiveInt
    delta: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    dt_ps: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    unit_cell: bool
    remarks: Text
    observed_times: tuple[RawFrameTime, ...] = Field(min_length=2)


class TimeControl(AuthorityModel):
    schema_version: Literal["mania.namd_time_authority.v1"]
    engine: Literal["NAMD"]
    config: SourceIdentity
    log: SourceIdentity
    dcd: DCDIdentity
    timestep_fs: Text
    dcd_frequency_steps: PositiveInt
    production_start_step: Annotated[int, Field(ge=0)]
    production_end_step: PositiveInt
    coordinate_write_steps: tuple[PositiveInt, ...] = Field(min_length=1)
    scientific_times_ps: tuple[Text, ...] = Field(min_length=1)
    derivation: Literal["config_log_step_times_timestep_fs_divided_by_1000"]
    status: Literal["validated"]


Control = TypeVar("Control", bound=AuthorityModel)


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def read_control(path: Path, model: type[Control]) -> Control:
    text = path.read_text(encoding="utf-8")
    json.loads(text, object_pairs_hook=_unique_pairs)
    return model.model_validate_json(text)


def read_reviewed_assignments(path: Path) -> tuple[ReviewedAssignment, ...]:
    payload = json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=_unique_pairs
    )
    if not isinstance(payload, list):
        raise ValueError("Reviewed assignments must be an explicit JSON array")
    return tuple(
        ReviewedAssignment.model_validate_json(json.dumps(row)) for row in payload
    )


def write_control(path: Path, control: AuthorityModel) -> None:
    with path.open("x", encoding="utf-8") as stream:
        stream.write(control.model_dump_json(indent=2) + "\n")


def source_identity(path: Path) -> SourceIdentity:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return SourceIdentity(
        path=str(path.resolve()),
        size_bytes=path.stat().st_size,
        sha256=digest.hexdigest(),
    )


def validate_source(source: SourceIdentity) -> None:
    if source_identity(Path(source.path)) != source:
        raise ValueError(f"Stale source identity/hash: {source.path}")


def psf_population(path: Path) -> tuple[dict[str, int], dict[str, list[str]]]:
    """Read exact NATOM types/masses; names and masses never assign elements."""
    counts: Counter[str] = Counter()
    masses: dict[str, set[str]] = {}
    with path.open() as stream:
        for line in stream:
            if "!NATOM" in line:
                count = int(line.split()[0])
                break
        else:
            raise ValueError("Missing PSF NATOM")
        for index in range(count):
            fields = next(stream).split()
            if len(fields) < 8 or int(fields[0]) != index + 1:
                raise ValueError("Invalid PSF atom record/order")
            atom_type = fields[5]
            counts[atom_type] += 1
            masses.setdefault(atom_type, set()).add(fields[7])
    if not counts:
        raise ValueError("Empty PSF")
    return dict(sorted(counts.items())), {
        key: sorted(value) for key, value in sorted(masses.items())
    }


def toppar_sources(directory: Path) -> tuple[SourceIdentity, ...]:
    return tuple(
        source_identity(path)
        for path in sorted(directory.rglob("*"))
        if path.is_file() and path.suffix in {".rtf", ".prm", ".str", ".crd"}
    )


def collect_definitions(
    sources: tuple[SourceIdentity, ...],
    used: set[str],
) -> dict[str, tuple[TypeDefinition, ...]]:
    result: dict[str, list[TypeDefinition]] = {key: [] for key in sorted(used)}
    for source in sources:
        for number, line in enumerate(Path(source.path).read_text().splitlines(), 1):
            fields = line.split("!", 1)[0].split()
            if not fields or fields[0].upper() != "MASS":
                continue
            if len(fields) < 4:
                raise ValueError("Malformed MASS definition")
            if fields[2] in used:
                if len(fields) not in (4, 5):
                    raise ValueError("Ambiguous MASS element token")
                result[fields[2]].append(
                    TypeDefinition(
                        source=source,
                        line=number,
                        text=line,
                        atom_type=fields[2],
                        mass=fields[3],
                        element_token=fields[4] if len(fields) == 5 else None,
                    )
                )
    return {key: tuple(value) for key, value in result.items()}


def definition_elements(definitions: tuple[TypeDefinition, ...]) -> set[str]:
    # CHARMM element tokens are case-insensitive; PSF TYPE KEYS are exact.
    tokens = {
        "H": "H",
        "C": "C",
        "N": "N",
        "O": "O",
        "P": "P",
        "S": "S",
        "NA": "Na",
        "CL": "Cl",
    }
    result = set()
    for definition in definitions:
        if definition.element_token is not None:
            token = definition.element_token.upper()
            if token not in tokens:
                raise ValueError(f"Unsupported explicit element token: {token}")
            result.add(tokens[token])
    if len(result) > 1:
        raise ValueError("Conflicting element definitions")
    return result


def validate_elements(control: ElementControl, psf: Path) -> dict[str, str]:
    if source_identity(psf) != control.psf:
        raise ValueError("Wrong PSF binding")
    counts, _ = psf_population(psf)
    if counts != control.used_type_counts:
        raise ValueError("Wrong exact used-type population")
    sources = toppar_sources(Path(control.source_directory))
    if sources != control.sources:
        raise ValueError("Stale source hash or incomplete source set")
    definitions = collect_definitions(sources, set(counts))
    entries = {entry.atom_type: entry for entry in control.entries}
    if len(entries) != len(control.entries) or set(entries) != set(counts):
        raise ValueError("Unknown, duplicate, or uncovered exact used type")
    for key, entry in entries.items():
        if not definitions[key] or entry.definitions != definitions[key]:
            raise ValueError(f"Incomplete/conflicting definition provenance: {key}")
        direct = definition_elements(definitions[key])
        if direct:
            if direct != {entry.element} or entry.authority_kind != "direct_definition":
                raise ValueError(f"Conflicting element authority: {key}")
            if entry.review is not None:
                raise ValueError("Direct definition cannot disguise reviewed authority")
        else:
            review = entry.review
            if (
                entry.authority_kind != "reviewed_explicit_assignment"
                or review is None
                or review.status != "accepted"
                or review.atom_type != key
                or review.element != entry.element
            ):
                raise ValueError(f"Unaccepted/unresolved reviewed mapping: {key}")
            for record in review.evidence:
                if record.source not in sources:
                    raise ValueError("Review evidence outside reviewed source set")
                lines = Path(record.source.path).read_text().splitlines()
                if record.line > len(lines) or lines[record.line - 1] != record.text:
                    raise ValueError("Stale source line evidence")
            if not any(
                record
                in [
                    SourceRecord(
                        **d.model_dump(exclude={"atom_type", "mass", "element_token"})
                    )
                    for d in definitions[key]
                ]
                for record in review.evidence
            ):
                raise ValueError("Review must cite an exact type definition")
    return {key: entry.element for key, entry in entries.items()}


def literal_config(path: Path) -> dict[str, str]:
    """A narrow literal config reader, never a Tcl interpreter."""
    keys = {"timestep", "dcdfreq", "firsttimestep", "numsteps", "dcdfile", "structure"}
    result: dict[str, str] = {}
    for line in path.read_text().splitlines():
        fields = line.split("#", 1)[0].split()
        if not fields:
            continue
        if fields[0].lower() in {
            "run",
            "minimize",
            "source",
            "if",
            "for",
            "while",
            "foreach",
            "proc",
            "eval",
            "uplevel",
            "switch",
            "catch",
            "exec",
            "namespace",
            "subst",
        }:
            raise ValueError("Nonliteral/multiple-run time authority is unsupported")
        if fields[0].lower() in keys:
            key = fields[0].lower()
            if (
                key in result
                or len(fields) != 2
                or any(c in fields[1] for c in "$[];{}")
            ):
                raise ValueError(f"Ambiguous config authority: {key}")
            result[key] = fields[1]
    if set(result) != keys:
        raise ValueError("Missing literal config authority")
    return result


def derive_time(config: Path, log: Path, frame_count: int) -> dict[str, object]:
    values = literal_config(config)
    timestep = Decimal(values["timestep"])
    if not timestep.is_finite() or timestep <= 0:
        raise ValueError("Invalid integrator timestep")
    frequency, start, end = (
        int(values[key]) for key in ("dcdfreq", "firsttimestep", "numsteps")
    )
    if frequency <= 0 or start < 0 or end <= start or start % frequency:
        raise ValueError("Unsupported production bounds/frequency")
    text = log.read_text()
    for label, expected in (
        ("TIMESTEP", timestep),
        ("DCD FREQUENCY", frequency),
        ("NUMBER OF STEPS", end),
        ("DCD FIRST STEP", start + frequency),
    ):
        found = re.findall(rf"^Info:\s+{label}\s+(\S+)\s*$", text, re.M)
        if len(found) != 1 or Decimal(found[0]) != expected:
            raise ValueError(f"Config/log disagree: {label}")
    for label, key in (("STRUCTURE FILE", "structure"), ("DCD FILENAME", "dcdfile")):
        found = re.findall(rf"^Info:\s+{label}\s+(\S+)\s*$", text, re.M)
        if found != [values[key]]:
            raise ValueError(f"Config/log source linkage differs: {label}")
    writes = re.findall(
        r"^WRITING COORDINATES TO DCD FILE (\S+) AT STEP (\d+)\s*$",
        text,
        re.M,
    )
    steps = tuple(int(step) for _, step in writes)
    expected_steps = tuple(range(start + frequency, end + 1, frequency))
    if (
        any(path != values["dcdfile"] for path, _ in writes)
        or steps != expected_steps
        or len(steps) != frame_count
    ):
        raise ValueError(
            "Missing/duplicate/irregular output steps or frame-count mismatch"
        )
    if len(re.findall(r"^WRITING COORDINATES TO DCD FILE", text, re.M)) != len(writes):
        raise ValueError("Unparsed coordinate-write record")
    with localcontext(
        Context(prec=max(50, len(str(end)) + len(values["timestep"]) + 8))
    ):
        times = tuple(format(Decimal(step) * timestep / 1000, "f") for step in steps)
    return dict(
        timestep_fs=values["timestep"],
        dcd_frequency_steps=frequency,
        production_start_step=start,
        production_end_step=end,
        coordinate_write_steps=steps,
        scientific_times_ps=times,
    )


def validate_time(control: TimeControl, dcd: Path) -> tuple[float, ...]:
    validate_source(control.config)
    validate_source(control.log)
    if (
        str(dcd.resolve()) != control.dcd.path
        or dcd.stat().st_size != control.dcd.size_bytes
    ):
        raise ValueError("Wrong DCD binding/size")
    derived = derive_time(
        Path(control.config.path), Path(control.log.path), control.dcd.frame_count
    )
    if any(getattr(control, key) != value for key, value in derived.items()):
        raise ValueError("Time control differs from config/log derivation")
    if (
        control.dcd.istart != control.coordinate_write_steps[0]
        or control.dcd.nsavc != control.dcd_frequency_steps
        or literal_config(Path(control.config.path))["dcdfile"]
        not in control.dcd.remarks
    ):
        raise ValueError("DCD header/config/log linkage differs")
    return tuple(float(Decimal(value)) for value in control.scientific_times_ps)
