# CFG-01 — Direct Chat burst/cooldown: effective-лимиты, hot-reload, остаток, анти-обход

Слайс: **CFG-01** (карта `plans/features/cfg/requirements-map.json`, строки `CFG-01.1–01.7`, `CFG-01.AC1–AC4`).
Лейн: CFG-01 (writer). Источник: `source-cfg-addendum.md`, раздел CFG-01 + ADD-1.

## 1. Корневая причина (подтверждена на базовом коде)

`DirectChatService.__init__` создавал троттлер **снимком** настроек:

* `services/direct_chat_service.py` → `DirectChatThrottle(hot.get("limits.chat_burst_limit", …),
  hot.get("limits.chat_cooldown_seconds", …))`;
* прод-путь (`bot.py`) инжектит `PersistentThrottle(hot.get(...), hot.get(...), "direct_chat", db)`.

Дальше `allow()` использовал сохранённые в конструкторе `_limit`/`_cooldown` и **не** перечитывал
настройки, а per-chat override (`chat_params.overrides`) в решении не участвовал вообще. Итог —
наблюдение владельца: правка «Обращений подряд до кулдауна» в MiniApp не меняла частоту ответов
до рестарта процесса.

## 2. Что сделано (минимальная реализация в существующих механизмах)

| Файл | Дельта |
|---|---|
| `services/chat_params.py` | `get_chat_param_sourced(chat_id, key, default)` → `(значение, источник)`: `chat` (override своего скоупа, каст по каталогу + тот же критерий валидности, что у `_resolve_from_root`) → `global` (ConfigCache) → `factory` (settings). Резолв-порядок идентичен существующему `get_chat_param` (spec §4.5) — второй резолвер не создан. |
| `services/persistent_throttling.py` | `normalize_direct_chat_limits()` (единицы/границы §01.4); `resolve_direct_chat_limits(chat_id)` → `(burst, cooldown, source)` через `chat_params` + `hot.get` + settings, fail-open; `throttle_refresh()` (прецедент `cooldown_refresh`); `PersistentThrottle.refresh()`; кламп накопленных зарядов до effective-лимита в **том же атомарном UPSERT** (`MIN(COALESCE(burst_left,0), limit)` в SET и WHERE). |
| `services/direct_chat_service.py` | `_handle_turn`: перед проверкой троттлера — effective-резолв + `throttle_refresh` + `cooldown_refresh(self.silence_streak, cooldown)`; `DirectChatThrottle.refresh()` и кламп `min(state, limit)`; отказ логируется с фактическим остатком, лимитом, паузой и источником; новый R17-safe event `direct_chat_throttle` (`usage_json`: `remaining_seconds/burst_limit/cooldown_seconds/source`, `reason_code=rate_limit`). |

Повторно использованы: `hot_config` (84.4 hot-reload), `chat_params`-кэш (TTL 120 с + NOTIFY-инвалидация),
`throttle_state` (персистентное состояние), `cooldown_refresh` (T-619), `mca_events` (наблюдаемость).

### Семантика (§01.4)

* `limits.chat_burst_limit` — **целое ≥ 1**, «сколько обращений подряд до паузы». `0`/`-1`/мусор
  нормализуются в `1` (вечного лока нет).
* `limits.chat_cooldown_seconds` — **секунды ≥ 0**, пауза после ПОСЛЕДНЕГО допущенного обращения
  (полное восстановление окна). `0` = окно не ограничивает; отрицательные/NaN → `0`.
* Гарантированное время обновления: глобальное значение — **немедленно** (POST /api/config обновляет
  ConfigCache); per-chat override — **немедленно** (NOTIFY `chat_params_updated`), не позднее **TTL 120 с**
  при потере NOTIFY.
* Политика активного кулдауна (§01.2): смена лимита/паузы **не сбрасывает** состояние — `last_ts`
  продолжает течь, остаток пересчитывается по новой паузе; уменьшение лимита обрезает накопленные
  заряды до нового значения (третье обращение после «10 → 2» уже ограничено), увеличение не выдаёт
  заряды до штатного полного восстановления.
* Перезапуск/процессы (§01.5): в прод-режиме (`flags.throttle_persistent_enabled` = true) состояние
  лежит в `throttle_state` и переживает рестарт, а несколько процессов делят один слот (кламп и списание —
  один UPSERT). Аварийный режим `THROTTLE_PERSISTENT_ENABLED=false` — прежний in-memory троттлер,
  состояние локально инстансу и сбрасывается рестартом (задокументировано в модуле).

### Анти-обход (§01.7)

Единственный вход пользовательских обращений — `handlers/direct_chat.py` → `DirectChatService.handle` →
`_handle_turn`; троттлер проверяется **первым барьером**, до CB, per-chat пула, дедупа, LLM и tool-раундов,
поэтому альтернативных Direct/tool/fallback-маршрутов в обход нет; административные действия
(команды `/clear`, `/persona`, `/tone`, `/forget`, `/style`, `edited_message`) троттлером не затрагивались
и не затронуты. Параллельность и два «воркера» на одной БД проверены тестами (см. §4).

## 3. Покрытие строк карты (план статуса; биндинг выполнен по кандидату `0282fe4b`)

| Строка | Статус-план | Доказательство |
|---|---|---|
| CFG-01.1 | `TESTED` | цепочка MiniApp→API→ConfigCache/chat_params→resolver→`allow()`→отказ/ответ: `test_global_hot_reload_without_restart`, `test_per_chat_override_isolated_and_inherit_restored` |
| CFG-01.2 | `TESTED` | hot-reload без рестарта + документированная политика активного кулдауна: `test_active_cooldown_not_reset_by_limit_change`, `test_refresh_new_cooldown_applies_to_active_state`, `test_refresh_hot_reload_clamps_persistent_bucket` |
| CFG-01.3 | `TESTED` | независимость GLOBAL/CHAT, невлияние на другие чаты, reset-to-inherited: `test_per_chat_override_isolated_and_inherit_restored`, `test_resolve_global_then_chat_then_inherit` |
| CFG-01.4 | `TESTED` (UI-текст — см. риск R1) | `test_normalize_bounds`, докстроки `normalize_direct_chat_limits`/`PersistentThrottle` |
| CFG-01.5 | `TESTED` | `chat_id/user_id`-изоляция (существующие + `test_isolation_per_chat_and_user`), параллель и 2 воркера: `test_parallel_burst_same_chat_obeys_limit_in_memory`, `test_parallel_burst_two_workers_shared_persistent_state`; рестарт: `test_persistent_limits_survive_restart_with_new_values`, `test_bucket_survives_restart` |
| CFG-01.6 | `READY_FOR_LIVE` (postdeploy) | локально: `test_refusal_reports_factual_remaining_and_source` (фактический остаток «4 мин 30 сек», `source=chat/global`, событие `direct_chat_throttle`). Живая проверка: см. §5 |
| CFG-01.7 | `TESTED` | троттлер — первый барьер в единственном входе; параллельные/альтернативные попытки не превышают лимит; административные команды и независимые лимиты не изменены (регрессионные наборы §4) |
| CFG-01.D | `TESTED` (дефект) | дефект «правка `limits.chat_burst_limit` в MiniApp не меняет фактическую частоту ответов без рестарта»: RED на базе `43f86ef2` (`-k Cfg01` → 7 failed) → GREEN на кандидате `0282fe4b` (`-k Cfg01` → 7 passed, три файла → 204 passed) — `red-green.txt`; end-to-end: `test_global_hot_reload_without_restart` (10→2: ровно 2 обращения, третье — отказ до LLM; возврат 10 без рестарта меняет поведение); поведенческая инверсия (старый «бонус» +5 → ровно 2) независимо воспроизведена на «модуль базы vs кандидат» — `review-cfg-01.md` §2/§4 |
| ADD-1.T1 | `TESTED` (алиас) | CFG-01 — новая самостоятельная работа, не переигрывание SOUL-1: состав диффа кандидата — ровно 8 файлов (`services/{persistent_throttling,chat_params,direct_chat_service}.py`, `tests/test_direct_chat.py`, `tests/test_direct_chat_concurrency.py`, `tests/test_persistent_throttling.py`, `evidence/cfg-01/{README.md,red-green.txt}`, +1057/−32), второй резолвер/второй троттлер не созданы — `get_chat_param_sourced` переиспользует порядок существующего `get_chat_param` (override → hot → settings); `param_catalog.py`/`web/*` не тронуты — `review-cfg-01.md` §1 |
| CFG-01.AC1 | `READY_FOR_LIVE` (postdeploy) | локально RED→GREEN: `test_global_hot_reload_without_restart` (10→2: ровно 2 обращения, третье ограничено; возврат 10 меняет поведение) |
| CFG-01.AC2 | `READY_FOR_LIVE` (postdeploy) | локально: `test_per_chat_override_isolated_and_inherit_restored` |
| CFG-01.AC3 | `TESTED` | редактирование на активном кулдауне, reset-to-inherited, restart, TTL/NOTIFY, два пользователя в чате, один пользователь в двух чатах, параллель — тесты §4 |
| CFG-01.AC4 | `READY_FOR_LIVE` (postdeploy) | локально: отказ до LLM/tool (`llm.call_count` не растёт), остаток > 0 и ≤ паузы, событие с `remaining_seconds` |

Live-строки (01.6, AC1/2/4) локально закрыты только поведенчески и не блокируют очередь (ADD-0.1; plan
§процесс.4); их подтверждает живой сценарий §5 — статус остаётся `READY_FOR_LIVE` (не `VERIFIED`), закрытие
на postdeploy. После биндинга по кандидату `0282fe4b` строки `CFG-01.1–01.7`, `CFG-01.AC3`, `CFG-01.D`,
`ADD-1.T1` в карте — `VERIFIED`.

## 4. Прогоны (команды и результаты)

```text
# RED (worktree базового коммита 43f86ef2, без правок CFG-01, те же тестовые файлы)
py -3 -m pytest tests/test_direct_chat.py tests/test_direct_chat_concurrency.py -q -k Cfg01
  → 7 failed (все новые CFG-01 тесты), 167 deselected
py -3 -m pytest tests/test_persistent_throttling.py -q -k Cfg01
  → ImportError: cannot import name 'normalize_direct_chat_limits' (новый API отсутствует)

# GREEN (кандидат)
py -3 -m pytest tests/test_direct_chat.py tests/test_direct_chat_concurrency.py tests/test_persistent_throttling.py -q
  → 204 passed
py -3 -m pytest tests/test_direct_chat.py tests/test_direct_chat_concurrency.py -q -k Cfg01
  → 7 passed
py -3 -m pytest <57 файлов: direct_chat*/persistent_throttling/hot_config/soul1-consumers> -q
  → 1693 passed, 2 failed (PRE-EXISTING: tests/test_asap7_direct_settings.py::test_migration_v35_idempotent_twice,
    ::test_backup_guard_fires_before_pending_step — воспроизведены на базовом 43f86ef2 без правок CFG-01)
```

Новые тесты помечены `TEST-LIFECYCLE: REGRESSION owner=CFG-01`.

## 5. Живые проверки (preprod; выполняет DevOps/Orchestrator после деплоя)

1. **MiniApp → глобально (AC1/01.2)**: «Лимиты» → `limits.chat_burst_limit` 10 → 2 (без рестарта) → три
   сообщения подряд в чат: первые два — ответы, третье — фраза R50-7 с фактическим остатком времени.
   Вернуть 10 → после паузы поведение снова по 10.
2. **MiniApp → чат (AC2/01.3)**: выбрать чат, задать другой burst/cooldown → второй чат продолжает
   работать по глобальному значению; «сброс» override возвращает наследование.
3. **Остаток и источник (01.6)**: в отказе — фактический остаток («через 4 мин 30 сек»), без ложного
   «технически не могу»; в MiniApp по ключу виден источник (чат/глобально/заводской), в админском
   просмотрщике логов (`/api/logs?component=direct_chat` / Inspector, доступ глобального админа) —
   событие `direct_chat_throttle` c `remaining_seconds` и `source`.
4. **Отказ до платного вызова (AC4)**: по usage-логам в окне отказа нет LLM/tool-вызовов direct_chat.

## 6. Девиации, риски, побочные находки

* **D1 (обновление существующих тестов).** 8 тестов в `tests/test_direct_chat*.py`, задававших лимит
  параметрами инъектированного троттлера, переведены на конфиг-слой (`chat_limits`-фикстура) — после
  CFG-01 единственный источник лимита в рантайме — конфиг; тесты стали строже (проверяют реальную
  привязку настройки к поведению). Ослабление проверок не выполнялось.
* **R1 (UI-текст/границы, §01.4).** Рантайм нормализует вне-диапазонные значения (≥1 / ≥0), но каталог
  (`services/param_catalog.py`) не задаёт min/max для этих ключей, а UI-тексты («Обращений подряд до
  кулдауна», «Кулдаун direct_chat, сек») описывают семантику верно, но без указания единиц/границ.
  `param_catalog.py`/`web/app.js`-валидация — вне write_scope CFG-01 → передаётся в **CFG-03** (аудит
  всех параметров, UI_missing/валидаторы). Лимит рантайма при этом честный.
* **R2 (факт из §01.6 «время разблокировки в админке»).** Реализовано через существующие поверхности:
  фраза бота (остаток), лог-строка и durable-событие `direct_chat_throttle` в `mca_events`
  (просмотрщик логов/Inspector по `chat_id`/`component`). Отдельной панели «доступность лимита» не
  создавалось (риск дубля UI — territory CFG-03/CFG-04).
* **R3 (кламп при уменьшении лимита).** Уменьшение лимита немедленно обрезает накопленные заряды; это
  документированная политика и условие AC1. Увеличение лимита не выдаёт «бонусные» заряды до конца окна —
  поведение осознанное и покрыто тестами.
* **Побочная находка (исправлена в этом же слайсе).** Исправлено **отсутствие клампа накопленного остатка**
  к effective-лимиту: на базовом коде сценарий «10 доступно, 5 израсходовано, лимит стал 2» допускал ещё 5
  обращений (старый запас работал как бонус) — кандидат допускает ровно 2 (`MIN(COALESCE(burst_left,0), ?)`
  в SET и WHERE **одного** UPSERT; `min(state[0], _limit)` в in-memory). Ветка refill
  (`CASE WHEN last_ts + cooldown <= now THEN ? - 1`, где `?` = `self._limit`) **не менялась**: окно после
  полного восстановления равно `limit` и на базе, и на кандидате — заряд не терялся, формулировка
  «`limit-1` → `limit`» к этому изменению не относится. Кламп закреплён тестом
  `test_refresh_hot_reload_clamps_persistent_bucket` (5 из 10 → `refresh(2)` → ровно 2, третье — отказ);
  инвариант «окно = ровно `limit`» — `test_refresh_limit_increase_no_bonus_in_window`. Поведенческая
  инверсия дополнительно воспроизведена сравнением «модуль базы vs кандидат» на одной БД
  (`review-cfg-01.md` §2/§4).
* **Pre-existing (не относится к CFG-01).** 2 RED в `tests/test_asap7_direct_settings.py` (миграции v35) —
  воспроизведены на базовом коммите без правок CFG-01; см. §4.

## 7. Runtime entrypoints и тесты (для манифеста)

* entrypoints: `services/direct_chat_service.py::DirectChatService._handle_turn`;
  `services/direct_chat_service.py::DirectChatThrottle.{refresh,allow}`;
  `services/persistent_throttling.py::PersistentThrottle.{refresh,allow}`,
  `resolve_direct_chat_limits`, `throttle_refresh`;
  `services/chat_params.py::get_chat_param_sourced` (вызов из `resolve_direct_chat_limits`).
* тесты: `tests/test_direct_chat.py` (`TestCfg01DirectChatLimits`, обновлённые
  `TestDirectChatThrottle*`/`TestHandleFlow`/`TestSilenceAfterCooldowns`/`TestChatLock`/`TestCircuitBreakerIntegration`),
  `tests/test_direct_chat_concurrency.py` (`TestCfg01AntiBypassParallel`),
  `tests/test_persistent_throttling.py` (`TestCfg01EffectiveLimits`).

Прогоны и результаты — `red-green.txt` (в этом каталоге).
