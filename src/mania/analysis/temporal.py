"""Stage 22.A temporal contact input and sampled-frame window contract."""

from __future__ import annotations

import csv
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from mania.constants import EDGE_TYPE_PRIORITY
from mania.preprocessing.trajectory_protein_contact_export import (
    PROTEIN_CONTACT_PERFRAME_COLUMNS,
)

TEMP_WINDOW: Final = 10
TEMP_STEP: Final = 10
TEMP_MIN_FREQ: Final = 0.25

_EDGE_TYPE_PRIORITY_INDEX = {
    edge_type: index for index, edge_type in enumerate(EDGE_TYPE_PRIORITY)
}


class TemporalRinInputError(ValueError):
    """Raised when a Stage 20 per-frame contact artifact is invalid."""


@dataclass(frozen=True)
class TemporalRinConfig:
    """Validated Stage 22 temporal configuration defaults."""

    window_size: int = TEMP_WINDOW
    step_size: int = TEMP_STEP
    min_frequency: float = TEMP_MIN_FREQ

    def __post_init__(self) -> None:
        _require_positive_int(self.window_size, "window_size")
        _require_positive_int(self.step_size, "step_size")
        if (
            isinstance(self.min_frequency, bool)
            or not isinstance(self.min_frequency, (int, float))
            or not math.isfinite(self.min_frequency)
            or not 0.0 <= self.min_frequency <= 1.0
        ):
            raise ValueError("min_frequency must be a finite number in [0, 1]")

    def to_dict(self) -> dict[str, object]:
        """Return JSON-safe configuration metadata."""
        return {
            "window_size": self.window_size,
            "step_size": self.step_size,
            "min_frequency": self.min_frequency,
        }


@dataclass(frozen=True)
class TemporalContactRow:
    """One validated, normalized Stage 20 per-frame contact observation."""

    condition: str
    frame_index: int
    time_ps: float | None
    residue_index_i: int
    resid_i: str
    resname_i: str
    segment_id_i: str | None
    residue_index_j: int
    resid_j: str
    resname_j: str
    segment_id_j: str | None
    edge_type: str
    distance_A: float | None


@dataclass(frozen=True)
class TemporalWindow:
    """One window over ordinal positions in the sampled-frame sequence."""

    condition: str
    window_id: int
    frame_start: int
    frame_end: int
    frame_start_ordinal: int
    frame_end_ordinal: int
    sampled_frame_count: int
    frame_indexes: tuple[int, ...]

    @property
    def contact_frequency_denominator(self) -> int:
        """Return the denominator reserved for Stage 22.B contact frequency."""
        return self.sampled_frame_count


@dataclass(frozen=True)
class TemporalRinInput:
    """Validated temporal rows, sampled frames, and deterministic windows."""

    condition: str
    config: TemporalRinConfig
    rows: tuple[TemporalContactRow, ...]
    sampled_frame_indexes: tuple[int, ...]
    windows: tuple[TemporalWindow, ...]


@dataclass(frozen=True)
class _ResidueIdentity:
    residue_index: int
    resid: str
    resname: str
    segment_id: str | None


def load_temporal_rin_input(
    contacts_perframe_path: str | Path,
    *,
    condition: str,
    config: TemporalRinConfig | None = None,
) -> TemporalRinInput:
    """Load and validate one accepted ``contacts_perframe_{condition}.csv``.

    Empty or header-only artifacts produce no rows, sampled frames, or windows.
    The explicit ``condition`` remains the identity for that empty input.
    """
    expected_condition = _required_condition(condition)
    selected_config = config or TemporalRinConfig()
    source_rows = _read_csv_rows(Path(contacts_perframe_path))

    identities: dict[int, _ResidueIdentity] = {}
    observation_keys: set[tuple[int, int, int, str]] = set()
    parsed_rows: list[TemporalContactRow] = []
    for row_number, row in enumerate(source_rows, start=2):
        row_condition = _required_text(
            row["condition"], "condition", row_number
        )
        if row_condition != expected_condition:
            raise TemporalRinInputError(
                f"condition mismatch at row {row_number}: "
                f"expected {expected_condition!r}, got {row_condition!r}"
            )
        frame_index = _required_non_negative_int(
            row["frame_index"], "frame_index", row_number
        )
        endpoint_i = _endpoint(row, "i", row_number)
        endpoint_j = _endpoint(row, "j", row_number)
        if endpoint_i.residue_index == endpoint_j.residue_index:
            raise TemporalRinInputError(
                f"self edge is not allowed at row {row_number}"
            )
        if endpoint_j.residue_index < endpoint_i.residue_index:
            endpoint_i, endpoint_j = endpoint_j, endpoint_i
        _remember_identity(identities, endpoint_i, row_number)
        _remember_identity(identities, endpoint_j, row_number)

        edge_type = _required_text(row["edge_type"], "edge_type", row_number)
        if edge_type not in _EDGE_TYPE_PRIORITY_INDEX:
            raise TemporalRinInputError(
                f"unsupported Stage 20 edge_type at row {row_number}: "
                f"{edge_type}"
            )
        observation_key = (
            frame_index,
            endpoint_i.residue_index,
            endpoint_j.residue_index,
            edge_type,
        )
        if observation_key in observation_keys:
            raise TemporalRinInputError(
                "duplicate frame/residue-pair/edge_type observation at row "
                f"{row_number}: {observation_key}"
            )
        observation_keys.add(observation_key)

        parsed_rows.append(
            TemporalContactRow(
                condition=expected_condition,
                frame_index=frame_index,
                time_ps=_optional_float(row["time_ps"], "time_ps", row_number),
                residue_index_i=endpoint_i.residue_index,
                resid_i=endpoint_i.resid,
                resname_i=endpoint_i.resname,
                segment_id_i=endpoint_i.segment_id,
                residue_index_j=endpoint_j.residue_index,
                resid_j=endpoint_j.resid,
                resname_j=endpoint_j.resname,
                segment_id_j=endpoint_j.segment_id,
                edge_type=edge_type,
                distance_A=_optional_non_negative_float(
                    row["distance_A"], "distance_A", row_number
                ),
            )
        )

    rows = tuple(sorted(parsed_rows, key=_contact_row_sort_key))
    sampled_frames = tuple(sorted({row.frame_index for row in rows}))
    windows = generate_temporal_windows(
        expected_condition,
        sampled_frames,
        config=selected_config,
    )
    return TemporalRinInput(
        condition=expected_condition,
        config=selected_config,
        rows=rows,
        sampled_frame_indexes=sampled_frames,
        windows=windows,
    )


def generate_temporal_windows(
    condition: str,
    sampled_frame_indexes: Iterable[int],
    *,
    config: TemporalRinConfig | None = None,
) -> tuple[TemporalWindow, ...]:
    """Generate 0-based windows over sorted unique sampled-frame indexes.

    ``frame_start`` and ``frame_end`` are the first and last assigned source
    frame indexes, both inclusive. Numeric gaps never create inferred frames.
    A final non-empty partial window is emitted when reached by ``step_size``.
    """
    normalized_condition = _required_condition(condition)
    selected_config = config or TemporalRinConfig()
    normalized_frames: set[int] = set()
    for frame_index in sampled_frame_indexes:
        if isinstance(frame_index, bool) or not isinstance(frame_index, int):
            raise ValueError("sampled_frame_indexes must contain integers")
        if frame_index < 0:
            raise ValueError("sampled_frame_indexes must be non-negative")
        normalized_frames.add(frame_index)
    frames = tuple(sorted(normalized_frames))

    windows: list[TemporalWindow] = []
    for start_ordinal in range(0, len(frames), selected_config.step_size):
        window_frames = frames[
            start_ordinal : start_ordinal + selected_config.window_size
        ]
        if not window_frames:
            continue
        end_ordinal = start_ordinal + len(window_frames) - 1
        windows.append(
            TemporalWindow(
                condition=normalized_condition,
                window_id=len(windows),
                frame_start=window_frames[0],
                frame_end=window_frames[-1],
                frame_start_ordinal=start_ordinal,
                frame_end_ordinal=end_ordinal,
                sampled_frame_count=len(window_frames),
                frame_indexes=window_frames,
            )
        )
    return tuple(windows)


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8", newline="") as csv_file:
            reader = csv.DictReader(csv_file)
            fieldnames = reader.fieldnames
            if fieldnames is None:
                raise TemporalRinInputError(
                    "contacts_perframe artifact is missing a header"
                )
            missing = [
                column
                for column in PROTEIN_CONTACT_PERFRAME_COLUMNS
                if column not in fieldnames
            ]
            if missing:
                raise TemporalRinInputError(
                    "contacts_perframe artifact is missing required columns: "
                    + ", ".join(missing)
                )
            return [
                {
                    column: value if value is not None else ""
                    for column, value in row.items()
                    if column is not None
                }
                for row in reader
            ]
    except FileNotFoundError as error:
        raise TemporalRinInputError(
            f"missing contacts_perframe artifact: {path}"
        ) from error
    except (OSError, UnicodeError, csv.Error) as error:
        raise TemporalRinInputError(
            f"contacts_perframe artifact could not be read: {path}"
        ) from error


def _endpoint(
    row: Mapping[str, str], suffix: str, row_number: int
) -> _ResidueIdentity:
    return _ResidueIdentity(
        residue_index=_required_non_negative_int(
            row[f"residue_index_{suffix}"],
            f"residue_index_{suffix}",
            row_number,
        ),
        resid=_required_text(row[f"resid_{suffix}"], f"resid_{suffix}", row_number),
        resname=_required_text(
            row[f"resname_{suffix}"], f"resname_{suffix}", row_number
        ),
        segment_id=_optional_text(row[f"segment_id_{suffix}"]),
    )


def _remember_identity(
    identities: dict[int, _ResidueIdentity],
    identity: _ResidueIdentity,
    row_number: int,
) -> None:
    previous = identities.setdefault(identity.residue_index, identity)
    if previous != identity:
        raise TemporalRinInputError(
            "residue_index maps to inconsistent resid/resname/segment_id "
            f"at row {row_number}: {identity.residue_index}"
        )


def _contact_row_sort_key(
    row: TemporalContactRow,
) -> tuple[int, int, int, int, str]:
    return (
        row.frame_index,
        row.residue_index_i,
        row.residue_index_j,
        _EDGE_TYPE_PRIORITY_INDEX[row.edge_type],
        row.edge_type,
    )


def _required_condition(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("condition must be a non-empty string")
    return value.strip()


def _required_text(value: str, field: str, row_number: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise TemporalRinInputError(f"empty {field} at row {row_number}")
    return normalized


def _optional_text(value: str) -> str | None:
    normalized = value.strip()
    return normalized or None


def _required_non_negative_int(
    value: str, field: str, row_number: int
) -> int:
    normalized = value.strip()
    if not normalized:
        raise TemporalRinInputError(f"empty {field} at row {row_number}")
    try:
        parsed = int(normalized)
    except ValueError as error:
        raise TemporalRinInputError(
            f"invalid integer {field} at row {row_number}"
        ) from error
    if parsed < 0:
        raise TemporalRinInputError(
            f"{field} must be non-negative at row {row_number}"
        )
    return parsed


def _optional_float(value: str, field: str, row_number: int) -> float | None:
    normalized = value.strip()
    if not normalized:
        return None
    try:
        parsed = float(normalized)
    except ValueError as error:
        raise TemporalRinInputError(
            f"invalid numeric {field} at row {row_number}"
        ) from error
    if not math.isfinite(parsed):
        raise TemporalRinInputError(f"non-finite {field} at row {row_number}")
    return parsed


def _optional_non_negative_float(
    value: str, field: str, row_number: int
) -> float | None:
    parsed = _optional_float(value, field, row_number)
    if parsed is not None and parsed < 0:
        raise TemporalRinInputError(
            f"{field} must be non-negative at row {row_number}"
        )
    return parsed


def _require_positive_int(value: object, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field} must be a positive integer")


__all__ = [
    "TEMP_MIN_FREQ",
    "TEMP_STEP",
    "TEMP_WINDOW",
    "TemporalContactRow",
    "TemporalRinConfig",
    "TemporalRinInput",
    "TemporalRinInputError",
    "TemporalWindow",
    "generate_temporal_windows",
    "load_temporal_rin_input",
]
