# MCA-10a `mca-10a-random-source-anu` — spec (design-freeze, Step 2 @Architect, 05.10.2026)

Фича: **`mca-10a-random-source-anu`** (эпик `memory-context-autonomy`, Wave 3, первая фича волны; MCA10-R1…R4, приёмки A18/A19/A28/A35, §20.2 `:1016/:1021/:1032`, §27.1 `:1355`). Источник — `plans/current_task.md:522–600` (§14.1–§14.4; файл НЕ изменялся, R17). Трассировка REQ/CA — `requirements-map.md`; задачи — `tasks.md` (T-4963…T-4987).

**База (проверено на Step 2):** HEAD `8ea8c1f` (mca-11 deploy-doc), прод **2.58.57**, SQLite **v26** (`schema_migrations` 15; v27 отсутствует — deploy-лог mca-11), каталог **489/105/103/21** (F8 `--check` OK, delta 78), канон инструментов **12**. mca-11 (`b88bfb1`) НЕ трогал `services/mca_dream_random.py`, `services/mca_dream_history.py`, `services/dream_worker.py`, `services/param_catalog.py` (проверено `git show --stat b88bfb1`); `mca_events.py`/`mca_gates.py`/`settings.py` — аддитивно (K5/`cost_unknown`), стыки целы. Решения — `adr-1028-14-random-source-anu.md` (ADR-1028-14; номер свободен, проверено grep 05.10.2026: последний занятый — ADR-1028-13). Санкции — §13. **Статус: `DESIGN_FROZEN`** — Builder T-4966+ не выбирает решений сам.

**Ключевые инварианты:** R17 (ключ ANU/сырой текст не в API/логах/URL/событиях/новых таблицах); один RandomSource, один словарь событий, один write-механизм, один координатор (вторые запрещены); OFF = байт-в-бит 2.58.57; «выбор ≠ вердикт» (случайность не подменяет истинность/уместность/права/деньги); ANU-квота ≠ денежные лимиты mca-11 (K5 OFF не трогается).

---

## 1. Scope и границы

**Входит (10a):** контракт `RandomSource` (quantum/pseudorandom, draw, журнал); ANU-клиент (контракт §14.3, активация, блокеры, квота, fallback); политика exploration (`exploration_probability`/`sleep_exploration_probability`, пул без основного, `no_eligible_alternative`, policy_version); durable-запас/watermark/refill; группа «Случайность» в существующих настройках + секрет; читающий блок «Источник случайности» на витрине; наблюдаемость (процесс/стадии/события/reason_code); kill-switches.

**Не входит:** применения §14.5–14.11 и контракты `ExplorationRequest`/`ExplorationResult` — **mca-10b**; Intent/Decision — mca-09; игровой stub §14.12 — mca-10c; рендер аналитики/диагностические действия — mca-17c; истории — mca-12; опыт/расходы — mca-16; единый релиз/effective state — mca-release. **Граница 10a↔10b:** 10a владеет источником чисел, политикой (семантика primary/alternatives/вероятность) и журналом draw; 10b оборачивает это в `ExplorationRequest/Result` и подключает применения. 10a НЕ создаёт `ExplorationRequest/Result` (второй контракт запрещён); публичный helper 10a возвращает нейтральный `PolicyChoice` (§7).

**Вторые механизмы запрещены:** RandomSource-контур, словарь событий/телеметрии, координатор, контур инициатив, очередь, write-механизм, LLM-провайдер, каталог. Канон инструментов **12** — новых tools/handlers нет (ANU-клиент — сервис, не tool).

---

## 2. D1 — RandomSource: контракт, модуль, режимы, draw, журнал

**Модуль:** один сервис `services/mca_random_source.py` (прецедент «один сервис» mca-08/mca-15). Внутри: `RandomSourceService` (async), `ExplorationPolicy` (чистая логика + инъекция источника), `CoreDreamRandomSource` (sync-адаптер стыка mca-06), `AnuClient` (async), `RandomStore` (доступ к v27-таблицам через `write_transaction`/DatabaseService). Публичных вторых модулей нет.

**Режимы.** Закрытый набор: `quantum` | `pseudorandom`. Настройка `memory.random_source` (catalog; default **quantum** при первом запуске). **Выбранный и фактический источник — разные поля:** selected = настройка (с per-chat override), effective = `quantum` | `pseudorandom`, выводится на каждом draw по доступности и fallback-политике. Режим сохраняется между рестартами (bot_settings); смена применяется без рестарта (hot-резолв per call).

**Draw-API (async; 10b/09 — потребители):**
- `draw_index(n, *, chat_id, purpose, policy_version=None) -> DrawResult` — равномерный индекс `0..n-1` без modulo bias;
- `draw_probability(*, chat_id, purpose) -> DrawResult` — равномерная величина `[0,1)`;
- `choose(primary, alternatives, *, probability, chat_id, purpose, policy_version) -> PolicyChoice` — политика §7.
Каждый draw расходует **отдельное** значение (запрет переиспользования одной величины между решениями и между «проверкой вероятности» и «выбором альтернативы»).

**Rejection sampling (quantum, uint8/uint16):** `limit = (range // n) * n`; значение `v < limit` → индекс `v % n`, иначе повторный draw (bounded: ≤32 попыток; исчерпание → следующий draw/честная причина `validation_failed`, без тихой подмены). `n=1` → draw не расходуется (детерминированный результат). Probability: `v / range` (uint16: `v/65536`). PRNG-путь использует stdlib `random.Random` (auto-seed; `randrange`/`random()` — равномерность библиотеки, своей криптографии нет); реализация/версия фиксируются для диагностики (`source_impl="python-random-mt19937"`, версия Python). PRNG не используется для ключей/токенов/security.

**Журнал draw** (durable, `mca_random_draws`, §3): `draw_id`, `created_at`, `chat_id`, `purpose`, `source` (quantum/pseudorandom), `provider`, `batch_id`, `value` (поведенческое число, не секрет), `candidates_json` (bounded cap 50; только ID/индексы), `pool_size`, `probability`, `policy_version`, `selected_id`, `fallback_reason`, `config_version`. Достаточно для воспроизведения выбора **без новых чисел**. R17-safe: без сырого текста/контента; кандидаты — идентификаторы.

**Purpose (закрытый набор 10a):** `less_studied_periods` (стык mca-06), `activation_selfcheck` (внутренняя проверка активации). Расширение имён — санкция 10b (не переписывая контракт).

**OFF-паритет D1:** `MCA_RANDOM_SOURCE_ENABLED=false` → сервис не используется; dream-пайплайн остаётся на `mca_dream_random.default_source` (ровно 2.58.57); новых записей/событий нет.

---

## 3. D2 — Durable-запас, watermark, refill (Δ DDL v27)

**Решение: additive v27 через реестр mca-14** (`MigrationStep(27)`, идемпотентно, guard `sqlite_master`/`PRAGMA table_info`, PG no-op — GEN-R4), backup-guard fail-closed при деплое. Обоснование против файлового store: кросс-процессный single-writer и «отдельные worker не расходуют один элемент дважды» обеспечиваются только существующим write-механизмом mca-01/`write_transaction`; файловый durable-буфер был бы вторым write-механизмом и не давал бы транзакционной семантики watermark+журнал. v27 свободна (прод v26; v27 отсутствует).

**Объекты v27 (точные имена/колонки фиксированы; CREATE — Builder):**

1. `mca_random_batches` — партия: `batch_id TEXT PK`, `provider TEXT NOT NULL`, `data_type TEXT NOT NULL`, `length INTEGER NOT NULL`, `values_json TEXT NOT NULL` (bounded ≤1024 значений), `reserved_upto INTEGER NOT NULL DEFAULT 0`, `consumed_upto INTEGER NOT NULL DEFAULT 0`, `source TEXT NOT NULL DEFAULT 'quantum'`, `created_at INTEGER NOT NULL` + `idx_mca_random_batches_created(created_at)`.
2. `mca_random_draws` — журнал §2: `draw_id TEXT PK`, `created_at`, `chat_id`, `purpose`, `source`, `provider`, `batch_id`, `value`, `candidates_json`, `pool_size`, `probability`, `policy_version`, `selected_id`, `fallback_reason`, `config_version` + `idx_mca_random_draws_created(created_at)`, `idx_mca_random_draws_chat(chat_id, created_at)`.
3. `mca_random_quota_state` — глобальный учёт (не per-chat): `account_key TEXT PK` (`anu:<plan>`), `period TEXT NOT NULL` (`YYYY-MM`), `success`, `failed`, `unknown` (delivery_unknown), `manual_checks` — INTEGER NOT NULL DEFAULT 0; `last_success_at`, `last_failure_at`, `last_reason`, `updated_at`.
4. `mca_random_state` — состояние активации (одна строка `scope='anu'`): `key_fingerprint TEXT` (`sha256(key)[:12]`, сервер-only детектор смены ключа — НЕ ключ, наружу не отдаётся), `activation_batch_id TEXT`, `activated_at INTEGER`, `last_fallback_reason TEXT`, `last_fallback_at INTEGER`, `updated_at INTEGER NOT NULL`.

**Запас и watermark (crash-семантика).** Draw = одна транзакция `write_transaction`: (a) `UPDATE mca_random_batches SET reserved_upto = reserved_upto + 1 WHERE batch_id=? AND reserved_upto < length` — **выдача диапазона фиксируется до использования**; (b) journal-запись. Crash после (a) может потерять значение, но **повторная выдача уже reserved диапазона невозможна**. `consumed_upto` — диагностика (обновляется после использования, может отставать). Возраст партии показывается, «просроченной» по выдуманному требованию не объявляется.

**Запас ограничен:** `buffer_max_values` (catalog, 2048) — при заполнении новые партии не запрашиваются (refill не стартует); `refill_low_watermark` (256) — порог запуска refill; `batch_length` (1024).

**Refill (фоновые партии, не запрос на каждый draw):** REUSE `TaskSupervisor.run(owner="random.source", kind="refill", coalesce_key="random.refill:<account_key>")` (singleflight; durable `task_jobs`); один refill при старте (если key_present и запас < watermark), далее по расходованию; **никаких периодических запросов с выбрасыванием неиспользованных чисел**. Проверочные числа зачисляются в запас. Bounded: запас ≤ buffer_max, журнал/партии прунятся (env-only retention §12), никаких рекурсивных цепочек.

**OFF-паритет D2:** K1 OFF → refill/запись в v27 не выполняются (таблицы инертны); K3 OFF → refill не запускается (запас только расходуется).

---

## 4. D3 — ANU-клиент (контракт §14.3, безопасность)

**Контракт:** `GET https://api.quantumnumbers.anu.edu.au` (HTTPS), header `x-api-key`, query `length` 1–1024, `type` ∈ {`uint8`,`uint16`,`hex8`,`hex16`}; `size` — только для hex-типов (block size, 1–10). Стартово `length=1024&type=uint16` (без size). Endpoint/header/defaults предзаполнены; владелец вводит только ключ. Параметры перепроверяются при подключении (owner live, T-4986).

**Allowlist/origin (не SSRF):** runtime принимает только `https`, точный host `api.quantumnumbers.anu.edu.au`, порт по умолчанию, без userinfo, путь пустой/`/`; иное → ошибка `invalid_url`/`scheme_not_allowed` (коды mca-02), запрос не выполняется, ключ не отправляется. Endpoint-настройка — owner-only; произвольный сервер невозможен. Клиент — доверенный провайдер: `httpx.AsyncClient` с `follow_redirects=False`, собственный origin-guard; **SafeFetcher (mca-02) не дублируется и не оборачивается** (тот — для пользовательских URL; `SAFE_FETCH_TRUSTED_HOSTS` не меняется). Любой 3xx → `redirect_blocked`, без повторной отправки ключа.

**Валидация ответа:** HTTP status; JSON-схема (`success`, `data`, `type`, `length`); `success=false` → `error`-поле (очищенное от ключа) как reason; тип/диапазон/длина (uint8 0–255, uint16 0–65535, hex-блоки → int с проверкой длины/диапазона); `length` ответа == запрошенной; иначе `validation_failed` (данные не зачисляются).

**Таймауты/повторы:** `request_timeout_seconds` (catalog, 5) — только фоновые/проверочные запросы, **direct flow не задерживает**; backoff с учётом `Retry-After`; circuit breaker: `MCA_RANDOM_CIRCUIT_FAILS` (3) подряд → open на `MCA_RANDOM_CIRCUIT_COOLDOWN_SECONDS` (60) → half-open один probe; in-memory (восстановление при рестарте допустимо, последняя причина durable). 401/403 → `auth_failed`, **без цикла** (breaker); 429 → `quota_exhausted`/`rate_limit`, **без запроса на каждое сообщение** (min interval `MCA_RANDOM_MIN_REQUEST_INTERVAL_SECONDS`=1.0; Trial 1 req/s перепроверяется при подключении).

**Квота (глобальная, не per-chat):** локальный учёт success/failed/unknown/manual_checks в `mca_random_quota_state` по `account_key`+period; один refill/проверка = одна запись; счётчик не дублируется по чатам. **Точный остаток — только при авторитетных данных провайдера, иначе «оценка»**: `Trial` → оценка `limit − (success+failed+unknown+manual)` при `MCA_RANDOM_ANU_TRIAL_MONTHLY_LIMIT` (100, env-only, перепроверяется); `Paid`/`Custom` → локальный счётчик без «остатка»; UI честно помечает «оценка». `delivery_unknown` (таймаут после отправки) учитывается отдельно (unknown) — не success и не failed; оценка помечает неопределённость. Квота ANU **не проходит** денежные лимиты mca-11 (`financial_limit_*` не используются; K5 OFF не трогается).

**OFF-паритет D3:** K2 OFF → ANU-запросы не выполняются (ни refill, ни активация); квота не расходуется.

---

## 5. D4 — Активация, блокеры, авто-возврат

**Активация при первом запуске с ключом:** key_present → проверка соединения (реальная партия по контракту §4) → валидация → зачисление в запас → **внутренний self-check через адаптер** (один draw purpose `activation_selfcheck`, без отправки сообщения в чат) → событие `quantum_activated` → effective=quantum. **HTTP 200 без проверки содержимого ≠ активация; mock/fallback ≠ активация.** Активация подтверждается реальными полученными числами; в CI — детерминированный фикстур клиента, реальный ключ — live/owner (T-4986).

**Блокеры (различимые, видимые):** нет ключа → `provider_unconfigured`; 401/403 → `auth_failed`; 429/исчерпание → `quota_exhausted`; провайдер недоступен → `provider_unavailable`; невалидный ответ → `validation_failed`. Без ключа/при ошибке показывается **незавершённость только квантовой интеграции**; остальные функции работают. После исправления ключа активация — сразу, без релиза/согласования (следующий refill/check; key_fingerprint меняется → состояние `unverified` до успешной проверки; «неизвестный ключ» не показывается healthy).

**Авто-возврат:** при восстановлении провайдера (успешный refill/check после breaker) effective снова quantum, если выбран quantum; событие/причина в журнале.

**OFF-паритет D4:** K2 OFF → активация не выполняется; состояние `disabled` (не «активно»).

---

## 6. D5 — Fallback-политика (честная деградация)

Порядок при недоступности ANU: **(1)** оставшийся квантовый запас → draw quantum; **(2)** запас пуст и `memory.random_fallback_to_pseudorandom=true` → локальный PRNG, событие `random_fallback` (notable, один раз на переход, не на каждый draw) + видимый `effective_source=pseudorandom` + `fallback_reason` в журнале каждого draw; **(3)** fallback выключен → **необязательная** случайная инициатива/исследование откладывается с причиной (`provider_unavailable`/`disabled`); **прямые ответы и обычные несвязанные функции продолжаются**. Чат **никогда не блокируется** ожиданием QRNG (draw — локальное чтение; сеть только в фоне). Fallback **не объявляется** успешной активацией; §20.2 `:1021/:1032` соблюдён.

**OFF-паритет D5:** fallback=false → PRNG-подстановки нет; поведение — отложить необязательное; direct-путь байт-в-бит 2.58.57.

---

## 7. D6 — Политика exploration (10a; потребители — 09/10b)

`ExplorationPolicy.choose(primary, alternatives, *, probability, chat_id, purpose, policy_version) -> PolicyChoice` (нейтральный результат; `ExplorationRequest/Result` — контракт 10b, здесь не создаётся):

- координатор (потребитель) формирует основной + **допустимые** альтернативы; exploration-пул **без основного**;
- **одна проверка вероятности на автономную ситуацию** (не сумма независимых 5%; инвариант для 10b/A29): `draw_probability` один раз; при успехе — один целостный альтернативный кандидат через `draw_index` (отдельный draw; несколько draw допустимы только для корректной выборки, не для «добиться» exploration);
- вероятность: purpose-карта в одном месте — `memory.random_exploration_probability` (0.05) по умолчанию; `memory.random_sleep_exploration_probability` (0.05) для фонового исследования после пакета сна/консолидации (§14.1 `:532`, §14.5 `:612` — потребление в 10b);
- нет допустимых альтернатив / пул без основного → основной + `no_eligible_alternative`; равномерный выбор из альтернатив;
- **недопустимые измерения не рандомизируются**: истинность, идентичность, назначение источника, права, удаление, выполнение прямого запроса, финансовые настройки; выбор не обходит общий фильтр уместности и проверку перед отправкой;
- `policy_version` фиксируется в журнале; 0.05 — стартовая настройка эксперимента, не доказанный оптимум (GEN-R27; формулировки честные).

**OFF-паритет D6:** K4 OFF → `choose` возвращает primary, probability-draw не выполняется (причина `disabled`); поведение потребителей = baseline.

---

## 8. D7 — Стык `DreamRandomSource` (mca-06, без fork)

Контракт mca-06 не меняется: `pick(candidates, *, chat_id, purpose, k) -> (items, selection_meta)` (`services/mca_dream_random.py:37–44`); вызывающий — `services/dream_worker.py:1839–1849`; потребитель meta — `services/mca_dream_history.py:314–321`. mca-10a реализует интерфейс **core-источником**:

- `await mca_random_source.for_dream(pipeline_run_id, k_hint=top_k)` — async-фабрика: K1 OFF → возвращает `mca_dream_random.default_source(pipeline_run_id)` (бит-в-бит 2.58.57); K1 ON → core-адаптер с **durably зарезервированным bounded chunk** значений (резерв = `min(max(2·k_hint+4, 8), 64)`; reserved_upto фиксируется до использования); fallback OFF + пусто → `None` (mca-06-семантика: ранжированный primary-путь);
- `pick` — **sync, без I/O**: маппинг reserved-значений в индексы (rejection sampling), `selection_meta` совместим с mca-06 и аддитивен: базовые `source/purpose/seed/k/pool/picked` (≤200) + `provider/batch_id/draw_ids/fallback/fallback_reason` (для quantum `seed=null` — честно); журнал draw пишется bounded-очередью и флашится на следующем async-входе сервиса (crash до флаша: значения потеряны, повторно не выдаются; журнал — для завершённых решений);
- инвариант «выбор ≠ вердикт» сохраняется (вердикт — только доказательства §5.3 mca-06); `MCA_DREAM_RANDOM_EXPLORE_ENABLED` (mca-06) остаётся гейтом вызывающего, **не дублируется**.

**OFF-паритет D7:** K1 OFF → ровно `default_source` (2.58.57), selection_meta как сегодня.

---

## 9. D8 — Настройки, каталог, секрет, кнопки (§14.4)

**Namespace-маппинг** (owner-ключи → проект; одна запись — один дом; новые категории НЕ создаются):

| Owner-ключ | pg_key | Группа (категория) | Вкладка | per-chat |
|---|---|---|---|---|
| `random.source` | `memory.random_source` | `memory_random` («Случайность») | `mod_sleep` («Сон») | **да** |
| `random.fallback_to_pseudorandom` | `memory.random_fallback_to_pseudorandom` | `memory_random` | `mod_sleep` | да |
| `random.exploration_probability` | `memory.random_exploration_probability` | `memory_random` | `mod_sleep` | **да** |
| `random.sleep_exploration_probability` | `memory.random_sleep_exploration_probability` | `memory_random` | `mod_sleep` | **да** |
| `random.quantum.provider` | `keys.random_quantum_provider` | `keys_random` («Случайность: подключение ANU») | `llm_providers` (секция «Ключи») | нет (глобально) |
| `random.quantum.endpoint` | `keys.random_quantum_endpoint` | `keys_random` | `llm_providers` | нет |
| `random.quantum.api_key` | `keys.random_quantum_api_key` | `keys_random` (**secret=True**) | `llm_providers` | нет |
| `random.quantum.plan` | `keys.random_quantum_plan` | `keys_random` | `llm_providers` | нет |
| `random.quantum.batch_length` | `keys.random_quantum_batch_length` | `keys_random` | `llm_providers` | нет |
| `random.quantum.data_type` | `keys.random_quantum_data_type` | `keys_random` | `llm_providers` | нет |
| `random.quantum.request_timeout_seconds` | `keys.random_quantum_request_timeout_seconds` | `keys_random` | `llm_providers` | нет |
| `random.quantum.refill_low_watermark` | `keys.random_quantum_refill_low_watermark` | `keys_random` | `llm_providers` | нет |
| `random.quantum.buffer_max_values` | `keys.random_quantum_buffer_max_values` | `keys_random` | `llm_providers` | нет |

Дефолты/типы: source select quantum/pseudorandom (default quantum); fallback bool true; exploration/sleep float 0.05 (0..1); provider str «ANU Quantum Numbers» (информационный; runtime принимает только ANU); endpoint str default `https://api.quantumnumbers.anu.edu.au` (owner-only, origin-guard §4); api_key secret str ""; plan select Trial/Paid/Custom (default Trial; **только описание, покупки нет**); batch_length int 1024 (1..1024); data_type select uint8/uint16/hex8/hex16 (default uint16; hex → `size` env-only `MCA_RANDOM_QUANTUM_HEX_BLOCK_SIZE`=4, 1..10, перепроверка live); timeout int 5 (1..30); refill_low_watermark int 256 (< buffer_max); buffer_max_values int 2048 (256..8192). Валидация на чтении: некорректное значение → дефолт + WARNING (не бросает).

**IA:** две группы внутри существующих вкладок (верхнеуровневых разделов НЕТ): `memory_random` — на существующей вкладке модуля «Сон» (`TAB_MOD_SLEEP`, где уже `memory_dream`); `keys_random` — на существующей вкладке «Настройки AI» (`TAB_LLM_PROVIDERS`, keys-секция, существующие права/маска). Подключение (ключ/endpoint) — глобальное; mode/probability/fallback — per-chat через существующий `chat_params.get_chat_param` (`services/chat_params.py:344`; категория memory — per-chat-eligible, non-secret).

**Секрет ANU (R17):** `ParamSpec(secret=True)`, settings-поле `RANDOM_QUANTUM_API_KEY` + `bot_settings` (`keys.random_quantum_api_key`) — существующий секретный контур; выдача API только `key_present`/`{configured,last4}` (`web/api/routes.py:271–278`, `:481`, `:507–508`; `status_service._mask_key_for_role:54–66`); non-global-admin не видит вовсе; **не в localStorage/bundle**; **не в новых таблицах** (в v27 хранится только `key_fingerprint`, §3); не в логах/URL/событиях; save/delete — существующими правами управления секретами; отмена запроса не оставляет ключ в логах/URL (ключ — только в POST-body).

**Кнопки:** «Проверить подключение» — backend-only `POST /api/random/test` (новый, +1 route; RBAC global admin/секретные права; draft-ключ в body, не в URL, не эхо; singleflight на повторные клики + min interval; ответ: status/latency/дата/размер партии/очищенная ошибка/key_present; проверочные числа зачисляются в запас; неизвестный ключ не healthy до успешной проверки). «Сохранить и применить» — существующий `POST /api/config` (routes.py:585) + hot-применение без рестарта (ConfigCache); выполняющиеся решения завершаются со своей `config_version`.

**Δ каталога (санкция §13.2, F8 ADR-1026-2 — переиздание обязательно):** REGISTRY 489→**502** (+13), GROUPS 105→**107** (+2), `_TAB_BY_GROUP` 103→**105** (+2), TAB_RULES **21** in-place (memory-set `mod_sleep` + `keys_random` в keys-set `llm_providers`), delta 78→**91**, Settings-поля +13, secret-строки 32→**33**, hidden 2 без изменений, screen-map +13 строк, widget-map — без нового виджета (блок на «Статусе»); переиздать TSV/meta/screen-map/widget-map/config_diff, обновить `tests/fixtures/round1025/*` и ассерты (прецедент `tools/_extra_reissue_f8.py`; `test_round1025_f8_registry.py`), routes-set +1, `ROUTES_SHA256_F11` переутвердить осознанно (L-F11S-1).

**OFF-паритет D8:** K1 OFF → ключи инертны (значения читаются, runtime-эффектов нет); секрет не отдаётся независимо от гейтов; registry/витрина — честный `disabled/not_run`.

---

## 10. D9 — Блок «Источник случайности» на витрине (§14.4, читающий)

Врезка в существующий «Статус» (`GET /api/status` routes.py:1637; JS-грид `UI_STATUS_GRID_V2`), **не новый маршрут/раздел**. Показывает: выбранный и **фактический** источник; состояние ANU (unconfigured/unverified/active/degraded/quota, с точным блокером); остаток запаса; последнее успешное пополнение (дата/размер/возраст); число quantum/PRNG draws; последнюю причину fallback. Клик — последние решения из журнала (purpose, кандидаты в рамках прав/chat scope, выбранный, source, fallback). **Только чтение:** открытие/повтор не делают QRNG/LLM-вызовов и не меняют поведение бота (A35-инвариант). При фактическом PRNG **не показывать quantum-статус** (честно `pseudorandom` + блокер). Данные — из `mca_random_draws/batches/quota_state/state`; второй виджет не создаётся (расширение — 10b/визуализация — 17c/10b).

**OFF-паритет D9:** K1 OFF → блок отдаёт `disabled/not_run` без данных.

---

## 11. D10 — Наблюдаемость (mca-17a/mca-13, без второго канала)

**Процесс** `random.source` v1 в `services/mca_process_registry.py` (после `:203+`): stages `("activate","receive","buffer","draw","select","fallback","result")`; `stages_to_events={"activate":"random_activation","receive":"random_batch","fallback":"random_fallback"}`; `instrumentation=("activate","receive","fallback")`; `state_source=("mca_random_batches","mca_random_draws","mca_random_quota_state","task_jobs")`; `settings_ref` — K1–K4 + `MCA_DREAM_RANDOM_EXPLORE_ENABLED`; `enabled_gate="MCA_RANDOM_SOURCE_ENABLED"`; `widget_id="Источник случайности"` (контракт для mca-17c); `recovery_ops=("refill_resume","draw_reconcile")`; `trigger_kind="background"`; note: draw/select/result — durable-журнал (не событийный поток; без нового шума). OFF → честный `disabled/not_run`.

**События — notable-only через единственный `emit_mca_event`** (`services/mca_events.py:513`; компонент `random`): `random_activation` (stage activate; success/failed; reason `quantum_activated`/`provider_unconfigured`/`auth_failed`/`quota_exhausted`/`provider_unavailable`/`validation_failed`); `random_batch` (stage receive; refill/check; success/failed; reason `provider_unavailable`/`timeout`/`rate_limit`/`validation_failed`/`quota_exhausted`/`delivery_unknown`); `random_fallback` (stage fallback; reason `random_fallback` при переходе на PRNG / `provider_unavailable` при отложенном необязательном). Per-draw событий НЕТ (журнал). Существующий агрегат `fallback_total` (`mca_events.py:1009`) продолжает считать `random_fallback` — не дублируется.

**reason_code: ровно +2** в единственный `REASON_CODES` (`mca_events.py:60–245`): **`quantum_activated`**, **`quota_exhausted`**. Переиспользуются: `provider_unavailable`, `provider_unconfigured`, `auth_failed`, `random_fallback`, `validation_failed`, `timeout`, `rate_limit`, `delivery_unknown`, `disabled`, `no_eligible_alternative`, `invalid_url`, `scheme_not_allowed`, `redirect_blocked`. Второго словаря нет.

---

## 12. D11 — Kill-switches и env-only лимиты

Kill-switches — env-only `ClassVar[bool]` в `config/settings.py`, реестр `mca_gates.KILL_SWITCHES` + резолверы (per-call, не бросают):

| # | Имя | Default | OFF-паритет |
|---|---|---|---|
| K1 | `MCA_RANDOM_SOURCE_ENABLED` (master) | ON | бит-в-бит 2.58.57: dream = `default_source`, ANU/refill/journal/витрина не активны |
| K2 | `MCA_RANDOM_QUANTUM_ENABLED` | ON | ANU-запросов/активации нет; при K1 ON effective=pseudorandom с причиной `disabled` |
| K3 | `MCA_RANDOM_REFILL_ENABLED` | ON | фоновый refill не запускается (запас только расходуется) |
| K4 | `MCA_RANDOM_EXPLORATION_ENABLED` | ON | политика возвращает primary; probability-draw нет |

Все default **ON** (owner-интент: quantum при наличии ключа). Fallback — пользовательская настройка (`memory.random_fallback_to_pseudorandom`, default true), не kill-switch. Переиспользуются и **не дублируются**: `MCA_DREAM_RANDOM_EXPLORE_ENABLED` (mca-06 — гейт вызывающего), `MCA_EVENT_CONTRACT_ENABLED`/`MCA_TELEMETRY_STORE_ENABLED` (mca-13), `MCA_OBSERVABILITY_ENABLED` (mca-17a), `MCA_MONEY_LIMITS_ENABLED` (mca-11; K5 OFF — не трогается).

Env-only технические лимиты (не каталог): `MCA_RANDOM_CIRCUIT_FAILS`=3, `MCA_RANDOM_CIRCUIT_COOLDOWN_SECONDS`=60, `MCA_RANDOM_MIN_REQUEST_INTERVAL_SECONDS`=1.0, `MCA_RANDOM_DRAW_RETENTION_DAYS`=90, `MCA_RANDOM_DRAW_MAX_ROWS`=10000, `MCA_RANDOM_ANU_TRIAL_MONTHLY_LIMIT`=100, `MCA_RANDOM_ANU_TRIAL_RPS`=1, `MCA_RANDOM_QUANTUM_HEX_BLOCK_SIZE`=4.

---

## 13. D12 — Санкции T-4965 (поимённо)

1. **Δ DDL = additive v27** (`MigrationStep(27)`, mca-14): 4 таблицы + 3 индекса (§3), идемпотентно, PG **no-op**, backup-guard fail-closed при деплое, повтор — no-op; v27 свободна (прод v26). Файловый store отклонён (второй write-механизм).
2. **Δ каталога ≠ 0**: точные значения §9 (+13 ключей, +2 группы, +2 tab-маппинга, TAB_RULES 21 in-place, delta 78→91, secret 32→33, Settings +13) + обязательное F8-переиздание по ADR-1026-2 (артефакты/фикстуры/ассерты; routes +1, `ROUTES_SHA256_F11` переутвердить).
3. **Канон инструментов 12** — без изменений; новых tools/handlers нет.
4. **reason_code: ровно +2** — `quantum_activated`, `quota_exhausted` (§11).
5. **Секрет ANU**: существующий секретный контур (`ParamSpec(secret=True)`, `keys.random_quantum_api_key`); выдача `{configured,last4}`/скрытие; не в localStorage/bundle/логах/URL/событиях/таблицах v27 (только `key_fingerprint`); R17.
6. **Risk: R3** (подтверждение планового `mca-round1027-plan.md:205`) — внешний провайдер/ключ/квота/durable crash-семантика/DDL/видимый статус активации; `threat-failure-analysis.md` обязателен (THR-1…THR-14).
7. **Deploy: CA-11 per-feature bump** `APP_VERSION 2.58.57 → 2.58.58` (прецедент mca-06/08/15/11), пер-фичевый; проверки: health/версия, backup-guard+миграция v26→v27 идемпотентно (повтор no-op), PG no-op, kill-switches default ON 0 env-оверрайдов, R17=0, F8 `--check` OK 502, focused-повтор; **rollback:** soft — K1–K4=false (+ вернуть `memory.random_source=pseudorandom` при необходимости), cold — git revert (v27 аддитивна/инертна; v26 мультивалидна).
8. **Merge:** `plans/ARCHITECTURE.md` **§118** + ADR-1028-14 → Accepted (по merge). Booking v27 фиксируется здесь и в ADR-1028-14 D2 (arch-frames/process-journal — вне diff этого шага).
9. **Live (PENDING OWNER, no-false-acceptance `:15167`):** реальный ключ ANU предоставляет владелец; активация quantum с реальной партией проверяется live (T-4986), без mock/fallback; до ключа — видимый блокер только квантовой интеграции, §20.2 `:1021/:1032`.

---

## 14. REQ → приёмки → задачи

| REQ | Решения spec | Приёмки | Задачи |
|---|---|---|---|
| MCA10-R1 | D6 (+D1, D2) | A18 `:899` (A29 — зона 10b) | T-4966, T-4967 |
| MCA10-R2 | D1, D2, D3, D4, D5, D7 | A18/A19 `:899–900`, A28 `:909` | T-4966–T-4975 |
| MCA10-R3 | D3, D4, D5 | A19 `:900`, A28 `:909` | T-4971–T-4975 |
| MCA10-R4 | D8, D9 | A19/A28, A35 `:916` (частично) | T-4976–T-4980 |
| GEN-R17 / §27.1 | D10 | A48/A73 (частично) | T-4981, T-4982 |
| Санкции/ревью | §13 | §19 `:874–976` | T-4983, T-4984 |
| Deploy/live/reconcile | §13.7–13.9 | §20 `:986–1045` | T-4985–T-4987 |

## 15. OFF-паритет по решениям

D1→K1, D2→K1/K3, D3→K2, D4→K2, D5→`memory.random_fallback_to_pseudorandom=false` (direct-путь 2.58.57), D6→K4, D7→K1, D8→K1, D9→K1, D10→K1 (событий/стадий нет, registry `not_run`), D11→K1–K4. Каждый OFF = поведение 2.58.57 для соответствующего пути; дефолты ON не меняют baseline-поведение аддитивно (активация quantum происходит только при наличии ключа и K2 ON).

## 16. Статус

`DESIGN_FROZEN` — санкции §13 обязательны для T-4966+; `plans/current_task.md` не изменялся (R17); runtime/test-код на Step 2 не менялся. Следующий шаг — @Builder T-4966+ (блок A) без дополнительных решений; live-часть — PENDING OWNER.
