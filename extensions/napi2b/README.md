# MANIA NaPi2b scientific profile

**[Русское руководство](../../docs/rus/extensions.md) ·
[English guide](../../docs/eng/extensions.md)**

`mania-napi2b==0.2.0` is an optional regular wheel requiring exactly
`mania-wania==0.2.0`. Core is independent. Installation alone leaves Core
scientific results and defaults unchanged; explicitly select `napi2b.legacy.v1`
or `napi2b.dataset.v1` when the corresponding scientific authority is available.
Full mode does not activate the extension. Selection creates fresh scoped
callables; shared generic algorithms remain in Core.

The immutable resources preserve O95436-1 sequence version 3 (690 residues), ECD
234–361 and MX35 311–341 inclusive, plus fixed contact-definition authority.
The sequence hash differs from the generic reference-roster digest. Actual
system mapping, annotations, study catalogs and reviewer decisions are external.
Legacy mapped-Cα RMSD retains its explicit mapping, reference, prepared
representation and source identities. Complete fixed annotations and incomplete
generic annotations keep their separate false/unknown rules.

[profile.yaml](examples/profile.yaml) is an authority-dependent template, not a
self-contained Dataset release example. Replace SUPPLIED identities only from
complete scientific sources and supply every referenced authority file. It
selects `profile_outputs`, `qc_manifest_path` using
`mania_napi2b.dataset_sources_bindings.v1`, and `release_input_manifest_path` using
the retained publication-input contract. The bilingual guides document exact
binding fields and ordered arrays. No mapping, cohort, MET-0200 value, reviewer
decision or scientific definition is guessed.

A strict complete projection preserves the fixed Dataset-v1 **17 CSV +3 JSON**
registry and a separate retained input-control copy. Source validation and exact
reconstruction precede writing. The nested inventory is exposed as role
`profile_inventory` without changing its bytes. Hard FAIL cannot be overridden;
REVIEW needs actual authorized external resolution. Technical completeness is
not permission to publish or evidence of real scientific acceptance.

With `mode: exploratory`, the explicitly selected dataset profile creates only
17 preview tables and a separate `mania_napi2b.dataset_exploratory_preview.v1`
manifest. Full scientific source/QC requirements remain. There is no official
Dataset-v1 release manifest/provenance/seal; official readers reject preview.
`SCIENTIFIC_VALIDATION_NOT_PERFORMED`, `authoritative_release_eligible=false`
and applicable `PBC_UNVERIFIED` remain visible and prevent scientifically qualified
authoritative FAIR release use.

The constructed profile documentation test binds the template to
complete coordinate-free sources, validates all 17+3 registry outputs and rejects
a corrupted authority SHA. It does not approve a real dataset. Real-input
scientific qualification remains incomplete. FAIR and WANIA remain separate projects;
no production catalog, WANIA payload, automatic download or mutable global
registration is installed. Python >=3.11 metadata and the approved numerical
environments are described in [English](../../docs/eng/reproducibility.md) and
[Russian](../../docs/rus/reproducibility.md).
