# REL-258124 — независимое релизное ревью 2.58.124 (read-only)

Дата: 24.10.2026. Лейн: REV-REL-258124.
Кандидат: `39a06b88` (2.58.124), tip с evidence `c6290ca1`; база `6e587696` (2.58.123, задеплоен).
Ревьюер не менял код, карты, `plans/current_task.md`, `workflow_state.md`, прод/SSH.

## Вердикт

**Approved for controlled deployment, parent not DONE.** Код-блокеров нет; деплой `39a06b88` допустим.
Parent нельзя закрывать: (1) строки ADDENDUM #3 в карте не привязаны (все PENDING, candidate_commit = `c128675a`);
(2) live-проверки ниже ещё не выполнены.

## Состав и целостность

- `6e587696..39a06b88` = ровно 5 коммитов: `f00050a5` (quotes A/B), `42657294` (quota A1–A6), `4df74a81` (UI-cleanup), `58b1bcca` (A7/F2 fix), `39a06b88` (bump).
- Cherry-pick не меняет поведение: итоговые `services/style_policy.py`, `prompt_composer.py`, `prompt_style_blocks.py`, `mca_expression.py`, `mca_gates.py`, `web/api/speech.py`, `web/app.js`, `web/index.html`, `AGENTS.md` **байт-в-байт** совпадают с проверенным master (HEAD), кроме `prompt_registry.py` (там различие только в 2 revision-метках от более позднего master; FACTORY_SET не менялся) и `settings.py` (номер версии).
- Bump: 31 файл, изменения — только версионные токены/версионные assert-строки; non-version правок нет (проверено независимо).
- `ΔDDL=0`: в диффе нет ни одного `CREATE/ALTER/DROP/INDEX`; файлов схемы нет.
- Оба evidence-файла в дереве релиза (`quota-removal.md`, `quotes.md`) содержат старую привязку кандидата (`2156b796` / `141e1e49`), т.к. docs-коммиты `894ec53c`/`20eac02d` не пикались. Это документация, не код; корректная привязка — в README `c6290ca1`.

## Acceptance ledger

| Пункт | Статус | Доказательство |
|---|---|---|
| Состав 4 пика + bump | VERIFIED | `git log 6e587696..39a06b88`, поблочное сравнение файлов с master |
| A1–A6 вытеснение/`budget_excluded`/env-квота | VERIFIED | диффы композера/gates; `SKIP_REASONS` без причины; `_BUDGET_LAYERS` нет |
| A7 owner-note (`note[:2000]`) | VERIFIED | `normalize_expression` без обрезки; REGRESSION-тест 3614 симв. прошёл |
| F2 `no_quotes` = одно правило | VERIFIED | `addStylePreset` сворачивает quotation_marks; node-тест в `test_quotes_modes.py` (30 passed) |
| B сохранено | VERIFIED | `model_capacity`/`CHAT_CONTEXT_BUDGET_TOKENS`, `max_tokens`, retry/fallback/таймауты, rate limits, выборки, «Бюджеты» не в диффе |
| Новых квот инструкций нет | VERIFIED | в диффе только удаления; `budget_chars` в hint без прод-вызова; AGENTS.md §2.10 добавлен |
| Кавычки A/B/OFF, protected, UI, миграция, no_quotes | VERIFIED | код + 30 CONTRACT; UI-файлы идентичны проверенным; визуальное evidence переиспользовано |
| Guards | VERIFIED | локально: quotes 30 + quota 8 = 38 passed; asap3 8 + parity 13 = 21 passed; evidence: pins24 868 passed (артефакт), factcheck 28, checkup 16, telemetry 13, F8 CHECK OK, bump 31/33, js 99/0, py_compile 44/0 |
| Payload/окно, нет тихого обрезания инструкций | VERIFIED (код) + READY_FOR_LIVE (замер) | инструкции не режутся: композер без квот; `context_middleware` режет только data-блоки; capacity-allocator вытесняет P3→P2→P1 контекст, не system; усечение в Inspector-логе помечается `truncated`; `llm_client` не менялся |
| Откат | VERIFIED | `6e587696` (2.58.123, подтверждён deploy-доказательством REL-258123) и второй — `c128675a` (2.58.122); ΔDDL=0 |
| Postdeploy-проверки | READY_FOR_LIVE | чек-лист ниже + rollback |

## Риск роста payload

Локальных квот инструкций не осталось, поэтому payload закономерно вырос. Тихого обрезания инструкций в кодовом пути нет; реальное переполнение ведёт себя как раньше: capacity-allocator режет **контекстные данные** с явной деградацией, `model_capacity`/`CHAT_CONTEXT_BUDGET_TOKENS` не тронуты. Обязательный live-замер (токены полного system, отсутствие context-overflow/деградации на боевой модели) — postdeploy, не может быть доказан до деплоя.

## Блокеры

Код-блокеров нет. Для финального закрытия задачи (не для деплоя):

1. **PROCESS — карта ADDENDUM #3 не привязана.** `requirements-map.json`: `candidate_commit = c128675a`, все `REQ-ADD3-*` = PENDING; slice-graph ссылается на несуществующие имена тестов. Формальный `check --stage review` не пройдёт. Действие: PM/Orchestrator.
2. **POSTDEPLOY** — выполнить чек-лист ниже, затем `--stage release` с фактическим SHA.

## Postdeploy (обязательно)

1. `healthz` → `2.58.124`; сервис active, NRestarts 0; tracked dirty 0.
2. Кавычки: A (default) — «…» → "…"; B (пресет/чекбокс) — удаление «» и "; OFF — текст байт-в-байт; save→reload сохраняет один правило; код/JSON/URL/литералы не меняются.
3. Инструкции: в preview/live manifest нет `budget_excluded`; `style_policy_hint`, expression, Core присутствуют; включённый hint с >1200 токенами доходит целиком.
4. Core: при `detail_level=full` — `core_detail=full:owner_setting`, причины `context_budget` нет; Core не понижается.
5. FREQUENT: остаётся честный PARTIAL (3/6 free-length + 1/4 micro), **не** объявлять DONE/MAIN-CRITERION закрытым.
6. После рестарта квоты не вернулись: `COMPOSER_LAYER_BUDGET_TOKENS` игнорируется, `composer_additive_budget_tokens` отсутствует, `budget_excluded` не появляется.
7. Замер payload/окна: размер полного system и отсутствие деградации/context-overflow на боевой модели; при аномалии — откат.

## Визуальная проверка

Новый прогон браузера в этом лейне не делался (лимит времени). Переиспользовано evidence REV-QUOTA-QUOTES и QUOTA-QUOTES-FIX: Playwright 390×844/1280×900 + Browser Use после фикса; `web/index.html` и `web/app.js` в релизе байт-в-байт равны проверенным. Postdeploy UI-шаг 2 остаётся обязательным на живом инстансе.

## Откат

- Основной: `6e587696` (2.58.123) — тот же код, что задеплоен REL-258123, + docs.
- Дополнительный: `c128675a` (2.58.122) — если 2.58.123 окажется непригоден.
- ΔDDL=0, миграций/данных нет; FACTORY_SET `47f0d1eb8de4` не менялся.

## Замечания (non-blocking)

- `workflow_state.md` в шапке всё ещё указывает прод 2.58.122, тогда как deploy-доказательство REL-258123 фиксирует 2.58.123 live — Orchestrator должен сверить шапку (файл вне моего write-scope).
- Косметика: `mca_sample_library.py:68` ссылается на удалённую константу; комментарий «≤4» в `mca_expression.py`; мёртвые подписи `budget_excluded`/`context_budget` в `web/app.js`.
- C1 `chat_style_anchor_max_chars` (400) и C6 `instruction[:500]` классифицированы как B (данные/модельный repair, не owner-инструкции) с обоснованием в `quota-quotes-fix.md`; принимаю классификацию, но решение остаётся за PM/Architect.
- `SampleWrite` `max_length` (2000/4000) — валидация входа API, не рантайм-обрезка; видимая, не блокер.

## Следующее действие

DevOps: деплой `39a06b88` (не `c6290ca1`), затем чек-лист postdeploy и `--stage release`. PM: привязать карту ADDENDUM #3 к фактическому кандидату/доказательствам до объявления parent DONE.