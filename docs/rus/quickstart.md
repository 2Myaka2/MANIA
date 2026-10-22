# Быстрый старт: синтетический пример и своя траектория

**MANIA 0.2.0.** Эти инструкции Bash/Linux
используют раздельные папки исходников, окружения и исследовательских данных.
Технические проверки относятся к конкретным численным окружениям Python 3.11/3.12;
они не обещают поддержку любых ОС или научную квалификацию реальных входов.

<a id="install"></a>
## A1. Получите исходники и установите изолированное окружение

В доступной для записи родительской папке получите исходники и создайте
виртуальное окружение вне checkout. Нужны Python 3.12 и сеть для обычного
разрешения зависимостей pip. Вместо него можно использовать `python3.11`, если
Python 3.11 установлен в вашем окружении. Если полный checkout уже получен,
начните с `cd MANIA`.

```bash
git clone https://github.com/2Myaka2/MANIA.git
cd MANIA
python3.12 -m venv ../mania-venv
source ../mania-venv/bin/activate
python -m pip install ".[md]"
mania --version
```

Так устанавливается дистрибутив `mania-wania==0.2.0` с поддерживаемым extra `md`;
команда и Python-импорт — `mania`. Это обычная установка из исходников.
Base требует NumPy >=2,<3, Pydantic >=2.7,<3 и PyYAML >=6,<7; чтение координат дополнительно требует MDAnalysis==2.10.0.
`science` — совместимый псевдоним того же reader. NaPi2b необязателен,
устанавливается и выбирается отдельно. О контролируемом воспроизведении численных
результатов см. [Воспроизводимость](reproducibility.md#environment).
`python -I -B -m mania` — изолированный установленный эквивалент команды `mania`.

<a id="copy"></a>
## A2. Скопируйте и выполните первый синтетический пример

Оставьте окружение активным и перейдите в родительскую папку checkout, как показано ниже.
Исходные ресурсы — четыре
YAML-файла в [examples/](../../examples/basic.yaml) и
[неизменённый tiny.pdb](../../examples/tiny.pdb). Исходные дистрибутивы содержат
общие примеры; установленные wheels не предоставляют API учебных ресурсов.
Необязательный `MANIA_Examples.zip` содержит ровно эти пять файлов в папке
`examples/`; при использовании полного checkout архив не нужен.

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

Ожидаемая версия: `0.2.0`. PDB содержит **две модели, четыре атома и два остатка
ALA**, специально созданные для учебной проверки программы. `engine: gromacs`
использует общий loader с PDB; это не реальная TPR/XTC-траектория и не
доказательство PBC. Помощники тестов или генератор входов не нужны.

**Относительные пути разрешаются от папки YAML**, независимо от cwd процесса.
Поэтому `tiny.pdb` — скопированный вход, а `results-basic/` появляется рядом
с `basic.yaml`. Результаты не могут пересекаться с входами, исходным деревом
MANIA или защищённым кодом пакета. Независимый исследовательский проект может
содержать `.git`; само по себе это не запрещает обычную папку результатов.

<a id="run"></a>
## A3. Выполните остальные примеры без перезаписи

Dry-run не создаёт результатов. Он проверяет конфигурацию и ограниченные
предварительные требования, не каждый кадр или научную пригодность PBC.
Отсутствующий MD-reader блокирует координатный запуск. До использования
результатов проверьте настоящие коды выхода и предупреждения. Полный JSON-план
доступен через `--dry-run --format json`.

После Basic выполните каждый оставшийся скопированный пример:

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

У каждого режима своя папка: `results-basic`, `results-custom`, `results-full`,
`results-exploratory`. Все примеры сохраняют `overwrite: false`. Повторный запуск
в непустую папку отвергается без молчаливой замены результатов. Для повторения
создайте новую папку, например `tutorial_02`. Автоматического resume нет.
Явная перезапись также требует точного inventory собственных результатов,
корректных provenance и повторного чтения; посторонние файлы не дают разрешения
на перезапись.

<a id="inspect"></a>
## A4. Прочитайте итог

Из `tutorial_01/` просмотрите записанные summary и provenance:

```bash
python -m json.tool results-basic/summary.json
python -m json.tool results-basic/provenance/run_provenance.json
```

В `results-basic/summary.json` находятся реальные статусы методов, затем изучите
`provenance/run_provenance.json` и `provenance/artifact_inventory.json` внутри
этой папки. Научные файлы — в `systems/s0001/t0001/{preprocessing,analysis}`;
см. [Результаты](outputs.md). Basic считает контакты/static RIN и отключает Rg
для данного неполного искусственного белка. Custom добавляет RMSD с раздельными
fit/evaluation. Full может сообщать объяснённые необязательные пропуски;
сохранённой популяции контактов недостаточно для PCA/clustering. Правильный
хеш артефакта не является научным одобрением.

Exploratory по умолчанию выполняет contacts/static RIN без автоматического Rg.
Пример сохраняет `SCIENTIFIC_VALIDATION_NOT_PERFORMED`,
`authoritative_release_eligible=false` и `PBC_UNVERIFIED`. Валидация не снимает
эти ограничения.

<a id="real-inputs"></a>
## B. Анализ своей траектории, включая Exploratory

`analysis_project` — иллюстративное имя, не обязательное расположение.
Создайте независимую исследовательскую папку, которая может быть Git-репозиторием,
и предоставьте настоящую совместимую топологию и упорядоченную траекторию:

```text
analysis_project/
├── exploratory.yaml
├── input/
│   ├── topol.tpr
│   └── trajectory.xtc
└── output/
```

Сохраните следующую полную корректную по схеме конфигурацию как
`exploratory.yaml`. Она задаёт непроверенный Exploratory-запрос, но не доказывает
читаемость или научную пригодность ваших файлов. Замените научные идентичности
собственными явными записями, не выводя их из имён папок.

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

`systems[].topology` задаёт топологию; `systems[].trajectories` — упорядоченный
непустой список. `id`, `trajectory_id` и `replica_id` вместе с `project` задают
идентичность научного входа. **Поля верхнего уровня `input:` нет**.
Пути `input/...` и `output/exploratory_01` разрешаются от этого YAML.
`output.root` выбирает новую папку результатов; `output.overwrite` предотвращает
неявную замену. Необязательные глобальные `methods` и системные
`method_overrides` изменяют только явно переданные опции; опущенные методы
сохраняют defaults режима. Например, явный RMSD требует fit/evaluation selections
и reference; его нельзя добавить, угадав отсутствующий научный источник.

Запустите из папки, содержащей `analysis_project/`, с активным окружением:

```bash
cd analysis_project
mania run --config exploratory.yaml --dry-run
mania run --config exploratory.yaml
mania artifacts validate --root output/exploratory_01
```

Используйте `pbc.mode: unverified` только при неподтверждённой пригодности
координат и честно укажите это в `declaration`. Строгие Basic/Custom/Full требуют
непериодических либо внешне подготовленных координат и необходимых доказательств.
Exploratory **не исправляет периодические координаты**, не подтверждает
непроверенный протокол PBC и не делает результаты научно авторитетными для FAIR.
Декартовы расстояния через периодические границы могут быть физически непригодны.

Когда метод требует, предоставьте дополнительные научные источники: preparation/
source bindings, явные настройки кадров/времени, RMSD reference/mapping/selections,
метаданные молекулярных партнёров, биологические аннотации, matching сравнения,
доступность реплик или QC/reviewer records. Для NAMD PSF/DCD нужны явные источники
элементов/времени и один связанный DCD. Не выдумывайте эти входы. См.
[Конфигурацию](configuration.md) и [Науку](science.md). Научная квалификация
реальных входов не завершена. Этот публичный снимок вычисляет RMSF/SASA; см.
[настройки и применение](configuration.md#rmsf-sasa) и
[научные определения](science.md#rmsf-sasa). Версия в метаданных остаётся 0.2.0;
сохраните публичный Git commit. Научная квалификация требуется для каждого
предполагаемого реального входа и применения. Вычисление вторичной структуры
и внутренняя подготовка PBC по-прежнему не поддерживаются. Техническое завершение и проверка
артефактов не устанавливают физическую пригодность, правильность биологии
или готовность к научной публикации.

---

[Все руководства](README.md) · [English](../eng/quickstart.md)
