# 2.58.198 (SELF-DIAG-01) — preflight STOP: не выкатывалось

**Итог: `BLOCKED` на преддеплойных обязательных проверках. Прод не тронут
(2.58.197 `25876167`), SSH не открывался, откат не требовался.**

Кандидат `454727ed` (docs `8797cd83`) + bump `78982058` собран в ветку
`release/2.58.198` и запушен, но **три обязательных теста краснеют именно
из-за кандидата** (на базе `25876167` те же тесты зелёные). Деплой не
выполнен: правило «новый RED = блок» важнее сроков.

## 1. Привязка

| Поле | Значение |
|---|---|
| База (прод) | `2587616759de31283585ffc105c91e7193c2e89e` = 2.58.197, ветка `release/2.58.197` |
| Кандидат (Reviewer Approved) | код `454727ede7a2577b80dbef1b5d9c1ce3c4a3342d`, docs `8797cd833878dcb7199dcf46ac85a01f599426eb` |
| Релизная ветка | `release/2.58.198` → `78982058119763b89fbf8e5f01cd376dfecab2c6` (bump 2.58.198), запушена в origin |
| Кумулятивно `25876167..78982058` | **139 файлов (103 M, 36 A, 0 D), +21488/−287** = 131 файл кандидата (+21457/−256) + 30 пинов (+31/−31) |
| Проверка состава | ровно 30 файлов бампа, все 62 изменённые строки — только пины версии (0 строк кода); DDL/миграций 0; новых LLM/БД/агентов/страниц/планировщиков 0; единственный новый `subprocess` — одобренный read-only git-коллектор D4 |
| DEPLOY_SOURCE | `release/2.58.198` @ `78982058` (immutable) |
| MUTABLE_WORKTREE_REQUIRED | no |
| Откат | не нужен (ничего не выкатывалось); резервная точка — `25876167` |

## 2. Обязательный преддеплойный прогон на `78982058`

| Набор | Факт | База/ожидание | Вердикт |
|---|---|---|---|
| D6 `test_checkup_contract` | 41 passed | 41 | ok |
| D6 broad 22 файла | 946 passed | 946 | ok |
| D6 16 файлов | 661 passed / 1 failed (`mca10b` 643/644) | 661 + тот же 1 | ok (pre-existing) |
| D2 5 файлов | 145 passed | 145 | ok |
| D2 6 файлов | 216 passed | 216 | ok |
| D2 `debug_config+log_ring` | 42 passed | 42 | ok |
| D2 9 файлов | 244 passed / 1 failed (`cfg03` dead knob) | 244 + тот же 1 | ok (pre-existing) |
| D4 `deploy_identity_d4c` | 22 passed | 22 | ok |
| D4 9 файлов | 366 passed | 366 | ok |
| D4 итого | 388 | 388 | ok |
| D5 `prompt_readback` | 62 passed | 62 | ok |
| D5 `self_diag_golden` | 38 passed | 38 | ok |
| D5 8 файлов | 355 passed | 355 | ok |
| D5 prompt-контракты | 56 passed, 1 skipped | 56+1s | ok |
| D3 `bundle+probes` | 80 passed | 80 | ok |
| D3 focused 35 файлов | 1325 passed | 1325 | ok |
| web/api 2 контракта | 190 passed | 190 | ok |
| **JS unit (`test_webapp_js_unit.py`)** | **44 passed / 1 FAILED** | 45 passed | **RED (кандидат)** |
| **web-wide `tests/test_web*.py` (68 файлов)** | **1536 passed / 14 failed** | **1539 / 11** | **+3 RED (кандидат)** |
| e2e `ui_inspector_exact_e2e.py` | `checks=142, failures=0` | 0 | ok |
| e2e `ui_meme_ui_fields_e2e.py` | `failures=0` | 0 | ok |
| e2e `ui_initiative_rework_e2e.py` | `failures=2` (1536, 390) | те же 2 | ok (pre-existing) |

Базовая линия подтверждена собственным прогоном в отдельном worktree
`25876167`: **11 failed / 1539 passed** (`baseline-web-wide-25876167.log`).

Чтобы отделить «новое» от «давнего», те же 14 упавших id прогнаны
изолированно в двух деревьях (`ids14-base-25876167.log` /
`ids14-cand-25882058.log`):

| Дерево | FAIL | PASS |
|---|---|---|
| база `25876167` (2.58.197) | 9 | 5 |
| кандидат `78982058` | 12 | 2 |

Перевернулись ровно три теста (F1, F2, F3 ниже); остальные 9 — давние
падения, одинаковые в обоих деревьях. `test_webapp_dm_ui::...s3_scheduler...`
в широком прогоне падает в обоих деревьях, а изолированно проходит в обоих —
это существующий флейк набора, не дефект кандидата.

## 3. Три новых RED (все воспроизводятся на `454727ed`, т.е. до бампа)

### F1. `test_webapp_js_unit.py::test_js_unit_round1025_hotfix6_lens_heartbeat_shell`
- Файл теста: `tests/js/round1025_hotfix6_lens_heartbeat_shell_test.js:200-204`.
- Суть: охранник «рендер-кадр без сети» берёт срез
  `APP_JS[indexOf('_hbDraw: function') .. indexOf('loadStatus: async function')]`
  и требует отсутствия `fetch(`/`this.api(`. Кандидат вставил между ними
  новый метод `loadSelfDiagnosis` (`web/app.js:29909`) с `this.api('/api/status/self-diagnosis'…)`.
- Продукт НЕ нарушает инвариант: `_hbDraw` (`web/app.js:29742-29762`) не
  изменён и сети не делает; `loadSelfDiagnosis` вызывается только по кнопке
  (`web/index.html:15108`), в кадре не исполняется.
- Класс: дефект тест-контракта (слишком широкий срез), внесён кандидатом.
- Воспроизведение: base `25876167` → `HOTFIX6-LENS-HEARTBEAT-SHELL-OK`,
  кандидат `454727ed` → `AssertionError: C: рендер-кадр без сети`.
- Минимальный фикс (Builder, тест-контракт): ограничить срез телом
  `_hbDraw` (конец — следующий ключ метода после `_hbDraw`), assertion не
  ослаблять.

### F2. `test_webapp_round109_ui.py::TestDescriptions::test_no_forbidden_jargon`
- `services/param_catalog.py:4100-4104`: описание новой настройки
  `flags.self_diag_repo_origin` содержит «URL», а `url` — в списке
  запрещённого жаргона (`tests/test_webapp_round109_ui.py:30-34`).
- Класс: реальный дефект owner-visible текста (описание видно в настройках).
- Минимальный фикс (Builder): переписать описание без запрещённых подстрок
  (например «адрес с логином/токеном нормализуется»). Внимание: правка
  `param_catalog.py` меняет байтовый F8-пин
  `PARAM_CATALOG_SHA256_FOLLOWUP` (`tests/test_round1025_f8_registry.py`) →
  нужен санкционированный re-pin и `tools/gen_param_registry_round1025.py --check`.

### F3. `test_webapp_evol_w14_states.py::TestUnifiedCheckboxes::test_every_native_checkbox_is_a_design_system_control`
- `web/index.html:987`: в новой матрице диагностики голый
  `<input type="checkbox">` без классов дизайн-системы (вне `ctl-check`/
  `ctl-toggle`).
- На базе `25876167` блока `diagMatrix` нет вовсе (0 вхождений) — элемент
  новый, падение кандидатское.
- Класс: реальный UI-дефект (нарушение правила «ни одного голого чекбокса»).
- Минимальный фикс (Builder): обернуть/разметить контрол дизайн-системы
  (`ctl-check`/`ctl-check__box`), затем визуальная проверка Reviewer.

## 4. Что НЕ делалось (и почему)

- SSH к проду не открывался (0 коннектов): преддеплойный прогон не пройден,
  выкатывать нечего. Прод жив: `GET /healthz` →
  `{"status":"ok","version":"2.58.197"}`, HTTP 200 (`prod-healthz-2.58.197.txt`).
- Снапшот БД не снимался (нет рестарта/записи на прод).
- `postdeploy-*`, `live-*`: не создавались — нечего постдеплойно проверять.
- Effective-config parity: снят **только baseline** (до) —
  `settings-parity-before-2.58.197.json` (sha256 по `/api/config` глобально,
  overrides-map, обоим чатам, каталогу промптов, 4 наборам версий,
  сохранённым блокам `meme-settings`; правки `chat_params`: latest
  `updated_at` 2026-11-11T12:33:23Z, 530 записей с меткой). «После» не
  снималось, т.к. выкатки не было.
- Release-гейт (`requirements_gate.py check --stage release`) не запускался:
  он проверяет факт выкатки, которой нет; финальную карту закрывает PM.

## 5. Откат / готовность

Не потребовался. Прод остался на `25876167` / `release/2.58.197` /
`APP_VERSION=2.58.197` (подтверждено HTTP `/healthz`). Команда отката на
случай будущей выкатки (для следующей попытки):

```
cd /var/www/admin_bot && git checkout -B release/2.58.197 25876167 && systemctl restart admin_bot
```

Данные не откатываются: схема 47, DDL=0.

## 6. Что дальше (конкретно)

1. Builder правит F2 и F3 (продукт/текст/UI) и F1 (тест-контракт) в новой
   ветке от `454727ed`; для F2 — санкционированный F8 re-pin.
2. Reviewer независимо проверяет новый кандидат (включая повторный прогон
   `test_webapp_js_unit.py`, `tests/test_web_*.py`, F8/cfg-03).
3. DevOps пересобирает `release/2.58.198` от нового кандидата (bump тем же
   паттерном, 30 файлов), прогоняет полный поезд, затем выкатывает.
4. Ветка `release/2.58.198 @ 78982058` — снимок отклонённого кандидата;
   после фикса её нужно пересобрать (перезапись опубликованной ветки —
   только по решению Orchestrator, я её не переписывал).

## 7. Артефакты

- `train-258198.txt` — сводка поезда на `78982058`.
- `baseline-web-wide-25876167.log` — базовая линия (11 failed / 1539 passed).
- `candidate-web-wide-258198.log` — кандидат (14 failed / 1536 passed) + тексты падений.
- `ids14-base-25876167.log`, `ids14-cand-78982058.log` — изолированный прогон 14 id в двух деревьях.
- `candidate-js-unit-258198.log` — падение F1 целиком.
- `repro-f1-hotfix6.txt` — воспроизведение F1 (база OK / кандидат RED).
- `blocked-findings.json` — машиночитаемый список F1–F3 + матрица сравнения.
- `settings-parity-before-2.58.197.json` — baseline эффективной конфигурации (sha256 поверхностей).
- `prod-healthz-2.58.197.txt` — HTTP-подтверждение живого прода.
- `harness/` — скрипты прогона/бампа/parity/деплоя (переиспользуются в следующей попытке).

## 8. Технические примечания для следующей попытки

- В релизной ветке карты требований нет (`plans/features/self-diag-01/` содержит
  только `evidence/`): `requirements-map.json`, `plan.md`, `slice-graph.json` и
  файл ревью живут на docs-линии (`master`). Release-гейт нужно запускать в
  рабочем дереве docs-линии с `--deployed-commit`.
- Прод-чекаут собирается из `release/*` (immutable), поэтому деплой карту не
  тащит — так же, как в 2.58.197.
- Housekeeping: временный baseline-worktree `25876167` снят (после восстановления
  сгенерированных тестами evidence-PNG), probe-каталог закрыт; релизный worktree
  `release/2.58.198` сохранён до пересборки ветки.
