# Commands, plans and progress

Use an installed environment. [Quickstart](quickstart.md) shows the Bash/Linux
copying procedure. Paths below are placeholders for an independent workspace.

```sh
mania --help
mania --version
mania run --config /path/to/work/basic.yaml --dry-run
mania run --config /path/to/work/basic.yaml --dry-run --format json
mania run --config /path/to/work/basic.yaml
mania artifacts validate --root /path/to/work/results-basic
```

Every form also works as `python -I -B -m mania ...` using the actual installed
interpreter. `mania run --help` and `mania artifacts validate --help` show their
supported arguments. The public CLI has no expert aliases or WANIA commands.

<a id="dry-run"></a>
## Dry-run is a plan

| Option | Actual behavior |
| --- | --- |
| `--config PATH` | Required strict YAML; inputs and outputs bind to its directory |
| `--dry-run` | Read-only bounded checks and human-readable text by default |
| `--dry-run --format text` | Explicit human text, same default presentation |
| `--dry-run --format json` | Full `mania.run_plan.v1` JSON on stdout |
| `artifacts validate --root PATH` | Validate an explicit existing result root |

`--format json` requires `--dry-run`; using it for execution exits **2** before
calculation. It is not a scientific-output-format setting. There is no CLI method
selector, frame selector, overwrite switch or automatic resume; those supported
settings belong in YAML. JSON plans can be redirected to an independent file
outside the MANIA source checkout. Exploratory JSON warnings go to stderr, preserving JSON stdout.

The human plan shows files, zero-based requested frame bounds, effective methods
and dependencies, selected profiles, output root and overwrite behavior.
`READY` / `READY WITH WARNINGS` means preliminary configuration/planning checks
passed. `BLOCKED` explains a schema or preflight problem. Bounds are requests,
not observed availability: `stop` is exclusive and `stride` starts at `start`.
Unbounded/physical-time frame totals remain unknown until observed.

Dry-run may read bounded header/topology metadata and selected authority files.
It does not decode the full trajectory, calculate contacts/Rg/RMSD/QC, hash huge
trajectories, create results, transform coordinates or verify scientific PBC
suitability. A missing topology is exit 3, not a successful plan.

<a id="progress"></a>
## Execution and final summary

During execution, stderr shows actual loading/checking, completed methods,
artifact writing and finalization stages. Percentages count completed recorded
work stages, **not elapsed-time prediction, resource estimates or scientific
approval**. Contact subprogress advances only for real `frame_done` events;
unknown totals show counts without a frame percentage. Separate input identities
retain separate counters even when condition labels repeat.

A terminal updates progress in place; redirected streams use sparse plain lines
without ANSI colors. The final stdout summary reports elapsed wall time, actual
method states, observed source frames when available, artifact count and output
root. Successful finalization may reach 100%; failed, cancelled or pending-review
outcomes retain partial evidence and do not receive a successful 100% marker.
Progress is a console view; scientific CSV/JSON and provenance remain authoritative
for recorded results. Inspect [Outputs](outputs.md) after every run.

<a id="exit-codes"></a>
## Exit codes and warnings

| Exit | Meaning |
| --- | --- |
| 0 | Help/version; requested work completed with permissible explained preset skips; or technical artifact validation completed |
| 2 | CLI usage, YAML/schema/type error, contradictory configuration |
| 3 | Missing input, optional MD runtime, selected extension, required authority or preflight incompatibility |
| 4 | Execution or artifact-validation failure; unresolved required scientific gate |
| 5 | Requested QC awaits external REVIEW resolution |
| 130 | Cancellation |

Overall run states include `completed`, `completed_with_skips`, `pending_review`,
`failed` and `cancelled`. Each method has its own status and reason; see
[the status reference](outputs.md#statuses). An explicitly requested failed method
cannot become an optional successful skip.

`SCIENTIFIC_VALIDATION_NOT_PERFORMED` and `authoritative_release_eligible=false`
persist for all Exploratory outcomes; `PBC_UNVERIFIED` identifies genuinely
unverified PBC and inherited source lineage when applicable. A strict run cannot
consume Exploratory upstreams as scientifically authoritative evidence.

> **Scientific warning.** `artifacts validate` checks integrity and reports the
> stored run status. An honestly failed root may pass integrity and return 0.
> Read the status and scientific qualification; exit 0 is not biological approval,
> PBC suitability, real-input scientific qualification or a publication decision.

Failure/cancellation preserves owned partial outputs and available error records.
A preflight failure may occur before a result root exists. Output reuse defaults
to rejection; explicit YAML overwrite still requires ownership and safety checks.

---

[Guide home](README.md) · [Русский](../rus/commands.md)
