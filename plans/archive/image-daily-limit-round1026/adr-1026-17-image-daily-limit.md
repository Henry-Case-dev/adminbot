# ADR-1026-17 — A5 «Image Daily Limit»: атомарный резерв/идемпотентность/учёт дневного лимита изображений (§26–§31), честная scope/TZ-семантика, санкция Δ DDL (PG-журнал резервов), UI-врезка §27/§50, границы A4/A6/A7

- **Статус:** **Accepted (merge to `plans/ARCHITECTURE.md` §86, 25.09.2026)**; T-3605. **Accepted = архитектурное решение принято и включено в pending epic-release Эпика 3; НЕ «deployed»** — release policy **EPIC_ONLY**, deployment **DEFERRED_TO_EPIC** (пер-фича деплоя нет; bump 2.58.30 → 2.58.31 — в агрегате Эпика 3, T-3606).
- **Фича:** A5 `image-daily-limit-round1026` (Эпик 3 «Agentic Intelligence», Wave 3, Раунд 10.26). **P0.**
- **Тип:** backend/лимит + **Δ DDL** (PG-журнал резервов) + Δ каталога + UI-врезка §27/§50; §104 не трогается; без 3-го LLM-вызова; без новых инструментов (канон 11).
- **ТЗ-основание:** `plans/current_task.md` **§26** (`:4905–4922`), **§27** (`:4923–4959`), **§28** (`:4962–4992`), **§29** (`:4995–5015`), **§30** (`:5018–5044`), **§31** (`:5047–5063`); ориентиры **§50** (`:5683–5717`, UI Mini App), **§37** (`:5252–5279`, инвариант безопасности); границы §22–§25 (A4), §32–§35 (A6), §36–§48 (A7), §49/§51 (A9), §104 (не трогать).
- **Durable-вход:** `plans/docs/agentic-audit-round1026.md` (A0, APPROVED) — `#s12-6-7` (лимиты), EV-19 «Бюджет `image_calls` (global+per-chat, env-only)» (`worker_budget.py:35,284–291`), `#epic3-reuse` («не вводить второй счётчик; расширять существующий (A5)»), `#epic3-handoff`.
- **Baseline:** HEAD **`e8646af`** == `origin/master` (рабочее дерево содержит **незакоммиченный pending epic-release код A2/A3** — не трогать); `APP_VERSION` **2.58.30**; pytest `.venv` **9156/0**; JS **47/47**; каталог **469/426/444/100/98/21**; канон инструментов **11**; **Δ DDL=0** (SQLite v12).
- **Связано:** **reuses** — ADR-1026-13 (durable-аудит/дисциплина EVIDENCE), ADR-1026-14 (A1: 2-вызовность, env-only киль-свитч-прецедент), ADR-1026-15 (A2: envelope/§17-лимиты/канон 11), **ADR-1026-16** (A3: `ImageRequest`/`run_image_request`, маркер `image_request_handled`, env-only `UNIFIED_IMAGE_REQUEST_ENABLED`), ADR-1018-7 D1 (scope/наследование `resolve_setting_cached`), ADR-1019-8 D2 (sentinel-семантика), ADR-1023-5 (image-tool: пре-гейт + `generate_image`, бюджет/провайдер/секрет), ADR-1020-3 (прецедент `limits.chat_timezone`), **hotfix5 ADR-1025-11 D3** (env-only ветка `image_calls`, «обложка не конкурирует за лимит LLM»), ADR-1025-24 (верификационный гейт/deploy-вердикт); **effective note (без hard-AMEND)** — ADR-1023-5 D2 (разделение «пре-гейт + tool-calling» сохранено; меняется только механизм списания); **NOT_APPLICABLE** — ADR-1013-3 (промпт-канон не меняется).
- **Δ DDL — санкционированный факт Эпика 3** (backlog `:314`); точный Δ DDL — D1/§«Санкция».

## Контекст

§26 требует дневной лимит генерации изображений с **глобальным значением** и **локальным значением конкретного чата**, через **существующую систему scope и наследования**, **без** отдельного независимого механизма локальных настроек. §27 задаёт расположение в Mini App («Модули → Генерация изображений → Лимиты»: «Дневной лимит изображений», «Использовано сегодня: N / M», источник лимита, время следующего сброса, текущая TZ; без дублирования в другом разделе). §28 фиксирует семантику: один успешно созданный результат = одна использованная генерация; ошибки до генерации не расходуют лимит; успех, не доставленный в Telegram, «расход уже мог произойти»; без автоматической повторной платной генерации; нужен отдельный учёт запросов/успехов/ошибок. §29 требует серверной проверки, защиты от параллельных запросов (при остатке 1 два одновременных не должны оба проходить), атомарного резервирования, освобождения резерва при сбое генерации и idempotency key. §30 разграничивает «глобальный лимит по умолчанию» и «общую квоту всех чатов» (отдельный явно названный бюджет). §31 требует календарный день по TZ (допустимо — TZ чата), без «24 ч от первого запроса», точное время сброса, неизменность использованной квоты при смене лимита.

**Фактическое состояние baseline (Step 0 EVIDENCE + карта кода).** Счётчик `image_calls` уже живёт в **PostgreSQL** (`worker_budget`, PK `(day, scope, metric)`; в SQLite его нет; runtime-`PgDatabase` DI). Лимиты — env-only `WORKER_DAILY_IMAGE_CALLS_GLOBAL/PER_CHAT` (200/60) с sentinel-семантикой. Списание — `worker_budget.consume` (**check-after-increment**: UPSERT `used=used+1` + `RETURNING used` → `used <= limit`; при отказе инкремент **не** откатывается → утечка квоты; **нет** атомарного резерва/идемпотентности/rollback; fail-open при PG down). Обвязка — `image_generation._consume_budget` (global→per-chat **до** генерации). **GAP §29:** нет резерва/идемпотентности/освобождения. **GAP §26/§30:** per-chat override для `image_calls` **не резолвится** (env-only ветка); «глобальный дефолт» и «общая квота» не разведены. **GAP §31:** день — глобальный `WORKER_BUDGET_TZ`; per-chat TZ-прецедент `limits.chat_timezone` существует. **GAP §28:** раздельного учёта запросов/успехов/ошибок нет. **GAP §27/§50:** маршрута «Модули → Генерация изображений → Лимиты» нет; `/api/workers/budget` показывает N/M частично.

**Открытые вопросы Step 1 (a)–(e)** требуют lasting-решений: (a) хранилище резерва/учёта и Δ DDL; (b) дефолт/scope; (c) TZ/сброс; (d) idem key; (e) границы A4/A6/A7; плюс (f) deploy/rollout/risk.

## Решения

**D1. Хранилище резерва/учёта — PostgreSQL; резерв поверх существующей `worker_budget` + журнал `image_reservation`; SQLite Δ DDL = 0.**
- Счётчик `image_calls` — единственный источник правды в PG (`worker_budget`); атомарный резерв требует одной транзакционной БД → резерв/журнал живут в PG. SQLite остаётся **v12** (Δ DDL=0); `worker_budget` — **без изменения схемы**.
- Журнал `image_reservation` — **ledger** (по строке на резерв), **не** второй агрегатный счётчик; `used` остаётся в `worker_budget`.
- **Альтернативы:** (i) SQLite-счётчик — отклонено (два источника правды, нет атомарности с PG); (ii) `SELECT FOR UPDATE` + `UPDATE` — допустимо, но условный UPSERT проще/уже используется; (iii) in-memory идемпотентность — отклонено (не переживает рестарт/мультипроцесс).

**D2. Атомарный резерв — условный UPSERT (`used < limit`), без утечки при отказе; reserve → generate → commit/release; одна транзакция на shared+per-chat.**
- Для `cap`: `INSERT ... ON CONFLICT (day,scope,metric) DO UPDATE SET used=worker_budget.used+1 WHERE worker_budget.used < $limit RETURNING used`. Для `unlimited` — безусловный апсерт. Для `forbidden` (`0`) — отказ **без** записи. Отказ **не** инкрементирует (устранена утечка baseline).
- Транзакция: idem-строка + shared-резерв (`scope='global'`) + per-chat-резерв (`scope='chat:<id>'`); отказ per-chat → откат shared-инкремента + `status='denied', error_code='limit_chat'`. При исчерпании shared per-chat не расходуется.
- Порядок: `reserve` до платного вызова; `commit` при успехе генерации; `release` при сбое генерации (результат не создан). Между транзакциями сбой процесса оставляет `status='reserved'` (инертно; reconcile — вне A5).
- **Альтернатива:** check-after-increment — отклонено (§29, утечка/гонка).

**D3. Idempotency key — `reservation_key = f"{chat_id}:{message_id}:{source}"`, UNIQUE/PK журнала.**
- `message_id` — **текущий** id сообщения (в `ToolContext` это `reply_to_message_id`, куда оба входа A3 кладут `message.message_id`); `chat_id` обязателен (message_id уникален только в чате); `source ∈ {direct, tool}` — внутренний enum (не пользовательский ввод).
- Fallback: `message_id is None` → `f"{chat_id}:corr:{correlation_id}:{source}"`; `correlation_id is None` → `f"{chat_id}:uuid:{uuid4().hex}:{source}"` (без дедупа, WARNING).
- Replay: ключ существует → повторный резерв не выполняется; возврат прежнего исхода (`committed` → already_handled; `released`/`denied` → прежний отказ); in-flight `reserved` → «уже резервировано».
- Retention: `IMAGE_RESERVATION_RETENTION_DAYS` (env-only, default **30**); opportunistic-purge ≤1/сутки/процесс. R17: без промптов/текстов.
- Cross-path double-spend исключён A3-маркером `image_request_handled` (ADR-1026-16 D3); ключ `+source` различает законные входы.
- **Альтернатива:** `correlation_id`-ключ — отклонено (не переживает повторную доставку update).

**D4. Scope-семантика — каталожный `limits.image_daily_limit` (глобальный дефолт + per-chat override) ≠ shared-бюджет `WORKER_DAILY_IMAGE_CALLS_GLOBAL` (явно названный, env-only).**
- Per-chat лимит резолвится `resolve_setting_cached("limits.image_daily_limit", chat_id=…, default=WORKER_DAILY_IMAGE_CALLS_PER_CHAT)` → `chat → global → env` (60), sentinel сохранён. При отсутствии ключа — env-дефолт (обратная совместимость).
- «Глобальный лимит по умолчанию» (значение по умолчанию) **не смешивается** с «общей квотой всех чатов» (shared-бюджет, `scope='global'`); UI показывает их **разными** строками. Shared-бюджет остаётся env-only (без каталожного ключа) — чтобы не плодить дублирующие формы.
- Используется **существующая** система scope/наследования (ADR-1018-7 D1); независимый механизм локальных настроек **не** создаётся.
- **Альтернатива:** env-only без override — отклонено (§26/§27).

**D5. TZ/сброс — per-chat день по `limits.chat_timezone` (reuse `resolve_timezone`); shared — `WORKER_BUDGET_TZ`; календарный день; точное время сброса.**
- День `chat:<id>` — в TZ чата (per-chat override → global `CHAT_TIMEZONE` → fallback `limits.summary_timezone`, прецедент `direct_chat_service._chat_time_line`/`tool_router._chat_timezone`); день `global` — `WORKER_BUDGET_TZ`. Legacy `consume` воркеров (`llm_calls`/`llm_tokens`) продолжает `today()` (`WORKER_BUDGET_TZ`) — без регресса воркеров.
- Никакого «24 ч от первого запроса»; изменение лимита **не** обнуляет `used`. `get_day_summary`/`get_usage` получают аддитивные `day`/`timezone`/`next_reset_at`/`source` (R16).
- **Альтернатива:** единый `WORKER_BUDGET_TZ` — отклонено (§31 допускает TZ чата).

**D6. Семантика учёта (§28) — 1 результат = 1 генерация (`n=1`, §104); раздельный учёт из журнала, не второй счётчик.**
- Единица: генератор создаёт ровно один результат (`n:1` в payload — §104), поэтому 1 запрос = 1 генерация = 1 результат; multi-image не поддерживается (фиксировано).
- Учёт запросов/успехов/ошибок/отказов выводится из `image_reservation` (`status`: `committed`=успех, `released`=ошибка генерации, `denied`=отказ по лимиту; `delivery_failed` — отдельный флаг). «Фактические расходы» — **N/A** (провайдер не отдаёт стоимость) — документировано. Второй агрегатный счётчик **не** вводится.

**D7. Rollback/outcome — release при сбое генерации; commit при успехе (в т.ч. сбой доставки); без авто-повторной платной генерации; bounded-retry резервирует один раз.**
- Сбой генерации (результат не создан) → `release_image` (квота возвращена). Успех генерации → `commit_image` независимо от исхода доставки (§28: «расход уже мог произойти»); сбой доставки помечается `delivery_failed=true` (учёт), повторная платная генерация не запускается.
- `generate_image_verbose` (bounded retry) сохраняет резерв один раз на запрос (внутренние попытки — `consume_budget=False`).
- **Альтернатива:** release при сбое доставки — отклонено (§28: платный вызов состоялся; иначе скрытый расход).

**D8. fail-open/fail-closed — сохранён fail-open с честным логом (baseline-паритет).**
- PG down / отсутствие таблицы / ошибка транзакции → `ok=True, reason='failopen'` + WARNING с дедупом (как baseline `consume`); журнал не пишется. Это **осознанный** tradeoff (доступность > строгая квота в аварии), документирован; транзакция исключает частичный расход.
- master-рубильник бюджетов OFF → legacy-путь (baseline-эквивалент); `IMAGE_DAILY_LIMIT_ENABLED=OFF` → legacy `consume`.
- **Альтернатива:** fail-closed — отклонено (меняет доступность живого чата сильнее, чем требует §29).

**D9. Санкция UI §27/§50 + Δ каталога — врезка «Лимиты» в существующий контур `mod_images`.**
- **Санкционировано:** +1 ParamSpec `limits.image_daily_limit` (`IMAGE_DAILY_LIMIT`, int, группа `limits_images`) + 1 GroupSpec `limits_images` (category `limits`, tab `mod_images`). Ожидаемые счётчики: REGISTRY 469→**470**, Settings 426→**427**, categorized 444→**445**, GROUPS 100→**101**, `_TAB_BY_GROUP` 98→**99**, TAB_RULES 21→**21** (финал — F8 `--check`).
- UI: в модуле «Генерация изображений» секция «Лимиты» с «Дневной лимит изображений», «Использовано сегодня: N / M», источником, временем сброса, TZ; отдельная (read-only) строка «Общий бюджет всех чатов». Reuse существующего UI-контура Эпика 1 и `/api/workers/budget` (аддитивные поля); **без** отдельной админ-панели и дублирующих форм. Полный набор под-вкладок §27 (Обзор/История/Контекст и память) — вне A5 (A4/прочие волны).
- **Альтернатива:** env-only без UI — отклонено (нарушает REQ-A5-09/§26).

**D10. Границы — A4/A6/A7/§104 не реализуются; REUSE ExecutionGraph; R17-safe наблюдаемость; §37 — инвариант.**
- Поля-заглушки A3 (`context_required`/`context_sources`/`resolved_subjects`) остаются; память/досье — A4; `get_user_context` — A6; URL+фактчек/безопасность — A7; события `IMAGE_GENERATION_*` — A9. §104 `generate_image` без изменений; канон 11.
- Лимиты/TZ/idem-key управляются **только** админ-конфигурацией (каталог/env), не текстом пользователя/LLM/tool-output (§37); журнал не хранит контент. Логи — числа/коды/id/`source`/`status`/`reason`; вторая аналитика не создаётся.

**D11. Release policy = EPIC_ONLY (deferred); hot-OFF kill-switch; cold-откат; DDL-откат не требуется.**
- A5 отдельно **не деплоится**; вклад в агрегатный pending epic-release Эпика 3 (bump 2.58.30 → **2.58.31** — на границе эпика, T-3606 = `DEFERRED_TO_EPIC`; **@DevOps не вызывается**). DDL применяется автоматически при старте прода (`PgDatabase.init()`), идемпотентно.
- Hot-OFF: env-only `IMAGE_DAILY_LIMIT_ENABLED` (default ON). Cold: `git revert` к **`e8646af`** + агрегатный анкер. **DDL-откат не требуется:** `image_reservation` аддитивна и инертна без кода; `DROP TABLE IF EXISTS image_reservation` — опционально/документировано. Теги/бэкапы не удаляются (R18).

**D12. Risk-Level: R3 + усиленные требования.**
- Изменение разделяемого бюджета живого direct-чата/tool-пути + DDL + каталог + UI + money-like квота при конкуренции; KG High: `Risk-a5-double-spend`, scope-semantics gap, TZ/reset gap.
- **Усиленные требования:** (1) threat/failure-анализ (механизм→код→тест); (2) race/atomic-order-тесты + concurrency-проба; (3) rollback-доказательства (OFF/legacy, hot/cold, анкер, отсутствие DDL-отката); (4) adversarial-приёмка + diff-аудит (Δ DDL/каталог, §104/§85-UI, ExecutionGraph, канон 11, второй счётчик).
- **Понижает до R2:** доказанная аддитивность OFF + отсутствие новых наблюдаемых исходов + успешные concurrency/rollback-доказательства. **Reviewer может повысить.**

## Санкция Δ DDL (verbatim, D1)

> Без этой санкции Δ DDL = 0 обязателен.

```sql
-- PostgreSQL, services/pg_db.py::DDL_STATEMENTS (идемпотентно, применяется PgDatabase.init())
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

- **SQLite:** Δ DDL = 0 (остаётся `user_version=12`). **`worker_budget`:** схема без изменений (PK `(day, scope, metric)`).
- **Автоматика:** `PgDatabase.init()` (`pg_db.py:521–536`) прогоняет DDL при старте (`bot.py`/`web/app.py` → `ConfigCache.init()` → `pg.init()`); повторный `init()` — no-op (`plans/project.md:56–63`).
- **Обратный путь:** откат кода без отката DDL (таблица инертна); опциональный `DROP TABLE IF EXISTS image_reservation` + `DROP INDEX IF EXISTS …`.

## AMEND / REUSE-карта (Dn → задачи)

| ADR | Статус в A5 | Суть |
|---|---|---|
| ADR-1026-16 (A3) | **REUSE** | `ImageRequest`/`run_image_request`; маркер `image_request_handled`; env-only `UNIFIED_IMAGE_REQUEST_ENABLED` |
| ADR-1026-15 (A2) | **REUSE** | envelope `ToolLoopResult.tool_results`/`ToolContext.result_for`; §17-лимиты; канон **11** |
| ADR-1026-14 (A1) | **REUSE** | 2-вызовность; env-only киль-свитч-прецедент |
| ADR-1026-13 (A0) | **REUSE** | durable-аудит; `#epic3-reuse` (не второй счётчик) |
| ADR-1018-7 D1 | **REUSE** | scope/наследование `resolve_setting_cached` |
| ADR-1019-8 D2 | **REUSE** | sentinel `0=запрет/<0=безлимит/>0=cap` |
| ADR-1023-5 | **REUSE + effective note** | Пре-гейт + `generate_image` сохранены; меняется только механизм списания |
| ADR-1025-11 D3 (hotfix5) | **REUSE** | env-only ветка `image_calls`; «обложка не конкурирует за лимит LLM»; fail-open-аннотации |
| ADR-1020-3 | **REUSE** | Прецедент `limits.chat_timezone` |
| ADR-1025-24 | **REUSE** | Дисциплина верификационного гейта/deploy-вердикта |
| ADR-1013-3 | **NOT_APPLICABLE** | Промпт-канон не меняется |

| Решение | Задачи (tasks.md) |
|---|---|
| D1 (хранилище/Δ DDL) | T-3590, T-3591, T-3598 |
| D2 (атомарный резерв) | T-3590, T-3591, T-3592 |
| D3 (idem key) | T-3590, T-3591, T-3594 |
| D4 (scope-семантика) | T-3595, T-3602 |
| D5 (TZ/сброс) | T-3596 |
| D6 (§28-учёт) | T-3597, T-3598 |
| D7 (rollback/outcome) | T-3593, T-3597 |
| D8 (fail-open) | T-3591, T-3601 |
| D9 (UI/Δ каталога) | T-3603 |
| D10 (границы/reuse) | T-3602 |
| D11 (deploy/rollback EPIC_ONLY) | T-3605, T-3606 |
| D12 (R3-усиленные доказательства) | T-3599, T-3604 |

## Альтернативы (сводно)

| Вопрос | Рассмотрено | Выбор | Почему |
|---|---|---|---|
| Хранилище резерва | SQLite-счётчик; `SELECT FOR UPDATE`; PG + журнал | **PG (`worker_budget` + `image_reservation`)** | Единый источник правды; атомарность; нет дубля счётчика |
| Механизм резерва | check-after-increment; условный UPSERT | **условный UPSERT (`used < limit`)** | §29; отказ не расходует квоту; устраняет гонку/утечку |
| Idem key | `correlation_id`; `message_id+source`; `chat_id:message_id:source` | **`chat_id:message_id:source`** | Переживает повторную доставку; различает входы; message_id уникален только в чате |
| Дефолт лимита | env-only; каталог | **каталог `limits.image_daily_limit` (+env-дефолт)** | §26 per-chat override; §27 UI |
| Shared-квота | смешать с глобальным дефолтом; отдельный env-only бюджет | **отдельный явно названный shared-бюджет** | §30 «не смешивать» |
| TZ | единый `WORKER_BUDGET_TZ`; TZ чата | **TZ чата (`limits.chat_timezone`) + `WORKER_BUDGET_TZ` для shared** | §31; существующий прецедент |
| Сбой доставки | release; commit | **commit (+`delivery_failed`)** | §28: расход уже мог произойти; нет авто-повтора |
| Деградация | fail-open; fail-closed | **fail-open с честным логом** | Паритет baseline; транзакция исключает частичный расход |
| UI | env-only; отдельная панель; врезка в контур | **врезка в `mod_images` + Δ каталога** | §27/§50; REQ-A5-09 |
| Deploy | ДА/bump; NOT_APPLICABLE; EPIC_ONLY | **EPIC_ONLY (deferred)** | Меняется рантайм разделяемого бюджета; пер-фича деплоя нет |
| Риск | R2; R3 | **R3** | Blast radius + money-like квота + DDL + конкуренция |

## Последствия

- Списание квоты становится **атомарным резервом**: отказ по лимиту не расходует квоту; при остатке 1 ровно один из двух параллельных запросов проходит; утечка baseline устранена.
- Повторная обработка одного сообщения списывает квоту **ровно один раз** (idempotency-ledger, переживающий рестарт/мультипроцесс).
- Резерв **освобождается** при сбое генерации; успех с неудачной доставкой честно учитывается как расход; авто-повторной платной генерации нет.
- Scope честный: «глобальный дефолт» (каталог) и «общая квота всех чатов» (shared-бюджет) разведены; per-chat override работает через существующее наследование.
- Календарный день — по TZ чата; точное время сброса; изменение лимита не обнуляет использованную квоту.
- Появляется **PG-таблица** `image_reservation` (идемпотентный DDL, авто-применение при старте) и **каталожный ключ** `limits.image_daily_limit` (+1 param/+1 group); UI-врезка «Лимиты» в существующий контур.
- §104/§85-UI-панель/канон 11/2-вызовность/A4/A6/A7 — не затронуты; REUSE ExecutionGraph/A2-envelope/A3-маркер.
- Риск **R3**; усиленные требования (threat/failure, race/concurrency, rollback-доказательства, adversarial + diff-аудит).
- Живой direct-чат: `IMAGE_DAILY_LIMIT_ENABLED=OFF` → прежнее поведение; cold-откат — `git revert` к `e8646af`; DDL-откат не требуется.

## Ссылки

- `plans/features/image-daily-limit-round1026/{spec.md, tasks.md}` (spec — Step 2 T-3588; сверка tasks — @PM T-3589).
- Durable-аудит: `plans/docs/agentic-audit-round1026.md` (анкоры `#s12-6-7`, `#epic3-reuse`, `#epic3-handoff`).
- ТЗ: `plans/current_task.md` §26 (`:4905–4922`), §27 (`:4923–4959`), §28 (`:4962–4992`), §29 (`:4995–5015`), §30 (`:5018–5044`), §31 (`:5047–5063`), §50 (`:5683–5717`), §37 (`:5252–5279`), §104 (`:3180–3203`).
- A3 (вход): `plans/ARCHITECTURE.md` §85; `plans/archive/unified-image-request-round1026/{spec.md, adr-1026-16-unified-image-request.md}`.
- A2 (вход): `plans/ARCHITECTURE.md` §84; `plans/archive/tool-chains-round1026/adr-1026-15-tool-chain-contract-and-limits.md`.
- Image-tool/hotfix5: `plans/archive/image-generation-tool-round1023/ADR-1023-5.md`; `plans/archive/hotfix5-summary-cover-window-round1025/` (ADR-1025-11 D3).
- Код (baseline `e8646af` + незакоммиченный A2/A3): `services/worker_budget.py` (`METRIC_IMAGE_CALLS:35`, `DAY_TZ:58`, `today:92–96`, `UPSERT_SQL:60–66`, `consume:211–242`, `_metric_limit:275–305`, `get_day_summary:335–373`); `services/pg_db.py` (`DDL_STATEMENTS:33`, `worker_budget:190–199`, `init:521–536`); `services/config_cache.py:165`; `services/image_generation.py` (`ImageRequest:201–224`, `run_image_request:256–266`, `_consume_budget:570–589`, `generate:837–924`, `generate_image_verbose:939–…`, `generate_and_send:1015–1044`, `maybe_handle_keyword:1047–1086`); `services/direct_chat_service.py` (`_image_pre_gate_block:1580–1609`, `ToolContext:954–968`, `_chat_time_line:1263–1277`); `services/tool_router.py` (`ToolContext:419–446`, `_chat_timezone:1480–1500`, `_generate_image:1553–1620`); `services/param_catalog.py` (`flags_module_images:338`, `CHAT_TIMEZONE:1061`, `TAB_MOD_IMAGES:2036`, `TAB_RULES:2192–2194`); `services/canonical_context.py::resolve_timezone:313`; `services/budget_limits.py`; `services/worker_settings.py::resolve_setting_cached:142–150`; `web/api/gates.py:157–166`.
- Точка отката: коммит **`e8646af`** (пер-фича тег не создаётся — `EPIC_ONLY`; агрегатный анкер — на границе эпика).
