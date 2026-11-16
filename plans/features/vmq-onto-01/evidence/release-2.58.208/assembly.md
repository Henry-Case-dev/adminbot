# VMQ-ONTO-01 / MEM-TIME — релизный кандидат `2.58.208` (без деплоя)

Дата сборки: 17.11.2026. Статус: **assembly done / REVIEW**, production не
менялся, деплоя не было, `VERIFIED` не заявляется.

- Ветка: `release/vmq-recent-window-2.58.208`
- Worktree: `C:\Users\main\.config\opencode\WorkspaceData\worktrees\c742e4de9e92c489\vmq-recent-window-8d57b3a83d31-e20af540`
  (unit `release-2.58.208`, зарегистрирован глобальным housekeeping;
  сохраняется для Reviewer/DevOps).
- База/прод/откат: `8e68e48b` (`2.58.207`, deployed 2026-11-16T12:44:18Z,
  health 200, schema 47; SMART/LLM/disk-фиксы внутри).
- Approved-источник: `5c29f377` (2 коммита: `0e47c0ec` fix, `5c29f377`
  tests). Docs-коммит `bca18c1e` чужой линии **не переносился**.
- Bump: `e4ca6c40`.

## 1. Состав кандидата

Линейно поверх `8e68e48b`, без мержей:

```
8e68e48b (2.58.207, deployed)
  -> 374fcecd fix(vmq-time): explicit recent window for get_recent_history; UTC stamps
  -> 252c99ad test(vmq-time): cover depth larger than the requested window
  -> e4ca6c40 chore(release): 2.58.208 - bump APP_VERSION и пинов версии
```

`git cherry-pick 0e47c0ec` и `5c29f377` прошли без конфликтов (автоматический
3-way merge; `services/direct_chat_service.py` — единственный файл набора,
отличавшийся между `bca18c1e` и `8e68e48b`, и его правки не пересекаются).

Кумулятивный дифф `8e68e48b..e4ca6c40`: **47 файлов, +1428/−181**:
- 17 файлов переноса: 6 продуктовых (`services/tool_router.py` +659,
  `services/tool_schemas.py`, `services/canonical_context.py`,
  `services/claim_envelope.py`, `services/direct_chat_service.py`,
  `services/runtime_probes.py`) + 11 тестовых/обновлённых
  (`tests/test_vmq_recent_window.py` — новый, 602 строки);
- 30 файлов пинов `2.58.207 → 2.58.208` (31 строка: APP_VERSION, meta,
  24 py, 4 JS в escaped-форме `2\.58\.207`, polygon ×2). BOM/CRLF сохранены,
  изменены только строки версии.

`deploy_v2.9.2.py` не изменялся. SMART/disk/LLM-файлы 2.58.207 не тронуты
(в диффе отсутствуют).

## 2. Контракт, проверенный по фактическому коду

- **Схема** (`services/tool_schemas.py:379-462`): у `get_recent_history`
  опциональный `time_window` = object c `since` (ISO-8601 UTC), `until`
  (ISO-8601 UTC), `last_seconds` (integer ≥ 1), `additionalProperties: false`;
  описание прямо требует не класть фразу периода в `query`.
- **Одна валидация** (`services/runtime_probes.py:442-502`): `parse_time_window`
  расширен необязательными `limits`/`max_seconds`; history вызывает его с
  техническим пределом 31 сутки и хвостом 24 ч (`tool_router.py:662-678`).
  Второй реализации нет — grep `def parse_time_window` даёт одну функцию.
- **Маршрутизация** (`tool_router.py:6162-6200`): кривое окно → JSON
  `status=unsupported` + `reason_code`; `time_window` без `query` →
  хронология окна; `time_window` + `query` → FTS внутри окна; `ctx.query`
  при явном окне фильтром не становится.
- **SQL до лимита** (`tool_router.py:6597-6697`): `since_ts`/`until_ts`/
  `order="time"` уходят в `search_long_term` (существующий
  `DatabaseService.search_messages_fts`, `database.py:9404-9476`), затем
  Python-пост-фильтр как страховка заглушек; `matched > limit` →
  `truncated=1`, cursor для FTS не выдаётся.
- **Статусы** (`tool_router.py:258`, `6500-6502`, `6260-6376`):
  `ok|empty_window|no_match|error`; техническая ошибка не выдаётся за пустой
  период; кривое окно — отдельный `unsupported`.
- **Нижняя/верхняя границы окна** (`tool_router.py:699-732`,
  `database.py:8580-8635`): якорь `(time_to, MAX_ID)`, нижний край
  `(time_from, 0)`, оба включительно, чтение ASC страницей `_HISTORY_PAGE_ROWS=40`.
- **Cursor v3** (`tool_router.py:475-566`, `6531-6537`): payload 15 полей
  включает `window_from/window_to`; v1/v2 → `unknown_cursor` (fail closed);
  формат подписи не менялся.
- **Одна UTC-шкала**: `canonical_context._fmt_ts` → `ДД.ММ.ГГГГ ЧЧ:ММ UTC`,
  `format_utc_timestamp` — тот же рендер, `direct_chat_service._ha_fmt_ts`
  делегирует ему, `tool_router._format_timestamp` → `… UTC`. `fact/archive`
  остаются `ММ.ГГГГ`.
- **Claim envelope legacy** (`claim_envelope.py:601-607`): regex принимает и
  «…ЧЧ:ММ UTC», и легаси «…ЧЧ:ММ»; probe: marked/legacy/month-year линии
  дают `ref` и `display_name`, «MSK» не парсится как штамп (консервативно
  уходит в имя).
- **SMART S7 не задет**: дифф `services/direct_chat_service.py` против базы —
  только импорт `format_utc_timestamp` и тело `_ha_fmt_ts`; строки
  `l1_decides`, `structural_diagnostic_research`, `_replied_message_id`,
  `structured_partial_from_result` присутствуют, S7-тесты прошли.

## 3. Инварианты (локальный in-memory probe, production не читался)

`tests-2.58.208.json` → `invariants`: `APP_VERSION=2.58.208`,
`Settings=472`, `REGISTRY=645 / GROUPS=121 / _TAB_BY_GROUP=119 / TAB_RULES=22`,
`MigrationStep=47`, `user_version=47`, `schema_migrations.max=47`,
`DDL=0`. `python tools/gen_param_registry_round1025.py --check` → `CHECK OK`.
Новых флагов/миграций/промптов/моделей/composer-механизмов нет.

## 4. Тесты

Полные числа и списки — `tests-2.58.208.json`. Кратко:
- новый набор `tests/test_vmq_recent_window.py` — **30 passed** (A–G);
- history/tools/VMQ/MEM — 294 passed, 8 failed; **те же 8 ID падают на
  `8e68e48b`** (проверено отдельным base-worktree) — pre-existing, дефект
  тестовых двойников (`_render_thread()` без kwarg `projection`);
- SMART S7/checkup/tool_loop + direct chat/L1 + transport — **368 passed**;
- disk retention/status/UI + meta/pin/deploy identity/manifest — 277 passed,
  1 failed (`test_hotfix_round1025_cachebust::test_version_bumped_and_matches_readme`);
  на базе падает тем же ID (README содержит `v2.58.174`) — pre-existing,
  в scope пинов не входит;
- изменённые тестовые швы (`test_epic65`, `evol_reply_context_integrity_seam`,
  `factcheck_deep_context_round1023`, `diagnostic_probes`,
  `native_reply_media_context_round1024`) + `test_webapp_js_unit` — **260 passed**;
- 4 JS pin-теста (`node tests/js/round1025_hotfix{7,8,9,10}…`) — 4/4 OK.

**RED на базе**: копия нового тест-файла на `8e68e48b` не собирается
(`ImportError: cannot import name '_HISTORY_WINDOW_DEFAULT_SECONDS'`), а
поведенческий probe с `time_window.last_seconds=7200` и 120 сообщениями
возвращает дефолтные 50 строк без `status/window_from/window_label`
(`feature_present=false`). На кандидате — `feature_present=true`,
`status=ok`, окно 7200, страницы 40/80 → 80/40 → 120/0, UTC-label
`16.11.2026 11:14 UTC - 16.11.2026 13:14 UTC`.

## 5. Manifest dry-run

`manifest-dry-run.json`: чистое дерево, `version=2.58.208`,
`dirty_tracked=false`, `deployed_sha=e4ca6c40` (content tip),
`previous_sha=8e68e48b`, `previous_version=2.58.207`, ветка релиза.
Перед прогоном в git-ignored `.deploy/release.json` положен локальный
снимок deployed-состояния 2.58.207 (значения из `release-2.58.207/deploy.md`);
production-файл не читался. Файл удалён после прогона.

## 6. Откат

`rollback.json`: цель `8e68e48b` (2.58.207), schema 47, DDL 0, миграций 0,
данных 0. Значения PG `models.llm_timeout=180` / `models.llm_total_budget=360`,
настроенные 2.58.207, при откате только кода сохраняются.

## 7. Ограничения (честно)

- Деплой не выполнялся; production-поведение, effective-конфигурация и
  Telegram-доставка этим артефактом не подтверждены.
- `VERIFIED` не заявляется: нужен независимый Reviewer.
- Pre-existing падения (8 history-w4, 1 cachebust/README) воспроизведены на
  базе и не исправлялись — вне scope переноса.
- Живой сценарий «что было за последние пару часов» на реальном чате не
  прогонялся: подтверждение на реальных сообщениях — задача deployed-проверки
  после деплоя (не owner-QA).
