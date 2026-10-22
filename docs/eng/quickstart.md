# Quickstart: synthetic tutorial and your own trajectory

**MANIA 0.2.0.** These Bash/Linux instructions
use separate source, environment and researcher directories. Technical checks
cover specific Python 3.11/3.12 numerical environments; they do not promise
unrestricted operating-system support or scientific qualification of real inputs.

<a id="install"></a>
## A1. Obtain source and install an isolated environment

In a writable parent directory, obtain the source and create a virtual environment
outside the checkout. You need Python 3.12 and network access for ordinary pip
dependency resolution. You may use `python3.11` instead when Python 3.11 is
installed in your environment. If you already have the full source checkout,
start with `cd MANIA`.

```bash
git clone https://github.com/2Myaka2/MANIA.git
cd MANIA
python3.12 -m venv ../mania-venv
source ../mania-venv/bin/activate
python -m pip install ".[md]"
mania --version
```

This installs the distribution `mania-wania==0.2.0` with the supported `md` extra;
the command and Python import are `mania`. It is a regular source install.
Base needs NumPy >=2,<3, Pydantic >=2.7,<3 and PyYAML >=6,<7; coordinate reading also needs MDAnalysis==2.10.0.
`science` is a compatibility extra for the same reader. NaPi2b is optional and
separately installed and selected. For controlled numerical reproduction, see
[Reproducibility](reproducibility.md#environment). `python -I -B -m mania`
is the isolated installed equivalent of the `mania` console command.

<a id="copy"></a>
## A2. Copy and run the first synthetic tutorial

Keep the environment active and move to the checkout's parent directory below.
The source
resources are the four YAML files in [examples/](../../examples/basic.yaml) and
[unchanged tiny.pdb](../../examples/tiny.pdb). Source distributions contain the
generic examples; installed wheels do not expose a tutorial-resource API. The
optional `MANIA_Examples.zip` contains exactly these five files under `examples/`;
you do not need it when using the full checkout.

```bash
cd ..
mkdir tutorial_01
cp MANIA/examples/{basic,custom,full,exploratory}.yaml MANIA/examples/tiny.pdb tutorial_01/
cd tutorial_01
mania --version
mania run --config basic.yaml --dry-run
mania run --config basic.yaml
mania artifacts validate --root results-basic
```

Expected version: `0.2.0`. The PDB has **two models, four atoms and two ALA
residues**, constructed for a software tutorial. `engine: gromacs` exercises the
generic loader with PDB; this is not a real TPR/XTC trajectory or PBC evidence.
No test helper or input generator is needed.

**Relative paths resolve against the YAML directory**, independently of process
cwd. `tiny.pdb` is therefore the copied input and `results-basic/` appears beside
`basic.yaml`. Outputs cannot overlap inputs, MANIA source trees or protected
package code. Your separate research project may itself contain `.git`; that
fact alone does not forbid its ordinary output directory.

<a id="run"></a>
## A3. Run the other examples without overwriting

Dry-run creates no results. It checks configuration and bounded prerequisites,
not every trajectory frame or scientific PBC suitability. An absent MD reader
blocks coordinate execution. Check actual exit codes and warnings before using
results. Full JSON planning is available with `--dry-run --format json`.

After Basic, run each remaining copied example:

```bash
mania run --config custom.yaml --dry-run
mania run --config custom.yaml
mania artifacts validate --root results-custom
mania run --config full.yaml --dry-run
mania run --config full.yaml
mania artifacts validate --root results-full
mania run --config exploratory.yaml --dry-run
mania run --config exploratory.yaml
mania artifacts validate --root results-exploratory
```

Each mode has its own root: `results-basic`, `results-custom`, `results-full`,
`results-exploratory`. All examples retain `overwrite: false`. A repeated run
against a nonempty root is rejected; it does not silently replace results.
Repeat in a fresh directory such as `tutorial_02`. There is no automatic resume.
Explicit overwrite still requires an exactly owned result inventory and valid
provenance/read-back; unrelated files are never an overwrite authorization.

<a id="inspect"></a>
## A4. Read the outcome

From `tutorial_01/`, inspect the recorded summary and provenance:

```bash
python -m json.tool results-basic/summary.json
python -m json.tool results-basic/provenance/run_provenance.json
```

Read `results-basic/summary.json` for actual method statuses, then
`provenance/run_provenance.json` and `provenance/artifact_inventory.json` within
that root. Scientific files are under `systems/s0001/t0001/{preprocessing,analysis}`;
see [Outputs](outputs.md). Basic computes contacts/static RIN and disables Rg
in this partial constructed protein. Custom adds separate fit/evaluation RMSD.
Full can report explained optional skips; its retained contact population is
insufficient for PCA/clustering. A valid artifact hash is not scientific approval.

Exploratory defaults to contacts/static RIN without automatic Rg. The example
preserves `SCIENTIFIC_VALIDATION_NOT_PERFORMED`,
`authoritative_release_eligible=false` and `PBC_UNVERIFIED`. Validation does not
remove those limitations.

<a id="real-inputs"></a>
## B. Analyze your own trajectory, including Exploratory

`analysis_project` is an illustrative directory name, not a mandatory location.
Create an independent researcher directory, which may also be a Git repository,
and supply your actual compatible topology and ordered trajectory:

```text
analysis_project/
├── exploratory.yaml
├── input/
│   ├── topol.tpr
│   └── trajectory.xtc
└── output/
```

Save the following complete schema-valid configuration as `exploratory.yaml`.
It describes an unverified Exploratory request; it does not establish that your
files are readable or scientifically suitable. Replace the scientific identities
with your own explicit records, rather than inferring them from folder names.

```yaml
schema_version: mania.run_config.v1
project: my-study
mode: exploratory
systems:
- id: system-01
  trajectory_id: trajectory-01
  replica_id: replica-01
  engine: gromacs
  topology: input/topol.tpr
  trajectories:
  - input/trajectory.xtc
  pbc:
    mode: unverified
    declaration: Coordinates supplied without verified PBC preparation; exploratory analysis only
output:
  root: output/exploratory_01
  overwrite: false
```

`systems[].topology` names the topology; `systems[].trajectories` is an ordered
nonempty list. `id`, `trajectory_id` and `replica_id`, together with `project`,
identify the scientific input. There is **no top-level `input:` field**.
Both `input/...` paths and `output/exploratory_01` resolve relative to this YAML.
`output.root` selects a fresh result root; `output.overwrite` prevents implicit
replacement. Optional global `methods` and per-system `method_overrides` change
only explicitly supplied options; omitted methods keep the mode's defaults.
For example, an explicit RMSD request requires fit/evaluation selections and a
reference; it cannot be added by guessing missing authority.

Run from the directory containing `analysis_project/`, with the environment active:

```bash
cd analysis_project
mania run --config exploratory.yaml --dry-run
mania run --config exploratory.yaml
mania artifacts validate --root output/exploratory_01
```

Use `pbc.mode: unverified` only when coordinate suitability is unverified and
state that honestly in `declaration`. Strict Basic/Custom/Full require nonperiodic
or externally prepared coordinates and their necessary evidence. Exploratory
**does not correct periodic coordinates**, does not validate an unverified PBC
protocol, and cannot make results scientifically authoritative for FAIR.
Cartesian distances across periodic boundaries may be physically unsuitable.

Supply additional scientific authority when required: preparation/source bindings,
explicit frame/time controls, RMSD reference/mapping/selections, molecular-partner
metadata, biological annotations, comparison matching, replica availability or
QC/reviewer records. NAMD PSF/DCD requires explicit element/time authority and
one bound DCD. Do not fabricate these inputs. See [Configuration](configuration.md)
and [Science](science.md). Real-input scientific qualification remains incomplete.
This public source snapshot computes RMSF and SASA; see
[settings and usage](configuration.md#rmsf-sasa) and
[scientific definitions](science.md#rmsf-sasa). Package metadata remains 0.2.0;
record the public Git commit. Scientific qualification is required for each
intended real input and use. Secondary-structure computation
and internal PBC preparation remain unsupported. Technical completion and artifact validation do not establish
physical suitability, biological correctness or publication readiness.

---

[Guide home](README.md) · [Русский](../rus/quickstart.md)
