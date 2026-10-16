"""Validators for manifest-level artifact metadata."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from mania.validation.artifacts import ArtifactValidationError

GLOBAL_FEATURES_KEY = "global_features"
CONDITIONS_KEY = "conditions"
RG_GLOBAL_FEATURE_KEYS = ("rg_mean_A", "rg_std_A", "n_rg_frames")


class ManifestValidationError(ArtifactValidationError):
    """Raised when manifest metadata does not satisfy the data contract."""


@dataclass(frozen=True)
class GlobalFeaturesValidationResult:
    """Validation details for manifest global feature blocks."""

    path: Path
    conditions: tuple[str, ...]
    feature_conditions: tuple[str, ...]
    required_feature_keys: tuple[str, ...]
    missing_conditions: tuple[str, ...]
    extra_conditions: tuple[str, ...]
    missing_feature_keys: Mapping[str, tuple[str, ...]]

    @property
    def is_valid(self) -> bool:
        return not self.missing_conditions and not self.missing_feature_keys


def load_manifest_json(path: str | Path) -> Mapping[str, object]:
    """Load a manifest JSON object from disk."""

    manifest_path = Path(path)
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManifestValidationError(
            f"Invalid JSON in manifest {manifest_path}: {exc.msg}"
        ) from exc

    if not isinstance(payload, dict):
        raise ManifestValidationError(f"Manifest {manifest_path} must be a JSON object")

    return payload


def get_manifest_conditions(manifest: Mapping[str, object]) -> tuple[str, ...]:
    """Return normalized condition names from a manifest conditions block."""

    conditions = manifest.get(CONDITIONS_KEY)
    if not isinstance(conditions, (list, tuple)):
        raise ManifestValidationError(
            f"Manifest {CONDITIONS_KEY!r} must be a list of condition names"
        )
    return tuple(str(condition) for condition in conditions)


def validate_global_features(
    path: str | Path,
    *,
    expected_conditions: Sequence[str] | None = None,
    required_feature_keys: Sequence[str] = RG_GLOBAL_FEATURE_KEYS,
    allow_extra_conditions: bool = True,
) -> GlobalFeaturesValidationResult:
    """Validate manifest global feature metadata."""

    manifest_path = Path(path)
    manifest = load_manifest_json(manifest_path)
    global_features = manifest.get(GLOBAL_FEATURES_KEY)
    if not isinstance(global_features, dict):
        raise ManifestValidationError(
            f"Manifest {manifest_path} must contain object {GLOBAL_FEATURES_KEY!r}"
        )

    if isinstance(expected_conditions, str):
        raise ManifestValidationError(
            "expected_conditions must be a sequence of strings"
        )

    if isinstance(required_feature_keys, str):
        raise ManifestValidationError(
            "required_feature_keys must be a sequence of strings"
        )

    if expected_conditions is not None:
        conditions = tuple(str(condition) for condition in expected_conditions)
    elif CONDITIONS_KEY in manifest:
        conditions = get_manifest_conditions(manifest)
    else:
        conditions = tuple(str(condition) for condition in global_features)

    feature_conditions = tuple(str(condition) for condition in global_features)
    required_keys = tuple(str(key) for key in required_feature_keys)

    feature_condition_set = set(feature_conditions)
    expected_condition_set = set(conditions)
    missing_conditions = tuple(
        condition for condition in conditions if condition not in feature_condition_set
    )
    extra_conditions = tuple(
        condition
        for condition in feature_conditions
        if condition not in expected_condition_set
    )

    missing_feature_keys: dict[str, tuple[str, ...]] = {}
    errors: list[str] = []
    if missing_conditions:
        errors.append(f"missing conditions: {', '.join(missing_conditions)}")
    if extra_conditions and not allow_extra_conditions:
        errors.append(f"extra conditions: {', '.join(extra_conditions)}")

    for condition in conditions:
        if condition not in global_features:
            continue

        feature_object = global_features[condition]
        if not isinstance(feature_object, dict):
            errors.append(f"global_features[{condition!r}] must be an object")
            continue

        missing_keys = tuple(key for key in required_keys if key not in feature_object)
        if missing_keys:
            missing_feature_keys[condition] = missing_keys
            missing_keys_text = ", ".join(missing_keys)
            errors.append(
                f"global_features[{condition!r}] missing keys: {missing_keys_text}"
            )

        for key in required_keys:
            if key in feature_object:
                _validate_known_rg_feature(condition, key, feature_object[key])

    result = GlobalFeaturesValidationResult(
        path=manifest_path,
        conditions=conditions,
        feature_conditions=feature_conditions,
        required_feature_keys=required_keys,
        missing_conditions=missing_conditions,
        extra_conditions=extra_conditions,
        missing_feature_keys=missing_feature_keys,
    )

    if errors:
        raise ManifestValidationError(
            f"Manifest {manifest_path} global features invalid: {'; '.join(errors)}"
        )

    return result


def _validate_known_rg_feature(condition: str, key: str, value: object) -> None:
    if key in {"rg_mean_A", "rg_std_A"}:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ManifestValidationError(
                f"global_features[{condition!r}][{key!r}] must be a non-negative number"
            )
        if value < 0:
            raise ManifestValidationError(
                f"global_features[{condition!r}][{key!r}] must be non-negative"
            )
        return

    if key == "n_rg_frames":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ManifestValidationError(
                f"global_features[{condition!r}][{key!r}] must be a positive integer"
            )
        if value <= 0:
            raise ManifestValidationError(
                f"global_features[{condition!r}][{key!r}] must be positive"
            )
