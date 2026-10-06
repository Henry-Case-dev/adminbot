# deployment.md — mca-19-image-understanding (prod 2.58.63)

**Статус: FAILED (T-5126) → VERIFIED (T-5126b, 06.10.2026)** — код-деплой и миграция v32 чистые; блокер T-5126 (`NameError: _aps`) устранён дельтой `d298f1f`, vision worker тикает на проде (детали §8).

## 1. Коммиты и деплой

- **feat `35f0dbc`** (132 файла, +17319/−8199): runtime/tests + bump 2.58.62→2.58.63 + release-пины + фичевый пакет планов (spec/ADR-1028-19/threat/tasks/requirements-map/evidence/**review** + WTH-манифест + scanner-аудит + `plans/docs/mca-round1027-arch-frames.md` §1.2.8). Биндинг — манифест итер.2 122 файла (`plans/reports/mca19_wth_manifest_review.txt`, HEAD `2dfb8c4`); вне манифеста добавлены release-owned: `README.md` (header), 4 py-пина (scope_selector/design_tokens/f6/hotfix6), 4 js-харнесса, `tools/_t5126_release_bump.py` (тул бампа — прецедент `_mca18_release_bump.py`), `plans/features/mca-19-image-understanding/review.md`, `plans/reports/mca19_scanner_audit.md`. В коммит НЕ включены: workflow_state/backlog/metrics/ARCHITECTURE/MEMORY/current_task, мусор (.playwright-mcp/, node_modules/, package*.json, tools/_ui_asap43_*, tools/_mca18_*, tools/_mca19_wave2_*, plans/verification_cache.json, deploy_commands.txt — содержит секреты).
- Push: `2dfb8c4..35f0dbc master -> master` (ff, без force); прод `git pull --ff-only` чистый: `4c70477 → 35f0dbc`.
- deploy-doc: этот файл (коммит поверх feat).

## 2. Preflight (биндинг/бамп)

- **Per-file identity gate**: все 122 файла манифеста против дерева — **121/121 кандидатских byte-identical** + 1 самореферентная запись самоманифеста (хеш файла в самом файле — расходится, документировано Scanner'ом). `MANIFEST_SHA256 da861426…287af028a17` воспроизведён из записей манифеста байт-в-байт (122 строки, file order, LF). Продуктового дрейфа нет → гейт PASS.
- **Бамп-тул** (`_t5126_release_bump.py`, 29 файлов): APP_VERSION `2.58.62→2.58.63`, README header, F8 meta-pin, **23 py-пина** (19 в манифесте + 4 release-owned), **4 js-харнесса** (`2\.58\.62→2\.58\.63`). 0 хвостов (проверено grep'ом); исторические упоминания 2.58.62 в docstring'ах сервисов (OFF-parity baseline) не тронуты.
- **Тесты**: focused mca-19 (8 файлов) + summary_handlers — **167 passed**; js — **59/59 OK**; полный набор — **12202 passed / 5 failed / 12207 collected**: 3 детерминированных pre-known (status-pin `test_webapp_nav_disclosure_ui` + `test_webapp_status_control`, `test_tool_loop::test_query_chat_memory_count_reaches_model` backlog mca-15) + 2 экземпляра документированного mca-09-флейка (`test_mca09_intents_block_e`: pollution + `test_candidate_ready_defers_intent_backoff`; изолированный перепрогон файла **15/15 ×2**, падает рандомный тест за прогон — ротация подтверждена). **0 новых падений**.

## 3. Прод-факты

- До деплоя (верифицировано): prod HEAD `4c70477` (2.58.62), `/healthz` 200 `{"status":"ok","version":"2.58.62"}`, PID 4020624, NRestarts=0; БД `user_version` 31, таблиц 116, book `(31, self_model)` ×1; env MCA_VISION-оверрайдов **0**.
- **Рестарт #1** 03:51:19 UTC → PID **4097315**, NRestarts=0, ExecMainStatus=0. **Бэкап-guard (mca-14, fail-closed):** `pre_migration_20261006_035238.db` **1.32 GB** (старт копии 03:52:38, «pre-migration copy created + read-back ok | target_version=31» в 03:55:14 — ~2.5 мин на 1.4 GB, диск VPS). Ротация guard-копии mca-18 (`pre_migration_20261005_211627.db`) — ожидаемое keep-newest.
- **Миграция v32 применена ровно один раз** (03:55:14–03:56:27, пошаговый журнал): `smart_messages` +10 nullable Origin-колонок (`sender_chat_id`→`media_group_id`), CREATE `mca_media_assets` + `mca_media_analyses` (CHECK), idx (`chat_tg`/`content_hash`/`file_unique`/`analyses_scope_status`); «migration v32 applied | media_vision». Polling 03:56:43.
- **Состояние после:** `user_version` **32**, таблиц **118** (116+2), `schema_migrations` `(32, media_vision)` **×1**, `smart_messages` 31→**41** колонка, media-таблицы 0 строк.
- **Рестарт #2 (идемпотентность)** 04:00:44 UTC → PID **4099844**, NRestarts=0: в журнале миграций/guard-копий **0** — no-op; polling 04:01.
- `/healthz` **200 `{"status":"ok","version":"2.58.63"}`** ×2; `/api/health` **200** ×2; «database is locked» **0**; ERROR/CRITICAL/Traceback после рестарта #2 — **0**.
- **Данные целы** (pre→post): `smart_messages` 1,999,436=1,999,436, `mca_bot_outputs` 96=96, `graph_facts` 16,273=16,273, `mca_random_draws` 13=13, `summary_runs` 18=18, `mca_trait_observations` 10=10, `mca_behavior_rules` 7=7 (`mca_events` 12,124→12,130, `task_jobs` 663→664 — активность бутов). Vision-очереди не накопились: assets/analyses 0 строк.
- PG no-op (тело v32 SQLite-only). **R17**: секретов в журналах/отчёте 0 (прод-.env не копировался; `deploy_commands.txt` untracked).

## 4. [BLOCKER] Vision worker не стартует — критический путь mca-19

- Бут #1, 03:56:31: `WARNING [mca-19] vision worker init failed — fail-open` → **`NameError: name '_aps' is not defined`** — `services/mca_vision.py:1692` (`VisionMediaWorker.start()`), причина: `import apscheduler.schedulers.asyncio as _aps` находится внутри `__init__` (`mca_vision.py:1672`) — function-local имя не видно в `start()`. Точка входа: `bot.py:807 _vision_worker.start()`.
- Следствие при K1 ON: воркер не тикает, intake/enqueue живут → тихий рост durable-очереди без потребителя; распознавание изображений не функционирует. **Продуктовое поведение ≠ контракту.** Тесты реальный `start()` не покрывают (focused 167 зелёные — gap: нет start-smoke реального пути).
- Классификация: **продуктовый дефект кандидата** (не deploy-механика) → возврат Builder + Reviewer.

## 5. Стабилизация (документированный soft-rollback)

- 03:59 UTC: в прод-`.env` добавлен `MCA_VISION_ENABLED=false` (K1; бэкап `.env.t5126.bak`) + рестарт #2. Журнал: «[vision] worker не запущен: K1 OFF» — чисто, без NameError/Traceback; intake/enqueue/tool/чтение контекста OFF (fail-режимы Scanner: K1 OFF ⇒ parity 2.58.62). K2–K4 оверрайдов нет, при K1 OFF инертны.
- **Текущее состояние прода:** код 2.58.63 (HEAD `35f0dbc`), v32 применена (аддитивна, инертна при OFF), бот здоров, vision-функциональность = бит-в-бит 2.58.62. Окно «K1 ON с мёртвым воркером»: 03:56:43–03:59 (очередь не накопилась — 4 UTC, assets/analyses 0).

## 6. Rollback

- **Soft (активирован):** `MCA_VISION_ENABLED=false` в прод-`.env` — vision-оси бит-в-бит 2.58.62; v32-объекты инертны.
- **Cold:** `git revert 35f0dbc` (или checkout `4c70477` = 2.58.62) — v32 строго аддитивна: v31-код v32-объекты не читает, реестр mca-14 пропускает применённые шаги; restore из `pre_migration_20261006_035238.db` (1.32 GB, app root, root-owned) — только R18-авария. Guard-полку не удалять.
- **Recovery (минимальный корректный):** Builder — фикс скоупа импорта (`_aps`: перенести import в `start()` либо на module-level) + start-smoke-регрессия (реальный `VisionMediaWorker.start()` при K1 ON, без мока планировщика) → review delta (манифест ±2 файла) → повторный деплой T-5126b: миграция НЕ повторяется (v32 уже применена, идемпотентна), на проде снять env-оверрайд K1, рестарт, healthz + vision worker started в журнале.

## 7. Notes

- **Полный pytest — средозависимый teardown-ханг** (leaked aiosqlite, backlog #121): однопроцессный полный прогон на этой машине 06.10 недостижим — 2/2 ханга на кандидате и 1/1 на **чистом HEAD `2dfb8c4`** (worktree, тот же venv) в одном месте: `tests/test_summary_memory.py::db` teardown, `run_until_complete(close())`, IOCP-select не прерывается, pytest-timeout(60s, thread) не доставляет исключение. Воспроизведено → **не регресс кандидата**. Полный набор выполнен **тремя сегментами** в алфавитном порядке файлов (4625+5062+2515, тот же тест-сет, тот же порядок внутри сегментов) — сегментный учёт красных сошёлся с документированным. Рекомендация в backlog: изолировать teardown (закрытие loop'а вне GIL-зависимого select) либо пороговое разбиение.
- mca-09-флейк: в mca-18 числился 1 red («pollution mca-09↔17a standalone-green»); здесь +1 экземпляр той же семьи (`test_candidate_ready_defers_intent_backoff`, изолированно зелёный ×2) — та же запись backlog #121, не новый дефект.
- Incidental: диск прод-ВМ 75% (5.7 GB свободно), guard-копия 1.32 GB — наблюдать; rotation работает.
- Live-приёмка изображений (T-5127, владелец) — **не заявлять и невозможна** до recovery: worker OFF.
- Служебное: `/tmp/t5126_dbcheck.py` на проде — одноразовый инспектор (read-only URI); preflight-тулы `_t5126_preflight_manifest.py`/`_t5126_recipe_variants.py`/`_t5126_commit_plan.py` остались untracked в дереве разработки.

## 8. T-5126b — повторный деплой: VERIFIED (серверное UTC 06.10.2026 ~11:07–11:50)

**Маршрут инцидента:** T-5126 FAILED (`NameError: _aps`, §4) → стабилизация K1 OFF (§5) → Builder-фикс + start-smoke-регрессия (B5) → дельта-ревью «к T-5126b ДА» (манифест `8a95bb46…`, FILE_COUNT 5, хеши `d6032dc0…`/`776e4f83…`) → T-5126b.

**Коммит/деплой-сорс:** `d298f1f` fix(vision) — module-level `AsyncIOScheduler` import (mca_vision.py:45, прецедент dream/lore worker), мёртвый function-local импорт из `__init__` удалён, `start():1692` — модульное имя, K1-гейт не тронут; +2 start-smoke теста реального прод-пути (всего в файле 16, прогон 2/2 selected + focused 116 у Reviewer). Push `ff95669..d298f1f` (ff, без force); прод `git pull --ff-only` 11:07 UTC: `ff95669 → d298f1f`, «Already up to date» при повторе; sha256 `services/mca_vision.py` на проде = **`d6032dc0f18516f3…`** (байт-в-байт с манифестом). Миграция v32 **не повторялась**: book `(32, media_vision)` ×1, `user_version` 32.

**Оверрайд:** строка `MCA_VISION_ENABLED=false` удалена из прод-.env (бэкап `.env.t5126b.bak`); после — **0 `MCA_VISION_*` оверрайдов**, все 4 KS default ON.

**Рестарты/воркер:** служебных рестартов три (11:31:16 / 11:37:11 / 11:40:25 UTC — два первых из-за сбоев моего деплой-тула, не прода; каждый чистый): в каждом буте **`[vision] media worker started | tick=5s`**; «K1 OFF»-строк — **0**; текущий PID **4190707**, NRestarts=0, ExecMainStatus=0, ActiveEnter 11:40:06 UTC; **70 тиков** `VisionMediaWorker._tick … executed successfully` за первые ~6.5 мин (интервал 5 c подтверждён журналом); polling поднимался в каждом буте.

**Health:** `/healthz` **200 `{"status":"ok","version":"2.58.63"}`** ×2 (подряд, +6 c); во время бута `TRY1=502 → TRY2=200` (подъём <20 c); `/api/health` **200**; «database is locked» — **0**; **NameError/Traceback с 11:40:06 — 0**.

**Данные:** `mca_media_assets` 83 (intake жив; 1 чат; спан 06:23–11:44 UTC), `mca_media_analyses` 0; smart_messages/graph_facts/outputs не проверялись повторно (не в дельте).

**Rollback:** не потребовался. Soft: вернуть `MCA_VISION_ENABLED=false` (бэкап `.env.t5126b.bak`) = бит-в-бит 2.58.62; cold: `git revert d298f1f` (v32 аддитивна, guard-полка §3 цела).

**Infra-инцидент сессии (не прод):** fail2ban — 3 бана деплой-канала в течение дня (перебор юзеров в начале сессии → ~1 ч; TNC-проба без SSH-баннера на истёкшем окне → ре-бан; устаревшая первая запись пароля в `deploy_commands.txt` → AUTH+бан). Владелец: смена IP, перезапуск fail2ban, канонизация записи `pass:`; AGENTS.md дополнен правилом fail2ban-дисциплины. R17: пароли нигде не печатались.

**Incidental (вне скоупа деплоя, факты):**
1. **mca-18**: ежечасный `_tick_legacy_traits_parse` падает TypeError (`memory_maintenance.py:292` → `mca_self_model.py:1891`, `int(datetime)`), наблюдён 11:08:40 UTC на **старом** процессе (до рестартов T-5126b); fail-soft, бот не деградирует. Роут: backlog/Builder (домен mca-18).
2. **mca-19 product**: intake пишет assets (83, один чат) при тикающем воркере, но `mca_media_analyses` = 0 — разборы не создаются (контрактные причины не диагностированы: per-chat effective-гейты / capability-probe). Критический путь деплоя (worker стартует/тикает без NameError) подтверждён; end-to-end распознавание — предмет live-приёмки **T-5127 (владелец)**.

**ИТОГ: VERIFIED** — дельта `d298f1f` на проде (хеш ✓), 0 оверрайдов, воркер тикает, health чистый, откат-механики известны. Блокеров деплоя нет.

## 8. T-5126b retry — INFRA-BLOCKED (06.10.2026, отложенная попытка после fail2ban-cooldown)

- Биндинг подтверждён до коннекта: HEAD/origin `d298f1f` (review «к T-5126b ДА», дельта-манифест `8a95bb46…` FILE_COUNT 5); локальный sha256 `services/mca_vision.py` = `d6032dc0f18516f3…` — совпадает с биндингом.
- Пауза 22 мин → **один** recon TCP22 198.46.175.136 (таймаут 15 с) — **ЗАКРЫТ** (timeout, cooldown ещё активен). Автоповторов нет: это был единственный разрешённый ретрай — дальнейшие попытки только по слову владельца.
- Прод здоров по HTTP (порт 443 не ограничен): `/healthz` **200** `{"status":"ok","version":"2.58.63"}` ×2, `/api/health` **200** — бот на 2.58.63; K1=false и v32 — по последнему задокументированному состоянию (§5; SSH-верификация недоступна при закрытом канале).
- Ру-бук НЕ выполнялся: pull/env/рестарты не производились, прод-`.env` не менялся — soft-стабилизация `MCA_VISION_ENABLED=false` сохранена.
- Готовые тулы для следующей попытки: `tools/_t5126b_deploy.py` (полный ру-бук одной сессией: pull `d298f1f` → hash-gate → снять K1-оверрайд с бэкапом `.env.t5126b.bak` → рестарт ×2 → батарея: worker started `tick=5s`, 0 NameError/Traceback, locked=0, assets/analyses=0) или `tools/_t5126b_ssh.py` (пошагово). Миграцию v32 не повторять. R17: секретов нет.
