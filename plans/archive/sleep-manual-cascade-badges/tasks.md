# Фича F2 — `sleep-manual-cascade-badges` (Сон: безусловный manual-приоритет, каскад Сон→Глубокий сон→Личность, реактивные бейджи, аудит цепочки сна)

> **Статус: 🚧 IN PROGRESS — Батч 2 реализован** (backend+frontend+T-1767…T-1771, pytest 0 failed). **Ревью-итерация 2 (R2-1…R2-5) закрыта — см. §12.** Открыто: T-1712 (@Architect-гейт), T-1713/T-1724 (живой прогон/enable per-chat), T-1725 (@DevOps), T-1726/T-1772 (@Reviewer/@PM).
> **Step 1 @PM → Step 2 @Architect, итерация 2 после human-gate, 15.09.2026.** Реализация — T-1713…T-1724 + **T-1767…T-1771** (@Builder), гейты T-1712 (@Architect) / T-1725 (@DevOps) / T-1726 (@Reviewer/@PM).
> **Spec:** `spec.md` (итерация 2). **ADR:** `adr-1018-2-sleep-manual-override.md` (SUPERSEDE F-10 §5-6 + AMEND ADR-1017-3; **без флагов**).
> **Зависимость (блокирующая):** **F7 `settings-worker-sync` / ADR-1018-7** — пока настройки UI не доходят до воркеров, F2 не проверяема (spec §4.7).
> **Раунд:** 10.18. **Нумерация:** T-1712…T-1726 + T-1767…T-1772.
> **Тип:** backend (`dream_worker.py`, `memory_agi.py`, пороги) + frontend (`web/app.js`). **Приоритет:** **P0**.
> **Конфликт файлов:** `services/dream_worker.py`, `web/api/memory_agi.py`, `web/app.js`, `config/settings.py`, `services/prompt_migrations.py` + **F7** (те же файлы).
> **ТЗ:** `plans/current_task.md` **§2.1–§2.4** (строки 27–54) + **UPD п.2, п.3, п.5** (строки 116–117, 119–121, 126).
> **Baseline:** HEAD `118a03c`; pytest **6007 passed / 0 failed**; каталог **435/406/411/90/88/19**; SQLite **v9**.

## 0. Цель

Вернуть рабочий пайплайн интеллекта: пороги/лимиты не «срезают всё на корню», ручной запуск Сна прогоняет **полный каскад** (Сон → Глубокий сон → Личность) **безусловно** (без таймингов, расписаний, бюджетов и гейтов), бейджи в реальном времени отражают состояние воркера, а вся цепочка сна продиагностирована таблицей порогов.

**Изменения итерации 2 (после human-gate):**
- **Manual — без флагов:** никакого `flags.sleep_manual_priority_enabled`; безусловный обход = базовая логика.
- **Рассинхрон настроек** — вынесен в **F7** (`features/settings-worker-sync/`), F2 на него ссылается и зависит.
- **Аудит цепочки сна** с таблицей текущих/предлагаемых порогов — обязательный результат.
- Каталог-Δ F2 = **0** (флаги исключены).

## 1. Контекст и доказательства (@Memory Step 0 + аудит итерации 2)

- **§2.3 — конкретный дефект:** `dreamPhaseBadge`/`deepPhaseBadge` (`web/app.js:1216-1248`) при `active=true` и `active_until=null` показывают «Сон идёт»; backend (`web/api/memory_agi.py:482-501`) считает `active_until` **только когда `dream_in`** → при ручном прогоне вне окна `active_until=null`.
- **§2.3 — стейл:** `runDreamNow` (`web/app.js:4974-4993`) **не перезагружает `cognition`** → до 15с стейл. Это же закрывает S10.17-2.
- **Конфликт ADR:** §2.3 расходится с **ADR-1017-3**; **WebSocket в проекте ОТСУТСТВУЕТ** → оптимистика + целевой reload + polling.
- **§2.2 (итерация 2):** расходится с **F-10 §5-6** («manual не минует gate/budget»). `window_skip` manual **уже обходится** (`dream_worker.py:588`). Реальные причины: kill-switch (`:569-577` → при глобальном `DREAM_ENABLED=False` возвращает False), бюджеты/near-limit (`:600-620`), порог кандидатов (`:437-451`), `distilled==0` из-за порогов, `DREAM_ENABLED/DEEP_SLEEP_ENABLED=False`.
- **§2.4:** `traits` вызываются только из глубокого сна (`:1315-1331`); каскад не стартует при `deep_sleep_enabled=false` / `trigger != after_sleep` / `distilled==0` (`:1100-1119`); traits требуют `bot_self_reply`-фактов. Причина — цепочка флагов/порогов, а не промпт.
- **КРИТИЧНО (UPD п.3):** тумблеры были ON в UI, а воркеры видели OFF → **рассинхрон слоя чата и глобального слоя** (деталь — F7 spec §2). Без F7 включение Сна из админки не влияет на воркер, а включение без рестарта не регистрирует джоб.
- **Ротация SSH — CANCELLED** (пароль действующий, вне раунда).
- **Аудит цепочки (UPD п.5):** звенья A–I — spec F2 §2.5; таблица порогов — spec §4.1.

## 2. Требования

- [x] **Manual — абсолютный приоритет БЕЗ ФЛАГА:** ручной запуск игнорирует окно, расписания, kill-switch, near-limit и бюджеты; расход учитывается.
- [x] **Guard-ы сохранены:** локи, `protected_facts`, ≥2 `source_ids`, R17, `persona_enabled` (последний не глушит каскад молча — `reason=persona_disabled`).
- [x] Ручной запуск гарантированно прогоняет **весь каскад** (Сон → Глубокий сон → Личность).
- [x] Пороги/лимиты ослаблены по таблице spec §4.1; факты доходят до дистилляции (без мусора из междометий); DML-миграция идемпотентна.
- [x] Бейджи реактивно отражают `running/active` (в т.ч. вне окна); «до {HH:MM}»/таймаут; свечение.
- [x] `active_until` рассчитывается вне окна расписания (устранить `null`).
- [x] Пайплайн Личности логирует причины отсутствия черт (WARNING/ERROR), включая `persona_disabled`.
- [x] Устранён residual **S10.17-2** (`cognition==null` → чистый `—`).
- [ ] `DREAM_ENABLED`/`DEEP_SLEEP_ENABLED` — включаются **после F7** (основание в отчёте T-1713). *(Code-default оставлен False — включается per-chat через UI/scope, ADR-1018-2 D10.)*
- [x] Каталог-Δ=0 (флаги НЕ вводятся).

## 3. Constraints (инварианты раунда)

- **R17:** логи — только класс/причина/числа; без текстов/секретов.
- **Порядок роутеров `bot.py` не менять** (только DI-kwargs); `media/`/`.env` **не трогать**.
- **R16** (id — ключ); **SQLite v9**, DDL не требуется.
- **Каталог Δ=0** (флаги F2 исключены UPD п.2).
- **ADR-1013-3 (канон промптов):** правка промптов — только канон-миграция (если понадобится; по умолчанию — не требуется).
- **F7 — блокирующая зависимость** (spec §4.7); воркер обязан читать настройки через accessor F7.
- **Ревью-гейты:** полный `pytest` 0 регрессий; `node --check web/app.js`; `JS-UNIT-OK`; `VUE-MOUNT-OK`; `git diff --check`; русские conventional commits.

## 4. Зависимости / порядок

- **Вверх:** **F7** (ADR-1018-7) → T-1712 (@Architect).
- **Вниз:** релиз 10.18; F4/F5 (F2 может вливаться параллельно).
- **Порядок:** F7 → **F2** (T-1713…T-1718 backend → T-1719 backend-статус → T-1720…T-1721 frontend). `web/app.js` делится с F4 — вливать ступенями.

## 5. Definition of Done

- [x] Ручной запуск вне окна запускает дистилляцию и каскад до Личности; в логах видна причина на каждом шаге.
- [x] Ручной запуск работает при `memory.dream_enabled=false` и при `gates[dream]=false` (аудит `gate_override`).
- [x] Бейджи меняются на «Сон идёт / до …»; `active_until` не `null` при ручном прогоне.
- [ ] Сон реально дистиллирует; Глубокий сон стартует следом; черты Личности генерируются (при `bot_self_reply`-фактах). *(Требует живого LLM — T-1724/T-1725.)*
- [x] Таблица порогов (spec §4.1) реализована; DML-миграция идемпотентна (тест).
- [ ] `DREAM_ENABLED`/`DEEP_SLEEP_ENABLED` включены после F7 и обоснованы. *(Per-chat через UI/scope — T-1713.)*
- [x] Полный `pytest` **0 failed**; JS-гейты чистые; R17-скан чист; каталог-Δ=0.

## 6. Чек-лист задач

- [ ] **T-1712 (@Architect, гейт):** `spec.md` + ADR-1018-2 (итерация 2) — (а) **SUPERSEDE F-10 §5-6** (manual безусловно, **без флага**); (б) таблица guard-ов «обходится/неприкосновенно»; (в) **AMEND ADR-1017-3** (реактивность без WebSocket); (г) контракт каскада и `active_until` вне окна; (д) ссылка на ADR-1018-7 (блокирующая зависимость).
- [ ] **T-1713 (@Builder):** обосновать и зафиксировать включение `DREAM_ENABLED`/`DEEP_SLEEP_ENABLED` **для целевого чата после F7** (через UI/scope), без хардкода; влияние на пайплайн; R17-safe отчёт.
- [x] **T-1714 (@Builder):** §4.1 spec — ослабить пороги (`repeat 3→2`, `sum 12→8`, `min_facts 5→2`, `clusters 5→10`, `distill/day 30→60`, `tokens/day 60000→300000`, `quiet 30→10`) + **идемпотентная DML-миграция** (замена только при равенстве прежнему дефолту). Сохранить анти-мусор.
- [x] **T-1715 (@Builder):** §2.2 — manual-приоритет **безусловно**: обход kill-switch (аудит `status="gate_override"`), near-limit и бюджетов (аудит `status="budget_override"`), расход `worker_budget.consume` сохраняется; `_run_lock`/`protected_facts`/≥2 `source_ids` — неприкосновенны.
- [x] **T-1716 (@Builder):** §2.4 — каскад: `_maybe_deep_after_sleep(manual=True)` без ранних return; `_run_deep_all(manual=True)` без `break`; `stats["cascade"]` аддитивно.
- [x] **T-1717 (@Builder):** §2.4 — WARNING/ERROR-логи Личности: `no_self_facts`, **`persona_disabled` (новое)**, `json_error` (raw_len), `all_duplicates`, `budget_skip`, `llm_error`, `write_error`. R17-safe.
- [x] **T-1718 (@Builder):** §2.4 — устранить причину 0 черт в цепочке флагов/порогов/кандидатов (не в промпте); traits доступны при self-фактах.
- [x] **T-1719 (@Builder):** backend-статус — `memory_agi.py`: считать `active_until` и при ручном прогоне вне окна; код-константа `_DREAM_RUN_TIMEOUT_SECONDS=900`; аддитивные `dream.manual`/`deep_sleep.manual`; контракт не ломать.
- [x] **T-1720 (@Builder):** §2.3 — frontend: `runDreamNow` немедленно перезагружает `cognition`; оптимистичная `active`; бейджи «Сон до …»; ускоренный polling на время прогона.
- [x] **T-1721 (@Builder):** §2.3 — S10.17-2 (`cognition==null` → `—` без «через») + фиксация в AMEND ADR-1017-3.
- [x] **T-1722 (@Builder):** тесты — пороги/manual-обход (без флага)/каскад/`persona_disabled` (py), реактивность бейджей и `active_until` (JS+py), DML-миграция.
- [x] **T-1723 (@Builder):** гейты — полный `pytest` 0 failed, JS-гейты, каталог Δ=0 (зафиксировать), R17-скан, `git diff --check`, русский commit.
- [ ] **T-1724 (@Builder):** ручной end-to-end (Сон→Глубокий→Личность) в dev/локали + фрагмент логов к отчёту (R17-safe). *(Осталось: требует живого LLM/бота — вне батча 2.)*
- [ ] **T-1725 (@DevOps, гейт):** деплой (SSH pull + `.env` при необходимости + `systemctl restart admin_bot` + live-проверка бейджей/логов). Пароль в репо **НЕ хранить**.
- [ ] **T-1726 (@Reviewer + @PM, гейт):** сверка DoD, R17, отсутствие регрессов порогов/каскада/бейджей; подтверждение безусловного manual-обхода **без слома safety** (таблица guard-ов).

**Новые задачи итерации 2:**

- [x] **T-1767 (@Builder):** заменить все условные ветки manual на безусловные; удалить из кода/спеки/ADR любые упоминания `flags.sleep_manual_priority_enabled` (не должно остаться ни одной ветки `if manual and flag`); регресс-тест «manual без флага обходит гейт/бюджет».
- [x] **T-1768 (@Builder):** manual-ветки читают настройки через accessor **F7** (`resolve_setting*`), а не локальный `hot.get` — чтобы ручной прогон уважал scope чата; smoke: `overrides` чата → manual видит.
- [x] **T-1769 (@Builder):** реализовать таблицу порогов (spec §4.1) + `migrate_dream_thresholds(cache)`; тест идемпотентности/кастома; вызов в `bot.py` рядом с `migrate_prompt_canons`. *(Модуль — `services/config_migrations.py`: `prompt_migrations.py` не трогаем — канон-дельта-тесты 10.13.)*
- [x] **T-1770 (@Builder):** диагностика `reason=persona_disabled` + валидация, что manual-каскад **не** глушится при выключенном persona (WARNING, но шаг выполняется).
- [x] **T-1771 (@Builder):** тесты аудита цепочки: (A) кандидаты с 2 фактами, (C) окно, (D) пороги, (E) kill-switch при глобальном OFF, (F) near-limit, (G) каскад, (H) Личность — каждый кейс проверяется отдельным тестом.
- [ ] **T-1772 (@Reviewer/@PM):** приёмка таблицы «настройка → пишется → читается → статус» из F7 spec §2.3 в части Сна; подтверждение, что все «РАЗРЫВ» по Сну закрыты.

## 7. Риски / ADR-конфликты

| # | Риск / конфликт | Мера |
|---|---|---|
| R1 | **§2.2 vs F-10 §5-6** («manual не минует gate/budget») | ADR-1018-2 **SUPERSEDE** + таблица guard-ов D3 |
| R2 | **§2.3 vs ADR-1017-3** + отсутствие WebSocket | AMEND: оптимистика + целевой reload + polling; **не вводить WebSocket** |
| R3 | `active_until=null` при ручном прогоне вне окна | T-1719 (backend) + T-1720 (frontend) |
| R4 | Расхождение диагноза: реальные причины обрыва | Аудит spec §2.5 (звенья A–I); T-1713/T-1715/T-1771 |
| R5 | Ослабление порогов → мусорные убеждения | Анти-мусор сохранён; F5-пенализация; пороговые тесты |
| R6 | 0 черт — не промпт | T-1717/T-1718/T-1770 |
| R7 | Потеря safety при **безусловном** manual-обходе | Таблица D3; аудит `gate_override`/`budget_override`; T-1726/T-1772 |
| R8 | F2 не проверяема без F7 | Порядок F7 → F2; T-1768 (accessor); T-1772 (приёмка) |
| R9 | Удаление флагов ломает существующие тесты F2-итерации-1 | T-1767 явно переписывает тесты; grep «не осталось `sleep_manual_priority_enabled`» |

**ADR:** обновлён — ADR-1018-2 (итерация 2, без флагов, + зависимость от ADR-1018-7).

## 8. Feature flag / progressive delivery

- **Feature flags: НЕТ** (решение владельца, UPD п.2). Manual-приоритет и новые пороги — базовая логика.
- **Rollout stages (без флагов):** F7 → DML порогов → включение рубильников для целевого чата → manual end-to-end → наблюдение 24ч.
- **Rollback:** `git revert` кода + обратная DML порогов (прецедент). Никаких переключателей в рантайме по F2.

## 9. Handoff / деплой

`@Orchestrator` — план F2 (итерация 2) готов. Спека/ADR — T-1712 (@Architect). **Зависимость F7 — блокирующая.** Реализация — T-1713…T-1724 + T-1767…T-1771 (@Builder). **Деплой (SSH pull + правка `.env` при необходимости + `systemctl restart admin_bot` + проверка бейджей/логов) — отдельный шаг @DevOps (T-1725). Пароль сервера в репозитории НЕ хранится.**

## 10. Ход реализации — Батч 2 (15.09.2026, @Builder)

**Файлы:** `services/dream_worker.py`, `services/config_migrations.py` (новый),
`config/settings.py`, `bot.py`, `web/api/memory_agi.py`, `web/app.js`,
`tests/test_sleep_manual_cascade_round1018.py` (новый) + правки
`tests/test_dream_worker.py`, `tests/test_sleep_fallback_round1015.py`,
`tests/test_smoke_round1016_sleep.py`, `tests/test_webapp_round1015_ui.py`,
`tests/js/routing_test.js`.

**Ключевое:**
- `manual=True` обходит kill-switch (`status="gate_override"`), near-limit и
  суточные бюджеты (`status="budget_override"`) **безусловно, без флагов**;
  `worker_budget.consume` по-прежнему пишется. Guard-ы (локи,
  `protected_facts`, ≥2 `source_ids`, R17, `persona_enabled`) сохранены.
- Каскад: `_maybe_deep_after_sleep(manual=True)` игнорирует
  `flags.deep_sleep_enabled`/`trigger`; `run_once` отдаёт аддитивный
  `stats["cascade"] = {"deep": {...}, "traits": {...}}`.
- Диагностика Личности: `no_self_facts`, `persona_disabled` (новое),
  `json_error`+`raw_len`, `all_duplicates`, `budget_skip`, `llm_error`,
  `write_error` — R17-safe.
- Пороги 2/8/2/10/60/300000/10 (code-default) + идемпотентная DML-миграция
  `migrate_dream_thresholds(cache)` в `services/config_migrations.py` (вызов в
  `bot.py`). `prompt_migrations.py` не трогаем — канон-дельта-тесты 10.13.
- Backend: `active_until = now+900` при running вне окна; аддитивные
  `dream.manual`/`deep_sleep.manual`. Frontend: оптимистичная `active`,
  немедленный `loadCognition` + ретраи 1/3/8с, ускоренный polling 5с/120с,
  `cognition==null` → `—` (закрыт S10.17-2).

**Отклонение от таблицы §4.1:** `DREAM_ENABLED`/`DEEP_SLEEP_ENABLED` code-default
оставлен `False` — включаются per-chat через UI/scope после F7 (ADR-1018-2 D10:
«не через хардкод в коде»); T-1713/T-1724/T-1725/T-1726/T-1772 открыты.

**Гейты батча:** `pytest` 6076 passed / 0 failed (после доводки §11 — **6083**);
`node --check web/app.js` OK;
`JS-UNIT-OK`; `VUE-MOUNT-OK`; `git diff --check` чист; каталог-Δ=0.

## 11. Доводка Батча 2 — F2 follow-up (15.09.2026, @Builder)

Закрыты остаточные дефекты аудита Батча 2 (D1–D9). T-1767…T-1771 подтверждены
(24 теста в `tests/test_sleep_manual_cascade_round1018.py`).

| ID | Суть | Файл:строка | Тест |
|---|---|---|---|
| **D1** | `manual` проброшен во все `_deep_budget_ok`/`_dream_budget_ok`: retry-JSON, Личность (`_run_persona_traits_once(manual=...)`), bridge. Manual-путь нигде не гейтится | `services/dream_worker.py:884,1473-1475,1490-1491,1727-1729,1776-1777` | `TestManualBudgetVerdictIgnored::test_persona_reached_with_exhausted_deep_cap` |
| **D2** | Restore-polling возвращает базовые 15с (общий `_startCognitionTimer` без раннего return; restore не зовёт `startCognitionPolling`) | `web/app.js:5403-5457` | `tests/js/routing_test.js` (restore 5000→15000) |
| **D3** | (было сделано) manual — 4 независимых `consume`, verdict не применяется | `services/dream_worker.py:115-123,1686-1694` | `TestManualBudgetVerdictIgnored` |
| **D4** | Тексты каталога актуализированы (2/8/2/10/60/10); `DREAM_ENABLED` — F7: джоб всегда, резолв per-tick | `services/param_catalog.py:1368-1435` | `tests/test_param_catalog.py` (Δ=0) |
| **D5** | Детерминированные тесты T-1771: (A) 2 факта при min=2, (C) manual вне окна, deep-кап исчерпан → Личность, `consume→False` → True | `tests/test_sleep_manual_cascade_round1018.py` | `TestCandidateMinFacts`, `TestManualBypassesWindow`, `TestManualBudgetVerdictIgnored` |
| **D6** | Ускоренный polling (5с) стартовал только на вкладке Статус (`activeTab==='status'`), вызов из `runDreamNow` (вкладка `modules`) — мёртв; **R2-1 (вариант b): гейт снят** — 5с стартует сразу после POST; `setTab`/`stopCognitionPolling` снимают interval+restore | `web/app.js:5452-5464` | `tests/js/routing_test.js` |
| **D7** | (было сделано) docstring `run_once` — manual обходит бюджеты; `_run_deep_all` early-return — единая dict-форма с `traits` | `services/dream_worker.py:423-434,1379-1382` | `tests/test_dream_worker.py` |
| **D8** | (было сделано) суточные лимиты резолвятся ОДИН раз ДО цикла кластеров | `services/dream_worker.py:690-698` | `TestManualBypassBudget` |
| **D9** | `last4` убран из старт-маркера BetterStack (R17: только `token_len`/`from`) | `bot.py:182-190` | `tests/test_betterstack_handler.py::TestBotMarkers` |

**Семантика:** spec §4.6 (restore базовых 15с; **R2-1 — гейт вкладки снят**)
и ADR-1018-2 D5 обновлены.
Каталог-Δ=0. Ручной путь по-прежнему без фича-флагов.

**Гейты F2 follow-up:** `pytest` **6083 passed / 0 failed**; `node --check` OK;
`JS-UNIT-OK`; `VUE-MOUNT-OK`; `git diff --check` чист.

## 12. Фиксы ревью итерации 2 (15.09.2026, @Builder)

Закрыты находки @Reviewer (R2-1 Medium + R2-2…R2-5 Low). **Выбран вариант (b)**
для R2-1 (предпочтительный): гейт `activeTab === 'status'` при СТАРТЕ ускорения
снят; «вечного 5с вне вкладки» нет — `setTab` → `stopCognitionPolling` уже
снимает и interval, и restore-таймер.

| ID | Уровень | Суть фикса | Файл:строка | Тест |
|---|---|---|---|---|
| **R2-1** | Medium | `restartCognitionPolling` больше не гейтится вкладкой: 5с стартует сразу после POST `runDreamNow` (кнопка живёт на `modules`). Уход с вкладки (`setTab`) снимает оба таймера | `web/app.js:5452-5464` | `tests/js/routing_test.js` (runDreamNow на `modules` → 5с; restore через срабатывание таймера → 15с; `stop` → оба null) |
| **R2-2** | Low | Синхрон доков с фактом D9: старт-маркер BetterStack без `last4` → `attached \| host=… \| token_len=N \| from=…` | `README.md:1045-1046`; `plans/ARCHITECTURE.md:211,223` | grep `last4`-маркера в этих строках — нет |
| **R2-3** | Low | Гейт-число `6076` → `6083`; добавлена запись об итерации 2 (D1–D9 + R2-1…R2-5) | `tasks.md:158` + §11/§12 | этот раздел |
| **R2-4** | Low | Описание `DREAM_DISTILLATIONS_PER_DAY` — per-chat (S10.18-1), не «глобальный» | `services/param_catalog.py:1438` | `tests/test_param_catalog.py` (Δ=0) |
| **R2-5** | Low | JS-тест дожимает restore **через срабатывание** `setTimeout(..., restoreMs)` (fake `setTimeout`/`clearTimeout`), а не прямым вызовом internal | `tests/js/routing_test.js:1887-1997` | сам тест |

**Гейты этой итерации:** `pytest` **6083 passed / 0 failed** (69.7с);
`node --check web/app.js` OK; `JS-UNIT-OK`; `VUE-MOUNT-OK`; `git diff --check` чист.
Каталог-Δ=0. Коммит/деплой — НЕ выполнялись (по указанию).

## 13. Фиксы аудита Батча 2 — S10.18-21…S10.18-26 (15.09.2026, @Builder)

Закрыты находки §8 отчёта `plans/reports/round10.18_scanner_audit.md`. Скоуп не
расширялся; S10.18-12/-13/-18/-19/-20/-27/-28 не трогались.

| ID | Уровень | Суть фикса | Файл:строка | Тест |
|---|---|---|---|---|
| **S10.18-21** | Medium | **Вариант (а):** предгейт `_deep_tick` `_deep_fixed_possible()` удалён — он опирался на прогрев in-memory `ChatParamsCache` и молча хоронил per-chat `trigger='fixed'` при глобальном `after_sleep`. `_deep_tick` снова безусловно выбирает кандидатов (1 SQL/час). Заодно удалены неиспользуемые `ChatParamsCache.has_any_override`/`note_overrides`/`_override_keys_seen` | `services/dream_worker.py:1320-1337`; `services/chat_params.py` | `tests/test_deep_sleep.py::TestDeepSleepSchedule::test_deep_tick_cold_cache_reaches_candidates` (реальный `ChatParamsCache` с пустым `_items`) |
| **S10.18-22** | Medium | `_restoreCognitionPolling` стартует базовые 15с ТОЛЬКО при `activeTab==='status'`; `closeModule` вне Статуса останавливает polling (модалка «Сон» на `modules`) | `web/app.js:_restoreCognitionPolling`/`closeModule` | `tests/js/routing_test.js` (restore вне Статуса → 15с не стартует; closeModule вне Статуса → stop) |
| **S10.18-23** | Low | Настоящий признак ручного прогона: `_manual_run_until`/`_manual_deep_until` (стажит `run_once`), свойства `manual_run_active`/`manual_deep_active`; `cognition_status` отдаёт `manual` из них, `active_until` вне окна растягивается только для `manual` | `services/dream_worker.py`; `web/api/memory_agi.py` | `tests/test_sleep_manual_cascade_round1018.py::TestManualRunMarker`; `tests/test_webapp_round1015_ui.py::test_auto_tick_outside_window_not_manual` |
| **S10.18-24** | Low | `_FALLBACK_MIN_IMPORTANCE_SUM` 8→**6** (ниже новых дефолтов 2/8), размер кластера 2 (ниже нельзя — анти-мусор). Fallback снова не no-op; spec §4.1 обновлён | `services/dream_worker.py:164-176` | `tests/test_sleep_fallback_round1015.py::test_fallback_constants` + логи (threshold 6) |
| **S10.18-25** | Low | Единая семантика `0` = «без лимита» в near-limit-ветке (`bool(dist_max)`/`bool(tok_max)`) — 0 больше не триггерит `budget_stop` | `services/dream_worker.py:733-745` | `tests/test_sleep_manual_cascade_round1018.py::TestZeroLimitUnlimited` |
| **S10.18-26** | Info | Хэндлы `_retryCognition` сохраняются в `_cognitionRetryTimers` и снимаются в `stopCognitionPolling`; порядок в `runDreamNow` — restart, затем ретраи | `web/app.js` | `tests/js/routing_test.js` (3 ретрая сняты clearTimeout) |

**Семантика:** spec §4.1/§4.3/§4.5/§4.6 и ADR-1018-2 D5 синхронизированы.
Каталог-Δ=0 (код-константы/строки). Коммит/деплой — НЕ выполнялись.

## 14. Фикс аудита Батча 3 — S10.18-29 (15.09.2026, @Builder)

Закрыта находка §9 отчёта `plans/reports/round10.18_scanner_audit.md`. Скоуп не
расширялся.

| ID | Уровень | Суть фикса | Файл:строка | Тест |
|---|---|---|---|---|
| **S10.18-29** | Low | `run_once(deep=False)` (кнопка «Сон сейчас») запускает Глубокий сон каскадом, но не выставлял `_manual_deep_until` → во время каскада `deep_sleep.manual=False` и бейдж deep «терял» фазу (симметрия T-1719 только для `?deep=1`). Теперь `_run_deep_all(manual=True)` выставляет маркер на всё время прогона (`_manual_deep_run`) + TTL после него, поэтому прогон >15 мин не теряет `manual` | `services/dream_worker.py::_run_deep_all`, `manual_deep_active` | `tests/test_sleep_manual_cascade_round1018.py::TestManualRunMarker::test_run_once_cascade_sets_manual_deep_marker` |

**Синхронизировано:** spec §4.5 и ADR-1018-2 D5.
**Гейты:** `pytest` **6106 passed / 0 failed**; `node --check web/app.js` OK;
`JS-UNIT-OK`; `VUE-MOUNT-OK`; `git diff --check` exit 0. Каталог-Δ=0.
Коммит/деплой — НЕ выполнялись.
