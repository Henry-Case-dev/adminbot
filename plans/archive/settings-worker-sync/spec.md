# Spec F7 — `settings-worker-sync` (единый источник истины настроек: UI → воркеры без рассинхрона)

> **Раунд:** 10.18 (Step 2 @Architect, итерация 2 после human-gate, 15.09.2026). **Тип:** backend (воркеры + статус-API + accessor) + точечно frontend. **Приоритет:** **P0 — самый важный пункт итерации** (симптом владельца: тумблеры включены в мини-аппе, бэкенд показывает OFF).
> **ADR:** `adr-1018-7-settings-single-source-of-truth.md` (обязателен). **Ссылается:** ADR-1018-2 (manual-приоритет Сна) — обязательная ссылка из F2.
> **Задачи:** T-1758…T-1764. **Baseline:** HEAD `118a03c`; pytest 6007 passed / 0 failed; каталог 435/406/411/90/88/19; SQLite v9.
> **Источник:** `plans/current_task.md` UPD п.3 (строки 119-121) + п.4 («остальные решения — ДА»).
> **R17:** в документе и логах — только имена ключей, числа, `source`, id чатов. Без значений секретов и без текстов фактов/промптов.

## 0. Выбор места (обоснование выноса в отдельную фичу)

Решение: **новая фича-папка `settings-worker-sync`, а не расширение F2.** Обоснование:
1. **Другой класс дефекта.** F2 — про Сон (пороги/manual/каскад/бейджи). Здесь — мета-инфраструктура «UI-запись в слой чата ↔ чтение воркером», затрагивающая минимум `DreamWorker`, `NostalgiaWorker`, `feature_gates`, статус-API и `ChatParamsCache`.
2. **Объём и риск.** Нужны: аудит пайплайна, единый accessor, реактивная переконфигурация планировщика, LISTEN-подписчик, таблица «настройка → пишется → читается → статус» по всем воркерам. Это не укладывается в P0-скоуп F2 без потери фокуса.
3. **ADR-1018-2 обязан ссылаться** (требование владельца) — ссылка дешевле слияния.
4. **Порядок в раунде:** F7 — **первая** (блокер для F2/F4/F5: пока настройки не доходят, «ослабленные пороги» и «каскад» проверять не на чем).

## 1. Контекст и цель

Владелец: «в интерфейсе мини-аппа тумблеры Dream/DeepSleep **УЖЕ БЫЛИ ВКЛЮЧЕНЫ** все эти дни, но бэкенд показывает их выключенными». Требование: не переключать флаг в коде, а найти и починить **рассинхрон UI → воркеры**; воркеры должны **реактивно** слушаться ползунков из админки (без рестарта).

**Цель:** любое изменение настройки в админке (глобально или в scope чата) немедленно и предсказуемо влияет на поведение воркеров и отражается в статус-API; источник каждого значения виден в логах.

## 2. Полный аудит пайплайна (C1) — установленные факты

### 2.1. Пайплайн `UI-ползунок → API → БД → воркер`

| Звено | Факт | Файл/строка |
|---|---|---|
| UI-тумблер Сна | `MODULES[mod_sleep].toggleKey = 'memory.dream_enabled'`; `toggleModule` → `saveConfigItem` | `web/app.js:351-353, 2375-2386` |
| Scope → заголовок | `api()` добавляет `X-Chat-Id`, если `activeChatId != null` и `global !== true` | `web/app.js:1520-1537` |
| Решение global/chat | `isGlobal = (item.per_chat === false)`; POST `/api/config` c `global: isGlobal` | `web/app.js:3350-3358`; `services/param_catalog.py:110-119` |
| Запись (global) | `_post_config_global` → `ConfigCache.set` → PG `bot_settings` **+ in-memory `_settings`** | `web/api/routes.py:703-744`; `services/config_cache.py:394-416` |
| Запись (chat) | `chat_params.set_chat_params(chat_id, {"overrides": …})` → PG `chat_profiles.chat_params` | `web/api/routes.py:438, 485-488`; `services/chat_params.py:254-311` |
| Чтение воркером | `DreamWorker._key` = `hot.get(f"memory.dream_{name}", default)` — **только глобальный слой** | `services/dream_worker.py:252-253` |
| Чтение deep-флага | `hot.get("flags.deep_sleep_enabled", settings.DEEP_SLEEP_ENABLED)` | `services/dream_worker.py:305-306, 1103, 1124, 1191` |
| Чтение статус-API | `hot.get("memory.dream_enabled", …)`, `hot.get("flags.deep_sleep_enabled", …)` — глобально, **`chat_id` игнорируется** | `web/api/memory_agi.py:442-444, 386` |
| Чтение gates (kill-switch) | `gates_enabled(chat_id, feature)` — **корректно** читает `chat_params.gates` → глобальный флаг → False | `services/feature_gates.py:67-89` |

### 2.2. Точка разрыва (точная)

**Главный разрыв:** слой чата (`chat_profiles.chat_params.overrides`) **пишется UI-ом**, но **не читается** ни `DreamWorker`, ни `cognition_status`/`deep_sleep_status`.
- `services/dream_worker.py:252-253` — `_key()` не принимает `chat_id` вообще.
- `web/api/memory_agi.py:442-444` — `enabled` считает глобально, хотя endpoint принимает `chat_id` (`:425-430`).
- Усилитель: `_DM_DISABLED_OVERRIDES` (`services/chat_params.py:328-334`) **принудительно** кладёт `memory.dream_enabled=False` в надстройку ЛС-профиля — слой, воркеру невидимый.

Именно поэтому UI (значение из override чата) показывает ON, а статус-API и воркер (глобальный слой) — OFF. Глобальный путь записи рассинхрона дать не может: `cache.set` обновляет PG и in-memory `_settings` в том же процессе, `hot.get` видит новое значение немедленно.

**Разрыв №2 (реактивность планировщика):** `DreamWorker.start()` регистрирует `dream_tick`/`deep_sleep_tick` **один раз** на старте по значению глобального слоя (`services/dream_worker.py:294-351`; вызов `bot.py:560`). Включение тумблера в рантайме **не создаёт** джоб, выключение **не снимает** → требуется `systemctl restart admin_bot`.

**Разрыв №3 (мёртвый NOTIFY):** `set_chat_params` шлёт `pg_notify('chat_params_updated', …)` (`services/chat_params.py:37,304`), но `LISTEN` на канал в коде **отсутствует**. Кросс-процессная инвалидация не работает; локальная — есть (`:306-310`); при раздельных процессах — до `_CACHE_TTL = 120.0` (`:38`).

**Разрыв №4 (UI-размещение ключа):** `TAB_MOD_SLEEP` покрывает только `(memory, {memory_dream})` (`services/param_catalog.py:1823-1825`); `flags.deep_sleep_enabled` живёт в группе `flags_memory` (`:831-835`) и рендерится только в `TAB_MEMORY_RAG` (`:1844-1850`) → тумблера Глубокого сна в окне «Сон» нет.

### 2.3. Таблица C4 — «настройка → пишется → читается → статус»

| Настройка (pg-key) | Куда пишет UI | Откуда читает воркер/API | Статус | Действие (задача) |
|---|---|---|---|---|
| `memory.dream_enabled` | global: `bot_settings`; chat: `chat_profiles.chat_params.overrides` (`routes.py:438`) | `dream_worker._key("enabled")` **global-only** (`:252-253`); статус `memory_agi.py:442` **global-only**, `chat_id` игнорируется | **РАЗРЫВ** (chat-запись не читается; воркер не реагирует без рестарта) | T-1760 per-chat резолв; T-1761 реактивный джоб; T-1762 статус-API |
| `flags.deep_sleep_enabled` | global/chat через ту же схему; **но тумблера нет в окне «Сон»** | `hot.get("flags.deep_sleep_enabled")` **global-only** (`:305,1103,1124,1191`); статус `memory_agi.py:386` | **РАЗРЫВ** (×2: chat-слой + отсутствует UI-доступ из Сна) | T-1760; T-1763 UI |
| `memory.deep_sleep_trigger` | global/chat (`TAB_MOD_SLEEP` его показывает) | `resolve_setting_cached(..., chat_id=)` **per-chat** в `_maybe_deep_after_sleep` И `_deep_tick` (S10.18-2); статус — глобально | **OK** (per-chat trigger/hour в fixed-тике) | T-1760 + S10.18-2 |
| `memory.deep_sleep_hour` | global/chat | `hot.get(...)` **global-only** (`:1132,489`) | **РАЗРЫВ** | T-1760 |
| `memory.dream_repeat_threshold` | global/chat | `self._key(...)` **global-only** (`:522-524`) | **РАЗРЫВ** | T-1760 |
| `memory.dream_importance_sum_threshold` | global/chat | `self._key(...)` **global-only** (`:524-525`) | **РАЗРЫВ** | T-1760 |
| `memory.dream_min_new_facts_per_chat` | global/chat | `self._key(...)` (`:443-445`) — **глобальный тик-слой отбора кандидатов** (одна SQL-выборка по всем чатам) | **OK / осознанно** (per-chat гейт — в `_process_chat`; порог кандидатов — свойство глобальной выборки) | документировано (ADR-1018-7 D3) |
| `memory.dream_max_chats_per_run` | global/chat | `self._key(...)` (`:446-448,1159-1161`) — кап на прогон (тик/глубокий) | **OK / осознанно** (кап прогона глобальный по дизайну; per-chat неприменим) | документировано (ADR-1018-7 D3) |
| `memory.dream_max_clusters_per_run` | global/chat | `self._key(...)` **global-only** (`:539-541`) | **РАЗРЫВ** | T-1760 |
| `memory.dream_distillations_per_day` | global/chat | `self._key_for(chat_id, …)` **per-chat** — и лимит, и суточный счётчик (`count_dream_log(..., chat_id=)`) | **OK** (S10.18-1: per-chat резолв + per-chat расход; иначе чат глушился чужим расходом) | T-1760 + S10.18-1 |
| `memory.dream_tokens_per_day` | global/chat | `self._key_for(chat_id, …)` **per-chat** — и лимит, и суточная сумма (`sum_dream_log_tokens(..., chat_id=)`) | **OK** (S10.18-1) | T-1760 + S10.18-1 |
| `memory.dream_window_start_hour` / `_end_hour` | global/chat | `self._key(...)` **global-only** (`:703-706,445-446,475-476`) | **РАЗРЫВ** | T-1760 |
| `memory.dream_quiet_check_minutes` | global/chat | `self._key(...)` (`:449-451`) — глобальный порог «тишины» в тик-выборке | **OK / осознанно** (глобальный тик-слой) | документировано (ADR-1018-7 D3) |
| `memory.dream_initial_window_hours` | global/chat | тик-выборка — `self._key(...)` (`:440-442`); фактическая выборка фактов чата — `self._key_for(chat_id, …)` (`:668-670`) | **OK / гибрид** (отбор кандидатов — глобальный тик-слой; окно фактов по чату — per-chat) | документировано (ADR-1018-7 D3) |
| `memory.dream_tick_minutes` | global/chat | `self._key(...)` **global-only**, применяется только при `start()` (`:312-314`) | **РАЗРЫВ** (не реактивно по определению) | T-1761 (перерегистрация тика) |
| `memory.deep_sleep_min_interval_hours` | **нет в каталоге** (код-константа `_DEEP_SLEEP_MIN_INTERVAL_HOURS=20`) | `_hot_number("memory.deep_sleep_min_interval_hours", 20)` (`:1207-1209`) | **OK / осознанно** (ключ читается через hot, дефолт код) | документировать |
| `limits.deep_sleep_top_k` | global/chat (`TAB_MEMORY_RAG`) | `settings.DEEP_SLEEP_TOP_K` / `hot` (`:1231-1232,347`) | **OK** (глобально, чат-слой не приоритетен; документировать) | T-1764 (аудит-таблица в docs) |
| `limits.deep_sleep_max_paradigms_per_run` | global/chat | `hot.get(...)` (`:348`) | **OK** (см. выше) | T-1764 |
| `limits.deep_sleep_tokens_per_day` | global/chat | `_deep_budget_ok`/worker_budget | **OK** (учёт бюджета — глобальный по дизайну) | T-1764 |
| `flags.persona_enabled` | global/chat | traits: `_persona_gate(chat_id, …)` — **per-chat-aware** (`:1321-1324`); API `routes.py:1488-1494` — **per-chat-aware**; `direct_chat` — per-chat (`:590-592`) | **OK** (эталон корректного резолва) | сохранить как образец |
| `flags.summary_enabled` | global/chat | воркеры Саммари — per-chat (прецедент) | **OK** | — |
| `flags.dream_enabled` (канон гейта) | global (FLAG_KEYS) | `feature_gates._global_flag_value` (`:51-64`) | **OK** (гейт), но `memory.dream_enabled` (второй ключ) не приоритезирован по чату | T-1760 |
| `chat_params.gates[dream]` | `PUT /api/chat/{id}/gates` → `set_feature_gate` | `gates_enabled(chat_id, "dream")` — **per-chat-aware** (`:67-89`) | **OK** | сохранить |
| `memory.nostalgia_enabled` | global/chat | `NostalgiaWorker` — global-only (аналогично Сну) | **РАЗРЫВ (аналогичный)** | T-1764 (backlog-задача/кандидат) |

**Итог:** 10 ключей Сна + 1 гейт-ключ — в состоянии **РАЗРЫВ**; 4 ключа тик-слоя (`min_new_facts_per_chat`, `max_chats_per_run`, `quiet_check_minutes`, `initial_window_hours`) — **OK / осознанно**: это параметры глобального тик-отбора кандидатов (ADR-1018-7 D3), per-chat гейт применяется в `_process_chat`; 3 ключа `gates`/`persona` — **OK** и служат эталоном; `nostalgia` — аналогичный разрыв, выносится в backlog (вне P0).

## 3. Требуемое поведение

1. **(C2) Воркеры читают реальный конфиг чата** через единый accessor, приоритет — per-chat DB > глобальный DB > env-дефолт; резолв — с кэшем/TTL.
2. **(C2) Реактивность без рестарта:** переключение тумблера действует со следующего тика; включение/выключение Сна не требует `systemctl restart`.
3. **(C3) Единый источник истины:** приоритет зафиксирован в одном месте и переиспользуется всеми воркерами/API; в логах явно указан источник значения (`source=chat|global|default`) и `chat_id`.
4. **(C3) Кросс-процессная инвалидация:** `LISTEN chat_params_updated` + `invalidate_chat` (или документированное ограничение TTL 120с как осознанная граница).
5. **(C4) Полная таблица проверена и зафиксирована в docs** (этот документ + ADR-1018-7 §Context); регресс-тест: запись в слой чата → воркер (в тесте) видит значение.
6. **UI-доступность:** тумблер Глубокого сна достижим там, где оператор его ожидает (без роста каталога: см. §4.4).
7. Инварианты: R16 (id), R17 (логи), fail-open, порядок роутеров `bot.py`, `media/`/`.env` не трогать.

## 4. Технический дизайн

### 4.1. Единый accessor (`services/worker_settings.py`, новый; D2 ADR)

```python
from typing import Any

async def resolve_setting(key: str, *, chat_id: int | None = None,
                          default: Any = None) -> Any:
    """chat overrides (каст по каталогу) → hot.get(key) → default.
    chat_id=None → hot.get(key, default). Fail-open (ошибка PG → global)."""

async def resolve_setting_cached(key: str, *, chat_id: int | None = None,
                                 default: Any = None) -> Any:
    """То же, но overrides — из ChatParamsCache (TTL 120с, локальная
    инвалидация); global — из ConfigCache (in-memory, sync-чтение)."""

def setting_source(key: str, *, chat_id: int | None = None) -> str:
    """'chat' | 'global' | 'default' — только факт источника (для логов)."""
```
- Реализация `resolve_setting` повторяет семантику `chat_params._resolve_from_root` (`services/chat_params.py:221-244`), чтобы не было двух разных правил каста/валидации.
- Логирование: `logger.debug("[settings] key=%s | chat=%s | source=%s", key, chat_id, src)` (значения не логируем; для чисел/bool допустим — по явному решению @Builder, R17-safe).

### 4.2. DreamWorker: per-chat резолв (`services/dream_worker.py`)

- Ввести `async def _key_for(self, chat_id: int, name: str, default)` → `resolve_setting_cached(f"memory.dream_{name}", chat_id=chat_id, default=default)`.
- `_process_chat`, `_candidates`, `_distill_cluster`, `_budget_reason_for`/`_daily_limit_for` получают `chat_id` и считают пороги/лимиты **по чату** (sync-варианты `_window_open`/`_daily_limit`/`_budget_reason` удалены — S10.18-16).
- `_maybe_deep_after_sleep(stats, *, manual)` — резолв `flags.deep_sleep_enabled`/`memory.deep_sleep_trigger` **по каждому чату** из `self._last_chat_ids` (или по `only_chat` при manual); если хотя бы один чат ON — прогнать именно его.
- `_deep_tick` (trigger='fixed') — глобальный резолв + per-chat фильтр кандидатов.
- `_run_deep_once(chat_id, …)` — `flags.deep_sleep_enabled` по `chat_id` (при `manual=False`).
- `start()` (`:294-351`) — **всегда** регистрирует джобы (см. 4.3); лог `DreamWorker job registered (enabled resolved per-tick)`.
- Анти-регресс: `_key()` остаётся (глобальный helper) — существующие тесты не ломаются.

### 4.3. Реактивность планировщика (D4 ADR)

- `_tick()` первым делом: `enabled = bool(await resolve_setting("memory.dream_enabled", default=settings.DREAM_ENABLED))`; `if not enabled: return` (счётчик/idle-лог не спамить — `debug`).
- `_deep_tick()` аналогично для `flags.deep_sleep_enabled` + `memory.deep_sleep_trigger == "fixed"`.
- Выключение «на ходу» не прерывает активный `_run` (уважает `_run_lock`); применяется со следующего тика.
- `memory.dream_tick_minutes`: изменение применяется при рестарте (IntervalTrigger создан один раз). Это осознанная граница: зафиксировать в логе `tick_minutes=%s (applies on restart)`. Альтернативный `reconcile_schedule()` — опционально (T-1761), если владелец захочет реактивность и по интервалу.

### 4.4. Статус-API (`web/api/memory_agi.py`)

- `cognition_status`: `enabled = await resolve_setting("memory.dream_enabled", chat_id=chat_id, default=settings.DREAM_ENABLED)`; `deep_enabled` — то же для `flags.deep_sleep_enabled`.
- Аддитивно в ответ: `"source": {"dream": "chat|global|default", "deep_sleep": …}` (R16; контракт не ломается).
- `deep_sleep_status` (`GET /api/memory/deep-sleep`) — принимает `chat_id: Query() = None` (аддитивно) и применяет тот же резолв.
- `active/active_until` — логика F2 §4.5 без изменений.

### 4.5. NOTIFY-подписчик (D6 ADR)

- В runtime (bot.py, рядом с `set_chat_params_cache`, `bot.py:846-847`): async-таска `LISTEN chat_params_updated`, на payload `chat_id` → `chat_params.get_chat_params_cache().invalidate_chat(int(chat_id))`.
- Fail-open: нет пула/ошибка → WARNING `[chat_params] listen unavailable — TTL fallback (120s)`, задача не роняет бот; авто-reconnect с backoff.
- Если кросс-процессный сценарий не подтверждён — задача P2, но TTL фиксируется как граница.

### 4.6. UI-доступ к тумблеру Глубокого сна (D8 ADR, каталог-Δ=0)

- **Не** расширять `TAB_RULES` (инвариант 19 секций / `mapped=88` сохраняется).
- Вариант-минимум (рекомендуется): в окне «Сон» рядом с бейджем Глубокого сна — подпись-хинт «Рубильник: Память → Глубокий сон: мета-синтез» со ссылкой-переходом на `#/ai/memory` (фактический маршрут страницы «Память», `web/app.js:626`; `#/ai/memory_rag` — не маршрут, а id таба — R10.18-11).
- Опция (если @Builder подтвердит наличие generic per-key механизма): вывести **только** `flags.deep_sleep_enabled` в окно Сна без расширения TAB_RULES (не точный TAB_RULES-механизм — требует проверки; иначе остаётся вариант-минимум).
- Каталог-Δ = **0** (ни новых записей, ни новых групп).

## 5. Изменения схемы / каталога / env

- **DDL:** **нет** (SQLite v9 не меняется; PG-схема не меняется).
- **Каталог:** **Δ = 0** (REGISTRY 435, Settings 406, GROUPS 90, mapped 88, TAB_RULES 19 — все без изменений). Всё делается код-константами/резолвом.
- **env:** не трогать; `.env.example` не меняется.
- **Новые модули:** `services/worker_settings.py` (новый файл, не каталог-запись).

## 6. Влияние на тесты

- Новый `tests/test_settings_worker_sync_round1018.py`:
  - `resolve_setting`: per-chat override приоритетнее глобального; глобальный приоритетнее default; fail-open при недоступном кэше; каст/валидация (прецедент `_cast_type_ok`).
  - Регресс-кейс симптома: `overrides["memory.dream_enabled"]=True` + глобальный `False` → `resolve_setting(..., chat_id=…)` → `True`, `source='chat'`.
  - `cognition_status` с `chat_id` → `dream.enabled == True` и `source.dream == 'chat'`.
- `tests/test_dream_worker.py`: per-chat пороги/лимиты; tick при выключенном/включённом флаге после старта (job всегда зарегистрирован); deep-флаг по чату; `manual` без изменений.
- `tests/test_deep_sleep.py`/`test_dream_persona_traits.py`: резолв по чату не ломает существующие ожидания при равных слоях.
- `tests/test_webapp_round1017_sleep.py`: аддитивное поле `source`.
- `tests/test_param_catalog.py` + пин-тесты каталога — **без изменений** (Δ=0).
- `LISTEN`-таска: тест fail-open (нет пула → WARNING, бот жив); при наличии asyncpg-мока — инвалидация по payload.
- JS: `node --check web/app.js`; `JS-UNIT-OK`; `VUE-MOUNT-OK` (UI-хинт — минимальная правка).
- Полный `pytest` 0 failed; `git diff --check`.

## 7. Rollout / feature-flag / откат

- **Без фича-флагов** (владелец: базовая логика). Откат = `git revert`.
- Порядок: T-1759 (accessor) → T-1760 (воркеры) → T-1761 (реактивность) → T-1762 (статус-API) → T-1763 (UI-хинт) → T-1764 (тесты/аудит-таблица/backlog по ностальгии) → T-1765 (@DevOps).
- **Проверка на проде:** включить Сон в scope чата → в течение одного тика (или немедленно при ручном прогоне) `/api/memory/cognition/status` отдаёт `enabled=true`, `source='chat'`; journald содержит `[settings] key=memory.dream_enabled | source=chat`.
- Progressive delivery неприменим (нет флага); страховка — обратимость коммита + fail-open.

## 8. Риски

| # | Риск | Мера |
|---|---|---|
| R1 | Per-chat резолв в горячем цикле → +нагрузка на PG | `resolve_setting_cached` (ChatParamsCache, TTL 120с); резолв раз на чат, не на факт; замер |
| R2 | «Джоб всегда зарегистрирован» → холостые тики | Ранний `debug`-return; цена — 1 no-op на `tick_minutes` |
| R3 | `LISTEN`-таска падает/не поддерживается в окружении | Fail-open + WARNING; TTL 120с как граница; задача P2 при отсутствии кросс-процесса |
| R4 | Двойной резолв (воркер + гейт) даёт расхождение | Один accessor; `gates_enabled` уже per-chat — сохраняем как отдельный слой (master-флаг vs kill-switch), различие задокументировано |
| R5 | Смена поведения при наличии per-chat override у чата | Это и есть цель; логируем `source=chat`; тест-регресс |
| R6 | UI-правка ломает JS-гейты | Минимальная правка (подпись/ссылка); `node --check` + `JS-UNIT-OK` |
| R7 | Аналогичный рассинхрон в Nostalgia/Lore остаётся | T-1764 фиксирует таблицу + backlog-задачу; P0 — только Сон |
| R8 | F2/F4/F5 зависят от F7 | F7 — первая; порядок раунда зафиксирован (§0) |

## 9. Открытые вопросы

Принятые решения (владелец, `current_task.md` UPD п.3-4) **не** переоткрываются: рассинхрон чинить; без флагов для базовой логики; DDL/лимиты/importance — «как есть».

Остаётся уточнить (@Builder при реализации, не блокирует):
1. **`resolve_setting` в новом модуле vs расширение `services/chat_params.py`.** Рекомендация: новый `services/worker_settings.py` (не раздувать дом chat_params), сигнатуры фиксированы в ADR D2.
2. **Логировать ли числовые значения** в `[settings]`-логе (bool/int — безопасно) или только `source`. Рекомендация: только `source` + `chat_id` + `key` (строже R17).
3. **Точный способ UI-хинта** для `flags.deep_sleep_enabled` (подпись+ссылка vs per-key вывод). Рекомендация: подпись+ссылка (Δ=0, гарантированно не ломает TAB_RULES).
4. **`LISTEN`-подписчик** — нужен ли уже сейчас (один процесс) или P2. Рекомендация: реализовать (малый объём, снимает будущий класс багов), но тест — fail-open.

## 10. 10.18, БАТЧ 1 — фиксы по аудиту @Scanner (S10.18-1…-12)

> Раздел добавлен @Builder по итогам `plans/reports/round10.18_scanner_audit.md`. Меняет семантику F7; каталог-Δ=0, DDL нет.

- **S10.18-1 (High) — бюджеты per-chat.** `_budget_reason_for`/near-limit в `_process_chat` теперь сравниваются с per-chat расходом: `db.count_dream_log(..., chat_id=)` и `db.sum_dream_log_tokens(..., chat_id=)`. Схема `memory_dream_log` уже имела `chat_id` (DDL не нужен); `kind='decay_run'` пишется с `chat_id=0` и в бюджет дистилляций не попадает (другой kind). Регресс-тест: чат A с override ON не глушится расходом чата B.
- **S10.18-2 — trigger/hour per-chat в `_deep_tick`.** Тик больше не делает глобальный ранний return: он резолвит `memory.deep_sleep_trigger`/`deep_sleep_hour` по каждому чату-кандидату. Per-chat `fixed` исполним при глобальном `after_sleep` (и наоборот). Кандидаты — общий helper `_deep_candidate_chat_ids`.
- **S10.18-3 — статусы = поведение.** `GET /api/chat/{id}/gates`, `feature_gates.allowed_features`, `oversight` (heavy) и `GET /api/oversight` передают тот же `fallback` (per-chat master `memory.dream_enabled`), что воркер. `cognition_status` добавляет аддитивное `dream.effective` (chat-gate → kill-switch → fallback → global) и считает `active` по нему.
- **S10.18-4 — decay при выключенном Сне.** `_maybe_decay` дополнительно гейтится глобальным master `memory.dream_enabled` (decay — глобальный этап цикла; per-chat резолв неприменим). Возвращает pre-10.18 поведение (при выключенном Сне decay не запускался).
- **S10.18-5 — manual-каскад по цели.** `_maybe_deep_after_sleep(..., only_chat=)` для manual идёт только по целевому чату; без цели — не более `_MANUAL_DEEP_CASCADE_MAX` (=1) чатов вместо `max_chats_per_run` LLM-прогонов.
- **S10.18-6 — BetterStack fail-safe.** Отсутствие `BETTERSTACK_HOST` при наличии токена → **ERROR** «логи НЕ отправляются в панель» (было WARNING). Без токена — WARNING с той же явной формулировкой.
- **S10.18-7/-11 — chat_params_notify lifecycle.** `_on_notify` держит сильные ссылки на invalidate-задачи (`self._pending` + done-callback); `stop()` вызывается из `bot.py::on_shutdown()` (не «мёртвый» код), закрывает соединение и снимает задачи.
- **S10.18-9 — доки F1.** Docstring `mask` уточнён (число `*` = длина секрета); §9 Q4 спеки F1 синхронизирован с T-1706 (logtail-python удалён).
- **S10.18-10 — изоляция теста.** `TestListenerFailOpen` восстанавливает исходный `config.settings.settings` и выгружает `bot` из `sys.modules` в `finally`.

## 11. 10.18, БАТЧ 1 — фиксы итерации 2 (S10.18-15…-17)

> Раздел добавлен @Builder по итогам `plans/reports/round10.18_scanner_audit.md` §7.2. Каталог-Δ=0, DDL нет, R16/R17 соблюдены.

- **S10.18-15 (Medium) — единый env-дефолт master-флага Сна.** `feature_gates._master_fallback_default("dream")` возвращает `settings.DREAM_ENABLED` (не `DEFAULT_BY_FEATURE["dream"]=False`), т.е. ровно дефолт воркера (`_key_for(chat_id, "enabled", settings.DREAM_ENABLED)`). При env `DREAM_ENABLED=true` и несозданном ключе `memory.dream_enabled` в БД `master_fallback`/`cognition.effective` теперь совпадают с фактическим поведением воркера. `DEFAULT_BY_FEATURE` остаётся консервативным дефолтом глобального слоя (`_global_flag_value`/kill-switch-путь). Регресс-тесты: `TestDreamGateFallback::test_master_fallback_default_matches_worker_env_on/_off`.
- **S10.18-16 (Low) — мёртвый код удалён.** Sync-хелперы `_window_open`/`_daily_limit`/`_budget_reason` (0 вызовов в проде и тестах) удалены из `DreamWorker`; hot-path использует `_window_open_for`/`_daily_limit_for`/`_budget_reason_for`. `_key()` сохранён (нужен тик-слою и совместимости).
- **S10.18-17 (Low) — дешёвый предгейт `_deep_tick`.** До SQL-выборки кандидатов `_deep_fixed_possible()` проверяет глобальный `memory.deep_sleep_trigger == "fixed"` ЛИБО наличие per-chat override триггера в in-memory кэше (`ChatParamsCache.has_any_override`, без I/O; прецедент `setting_source`; найденные ключи-стикеры `note_overrides` переживают `invalidate_chat`, включая запись через `set_chat_params` — реактивность). Неизвестный/нестандартный кэш → True (консервативно, реактивность важнее экономии). Тесты: `test_deep_sleep.py::test_deep_tick_skips_candidate_sql_when_disabled` / `test_deep_tick_proceeds_when_per_chat_override` + unit `test_chat_params.py::test_has_any_override_scans_loaded_cache_only` / `test_set_chat_params_notes_override_for_pregate`.
