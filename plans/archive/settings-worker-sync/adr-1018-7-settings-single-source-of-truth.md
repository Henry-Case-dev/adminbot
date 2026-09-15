# ADR-1018-7 — Единый источник истины настроек: per-chat DB > глобальный DB > env-дефолт, реактивная переконфигурация воркеров

- **Статус:** Proposed
- **Дата:** 2026-09-15
- **Раунд:** 10.18, фича F7 `settings-worker-sync` (T-1758)
- **База:** HEAD `118a03c`. **Связано:** ADR-1018-2 (manual-приоритет Сна), F-7/F-10/F-14 (chat_params, гейты, DM-скоуп), раунд 10 (multi-chat scaling), раунд 10.14 T-1493 («аудит путей чтения»).
- **AMEND:** уточняет контракт F-7 §6 и F-14 (§3.1): слой чата (`chat_profiles.chat_params.overrides`) становится **обязательным** для воркеров и статус-API, а не «только для путей ответа». Не supersede — расширение области действия того же приоритета.
- **SUPERSEDE (частично):** снимает неявный инвариант «воркеры читают только глобальный `hot.get` (бот_settings)».

## Context

### Симптом владельца (current_task.md UPD п.3, строки 119-121)
«Тумблеры Dream/DeepSleep в мини-аппе **УЖЕ БЫЛИ ВКЛЮЧЕНЫ** все эти дни, но бэкенд показывает их выключенными.» Требование: не переключать флаг в коде, а найти и починить **рассинхрон UI → воркеры**, воркеры должны реактивно слушаться ползунков.

### Факты из кода (аудит, не догадки)

1. **Глобальный путь записи рассинхрона НЕ даёт.**
   `POST /api/config` без `X-Chat-Id` → `web/api/routes.py::_post_config_global` (`:703-744`) → `ConfigCache.set` (`services/config_cache.py:394-416`) пишет PG `bot_settings` **и** in-memory `self._settings` в том же процессе; `hot.get` (`services/hot_config.py:71`) читает тот же объект. Если бы тумблер писался глобально, воркер увидел бы значение немедленно.

2. **Разрыв — на границе «слой чата vs глобальный слой».**
   - Фронт: `api()` добавляет `X-Chat-Id`, когда выбран чат (`web/app.js:1536-1537`); `saveConfigItem` шлёт `global: per_chat === false` (`:3350-3358`). Для ключей категорий `memory`/`flags` (`per_chat=True`, `services/param_catalog.py:52-54,110-119`) запись идёт **в слой чата**.
   - Бэк: `post_config` при `X-Chat-Id` пишет `chat_params.set_chat_params(..., {"overrides": …})` (`web/api/routes.py:438,485-488`; `services/chat_params.py:254-311`).
   - Воркеры: `DreamWorker._key` = `hot.get(f"memory.dream_{name}", default)` (`services/dream_worker.py:252-253`) — **только глобальный слой**; `flags.deep_sleep_enabled` — `hot.get("flags.deep_sleep_enabled", …)` (`:305-306,1103,1124,1191`). Слой чата не читается.
   - Статус-API: `cognition_status` (`web/api/memory_agi.py:442-444`) и `deep_sleep_status` (`:386`) тоже читают только глобально, **хотя endpoint принимает `chat_id`**.
   - **Структурный усилитель:** `_DM_DISABLED_OVERRIDES` (`services/chat_params.py:328-334`) при `ensure_scope_profile(dm=True)` пишет в ЛС-профиль `memory.dream_enabled=False` — в слой, невидимый воркеру; UI ЛС при этом честно показывает значение из override.
   - **Итог:** админ включил → UI показывает ON (значение override чата) → воркер/статус видят глобальное `False`/default → «бэкенд показывает выключено».

3. **Второй независимый дефект — отсутствие реактивности планировщика.**
   `DreamWorker.start()` (`services/dream_worker.py:294-351`, вызов `bot.py:560`) регистрирует джоб `dream_tick`/`deep_sleep_tick` **один раз** по значению глобального слоя на момент старта. Переключение ON в рантайме **не создаёт** джоб; OFF — **не снимает**. Изменение вступает в силу только после `systemctl restart admin_bot`.

4. **Третий дефект — нет подписчика NOTIFY.**
   `set_chat_params` шлёт `pg_notify('chat_params_updated', …)` (`services/chat_params.py:37,304`), но `LISTEN` на этот канал в коде **отсутствует** (grep по `services/` — только определение константы). Инвалидация кэша работает лишь локально (`cache.invalidate_chat`, `:306-310`); при выносе web/бот в разные процессы изменения подхватятся не раньше TTL `_CACHE_TTL = 120.0` (`:38,161-164`).

5. **Четвёртый дефект — UI-размещение ключа `flags.deep_sleep_enabled`.**
   `TAB_MOD_SLEEP` (`services/param_catalog.py:1823-1825`) покрывает только `(memory, {memory_dream})`; группа `flags_memory` (где живёт `DEEP_SLEEP_ENABLED`, `:831-835`) рендерится лишь в `TAB_MEMORY_RAG` («Память и граф знаний», `:1844-1850`). Тумблер Глубокого сна **не виден в окне «Сон»** — источник ложных ожиданий и «нажимал, а не то».

### Инварианты, которые нельзя сломать
R16 (id — ключ), R17 (логи без секретов/текстов), fail-open на ошибках PG (бот жив), прецедент резолва per-chat → global → default (`services/chat_params.py::get_chat_param`, `_resolve_from_root:211-244`), порядок роутеров `bot.py`.

## Decision

### D1. Приоритет значения — явный и единый
Для любого параметра воркера/статуса: **`chat_params.overrides[key]` (каст по каталогу) → `hot.get(key)` (глобальный DB) → `settings`-дефолт (env)**. Это ровно семантика уже существующего `get_chat_param`, но распространённая **обязательно** на воркеры и статус-API.

### D2. Единый accessor для воркеров
Новый модуль `services/worker_settings.py` (или расширение `services/chat_params.py`; выбор — @Builder, сигнатура фиксирована):

```python
async def resolve_setting(key: str, *, chat_id: int | None = None,
                          default=None, log_source: bool = False) -> object
async def resolve_setting_cached(key: str, *, chat_id: int | None = None,
                                 default=None) -> object
```
- `chat_id=None` → `hot.get(key, default)` (глобальный плановый путь).
- `chat_id=<id>` → `overrides[key]` (с `normalize_value`-кастом, как `_resolve_from_root`) → `hot.get` → `default`.
- `resolve_setting_cached` — тонкая обёртка над `ChatParamsCache` (уже кэш с TTL 120с и локальной инвалидацией), чтобы не плодить PG-раундтрипы в горячем цикле.
- Обязательный R17-safe `logger.debug`/`info` источника: `[settings] key=%s | chat=%s | source=chat|global|default | value=%s` (только числа/bool — не секреты и не свободный текст).

### D3. DreamWorker: per-chat резолв там, где он осмыслен
- **Плановый tick** (`_run`/`_tick`) — глобальный слой (он выбирает чаты-кандидаты; per-chat гейт уже применяется в `gates_enabled`, `services/feature_gates.py:67-89`). Но при обработке **конкретного** чата все параметры резолвятся по этому чату: `_process_chat`/`_candidates`/`_distill_cluster` получают `chat_id` и читают через `resolve_setting(key, chat_id=chat_id, default=…)`.
- **Ручной `run_once(chat_id=…)`** — резолв по `chat_id` (manual вообще обходит гейты, см. ADR-1018-2).
- Сигнатура-расширение: `_key()` сохраняется как глобальный helper (обратная совместимость тестов), вводится `async _key_for(chat_id, name, default)`.
- Минимально обязательный набор (P0 в таблице задачи T-1760): `memory.dream_enabled`, `flags.deep_sleep_enabled`, `memory.deep_sleep_trigger`, `memory.dream_repeat_threshold`, `memory.dream_importance_sum_threshold`, `memory.dream_window_start_hour`, `memory.dream_window_end_hour`, `flags.persona_enabled`.
- **Тик-слой — осознанно глобальный** (согласовано со spec §2.3, фикс R10.18-5): `memory.dream_min_new_facts_per_chat`, `memory.dream_max_chats_per_run`, `memory.dream_quiet_check_minutes`, `memory.dream_initial_window_hours` — это параметры ОДНОЙ SQL-выборки чатов-кандидатов на весь тик (`_run`) и капы прогона. Per-chat резолв здесь неприменим конструктивно; per-chat решение «работать/не работать» реализовано в `_process_chat` через `_key_for`. Гибрид: `initial_window_hours` также резолвится per-chat в `_candidates(chat_id)` (окно выборки фактов конкретного чата).
- **Слой гейта: kill-switch vs master-флаг** (фикс R10.18-3, выравнивает spec §8 R4 с кодом). Порядок в `gates_enabled(chat_id, feature, fallback=…)`: явный per-chat `gates[feature]` → явный глобальный **kill-switch** `flags.<feature>_enabled` → `fallback` (per-chat master `memory.dream_enabled`) → глобальный флаг (`_global_flag_value`) → `False`. Явный kill-switch ВСЕГДА побеждает `fallback`: иначе `flags.dream_enabled=false` не останавливал бы тик при per-chat override ON (регрессия). `fallback` учитывается только при отсутствии явного kill-switch.

### D4. Реактивная переконфигурация планировщика
- `DreamWorker.start()` регистрирует джоб **всегда** (не зависит от флага), а решение «работать/не работать» принимается **внутри** `_tick`/`_deep_tick` через `resolve_setting(“memory.dream_enabled”, …)`. Тогда переключение тумблера действует без рестарта.
- Альтернатива (если «всегда зарегистрированный джоб» нежелателен): `reconcile_schedule()` — вызывается из `POST /api/config` (и/или по `LISTEN`) и создаёт/удаляет job по текущему значению. Оба варианта допустимы; **рекомендация — «джоб всегда + ранний return в тике»** (проще, идемпотентно, без гонок с `AsyncIOScheduler`).
- При выключении on-the-fly **не прерывать** уже идущий `_run` (уважать `_run_lock`); новое значение применяется со следующего тика.

### D5. Статус-API читает тот же слой
`cognition_status`/`deep_sleep_status`/`GET /api/memory/deep-sleep` резолвят `enabled` по `chat_id` из query (если он передан) через D2, иначе глобально; в ответ добавляется `source` (`chat|global|default`) — R16-аддитивно. `active/active_until`-логика (F2 §4.5) не меняется.

### D6. Закрытие «мёртвого» NOTIFY
Добавить `LISTEN chat_params_updated` (asyncpg) в runtime и на событие вызывать `ChatParamsCache.invalidate_chat(chat_id)`. Fail-open: нет пула/ошибка LISTEN → WARNING, работаем на TTL 120с. Это закрывает кросс-процессный рассинхрон и делает реактивность честной. Если кросс-процессный сценарий не подтверждён — задача понижается до P2, но TTL остаётся документированной границей.

### D7. `#/modules`-тумблеры честно отражают scope
`moduleEnabled()`/`toggleModule()` (`web/app.js:2368-2386`) работают в активном scope (global или chat) — это корректно; дефект был не во фронте, а в чтении на бэке. Дополнительно: в окне «Сон» показать реальный тумблер `flags.deep_sleep_enabled` (см. D8), чтобы «включил глубокий сон» означало именно то, что кажется.

### D8. UI-размещение ключей Сна (Δ каталога = 0)
`TAB_MOD_SLEEP` дополняется правилом `(CATEGORY_FLAGS, frozenset({"flags_memory"}))`? **Нет** — это вытащило бы в окно «Сон» всю группу памяти. Решение: **не расширять TAB_RULES** (инвариант 19 секций и `mapped=88` сохраняется), а добавить в окно «Сон» **ссылку-навигацию** на раздел «Память» / либо показать два ключа через существующий per-key механизм, если он есть (уточнить у @Builder, `T-1763`). Минимально допустимый вариант: подпись рядом с бейджем «Глубокий сон» с указанием, где включён рубильник. Каталог-Δ = 0 в любом случае.

### D9. Источник значения в логах — обязателен
Каждое решение воркера «включено/выключено» логируется с `source=` (chat/global/default) и `chat_id`. Это делает будущие рассинхроны видимыми в journald без отладки.

## Consequences

**Positive**
- Симптом владельца устранён: включение тумблера в любом scope реально влияет на воркеры; бэкенд-статус соответствует UI.
- Переключение работает **без рестарта** (джоб всегда зарегистрирован; резолв на каждом тике).
- Единая точка чтения → будущий дрейф невозможен без явного нарушения контракта; `source=` в логах делает его видимым.
- Закрыт мёртвый NOTIFY; восстановлена нормальная семантика слоя чата.

**Negative**
- Per-chat резолв в горячем цикле — дополнительные async-вызовы; митигируется кэшем `ChatParamsCache` (TTL 120с) и тем, что резолв делается раз на чат, а не на факт.
- «Джоб всегда зарегистрирован» означает, что тик просыпается вхолостую при выключенном Сне; цена — один ранний return раз в `tick_minutes`.
- При `source=chat` и последующем откате глобального флага поведение чата не изменится — это **ожидаемо** (per-chat приоритет), но требует понимания оператором; фиксируется в логах.
- Список ключей из D3 неполон по определению (только воркеры Сна + persona); для ностальгии/лора аналогичная миграция — кандидат в backlog.

## Alternatives

- **A1. Просто переключить `DREAM_ENABLED=True` в `settings.py`.** Отклонено прямо владельцем (UPD п.3, строки 119-121): не лечит рассинхрон и не даёт реактивности.
- **A2. Запретить per-chat запись для `memory.*`/`flags.*` (сделать всё глобальным).** Отклонено: ломает F-7/F-14 (per-chat настройки — продуктовая фича) и DM-скоуп.
- **A3. Читать per-chat только в API-статусе, воркеры оставить глобальными.** Отклонено: симптом остаётся (воркер не работает), это косметика.
- **A4. Ввести отдельный флаг «читать per-chat».** Отклонено: владелец требует отсутствия флагов для базовой логики; правильный приоритет должен быть безусловным.
- **A5. Поллинг `bot_settings`/`chat_params` по таймеру каждые N секунд.** Отклонено: лишняя нагрузка и задержка; `ChatParamsCache`+LISTEN+«джоб всегда» покрывают кейс.
- **A6. WebSocket-пуш настроек из админки в воркеры.** Отклонено: в проекте нет WebSocket (ADR-1017-3 §2.6), и задача решается на сервере.

## References

- `web/app.js:1520-1537` (`api`/X-Chat-Id), `:2336-2386` (`openModuleWindow`/`moduleEnabled`/`toggleModule`), `:3306-3358` (`saveConfigItem`)
- `web/api/routes.py:279-400` (`get_config`), `:403-498` (`post_config`, слой чата), `:703-744` (`_post_config_global`), `:501-522` (`params-meta`)
- `services/chat_params.py:37-38,60-76,152-182` (кэш/TTL), `:211-244` (`get_chat_param`/`_resolve_from_root` — эталон резолва), `:254-311` (`set_chat_params`+NOTIFY), `:328-334` (`_DM_DISABLED_OVERRIDES`)
- `services/config_cache.py:352-358` (`get`/`get_all`), `:394-416` (`set`)
- `services/hot_config.py:32-76`; `services/param_catalog.py:52-54` (per-chat категории), `:110-119` (`per_chat`), `:831-835` (`DEEP_SLEEP_ENABLED`), `:1364-1448` (`memory_dream`), `:1823-1825` (`TAB_MOD_SLEEP`), `:1844-1850` (`TAB_MEMORY_RAG`)
- `services/dream_worker.py:252-253` (`_key`), `:294-351` (`start`), `:420-478` (`_run`), `:482-648` (`_process_chat`), `:1099-1211` (`_maybe_deep_after_sleep`/`_deep_tick`/`_run_deep_once`), `:1317-1331` (persona-гейт)
- `services/feature_gates.py:33-89` (FLAG_KEYS/gates_enabled); `web/api/memory_agi.py:386,442-444,486-501,528-540`
- `services/direct_chat_service.py:581-593` (эталон per-chat резолва на пути ответа)
- `bot.py:536-565` (старт DreamWorker), `:839-850` (порядок ConfigCache/chat_params/worker_budget)
- ADR-1018-2 (manual), F-7 §6, F-10 §5-6, F-14 §3.1; задачи T-1758…T-1764.

## Addendum (10.18, БАТЧ 1, фиксы @Scanner S10.18-1…-12)

Уточнения контракта, не меняющие D1/D2 (каталог-Δ=0, DDL нет):

- **D3 (budgets): `memory.dream_distillations_per_day`/`dream_tokens_per_day` — per-chat не только в лимите, но и в РАСХОДЕ.** `DatabaseService.count_dream_log`/`sum_dream_log_tokens` получили keyword-only `chat_id` (SQL `AND chat_id = ?`); `_process_chat` считает суточный расход по чату. Иначе per-chat override сравнивался с чужим/общим расходом (S10.18-1). `kind='decay_run'` пишется с `chat_id=0` и бюджет дистилляций не искажает.
- **D3 (decay): глобальный этап.** `_maybe_decay` дополнительно гейтится глобальным master `memory.dream_enabled` (chat_id=None). Decay охлаждает beliefs всех чатов — per-chat резолв неприменим; гейт возвращает pre-10.18 поведение (S10.18-4).
- **D3 (deep trigger): per-chat в `_deep_tick`.** Тик резолвит `memory.deep_sleep_trigger`/`deep_sleep_hour` по каждому чату-кандидату (а не глобально) — per-chat `fixed`/`after_sleep` исполняются по override (S10.18-2). Fallback-путь — `_deep_candidate_chat_ids`.
- **D3/D5 (статус = поведение):** `gates_enabled`-fallback передаётся во всех статус-потребителях (`gates_get`, `allowed_features`, `oversight`, `web/api/oversight`); `cognition_status` отдаёт аддитивное `dream.effective` и считает `active` по нему (S10.18-3).
- **D4/manual (R10.18-5):** manual-каскад `_maybe_deep_after_sleep(only_chat=)` идёт по целевому чату; без цели — кап `_MANUAL_DEEP_CASCADE_MAX`.
- **D6 (LISTEN lifecycle):** `ChatParamsNotify.stop()` вызывается из `on_shutdown()`; `_on_notify` держит сильные ссылки на invalidate-задачи (`_pending` + done-callback) (S10.18-7/-11).
