# Фича F2 — `direct-chat-budget-unlimited` (Безлимит по чату без хардкода: sentinel вместо «0 = запрет», устранение ложного sandbox, фикс бюджета direct)

> **Статус: ✅ РЕАЛИЗОВАНО (Батч B, @Builder, 15.09.2026).** T-1789/T-1853 (@Architect) ✅; T-1790…T-1797 ✅; T-1854/T-1855 ✅. Остаётся ревью-гейт **T-1798** (@Reviewer/@PM) и прод-применение безлимита (сид) (`-1002661910336`) **сидом F3 (T-1859)** + @DevOps. **В Батче B `services/chat_settings_seed.py` НЕ создаётся** — он принадлежит F3 (T-1859); здесь только механизм per-chat override.
> **Spec/ADR:** создаёт @Architect — `spec.md` + **ADR-1019-2** (**SUPERSEDE/AMEND F-15** раунда 10.3 `direct-sandbox-budget-investigation`).
> **Раунд:** 10.19 (UPD2, `plans/current_task.md:130-175`). **Нумерация:** T-1789…T-1798.
> **Тип:** backend (`services/chat_usage.py`, `services/llm_client.py`, `services/direct_chat_service.py`, `services/chat_params.py`, `web/api/*`). **Приоритет:** **P0** (бот уходит в sandbox-заглушки, прод-блокер общения).
> **Зависимости:** связана с **F3** (`budget-settings-section`, UI-тумблер безлимита) — F2 даёт механизм, F3 — интерфейс; порядок **F2 → F3**. **Конфликт файлов:** `services/chat_usage.py` (F3/F4 читают), `services/param_catalog.py` (F3/F4).
> **ТЗ:** UPD2 **п.1** (`plans/current_task.md:131-132`) + чекап (строки 162).
> **Baseline:** HEAD `fd6acc7`; pytest **6139 passed / 0 failed**; каталог **436/406/411/90/88/19**; SQLite **v10**; APP_VERSION 2.57.0.

## 0. Цель

Дать возможность выставлять **безлимит по конкретному чату** (не хардкодить id) и починить ложный sandbox-путь: бот в чате `-1002661910336` отвечает заглушкой «у чата нет своего ключа, а глобальный недоступен или исчерпан» при `used_calls=25 / limit_calls=25`, при этом в «Сводке» лимиты далеки от исчерпания.

**Требуется (UPD2 п.1):**
- Чату `-1002661910336` — **безлимит** (или существенно поднятые лимиты), **без хардкода** в коде (через БД/hot-config/UI).
- Механизм «безлимит» — не «0» (текущая семантика `0 = запрет`), а явный sentinel/флаг.
- Разобраться, почему sandbox сработал при непревышенных лимитах (ложный путь).
- Простыми словами объяснить, как работают бюджеты фона и интеллекта и почему выбраны текущие значения (описание — в F3/spec).

## 1. Доказательства / карта кода (HEAD `fd6acc7`)

- **Симптом (лог):** `WARNING | services.direct_chat_service | [direct] no key — sandbox answer | chat=-1002661910336 | reason=budget | details={'resolve_path': 'budget', 'used_calls': 25, 'limit_calls': 25, 'used_tokens': 699, 'limit_tokens': 100000, 'allow_global': True}`.
- `services/llm_client.py:361-426` — `_resolve_api_key_and_source`: свой ключ → `allow_global=false` → `budget_exceeded` (reason `budget`) → глобальный ключ. Budget-ветка `:396-418` формирует `details`.
- `services/chat_usage.py:100-113` — `budget_exceeded`: **любой лимит ≤ 0 = запрет** (`:105-106`); иначе `used_calls >= req_limit` или `used_tokens + estimate > tok_limit`.
- `services/chat_usage.py:53-60` — дефолты `_budget_limit_requests=25`, `_budget_limit_tokens=100000` (`hot.get`).
- `services/chat_usage.py:121-125` — `report_call` (1 вызов + токены на конец LLM-вызова); `services/chat_usage.py:22-25` — ключи/таймзона (`WORKER_BUDGET_TZ`, `Asia/Yekaterinburg`).
- `services/direct_chat_service.py:624-638` — sandbox-ответ при `NoApiKeyForChat` (`content.no_key_reply`).
- `services/pg_db.py:181` — таблица `chat_usage (chat_id, day, metric, used, PK(chat_id, day, metric))`.
- `config/settings.py:481-484` — `CHAT_GLOBAL_KEY_BUDGET_TOKENS=100000`, `CHAT_GLOBAL_KEY_BUDGET_REQUESTS=25`.
- `services/param_catalog.py:1232-1240` — REGISTRY-ключи `limits.chat_global_key_budget_*` (группа `limits_chat` → вкладка `TAB_MOD_DIRECT`), в описаниях зафиксировано «0 — общий ключ чату запрещён».
- **Смежный контур «фон/Сводка»:** `services/oversight.py:128-230` (bar-графики читают `worker_budget.get_usage(f"chat:{id}")`); `services/worker_budget.py:210-217` (`limits.worker_daily_llm_calls_per_chat=35`); `services/param_catalog.py:1244-1267` (группа `limits_worker` → вкладка `TAB_MOD_CHECKUP`).

## 2. Требования

- [ ] Ввести **sentinel/флаг «безлимит»** (например, выделенный per-chat ключ или спец-значение лимита) вместо семантики «0 = запрет»; «0» остаётся запретом либо меняется по решению ADR (human-gate (c)).
- [ ] Чату `-1002661910336` выставить безлимит **данными** (БД/hot-config/UI), **не хардкодом** id в коде.
- [ ] `budget_exceeded`/`used_today`/`key_status` учитывают sentinel безлимита; details-снапшот отражает фактический режим (например, `unlimited: true`).
- [ ] Устранить **ложный sandbox**: при наличии валидного доступа (глобальный ключ, лимит не исчерпан) `NoApiKeyForChat(reason=budget)` не должен возникать; повторная проверка BYOK-фоллбэка сохранена.
- [ ] Порядок резолва ключа не менять (свой → запрет → бюджет → фоллбэк свой → глобал); sandbox — только когда доступа реально нет.
- [ ] Разграничение контуров: лимиты **direct-чата** (`chat_usage`) и **фон-воркеров** (`worker_budget`) — независимы; правка одного не ломает другой.
- [ ] R17: `details`/логи без секретов; ключи только `{configured}`-подобно.
- [ ] Тесты: безлимит (calls/tokens), «0 = запрет», per-chat override, отсутствие sandbox при валидном доступе, изоляция от `worker_budget`.

## 3. Constraints (инварианты раунда)

- **R17**, **R16** (Аддитивные поля — только добавление).
- **Каталог:** любые изменения ключей/описаний — **Δ** через **human-gate (c)** (санкция владельца). Механизм можно реализовать без Δ, если использовать существующие per-chat ключи/БД.
- **Порядок роутеров `bot.py` не менять**; `media/`/`.env` **не трогать**.
- **DDL:** санкционирован (project.md §Политика DDL), но новые колонки не обязательны — предпочтительно per-chat hot-config/`chat_params`; если DDL — идемпотентно + обратный путь.
- **Ревью-гейты:** полный `pytest` 0 регрессий; `git diff --check`; русские conventional commits.

## 4. Зависимости / порядок

- **Вверх:** T-1789 (@Architect, ADR-1019-2) — обязателен.
- **Вниз:** **F3** (UI-раздел «Бюджеты» + тумблер безлимита) опирается на механизм F2.
- **Порядок:** **F2 → F3**. F2 делит `services/chat_usage.py` с F4 — согласовать чтение лимитов.

## 5. Definition of Done

- [ ] Безлимит работает: чат отвечает через глобальный ключ без sandbox-заглушки при превышении 25 вызовов.
- [ ] Чату `-1002661910336` безлимит выставлен через данные/UI (в коде нет хардкода id).
- [ ] Ложный `reason=budget` при доступном ключе не воспроизводится (лог/тест).
- [ ] Семантика `0` и безлимит зафиксированы в ADR/доках; конфликт F-15 (10.3) снят/помечен SUPERSEDE/AMEND.
- [ ] Полный `pytest` **0 failed**; R17-скан чист; каталог-Δ — согласован.

## 6. Чек-лист задач

- [x] **T-1789 (@Architect, гейт):** `spec.md` + **ADR-1019-2** — семантика безлимита (sentinel vs «0»), источник резолва (per-chat DB → global DB → env), контракт `key_status`/details, **SUPERSEDE/AMEND F-15** («0 = запрет»), граница с F3; ответ на human-gate (c). + итерация 2 (T-1853, ADR-1019-8).
- [x] **T-1790 (@Builder):** механизм безлимита в `services/chat_usage.py` (`budget_exceeded`, чтение лимитов) — sentinel (без хардкода чата); «0» по решению ADR.
- [x] **T-1791 (@Builder):** резолв per-chat признака безлимита (DB/`chat_params`) и проброс в `_resolve_api_key_and_source`/`key_status` (аддитивно, R16). — `_limit_with_source` → `resolve_setting_with_source` (chat→global→default) + `budget_snapshot`/`source`.
- [x] **T-1792 (@Builder):** выставить безлимит чату `-1002661910336` через данные/UI (не код); операция идемпотентна и документирована (как включить/выключить). — механизм per-chat override готов (spec §4.4, `set_chat_params`); **прод-применение (целевой чат) — сид F3 (T-1859)**, id в коде отсутствует.
- [x] **T-1793 (@Builder):** устранить ложный sandbox-путь: проверить ветку `reason=budget`, при валидном глобальном доступе не уходить в `no_key_reply`; сохранить BYOK-фоллбэк. — `budget_snapshot` (инвариант `exceeded_metric`, ERROR + fail-open) + details из снимка.
- [x] **T-1794 (@Builder):** тесты — безлимит calls/tokens; «0 = запрет»; per-chat override; sandbox только при реальном отсутствии доступа; `details` без секретов. — `tests/test_budget_unlimited_round1019.py` + обновлён `test_chat_keys.py`.
- [x] **T-1795 (@Builder):** изоляция контуров — тест/регресс, что правки `chat_usage` не меняют `worker_budget` (`limits.worker_daily_*`). — `TestContourIsolation`.
- [x] **T-1796 (@Builder):** R17-ревизия логов (`[direct] no key — sandbox answer`, details) — без токенов/ключей.
- [x] **T-1797 (@Builder):** гейты — полный `pytest` 0 failed; каталог-Δ зафиксирован (0 или санкционированный); `git diff --check` clean.
- [ ] **T-1798 (@Reviewer + @PM, гейт):** сверка DoD; подтверждение отсутствия хардкода id; согласованность ADR-1019-2 ↔ код; проверка снятия конфликта F-15.

## 7. Риски / ADR-конфликты

| # | Риск / конфликт | Мера |
|---|---|---|
| R1 | **F-15 (раунд 10.3)** постановил: дефолты 25/100k **не меняются**, «0 = запрет», sandbox — штатно | **SUPERSEDE/AMEND** (ADR-1019-2): владелец изменил требование (безлимит по чату + видимые бюджеты) |
| R2 | «0 = запрет» конфликтует с интуитивным «0 = безлимит» | Явный sentinel/флаг; семантику фиксирует ADR; human-gate (c) |
| R3 | Хардкод чата `-1002661910336` в коде | Запрещено: только данные/hot-config/UI; проверка @Reviewer |
| R4 | Ложный sandbox может быть симптомом другого пути резолва | T-1793 диагностика ветки `budget_exceeded` + details-лог; тест на валидный доступ |
| R5 | Изменение `chat_usage` ломает `worker_budget`-бары «Сводки» | T-1795 изоляция; F3 чинит отображение обоих контуров аддитивно |
| R6 | Δ каталога без санкции | Human-gate (c); реализация возможна без Δ |

**ADR:** требуется новый **ADR-1019-2** (SUPERSEDE/AMEND F-15 10.3).

## 8. Feature flag / progressive delivery

- **Feature flag:** не требуется (правка политики бюджета). Возможен per-chat флаг «безлимит» как механизм (не rollout-флаг).
- **Rollback:** `git revert` + снятие per-chat безлимита (данные/hot-config) → возврат к лимитам 25/100k.
- **Progressive delivery:** применимо поэтапно на уровне данных: сначала тестовый чат `-1002661910336` → проверка → (опционально) другие чаты по решению владельца.

## 9. Handoff / деплой

`@Orchestrator` — план F2 готов. Spec/ADR — T-1789 (@Architect). Реализация — T-1790…T-1797 (@Builder). **Деплой (SSH + данные/hot-config безлимита + рестарт + live-проверка ответа бота в `-1002661910336`) — @DevOps. Пароль/секреты в репозитории НЕ хранятся.**

## 10. 🔴 Итерация 2 — UPD3 (15.09.2026): мультичатовость вместо глобального хардкода

> **Источник:** `plans/current_task.md:178-216` (UPD3 п.2-5). **ADR:** `../budget-settings-section/adr-1019-8-per-chat-limits-and-seed.md`. **Обновлены:** `spec.md` §3.1/§4.5/§5/§9, `adr-1019-2` D5/D8.

- [x] **T-1853 (@Architect, гейт) — ✅ DONE (Step 2):** ADR-1019-8 + обновление spec/ADR F2/F3/F4/F7 (sentinel-таблица, сид настроек чатов, guard, изоляция, дефолты).
- [x] **T-1854 (@Builder):** `services/budget_limits.py` — хелперы `budget_state/is_unlimited/is_forbidden` (+ `context_state`/`retention_state` — изоляция семейств); per-chat резолв `chat_usage` (`resolve_setting_with_source`); `0=запрет`, `−1=безлимит`.
- [x] **T-1855 (@Builder):** консервативные дефолты (`CHAT_GLOBAL_KEY_BUDGET_REQUESTS=100`, `…_TOKENS=500 000`; фон per-chat `60`/`300 000`) + тексты каталога с sentinel-пояснениями; **не** делать глобальный безлимит. Каталог-Δ = 0.
- [ ] **Зависимость:** безлимит целевого чата `-1002661910336` — **сидом** (F3 T-1859), не сменой дефолта.

## 11. Ревью-фиксы Батча B (D-1…D-5, @Builder, 15.09.2026)

> Отклонение @Reviewer по Батчу B; санкция на sentinel/резолв в фон-контуре принята (UPD3 п.3: «Фоновый бюджет: −1 = Безлимит»).

- [x] **D-1/D-2 (`services/worker_budget.py`):** sentinel реализован в фон-контуре — `consume`/`allowed_workers`/`_metric_limit` используют `services/budget_limits.py` (`0`=запрет, `<0`=безлимит с учётом расхода, `>0`=cap); `_metric_limit` стал **async** и резолвит лимиты **per-chat** (`worker_settings.resolve_setting_cached`, default = `settings.WORKER_DAILY_LLM_*_PER_CHAT`) → новые дефолты 60/300 000 действуют, per-chat override F3 доходит до фона. Тесты: `TestWorkerBudgetSentinel` + `TestContourIsolation`.
- [x] **D-3 (`plans/ARCHITECTURE.md`):** §40 (раунд 10.19/F2) + точечные AMEND в §22 (direct/фон-бюджеты) и §23 (F-15 sandbox).
- [x] **D-4 (`services/chat_usage.py`):** fail-open ветка `budget_snapshot` пробрасывает вычисленный `forbidden` и `source=_aggregate_source(...)` вместо хардкода `False`/`"default"`. Тесты: `test_failopen_keeps_forbidden_visible`, `test_failopen_usage_unavailable`.
- [x] **D-5 (`services/llm_client.py`):** единый снимок — `budget_snapshot` вызывается один раз (и решение, и `details`); устранён двойной PG-раундтрип/TOCTOU. Тесты `test_chat_keys.py` переведены на мок снимка.
- [x] **I-1/I-2:** чек-лист T-1853 приведён в порядок; в `spec.md` §6 тесты сида настроек явно помечены как F3.
