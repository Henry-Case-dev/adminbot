# P0 admin-toggle-save — corrective evidence (28.10.2026)

Кандидат: ветка `task/admin-toggle-save`, worktree `C:\Code\Python\adminbot-wt-tgl`,
база `release/p0-2026-10-26` @ tip `9261565d` (deployed 2.58.139 = `95e6c7c9` + docs).
Бриф называл базой `c987a825` — фактический tip ветки уходит дальше (fcpost-фиксы,
регенерация реестра `820d443f`, bump 2.58.139 `95e6c7c9`, docs `9261565d`); взят
фактический tip, чтобы фикс строился против кода задеплоенной линии.

## 1. Root cause (файл:строка, воспроизведён локально на РЕАЛЬНОМ UI)

Точная цепочка отказа владельца (Модули → Умный кэш → тумблер «Exact Match
Cache» → тост «Сохранено 0 из 1; не сохранено: Exact Match Cache»):

1. UI: тумблер вкладки smart_cache — автосейв `saveConfigItem` → `persistItems`
   → `POST /api/config` (web/app.js:17051/16842; тост формата «Сохранено N из M»
   — только `saveModalEdits`, app.js:10430 — т.е. в момент скриншота автосейв
   уже провалился и элемент остался dirty).
2. Сервер: chat-путь `post_config` → `set_chat_params` со строгим optimistic-
   токеном; несовпадение `updated_at` → `ChatParamsConflict` → 409
   (web/api/routes.py:700-713 база; services/chat_params.py:452-475, SQL
   `UPDATE ... WHERE chat_id=$1 AND updated_at=$3::timestamptz` :84-86).
3. Почему токен систематически устаревает в проде: `chat_params` пишут
   конкурирующие потоки (гейты модулей feature_gates.set_feature_gate, speech/
   persona/cover/oversight правки, вторая вкладка TMA на другом устройстве);
   кроме того `set_gates_opt_in` (chat_params.py:500) сдвигает
   `chat_profiles.updated_at` вообще БЕЗ NOTIFY → кэш `ChatParamsCache`
   (TTL 120 c) отдаёт устаревший токен повторно.
4. Recovery в UI (app.js persistItems §2.3): один re-read + сравнение — сервер
   (OFF) ≠ черновик (ON) → `stillFailed` → sticky-бар; повторное «Сохранить
   изменения» ловит 409/устаревший токен снова → тост владельца.

Воспроизведение: реальный сервер (uvicorn + create_app + реальный
chat_params/ConfigCache поверх sqlite-shim) + реальный web/index.html + app.js
через Playwright (пробник `OPENCODE_WORKFLOW_SCRATCH/tgl-ui-probe/server_probe.py`).
Фаза «конкурентная запись между loadConfig и тумблом» на базе:
`POST /api/config → 409 {"code":"conflict",...}`, `saveResult:false`,
`dirty:["flags.smart_cache_enabled"]` — ровно прод-симптом. После фикса:
та же фаза → 200, тумблер применён, `dirty:[]`.

Второй триггер того же симптома: групповой чат без строки `chat_profiles`
(join-событие потеряно) → `ChatParamsConflict(current=None)` → вечный 409;
F-14 ensure был только у DM-ветки (routes.py:637-639).

Read-side (аудит, п.2 ТЗ): `SmartCache.get()` гейтился ТОЛЬКО на
`settings.SMART_CACHE_ENABLED` (smart_cache.py:316-318 база), тогда как
`set()`/_sweep_ttl/get_dedup — на hot (T-619). Прод: env-дефолт False →
тумблер ON включал запись кэша (handlers search/youtube/web: set), но get()
никогда не отдавал → тумблер был полу-декоративным (писал, не отдавал).

## 2. Фикс (наименьший слой, владеющий причиной — write-path)

- `web/api/routes.py:609` — `_write_chat_overrides_with_retry`: одна
  ограниченная попытка на `ChatParamsConflict`. (a) профиль отсутствует
  (current=None) → `ensure_scope_profile(dm=False)` + запись (групповой путь
  получил то же ленивое создание, что DM F-14); (b) токен устарел → перечитать
  СВЕЖИЙ root (напрямую PG, мимо кэша), смержить патч поверх, записать с
  `expected_updated_at=None`. Права/типизация проверены ДО записи и не зависят
  от value_overrides (матрица — perm_overrides). Первая попытка сохраняет
  честный optimistic-протокол (включая D-409-1 idempotent short-circuit);
  структурный 409 наружу остаётся прежним.
- `services/chat_params.py:506` — `set_gates_opt_in` посылает NOTIFY
  (`chat_params_updated`), как весь канон write-path (fail-open).
- `services/smart_cache.py:316` — `get()` переведён на hot-рубильник + hot-TTL
  (`flags.smart_cache_enabled` / `limits.smart_cache_ttl_seconds`, settings —
  дефолт-фолбэк; аварийный env-рубильник R51-3 сохранён). Паттерн тот же, что
  у get_dedup/_sweep_ttl.

Trade-off (осознанный): при конкурентной правке ОДНОГО И ТОГО ЖЕ ключа двумя
админ-сессиями побеждает последняя (LWW на пересекающихся ключах после
перечитанного merge); чужие ключи не теряются никогда (база merge свежая).
Для админ-UI владельца в 1–2 чатах это восстанавливает первичную функцию
(сохранение тумблера) вместо систематического отказа.

## 3. Аудит-матрица: ВСЕ bool-тумблеры `flags_*` (106 шт., каталог 9261565d)

Метод: реальный сервер-харнесс → на КАЖДЫЙ флаг `POST /api/config` глобально
(→200, `hot.get(pg_key)` отражает) и chat-scope (→200, override в
chat_profiles применён); потребители — grep pg_key/settings_field по
services/+handlers/+filters/+bot.py/SmartModule (без param_catalog).
Артефакты: `OPENCODE_WORKFLOW_SCRATCH/tgl-ui-probe/flags_audit.json` (106 строк),
`flags_consumers.json`.

| Классификация | Кол-во | Примечание |
|---|---|---|
| WORKS (save 200 global+chat, hot отражает, override применяется, потребитель есть) | 106/106 | write-path общий — защита от stale-token теперь у всех per-chat флагов |
| BROKEN-fixed в этой полосе | `flags.smart_cache_enabled` | (a) save — root-cause фикс выше; (b) `get()` не читал hot → кэш не отдавал ответы (search/youtube/web) — починено |
| BROKEN-followup | 0 | не найдено |

Потребители `flags.smart_cache_enabled` (живая цепочка подтверждена):
`handlers/search.py:140-168`, `handlers/youtube.py:1226-1293`,
`handlers/web.py:171-197` (get/set), `services/smart_cache.py`
(set/_sweep_ttl/get — hot после фикса).

## 4. Тесты

Новый `tests/test_p0_admin_cache_toggle_save.py` — 9 тестов:
- TMA-флоу: глобальный roundtrip; chat-scope roundtrip (fake + РЕАЛЬНЫЙ
  chat_params поверх sqlite); OFF→ON→OFF с токенами из ответов.
- Эффективный рантайм: hot после сохранения, `SmartCache._active`,
  чтение UI (chat_source='chat').
- Root-cause регрессии (RED на базе `9261565d` — проверено stash-прогоном,
  3/3 FAILED; GREEN после фикса): stale-token → 200 + merge сохраняет
  конкурентную правку; отсутствующий профиль группы → ensure + 200;
  `SmartCache.get` следует hot в обе стороны.

Регрессии затронутых швов (итог: 358 passed):
`test_webapp_api` (63), `test_budget_overrides_merge_round1024`,
`test_smart_cache`, `test_settings_worker_sync_round1018`,
`test_settings_helpers`, `test_p0_persistfix_speech_chat_scope`,
`test_round1025_f8_registry`, `test_mca23_planned_vs_actual`,
`test_webapp_gates_api`, `test_dm_access`, `test_global_config_optimistic_round1025`,
`test_asap3_acceptance`, `test_104_backend_additions`,
`test_asap7_cover_preview/readpath`, `test_mca10b/mca12/mca17c` (пины F11),
`test_p0_prompts_core` (factory fingerprint pin), `test_mca10a_random_source_block_c_round1037`,
`test_soul1_registry_completeness`.

Обновлены по конвенции (пин-гигиена):
- `ROUTES_SHA256_F11` (канон test_round1025_f8_registry.py + дубль в
  test_mca23) → `b63dab2a47117c6805…` — byte-freeze routes.py переутверждён
  осознанно (L-F11S-1): Δ routes=0, новых endpoint'ов нет, RBAC/DDL не тронуты.
- `test_budget_overrides_merge_round1024 (e)`: strict-409-на-любой-токен
  был пином корневой причины бага → контракт обновлён (stale-token → 200
  со свежим merge), актуальный токен → 200.

Гварды: `tools/gen_param_registry_round1025.py --check` → OK (586==REGISTRY);
`compileall services+web changed files` → rc=0. Каталог НЕ менялся.

Предварительные падения на БАЗЕ (не от этой полосы, задокументированы для
владельца/PM): `test_soul1_registry_completeness` ×2 (пины канонов персоны vs
слияние SOUL/nost), `test_mca10a_random_source_block_c_round1037` ×2
(Settings 465 vs ожидание 466 — след fcpost-удаления settings-поля на линии
релиза). Воспроизведены stash-прогоном на чистом `9261565d`.

## 5. Live/UI-доказательство

Playwright + реальный UI (real app.js, реальный сервер, TMA initData-инъекция):
- Глобальный scope: тумблер → POST 200, автосейв, dirty=0 (PROBE-2).
- Chat-scope: тумблер → POST 200, override применён, dirty=0 (PROBE-4).
- Конфликт-фаза (конкурентная запись бота между loadConfig и тумблом) — на
  базе 409/ошибка, после фикса 200/применено/dirty=0 (PROBE-5).
Реальный владелец-чек на устройстве — не требуется для инженерной приёмки
(поведение воспроизведено и починено end-to-end на реальном UI-коде); остаётся
добровольным наблюдением владельца.
