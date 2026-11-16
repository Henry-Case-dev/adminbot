# SMART-CORRECTIVE-01 — релизный кандидат `2.58.207` на базе deployed `2.58.206`

Дата сборки: 17.11.2026. Статус: **assembly done / REVIEW**; деплой не
выполнялся, production не трогался, VERIFIED не заявляется.

## 1. Причина пересборки (lineage correction)

Первая сборка поезда SMART была сделана от `bca18c1e` (2.58.205). Production
уже работает на `6a878fec` (2.58.206: disk retention keep=2 + пороги
«Статуса» 85/90), поэтому такая ветка при деплое **откатила бы disk-fix**.
Сборка остановлена до push/деплоя; новая ветка собрана от deployed
`6a878fec`.

- База/прод/откат: `6a878fec` (`2.58.206`, schema 47, DDL 0).
- Ветка: `release/smart-corrective-2.58.207`.
- Worktree:
  `C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\smart-corrective-01-0097aecc4a7a-b4585c29`
  (unit `smart-release-2.58.207`, зарегистрирован глобальным
  `workflow_housekeeping.py`; сохраняется для Reviewer/DevOps).
- Предыдущий релиз: `bca18c1e` (`2.58.205`).

## 2. Состав (линейная история от базы)

```
6a878fec (2.58.206, deployed)
  -> 67828dec  cherry-pick 612e6518  S7: ответ на доставленный отчёт
  -> 13b248c7  cherry-pick b9f5ec88  S7 review
  -> de92f0a5  cherry-pick 98338292  checkup S1-S6, S8
  -> 3e447956  cherry-pick a9a32b8b  checkup evidence
  -> da434d70  cherry-pick 6c2ba4a4  checkup F1/F1b/F2
  -> c21a7fe0  cherry-pick d47a0cda  checkup F2 marker
  -> 38b56cd5  cherry-pick bfa66930  S7 R1: пустые результаты
  -> 8e87f883  cherry-pick c292a1cf  LLM transport
  -> aea3c640  cherry-pick 25df4f9e  transport evidence
  -> 8eed2f92  cherry-pick bf10e3f0  transport catalog re-pin
  -> 60cede96  cherry-pick 411f8686  transport review F1
  -> 1519ec04  bump 2.58.206 -> 2.58.207
```

12 коммитов, 0 merge-коммитов. Все delta-коммиты перенесены
`git cherry-pick`; S7 `bfa66930` (ребёнок `b9f5ec88`) перенесён после
checkup-диапазона и чисто авто-смёржен в `services/tool_loop.py`.

Cumulative diff `6a878fec..1519ec04` (content tip до evidence-коммита):

```
70 files changed, 4581 insertions(+), 267 deletions(-)
```

Из них SMART-дельты до bump (`6a878fec..60cede96`) — 42 файла,
+4550/−236; bump добавляет 30 файлов / 31 строку (2 файла пересекаются:
`config/settings.py`, `plans/docs/param-registry-round1025.meta.md`).

## 3. Конфликты и разрешения

| Файл | Причина | Разрешение |
|---|---|---|
| `plans/docs/param-registry-round1025.meta.md` | `bf10e3f0` менял `HEAD (short)` на линии 2.58.205; база уже несла bump 2.58.206 | Оставлены base-строки (`APP_VERSION 2.58.206`, `HEAD 5bdb80cb`), затем bump выставил `APP_VERSION 2.58.207`; transport TSV/sha re-pin сохранён |

`web/app.js`, `web/index.html`, `web/static/app.css`, `config/settings.py`,
`tests/test_webapp_js_unit.py`, `tests/test_round1025_f8_registry.py`
авто-смёржены без конфликтов. Сохранение обоих наборов проверено реально,
не только отсутствием маркеров:

- disk: `DEPLOY_BACKUP_KEEP = 2`, sidecar/WAL/SHM, CLI cleanup;
  `STATUS_DISK_WARN_PERCENT = 85`, `STATUS_DISK_CRIT_PERCENT = 90`,
  `ctlDiskAlert`/`ctlDiskProg`, `status-disk`/`aria-live` разметка и CSS;
- transport: `LLM_TIMEOUT=180.0`, `LLM_TOTAL_BUDGET=360.0`,
  `LLM_GUARD_MIGRATIONS` (30→180, 60→360, custom preserve),
  `prov_policy` первой видимой группой, `llm_guard` в advanced;
- checkup/S7: `research_requested`, `structural_diagnostic_research`,
  `report_sent_partial`/`report_sent_unresearched`, rich-Markdown;
- `tests/test_round1025_f8_registry.py` несёт **оба** re-pin: routes-hash
  checkup S5 и param-catalog hash transport.

## 4. Bump `2.58.206` -> `2.58.207`

По шаблону `ebd0160b`:

- `config/settings.py`: `APP_VERSION = "2.58.207"` + новая релизная заметка,
  полный `Prior 2.58.206` сохранён; BOM=true, CRLF сохранены,
  `git diff --check` = 0;
- `plans/docs/param-registry-round1025.meta.md`: `APP_VERSION: 2.58.207`;
- 24 py-файла пинов (`test_webapp_round1026_polygon.py` — 2 пина);
- 4 JS-пина (`/APP_VERSION = "2\.58\.207"/`);
- всего **30 файлов / 31 строка**.

## 5. Статические проверки

- `APP_VERSION` импортируется = **2.58.207**.
- DDL = **0**: в diff `6a878fec..HEAD` по `services/` и `config/` нет
  `CREATE TABLE`, `ALTER TABLE`, `DROP TABLE`, `CREATE INDEX`, `DROP INDEX`,
  `PRAGMA user_version`, `executescript`.
- `MigrationStep(` в `services/database.py`: **47** на базе и **47** на
  вершине; `_SCHEMA_VERSION_SEMANTIC_SCHEDULE = 47`.
- Свежая БД (`DatabaseService.initialize()` на дереве 2.58.207):
  `user_version=47`, `MigrationStep=47`, таблиц **101**.
- Каталог/настройки: REGISTRY **645** / GROUPS **121** /
  `_TAB_BY_GROUP` **119** / TAB_RULES **22** / Settings fields **472**
  (как на базе; transport менял только описания/подписи).
- Новых флагов, миграций БД, моделей, агентов и планировщиков нет.
- `deploy_v2.9.2.py` не тронут.

## 6. Тесты (детали — `tests-2.58.207.json`)

| Набор | Объём | Результат |
|---|---|---|
| SMART core (checkup + S7 + checkup contract/handlers/logs + tool_loop) | 6 файлов | **185 passed / 0 failed** |
| SMART transport focused | 8 файлов | **243 passed / 0 failed** |
| Transport affected (llm_client/hot migration/supervisor/embedding/и т.д.) | 9 файлов | **306 passed / 0 failed** |
| SMART affected (direct chat/L1/checkup service/prompts) | 9 файлов | **374 passed / 1 failed** (pre-existing) |
| Disk retention focused | 4 файла | **112 passed / 0 failed** |
| Status UI pytest | 15 файлов | **411 passed / 0 failed** |
| JS status UI + version pins (node) | 11 скриптов | **11 OK / 0 failed** |
| Pin-guard (24 py-файла волны bump) | 860 тестов | **856 passed / 4 failed** (pre-existing) |
| Broad `-k "disk or retention or backup or status or release_manifest or deploy_identity"` | 781 тест | **781 passed / 0 failed** |

Pre-existing падения воспроизведены на чистом `6a878fec` (detached
worktree, удалён после прогона) теми же node-id и assert-сообщениями:

```
tests/test_tool_coordinator_round1026.py::TestBounds::test_forbidden_paths_out_of_diff
tests/test_tool_coordinator_round1026.py::TestBounds::test_canon_twelve_tools
tests/test_unified_image_request_round1026.py::TestToolDescriptionU21::test_canon_unchanged
tests/test_unified_image_request_round1026.py::TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline
# 4 failed на базе, 856 passed / 4 failed на кандидате
```

Ещё одно pre-existing падение вне pin-guard:

```
tests/test_direct_l1_corrective_r1.py::test_build_l1_context_bot_replies_caps_and_limit
# кандидат: 1 failed, 374 passed; база 6a878fec: 1 failed, 11 passed (тот же assert)
```

## 7. UI (Playwright; route-stub)

- Disk: `capture_p0_disk_status_ui.py` — **8 сценариев / 0 ошибок**
  (desktop 1280×800 и mobile 390×844; 92 crit, 86 warn, 50 ok, unknown;
  бар/текст/aria-live/console errors).
- Transport: `tools/ui_p0_llm_guard_e2e.py` — `{"ok": true, "failures": []}`
  на 1280×800 и 390×844: `prov_policy` видима первой, `llm_guard` внутри
  advanced, `details.open=false`, 3 подписи, 3 видимых поля, overflow=false.
- Оба прогона на дереве 2.58.207 дали **идентичный** check-JSON
  соответствующим прогонам 2.58.206-slice; отличались только байты PNG
  (рендеринг), tracked-снимки восстановлены. Harness использует route-stub
  `/api/*` и mock Telegram SDK — это не live TMA.

## 8. Manifest dry-run

На content tip `1519ec04` (`manifest-dry-run.json`):

```json
{
  "deployed_at": "2026-11-16T12:08:14.219052Z",
  "deployed_sha": "1519ec04c17e8778ae4d5867b09713a7b0947f58",
  "dirty_tracked": false,
  "effect": "deploy",
  "previous_sha": null,
  "previous_version": null,
  "release_branch": "release/smart-corrective-2.58.207",
  "schema": 1,
  "version": "2.58.207"
}
```

Evidence-коммит меняет tip только метаданными (файл не может содержать SHA
коммита, который его добавляет); production при деплое запишет фактический
deployed SHA сам.

## 9. Откат

- Цель: `6a878fec` (`2.58.206`), schema 47, DDL=0.
- Данные: `migrate_llm_guard_defaults` может заменить PG-значения
  `models.llm_timeout` 30→180 и `models.llm_total_budget` 60→360 **только**
  если они точно равны прежним дефолтам; кастом владельца сохраняется.
  После отката кода сохранённые 180/360 остаются действующим hot config —
  для полного возврата старых дефолтов их нужно явно выставить 30/60.
- Disk-retention удаления, уже выполненные 2.58.206, необратимы; этот релиз
  нового поведения удаления не добавляет.

## 10. Ограничения / что не проверено

- Деплой не выполнялся; production effective-state, `/healthz`, live TMA и
  реальные LLM-вызовы не проверялись.
- Playwright — harness с route-stub `/api/*` и mock Telegram SDK.
- 4 pin-guard падения и direct_l1 line-cap падение — pre-existing, вне scope,
  не исправлялись.
- Внешние LLM/сетевые сценарии в broad-выборку не входили.

## 11. Пометка о версии в transport-текстах

Transport-slice готовился как кандидат `2.58.206` на `bca18c1e`; поэтому его
исходные комментарии/имя evidence-файла содержат «2.58.206» как метку
черновика. Фактический релиз — **2.58.207**: `APP_VERSION`, meta и все пины
равны 2.58.207, ни один тест не опирается на прозу. Переименование
исторических evidence-файлов не выполнялось, чтобы не терять provenance.

## 12. Housekeeping

- Worktree и unit зарегистрированы; base-check worktree `6a878fec` создан
  временно, проверен чистым и удалён без `--force`. Ретеншн worktree
  зафиксирован в `retention.json` для Reviewer/DevOps (unit-check).
- Прогонные логи и одноразовые скрипты — в tool-owned run
  `...\runs\c742e4de9e92c489\smart-corrective-01-0097aecc4a7a\temp-2af220cd55`,
  закрывается после сдачи evidence.
- Прогон status-ui pytest перезаписывает tracked PNG evidence
  (`plans/features/evol/audit/evidence/*`); изменения восстановлены,
  в кандидат не входят (известное поведение тестов, backlog).
