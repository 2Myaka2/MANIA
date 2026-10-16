"""Strict UTF-8 YAML with explicit config-relative local-file admission."""

from __future__ import annotations

from collections.abc import Callable, Hashable, Iterator
from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import BaseModel, ValidationError
from yaml.nodes import MappingNode, Node

from mania.output_paths import (
    protected_product_roots,
    require_input_file,
    validate_output_root,
)
from mania.run_config import RunConfig, RunConfigError, RunPreflightError, _path


class _ClosedLoader(yaml.SafeLoader):
    def construct_mapping(
        self, node: MappingNode, deep: bool = False
    ) -> dict[Hashable, Any]:
        if not isinstance(node, MappingNode):
            raise RunConfigError("YAML object must be a mapping")
        result: dict[Hashable, Any] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if type(key) is not str or key in result:
                raise RunConfigError("YAML keys must be unique strings at every level")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def _reject_cycles(node: Node, active: set[int]) -> None:
    if id(node) in active:
        raise RunConfigError("Cyclic YAML aliases are unsupported")
    active.add(id(node))
    if isinstance(node, MappingNode):
        for key, value in node.value:
            if key.tag == "tag:yaml.org,2002:merge":
                raise RunConfigError("YAML merge keys are unsupported")
            _reject_cycles(key, active)
            _reject_cycles(value, active)
    elif isinstance(node, yaml.SequenceNode):
        for child in node.value:
            _reject_cycles(child, active)
    active.remove(id(node))


def _bind(value: Any, base: Path) -> Any:
    if isinstance(value, Path):
        return value if value.is_absolute() else base / value
    if isinstance(value, BaseModel):
        # Preserve supplied-field information: omitted defaults must not become
        # explicit frame selectors or explicit scientific requests on revalidation.
        return {
            name: _bind(getattr(value, name), base) for name in value.model_fields_set
        }
    if type(value) is tuple:
        return tuple(_bind(item, base) for item in value)
    return value


def _paths(value: object) -> Iterator[Path]:
    if isinstance(value, Path):
        yield value
    elif isinstance(value, BaseModel):
        for name in type(value).model_fields:
            yield from _paths(getattr(value, name))
    elif type(value) is tuple:
        for item in value:
            yield from _paths(item)


def load_run_config(path: str | Path) -> RunConfig:
    """Read one closed mapping; validate paths without science or output writes.

    This admission does not establish PBC, Rg eligibility, reference/mapping
    correspondence or the scientific authority of the supplied document bytes.
    Method-specific typed readers and checks belong to the execution plan.
    """
    try:
        source = _path(path)
    except ValueError as exc:
        raise RunConfigError(str(exc)) from exc
    if not source.is_absolute():
        source = Path.cwd() / source
    source = require_input_file(source)
    try:
        text = source.read_text(encoding="utf-8")
        if text.startswith("\ufeff"):
            raise RunConfigError("UTF-8 YAML must not contain a BOM")
        loader = _ClosedLoader(text)
        try:
            node = loader.get_single_node()
            if not isinstance(node, MappingNode):
                raise RunConfigError("YAML root must be one mapping")
            _reject_cycles(node, set())
            payload = cast(Callable[[Node], object], loader.construct_document)(node)
        finally:
            cast(Callable[[], None], loader.dispose)()
        parsed = RunConfig.model_validate(payload)
        config = RunConfig.model_validate(_bind(parsed, source.parent))
    except ValidationError as exc:
        if any(
            isinstance(e.get("ctx", {}).get("error"), RunPreflightError)
            for e in exc.errors()
        ):
            raise RunPreflightError(f"Missing required authority: {exc}") from exc
        raise RunConfigError(f"Invalid run YAML: {exc}") from exc
    except (yaml.YAMLError, UnicodeError, RecursionError) as exc:
        raise RunConfigError(f"Invalid run YAML: {exc}") from exc
    except OSError as exc:
        raise RunPreflightError(f"Cannot read configuration: {source}") from exc
    inputs = tuple(
        p
        for name in type(config).model_fields
        if name != "output"
        for p in _paths(getattr(config, name))
    )
    inodes: dict[tuple[int, int], Path] = {}
    for input_path in (*inputs, source):
        bound = require_input_file(input_path)
        state = bound.stat()
        key = (state.st_dev, state.st_ino)
        if key in inodes and inodes[key] != bound:
            raise RunPreflightError(f"Aliased input paths: {inodes[key]} and {bound}")
        inodes[key] = bound
    from mania.artifact_inventory_io import stream_file_sha256

    for system in config.systems:
        if system.reference is not None and system.reference.sha256 is not None:
            if (
                stream_file_sha256(system.reference.reference_path)
                != system.reference.sha256
            ):
                raise RunPreflightError("Supplied reference file digest mismatch")
    validate_output_root(
        config.output.root,
        inputs=(*inputs, source),
        overwrite=config.output.overwrite,
        protected_roots=protected_product_roots(),
    )
    config._config_path = source
    return config


def read_bound_run_config(path: str | Path) -> RunConfig:
    """Read a bound effective config without fresh-run output admission."""
    source = require_input_file(Path(path).absolute())
    try:
        text = source.read_text(encoding="utf-8")
        if text.startswith("\ufeff"):
            raise RunConfigError("Bound YAML must not contain a BOM")
        loader = _ClosedLoader(text)
        try:
            node = loader.get_single_node()
            if not isinstance(node, MappingNode):
                raise RunConfigError("Bound config root must be a mapping")
            _reject_cycles(node, set())
            payload = cast(Callable[[Node], object], loader.construct_document)(node)
            parsed = RunConfig.model_validate(payload)
            config = RunConfig.model_validate(_bind(parsed, source.parent))
            config._config_path = source
            return config
        finally:
            cast(Callable[[], None], loader.dispose)()
    except (yaml.YAMLError, ValidationError, UnicodeError, RecursionError) as exc:
        raise RunConfigError(f"Invalid bound run YAML: {exc}") from exc
