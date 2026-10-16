# Справочник конфигурации

Схема UTF-8 YAML — **`mania.run_config.v1`**. YAML задаёт запрос; научные файлы
предоставляют требуемые конкретным методом подтверждённые источники.
Начинайте со [скопированного исполняемого примера](quickstart.md#copy), а не
с выдуманного поля или исторического API конфигурации. Значения ниже относятся
к нынешнему run-интерфейсу; legacy-опции Python имеют отдельные контракты.

<a id="top-level"></a>
## Поля верхнего уровня

| Поле | Обязательность / default | Значение |
| --- | --- | --- |
| `schema_version` | Обязательный литерал `mania.run_config.v1` | Версионированная закрытая схема |
| `project` | Обязательная непустая строка | Научная идентичность проекта |
| `mode` | `basic` | `basic`, `custom`, `full`, `exploratory` |
| `systems` | Обязательный непустой упорядоченный список | Входные записи и научные идентичности |
| `output` | Обязательный объект с `root` | Собственная папка результатов и настройки записи |
| `methods` | Пустой объект | Типизированные опции; развёртывание режима сохраняется |
| `extensions` | Пустой список | Явно выбранные дополнительные профили |
| `comparisons` | Пустой список | Явные группы сопоставленных входов |
| `replica_groups` | Пустой список | Явные совместимые группы реплик |
| `reproducibility` | Объект по умолчанию | Контрольные суммы входов и переданный манифест |

<a id="systems"></a>
## Системы и научные идентичности

Каждая запись требует `id`, `trajectory_id`, `replica_id`, `engine` (`gromacs`
или `namd`), `topology`, непустой упорядоченный `trajectories` и `pbc`.
`condition`, `variant_id`, `disulfide_state` — необязательные строки/null.
Идентичность выполнения — `(project, id, trajectory_id, replica_id)`; повтор
составного ключа ошибочен. Повтор condition не объединяет входы и не создаёт
парную популяцию. Метки не выводятся из имён папок.

Дополнительные поля: `frames`, `physical_time`, `reference`, `mapping_path`,
`annotations_path`, `partners_path`, `namd_authority`, `input_binding_path`,
`fasta_path`, `method_overrides`. Их отсутствие допустимо, только когда выбранный
расчёт в них не нуждается. Одна последовательность не даёт MD-наблюдений.

<a id="paths"></a>
## Буквальные пути и независимые рабочие папки

**Относительные входные и выходные пути разрешаются от папки YAML, а не cwd
процесса.** Абсолютные Linux-пути поддерживаются. Схема не раскрывает `~`,
переменные окружения или glob; `..`, обратные слеши, синтаксис диска с двоеточием,
управляющие символы и неоднозначные записи отвергаются. В WSL используйте
абсолютные Linux-пути вместо Windows-синтаксиса диска. Входы должны быть существующими
обычными файлами; aliases, symlinks и пересечения входов/выходов проверяются строго.

Копирование YAML и `tiny.pdb` в новую пользовательскую папку делает её местом
входа и результата `results-<mode>`. Поставляемые выходные пути безопасны именно
в скопированном workflow: запись результата в исходном дереве MANIA блокируется. Независимый
исследовательский проект может содержать `.git`; само по себе это не запрещает
его папку `output/`. Все четыре
папки различны; перезапись по умолчанию отключена. См. [Быстрый старт](quickstart.md).

Дополнительные локальные каталоги только для чтения можно объявить перед запуском
через необязательную переменную окружения `MANIA_PROTECTED_ROOTS`. Укажите
абсолютные пути существующих каталогов с разделителем `os.pathsep` (`:` в Linux).
Если переменная не задана, дополнительных корней нет; явные пустые элементы,
относительные пути/переходы `..`, компоненты-симлинки, отсутствующие каталоги
и обычные файлы вызывают отказ до записи. Это не меняет YAML и не ослабляет
автоматическую защиту исходников/кода пакета, входов или собственных результатов.
Посторонние архивы требуют явного объявления; эта дополнительная защита действует
только при заданной переменной.

<a id="frames"></a>
## Исходные кадры, физическое время и окна

| Поле кадров | Default | Правило |
| --- | --- | --- |
| `start` | 0 | Нумерация с нуля, граница включена |
| `stop` | null | Граница исключена; переданное целое должно превышать start |
| `stride` | 1 | Положительное целое, отсчёт от start |
| `max_frames` | null | Явный положительный предел числа выбранных кадров; скрытого предела нет |
| `indexes` | null | Непустой возрастающий уникальный список неотрицательных индексов; не совместим с нестандартными интервалом/шагом/пределом |

Следующий иллюстративный **фрагмент записи системы** выбирает до пяти исходных
кадров; их идентичности не превращаются в компактные номера строк:

```yaml
frames:
  start: 0
  stop: 20
  stride: 2
  max_frames: 5
# Alternative, not combined with the nondefault selector above:
# frames: {indexes: [0, 2, 4]}
```

`physical_time` несовместим с явно переданным объектом `frames`, включая
`frames: {}`. Задайте `production_start_ns >= 0`, `production_end_ns > start`
и положительный `frame_stride_ps`. Нужны настоящие числовые YAML-скаляры,
без booleans/нефинитных значений. Выборка использует Decimal-сетку целевых моментов
и однозначное сопоставление исходного времени; пропуски остаются пропусками.
Окна для физической выборки необязательны. Для методов физических окон дополнительно
задайте `variant_id` и полный `windows`. Иллюстративный фрагмент не означает,
что малый PDB следует запускать на этом временном интервале:

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

`step_ns` положителен и <= `length_ns`; `overlap_percent` в [0,100) должен
согласовываться с `100*(1-step/length)`. Точные ID профилей:
`mania.window_boundaries.legacy.v1` и `mania.window_boundaries.inclusive.v1`.
Физические окна отличаются от `temporal_rin.window_size/step_size`, измеряемых
выбранными кадрами. Границы, покрытие и существующие допуски времени описаны
в [Науке](science.md#time-windows).

<a id="pbc"></a>
## Декларации PBC

| `pbc.mode` | Дополнительные поля / значение |
| --- | --- |
| `nonperiodic` | Содержательная `declaration`; нет противоречащей периодичности и пути preparation evidence |
| `prepared` | `declaration` и существующий `preparation_evidence_path`, связывающий источники/атомы/кадры/время с пригодностью |
| `unverified` | Только Exploratory; содержательная `declaration`, без preparation evidence; координаты читаются как есть |

Ни один режим не выполняет MIC/wrap/unwrap/центрирование. Флаг или размер ячейки
не доказывает научную пригодность. Непериодическая декларация с ненулевой ячейкой
остаётся противоречивой, в том числе в Exploratory. Подготовленные доказательства
проходят собственные строгие проверки чтения и происхождения. Basic/Custom/Full
отвергают unverified.

<a id="methods"></a>
## Методы, опции и зависимости

Порядок объединения: preset режима → глобальные `methods` → `method_overrides`
записи. Ранее заданные значения меняются только переданными полями. Для метода
с defaults используйте `{}`, не YAML `null`. У каждого метода есть `enabled`
(default true). Отключённая зависимость включённого метода — ошибка конфигурации.

| ID метода | Другие опции / defaults | Основные требования |
| --- | --- | --- |
| `contacts` | `selection: protein` либо `all`; `atom_filter: heavy`; `cutoff_distance: 4.5`; `distance_unit: angstrom`; `skip_resnames: []`; `min_frequency: 0.0` | Доступные координаты выбранных атомов/остатков |
| `static_rin` | Нет | `contacts` с выборкой protein |
| `communities` | Нет | `static_rin` |
| `region_enrichment` | Явный включённый объект требует `annotations_path` | Сообщества, переданные annotations/reference/mapping |
| `typed_interactions` | Нет | Контакты; публикует типизированные наблюдения |
| `rg` | Явный включённый запрос требует `selection`; `include_failed_frames: true` | Пригодная группа, массы, входы и координаты |
| `rmsd` | Обязательные `fit_selection`, `evaluation_selection`, `reference` | Правильное соответствие атомов и пригодная геометрия |
| `temporal_rin` | `window_size: 10`, `step_size: 10`, `min_frequency: 0.25` | Контакты/покадровые наблюдения; окна в кадрах |
| `fingerprints` | Нет | Контакты и принятый набор признаков/кадров |
| `pca` | `max_components: 10` | Fingerprints |
| `clustering` | `basis: fingerprint` либо `pca`; `max_k: 10`; `max_iterations: 100`; положительный `pca_components` только для pca | Fingerprints; при basis pca добавляется зависимость PCA |
| `physical_windows` | Нет | Контакты, физические окна, `variant_id` |
| `lipid_contacts`, `glycan_contacts` | Нет | Физические окна и `partners_path`; фиксированные пороги 6.0/4.5 Å |
| `replay` | Обязательные `completion_path`, `execution_plan_path` | Завершённые связанные покадровые данные; координаты не открываются |
| `comparison` | Нет | Явные `comparisons` и источник соответствий |
| `replica_aggregation` | Нет | Явные `replica_groups` и доступность/соответствие |
| `qc` | Обязательный `evidence_manifest_path`; generic `policy_path`; необязательный `review_decisions_path` | Связанные источники и совместимая политика/когорта |
| `profile_outputs` | Нет | Явный dataset-профиль и полный набор источников расширения |

Частотные пороги контактов в [0,1]; расстояния конечные положительные Å.
Размеры временных окон, число компонент и итераций — положительные целые;
`max_k >= 2`. Фиксированные константы химии не становятся новыми YAML-опциями.
Перечень ID закрыт; RMSF/SASA/вторичная структура, `n_jobs`, `resume` и флаги
подготовки PBC не поддерживаются. Defaults режимов описаны в [Режимах](modes.md).

<a id="rg-rmsd"></a>
## Запросы Rg и RMSD

Полностью опустите `rg` для условного автоматического белкового Rg в Basic/Full.
Нужны полная однозначная выборка белка, корректные массы/данные и пригодность
координат. `rg: {}` — явный неполный запрос и ошибка. Для отключения используйте
`rg: {enabled: false}`. Явный запрос задаёт настоящую непустую MDAnalysis-selection,
например `selection: protein`, и по-прежнему требует пригодности.
Exploratory отключает автоматический Rg и не подтверждает непроверенный PBC.

RMSD не выбирается без полного явного набора из трёх полей. Следующий
**фрагмент methods** исполним с поставляемой четырёхатомной геометрией внутри
корректного Custom YAML; индексы selection относятся к атомам, а не остаткам:

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

`first_selected` принимает **только `kind`**, в том числе при повторном чтении
effective-config. Лишние `path` или `atom_mapping_path` даже со значением null
отвергаются. Внешний эталон требует обоих путей, `mania.rmsd_external_coordinates.v1`
и `mania.rmsd_atom_mapping.v1`: конечные координаты Å, точные SHA/размеры
топологии/эталона и упорядоченные взаимно однозначные fit/evaluation identities.
Автоматического соответствия по именам или выбора эталона нет. Fit требует >=3
неколлинеарных конечных атомов (rank >=2); evaluation — >=1 без отдельного rank.

<a id="authorities"></a>
## Дополнительные научные источники

| Поле конфигурации | Источник и ограничения |
| --- | --- |
| `reference: {reference_path: ..., sha256: ...}` | `mania.reference.v1`; необязательный SHA файла; полный digest упорядоченного roster проверяется отдельно |
| `mapping_path` / `annotations_path` | `mania.residue_mapping.v1` / `mania.annotations.v1`; явные химия, пространства имён и полнота |
| `partners_path` | Переданные топология/метаданные партнёров, компоненты и связь гликана; без угадывания имён остатков |
| `namd_authority: {elements_path: ..., time_path: ...}` | `mania.namd_atom_type_elements.v1`, `mania.namd_time_authority.v1`; нужны для чтения NAMD, ровно один связанный DCD |
| `input_binding_path` / `fasta_path` | Связанные с источником identities/кадры/preparation / необязательное свидетельство последовательности, не автоматический научный источник |
| `comparisons[]` | `id`, >=2 упорядоченных `members`, `matching_path`, необязательный `annotations_path`; у участника `system_id`, `trajectory_id`, `replica_id` |
| `replica_groups[]` | `id`, >=1 упорядоченных `members`, `reference_id`, `layer: protein\|lipid\|glycan`, `availability_path`, необязательные `correspondence_path`, `qc_decisions_path`; специальные слои требуют correspondence |
| `extensions[]` | Явные `id: napi2b`, `version: '==0.2.0'`, профиль и дополнительные пути; см. [Расширения](extensions.md) |

Сопоставление сравнений использует `mania.static_rin_matching.v1`; равенство
числовых номеров остатков не задаёт соответствие. Доступность реплик и совместимые
reference/layer/window передаются, а не выводятся из разреженных файлов.

Оболочка generic QC `mania.qc_source_bindings.v1` содержит ровно `schema_version`,
`kind`, `policy_evidence`, `group_evidence`, `members`. Упорядоченные участники:
`identity`, `qc_evidence`, `window_input`, `metric_selections`. Window input
связывает `temporal_evidence`, `observation_directory`, `observation_evidence`,
`mapping_evidence`, `reference_evidence`. Каждый выбор метрики задаёт `check_id`,
`source`, `source_row_key`, `numeric_field`, `unit`. `FileEvidence` связывает
точные `role`, `path`, `size_bytes`, `sha256` относительно объявленного корня
доказательств. Используйте поддерживаемые конструкторы/readers; не выдумывайте
эти документы. Выбранный профиль может задать политику, но не источники и решения.

<a id="output"></a>
## Настройки вывода и воспроизводимости

| Объект | Поля / defaults |
| --- | --- |
| `output` | Обязательный `root`; `overwrite: false`; `log_level: INFO` (DEBUG/INFO/WARNING/ERROR); `retain_perframe: false` |
| `reproducibility` | `checksum_mode: none` либо `sha256`; необязательный `input_checksum_manifest_path` |

При необходимости методы с доказательствами принудительно сохраняют покадровые
данные и отражают это в плане. `checksum_mode: none` не отключает обязательные
digests источников и эталонов. Dry-run не хеширует всю траекторию. Существующий
результат требует явного overwrite и проверки владения; посторонние файлы
не дают разрешения на перезапись.

<a id="validation"></a>
## Строгая проверка и типичные ошибки

Отвергаются неизвестные/повторные ключи на каждом уровне, нестроковые ID,
преобразования скаляров, booleans вместо чисел, нефинитные числа, циклические
aliases, YAML merge keys, BOM, конкурирующие selectors и неполные научные объекты.
Заключайте похожие на числа идентификаторы в кавычки; для отключения нужен
настоящий boolean `false`. Отсутствующий файл — ошибка до расчёта;
неустановленный научный факт не равен нулю. Перед выполнением подтвердите план
через [dry-run](commands.md#dry-run).

---

[Все руководства](README.md) · [English](../eng/configuration.md)
