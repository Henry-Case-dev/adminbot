# Spec F5 — `settings-persistence-audit-round1014` (Багфикс сохранения настроек + реактивность параметров)

> **Статус: ✅ COMPLETED** (Step 2 @Architect, **итерация 2**, 13.09.2026).
> **Раунд:** 10.14. **T-ID:** T-1511…T-1525. **ТЗ:** `plans/current_task.md` §4 + **UPD** (новые сущности раунда).
> **Зависимости:** нет (параллельно F1/F2; **согласовать с активной `config-read-path-audit`**).
> **Baseline:** HEAD `2edc65b`, pytest 5392/0.
> **ADR:** не требуется (фикс существующего пайплайна; методика ниже = spec-контракт).

---

## §0. Решения Architect (кратко)

| Вопрос | Решение |
|---|---|
| **F5-Q1** границы с `config-read-path-audit` (F-5 active) | F5 владеет **write-path + scope-маршрутизацией + restart-персистентностью + полной инвентаризацией**. `config-read-path-audit` владеет **точечным read-path** (`settings.`-grep, import-time чтения, `/debug_config`-верификация, тесты `test_hot_*`). Пересечение только по «рантайм читает БД» — **ссылаемся, не дублируем** (T-1516). |
| **F5-Q2** «немедленно» | **Sync-await**: UI ждёт 200 от сервера до тоста. Оптимистичный UI **не вводим** (цель — гарантия персистентности, а не скорость). Пишущие вызовы (`ConfigCache.set` `:271`, `set_chat_params` `:254`) уже await-ят PG. |
| **F5-Q3** каталог-Δ | **F5 сам Δ не вводит.** Если фикс scope потребует `per_chat`-флип ключа — только санкционированный Δ + пин-тесты + ADR (пока не требуется). |
| **F5-Q4** import-time потребители | Согласуются с `config-read-path-audit`: мигрировать на `hot.get` **или** зафиксировать фолбек-семантику с пометкой. F5 не трогает уже закрытые T-651/T-652. |
| **F5-Q5** live-верификация | Автотесты + выборка по одному ключу из каждой категории (7) на Android; полный ручной прогон — опц. прод-чек после деплоя. |
| **F5-Q6 (UPD)** новые сущности | В инвентаризацию входят: `flags.persona_enabled`, `flags.bot_self_awareness_enabled` (каталог, generic save); provider-блок `intel_reflection` (F8, models/keys, per_chat=False); **dedicated-API** `GET/PUT/DELETE /api/persona` (PG `personas`, scope Global↔чат) и `GET/POST /api/info/guide` (PG `content.intelligence_guide`). Для dedicated-API проверяются немедленный commit, scope-реактивность и restart-персистентность так же, как для `/api/config`. |

---

## §1. Цель и scope

Изменённые в мини-аппе параметры должны **сохраняться**: немедленно коммититься в БД, переживать переключение Global ↔ чат и рестарт `admin_bot`, и **реально применяться** рантаймом (воркеры, RAG, LLM-клиенты), а не игнорироваться хардкод-дефолтами.

**In scope:** инвентаризация ВСЕХ изменяемых параметров; аудит write-path (Vue → API → БД); scope-маршрутизация Global↔чат; restart-персистентность; ревизия рантайм-потребителей; закрытие найденных дефектов; матрица «сохранено ↔ подхвачено».

**Out of scope:** полный read-path-grep `settings\.` (это `config-read-path-audit`); касты T-651/T-652; изменение каталога ради самого аудита; UI-редизайн.

---

## §2. Таксономия дефектов (T-class)

| ID | Класс | Признак | Пример-кандидат |
|---|---|---|---|
| **T1** | Потеря при scope-свитче | Введённое для скоупа A не сохраняется/затирается при переключении A↔B (кэш/дефолт при рендере, черновик «переживает» reload) | `setActiveChat` не сбрасывает `configChatUpdatedAt`/`keyDrafts` |
| **T2** | Потеря при рестарте | Значение ушло в память, но не в БД (fire-and-forget, PG down проглочен) | гипотетика; проверяем каждый save-путь |
| **T3** | Запись не доходит | Неверный роут/скоуп, 422/403 проглочен, `per_chat`-мисматч, optimistic-409 без ретрая | R10.3-1/R10.5-2 (DM `models.*` per_chat=False), R10.12-1 (закрыт) |
| **T4** | Рантайм игнорирует БД | Потребитель читает import-time `settings.X` или литерал вместо `hot.get`/`get_chat_param` | `UserIdFilter(hot.get(...))` `alan.py:120`; R10.4-7 (direct-RAG cap) |
| **T5** | Стейл read-path после save | Кэш не инвалидируется при записи | **R10.9-4**: `_health_cache[module_id]` не сбрасывается при `saveBlock`/`saveKeyItem` |

**«Осознанное исключение»** (критерий допуска НЕ-мигрированного чтения): (а) значение не user-editable (инфраструктурная константа); (б) поведение зафиксировано by-design (DM read-only) и покрыто тестом; (в) в матрице §5 помечено `EXCEPTION` с обоснованием + ссылкой на задачу-владельца (`config-read-path-audit`).

---

## §3. Аудит write-path

### 3.1. Цепочка (trace)
```
Vue (web/app.js)
  saveBlock              :2386   → api('/api/config', {items, updated_at, global?})
  saveConfigItem         :3170   → api('/api/config', ...)
  saveKeyItem            :3253   → api('/api/config', ...)
  api()                  :1414   → авто X-Chat-Id при activeChatId!=null (:1430);
                                   global:true → БЕЗ X-Chat-Id (:1424-1432)
        ↓
routes.post_config        :367    → chat_id=_chat_id_or_none(X-Chat-Id)
   ├─ chat_id None → _post_config_global :662 → cache.set() (bot_settings)
   └─ chat_id != None → set_chat_params(overrides) :448
        ↓
services/config_cache.set :271    → INSERT ... ON CONFLICT (bot_settings) [await]
services/chat_params.set_chat_params :254 → UPDATE chat_profiles ... [transaction, await]
```

**Новые dedicated-API раунда (UPD) — проверить тем же методом:**
```
Persona (F2/F3):  savePersona/resetPersona → PUT/DELETE /api/persona (X-Chat-Id)
                  → services/bot_persona.save_persona/delete_persona
                  → UPSERT/DELETE personas (scope global|chat) [await]; GET → resolve_bot_persona
Справка (F6):     saveGuide → POST /api/info/guide → InfoService.save_guide
                  → ConfigCache.set(content.intelligence_guide) [await]
Провайдер (F8):   saveKeyItem/saveBlock → generic /api/config → bot_settings (models/keys; per_chat=False)
Флаги (F1/F2):    flags.bot_self_awareness_enabled / persona_enabled → generic /api/config
```
Критерий немедленного коммита для dedicated-API тот же: нет `asyncio.create_task`/fire-and-forget в записи; ошибки PG не проглатываются (5xx/сообщение).

### 3.2. Методика трассировки
- Для КАЖДОГО параметра каталога: `saveBlock`/`saveConfigItem`/`saveKeyItem` → `api()` (X-Chat-Id?) → `routes.post_config` (global vs chat) → хранилище (`bot_settings` или `chat_profiles.chat_params.overrides`) → верификация `/debug_config`.
- Проверка «немедленного коммита»: убедиться, что нет `asyncio.create_task`/fire-and-forget при записи; `ConfigCache.set` и `set_chat_params` await-ят.

### 3.3. Известные дефекты и фиксы

| ID | Класс | Место | Фикс |
|---|---|---|---|
| R10.3-1 / R10.5-2 | T3 | DM-скоуп: `models.*` (per_chat=False) — контролы read-only с R10.5-2 (`canEditConfig`), сервер 422 | **Верифицировать** DM read-only на всех per_chat=False (`models.*`/`keys.*`); серверный гейт `routes.py:414-417` не ослаблять. Тест на DM: контрол disabled, POST → 4xx |
| R10.12-1 | T3 | `saveKeyItem` global-save — закрыт | Регресс-тест (уже есть); подтвердить в матрице |
| **R10.9-4** | **T5** | `services/status_service.py:283-305` — `_health_cache` ключ по `module_id`, смена base/key/model не инвалидирует `ok` ≤60с | **Фикс:** в `post_config`/`_post_config_global` после успешной записи сбросить health-кэш затронутых модулей (по `_BLOCK`-карте `llm_probe`/`KNOWN_BLOCKS`), либо добавить config-version в ключ кэша. Тест: save → health переспрашивается |
| R10.4-7 | T4 | `direct_chat_service._build_rag_block` `:1762` использует глобальный `graph_rag_context_max_chars` (не per-chat) | Согласовать с `config-read-path-audit`; при подтверждении — `get_chat_param` в direct-пути. Помечено как граница G-4 |
| R10.4-6 | T2 | `scripts/backfill_104_*.py` пишут `expected_updated_at=None` (last-write-wins окно) | Осознанное исключение (деплой-минуты); задокументировать |
| S10.13-9/-11/-13/-14/-6b | — | известный техдолг памяти (не write-path) | **Вне scope F5**; ссылка на ARCH §25 |

### 3.4. Scope-маршрутизация Global ↔ чат

- `api()` `:1430`: при `activeChatId != null` ставит `X-Chat-Id`; `global:true` — не ставит.
- `saveBlock` `:2416-2443`: `per_chat===false` → глобальный путь (без X-Chat-Id), смешанный блок → два запроса.
- `saveConfigItem` `:3214` / `saveKeyItem` `:3263`: `global: item.per_chat === false` + `updated_at:null` для global.
- `setActiveChat` `:1621`: сбрасывает chat-scoped стейт, `configItems=[]`, `blockDrafts={}`, `blockResults={}`, вызывает `loadConfig()`. **Дефект T1-кандидат:** `configChatUpdatedAt` НЕ сбрасывается явно в `setActiveChat` (перезапишется `loadConfig`, но между сбросом и ответом возможна запись со старым токеном) + `keyDrafts` не сбрасывается. **Фикс:** сбросить `configChatUpdatedAt=null`, `keyDrafts={}`, **`personaDraft={}`/`personaMeta=null`** (F3) в единый сброс; `scopeEpoch`-гвард уже есть. Для dedicated-API персона-скоуп — `X-Chat-Id` (global → без заголовка), `reset` — явный, а не «пустое значение».
- **Драфт не затирает чужой scope:** после `loadConfig` черновики пусты (`:2882`); для блоков — `blockDrafts`/`blockResults` (`:1661-1662`).

## §4. Ревизия рантайм-потребителей

| Потребитель | Что читает | Ожидаемый путь | Верификация |
|---|---|---|---|
| `dream_worker`, `lore_worker`, `nostalgia_worker` | лимиты/флаги/промпты | `hot.get` / `get_chat_param` | сохранённое значение меняет поведение |
| `summary_memory` (RAG, веса, TTL, decay) | limits/flags | `hot.get` (+ `_chat_limit`) | `_graph_fact_weight*`, `rag_stale_after_days` |
| `tool_router` | лимиты RAG/dig | `hot.get`/`get_chat_param` | — |
| `llm_client`, `llm_probe`, `worker_budget`, `status_service` | base_url/model/key/budget | `hot.get` | `model_source` не рассинхронен (R10.9-1); R17 `{configured,last4}`; роль `intel_reflection` в probe |
| `feature_gates` | флаги | `hot.get` | — |
| **`bot_persona`** (F2) | `personas`/`persona_traits` (PG), `flags.persona_enabled` | `resolve_bot_persona` + `hot.get` | PUT → рестарт → персона на месте; промпт подхватывает |
| **`self_reflection`** (F1) | `flags.bot_self_awareness_enabled`, роль `reflection` | `hot.get` + `generate_worker` | `persona_state` обновляется; фоллбэк на основную |
| **`InfoService`/гайд** (F6) | `content.intelligence_guide` | `hot.get` + `ConfigCache.set` | POST → рестарт → гайд на месте; сид не затирает |

Прямые `settings.X` в рантайм-пути → мигрировать на `hot.get` **или** пометить осознанным исключением (§2). **Не дублировать** `config-read-path-audit/tasks.md`.

## §5. Матрица инвентаризации (заполняет @Builder T-1512)

Формат (одна строка на параметр):
`category | group | pg_key | per_chat | type | widget | save_fn | API route | storage | runtime_consumer(s) | read_fn | status`

Статусы: `OK` | `FIXED` | `EXCEPTION(<причина>)` | `TO-VERIFY`. Категории: `models, keys, prompts, limits, flags, reactions, content, memory`. Источник — рантайм-обход REGISTRY (`param_catalog.REGISTRY`) + `TAB_RULES` + `per_chat`. **Отдельная таблица (UPD):** dedicated-API (`/api/persona`, `/api/info/guide`) — колонки `entity | API | scope | storage | runtime_consumer | restart-check`.

## §6. Верификация (процедура)

1. **Auto:** новый `tests/test_settings_persistence_round1014.py` — save-path per_chat true/false; scope-переключение; restart-персистентность (запись → новый процесс/кэш → чтение); рантайм-чтение (воркер/RAG/LLM) через mock/`hot`.
2. **Manual:** изменить параметр в админке → `GET /api/debug/config?key=<ENV_NAME>` (`routes.py:1187`, `services/debug_config.py`) или `/debug_config <ENV_NAME>` показывает новое значение; рестарт → значение на месте.
3. **Live:** по одному ключу из каждой категории; PERMsoc-раздел (жалоба владельца) + persona (F2/F3) — приоритетно.

## §7. Feature flag / progressive delivery

Не требуется (фикс пайплайна). Rollback = `git revert`. Верификация — статическая + live (владелец), опц. прод-чек после деплоя.

## §8. Критерии приёмки (DoD)

- [ ] Инвентаризация ВСЕХ изменяемых параметров выполнена (таблица §5; каждый — с классификацией T-class и статусом).
- [ ] Цепочка Vue → API → БД проtrace-ена; дефекты записи закрыты.
- [ ] Scope-маршрутизация Global ↔ чат: переключение не затирает введённое; значения читаются из своего скоупа; 422/пер-чат-кейсы обработаны; DM read-only per_chat=False подтверждён.
- [ ] `configChatUpdatedAt`/`keyDrafts` сбрасываются при смене scope.
- [ ] Сохранённое переживает рестарт `admin_bot` (сквозная процедура).
- [ ] Для каждого параметра подтверждено, что рантайм читает БД (`hot.get`/`get_chat_param`), либо осознанно зафиксировано исключение.
- [ ] R10.9-4 (health-кэш) закрыт; границы с `config-read-path-audit` задокументированы (нет дублей).
- [ ] Dedicated-API (UPD): `GET/PUT/DELETE /api/persona`, `GET/POST /api/info/guide`, provider-блок `intel_reflection` и флаги F1/F2 — save/scope/restart-реактивность проверены (немедленный commit, `X-Chat-Id`, сид не затирает).
- [ ] Полный `pytest` 0 failed (база 5392); `node --check` clean; `git diff --check` чист.
