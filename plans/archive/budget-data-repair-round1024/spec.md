# spec.md — F22 `budget-data-repair-round1024`

> **Раунд:** 10.24 (UPD5-critical) · **Приоритет:** P0 / Critical · **Шаг 2 @Architect** · **Тип:** ремонт/аудит данных (PG `overrides`) + разграничение флага
> **ТЗ:** `plans/current_task.md`, строка 404 · **Задачи:** `tasks.md` T-2369…T-2375 · **Baseline:** HEAD `a406440` (F20 уже закоммичен `070f31c`; прод `4314ea4`)
> **ADR:** `ADR-1024-23.md` (**AMEND ADR-1019-8 D4**) · **Backlog:** 10.24, F22
> **Границы:** F20 `budget-overrides-merge-fix-round1024` (**предпосылка**, уже в HEAD) · F21 `budget-global-toggle-round1024` (master-тумблер; F22 только **разграничивает** семантику, не реализует) · F23 `budget-guardrails-round1024` (пин-тесты)

---

## 1. Цель

1. **Идемпотентно вернуть** целевого чата `-1002661910336` потерянные per-chat значения `overrides` — 8 seed-ключей из `config/chat_settings_seed.json:11-20` (включая `-1` = безлимит). Значения были стёрты merge-багом, починенным в **F20** (после F20 потеря прекращена, но данные не восстановлены).
2. **Дать read-only аудит**: когда и что именно стёрлось (таймлайн `chat_lore_history`), что сейчас фактически лежит в `chat_profiles.chat_params`, и сходится ли это с эталоном.
3. **Зафиксировать разграничение** `flags.chat_context_budgets_enabled` (усечение контекста) ↔ master-тумблер бюджетов (F21 `flags.budgets_enabled`), не сломав `scripts/backfill_104_chat_flags.py`.

**Решение владельца (Gate G5 — да):** идемпотентно вернуть 8 стандартных значений из сида (с бесконечными лимитами) + аудит истории правок; JSONL/историю читать **read-only**, **секреты не выводить** (R17/R18).

**Строгий порядок:** **F20 (fix, ✅ есть) → F22 (repair)**. Ремонт до фикса бессмысленен (данные снова затираются).

---

## 2. Что уже есть (координаты, подтверждены разведкой кода)

| Зона | Координата | Роль |
|---|---|---|
| **Эталон 8 ключей** | `config/chat_settings_seed.json:11-20` — `limits.import_history_retention_days: 0`, `limits.chat_global_key_budget_requests/tokens: -1`, `limits.worker_daily_llm_calls/tokens_per_chat: -1`, `limits.chat_global_context_max_tokens: -1`, `limits.chat_thread_max_tokens: -1`, `limits.chat_context_budget_tokens: -1` | Данные оператора (не ветвление) |
| **Идемпотентный сид** | `services/chat_settings_seed.py:127-202` — `apply_chat_settings_seed(pg, force=…)`: ensure-профиль → direct PG-read `overrides`+`meta` → patch только при фактическом изменении → `set_chat_params` (иначе `skipped`, без UPDATE/history/NOTIFY) | Канонический write-path ремонта |
| **Политика полей (D4)** | `:149-172` — `enforce` всегда; иначе `force or not present or version_bump` | Ключ к выбору метода ремонта (см. §3.1) |
| **CLI сида** | `manage.py:595-603` (парсер), `:828-852` (`_cmd_apply_chat_overrides`) | **Содержит дефект** (см. ниже) |
| **Авто-сид при старте** | `bot.py:1049-1054` (fail-open) | Резервный путь ремонта (рестарт) |
| **Баг F20 (исправлен)** | `web/api/routes.py:482-488` — после фикса `perm_overrides` (права) и `value_overrides` (значения) разведены; `:529-537` merge от `value_overrides` | Причина потери устранена |
| **История/аудит** | `chat_lore_history` (`services/pg_db.py:89-102`, CHECK включает `'chat_params'` `:204-208`); `services/chat_params.py:347-353` пишет `old_value`/`new_value` = `json.dumps` **всего root** | Таймлайн правок |
| **Читатель значений** | `services/worker_settings.py:123-150` (`resolve_setting(_cached)`, источник `chat\|global\|default`) | Резолв флага/лимитов |
| **Разграничиваемый флаг** | `services/direct_chat_service.py:1139-1149` (`flags.chat_context_budgets_enabled` + `limits.chat_context_budget_tokens`); `scripts/backfill_104_chat_flags.py` (ставит `false` целевому, только если ключа нет) | Усечение контекста, НЕ master-рубильник |
| **Маска ключей** | `services/chat_keys.py:47-59` (`mask_key_info`/`mask_chat_key_info` → `{configured,last4}`) | R17-safe вывод chat_keys |
| **Мастер-схема PG** | `bot_settings(key,value,category)`; `chat_usage(chat_id,day,metric,used)`; `worker_budget(day,scope 'chat:<id>',metric,used)`; `chat_keys(chat_id,key_name,key_value,key_hint)` | Read-only аудит |

### 2.1. Критическая находка: CLI `apply-chat-overrides` — тихий no-op

`manage.py:832-846`:
```python
pg = PgDatabase()
await pg.init(seed_settings=False)   # ← НЕТ await pg.connect()
```
`PgDatabase.init()` при `self._pool is None` пишет WARNING и **возвращается** (`services/pg_db.py:521-528`). Следом `apply_chat_settings_seed` видит `pg.pool is None` → лог «skip: PG недоступен» → возвращает пустой отчёт. CLI печатает `applied=0 skipped=0 errors=0` и **exit 0**.

**Итог:** сегодня `python manage.py apply-chat-overrides` физически ничего не делает и притворяется успешным (подтверждено follow-up `plans/metrics.md:299`). Это **блокер** T-2370/T-2375 — F22 обязан это починить (F22 владеет `manage.py` по ступени).

> Проверка «вживую» из этой сессии невозможна: PG слушает только `127.0.0.1` прод-сервера (`project.md`), в локальном окружении нет ни Docker, ни Python-рантайма. Read-only SQL из §6 выполняет @DevOps на проде.

---

## 3. Требуемое поведение

### 3.1. Канонический ремонт = **plain-сид** (без `--force`)

Логика `services/chat_settings_seed.py:165-172` уже реализует нужное: ключ, которого **нет** в `overrides` (`not present=True`), добавляется; существующий ключ не трогается (при `force=False` и без bump версии). Merge-баг F20 стирал namespace **целиком**, поэтому все 8 seed-ключей целевого чата стали **absent** → plain-сид их вернёт.

**Контракт ремонта:**
1. Ремонт выполняется **тем же** `apply_chat_settings_seed(force=False)` — без новой repair-логики и без второй write-path (единый источник истины — сид).
2. Идемпотентность: повторный прогон при наборе == эталон даёт `skipped` (нет `set_chat_params`, нет `chat_lore_history`, нет NOTIFY). «Петля save → стирание → рестарт-лечение» разорвана F20 и подтверждается §6.8.
3. `--force` **НЕ используется по умолчанию**: он перезаписывает present-значения и потому **нарушает `manual-overrides-immutable`** (§4). `--force` — только **break-glass** по явному гейту владельца и после read-only аудита (§3.3), как «плановое решение» для случая «ключ present, но значение неверное».
4. Перед ремонтом обязателен read-only аудит (§3.3): он даёт классификацию каждого seed-ключа — `ok` / `absent` / `different`. Если все `ok`/`absent` → plain-сид. Если есть `different` → **Human Gate** (владелец решает, применять ли `--force`); без санкции такие ключи не перезаписываются.

### 3.2. Починка CLI-пути (`manage.py`)

`_cmd_apply_chat_overrides` обязан:
1. вызвать `await pg.connect()` **до** `pg.init(seed_settings=False)`;
2. если после connect `pg.pool is None` → печать ошибки в stderr и **non-zero exit** (не выдавать успех за тихий no-op);
3. различать «нечего делать» (PG ok, отчёт пуст из-за no-op) и «PG недоступен» (ошибка);
4. печатать тот же итог (`applied/skipped/errors` + ключи), что и сейчас, чтобы контракт вывода сохранился.

### 3.3. Read-only аудит (`manage.py audit-chat-overrides`)

Новая **read-only** CLI-команда (только `SELECT`, без `set_chat_params`/NOTIFY). Собирает:

1. **Текущее состояние** `chat_profiles.chat_params` целевого чата: набор ключей `overrides`; сверка с эталоном сида для этого chat_id → по каждому из 8 ключей класс `ok|absent|different`; `meta.chat_settings_seed_version`; `keys.allow_global` (**только presence**, без значения); `updated_at`.
2. **JSONL-таймлайн** `chat_lore_history WHERE chat_id=$1 AND field='chat_params'`: по каждой строке — `created_at`, `changed_by` (BIGINT; `NULL` = бот/сид, по README «changed_by NULL = бот/AI»), наборы ключей `overrides` из `old_value`/`new_value`, `added`/`dropped`, `seed_version_old/new`, признак `wipe_suspected` (уменьшение числа seed-ключей). Это и есть ответ «когда/что стёрлось».
3. `chat_keys` — **только** `{configured, last4}` через `mask_key_info` (сырое значение не печатается никогда).
4. `chat_usage` (metric/used) и `worker_budget` (scope `chat:<id>`) — **только числа**.
5. `bot_settings` глобальные значения 8 limit-ключей — **только числа**.
6. Резолв `flags.chat_context_budgets_enabled` через `worker_settings.resolve_setting_with_source` → `{value, source}`.

**R17/R18-редакция (жёстко):** в stdout/JSONL попадают только **имена** ключей, **счётчики**, seed-значения (числа `0/-1`) и `{configured,last4}`. Сырые `key_value`, токены, пароли, полные JSON-дампы `new_value` — **не выводятся**. JSONL — в `var/` (gitignored); редактированная сводка — в `plans/reports/round1024_f22_audit.md`.

### 3.4. Разграничение `flags.chat_context_budgets_enabled` ↔ master-тумблер (F21)

Это **две разные оси**, их нельзя смешивать:

| Ось | Ключ | Что делает | Где |
|---|---|---|---|
| **Усечение контекста** (direct) | `flags.chat_context_budgets_enabled` | Включает/выключает *применение бюджетов контекста промпта* (`_apply_context_budget`: per-block/агрегатное усечение) | `direct_chat_service.py:1139-1162` |
| **Master-рубильник бюджетов** (F21) | `flags.budgets_enabled` (новый, F21) | Выключает **все** бюджеты (direct key + worker + context) глобально/для чата | F21 |

**Иерархия (фиксируется F22, реализуется F21):** master OFF **перекрывает** всё, включая `chat_context_budgets_enabled`; master ON **не отменяет** усечение контекста (`chat_context_budgets_enabled=false` продолжает работать как раньше). Значит `scripts/backfill_104_chat_flags.py` (ставит `false` целевому) остаётся валидным и **не меняется**.

**F22 не трогает ни один из этих флагов** и не пишет их: 8 seed-ключей — это `-1` (безлимит), они ортогональны обеим осям. Если master (F21) в будущем станет OFF для чата — это не предмет F22.

### 3.5. Порядок и границы

- **F20 → F22** (F20 в HEAD `070f31c`). Ремонт запускается только после подтверждённого F20.
- F22 **не реализует** F21 (только документирует границу) и **не** правит F20-код.
- F22 **не меняет** `scripts/backfill_104_chat_flags.py`.

---

## 4. Инварианты

- **`manual-overrides-immutable`** (ADR-1024-21 D3): ремонт восстанавливает **только seed-набор** и не может разрушить/затереть ручные `overrides`. Plain-сид уважает present; `--force` — только по гейту.
- **R16** (id — ключ, не имя; API-аддитивность): аудит — новый локальный CLI, внешних API-контрактов не меняет.
- **R17/R18** (секреты/значения ключей): в выводе только `{configured,last4}`, имена ключей и числа; значения-секреты не логируются/не печатаются.
- **Канон write-path:** любая запись — только через `chat_params.set_chat_params` (NOTIFY + инвалидация `ChatParamsCache` + history). F22 не вводит второго write-path.
- **Δ DDL = 0. Δ каталога = 0.** Новых config-ключей нет.
- Порядок роутеров `bot.py` — не затрагивается.

---

## 5. Изменения по файлам / CLI

### 5.1. `manage.py` (один файл, F22-ступень)
- **`:832-846`** — `_cmd_apply_chat_overrides`: добавить `await pg.connect()` перед `pg.init(...)`; при `pg.pool is None` — stderr + non-zero. Форма вывода сохраняется.
- **`:595-603` + диспетчер `:1117-1118`** — новый subparser `audit-chat-overrides` + хендлер `_cmd_audit_chat_overrides` (read-only, §3.3). Аргументы: `--chat-id` (required), `--seed` (default `config/chat_settings_seed.json`), `--history-limit` (default 200), `--jsonl` (default `var/audit/chat_overrides_<chat_id>_<utc>.jsonl`), `--strict` (non-zero при дрейфе).

### 5.2. `services/chat_settings_seed.py` — **не меняется**
Политика `enforce`/`version`/`force` достаточна (ADR-1019-8 D4). Ничего не добавляем, чтобы не создавать второй ремонтный путь.

### 5.3. `config/chat_settings_seed.json` — **не меняется** (эталон уже верный).

### 5.4. `scripts/backfill_104_chat_flags.py` — **не меняется** (только read-only ссылка для сверки).

### 5.5. Служебное (не runtime)
- `plans/reports/round1024_f22_audit.md` — редактированная сводка аудита (без секретов).
- `var/audit/*.jsonl` — сырой JSONL (gitignored).

Опционально (если @Architect/@Builder решат не расширять `manage.py`): вынести аудит в `scripts/audit_chat_overrides.py`. Предпочтение — subcommand `manage.py` (обнаружимость, единый CLI), см. ADR-1024-23 A4.

---

## 6. План проверки

### 6.1. Тесты (T-2370/T-2371/T-2372/T-2373)
Локации: `tests/test_chat_settings_seed_round1019.py` (дополнить) и новый `tests/test_budget_data_repair_round1024.py` (по образцу `_FakeChatParams`/`_FakeSeedConn`).

1. **(ремонт) отсутствующие 8 ключей восстанавливаются.** Пустые `overrides` целевого → `apply_chat_settings_seed` → все 8 ключей записаны, включая `limits.chat_global_key_budget_requests == -1`; retention `0`; `meta.chat_settings_seed_version == 1`.
2. **(идемпотентность) повторный прогон — no-op.** Второй вызов → `skipped`, `set_chat_params` **не** вызван, history-строк нет.
3. **(immutability) ручные правки не трутся.** Предзаполнить чужим ключом (`limits.chat_mood_enabled`) и одним seed-ключом с ручным значением → plain-сид восстанавливает только absent, ручные не меняет.
4. **(break-glass) `--force` перезаписывает present seed-ключ** — тест документирует, что это осознанный гейт, а не дефолт.
5. **(разрыв петли, T-2372)** Прогнать F20-merge (`new_overrides = value_overrides ∪ patch`) на 8-key наборе → набор цел; затем сид → no-op.
6. **(история/аудит)** `_FakeSeedConn` отдаёт строки `chat_lore_history`: old c 8 ключами → new c 1 ключом ⇒ `wipe_suspected=True`, `dropped ⊇ seed-ключей`; детектор классифицирует `added/dropped/seed_version`.
7. **(read-only)** Аудит-команда на fake-PG: собираются **только** `SELECT`; `set_chat_params`/`NOTIFY` не вызываются.
8. **(R17)** Вывод аудита не содержит сырого `key_value`; для chat_keys — только `{configured,last4}`; в JSONL нет полных `new_value`.
9. **(CLI connect)** `_cmd_apply_chat_overrides` вызывает `pg.connect()`; при `pool is None` — non-zero exit (monkeypatch `PgDatabase`).
10. **(Δ=0)** Грепы: нет новых DDL-строк в `services/pg_db.py`; `services/param_catalog.py` не менялся.

**Тест-гейт:** полный `pytest` — `0 failed`; `git diff --check` — чисто.

### 6.2. Read-only проверка в PG (T-2375, @DevOps на проде; локально PG нет)
Строго `SELECT` (без записи). Подтвердить до ремонта и после.

```sql
-- (1) фактическое состояние целевого чата
SELECT chat_id, updated_at,
       jsonb_object_keys(chat_params->'overrides') AS override_key,
       chat_params->'meta'->>'chat_settings_seed_version' AS seed_version,
       chat_params->'keys'->>'allow_global' AS allow_global_present  -- presence
FROM chat_profiles
WHERE chat_id = -1002661910336;

-- (1b) только отсутствующие/лишние seed-ключи (классификация absent/different)
WITH seed(k) AS (VALUES
  ('limits.import_history_retention_days'),('limits.chat_global_key_budget_requests'),
  ('limits.chat_global_key_budget_tokens'),('limits.worker_daily_llm_calls_per_chat'),
  ('limits.worker_daily_llm_tokens_per_chat'),('limits.chat_global_context_max_tokens'),
  ('limits.chat_thread_max_tokens'),('limits.chat_context_budget_tokens'))
SELECT s.k, (cp.chat_params->'overrides' ? s.k) AS present,
       cp.chat_params->'overrides'->>s.k AS value
FROM seed s
LEFT JOIN chat_profiles cp ON cp.chat_id = -1002661910336
ORDER BY s.k;

-- (2) таймлайн правок chat_params (момент вайпа)
SELECT id, created_at, changed_by,
       jsonb_array_length(COALESCE((old_value::jsonb->'overrides'),'{}'::jsonb)
                          ::jsonb) AS old_n,           -- осторожно: старые строки могут быть не-JSON
       new_value
FROM chat_lore_history
WHERE chat_id = -1002661910336 AND field = 'chat_params'
ORDER BY created_at DESC, id DESC
LIMIT 200;

-- (3) chat_keys — ТОЛЬКО presence/last4, без key_value
SELECT key_name, key_hint, right(key_value, 4) AS last4
FROM chat_keys WHERE chat_id = -1002661910336;

-- (4) счётчики (числа, R17-safe)
SELECT metric, used, day FROM chat_usage
 WHERE chat_id = -1002661910336 ORDER BY day DESC LIMIT 30;
SELECT day, scope, metric, used FROM worker_budget
 WHERE scope = 'chat:-1002661910336' ORDER BY day DESC LIMIT 30;

-- (5) глобальный слой лимитов (числа)
SELECT key, value FROM bot_settings WHERE key IN (
  'limits.import_history_retention_days','limits.chat_global_key_budget_requests',
  'limits.chat_global_key_budget_tokens','limits.worker_daily_llm_calls_per_chat',
  'limits.worker_daily_llm_tokens_per_chat','limits.chat_global_context_max_tokens',
  'limits.chat_thread_max_tokens','limits.chat_context_budget_tokens');
```

> ⚠️ В (2) `old_value`/`new_value` — свободный TEXT; старые/не-JSON строки оборачивать в `try`/`CASE` (в CLI-аудите — `json.loads` в try/except, не падать на мусоре).

### 6.3. Порядок прод-проверки (T-2375)
1. `audit-chat-overrides` (dry, read-only) → зафиксировать классификацию 8 ключей и найденный вайп.
2. `apply-chat-overrides` (**plain**, без `--force`) → `applied` содержит 8 ключей (или `skipped`, если уже ок).
3. Повторный `apply-chat-overrides` → `skipped` (идемпотентность).
4. `audit-chat-overrides` → все 8 `ok`, `-1` на месте; `flags.chat_context_budgets_enabled` не изменился.
5. UI-save любого одного ключа → набор цел (F20); сид-рестарт → no-op.

---

## 7. Риски и митигации

| # | Риск | Уровень | Митигация |
|---|---|---|---|
| R1 | Ремонт до фикса F20 → снова затрётся | Critical | Порядок **F20 → F22**; F20 уже в HEAD `070f31c`; проверка §6.3.5 |
| R2 | `--force` затирает намеренный выбор админа | High | Дефолт — **plain-сид**; `--force` только по Human Gate после read-only аудита (`different`-ключи); `manual-overrides-immutable` |
| R3 | Секреты/приватные значения в JSONL/отчёте | Medium/High | В вывод только имена/числа/`{configured,last4}`; сырые `key_value`/полные JSON не печатаются; JSONL в gitignored `var/` |
| R4 | Конфликт с `scripts/backfill_104_chat_flags.py` | Medium | F22 флаги не пишет; один write-path (сид); backfill не меняется |
| R5 | **CLI no-op** (дефект `pg.init` без connect) → ремонт «выполнен», но данных нет | High | §3.2: `pg.connect()` + fail-loud non-zero; тест §6.1.9 |
| R6 | Ошибка сверки (чужой тип/мусор в значении) | Low | Классификация через каталог/`normalize_value`; `json.loads` в try/except |
| R7 | Лишний history-шум от ремонта | Low | plain-сид пишет history только при реальном patch; повтор — `skipped` |

---

## 8. Критерии приёмки

1. В `overrides` целевого чата восстановлены **все 8** seed-значений из `config/chat_settings_seed.json:11-20` (в т.ч. `-1` = безлимит), подтверждено read-only аудитом.
2. Ремонт **идемпотентен** (повторный прогон — `skipped`, без history/NOTIFY) и **не перетирает** ручные overrides.
3. `manage.py apply-chat-overrides` реально работает (connect + fail-loud); CLI-путь не no-op.
4. Аудит-команда read-only воспроизводима; таймлайн `chat_lore_history` показывает момент/причину стирания; секреты не утекли (R17/R18).
5. Разграничение `flags.chat_context_budgets_enabled` ↔ master-тумблер зафиксировано и покрыто тестом; `backfill_104` не сломан.
6. После ремонта UI-save сохраняет набор (зависит от F20), сид-рестарт — no-op.
7. Полный `pytest` — `0 failed`; `git diff --check` — чисто.
8. **Δ DDL = 0, Δ каталога = 0.**

---

## 9. Откат

- **Данные:** plain-сид идемпотентен; откат ремонта — ручное удаление восстановленных ключей через `DELETE /api/config/chat/{key}` (по одному) либо `git revert` — данные не мигрируют, обратной миграции нет.
- **Код:** `git revert` коммита F22 (аудит-команда + connect-fix) возвращает прежнее (no-op) поведение CLI; runtime/бот не затронут.
- Побочный эффект отката: CLI-ремонт снова становится no-op (приемлемо как аварийная мера — остаётся рестарт бота с авто-сидом).

---

## 10. Feature flag / Progressive delivery

- **Feature flag не вводится** — это ops/ремонт данных, не rollout-переключатель (T-2369). Kill-switch — откат (§9).
- Progressive delivery — по данным: сначала read-only аудит, затем ремонт целевого чата, затем (при желании владельца) остальные чаты — тем же plain-сидом.

---

## 11. Вне scope

- **F21** `flags.budgets_enabled` (master-тумблер) — реализация; F22 даёт только разграничение.
- **F23** — пин-тесты каталога/TAB_RULES/menu-freeze.
- Ремонт merge прав в `web/api/access.py:443-447` (наблюдение F20 §12) — отдельный follow-up.
- Изменение политики `enforce`/`version`/`force` сида — **нет** (AMEND только уточняет, что `present=False` = штатный ремонт, а `force` — исключение).

---

## 12. Ссылки

- `plans/features/budget-data-repair-round1024/tasks.md` (T-2369…T-2375)
- `plans/features/budget-overrides-merge-fix-round1024/spec.md`, `ADR-1024-21.md` (F20, предпосылка)
- `plans/features/budget-global-toggle-round1024/tasks.md` (F21, разграничение)
- `plans/archive/budget-settings-section/adr-1019-8-per-chat-limits-and-seed.md` (AMEND D4)
- `services/chat_settings_seed.py`, `config/chat_settings_seed.json`, `manage.py`, `services/chat_params.py`, `services/chat_lore_store.py`, `services/chat_keys.py`, `services/direct_chat_service.py:1139-1162`, `scripts/backfill_104_chat_flags.py`, `services/pg_db.py:89-102,204-208`
- `plans/current_task.md:404`; `plans/backlog.md` §10.24, F22; `plans/metrics.md:299` (follow-up CLI no-op)
