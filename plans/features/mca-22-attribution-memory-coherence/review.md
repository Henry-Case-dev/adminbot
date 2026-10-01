# `mca-22-attribution-memory-coherence` — review (Step 3 Build + fix round-1)

- **Feature-ID:** `mca-22-attribution-memory-coherence`
- **Risk-Level:** R3 (ратифицирован в spec; подтверждён ревью — сквозной read-path, память, freshness)
- **Status: Approved** — финальный статус (Round 2, 02.10.2026): все 4 blocking findings round 1 (M-1…M-4) RESOLVED, дельта верифицирована независимо (см. секцию «Round 2» ниже). Релиз фичи — за плановыми гейтами T-4317 (Browser-Verification UI, обязателен по spec) / T-4319 (prod-acceptance §37) / T-4320/T-4321.
- **История:** Round 1 (Step 3 Build, PARTIAL) — `Needs Fixes` (1 requirement-blocking Medium M-1, гигиена M-3, honesty M-2/M-4; 0 C/0 H); полный отчёт round 1 сохранён ниже без изменений.

## Binding

| Параметр | Значение |
|---|---|
| `Reviewed-Commit` | `7a86179688628bd060b47014db8bdec837de694c` (HEAD master; docs-only архив хотфикса 2.58.43) |
| `Working-Tree-Hash` | `46621E4601BB590819EE643E6F9BE641AAD644E902590055A33669C784E68310` — SHA-256 манифеста скоупа фичи: 28 файлов (15 изменённых product/tests + 8 новых product/tests + 4 артефакта фичи), формат `path|size|sha256`, sorted, LF. Чужой/служебный WIP вне манифеста: `plans/backlog.md`, `plans/metrics.md`, `plans/workflow_state.md`, `plans/reports/full_audit_results.md`, `plans/docs/mca-round1027-arch-frames.md` (фазы planning/прежних сессий), `node_modules/`, `package*.json`, `.playwright-mcp/`, `extra_images/` — зафиксированы, в ревью кода не входят |
| `Spec-Hash` | `C4B4043E334373A40C6867CB0B1208516EBC6EE29840B2F65016992ABA5B192E` — воспроизведён независимо ✅ (совпадает с заявкой и ADR-анкером) |
| ADR-1028-6 | `6C8E82E5157A663CD63BFE86D5D95CE994DAC09B340A9FB7077ACCB1E8276EF3` ✅; D1–D10 на месте |
| tasks.md | фактический `1667FDD3421D79DA771BB3EFECB75E3E13BE07975991AA33A6A536C32E04DE60`; заявленный при старте Build `69C90CD8…3FBE4` (evidence.md §шапка) отличается добавлением §16 «Статус Build» — ожидаемый дрейф статусов, определения задач не менялись (сверено по контрольным точкам T-4280/T-4299/T-4315) |
| ТЗ-блок | `plans/current_task.md:15305–16480` — SHA-256 `AD38921237007AC2A9F9A784593B2D3188901AB328985811859D24658D9A660C` воспроизведён байт-в-байт ✅; префикс 1–15302 `E828A092…B6750A` ✅. Полный хэш файла изменился законно: владелец добавил блок ASAP-4 ПОСЛЕ строки 16484 (MCA-22-блок не тронут) |

**Git base и скоуп изменений:** base `7a86179` (spec pin подтверждён; «HEAD 0b1ae9c» в задании устарел — между ними docs-коммиты и уже задеплоенный/заревьюенный хотфикс `f1057db` другой фичи). Инспекция: полный `git diff HEAD` (20 файлов) + 8 untracked product/test файлов + feature-доки; интеграционные кромки `smart_cache`, `provenance`, `thread_chain`, `handlers/direct_chat.py` (entry `handle`), `web/api` bounds.

## Проверки выполнены (17 обязательных)

| # | Проверка | Результат |
|---|---|---|
| 1 | 15 полностью закрытых задач | Верифицированы по коду+тестам: T-4273/4279/4286/4287/4288/4290/4291/4292/4293/4294/4297/4305/4307/4311/4315. Код существует, тесты реальны (71 new passed). Но: T-4287/4288 и T-4290 — с honesty-оговорками (M-2, M-4 ниже) |
| 2 | Честность маркировки частичных | В основном честно (§16/evidence §3 прямо называют незавершённое); 3 overstated-места → findings M-2, M-4, L-2, L-5. Итог: 20 `[x]` (15 build + 5 planning-гейтов), 26 partial, 4 гейта следующих стадий (T-4319/4320/4321/4322) — 20+26+4 = 50 ✅ |
| 3 | Миграция v22 идемпотентна | ✅ `_migrate_bot_outputs_v22`: `CREATE … IF NOT EXISTS` + guard `sqlite_master`, 3 индекса, `user_version` 21→22, реестр `MigrationStep` после v21; тесты create/idempotent/legacy-untouched; single-writer allowlist 141→144 (+3 commit) сходится с телом миграции. PG вне diff (pg_db.py не менялся) ✅ |
| 4 | Canonical envelope / 12 потребителей | DTO `CanonicalMessage` + batch projection (один SELECT, без N+1; batch-карта reply-target'ов), honest-None, render с раздельными слотами reply/quote/forward — ✅ как компонент. Перевод потребителей — НЕ сделан (0 prod-call sites projection; disclosed в §16: переведены retrieval-каналы/bundle/thread_chain частично, остальные 6+ открыты) — честный PARTIAL |
| 5 | Own Output Ledger | ✅ `mca_bot_outputs` по DDL spec §4.1 (поля 1:1), append-only, только delivered, SourceRef `bot_output:<id>`, `self_referential`, в `smart_messages` НЕ пишется (grep-проверка), read: thread_chain TTL-restore + priority-5 + guard. Ограничение: прод-write только `direct_reply` (M-4) |
| 6 | Quote resolver 7 ступеней | Модуль полный: 1/2/4/5/6/7 + ambiguous (2 автора, self-restatement) + sender-никогда-не-автор + короткие фразы не auto-bind. Ступень 3 свёрнута в 1 (родитель известен только через reply-metadata — семантика §5 partial-quote сохранена). **Важно:** `resolve_quote` не вызывается из прод-пути (M-2) |
| 7 | Claim envelope: speaker≠subject | ✅ компонент: C/L/D/I-тесты, запрет fallback subject=sender, gated speech acts, coreference без слияния, валидатор outcomes закрытым набором. Интеграция: реальный прод-гейтинг — только remember-путь (`gate_personal_text_write`); envelope-валидаторы в остальные producers не врезаны (disclosed) |
| 8 | Correction revalidation | ✅ живой путь: фразы-триггеры (детерминированно) → `_run_correction_path` → contradicts-EvidenceLink(tentative)+`conflicting` только provenance-backed фактам; legacy БЕЗ auto-bind (тест); revalidation — существующий `reconstruct_fact_provenance`; «исправлено» не пишется. E-тесты на реальной БД ✅ |
| 9 | Freshness guard | Механика жива: update-dedup identity `(chat,tg,rev,user)`, guard bounded-1 + exemptions + без paraphrase-процессора, lineage R17-safe, события 4/5. **Дефект TTL/связки — M-1** |
| 10 | Kill-switches 4 env-only | ✅ ровно 4 в `KILL_SWITCHES`+`settings` (env-only ClassVar, default ON), аксессоры per-call, инертности (correction инертен при canonical OFF); OFF-паритет покрыт тестами по каждому контуру (projection/bundle-legacy/ledger/dedup/correction/quote/person-edge). В админ-UI не вынесены; каталог Δ=0 (тест) |
| 11 | reason_code +12 | ✅ ровно 12 добавлено, словарь расширен по прецеденту. Замечание: `direct_intermediate_cache_hit` и `bot_output_undelivered_skipped` объявлены, но не эмитятся (L-5; первый — disclosed) |
| 12 | Catalog Δ=0 | ✅ `param_catalog.py` вне diff, тест `test_catalog_delta_zero` зелёный; F8 NOT_APPLICABLE |
| 13 | R17-скан | ✅ чисто: новые/изменённые файлы без секретов/токенов/сырых переписок; логи — только ID/коды/числа; lineage без raw content; trace-эндпоинт admin-only (как существующие beliefs) |
| 14 | Тесты | Полный сьют: **10508 passed / 2 failed** — ровно заявленное; оба failed — якорные bound-тесты round1026, **независимо воспроизведены на чистом HEAD 7a86179 во временном worktree** → pre-existing, не регрессия MCA-22 ✅. Новые наборы 71/71 ✅. JS (webapp_js_unit): **36/36** ✅. Соседние правки тестов аргументированы (mca01 allowlist +3, mca05 tail-mark v22, 2 direct-теста скоупнуты guard-off с внятным объяснением) |
| 15 | Browser-verification (частично закрытый UI) | Handler-level функциональная верификация обоих новых API на fixture-БД с real-обработчиками: trace возвращает роли (author/reply/quote), ledger-запись видна с kind, промах — честная пустая структура, fail-open подтверждён; metrics — 8 полей. Полноценный browser-прогон UI-виджетов/справки НЕВОЗМОЖЕН — UI не построен (web/app.js вне diff; T-4313-UI/T-4317/T-4320 открыты). Обязательство spec «Browser-Verification: REQUIRED (scoped)» переносится на инкремент, где UI появится (обязательный гейт перед release) |
| 16 | Staging-перечень DevOps | Готов — раздел «Staging checklist» ниже |
| 17 | Оценка PARTIAL | Раздел «Оценка PARTIAL» ниже: большинство честно отложено; 4 пункта требуют коррекции маркировки/кода (M-1…M-4) |

## Requirement/evidence coverage

- Цепочка `ТЗ-блок (байт-цел) → spec C1–C8/§4 санкции → tasks 50 → implementation → tests → evidence` сверена; противоречий «спека↔код» не найдено, кроме M-1 (TTL) и honesty-хвостов.
- Санкции соблюдены: ровно 1 DDL (v22), ровно 4 рубильника, +12 reason_codes, Δ каталога 0, PG no-op, merge §109+/ADR→Accepted — отложены на merge-гейт (корректно).
- §36 «mock-only недостаточен»: real DB integration (SQLite-фикстуры через `DatabaseService`/`message_identity`) ✅; real Direct pipeline — частично (guard/dedup/correction на живом пути ✅; quote/envelope на живом пути ✗ — M-2); real SourceRefs ✅ (E-тест, bundle v2); tool-loop fixture — ✗ (T-4300 открыт, disclosed); Browser checks — ✗ (см. #15).

## Focused audit coverage

- Интеграционные швы: `smart_cache` (дедуп-ветки/TTL/flags), `provenance` (SourceRef/EvidenceLink/status — второй контур не создан ✅), `thread_chain` (ledger-walk, родитель tg: продолжение ✅), `mca_retrieval_context` (prior: episode-канал не штрафуется, episodes-first сохранён ✅), `handlers/direct_chat.py` (единственный prod-entry `handle` — dedup покрывает Force/обычный путь ✅), FTS-SELECT расширения аддитивны ✅.
- Отказоустойчивость: все новые модули fail-open (никогда не роняют хендлер), проверено точечным воспроизведением ошибки БД-слоя в trace-эндпоинте (честная пустая структура) и кодом (try/except + WARNING).
- Безопасность: новые эндпоинты за `_require_global_admin`; инъекций нет (параметризованные запросы; FTS match собирается из токенов `[а-яёa-z0-9]+`); R17 чисто.
- Регрессии закрытых MCA-фич: полный сьют + OFF-паритет-тесты + allowlist-конвенции; mca-05 tail-mark и mca01 +3 commit — обоснованы.

## Counterexamples checked (анти-счастливый путь)

1. Повторная доставка update спустя время → **обнаружен дефект**: маркер живёт ~300 с (M-1), а не ≈24h — двойной reply/LLM возможен при поздней редоставке.
2. `CHAT_DEDUP_ENABLED=OFF` (UI-флаг) → update-dedup MCA-22 молча мёртв при включённом собственном рубильнике (M-1).
3. Пользователь цитирует сам себя (self-restatement) → ambiguous, не resolved ✅ (тест).
4. Цитата ≥2 авторов → ambiguous ✅; sender никогда не автор ✅; короткая фраза → не auto-bind ✅.
5. Legacy-факт при коррекции → без auto-bind ✅ (тест на реальной БД).
6. Ledger OFF → thread_chain обрывается как baseline ✅ (тест паритета).
7. Второй совпавший ответ guard'а → отправляется + metric, без loop ✅.
8. Промах trace-эндпоинта / ошибка слоя → honest empty (воспроизведено) ✅.
9. Две личности с одним display name → не сливаются (unresolved) ✅.
10. «Я не говорил X» → rejected/negation_guard ✅.

## Blocking findings

### M-1 [Medium, requirement-blocking, OPEN] — Update-dedup: TTL ~300 с вместо санкционированных ≈24 ч + скрытая связка с `CHAT_DEDUP_ENABLED`
- **Где:** `services/response_freshness.py` (`UPDATE_DEDUP_TTL_SECONDS = 24*3600` — мёртвая константа, никем не читается); `services/smart_cache.py:318–330` (`get_dedup`/`set_dedup`); вызов `services/direct_chat_service.py:1589–1600`.
- **Требование/инвариант:** spec §3-C7/§4.2: «маркер в существующей smart_cache (slug direct_update, **TTL ≈ 24 h**)»; §16: same update → idempotent, не платить дважды за LLM.
- **Наблюдение:** `check_update_seen` читает через `get_dedup`, TTL чтения = `chat_dedup_ttl_seconds` = **300 с** (settings.py:2072); `set_dedup` гейтится флагом `CHAT_DEDUP_ENABLED` (UI-флаг каталога, дефолт ON) — при OFF администратором update-dedup молча не работает, хотя `MCA_RESPONSE_FRESHNESS_GUARD_ENABLED=ON`. truth-set N проверяет мгновенный повтор и дефект не ловит.
- **Impact:** повторная доставка Telegram update позже ~5 минут (webhook-retry/бэклог/сбой доставки) → второй LLM-вызов и второй ответ; тихая деградация инварианта при несвязанном UI-флаге. §37-приёмка «повторная доставка → нет второго reply» пройдёт только в коротком окне.
- **Исправление:** выделить собственный маркер-метод SmartCache с явным TTL-параметром (или использовать `get/set` с ключом `direct_update\x00<hash>` под SMART_CACHE_ENABLED-политикой) и передавать `UPDATE_DEDUP_TTL_SECONDS`; убрать зависимость от `CHAT_DEDUP_ENABLED` (или явно задокументировать и добавить в T-4319 prod-чек: `CHAT_DEDUP_ENABLED=ON`).
- **Верификация фикса:** тест «маркер жив ≥24h, истёк → fresh»; тест «CHAT_DEDUP_ENABLED=OFF не влияет на update-dedup»; обновить docstring `mark_update_seen` (фактически маркировка ДО обработки — семантика at-most-once; задокументировать выбранный трейд-офф).

### M-2 [Medium, honesty/marking, OPEN] — T-4290 `[x]` «полностью»: quote-resolver не вызывается из прод-пути (0 call sites)
- **Где:** `services/quote_resolver.py` (модуль), grep по prod-коду — вызовов `resolve_quote` нет (только тесты); аналогично `get_canonical_messages*`/`format_canonical_envelope` (C1-перевод потребителей — открытые T-4281/4282, это честно disclosed), `build_envelope`/`validate_personal_write` (C4), `validate_person_edge_write` (C5), `read_policy_rank` (C8) — библиотечная готовность без интеграции.
- **Требование:** §36 «mock-only acceptance недостаточен»; narrative evidence/гейтов «quote-priority 5 недоступна при OFF» подразумевает доступность при ON — фактически она недостижима в обоих состояниях.
- **Impact:** карта готовности overstated: читатель `[x]` не видит, что цитата в живом direct-флоу резолвится только ingestion-полем `quote_author_id`, без лестницы/ledger-priority-5/self-quote-семантики. Компонент сам по себе качественный и протестирован — регресса нет.
- **Исправление:** пометить в tasks.md §16 и evidence.md §3: «T-4290: компонент + unit/integration-тесты готовы; прод-интеграция (вызов из direct-пути) — следующий инкремент (T-4281/T-4317)»; в docstring гейта `bot_output_ledger_enabled` скорректировать формулировку. Допустимо оставить `[x]` при явной пометке — решение за Orchestrator/Builder, но скрытым остаться не должно.

### M-3 [Medium, commit-гигиена, OPEN — обязателен к исправлению ДО коммита] — `web/api/memory_agi.py` переписан целиком с CRLF
- **Где:** рабочий файл имеет 1149/1149 строк CRLF; HEAD-версия — pure LF; `core.autocrlf=false`, `.gitattributes` нет.
- **Наблюдение:** реальных изменений 168 строк (2 эндпоинта), дифф же — 1149+/982− (весь файл). Проверено байтовым сравнением и `git diff --ignore-all-space` (168+/1−).
- **Impact:** замусоривание истории/blame, срыв byte-exact WTH-конвенций релизных гейтов проекта (прецеденты re-measure per-file), риск расхождений между окружениями.
- **Исправление:** ренормализовать файл в LF (сохранив 168 строк изменений), перегнать связанный bound-тест. Проверка: `git diff --stat` по файлу ≤ ~200 строк.

### M-4 [Medium, honesty/coverage, OPEN] — Ledger write-path только `direct_reply`: `rich_message`/`media_caption`/`autonomous_reply` объявлены, но в проде не пишутся; truth-set H сидируется фикстурой
- **Где:** единственный прод-writer — `direct_chat_service.py:2427` (`output_kind="direct_reply"`); summary/RichMessage/автономные/подписи не подключены; `tests/...truthset...py:141–145` вручную пишет `rich_message`-строку для кейса H.
- **Требование:** §4/Q15 (виды outputs), DoD-3/§36-4; §16 частично раскрывает (T-4289: «relation Summary-run … витрины нет»), но в `[x]`-задачах T-4287/T-4288 разрыв не назван.
- **Impact:** в живой системе «reply на старую RichMessage» не восстановится — записывать нечего; кейс H валиден только контрактом read-side. До релиза DoD-3 не закрывается.
- **Исправление:** следующий инкремент — врезить `record_delivered_output` в send-пути RichMessage/summary и autonomous (kinds уже поддержаны схемой); пометить в tasks.md §16; при релизе — prod-smoke «reply на старую статью после TTL».

## Non-blocking debt (Low)

- **L-1** `UPDATE_DEDUP_TTL_SECONDS` — мёртвая константа; docstring `mark_update_seen` («после ответа») противоречит вызову (до обработки). Покрыто фиксом M-1.
- **L-2** `RetrievalCandidate.verification`/`contradiction_status` объявлены и никогда не заполняются (2 из 9 полей §10); `revision` message-кандидата = `tg:<id>` (наследие, не MCA-03 revision). Conflict-факты не пессимизируются на retrieval-уровне (read-policy ранг есть, но не врезан). → довести в инкременте T-4297-хвост/T-4302.
- **L-3** tasks.md §16 содержит управляющие символы `\r`/`\t` (рвут слова: «
ead_policy_rank», «	est_tool…», «ormat_canonical…») — гигиена документа.
- **L-4** `plans/workflow_state.md` checkpoint: `review.spec_hash = CC363992…` не совпадает с фактическим spec `C4B4043E…` (устаревший пин дизайн-фазы). Поправить @Orchestrator при следующем checkpoint.
- **L-5** reason-коды `direct_intermediate_cache_hit`, `bot_output_undelivered_skipped` объявлены, но не эмитятся (первый disclosed в §16; точка эмиссии второго — на «вызывающей стороне», которая не написана).
- **L-6** `/memory/attribution/metrics` возвращает 8 из 11 метрик §25 (нет `personal_fact_with_source_ref_rate`, `wrong_subject_truthset_rate`, `retrieval_subject_mismatch_rate`) — T-4314 честно открыт.
- **L-7** Новые тест-файлы оставляют ~34 leaked aiosqlite-соединений (warning при прогоне) — тестовая гигиена (close в teardown).
- **L-8** Ступень 3 лестницы цитат свёрнута в ступень 1 (семантика сохранена, константа `PRIORITY_EXACT_IN_PARENT` не возвращается) — задокументировать в docstring модуля.

## Unavailable checks

- Полноценная browser-верификация UI (Attribution Trace-виджеты, source card, correction trace, справка §38) — UI не существует в этом инкременте (web/app.js вне diff; T-4313-UI/T-4317/T-4320 открыты). Выполнен handler-level прогон API (см. #15). Переносится обязательным гейтом на релизный инкремент.
- Prod-acceptance §37 / T-4319 (включая prod-env гейт-чек) — вне Step 3, за DevOps/владельцем; в чеклист T-4319 добавить `CHAT_DEDUP_ENABLED=ON` до фикса M-1.
- LLM-resolver ступеней 3–4/6 — не подключён (bounded-детерминированный вместо; disclosed §16 T-4284).
- Authenticated TMA-прогон новых эндпоинтов живой обвязкой (`get_tma_user`) — не выполнялся; авторизация — существующая инфраструктура `_require_global_admin` (анкеры в коде подтверждены).

## Оценка PARTIAL (вопрос 17)

**Честно отложено (не блокеры, подтверждено кодом):** перевод потребителей 3/5–10 на projection; tool-loop сохранение ролей (T-4300); previous-answer в контексте (T-4310); `DIRECT_INTERMEDIATE_CACHE_HIT`; полный structure-first рефакторинг `_build_user_content`; UI-виджеты/скриншотный E2E/справка (гейты следующих стадий); dossier live/rebuild единый валидатор; LLM-resolver. Эти пункты прямо названы в §16/evidence §3, не маскируются под готовые и не ломают существующее поведение.

**Требуют действия (findings):** M-1 — дефект в задаче, помеченной `[x]` полностью (T-4307): TTL/связка; M-2/M-4 — коррекция маркировки готовности (T-4290/T-4287/T-4288) и доведение write-path RichMessage/autonomous до релиза; M-3 — гигиена до коммита. Существующая память/данные не затронуты (все Δ аддитивны, backfill отсутствует — соответствует §31).

## Staging checklist (для DevOps, к T-4319)

1. **До рестарта:** backup SQLite `VACUUM INTO` (pre_v22) + read-back; свободное место; PG — no-op (pg_db.py вне diff).
2. **Env-проверка:** нет OFF-override `MCA_CONTEXT_ANSWER_CACHE_ENABLED`; нет OFF-override четырёх новых рубильников; `CHAT_DEDUP_ENABLED=ON` (до фикса M-1 — критично); каталог 488/427/463/105/103/21 (Δ=0), F8 CHECK OK.
3. **Миграция (авто на старте):** `user_version=22`; `mca_bot_outputs` + 3 индекса существуют; повторный рестарт — no-op; данные целы.
4. **Smoke:** direct Q&A → строка в `mca_bot_outputs` (kind=direct_reply); повторная доставка того же update → событие `DIRECT_UPDATE_DEDUP_HIT`, 0 второго ответа; тот же текст новым message → fresh generation (`DIRECT_FRESH_GENERATION`), не replay; коррекционная фраза в чате с provenance-фактом → `conflict_status=conflicting` + contradicts-link + событие; `/api/memory/attribution/trace|metrics` (admin) → 200.
5. **OFF-учения:** `MCA_RESPONSE_FRESHNESS_GUARD_ENABLED=false` → поведение baseline; `MCA_BOT_OUTPUT_LEDGER_ENABLED=false` → ledger не растёт, `bot_replies` как раньше; `MCA_CANONICAL_ATTRIBUTION_ENABLED=false` → старые SELECT/записи.
6. **Откат:** hot — 4 env-рубильника; cold — `git revert` (v22 аддитивен, остаётся безвредно); restore бэкапа — крайний случай.
7. **Наблюдение:** 0 новых ошибок после рестарта; в логах/событиях нет сырых текстов (R17).

## MEMORY_DELTA (для Orchestrator)

- mca-22 Build (PARTIAL) отревьюен: Status **Needs Fixes**; binding: HEAD `7a86179`, WTH `46621E46…E68310`, spec `C4B4043E…` (воспроизведён), ТЗ-блок `ad389212…660c` байт-цел (после него владельцем добавлен блок ASAP-4 — пин полного файла 7025FEF7… устарел законно).
- Блокер M-1: update-dedup TTL фактически 300 с (`CHAT_DEDUP_TTL_SECONDS`) вместо ≈24h, `UPDATE_DEDUP_TTL_SECONDS` мёртвая константа, дедуп связан с UI-флагом `CHAT_DEDUP_ENABLED`; фикс — собственный TTL-маркер + развязка флага + пункт в T-4319.
- Честность маркировки: T-4290/T-4287/T-4288 `[x]` требуют пометки «компонент готов, прод-интеграция/coverage следующим инкрементом» (quote-resolver без call sites; ledger пишет только direct_reply; truth-set H синтетический).
- Гигиена: `web/api/memory_agi.py` — ренормализация CRLF→LF до коммита; tasks.md §16 — управляющие символы; workflow_state review.spec_hash (CC363992…) устарел.
- Пины в силе: 2 known failing bound-теста — pre-existing (воспроизведены на чистом HEAD независимо).

---

# Round 2 — точечная ревалидация fix round-1 (@Reviewer, 02.10.2026)

- **Feature-ID:** `mca-22-attribution-memory-coherence`
- **Risk-Level:** R3 (без изменений)
- **Status: Approved** — дельта-вердикт по 4 blocking findings round 1: **M-1…M-4 RESOLVED (4/4)**, новых blocking не найдено. Round-1 ядро (15 закрытых задач, v22, OFF-паритет, R17) не перепроверялось — одобрено в round 1. Релиз фичи в целом остаётся за плановыми гейтами T-4317 (Browser-Verification UI — обязателен по spec) / T-4319 (prod-acceptance §37) / T-4320/T-4321 — это инкременты того же эпика, не блокеры данного build-состояния.

## Binding (round 2)

| Параметр | Значение |
|---|---|
| `Reviewed-Commit` | `7a86179688628bd060b47014db8bdec837de694c` (HEAD не изменился; коммитов по-прежнему нет, R18) |
| `Working-Tree-Hash` | `F28E59B2AD81ECC29E42A6EB8288B2603F19718884BCC3E72FF64E9D4725D208` — пересчитан независимо по манифесту **33 файла** (20 изменённых product/tests + 8 новых + 5 артефактов фичи), формат `path|size|sha256`, sorted, LF, SHA-256 конкатенации с trailing-LF — **совпал с хэндоффом Builder байт-в-байт** ✅. Самореференсная оговорка (конвенция round 1): манифест включает review.md — пин зафиксирован на момент верификации, ПОСЛЕ записи этой секции review.md — единственный файл манифеста, отличающийся от пина; остальные 32 файла пин покрывает байт-в-байт |
| `Spec-Hash` | `C4B4043E334373A40C6867CB0B1208516EBC6EE29840B2F65016992ABA5B192E` — воспроизведён повторно, не менялся ✅ |
| tasks.md | `E17B0D5A3EFA2751981F466D18132CB8E04C2965F4D096361FE12916E2C93708` — изменился против round-1 пина `1667FDD3…`: §16 переписан по итогам фиксов + добавлен §17 «Fix round-1» (сверено: определения задач T-4287/T-4288/T-4290/T-4307 не тронуты — только статусы/верификация; дрейф того же класса, что принят в round 1) |
| ADR-1028-6 | `6C8E82E5157A663CD63BFE86D5D95CE994DAC09B340A9FB7077ACCB1E8276EF3` — не менялся ✅ |

**Git base и inspected scope:** base тот же `7a86179`. Дельта против round-1 пина: +5 product-файлов фиксов (`smart_cache`, `summary_generator`, `video_download`, `goodmorning_relay`, `dead_page_relay`) + review.md-артефакт; инспектированы хунки фиксов и их швы (permit-жизненный цикл `handle()`, sweep-взаимодействие legacy/маркер-записей в `smart_cache`, порядок «send → ledger» во всех новых write-points, binding-цепочка `setup_summary → bind_default_db`, import-кромка `_qres`).

## Верификация findings round 1 (4/4 RESOLVED — подтверждено кодом, тестами и прогонами)

| Finding | Вердикт | Независимое подтверждение |
|---|---|---|
| **M-1** TTL/связка | **RESOLVED** | `smart_cache.py:41` `_UPDATE_MARKER_SWEEP_TTL=24*3600`; `_sweep_ttl():183–198` учитывает 24h **безусловно** (max) — legacy `set()` с малым SMART_CACHE_TTL не выметает маркеры (per-read TTL истекает записи честно; вытеснение MAX_ROWS — задокументированный компромисс). Новые `get/set_update_marker:359–367` — явный `ttl_seconds`, **нет гейтов** на `CHAT_DEDUP_ENABLED`/`SMART_CACHE_ENABLED`; единственный рубильник — `MCA_RESPONSE_FRESHNESS_GUARD_ENABLED` у вызывающего. `response_freshness.py:87–147` — обе операции через маркер-методы с `UPDATE_DEDUP_TTL_SECONDS=24*3600` (константа теперь живая), docstring честно фиксирует at-most-once. Тесты core:704–758: TTL wired, drift-guard констант, маркер жив >300 c / истекает >24h на TTL-честном fake (legacy-методы сознательно не реализованы — дефект не замаскировать), OFF обоих legacy-флагов не убивает дедуп на реальном SmartCache |
| **M-1-bonus** permit leak | **RESOLVED** | `direct_chat_service.py:1597–1615`: `permit.release():1614` перед `return` dedup-hit; блок стоит ДО `try:`(:1636)/`finally`-release(:2530–2531) — двойного release нет. Регресс-тест `test_direct_chat.py:2970` с ужатым `CHAT_LOCK_WAIT_SECONDS=2`: после dedup-hit следующий новый update того же чата доходит до LLM без lock-wait (до фикса — 2 c ожидания и «занят», assert падает) |
| **M-2** quote-resolver в проде | **RESOLVED** | Call-site реален: v2-ветка `_build_evidence_bundle` `:3787–3801` — metadata-first (лестница только при NULL `quote_author_id`), результат → `quoted_speaker`/`ambiguities:3843–3852`, ledger-реф `bot_output:<id>` → evidence-item label='quote' `:3835–3842`. `_resolve_quote_live:3884–3918` — gate-aware (`canonical_attribution_enabled`), fail-open, `_rowval` защищает отсутствие колонок. Семантический фикс: `exclude_tg_message_id` (`quote_resolver.py:110,116–121,269–272`) исключает триггер из ступени 6 — без него `>`-цитата в самом триггере всегда давала «второго автора» → вырожденный ambiguous; self-restatement по чужим/своим старым сообщениям сохранён. Truthset:334–412 — живой резолв через прод-bundle на real DB (автор «2», не sender), spy-вызов + ledger-реф в evidence, ambiguous → автор не выдумывается |
| **M-3** CRLF | **RESOLVED** | `git diff --numstat` = **168+/1−** (было 1149+/982−); байтовая проверка: **0 CR-байтов** в файле; `git diff --check` — EXIT 0 |
| **M-4** ledger все типы | **RESOLVED** (в заявленном объёме) | `bot_output_ledger.py:37–49,101–105` — binding/fail-open; direct+autonomous: `direct_output_kind:773–778` (`free_will`→`autonomous_reply`), запись после успешной send `:2447–2456`; rich_message ×4 (`summary_generator`: rich :1539, no-cover :1739, plain :1241, plain-fallback :1281 — все после `log_publish_text_complete`/успешной доставки); media_caption ×4 (video_download fast-track :615 + `_send_file` :799, goodmorning :155–169 — запись только на успешной ветке, dead_page :699–713 с явным db). Binding: `setup_summary:120–127 → bind_default_db`, вызов bot.py:432 с db подтверждён. Тесты truthset:419–498 — все kind'и, маппинг, fail-open без binding, прод-wiring plain-публикации. Задокументированные остатки: edit→revision (хвост T-4287), overflow dead-page, alan_greeting |

## Прогоны (независимо воспроизведены)

| Проверка | Результат |
|---|---|
| Полный pytest `tests -q --timeout=120 --tb=no` | **10520 passed / 2 failed** за 320.98 с — ровно заявленное; оба failed — те же два pre-existing bound-теста round1026 (`test_tool_coordinator_round1026::TestBounds::test_forbidden_paths_out_of_diff`, `test_unified_image_request_round1026::…vs_baseline`), их чистый-HEAD-статус независимо установлен в round 1 на том же HEAD `7a86179` — пин в силе |
| Новые/затронутые наборы | **243 passed**: core 58 + truthset 24 + test_direct_chat **161** (evidence называет «160/160» — косметическая недоточенность на +1 новый регресс-тест; не влияет на вердикт) |
| JS | `test_webapp_js_unit` **36/36**; скриптов `tests/js/*_test.js` в дереве — **52** (остальные зелёные в составе полного сьюта) |
| F8 | `gen_param_registry_round1025.py --check` → «CHECK OK: реестр 488», **EXIT=0** |
| WTH | Пересчитан независимо — `F28E59B2…D208`, 33 файла, byte-exact совпадение с хэндоффом |

## Counterexamples checked (round 2, анти-счастливый путь)

1. Редоставка того же update спустя >5 мин (старый дефект-окно) → маркер жив, dedup-hit, 0 LLM (TTL-тест 301 c) ✅
2. `CHAT_DEDUP_ENABLED=OFF ∧ SMART_CACHE_ENABLED=OFF` → update-dedup работает на реальном SmartCache ✅
3. Dedup-hit → следующий новый update того же чата доходит до LLM без lock-wait (слот возвращён; lock-wait 2 c) ✅
4. Двойной release permit невозможен структурно (dedup-return до try/finally) ✅
5. Малый `SMART_CACHE_TTL_SECONDS` не выметает 24h-маркеры (sweep max БЕЗУСЛОВНО) ✅
6. `>`-цитата в самом триггере → резолв автора из истории, а не вырожденный ambiguous (exclude триггера, real DB) ✅
7. Ambiguous (≥2 авторов) → `quoted_speaker=None`, маркировка в `ambiguities` — автор не выдуман ✅
8. Ledger без binding/gate OFF → честный skip, без скрытых хранилищ ✅
9. Неуспешная send (goodmorning exception) → записи нет (return до record); недоставленное ≠ слова бота ✅
10. Summary plain-публикация → строка `rich_message` с correlation_id рана и searchable-текстом (прод-wiring на real generator) ✅

## Non-blocking debt (round 2, поверх round-1 Low)

- **N-1** Решение по `alan_greeting` (запрос Builder'а): **неписание одобряю** — фиксированный тег-упоминание, не содержательный вывод бота; запись создавала бы шум в ledger без read-side пользы. Зафиксировать решение в хвосте T-4287.
- **N-2** Overflow-текст dead page (plain-продолжение после подписи) доставляется, но не пишется в ledger — узкая ветка, disclosed; bounded follow-up в T-4287-хвост.
- **N-3** Edit→revision-строка ledger не врезана (правка собственного сообщения бота) — spec C2-требование, сознательно отложено в §16/§17; остаётся в T-4287-хвосте **до релиза** (не блокер данного состояния, обязателен к закрытию в UI-инкременте вместе с T-4317).
- **N-4** Evidence-счётчик «test_direct_chat 160/160» → фактически 161 (косметика отчёта).
- Round-1 Low L-1…L-8 — без регресса; L-5 (`bot_output_undelivered_skipped` без точки эмиссии) остаётся: новые writers просто не вызывают запись при неуспехе (событие не эмитится — то же состояние, не хуже).

## Staging checklist — поправка к round 1

Пункт 2 round-1 чеклиста «`CHAT_DEDUP_ENABLED=ON` (до фикса M-1 — критично)» **более не критичен для update-dedup** (развязка флагов зафиксирована тестом). Оставить проверку флага в T-4319 можно только ради legacy text-дедупа при `MCA_CONTEXT_ANSWER_CACHE_ENABLED=OFF` (политика Q13) — не как условие идемпотентности update'ов. Остальные пункты чеклиста round 1 в силе.

## Unavailable checks (round 2)

- Без изменений относительно round 1: browser-верификация UI/справки (UI не построен; обязательный релизный гейт T-4317/T-4320), prod-acceptance §37/T-4319, authenticated TMA-прогон, LLM-resolver ступеней 3–4/6 (disclosed).
- Round-2 специфичное: недоступного нового не появилось — все заявленные фиксы покрываются кодом, тестами и воспроизведёнными прогонами; работа велась в PowerShell/pytest-окружении без browser-слоя (не требовалась для дельты).

## MEMORY_DELTA (round 2, для Orchestrator)

- mca-22 fix round-1 отревьюен (дельта): **M-1/M-2/M-3/M-4 RESOLVED 4/4**; Status **Approved** (build-состояние; релиз фичи — за плановыми гейтами T-4317 Browser-Verification + T-4319 prod-acceptance + T-4320/4321).
- Binding: HEAD `7a86179` (не менялся), WTH `F28E59B2AD81ECC29E42A6EB8288B2603F19718884BCC3E72FF64E9D4725D208` (33 файла, воспроизведён независимо, совпал с хэндоффом), spec `C4B4043E…` (не менялся), tasks.md `E17B0D5A…` (§16/§17-статусы; определения не тронуты).
- Прогоны: полный pytest **10520/2** (оба failed — pre-existing round1026, пин round 1 в силе); 243/243 новых/затронутых; JS 36/36 (52 скрипта); F8 EXIT=0.
- Решения Reviewer: alan_greeting в ledger НЕ писать (тег-упоминание); overflow dead-page и edit→revision — bounded follow-up в T-4287-хвосте; `CHAT_DEDUP_ENABLED` больше не критичен для update-dedup (поправка staging-чеклиста).
- Пин round-1 WTH `46621E46…` устарел законно (скоуп +5 файлов фиксов + review.md).
