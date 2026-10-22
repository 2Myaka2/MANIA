# Configuration reference

The UTF-8 YAML schema is **`mania.run_config.v1`**. A YAML describes a request;
scientific source files establish the authority that individual methods need.
Start from a [copied executable example](quickstart.md#copy), not an imagined
field or a historical configuration API. Defaults below are the current run
interface; legacy Python options have separate contracts.

<a id="top-level"></a>
## Top-level fields

| Field | Required / default | Meaning |
| --- | --- | --- |
| `schema_version` | Required literal `mania.run_config.v1` | Versioned closed schema |
| `project` | Required nonempty string | Scientific project identity |
| `mode` | `basic` | `basic`, `custom`, `full`, `exploratory` |
| `systems` | Required nonempty ordered list | Input entries and scientific identities |
| `output` | Required object with `root` | Owned result location and output settings |
| `methods` | Empty object | Typed method options; mode expansion still applies |
| `extensions` | Empty list | Explicit optional profile selections |
| `comparisons` | Empty list | Explicit matched input groups |
| `replica_groups` | Empty list | Explicit compatible replica groups |
| `reproducibility` | Default object | Input checksums and supplied checksum manifest |

<a id="systems"></a>
## Systems and scientific identities

Each entry requires `id`, `trajectory_id`, `replica_id`, `engine` (`gromacs` or
`namd`), `topology`, a nonempty ordered `trajectories` list and `pbc`.
`condition`, `variant_id`, `disulfide_state` are optional string/null labels.
Execution identity is `(project, id, trajectory_id, replica_id)`; duplicate
composite identities fail. Repeated conditions do not merge inputs or imply
paired populations. Labels cannot be inferred from directory names.

Optional entries are `frames`, `physical_time`, `reference`, `mapping_path`,
`annotations_path`, `partners_path`, `namd_authority`, `input_binding_path`,
`fasta_path` and `method_overrides`. Their absence is allowed only when the chosen
calculation does not need them. A sequence alone supplies no MD observations.

<a id="paths"></a>
## Literal paths and independent workspaces

**Relative input and output paths resolve against the directory containing the
YAML, not process cwd.** Absolute Linux paths are supported. The schema does not
expand `~`, environment variables or globs; `..`, backslashes, drive-colon syntax,
control characters and ambiguous path spellings are rejected. In WSL use absolute Linux
paths rather than Windows drive syntax. Inputs must be existing regular files;
aliases, symlinks and input/output overlap face strict admission checks.

Copying a YAML and `tiny.pdb` into a new user directory makes both its input and
`results-<mode>` output local to that directory. The bundled roots are safe only
in that copied workflow: result creation in MANIA source trees is blocked. An independent research
project may contain `.git`; this alone does not prohibit its `output/` directory. All four roots
are distinct, and overwrite defaults to false. See [Quickstart](quickstart.md).

Additional local read-only directories can be declared through the optional
`MANIA_PROTECTED_ROOTS` environment variable before running MANIA. Use absolute
existing directory paths separated by `os.pathsep` (`:` on Linux). An unset
variable adds no roots; explicit empty entries, relative/traversal paths,
symlink components, missing directories and non-directories fail preflight.
This adds protection without changing YAML or relaxing automatic source/package,
input or owned-overwrite checks. Unrelated archives require an explicit declaration;
their protection is effective only while that variable is set.

<a id="frames"></a>
## Source frames, physical time and windows

| Frame field | Default | Rule |
| --- | --- | --- |
| `start` | 0 | Zero-based, included |
| `stop` | null | Excluded; supplied integer must exceed start |
| `stride` | 1 | Positive integer, anchored at start |
| `max_frames` | null | Explicit positive limit on selected count; no hidden cap |
| `indexes` | null | Nonempty increasing unique nonnegative list; cannot coexist with nondefault interval/stride/cap |

This illustrative **system-entry fragment** selects up to five source frames;
it does not change source identities into compact row numbers:

```yaml
frames:
  start: 0
  stop: 20
  stride: 2
  max_frames: 5
# Alternative, not combined with the nondefault selector above:
# frames: {indexes: [0, 2, 4]}
```

`physical_time` cannot coexist with an explicitly supplied `frames` object,
including `frames: {}`. Supply `production_start_ns >= 0`,
`production_end_ns > start`, and positive `frame_stride_ps`. Values must be real
numeric YAML scalars, with no booleans/nonfinite values. Sampling uses a Decimal
target grid and unique source-time matches; missing targets remain missing.
Windows are optional for physical sampling. For physical-window methods also
supply `variant_id` and the complete `windows` object. Illustrative fragment,
not a request to run the tiny PDB on this time interval:

```yaml
variant_id: supplied-variant
physical_time:
  production_start_ns: 0.0
  production_end_ns: 10.0
  frame_stride_ps: 100.0
  windows:
    length_ns: 2.0
    step_ns: 1.0
    overlap_percent: 50.0
    boundary_profile: mania.window_boundaries.legacy.v1
```

Window `step_ns` must be positive and <= `length_ns`; `overlap_percent` in [0,100)
must agree with `100*(1-step/length)`. Exact profile IDs are
`mania.window_boundaries.legacy.v1` and `mania.window_boundaries.inclusive.v1`.
These physical windows differ from `temporal_rin.window_size/step_size`, whose
units are selected frames. See [Science](science.md#time-windows) for boundaries,
coverage and the existing time-matching tolerances.

<a id="pbc"></a>
## PBC declarations

| `pbc.mode` | Additional fields / meaning |
| --- | --- |
| `nonperiodic` | Meaningful `declaration`; no contradictory periodic evidence; no preparation evidence path |
| `prepared` | `declaration` plus existing `preparation_evidence_path` with source/atom/frame/time bindings and suitability evidence |
| `unverified` | Exploratory only; meaningful `declaration`, no preparation evidence path; read coordinates as supplied |

No mode performs internal MIC/wrap/unwrap/centering. A flag or box size is not
scientific proof of suitability. Nonperiodic declarations with a nonzero cell
remain contradictory, including in Exploratory. Prepared evidence must pass its
own exact reader and lineage checks. Basic/Custom/Full reject unverified mode.

<a id="methods"></a>
## Methods, options and dependencies

Merge order is mode preset → global `methods` → per-entry `method_overrides`.
Only supplied option fields override earlier values. Use `{}` for a method with
only defaults, never YAML `null`. Every method accepts `enabled` (default true).
A disabled prerequisite of an enabled method is a configuration error.

| Method ID | Other supported options / defaults | Main prerequisites |
| --- | --- | --- |
| `contacts` | `selection: protein` or `all`; `atom_filter: heavy`; `cutoff_distance: 4.5`; `distance_unit: angstrom`; `skip_resnames: []`; `min_frequency: 0.0` | Readable selected atom/residue coordinates |
| `static_rin` | None | `contacts` with protein selection |
| `communities` | None | `static_rin` |
| `region_enrichment` | Explicit enabled object requires `annotations_path` | Communities, supplied annotations/reference/mapping |
| `typed_interactions` | None | Contacts; publishes typed observations |
| `rg` | Explicit enabled request requires `selection`; `include_failed_frames: true` | Qualified group, masses, inputs and coordinate suitability |
| `rmsd` | Required `fit_selection`, `evaluation_selection`, `reference` | Correct atom correspondence, valid fit/evaluation geometry |
| `temporal_rin` | `window_size: 10`, `step_size: 10`, `min_frequency: 0.25` | Contacts/per-frame observations; windows measured in frames |
| `fingerprints` | None | Contacts and accepted feature/frame roster |
| `pca` | `max_components: 10` | Fingerprints |
| `clustering` | `basis: fingerprint` or `pca`; `max_k: 10`; `max_iterations: 100`; optional positive `pca_components` only for pca | Fingerprints; PCA dependency when basis is pca |
| `physical_windows` | None | Contacts, physical windows, `variant_id` |
| `lipid_contacts`, `glycan_contacts` | None | Physical windows and `partners_path`; fixed 6.0/4.5 Å cutoffs |
| `replay` | Required `completion_path`, `execution_plan_path` | Completed bound per-frame evidence; no coordinate reopening |
| `comparison` | None | Explicit `comparisons` and matching authority |
| `replica_aggregation` | None | Explicit `replica_groups` and availability/correspondence |
| `qc` | Required `evidence_manifest_path`; generic `policy_path`; optional `review_decisions_path` | Source-bound evidence and compatible policy/cohort |
| `profile_outputs` | None | Explicit dataset profile and complete extension source envelope |

Contacts frequency thresholds must be in [0,1]; distances are finite positive Å.
Temporal sizes, PCA count and iteration count are positive integers; `max_k >= 2`.
Do not expose fixed chemistry constants as new YAML options. Method IDs above are
the initial public 0.2.0 set. This source snapshot also includes
[RMSF and SASA](#rmsf-sasa). Secondary structure, `n_jobs`, `resume` and
PBC-preprocessing flags are unsupported. [Modes](modes.md) explains defaults.

<a id="rg-rmsd"></a>
## Rg and RMSD requests

Omit `rg` entirely for conditional automatic protein Rg in Basic/Full. It requires
complete unambiguous protein selection, valid masses/data and coordinate
suitability. `rg: {}` is an explicit incomplete request and fails. Use
`rg: {enabled: false}` to disable it. An explicit request uses an actual nonempty
MDAnalysis selection, such as `selection: protein`, and still needs eligibility.
Exploratory disables automatic Rg and never upgrades unverified PBC qualification.

RMSD is not selected without the complete explicit triplet. The following
**methods fragment** is executable with the bundled four-atom geometry when used
inside its valid Custom YAML; selection indexes refer to atoms, not residues:

```yaml
methods:
  rg: {enabled: false}
  rmsd:
    fit_selection: index 0 1 2
    evaluation_selection: index 3
    reference: {kind: first_selected}
# External alternative for reference only:
# reference:
#   kind: external
#   path: sources/reference_coordinates.json
#   atom_mapping_path: sources/atom_mapping.json
```

`first_selected` accepts **only `kind`**, including during effective-config
read-back. Even extra null `path` or `atom_mapping_path` is rejected. External
reference requires both paths, `mania.rmsd_external_coordinates.v1` and
`mania.rmsd_atom_mapping.v1`: finite Å coordinates, exact topology/reference
SHA/size and ordered one-to-one fit/evaluation atom identities. No automatic
name-based matching or reference choice occurs. Fit needs >=3 noncollinear
finite atoms (rank >=2); evaluation needs >=1, with no independent rank rule.

<a id="authorities"></a>
## Additional scientific authorities

| Configuration field | Authority and limitations |
| --- | --- |
| `reference: {reference_path: ..., sha256: ...}` | `mania.reference.v1`; optional file SHA; full ordered roster digest is separately validated |
| `mapping_path` / `annotations_path` | `mania.residue_mapping.v1` / `mania.annotations.v1`; explicit chemistry, namespaces, completeness |
| `partners_path` | Supplied molecular-partner topology/metadata, components and glycan linkage; no universal residue-name guess |
| `namd_authority: {elements_path: ..., time_path: ...}` | `mania.namd_atom_type_elements.v1`, `mania.namd_time_authority.v1`; required for NAMD coordinate reads, exactly one bound DCD |
| `input_binding_path` / `fasta_path` | Source-bound identities/frame/preparation evidence / optional sequence evidence, not automatic scientific authority |
| `comparisons[]` | `id`, >=2 ordered `members`, `matching_path`, optional `annotations_path`; each member has `system_id`, `trajectory_id`, `replica_id` |
| `replica_groups[]` | `id`, >=1 ordered `members`, `reference_id`, `layer: protein\|lipid\|glycan`, `availability_path`, optional `correspondence_path`, `qc_decisions_path`; specialized layers require correspondence |
| `extensions[]` | Explicit `id: napi2b`, `version: '==0.2.0'`, profile and optional source paths; see [Extensions](extensions.md) |

Comparison matching uses `mania.static_rin_matching.v1`; equality of numeric
residue numbers is not correspondence. Replica availability and compatible
reference/layer/window identities are supplied, not inferred from sparse files.

Generic QC's `mania.qc_source_bindings.v1` envelope contains exactly
`schema_version`, `kind`, `policy_evidence`, `group_evidence`, `members`.
Ordered members contain `identity`, `qc_evidence`, `window_input`,
`metric_selections`. Window input binds `temporal_evidence`,
`observation_directory`, `observation_evidence`, `mapping_evidence`,
`reference_evidence`. Each metric selection supplies `check_id`, `source`,
`source_row_key`, `numeric_field`, `unit`. `FileEvidence` binds exact
`role`, `path`, `size_bytes`, `sha256` relative to its declared authority root.
Use the supported constructors/readers; do not fabricate these documents.
A selected profile may supply its policy, but cannot invent sources or decisions.

<a id="output"></a>
## Output and reproducibility settings

| Object | Fields / defaults |
| --- | --- |
| `output` | Required `root`; `overwrite: false`; `log_level: INFO` (DEBUG/INFO/WARNING/ERROR); `retain_perframe: false` |
| `reproducibility` | `checksum_mode: none` or `sha256`; optional `input_checksum_manifest_path` |

Required evidence-dependent methods force retention when necessary and show it
in the effective plan. `checksum_mode: none` does not disable mandatory authority
or reference digests. Dry-run does not perform full trajectory hashing. Existing
roots need explicit overwrite plus ownership validation; unrelated files are not
an overwrite authorization.

<a id="validation"></a>
## Strict validation and typical mistakes

Reject unknown/duplicate keys at every level, non-string IDs, scalar coercion,
booleans as numbers, nonfinite numbers, cyclic aliases, YAML merge keys, a BOM,
contradictory selectors and incomplete scientific objects. Use quoted strings for
numeric-looking identities and real boolean `false` for disabled options.
A missing file is a preflight failure; an unestablished scientific fact is not a
zero. Confirm the plan with [dry-run](commands.md#dry-run) before execution.

<a id="rmsf-sasa"></a>
## RMSF and SASA in this source snapshot requests

These additions retain the single `mania.run_config.v1` schema. The following
**methods fragment** is merged into a complete configuration in an independent
workspace with explicit source identities, valid inputs and a distinct
`output.root`. Build and install this public source snapshot using the
[Quickstart](quickstart.md); record its Git commit because package metadata
remains 0.2.0. Inspect with `mania run --config run.yaml --dry-run`,
execute with `mania run --config run.yaml`, then use
`mania artifacts validate --root <output.root>`.

### RMSF: Calculation settings and modes

| Field | Default / rule |
| --- | --- |
| `enabled` | `true`; `false` disables the method |
| `atom_selection` | `protein and name CA`; source atoms, never residue averages |
| `fit_selection` | `protein and name CA`; at least three unique atoms, centered rank ≥2 |
| `reference` | `{kind: first_selected}`; the actual first requested frame, never silently replaced |
| External reference | `kind: external`, existing `path` and `atom_mapping_path`; retained RMSD coordinate/mapping contracts, exact source-bound ordered fit/evaluation correspondence |

At least two observed frames are required. The default requires exactly one
source-proven C-alpha per protein residue. Explicit qualified heavy-atom or
backbone selections produce one value per selected atom. Fit and evaluation
selections are independent. No mass weighting or residue averaging is performed.

### SASA: Calculation settings and modes

| Field | Default / rule |
| --- | --- |
| `enabled` | `true`; `false` disables the method |
| `target_selection` | `protein`; automatic protein selection must be unambiguous |
| `variants` | `[isolated]`; unique ordered subset of `isolated`, `with_environment` |
| `environment_selection` | Explicit nonempty disjoint group for `with_environment`; no inferred water, ion or biological membership |
| `environment_rationale` | Nonempty, non-whitespace text for every explicit `with_environment` request; optional for isolated. When ions are selected, the owner must explicitly explain their inclusion |
| `probe_radius_A` | 1.4 Å; any finite real in inclusive [0.5,3.0], including nonstandard values; bool rejected |
| `include_hydrogens` | `false`; H excluded from target and environment. `true` requires explicit source element H |
| Grid | Fixed 3840 float64 Fibonacci points, fixed orientation/order; no YAML point-count option |

```yaml
methods:
  rmsf:
    atom_selection: protein and name CA
    fit_selection: protein and name CA
    reference: {kind: first_selected}
  sasa:
    target_selection: protein
    variants: [isolated]
    frame_stride: 2
    probe_radius_A: 1.4
    include_hydrogens: false
```

For an explicitly justified environment, replace the SASA options with this
**methods fragment**. The statement is retained verbatim in measurement metadata
and provenance. Its presence does not validate biology, ion membership or PBC.

```yaml
methods:
  sasa:
    target_selection: protein
    variants: [isolated, with_environment]
    frame_stride: 10
    environment_selection: segid ENV
    environment_rationale: "Synthetic ENV occluders, including explicitly selected sodium ions, are included only to test shielding."
```

The same fields work in system `method_overrides`; explicit system values override
global fields while retaining other options. Basic has no new automatic methods.
Custom and Exploratory accept explicit requests. Full automatically adds eligible
RMSF and isolated SASA; explicit requests merge with these presets and remain
explicit. Full never invents an environment. Missing optional prerequisites may
skip a preset before calculation starts, with a reason and no fabricated CSV.
Invalid explicit requests and any numerical/I/O failure after calculation starts
fail the run. Strict Basic/Custom/Full retain nonperiodic/prepared source guards;
Exploratory may retain raw unverified coordinates with `PBC_UNVERIFIED`,
`SCIENTIFIC_VALIDATION_NOT_PERFORMED` and `authoritative_release_eligible=false`.
No method unwraps, centers, images or reconstructs molecules. Preparation evidence
alone does not establish physical co-locality or scientific suitability.

See [definitions](science.md#rmsf-sasa), [output populations](outputs.md#rmsf-sasa)
and [mode expansion](modes.md#full). Technical read-back is not scientific validation.


<a id="sasa-frame-stride"></a>
## SASA frame_stride and compatible source paths — source snapshot

`methods.sasa.frame_stride` defaults to **1** and accepts strictly positive integers
such as **1, 2, 10**. The same field in
`systems[].method_overrides.sasa.frame_stride` takes precedence over the global
value using the retained merge rules. Zero, negatives, strings, floats (including
10.0), bool and null fail. There is no silent cap or rounding and no new YAML
schema: only `mania.run_config.v1`. This source snapshot supports this setting; the initial public 0.2.0 snapshot did not.

First MANIA constructs its existing ordered **global requested sequence G** using
`frames` or source-bound physical-time controls. SASA then selects **positions**
0,s,2s,... from G, before missing/invalid filtering. With global source indices
500,502,...,598 (50 slots), stride2 selects 25 positions; stride10 selects global
positions 0,10,20,30,40 and source indices **500,520,540,560,580**. It never resets
those sources to 0,10,... or reinterprets `frames.stride`. A stride larger than
the global population selects its first requested slot. One observed SASA frame
is valid; zero selected observations fail an explicit request or honestly skip
an unavailable Full preset before numerical start. Invalid selected geometry
fails under the existing before/after-start policy; no later replacement is used.

Both variants share the exact selected roster. Missing selected slots remain null
with a reason; unselected missing slots contribute no SASA row. Unknown actual
time stays null with `source_time_unavailable`, never an interpolated clock.
Means use observed/processed SASA frames only: M=50 global, K=5 requested SASA,
one selected missing gives N=4, so divide by **4**, never 5 or 50. Real measured
zero remains zero. This is a sparse selected-population mean, not complete global
time coverage. RMSF, contacts, RIN and all other methods keep their original
sampling, reference and observations.

Full uses stride1 for automatic isolated SASA unless overridden; Custom and
Exploratory apply it only to an explicit SASA request. Basic has no automatic SASA.
An explicit with_environment still needs the approved qualified disjoint selection
and nonblank rationale, including explanation of selected ions. All source-element,
probe/radius/grid, hydrogen and strict/Exploratory PBC rules are unchanged.
Resolved defaults/options appear in plan/status/provenance and the effective
config; implicit Full presets are recorded in per-system effective-config comments
without pretending they were explicit requests.

B-01 is corrected in this source snapshot: genuine absolute topology and
trajectory paths may be outside the YAML folder. Genuine NAMD element/time JSON
may also be outside a prepared input binding's root. Each declared source is
independently bound to its exact role, identity and SHA256; no shared `/` root,
symlink, traversal, automatic relocation or guessed source is permitted. Prepared
InputBinding evidence retains its original strict root/ordering/hash rules.
See [output lineage and validation](outputs.md#sasa-frame-stride).


---

[Guide home](README.md) · [Русский](../rus/configuration.md)
