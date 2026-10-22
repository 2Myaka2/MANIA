# Outputs, statuses and read-back

Start with `summary.json`, then the plan's `path_identity_map` and artifact roles.
The hierarchy below is a **layout**, not an assertion that every method ran or
every directory exists. Generic tutorial roots are independent user directories.

```text
<output.root>/
├── effective_config.yaml
├── run_plan.json
├── summary.json
├── run.log
├── provenance/
│   ├── run_provenance.json
│   ├── artifact_inventory.json
│   └── runtime_metadata.json
├── systems/s0001/t0001/
│   ├── preprocessing/       # selected scientific outputs
│   ├── analysis/            # selected network/statistical outputs
│   └── qc/                  # conditional
├── comparisons/g0001/       # conditional
├── replicas/g0001/          # conditional
└── profiles/p0001/          # explicitly selected profile output
```

`sNNNN`, `tNNNN` and `gNNNN` are deterministic ordinal tokens assigned from
configuration order. Original scientific identities remain in the plan/summary;
a directory token or repeated condition label does not replace them. Selected
profile outputs currently use `profiles/p0001`, not a generic `profiles/napi2b` rule.

<a id="controller"></a>
## Controller records

| File | Read it for |
| --- | --- |
| `effective_config.yaml` | Bound paths and effective output/configuration settings, including necessary retention; method defaults are also resolved in the plan's method records |
| `run_plan.json` | `mania.run_plan.v1`: input identities, path mapping, method prerequisites/options/statuses, selected profiles, expected roles and unverified conditions |
| `summary.json` | Run ID/mode/status, actual `methods`, actual `artifact_references`, path mapping, selected extensions and provenance locations |
| `run.log` | Controller execution/status record; console progress is a separate presentation |
| `provenance/run_provenance.json` | Requested/effective source bindings, selections, observed sampling, runtime and completion status |
| `provenance/artifact_inventory.json` | Exact owned role/path/byte size and applicable SHA256 bindings; not a scientific certificate |
| `provenance/runtime_metadata.json` | Actual software/dependency/runtime identity; unavailable Git identity is not fabricated |

Expected artifacts in a plan are intentions. Read the actual summary/inventory
to find what was produced. Inventory dependencies avoid a self-hashing cycle;
input hashing follows reproducibility settings while mandatory authority digests
still apply. A valid digest binds bytes, not biological meaning.

<a id="scientific-files"></a>
## Essential scientific files and fields

All filenames below are conditional on the request and actual outcome. `{token}`
is the controller's input token (for the tutorial, `t0001`). Units and missing
definitions belong to each schema; consult [Science](science.md) before combining
populations.

| File / family | Essential content |
| --- | --- |
| `preprocessing/contact_edges.csv` | Legacy aggregate: source/target residue identity, `contact_frame_count`, `total_frame_count`, `contact_frequency`, `minimum_distance`, `mean_minimum_distance`, `distance_unit`, `atom_filter` |
| `preprocessing/protein_contact_edges.csv` | Typed pairs with `edge_type`, `contact_frame_count`, `sampled_frame_count`, `contact_freq`, `mean_dist_A`, `std_dist_A`, `weight` |
| `preprocessing/edge_semantics.json` | Retained interpretation/priority of edge types |
| `preprocessing/residue_table.csv` | Source roster, residue/segment identity and representative CA coordinates; legacy optional supplied columns may be blank |
| `preprocessing/protein_contacts_perframe.csv` | Retained typed positive rows: `frame_index`, `time_ps`, pair identities, `edge_type`, `distance_A`; not a full physical missing/zero completion record |
| `analysis/graph.json` | Static graph nodes/edges, primary `edge_type`, `all_edge_types`, `n_edge_types`, weights and identity |
| `analysis/centrality_{token}.csv` | Node identity, degree, strength, betweenness, closeness, eigenvector, PageRank, k-core |
| `analysis/communities_{token}.csv` | Community ID/size, algorithm, modularity and count; IDs local to that graph |
| `analysis/region_enrichment_{token}.csv` | Supplied-label contingency/enrichment or explicit skipped status |
| `analysis/temporal_rin_{token}.csv` | `window_id`, source `frame_start/end`, sampled/active counts, nodes/edges and window metrics/status |
| `analysis/conformation_pca_{token}.csv` | Source frame/time, pc1..pc3 and explained ratios, component/feature/frame counts, status/notes |
| `analysis/conformation_labels_{token}.csv` | State/cluster, k, silhouette, representative, squared `distance_to_centroid`, basis/status |
| `preprocessing/rg_timeseries.csv` | Source frames/times, Rg in Å and retained failed-frame diagnostics |
| `preprocessing/rmsd_timeseries.csv` | Requested sample/time, `state`, runtime/source/prepared indexes, actual time/delta, `rmsd_A` |
| `preprocessing/rmsd_measurement.json` | `mania.rmsd.v1` reference/selection identities and measurement evidence |
| Physical windows / observations | `temporal_execution.json`, `observations/` completion and typed per-frame evidence, `protein_edges_by_window_source.csv`, lipid/glycan source tables when selected |
| Reference/annotated windows | Source values plus validated reference keys/digests and supplied annotations; no geometry recomputation |
| `comparisons/gNNNN/{comparison,stats}.csv` | Matching-v1 64/62 ordered columns, both source identities, values/deltas, paired counts/statistics and reasons |
| `replicas/gNNNN/` | Layer-specific `*_by_window_replica_aggregation.csv`, compatible window/reference/partner keys and availability-derived statistics |
| `systems/.../qc/qc_decisions.json` | Source-bound QC policy/evidence/findings and actual decisions; no inferred reviewer |

Physical source tables include requested/effective window bounds,
`requested_sample_count`, `resolved_frame_count`, `missing_sample_count`,
`coverage_fraction`, `n_contact_frames`, `occupancy`, `n_contact_episodes`,
`mean_episode_length_ns`, `max_episode_length_ns`; partner tables additionally
carry their partner/linkage and `distance_mean_A`, `distance_min_A` fields.
Distance units are Å; time fields explicitly use ps or ns. Coverage/occupancy and
support fractions are dimensionless. Fingerprints can be completed in memory
without a separate standalone fingerprint file; consult actual artifact roles.

Backend legacy `nodes.csv`/`edges.csv`/`graph.json` exports have distinct validators;
aggregate `contact_edges.csv` is not backend graph `edges.csv`. An export bundle
consumes those files; it does not itself run diagnostics. The diagnostics report
consumes computed diagnostics. Retained Python analysis may also emit
`extended_metrics.json` describing its owned outputs; do not assume that file is
in every unified CLI root.

The retained nodes and backend edges writers have separate validation boundaries.
Graph CSV validation consumes generated `nodes.csv` and corrected `edges.csv`.
The graph JSON writer uses accepted/validated nodes plus corrected edges. Backend
edges preserve all unique types and primary priority. Export bundles consume the
existing nodes/edges/graph files and do not run diagnostics. Diagnostics run the
existing graph validators on generated artifacts; reports consume already
computed diagnostics without rerunning them. Reference-comparison input
validation checks generated/reference artifact readiness without comparing;
the comparison API performs that separate operation. Reference comparison is
disabled by default and requires explicit reference artifact paths. Technical
validation is not scientific approval.

The retained `write_temporal_rin_csv` API names files
`temporal_rin_{condition}.csv`; the unified workflow writes
`analysis/temporal_rin_{token}.csv`. The window builder does not compute
temporal graph metrics; a separate metrics API computes them.

<a id="missing"></a>
## Null, zero, absence and serialization

| Representation | Scientific meaning |
| --- | --- |
| Numeric 0 | A computed zero or a proven negative within the applicable population |
| JSON null / schema-defined blank CSV | Unknown, unavailable or undefined value; inspect status |
| No sparse edge row | No exported positive row; a zero is justified only with complete available observation evidence |
| Missing/failed frame | Not a negative contact; do not add it to resolved occupancy denominators |
| n=1 replica SD null | Sample dispersion undefined; differs from numeric zero SD at n>=2 |

Preserve ordered rows/columns and the family serializer: RMSD `.17g`, static/
analysis floats `.15g`, ordinary legacy contact/Rg own formatting, fixed Dataset
numbers exact `Decimal.from_float` for native floats. There is no universal rounding
policy. Legacy `rmsf_A`, `sasa_A2`, `ss`, lifetime/window-CV columns can be supplied
or blank; their names do not mean those methods ran.

<a id="statuses"></a>
## Method and run statuses

| Method status | Meaning |
| --- | --- |
| `not_requested` | Not selected or explicitly disabled |
| `not_applicable` | Affirmative inapplicability or a valid method-specific degenerate result |
| `missing_optional_input` | Optional preset cannot establish a prerequisite; not a scientific negative |
| `planned`, `running` | Intended/in progress, not completed measurements |
| `completed` | Actual method computation completed under its contract |
| `pending_review` | Required external review unresolved |
| `failed`, `cancelled` | Actual unsuccessful/interrupted outcome |

Each record retains `method_id`, identity, `request_origin`, `reason_code`, message,
prerequisites, effective parameters and artifact roles. Overall `completed_with_skips`
allows explained optional preset skips; explicit required failure cannot become
that status. Overall `pending_review`, `failed` and `cancelled` preserve available
partial outputs. Do not consume an owned partial file as a completed dataset.
Preflight may fail before output ownership exists; automatic resume is unsupported.

<a id="validation"></a>
## Read-back, integrity and explicit replay

```sh
mania artifacts validate --root /path/to/work/results-basic
```

The reader checks bound config/plan/summary/provenance/inventory/runtime identities,
owned files, applicable digests and typed scientific structures. Use installed
Python independently when integrating results:

```python
from mania.result_readers import read_run_summary, validate_run_artifacts

summary = read_run_summary("/path/to/work/results-basic")
validated = validate_run_artifacts("/path/to/work/results-basic")
print(summary.status, validated.artifact_count)
```

An honestly failed root can pass integrity validation: inspect its actual status.
Integrity does not establish QC PASS, scientific PBC suitability or publication
approval. Replay is an explicit method request with completed observation and
execution-plan sources; validation alone does not recompute a trajectory or
perform replay. See [Replay science](science.md#replay).

Retained Python interfaces include `mania.preprocessing`, `mania.analysis`,
`mania.comparison`, `mania.validation`, `mania.export`, `mania.pipeline_steps`
and `mania.adapters.notebook_export`. In particular,
`mania.analysis.orchestration.run_analysis(AnalyzeRequest(...))` reads validated
preprocessing artifacts, not raw trajectories. `compute_condition_contacts`,
`compute_manifest_contacts`, `compute_condition_rg` and `compute_manifest_rg`
preserve their distinct options and result/error records. Legacy config/pipeline
and preprocessing planning APIs retain their own contracts; planning alone does
not execute their computation APIs or validate a reference comparison.

Temporal RIN analysis is separate from the retained legacy preprocessing
controller; the unified YAML workflow is implemented. Reference-package,
supplied-residue-library and input/config/report/graph/comparator validation
remain separate supported Python APIs.

<a id="qualification"></a>
## Exploratory qualification and NaPi2b preview

Strict roots retain `mania.run_summary.v1` and `mania.run_provenance.v0.1`.
Exploratory uses `mania.run_summary.v2` and `mania.run_provenance.v0.2`, each with
the same closed `mania.scientific_qualification.v1` object. It binds source
identities/PBC declarations/upstream receipts, final method scopes and actual
scientific artifact scopes. All outcomes retain
`SCIENTIFIC_VALIDATION_NOT_PERFORMED`, `authoritative_release_eligible=false` and
actual `PBC_UNVERIFIED` lineage when applicable. Read-back cross-checks them;
a detached CSV or resealed checksum cannot promote qualification. Historical
schemas do not gain a backfilled scientific approval claim.

Explicit strict NaPi2b Dataset-v1 output uses its fixed **17 CSV +3 JSON** registry
plus a retained control copy. The controller records its nested inventory as
`profile_inventory` without changing its bytes. Registry completeness is not
publication permission.

Exploratory emits only `profiles/p0001/preview/tables/` (17 validated tables) and
`profiles/p0001/preview/preview_manifest.json` with schema
`mania_napi2b.dataset_exploratory_preview.v1`. A complete comparable projection
retains the same scientific table bytes, with full source/QC prerequisites;
incomplete work produces no completed preview manifest. Official Dataset-v1
readers reject preview. No official `release/dataset_manifest.json`, release
provenance or publication seal is produced. See [Extensions](extensions.md#preview).

<a id="rmsf-sasa"></a>
## RMSF and SASA in this source snapshot artifact families

Files live under `systems/sNNNN/tNNNN/preprocessing/` and exist only for completed
selected methods. Published 0.2.0 artifacts remain readable and unchanged. Legacy
optional column names are preserved and are not repurposed as these measurements.

| File | Content |
| --- | --- |
| `rmsf_atoms.csv` | Ordered source atom keys, `rmsf_A`, `observed_frame_count` |
| `rmsf_samples.csv` | Complete requested roster: requested sample/time, observed/missing state, runtime/source/prepared index, actual time/delta, reason |
| `rmsf_measurement.json` | `mania.rmsf_measurement.v1`: context, options, source rosters/hashes, actual reference and fit coordinates/hash, N, means/M2, precision/proper rotation/equal weighting/N divisor, CSV digests |
| `rmsf_external_coordinates.json`, `rmsf_atom_mapping.json` | Only for external reference: exact retained input documents, no invented correspondence |
| `sasa_atom_frames.csv`, `sasa_residue_frames.csv`, `sasa_total_frames.csv` | Variant and full sample identity; selected target atom/residue identities; `sasa_A2`; atom rows also `accessible_points` |
| `sasa_atom_means.csv`, `sasa_residue_means.csv`, `sasa_total_means.csv` | Variant, target identity when applicable, observed N, `mean_sasa_A2` |
| `sasa_measurement.json` | `mania.sasa_measurement.v1`: context, exact options/rationale, target/environment rosters/hashes, Bondi registry/hash/DOIs, used radii, probe, grid ID/count/hash, precision, strict occlusion, integer counts and CSV digests |

CSV is UTF-8 with LF and fixed ordered headers; null is empty, valid zero is `0`.
Float64 values use 17 significant digits. JSON is closed and versioned. Source
atom keys retain engine, atom index/name, chain, segment, residue/insertion/name,
element and altloc; residues use that full residue key. Means include observed
frames only. No environment surface or residue-averaged RMSF is exported.

Read-back regenerates CSV from the closed measurement, verifies identity, role,
schema, populations, exact sample order, reference and authority hashes, N, counts,
means/sums, options and grid/radius registry. Changing a digest alone does not make
a corrupted family valid. Strict/Exploratory qualification and original/prepared
lineage remain explicit. The rationale is retained in measurement options and
provenance parameters; it is an owner statement, not a validation certificate.
Outputs do not establish PBC suitability, biology or publication readiness.
See [settings](configuration.md#rmsf-sasa) and [formulas](science.md#rmsf-sasa).


<a id="sasa-frame-stride"></a>
## Additive SASA sampling and atomic source bindings

This source snapshot retains `mania.sasa_measurement.v1` with an additive
`sampling` record: full `global_samples`, `selected_global_ordinals`,
`global_requested_count`, `requested_count`, `observed_count`, `processed_count`,
`missing_count`, `invalid_count`, `failed_count` and `unavailable_time_reason`.
Completed measurements have processed=observed>0 and failed_count=0. Failed runs
retain honest run/method status; no fraudulent zero/mean is sealed.

`context.samples[].requested_sample_index` is the contiguous **local SASA** ordinal.
`selected_global_ordinals[local]` maps it to the global request, whose original
source/prepared indices, actual time, state and reason remain unchanged. New
SASA frame CSVs add `global_requested_sample_index` and `actual_time_reason`;
other columns/units and all non-SASA CSVs are unchanged. Means' existing
`observed_frame_count` is N of processed SASA frames, not global M/requested K.

`mania artifacts validate` reconstructs G from the effective global request and
actual source/header metadata using the existing optional MD loader, without
calling a scientific kernel. It verifies selected global/local/source/prepared/time
correspondence, both variant populations, counts, null/zero distinctions and
means even after ordinary hashes are resealed. This source-lineage validation of
new SASA artifacts requires the optional MD runtime and access to declared inputs.
Older first-candidate v1 SASA records without these fields remain readable only
under the constrained original stride1/full-population contract; no evidence is
rewritten or silently relabeled.

New RMSF/SASA authority paths are portable role/content locators of the form
`atomic_sources/<role>/<ordinal>/<sha256>/<basename>`. They are not paths to join
under `/` or YAML's directory. The resolver reconstructs them solely from the exact
typed effective-config source roster and verifies canonical regular files,
source identity and actual digest. Topology, ordered trajectories, binding/
preparation evidence, NAMD element/time controls and explicit RMSF reference/mapping
have separate roles. Original legacy relative authority records use their original
strict resolution rules. No older authority consumer or InputBinding is changed.
These checks establish technical lineage, not PBC/biology/scientific acceptance.


---

[Guide home](README.md) · [Русский](../rus/outputs.md)

New SASA measurements use `mania.sasa.fibonacci3840.v1`, 3,840 points, and grid SHA256 `bd52bac9426729dcd0fff5445562eefe3745ea4cb8be70e04b80124ca31871f0`. The unchanged `mania.sasa_measurement.v1` reader also accepts authentic historical `mania.sasa.fibonacci960.v1` measurements only with 960 points and SHA256 `89662d78956cad341fdeddaddc793c36e5971c733fe9e832e6442a81399132dd`. Each identity/count/hash combination is closed; count bounds and area divisors follow that validated grid. Only historical 960 artifacts may omit the original sampling fields. There is no YAML point-count setting. Historical 960 results and failures retain their original interpretation; denser sampling does not establish independent scientific acceptance.
