# Аудит раунда 10.24 — F22 `budget-data-repair-round1024` (шаг 5, @Reviewer)

- **Коммит:** `cbc4f98` (HEAD) · База: `cbc4f98^`
- **Спека/ADR/задачи:** `spec.md`, `ADR-1024-23.md`, `tasks.md` (T-2369…T-2375)
- **ТЗ:** `plans/current_task.md:404` (сброс бюджетов целевого чата `-1002661910336`, не применяются значения в миниаппе). Секреты не цитируются (R17/R18).
- **Артефакты коммита:** 2 файла, `manage.py` (+466/−4), `tests/test_budget_data_repair_round1024.py` (+486). Δ DDL = 0, Δ каталога = 0, `config/chat_settings_seed.json` / `services/chat_settings_seed.py` / `scripts/backfill_104_chat_flags.py` не тронуты.
- **Прогоны:** F22-файл — 17 passed; полный `pytest -q` — **7556 passed, 0 failed** (0:01:48); `git diff --check cbc4f98^ cbc4f98` — чисто.

> ⚠️ **Оговорка к доказательной базе:** полный прогон выполнен на **грязном рабочем дереве** — вне коммита `cbc4f98` не закоммичены правки F21 (`services/budget_gate.py`, `services/worker_budget.py`, `tests/test_budget_global_toggle_round1024.py` +4 теста). Число `7556` относится к рабочему дереву, а не к самому `cbc4f98` (в коммите тестов на 4 меньше). Ревью самого кода F22 от этого не меняется, но заявленный «pytest 7556» **не подтверждён изоляцией на коммите**.

**Статус: Changes Requested**

Итог: ремонтный путь через штатный `apply_chat_settings_seed(force=False)` собран верно (идемпотентность, `manual-overrides-immutable`, break-glass, разрыв петли F20) и read-only-аудит в целом соответствует спеке. **Но два заявленных контракта не выполнены:** (1) аудит `flags.chat_context_budgets_enabled` в CLI **физически не резолвит per-chat значение** — `ChatParamsCache` инициализируется только в `bot.py`, поэтому `resolve_setting_with_source` в CLI всегда возвращает `(None, 'error')`, а тест-заглушка это прячет; (2) **«тихий no-op» не добит** — при отсутствующем/битом `config/chat_settings_seed.json` и `apply-chat-overrides`, и `audit-chat-overrides` печатают пустой успех и выходят с кодом 0 (даже под `--strict`). Именно этот класс отказа фича обязана устранить. Дополнительно: удалён `pg.init(seed_settings=False)`, хотя спека требует «connect **до** init».

---

## Findings

### [Severity: High] Аудит флага `flags.chat_context_budgets_enabled` в CLI не работает — всегда `(None, 'error')`

- **Файл:** `manage.py:1177-1184` (`_collect_chat_overrides_audit`, блок `context_flag`); тест-заглушка — `tests/test_budget_data_repair_round1024.py:246-252` (`_stub_flag`).
- **Проблема:** аудит вызывает `worker_settings.resolve_setting_with_source(...)`. Этот резолвер читает chat-слой через `ChatParamsCache`, но `_chat_params_cache` — процесс-глобал, который выставляется **только** в `bot.py:971-972`. В процессе CLI (`manage.py`) он `None` → `_chat_root` возвращает `({}, False)` → `_resolve_full` (services/worker_settings.py:100-115) возвращает **значение глобального слоя/дефолт и `source='error'`**. Подтверждено в venv: `cache is None: True` → `resolve_setting_with_source('flags.chat_context_budgets_enabled', chat_id=-1002661910336, default=None)` → `(None, 'error')`. При этом сам чат-оверрайд (`flags.chat_context_budgets_enabled=false` для целевого, поставлен `backfill_104`) лежит рядом — в `chat_params`, который аудит уже вычитал в `overrides`.
- **Почему это важно:** спека §3.3.6 требует «Резолв `flags.chat_context_budgets_enabled` через `worker_settings.resolve_setting_with_source` → `{value, source}`», а процедура §6.3.4 — «`flags.chat_context_budgets_enabled` не изменился». В реальном CLI-прогоне аудит покажет `value=None source=error` вместо фактического per-chat значения, т.е. **оператор не сможет подтвердить границу с master-тумблером F21**. Тест `_stub_flag` подменяет резолвер и **скрывает** дефект — это ложная гарантия: зелёный тест не проверяет ни одну реальную ветку.
- **Обязательный фикс:** не опираться на bot-only-глобал в CLI. Резолвить флаг из уже собранных данных: `overrides.get("flags.chat_context_budgets_enabled")` (source `'chat'`) → иначе из `global_limits`/`bot_settings` (source `'global'`) → иначе `default`; либо явно инициализировать `ChatParamsCache`/`ConfigCache` в `_run()` аудита. Тест `_stub_flag` убрать и добавить кейс «чат-оверрайд `false` → `context_flag == {'value': False, 'source': 'chat'}`» на реальном резолвере (достаточно fake-PG с chat-слоем, без подмены `resolve_setting_with_source`).

### [Severity: High] «Тихий no-op» остался: при отсутствующем/битом сиде обе команды рапортуют успех с кодом 0

- **Файлы:** `manage.py:879-900` (`_cmd_apply_chat_overrides`), `manage.py:1078-1079` + `1188-1193` (`_load_seed_ref` / `_audit_drift`); корень — `services/chat_settings_seed.py:81-84, 94-100` (`load_chat_settings_seed` fail-open → `{}`).
- **Проблема:**
  - `apply-chat-overrides`: `load_chat_settings_seed` при недоступном/битом JSON возвращает `{}`; `entries=[]`; `apply_chat_settings_seed` отдаёт `{"applied": [], "skipped": [], "errors": []}`. CLI печатает `applied=0 skipped=0 errors=0` и **`return 0`** — ровно та мина, которую F22 обязан был убрать (spec §2.1, §3.2, R5, критерий 3 «CLI-путь не no-op»). Отличие от исходного дефекта (pool=None) только в причине — итог тот же: «выполнено», данных нет.
  - `audit-chat-overrides`: при том же `{}` `_load_seed_ref` даёт `reference={}` → `reference_keys=0`, `classification=[]`, `wipe_detected=False` → `_audit_drift` = `False` → **exit 0 даже под `--strict`**. Аудит молча выдаёт «всё ок, дрейфа нет», хотя эталон сида не прочитан.
- **Почему это важно:** фича создавалась именно для устранения скрытого no-op (§2.1/ADR D4) и для достоверного аудита (§3.3). Если деплой/копирование конфига не принесло `config/chat_settings_seed.json`, ремонт «успешен» и аудит «чист» — владелец остаётся с нулевыми лимитами и без сигнала. Ни один тест этот путь не покрывает (§6.1.9 проверяет только `pool is None`).
- **Обязательный фикс:** различать «сид нечитаем/пуст» и «нечего делать». Использовать `_seed_snapshot`/`enforced_eternal_chat_ids_checked` (флаг `ok`) в CLI: при `ok=False` либо пустом `chats` — печатать ошибку в stderr и `return 1` в `apply-chat-overrides`; в `audit-chat-overrides` — считать это дрейфом/ошибкой (при `--strict` гарантированно `return 1`). Добавить тесты: нечитаемый/пустой сид → non-zero, ненулевой stderr.

### [Severity: Medium] Удалён `pg.init(seed_settings=False)` — отклонение от спеки §3.2.1/§5.1 и ADR D4

- **Файл:** `manage.py:865-886` (`_cmd_apply_chat_overrides`).
- **Проблема:** контракт требует «вызвать `await pg.connect()` **до** `pg.init(seed_settings=False)`» (spec §3.2.1, §5.1: «добавить `await pg.connect()` **перед** `pg.init(...)`»; ADR-1024-23 D4: «`pg.connect()` до `pg.init(...)`»). В реализации строка `await pg.init(seed_settings=False)` **удалена целиком** — оставлен только `connect()`. Это «connect вместо init», а не «connect до init». Тест `TestApplyCliFailLoud` (`tests/...:400-427`) вдобавок вшивает этот сдвиг: `init` объявлен как `raise AssertionError(...)`.
- **Почему это важно:** CLI больше не гарантирует наличие схемы (DDL)/ролей/админов. На здоровом проде таблицы есть, поэтому фактический ущерб мал, но формальный контракт нарушен, а поведение на неполной БД меняется (падение вместо self-provision). Молчаливая переинтерпретация контракта недопустима.
- **Обязательный фикс:** вызвать `await pg.init(seed_settings=False)` после успешного `connect()` и до `apply_chat_settings_seed`; привести тест к «connect → init → apply». Если `init` в CLI сознательно не нужен — оформить AMEND (spec §3.2/§5.1 + ADR D4) явным решением, а не расхождением в коде.

### [Severity: Medium] R17: в stdout/JSONL печатается **текущее** значение override, а не только seed-числа

- **Файлы:** `manage.py:1272-1274` (`print(f"  [{status}] {key}{suffix}")`, `value={item['value']}`) и `manage.py:1200-1204` (JSONL-`summary` включает `classification` с `value`).
- **Проблема:** спека §3.3 (R17-редакция) допускает в вывод только «имена ключей, счётчики, seed-значения (числа `0/-1`) и `{configured,last4}`». Код для классов `ok`/`different` печатает `overrides[key]` — фактическое текущее значение вычитанного из PG `overrides`. Для класса `different` это может быть произвольное значение (в т.ч. строковое), а не числовое seed-значение. То же уходит в JSONL-`summary`.
- **Почему это важно:** R17/R18 объявлены не-negotiable. Пусть seed-ключи — `limits.*` и обычно числовые, но корректность вывода не должна зависеть от «обычно»: испорченные/подменённые данные в `overrides` протекут в stdout и в файл на диске.
- **Обязательный фикс:** печатать только эталонное seed-значение (`reference[key]`) или вовсе не печатать значение, ограничившись классом. Для JSONL — исключить `value` из `classification` (или маскировать не-числовые). Добавить тест «`different`-значение — строка-маркер → её нет в stdout/JSONL».

### [Severity: Medium] Тесты частично тавтологичны и не покрывают заявленные контракты

- **Файл:** `tests/test_budget_data_repair_round1024.py`.
- **Проблема:**
  1. `test_f20_merge_keeps_set_then_seed_noop` (`:167-180`) **сам** исполняет `new_overrides = dict(value_overrides); new_overrides.update(patch)` и проверяет `set(new_overrides) == set(SEED_KEYS)`. Это тест семантики `dict.update`, а не F20-merge из `web/api/routes.py`. Реальная функция F20 не вызывается — регресс в ней этот тест не поймает.
  2. Нет теста `--strict` → non-zero при дрейфе (контракт §5.1).
  3. Нет теста, что `context_flag` в аудите отражает **реальный** резолвер (см. High-1): `_stub_flag` подменяет функцию и маскирует дефект.
  4. Нет пин-теста Δ DDL = 0 / Δ каталога = 0 (§6.1.10) — «Δ=0» подтверждён только отсутствием файлов в коммите, без автопроверки.
- **Почему это важно:** тесты дают ложную уверенность именно там, где спека требует гарантий (F20-петля, strict, граница флага, Δ=0).
- **Обязательный фикс:** вызывать реальный F20-merge-путь (или его выделенную функцию) вместо инлайн-реплики; добавить тесты `--strict`, реального `context_flag`, Δ DDL/каталога.

### [Severity: Low] Широкие `except` маскируют отказ секций, `_audit_drift` их игнорирует

- **Файл:** `manage.py:1128-1175` (chat_keys/chat_usage/worker_budget/bot_settings) и `_audit_drift` `manage.py:1188-1193`.
- **Проблема:** падение отдельного `SELECT` пишется лишь в `warnings`; `_audit_drift` учитывает только `classification` и `wipe`. Под `--strict` можно получить exit 0 при фактически неполном аудите (например, `chat_keys` не прочитан — а это R17-чувствительная секция).
- **Почему это важно:** «аудит прошёл» не должно означать «половину не собрали». Некритично, но подрывает воспроизводимость (критерий 4).
- **Обязательный фикс:** при `--strict` трактовать наличие `warnings` секций как ошибку/дрейф (или отдельный ненулевой код), либо явно печатать «аудит неполный».

---

## Контракт: чекбоксы / инварианты / тесты

### spec §3.1 ремонт (T-2370)
- [x] Ремонт тем же `apply_chat_settings_seed(force=False)`, без второго write-path (`manage.py` новый write-path не вводит).
- [x] Идемпотентность: повторный прогон → `skipped`, без `set_chat_params`/history (`TestRepair.test_repair_idempotent_no_set_no_history`).
- [x] 8 seed-ключей восстанавливаются, включая `-1` (`test_repair_restores_all_eight_keys`).
- [x] `manual-overrides-immutable`: present seed-ключ и чужой ключ сохранены (`test_plain_seed_restores_absent_and_keeps_manual`).
- [x] `--force` — break-glass (`test_force_is_break_glass`).

### spec §3.2 CLI connect-fix (T-2370)
- [x] `await pg.connect()` вызывается; при `pool is None` — stderr + exit 1 (`TestApplyCliFailLoud`, подтверждён код).
- [x] `errors` → exit 1 (`test_real_errors_are_nonzero`).
- [ ] `pg.init(seed_settings=False)` после connect — **удалён** (Medium-finding).
- [ ] Fail-loud при нечитаемом/пустом сиде — **нет** (High-finding).

### spec §3.3 read-only аудит (T-2371)
- [x] Только `SELECT`; `set_chat_params`/NOTIFY не вызываются (`TestReadOnly`, статические SQL-константы).
- [x] Классы `ok|absent|different`; `meta.chat_settings_seed_version`; `keys.allow_global` presence.
- [x] Таймлайн `chat_lore_history field='chat_params'` с `added`/`dropped`, `seed_version_old/new`, `wipe_suspected`; устойчивость к не-JSON (`test_parse_malformed_is_safe`).
- [x] `chat_keys` — только `{configured,last4}` (`TestRedaction`).
- [x] `chat_usage`/`worker_budget`/`bot_settings` — числа.
- [x] Секреты не выведены в протестированных ветвях; JSONL в gitignored `var/` (`var/` в `.gitignore:86`).
- [ ] `flags.chat_context_budgets_enabled` резолв per-chat — **не работает в CLI** (High-finding).
- [ ] R17-полнота: текущее override-значение печатается (Medium-finding).

### spec §3.4 границы F21 / backfill (T-2373)
- [x] `flags.chat_context_budgets_enabled` и `flags.budgets_enabled` — два разных ключа каталога (`param_catalog.py:826`, `:969`); тест `test_two_distinct_axes_in_catalog`.
- [x] `scripts/backfill_104_chat_flags.py` не изменён коммитом; `flags.budgets_enabled` в нём отсутствует (`test_backfill_104_targets_only_context_flag`).
- [x] F22 не пишет ни один из флагов.
- [ ] Иерархия master OFF → context off покрыта только косвенно (в F21), F22-тест поверхностен (Medium-finding про тесты).

### Инварианты
- [x] `manual-overrides-immutable` (ADR-1024-21 D3).
- [x] R16: новых внешних API-контрактов нет (только локальный CLI).
- [x] Δ DDL = 0, Δ каталога = 0 (в коммите нет `services/pg_db.py`, `services/param_catalog.py`).
- [x] F20-код (`web/api/routes.py`) и F21-код коммитом не тронуты.
- [x] `git diff --check` — чисто.

### Тесты
- [x] 17 тестов F22, не тавтологичны **в ремонтной части** (идемпотентность/immutability/break-glass/R17/read-only).
- [ ] `test_f20_merge_keeps_set_then_seed_noop` — инлайн-реплика F20 (тавтологичен).
- [ ] Нет тестов: `--strict`, реальный `context_flag`, нечитаемый/пустой сид, Δ=0.
- [x] Полный `pytest -q` — 7556 passed (оговорка: грязное дерево, см. выше).

---

## Требуемая последовательность исправлений

1. **High-1:** резолв `context_flag` без bot-only-глобала + убрать stub, добавить реальный тест.
2. **High-2:** fail-loud на нечитаемый/пустой сид в обеих командах.
3. **Medium-3:** вернуть `pg.init(seed_settings=False)` после `connect()` (либо AMEND спеки/ADR).
4. **Medium-4:** убрать вывод текущего значения override из stdout/JSONL (оставить seed-числа/класс).
5. **Medium-5:** тесты F20-merge (реальный код), `--strict`, Δ=0.
6. **Low-6:** трактовать `warnings` секций как неполный аудит под `--strict`.

После фиксов — повторный полный `pytest` **на чистом коммите** (без незакоммиченных правок F21) с фиксацией числа тестов.

---

Верни исправленную версию. Текущий код отклонён.

---
---

# Итерация 2 — повторный аудит F22 (коммит `268a8b1`)

- **Коммит:** `268a8b1` (HEAD) · База: `268a8b1^` = `cbc4f98`. Поверх него влит F21-фикс `d8e09a6` — он вне scope F22, не приписывается.
- **Объём коммита:** 2 файла — `manage.py` (+152/−?), `tests/test_budget_data_repair_round1024.py` (+314/−?). Сервисы/каталог/DDL/сид/backfill не тронуты.
- **Прогоны (чистое дерево, код на `268a8b1`):** F22-файл — **31 passed**; полный `pytest -q` — **7574 passed, 0 failed** (0:01:50); `git diff --check 268a8b1^ 268a8b1` — чисто.

**Статус: Approved**

Все findings итерации 1 (High-1, High-2, Medium-3, Medium-4, Medium-5, Low-6) закрыты **по существу**, а не косметически. Оба High подтверждены воспроизведением и реальными (не заглушечными) тестами. R17 больше не течёт, инварианты (`manual-overrides-immutable`, Δ DDL=0, Δ каталога=0, F20/F21 не тронуты) выполнены. Полный pytest прогнан **на чистом коммите** — заявленные 7574 подтверждены.

---

## Закрытие findings итерации 1

### [High-1] Резолв `flags.chat_context_budgets_enabled` в CLI — **закрыт**
- `manage.py:1107-1128` — новый `_resolve_context_flag(overrides, global_values)`; `manage.py:1242` — вызов. Резолв идёт из уже вычитанных PG-данных: chat (`overrides`) → global (`global_values` из `bot_settings`) → default (`settings.CHAT_CONTEXT_BUDGETS_ENABLED`), с `normalize_value` (строка `"false"` → `False`).
- Зависимость от bot-only `ChatParamsCache` убрана: `grep` по `manage.py` показывает `worker_settings` **только в комментарии-пояснении**.
- Заглушка `_stub_flag` удалена; добавлены реальные тесты `TestContextFlag` (`tests/...:321-349`): chat (bool и строка `"false"`), global, default. Воспроизвёл вручную — резолвер чистый, без глобала CLI.

### [High-2] Fail-loud при нечитаемом/пустом сиде — **закрыт**
- `manage.py:856-865` (`_seed_usable`) — `apply-chat-overrides` возвращает **1 + stderr** при пустом/битом сиде, **до** подключения; `manage.py:999-1019` (`_load_seed_ref` → `seed_ok`) и `manage.py:1323,1373-1376` (`seed_unusable`) — `audit-chat-overrides` возвращает **1** («аудит недостоверен»), в т.ч. **без `--strict`**.
- Тесты `TestSeedFailLoud` (`:515-543`): битый JSON и пустой `chats` для apply; битый JSON для audit — все non-zero + проверка stderr.
- Воспроизведение edge: `_seed_usable(broken)`/`_load_seed_ref(..., broken)` дают `ok=False`; целевой чат — `reference=8 keys, seed_ok=True`.

### [Medium-3] `init` после `connect` — **закрыт**
- `manage.py:903` — `await pg.init(seed_settings=False)` вызывается после успешного `connect()` и до `apply_chat_settings_seed`; `init` при отсутствии пула не вызывается (guard `pool is None` выше).
- Тест `test_connect_init_then_seed_applied` (`:448-475`) фиксирует порядок ровно: `connect` → `("init", False)` → `apply`.

### [Medium-4] R17: не течёт текущее значение override — **закрыт**
- `_classify_overrides` (`manage.py:1033-1048`) отдаёт `seed_value` = **эталон из сида**, а не текущее `overrides[key]`; CLI печатает `seed=...` (`manage.py:1337-1340`); JSONL-`summary` содержит `classification` с `seed_value` (значения сида — числа/`0/-1`, без секретов).
- Тест `test_different_value_not_printed` (`:407-426`): `overrides["...budget_tokens"] = "SECRET_MARKER_STRING"` → `different=1`, маркер **отсутствует** в stdout и JSONL. R17 подтверждён.

### [Medium-5] Тесты не тавтологичны — **закрыт**
- Петля F20 теперь на **реальном роуте**: `test_f20_route_save_then_seed_noop` (`:165-178`) использует `TestClient` + `POST /api/config` из F20-харнесса (`webapp`/`_f20_post`), проверяет сохранение seed-набора и последующий `skipped` сида.
- Добавлены `TestStrictMode` (`:545-578`): strict non-zero на дрейфе, non-strict 0, strict 0 на чистом, strict non-zero при отказе секции.
- Добавлены пины Δ=0: `DDL_STATEMENTS == 45`, `REGISTRY == 459`, `GROUPS == 98` (`:595-602`). Сверено с коммитом: `services/pg_db.py` и `services/param_catalog.py` не менялись — Δ DDL = 0, Δ каталога = 0.

### [Low-6] Неполный аудит под `--strict` — **закрыт**
- `_audit_drift` (`manage.py:1246-1255`) теперь `True` при `not seed_ok`, `wipe_detected` и **любом `warnings`**; тест `test_strict_nonzero_when_section_failed` (`:565-578`) — отказ `chat_keys` → `warnings` → strict non-zero.

---

## Контракт (итерация 2)

- Ремонт: идемпотентность ✅ · 8 ключей/`-1` ✅ · `manual-overrides-immutable` ✅ · break-glass ✅
- CLI apply: `connect → init(False) → apply` ✅ · non-zero при `pool is None` / `errors` / **нечитаемом/пустом сиде** ✅
- Аудит: read-only (только SELECT) ✅ · `ok|absent|different` ✅ · `meta`/`allow_global` presence ✅ · таймлайн/`wipe_suspected` ✅ · `{configured,last4}` ✅ · числа ✅ · **context_flag chat/global/default** ✅ · **R17 (нет текущих значений)** ✅ · `--strict` ✅
- R17/R18: сырые `key_value`, секреты и текущие значения override не попадают в stdout/JSONL ✅
- Границы/инварианты: `flags.chat_context_budgets_enabled` ↔ `flags.budgets_enabled` ✅ · backfill_104 не тронут ✅ · Δ DDL=0 / Δ каталога=0 ✅ · R16 ✅ · F20/F21 код не тронут ✅
- Тесты: F22 **31 passed**; полный **7574 passed / 0 failed** на чистом коммите ✅; `git diff --check` чисто ✅

---

## Остаточные замечания (Low, не блокеры)

1. **Аудит чата, которого нет в сиде.** `_load_seed_ref`/`_seed_usable` считают `seed_ok` по наличию **любого** чата в сиде, а не целевого. Воспроизведено: `_load_seed_ref(123456789)` → `({}, 1, True)`, `_audit_drift` → `False` → exit 0 (даже `--strict`). Для целевого `-1002661910336` не влияет (8 ключей, `seed_ok=True`). На будущее: различать «чата нет в эталоне» и «всё ок».
2. **Резолв context-флага не валидирует тип chat-значения как runtime.** При `overrides[FLAG] = "maybe"` аудит покажет `source='chat'`, тогда как реальный `resolve_setting_with_source` отбросит невалидное и уйдёт на global/default (`cp._cast_type_ok("bool", "maybe") is False`). Edge-случай порчи данных; на валидных `true/false/0/1` поведение совпадает (проверено).
3. **Doc drift:** спека §3.3.6 / ADR D5 всё ещё называют `worker_settings.resolve_setting_with_source`; реализация сознательно перешла на резолв из данных PG (санкционировано итерацией 1). Стоит обновить формулировку спеки/ADR.
4. **Δ-пины — магические константы** (45/459/98): это трипваеры «каталог/DDL не менялись», а не проверка поведения; при легитимном росте каталога в других фичах потребуют обновления.

`**Approved** @Orchestrator Код прошёл ревью. Можно двигаться дальше.`
