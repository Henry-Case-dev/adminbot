# A5 `image-daily-limit-round1026` — спецификация (Step 2 @Architect, T-3588)

- **Epic-ID:** Эпик 3 «Agentic Intelligence» (Wave 3). **Feature-ID:** `image-daily-limit-round1026`. **Раунд:** 10.26.
- **Тип:** backend/лимит + **Δ DDL** (резерв/идемпотентность/учёт) + Δ каталога + UI-врезка §27/§50. **P0.**
- **Источник (verbatim):** `plans/current_task.md` **§26 «ДНЕВНОЙ ЛИМИТ ИЗОБРАЖЕНИЙ»** (`:4905–4922`), **§27 «РАСПОЛОЖЕНИЕ В MINI APP»** (`:4923–4959`), **§28 «СЕМАНТИКА ЛИМИТА»** (`:4962–4992`), **§29 «ЗАЩИТА ОТ ПАРАЛЛЕЛЬНЫХ ЗАПРОСОВ»** (`:4995–5015`), **§30 «ГЛОБАЛЬНЫЕ И ЛОКАЛЬНЫЕ ЛИМИТЫ»** (`:5018–5044`), **§31 «ВРЕМЕННАЯ ЗОНА И СБРОС»** (`:5047–5063`); сопутствующие ориентиры: **§50 «ИНТЕГРАЦИЯ С MINI APP»** (`:5683–5717`) — «Модули → Генерация изображений: … дневной лимит …» + «Не дублировать один параметр в нескольких независимых формах»; **§37 «БЕЗОПАСНОСТЬ TOOL OUTPUT»** (`:5252–5279`) — инвариант безопасности резерва (внешний контент не управляет лимитами/очередями). **§27** — источник UI-требования; **§31** — источник TZ/сброса.
- **Границы (не реализуются в A5):** **§22–§25** (изображения на основе памяти/досье/RAG) — **A4**; **§32–§35** (`get_user_context`, structured memory lookup) — **A6**; **§36–§37** (URL+фактчек, безопасность tool output) — **A7**; §38–§48 — A7/A8; **§49/§51** (ExecutionGraph/события `IMAGE_GENERATION_*`) — **A9** (A5 новых событий не создаёт); **§52–§54** — A10. **§104 «GENERATE_IMAGE — НЕ ТРОГАТЬ»** (`:3180–3203`) — генератор не переписывается. **§85-UI** — используется только как «врезка в существующий UI-контур Эпика 1», отдельной админ-панели не создаётся.
- **Durable-вход:** `plans/docs/agentic-audit-round1026.md` (A0, APPROVED) — анкоры `#s12-6-7` (лимиты), EV-19 «Бюджет `image_calls` (global+per-chat, env-only)» (`worker_budget.py:35,284–291`), `#epic3-reuse` («Бюджет изображений — `worker_budget image_calls`; **не вводить второй счётчик**; расширять существующий (A5)»), `#epic3-handoff`.
- **Зависит от:** **A0** ✅ (durable-аудит); **A1** ✅ (`tool-coordinator`, Merge §83, ADR-1026-14 Accepted); **A2** ✅ (`tool-chains`, Merge §84, ADR-1026-15 Accepted — envelope `ToolLoopResult.tool_results`/`ToolContext.result_for`, §17-лимиты, канон **11**); **A3** ✅ (`unified-image-request`, Merge §85, ADR-1026-16 Accepted — единый `ImageRequest`/`run_image_request`, оба входа → существующий `generate_and_send`, маркер `ToolContext.image_request_handled`, env-only `UNIFIED_IMAGE_REQUEST_ENABLED`); Эпики 1–2 ✅ (§70, §71–§81 — scope/наследование каталога, UI-контур Эпика 1).
- **Baseline (Step 0 @Memory, 25.09.2026; в Step 2 не перемеряется):** HEAD **`e8646af`** == `origin/master` (рабочее дерево содержит **незакоммиченный pending epic-release код A2/A3** — НЕ трогать/не коммитить); `APP_VERSION` **2.58.30**; pytest `.venv` **9156/0**; JS **47/47**; каталог **REGISTRY 469 / Settings 426 / categorized 444 / GROUPS 100 / `_TAB_BY_GROUP` 98 / TAB_RULES 21**; канон инструментов **11**; **Δ DDL=0** (SQLite v12; PG `worker_budget` — PK `(day, scope, metric)`); прод активен 2.58.30 (MainPID 652183). Точка отката — коммит **`e8646af`** + env-киль-свитч (пер-фича тег **не создаётся** — `EPIC_ONLY`; агрегатный анкер — на границе эпика). R18: теги/бэкапы не удаляются.
- **Карта кода (baseline `e8646af` + незакоммиченный A2/A3, факт):**
  **Бюджет (единственный источник правды — PG):** `services/worker_budget.py` — `METRIC_IMAGE_CALLS:35`, `DAY_TZ:58` (= `WORKER_BUDGET_TZ`), `today():92–96`, `UPSERT_SQL:60–66`, `consume():211–242` (**check-after-increment**: апсерт `used=used+amount` + `RETURNING used` → сравнение `used <= limit` **после** инкремента; при отказе инкремент **не откатывается** → утечка квоты; без idempotency/rollback; fail-open при PG down `:218–231`), `_metric_limit():275–305` (для `image_calls` — **env-only** ветка `WORKER_DAILY_IMAGE_CALLS_GLOBAL/PER_CHAT`, **per-chat override не резолвится** — gap §26/§30), `get_usage():308–332`, `get_day_summary():335–373` (UI N/M частично; `timezone=DAY_TZ`), `budget_gate.budgets_enabled` master-рубильник.
  **DDL:** `services/pg_db.py` — `DDL_STATEMENTS:33`, `worker_budget` (`:190–199`: `day DATE, scope TEXT, metric TEXT, used BIGINT, updated_at, PK(day,scope,metric)`), `init():521–536` (прогон `DDL_STATEMENTS` — идемпотентно; вызывается из `ConfigCache.init()` `services/config_cache.py:165` на старте `bot.py`/`web/app.py` → **DDL применяется автоматически при старте прод**).
  **Генерация:** `services/image_generation.py` — `ImageRequest:201–224`, `build_image_request:227–243`, `build_final_prompt:246–253`, `run_image_request:256–266`, `_consume_budget:570–589` (global→per-chat **до** генерации), `generate():837–924` (`consume_budget=True`), `generate_image_verbose():939–…` (bounded retry; резерв списывается **один раз** на запрос, внутренние попытки `consume_budget=False`), `generate_and_send():1015–1044`, `maybe_handle_keyword:1047–1086`.
  **Входы:** `services/direct_chat_service.py` — `_image_pre_gate_block:1580–1609` (ToolContext `reply_to_message_id=message.message_id` → **текущий** message_id), сборка `ToolContext:954–968` (`reply_to_message_id=message.message_id`, `image_request_handled=image_pre_gate_fired`), `_chat_time_line:1263–1277` (per-chat TZ `limits.chat_timezone`); `services/tool_router.py` — `ToolContext:419–446`, `_chat_timezone:1480–1500`, `_generate_image:1553–1620`.
  **Scope/каталог/TZ:** `services/worker_settings.py::resolve_setting_cached:142–150` (chat → global → default; ADR-1018-7 D1); `services/param_catalog.py` — `flags_module_images:338`, `IMAGE_GENERATION_MODULE_ENABLED:997`, `CHAT_TIMEZONE:1061`, `TAB_MOD_IMAGES:2036`, `TAB_RULES` `mod_images:2192–2194`; `services/canonical_context.py::resolve_timezone:313`; `services/budget_limits.py` (sentinel `0=запрет/<0=безлимит/>0=cap`).
  **UI:** `web/api/gates.py::/workers/budget:157–166` → `worker_budget.get_day_summary`.
- **ADR:** `adr-1026-17-image-daily-limit.md` (D1–D12); **Status: Proposed → Accepted по merge** (ожидается раздел `plans/ARCHITECTURE.md` **§86**; T-3605).
- **Release policy:** **EPIC_ONLY** — A5 входит в **pending epic-release Эпика 3**; отдельный деплой после approval **не предусмотрен** (см. §9). **@DevOps на пер-фича деплой не вызывается.**
- **Risk-Level: R3** (обоснование — §10). **Статус:** Proposed.

## 1. Область и исключения

**Входит (что делает A5):**
- **Атомарный резерв квоты изображений (§29, REQ-A5-01/-04):** замена `check-after-increment` `consume` на **условный атомарный резерв** поверх **существующей** таблицы `worker_budget` (без второго счётчика): инкремент выполняется **только если** `used < limit` (или `limit < 0` = безлимит), отказ **не** расходует квоту. Резерв — **до** платного вызова генерации; освобождение — при сбое генерации.
- **Идемпотентность (§29, REQ-A5-02):** журнал резервов в PG с UNIQUE-ключом `(chat_id, message_id, source)`; повторная обработка одного сообщения (ретрай/повторная доставка update) списывает квоту **ровно один раз**.
- **Честный scope (§26/§30, REQ-A5-05):** «глобальный лимит по умолчанию» (каталожный ключ, наследуется как дефолт) **≠** «общая квота всех чатов» (существующий global-бюджет, отдельно и явно названный); per-chat override через существующую систему scope/наследования каталога; **без** нового независимого механизма локальных настроек.
- **Календарный день/TZ/сброс (§31, REQ-A5-06):** день per-chat по существующей TZ-инфраструктуре `limits.chat_timezone` (per-chat override → global → код-дефолт; fallback `limits.summary_timezone`); для shared-бюджета — `WORKER_BUDGET_TZ`; точное время следующего сброса; изменение лимита **не** обнуляет использованную квоту; **никакого** «24 ч от первого запроса».
- **Семантика учёта (§28, REQ-A5-07/-08):** один успешно созданный результат = одна использованная генерация (генератор создаёт ровно `n=1` — §104); ошибки **до** генерации не расходуют лимит; успешный результат, не доставленный в Telegram, **учитывается как расход** (платный вызов состоялся); повторная платная генерация ради доставки **не** выполняется; отдельный учёт **запросов / успешных генераций / ошибок** (расходы — «если доступны» → N/A, документировано), выводимый из журнала резервов (не второй счётчик квоты).
- **UI §27/§50 (REQ-A5-09, по санкции D9):** врезка «Модули → Генерация изображений → Лимиты» в **существующий** UI-контур Эпика 1: «Дневной лимит изображений», «Использовано сегодня: N / M», источник лимита, время следующего сброса, текущая TZ; **без** дублирования настройки в независимых формах.
- **Санкции:** **Δ DDL ≠ 0** (PG-таблица журнала резервов + индексы; SQLite Δ=0) — verbatim §7; **Δ каталога = +1 ParamSpec +1 GroupSpec** (D9/§6); env-only kill-switch.
- **R17-safe наблюдаемость**, **reuse ExecutionGraph** (вторая аналитика не создаётся), сохранение 2-вызовности System 2, сохранение A3-контракта `image_request_handled`, канон инструментов **11**.

**Не входит (границы, категорически):**
- **A4 (§22–§25):** память/досье/RAG на изображениях, разрешение имён, сборка prompt из независимых частей. Поля-заглушки A3 (`context_required`/`context_sources`/`resolved_subjects`) **остаются заглушками**.
- **A6 (§32–§35):** `get_user_context(purpose)`, structured memory lookup.
- **A7 (§36–§48):** URL+фактчек, безопасность tool output как функциональность, `action`/стили, новый Decision Making. §37 используется **только** как инвариант (внешний контент не управляет лимитами).
- **A9 (§49/§51):** новые события `IMAGE_GENERATION_*`; ExecutionGraph **только reuse**.
- **§104 `generate_image`:** модель/провайдер/ключи/промпт/параметры/обработка ошибок генератора/порядок публикации/механизм прикрепления — **без изменений**. Обвязка резерва — **вокруг** неизменного генератора.
- **Второй счётчик `image_calls`** / второй контур локальных настроек / второй механизм цепочек — **запрещены** (A0 `#epic3-reuse`).
- **Отдельная административная панель** (§50) — запрещена; используется существующий UI-контур.
- **3-й LLM-вызов**; новый LLM-роутер/агент; новые инструменты (канон остаётся **11**).
- Правки `plans/current_task.md` (immutable), машинного блока `OPENCODE_WORKFLOW_STATE_V1`, `tasks.md` (сверка — @PM T-3589), `plans/backlog.md`, `plans/metrics.md`, `plans/ARCHITECTURE.md` (на своих шагах), durable-аудита A0 (только чтение). **@Scanner отсутствует** (единый Reviewer gate). **@DevOps не вызывается** (EPIC_ONLY).

## 2. Трассируемость REQ → SC

| REQ | §ТЗ (verbatim) | Блок / задача | SC |
|---|---|---|---|
| REQ-A5-01 | §29 «Использовать атомарное резервирование квоты или другой подходящий механизм.» (`:5007–5008`) | B, C / T-3590, T-3591, T-3592 | SC-A5-01 |
| REQ-A5-02 | §29 «Предусмотреть idempotency key, чтобы повторная обработка одного сообщения не списывала квоту повторно.» (`:5013–5015`) | B, C / T-3590, T-3591, T-3594 | SC-A5-02 |
| REQ-A5-03 | §29 «При ошибке генерации освобождать резерв, если результат не был создан.» (`:5010–5011`) | C / T-3593 | SC-A5-03 |
| REQ-A5-04 | §29 «Проверку лимита выполнять на сервере.» + «Не считать клиентский счётчик источником истины.» + «Если осталось одно изображение, два одновременных запроса не должны оба проходить проверку без контроля.» (`:4998–5005`) | B, C, F / T-3590, T-3592, T-3599 | SC-A5-04 |
| REQ-A5-05 | §26 «Глобальное значение.» «Локальное значение конкретного чата.» «Использовать существующую систему scope и наследования конфигурации.» «Не создавать отдельный независимый механизм локальных настроек.» (`:4912–4920`); §30 «Глобальный дневной лимит задаёт значение по умолчанию.» + «Локальное значение может переопределять его для конкретного чата.» + «Если дополнительно требуется общий предел на все чаты вместе, это должен быть отдельный явно названный бюджет.» + «Не смешивать: "Глобальный лимит по умолчанию" и "Общая квота всех чатов".» (`:5023–5041`) | D, G / T-3595, T-3596, T-3602 | SC-A5-05 |
| REQ-A5-06 | §31 «Определить календарный день по выбранной временной зоне.» «Для текущего проекта допустимо использовать существующую часовую зону чата.» + «Не сбрасывать квоту каждые 24 часа от момента первого запроса, если интерфейс обещает календарный день.» + «Показывать точное время следующего сброса.» + «При изменении лимита не обнулять уже использованную квоту.» (`:5050–5063`) | D, F / T-3596, T-3599 | SC-A5-06 |
| REQ-A5-07 | §28 «Нужен отдельный учёт: запросов; успешных генераций; ошибок; фактических расходов, если доступны.» (`:4987–4992`) | E / T-3598 | SC-A5-07 |
| REQ-A5-08 | §28 «Один успешно созданный результат — одна использованная генерация.» + «Ошибки до запуска генерации не должны расходовать пользовательский лимит.» + «При успешном результате, который не удалось доставить в Telegram, расход генерации уже мог произойти.» + «Не выполнять повторную платную генерацию автоматически ради исправления ошибки отправки.» (`:4968–4985`) | C, E, F / T-3592, T-3593, T-3597, T-3599 | SC-A5-08 |
| REQ-A5-09 | §27 «В разделе "Лимиты": "Дневной лимит изображений".» + «Рядом: "Использовано сегодня: N / M".» + Показывать «источник лимита; время следующего сброса; текущую временную зону.» + «Не дублировать настройку в другом разделе с независимым состоянием.» (`:4941–4959`); §50 «Модули → Генерация изображений: … дневной лимит …» + «Не дублировать один параметр в нескольких независимых формах.» (`:5693–5717`) | G / T-3603 | SC-A5-09 |
| REQ-A5-10 | Границы/инварианты: §104 «GENERATE_IMAGE — НЕ ТРОГАТЬ» (`:3180–3203`); §85-UI — отдельная санкция (D9); reuse `worker_budget` без второго счётчика (A0 `#epic3-reuse`); границы A4/A6/A7; fail-open/fail-closed семантика (hotfix5); R17/R18; deploy EPIC_ONLY | 0, G, H / T-3587, T-3602, T-3606 | SC-A5-10…SC-A5-14 |

Orphan-REQ нет: каждый REQ-A5-01…-10 привязан к ≥1 SC; каждый SC восходит к REQ (§8). 14 приёмочных инвариантов привязаны к SC в §5.

## 3. Наблюдаемое поведение и отказы

**Наблюдаемое поведение (что меняется в рантайме):**
- Каждый запрос генерации изображения (прямая фраза или tool) перед платным вызовом выполняет **атомарный резерв**: в одной транзакции PG (i) регистрирует идемпотентный ключ `(chat_id, message_id, source)`, (ii) условно инкрементирует shared-бюджет (`scope='global'`), (iii) условно инкрементирует per-chat лимит (`scope='chat:<id>'`). Резерв проходит, только если **оба** контура под кэпом (или безлимит). При исчерпании — честный отказ **до** платного вызова.
- При исчерпании **shared**-бюджета per-chat **не** расходуется (как раньше); при исчерпании **per-chat** shared-инкремент **откатывается** в той же транзакции (устранена утечка baseline).
- Генерация успешна → резерв **commit** (расход сохранён); сбой генерации (результат не создан) → резерв **release** (квота возвращена); успех + сбой доставки в Telegram → **commit** (платный вызов состоялся), автоматической повторной платной генерации нет.
- Повторная обработка того же сообщения (ретрай/повторная доставка update) → ключ уже существует → резерв **не** выполняется повторно (ровно одно списание).
- Календарный день per-chat определяется по TZ чата (`limits.chat_timezone`); shared-бюджет — по `WORKER_BUDGET_TZ`. Сброс — на календарной границе дня (не «24 ч от первого запроса»).
- UI «Модули → Генерация изображений → Лимиты» показывает «Дневной лимит изображений», «Использовано сегодня: N / M», источник лимита (`chat`/`global`/`default`), точное время следующего сброса и текущую TZ; отдельная строка — общий бюджет всех чатов (только чтение, env).
- **Наблюдаемость:** R17-safe (числа/коды/id/`source`/`status`/`reason`); reuse `[image]`/`[tools]`-логов + ExecutionGraph; второго контура аналитики нет. Новые логи — только при отказе резерва/сбое хранилища (с дедупом).
- **Канон инструментов:** **11** (не меняется). **§104** — вне diff. **2-вызовность** System 2 сохранена.

**Отказы/негативные сценарии (что считается НЕ выполнением):**
- Отказ по лимиту **расходует** квоту (утечка, check-after-increment) → не принято (REQ-A5-01/-04).
- При остатке 1 два одновременных запроса **оба** проходят резерв → не принято (REQ-A5-04).
- Повторная обработка одного сообщения списывает квоту **второй** раз → не принято (REQ-A5-02).
- Резерв **не освобождается** при сбое генерации (результат не создан) → не принято (REQ-A5-03).
- Квота обнуляется/теряется при изменении лимита; сброс «24 ч от первого запроса»; день считается не по TZ чата → не принято (REQ-A5-06).
- Смешаны «глобальный лимит по умолчанию» и «общая квота всех чатов»; per-chat override не работает; введён независимый механизм локальных настроек → не принято (REQ-A5-05).
- Введён **второй счётчик** `image_calls`/второй контур локальных настроек → не принято (REQ-A5-10).
- Автоматическая повторная платная генерация ради исправления ошибки доставки → не принято (REQ-A5-08).
- Изменены §104 (генератор/провайдер/ключи/параметры/ошибки/публикация/прикрепление), §85-UI-контур (отдельная админ-панель), канон инструментов, A4/A6/A7 → не принято (REQ-A5-10).
- Δ DDL вне санкции §7; неидемпотентная миграция; Δ каталога вне санкции D9; пер-фича деплой/тег → не принято (REQ-A5-10).
- R17-нарушения (сырые тексты/ключи/промпты в логах) → не принято.

## 4. Решения (открытые вопросы (a)–(f))

### (a) Хранилище резерва/учёта и verbatim Δ DDL-санкция (D1, D2) — **ГЛАВНОЕ**
**Выбрано: хранилище — PostgreSQL (там же, где `worker_budget`, единственный источник правды); резерв — условный атомарный UPSERT поверх существующей `worker_budget` + журнал `image_reservation`; SQLite Δ DDL = 0.**
- **Почему PG, а не SQLite:** счётчик `image_calls` уже живёт **только** в PG (`worker_budget`; в SQLite его нет; runtime-`PgDatabase` через DI — `worker_budget.py:78–89`). Атомарный резерв требует **одной транзакционной** БД; SQLite — per-process и не является источником правды бюджета. Поэтому резерв/журнал — PG; SQLite остаётся **v12** (Δ DDL=0), `worker_budget` — **без изменения схемы**.
- **`worker_budget` не дублируется:** `used` для `image_calls` остаётся **единственным** счётчиком. Журнал `image_reservation` — это **ledger** (по одной строке на резерв), а не второй агрегатный счётчик.
- **Δ DDL (verbatim, PG — в `DDL_STATEMENTS` `services/pg_db.py`):**
  ```sql
  CREATE TABLE IF NOT EXISTS image_reservation (
      reservation_key TEXT PRIMARY KEY,
      chat_id         BIGINT,
      source          TEXT NOT NULL DEFAULT 'direct',
      message_id      BIGINT,
      day             DATE NOT NULL,
      status          TEXT NOT NULL DEFAULT 'reserved',
      error_code      TEXT NOT NULL DEFAULT '',
      delivery_failed BOOLEAN NOT NULL DEFAULT false,
      created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
      CONSTRAINT image_reservation_status_chk
          CHECK (status IN ('reserved','committed','released','denied'))
  );
  CREATE INDEX IF NOT EXISTS idx_image_reservation_day_status
      ON image_reservation (day, status);
  CREATE INDEX IF NOT EXISTS idx_image_reservation_chat_day
      ON image_reservation (chat_id, day);
  ```
- **Автоматическое применение:** `PgDatabase.init()` прогоняет `DDL_STATEMENTS` при старте (`bot.py`/`web/app.py` → `ConfigCache.init()` → `pg.init()`, `pg_db.py:521–536`); идемпотентно (`CREATE TABLE/INDEX IF NOT EXISTS`), повторный `init()` — no-op. Отдельная миграционная задача не требуется (политика DDL `plans/project.md:56–63`).
- **Порядок (failure-safe):** `reserve` → `generate` → `commit` (успех) / `release` (сбой генерации). `reserve` и `commit`/`release` — отдельные транзакции; между ними сбой процесса оставляет `status='reserved'` (инертно; reconcile — вне A5).
- **Альтернативы:** (i) новая таблица-счётчик в SQLite — отклонено (два источника правды, нет атомарности с PG-счётчиком); (ii) резерв через `SELECT ... FOR UPDATE` + `UPDATE` — допустимо, но условный UPSERT проще и уже используется в модуле; (iii) хранить идемпотентность in-memory — отклонено (не переживает рестарт/мультипроцесс).

### (b) Дефолт суточного лимита и scope-семантика (D4)
**Выбрано: «глобальный лимит по умолчанию» — новый каталожный ключ `limits.image_daily_limit` (per-chat override → global → env-дефолт `WORKER_DAILY_IMAGE_CALLS_PER_CHAT` = 60); «общая квота всех чатов» — существующий global-бюджет `WORKER_DAILY_IMAGE_CALLS_GLOBAL` = 200, явно названный и отделённый.**
- **Per-chat override (gap §26/§30 fix):** `_metric_limit("chat:<id>", "image_calls")` резолвит `limits.image_daily_limit` через `resolve_setting_cached` (chat → global → env-дефолт 60), сохраняя sentinel-семантику (`0=запрет`, `<0=безлимит`, `>0=cap`). При отсутствии ключа в каталоге — env-дефолт (обратная совместимость; существующие тесты 200/60 не ломаются).
- **Честная семантика:** global-бюджет `scope='global'` — это **«общий предел на все чаты»** (shared quota), а **не** «глобальный лимит по умолчанию». «Глобальный лимит по умолчанию» — значение по умолчанию для per-chat лимита. Смешивание запрещено; UI показывает их **разными** строками (§27 «источник лимита»).
- **Общий бюджет** остаётся **env-only** (без каталожного ключа) — чтобы не плодить дублирующие формы и не смешивать с настройкой дневного лимита. Если в будущем потребуется настраивать shared-бюджет — отдельное решение/санкция.
- **Δ каталога:** +1 ParamSpec `IMAGE_DAILY_LIMIT` (key `limits.image_daily_limit`, тип `int`, группа `limits_images`) + 1 GroupSpec `limits_images` (category `limits`, tab `mod_images`). Точные счётчики — §6. Наследование — существующая система scope (ADR-1018-7 D1), независимый механизм локальных настроек **не** создаётся.
- **Альтернатива:** оставить env-only без per-chat override — отклонено (нарушает §26 «Локальное значение конкретного чата» и §27 UI).

### (c) TZ/сброс (D5)
**Выбрано: per-chat день — по TZ чата через `limits.chat_timezone` (reuse `resolve_timezone`, прецедент `direct_chat_service._chat_time_line:1263–1277` / `tool_router._chat_timezone:1480–1500`); shared-бюджет — по `WORKER_BUDGET_TZ`; сброс — на календарной границе дня; точное время следующего сброса для UI.**
- День `chat:<id>` вычисляется в TZ чата; день `global` (shared) — в `WORKER_BUDGET_TZ`. Изменение касается **только** image-резерва: legacy `consume` воркеров (`llm_calls`/`llm_tokens`) продолжает использовать `today()` (`WORKER_BUDGET_TZ`) — **без регресса воркеров**.
- Никакого «24 ч от первого запроса»; при изменении лимита `used` **не** обнуляется (меняется только значение лимита).
- Read-path (`get_usage`/`get_day_summary`) для per-chat image_calls учитывает per-chat день; в ответ добавляются `day`/`timezone`/`next_reset_at`/`source` (аддитивно, R16).
- **Альтернатива:** единый `WORKER_BUDGET_TZ` для всех — отклонено (§31 допускает TZ чата; §26 per-chat семантика).

### (d) Idempotency key (D3)
**Выбрано: `reservation_key = f"{chat_id}:{message_id}:{source}"` (`source ∈ {direct, tool}`), UNIQUE/PK журнала.**
- `message_id` — **текущий** id сообщения (в `ToolContext` это поле `reply_to_message_id`, куда оба входа кладут `message.message_id`; `_image_pre_gate_block:1599`, сборка `ToolContext:955`). `chat_id` — обязателен (message_id уникален только в чате). `source` — внутренний enum (не пользовательский ввод) — различает законные входы; cross-path double-spend уже исключён A3-маркером `image_request_handled` (ADR-1026-16 D3).
- Fallback: `message_id is None` → `f"{chat_id}:corr:{correlation_id}:{source}"`; и `correlation_id is None` → `f"{chat_id}:uuid:{uuid4().hex}:{source}"` (резерв без дедупа; WARNING). R17-safe: только id/enum.
- **Replay-семантика:** ключ существует → повторный резерв **не** выполняется; возвращается прежний исход (`committed` → already_handled; `released`/`denied` → прежний отказ). In-flight `reserved` → «уже резервировано» (без второго списания).
- **Retention:** журнал хранится `IMAGE_RESERVATION_RETENTION_DAYS` (env-only, default **30**); opportunistic-purge устаревших строк ≤1 раз/сутки/процесс. R17: без промптов/текстов.
- **Альтернатива:** `correlation_id` как ключ — отклонено (не переживает повторную доставку update с новым correlation).

### (e) Границы A4/A6/A7 (D10)
**Выбрано: A5 не реализует память/досье (A4), `get_user_context` (A6), URL+фактчек/безопасность (A7); поля-заглушки A3 остаются; REUSE ExecutionGraph; новых событий нет; §104 не трогать.**
- §37 — инвариант: лимиты/TZ/idem-key управляются **только** админ-конфигурацией (каталог/env), а не текстом пользователя/LLM/tool-output. Журнал не хранит контент.
- Наблюдаемость — reuse существующих логов + ExecutionGraph (`STEP_KIND` `image→llm`); вторая аналитика не создаётся.

### (f) Deploy/rollout/risk (D8, D11, D12)
- **Deploy = `DEFERRED` (EPIC_ONLY):** пер-фича деплоя/тега/бампа нет; вклад в агрегатный релиз Эпика 3 (bump 2.58.31 — на границе эпика, T-3606 = `DEFERRED_TO_EPIC`). Активация DDL — при старте прода (идемпотентно). **@DevOps не вызывается.**
- **Hot-OFF:** env-only kill-switch `IMAGE_DAILY_LIMIT_ENABLED` (default ON) → OFF = legacy `consume`-путь (поведение baseline, журнал не используется). **Fallback:** ошибка PG/отсутствие таблицы → fail-open legacy с честным WARNING.
- **Cold-откат:** `git revert` к анкеру **`e8646af`**; DDL-откат **не требуется** (таблица аддитивна/инертна; при желании — документированный `DROP TABLE IF EXISTS image_reservation`, не обязателен).
- **Risk-Level: R3** (финал) — §10; усиленные доказательства: race/atomic-order-тесты, concurrency-пробы, rollback-доказательства, threat/failure-анализ.

## 5. Feature contract (границы ответственности)

**Preconditions:**
- direct-чат сконфигурирован; `IMAGE_GENERATION_ENABLED` (env) и `flags.image_generation_module_enabled` (per-chat) резолвятся; `UNIFIED_IMAGE_REQUEST_ENABLED` (A3) и `IMAGE_DAILY_LIMIT_ENABLED` резолвятся per-call.
- PG доступен и `PgDatabase.init()` выполнен (таблица `image_reservation` создана; `worker_budget` существует).
- Канон `TOOL_CALLING_TOOLS` = **11** (A2); `active_tools` гейтит `generate_image`.
- Существующий генератор `image_generation.generate_and_send` доступен и **не изменён** (§104).

**Invariants (нарушение = не принято):**
1. **Атомарный резерв без утечки:** отказ по лимиту **не** инкрементирует `used`; резерв — conditional UPSERT (`used < limit`) или безлимит. *(SC-A5-01)*
2. **Идемпотентность:** повторная обработка одного сообщения списывает квоту ровно один раз (ключ `chat_id:message_id:source`). *(SC-A5-02)*
3. **Release при сбое генерации** (результат не создан); при успехе + сбое доставки — **commit** (расход сохранён), без авто-повторной платной генерации. *(SC-A5-03)*
4. **Серверная атомарность:** при остатке 1 два одновременных запроса → ровно один резерв; все проверки на сервере (клиентский счётчик ≠ источник истины). *(SC-A5-04)*
5. **Честный scope:** «глобальный дефолт» ≠ «общая квота»; per-chat override через существующее наследование; без независимого механизма локальных настроек. *(SC-A5-05)*
6. **TZ/сброс:** календарный день по TZ чата (reuse `limits.chat_timezone`), shared — `WORKER_BUDGET_TZ`; точное время сброса; изменение лимита не обнуляет `used`. *(SC-A5-06)*
7. **Раздельный учёт** запросов/успехов/ошибок (расходы N/A), выводимый из журнала; **не** второй счётчик квоты. *(SC-A5-07)*
8. **Единица учёта:** 1 результат = 1 генерация (`n=1`); ошибки до генерации не расходуют лимит. *(SC-A5-08)*
9. **UI §27/§50** в существующем контуре: лимит + N/M + источник + сброс + TZ; без дублирующей формы. *(SC-A5-09)*
10. **§104 вне diff; канон 11; без второго счётчика; REUSE ExecutionGraph; R17/R18.** *(SC-A5-10)*
11. **Δ DDL — по санкции §7** (PG-таблица+индексы; SQLite Δ=0); идемпотентно; rollback без `DROP`. *(SC-A5-11)*
12. **Δ каталога — по санкции D9** (+1 param/+1 group); §85-UI-контур не создаёт отдельную панель; env-only kill-switch. *(SC-A5-12)*
13. **fail-open с честным логом** (поведение не хуже baseline); нет тихой потери квоты/двойного списания на пути отказа; границы A4/A6/A7 не нарушены. *(SC-A5-13)*
14. **Deploy = `DEFERRED` (EPIC_ONLY)**; вклад в pending epic-release; hot/cold-откат определён; теги/бэкапы целы. *(SC-A5-14)*

**Inputs/Outputs:**
- **Вход:** сообщение Telegram (текущий `message_id`, `chat_id`, `source`), резолвнутые лимиты (каталог/env, sentinel), TZ чата; существующий `ImageRequest` (A3).
- **Выход:** прежний результат генерации (изображение в чат), прежние `<image_result>`/JSON-контракты; для UI — аддитивные поля `day`/`timezone`/`next_reset_at`/`source`/`status`-счётчики.
- **Контракты стадий (не меняются):** `generate_and_send`/`GenerationResult` (§104), `ToolLoopResult`/`tool_results` (A2), A3-маркер `image_request_handled`.

**Failure semantics (fail-safe):**
- Лимит исчерпан → честный отказ (`reason=budget`), без платного вызова и без расхода квоты.
- Сбой генерации → release; сбой доставки после успеха → commit; повторная платная генерация не запускается.
- PG down / таблица недоступна → fail-open (как baseline) + WARNING с дедупом; резерв не записан (документированный tradeoff).
- master-рубильник бюджетов OFF → legacy-путь (baseline-эквивалент).
- Киль-свитч OFF → legacy `consume` (значения baseline).

**Compatibility:** живой direct-чат и tool-путь не регрессируют; 2-вызовность сохранена; A2/A3-контракты reuse; OFF/legacy эквивалентен baseline.

**Observability (R17):** только числа/коды/id/`source`/`status`/`reason`/длительности; без сырых промптов/текстов/URL/ключей. Reuse существующих логов + ExecutionGraph.

**Acceptance evidence:** тесты §9 (атомарность/race, идемпотентность, release/commit, TZ-граница, scope, OFF/legacy, R17, регресс §104), concurrency-проба, `threat-failure-analysis.md` (R3), diff-аудит (Δ DDL/каталог, §104/§85-UI, ExecutionGraph, канон, второй счётчик).

**Release-order constraints:** A5 — Wave 3 Эпика 3, после A3 ✅; reuse A2-envelope/A3-ImageRequest; отдельного пер-фича деплоя нет (**EPIC_ONLY**); незакоммиченный A2/A3-кандидат фиксируется на границе эпика.

**Rollback boundary:** hot — env-киль-свитч `IMAGE_DAILY_LIMIT_ENABLED=OFF`; cold — `git revert` к **`e8646af`** + агрегатный анкер Эпика 3; DDL-откат не требуется (таблица инертна).

**Ownership верификации:** @Builder (блоки B–G: T-3590…T-3603; **threat/failure-анализ** — R3-артефакт) → **единый @Reviewer gate** (T-3604: обе линзы; Scanner отсутствует) → @Architect merge (T-3605) → @PM архивация (T-3605) → @DevOps (**T-3606 = `DEFERRED_TO_EPIC`**, на границе эпика). @Scanner отсутствует.

**Epic-release contribution:** A5 добавляет в pending epic-release Эпика 3 атомарный резерв/идемпотентность/учёт дневного лимита изображений, честную scope/TZ-семантику, PG-таблицу журнала и UI-врезку «Лимиты»; агрегируется в общий манифест на границе эпика.

## 6. Контракты данных и API

### 6.1. Δ каталога (санкция D9)
| Что | Ключ | Тип | Группа | Семантика |
|---|---|---|---|---|
| +1 ParamSpec | `limits.image_daily_limit` (`IMAGE_DAILY_LIMIT`) | `int` | `limits_images` | Дневной лимит изображений: **global-дефолт** + **per-chat override** (существующее наследование); sentinel `0=запрет/<0=безлимит/>0=cap`; отсутствие ключа → env `WORKER_DAILY_IMAGE_CALLS_PER_CHAT` (60) |
| +1 GroupSpec | `limits_images` (category `limits`, tab `mod_images`) | — | — | Секция «Лимиты» в модуле «Генерация изображений» (§27) |

- **Счётчики каталога (санкция, ожидаемо):** REGISTRY **469 → 470**; Settings **426 → 427**; categorized **444 → 445**; GROUPS **100 → 101**; `_TAB_BY_GROUP` **98 → 99**; TAB_RULES **21 → 21** (существующая вкладка `mod_images` получает лимит-правило). Финальные числа подтверждает F8 `--check` у @Builder/@Reviewer.
- **Не вводится** второй ключ/второй контур локальных настроек; shared-бюджет (`WORKER_DAILY_IMAGE_CALLS_GLOBAL`) остаётся env-only.

### 6.2. Резерв/учёт — API `services/worker_budget.py` (расширение существующего модуля)
```python
# Резолв (chat → global → env-дефолт; sentinel сохраняется)
async def image_limits(chat_id: int | None) -> tuple[int, int, str]
    # -> (shared_limit_global_env, per_chat_limit_catalog_or_env, per_chat_source)

# День по scope: chat:<id> -> TZ чата; global -> WORKER_BUDGET_TZ
def image_day(chat_id: int | None) -> datetime.date
def image_next_reset(chat_id: int | None) -> datetime.datetime   # точное время сброса

# Одна транзакция: idem-ключ + условный резерв shared + per-chat
async def reserve_image(pg, *, chat_id, idem_key, source,
                        message_id=None) -> ImageReserveResult
#   ImageReserveResult: ok(bool) | reason('ok'|'already'|'limit_global'|'limit_chat'|'failopen')
#                       status('reserved'|'committed'|'released'|'denied')

async def commit_image(pg, idem_key) -> None     # успех генерации (в т.ч. сбой доставки)
async def release_image(pg, idem_key, *, error_code="generation_failed") -> None  # сбой генерации

# Агрегаты для UI (§28), выводятся из журнала — не второй счётчик
async def image_usage_summary(pg, chat_id) -> dict
    # {day, timezone, used, limit, source, next_reset_at,
    #  requests, success, errors, denied, delivery_failed}
```
- **Условный атомарный инкремент (ядро):** для `cap` — `INSERT ... ON CONFLICT (day,scope,metric) DO UPDATE SET used=worker_budget.used+1 WHERE worker_budget.used < $limit RETURNING used`; для `unlimited` — безусловный апсерт; для `forbidden` — отказ без записи. Отказ **не** инкрементирует.
- **Транзакция:** журнал-строка + shared-резерв + per-chat-резерв в **одной** `conn.transaction()`; отказ per-chat → откат shared-инкремента + `status='denied', error_code='limit_chat'`.
- **Fail-open:** нет pool / ошибка PG → `ok=True, reason='failopen'` + WARNING (дедуп), журнал не пишется.

### 6.3. Изменения существующих контрактов (аддитивно)
- `_metric_limit("chat:<id>", "image_calls")` → резолв `limits.image_daily_limit` (было env-only) — **поведение при отсутствии ключа = env-дефолт 60**.
- `get_day_summary`/`get_usage` → аддитивные `day`/`timezone`/`next_reset_at`/`source` для `image_calls` (R16).
- `image_generation._consume_budget` → `reserve_image` (при ON) / legacy `consume` (при OFF); `generate`/`generate_and_send`/`maybe_handle_keyword` сохраняют сигнатуры; добавляется связка `reserve → generate → commit/release`.
- **§104-код генератора** (`generate`, HTTP, payload, ошибки провайдера) — **вне diff**.

## 7. Санкция Δ DDL (verbatim)

> **Санкционировано Шагом 2 @Architect (ADR-1026-17 D1).** Без этой санкции Δ DDL = 0 обязателен.

- **PostgreSQL (Δ DDL ≠ 0):** +1 таблица `image_reservation` + 2 индекса — точный SQL в §4(a). Добавляются в `DDL_STATEMENTS` (`services/pg_db.py`); применяются автоматически при старте (`PgDatabase.init()`), идемпотентно (`IF NOT EXISTS`), повторный `init()` — no-op.
- **SQLite (Δ DDL = 0):** миграций нет, `PRAGMA user_version` остаётся **12**; счётчик/журнал живут в PG.
- **`worker_budget`:** схема **не меняется** (PK `(day, scope, metric)` сохраняется); резерв использует её без новых колонок.
- **Миграционная политика:** идемпотентный DDL по `plans/project.md:56–63`; данные не теряются; обратный путь — **откат кода без отката DDL** (таблица инертна, `DROP` не требуется; при полной очистке документирован `DROP TABLE IF EXISTS image_reservation` + `DROP INDEX IF EXISTS …`).
- **R17:** в таблице нет промптов/текстов/URL/ключей — только id/`source`/`status`/`error_code`/`day`/`delivery_failed`.

## 8. Приёмочные сценарии (SC-A5-01…14)

- **SC-A5-01:** атомарный резерв: отказ по лимиту **не** инкрементирует `used`; резерв — conditional UPSERT; порядок reserve → generate → commit/release. *(REQ-A5-01)*
- **SC-A5-02:** idempotency-ключ `chat_id:message_id:source`; повторная обработка/ретрай одного сообщения списывает ровно один раз; in-flight не дублирует. *(REQ-A5-02)*
- **SC-A5-03:** сбой генерации (результат не создан) → release; успех + сбой доставки → commit; авто-повторной платной генерации нет. *(REQ-A5-03)*
- **SC-A5-04:** при остатке 1 два одновременных запроса → ровно один резерв; отказ не расходует квоту; проверки на сервере (клиентский счётчик не источник истины). *(REQ-A5-04)*
- **SC-A5-05:** «глобальный лимит по умолчанию» (каталог, наследуется) ≠ «общая квота всех чатов» (явно названный shared-бюджет); per-chat override работает; нет независимого механизма локальных настроек. *(REQ-A5-05)*
- **SC-A5-06:** календарный день per-chat по `limits.chat_timezone`, shared — `WORKER_BUDGET_TZ`; точное время следующего сброса; изменение лимита не обнуляет `used`; нет «24 ч от первого запроса». *(REQ-A5-06)*
- **SC-A5-07:** отдельный учёт запросов/успехов/ошибок (расходы N/A), выводимый из журнала; не второй счётчик квоты. *(REQ-A5-07)*
- **SC-A5-08:** 1 успешно созданный результат = 1 генерация (`n=1`); ошибки до генерации не расходуют лимит. *(REQ-A5-08)*
- **SC-A5-09:** UI «Модули → Генерация изображений → Лимиты»: «Дневной лимит изображений» + «Использовано сегодня: N/M» + источник + время сброса + TZ; без дублирующей формы. *(REQ-A5-09)*
- **SC-A5-10:** §104 вне diff; канон **11**; без второго счётчика; REUSE ExecutionGraph; R17/R18; 2-вызовность сохранена. *(REQ-A5-10)*
- **SC-A5-11:** Δ DDL по §7 (PG-таблица+индексы; SQLite Δ=0); идемпотентно; rollback без `DROP`; `worker_budget` без изменения схемы. *(REQ-A5-10)*
- **SC-A5-12:** Δ каталога по §6.1 (+1 param/+1 group); UI-врезка в существующий контур (не отдельная панель); env-only kill-switch. *(REQ-A5-10)*
- **SC-A5-13:** fail-open с честным логом; нет тихой потери квоты/двойного списания на пути отказа; границы A4/A6/A7 не нарушены; §37-инвариант (внешний контент не управляет лимитами). *(REQ-A5-10)*
- **SC-A5-14:** deploy = `DEFERRED` (EPIC_ONLY); вклад в pending epic-release; hot/cold-откат определён; теги/бэкапы целы. *(REQ-A5-10)*

## 9. Стратегия тестов / деплоя / отката

- **Тесты (T-3599):**
  - **Атомарность/race:** эмуляция двух одновременных резервов при остатке 1 → ровно один `ok`; отказ не инкрементирует `used`; `used` не превышает cap.
  - **Идемпотентность:** повторный `reserve_image` с тем же ключом → `already`, квота не тратится; in-flight `reserved` не дублирует.
  - **Rollback:** сбой генерации → `used` возвращён; успех + сбой доставки → `used` сохранён; bounded-retry резервирует один раз.
  - **Scope:** per-chat override (chat → global → env 60); sentinel `0/<0/>0`; shared-бюджет отдельно; отказ per-chat откатывает shared.
  - **TZ/сброс:** граница дня по TZ чата; `next_reset_at` точен; изменение лимита не обнуляет `used`; global — `WORKER_BUDGET_TZ`.
  - **Учёт:** requests/success/errors/denied из журнала; расходы N/A.
  - **R17:** в логах/журнале — только числа/коды/id/`source`/`status`/`reason`.
  - **OFF/legacy:** kill-switch OFF → поведение baseline; master budgets OFF → legacy; PG down → fail-open.
  - **Регресс §104/2-вызовность:** AST/эквивалентность генератора; `await_count==2`.
  - **Baseline приёмки:** pytest `.venv` ≥ **9156/0**; JS **47/47**; `git diff --check`=0; канон **11**.
- **Усиленная R3-приёмка:** `threat-failure-analysis.md` (двойное списание, утечка квоты, idempotency-обход, регресс TZ, R17-утечка, смешение scope, fail-open злоупотребление — механизм + тест); concurrency-проба; rollback-доказательства (OFF/legacy, hot/cold, анкер); diff-аудит.
- **Деплой (T-3606) = `DEFERRED_TO_EPIC`:** release policy **EPIC_ONLY** — A5 отдельно не деплоится; bump `APP_VERSION` 2.58.30 → **2.58.31**, README/cache-bust, push без force, прод ff, `/api/health` 200, `database is locked`=0 — **в составе агрегированного релиза Эпика 3 на границе эпика** под агрегатным Reviewer gate. DDL применяется автоматически при старте прода. `deployment.md` фиксирует вердикт там же.
- **Откат:** hot — `IMAGE_DAILY_LIMIT_ENABLED=OFF` (legacy baseline); cold — `git revert` к **`e8646af`** + агрегатный анкер Эпика 3. **DDL-откат не требуется:** таблица `image_reservation` аддитивна и инертна без кода; `DROP TABLE IF EXISTS image_reservation` — опционально, документировано, не обязателен. Теги/бэкапы не удаляются (R18).

## 10. Risk-Level: R3 и усиленные требования

- **Risk-Level: R3.** Обоснование: A5 меняет рантайм-семантику **разделяемого** бюджета (`worker_budget`) на **живом direct-чате** и tool-пути; вводит **DDL**, каталожный ключ и UI-врезку; затрагивает money-like квоту при конкурентных запросах. KG-риски Step 0: **High** `Risk-a5-double-spend` (гонка/двойное списание), **High** scope-semantics gap, **High** TZ/reset gap; плюс DDL/каталожная дельта и конкуренция с воркер-бюджетом. Смягчение (conditional UPSERT, idempotency-ledger, rollback, reuse существующего счётчика, env-киль-свитч, fail-open) снижает, но не снимает риск: изменение базового контура лимитов живого чата.
- **Усиленные требования при R3 (обязательны):**
  1. **Threat/failure-анализ** (отдельный файл фичи, по образцу A2): двойное списание, утечка квоты, idempotency-обход, регресс TZ, R17-утечка, смешение scope, злоупотребление fail-open, регресс воркер-бюджета — механизм + тест на каждую.
  2. **Race/atomic-order-тесты + concurrency-проба:** два параллельных резерва при остатке 1; порядок reserve→commit/release; отказ без утечки.
  3. **Rollback-доказательства:** OFF/legacy-эквивалентность (воспроизводимая проба), hot/cold-процедуры, анкер `e8646af`, отсутствие необходимости DDL-отката.
  4. **Adversarial-приёмка + diff-аудит:** Δ DDL/каталог, §104/§85-UI, ExecutionGraph, канон 11, отсутствие второго счётчика.
- **Что понижает до R2:** доказанная полная аддитивность при OFF, отсутствие новых наблюдаемых исходов кроме заявленных, успешные concurrency/rollback-доказательства. **Reviewer может повысить** при скрытом изменении поведения/утечке.

## 11. Границы Эпика 3 (REUSE / не дублировать)

| Точка | Что использовать (REUSE) | Что НЕ делать в A5 |
|---|---|---|
| Счётчик квоты | существующий `worker_budget.image_calls` (global+per-chat) | Второй счётчик/второй контур локальных настроек |
| Хранилище | PG (`worker_budget` + новый журнал `image_reservation`) | Отдельная БД/счётчик в SQLite |
| Наследование | существующая система scope (`resolve_setting_cached`, ADR-1018-7 D1) | Независимый механизм локальных настроек |
| TZ | `limits.chat_timezone` + `resolve_timezone` (прецедент `_chat_time_line`/`_chat_timezone`) | Новая TZ-инфраструктура; «24 ч от первого запроса» |
| Генерация | существующий `generate_and_send`/`generate` (§104); A3 `ImageRequest`/`run_image_request` | Менять модель/провайдер/ключи/параметры/ошибки/публикацию/прикрепление; второй pipeline |
| Идемпотентность входа | A3-маркер `ToolContext.image_request_handled` | Дублировать маркер; per-phrase костыль |
| Контракт результата | A2-envelope (`ToolLoopResult.tool_results`/`ToolContext.result_for`) | Дублировать envelope |
| Наблюдаемость | существующие `[image]`/`[tools]`-логи + ExecutionGraph | Вторая аналитика/карта; новые `IMAGE_GENERATION_*`-события (A9) |
| Инструменты | канон **11** | Расширять состав/имена/порядок |
| Память/досье/§22–§25 | поля-заглушки A3 | Реализовывать (A4) |
| `get_user_context` §32–§35 | — | Реализовывать (A6) |
| §36–§48 | — | Реализовывать (A7) |
| UI | существующий контур Эпика 1 (`mod_images`, `/workers/budget`) | Отдельная админ-панель; дублирующая форма параметра |

## 12. Закрытие открытых вопросов (a)–(e)

- **(a)** Хранилище — **PostgreSQL** (`worker_budget` + журнал `image_reservation`); резерв — условный атомарный UPSERT поверх существующей таблицы; SQLite Δ DDL=0; Δ DDL-PG зафиксирован **verbatim** в §4(a)/§7; DDL применяется автоматически при старте (D1, D2).
- **(b)** Дефолт — каталожный ключ `limits.image_daily_limit` (per-chat override → global → env 60); «глобальный дефолт» **отделён** от shared-бюджета `WORKER_DAILY_IMAGE_CALLS_GLOBAL` (200, env-only); sentinel сохранён; Δ каталога = +1 param/+1 group (D4).
- **(c)** TZ/сброс — per-chat по `limits.chat_timezone` (reuse `resolve_timezone`), shared по `WORKER_BUDGET_TZ`; календарный день, точное время сброса; изменение лимита не обнуляет `used` (D5).
- **(d)** Idem key — `f"{chat_id}:{message_id}:{source}"` (UNIQUE журнала); replay-семантика; retention `IMAGE_RESERVATION_RETENTION_DAYS` (default 30) (D3).
- **(e)** Границы — A4/A6/A7/§104 не реализуются; поля-заглушки A3 остаются; REUSE ExecutionGraph; §37 — инвариант; R17-safe (D10).
- **(f)** Deploy = **`DEFERRED` (EPIC_ONLY)**; hot-OFF `IMAGE_DAILY_LIMIT_ENABLED`; cold-откат к `e8646af`; DDL-откат не требуется; **Risk-Level R3** (D8, D11, D12).

## 13. Design consistency gate (вход в T-3589) и Builder-запреты

- **Каждый REQ-A5-01…-10 → SC (§2) → блок/задача (`tasks.md`).** Orphan-REQ нет; каждый SC восходит к REQ; 14 инвариантов привязаны к SC (§5).
- **Сверке T-3589 подлежит:** заполнить колонки SC/ADR в трассируемости `tasks.md`; построить карту «D1…D12 → задачи/блоки» (см. ADR §«AMEND/REUSE-карта»); привязать 14 инвариантов к SC-A5-01…14 (без потерь); подтвердить deploy `DEFERRED`/`EPIC_ONLY` и откат (анкер `e8646af`); подтвердить **Δ DDL ≠ 0** по §7 (PG-таблица+индексы; SQLite Δ=0) и **Δ каталога = +1 param/+1 group** по §6.1; подтвердить env-only kill-switch `IMAGE_DAILY_LIMIT_ENABLED`; зафиксировать, что канон = **11** и §104/§85-UI/A4/A6/A7 вне diff; согласовать T-3603 (UI §27/§50) как **активную** задачу (санкция D9), а не N/A.
- **Расхождения, требующие реконсиляции:** если @PM обнаружит несоответствие Δ DDL/каталога или scope-семантики — эскалация @Architect через @Orchestrator до старта Build.

**Builder-у категорически нельзя (нарушение = отказ приёмки):**
- Менять §104 `generate_image` (модель/провайдер/ключи/промпт/параметры/обработка ошибок генератора/порядок публикации/прикрепление).
- Вводить **второй счётчик** `image_calls` или независимый механизм локальных настроек; дублировать `worker_budget`/A2-envelope/A3-маркер.
- Делать резерв через check-after-increment/`SELECT FOR UPDATE` без условного инкремента (отказ не должен расходовать квоту).
- Реализовывать память/досье (A4), `get_user_context` (A6), URL+фактчек/безопасность (A7), события `IMAGE_GENERATION_*` (A9).
- Создавать отдельную админ-панель (§50); дублировать параметр в независимых формах; расширять канон инструментов (остаётся **11**).
- Писать неидемпотентный DDL; менять схему `worker_budget`; поднимать SQLite `user_version`; удалять/переименовывать таблицы.
- Делать пер-фича деплой/тег/бамп; вызывать @DevOps/@Scanner; коммитить незакоммиченный A2/A3-кандидат; трогать `plans/current_task.md`/машинный блок/durable-аудит.
- Логировать сырые тексты/промпты/URL/ключи (R17); читать лимиты/TZ/idem-key из пользовательского/tool-контента (§37).
