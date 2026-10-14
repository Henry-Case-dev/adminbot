# Отчёт @Scanner — раунд 10.18, БАТЧИ 1–4 + итог эпика (ШАГ 6 OpenSpec, Strict Workflow)

> **Сканер:** @Scanner (независимый diff-аудит логических ошибок). **Дата:** 15.09.2026.
> **Baseline HEAD:** `118a03c` (docs-синхронизация 10.17); прод — `b6c153f`.
> **Объём:** незакоммиченный `git diff` + untracked — **F7 `settings-worker-sync`** (T-1759…T-1764)
> и **F1 `betterstack-us-region-401`** (T-1703…T-1711).
> **Режим:** код НЕ правился; искались реальные баги/риски/регрессии (не стиль и не спек-комплаенс — это @Reviewer).
> **Метод:** `git status/diff` → адресные чтения `file:line` → сравнительный grep (`logtail`, `hot.get` по воркерам,
> `gates_enabled`) → инструментальные пробы (полный pytest, интроспекция каталога).
> **⏱ Итерация 2 (после фиксов @Builder):** статусы находок и новые пункты — в §7 (ниже);
> итог итерации 2: **0 Critical / 0 High** (S10.18-1 закрыт), открыто 1 Medium + 2 Low + 5 Info.
> Валидатор итерации 2: pytest **6052 passed / 0 failed**, JS-гейты OK, `git diff --check` exit 0.
> **⏱ Итерация 3 — БАТЧ 2 (F2 `sleep-manual-cascade-badges`, 15.09.2026): см. §8.** Закрыты
> S10.18-15/-16/-17; новые находки S10.18-21…-28 (2 Medium / 2 Low / 4 Info); итог: 0 Critical / 0 High.
> Валидатор Батча 2: pytest **6083 passed / 0 failed**, JS-гейты OK, `git diff --check` exit 0, каталог Δ=0.
> **⏱ Итерация 4 — БАТЧ 3 (F3 `graph-density-scoring-stoplist` + F4 `graph-physics-stabilization`, 15.09.2026): см. §9.**
> Закрыты S10.18-21/-22/-23/-24/-25/-26; новые находки S10.18-29…-34 (1 Medium / 1 Low / 5 Info); итог: 0 Critical / 0 High.
> Валидатор Батча 3: pytest **6104 passed / 0 failed**, JS-гейты OK, `git diff --check` exit 0, каталог Δ=0
> (SQLite v10 — миграция `edges.fact_id`).
> **⏱ Итерация 5 — БАТЧ 4 (F5 `metafact-penalty-extractor-prompt` + F6 `role-matrix-settings-actualization`, 15.09.2026): см. §10**
> (новые находки S10.18-35…-38: 1 Low / 3 Info; **итоговая сводка эпика — §10.4**).
> Валидатор Батча 4: pytest **6137 passed / 0 failed**, JS-гейты OK, `git diff --check` exit 0, каталог Δ=0.
> **ЭПИК 10.18 (F1–F7): 0 Critical / 0 High → готов к @Reviewer/@PM → Merge/архивация/деплой.**
> **⏱ Пост-фикс-актуализация (15.09.2026, @Builder fix-pass): см. §10.6** — §10.4 ниже отражала устаревший
> статус S10.18-30 (копия §9 без перепроверки); фактически перф ×2-фазы закрыт. Итог после фикс-прохода:
> открыто **0 Medium + 1 Low (S10.18-29) + 10 Info**; S10.18-30/-35/-36 — **CLOSED**.

## 0. Сводка (итерация 1 — историческая, 15.09.2026)

| Severity | Кол-во | Коды |
|---|---|---|
| **Critical** | **0** | — |
| **High** | **1** | S10.18-1 |
| **Medium** | **5** | S10.18-2, S10.18-3, S10.18-4, S10.18-5, S10.18-6 |
| **Low** | **5** | S10.18-7 … S10.18-11 |
| **Info** | **3** | S10.18-12, S10.18-13, S10.18-14 |

Обе фичи батча реализованы по своим ADR: приоритет `chat overrides → hot.get → settings-дефолт` в accessor'е
воспроизводит семантику `chat_params._resolve_from_root` (каст/`_cast_type_ok`/`math.isfinite`); «сентинел»
`worker_settings._global_with_source` реально проходит `_coerce` без изменений (проверено по `_cast_to_type` —
все 5 типов возвращают значение как есть для `object()`); kill-switch `flags.<feature>_enabled` побеждает
`fallback` (R10.18-3); LISTEN поднят на **отдельном** `asyncpg.connect` (не `Pool.add_listener`), с backoff и
rate-limited WARNING; BetterStack-хендлер без хоста не создаётся (`ValueError` в ctor — `DEFAULT_HOST=""`),
`extract_sentry_public_key`/`token_equals_sentry_public_key` — точное сравнение через `hmac.compare_digest`;
`logtail-python` удалён из `requirements.txt`, оставшихся импортов нет (grep пуст).

Полный прогон подтверждён: **6042 passed / 1 failed** (pre-existing
`tests/test_tool_download_quality_round1017::TestSchemaAndAdr::test_adr_supersede_recorded` — stale doc-path).
Каталог: **REGISTRY 436 / Settings 406 / categorized 411 / GROUPS 90 / mapped 88 / TAB_RULES 19 /
CONFIG_TAB_TITLES 19** (интроспекция `param_catalog`).

Блокирует переход к следующему батчу **S10.18-1 (High)** — per-chat суточные лимиты Сна сравниваются с
глобальными счётчиками (per-chat override либо глушит чат чужим расходом, либо не даёт своего бюджета).

## 1. Findings

| ID | Sev | File:line | Суть | Рекомендация |
|---|---|---|---|---|
| S10.18-1 | **High** | `services/dream_worker.py:598-600,617-639,741-758`; `services/database.py:1976,1985` | **Per-chat лимиты Сна учитываются по ГЛОБАЛЬНОМУ расходу.** `_daily_limit_for(chat_id,…)`/`_budget_reason_for(chat_id,…)` резолвят `memory.dream_distillations_per_day`/`_tokens_per_day` **по чату**, а счётчики берутся без чата (`count_dream_log(day_start, kind="distilled")`, `sum_dream_log_tokens(day_start)`) — DB-методы вообще не принимают `chat_id`. Итог: при per-chat override (главный сценарий F7) лимит чата сравнивается с суммой по ВСЕМ чатам → чат A глушится расходом чата B; либо override 50 даёт чату A долю общего счётчика. В дефолте (без override) поведение совпадает со старым, поэтому регресс скрыт до первой per-chat настройки. | Добавить `chat_id` в `count_dream_log`/`sum_dream_log_tokens` (`AND chat_id = ?`) и считать `distilled_today`/`tokens_today` per-chat в `_process_chat`; near-limit-проверку — по тем же per-chat числам. Если глобальный учёт осознан (worker_budget) — зафиксировать в ADR и UI, что `distillations_per_day`/`tokens_per_day` — глобальные ключи (убрать per-chat резолв). |
| S10.18-2 | Medium | `services/dream_worker.py:1196-1203` (ср. `1178-1182`, `1262-1266`) | **`memory.deep_sleep_trigger` НЕ резолвится по чату в `_deep_tick`** (в отличие от `_maybe_deep_after_sleep`, где триггер читается per-chat). Чат с override `trigger='fixed'` при глобальном `'after_sleep'`: `_deep_tick` делает ранний return (глобально «after_sleep»), а after_sleep-хук пропускает чат (per-chat триггер ≠ 'after_sleep') → глубокий сон для чата не запускается никогда; `_run_deep_once` триггер вообще не проверяет (обратный кейс: global 'fixed' прогонит чат, у которого override 'after_sleep'). Ключ входит в обязательный P0-набор ADR-1018-7 D3, но spec §4.2 разрешает для `_deep_tick` «глобальный резолв + per-chat фильтр» — т.е. spec и ADR расходятся, код следует spec. | Либо реализовать per-chat фильтр кандидатов в `_deep_tick` (чаты с override `fixed` + свой час), либо явно вырезать `memory.deep_sleep_trigger` из P0-списка ADR D3 и внести остаточный РАЗРЫВ в таблицу spec §2.3/backlog. |
| S10.18-3 | Medium | `web/api/gates.py:68`; `services/feature_gates.py:190-201`; `services/oversight.py:172`; `web/api/memory_agi.py:452-459` | **Расхождение «эффективный гейт воркера» ↔ «статус гейтов».** Воркер зовёт `gates_enabled(…, fallback=per-chat master)`, а `GET /api/chat/{id}/gates`, `allowed_features`, oversight-heavy — без `fallback`: при per-chat `memory.dream_enabled=true` + глобальном `false` воркер фактически работает, а UI «Гейты/Тяжёлые фичи» показывает `dream=false` (симптом «UI OFF, бэкенд ON» на другом экране). Симметрично `cognition_status.dream.enabled` не учитывает kill-switch `flags.dream_enabled=false` → статус «включено», воркер скипает (`[dream] WARNING skip: gate dream`). Риск R4 spec §8 закрыт лишь документально. | В `gates_get`/`allowed_features`/`oversight` передавать тот же `fallback` (резолв master-флага через `worker_settings`) — или разделить контракт: отдавать `gate` (kill-switch) и `effective` (с fallback) отдельными полями (R16-аддитивно). |
| S10.18-4 | Medium | `services/dream_worker.py:307-345,430-434,966-985` | **Побочное включение belief-decay.** `start()` теперь регистрирует `dream_tick` ВСЕГДА → `_run` всегда вызывает `_maybe_decay`, а её гейт — только `flags.belief_decay_enabled` (default False, но в PG может быть True). При `dream_enabled=false` + decay=true beliefs начнут декаиться/архивироваться (раз в `BELIEF_DECAY_INTERVAL_DAYS`) — ранее этот путь был недостижим при выключенном Сне. В spec/ADR 10.18 этот побочный эффект не описан. | Явно решить и зафиксировать: (а) decay — независимая подфича (тогда ок, добавить тест/строку в ADR), либо (б) гейтить `_maybe_decay` дополнительно `memory.dream_enabled` (per-chat-агностично — глобально). До решения — проверить прод-значение `flags.belief_decay_enabled`. |
| S10.18-5 | Medium | `services/dream_worker.py:378-382,413-417,1148-1187,1214-1254` | **Ручной обычный прогон уходит в дорогой deep-каскад.** `run_once(chat_id, deep=False)` → `_maybe_deep_after_sleep(stats, manual=True)` запускает Глубокий сон по ВСЕМ `_last_chat_ids` (до `max_chats_per_run`), **игнорируя** `flags.deep_sleep_enabled`/`trigger`, а `_run_deep_all(manual=True)` не делает `break` после первого успеха → один клик «Сон сейчас» = до 10 LLM-прогонов «Моста времени». Это осознанный задел F2 (ADR-1018-2 D2/D4), но в текущем батче обход kill-switch для manual ещё не реализован (F2 T-1715), поэтому возможен разрыв: обычный Сон скипнут гейтом, а deep-каскад всё равно ушёл. Ограничитель — только `_deep_budget_ok` (`limits.deep_sleep_tokens_per_day`). | Подтвердить, что задел F2 принят в этом батче; при каскаде manual добавить учёт/лимит числа deep-прогонов и лог `cascade=deep|traits` (как в ADR-1018-2 D4), чтобы API-ответ отражал фактический каскад. |
| S10.18-6 | Medium | `bot.py:141-198`; `plans/features/betterstack-us-region-401/spec.md:33,141-148` | **Fail-safe BetterStack — «тишина вместо 401».** Без `BETTERSTACK_HOST` хендлер не создаётся вообще (это правильно по ADR-1018-1 D2), но маркер — WARNING, не ERROR; в прод-`.env` переменной ещё нет → после деплоя логи в панель прекратятся полностью до шага @DevOps (T-1710). Явного ERROR/алерта нет; `/api/status/logs` покажет только WARNING. | Временно выдавать ERROR-маркер (или добавить поле в `/healthz`/Статус «betterstack: disabled (no host)»), чтобы потеря панели была видна мониторингу; либо деплоить код и `.env` одним шагом (порядок T-1710 → рестарт). Принято спекой §8/R3, поэтому Medium, не High. |
| S10.18-7 | Low | `services/chat_params_notify.py:125-135`; `bot.py:1005-1010,824-830` | `ChatParamsNotify.stop()` — **мёртвый код**: bot.py отменяет raw-таску напрямую (`task.cancel()`+`await`), а не вызывает lifecycle-метод. Это расходится с конвенцией `LoreNotify.stop()` (`bot.py:829-830`) и оставляет `stop()` непокрытым тестами (тесты тоже используют `task.cancel()`). | Либо вызывать `await _chat_params_notify.stop()` в `on_shutdown()` (как lore_notify), либо удалить метод и оставить только cancel-путь (тогда убрать `_stop`/`_task`-обвязку). |
| S10.18-8 | Low | `bot.py:565-566`; `plans/ARCHITECTURE.md:161,211,223`; `README.md:676,1044-1045` | **Stale-документация vs код батча.** `bot.py:565-566` всё ещё «Джоб регистрируется ТОЛЬКО при memory.dream_enabled (default false)» — устарело (теперь всегда). `ARCHITECTURE.md:211` описывает `host="in.logs.betterstack.com"` дефолт и токен-алиас `BETTERSTACK_SOURCE_TOKEN`; `:223` — функции `looks_like_sentry_public_key`/`betterstack_source_env_name` и маркер `from=%s`, которых в коде нет (grep — 0); `README.md:676` — «BETTERSTACK_SOURCE_TOKEN, LOGTAIL — запасной алиас» (код читает только `LOGTAIL_SOURCE_TOKEN`). | Обновить 3 файла под фактический контракт батча (host обязателен; только `LOGTAIL_SOURCE_TOKEN`; `token_equals_sentry_public_key`; `last4`-маркер); stale-функции в ARCHITECTURE.md §16 удалить/заменить. |
| S10.18-9 | Low | `plans/features/betterstack-us-region-401/spec.md:7,153-155`; `tasks.md:70`; `scripts/betterstack_host_token_probe.py:33-40` | **Спека F1 противоречит своим таскам:** §9 Q4 (и строка 7 «закрыты в пользу рекомендаций») рекомендует **оставить** `logtail-python` до ревизии smoke, а T-1706 фиксирует удаление — удалено (импортов нет, корректно). Плюс docstring `mask(keep=0)` обещает «длина скрыта полностью», фактически число звёздочек = длине секрета. | Синхронизировать §9 Q4 спеки с T-1706 (или пометить решение владельца); поправить docstring `mask` («длина раскрывается как число `*`»). |
| S10.18-10 | Low | `tests/test_settings_worker_sync_round1018.py:412-432` | **Тест-изоляция:** `TestListenerFailOpen` делает `importlib.reload(config.settings)` + повторный `import bot`; reload остаётся в `sys.modules` на весь прогон (в `config.settings.settings` — тестовые env: пустые токены, `API_TOKEN=123456:...`). Паттерн заимствован из `tests/test_betterstack_handler.py`, прогон зелёный (6042/1), но порядок тестов при `pytest-randomly` может дать флейки. | Вынести «bot-импорт с env» в фикстуру с восстановлением `sys.modules`/повторным reload после теста (или проверять `_start_chat_params_listener` без импорта bot). |
| S10.18-11 | Low | `services/chat_params_notify.py:139-158` | `_on_notify` создаёт **неотслеживаемый** `asyncio.create_task(self._safe_invalidate(payload))`; при shutdown / закрытии loop возможен «Task was destroyed but it is pending», нет агрегации/ограничения на всплеск NOTIFY. Прецедент `LoreNotify`, но новый модуль мог быть чище. | Хранить set задач и отменять их в `stop()`, либо переиспользовать один worker-queue (deque + single consumer). |
| S10.18-12 | Info | `services/nostalgia_worker.py:131,148-155`; `plans/backlog.md` (10.18) | **Остаточный РАЗРЫВ spec §2.3 (осознанно вне P0):** `NostalgiaWorker` читает `memory.nostalgia_*` только через `hot.get` и регистрирует джоб только при флаге глобального слоя — аналог симптома Сна не исправлен, зафиксирован backlog-задачей T-1764 (перенос на `worker_settings`). `lore_worker`/`self_reflection`/`bot_persona` — вне P0-скоупа F7 (persona-гейт уже per-chat, эталон). | Держать как backlog-задачу раунда 10.18; при реализации Nostalgia — сразу `_key_for`-паттерн + per-chat статус с `source`. |
| S10.18-13 | Info | `plans/archive/security-rotation-finalize-round1016/spec.md:35` | **Pre-existing утечка фрагмента (R10.18-12).** В отслеживаемом архиве на строке 35 присутствует фрагмент SSH-пароля раунда 10.16 (в отчёт значение НЕ копируется; ротация CANCELLED). Не входит в батч 1, шаг 7 не блокирует. | Вычистить строку плейсхолдером (`<маркер>`), отдельной задачей проверить `git log -p`/историю и согласовать с владельцем возможный rewrite (`filter-repo`) — как уже записано в `plans/backlog.md` (10.18, R10.18-12). |
| S10.18-14 | Info | инварианты | **Проверено чисто:** `logtail`-импортов/пина нет (grep 0); DDL нет (`database.py`/`pg_db.py` вне диффа, SQLite v9); каталог 436/406/411/90/88/19 (Δ=+1 — санкционированный F1 `BETTERSTACK_HOST`); порядок роутеров `bot.py` не тронут; `_key`/`_window_open`/`_daily_limit`/`_budget_reason` сохранены (обратная совместимость); новые параметры добавлены аддитивно (R16); секреты в логи не попадают (`last4`-маска для токена <4 симв.), `sanitize` жив. | — |

## 2. Детали ключевых находок

### S10.18-1 (High) — per-chat бюджет vs глобальный счётчик

- `services/dream_worker.py:617-618` → `reason = await self._budget_reason_for(chat_id, distilled_today, tokens_today)`;
  внутри `:741-758` лимиты резолвятся по чату (`_key_for` → `memory.dream_*_per_day`).
- `:598-600` → `distilled_today = await self.db.count_dream_log(day_start, kind="distilled")`,
  `tokens_today = await self.db.sum_dream_log_tokens(day_start)` — **без chat_id**;
  `services/database.py:1976` / `:1985` сигнатуры `chat_id` не имеют вовсе.
- Итог: `limit(chat) - used(ALL)`. Пример: у чата B per-chat `distillations_per_day=3`, у чатов A+C сегодня уже
  10 дистилляций → чат B остановлен (`budget distillations reached`) до первой своей дистилляции.
  Инструментально подтверждено сигнатурами DB-методов; автотеста на per-chat бюджет нет
  (`tests/test_settings_worker_sync_round1018.py` проверяет только резолв `_key_for`, не бюджеты).
- Рекомендация: `count_dream_log(since_ts, *, kind, chat_id=None)` + `sum_dream_log_tokens(..., chat_id=None)`
  (SQLite `AND chat_id = ?`), near-limit-проверка `:626-633` — по per-chat числам; `memory_dream_log.kind='decay_run'`
  пишется с `chat_id=0` (глобально) — фильтр должен это учитывать.

### S10.18-3 (Medium) — два «источника правды» на гейт

- Воркер: `services/dream_worker.py:587` → `gates_enabled(chat_id, "dream", fallback=enabled)`.
- Отображение: `web/api/gates.py:68` (GET gates), `services/feature_gates.py:199-200` (`allowed_features`,
  используется API/сводкой), `services/oversight.py:170-173` (heavy для карточек) — **без** `fallback`.
- `feature_gates.gates_enabled` порядок: chat-gate → explicit kill-switch → `fallback` → global → False
  (`:106-121`). Значит без `fallback` результат при per-chat master-ON и глобальном OFF = **False**, у воркера = **True**.
- `cognition_status` дополнительно не учитывает kill-switch (показывает master-флаг).

### S10.18-2 (Medium) — триггер глубокого сна

- `_deep_tick:1196-1199` — `resolve_setting_cached("memory.deep_sleep_trigger")` **без chat_id**; далее
  `if trigger != "fixed": return`, затем `_run_deep_all(None, manual=False)` по кандидатам.
- `_maybe_deep_after_sleep:1178-1182` — триггер per-chat (и только `== 'after_sleep'`).
- `_run_deep_once:1261-1266` — per-chat только `flags.deep_sleep_enabled`, триггер не проверяется.
- Следствие: per-chat `trigger='fixed'` неисполним; per-chat `trigger='after_sleep'` при global `fixed`
  может получить deep в фиксированный час (семантика override нарушена).

## 3. Верифицировано чисто (доказательства)

- **Accessor (T-1759):** `worker_settings._global_with_source` использует `hot.get(key, _SENTINEL)`; проверено, что
  `_cast_to_type` (`param_catalog.py:1966-2034`) для int/float/bool/json/str возвращает `object()`-сентинел как есть
  (ни одна ветка не кастует произвольный объект) → `source='default'` корректен. `_chat_with_source` повторяет
  `normalize_value` + `_cast_type_ok` + `math.isfinite` — семантика `_resolve_from_root` не раздвоена.
- **Приоритет (симптом владельца):** per-chat override ON + global OFF → `source='chat'`, значение `True`
  (`test_regression_symptom_ui_on_chat_off_global`); kill-switch `flags.dream_enabled=false` побеждает `fallback`
  (`test_kill_switch_beats_per_chat_fallback`, `feature_gates.py:113-117`).
- **Обратная совместимость `gates_enabled` без `fallback`:** для всех прочих вызовов
  (`lore_worker:316`, `nostalgia_worker:287`, `oversight.py:172`, `web/api/gates.py:68`, `web/api/oversight.py:106`)
  добавление `_explicit_flag_value` не меняет результат: `flags.<feature>_enabled` и первый ключ `_global_flag_value`
  — один и тот же ключ; при `None` управление уходит в `_global_flag_value` (2-й ключ `memory.*_enabled`) как раньше.
- **START всегда (T-1761):** `start()` регистрирует оба джоба с `replace_existing=True`, `max_instances=1`,
  `coalesce=True`; повторный `start()` идемпотентен; `_tick` уважает `_run_lock` (ранний return, активный прогон не
  прерывается) — тест `test_lock_held_tick_returns_and_does_not_interrupt_run`. Двойного запуска при рестарте нет.
- **LISTEN (T-1764):** слушатель на **отдельном** `asyncpg.connect` + `_init_connection` (у `Pool.add_listener`
  нет — Critical R10.18-1 закрыт); реконнект с backoff 1→60 c и сбросом после успеха; `finally` закрывает conn
  (в т.ч. при cancel); rate-limited WARNING; тесты mount/reconnect/connect-failure/manual-payload зелёные.
- **Статус-API (T-1762):** `chat_id: Query() = None` на обоих эндпоинтах; `source` — аддитивно (R16);
  `deep_sleep_status`/`cognition_status` не бросают при ошибке БД (fail-open).
- **F1 BetterStack:** ctor без хоста → `ValueError`; `DEFAULT_HOST=""`; `_url = https://{host}/{token}`;
  `extract_sentry_public_key` (regex userinfo) + `token_equals_sentry_public_key` (`hmac.compare_digest`), 401-хинт
  без значений; R17: в маркере `token_len`/`last4` (`****` при длине < 4), полного токена нет; `logtail-python`
  удалён, импортов не осталось; smoke-скрипт переведён на `BetterStackHandler`; probe-скрипт не делает сети в тестах.
- **Тесты/инварианты:** 6042 passed / 1 pre-existing failed; `tests/test_settings_worker_sync_round1018.py` +
  `test_betterstack_probe.py` + обновлённые `test_betterstack_handler.py`/`test_dream_worker.py`/пин-тесты каталога —
  зелёные (110 + 280 в целевых наборах).

## 4. Открытые из прошлых раундов

- **S10.17-1 (Medium, docs-only):** `plans/archive/security-rotation-finalize-round1016/spec.md` без CANCELLED-баннера
  (§8 «ротация обязательна в любом случае») — не блокирует; один класс с S10.18-13 (docs-артефакты раунда безопасности).
- **S10.17-2/-3 (Low):** бейджи «Сон через —» при `cognition==null`; доки-счётчики pytest в спеках 10.17.
- **S10.17-4/-5/-6 (Info):** tool env-preflight, callback `tdq:` без hot-гейта, `/healthz` version.
- **R10.6-1/-2/-3 (Low/Info, старше):** дубль generic-рендера `llm_providers`, https-SSRF в probe, 422-эхо `api_key`
  (см. `plans/reports/audit_backlog.md`).
- **S10.16-1/-2 — CLOSED** (10.16 итерация 2): R17-утечка youtube-логов и force-доставка канона без бэкапа.

## 5. Вердикт по контракту

- **Открытых Critical — НЕТ.**
- **Открытый High — 1 (S10.18-1) → переход к БАТЧУ 2 блокируется** до решения (фикс per-chat учёта либо
  явная фиксация «бюджеты глобальные» в ADR/spec + снятие per-chat резолва).
- Medium S10.18-2/-3 — реальные рассинхроны/семантические дыры F7, рекомендуются к фиксу в этом же батче;
  S10.18-4/-5/-6 — риски поведения/деплоя, требующие явного решения (док/лог), не блокеры кода.
- Low/Info — не блокеры.

## 6. Что обновлено

- `plans/reports/round10.18_scanner_audit.md` — этот отчёт (новый).
- `plans/reports/global_map.md` — секция «Round 10.18 (БАТЧ 1)» + baseline 10.18.
- `plans/reports/full_audit_results.md` — аддитивная секция «Round 10.18».
- `plans/reports/audit_backlog.md` — аддитивно: Round 10.18 (файлы просканированы; открытые пункты + validator).

*Отчёт сгенерирован @Scanner 15.09.2026 (Шаг 6 OpenSpec, Strict Workflow, БАТЧ 1/3).*

## 7. Итерация 2 — повторный аудит после фиксов @Builder (15.09.2026)

**Метод:** повторный `git status/diff` + адресные чтения новых участков; проверка SQL-фильтров, порядка гейтов
и lifecycle; инструментальные пробы (полный pytest, JS-гейты, `git diff --check`, воспроизведение env-расхождения
`master_fallback` мини-скриптом).

### 7.1. Статусы находок итерации 1

| ID | Sev | Статус | Доказательство закрытия |
|---|---|---|---|
| S10.18-1 | High | **CLOSED** | `database.count_dream_log(..., chat_id=None)` + `sum_dream_log_tokens(..., *, chat_id=None)` добавляют `AND chat_id = ?` (порядок params корректен); `dream_worker:618-620` считает расход по чату; `:494` лог `budget_stop` — с chat_id. Тест `TestPerChatBudget::test_chat_override_not_blocked_by_other_chat_spend` (чат A с override 50 не глушится 10 дистилляциями чата B). Обходов не найдено: все прочие вызовы — статусные счётчики (глобальные) либо `_deep_budget_ok` (глобальный deep-кап по дизайну, с фильтром kind). `decay_run` (chat_id=0, kind='decay_run') в per-chat `distilled` не попадает. |
| S10.18-2 | Medium | **CLOSED** | `_deep_tick` резолвит `memory.deep_sleep_trigger` + `deep_sleep_hour` **по каждому чату-кандидату**; вынесен `_deep_candidate_chat_ids`. Тест `test_deep_tick_resolves_trigger_per_chat` (override 'fixed' исполним при глобальном 'after_sleep'; чат без override не запускается). |
| S10.18-3 | Medium | **CLOSED** | `feature_gates.master_fallback` + `MASTER_FALLBACK_KEYS={"dream": …}`; подключён в `allowed_features`, `web/api/gates.py:68-72`, `services/oversight.py:174`, `web/api/oversight.py:105-110`; `cognition_status` отдаёт аддитивный `dream.effective` и использует его в `dream_in/active`. Тесты `TestStatusMatchesWorkerBehavior` (kill-switch → `effective=False`, `active=False`; без kill-switch → True). Не-dream фичи: `master_fallback → None` → поведение прежнее. |
| S10.18-4 | Medium | **CLOSED** | `_run` гейтит decay через `_dream_master_on()` (глобальный `memory.dream_enabled`). Тесты `TestDecayGatedByDreamMaster` (off → `last_decay_run() is None`; on → маркер записан). |
| S10.18-5 | Medium | **CLOSED** | `run_once` передаёт `only_chat`; `_maybe_deep_after_sleep` идёт по целевому чату, а без цели капает `eligible[:_MANUAL_DEEP_CASCADE_MAX=1]`. Тесты `TestManualDeepCascade` (target → `[CHAT_ID]`; без цели → 1 чат). |
| S10.18-6 | Medium | **CLOSED** | `bot.py:193-203`: токен без хоста → `logger.error("[betterstack] disabled (no BETTERSTACK_HOST) — логи НЕ отправляются…")`; оба отсутствуют → WARNING. |
| S10.18-7 | Low | **CLOSED** | `on_shutdown` вызывает `await _chat_params_notify.stop()` (bot.py:838-841); `stop()` гасит цикл/cancel задачи; тест `TestListenerStopLifecycle`. Замечание: порядок cancel в `main().finally` (до `on_shutdown`) остаётся — stop() после уже отменённой задачи безопасен (идемпотентно). |
| S10.18-8 | Low | **CLOSED** | Обновлены `README.md` (таблица env + §Мониторинг), `plans/ARCHITECTURE.md` §10/§16/§17 (SUPERSEDES-пометки), `bot.py:568-571` (актуальный комментарий). |
| S10.18-9 | Low | **CLOSED** | Спека/таск-конфликт F1 закрыт пометкой в ARCHITECTURE (удаление `logtail-python` зафиксировано); docstring probe-скрипта актуализирован. |
| S10.18-10 | Low | **CLOSED (mitigated)** | reload `config.settings` остался, но `settings_mod.settings = orig_settings` + `sys.modules.pop("bot")` выполняются в `finally` (тест `TestListenerFailOpen`, :470-496) → тестовые env не «протекают» в прогон (проверено: полный pytest 6052/0). |
| S10.18-11 | Low | **CLOSED** | `ChatParamsNotify._pending` — сильные ссылки + `add_done_callback(discard)`, отмена в `stop()`; тест `test_stop_cancels_pending_and_closes`. |
| S10.18-12 | Info | **OPEN** | Остаточный РАЗРЫВ `memory.nostalgia_enabled` (global-only) — backlog T-1764; в батче не трогался. |
| S10.18-13 | Info | **OPEN (вне скоупа)** | Фрагмент SSH-пароля в `plans/archive/security-rotation-finalize-round1016/spec.md:35` присутствует (файл **отслеживаемый** — `git ls-files` подтверждает), 1 вхождение; трекается в `plans/backlog.md` (R10.18-12), ротация CANCELLED. Значение в отчёт не копируется. |
| S10.18-14 | Info | **CLOSED** | Инварианты перепроверены (см. 7.3). |

### 7.2. Новые находки итерации 2

| ID | Sev | File:line | Суть | Рекомендация |
|---|---|---|---|---|
| S10.18-15 | Medium | `services/feature_gates.py:55-72` | **`master_fallback` использует не тот default.** Для dream он передаёт `default=DEFAULT_BY_FEATURE["dream"]=False`, тогда как воркер (`dream_worker._key_for`) — `settings.DREAM_ENABLED`. При env `DREAM_ENABLED=true` и отсутствии ключа `memory.dream_enabled` в БД (ключ в PG **не сидится** — grep по `pg_db.py`/`config_cache.py` пуст) воркер считает master ON, а статус гейтов/`cognition.effective` — OFF. Воспроизведено пробой: `worker_enabled=True`, `master_fallback=False`, `status_gate=False`, `worker_gate=True`. Это тот же класс рассинхрона, что чинил S10.18-3, но в env-ветке. | Брать default из `settings` (например, `MASTER_FALLBACK_DEFAULTS={"dream": settings.DREAM_ENABLED}`) либо вызывать тот же резолвер, что воркер (`resolve_setting_cached(..., default=settings.DREAM_ENABLED)`). |
| S10.18-16 | Low | `services/dream_worker.py:753,766,784-793` | Мёртвый код: sync-хелперы `_window_open`/`_daily_limit`/`_budget_reason` больше не вызываются ни в проде, ни в тестах (grep пуст) — hot-path перешёл на `*_for`-варианты. | Удалить (или пометить deprecated) — обратная совместимость требовалась только для `_key`. |
| S10.18-17 | Low | `services/dream_worker.py:1205-1230` | `_deep_tick` теперь **всегда** делает `get_dream_candidate_chats` (SQL) + N per-chat resolve на каждом тике (60 мин), даже если ни у одного чата `trigger != 'fixed'` — раньше был ранний `return` без I/O. Не баг, но лишняя нагрузка/лог-шум (WARNING `candidate chats failed`) на пустой конфигурации. | Дешёвый предгейт: если глобальный `memory.deep_sleep_trigger` + `flags.deep_sleep_enabled` выключены и per-chat overrides отсутствуют — ранний return до выборки (или кэш доступности `fixed`). |
| S10.18-18 | Info | `services/dream_worker.py:1271-1280` | Явный `POST /api/memory/dream/run?deep=1` без `chat_id` по-прежнему прогоняет deep по **всем** кандидатам (`chat_ids is None`), без капа `_MANUAL_DEEP_CASCADE_MAX` — осознанно (явный запрос оператора), ограничен `max_chats_per_run` и `limits.deep_sleep_tokens_per_day`. | Оставить; при желании документировать в API-описании. |
| S10.18-19 | Info | `services/dream_worker.py:620` | Per-chat `tokens_today` суммирует `memory_dream_log` **без фильтра `kind`** → токены deep-прогонов/скипов того же чата входят в бюджет обычного Сна. Поведение pre-existing (раньше — глобально), теперь консистентно per-chat; возможно уточнение. | Опционально: фильтр `kind IN ('distilled','run','skipped','error')` для бюджета обычного Сна (deep уже считается отдельно в `_deep_budget_ok`). |
| S10.18-20 | Info | `web/api/oversight.py:105-110` | Поле `previous` в ответе kill-switch теперь = эффективный гейт (с per-chat master-fallback), а не «прежнее явное значение»; при master ON без явного gate вернётся `true`. Семантика поля сместилась (аддитивно, для аудита). | Либо оставить (осознанно — «что реально исполнялось»), либо вернуть «прежнее явное значение» + отдельное поле `previous_effective`. |

### 7.3. Верификация итерации 2 (доказательства)

- **Проверки закрытия:** см. таблицу 7.1; новых обходов учёта не найдено (grep всех call-sites `count_dream_log`/
  `sum_dream_log_tokens`: прод — только `dream_worker` (per-chat) + `_deep_budget_ok` (глобально по kind) +
  `memory_agi` (статусные счётчики); decay-логи `kind='decay_run'`/chat_id=0 из per-chat выборки исключены).
- **Гонки `_deep_tick`:** `max_instances=1/coalesce=True` в APScheduler + `_deep_lock` внутри `_run_deep_all`
  (повторный вход → `{"skipped": 1}`, без двойных LLM-вызовов). Между `locked()`-проверкой и `_run_deep_all`
  гонка не опасна (второй вход самосдерживается).
- **Не-dream фичи:** `MASTER_FALLBACK_KEYS` содержит только `dream`; `master_fallback` для остальных → `None`,
  `gates_enabled(..., fallback=None)` эквивалентен прежнему пути (`_explicit_flag_value` → `_global_flag_value`).
- **Manual-путь:** `run_once(deep=False, chat_id=X)` → каскад только по X; `run_once(deep=True)` не затронут;
  `manual=True` в `_maybe_deep_after_sleep` по-прежнему обходит flag/trigger (задел F2/ADR-1018-2 D2) — регрессий нет.
- **Инварианты:** каталог **436/406/411/90/88/19** (интроспекция); DDL нет; SQLite v9; `logtail`-импортов нет;
  порядок роутеров `bot.py` не тронут; R16 (`source`/`effective` — аддитивно), R17 (last4-маска, probe-маскирование).
- **Валидатор:** `.venv/Scripts/python.exe -m pytest -q` → **6052 passed / 0 failed** (75.6 c; pre-existing
  `test_tool_download_quality_round1017::TestSchemaAndAdr::test_adr_supersede_recorded` починен fallback'ом на
  `plans/archive/`); целевые наборы 10.18 — **121 passed**; `node --check web/app.js` OK; `routing_test.js`
  `JS-UNIT-OK`; `vue_mount_test.js` `VUE-MOUNT-OK`; `git diff --check` → exit 0.

### 7.4. Итог итерации 2 и вердикт

| Severity | Открыто | Закрыто | Коды открытых |
|---|---|---|---|
| Critical | **0** | 0 | — |
| High | **0** | 1 | — |
| Medium | **1** | 5 | S10.18-15 |
| Low | **2** | 5 | S10.18-16, S10.18-17 |
| Info | **5** | 1 (verified) | S10.18-12, S10.18-13, S10.18-18, S10.18-19, S10.18-20 |

- **ВЕРДИКТ: переход к БАТЧУ 2 (F2 Сон/каскад/бейджи) — РАЗРЕШЁН.** Открытых Critical/High нет;
  S10.18-1 (High) закрыт с регресс-тестом. Открытый Medium S10.18-15 — узкая env-ветка
  (`DREAM_ENABLED=true` без DB-ключа), к F2 не относится, чинится однострочно и не блокирует.
- Low/Info — не блокеры (S10.18-16/-17 — чистка/perf; S10.18-12/-13 — backlog).

*Итерация 2 отчёта сгенерирована @Scanner 15.09.2026 (повторный аудит БАТЧА 1 после фиксов @Builder).*

## 8. БАТЧ 2 — F2 `sleep-manual-cascade-badges` (аудит 15.09.2026)

> **Область:** `services/dream_worker.py`, `services/config_migrations.py` (новый), `config/settings.py`,
> `bot.py`, `web/api/memory_agi.py`, `web/app.js`, `services/param_catalog.py`, `services/feature_gates.py`,
> `services/chat_params.py`, `tests/test_sleep_manual_cascade_round1018.py` (новый) + правки 9 тест-файлов.
> **Эталон:** `plans/features/sleep-manual-cascade-badges/{spec.md, adr-1018-2-*.md, tasks.md}`.
> **Метод:** `git diff`/чтения `file:line` + grep (`gates_enabled`, `consume`, `manual`, `hot.get` по воркеру)
> + инструментальные пробы (полный pytest, JS-гейты, каталог, воспроизведение cold-cache предгейта).

### 8.1. Статусы находок итерации 2 (перепроверено в Батче 2)

| ID | Sev | Статус | Доказательство |
|---|---|---|---|
| S10.18-15 | Medium | **CLOSED** | `services/feature_gates.py:58-63` — новый `_master_fallback_default(feature)`: для dream возвращает `settings.DREAM_ENABLED` (единый дефолт с воркером), для остальных — `DEFAULT_BY_FEATURE`. Проба env-ветки (`DREAM_ENABLED=true`, нет DB-ключа) больше не даёт расхождения worker ON / status OFF. |
| S10.18-16 | Low | **CLOSED** | Мёртвые sync-хелперы `_window_open`/`_daily_limit`/`_budget_reason` удалены из `services/dream_worker.py` (grep — 0 определений). |
| S10.18-17 | Low | **CLOSED (частично)** | `_deep_tick` получил дешёвый предгейт `_deep_fixed_possible()` (`dream_worker.py:1282-1328`) → SQL-выборки кандидатов нет при глобальном `after_sleep` и отсутствии прогретого override. **Но** предгейт породил S10.18-21 (см. ниже). |
| S10.18-10/-11 (iter-2) | Low | CLOSED | см. §7.1 (без изменений). |
| S10.18-12/-13/-18/-19/-20 | Info | OPEN | Nostalgia-РАЗРЫВ (backlog T-1764); pre-existing фрагмент в архивной спеке; `?deep=1` без капа; `tokens_per_day` без фильтра `kind`; `previous` kill-switch = effective. Батч 2 их не касается. |

### 8.2. Новые находки Батча 2

| ID | Sev | File:line | Суть | Рекомендация |
|---|---|---|---|---|
| S10.18-21 | Medium | `services/dream_worker.py:1282-1333`; `services/chat_params.py:150-183` | **Предгейт `_deep_tick` может молча похоронить per-chat `trigger='fixed'`** (частичный откат R10.18-2). `_deep_fixed_possible()` = (глобальный `deep_sleep_trigger == 'fixed'`) ИЛИ `ChatParamsCache.has_any_override(...)` — скан **только уже загруженных** `_items` + `_override_keys_seen` (in-memory, очищается рестартом). Если глобальный триггер `after_sleep` (дефолт) и ни один чат с таким override ещё не загружен в процесс (свежий старт; override записан web-процессом и пришёл через NOTIFY — `invalidate_chat` чистит `_items` и не отмечает ключ), `_deep_tick` делает ранний return → фиксированный прогон для этого чата не состоится, пока чат случайно не загрузит другой путь. Воспроизведено: реальный `ChatParamsCache(pg=None)` с пустым `_items` → `has_any_override=False` → `_deep_fixed_possible=False`. Тесты покрывают только «прогретый» кейс (`test_deep_tick_proceeds_when_per_chat_override`) и «пустой кэш = скип» (`test_deep_tick_skips_candidate_sql_when_disabled`) — т.е. ложная уверенность. | Не строить корректность на прогретости кэша: (а) вернуть безусловную дешёвую SQL-выборку (1 запрос/час — цена предгейта ниже риска), либо (б) считать «нет загруженных чатов / ключ не виден» = True (консервативно), либо (в) отмечать ключ в `invalidate_chat_from_notify` (payload — только chat_id, нужен флаг «ключ был виден» в PG/ConfigCache). Обязателен тест «cold-cache + per-chat fixed → тик доходит до кандидатов». |
| S10.18-22 | Medium | `web/app.js:5440-5463`; `setTab:2737-2741`; `closeModule:2371-2373` | **После ручного POST базовый 15с-polling остаётся включённым вне вкладки «Статус».** `_restoreCognitionPolling()` (через 120с) делает `stopCognitionPolling()` + `_startCognitionTimer(15000)` без проверки `activeTab`; `_startCognitionTimer` смотрит только `document.hidden`. Кнопка живёт в модалке «Сон» на вкладке `modules` → оператор, не уходя с вкладки, получает постоянный 15с-polling `loadCognition()` (6 GET'ов на тик) бессрочно; снимается только сменой вкладки или `document.hidden`. Модалка обосновывает polling, пока открыта (бейджи `dreamPhaseBadge`/`deepPhaseBadge` в `web/index.html:1039-1040`), **но** `closeModule` polling не останавливает, а ADR-1018-2 D5/спека §4.6 описывают только «уход с вкладки» — т.е. инвариант F5/R10.11-5 «вне Статуса — стоп» нарушен частично. JS-тест `routing_test.js` фиксирует текущее поведение (`seenMs == [5000, 15000]`). | В `_restoreCognitionPolling` стартовать 15с только при `this.activeTab === 'status'` (или останавливать в `closeModule` для не-status вкладок); синхронно поправить JS-тест и ADR D5. |
| S10.18-23 | Low | `web/api/memory_agi.py:590-601` | **`dream.manual`/`deep_sleep.manual` выводятся как `running && !in_window`** — это «активность вне окна», а не «ручной прогон». Плановый тик запускается каждые 60 мин **вне** окна [4,6) (22 часа в сутки) и на время работы держит `_lock` → `running=True`, `dream_in=False` → транзиентно `manual=True` и `active_until = now+900` для автотика, который на самом деле только отбирает кандидатов и делает `window_skip`. Бейдж/диагностика могут показать «ручной прогон» без ручного запуска. | Ввести настоящий признак ручного прогона на воркере (атрибут `_manual_run_until`/`_manual_chat`, выставляемый в `run_once`) и отдавать `manual` из него; `active_until` для авто-тика вне окна — не растягивать на 900с. |
| S10.18-24 | Low | `services/dream_worker.py:168-170`; `config/settings.py:1101-1107` | **Новые базовые пороги сравнялись с F3-fallback'ом.** `_FALLBACK_MIN_CLUSTER_SIZE=2` / `_FALLBACK_MIN_IMPORTANCE_SUM=8` теперь равны новым code-дефолтам (`DREAM_REPEAT_THRESHOLD=2`, `DREAM_IMPORTANCE_SUM_THRESHOLD=8`) → механика «0 убеждений за 3 дня → ослабить пороги» (F3/T-1435) при дефолтах становится no-op (различие осталось только при явно поднятых порогах). В spec §4.1 этот коллизионный эффект не отражён; два теста пришлось искусственно пиновать 3/12. | Либо опустить fallback-константы ниже новых дефолтов (напр. 2/6), либо задокументировать, что fallback актуален только при повышенных порогах (и убрать «мёртвый» путь), либо признать его устаревшим и удалить. |
| S10.18-25 | Low | `services/dream_worker.py:723-733` | **`0` как per-chat лимит противоречив.** `_budget_reason_for` трактует `0` как «без лимита» (`if dist_max and …`), а near-limit-проверка `dist_max - distilled_today < _DREAM_NEAR_LIMIT_DIST` при `dist_max=0` истинна сразу → чат останавливается с `budget_stop` до первой дистилляции. Ключи `memory.dream_distillations_per_day`/`tokens_per_day` не имеют min/max в каталоге → `0` достижим из UI. Формула pre-existing, но раньше ключ был глобальным, теперь per-chat и легко настраивается на один чат. | Единая семантика: `if not dist_max: без лимита` в near-limit-ветке (или запретить 0 в каталоге `min_value=1`). |
| S10.18-26 | Info | `web/app.js:5431-5436` | `_retryCognition([1000,3000,8000])` создаёт 3 `setTimeout` без сохранения/очистки: после ухода с вкладки они всё равно вызовут `loadCognition()` (у `loadCognition` нет гейта вкладки/`document.hidden`), а `stopCognitionPolling` их не снимает. Утечки нет (таймеры одноразовые), но это лишние 3 запроса вне вкладки; `dreamBusy` ограничивает частоту кликов. | Сохранять хэндлы ретраев в массив и чистить в `stopCognitionPolling` (как `_cognitionPollRestore`). |
| S10.18-27 | Info | `services/dream_worker.py:1428-1441,1640-1695` | Ручной deep-прогон игнорирует **и** cooldown, **и** суточный `limits.deep_sleep_tokens_per_day`, **и** `worker_budget`-деградацию (verdict не применяется, расход пишется) → серия кликов «Сон сейчас» даёт неограниченный LLM-расход по выбранному чату (принято ADR-1018-2 D2/UPD п.5 «игнорировать экономию»; для `?deep=1` без `chat_id` дополнительно нет капа `_MANUAL_DEEP_CASCADE_MAX` — batch-1 S10.18-18). | Оставить (зафиксировано в ADR); в отчёт @DevOps — ориентир по расходу (спека §4.8 просила фактические токены ручного прогона). |
| S10.18-28 | Info | `config/settings.py:1090,1137`; `tasks.md:154-156` | `DREAM_ENABLED`/`DEEP_SLEEP_ENABLED` code-default оставлены `False` (в spec §4.1 таблица помечает их «True»), включение — per-chat через UI после F7. Отклонение от таблицы задокументировано в `tasks.md` §11; T-1713/T-1724/T-1725/T-1726/T-1772 открыты → прод-симптом «0 дистилляций» сам кодом не включается. | Не блокер (осознанное отклонение). @Orchestrator/@DevOps: включить целевой чат в UI и провести живой прогон (T-1724/T-1725) — иначе F2 end-to-end не подтверждена. |

### 8.3. Верифицировано чисто (Батч 2)

- **Manual-приоритет:** обход kill-switch (`gate_override`), near-limit и суточных бюджетов (`budget_override`) —
  безусловный, без фича-флагов (grep: `sleep_manual_priority_enabled`/`sleep_relaxed_thresholds_enabled` — 0,
  нет веток `if manual and flag`). Аудиторские строки `kind='skipped'` не влияют на счётчики `kind='distilled'`.
  Неприкосновенны: `_run_lock`/`_deep_lock` (`already_running`), `protected_facts`, ≥2 реальных `source_ids`,
  `flags.persona_enabled` (только WARNING `reason=persona_disabled`, запись traits не обходится), R17/fail-open,
  `PERSONA_TRAITS_MAX`/дедуп — как в ADR D3/spec §4.2a.
- **Бюджет не удваивается:** SQLite-счётчики (`count_dream_log`/`sum_dream_log_tokens`) и леджер `worker_budget.consume`
  — разные механизмы; manual делает 4 независимых `consume` на один вызов (`_dream_budget_ok`/`_deep_budget_ok`),
  retry/Личность получают свои вызовы; двойного списания одного LLM-вызова нет.
- **Каскад:** `run_once(deep=False)` → `_maybe_deep_after_sleep(manual=True, only_chat=…)` — один проход, без рекурсии;
  `only_chat` → ровно целевой чат, без цели — `_MANUAL_DEEP_CASCADE_MAX=1`; `_run_deep_all(manual=True)` без `break`
  (все выбранные чаты), `stats["cascade"]={"deep":…,"traits":…}` аддитивно; все ранние return'ы глубокого сна несут
  единый набор ключей (`_deep_result`) → `KeyError` на `traits` исключён.
- **Пороги/миграция:** `migrate_dream_thresholds` — идемпотентна (2-й прогон → `{}`), правит **только** равенство
  прежнему дефолту (3/12/5/5/30/60000/30), кастом → WARNING и не трогает, отсутствующий ключ → skip, PG down → skip;
  вызов в `bot.py` после `migrate_prompt_canons` (после `cache.init()`); DDL нет; маппинг совпадает с `settings.py`
  (2/8/2/10/60/300000/10). `prompt_migrations.py` не тронут (канон-тесты 10.13 целы).
- **Бейджи:** `cognition==null` → `{text:'—', cls:'badge-muted'}` (S10.17-2 закрыт); `active_until` при `running`
  вне окна = `now+900`, в окне — `min(конец окна, now+900)`, не running в окне — конец окна (F5-семантика не сдвинута);
  `runDreamNow` — оптимистичная `active` + немедленный `loadCognition` + ретраи 1/3/8с + ускорение 5с/120с.
- **Диагностика Личности:** все reason-коды (`no_self_facts`, `persona_disabled`, `budget_skip`, `llm_error`,
  `json_error`+`raw_len`, `empty_response`, `all_duplicates`, `write_error`) на месте, R17-safe (только chat_id/числа/длина).
- **F7-совместимость:** per-chat учёт бюджетов Сна (S10.18-1) сохранён (`distilled_today`/`tokens_today` с `chat_id`);
  лимиты резолвятся per-chat и **один раз** до цикла кластеров (D8/T-1771) — меньше обращений, семантика та же.
- **Инварианты:** каталог **436/406/411/90/88/19** (Δ F2 = 0); DDL нет (SQLite v9); R16 (`manual`/`effective`/`source`/
  `cascade` — аддитивно); R17 (нет текстов/секретов в новых логах); порядок роутеров `bot.py` не тронут.
- **Валидатор:** `.venv/Scripts/python.exe -m pytest -q` → **6083 passed / 0 failed** (69.6 c);
  `node --check web/app.js` OK; `routing_test.js` `JS-UNIT-OK`; `vue_mount_test.js` `VUE-MOUNT-OK`;
  `git diff --check` → exit 0.

### 8.4. Итог Батча 2 и вердикт

| Severity | Открыто | Закрыто | Коды открытых |
|---|---|---|---|
| Critical | **0** | 0 | — |
| High | **0** | 0 | — |
| Medium | **2** | 1 (S10.18-15) | S10.18-21, S10.18-22 |
| Low | **4** | 2 (S10.18-16, -17) | S10.18-23, S10.18-24, S10.18-25 (+ S10.18-10 closed в iter-2) |
| Info | **8** | 0 | S10.18-12, -13, -18, -19, -20, -26, -27, -28 |

- **ВЕРДИКТ: переход к БАТЧУ 3 (F3 граф + миграция v10) — РАЗРЕШЁН.** Открытых Critical/High нет;
  Medium S10.18-21/-22 — локализованные (предгейт `_deep_tick`; restore-polling вне вкладки), не блокируют F3
  (граф/SQLite v10), но требуют фикса до шага 7 (рекомендуется в этом же раунде).
- Low/Info — не блокеры (S10.18-23/-24/-25 — семантика/доки; S10.18-26…-28 — диагностика/расход/включение рубильников).

*Секция Батча 2 сгенерирована @Scanner 15.09.2026 (Шаг 6 OpenSpec, Strict Workflow).*

## 9. БАТЧ 3 — F3 `graph-density-scoring-stoplist` + F4 `graph-physics-stabilization` (аудит 15.09.2026)

> **Область:** `services/database.py` (миграция v10, `graph_snapshot`, `upsert_edge`, `commit`-параметр,
> `_belief_participation_blob`), `services/graph_stoplist.py` (новый), `services/summary_memory.py`
> (атомарность fact+edge), `web/api/memory_agi.py` (лимиты 800/2400/150), `web/app.js` (physics 150 +
> авто-отключение; polling/`manual`-маркеры), `tests/test_graph_scoring_round1018.py` (новый) + 11 тест-файлов.
> **Эталон:** `plans/features/{graph-density-scoring-stoplist,graph-physics-stabilization}/{spec.md,adr-1018-{3,4}-*.md,tasks.md}`,
> `plans/ARCHITECTURE.md` §36.
> **Метод:** `git diff`/чтения `file:line` + grep (`INSERT INTO edges`, `insert_graph_fact` callers, `user_version`)
> + инструментальные пробы (полный pytest, JS-гейты, каталог, синтетический граф 15k рёбер — замер `graph_snapshot`
> и атрибуция фаз).

### 9.1. Статусы находок Батча 2 (перепроверено в Батче 3)

| ID | Sev | Статус | Доказательство |
|---|---|---|---|
| S10.18-21 | Medium | **CLOSED** | Предгейт `_deep_fixed_possible()` **удалён**; `has_any_override`/`note_overrides`/`_override_keys_seen` убраны из `services/chat_params.py` (grep — 0). `_deep_tick` теперь **всегда** выбирает кандидатов (`_deep_candidate_chat_ids`) — 1 дешёвый SQL/час; docstring фиксирует причину (cold-cache терял per-chat `fixed`). |
| S10.18-22 | Medium | **CLOSED** | `web/app.js::_restoreCognitionPolling` стартует 15с **только** при `activeTab === 'status'`; `closeModule` вне «Статуса» зовёт `stopCognitionPolling()`; JS-тесты на оба случая. |
| S10.18-23 | Low | **CLOSED** | Настоящие маркеры: `DreamWorker.manual_run_active`/`manual_deep_active` (TTL `_MANUAL_RUN_MARKER_SECONDS=900`, ставит только `run_once`), `cognition_status` использует их для `dream.manual`/`deep_sleep.manual`; `_badge_active_until(manual=…)`. Остаточный нюанс — S10.18-29. |
| S10.18-24 | Low | **CLOSED (частично)** | `_FALLBACK_MIN_IMPORTANCE_SUM` = **6** (< дефолт 8) → fallback снова отличим; `_FALLBACK_MIN_CLUSTER_SIZE` = 2 = дефолт (компонент размера кластера остаётся no-op) — зафиксировано комментарием. |
| S10.18-25 | Low | **CLOSED** | near-limit-ветка получила `bool(dist_max)`/`bool(tok_max)` → `0` = «без лимита» согласовано с `_budget_reason_for`. |
| S10.18-26 | Info | **CLOSED** | `_cognitionRetryTimers` сохраняются и снимаются в `stopCognitionPolling`; в `runDreamNow` порядок исправлен (`restartCognitionPolling` → затем `_retryCognition`, иначе restart снял бы свежие ретраи). |
| S10.18-12/-13/-18/-19/-20 | Info | OPEN | Nostalgia-РАЗРЫВ (backlog T-1764); pre-existing фрагмент пароля в архивной спеке; `?deep=1` без капа; `tokens_per_day` без фильтра `kind`; `previous` kill-switch = effective. Батч 3 их не касается. |

### 9.2. Новые находки Батча 3

| ID | Sev | File:line | Суть | Рекомендация |
|---|---|---|---|---|
| S10.18-30 | Medium | `services/database.py:3796-3833` (`graph_snapshot`, ×2-цикл) | **Перф: фаза ×2 доминирует и масштабируется линейно с числом живых beliefs; замер не подтверждает заявленные 50–56 мс.** Синтетический граф (15 000 рёбер, 20 000 фактов, 4 000 узлов, 200 живых beliefs, один чат): полный `graph_snapshot` **≈238 мс**; с отключённым `_belief_participation_blob` — **≈59 мс** (это и есть «SQL-часть»); изолированный ×2-цикл (2000 строк пула × blob) — **≈176 мс** при blob 5 КБ, **≈680 мс** при 25 КБ (1000 beliefs), **≈2.3 с** при 100 КБ (4000), **≈6.5 с** при 254 КБ (10 000). Цикл `for r in rows: … re.search(...)` — чистый Python **в event loop**, вызывается на каждый `GET /api/memory/graph` (polling 15с, а во время ручного прогона Сна — 5с) → блокировка loop'а бота (heartbeat/поллинг/LLM) на сотни мс–секунды. Для `chat_id=None` blob агрегирует beliefs ВСЕХ чатов — худший случай. Формула ×2 корректна (границы токенов, `re.escape`, substring-тест покрыт), проблема — только стоимость. | Заменить per-node `re.search` по blob на O(1)-проверку: один раз построить набор токенов (`set(re.findall(r"[\wё]+", blob))` + при необходимости «падежный» padded-блоб `" " + " ".join(tokens) + " "` и `f" {name} " in padded`), либо кэшировать blob/токены по чату с TTL; многословные имена — предпроверка по словам. Дополнительно: пересмотреть замер perf-бюджета (T-1729) с учётом ×2-фазы. |
| S10.18-29 | Low | `services/dream_worker.py:464-503`; `web/api/memory_agi.py:483-489,614-621` | **`run_once(deep=False)` (кнопка «Сон сейчас») не выставляет `_manual_deep_until`**, хотя каскад реально запускает Глубокий сон (`_maybe_deep_after_sleep(manual=True, only_chat=…)`). В результате во время manual-каскада `deep_sleep.manual=False`, а `deep_active_until=None` вне окна — бейдж глубокого сна «теряет» фазу (симметричная половина T-1719 закрыта только для `?deep=1`). Плюс TTL маркера (900с) не связан с `_run_lock`/`_deep_lock`: прогон длиннее 15 мин теряет `manual` до своего конца. | В `run_once` (ветка `deep=False`) или в `_maybe_deep_after_sleep` при `manual=True` ставить `self._manual_deep_until`; при желании — продлевать маркер на время прогона (или считать `manual` как «маркер ИЛИ (running И стартовал из run_once)»). |
| S10.18-31 | Info | `services/graph_stoplist.py:26-39` | Нормализация STOP_LIST не ловит варианты с внутренним дефисом/пробелом («видео-сообщение», «голосовое сообщение») и морфологию («сообщения») — жёстко, как в ADR; ложных срабатываний нет (эмодзи/пунктуация по краям и регистр обработаны тестами). | Оставить; при живых данных проверить, что экстрактор действительно даёт «видеосообщение»/«голосовое» (иначе добавить варианты в список осознанно). |
| S10.18-32 | Info | `services/database.py:3788-3798` | Само-петля (`source_id == target_id`) даёт 2 строки в `re` → degree и score учитывают её **дважды** (`UNION ALL`-семантика pre-existing). `_memorize_facts_inner` может создать такую петлю, если LLM вернёт subject == object. | Опционально: `WHERE source_id != target_id` в `re`/`deg` или дедуп в `upsert_node`-пути. |
| S10.18-33 | Info | `services/database.py:1683-1692`; `services/summary_memory.py:1838-1852` | `upsert_edge` — `INSERT … SELECT … FROM nodes WHERE id = ?`: если узел отсутствует, вставка **молча** даёт 0 строк, и факт остаётся закоммиченным без ребра. Гарантия B3-5 покрывает исключения, но не этот кейс. | Логировать WARNING, если `cursor.rowcount == 0` (fail-open), либо вызывать `upsert_edge` через проверку существования узла. |
| S10.18-34 | Info | `services/dream_worker.py`; `web/api/oversight.py` | Открытые Info Батча 1 (не в скоупе 3): S10.18-18 (`?deep=1` без `chat_id` — без капа `_MANUAL_DEEP_CASCADE_MAX`), S10.18-19 (`tokens_per_day` без фильтра `kind`), S10.18-20 (`previous` kill-switch = effective). | Перенести в backlog/фикс по желанию. |

### 9.3. Верифицировано чисто (Батч 3)

- **Миграция v10 (`_migrate_edges_fact_id_v10`):** порядок в `initialize()` после `_migrate_self_origin_v9()` ✓;
  guard по `PRAGMA table_info(edges)` → ALTER только при отсутствии колонки; `CREATE INDEX IF NOT EXISTS
  idx_edges_fact_id` — **вне** guard и **не** в `_SCHEMA_SQL` (иначе legacy-БД упала бы на несуществующей колонке) ✓;
  `PRAGMA user_version = 10` — безусловно, **после** индекса → частичный сбой (ALTER прошёл, индекс/PRAGMA — нет)
  самовосстанавливается при следующем старте; повторный `initialize()` — no-op (тест
  `test_legacy_edges_are_migrated_preserving_rows`: строки сохранены, `fact_id IS NULL`, версия 10, re-init идемпотентен).
  Fresh DB получает `fact_id` из `_SCHEMA_SQL` (тест `test_fresh_db_has_fact_id_index_and_version`); FTS5/vec не
  затрагиваются (миграция только `edges`; тест `test_fts_survives_migration`); обратный путь задокументирован в
  docstring (DROP INDEX + DROP COLUMN + user_version=9); обратная совместимость кода при откате сохранена (колонка
  nullable, старый `upsert_edge` её не упоминает).
- **Скоринг:** `edges.fact_id → graph_facts.id` — корректный `LEFT JOIN f ON f.id = e.fact_id` ✓; NULL-fact_id
  (legacy/`deleted fact`) → `COALESCE(weight)` без потери строки ✓; дубли ребра к одному факту считаются по
  одному разу на ребро ✓ (`re` даёт 2 строки на ребро = по одной на каждый конец); `deg` и `score` считаются из
  одного `re`; порядок параметров SQL (`scope ×3` → nparams → LIMIT) сходится ✓; bounded-пул
  `max(seed×10, 2000)` + Python-ранжирование (ADR D8) — «недобор» возможен только если топ-2000 выеден
  STOP_LIST-центрами (на практике пул на порядок больше сидов).
- **STOP_LIST:** центры фильтруются только в сид-выборке, периферия остаётся (тест) ✓; `normalize_token` —
  casefold + ё→е + срез краевой пунктуации/эмодзи; «СООБЩЕНИЕ»/«Ссылка.»/«КРУЖОЧЁК» распознаются ✓; списки
  centers/penalty различаются явно (сообщение/стикер) и совпадают с формулировкой F5 (§3.1/§4) — модуль готов к
  переиспользованию в Батче 4 ✓.
- **×2:** `re.escape(name)` → нет regex-инъекции/катастрофического бэктрекинга ✓; границы токенов
  `(?<![\wё])…(?![\wё])` — «тема» внутри «система» ×2 не получает (тест `test_substring_does_not_grant_x2`) ✓;
  многословные имена и ё-нормализация покрыты ✓; belief-блоб = только живые (`confirmed`, `supersedes IS NULL`)
  beliefs чата, `kind='belief'` включает парадигмы ✓; fail-open при ошибке БД (×1) ✓.
- **Атомарность (B3-5):** порядок `insert_graph_fact(commit=False)` → `upsert_edge(fact_id=…, commit=False)` →
  единый `commit`, `except → rollback; raise` ✓; FTS-строка в той же транзакции ✓; `commit=True` по умолчанию у
  обоих методов → все прочие вызовы (8 сайтов `insert_graph_fact`, все `upsert_edge`, cron-путь с осознанным
  NULL) не изменены ✓; тест `test_fact_and_edge_are_atomic` подтверждает отсутствие «факта без ребра» ✓.
- **F4:** `GRAPH_PHYSICS_ITERATIONS=150` в опциях ✓; `net.once('stabilizationIterationsDone'|'stabilized')` с
  guard **только по тождеству** `net === this.cognitionNetwork` (в self-host v9.1.9 нет `destroyed`/`isDestroyed`
  — мёртвых guard'ов нет) ✓; `once` → обработчики не копятся (JS-тест) ✓; `reducedMotion → physics:false` и
  слушатели не навешиваются ✓; `renderCognitionGraph` → `destroyCognitionGraph()` перед созданием + early-return
  по `_graphSignature` → повторные рендеры/поиск (`find/focus/selectNodes`) не затронуты ✓; `truncated` показывается
  («показаны не все») ✓.
- **Р16/контракты:** `/api/memory/graph` добавляет `limits` аддитивно; `nodes[].id/label/group/degree` и
  `edges[].from/to/label/weight` без изменений; лимиты 800/2400/150 — код-константы (каталог Δ=0).
- **Валидатор:** `.venv/Scripts/python.exe -m pytest -q` → **6104 passed / 0 failed** (75.4 c);
  `node --check web/app.js` OK; `routing_test.js` `JS-UNIT-OK`; `vue_mount_test.js` `VUE-MOUNT-OK`;
  `git diff --check` → exit 0; каталог **436/406/411/90/88/19** (Δ Батча 3 = 0).

### 9.4. Итог Батча 3 и вердикт

| Severity | Открыто | Закрыто | Коды открытых |
|---|---|---|---|
| Critical | **0** | 0 | — |
| High | **0** | 0 | — |
| Medium | **1** | 1 (S10.18-21) + 1 (S10.18-22) | S10.18-30 |
| Low | **1** | 3 (S10.18-23/-24/-25) | S10.18-29 |
| Info | **8** | 1 (S10.18-26) | S10.18-12, -13, -18, -19, -20, -31, -32, -33, -34 |

- **ВЕРДИКТ: переход к БАТЧУ 4 (F5 экстрактор + F6 матрица ролей) — РАЗРЕШЁН.** Открытых Critical/High нет;
  миграция v10 идемпотентна/обратима, скоринг-формула и STOP_LIST корректны, атомарность fact+edge подтверждена,
  F4 соответствует ADR-1018-4. Открытый Medium S10.18-30 (перф ×2-фазы) — рекомендация закрыть в этом же раунде
  (не блокирует F5/F6, но усиливается с ростом числа beliefs; F5 переиспользует `graph_stoplist`).
- Low/Info — не блокеры.

*Секция Батча 3 сгенерирована @Scanner 15.09.2026 (Шаг 6 OpenSpec, Strict Workflow).*

## 10. БАТЧ 4 — F5 `metafact-penalty-extractor-prompt` + F6 `role-matrix-settings-actualization` (аудит 15.09.2026)

> **Область:** `services/graph_stoplist.py` (`METAFACT_PENALTY_IMPORTANCE`), `services/database.py`
> (importance-срез в `insert_graph_fact` + `f.importance` в SELECT RAG), `services/summary_memory.py`
> (`PREV_FACT_EXTRACT_PROMPT`/`FACT_EXTRACT_PROMPT`, subject/object, `_importance_factor` в FTS+KNN),
> `services/param_catalog.py` (`NAV_*`/`TAB_NAV`/`tab_nav`), `web/api/access.py` (`nav/nav_title/nav_order`),
> `web/app.js` (`matrixSections` по nav; `NAV_GROUP_ORDER`/`NAV_GROUP_TITLES`), `web/index.html` (вложенный
> шаблон матрицы), `tests/test_metafact_penalty_round1018.py` (новый) + тесты mapping/api.
> **Эталон:** `plans/features/{metafact-penalty-extractor-prompt,role-matrix-settings-actualization}/…`,
> `plans/docs/canon/backlog.md`.
> **Метод:** `git diff`/чтения `file:line` + grep всех `insert_graph_fact`-callers и `_effective_weight` + AST-проба
> байт-паритета PREV-промпта + интроспекция nav-распределения каталога + полный pytest/JS-гейты.

### 10.1. Новые находки Батча 4

| ID | Sev | File:line | Суть | Рекомендация |
|---|---|---|---|---|
| S10.18-35 | Low | `services/database.py:1833-1836`; `services/memory_maintenance.py:250-258`; ADR-1018-5 D2 | **Покрытие хард-среза неполное — и есть путь, который его «отменяет».** Срез применяется только там, где передан `subject`/`object`, т.е. лишь `_memorize_facts_inner` (1 из 8 call-сайтов `insert_graph_fact`; девятая строка в grep — docstring); прочие пути (history_import, `lore_worker`, `chat_lore`, cron `_extract_and_save_graph`, `dream_worker`, `memory_maintenance`) не затронуты — это осознанное ограничение ADR D2/spec §9 Q3. Отдельно: **эпи-мерж** (`memory_maintenance::insert_graph_fact(chat_id, merged_text, origin, …)`) не передаёт importance → `rule_importance('chat_history')=4` → слитый мета-факт «теряет» пенальти (imp 1 → 4, factor 0.55 → 0.70) и с двумя такими фактами набирает Σ8 ≥ гейта Сна. | В merge-пути прокинуть пенальти: если все члены кластера имели `importance <= 1` → новому факту `importance=1` (или явный `is_metafact_stopword` по сохранённым subject/object, если кластер их несёт). Как минимум — зафиксировать в ADR как известный остаток + кандидат задачи. |
| S10.18-36 | Info | `plans/features/role-matrix-settings-actualization/spec.md:37-45`; ADR-1018-6 D4 (B4-info(a)) | **Спека и ADR расходятся по числу nav-групп:** spec §3.1 говорит «nav = 3 родителя с настройками», фактическая реализация (и ADR D4) рендерит **4** группы — 3 из backend `NAV_ORDER` + «Прочее» для 5 категоризированных content-параметров с `tab=None`. Моя независимая интроспекция каталога подтверждает ровно 5 таких параметров (`MEDIA_PUBLIC_BASE_URL`, `MEDIA_SHARE_DIR`, `content.info_how_it_works`, `content.intelligence_guide`, `content.no_key_reply`) и распределение nav: `modules 161 / ai 180 / permsoc 65 / None 5` = 411. | Синхронизировать spec §3.1 с ADR D4 (упомянуть «Прочее»/`other` явно). |
| S10.18-37 | Info | `services/summary_memory.py:2349-2351,2410` | **F5-множитель меняет RAG-порядок для ВСЕХ чатов и фактов** (было `weight×decay`, стало `×0.55…1.0` по importance). Логической ошибки нет (монотонно, ограниченно, равные importance порядок не ломают, двойного применения нет — FTS и KNN взаимоисключающи), но это поведенческое изменение на существующих данных: бонусы `rule_importance` (+1 за год/число, +1 за длину ≥200) теперь влияют и на RAG-ранг. | Прогнать живую проверку RAG-качества (T-1724/T-1749) и зафиксировать в отчёте эпика как ожидаемое изменение порядка. |
| S10.18-38 | Info | — | **Сквозные остатки эпика, переносимые в сводку:** S10.18-30 (Medium, перф ×2-фазы `graph_snapshot`), S10.18-29 (Low, `_manual_deep_until` не ставится в manual-каскаде), S10.18-31/-32/-33 (Info F3: варианты стоп-листа, self-loop, `upsert_edge` при отсутствии узла), S10.18-18/-19/-20 (Info F2/F1), S10.18-12 (nostalgia-backlog T-1764), S10.18-13 (SSH-фрагмент, вне батча). | См. сводную таблицу §10.4. |

### 10.2. Верифицировано чисто (Батч 4)

- **F5 хард-срез:** в `insert_graph_fact` после `imp` → `if is_metafact_stopword(subject) or is_metafact_stopword(object):
  imp = min(imp, METAFACT_PENALTY_IMPORTANCE=1)`; `or` покрывает оба направления (subject из списка / object из списка —
  есть тесты на обе стороны); перекрывает и `rule_importance`, и явный `importance=10` (тесты); нормализация строгая
  (casefold/ё/краевая пунктуация) — «сообщения»/«фотку» НЕ режутся (жёстко по ADR D4, документировано);
  «сообщение» — только в center-списке (F3), «стикер» — только в penalty-списке (F5) (тесты `TestStoplistsDistinct`);
  сериализация/сигнатура аддитивны (subject/object в конце → позиционная совместимость всех 8 call-сайтов сохранена);
  `_memorize_facts_inner` реально передаёт `subject=subject, object=obj` (тест).
- **F5 RAG-множитель:** `_importance_factor(imp)=0.5+0.05·clamp(1..10)` ∈ [0.55, 1.0] — монотонный, ограниченный;
  `None`/мусор → 5 (нейтраль 0.75); применяется в **обеих** ветках `_search_graph_facts` (FTS-фолбек и KNN), которые
  взаимоисключающи (KNN → return при наличии строк) → **двойного применения нет**; равные importance сохраняют
  относительный порядок по `weight`/`cosine`; `f.importance` действительно добавлен в SELECT и
  `search_graph_facts_fts` (`database.py:2637`), и `get_graph_fact_records` (`:3448`) → KNN-путь не «нейтрализуется»
  молча (проверено чтением SQL, не только тестом); MMR/дедуп/`touch`/resurrection используют те же `score`/`cosine`
  (`cosine_by_id` — без множителя, осознанно для «резонанса»); формулы weight/time-decay/cosine не изменены;
  golden-путь отдельный (SQL-фильтр `importance >= min_importance`, порог = `settings.NOSTALGIA_GOLDEN_MIN_IMPORTANCE`)
  → мета-факты (imp=1) исключены (тест).
- **F5 канон:** AST-проба — `PREV_FACT_EXTRACT_PROMPT` **байт-в-байт** равен `FACT_EXTRACT_PROMPT` из HEAD
  (649 симв.), новый `FACT_EXTRACT_PROMPT = PREV + 335-байтный аддитивный блок` («ФОКУС НА СОДЕРЖАНИИ», 3 пункта);
  `PROMPT_MIGRATIONS` не расширен (`prompts.extract_system_prompt`/`EXTRACT_PROMPT` не тронуты — только комментарии);
  `_FACT_RETRY_SYSTEM_PROMPT` не менялся; `plans/docs/canon/backlog.md` синхронизирован (байт-тест).
- **F6:** `NAV_TITLES`/`NAV_ORDER`/`TAB_NAV` — Python-метаданные (не ParamSpec/GroupSpec → каталог Δ=0); `TAB_NAV`
  исчерпывающе покрывает все 19 `TAB_RULES`-вкладок, значения ⊆ `NAV_TITLES`, каждая вкладка имеет ≥1 группу
  (нет «мёртвых» nav/секций); `tab_nav(None/'unknown')` → None; `CONFIG_TAB_TITLES[TAB_PERMSOC]` = «PERMsoc»
  (дрейф устранён) + инвариант-тест `CONFIG_TAB_TITLES ↔ web/app.js TABS[].label` (19); API `nav/nav_title/nav_order`
  аддитивны (R16), форма прав `view_roles/edit_roles/default` и 403-guard не изменены; JS-зеркало
  `NAV_GROUP_ORDER`/`NAV_GROUP_TITLES` закреплено parity-тестом с backend; `matrixSections()` группирует
  nav → секция (`TAB_SECTION_ORDER`, fallback `cat:<category>`) → группа (`group_order`) → параметры, поиск
  фильтрует ДО группировки (нет пустых групп), сортировки устойчивы (`order||id`), `web/index.html` рендерит
  новую вложенность (`nav.sections → sec.groups → grp.items`), `#/access`/`#/ai/persona` вне матрицы (нет ParamSpec).
- **Сквозные инварианты:** каталог **436/406/411/90/88/19** (интроспекция; Δ Батча 4 = 0); SQLite **v10**;
  R16 (все новые поля аддитивны); R17 (логи — только классы/числа/ключи); порядок роутеров `bot.py` не тронут.
- **Валидатор:** `.venv/Scripts/python.exe -m pytest -q` → **6137 passed / 0 failed** (67.8 c);
  `node --check web/app.js` OK; `routing_test.js` `JS-UNIT-OK`; `vue_mount_test.js` `VUE-MOUNT-OK`;
  `git diff --check` → exit 0.

### 10.3. Интеграция батчей (сквозной аудит эпика)

- **F7 ↔ F2/F3/F5/F6:** per-chat accessor (`worker_settings`) не конфликтует с F5 (`_importance_factor` читает `hot.get`
  для флагов — прежний путь) и с F6 (nav — чистые метаданные); `count_dream_log/sum_dream_log_tokens(chat_id)` (F7)
  сосуществует с F5-срезом в `insert_graph_fact` (разные таблицы).
- **F3 ↔ F5:** `graph_snapshot` считает `Σ COALESCE(importance, weight)` → мета-факты (imp=1) вносят минимум в score
  сидов, ×2-фаза не зависит от F5 — синергия без конфликтов; RAG-множитель F5 работает в `summary_memory`, скоринг F3 —
  в `database.graph_snapshot` (разные read-пути, двойного влияния нет).
- **F3 ↔ F4:** 150 итераций/авто-отключение physics рассчитаны на плотность 500–800 узлов из F3 (проверено тестом
  плотности и JS-тестами); `truncated` отображается.
- **F2 ↔ F3/F4/F5:** manual-обход гейтов Сна не обходит пороги квалификации кластера → мета-факты (imp=1) не
  дистиллируются и вручную (Σ8 требует ≥8 фактов); F2-поллинг (5с при manual) совпадает с вызовом `GET /api/memory/graph`
  → здесь усиливается риск S10.18-30 (перф).
- **F1 ↔ F5/F6:** `BETTERSTACK_HOST` (+1 REGISTRY) — единственный Δ каталога; F5/F6 Δ=0 → свод 436/406/411/90/88/19
  сходится (проверено интроспекцией).
- **Общий вывод:** конфликтов файлов/семантики между батчами не найдено; все 4 батча собираются в один зелёный прогон
  (6137/0) и один инвариант каталога.

### 10.4. Итоговая сводка эпика 10.18 (F1–F7, БАТЧИ 1–4)

| Severity | Открыто | Коды |
|---|---|---|
| Critical | **0** | — |
| High | **0** | — |
| Medium | **0** | — (S10.18-30 CLOSED после фикс-прохода, §10.6) |
| Low | **1** | S10.18-29 (deep-manual маркер, Батч 3) — S10.18-35 CLOSED (§10.6) |
| Info | **10** | S10.18-12, -13, -18, -19, -20, -31, -32, -33, -34, -37 — S10.18-36 CLOSED (§10.6) |

> **Примечание (S10.18-30, исправлено после фикс-прохода 15.09.2026):** перф ×2-фазы `graph_snapshot`
> **CLOSED**; сводка §10.4 была устаревшей — она дублировала §9 без перепроверки (см. §10.6).

Сводная таблица для @Architect/@PM:

| ID | Sev | Фича / батч | Суть (кратко) | Действие |
|---|---|---|---|---|
| S10.18-30 | Medium | F3 / Батч 3 | ×2-фаза `graph_snapshot` ~176 мс при 200 beliefs и линейно растёт (до секунд) → stall event loop на каждый `GET /api/memory/graph` (15с / 5с при manual) | **CLOSED** (fix-pass, §10.6): набор токенов + `_belief_name_participates`, замер 241 мс → 55.5 мс на референсе |
| S10.18-29 | Low | F2 / Батч 3 | manual-каскад не ставит `_manual_deep_until` → `deep_sleep.manual=False`, `active_until=None` вне окна | фикс в `run_once`/`_maybe_deep_after_sleep` |
| S10.18-35 | Low | F5 / Батч 4 | хард-срез покрывает только memorise-путь; эпи-мерж ре-вычисляет importance от origin (мета-факт 1 → 4) | **CLOSED** (fix-pass, §10.6): merge переносит пенальти (кластер imp≤1 → merged imp=1) |
| S10.18-12 | Info | F7-контекст | `NostalgiaWorker` — остаточный РАЗРЫВ spec §2.3 (global-only) | backlog T-1764 |
| S10.18-13 | Info | вне батча | pre-existing фрагмент SSH-пароля в `plans/archive/…/spec.md:35` (файл отслеживаемый) | R10.18-12 (очистка + скан истории) |
| S10.18-18/-19/-20 | Info | F2/F1 | `?deep=1` без капа; `tokens_per_day` без фильтра `kind`; `previous` kill-switch = effective | по желанию/backlog |
| S10.18-31/-32/-33 | Info | F3 | варианты стоп-листа с дефисом; self-loop ×2; `upsert_edge` при отсутствии узла | по желанию/backlog |
| S10.18-34 | Info | сводка | агрегация открытых Info Батча 1 | — |
| S10.18-36 | Info | F6 | spec §3.1 говорит «3 nav», фактически 4 (+«Прочее») | **CLOSED** (fix-pass, §10.6): spec §3.1 синхронизирован с ADR-1018-6 D4 |
| S10.18-37 | Info | F5 | множитель importance меняет RAG-порядок для всех чатов | живая проверка (T-1724/T-1749) |
| S10.18-38 | Info | сводка | перечень сквозных остатков эпика | — |

### 10.5. Вердикт Батча 4 и эпика

- **Батч 4: 0 Critical / 0 High**; F5-срез/канон/множитель и F6-nav реализованы корректно и аддитивно,
  тесты поведенческие (не только константы), каталог Δ=0.
- **Эпик 10.18 (F1–F7, батчи 1–4): 0 Critical / 0 High открыто.**
  **Готов к передаче на @Reviewer/@PM (T-1749/T-1757) → Merge/архивация → деплой @DevOps** — блокеров нет.
  После фикс-прохода **S10.18-30** (Medium, перф ×2) и **S10.18-35/-36** закрыты (см. §10.6); остаётся
  S10.18-29 (Low, deep-manual маркер) и Info/backlog (S10.18-13 — вне батча, трекается как R10.18-12).
- **Валидатор эпика:** pytest **6137 passed / 0 failed** (67.8 c); `node --check web/app.js` OK; `JS-UNIT-OK`;
  `VUE-MOUNT-OK`; `git diff --check` exit 0; каталог 436/406/411/90/88/19; SQLite v10.

### 10.6. Пост-фикс-актуализация (@Builder fix-pass, 15.09.2026)

Финальный консистентный проход эпика 10.18; §10.4 исправлена — она дублировала статус из §9 без перепроверки
(к моменту сводки S10.18-30 был уже закрыт кодом, но в таблицу попал как открытый Medium).

| ID | Sev | Статус | Доказательство |
|---|---|---|---|
| S10.18-30 | Medium | **CLOSED** | ×2-фаза `graph_snapshot` ускорена: `_belief_name_participates` (`database.py:3780-3803`) + набор токенов блоба вместо per-node `re.search`; замер на референсе **241 мс → 55.5 мс**. Семантика границ токенов сохранена (однословное — точное совпадение, многословное — padded-последовательность; «тема» ⊄ «система»). |
| S10.18-35 | Low | **CLOSED** | Merge-путь переносит F5-пенальти: `get_live_graph_facts` отдаёт `importance`; `memory_maintenance._merge_cluster` при **всех** членах кластера `imp<=1` → `importance=METAFACT_PENALTY_IMPORTANCE` (1), иначе прежний `rule_importance` (`None`). Тесты `TestEpisodeMergePenalty` (2): мерж двух мета-фактов → imp=1; обычный мерж → imp=4 (без регресса). Существующие merge-тесты зелёные. |
| S10.18-36 | Info | **CLOSED** | `spec.md` F6 §3.1 синхронизирован с ADR-1018-6 D4: 4 nav-группы = 3 из `NAV_ORDER` + «Прочее» (5 content-параметров с `tab=None`); поправлены §2/§3.1/§9 Q1. |

Примечание: статус S10.18-30 исправлен на CLOSED **после** фикс-прохода (@Builder), когда перф-фикс был
подтверждён замером; §10.4 приведена в соответствие.

*Секция §10.6 — @Builder 15.09.2026 (финальный консистентный проход эпика 10.18).*

*Секция Батча 4 и итоговая сводка эпика сгенерированы @Scanner 15.09.2026 (Шаг 6 OpenSpec, Strict Workflow).*




