"""Unified execution and explicit technical artifact diagnostics."""

import argparse
import json
import sys
from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mania.scientific_qualification import ScientificQualificationV1

from mania._version import __version__


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mania",
        description=(
            "MANIA scientific workflows with explicit configuration and "
            "source authority."
        ),
    )
    parser.add_argument("--version", action="version", version=f"mania {__version__}")
    commands = parser.add_subparsers(dest="command")
    run_parser = commands.add_parser(
        "run", help="Execute a configured scientific workflow"
    )
    run_parser.add_argument("--config", required=True)
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and print a bounded read-only plan",
    )
    run_parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Dry-run presentation; json preserves the complete run plan",
    )
    artifacts = commands.add_parser(
        "artifacts", help="Technical artifact integrity diagnostics"
    )
    diagnostics = artifacts.add_subparsers(dest="diagnostic", required=True)
    validation = diagnostics.add_parser(
        "validate", help="Validate an explicit existing MANIA result directory"
    )
    validation.add_argument("--root", required=True)
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "run" and args.format == "json" and not args.dry_run:
        parser.error("--format json requires --dry-run")
    from mania.cli_presentation import ProgressRenderer, format_plan
    from mania.result_readers import ArtifactValidationError, validate_run_artifacts
    from mania.run_config import (
        RunConfigError,
        RunPreflightError,
        _path,
        load_run_config,
    )
    from mania.workflow import RunExecutionError, build_run_plan, run

    presenter = None
    try:
        if args.command == "artifacts":
            try:
                target = _path(args.root)
            except ValueError as exc:
                raise RunConfigError(str(exc)) from exc
            result = validate_run_artifacts(target)
            if result.summary.mode == "exploratory":
                _warn_exploratory(
                    result.plan.effective_parameters,
                    result.summary.scientific_qualification,
                )
            print(
                f"Technical integrity validated: {result.artifact_count} artifacts; "
                f"run status {result.summary.status}"
            )
            return 0
        config = load_run_config(args.config)
        if args.dry_run:
            plan = build_run_plan(config)
            if args.format == "json":
                if config.mode == "exploratory":
                    _warn_exploratory(config)
                print(
                    json.dumps(
                        plan.to_dict(), ensure_ascii=False, indent=2, allow_nan=False
                    )
                )
            else:
                print(format_plan(plan))
            return 0
        if config.mode == "exploratory":
            _warn_exploratory(config)
        presenter = ProgressRenderer(sys.stderr)
        executed = run(config, progress=presenter)
        if executed.summary.mode == "exploratory":
            _warn_exploratory(
                config, executed.summary.scientific_qualification, inherited_only=True
            )
        print(presenter.finish(executed))
        return 0
    except RunConfigError as exc:
        print(f"MANIA BLOCKED: {exc}", file=sys.stderr)
        return 2
    except RunPreflightError as exc:
        print(f"MANIA BLOCKED: {exc}", file=sys.stderr)
        return 3
    except ArtifactValidationError as exc:
        print(f"MANIA: {exc}", file=sys.stderr)
        return 4
    except RunExecutionError as exc:
        if presenter is not None:
            print(presenter.finish(exc.result, exit_code=exc.exit_code))
        if exc.result.summary.mode == "exploratory":
            _warn_exploratory(
                exc.result.plan.effective_parameters,
                exc.result.summary.scientific_qualification,
                inherited_only=True,
            )
        print(
            f"MANIA: {exc}; result status {exc.result.summary.status}", file=sys.stderr
        )
        return exc.exit_code
    except KeyboardInterrupt:
        print("MANIA cancelled before result finalization", file=sys.stderr)
        return 130


def _warn_exploratory(
    config: object,
    qualification: "ScientificQualificationV1 | None" = None,
    *,
    inherited_only: bool = False,
) -> None:
    from mania.cli_presentation import warning_line
    from mania.scientific_qualification import warning_records

    warnings = warning_records(config, qualification)
    if inherited_only:
        warnings = warnings[len(warning_records(config)) :]
    for warning in warnings:
        print(warning_line(warning), file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
