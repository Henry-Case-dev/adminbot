# Scanner-аудит безопасности/R17 — `mca-19-image-understanding` (T-5125, 06.10.2026)

## Вердикт: **к деплою ДА** (Critical 0 / High 0)

**Сводка: Critical 0 / High 0 / Medium 0 (новых) / Low 2 (backlog) / Info 5.**

- Binding: HEAD `2dfb8c4`, кандидат — незакоммиченный working tree. Манифест `plans/reports/mca19_wth_manifest_review.txt` перепроверен моим пересчётом: MANIFEST_SHA256 `da861426…287af028a17`, FILE_COUNT 122 — совпадает; 121/122 файла байт-в-байт (1 несовпадающий — самоманифест, самореферентная запись). Хеши реворка 5/5: database `e58338d2…`, mca_vision `7427ddf7…`, chat_context `f4112edc…`, search `c26a54f2…`, factcheck `a0d983eb…` — кандидат тот же, что ревьюен (Approved, итер.2).
- Мои прогоны на этом дереве: focused mca-19 (8 файлов) — **114 passed** + `test_summary_handlers` — 53 = **167 passed**; F8 `--check` — 519/411/108/22, ROUTES pin `eb0611ae…`, после прогона повторный хеш-свер манифеста — 0 расхождений (дерево не тронуто).
- Санкции импортом факта: REASON_CODES=**269** (включая `deadline_exceeded`), KILL_SWITCHES=**80** (ровно 4 `MCA_VISION_*`), `category_for('recognize_image')='external_read'`, METERED_TOOLS содержит `recognize_image`, `vision_stages()`=9, процесс `vision.media` v1 в реестре mca-17a (`mca_process_registry.py:1094–1125`).

## Независимые репро (мой скрипт на реальном DatabaseService, offline SQLite)

1. **Кросс-чат-кеш (TH-5):** один `content_hash` в чатах 111/222 → `find_ready_analysis_by_content_hash('…', 'chat:222')` → **None** (утечки нет); `chat:111` → своя строка; `get_ready_analysis` тоже scope-bound; кеш-строка без полей автора/времени (нейтрален). `access_scope` в WHERE (`database.py:3878–3885`) и в UNIQUE-грануле (`:1581`).
2. **H-1 singleflight (закрыт, подтверждён):** конфликт UNIQUE-гранулы после посторонних INSERT → возвращён истинный id существующей строки (`database.py:3777–3791`, ветвление по `rowcount`); CAS-finish проходит по своей строке, чужая не задета.
3. **failed ≠ success-кеш:** `status='failed'` не переиспользуется (`database.py:3854`, `mca_vision.py:1252`).

## Проверка по чек-листу (сводка, file:line)

1. **SSRF/загрузки:** прод-пайплайн — getFile-only (`download_telegram_file`, `mca_vision.py:628–644`): URL с токеном строится внутри aiogram, наружу не возвращается/не логируется. `fetch_external_image` (`:647–661`) — **прод-вызовов нет** (grep: только тесты), fail-closed при `MCA_SAFE_FETCH_ENABLED=false`, наружу только через SafeFetcher mca-02. `safe_fetch.py` **в диффе отсутствует** (переиспользован неизменным): redirect — каждый хоп повторно через `aguarded_target` + `redirect_blocked` (`safe_fetch.py:560–574`); DNS-rebinding — pre-flight resolve + post-response `peer_allowed` до чтения тела (`:551–555`, тело при mismatch не читается; TOCTOU-окно residual mca-02, не ухудшено); лимиты байт до/после распаковки в стриме (`:620–645`) + повторный `max_bytes`-чек сниффером после загрузки (`mca_vision.py:603–625`). Mpx bomb-guard по заголовкам без декодирования в процессе (декода PIL нет вообще — байты уходят base64-URL наружу, `:367–368`). «Размер до/после sniff» — покрыт двойным чеком.
2. **Инъекции:** system prompt vision-вызова — константа с анти-инъекционной инструкцией (`ANALYSIS_SYSTEM_PROMPT`, `mca_vision.py:815–827`); OCR-ответ модели — только data-канал `untrusted_image_data` (`:843–848`), parse-ошибка → честный `failed:parse_error` (`:851–862`). Все прод-потребители контекста — только `build_chat_context` (`handlers/factcheck.py:81`, `handlers/search.py:91`; grep `format_chat_context` — других прод-вызовов нет); блок попадает в **user**-контент `<chat_context>` с note «НЕ доказательства» (`factcheck_service.py:112–115`), НЕ в system prompt. Рендер OCR — с обязательным лейблом канала (`mca_vision.py:2017–2023`). Tool `recognize_image`: chat scope из `ctx.chat_id`, чужой чат → `missing/out_of_scope` (`tool_router.py`, блок `_recognize_image`), `additionalProperties: false` (URL/key/model от LLM не принимаются), серверный двойной гейт K1+K4; pending — job-связка, без LLM-опросов, дедуп триггеров ≤1 ответ (`mca_vision.py:2280–2297`), bounded-память 512/TTL 600с.
3. **Кросс-чат/приватность:** см. репро 1–3; `resolve_target_assets` ищет только в текущем chat_id (`mca_vision.py:2191–2238`); renderer — `get_smart_message_by_tg_id(chat_id,…)` + scope чата строки (`chat_context.py:241–250`). API: POST `/api/vision/test` и GET `/api/vision/state` — RBAC global-admin ИЛИ право `keys.vision_api_key` (`routes.py:2056–2061, 2095–2100`, оба, не только test); snapshot — статусы/модель/очередь/stages/last-meta (status/model/completed_at/error_reason/revision — без chat_id/OCR/байт, `mca_vision.py:2155–2163`).
4. **Бюджет/антиспам:** VISION_ENABLED default **OFF** (`settings.py`, владельческий тумблер — без согласия владельца расходов нет); token bucket участник/чат env/каталог (`mca_vision.py:1090–1129`), bounded-память buckets; очередь durable, capacity → deferred с TTL → `vision_skipped_expired` (`:1784–1804`); worker: tick-lock, sem concurrency, ≤6/tick (`:1664–1746`); backfill bounded batch=10, ниже live, K3-gate, missing_source честный, детерминированный job_id (`:1832–1897`); breaker (3/60с, `:1648–1660`). Расход: `usage_events.record(module='vision', step='media')` только при реальном вызове (`:932–942`); cache hit до вызова (`:1403–1485`) — 0 токенов; в карту mca-11 тул не входит (external_read) → double-count нет.
5. **R17:** все logger-точки mca_vision — id/chat/типы исключений, без URL/токена/байт/OCR (полный grep); события `vision_media`/`vision_capability_probe` — stage/reason_code/chat_id/operation_id/model, без endpoint/ключа/тела (`:501–515`, `:1232–1246`); ответ `/vision/test` — `status_code: None` (`routes.py:2076`); ключ — маска {configured,last4}, `secret=True` в каталоге (`param_catalog.py:753–758`), пустое поле = «оставить сохранённый»; скан диффа+untracked по 7 сигнатурам секретов — **0 совпадений**, фикстуры чистые.
6. **DDL v32:** строго аддитивно — ALTER 10 колонок под guard `PRAGMA table_info` (`database.py:3629–3637`, `_table_columns`), таблицы под `sqlite_master`-guard, CREATE INDEX IF NOT EXISTS, 0 UPDATE/DELETE, `user_version=32`; тест повторной инициализации (no-op) в Block A (`test_mca19_block_a…:123–128`); `pg_db.py` вне диффа → PG no-op.
7. **Fail-режимы:** K1 OFF — intake 0 строк (`mca_vision.py:749`), enqueue 0 (`:1172`), worker не стартует (`:1686–1688`), tool disabled (`tool_router`), чтение контекста OFF → None → байт-в-байт прежний (`chat_context.py:225–234`); статусы честные: 401/403/429/timeout ≠ `main_model_no_vision` (`_classify_probe`, `:384–400`), mapping reason→status (`:1305–1311`), effective только при proven capability (`:281–350`); инертности K2/K3/K4 при K1 — в гейт-хелперах (`mca_gates.py`).
8. **M-3 (captioned-фото):** класс подтверждён по коду — блок фасада подставляется только у media-строк с пустым текстом (`chat_context.py:117–132`: `if not text and media_enabled`), фото с подписью показывает только caption. Security-сторона чистая: OCR в окно не попадает (данных в промпте меньше, не больше), caption — обычный текст участника в data-канале (не новый класс инъекции); renderer/tool-пути OCR отдают с лейблом. Disposition «follow-up + T-5127» подтверждён, **не блокер**.
9. **Threat Medium (закрытие в коде):** TH-4 — сниффер+байты+пиксели без декода в процессе ✓; TH-6 — buckets/очередь/breaker/учёт usage, residual «не exactly-once» disclosed ✓; TH-8 — H-1 фикс + CAS `finish_media_analysis` (`database.py:3796–3828`) + coalesce ✓; TH-9 — прод-писателей OCR-фактов нет, SourceRef-гранулярность как библиотека/тул-ref ✓; TH-1/2/3/5/7/10/11 (High) — см. п.1–3; TH-12 (retention, Low) — disclosed.

## Находки

| # | Severity | Координаты | Суть | Blocking |
|---|---|---|---|---|
| L-A | Low (backlog) | `services/chat_context.py:198` | Структурный delimiter-injection: OCR/caption с текстом `</chat_context>` может оборвать обёртку окна. Не новый класс mca-19: любой текст участника в этом окне рендерится так же (без экранирования, `_squash` только нормализует пробелы) — attacker и так может ввести это текстом. GEN-R18 residual (семантическая уступка) disclosed. Backlog: экранирование/маркеры для всех канонических блоков единым решением. | нет |
| L-B | Low (backlog) | `services/mca_vision.py:1087` | Rate-бакеты в памяти процесса: рестарт обнуляет антиспам-окно (burst заново). Потолок фактически задан concurrency=2/≤6-job за тик и durable-очередью; TH-6 residual не ухудшен. Backlog: персистентный счётчик при желании жёстче. | нет |

Incidental (unrelated/pre-existing, не мета- candidates): `test_summary_handlers` warning «leaked aiosqlite» — backlog §121; 4 красных полного прогона — pre-existing (reused evidence 12203/4, оркестраторская верификация, согласуется с моими 167 focused).

## Info

- **I-1.** `fetch_external_image` — провайдер без прод-вызовов (только тесты): произвольных URL в прод-пайплайне нет вообще; при будущей проводке — SafeFetcher-гейты уже внутри. Dead-but-gated, безопасно.
- **I-2.** `mca_media_analyses`/`mca_media_assets` без TTL-очистки — TH-12 disclosed (политика хранения — существующий контур).
- **I-3.** `runtime_snapshot` «последний анализ» — глобальный (без scope), но: RBAC admin/ключ-vision + поля только meta (без контента/chat_id) — приемлемо.
- **I-4.** `pipeline_stage_event(**extra)` допускает произвольные поля — все фактические вызовы передают только model/chat_id/operation_id/reason_code (проверено grep); регресс-риск на будущее, не дефект.
- **I-5.** `record_media_analysis` при гипотетическом конфликте без найденной строки возвращает 0 → каскад честно завершает job `vision_stale_discarded` (не тишина); в SQLite на том же коннекте недостижимо.

## Disposition

- Блокирующих находок нет; H-1/H-2/M-1/M-2 реворка перепроверены в коде и репро; M-3/L-3/L-1/L-2 — backlog per review итер.2.
- Обязательные post-deploy условия без изменений: T-5122 (real-network smoke) и T-5127 (live-приёмка, PENDING OWNER) — в T-5127 обязательно сценарии captioned-фото (M-3) и фото в контексте фактических потребителей.
- Rollback: soft K1=false (бит-в-бит 2.58.62 — гейт-ревью п.7), cold revert; v32 аддитивна.

R17: в отчёте секретов и сырого контента нет.

**Вердикт: к деплою ДА** (Critical 0 / High 0; join-barrier T-5126 @DevOps снят).
