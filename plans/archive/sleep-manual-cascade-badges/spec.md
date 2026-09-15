# Spec F2 — `sleep-manual-cascade-badges` (manual-абсолютный-приоритет, каскад Сон→Глубокий→Личность, реактивные бейджи, аудит цепочки сна)

> **Раунд:** 10.18 (Step 2 @Architect, **итерация 2 после human-gate**, 15.09.2026). **Тип:** backend (`dream_worker.py`, `memory_agi.py`) + frontend (`web/app.js`). **Приоритет:** P0.
> **ADR:** `adr-1018-2-sleep-manual-override.md` (обязателен; SUPERSEDE/AMEND F-10 §5-6 + AMEND ADR-1017-3).
> **Задачи:** T-1712…T-1726 + **T-1767…T-1772** (итерация 2). **Baseline:** HEAD `118a03c`; pytest 6007 passed; каталог 435/406/411/90/88/19; SQLite v9.
> **Источник:** `plans/current_task.md` §2.1–§2.4 (строки 27–54) + UPD п.2, п.3, п.5 (строки 116–117, 119–121, 126).
> **Связано (обязательно):** **ADR-1018-7 / F7 `settings-worker-sync`** — без исправления чтения настроек manual-каскад проверять не на чем (см. §4.7).
> **R17:** без секретов; логи — класс/причина/числа.

## 0. Что изменилось после human-gate (итерация 2)

| Пункт ТЗ | Прежнее решение (итерация 1) | Решение владельца (UPD) | Следствие в спеке |
|---|---|---|---|
| UPD п.2 (строки 116-117) | manual-обход за фича-флагом `flags.sleep_manual_priority_enabled` (OFF) | **«ДА (БЕЗ ФЛАГОВ)»** — новый стандарт базовой логики | §4.2/§4.3 переписаны **без флагов**; §5 каталог-Δ → **0** по флагам F2; §7 без staged-флагов |
| UPD п.3 (строки 119-121) | «`DREAM_ENABLED=True` после смоука» | «включайте, **но** сначала починить рассинхрон UI→воркеры» | Новый §4.7 + вынос в **F7** (`plans/features/settings-worker-sync/`, ADR-1018-7) |
| UPD п.5 (строка 126) | пороги как гипотеза | «полноценный аудит всей цепочки Сон→Глубокий→Личность» | Новый **§2.5 + §4.1-таблица** с текущими/предлагаемыми порогами + §4.8 (игнор экономии токенов) |
| UPD п.4 (строка 124) | — | «остальные решения — ДА» | ADR-1018-1/-3/-5 зафиксированы «как есть»; эта спека на них ссылается |

**Снятые открытые вопросы (приняты владельцем):** границы manual-обхода, включение `DREAM_ENABLED`/`DEEP_SLEEP_ENABLED`, числовые дефолты порогов, таймаут прогона. Открытые вопросы — только новые (см. §9).

## 1. Контекст и цель

С 12.09 Сон не дистиллирует, Глубокий сон пуст, черты Личности = 0. Ручной запуск Сна из админки падает на гейтах, бейджи не меняются. Целевое: (а) ослабить пороги/пре-гейты до рабочего баланса; (б) ручной запуск = **абсолютный приоритет** и полный каскад Сон→Глубокий→Личность; (в) бейджи в реальном времени (без WebSocket); (г) **настройки из UI реально доходят до воркеров** (F7); (д) полный аудит цепочки сна с таблицей порогов.

## 2. Текущее поведение (сверено с кодом)

### 2.1. Гейты/пороги Сна
- Пороги: `repeat_threshold=3`, `importance_sum_threshold=12`, `min_new_facts_per_chat=5`, `max_clusters_per_run=5`, `distillations_per_day=30`, `tokens_per_day=60000`, `quiet_check_minutes=30`, `initial_window_hours=168`, `cluster_overlap_tokens=2` (`config/settings.py:1090-1107`; чтение `dream_worker._key` → `memory.dream_*`, `:252-253`).
- Кластеры: `qualified = len(cl) >= repeat_min AND Σimportance >= sum_min` (`dream_worker.py:522-534`).
- Fallback 2/8 уже есть при «0 убеждений за 3 дня» (`:257-272,140-142,527-529`).
- Пре-гейт-логи `[Sleep] Chunks… Skipped/Passed` (`:545-563`).
- Near-limit: `_DREAM_NEAR_LIMIT_DIST=5`, `_DREAM_NEAR_LIMIT_TOKENS=5000` (`:115-116`).

### 2.2. Manual и гейты
- `window_skip` для manual **уже** обходится: `if not manual and not self._window_open(now)` (`dream_worker.py:588`).
- Kill-switch: `gates_enabled(chat_id,"dream")` применяется **и к manual** (`:569-577`, фикс R5 F-10 §6). При глобальном `DREAM_ENABLED=False` (default) `gates_enabled` возвращает **False** → блокирует даже manual.
- Бюджеты/near-limit: `_budget_reason` + near-limit early-stop применяются и к manual (`:600-620`); `_dream_budget_ok` в дистилляции.
- `run_once(manual=True)` **не** проверяет `memory.dream_enabled` (рубильник обходится и так — API `memory_agi.py:249-263`).

### 2.3. Каскад
- `run_once(manual=True)` → `_run(manual=True)` → (после) `_maybe_deep_after_sleep(stats)` (`dream_worker.py:382-416`).
- `_maybe_deep_after_sleep` **ранний return**, если `flags.deep_sleep_enabled` false ИЛИ `trigger != "after_sleep"` ИЛИ нет distilled/chats (`:1099-1119`). `DEEP_SLEEP_ENABLED=False` по умолчанию (`settings.py:1133`) → каскад **не стартует**.
- `_run_deep_once(manual=True)` обходит `deep_sleep_enabled`/cooldown/daily-limit (`:1186-1211`), но сам вызывается только из `_maybe_deep_after_sleep`/`_deep_tick`/`run_once(deep=True)`.
- Traits: вызываются **только из** `_run_deep_once` при `flags.persona_enabled` (per-chat, `:1315-1331`). Требуют `bot_self_reply`-фактов; иначе `status='empty'` (`:1476-1493`). Промпт-парсер `parse_persona_traits` (`dream_prompts.py:328-348`).
- `DREAM_ENABLED=False`/`DEEP_SLEEP_ENABLED=False` по умолчанию (`settings.py:1090,1133`).

### 2.4. Бейджи (фронт/бэкенд)
- Бэкенд `cognition/status` (`memory_agi.py:466-502`): `dream_active_until = _next_hour_epoch(end_h) if dream_in else None`; при `running` вне окна `dream_in=False` → **`active_until=null`** (и то же у `deep`). `dream_running`/`deep_running` берутся из воркера (`:440-441`).
- `enabled` статуса считается **только по глобальному слою** (`:442-444`) — часть рассинхрона F7.
- Фронт `dreamPhaseBadge` (`web/app.js:1216-1233`): при `active && !active_until` → «🌙 Сон идёт» (без «до»). `deepPhaseBadge` — аналогично (`:1234-1248`).
- `runDreamNow` (`web/app.js:4974-4999`): POST → toast + `loadDreamBeliefs/loadDreamLog` через 3с; **`cognition` не перезагружается** → до 15с стейл.
- Polling 15с с паузой при `document.hidden` (`:5385-5408`). S10.17-2: при `cognition==null` бейдж показывает «Сон через —».
- WebSocket в проекте **отсутствует** (только polling). ADR-1017-3 §2.6: без живого tick-таймера.

### 2.5. Аудит цепочки сна (UPD п.5) — где именно «падает активность»

| # | Звено | Что установлено (код) | Почему активность падает |
|---|---|---|---|
| A | Кандидаты чата | `get_dream_candidate_chats` требует `new_count >= min_new_facts_per_chat=5` И тишину `quiet_after_ts=now-30мин` (`:437-451`) | Чаты с 1–4 новыми фактами **не попадают** в тик; «тишина 30 мин» отсекает активные чаты |
| B | Появление джоба | `start()` регистрирует `dream_tick` только при `memory.dream_enabled` (`:294-309`); при OFF джоба нет | Включение в UI без рестарта не создаёт джоб (**F7 T-1761**) |
| C | Окно дистилляции | `_window_open` ∈ `[4,6)` local; при `manual=False` вне окна — `window_skip` (`:588-599`) | Реальный расход возможен только 2 часа в сутки |
| D | Пороги кластера | `repeat>=3` И `Σimp>=12` (`:522-534`) | При ослабленном потоке фактов кластеры не набирают Σ=12 → `[Sleep] … Skipped` |
| E | Kill-switch | `gates_enabled(chat_id,"dream")` (`:569-577`); при глобальном флаге OFF → False | Блокирует и плановый, и ручной прогон |
| F | Бюджеты | `_budget_reason`/near-limit (`:600-620`); near-limit срабатывает при остатке <5 дистилляций / <5000 токенов | Ранний стоп тика; при `distillations_per_day=30` это 5 «резервных» прогонов, которые не используются |
| G | Каскад | `_maybe_deep_after_sleep` требует `flags.deep_sleep_enabled=true` (`:1103-1109`) | При OFF глубокий сон не стартует вообще |
| H | Личность | traits требуют `bot_self_reply`-фактов + `flags.persona_enabled` (`:1315-1331,1476-1493`) | Нет self-фактов → 0 черт; причина сейчас логируется слабо |
| I | Экономия токенов | `tokens_per_day=60000` + `_dream_budget_ok` (`worker_budget.consume`) | Осознанная экономия ограничивает глубину процесса (UPD п.5: «игнорировать экономию») |

**Вывод аудита:** причина 0-результата — **не** `window_skip` для manual (он уже обходится), а комбинация: (A) жёсткий порог кандидатов, (B) нереактивный джоб, (C) узкое окно, (D) пороги кластера, (E) kill-switch при выключенном глобальном флаге, (G) глухой каскад, (H) слабая диагностика Личности. Все шесть лечатся в §4.

## 3. Требуемое поведение

1. **Manual-абсолютный-приоритет (без флагов):** ручной запуск из UI выполняется **безусловно** — игнорируя тайминги, расписания, окна, kill-switch, near-limit и суточные бюджеты. Это **базовое** поведение (не за флагом).
2. **Неприкосновенные guard-ы (пересмотрены после UPD):** локи (`already_running`, 409), `protected_facts`, анти-галлюцинация (≥2 real `source_ids`), R17/fail-safe, дедуп/кап `PERSONA_TRAITS_MAX`. `flags.persona_enabled` — **не** обходится (см. §4.2a), но его OFF не «глушит» каскад молча: фиксируется причина.
3. **Пороги ослаблены и предсказуемы:** факты доходят до дистилляции; анти-мусор сохранён.
4. **Каскад:** manual-Сон **гарантированно** запускает Глубокий сон (игнор `deep_sleep_enabled`/`trigger`/таймингов), а тот — Личность (при self-фактах; `persona_enabled` уважается).
5. **Бейджи без WebSocket:** немедленный `loadCognition()` после POST + оптимистичная установка `active`; `active_until` при `running` вне окна; ускоренный polling во время прогона; закрытие S10.17-2.
6. **Диагностика цепочки:** WARNING/ERROR на каждый исход (кандидаты/пороги/гейт/бюджет/каскад/Личность), R17-safe.
7. **Настройки UI реально влияют** (через F7): manual-прогон читает РЕАЛЬНЫЙ конфиг чата, не глобальный дефолт.

## 4. Технический дизайн

### 4.1. Аудит и пересмотр порогов (`config/settings.py` + идемпотентная DML-миграция)

**Текущие vs предлагаемые значения (полная таблица, UPD п.5):**

| Ключ | Текущий code-default | Прежний дефолт для DML-миграции | **Предлагаемое** | Обоснование (аудит §2.5) |
|---|---|---|---|---|
| `DREAM_REPEAT_THRESHOLD` | 3 | 3 | **2** | звено D: δ-кластеры из 2 фактов доходят до дистилляции |
| `DREAM_IMPORTANCE_SUM_THRESHOLD` | 12 | 12 | **8** | звено D: Σ=8 реалистична для разговорной памяти |
| `DREAM_MIN_NEW_FACTS_PER_CHAT` | 5 | 5 | **2** | звено A: чаты с 2–4 новыми фактами больше не выпадают |
| `DREAM_MAX_CLUSTERS_PER_RUN` | 5 | 5 | **10** | пропускная способность на ослабленных порогах |
| `DREAM_DISTILLATIONS_PER_DAY` | 30 | 30 | **60** | звено F/I: убрать «экономный» потолок |
| `DREAM_TOKENS_PER_DAY` | 60000 | 60000 | **300000** | UPD п.5 «игнорировать экономию токенов» |
| `DREAM_QUIET_CHECK_MINUTES` | 30 | 30 | **10** | звено A: активные чаты чаще попадают в тик |
| `DREAM_CLUSTER_OVERLAP_TOKENS` | 2 | 2 | 2 (без изменений) | анти-мусор |
| `DREAM_INITIAL_WINDOW_HOURS` | 168 | 168 | 168 (без изменений) | первый прогон — неделя истории |
| `DREAM_TICK_MINUTES` | 60 | 60 | 60 (без изменений) | реактивность даёт F7, не интервал |
| `DREAM_WINDOW_START_HOUR` / `_END_HOUR` | 4 / 6 | 4 / 6 | **без изменений** (обход — через manual §4.2) | ручной запуск игнорирует окно |
| `_DREAM_NEAR_LIMIT_DIST` / `_TOKENS` (код-константы) | 5 / 5000 | — | **без изменений** (manual обходит §4.2) | near-limit не режет плановый тик при новых лимитах |
| `DEEP_SLEEP_ENABLED` | False | — | **True** (владелец, UPD п.3) | звено G |
| `DREAM_ENABLED` | False | — | **True** (владелец, UPD п.3) | звено B; включать **после** F7 |
| `_DEEP_SLEEP_MIN_INTERVAL_HOURS` | 20 | — | **без изменений** (manual обходит) | cooldown не мешает manual |
| `_DEEP_SLEEP_LOOKBACK_HOURS` | 12 | — | без изменений | «свежая активность» |
| `_DEEP_SLEEP_MIN_HISTORICAL` | 2 | — | без изменений | анти-галлюцинация каскада |

**Механизм DML-миграции (идемпотентный):** в `services/prompt_migrations.py` (или новый `services/config_migrations.py`) — `migrate_dream_thresholds(cache)` заменяет значение **только если оно равно прежнему дефолту** (3/12/5/5/30/60000/30); кастом владельца не трогается (WARNING); PG down → skip. Прецеденты: `migrate_prompt_canons`, `migrate_direct_reply_ttl_default`. Вызов — в `bot.py` рядом с ними (`bot.py:862-868`).

**Fallback-пороги F3 (S10.18-24):** после подъёма дефолтов к 2/8 fallback
«0 убеждений за 3 дня» ослабляет **только Σ-важность**: code-константа
`_FALLBACK_MIN_IMPORTANCE_SUM` опущена 8→**6** (ниже дефолтных 8), размер
кластера остаётся **2** (= дефолт; ниже нельзя — одиночный факт это мусор,
`test_single_fact_rejected_even_in_fallback`). Без этого fallback был бы
no-op при дефолтных порогах (актуален лишь при явно поднятых). Тесты,
пиновавшие базу 3/12, продолжают проверять отличие базы от fallback.

### 4.2. Manual-абсолютный-приоритет (`services/dream_worker.py`) — БЕЗ флагов

Единая точка: **`manual=True` → безусловный обход** (новый стандарт базовой логики):

- `_process_chat`: **пропустить** kill-switch-ветку (`:569-577`) — лог WARNING `[dream] manual override: gate dream | chat_id=%s` + аудит `log_dream_event(kind="skipped", status="gate_override")`.
- `_process_chat`: **пропустить** near-limit early-stop (`:609-620`) и жёсткий `_budget_reason`-break (`:601-608`) — аудит `status="budget_override"`.
- `_distill_cluster` → `_dream_budget_ok`: при `manual=True` не отказывает, но **consume расхода всё равно пишется** (fail-open учёт; Worker Budget сохраняется).
- `window_skip` (`:588`) — как было: обходится (это и есть manual).
- **Аудит без нового каталог-ключа:** используем существующую `memory_dream_log` с новыми строковыми `status` (`gate_override`, `budget_override`) — строки не каталог, Δ=0. R17-safe (только статус/chat_id/числа).

**4.2a. Guard-ы и их совместимость с «абсолютным приоритетом» (перепроверено):**

| Guard | Обходит ли manual | Обоснование |
|---|---|---|
| `_run_lock`/`_deep_lock` (`already_running`, 409) | **НЕТ** | анти-рейс; обход = двойной прогон/порча watermark. «Безусловно» = старт не отклоняется гейтами, а не «параллельно» |
| `protected_facts`-гейт | **НЕТ** | явный пользовательский запрет на факты; обход = нарушение приватности. Manual выбирает *что* дистиллировать из разрешённого |
| ≥2 real `source_ids` для belief | **НЕТ** | анти-галлюцинация; иначе manual создаёт мусор |
| R17/fail-safe | **НЕТ** | инвариант проекта |
| `PERSONA_TRAITS_MAX` / дедуп | **НЕТ** | целостность данных персоны |
| `flags.persona_enabled` | **НЕТ** (но и **не глушит молча**) | **конфликт разрешён так:** запрет на запись traits уважается (это контентный гейт владельца), но manual-каскад **доходит** до шага Личности и логирует `reason=persona_disabled` (сейчас — тишина). Явно задокументировать в ADR-1018-2 §D3 |
| `gates_enabled(chat_id,"dream")` (kill-switch) | **ДА** | это и есть цель §2.2 ТЗ |
| Бюджеты/near-limit | **ДА** (решение о запуске), учёт — **НЕТ** | «игнорировать экономию» (UPD п.5), расход пишем |

### 4.3. Каскад (`services/dream_worker.py`)

- `_maybe_deep_after_sleep(stats, *, manual: bool = False)`:
  - при `manual=True` — **без** ранних return по `deep_sleep_enabled`/`trigger` (безусловно);
  - критерий «есть что каскадировать» для manual — `stats["chats"] > 0`;
  - чаты — `self._last_chat_ids` или `only_chat`.
- `run_once` (обе ветки) передаёт `manual=True` в `_maybe_deep_after_sleep`.
- `_run_deep_all(chat_ids, manual=True)` — без `break` после первого успеха (`:1180-1181`): прогнать все выбранные чаты.
- `_run_deep_once` уже вызывает traits (`:1315-1331`) — при manual каскад доходит до Личности.
- `run_once` возвращает аддитивный `stats["cascade"] = {"deep": {...}, "traits": {...}}` (контракт 202 не ломается).
- **F7-зависимость:** значения `deep_sleep_trigger`/`deep_sleep_enabled` для **не-manual** пути резолвятся per-chat (F7 T-1760); для manual они игнорируются вовсе.
- **S10.18-21 (исправление регресса R10.18-17):** дешёвый предгейт
  `_deep_tick` (`_deep_fixed_possible`) **удалён**. Он опирался на прогретость
  in-memory `ChatParamsCache` (`has_any_override`) и при глобальном
  `after_sleep` + незагруженном чате с per-chat `trigger='fixed'` молча
  хоронил фиксированный прогон. `_deep_tick` снова безусловно выбирает
  кандидатов (1 дешёвый SQL/час) — цена предгейта ниже риска потерять прогон.

### 4.4. Диагностика Личности (`dream_worker._run_persona_traits_once`)

R17-safe WARNING/ERROR на каждый исход:
- `self_facts == 0` → `logger.warning("[persona_traits] skip | reason=no_self_facts | chat_id=%s")`.
- `persona_enabled == False` → `logger.warning("[persona_traits] skip | reason=persona_disabled | chat_id=%s")` (**новое**, закрывает «молчаливую» ветку).
- `parse_persona_traits` ValueError → WARNING `reason=json_error | raw_len=%d` (без текста ответа).
- пусто после дедупа → INFO `reason=all_duplicates`; budget/LLM/write → WARNING с `reason=`.
- плюс `kind=deep_traits` в worker_budget-логе (уже есть).
Никаких текстов фактов/промптов в логах.

### 4.5. Backend `active_until` при running (`web/api/memory_agi.py`)

В `cognition_status` (`:466-502`):
```python
run_timeout = _DREAM_RUN_TIMEOUT_SECONDS   # код-константа 900 (Δ=0)
# S10.18-23: manual — НАСТОЯЩИЙ маркер воркера (выставляет run_once),
# а не «running вне окна» (авто-тик идёт вне окна 22 ч/сутки).
dream_manual = dream_running and worker.manual_run_active
if dream_running:
    dream_active_until = (min(_next_hour_epoch(end_h, tz_name, now),
                              int(now) + run_timeout) if dream_in
                          else (int(now) + run_timeout if dream_manual
                                else None))
elif dream_in:
    dream_active_until = _next_hour_epoch(end_h, tz_name, now)
else:
    dream_active_until = None
# аналогично deep_running/deep_in/deep_manual
```
Аддитивно: `dream.manual = dream_manual`, `deep_sleep.manual = deep_manual`. Контракт (`running/enabled/active/active_until/next_*`) не ломается (R16). **`enabled` дополнительно резолвится по `chat_id` и отдаётся `source` — это F7 T-1762.** Воркер-маркеры: `DreamWorker._manual_run_until`/`_manual_deep_until` (`_MANUAL_RUN_MARKER_SECONDS=900`, Δ=0). **S10.18-29:** `_manual_deep_until` выставляется и при manual-каскаде `run_once(deep=False)` (в `_run_deep_all(manual=True)`); флаг `_manual_deep_run` держит `manual=True` весь прогон (в т.ч. >900с) — бейдж deep не «теряет» фазу.

### 4.6. Frontend (`web/app.js`)

- `runDreamNow` (`:4974-4999`): после 202 — оптимистично `this.cognition.dream.active = true` (если `cognition` есть) + `this.loadCognition()` немедленно; ретраи `loadCognition` на 1с/3с/8с; `loadDreamBeliefs/loadDreamLog` — как сейчас.
- `runDeepNow` (если кнопка есть) — аналогично, `deep_sleep.active=true`.
- Бейджи `dreamPhaseBadge`/`deepPhaseBadge` (`:1216-1248`): «🌙 Сон идёт»/«🌌 Глубокий сон идёт» + «до HH:MM» при `active_until`; при `cognition == null` → `{ text: '—', cls: 'badge-muted' }` (закрытие S10.17-2), **без** «через —».
- `restartCognitionPolling`/`_startCognitionTimer`: временное ускорение до 5с на время прогона, затем восстановление **базовых 15с**. D2: общий helper `_startCognitionTimer(ms)` без раннего return по `cognitionTimer` (прямой `startCognitionPolling()` в restore раннеретурнил и оставлял 5с навсегда). **D6/R2-1 (итерация 2, вариант b):** гейт `activeTab === 'status'` при СТАРТЕ ускорения **снят** — кнопка «Запустить синтез сейчас» живёт на вкладке `modules`, поэтому ускорение стартует сразу после POST независимо от вкладки; «вечного 5с вне вкладки» нет, т.к. `setTab` при любом уходе вызывает `stopCognitionPolling` (снимает и interval, и restore-таймер). Без WebSocket.
- **S10.18-22 / S10.18-26 (фикс инварианта F5/R10.11-5):** восстановление
  базовых 15с (`_restoreCognitionPolling`) стартует **только** при
  `activeTab === 'status'` (вне Статуса — лишь `stopCognitionPolling`).
  `closeModule` вне Статуса останавливает polling (модалка «Сон» живёт на
  `modules`). Ретраи `_retryCognition` сохраняют хэндлы в
  `_cognitionRetryTimers` и снимаются в `stopCognitionPolling`. Порядок в
  `runDreamNow`: сначала `restartCognitionPolling` (чистит старые ретраи), затем
  новые ретраи.

### 4.7. Жёсткая зависимость от F7 (`settings-worker-sync`, ADR-1018-7)

**Блокирующее требование:** пока воркер читает только глобальный слой (`dream_worker._key`, `:252-253`), включение тумблера в scope чата и/или отсутствие рестарта делают любой «ослабленный порог» и любой «каскад» недействительными. Поэтому:
- F2 **не может** быть проверена end-to-end до выполнения F7 T-1759…T-1762;
- порядок раунда: **F7 → F2 → F4/F5**;
- `enabled`/пороги/флаги в `dream_worker` обязаны читаться через `resolve_setting*` из F7 (единый accessor), а не через локальный `hot.get`.

### 4.8. Игнорирование экономии токенов (UPD п.5)

- Числовые лимиты подняты (§4.1): `tokens_per_day 60000 → 300000`, `distillations_per_day 30 → 60`.
- Manual: бюджеты не блокируют запуск (§4.2), но расход учитывается (видимость стоимости).
- `worker_budget` как учёт **сохраняется** (не удаляем); меняется только политика «не отказывать manual».
- В отчёт — фактические токены ручного прогона (для владельца), без «экономного» раннего стопа при manual.

## 5. Изменения схемы / каталога / env

- **DDL:** не требуется (SQLite v9; трейт-статусы/логи существуют). *(DDL v10 — только F3.)*
- **Каталог:** **Δ = 0.** Флаги F2 **не вводятся** (UPD п.2: без флагов). `flags.sleep_manual_priority_enabled` / `flags.sleep_relaxed_thresholds_enabled` — **исключены** из спеки. `source`-поле статус-API и `status`-строки аудита — не каталог-записи.
- **`.env`:** не трогать; `.env.example` — без изменений.
- Промпт Личности: без правки (причина 0 черт — флаги/пороги/read-path, не промпт). Если правка понадобится — канон-миграция ADR-1013-3 (PREV+байты).

## 6. Влияние на тесты

- `tests/test_dream_worker.py`: пороги/fallback/каскад; новые кейсы — `manual=True` обходит gate/budget/окно **безусловно** (без флага); `_maybe_deep_after_sleep(manual=True)` стартует deep независимо от `deep_sleep_enabled`; traits вызываются; `reason=persona_disabled` логируется.
- `tests/test_sleep_fallback_round1015.py` — пороги (ожидания 2/8 vs новые базовые 2/8 — синонимичны, проверить).
- `tests/test_persona_traits*.py` / `test_dream_persona_traits.py` — WARNING-причины (в т.ч. новая `persona_disabled`).
- `tests/test_webapp_round1017_sleep.py` + `tests/js/routing_test.js` — `active_until` при running, `manual`-флаг, `—` при null.
- Тест миграции порогов (новый) — идемпотентность/кастом/OLD-default.
- `tests/test_param_catalog.py` + пин-тесты каталога — **без изменений** (Δ=0).
- Полный `pytest` 0 failed; `node --check web/app.js`; `JS-UNIT-OK`; `VUE-MOUNT-OK`; `git diff --check`.

## 7. Rollout / feature-flag / откат

- **Флаги: нет** (UPD п.2). Базовое поведение; откат = `git revert` (в т.ч. обратная DML порогов по прецеденту).
- **Стадии (без флагов):** (1) F7 → (2) DML-миграция порогов → (3) `DREAM_ENABLED=True` + `DEEP_SLEEP_ENABLED=True` **для целевого чата** (через UI/scope чата, после F7) → (4) manual-прогон end-to-end → (5) наблюдение 24ч по логам (`[settings] source=`, `[Sleep] Chunks…`, `[persona_traits] reason=`).
- `DREAM_ENABLED`/`DEEP_SLEEP_ENABLED` включаются **после** F7 и **не** «вслепую»: обоснование в отчёте T-1713.
- Rollback: `git revert` кода + обратная DML (вернуть прежние значения порогов) — прецедент миграций.

## 8. Риски

| # | Риск | Мера |
|---|---|---|
| R1 | §2.2 vs F-10 §5-6 («manual не минует gate/budget») | ADR-1018-2 SUPERSEDE/AMEND: перечислить обходимое/неприкосновенное (таблица §4.2a) |
| R2 | §2.3 vs ADR-1017-3 + нет WebSocket | AMEND ADR-1017-3: оптимистика + целевой reload + polling; WebSocket не вводить |
| R3 | `active_until=null` при manual вне окна | §4.5 (бэкенд) + §4.6 (фронт) |
| R4 | Реальные причины обрыва — gates/budget/кандидаты/пороги/флаги, а не `window_skip` | §2.5-аудит + §4.1-таблица; T-1713/T-1715 проверяют все звенья |
| R5 | Ослабление порогов → мусорные убеждения | Анти-мусор сохранён (len≥5 токены, overlap≥2, ≥2 источника, `protected_facts`, F5-пенализация метафактов); пороговые тесты |
| R6 | 0 черт — флаги/пороги/read-path, не промпт | §4.4 диагностика; правка промпта — только через ADR-1013-3 |
| R7 | Потеря safety при безусловном manual-обходе (теперь без флага!) | Таблица §4.2a (что не обходится) + аудит `gate_override`/`budget_override` + ревью T-1726 |
| R8 | F2 не проверяема без F7 | Жёсткая зависимость §4.7; порядок раунда F7 → F2 |
| R9 | Безусловный обход manual может «прожечь» бюджет | Осознанно (UPD п.5 «игнорировать экономию»); расход логируется; лимиты подняты |

## 9. Открытые вопросы

**Принято владельцем (не переоткрывается):** manual обходит гейты безусловно и без флагов (UPD п.2); `DREAM_ENABLED`/`DEEP_SLEEP_ENABLED` включать при условии фикса рассинхрона (UPD п.3); числовые дефолты порогов — таблица §4.1 (UPD п.5/п.4); таймаут прогона — код-константа 900с (Δ=0).

Осталось уточнить (@Builder при реализации, не блокирует):
1. **Точные значения поднятых лимитов:** `tokens_per_day=300000` / `distillations_per_day=60` — рекомендация из аудита; если владелец хочет «без лимита вовсе» — вынести в отдельную правку (лимит-0 как «без ограничения» требует явной семантики в `_budget_reason`).
2. **Нужен ли `reconcile_schedule()`** (реактивность и по `dream_tick_minutes`), или достаточно «джоб всегда + ранний return» (F7 T-1761). Рекомендация: второго достаточно, интервал — на рестарте (подписано в логе).
3. **UI-доступ к `flags.deep_sleep_enabled`:** подпись+ссылка (рекомендация) vs per-key вывод в окне Сна (F7 T-1763).
4. **`status='gate_override'/'budget_override'` в `memory_dream_log`:** подтвердить, что UI-лента логов Сна корректно отображает новые строковые статусы (без правки схемы). Рекомендация: да, статусы — свободные строки.
