# ADR-1028-14 — mca-10a-random-source-anu: RandomSource (quantum/pseudorandom), ANU-контракт, exploration-политика и честная активация

**Статус:** **Accepted** (05.10.2026; merge `plans/ARCHITECTURE.md` §118 + прод-валидация 2.58.58 VERIFIED; ранее — Proposed, Step 2 @Architect, T-4964/T-4965)
**Дата:** 05.10.2026 (Step 2 @Architect, T-4964/T-4965)
**Номер проверен:** `ADR-1028-14` нигде не занят (grep по `plans/**` 05.10.2026: последний фактический — ADR-1028-13 mca-11, Accepted 05.10.2026; `ADR-1028-1[4-9]`/`ADR-1029` — 0 хитов). Merge-цель — следующий фактически свободный **§118** (последний занятый — §117 mca-11).
**Фича:** `mca-10a-random-source-anu` (Wave 3 эпика `memory-context-autonomy`); ТЗ `plans/current_task.md:522–600` §14.1–§14.4; приёмки A18/A19/A28/A35 `:899–916`; §20.2 `:1016/:1021/:1032`; §27.1 `:1355`. Артефакты — `plans/features/mca-10a-random-source-anu/` (spec, threat-failure-analysis, tasks, requirements-map). База: HEAD `8ea8c1f`, прод 2.58.57, SQLite v26, каталог 489/105/103/21, канон инструментов 12.

---

## Контекст

Владелец требует обязательную интеграцию ANU Quantum Numbers: quantum-режим активируется при первом деплое с ключом и подтверждается **реальными** числами; fallback виден и **не заменяет** приёмку подключения; без ключа — видимый блокер только квантовой интеграции; автоматическая платная подписка запрещена. Первый потребитель источника — стык `DreamRandomSource` (mca-06, ADR-1028-9 AM-2), реализуемый core-источником mca-10a «без переписывания пайплайна». Все применения §14.5–14.11 и контракты `ExplorationRequest/Result` — mca-10b; 10a владеет источником чисел, политикой и журналом.

Зависимости закрыты: mca-13 (§94, единый словарь событий), mca-17a (§100, реестр/trace), mca-14 (§93, migration-runner), mca-01 (§95, single-writer/очереди), mca-02 (§97, доверенные API/маскирование), mca-06 (2.58.49, стык), mca-11 (2.58.57, K5 OFF — ANU-квота ≠ деньги).

---

## Решения

### D1. RandomSource — единственный контракт источника (один сервис)

Дом — `services/mca_random_source.py` (один сервис: `RandomSourceService` async + `ExplorationPolicy` + `CoreDreamRandomSource` sync-адаптер + `AnuClient` + `RandomStore`). Режимы — закрытый набор `quantum|pseudorandom`; настройка `memory.random_source` (первый запуск — quantum). **Выбранный и фактический источник — разные поля** (selected vs effective; effective резолвится на каждом draw). Draw-API: `draw_index(n)` (равномерно, rejection sampling `limit=(range//n)*n`, без modulo bias; bounded повторы), `draw_probability()` (`v/range`), `choose(...)` (политика D6). Каждый draw расходует отдельное значение; переиспользование между решениями и между probability- и selection-draw запрещено. PRNG — stdlib `random.Random` (auto-seed; `randrange`/`random()`; реализация/версия фиксируются; не для ключей/токенов/security). Журнал draw — durable `mca_random_draws` (поля spec §2) — воспроизводимость выбора без новых чисел; R17-safe (ID/числа/коды). Purpose 10a: `less_studied_periods`, `activation_selfcheck`; расширение имён — 10b. **OFF (K1) = бит-в-бит 2.58.57.** (spec §2)

### D2. Durable-запас, watermark и refill — additive v27 через mca-14

Запас/партии/журнал/квота/состояние активации — 4 аддитивные таблицы + 3 индекса в **v27** (`MigrationStep(27)`: `mca_random_batches`, `mca_random_draws`, `mca_random_quota_state`, `mca_random_state`; точные колонки — spec §3), идемпотентно, PG no-op, backup-guard fail-closed. Выдача значения = транзакция `write_transaction`: `reserved_upto += 1` (watermark **до** использования) + journal-запись; crash может потерять выданное, но **повторная выдача исключена**; `consumed_upto` — диагностика. Файловый store отклонён: второй write-механизм и отсутствие кросс-процессного single-writer. Запас bounded (`buffer_max_values`), refill — фоновый, singleflight через `TaskSupervisor`/`task_jobs` (`coalesce_key="random.refill:<account>"`), без периодических запросов с выбросом чисел; проверочные числа зачисляются. Retention/кап журнала — env-only (D11). **OFF (K1/K3) = baseline.** (spec §3)

### D3. ANU-клиент — контракт §14.3, origin-guard, честная квота

`GET https://api.quantumnumbers.anu.edu.au`, header `x-api-key`, `length` 1–1024, `type ∈ {uint8,uint16,hex8,hex16}` (`size` только hex, 1–10), стартово `length=1024&type=uint16`; endpoint/header/defaults предзаполнены, параметры перепроверяются при подключении (owner live). Runtime allowlist: только `https` + точный host ANU + без userinfo/порта/пути; иное → `invalid_url`/`scheme_not_allowed` (mca-02-коды), ключ не отправляется; `follow_redirects=False`, любой 3xx → `redirect_blocked` без повторной отправки ключа. Валидация HTTPS/TLS/JSON/schema/`success`/типа/диапазона/длины. Таймаут catalog 5 с (фон/проверка; direct flow не задерживает); backoff с `Retry-After`; circuit breaker (env-only 3/60 с, in-memory); 401/403 → `auth_failed` без цикла; 429 → `quota_exhausted`/`rate_limit` без запроса на каждое сообщение (min interval 1 с). SafeFetcher (mca-02) **не дублируется** — клиент доверенного провайдера с собственным guard'ом; `SAFE_FETCH_TRUSTED_HOSTS` не меняется. Квота — глобальная (`account_key`+period; success/failed/unknown/manual_checks), не per-chat; точный остаток только при авторитетных данных, иначе «оценка» (Trial 100/мес env-only, перепроверка); `delivery_unknown` — отдельный счётчик. Денежные лимиты mca-11 (K5) не задействованы. **OFF (K2) = ANU-запросов нет.** (spec §4)

### D4. Активация — только реальная партия; HTTP 200 ≠ активация

При первом запуске с ключом: проверка соединения → валидная партия → зачисление в запас → внутренний self-check через адаптер (draw `activation_selfcheck`, без отправки в чат) → `quantum_activated` → effective=quantum. Mock/fallback ≠ активация; блокеры различимы: `provider_unconfigured` (нет ключа), `auth_failed` (401/403), `quota_exhausted` (429/лимит), `provider_unavailable`, `validation_failed` — видима незавершённость **только** квантовой интеграции. Смена ключа (`key_fingerprint` sha256[:12], сервер-only) → `unverified` до успешной проверки; после исправления ключа активация сразу, без релиза. Авто-возврат к quantum при восстановлении, если выбран. **OFF (K2) = `disabled`, не «активно».** (spec §5)

### D5. Fallback — честная деградация, чат не блокируется

Порядок: остаток квантового запаса → при пустом и `fallback_to_pseudorandom=true` локальный PRNG + событие `random_fallback` (notable, один раз на переход) + видимый `effective_source=pseudorandom` + `fallback_reason` в каждом draw → при fallback=false необязательная случайная инициатива/исследование **откладывается** с причиной, прямые ответы и обычные функции продолжаются. QRNG-ожидание никогда не блокирует чат (draw — локальное чтение; сеть — фон). Fallback не объявляется успешной активацией (§20.2 `:1021/:1032`). **OFF (fallback=false) = direct-путь 2.58.57.** (spec §6)

### D6. Exploration-политика — одна проверка, пул без основного, недопустимое не рандомизируется

`ExplorationPolicy.choose(primary, alternatives, *, probability, chat_id, purpose, policy_version) -> PolicyChoice` — нейтральный результат 10a; `ExplorationRequest/Result` создаёт 10b (второй контракт запрещён). Семантика: одна probability-проверка на автономную ситуацию (не сумма независимых 5%; инвариант A29 для 10b); при успехе — один целостный альтернативный кандидат отдельным draw; exploration-пул без основного; нет допустимых альтернатив → primary + `no_eligible_alternative`; равномерный выбор; `policy_version` в журнале; недопустимые измерения (истинность/идентичность/назначение источника/права/удаление/прямой запрос/финансы) не рандомизируются; выбор не обходит уместность и проверку перед отправкой. Вероятности: `memory.random_exploration_probability` (0.05) и `memory.random_sleep_exploration_probability` (0.05) — purpose-карта в одном месте; 0.05 — стартовая настройка, не оптимум (GEN-R27). **OFF (K4) = primary без probability-draw.** (spec §7)

### D7. Стык mca-06 `DreamRandomSource` — расширение без fork

Контракт mca-06 не меняется (`pick(candidates, *, chat_id, purpose, k) -> (items, selection_meta)`, `mca_dream_random.py:37–44`). `await mca_random_source.for_dream(pipeline_run_id, k_hint=top_k)`: K1 OFF → `default_source` (2.58.57); K1 ON → core-адаптер с durably зарезервированным bounded chunk значений (`min(max(2·k_hint+4,8),64)`), `pick` sync/без I/O, `selection_meta` совместим + аддитивен (`provider/batch_id/draw_ids/fallback/fallback_reason`; quantum → `seed=null`); журнал флашится bounded-очередью на следующем async-входе (crash → значения потеряны, не переиспользованы). Инвариант «выбор ≠ вердикт» сохраняется; `MCA_DREAM_RANDOM_EXPLORE_ENABLED` — гейт вызывающего, не дублируется. **OFF (K1) = ровно `default_source`.** (spec §8)

### D8. Настройки — две группы в существующих вкладках; секрет — существующий контур

13 ключей: `memory_random` («Случайность»; `memory.*`; вкладка модуля «Сон» `mod_sleep`) — source/fallback/probabilities (per-chat через `chat_params.get_chat_param`, `chat_params.py:344`); `keys_random` («Случайность: подключение ANU»; `keys.*`; вкладка `llm_providers`, keys-секция) — provider/endpoint/api_key/plan/batch_length/data_type/timeout/watermark/buffer (глобальные; credentials/quota не per-chat). Верхнеуровневых разделов нет. `random.quantum.api_key` — `ParamSpec(secret=True)` в существующем секретном контуре (settings + bot_settings), выдача только `{configured,last4}` (`routes.py:271–278`, `:481`, `:507–508`; `status_service.py:54–66`), скрытие от non-global-admin, не в localStorage/bundle/логах/URL/событиях/таблицах v27 (только `key_fingerprint`). «Проверить подключение» — `POST /api/random/test` (backend-only, RBAC секретных прав, draft-ключ в body, singleflight, очищенная ошибка, проверочные числа в запас, неизвестный ключ не healthy); «Сохранить и применить» — существующий `POST /api/config` + hot-применение без рестарта; выполняющиеся решения — со своей `config_version`. План — только описание, покупки нет. **Δ каталога ≠ 0 (F8 ADR-1026-2 обязателен):** REGISTRY 489→502, GROUPS 105→107, `_TAB_BY_GROUP` 103→105, TAB_RULES 21 in-place, delta 78→91, secret 32→33 (errata: тул-семантика 32→41 / истинных 31→32 — см. «Прод-валидация»), Settings +13, screen-map +13, routes +1, `ROUTES_SHA256_F11` переутвердить. **OFF (K1) = ключи инертны, секрет не отдаётся независимо.** (spec §9)

### D9. Витрина — читающий блок в существующем «Статусе»

Врезка в `GET /api/status` (`routes.py:1637`; JS `UI_STATUS_GRID_V2`) — выбранный/фактический источник, состояние ANU с точным блокером, остаток запаса, последнее пополнение, счётчики quantum/PRNG draws, последняя причина fallback; клик — последние решения из журнала (права/chat scope). **Только чтение** (A35): открытие/повтор не делают QRNG/LLM-вызовов и не меняют поведение. При фактическом PRNG quantum-статус не показывается. Второго виджета/маршрута нет. **OFF (K1) = `disabled/not_run`.** (spec §10)

### D10. Наблюдаемость — один реестр, один словарь, без нового шума

Процесс `random.source` v1 в `mca_process_registry` (stages `activate/receive/buffer/draw/select/fallback/result`; `stages_to_events` на 3 notable-события; `state_source` — v27-таблицы + `task_jobs`; `widget_id="Источник случайности"` — контракт mca-17c; `enabled_gate=MCA_RANDOM_SOURCE_ENABLED`). События через единственный `emit_mca_event` (`mca_events.py:513`, компонент `random`, notable-only): `random_activation`, `random_batch`, `random_fallback`; per-draw событий нет (журнал). `REASON_CODES` — ровно **+2**: `quantum_activated`, `quota_exhausted`; остальное переиспользуется; второй словарь/канал запрещён; существующий агрегат `fallback_total` (`mca_events.py:1009`) не дублируется. **OFF (K1) = событий/стадий нет, registry `not_run`.** (spec §11)

### D11. Kill-switches и env-only лимиты

K1 `MCA_RANDOM_SOURCE_ENABLED` ON (master; OFF = бит-в-бит 2.58.57), K2 `MCA_RANDOM_QUANTUM_ENABLED` ON (OFF = без ANU, effective pseudorandom с причиной `disabled`), K3 `MCA_RANDOM_REFILL_ENABLED` ON (OFF = refill не запускается), K4 `MCA_RANDOM_EXPLORATION_ENABLED` ON (OFF = primary без probability-draw). Env-only ClassVar + `mca_gates.KILL_SWITCHES` + резолверы (per-call, не бросают). Fallback — пользовательская настройка (default true), не kill-switch. Переиспользуются без дублирования: `MCA_DREAM_RANDOM_EXPLORE_ENABLED`, `MCA_EVENT_CONTRACT_ENABLED`, `MCA_TELEMETRY_STORE_ENABLED`, `MCA_OBSERVABILITY_ENABLED`, `MCA_MONEY_LIMITS_ENABLED` (K5 OFF не трогается). Env-only лимиты: circuit 3/60, min interval 1.0, retention 90 дней, cap 10000, Trial 100/мес, 1 rps, hex block size 4. (spec §12)

### D12. Санкции T-4965 — поимённо

Δ DDL = **v27** (4 таблицы + 3 индекса, mca-14, backup-guard, PG no-op); Δ каталога ≠ 0 (+13/+2/+2; F8 обязателен; delta 78→91; secret 32→33 — errata: тул-семантика 32→41 / истинных 31→32, код = +1 секрет, см. «Прод-валидация»); канон инструментов **12** без изменений; reason_code **+2**; секрет — существующий контур, R17; Risk **R3** + `threat-failure-analysis.md` (THR-1…THR-14); deploy **CA-11** bump 2.58.57→**2.58.58**, rollback soft (K1–K4=false) / cold (v27 инертна, v26 мультивалидна); merge **§118**; live — **PENDING OWNER** (реальный ключ, без имитации; до ключа виден блокер). Полная формулировка — spec §13. (spec §13)

---

## AMEND/REUSE-регистр

| # | Отношение | Решение |
|---|---|---|
| **AM-1** | **REUSE/EXTEND ADR-1028-9 (AM-2)** | Стык `DreamRandomSource` — core-источник 10a реализует существующий узкий интерфейс без fork/переписывания пайплайна; контракт mca-06 не меняется. |
| **AM-2** | **AMEND ADR-1027-8 (mca-17a)** | Аддитивная запись процесса `random.source` v1 + 3 notable-события; контракт реестра/trace не меняется. |
| **AM-3** | **AMEND ADR-1027-5 (mca-02)** | ANU-клиент — доверенный провайдер с собственным origin-guard; SafeFetcher/`SAFE_FETCH_TRUSTED_HOSTS` не дублируются и не меняются; коды `invalid_url`/`scheme_not_allowed`/`redirect_blocked` переиспользуются. |
| **AM-4** | **AMEND ADR-1026-2 (F8)** | Δ каталога ≠ 0 — переиздание TSV/meta/screen-map/widget-map/config_diff + фикстур/ассертов обязательно (прецедент `tools/_extra_reissue_f8.py`). |
| **AM-5** | **CONFIRM ADR-1028-13 (mca-11)** | K5 `MCA_MONEY_LIMITS_ENABLED` OFF не трогается; ANU-квота — отдельный локальный счётчик; `financial_limit_*` не используются. |
| **AM-6** | **AMEND ADR-1027-1 (mca-14)** | Клейм версии **v27** для 4 аддитивных таблиц; идемпотентность/backup-guard/PG no-op — по действующему контракту. |

**Supersede-регистр:** пуст — существующие решения не заменяются/не отменяются.

---

## Последствия

- Появляется единственный источник поведенческой случайности (quantum/pseudorandom) с durable-журналом; mca-09/10b/10c используют его через DI без второго контура.
- Владелец получает видимый статус квантовой интеграции и точный блокер; fallback честно различим и не заменяет приёмку подключения; платная подписка не инициируется автоматически.
- Деплой: пер-фичевый bump 2.58.57→2.58.58, миграция v26→v27 с backup-guard; откат — soft-гейты или cold revert (аддитивная схема инертна).
- Риск R3 (внешний провайдер/ключ/квота/crash-семантика/видимый статус) — митигации в `threat-failure-analysis.md`; live-часть — за владельцем.

**✅ Прод-валидация 2.58.58 (VERIFIED 05.10.2026; факты — серверное UTC):** прод ff `9f4989c..12a741a` (feat `cd0a353` 88 файлов; docs `12a741a` 8 файлов; deploy-doc `e6d1616`), рестарт #1 03:36:21 UTC (PID 3806556) + идемпотентный рестарт #2 03:41:25 UTC (PID 3807957, NRestarts=0, ExecMainStatus=0), `/healthz` 200 `2.58.58` ×2 + `/api/health` 200. **DDL v26→v27 применена ровно один раз** (fail-closed guard @03:38:58 UTC: полка `pre_migration_20261005_033640.db` — 1 316 651 008 B (1.317 GB), read-back ok @v26; `user_version` 26→27, книга 15→16 (`(27, random_source)` ×1), таблицы 100→104, 4 `mca_random_*` + 3 индекса; повторный рестарт — no-op). PG **no-op** (26 таблиц; assignments 17 / next 18 / assets 13 / provenance 24 / `llm_usage_events` 2890 — байт-равно pre). Данные целы (`task_jobs` 643→644 live, `mca_events` 10265→10272 live boot, `mca_bot_outputs` 75=75, `summary_runs` 13=13). Kill-switches — **0 env-оверрайдов** (K1–K4 default ON; K5 OFF не тронут). Проверки: локально **108 passed** (A19+B20+C22+D9+E8+JS1+F8 29; вкл. F-1-тест `test_quota_period_rollover_honest_remaining`) + 14 release-pin + 4 JS hotfix (**F-5 closed**), prod-venv **107 passed + 1 skipped** (JS-узел не установлен на проде), `POST /api/random/test` unauth **401**, F8 `--check` OK **502** ×2, 0 ERROR/CRITICAL/Traceback, **R17 = 0** (ANU-ключ нигде; live-ключ не установлен). Review T-4984 **Approved** + addendum «F-1 resolved — quota recheck» (binding HEAD `c49ee02`; WTH-манифест 89 файлов `plans/reports/mca10a_wth_manifest_review.txt`, тело sha256 `424b09d57b47c3fc34459a4ecdfb39e7f9e9353a9b3fd7fadca111337fc10435`; preflight 89/89 drift=0). **Rollback:** soft — K1–K4 `=false` + рестарт (OFF = бит-в-бит 2.58.57; v27 аддитивна/инертна — старый код её не читает); cold — `git revert` `cd0a353` (либо checkout `9f4989c` = 2.58.57; v26 мультивалидна; restore не требуется); аварийный restore-якорь — `pre_migration_20261005_033640.db` (только R18). **Live-приёмка T-4986 — [PENDING OWNER]** (реальный ключ ANU, no-false-acceptance/имитация запрещена; сценарий — `plans/backlog.md` Round 10.38 Follow-up п.1) → затем T-4987 архив/передача. Полная прод-фактура — `deployment.md` (VERIFIED).

**Errata (secret-счётчик, 05.10.2026):** санкционная цифра «secret 32→33» (spec §9/§13.2, D8/D12) не соответствует ни одной реальной семантике счётчика F8-тула: `_is_secret = spec.secret or category==keys` даёт **32→41** (+9 полей `keys_random`), истинных `ParamSpec(secret=True)` — **31→32** (+1 — `RANDOM_QUANTUM_API_KEY`); «33» — арифметическая ошибка санкции (автор считал «+1 секрет» к 32 без учёта keys-семантики тула). Фактический код удовлетворяет сути санкции (единственный новый `secret=True`, существующий секретный контур, маска `{configured,last4}`, в v27 только `key_fingerprint`); код-импакта нет, errata зафиксирована в spec §9/§13 и здесь.

**История ревизий:** 05.10.2026 — Proposed (Step 2 @Architect, design-freeze, T-4964/T-4965; номер свободен, merge-цель §118); 05.10.2026 — **Accepted** (merge §118 + deploy 2.58.58 VERIFIED; live T-4986 — за владельцем).
