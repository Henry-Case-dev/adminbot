# Spec — S10 `summary-deploy-round1026` (Эпик 2, §107/§114/§115/§116/§117)

- **Статус:** Step 2 @Architect (24.09.2026, T-3462). Код — не в этом шаге. Сверка `tasks.md` ↔ spec/ADR — @PM (T-3463); `tasks.md` (T-3461…T-3480) на этом шаге не переписывался.
- **Тип:** deploy/ops (§107 прямой деплой/активация, §114 предполётная проверка, §115 первый рабочий запуск) + активация/наблюдаемость (§117-результаты). **P0, gate-фича** — закрывает Эпик 2 и является предусловием Эпика 3.
- **Risk-Level:** **R2** — S10 впервые **включает** живой Hybrid-пайплайн и реальную публикацию на постоянной основе (blast radius — каждый прогон Саммари), при этом активация полностью обратима (env/hot OFF + `git revert`), 0 новых LLM-вызовов (2-вызовность), Δ DDL=0, Δ каталога=0, §104-контур/`generate_image` не тронуты, обращение с секретами не меняется, fail-closed §106 + dry-run S9 сохранены, §114-harness до деплоя, §115 после. **Повышает до R3:** касание `generate_image`/§104, изменение OFF-генерации (промпты/вызовы/XML/память), DDL/каталог/новые зависимости, изменение обращения с секретами, невозможность безопасного отката.
- **ADR:** `adr-1026-12-summary-deploy-activation.md` (D1–D8; **Proposed** → Accepted фактом merge T-3476/T-3477, ожидается §81).
- **Гейт D4 (ADR-1025-24) — ✅ закрыт владельцем 24.09.2026** (live-приёмка Эпика 1 подтверждена) — живая активация/публикация разрешены.
- **Baseline:** HEAD **`76abf91`** == `origin/master` (closing-docs S6); `APP_VERSION` **2.58.28** (прод активен, MainPID **575712**); pytest `.venv` **9000/0**; JS **47/47**; каталог **469/426/444/100/98/21**; **Δ DDL=0** (SQLite v12). Подтверждается baseline @DevOps (T-3461).
- **Зависит от:** S1–S9 ✅ (2.58.18–2.58.28; S6 — 2.58.28, §80).

## 1. Цель и контекст

§107: новый пайплайн Саммари (Эпик 2) становится **основным сразу после завершения Эпика 2**; **не требуется** обязательный теневой режим, поэтапный rollout, длительное сравнение с Legacy, отдельный интерфейс выбора Legacy/Hybrid; функциональность **включена после деплоя**; алгоритмический фильтр включён по умолчанию; раздельный роутинг активен; **не оставлять фичу выключенной в ожидании ручной активации**; перед деплоем — минимальные функциональные тесты. §114: 11 минимальных сценариев; тестовые результаты **не публикуются** в основной чат; после проверки — деплой. §115: после деплоя — 7 проверок (Hybrid активен; фильтр включён; модели L1/L2; загрузка промптов; штатный запуск; логи всех этапов; публикация); rich — статья с изображением сверху и настоящим H1, plain — жирный заголовок + абзацы, текст читаем. §116: 15 критериев «ЭПИК 2 НЕ ЗАВЕРШЁН, ЕСЛИ…» — основа приёмки. §117: 14 обязательных результатов Эпика 2. Смежное: §85-UI — **отдельная санкция** (Δ каталога ≠ 0), вне S10.

**Факты кода (Step 0 @Memory + Step 2 @Architect):**

1. `SUMMARY_HYBRID_L2_ENABLED` — env-only `ClassVar`, **default OFF** (`config/settings.py:984–985`); резолв `_hybrid_l2_enabled` (`services/summary_generator.py:652–666`): `_chat_limit(chat_id, "flags.summary_hybrid_l2_enabled", hot.get("flags.summary_hybrid_l2_enabled", settings.SUMMARY_HYBRID_L2_ENABLED))`. `_run` резолвит режим один раз (`:407`); при ON → `_run_hybrid_l2` (`:470–483`), OFF-ветка (`_generate_two_call`) не выполняется.
2. `flags.summary_hybrid_l2_enabled` **не в каталоге** (`services/param_catalog.py::get_by_pg_key` → `None`) → штатного UI/API-пути записи нет; `hot.get` (плоский dict `ConfigCache`, `services/config_cache.py:467`) возвращает переданный default. Фактический рычаг активации — **env/default**.
3. Per-chat резолв (`services/chat_params.py:344–377`): `overrides` (каст по каталогу) → `hot.get` → default. Для не-каталожного ключа override возможен только ручной записью.
4. Фильтр ON по умолчанию: `SUMMARY_FILTER_ENABLED = _env_bool(..., True)` (`config/settings.py:945`); **в каталоге** (pg_key `flags.summary_filter_enabled`, группа `flags_summary_filter`); per-chat резолв `services/summary_generator.py:447–450`.
5. Раздельный роутинг уже активен: слоты `SUMMARY_L1_*`/`SUMMARY_L2_*` — env-only `ClassVar` (`config/settings.py:966–977`); «не выбрано» (пусто) → глобальная основная модель; hot-first `models.summary_l1_*`/`models.summary_l2_*`.
6. Наблюдаемость: S7 `services/summary_run_log.py` (сквозной `run_id`=`correlation_id`, события §108/§109); S8 `services/execution_graph_source.py` (карта вызовов, publish-узел из S6); §110 log viewer; S9 `services/summary_test_run.py` dry-run (0 публикаций/0 памяти/0 `generate_image`).
7. Публикация S6 уже в живом пути (`_publish_rich_document` 969 / `_publish_plain_document` 849; rich `<h1>`, plain `<b>`) — §115 использует как есть.
8. Планировщик — cron 0/6/12/18 (`services/summary_scheduler.py:30–45`); канон L1/L2 — `services/summary_prompts.py` (L1 257, L2 302) + `services/prompt_migrations.py`.
9. Гейт D4 закрыт владельцем 24.09.2026.

## 2. Границы

**В scope S10:**
- Механика активации §107: смена code-default `SUMMARY_HYBRID_L2_ENABLED` OFF→ON; сохранение per-chat/hot резолва как **аварийного** kill-switch; «не оставить выключенной» (проверка `.env` + effective-резолв).
- §114-предполётный harness (11 сценариев) без публикации в основной чат (reuse S9 dry-run + моки/шпионы) + evidence.
- §115-процедура (7 проверок) и артефакты rich/plain (reuse S6-публикации).
- §117 — оформление 14 обязательных результатов Эпика 2 (документ-результат + merge-раздел).
- Deploy/bump/активация/откат: тег `pre-round1026-s10` → `76abf91`, `.env.bak`, soft-флаги, `git revert`.
- §116-критерии как acceptance; R17/R18; Δ DDL=0; Δ каталога=0.

**Вне scope (не трогать):**
- §85-UI (каталог/вкладки «Сводки чатов», UI-слоты L1/L2-моделей/ключей, видимость Hybrid-флага) — **отдельная санкция владельца (Δ каталога ≠ 0), вне S10**.
- §104 (`generate_image`/обложка-контур: модель/провайдер/ключи/промпт/параметры/обработка/порядок/прикрепление).
- §110 (log viewer S7), §111/S8 (ExecutionGraph — не переписывать, вторая аналитика запрещена), §113/S9 (`summary_test_run.py` — не публикует, не ломать).
- Логика генерации/форматирования/фильтра/восстановления/контрактов L1/пакета/L2 (`summary_filter.py`, `summary_context_restore.py`, `summary_l1_clusterizer.py`, `summary_fact_package.py`, `summary_l2_writer.py`, `summary_article_formatter.py`), каноны/промпты и миграции, `services/telegram_send.py`, `web/api/routes.py`, `web/**`, `db/**`, `services/param_catalog.py`, `bot.py`/порядок роутеров.
- Управляющие документы: `plans/current_task.md`, машинный блок `OPENCODE_WORKFLOW_STATE_V1`, `plans/backlog.md`, `plans/metrics.md`, `plans/ARCHITECTURE.md` (на своих шагах), `tasks.md` (правит только @PM T-3463).

## 3. Трассируемость REQ → SC → ADR

| REQ (tasks.md) | §ТЗ (verbatim-источник) | SC спеки | Решение ADR |
|---|---|---|---|
| REQ-S10-01 | §107 «Новый пайплайн должен стать основным сразу после завершения Эпика 2.» | SC-01, SC-03 | D1, D2, D7 |
| REQ-S10-02 | §107 «Не требуется: Обязательный теневой режим. Поэтапный rollout. Длительное сравнение с Legacy. Отдельный интерфейс выбора Legacy/Hybrid.» | SC-02, SC-14 | D1, D2, D8 |
| REQ-S10-03 | §107 «Новая функциональность должна быть включена после деплоя… Не оставлять фичу выключенной в ожидании ручной активации.» | SC-01, SC-03, SC-15 | D2, D7 |
| REQ-S10-04 | §107 «Алгоритмический фильтр включён по умолчанию.» | SC-04 | D2 |
| REQ-S10-05 | §107 «Раздельный роутинг активен.» | SC-05 | D2 |
| REQ-S10-06 | §107 «При этом перед деплоем выполнить минимальные функциональные тесты.» | SC-06 | D3, D7 |
| REQ-S10-07 | §114 (11 сценариев) | SC-07 | D3 |
| REQ-S10-08 | §114 «Не публиковать тестовые результаты в основной чат.» + «После проверки выполнить деплой.» | SC-08 | D3, D7 |
| REQ-S10-09 | §115 (7 проверок) | SC-09 | D4 |
| REQ-S10-10 | §115 rich/plain артефакты | SC-10 | D4 |
| REQ-S10-11 | §116 «ЭПИК 2 НЕ ЗАВЕРШЁН, ЕСЛИ…» (15 критериев) | SC-11 | D8 |
| REQ-S10-12 | §117 (14 обязательных результатов) | SC-12 | D5 |
| REQ-S10-13 | R17 + R18 + Δ DDL=0 + Δ каталога=0 + CSP/zero-build + 0 зависимостей + 2-вызовность | SC-13 | D6 |
| REQ-S10-14 | Границы §104/§110/§111/S9; §85-UI — отдельная санкция; активация только существующими рычагами | SC-14 | D1, D8 |

## 4. Решения (D1–D8; полно — в ADR-1026-12)

### D1. Границы diff
Diff S10: `config/settings.py` (default ON + комментарий + `APP_VERSION`), docstrings `_hybrid_l2_enabled`/`summary_l2_writer` (при необходимости), тесты (обновление OFF-default-пинов + §114-harness), `README.md`. Вне diff — всё из §2. Логика `_run`/`_run_hybrid_l2`/резолв **не меняется**.

### D2. Механика активации §107 (ответ (a)) — ГЛАВНОЕ
- **Активация = code-default ON.** `_env_bool("SUMMARY_HYBRID_L2_ENABLED", True)`. После деплоя (без явного `false`) пайплайн — основной во всех чатах, **без ручного действия**.
- **Слои сохраняются, смысл перевёрнут:** `per-chat override → hot → env/default`; отсутствие override → ON; явный `false` → **аварийное выключение**.
- **«Ручная активация» (запрещена) vs «аварийное выключение» (разрешено):** ON-действие/UI-селектор для запуска — нет; оператор может явно выключить (`SUMMARY_HYBRID_L2_ENABLED=false` в `.env` + рестарт; либо non-catalog `flags.summary_hybrid_l2_enabled=false`).
- **Раздельный роутинг** уже активен (проверка §115 п.3); **фильтр** default ON (не меняется); **per-chat override** сохраняется (для не-каталожного ключа — только advanced/ops).
- **«Не оставить выключенной»:** деплой проверяет отсутствие `SUMMARY_HYBRID_L2_ENABLED=false` в `.env`; §115 п.1 подтверждает effective ON.
- Альтернативы (env-пин на сервере; удаление kill-switch; каталожный UI-тумблер) — отклонены (ADR D2).

### D3. §114-harness (ответ (c))
- База: `services/summary_test_run.py::run_summary_test` (dry-run) + `build_test_rows`; моки/шпионы LLM и `telegram_send` для публикации/обложки/фолбэка.
- **11/11 сценариев** покрыты ≥1 прогоном; **0 реальных отправок** Telegram (шпионы) — тестовые результаты не попадают в основной чат.
- Артефакты: тест-модуль + чек-лист «сценарий → тест → pass/fail» (R17-safe).
- Опционально — прогон S9-контура «Тестирование» на проде (0 публикаций) как «живое» предполётное evidence.

### D4. §115-процедура и артефакты (ответ (d))
- 7 проверок (Hybrid активен; фильтр; модели L1/L2; промпты; штатный запуск; логи всех этапов; публикация) — см. ADR D4, таблица; наблюдаемость — S7-события/§110-viewer + S8-карта (без новой витрины).
- Артефакты: rich — изображение сверху + настоящий H1; plain — жирный заголовок + абзацы; текст читаем. Evidence — скриншот + R17-safe логи.
- §115 п.5/7 — легитимный первый рабочий прогон (публикует в целевой чат); §114-тесты — не публикуют.

### D5. §117-результаты (ответ (e))
Один документ `plans/features/summary-deploy-round1026/results.md` (T-3470) + merge-раздел ARCHITECTURE (T-3476); 14 пунктов §117 «После Эпика 2» (ADR D5), каждый трассируется к артефактам S1–S10.

### D6. Риск + санкции (ответ (b), (f))
**R2** (обоснование в шапке). **Δ DDL=0**; **Δ каталога=0** (F8 N/A); **CSP/zero-build**; **0 новых зависимостей**; **2-вызовность**; **R17/R18**. §104/§110/§111/S9/routes/db/каталог — не переписываются.

### D7. Deploy/bump/активация/откат (ответ (g))
Тег `pre-round1026-s10` → `76abf91`; `.env.bak.round1026-s10`; bump `APP_VERSION` **2.58.28 → 2.58.29** + `README.md` + cache-bust; порядок «§114 → push (без force) → прод ff → проверка `.env` → рестарт → health → §115»; soft-откат `SUMMARY_HYBRID_L2_ENABLED=false` + рестарт; жёсткий `git revert` + рестарт; VERIFIED = deploy VERIFIED + §115 7/7 + effective ON; live-приёмка публикации — владелец; теги/бэкапы не удаляются (R18).

### D8. §116-приёмка, §85-UI, ownership
§116 (15 критериев) — обязательный чек-лист приёмки (SC-11). §85-UI — отдельная санкция (Δ каталога ≠ 0), в S10 запрещены правки каталога/новые UI-тумблеры/F8-переиздание. Ownership: §114 — @Builder/@Reviewer; §115 — @Builder/@DevOps + владелец; §117 — @Architect/@PM; риск/откат — @DevOps; трассируемость/архив — @PM. @Scanner не создаётся (единый Reviewer gate).

## 5. Наблюдаемое поведение

- **До деплоя (baseline 2.58.28):** `SUMMARY_HYBRID_L2_ENABLED=false` по умолчанию → `_run` идёт в legacy `_generate_two_call`.
- **После деплоя 2.58.29:** default ON → `_run` резолвит `hybrid=True`, идёт в `_run_hybrid_l2`: filter → restore → L1 → пакет → L2 → форматтер → публикация (rich/plain). Ровно 2 LLM-вызова.
- **Явное `false` (`.env`/hot/per-chat):** возврат к legacy-генерации без переписывания кода (аварийный режим).
- **Публикация:** rich — `<img>` → `<h1>` → `<p>`; plain — `<b>title</b>` + абзацы; при отсутствии обложки текст публикуется (§105/S6).
- **Отказы (fail-closed §106):** L1 не usable / пакет не deliverable / L2 не usable / LLM-ошибка → публикации нет; `SUMMARY_FAILED`/`degraded` + `code=`; обложка-провал → публикуется текст; ошибка rich-отправки → plain-фолбэк; без бесконечных повторов. Причина сбоя устанавливаема по логам (§109, `run_id`/этап/модель/host/HTTP-статус/тип/причина/попытки).
- **Фильтр OFF (per-chat/global):** вход L1 не фильтруется (fail-open), публикация не ломается.

## 6. Интерфейсы и контракты

- **env/ClassVar:** `SUMMARY_HYBRID_L2_ENABLED` (default **True** после S10; env-override; hot non-catalog `flags.summary_hybrid_l2_enabled`; per-chat override), `SUMMARY_FILTER_ENABLED` (default True, каталожный `flags.summary_filter_enabled`), `SUMMARY_L1_BASE_URL/MODEL_NAME/API_KEY`, `SUMMARY_L2_BASE_URL/MODEL_NAME/API_KEY` (env-only; пусто → глобальная модель; секреты не логируются).
- **Резолв режима:** `SummaryGenerator._hybrid_l2_enabled(chat_id)` → bool; fail-safe `False` при исключении (сохраняется).
- **Роутинг L1/L2:** независимые резолверы `services/summary_l1_clusterizer.py`/`summary_l2_writer.py` (hot-first `models.summary_l1_*`/`models.summary_l2_*`).
- **§114-harness:** `run_summary_test(chat_id, window, *, allow_cover=False, correlation_id=None, generator=None, pg=None)` → `TestRunResult` (`publication = not_published/dry_run`); шпионы `services.telegram_send`.
- **Наблюдаемость:** события `SUMMARY_*`/`FILTER_*`/`L1_*`/`L2_*`/`FORMAT_*`/`COVER_*`/`PUBLISH_*` (`services/summary_run_log.py`); `run_id`=`correlation_id`; S8 `ExecutionGraph` (узлы filter/l1_clusterizer/l2_writer/formatting/publication).
- **БД/DDL:** без изменений (Δ DDL=0).
- **Совместимость:** per-chat/hot/env-резолв байт-в-байт; меняется только default. OFF-путь доступен как legacy при явном OFF.

## 7. Acceptance scenarios (SC-01…SC-18)

| SC | Проверка (observable) | REQ | ADR |
|---|---|---|---|
| SC-01 | После деплоя effective `_hybrid_l2_enabled` = True по умолчанию; `_run` уходит в `_run_hybrid_l2` без ручного действия (unit + §115 п.1) | 01, 03 | D2, D7 |
| SC-02 | В diff/UI нет теневого режима, поэтапного rollout, Legacy↔Hybrid-селектора, нового режимного UI | 02 | D1, D2 |
| SC-03 | Нет code-пути, требующего ON-действия; `.env` не пинит `false`; фича не остаётся выключенной | 03 | D2, D7 |
| SC-04 | `SUMMARY_FILTER_ENABLED` default True; фильтр активен (per-chat резолв) | 04 | D2 |
| SC-05 | Слоты `SUMMARY_L1_*`/`SUMMARY_L2_*` резолвятся независимо; «не выбрано» → глобальная модель | 05 | D2 |
| SC-06 | §114-harness выполнен **до** деплоя; evidence приложено | 06 | D3, D7 |
| SC-07 | Все 11 сценариев §114 покрыты ≥1 прогоном; 0 реальных отправок | 07 | D3 |
| SC-08 | Тестовые результаты не опубликованы в основной чат (0 sends); деплой — после проверки | 08 | D3, D7 |
| SC-09 | §115 7/7 проверок с evidence | 09 | D4 |
| SC-10 | rich: изображение сверху + настоящий H1; plain: жирный заголовок + абзацы; текст читаем | 10 | D4 |
| SC-11 | 15 критериев §116 «не завершён» не нарушены (чек-лист) | 11 | D8 |
| SC-12 | 14 пунктов §117 присутствуют и трассируемы | 12 | D5 |
| SC-13 | Δ DDL=0; Δ каталога=0 (F8 N/A); CSP/zero-build; 0 новых зависимостей; 2-вызовность; R17; R18 | 13 | D6 |
| SC-14 | §104/§110/§111/S9 не тронуты; §85-UI вне S10; активация — только существующими рычагами | 14 | D1, D8 |
| SC-15 | Откат: тег `pre-round1026-s10`→`76abf91`; soft-OFF работает; `git revert` задокументирован | 03, 13 | D7 |
| SC-16 | Регресс: pytest ≥9000/0; JS ≥47/47; `git diff --check`=0 | 13 | D6, D7 |
| SC-17 | Risk-Level R2 зафиксирован с условиями повышения до R3 | — | D6 |
| SC-18 | Live-приёмка публикации — за владельцем; VERIFIED-критерии определены | 09, 10 | D4, D7 |

## 8. Стратегия тестов / деплоя / активации / отката

- **Тесты:** §114-harness (11 сценариев) + тесты активации (default ON; аварийный OFF; per-chat/hot резолв; роутинг L1/L2; фильтр ON) + §116-проверки + §117-артефакты; полный регресс pytest ≥9000/0; JS ≥47/47; `git diff --check`=0.
- **Деплой:** §114 → commit/push (без force) → прод `git pull --ff-only` → проверка `.env` → `systemctl restart` → `/api/health` 200 / `/healthz` = 2.58.29 / `database is locked`=0 / Traceback·ERROR=0.
- **Активация:** code-default ON; фича **не остаётся выключенной**; effective ON подтверждён §115 п.1.
- **Откат:** soft — `SUMMARY_HYBRID_L2_ENABLED=false` + рестарт; hard — `git revert` + рестарт / `git checkout pre-round1026-s10`; теги/бэкапы не удаляются (R18).
- **VERIFIED:** deploy VERIFIED + §115 7/7 + effective ON; live-приёмка качества публикации — владелец.

## 9. Санкции / безопасность / приватность

- **Δ каталога = 0** — санкции нет; `param_catalog.py` вне diff; F8 не переиздаётся (N/A). **§85-UI — отдельная санкция (Δ каталога ≠ 0), вне S10.**
- **Δ DDL = 0**; **CSP/zero-build**; **0 новых внешних зависимостей**; **2-вызовность**.
- **R17:** логи/события/ошибки — числа/коды/id/host/HTTP-статус/тип/причина/попытки; без ключей/промптов/сырых текстов/сырых ответов; секреты L1/L2 не логируются.
- **R18:** теги/бэкапы не удаляются.

## 10. Зависимости и ownership проверок

- **Зависимости:** S1–S9 ✅; гейт D4 ✅ (24.09.2026); baseline @DevOps T-3461 (параллельно).
- **Ownership:** §114-harness — @Builder/@Reviewer; §115 — @Builder/@DevOps + владелец (live); §117 — @Architect/@PM (T-3470); deploy/rollback — @DevOps; сверка/трассируемость/архив — @PM (T-3463/T-3477/T-3480); merge/ADR-Accepted — @Architect (T-3476); единый Reviewer gate (линзы 1+2) — @Reviewer (T-3474/T-3475). @Scanner не создаётся.

## 11. Закрытые вопросы Step 1 (a)–(g)

| # | Вопрос | Решение |
|---|---|---|
| (a) | Механика активации §107 | **D2**: code-default OFF→ON; слои сохраняются как аварийный kill-switch; «ручная активация» запрещена, «аварийное выключение» разрешено |
| (b) | Риск R2/R3 | **D6**: **R2** (условия повышения до R3 зафиксированы) |
| (c) | §114-harness | **D3**: reuse S9 dry-run + моки/шпионы; 0 публикаций в основной чат; 11/11 |
| (d) | §115-процедура | **D4**: 7 проверок + артефакты rich/plain; наблюдаемость S7/S8 |
| (e) | §117-состав | **D5**: `results.md` (T-3470) + merge-раздел; 14 пунктов |
| (f) | §85-UI | **D8**: отдельная санкция (Δ каталога ≠ 0), вне S10 |
| (g) | Deploy/откат | **D7**: тег `pre-round1026-s10`→`76abf91`; soft-OFF + `git revert`; bump 2.58.29 |

## 12. Артефакты и evidence

- `spec.md`, `adr-1026-12-summary-deploy-activation.md` (этот шаг); `tasks.md` (Step 1, сверка @PM T-3463).
- §114: тест-модуль + чек-лист сценариев.
- §115: `deployment.md` (VERIFIED) + R17-safe логи + скриншот публикации.
- §117: `results.md` + merge-раздел `plans/ARCHITECTURE.md` (ожидается §81).
- Откат: annotated-тег `pre-round1026-s10` → `76abf91`; `.env.bak.round1026-s10`; `var/backups/s10-round1026-*/`.
