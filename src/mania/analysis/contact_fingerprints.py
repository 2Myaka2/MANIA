"""Deterministic binary contact fingerprints from validated temporal input."""

from __future__ import annotations

from dataclasses import dataclass

from mania.analysis.temporal import TemporalContactRow, TemporalRinInput
from mania.constants import EDGE_TYPE_PRIORITY

CONTACT_FINGERPRINT_STATUS_COMPUTED = "computed"
CONTACT_FINGERPRINT_STATUS_EMPTY_INPUT = "empty_input"
CONTACT_FINGERPRINT_STATUS_ZERO_FEATURES = "zero_features"

_EDGE_TYPE_PRIORITY_INDEX = {
    edge_type: index for index, edge_type in enumerate(EDGE_TYPE_PRIORITY)
}

_FeatureKey = tuple[int, int, str]


class ContactFingerprintError(ValueError):
    """Raised when validated temporal input cannot form a fingerprint matrix."""


@dataclass(frozen=True)
class ContactFingerprintFrame:
    """Identity and timing metadata for one matrix row."""

    condition: str
    row_index: int
    frame_index: int
    time_ps: float | None

    def to_dict(self) -> dict[str, object]:
        """Return deterministic frame metadata."""
        return {
            "condition": self.condition,
            "row_index": self.row_index,
            "frame_index": self.frame_index,
            "time_ps": self.time_ps,
        }


@dataclass(frozen=True)
class ContactFingerprintFeature:
    """Identity and residue metadata for one matrix column."""

    condition: str
    feature_id: str
    column_index: int
    residue_index_i: int
    resid_i: str
    resname_i: str
    segment_id_i: str | None
    residue_index_j: int
    resid_j: str
    resname_j: str
    segment_id_j: str | None
    edge_type: str
    edge_priority_rank: int

    def to_dict(self) -> dict[str, object]:
        """Return deterministic feature metadata."""
        return {
            "condition": self.condition,
            "feature_id": self.feature_id,
            "column_index": self.column_index,
            "residue_index_i": self.residue_index_i,
            "resid_i": self.resid_i,
            "resname_i": self.resname_i,
            "segment_id_i": self.segment_id_i,
            "residue_index_j": self.residue_index_j,
            "resid_j": self.resid_j,
            "resname_j": self.resname_j,
            "segment_id_j": self.segment_id_j,
            "edge_type": self.edge_type,
            "edge_priority_rank": self.edge_priority_rank,
        }


@dataclass(frozen=True)
class ContactFingerprintMatrix:
    """Condition-local frame-by-contact-feature binary matrix."""

    condition: str
    frames: tuple[ContactFingerprintFrame, ...]
    features: tuple[ContactFingerprintFeature, ...]
    values: tuple[tuple[int, ...], ...]
    status: str
    notes: str

    @property
    def shape(self) -> tuple[int, int]:
        """Return matrix row and column counts."""
        return (len(self.frames), len(self.features))

    def to_dict(self) -> dict[str, object]:
        """Return a deterministic dependency-light snapshot."""
        return {
            "condition": self.condition,
            "status": self.status,
            "notes": self.notes,
            "n_frames": len(self.frames),
            "n_features": len(self.features),
            "frames": [frame.to_dict() for frame in self.frames],
            "features": [feature.to_dict() for feature in self.features],
            "values": [list(row) for row in self.values],
        }


@dataclass(frozen=True)
class _EndpointIdentity:
    residue_index: int
    resid: str
    resname: str
    segment_id: str | None


@dataclass(frozen=True)
class _FeatureIdentity:
    endpoint_i: _EndpointIdentity
    endpoint_j: _EndpointIdentity
    edge_type: str


def build_contact_fingerprint_matrix(
    temporal_input: TemporalRinInput,
) -> ContactFingerprintMatrix:
    """Build binary per-frame fingerprints from accepted Stage 22.A rows."""
    if not isinstance(temporal_input, TemporalRinInput):
        raise TypeError("temporal_input must be a TemporalRinInput")

    condition = temporal_input.condition
    frame_indexes = temporal_input.sampled_frame_indexes
    if frame_indexes != tuple(sorted(set(frame_indexes))):
        raise ContactFingerprintError(
            "sampled_frame_indexes must be unique and sorted numerically"
        )
    frame_index_set = set(frame_indexes)
    rows_by_frame: dict[int, list[TemporalContactRow]] = {
        frame_index: [] for frame_index in frame_indexes
    }
    observed_by_frame: dict[int, set[_FeatureKey]] = {
        frame_index: set() for frame_index in frame_indexes
    }
    feature_identities: dict[_FeatureKey, _FeatureIdentity] = {}

    for row in temporal_input.rows:
        if row.condition != condition:
            raise ContactFingerprintError(
                "contact row condition does not match temporal input"
            )
        if row.frame_index not in frame_index_set:
            raise ContactFingerprintError(
                "contact row frame_index is not an accepted sampled frame"
            )
        if row.edge_type not in _EDGE_TYPE_PRIORITY_INDEX:
            raise ContactFingerprintError(
                f"unsupported contact edge_type: {row.edge_type}"
            )
        endpoint_i, endpoint_j = _normalized_endpoints(row)
        if endpoint_i.residue_index == endpoint_j.residue_index:
            raise ContactFingerprintError("self contact feature is not allowed")
        feature_key = (
            endpoint_i.residue_index,
            endpoint_j.residue_index,
            row.edge_type,
        )
        if feature_key in observed_by_frame[row.frame_index]:
            raise ContactFingerprintError(
                "duplicate frame/residue-pair/edge_type observation"
            )
        identity = _FeatureIdentity(endpoint_i, endpoint_j, row.edge_type)
        previous = feature_identities.setdefault(feature_key, identity)
        if previous != identity:
            raise ContactFingerprintError(
                "contact feature has inconsistent residue identity"
            )
        rows_by_frame[row.frame_index].append(row)
        observed_by_frame[row.frame_index].add(feature_key)

    feature_keys = tuple(sorted(feature_identities, key=_feature_sort_key))
    frames = tuple(
        ContactFingerprintFrame(
            condition=condition,
            row_index=row_index,
            frame_index=frame_index,
            time_ps=_frame_time(rows_by_frame[frame_index], frame_index),
        )
        for row_index, frame_index in enumerate(frame_indexes)
    )
    features = tuple(
        _feature(
            condition,
            column_index,
            feature_key,
            feature_identities[feature_key],
        )
        for column_index, feature_key in enumerate(feature_keys)
    )
    values = tuple(
        tuple(
            int(feature_key in observed_by_frame[frame.frame_index])
            for feature_key in feature_keys
        )
        for frame in frames
    )

    if not frames:
        status = CONTACT_FINGERPRINT_STATUS_EMPTY_INPUT
        notes = "no sampled frames"
    elif not features:
        status = CONTACT_FINGERPRINT_STATUS_ZERO_FEATURES
        notes = "sampled frames contain no contact features"
    else:
        status = CONTACT_FINGERPRINT_STATUS_COMPUTED
        notes = ""
    return ContactFingerprintMatrix(
        condition=condition,
        frames=frames,
        features=features,
        values=values,
        status=status,
        notes=notes,
    )


def _normalized_endpoints(
    row: TemporalContactRow,
) -> tuple[_EndpointIdentity, _EndpointIdentity]:
    endpoint_i = _EndpointIdentity(
        row.residue_index_i,
        row.resid_i,
        row.resname_i,
        row.segment_id_i,
    )
    endpoint_j = _EndpointIdentity(
        row.residue_index_j,
        row.resid_j,
        row.resname_j,
        row.segment_id_j,
    )
    if endpoint_j.residue_index < endpoint_i.residue_index:
        return endpoint_j, endpoint_i
    return endpoint_i, endpoint_j


def _feature_sort_key(feature_key: _FeatureKey) -> tuple[int, int, int, str]:
    residue_index_i, residue_index_j, edge_type = feature_key
    return (
        residue_index_i,
        residue_index_j,
        _EDGE_TYPE_PRIORITY_INDEX[edge_type],
        edge_type,
    )


def _feature(
    condition: str,
    column_index: int,
    feature_key: _FeatureKey,
    identity: _FeatureIdentity,
) -> ContactFingerprintFeature:
    residue_index_i, residue_index_j, edge_type = feature_key
    return ContactFingerprintFeature(
        condition=condition,
        feature_id=f"{condition}:{residue_index_i}--{residue_index_j}:{edge_type}",
        column_index=column_index,
        residue_index_i=residue_index_i,
        resid_i=identity.endpoint_i.resid,
        resname_i=identity.endpoint_i.resname,
        segment_id_i=identity.endpoint_i.segment_id,
        residue_index_j=residue_index_j,
        resid_j=identity.endpoint_j.resid,
        resname_j=identity.endpoint_j.resname,
        segment_id_j=identity.endpoint_j.segment_id,
        edge_type=edge_type,
        edge_priority_rank=_EDGE_TYPE_PRIORITY_INDEX[edge_type],
    )


def _frame_time(rows: list[TemporalContactRow], frame_index: int) -> float | None:
    times = {row.time_ps for row in rows}
    if len(times) > 1:
        raise ContactFingerprintError(
            f"sampled frame {frame_index} has inconsistent time_ps values"
        )
    return next(iter(times), None)


__all__ = [
    "CONTACT_FINGERPRINT_STATUS_COMPUTED",
    "CONTACT_FINGERPRINT_STATUS_EMPTY_INPUT",
    "CONTACT_FINGERPRINT_STATUS_ZERO_FEATURES",
    "ContactFingerprintError",
    "ContactFingerprintFeature",
    "ContactFingerprintFrame",
    "ContactFingerprintMatrix",
    "build_contact_fingerprint_matrix",
]
