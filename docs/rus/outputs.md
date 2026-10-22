# Результаты, статусы и повторное чтение

Начните с `summary.json`, затем `path_identity_map` плана и ролей артефактов.
Ниже **структура**, а не утверждение о выполнении всех методов или наличии всех
папок. Корни учебных примеров — независимые пользовательские папки.

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

`sNNNN`, `tNNNN`, `gNNNN` — детерминированные порядковые токены конфигурации.
Исходные научные identities остаются в plan/summary; токен или повтор condition
их не заменяет. Выход выбранного профиля сейчас `profiles/p0001`, а не общее
правило `profiles/napi2b`.

<a id="controller"></a>
## Записи контроллера

| Файл | Назначение |
| --- | --- |
| `effective_config.yaml` | Связанные пути и эффективные настройки вывода/конфигурации, включая нужное retention; defaults методов также разрешены в записях плана |
| `run_plan.json` | `mania.run_plan.v1`: input identities, пути, требования/опции/статусы методов, профили, ожидаемые роли и непроверенные условия |
| `summary.json` | Run ID/mode/status, фактические `methods`, `artifact_references`, пути, выбранные расширения и адреса provenance |
| `run.log` | Запись выполнения/статусов контроллера; консольный прогресс — отдельное представление |
| `provenance/run_provenance.json` | Запрошенные/эффективные связи с источниками, selections, наблюдённая выборка, runtime и завершённость |
| `provenance/artifact_inventory.json` | Точные собственные role/path/byte size и применимые SHA256; не научный сертификат |
| `provenance/runtime_metadata.json` | Настоящая идентичность software/dependencies/runtime; недоступный Git не выдумывается |

Ожидаемые артефакты плана — намерения. Что создано, определяют фактические
summary/inventory. Зависимости инвентаря не образуют самохеширующего цикла;
хеширование входов следует reproducibility, обязательные digests источников
сохраняются. Digest связывает байты, не биологический смысл.

<a id="scientific-files"></a>
## Основные научные файлы и поля

Файлы ниже зависят от запроса и настоящего исхода. `{token}` — входной токен
контроллера (в примере `t0001`). Единицы и missing принадлежат конкретной схеме;
перед объединением популяций читайте [Науку](science.md).

| Файл / семейство | Основное содержимое |
| --- | --- |
| `preprocessing/contact_edges.csv` | Legacy aggregate: source/target identity, `contact_frame_count`, `total_frame_count`, `contact_frequency`, `minimum_distance`, `mean_minimum_distance`, `distance_unit`, `atom_filter` |
| `preprocessing/protein_contact_edges.csv` | Типизированные пары: `edge_type`, `contact_frame_count`, `sampled_frame_count`, `contact_freq`, `mean_dist_A`, `std_dist_A`, `weight` |
| `preprocessing/edge_semantics.json` | Сохранённые интерпретация/приоритет типов рёбер |
| `preprocessing/residue_table.csv` | Исходный roster, residue/segment identity, представительные CA; дополнительные переданные legacy-столбцы могут быть пустыми |
| `preprocessing/protein_contacts_perframe.csv` | Сохранённые typed positives: `frame_index`, `time_ps`, identities пары, `edge_type`, `distance_A`; не полный physical missing/zero completion |
| `analysis/graph.json` | Узлы/рёбра static graph, primary `edge_type`, `all_edge_types`, `n_edge_types`, веса и identity |
| `analysis/centrality_{token}.csv` | Identity узла, degree, strength, betweenness, closeness, eigenvector, PageRank, k-core |
| `analysis/communities_{token}.csv` | Локальные ID/size сообщества, algorithm, modularity и число |
| `analysis/region_enrichment_{token}.csv` | Contingency/enrichment переданных меток либо явный skipped |
| `analysis/temporal_rin_{token}.csv` | `window_id`, исходные `frame_start/end`, sampled/active counts, nodes/edges и оконные метрики/status |
| `analysis/conformation_pca_{token}.csv` | Исходный кадр/время, pc1..pc3 и explained ratios, число компонент/признаков/кадров, status/notes |
| `analysis/conformation_labels_{token}.csv` | State/cluster, k, silhouette, representative, квадрат `distance_to_centroid`, basis/status |
| `preprocessing/rg_timeseries.csv` | Исходные кадры/время, Rg в Å и диагностика ошибочных кадров |
| `preprocessing/rmsd_timeseries.csv` | Запрошенные sample/time, `state`, runtime/source/prepared indexes, actual time/delta, `rmsd_A` |
| `preprocessing/rmsd_measurement.json` | `mania.rmsd.v1`: identities эталона/выборок и свидетельства измерения |
| Физические окна / observations | `temporal_execution.json`, `observations/` completion и typed per-frame, `protein_edges_by_window_source.csv`, при выборе lipid/glycan source tables |
| Reference/annotated окна | Исходные значения плюс проверенные reference keys/digests и переданные аннотации; геометрия не пересчитывается |
| `comparisons/gNNNN/{comparison,stats}.csv` | Matching-v1 64/62 упорядоченных столбца, обе исходные identities, values/deltas, парные counts/statistics и причины |
| `replicas/gNNNN/` | Layer-specific `*_by_window_replica_aggregation.csv`, совместимые window/reference/partner keys и статистика по доступности |
| `systems/.../qc/qc_decisions.json` | Связанные источники QC policy/evidence/findings и настоящие решения; без выдуманного reviewer |

Физические source tables содержат requested/effective window bounds,
`requested_sample_count`, `resolved_frame_count`, `missing_sample_count`,
`coverage_fraction`, `n_contact_frames`, `occupancy`, `n_contact_episodes`,
`mean_episode_length_ns`, `max_episode_length_ns`; партнёрские таблицы дополнительно
хранят partner/linkage и `distance_mean_A`, `distance_min_A`. Расстояния в Å;
временные поля явно используют ps или ns. Coverage/occupancy/support безразмерны.
Fingerprints могут завершиться в памяти без отдельного файла; смотрите реальные
роли артефактов.

Backend legacy `nodes.csv`/`edges.csv`/`graph.json` имеют разные validators;
aggregate `contact_edges.csv` не равен backend `edges.csv`. Export bundle
использует готовые файлы и сам не выполняет диагностику. Diagnostics report
потребляет готовую диагностику. Сохранённый Python analysis может создавать
`extended_metrics.json` со своими выходами; файл не гарантирован в каждом unified CLI.

Сохранённые writers nodes и backend edges имеют отдельные границы проверки.
Graph CSV validation использует созданные `nodes.csv` и исправленные `edges.csv`.
Graph JSON writer использует принятые/проверенные nodes и исправленные edges.
Backend edges сохраняют все уникальные типы и primary-приоритет. Export bundles
используют готовые nodes/edges/graph и не запускают диагностику. Diagnostics
запускает существующие graph validators готовых артефактов; reports используют
вычисленную диагностику без повторного запуска. Проверка входов reference comparison
проверяет готовность generated/reference artifacts без сравнения; comparison API
выполняет отдельную операцию. Reference comparison по умолчанию отключён и требует
явных путей reference artifacts. Техническая валидация не является научным одобрением.

Сохранённый API `write_temporal_rin_csv` создаёт файлы
`temporal_rin_{condition}.csv`; unified workflow записывает
`analysis/temporal_rin_{token}.csv`. Построитель окон сам не вычисляет
метрики временного графа; их вычисляет отдельный API метрик.

<a id="missing"></a>
## Null, ноль, отсутствие и сериализация

| Представление | Научный смысл |
| --- | --- |
| Числовой 0 | Вычисленный ноль или доказанный negative в нужной популяции |
| JSON null / определённая схемой пустая CSV-ячейка | Неизвестное, недоступное или неопределённое значение; читайте статус |
| Нет sparse-строки ребра | Нет exported positive; ноль обоснован лишь полным доступным observation evidence |
| Missing/failed кадр | Не отрицательный контакт; не добавляется в resolved-знаменатель occupancy |
| n=1 replica SD null | Выборочный разброс неопределён; отличается от нулевой SD при n>=2 |

Сохраняются порядок строк/столбцов и serializer семейства: RMSD `.17g`, static/
analysis floats `.15g`, собственное форматирование legacy contact/Rg, fixed Dataset
numbers через точный `Decimal.from_float` для native floats. Универсального
округления нет. Legacy `rmsf_A`, `sasa_A2`, `ss`, lifetime/window-CV могут быть
переданными или пустыми; имя не означает выполнение соответствующего метода.

<a id="statuses"></a>
## Статусы методов и запуска

| Статус метода | Значение |
| --- | --- |
| `not_requested` | Не выбран или явно отключён |
| `not_applicable` | Доказанная неприменимость либо допустимое вырождение метода |
| `missing_optional_input` | Необязательный preset не установил требование; не научный negative |
| `planned`, `running` | Намерение/выполнение, не завершённое измерение |
| `completed` | Реальное вычисление метода завершено по контракту |
| `pending_review` | Обязательный внешний review не разрешён |
| `failed`, `cancelled` | Настоящий неуспешный/прерванный исход |

Запись хранит `method_id`, identity, `request_origin`, `reason_code`, message,
prerequisites, effective parameters и artifact roles. Общий `completed_with_skips`
допускает объяснённые необязательные пропуски preset; явная обязательная ошибка
не превращается в этот статус. `pending_review`, `failed`, `cancelled` сохраняют
доступные частичные выходы. Не используйте частичный файл как завершённый dataset.
Preflight может завершиться до владения выходом; автоматического resume нет.

<a id="validation"></a>
## Повторное чтение, целостность и явный replay

```sh
mania artifacts validate --root /path/to/work/results-basic
```

Reader проверяет связанные config/plan/summary/provenance/inventory/runtime
identities, собственные файлы, применимые digests и научные typed structures.
При интеграции используйте установленный Python независимо:

```python
from mania.result_readers import read_run_summary, validate_run_artifacts

summary = read_run_summary("/path/to/work/results-basic")
validated = validate_run_artifacts("/path/to/work/results-basic")
print(summary.status, validated.artifact_count)
```

Честный failed-root может пройти integrity: читайте настоящий статус. Целостность
не доказывает QC PASS, научную пригодность PBC или публикационное одобрение.
Replay — отдельный явный метод с завершёнными observation и execution-plan
источниками; валидация сама не пересчитывает траекторию и не делает replay.
См. [Науку replay](science.md#replay).

Сохранённые Python-интерфейсы: `mania.preprocessing`, `mania.analysis`,
`mania.comparison`, `mania.validation`, `mania.export`, `mania.pipeline_steps`,
`mania.adapters.notebook_export`. В частности,
`mania.analysis.orchestration.run_analysis(AnalyzeRequest(...))` читает проверенные
preprocessing artifacts, а не сырые траектории. `compute_condition_contacts`,
`compute_manifest_contacts`, `compute_condition_rg`, `compute_manifest_rg`
сохраняют отдельные опции и записи результата/ошибок. Legacy config/pipeline
и preprocessing planning APIs имеют свои контракты; один план не выполняет
вычислительные API и не валидирует reference comparison.

Временной анализ RIN отделён от сохранённого legacy preprocessing controller;
unified YAML workflow реализован. Валидация reference package, переданной
residue library и input/config/report/graph/comparator остаётся отдельными
поддерживаемыми Python API.

<a id="qualification"></a>
## Квалификация Exploratory и NaPi2b preview

Строгие результаты сохраняют `mania.run_summary.v1` и `mania.run_provenance.v0.1`.
Exploratory использует `mania.run_summary.v2` и `mania.run_provenance.v0.2`,
оба с одинаковым закрытым `mania.scientific_qualification.v1`. Он связывает
source identities/PBC declarations/upstream receipts, финальные scopes методов
и настоящих научных артефактов. Все исходы сохраняют
`SCIENTIFIC_VALIDATION_NOT_PERFORMED`, `authoritative_release_eligible=false`
и реальное `PBC_UNVERIFIED` происхождение при наличии. Read-back их сверяет;
отделённый CSV или пересчитанная checksum не повышает квалификацию. Исторические
схемы не получают задним числом утверждение научного одобрения.

Явный строгий NaPi2b Dataset-v1 использует фиксированный реестр **17 CSV +3 JSON**
и сохранённую контрольную копию. Контроллер называет вложенный inventory
`profile_inventory`, не меняя его байтов. Полнота реестра не даёт разрешения
публикации.

Exploratory создаёт только `profiles/p0001/preview/tables/` (17 проверенных таблиц)
и `profiles/p0001/preview/preview_manifest.json` со схемой
`mania_napi2b.dataset_exploratory_preview.v1`. Полная сопоставимая проекция
сохраняет те же научные байты таблиц при всех требованиях source/QC;
неполная работа не даёт completed preview manifest. Официальные Dataset-v1
readers отвергают preview. Нет официального `release/dataset_manifest.json`,
release provenance или публикационной печати. См. [Расширения](extensions.md#preview).

<a id="rmsf-sasa"></a>
## Семейства артефактов RMSF и SASA в этом снимке

Файлы находятся в `systems/sNNNN/tNNNN/preprocessing/` только для завершённых
выбранных методов. Артефакты опубликованной 0.2.0 читаются без изменений.
Имена необязательных legacy-колонок сохранены и не используются вместо этих измерений.

| Файл | Содержимое |
| --- | --- |
| `rmsf_atoms.csv` | Упорядоченные исходные ключи атомов, `rmsf_A`, `observed_frame_count` |
| `rmsf_samples.csv` | Полный запрошенный roster: requested sample/time, observed/missing state, runtime/source/prepared index, actual time/delta, reason |
| `rmsf_measurement.json` | `mania.rmsf_measurement.v1`: контекст, опции, исходные rosters/hashes, фактический reference и fit coordinates/hash, N, means/M2, точность/proper rotation/равные веса/делитель N, CSV digests |
| `rmsf_external_coordinates.json`, `rmsf_atom_mapping.json` | Только внешний reference: точные сохранённые входные документы, без выдуманного соответствия |
| `sasa_atom_frames.csv`, `sasa_residue_frames.csv`, `sasa_total_frames.csv` | Вариант и полная sample identity; выбранные target-атомы/остатки; `sasa_A2`; в атомных строках также `accessible_points` |
| `sasa_atom_means.csv`, `sasa_residue_means.csv`, `sasa_total_means.csv` | Вариант, target identity при наличии, наблюдённое N, `mean_sasa_A2` |
| `sasa_measurement.json` | `mania.sasa_measurement.v1`: контекст, точные опции/обоснование, target/environment rosters/hashes, реестр Bondi/hash/DOI, использованные радиусы, probe, grid ID/count/hash, точность, строгое occlusion, целые counts и CSV digests |

CSV — UTF-8 с LF и фиксированным порядком заголовков; null — пустое поле,
валидный ноль — `0`. Float64 записывается с 17 значащими цифрами. JSON закрыт
и версионирован. Source atom keys сохраняют engine, индекс/имя атома, chain,
segment, residue/insertion/name, element и altloc; для остатков используется полный
residue key. Means включают только наблюдённые кадры. Поверхность окружения
и усреднённый по остаткам RMSF не экспортируются.

Чтение заново строит CSV из закрытого измерения, проверяет identity, role, schema,
популяции, точный порядок samples, reference/authority hashes, N, counts,
means/sums, options и grid/radius registry. Одна смена digest не делает испорченное
семейство валидным. Qualification strict/Exploratory и original/prepared lineage
остаются явными. Обоснование сохраняется в measurement options и provenance
parameters как заявление владельца, а не сертификат. Выходы не устанавливают
пригодность PBC, биологию или готовность публикации. См. [настройки](configuration.md#rmsf-sasa)
и [формулы](science.md#rmsf-sasa).


<a id="sasa-frame-stride"></a>
## Добавленные SASA sampling и привязки атомных источников

Этот снимок сохраняет `mania.sasa_measurement.v1` с дополнительным
`sampling`: полные `global_samples`, `selected_global_ordinals`,
`global_requested_count`, `requested_count`, `observed_count`, `processed_count`,
`missing_count`, `invalid_count`, `failed_count`, `unavailable_time_reason`.
В завершённом измерении processed=observed>0, failed_count=0. Ошибка сохраняется
в run/method status; выдуманный ноль/mean не запечатывается.

`context.samples[].requested_sample_index` — непрерывный **локальный SASA** ordinal.
`selected_global_ordinals[local]` указывает общий запрос, сохраняя его source/
prepared indices, actual time, state и reason. Новые SASA frame CSV добавляют
`global_requested_sample_index` и `actual_time_reason`; остальные поля/единицы
и все не-SASA CSV неизменны. Прежний `observed_frame_count` в means — N реально
обработанных SASA кадров, не общие M/запрошенные K.

`mania artifacts validate` восстанавливает G по effective global request и
настоящим source/header metadata прежним optional MD loader без научного kernel.
Проверяются global/local/source/prepared/time correspondence, популяции обоих
вариантов, counts, null/zero и means даже после пересчёта обычных hashes.
Проверка source lineage новых SASA-артефактов требует optional MD runtime и доступа
к объявленным входам. Старые v1 SASA первого кандидата без новых полей читаются
только по ограниченному исходному stride1/full-population контракту; свидетельства
не переписываются и не переименовываются скрытно.

Новые authority paths RMSF/SASA — переносимые role/content locators
`atomic_sources/<role>/<ordinal>/<sha256>/<basename>`. Это не пути для разрешения
от `/` либо папки YAML. Resolver строит их только по точному типизированному
roster effective config и проверяет canonical regular files, source identity
и настоящий digest. Topology, упорядоченные trajectories, binding/preparation,
NAMD element/time controls, явные RMSF reference/mapping имеют отдельные роли.
Старые относительные authority records используют прежние строгие правила.
Другие authority consumers и InputBinding не меняются. Проверки подтверждают
техническую lineage, а не PBC/биологию/научную приёмку.


---

[Все руководства](README.md) · [English](../eng/outputs.md)

Новые измерения SASA используют `mania.sasa.fibonacci3840.v1`, 3840 точек и SHA256 сетки `bd52bac9426729dcd0fff5445562eefe3745ea4cb8be70e04b80124ca31871f0`. Читатель неизменённой схемы `mania.sasa_measurement.v1` также принимает подлинные исторические измерения `mania.sasa.fibonacci960.v1` только с 960 точками и SHA256 `89662d78956cad341fdeddaddc793c36e5971c733fe9e832e6442a81399132dd`. Разрешены только эти точные сочетания идентификатора, числа точек и хеша; границы счётчиков и делитель площади соответствуют проверенной сетке. Только исторические артефакты 960 могут не содержать исходные поля sampling. YAML-настройки числа точек нет. Исторические результаты и FAIL при 960 сохраняют исходную интерпретацию; более плотная сетка не означает независимой научной приёмки.
