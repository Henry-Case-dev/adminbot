# Отчёт F5 — `settings-persistence-audit-round1014` (Step 4 @Builder)

> **Статус: ✅ COMPLETED** (13.09.2026). Все задачи @Builder T-1512…T-1522 закрыты.
> **Baseline:** HEAD `2edc65b` + незакоммиченные F1/F2/F3/F4/F6/F8. Полный `pytest`: см. §5 (актуальный прогон).
> **Каталог-Δ F5 = 0:** REGISTRY 435 / Settings 406 / categorized 411 / GROUPS 90 / mapped 88 / TAB_RULES 19
> (Δ=0 от F5; +1 `content.intelligence_guide` добавлен F6).

## 1. Инвентаризация (T-1512)

Полная механическая таблица изменяемых параметров — `inventory.tsv` (411 строк данных, обход `param_catalog.REGISTRY`;
включая F6-ключ `content.intelligence_guide` и dedicated-роут `/api/info/guide`).
Формат строки: `category | group | pg_key | per_chat | type | widget | save_fn | api_route | storage |
runtime_consumer | read_fn | status`.

Сводка по маршрутизации (решения фронта/сервера):

| per_chat | Категории | Save-path | X-Chat-Id | Storage | Read |
|---|---|---|---|---|---|
| `true` | prompts, limits, flags, reactions, content, memory | `saveBlock`/`saveConfigItem` | есть | `chat_profiles.chat_params.overrides` | `get_chat_param` → `hot.get` |
| `false` | models, keys | `saveBlock`/`saveConfigItem`/`saveKeyItem` (`global:true`) | нет | `bot_settings` | `hot.get` |

`per_chat` — свойство каталога (`ParamSpec.per_chat`: категория ∈ per-chat-набор и `not secret`).
Серверный гейт (`routes.py:429-432`) на chat-пути отдаёт **422** для `per_chat=False` (не ослаблен).
Нативные dedicated-API раунда идут мимо generic-пайплайна и проверены отдельно:

| entity | API | scope | storage | runtime_consumer | restart-check |
|---|---|---|---|---|---|
| Persona (F2/F3) | `GET/PUT/DELETE /api/persona` | Global↔чат (`X-Chat-Id`) | PG `personas`/`persona_traits`/`persona_state` | `resolve_bot_persona` + `get_chat_param("flags.persona_enabled")` (per-chat, H3-фикс) | PUT → новый процесс → персона на месте |
| Справка (F6) | `GET/POST /api/info/guide` (dedicated) | глобально (сид + PG) | `bot_settings[content.intelligence_guide]` | `InfoService.get_guide`/`hot.get` | POST → рестарт → сид НЕ затирает (`_seed_info_key` skip-if-present) |
| Провайдеры (F8) | generic `/api/config` | Global (`per_chat=False`) | `bot_settings` (`models.intel_reflection_*`, `keys.intel_reflection_api_key`) | `llm_probe` block `intel_reflection_main`; runtime роль `reflection` | save → health сброс (см. R10.9-4) |
| Флаги (F1/F2) | generic `/api/config` | per-chat | overrides | `get_chat_param` (per-chat; H3-фикс: persona/self-awareness/weight) | overrides в PG, переживает рестарт |

> Примечание: dedicated-роут `/api/info/guide` (`GET`/`POST`) реализован F6
> (`help-guide-integration-round1014`, `web/api/routes.py:1115-1156`) и внесён в `inventory.tsv`.
> F5-ключ `content.intelligence_guide` сохраняется в `bot_settings` через dedicated-панель справки.

## 2. Trace write-path (T-1513)

```
Vue saveBlock/saveConfigItem/saveKeyItem
   → api() (X-Chat-Id при activeChatId!=null; global:true — без заголовка)
   → routes.post_config  (chat: set_chat_params — транзакция, await)
      └─ routes._post_config_global  (global: ConfigCache.set — INSERT ... ON CONFLICT, await)
```

Оба пути **sync-await**: `ConfigCache.set` ждёт `conn.execute`, `set_chat_params` — транзакцию UPDATE+history+NOTIFY.
Fire-and-forget / `asyncio.create_task` в записи нет → «немедленный commit» выполнен (F5-Q2).

## 3. Найденные дефекты и фиксы

| ID | Класс | Место | Фикс | Файл |
|---|---|---|---|---|
| **R10.9-4** | T5 | `status_service._health_cache` ключ по `module_id`; смена base_url/model/key не инвалидирует `ok` ≤60с | `StatusService.invalidate_health_cache(keys)`; вызов после успешной записи в `_post_config_global`, `config_keys_own_put/delete`. Сброс только для `models.*`/`keys.*` | `services/status_service.py`, `web/api/routes.py` |
| **T1 (scope, `configChatUpdatedAt`)** | T1 | `setActiveChat` не сбрасывал optimistic-метку → save нового чата уходил бы со старым `updated_at` | `this.configChatUpdatedAt = null` в едином scope-сбросе | `web/app.js` |
| **T1 (scope, `keyDrafts`)** | T1 | Черновик ключа/секрета «переживал» смену чата → запись не в свой scope | `this.keyDrafts = {}` + `this.ownKeyDraft = ''` (BYOK) | `web/app.js` |
| **R10.4-7** | T4 | `direct_chat_service._build_rag_block` cap `limits.graph_rag_context_max_chars` читался глобально (`hot.get`) | per-chat резолв `get_chat_param(chat_id, …)` (зеркало `summary_memory._chat_limit`) | `services/direct_chat_service.py` |
| **H3 (10.14-review)** | T4 | `flags.persona_enabled`/`flags.bot_self_awareness_enabled`/`limits.graph_fact_weight_bot` читались глобально (`hot.get`) — per-chat override игнорировался | per-chat `get_chat_param` в async-путях (`direct_chat_service`, `summary_memory`, `dream_worker`); `build_persona_prompt_block(enabled=…)` | `services/direct_chat_service.py`, `services/summary_memory.py`, `services/dream_worker.py`, `services/bot_persona.py` |

### Верифицировано (без изменений кода)
- **R10.3-1 / R10.5-2** (DM, `per_chat=False`): фронтовый `canEditConfig` → read-only (`app.js:2910-2916`),
  серверный гейт chat-пути → 422 (`routes.py:429-432`). Покрыто `test_dm_access.py` + `inventory.tsv`.
- **R10.12-1** (global-save `keys.*`): `saveKeyItem`/`saveBlock` ставят `global:true`, `updated_at:null`;
  регресс-тесты в `tests/js/routing_test.js` (10.12) на месте.
- **Рантайм-воркеры** (T-1517): `dream_worker`/`lore_worker`/`nostalgia_worker`/`memory_health`/
  `memory_maintenance` читают лимиты/флаги через `hot.get` (`_key`/`_cfg` обёртки), не import-time литералы.
- **Рантайм-LLM** (T-1519): `llm_client`/`llm_probe`/`worker_budget`/`status_service` — base_url/model/key
  через `hot.get`/`_resolve`; `model_source ∈ {config, code}` не рассинхронен; R17 — только `{configured,last4}`;
  блок `intel_reflection_main` присутствует в `KNOWN_BLOCKS`/`_BLOCK_SAVED_KEY`.
- **Persona/флаги (UPD, H3-фикс):** PUT/DELETE пишут PG-`personas` синхронно; `flags.persona_enabled`/
  `flags.bot_self_awareness_enabled`/`limits.graph_fact_weight_bot` резолвятся per-chat
  (`get_chat_param`) в direct-пути, `memorize_self_reply`, `dream_worker`; per-chat OFF → persona-блок пуст
  и self-факт не пишется (регресс-тесты в `tests/test_settings_persistence_round1014.py`).

### Граница с активной `config-read-path-audit` (T-1516)
- **F-5 (активная):** точечный read-path grep `settings\.`, import-time потребители (`alan.py:120`), тесты
  `test_hot_config`/`test_config_cache`/`test_hot_migration`. **Не дублировалось.**
- **F5 round1014:** write-path + scope + restart-персистентность + инвентаризация. Единственный read-path-фикс
  (`R10.4-7`) — в рамках T-1518 и не пересекается с задачами F-5.
- Касты T-651/T-652 не трогались (ссылка на `config-read-path-audit/tasks.md`).

## 4. Процедура верификации (T-1520)

**Auto:**
```
.venv/Scripts/python.exe -m pytest tests/test_settings_persistence_round1014.py -q
node --check web/app.js
node tests/js/routing_test.js          # + новый блок F5/T-1514
```
**Manual (сквозная, `/debug_config`):**
1. Админка → выбрать scope (Global или чат) → изменить параметр → «Сохранить».
2. `GET /api/debug/config?key=<ENV_NAME>` (или `/debug_config <ENV_NAME>`) → новое значение немедленно.
3. `sudo systemctl restart admin_bot` → повторить шаг 2 → значение на месте (PG, не RAM).
4. Переключить Global ↔ чат → параметры каждого скоупа не смешиваются; черновики ключей не «переезжают».
5. `models.*`/`keys.*` в DM-скоупе — контролы read-only, ручной POST → 4xx.
**Live (T-1525, гейт @PM/@DevOps):** по одному ключу из каждой категории на Android; приоритет — PERMsoc + persona.

## 5. Тесты (T-1521/T-1522)

- Новый `tests/test_settings_persistence_round1014.py` — **11 тестов**: каталог-инвариант + per_chat-классификация;
  bot_settings round-trip через «рестарт»; chat-override round-trip через новый `ChatParamsCache`; unit +
  route-level инвалидация health-кэша (позитив/негатив); per-chat cap RAG (`_build_rag_block`); статика
  scope-сброса фронта; **H3-регресс**: per-chat OFF → self-факт не пишется + per-chat вес self-факта.
- `tests/js/routing_test.js` — новый блок F5/T-1514 (реальный вызов `setActiveChat`).
- Полный прогон: **5582 passed, 0 failed**; `node --check` clean; `git diff --check` clean.
