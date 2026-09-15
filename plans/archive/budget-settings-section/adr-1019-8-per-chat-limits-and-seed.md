# ADR-1019-8 — Мультичатовая per-chat архитектура лимитов/хранения + сид настроек чатов (данные, не хардкод)

- **Статус:** Proposed (Step 2 @Architect, итерация 2 раунда 10.19, 15.09.2026). **Требует санкции владельца** на каталог-Δ и целевые дефолты (принято в UPD3).
  **Реализация по батчам:** **F2-часть (Батч B, @Builder, 15.09.2026) ✅** — sentinel-таблица семейств в `services/budget_limits.py`, per-chat резолв `chat_usage`, дефолты 100/500k и 60/300k (D2/D7). **Ревью-фиксы Батча B (D-1/D-2):** строка «Бюджет фона» реализована и в `services/worker_budget.py` — sentinel `−1`=безлимит/`0`=запрет + per-chat резолв (`resolve_setting_cached`, дефолты 60/300k), `_metric_limit` async.   **F3-часть (Батч C, @Builder, 16.09.2026) ✅** — сид настроек чатов D4 (`services/chat_settings_seed.py` + `config/chat_settings_seed.json`, идемпотентный вызов в `bot.py main()`), guard purge D5 (`services/retention_policy.py`), «Сводка» D6 (`limits` в `build_summary` + UI «Безлимит (∞)»/«Импорт: Вечно»), каталог-Δ D8 (2 группы + `mod_budgets` + retention-ключ), S10.19-8 (`migrate_global_budget_defaults`).
  **Ревью-фиксы Батча C (D-1…D-8, @Builder, 16.09.2026):** D-1 — `_limits_metric` разводит контуры явным `contour` (`direct`→`chat_usage.key_status`; `worker`→`day_rows`), `key_budget != worker_budget`; D-2 — `chat_params.get_all_chat_params(chat_id, pg=…)` (прямое PG-чтение для CLI-пути сида, merge не теряет чужие overrides/meta); D-3 — OFF тумблера пишет явные `global_value` вместо DELETE (см. §D4); D-4 — тесты direct-контура (key_status вызван, контуры различаются, `used` из key_status); D-5 — retention **fail-closed** на ошибке резолва + шапка модуля фиксирует, что DB-слой/purge = F7; D-6 — «не задано» (0/None) контекста → фактически эффективный дефолт (1000/500), не ложный `limit: 0`; D-7 — `IMPORT_HISTORY_RETENTION_DAYS` в `.env.example`; D-8 — формулировки «новых хардкодов нет» (spec/ADR/тест).
- **Дата:** 2026-09-15
- **Раунд:** 10.19, итерация 2 (**UPD3**, `plans/current_task.md:178-216`). Затрагивает F2/F3/F4/F7.
- **База:** HEAD `fd6acc7`. **Связано:** ADR-1019-2 (бюджетный sentinel), ADR-1019-3 (раздел «Бюджеты»), ADR-1019-4 (контекстные лимиты), ADR-1019-6 (retention), ADR-1018-7 (единый резолв настроек `chat → global → default`), F-7 §4.4 (`per_chat`).
- **AMEND:** ADR-1019-2 D1/D5 (дефолты), ADR-1019-3 D2/D3/D4/D6, ADR-1019-4 D3, ADR-1019-6 D1/D2. **SUPERSEDE:** идея «глобального хардкода безлимитов» и ранее предложенные дефолты 300/1.5M и 120/500k.
- **Создаётся вместо `advisor`-amend:** централизованный ADR нужен, потому что решение сквозное (4 фичи, 3 семейства sentinel, сид, guard, изоляция, каталог). Локальные ADR ссылаются на него, не дублируют.

## Context

1. **UPD3 (п.2):** «Хардкодить безлимиты глобально **ЗАПРЕЩЕНО**. Система должна быть мультичатовой.» Глобальные дефолты остаются консервативными предохранителями; безлимит — **только per-chat override**.
2. **UPD3 (п.3):** целевой чат `-1002661910336` должен получить эксклюзивные настройки **данными** (миграция/сид): хранение импорта `0` (вечно), бюджеты `−1` (безлимит), контекст — максимально возможный/безлимит. Id — «операционный параметр», не ветвление в бизнес-логике.
3. **UPD3 (п.2):** изоляция памяти — импорт и вся память строго по `chat_id`; утечка контекста между чатами недопустима.
4. **UPD3 (п.4-5):** «Сводка» показывает состояние лимитов (`Безлимит (∞)`) и статус хранения (`Импорт: Вечно`); дефолты пересмотреть (умеренные глобальные + per-chat безлимит).
5. **Разнородность sentinel-семантик:** у бюджетов канон F-7/F-15 — `0 = запрет`; у срока хранения интуитивно `0 = вечно`; у контекста `0` исторически означает «не задано → дефолт». Одна общая константа `0` для всех недопустима — нужно **явное разделение по семействам** с таблицей.
6. **Инварианты:** R16 (аддитивность API), R17 (без секретов), fail-open, порядок роутеров `bot.py`, DDL санкционирован (project.md).

## Decision

### D1. Мультичатовая модель: безлимит = данные чата, не код
Единственный путь включения безлимита — per-chat override (`chat_profiles.chat_params.overrides`) через `chat_params.set_chat_params` / `POST /api/config` (+`X-Chat-Id`) / тумблер F3. **В коде нет ветвлений по `chat_id`.** Глобальный слой (`hot.get`/env) остаётся **консервативным предохранителем** для всех чатов без override.

### D2. Таблица sentinel-семантик (по семействам — разные!)
| Семейство | Ключи | `0` | `< 0` (`−1` канон) | `> 0` | Глобальный дефолт |
|---|---|---|---|---|---|
| **Бюджет ключа чата** (direct) | `limits.chat_global_key_budget_requests`, `…_tokens` | **запрет** общего ключа чату (канон F-7/F-15 — **осознанно сохранён**) | **безлимит** | cap | 100 / 500 000 |
| **Бюджет фона** (worker, per-chat scope) | `limits.worker_daily_llm_calls_per_chat`, `…_tokens_per_chat` | **запрет** фонового расхода чата | **безлимит** | cap | 60 / 300 000 |
| **Лимит контекста** | `limits.chat_global_context_max_tokens`, `limits.chat_thread_max_tokens`, `limits.chat_context_budget_tokens` | **не задано** → глобальный дефолт (никогда не «пустой блок») | **безлимит** → практический потолок `CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS` | cap | 5000 / 3000 / 16000 |
| **Хранение импорта** | `limits.import_history_retention_days` | **вечно** (purge категорически запрещён) | **невалидно** → fallback на глобальный дефолт + WARNING | хранить N дней | 180 |

Обоснование таблицы:
- **Бюджеты** сохраняют `0 = запрет` — явное требование канона F-7/F-15 (подтверждено как осознанное), `−1` — безлимит. Не переиспользуем `0` под «безлимит» (ломка прод-значений и тестов).
- **Контекст**: `0` не может означать «запрет» (это тихо опустошило бы блок и сломало ответ), поэтому `0 = не задано`. Безлимит `−1` **не бесконечен физически** — ограничен окном модели и потолком безопасности (D3).
- **Retention**: здесь `0 = вечно` — **другой sentinel**, чем у бюджетов. Негатив невалиден (нет смысла «минус дней»), поэтому fallback на глобальный дефолт. Семейства не смешиваются: у каждого свой хелпер (`budget_state`, `context_state`, `retention_state`).

### D3. Потолок безопасности безлимитного контекста (env-only, Δ каталога = 0)
`config/settings.py`: `CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS: int = _env_int_min("CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS", 32000, 1000)` — **infra/env-only**, не в каталоге. `−1` у per-block/общего бюджета резолвится в этот потолок; `unlimited=True` сохраняется в статусе. `−1` у общего бюджета означает «не применять агрегатное усечение `_apply_context_budget`» (per-block потолки продолжают действовать).

### D4. Сид настроек чатов — данные, не хардкод
- **Артефакт:** `config/chat_settings_seed.json` (versioned, без секретов) — список `{chat_id, note, enforce: [...], overrides: {...}}`.
- **Загрузчик:** `services/chat_settings_seed.py::apply_chat_settings_seed(pg, *, force=False, seed_path=None) -> dict`.
- **Идемпотентность:** ensure-профиль (`chat_params.ensure_scope_profile(chat_id, dm=False)`) → merge overrides (текущие ∪ желаемые) → `set_chat_params` **только при фактическом изменении** (иначе skip: без NOTIFY/history-шума). Повторный запуск — no-op.
- **Политика полей:** `enforce`-ключи (retention) применяются **всегда** (tail-инвариант безопасности данных); остальные (бюджеты/контекст) — при отсутствии, при росте `version` сида или `force=True` (уважает ручные правки владельца через UI).
- **Точка вызова:** `bot.py main()` рядом с `migrate_dream_thresholds` (fail-open: PG down/нет файла → WARNING, бот жив). Опционально CLI `python manage.py apply-chat-overrides [--force]`.
- **Почему id в сиде допустим:** это **декларативные данные оператора** (как `DREAM_THRESHOLD_MIGRATIONS` в `services/config_migrations.py` или DM-дефолты `_DM_DISABLED_OVERRIDES`), а не ветвление бизнес-логики. Код-путь generic (`for entry in seed["chats"]`), работает для N чатов, не содержит `if chat_id == …`. @Reviewer проверяет, что **новых хардкодов нет** (grep `services/*`): id допустим в `config/chat_settings_seed.json`/тестах; легаси-константы `services/chat_lore.py`, `manage.py:44`, `tools/history_import/llm_worker.py` существовали до F3 и настройками сида не являются (D-8 ревью Батча C).
- **HOTFIX (Post-Deploy Gate, 16.09.2026):** запись истории сида обязана передавать `changed_by=None` (а не строковый маркер): колонка `chat_lore_history.changed_by` — `BIGINT` (`services/pg_db.py:95`), строка давала asyncpg `DataError` и fail-open съедал исключение → сид не применялся на проде. `None` — канон «системная/бот-запись» (README: «changed_by NULL = бот/AI»; `scripts/backfill_*.py`, `handlers/chat_lifecycle.py`), аудит-строка сохраняется (в отличие от `record_history=False`); int-сентинел `0` в кодовой базе не используется.
- **D-3 (ревью Батча C) — OFF тумблера безлимита:** OFF пишет **явные значения глобального слоя** через `POST /api/config` (новое аддитивное поле `global_value` в GET-элементе), а **не** `DELETE /api/config/chat/<key>`. Причина: DELETE терял `meta.chat_settings_seed_version`, и сид на рестарте снова ставил `−1` → «Выключено» для целевого чата было ложным. Выбор варианта (а) обоснован: (б) tombstone — новый механизм/схема, (в) скрыть OFF — владелец не может снять безлимит. Generic-`DELETE` дополнительно чинится merge'ом `meta` (не затираем чужой meta) — belt-and-suspenders.

### D5. Guard purge импортированной истории
- **Policy-слой:** `services/retention_policy.py::imported_history_purge_allowed(chat_id) -> (allowed: bool, days: int, source: str)`; `allowed = (days != 0)`.
- **Fail-closed (D-5 ревью Батча C):** ошибка резолва срока → `(False, 0, 'error')` — для разрушительной операции «не удалять» безопаснее, чем fail-open. Невалидный override (`<0`) — по-прежнему fallback на глобальный дефолт (не ошибка).
- **DB-слой (структурный guard):** `DatabaseService.purge_imported_history(*, chat_cutoffs: dict[int, int], batch=2000, dry_run=False)` — **keyword-only, без дефолта**; обрабатываются только чаты из маппинга. Нет «удалить всё по глобальному сроку» как возможности.
- **Call-site:** единственный — `services/memory_maintenance.py::run_import_retention()`; маппинг строится только из чатов, где `allowed=True`. Тест фиксирует единственный call-site и что целевой чат (retention=0) никогда не попадает в маппинг.
- **Статус (D-5):** реализована ТОЛЬКО policy-часть; DB-слой (`purge_imported_history`) и call-site (`run_import_retention`) — **F7**, в этом раунде не реализованы. Пока DB-слоя нет, destructive-purge невозможен по построению; D5 **не закрыт** полностью.
- **Belt-and-suspenders:** `enforce`-политика сида (D4) гарантирует возврат `0` на каждом старте; `0 → false` в policy.

### D6. «Сводка»: аддитивный контракт (R16) + UI-тексты
В карточку чата (`services/oversight.py::build_summary`) добавляется `limits` (новый ключ; существующий `budget` worker-контура **не трогается**):
```python
"limits": {
  "key_budget":    {"calls": METRIC, "tokens": METRIC},   # direct (chat_usage)
  "worker_budget": {"calls": METRIC, "tokens": METRIC},   # фон (зеркало budget)
  "context": {"global_tokens": CAP, "thread_tokens": CAP,
              "total_budget_tokens": CAP},
  "storage": {"import_retention_days": int, "import_forever": bool,
              "source": "chat|global|default", "label": "Вечно" | "180 дней"},
}
# METRIC = {"used": int, "limit": int, "unlimited": bool,
#           "forbidden": bool, "source": "chat|global|default"}
# CAP    = {"limit": int, "unlimited": bool, "source": "chat|global|default"}
```
UI: при `unlimited` → бейдж/текст **«Безлимит (∞)»** вместо `N / M`; при `forbidden` → **«Запрещено»**; storage → **«Импорт: Вечно»** / «Импорт: N дней». Показывается в «Сводке» (карточка чата) и/или виджете «Интеллект и Память». Ноль новых эндпоинтов.

### D7. Пересчёт дефолтов (консервативные глобальные предохранители)
Пересматривают предыдущие предложения (300/1.5M, 120/500k) в пользу умеренных значений; безлимит — только per-chat (данными сида). Точная таблица — ADR-1019-2 §D5 (updated), ADR-1019-3 §D7 (updated), ADR-1019-6 §D1 (retention 180). Глобальные лимиты фон-контура (200/500k) — **не меняются**.

### D8. Каталог-Δ (точный; санкция владельца — UPD3 принято)
См. ADR-1019-3 §D3 (updated) и spec F3 §4.3: `REGISTRY 436→437`, `Settings 406→407`, `categorized 411→412`, `GROUPS 90→92`, `mapped 88→90`, `TAB_RULES = CONFIG_TAB_TITLES 19→20`, `TAB_NAV +1`; JS `TABS` +1 (`mod_budgets`). Новых REGISTRY-ключей — **ровно 1** (`IMPORT_HISTORY_RETENTION_DAYS`); остальные поля — существующие per-chat ключи.

### D9. Feature flag не вводится
Безлимит/retention — персистентные данные чата, не rollout-флаг. Progressive delivery — по данным: целевой чат (`-1002661910336`, сид) → проверка → остальные по решению владельца. Rollback — `git revert` + снятие override (или `force`-перезапись значений).

### D10. UPD4 — нейтральный сид настроек + бэкап-гейт деструктивного purge
- **Концепция «VIP» удалена из кода полностью** (UPD4 п.1): артефакты переименованы в нейтральные универсальные —
  `services/chat_settings_seed.py` + `config/chat_settings_seed.json` (`load_chat_settings_seed`/`apply_chat_settings_seed`/`enforced_eternal_chat_ids`),
  CLI — `python manage.py apply-chat-overrides [--force]`, мета-ключ — `chat_settings_seed_version`, источник резолва retention — `source='seed_enforced'`.
  Код-путь остаётся generic (`for entry in seed["chats"]`), никаких `if chat_id == …`. Целевой id — **только данные** (`config/chat_settings_seed.json`) и тесты.
- **Fail-safe деструктивных операций (D-1):** недоступность chat-слоя → `source='error'` → `allowed=False` (retention `0`) и `run_import_retention` отменяет прогон целиком (`chat_layer_unavailable`); fallback на 180 дней **запрещён**.
- **Dry-run + бэкап-гейт (D-2/UPD4 п.3):** `run_import_retention`/`purge_imported_history` поддерживают `dry_run`; авто-крон `compress_and_purge` выполняет DELETE только при `IMPORT_RETENTION_ENABLED=true` И `IMPORT_RETENTION_DRY_RUN=false` И `IMPORT_RETENTION_BACKUP_CONFIRMED=true` (env-only ClassVar, Δ каталога = 0); иначе — dry-run + WARNING.
- **Двухэтапный гейт данных (UPD4 п.4):** @Reviewer проверяет только наличие/корректность сида; @DevOps выполняет SQL-проверку `chat_profiles.chat_params` целевого чата (`retention=0`, бюджеты/фон/контекст `-1`) **до** рестарта и при расхождении делает abort+откат. Чеклист — spec F7 §10.


## Consequences

**Positive**
- Мультичатовость соблюдена; нет глобального хардкода безлимитов — дефолты остаются предохранителем.
- Один явный, документированный механизм для любой политики чата (сид) + безопасный guard уничтожения данных.
- Разные sentinel-семантики разведены таблицей; исчезает риск «0 = то ли запрет, то ли вечно».
- «Сводка» показывает правду (`Безлимит (∞)`, `Импорт: Вечно`) — владелец визуально контролирует безопасность данных.

**Negative**
- Три семейства sentinel-семантик требуют дисциплины и тестов (митигируется хелперами и таблицей).
- Retention-сид с `enforce` перезаписывает ручную правку срока хранения для целевого чата при каждом старте (осознанно: защита от необратимого удаления).
- Каталог-Δ (+1 ключ / +2 группы / +1 вкладка) — синхронные пин-тесты и JS-parity.
- Ещё один артефакт-сид в репозитории (chat_id без секретов) — риск-принято.

## Alternatives

- **A1. Глобальный безлимит (env/код) — отклонено владельцем прямо (UPD3 п.2).**
- **A2. «0 = безлимит» для бюджетов — отклонено (ломка канона F-7/F-15, прод-значений, тестов).**
- **A3. Хардкод `if chat_id == -1002661910336` — отклонено (UPD2/UPD3).**
- **A4. Отдельный bool-флаг «безлимит» — отклонено (дублирует `−1`, Δ каталога).**
- **A5. Retention целевого чата через код-исключение — отклонено (нарушает мультичатовость); вместо этого `0 = вечно` + `enforce`-сид.**
- **A6. Безусловный purge по глобальному сроку — отклонено (D5: только явный chat-allow-list).**
- **A7. Новая таблица per-chat-лимитов — отклонено: `chat_params.overrides` уже слой per-chat (ADR-1018-7).**

## References

- `plans/current_task.md:178-216` (UPD3), `:130-175` (UPD2)
- `services/chat_params.py:226-326,352-386` (`get_chat_param`, `set_chat_params`, `ensure_scope_profile`)
- `services/worker_settings.py:112-155` (`resolve_setting_cached`)
- `services/config_migrations.py:21-73` (прецедент идемпотентной DML-миграции данных)
- `services/chat_usage.py:53-136`; `services/worker_budget.py:184-244`; `services/token_counter.py:100-140`
- `services/database.py:1457-1556` (`get_smart_raw`, `purge`-пути), `tools/history_import/loader.py:126-223`, `tools/history_import/parser.py:122-171`, `tools/history_import/checkpoints.py:29-64`
- `services/oversight.py:128-230`; `web/index.html:983-1180`; `web/app.js:36-99`
- `services/param_catalog.py:139-253,1229-1268,1737-1936`
- ADR-1018-7; ADR-1019-2/-3/-4/-6; spec F2/F3/F4/F7 (итерация 2)
- Задачи итерации 2: T-1853…T-1865 (backlog 10.19)
