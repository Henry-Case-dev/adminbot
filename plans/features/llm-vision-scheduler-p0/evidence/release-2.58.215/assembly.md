# Release 2.58.215 — P0 train (L1 + Vision + Scheduler), сборка REVIEW

| Поле | Значение |
|---|---|
| Дата сборки | 2026-11-18 |
| Ветка | `release/p0-2.58.215` |
| База (предыдущий релиз / откат) | `ea9f760f398a5859c5e8b981c1710b1c8bf9e787` (2.58.214, deployed) |
| Approved L1 | `fix/p0-l1-model-switch` tip `bf529e17803c8f4928b03df6ba342c81e31b461e` (код `bed0ad30` + corrective `491d6042`, `ff2d11c4b`, `b733e29ea`) |
| Approved Vision | `fix/p0-vision-download` tip `e2edd11fcdbe02b5cba709ac0d1388f7f3261d8c` (код `a4bf7b4b` поверх `32af3fe6`) |
| Approved Scheduler | `fix/p0-scheduler-loop` tip `4174cd478377257ca47c0fa1ce04629403f09837` (код `03b4358f` + r2 `491066378`) |
| Merge commits | `96f394a4e` (L1), `bfa57103b` (Vision), `0e3050042` (Scheduler) |
| Bump commit | `2b00ad035f4c19cb32f718383c429611172c0709` (2.58.214 → 2.58.215) |
| Content tip | `2b00ad035f4c19cb32f718383c429611172c0709` |
| Версия | 2.58.215 |
| Статус | **REVIEW** (не деплой, не VERIFIED) |
| Деплой | не выполнялся; production не затронут |

## 1. Порядок слияний и конфликты

`git merge --no-ff` по порядку L1 → Vision → Scheduler от `ea9f760f`.
Все три merge завершились **без конфликтов** (0 unmerged paths, `git status`
чист после каждого шага). Cherry-pick не потребовался: merge не принёс
продуктовых коммитов сверх одобренных веток.

Побайтовая сверка после слияния: для каждого из 43 файлов, изменённых тремя
ветками относительно `ea9f760f`, blob в `HEAD` совпал с blob одобренной ветки
(`git rev-parse <branch>:<file>` == `git rev-parse HEAD:<file>`) — **0
расхождений**. Пересечений по продуктовым файлам между слайсами нет; общие
файлы только в `plans/` (`param-registry-round1025.meta.md` — L1 provenance +
bump APP_VERSION, разные строки; `tests/test_round1025_f8_registry.py` — L1
переутвердил хэш, bump обновил пин версии).

## 2. Состав

| Блок | Коммиты | Файлов | Строк |
|---|---|---|---|
| L1 (`bf529e17`) | `bed0ad30`, `491d6042`, `ff2d11c4`, `b733e29e` | 24 | +4567 / −235 |
| Vision (`e2edd11f`) | `32af3fe6`, `a4bf7b4b` | 6 | +2025 / −63 |
| Scheduler (`4174cd47`) | `03b4358f`, `49106637` | 13 | +1462 / −42 |
| Bump 2.58.215 | `2b00ad035` | 30 | +31 / −31 |
| **Итого от базы до content tip** | 3 merge + 1 bump | **71** | **+8085 / −371** |

Продуктовые файлы (вне `plans/` и `docs/`), 27 шт.:

- L1: `services/agentic_events.py`, `direct_chat_service.py`, `direct_l1.py`,
  `llm_client.py`, `model_capacity.py`, `param_catalog.py` (только описания
  двух существующих ключей), `usage_events.py`;
  `tests/fixtures/round1025/f8_baseline.json`, `tests/test_round1025_f8_registry.py`,
  `tests/test_rlr_acceptance_rows.py`, новый `tests/test_p0_l1_model_switch.py`,
  новый `tools/_p0_l1_reissue_catalog.py`.
- Vision: `services/mca_vision.py`, `services/media_download.py`,
  `services/task_supervisor.py`, новый `tests/test_p0_vision_download_transport.py`.
- Scheduler: `services/dream_worker.py`, `goodmorning_scheduler.py`,
  `lore_worker.py`, `memory_backup.py`, `memory_maintenance.py`,
  `nostalgia_worker.py`, `publication_coordination.py`, `slot_claims.py`,
  `summary_scheduler.py`, `uptime_heartbeat.py`, новый
  `tests/test_p0_scheduler_loop.py`.

Не менялись: `config/settings.py` (кроме строки `APP_VERSION` bump-коммита),
`services/database.py` (DDL 0), `web/*`, `web/api/*`, `handlers/*`, composer,
prompt registry, `deploy_v2.9.2.py`.

## 3. Bump 2.58.214 → 2.58.215

Тот же набор, что 2.58.214: `config/settings.py` (APP_VERSION + changelog
«Prior 2.58.214»), `plans/docs/param-registry-round1025.meta.md`, 24 py-файла
и 4 JS-пина в escaped-виде `2\.58\.215` — **30 замен / 29 файлов**, polygon — 2.
BOM/CRLF сохранены (правки байтовые; `git diff --stat` 31/31, без перезаписи
целых файлов). `tools/gen_param_registry_round1025.py --check` → OK
(реестр 645, TSV/map идемпотентны), повторный `emit` на content tip изменил
только строку `HEAD (short)` в meta (провенанс).

## 4. Инварианты на content tip (измерено)

| Инвариант | Значение |
|---|---|
| `APP_VERSION` | 2.58.215 |
| Каталог | REGISTRY **645**, GROUPS **121**, `_TAB_BY_GROUP` **119**, TAB_RULES **22** |
| Settings | **472** поля |
| Миграции | MigrationStep **47**, max **47**, уникальные/непрерывные/сортированные |
| Схема | target `user_version` **47**, DDL **0** (`services/database.py` не изменён) |
| Новые флаги/миграции/endpoint'ы/composer/промпты/модели | нет |
| `tests/fixtures` drift guard | обновлён L1 осознанно (только описания двух ключей) |

## 5. Проверки

Полный набор и фактические числа — `tests-2.58.215.json`. Кратко: mandatory
**386**, L1 **49**, Vision **28**, Scheduler **12**, targeted scheduler **298**,
L1 consumers **374**, Vision focus **189/1**, JS **117/4** (те же 4
pre-existing, что на 2.58.214), `node --check web/app.js` OK,
`git diff --check` OK, `gen_param_registry --check` OK, сквозной smoke без сети
(L1 route / Vision cloud fallback / scheduler gap 547 → 16 мс). Мутации не
перезапускались — ссылки и SHA в `limitations.md`.

## 6. Манифест и откат

- `manifest-dry-run.json`: `version=2.58.215`, `deployed_sha=2b00ad03…`
  (content tip), `previous_sha=ea9f760f…`, `previous_version=2.58.214`,
  `release_branch=release/p0-2.58.215`, `dirty_tracked=false`. Вход
  `.deploy/release.json` (реконструкция документированного состояния 2.58.214)
  удалён после прогона; в дереве не осталось untracked-файлов.
- `rollback.json`: цель `ea9f760f` (2.58.214), schema 47, DDL 0, данные не
  сбрасываются.

## 7. Честные границы

Реальный GLM-вызов, Vision live/9-asset re-drive и postdeploy-наблюдения —
только после деплоя (`limitations.md`); этот артефакт их не имитирует.
