# MANIA source snapshot · снимок исходников

**[Русское руководство](docs/rus/README.md) · [English guide](docs/eng/README.md)**

This public source snapshot includes RMSF, isolated/with-environment SASA,
SASA `frame_stride`, B-01 source-path compatibility and the 3,840-point default.
Package metadata remains **0.2.0**; this is a source-branch update, not a new
numbered software release. Record the public Git commit when identifying this
code: version 0.2.0 alone cannot distinguish it from the initial public snapshot.

Этот публичный снимок исходников включает RMSF, isolated/with-environment SASA,
SASA `frame_stride`, исправление путей B-01 и сетку по умолчанию из 3840 точек.
Версия в метаданных остаётся **0.2.0**; это обновление ветки исходников, а не
новый нумерованный выпуск. Для идентификации кода сохраняйте публичный Git commit:
одной версии 0.2.0 недостаточно для отличия от первоначального публичного снимка.

MANIA analyzes molecular trajectories from an explicit YAML request and records
scientific CSV/JSON, method statuses and provenance. Implemented methods include
protein and supplied-partner contacts, Rg, explicit-reference RMSD, static and
temporal residue networks, fingerprints, PCA, clustering, comparisons, replica
aggregation and QC with supplied authority.

MANIA анализирует молекулярные траектории по явному YAML-запросу и сохраняет
научные CSV/JSON, статусы методов и происхождение результатов. Реализованы
контакты белка и явно заданных партнёров, Rg, RMSD с явным эталоном, статические
и временные сети остатков, fingerprints, PCA, кластеризация, сравнения, агрегация
реплик и QC по переданным научным источникам.

The distribution is **`mania-wania`**, the command/import **`mania`**. Python
>=3.11 is required; technical checks cover specific Linux Python
3.11/3.12 environments. Coordinate reading requires the optional `md` extra
(MDAnalysis==2.10.0); `science` is its compatibility alias. NaPi2b is separately
installed and explicitly selected. Core works independently; FAIR is a separate
scientific project and WANIA an external visualization application.

Дистрибутив — **`mania-wania`**, команда/импорт — **`mania`**. Нужен Python >=3.11;
технические проверки этой версии относятся к конкретным Linux-окружениям Python
3.11/3.12. Чтение координат требует extra `md` (MDAnalysis==2.10.0); `science` —
совместимый псевдоним extra. NaPi2b устанавливается и выбирается отдельно. Core
независим; FAIR — отдельный научный проект, WANIA — внешняя визуализация.

Follow the [English quickstart](docs/eng/quickstart.md) or
[русский быстрый старт](docs/rus/quickstart.md) to install from source,
run the four synthetic examples in your own directory, and describe your own
trajectory.

В руководствах показаны установка из исходников, четыре синтетических
примера в своей папке и описание собственной траектории.

The retained Python clustering API writes `conformation_labels_{condition}.csv`
using deterministic dependency-free k-means on a binary contact fingerprint or
PCA coordinates. It does not claim notebook PCA-to-k-means parity; consult the
[scientific definitions](docs/eng/science.md#clustering).

Сохранённый Python API кластеризации записывает `conformation_labels_{condition}.csv`
детерминированным k-means без дополнительных зависимостей по бинарным контактным
признакам либо координатам PCA. Равенство notebook PCA-to-k-means не заявляется;
см. [научные определения](docs/rus/science.md#clustering).

**Scientific limits / Научные ограничения.** Strict modes require nonperiodic
or externally prepared coordinates with appropriate evidence. Exploratory reads
explicitly unverified coordinates as supplied and always records
`SCIENTIFIC_VALIDATION_NOT_PERFORMED`, `authoritative_release_eligible=false`
and, when applicable, `PBC_UNVERIFIED`. There is no internal MIC, wrap, unwrap or
centering. This source snapshot computes RMSF/SASA; see the
[settings](docs/eng/configuration.md#rmsf-sasa) and
[definitions](docs/eng/science.md#rmsf-sasa). Technical verification is separate
from scientific qualification of each intended input and use. Secondary-structure computation remains unimplemented.
Real-input scientific qualification is incomplete; technical success and artifact
integrity do not establish biological correctness or publication readiness.

Строгие режимы требуют непериодических либо внешне подготовленных координат
с соответствующими доказательствами. Exploratory читает явно непроверенные
координаты как есть и сохраняет указанные признаки неполной квалификации.
Внутренних MIC, wrap, unwrap и центрирования нет. Этот снимок вычисляет
RMSF/SASA; см. [настройки](docs/rus/configuration.md#rmsf-sasa)
и [определения](docs/rus/science.md#rmsf-sasa). Техническая проверка отделена
от научной квалификации каждого предполагаемого входа и применения. Вторичная структура не вычисляется. Научная квалификация реальных
входов не завершена; технический
успех и целостность артефактов не доказывают правильность биологии или готовность
к научной публикации.
