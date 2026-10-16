# Дополнительный NaPi2b и внешние потребители

<a id="architecture"></a>
## Независимые обязанности

```mermaid
flowchart LR
  N[Необязательный явно выбранный NaPi2b] --> C[Независимый MANIA Core]
  F[Отдельный научный проект FAIR] -->|Использует вычисления| C
  C --> A[Общие научные артефакты]
  A --> F
  A --> W[Внешняя визуализация WANIA]
  W -->|Может вызывать публичный CLI или API| C
```

Core владеет общей наукой, механизмами QC/evidence, provenance и валидацией.
NaPi2b — фиксированными белковыми фактами и проекцией совместимости. FAIR —
настоящими входами исследования, каталогами, группировками, решениями экспертов
и политикой выпуска. WANIA — внешняя визуализация. Core не требует этих проектов
для общих научных результатов; специальной MANIA-команды WANIA payload,
demo-контракта и пространства `mania.wania` нет. Сохранённый notebook CSV/JSON
converter поддерживается независимо и не исполняет `.ipynb`.

<a id="activation"></a>
## Отдельная установка, явный выбор

Дополнительный пакет `mania-napi2b==0.2.0` требует ровно
`mania-wania==0.2.0`. После установки Core по [Быстрому старту](quickstart.md#install)
оставьте окружение активным и выполните команду из корня полного checkout MANIA:

```sh
python -m pip install ./extensions/napi2b
```

Сама установка **не** активирует профиль. Full также его не активирует.
Неактивные entry-point metadata не меняют defaults Core, общие численные
зависимости или научные выходы. Выбор создаёт свежие scoped callables без mutable
глобальной регистрации. Профили: `napi2b.legacy.v1`, `napi2b.dataset.v1`;
первый можно явно выбрать через Python:

```python
from mania.extensions import load_selected_extension

profile = load_selected_extension("napi2b", "==0.2.0", "napi2b.legacy.v1")
reference = profile.reference_factories["uniprotkb:O95436-1:sequence-v3"]()
```

Явный Dataset output использует следующий **фрагмент YAML** внутри полной
корректной конфигурации и со всеми переданными файлами источников:

```yaml
extensions:
- id: napi2b
  version: '==0.2.0'
  profile: napi2b.dataset.v1
  options:
    qc_manifest_path: sources/dataset_bindings.json
    release_input_manifest_path: sources/publication_inputs.json
methods:
  profile_outputs: {}
```

[profile.yaml](../../extensions/napi2b/examples/profile.yaml) —
**шаблон, зависящий от научных источников**, не самостоятельный release-пример.
SUPPLIED identities заменяются только настоящими авторитетными записями.
Без файлов шаблон не исполняется. Его искусственный coordinate-free тест проверяет
сборку источников, 17+3 read-back и отказ при повреждённом SHA, не реальное исследование.

Core sdist включает двуязычные руководства и generic-примеры, но исключает тесты и дерево дополнительного расширения. Относительные ссылки на исходники/шаблон расширения предполагают полный checkout; при работе только с core sdist используйте отдельно предоставленные исходники/артефакты расширения. API установленных учебных ресурсов и автоматического поиска источников нет.

<a id="biology"></a>
## Фиксированный эталон, mapping и QC

Неизменяемые ресурсы сохраняют O95436-1 sequence version 3, **690 остатков**, ECD
**234–361** и MX35 **311–341**, включительно. Фиксированный sequence SHA256:
`33ce6c59e28a7373fce51debe32cec8d891ef691c2e77a0655a74040da25eef9`;
он отличается от generic digest полного reference-roster. Источник закреплён;
онлайн-обновления и default-белка в Core нет.

Реальные mapping системы, glycosylation/disulfide/variant annotations, научные
источники и решения экспертов остаются внешними. В полных fixed annotations
отсутствующий site может означать false; в неполных generic — unknown/null.
Legacy mapped-Cα RMSD требует явных mapping/reference и prepared-происхождения.
Алгоритмы Core используются повторно, а не копируются в калькулятор расширения.

Пороги выбранной политики: 95% production coverage, >1% валидных пустых белковых
окон для REVIEW, строгие median ±3 **raw unscaled MAD** и правила n=1/MAD=0.
Это не generic defaults. Hard FAIL нельзя переопределить; REVIEW требует
переданного уполномоченного решения. См. [Науку QC](science.md#qc).

<a id="sources"></a>
## Точные связи с источниками

`options.qc_manifest_path` читает
`mania_napi2b.dataset_sources_bindings.v1`. Точные поля: `schema_version`, `kind`,
`qc_sources`, `control_evidence`, `policy_evidence`, `handoffs`,
`qc_evidence_files`, `qc_decision_files`, `group_files`, `fixed_mappings`,
`canonical_sources`, `annotated_sources`, `fixed_qc_files`,
`publication_input_evidence`. `qc_sources` связывает generic QC source document.
File evidence сохраняет точные role/path/size/SHA относительно корня источников.
Release-input path использует сохранённый publication-input контракт.

Упорядоченные tuples сериализуются массивами: handoffs содержат
`[FileEvidence, WindowInputBinding, SystemAnnotations|null, rmsd_directory|null]`;
fixed mappings — `[InputIdentity, FileEvidence]`; canonical/annotated sources —
`[InputIdentity, protein|lipid|glycan, FileEvidence]`. Generic/profile policy,
cohort, identities, units и metric selections согласуются. Переданные полные
annotation bindings остаются авторитетными. Не выводите mapping, group, MET-0200,
определение научной метрики или reviewer decision. Валидация/восстановление полного
DatasetSources предшествуют сериализации.

<a id="dataset"></a>
## Граница совместимости Dataset-v1

Строгая выбранная проекция содержит **17 CSV +3 JSON** и сохранённую контрольную
копию входа. Ниже фиксированные пути реестра относительно корня профиля;
это не универсальная структура Core:

```text
aggregates/protein_edges_by_window_replica_aggregation.csv
aggregates/protein_glycan_contacts_by_window_replica_aggregation.csv
aggregates/protein_lipid_contacts_by_window_replica_aggregation.csv
canonical/nodes.csv
canonical/residue_annotations.csv
metadata/contact_definitions.csv
metadata/quality_control.csv
metadata/quality_control_evidence.csv
metadata/quality_control_findings.csv
metadata/simulations.csv
metadata/software_versions.csv
metadata/systems.csv
metadata/time_windows.csv
metrics/metrics.csv
science/protein_edges_by_window.csv
science/protein_glycan_contacts_by_window.csv
science/protein_lipid_contacts_by_window.csv
release/artifact_inventory.json
release/dataset_manifest.json
release/provenance.json
```

Проекция копирует авторитетную upstream-науку; не считает отсутствующие метрики,
не создаёт каталоги FAIR и не одобряет публикацию. Вложенный inventory доступен
под ролью `profile_inventory`, без переименования/перезаписи файла. Нужны полное
происхождение, совместимые reference/windows/partners/QC и строгое восстановление,
а не только наличие 20 имён файлов.

<a id="preview"></a>
## Exploratory preview

В Exploratory явно выбранные `napi2b.dataset.v1` и `profile_outputs` создают только
неавторитетный preview. **Все требования полных source, mapping, annotation,
metric, QC и correspondence** сохраняются. Успешный preview содержит 17 проверенных
таблиц в `profiles/p0001/preview/tables/` и
`profiles/p0001/preview/preview_manifest.json` со схемой
`mania_napi2b.dataset_exploratory_preview.v1`, source/run bindings и хешами.
Сопоставимая полная проекция сохраняет те же научные байты таблиц.

Официальных Dataset-v1 release manifests/provenance/seals нет. Официальные readers
отвергают preview; используйте validator preview выбранного профиля. Неполные/
ошибочные источники и неразрешённый обязательный review сохраняют failed/pending
без поддельного completion manifest. `SCIENTIFIC_VALIDATION_NOT_PERFORMED`,
`authoritative_release_eligible=false` и применимое unverified-PBC происхождение
сохраняются. Такие результаты не являются научно квалифицированными авторитетными
входами выпуска FAIR.

[Руководство пакета NaPi2b](../../extensions/napi2b/README.md) ·
[Контракты результатов](outputs.md#qualification)

---

[Все руководства](README.md) · [English](../eng/extensions.md)
