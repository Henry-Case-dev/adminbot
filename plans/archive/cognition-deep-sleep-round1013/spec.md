# Spec F3 — `cognition-deep-sleep-round1013` («Глубокий сон» + роутер LLM воркеров)

> Статус: **✅ COMPLETED** (Step 8 @PM Archive, 13.09.2026; спека Step 2 @Architect, 13.09.2026). База: HEAD `ce25dc7`.
> ТЗ: `plans/current_task.md` §6 + backend §3. Tasks: T-1434…T-1442. P1.
> Зависимости: F1, F2. Обслуживает F4 (единые PG-ключи). ADR: `../cognition-llm-providers-round1013/adr-1013-1-provider-keys.md`.

## 0. Цель

Ежедневный «Глубокий сон» после обычного сна идёт по всей старой базе, находит
якоря, синтезирует «парадигмы» (мета-факты) и подаёт их как фоновый исторический
слой; бэкенд-роутер моделей воркеров читает выделенные LLM с фоллбэком на основную.

## 1. Объём

### In scope
- Фаза/воркер «глубокий сон» строго после завершения обычного сна (+ свой диапазон).
- «Поиск по якорям»: свежие beliefs + 12ч-выжимка → векторный RAG по всей базе.
- Синтез «Мост времени» → парадигмы (без DDL) + подача с весом 0.5–0.6.
- Роутер моделей воркеров (history/background) с фоллбэком.
- Настройки расписания/весов/лимитов; телеметрия/API; feature flag.

### Out of scope
- UI-настройки «Сон» (поля — F5/админка; здесь — каталог-ключи).
- Новые таблицы/DDL.

## 2. Схема данных (без DDL)

Парадигмы = строки `graph_facts`:
- `origin='derived_belief'` (единственный доступный для синтеза; CHECK origin
  новых значений не допускает),
- `kind='belief'` (CHECK допускает только fact/belief),
- `status='confirmed'`, `weight=0.55` (в диапазоне 0.5–0.6),
- `belief_meta` (JSON): `{"type":"paradigm","anchors":[...],"lookback_hours":12,
  "bridge":true,"created_at":...,"sources_count":N,"dedup_key":"<hash>"}`,
- `source_ids` — JSON id фактов/убеждений-опор, `target_user` — ключевая персона (если есть).
- `importance` — явно по числу опор (как у beliefs).

**Различение beliefs/paradigms:** `kind='belief'` у обоих; фильтр — по
`belief_meta` (`json_extract(belief_meta,'$.type')='paradigm'` или
`belief_meta LIKE '%"type":"paradigm"%'`). В `list_recent_beliefs` добавить
опц. параметр `belief_type`.

**Источник 12ч-выжимки (F3-Q2 — РЕШЕНО):** свежие `graph_facts` (`kind='fact'`,
`status='confirmed'`, `created_at >= now-12h`, `origin IN _DREAM_SOURCE_ORIGINS`)
+ свежие beliefs (`kind='belief'`, `status='confirmed'`, созданные обычным сном
в текущем прогоне). НЕ `smart_messages` (дорого/шумно). Выжимка = тексты фактов,
склеенные до `_DEEP_SLEEP_SUMMARY_MAX_CHARS = 6000`, топ по importance.

## 3. Расписание (F3-Q4 — РЕШЕНО)

- Триггер по умолчанию: `memory.deep_sleep_trigger = 'after_sleep'` — запуск
  сразу после успешного завершения обычного сна (`DreamWorker._run` вернул
  `distilled > 0` ИЛИ обычный сон завершил батч-проход). Иначе —
  `memory.deep_sleep_trigger='fixed'` + `memory.deep_sleep_hour` (local TZ
  `WORKER_BUDGET_TZ`).
- Cooldown: не чаще `memory.deep_sleep_min_interval_hours = 20` (защита от
  наложений/циклов). Идемпотентность: маркер `memory_dream_log(kind='deep_run')`.
- Защита от наложения: `asyncio.Lock`/`max_instances=1` (как у других воркеров).
- TZ — `settings.WORKER_BUDGET_TZ` (Asia/Yekaterinburg).

## 4. Алгоритм «Поиск по якорям» + «Мост времени»

```
async def _run_deep_once(chat_id):
    if not flag("flags.deep_sleep_enabled"): return
    if cooldown_active(chat_id): return
    packet = {
      "beliefs": свежие beliefs обычного сна (kind='belief' AND belief_meta.type!='paradigm'),
      "recent":  выжимка 12ч (см. §2),
    }
    query = join(packet.beliefs.texts[:20] + packet.recent.texts)
    anchors = await memory.get_rag_facts(chat_id, query)      # векторный RAG
    # F3-Q3: ограничение стоимости
    anchors = anchors[: limits.deep_sleep_top_k]              # default 20
    historical = [a for a in anchors if is_old(a.rag_ts, >90d)]
    if len(historical) < 2: log(skip='no_anchors'); return
    prompt = DEEP_SLEEP_BRIDGE_SYSTEM_PROMPT                 # модульная константа
    user   = build_bridge_user(packet, historical)
    raw    = await llm.generate_worker("history", [system,user], temperature=0.3)
    paradigms = parse_bridge_answer(raw)                     # STRICT JSON
    for p in paradigms[: _DEEP_SLEEP_MAX_PARADIGMS_PER_RUN=3]:
        if dedup(p): continue                                # по dedup_key/anchor
        insert_graph_fact(chat_id, p.text, "derived_belief", None,
                          weight=0.55, importance=..., source_ids=..., kind="belief",
                          belief_meta={"type":"paradigm",...})
    log(kind='deep_run', tokens=...)
```

**Ограничение стоимости RAG (F3-Q3 — РЕШЕНО):**
- `limits.deep_sleep_top_k` (default 20) — cap кандидатов;
- бюджет токенов через существующий `worker_budget.consume` (`deep_sleep` добавить
  в `WORKER_IDS`) + суточный cap `limits.deep_sleep_tokens_per_day` (default 40000);
- частота — 1 раз/сутки с cooldown 20ч;
- fail-open: ошибка RAG/LLM → skip, без ретраев сверх 1.

**Промпт «Мост времени» (канон):** новый модульный каннон
`DEEP_SLEEP_BRIDGE_SYSTEM_PROMPT` в `services/dream_prompts.py` (+ он же user-хеlper
`build_bridge_user`). Требует: «найди связь между текущими событиями и
историческими фактами; сформулируй мета-факт (парадигму) о развитии
ситуации/человека»; строгий JSON `{"paradigms":[{"text":"...","anchors":[...]}]}`.
Правка/создание канона — PREV + байт-тесты (ADR-1013-3), `PROMPT_MIGRATIONS` не трогаем.

**Подача в контекст:** парадигмы попадают в RAG как обычные belief-строки с
`weight=0.55` (фоновый слой; не перекрывают точный RAG благодаря меньшему весу).
Дополнительный рендер-маркер не нужен.

## 5. Роутер моделей воркеров (F3-Q5 — РЕШЕНО)

Единые PG-ключи (ADR-1013-1):

| Role | base_url | model_name | display_name | api_key |
|---|---|---|---|---|
| `history` | `models.intel_history_base_url` | `models.intel_history_model_name` | `models.intel_history_display_name` | `keys.intel_history_api_key` |
| `background` | `models.intel_bg_base_url` | `models.intel_bg_model_name` | `models.intel_bg_display_name` | `keys.intel_bg_api_key` |

Реализация — новый метод `LLMClient.generate_worker(role, messages, *, temperature=None)`
(использует существующий `_post(..., api_key=..., base_url=...)`, `llm_client.py:581`):
```
def _worker_profile(role):
    prefix = f"models.intel_{role}"
    base = hot.get(f"{prefix}_base_url","") or self._base_url
    model= hot.get(f"{prefix}_model_name","") or self._chat_model
    key  = hot.get(f"keys.intel_{role}_api_key","") or self._current_api_key()
    dedicated = any(hot.get(f"{prefix}_{f}","") or hot.get(f"keys.intel_{role}_api_key","") for f in (...))
    return base, model, key, dedicated

async def generate_worker(role, messages, *, temperature=None):
    base, model, key, dedicated = _worker_profile(role)
    if not dedicated:                          # пусто → основная модель
        return await self.generate(messages, temperature=temperature)
    payload = {"model": model, "messages": messages}
    if temperature is not None: payload["temperature"]=temperature
    try:
        resp = await self._post("/chat/completions", payload, api_key=key,
                                base_url=base, channel="chat")
    except Exception:                          # fail-open → основная модель
        logger.warning("[worker_llm] dedicated failed → main | role=%s", role)
        return await self.generate(messages, temperature=temperature)
    return parse_content(resp)
```

Обязательные в v1 (F3-Q5): **`LoreWorker` → `history`**, **`DreamWorker` → `background`**,
**deep-sleep bridge → `history`**. Рекомендуется также `NostalgiaWorker → background`.
Роутер no-op при пустых ключах → безопасно применить ко всем четырём.
`bot.py` — **только DI-kwargs** (порядок роутеров не трогать); сам роутер живёт
в `LLMClient`, отдельный клиент не создаётся.

## 6. Файлы и точки изменения

| Файл | Что |
|---|---|
| `services/dream_worker.py` | `_tick` :255, `_run` :283, `_finish_chat` :481 — hook запуска deep-sleep после обычного сна; новый `_run_deep_once`/`DeepSleepState` |
| `services/dream_prompts.py` | `DEEP_SLEEP_BRIDGE_SYSTEM_PROMPT` + `build_bridge_user` + `parse_bridge_answer` |
| `services/llm_client.py` | `generate_worker(role, ...)` + `_worker_profile` (аддитивно) |
| `services/lore_worker.py` | `_run_generation` :408 → `generate_worker("history", ...)` |
| `services/dream_worker.py` | `_llm_once` :645 → `generate_worker("background", ...)` |
| `services/nostalgia_worker.py` | LLM-вызовы → `generate_worker("background", ...)` (реком.) |
| `services/worker_budget.py` | `WORKER_IDS` += `deep_sleep`; scope/метрики |
| `services/database.py` | `list_recent_beliefs` + `belief_type`; helpers `insert paradigm` (через `insert_graph_fact`), `last_deep_run`, `count_paradigms` |
| `services/memory_health.py`, `web/api/memory_agi.py` | статус deep-sleep, парадигмы, счётчики |
| `config/settings.py`, `services/param_catalog.py` | новые ключи (см. §8) |

## 7. Каталог-Δ

| Ключ | Кат. | Группа | Тип/дефолт | Settings-поле | per_chat |
|---|---|---|---|---|---|
| `flags.deep_sleep_enabled` | flags | `flags_memory` | bool / **False** | `DEEP_SLEEP_ENABLED` | true |
| `memory.deep_sleep_trigger` | memory | `memory_dream` | str-select / `after_sleep` | `DEEP_SLEEP_TRIGGER` | true |
| `memory.deep_sleep_hour` | memory | `memory_dream` | int / 7 | `DEEP_SLEEP_HOUR` | true |
| `limits.deep_sleep_top_k` | limits | `limits_memory` | int / 20 | `DEEP_SLEEP_TOP_K` | true |
| `limits.deep_sleep_max_paradigms_per_run` | limits | `limits_memory` | int / 3 | `DEEP_SLEEP_MAX_PARADIGMS` | true |
| `limits.deep_sleep_tokens_per_day` | limits | `limits_memory` | int / 40000 | `DEEP_SLEEP_TOKENS_PER_DAY` | true |

Итог F3: **REGISTRY +6 (412→418 с учётом F1/F2)**, Settings +6 (384→390),
GROUPS 90, mapped 88, TAB_RULES 19 — без изменений. `select`-виджет для
`deep_sleep_trigger` — как существующие (`widget='select'`, опции
`after_sleep|fixed`); учесть поля 10.4.

## 8. Feature flag / progressive delivery

- `flags.deep_sleep_enabled` (default **OFF**). OFF → воркер не стартует.
- Rollout: internal (ручной `POST /api/memory/dream/run?deep=1`) → 10% → 50% → 100%.
- Критерии отката: рост бюджета воркеров, ошибки LLM, дубли парадигм, деградация контекста.
- Rollback: флаг OFF + `git revert`; данные (парадигмы) — помечаются архивом без DDL.

## 9. Тест-план

1. Расписание: `after_sleep` — запуск после успешного обычного сна; `fixed` — по часу;
   cooldown 20ч блокирует повтор; наложение прогонов исключено (lock/max_instances).
2. Якорный отбор: свежие beliefs + 12ч-выжимка → RAG; top-k cap; нет истории ≥90д → skip.
3. Синтез: JSON парсится (`parse_bridge_answer`), paradigms пишутся `kind='belief'`,
   `weight=0.55`, `belief_meta.type='paradigm'`; анти-дубли по `dedup_key`.
4. Вес 0.5–0.6 в контексте; precision RAG не перекрыт.
5. Роутер: dedicated модель → вызов на неё; пустые ключи → основная; ошибка dedicated
   → фоллбэк на основную; R17 (ключ не логируется).
6. Байт-канон deep-sleep промпта (PREV + reference).
7. Каталог: Settings 390, ключи читаются `hot.get`.
8. Регресс `test_dream*`, `test_worker_budget*`, `test_llm_client*`.

## 10. Риски

| Риск | Митигация |
|---|---|
| RAG по всей базе дорого | top-k cap + суточный токен-бюджет + cooldown + 1/сутки |
| Дубли парадигм | `dedup_key` (hash anchors+text), анти-галлюцинации по опорам |
| Парадигмы перекрывают точный RAG | weight 0.55 < точных фактов; фоновый слой |
| Наложение с обычным сном | триггер `after_sleep` + lock + cooldown |
| Роутер ломает BYOK/бюджет | dedicated-путь отдельный; no-op при пустых; fallback main |

## 11. Критерии приёмки

- [ ] Deep-sleep стартует ежедневно после обычного сна (или по своему часу).
- [ ] Якорный пакет (beliefs + 12ч) уходит в RAG по всей базе; стоимость ограничена.
- [ ] «Мост времени» пишет парадигму без дублей; вес 0.5–0.6 в контексте.
- [ ] Роутер читает выделенные LLM через `hot` и фоллбэчит на основную.
- [ ] Телеметрия deep-sleep/парадигм; `flags.deep_sleep_enabled` (OFF); R17.
- [ ] `pytest` 0 failed; `git diff --check`; каталог-Δ (418/390) сверена.

## 12. Разрешение open questions (F3)

- **F3-Q1** — `origin='derived_belief'`, `kind='belief'`, маркер `belief_meta.type='paradigm'`; без новой таблицы.
- **F3-Q2** — 12ч-выжимка = свежие `graph_facts` (+beliefs текущего сна), не `smart_messages`.
- **F3-Q3** — top-k 20 + токен-бюджет 40000/сутки + 1/сутки + cooldown 20ч.
- **F3-Q4** — дефолт `after_sleep`, TZ `Asia/Yekaterinburg`, cooldown 20ч.
- **F3-Q5** — обязательны v1: Lore→history, Dream→background, deep-sleep→history; Nostalgia→background рекомендовано.
