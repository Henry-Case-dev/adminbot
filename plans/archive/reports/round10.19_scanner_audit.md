# Отчёт @Scanner — раунд 10.19, БАТЧИ A–E + итог эпика (ШАГ 6 OpenSpec, Strict Workflow)

> **Сканер:** @Scanner (независимый diff-аудит логических ошибок). **Дата:** 15.09.2026.
> **Baseline HEAD:** `fd6acc7` (docs-синхронизация 10.18, COMPLETED+DEPLOYED) + рабочее дерево; прод — `16a8c0b`.
> **Объём:** незакоммиченный `git diff` + untracked — **БАТЧ A:** F1 `betterstack-ingest-bearer-contract`
> (T-1778…T-1789) + F8 `graphrag-memorize-robustness` (T-1845…T-1853); **БАТЧ B:** F2
> `direct-chat-budget-unlimited` (T-1789/T-1853…T-1798) + перенос фиксов Батча A (см. §7).
> **Режим:** код НЕ правился; искались реальные баги/риски/регрессии (не стиль и не спек-комплаенс — это @Reviewer).
> **Метод:** `git diff`/адресные чтения `file:line` + grep всех call-sites (`insert_graph_fact`, `parse_fact_list`,
> `_metric_limit`, `_budget_limit_*`, `hot.get(…budget…)`, `budget_limits.`, `LOGTAIL_SOURCE_TOKEN`) +
> инструментальные пробы (полный pytest, JS-гейты, `git diff --check`, интроспекция каталога, разбор
> opener/redirect-обработчиков CPython, сентинел/каст-проба, перф-проба `graph_snapshot` на синтетике 15k рёбер,
> семантика ×2 fast-path).
>
> **⏱ Сводки по батчам (0 Critical везде):**

| Батч | Фичи | Итог | Валидатор | Секция |
|---|---|---|---|---|
| A | F1 betterstack-ingest-bearer-contract + F8 graphrag-memorize-robustness | 0 High / 0 Medium, 2 Low + 4 Info | 6164/0 | §0–§6 |
| B | F2 direct-chat-budget-unlimited (+ перенос фиксов A) | 0 High / 0 Medium, 2 Low + 4 Info; закрыты S10.19-1/-2 + S10.18-30/-35/-36 | 6195/0 | §7 |
| C | F3 budget-settings-section | 1 High (S10.19-13) + 1 Medium + 1 Low; закрыты S10.19-7/-8 | 6232/0 | §8 |
| D | F4 direct-context-limit-expansion + F5 status-section-ui-merge | **0 High / 0 Medium** (S10.19-13 High и S10.19-14 Medium — CLOSED, проверено независимо) + 1 Low + 7 Info | 6262/0 | §9 |
| E | F6 media-files-avatars-sync + F7 memory-retention-health | 0 High / 0 Medium, 1 Low + 6 Info | 6323/0 | §10 |

> **ИТОГ ЭПИКА 10.19:** открыто 0 Critical / 0 High / 0 Medium; 2 Low (S10.19-15, S10.19-23) + 1 Low из 10.18
> (S10.18-29) + 16 Info → **эпик готов к Merge/архивации и двухэтапному деплою** (итоговая сводка §10.4,
> обязательные @DevOps-гейты §10.5).

## 0. Сводка

| Severity | Кол-во | Коды |
|---|---|---|
| **Critical** | **0** | — |
| **High** | **0** | — |
| **Medium** | **0** | — |
| **Low** | **2** | S10.19-1, S10.19-2 |
| **Info** | **4** | S10.19-3, S10.19-4, S10.19-5, S10.19-6 |

Обе фичи батча реализованы по своим ADR и включают ревью-фиксы: **F1** — официальный ingest-контракт
(`POST https://{host}` + `Authorization: Bearer`, токена в path нет), редиректы запрещены (`_NoRedirectHandler`,
3xx = отказ без повтора и без форварда токена), `_HINT_401` → словарь `_STATUS_HINTS` (401/402/403/406),
ложный WARNING «token == SENTRY_DSN public key» понижен до DEBUG; **F8** — `parse_fact_list_ex` со статусами
`ok/empty_valid/invalid`, восстановление после `LLMError` первичной экстракции (fallback + ровно 1 retry),
единый rate-limited WARNING (`_log_memorize_lost`) с bounded-словарями (D-06) и сентинелом `None` (D-07),
`invalid` включает D-08-подслучай (валидный список без годных фактов).

Полный прогон: **6164 passed / 0 failed** (71.98 c); JS-гейты OK; `git diff --check` exit 0; каталог
**436/406/411/90/88/19** (Δ батча = 0); SQLite v10 (DDL в батче нет).

## 1. Находки

| ID | Sev | File:line | Суть | Рекомендация |
|---|---|---|---|---|
| S10.19-1 | Low | `services/summary_memory.py:602,1889-1891` | **F8: валидный `[]` стал невидимым на прод-уровне логов.** До батча путь «модель вернула пустой список» заканчивался `logger.info("graphrag memorize: 0 facts \| chat_id=…")`; теперь `empty_valid` логируется только `debug` (в `parse_fact_list_ex:602` — «valid empty fact list», в `_memorize_facts_inner:1889` — «empty valid list (no facts)»). При дефолтном root=INFO в прод-`journald` кейс «пустой список» **снова невидим** — а это ровно исходный симптом владельца (ADR-1019-7 Context §11: «graphrag … скипает, потому что пришёл не json, а **пустой список**»). Невалидный ответ теперь WARNING (хорошо), пустой — тише, чем было. | Либо вернуть `INFO` для `empty_valid` (rate-limited как `_log_memorize_lost`), либо вести агрегированный счётчик пустых ответов (`empty_total` в том же bounded-состоянии) и логировать его раз в окно — иначе «скипает молча» остаётся объяснимым только при DEBUG. |
| S10.19-2 | Low | `plans/ARCHITECTURE.md:687`; `README.md:1046` | **Доки F1 не приведены «в чистовую» (заявлено D-03).** В §687 (10.18 F1) тело пункта по-прежнему утверждает: «`_url = https://{host}/{token}`, token — в path, без Bearer», «при совпадении WARNING на старте», маркер «…\| last4=XXXX \|…» — корректно только по хвостовой пометке `[10.19/F1 AMEND …]` (для сравнения §215 переписан inline). Плюс `README.md:1046` заявляет как факт «после перехода (10.19/ADR-1019-1) 401 уходит», тогда как живой curl-матрикс (T-1779, @DevOps) ещё не выполнен. | Переписать §687 inline (как §215): убрать path-token/`last4`/WARNING-про-public-key из тела, оставить AMEND-ссылку; в README — «ожидается (проверяется T-1779)» вместо утверждения. |
| S10.19-3 | Info | `services/summary_memory.py:195-198,1861-1866` | **`reason=not_json` неточен для D-08-подслучая.** `_memorize_reason` различает лишь «пусто/непусто», поэтому структурно валидный JSON-список, где все элементы отсеяны `_validate_fact` (промпт-дрейф), попадает в лог как `status=invalid \| reason=not_json` — хотя JSON был валидным. Диагностика не отличает «модель вернула мусор» от «вернула негодные записи». | Добавить четвёртый reason (`no_valid_facts`) для ветки «список валиден, годных 0» (ADR D4 перечисляет три кода — расширение аддитивно и упрощает разбор journald). |
| S10.19-4 | Info | `services/betterstack_handler.py:298-330` | **Все 4xx (включая 429) и 3xx → батч (≤500 событий) отбрасывается, без re-buffer.** События не возвращаются в буфер и не ретраятся (по ADR D3/D5 — осознанно), остаются лишь `failed += n` + rate-limited WARNING; при 429 (rate limit BetterStack) это документированная потеря логов, видимая только в счётчике/journald. | Принято ADR; для @DevOps — в live-проверке (T-1779) отдельно смотреть `failed/dropped` и отсутствие spam-429; при необходимости — follow-up: re-buffer 429 с backoff (вне батча A). |
| S10.19-5 | Info | `services/summary_memory.py:1781-1790` | **Верхний `except LLMError` в `memorize_facts` фактически недостижим и вводит в заблуждение.** После F8 `LLMError` первичной экстракции и retry ловятся внутри `_memorize_facts_inner`, `_embed`/`_save_graph_fact_embedding` — внутри per-fact `try/except Exception`; сообщение «facts lost after recovery (unexpected LLMError)» при срабатывании могло бы сказать «потеряны» уже после успешной записи фактов. | Оставить как defensive-страховку, но переформулировать («unexpected LLMError after recovery path»), либо явно пометить комментарием «недостижимо при штатной работе». |
| S10.19-6 | Info | `scripts/betterstack_host_token_probe.py:60-80` | **`path`-режим пробника кладёт РЕАЛЬНЫЙ прод-токен в URL** (`https://{us\|eu}/{token}`) для сравнения контрактов — по ADR D6 это ручная диагностика @DevOps с маскированным выводом; в URL токен может осесть в access-логах промежуточных узлов, а `path`-запрос на EU-хост заведомо 401. | Принято ADR D6 (evidence для root cause); убедиться, что скрипт не запускается из CI/крона, и в отчёте T-1779 фиксировать только коды (как и заявлено). |

## 2. Детали ключевых находок

### S10.19-1 (Low) — «пустой список» снова невидим на INFO

- Было (до батча): `parse_fact_list` для `[]` молчал → `_fallback_parse_facts` → 1 retry → при неудаче
  `logger.info("graphrag memorize: 0 facts | chat_id=%s | source=%s")` — строка была видна в journald (root=INFO).
- Стало: `parse_fact_list_ex` → `PARSE_EMPTY_VALID` → debug (`:602`), `_memorize_facts_inner` — ранний return +
  debug (`:1889`); retry при `empty_valid` не делается (D3, корректно). WARNING-путь (`_log_memorize_lost`)
  для `empty_valid` не вызывается вовсе.
- Итог: невалидный ответ диагностируется лучше (WARNING + маскированный raw), а легитимно-пустой — тише, чем в
  10.18, хотя именно он был в симптоме владельца. Тесты этого не проверяют (они проверяют «нет WARNING» — что
  и закрепляет понижение уровня).
- Рекомендация: INFO (rate-limited) или агрегат `empty_total` рядом с `lost_total` в bounded-состоянии.

### S10.19-2 (Low) — доки F1

- `plans/ARCHITECTURE.md:687` — тело пункта описывает старый контракт, исправление только в хвостовой AMEND-пометке
  (строка длинная, читатель может принять тело за актуальное); аналогичный §215 в этом же файле переписан inline
  («token в path УБРАН»), т.е. стиль в репо есть.
- `README.md:1046` — «после перехода 401 уходит» подаётся как факт без live-подтверждения (T-1779 открыт).

## 3. Верифицировано чисто (доказательства)

**F1 (ingest-контракт):**
- `_url = f"https://{host}"` (`:202`) — токена в URL нет; авторизация `Authorization: Bearer {token}` (`:203`)
  ставится в каждом POST (`:295-297`); тест сверяет `req.full_url == "https://test.invalid"` и заголовок.
- **Редиректы:** `_NoRedirectHandler(HTTPRedirectHandler).redirect_request → None` (`:82-96`); `build_opener`
  с подклассом заменяет дефолтный обработчик (проверено и тестом: в `_OPENER.handlers` ровно наш
  redirect-обработчик). Возврат `None` → базовый `http_error_30x` не повторяет запрос → `OpenerDirector`
  поднимает исходный `HTTPError` с кодом 3xx → `_post` → `_mark_failed("status=3xx")` **без ретрая**; тело POST
  не «переезжает» в GET, `Authorization` не уходит на чужой `Location`, `sent` не растёт. Подтверждено и
  end-to-end тестом с двумя локальными HTTP-серверами (target не получил ни одного запроса).
- **Статусы:** 2xx (включая 202) — успех (`:303-305`); 3xx-ответ без исключения обрабатывается защитной веткой
  (`:298-302`); 400/401/402/403/406/429 → `_BadStatusError`/`HTTPError` → `status < 500` → **без ретрая**,
  `_mark_failed` с `_STATUS_HINTS`; 5xx/транспорт — ровно 1 повтор (`retried`-guard, `_fail_streak` не двоится);
  тесты: 400 → 1 запрос, 500 → 2 запроса, 403 → 1 запрос, 302 → 1 запрос, 307-ответ → `sent==0, failed==1`.
- **R17:** `_auth_header`/`_url` в логи не попадают; `_STATUS_HINTS` — только слова/коды, без значений токена/URL;
  `_mark_failed` формирует `reason=status=NNN | <слова>`, `_reason()` не печатает тело/URL; тест «в WARNING нет
  токена» зелёный. Дополнительный плюс F1: раньше токен был в URL, т.е. любой repr исключения/URL мог его унести.
- **Таймаут/сеть:** `_urlopen(request, timeout=self.timeout)` → `_OPENER.open(...)`; `TimeoutError`/`URLError`
  → статус None → 1 повтор → `_mark_failed("timeout"/"transport: …")` (тест `boom` → 2 вызова).
- **Счётчики/флушер:** `sent += len(items)` только на 2xx; каждая неудача (`_mark_failed`) — ровно один раз на батч
  (двойного учёта нет: retry не инкрементит, 400/500/3xx пути взаимоисключающи); `dropped` — по-прежнему только
  при переполнении буфера; `close()` = stop → join → `flush()` остатка; поток daemon, join с таймаутом, утечек
  задач/потоков нет; бесконечного ретрая нет (guard `retried`, 4xx/3xx не ретраятся).
- **Проприетарность:** `import logtail`/`from logtail` — 0 по репо; `logtail-python` в `requirements.txt` только в
  комментарии об удалении; `endpoint=` в handler'е отсутствует (совпадения grep — Ollama/manage.py).
- Probe-скрипт: матрица `{path-token, Bearer} × {US, EU}`, вывод маскирован (`mask(keep=0)` для токена,
  `mask_host(keep=6)`), `--dry-run` без сети, тесты не делают реальных запросов.

**F8 (устойчивость memorize):**
- `parse_fact_list_ex` — статусы `ok/empty_valid/invalid`; `parse_fact_list` — тонкая обёртка (результат как
  раньше); `empty_valid` — валидный `[]` (включая ```-fence и `[ ]`), `invalid` — не-список, кривой JSON,
  объект без списка **и** структурно валидный список без годных фактов (D-08), при `warn=True` — WARNING
  (маскированный raw), при `warn=False` (memorize-ветка) — без дубля.
- **Восстановление после `LLMError`:** первичная экстракция ловится внутри `_memorize_facts_inner` → fallback по
  доступному raw → ровно **1** retry `_FACT_RETRY_SYSTEM_PROMPT` (`_safe_retry`, бюджет bounded, сверх F-15 не
  растёт) → при успехе факты пишутся (`INFO recovered=N`), при неудаче — единый `WARNING facts lost |
  reason=llm_error`; `[]` retry не вызывает (тест: 1 LLM-вызов). Поведенческие тесты: ERROR→retry recovered
  (факт в БД, 2 вызова), двойной провал → ровно 1 WARNING, rate-limit (2 события → 1 WARNING + debug
  `lost_total=2`), R17-маска `sk-…` → `<secret>`.
- **Bounded-состояние (D-06) и сентинел (D-07):** словари `_memorize_warn_state`/`_memorize_lost_totals` ограничены
  `_MEMORIZE_WARN_STATE_MAX=512` с эвикцией старейших (тест: 12 ключей → ≤3 при лимите 3); «ещё не логировали» —
  `None`, поэтому первое событие WARNING'ится даже при `monotonic()≈0.5` (тест); функция синхронна (нет `await`
  между чтением/записью) → гонок в одном event loop нет.
- **Крон-путь** (`_extract_and_save_graph`) — только различение `[]`/невалид в лог (debug/info), без новых
  LLM-вызовов/ретраев; `parse_triplets` и `EXTRACT_PROMPT` не тронуты; канон `FACT_EXTRACT_PROMPT` байт-в-байт
  (тесты 10.18/10.19 зелёные), `PROMPT_MIGRATIONS` не расширен.
- **`_mask_llm_raw`:** uid/chat_id (числа) и короткие идентификаторы НЕ маскируются (диагностика сохранена),
  секреты по 5 паттернам → `<secret>`; обрезка до 500 симв. + схлопывание пробелов — как раньше (F-15).
- **F8 ↔ F7/F5:** F5-срез (`subject=subject, object=obj`) на месте (`summary_memory.py:2000`), F8 изменяет
  смежные, но не те же участки; `database.py`/`worker_settings.py` (F7) батч не трогает → конфликтов мержа нет.

**Инварианты:** каталог **436/406/411/90/88/19** (интроспекция; Δ батча = 0); DDL нет (SQLite v10);
R16 (аддитивные статусы/поля), R17 (нет значений токена/URL в логах и подсказках); порядок роутеров `bot.py` не тронут.

## 4. Открытые из прошлых раундов (эпик 10.18)

- **S10.18-30 [Medium]** — перф ×2-фазы `graph_snapshot` (`database.py`): ≈176 мс при 200 beliefs, линейно растёт
  (до секунд) → stall event loop на каждый `GET /api/memory/graph` (15с / 5с при manual). В батче A не трогался.
- **S10.18-29 [Low]** — manual-каскад (`run_once(deep=False)`) не ставит `_manual_deep_until` → `deep_sleep.manual=False`,
  `active_until=None` вне окна.
- **S10.18-35 [Low]** — F5-срез не покрывает эпи-мерж (`memory_maintenance`), importance мета-факта может вернуться к 4.
- **Info:** S10.18-12 (nostalgia-РАЗРЫВ, backlog T-1764), S10.18-13 (pre-existing фрагмент SSH-пароля в
  `plans/archive/security-rotation-finalize-round1016/spec.md:35`, файл отслеживаемый), S10.18-18/-19/-20,
  S10.18-31/-32/-33, S10.18-36/-37.

## 5. Вердикт

- **Батч A: 0 Critical / 0 High / 0 Medium.** F1-контракт (Bearer, запрет редиректов, словарь подсказок, R17) и
  F8 (статусы парсинга, восстановление после `LLMError`, не-спамящая диагностика, bounded-состояние) реализованы
  корректно; инварианты (канон, каталог Δ=0, R17, отсутствие logtail) целы.
- **Переход к Батчу B (F2 бюджеты) — РАЗРЕШЁН.** Блокеров нет; открытые Low/Info — не блокирующие (S10.19-1 и
  S10.19-2 рекомендуется закрыть в этом же раунде).
- **Валидатор:** `.venv/Scripts/python.exe -m pytest -q` → **6164 passed / 0 failed** (71.98 c);
  `node --check web/app.js` OK; `routing_test.js` `JS-UNIT-OK`; `vue_mount_test.js` `VUE-MOUNT-OK`;
  `git diff --check` → exit 0.

## 6. Что обновлено

- `plans/reports/round10.19_scanner_audit.md` — этот отчёт (новый).
- `plans/reports/global_map.md` — секция «Round 10.19 — БАТЧ A» + baseline 10.19.

*Отчёт сгенерирован @Scanner 15.09.2026 (Шаг 6 OpenSpec, Strict Workflow, БАТЧ A).*

## 7. БАТЧ B — F2 `direct-chat-budget-unlimited` (+ перенос фиксов Батча A) — аудит 15.09.2026

> **Область:** `services/budget_limits.py` (новый), `services/chat_usage.py`, `services/worker_budget.py`,
> `services/llm_client.py`, `config/settings.py`, `services/param_catalog.py` (тексты), `.env.example`,
> `services/summary_memory.py` (`_log_empty_valid`), `plans/ARCHITECTURE.md` (§22/§23/§40), `README.md`,
> `scripts/betterstack_host_token_probe.py`, `plans/archive/betterstack-us-region-401/adr-1018-1-*.md`,
> `tests/test_budget_unlimited_round1019.py` (новый), `tests/test_chat_keys.py`, `tests/test_betterstack_*`.
> **Эталон:** `plans/features/direct-chat-budget-unlimited/{spec.md, adr-1019-2-*.md, tasks.md}`,
> `plans/features/budget-settings-section/adr-1019-8-*.md`, `plans/current_task.md` (UPD2 п.1 + UPD3 п.2/3).
> **Метод:** `git diff`/чтения `file:line` + grep всех call-sites `_metric_limit`/`_budget_limit_*`/`hot.get(…budget…)`/
> `budget_limits.` + собственные пробы (полный pytest, JS-гейты, `git diff --check`, интроспекция каталога,
> сентинел/каст-проба, перф-проба `graph_snapshot` на синтетике 15k рёбер, семантика ×2 fast-path).

### 7.1. Статусы находок Батча A и 10.18 (перепроверено)

| ID | Sev | Статус | Доказательство |
|---|---|---|---|
| S10.19-1 | Low | **CLOSED** | `services/summary_memory.py:233-…` — новый `_log_empty_valid` (rate-limited **INFO**, `empty_total` в bounded-словарях, `_evict_memorize_state` покрывает и его); вызовы: memorize (`:1921`) и крон-ветка (`:3120`, `label="graph extract"`) — валидный `[]` снова виден при root=INFO (симптом «модель вернула пустой список»). |
| S10.19-2 | Low | **CLOSED** | `README.md:1046` переписан: «переход в коде уже сделан, а устранение 401 **ожидается** — живое подтверждение ждёт T-1779» (гипотеза, не факт). `plans/ARCHITECTURE.md:687` переписан inline: единственное вхождение `https://{host}/{token}` — внутри корректирующей фразы («прежний … давал 401»), D4 — «при совпадении DEBUG»; остальных stale-утверждений (`last4=XXXX`, WARNING про public key) нет (оставшиеся `last4` в файле — про маску API-ключей `{configured,last4}`, другая фича). |
| S10.18-30 | Medium | **CLOSED** | ×2-фаза ускорена: `database._belief_name_participates` (token-set + padded-строка вместо per-node `re.search`). **Моя проба** (4000 узлов / 15000 рёбер / 20000 фактов / 200 beliefs, chat-scope): было **238 мс** → стало **65.6–70.3 мс** (chat=None 86 мс) — доминирует SQL-часть (~59 мс), заявленный порядок 55 мс подтверждается. |
| S10.18-35 | Low | **CLOSED** | `services/memory_maintenance.py:256-271` — merge переносит F5-пенальти: при **всех** членах кластера `importance <= 1` → `importance=METAFACT_PENALTY_IMPORTANCE`; `get_live_graph_facts` SELECT += `importance` (`database.py:3559-3564`). |
| S10.18-36 | Info | **CLOSED** | `plans/archive/role-matrix-settings-actualization/spec.md` (§2/§3.1/§9) синхронизирован: «3 nav-родителя + группа **«Прочее»**», 4 группы, 5 content-параметров с `tab=None` (фича 10.18 заархивирована). |

Остаются открытыми из 10.18: **S10.18-29 [Low]** (manual-каскад не ставит `_manual_deep_until`) + Info
(S10.18-12/-13/-18/-19/-20/-31/-32/-33/-37/-38).

### 7.2. Новые находки Батча B

| ID | Sev | File:line | Суть | Рекомендация |
|---|---|---|---|---|
| S10.19-7 | Low | `README.md:365,368` | **README описывает старые бюджеты как текущие.** «BYOK» → «по умолчанию **100 000 токенов / 25 запросов в сутки**» (факт: 500 000/100); «Worker Budget» → «на чат — **35 вызовов / 100 000 токенов**» (факт: 60/300 000). Плюс там же «ручные прогоны из бюджета тоже не выпадают» — с 10.18 (ADR-1018-2) ручной запуск гонки бюджета обходит. README был в списке файлов батча, но получил только правку BetterStack. | Обновить обе строки (100/500 000, 60/300 000, sentinel −1=безлимит, ручной manual-обход) — иначе оператор видит несуществующие лимиты. |
| S10.19-8 | Low | `config/settings.py:484-493`; `plans/features/direct-chat-budget-unlimited/spec.md:151,181` | **Новые глобальные дефолты не доедут до прода без шага данных.** Код-дефолты подняты (direct 25/100 000 → 100/500 000; фон per-chat 35/100 000 → 60/300 000), но эффективное значение читается как `overrides → hot.get → env-дефолт`, а PG-ключи `bot_settings` **уже засеяны** старыми значениями (`_seed_settings` — `ON CONFLICT DO NOTHING`) → у не-VIP чатов останутся прежние 25/100 000 (и фон 35/100 000) до записи данных. В спеке §4.5/§7 это зафиксировано и адресовано @DevOps/F3 (VIP-сид T-1859 ставит `−1` только целевому чату), но ни один шаг батча не пишет 4 глобальных/фон-ключа. | Либо идемпотентная миграция в стиле прецедента `migrate_dream_thresholds` («обновить только если значение == прежнему дефолту 25/100 000/35/100 000»), либо включить эти 4 ключа в чек-лист данных F3/@DevOps. Иначе прод-симптом «sandbox на 25 вызовов» сохранится для всех чатов, кроме VIP. |
| S10.19-9 | Info | `services/database.py:3779-3803` | **У ×2-fast-path есть небольшая семантическая дельта для «грязных» имён.** Новая `_belief_name_participates`: однословное имя → точное совпадение токена; многословное → непрерывная последовательность слов. Проба (blob «вася любит дом и тему дня. система важна. дом!»): `дом` → True/True ✓, `система` → True/True ✓, `тема` → False/False ✓ (не подстрока), а **`дом!` → было True (regex по сырому тексту) → стало False** (в набор токенов пунктуация не входит). Практический риск низкий (имена узлов обычно без пунктуации; выигрыш перфа ~3.6×), но тестами случай не покрыт. | Опционально: для однословных имён с не-словными символами нормализовать до слова (`words[0] in token_set`) или добавить тест-кейс «имя с пунктуацией» — чтобы поведение было явным. |
| S10.19-10 | Info | `services/budget_limits.py:70-94`; `services/token_counter.py:124-141`; `services/status_service.py:513` | **Контекстный/retention-семейства ещё не подключены (F4/F7).** `context_state`/`retention_state` реализованы, но не используются: `resolve_chat_limit` пропускает `token_value` как есть (отрицательный лимит → отрицательная цель truncation), `status_service` — `acct.get("context_limit") or ctx_cap` (0-безопасно, отрицательный проходит). До F4 «−1» для контекста в UI не задокументирован для оператора (только ADR-1019-8), поэтому реальный риск — если владелец поставит −1 раньше F4. | В F4/F7 провести контекст через `context_state` (0=unset→дефолт, <0→unlimited→`CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS`), retention — через `retention_state` (0=eternal, <0=invalid→fallback+WARNING); сейчас ничего не менять. |
| S10.19-11 | Info | `services/worker_budget.py:290-325`; `services/oversight.py:193-202` | **В «Сводке»/API фона нет флагов sentinel — только число.** `get_usage`/`get_day_summary` отдают `limit` (может быть −1/0) без `unlimited/forbidden/source` (в отличие от `chat_usage.key_status`), а `oversight.build_summary` вообще опускает `budget`, если у чата сегодня нет строк расхода (`if day_rows:`) — лимит «тихого» чата в Сводке не виден. F3 рисует «честные бары». | F3: аддитивно добавить в строки `get_usage`/`get_day_summary` те же флаги (R16) либо рендерить `<0` как ∞ и не скрывать бюджет при пустом расходе. |
| S10.19-12 | Info | `services/worker_budget.py:196-222`; `services/chat_usage.py:141-160` | Предсуществующие нюансы учёта, которые всплывут в UI F3: (а) `consume` пишет расход **до** проверки сентинела → у чата с лимитом `0` (запрет) леджер всё равно растёт; (б) граница cap различается: фон разрешает `used <= limit` (т.е. limit+1-й вызов), direct — `used >= limit` (ровно limit вызовов). | Учесть при отрисовке баров F3 (или выровнять границы отдельной задачей) — не блокер. |

### 7.3. Верифицировано чисто (Батч B)

- **Sentinel-согласованность:** `budget_limits.budget_state` — `0/мусор → forbidden`, `любое <0 → unlimited`, `>0 → cap`;
  `chat_usage._exceeds` проверяет forbidden → затем `not is_unlimited(...)` для обеих метрик (отрицательный лимит **никогда**
  не даёт «мгновенный стоп», `0` не трактуется как cap); `worker_budget.consume` — `forbidden → False`,
  `unlimited → True` (расход записан), `cap → used <= limit`; `allowed_workers` — `0 → все False`, `<0 → все True`,
  `>0 → матрица деградации`. Семьи **не** взаимозаменяемы и это явно зафиксировано (таблица в docstring + тест
  `test_families_not_interchangeable`): контекст `0 → unset`, retention `0 → eternal`, негатив в retention → `invalid`.
- **Моя независимая проба сентинел/каста:** глобальное значение `"abc"` → env-дефолт 100 + WARNING (fail-open);
  `-5/-100` → unlimited; `False` → forbidden; `None` → дефолт; `" 42 "` → 42; `3.5` → 3 (тихое усечение, но такие
  значения в int-ключ каталога не пишутся). Итог: мусор безопасен, `-1` безлимитен, `0` запрещает.
- **Async-рефактор `worker_budget`:** все call-sites `_metric_limit` awaited (`consume`, `get_usage`, `get_day_summary`
  ×3, `global_degradation_allows` → `get_usage`); un-awaited корутин/предупреждений нет; `_limit()` (sync) остался
  только для jitter/priority (не бюджеты); `get_usage`/`get_day_summary`/`allowed_workers`/деградация воркеров
  сохранены; PG-down: `consume → True` + дедуп-WARNING, `_resolve_limit → env-дефолт`, `budget_snapshot → exceeded=False`.
- **Ложный sandbox устранён как класс:** `budget_snapshot` — единственный источник решения и `details`
  (один резолв лимитов + одно чтение usage; TOCTOU/двойной PG-раундтрип убраны — D-5); инвариант
  «`exceeded=True` ⇒ валидный `exceeded_metric`» соблюдён (несогласованность → ERROR-лог + fail-open);
  прод-симптом воспроизводится как `exceeded_metric='calls'` с `source`; `used_tokens ≪ limit` больше не даёт
  «бюджет вообще» без метрики (тесты `TestSnapshot`).
- **Per-chat резолв без обходов:** `hot.get("limits.chat_global_key_budget*")` и `hot.get("limits.worker_daily*")` —
  **0 совпадений** в коде; `settings.CHAT_GLOBAL_KEY_BUDGET_*` читается только в `_env_default`, `WORKER_DAILY_LLM_*` —
  только как `default` в `_metric_limit`; оба контура резолвят через `worker_settings.resolve_setting_with_source/cached`
  (chat → global → env) и изолированы (разные пространства ключей, тест `TestContourIsolation`).
- **Каталог:** число ключей не изменилось — **436/406/411/90/88/19** (интроспекция); тексты `CHAT_GLOBAL_KEY_BUDGET_*`
  и `WORKER_DAILY_LLM_*_PER_CHAT` согласованы с кодом (100/500 000, 60/300 000, «−1 — безлимит»); `.env.example`
  дополнен закомментированными дефолтами.
- **Нет хардкода VIP-id в бизнес-логике батча:** в `services/` id остаётся только в pre-existing легаси-константе
  `chat_lore.CHAT_LORE_TARGET_CHAT_ID(-1002661910336)` (декларативный сид лора раунда 5) и в `scripts/backfill_*`
  (данные-скрипты) — ADR-1019-8 D4 допускает id в сидах/данных; новых `if chat_id == …` нет (grep).
- **Доки/архив:** `plans/ARCHITECTURE.md` — §22/§23 получили inline-AMEND, добавлен **§40** (F2 + ревью-фиксы D-1…D-5);
  архивный ADR-1018-1 обновлён (AMEND ADR-1019-1); каталог-дельта и контуры описаны.
- **Сквозные риски (item 8):** F2↔F3 — `key_status` уже отдаёт `unlimited/forbidden/source` на метрику (R16), фон —
  только число (S10.19-11); F2↔F7 — retention-семейство независимо (`0=вечно`), код его не трогает, конфликтов
  ключей/таблиц нет; `budget_limits` не используется в retention-путях (риск «0=запрет vs 0=вечно» закрыт
  таблицей-документацией и раздельными хелперами).
- **Валидатор:** `.venv/Scripts/python.exe -m pytest -q` → **6195 passed / 0 failed** (78.62 c);
  `node --check web/app.js` OK; `routing_test.js` `JS-UNIT-OK`; `vue_mount_test.js` `VUE-MOUNT-OK`;
  `git diff --check` → exit 0.

### 7.4. Итог Батча B и вердикт

| Severity | Открыто | Закрыто | Коды открытых |
|---|---|---|---|
| Critical | **0** | 0 | — |
| High | **0** | 0 | — |
| Medium | **0** | 1 (S10.18-30) | — |
| Low | **3** | 2 (S10.19-1, S10.19-2) + 1 (S10.18-35) | S10.18-29, S10.19-7, S10.19-8 |
| Info | **9** | 1 (S10.18-36) | S10.18-12, -13, -18, -19, -20, -31, -32, -33, -37; + S10.19-9, -10, -11, -12 |

- **ВЕРДИКТ: переход к Батчу C (F3 бюджеты-UI + VIP-сид) — РАЗРЕШЁН.** Открытых Critical/High/Medium нет;
  sentinel-семантика консистентна в обоих контурах, async-рефактор корректен, ложный sandbox закрыт как класс,
  per-chat резолв без обходов, каталог Δ=0. S10.19-7/-8 — доки/операционный шаг данных (не блокеры, но
  S10.19-8 стоит учесть в сид/DevOps-чек-листе F3).
- **Валидатор:** pytest **6195/0**; JS-гейты OK; `git diff --check` exit 0; каталог 436/406/411/90/88/19.

### 7.5. Что обновлено (Батч B)

- `plans/reports/round10.19_scanner_audit.md` — эта секция (§7) + статус-правки §0/§7.1.
- `plans/reports/global_map.md` — секция «Round 10.19 — БАТЧ B» + baseline.

*Секция Батча B сгенерирована @Scanner 15.09.2026 (Шаг 6 OpenSpec, Strict Workflow).*

## 8. БАТЧ C — F3 `budget-settings-section` (вкладка «Бюджеты», VIP-сид, Сводка, guard purge) — аудит 15.09.2026

> **Область:** `services/vip_seed.py` (новый), `config/vip_chats.json` (новый), `services/retention_policy.py` (новый),
> `services/oversight.py` (аддитивный `limits`), `services/param_catalog.py` (каталог-Δ), `services/chat_params.py`
> (`get_all_chat_params(pg=…)`), `services/config_migrations.py` (`migrate_global_budget_defaults`), `bot.py`, `manage.py`,
> `web/api/routes.py` (`global_value`/meta-merge), `web/app.js`, `web/index.html`, `README.md`, `plans/ARCHITECTURE.md`,
> `tests/test_budget_settings_round1019.py`, `tests/test_vip_seed_round1019.py` + ~14 пин-тестов.
> **Эталон:** `plans/features/budget-settings-section/{spec.md, adr-1019-3-*.md, adr-1019-8-*.md, tasks.md}`,
> `plans/current_task.md` (UPD2 п.1, UPD3 п.2/3/4).
> **Метод:** `git diff`/чтения `file:line` + grep потребителей контекст-лимитов (`resolve_chat_limit`/`safe_budget`/
> `truncate_to_tokens`) + интроспекция каталога (осиротевшие ключи/группы, владельцы групп) + пробы
> (полный pytest, JS-гейты, `git diff --check`, сентинел-проба контекста `-1`/`0` → `safe_budget`).

### 8.1. Новые находки Батча C

| ID | Sev | File:line | Суть | Рекомендация |
|---|---|---|---|---|
| S10.19-13 | **High** | `config/vip_chats.json` (3 контекст-ключа = −1); `services/token_counter.py:124-141` (`resolve_chat_limit`), `:119-121` (`safe_budget`); `services/direct_chat_service.py:1993-2033,2134`, `services/summary_generator.py:172-188`; `web/app.js` (OFF-ветка пишет `0`) | **Семантика контекстного семейства (`0 = не задано → глобальный дефолт`, `−1 = безлимит`) НЕ реализована в потребителях, а сид F3 уже ставит `−1`, и это применяется в проде.** Проба: `resolve_chat_limit(-1, 1000, …)` → `('tokens', -1)` → `safe_budget(-1) = max(1, int(-1/1.15)) = 1`; то же для `0`. `direct_chat_service._build_global_context` (вызывается **безусловно**, не под `flags.chat_context_budgets_enabled`) при `measure(text) > budget` (1) логирует `keep-head truncated to 1 tokens (was 21)` и **срезает `<Global_Context>` до 1 токена**; симметрично `:2134` (thread/branch) и `summary_generator:183` (контекст сводки, `SUMMARY_MAX_CONTEXT_TOKENS=None`). Итог: (а) VIP-чат владельца (`-1002661910336`) после применения сида (`bot.py:944-953` на каждом старте + CLI `manage.py vip-seed`) теряет фон/ветку/сводку в ответах — `CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS=32000` существует (`config/settings.py:485`), но **не используется нигде**; (б) OFF-ветка нового тумблера пишет `0` для ключей, чей env-дефолт = `None` (`CHAT_GLOBAL_CONTEXT_MAX_TOKENS`/`CHAT_THREAD_MAX_TOKENS` → `global_value=null`) → тот же срез «в 1 токен» для любого чата; (в) тексты каталога/UI («0 — не задано (глобальный дефолт); −1 — безлимит») пока **не соответствуют коду** (обещание F4). В спеку F3 это заложено как «зависимость F2 → F3 → F4», но сид C-батча активирует `−1` раньше потребителя. | Блокер Батча D (F4). Минимальный безопасный фикс на стороне C: **убрать 3 контекст-ключа из `config/vip_chats.json`** (перенести в версию сида F4) **и** не писать `0`/`−1` для контекста из OFF-ветки тумблера (писать эффективный дефолт или не трогать ключ). Целевой фикс (F4, ADR-1019-3 D7): в `resolve_chat_limit`/call-sites трактовать `<0` → `CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS`, `0/None` → глобальный дефолт. До этого — не применять сид на проде (`vip-seed`/рестарт). |
| S10.19-14 | Medium | `services/oversight.py:167-181,185-216` | **«Сводка»: worker-контур без строк за сутки рапортует «Запрещено».** `_limits_metric(contour='worker')` при пустом `day_rows` берёт `limit = 0` → `budget_limits.is_forbidden(0) → True` → UI (`limitsPairText`) рисует «фон: **Запрещено**» для каждого «тихого» чата (строки `worker_budget` появляются только после первого `consume`), тогда как фактический лимит — 60/300 000 или `−1`. Прямой контур корректен (`chat_usage.key_status` резолвит лимиты), т.е. блоки асимметричны; поведение закреплено тестом `test_fail_open_on_source_error` (`limit == 0, forbidden is True`). | Когда строк нет (или всегда) брать `limit/unlimited/forbidden` из `resolve_setting_with_source(WORKER_LIMIT_KEYS[metric], chat_id, default=…)`, как сделано для контекста (D-6), `used` оставить 0. Поправить тест. |
| S10.19-15 | Low | `services/oversight.py:203-216` | **Лишние PG-запросы в `build_summary`.** `_limits_block` вызывает `chat_usage.key_status` **дважды** на чат (по разу на метрику), т.е. 2× `budget_snapshot` → 2× `used_today` + до 2× чтения `chat_profiles` на чат за построение Сводки (кэш 60 с; тест `test_direct_contour_reads_key_status` это закрепляет: `seen == [-100, -100]`). | Один `key_status` (или один `budget_snapshot`) на чат — забрать обе метрики из результата. |
| S10.19-16 | Info | `web/app.js` (OFF-ветка `toggleBudgetsUnlimited`), `web/api/routes.py:330-355` | OFF-ветка тумблера пишет **явные значения глобального слоя** вместо `DELETE` (чтобы сид не переприменил `−1` по условию «ключа нет»). Как следствие чат «пришпиливается» к сегодняшним глобальным значениям и перестаёт наследовать будущие изменения дефолтов; плюс сам эвристический фолбэк `null → 0` опасен для контекста (см. S10.19-13). | Для не-enforce ключей: `DELETE` + tombstone-маркер в `meta` (теперь `meta` при DELETE сохраняется — фикс D-3), либо явный признак «оператор OFF» в `meta`, который сид уважает. |
| S10.19-17 | Info | `services/retention_policy.py:38-57`; `services/oversight.py:243-250` | `imported_history_purge_allowed` — пока **без прод-call-site** (контракт для F7); это честно записано в docstring/ADR, DB-слоя purge нет → деструктивный путь отсутствует, ложного чувства защиты нет. Замечание: fallback «invalid retention → глобальный дефолт + WARNING» реализован и в policy-хелпере, и повторно в `oversight._limits_block` — два места для синхронизации. | В F7 использовать policy-хелпер как единственный источник (в т.ч. в Сводке) — иначе возможен дрейф. |

### 8.2. Верифицировано чисто (Батч C)

- **VIP-сид (иденпотентность/merge/fail-open):** `ensure_scope_profile` → чтение root **напрямую из PG** (D-2:
  `chat_params.get_all_chat_params(chat_id, pg=…)` — DB-путь, чтобы CLI без кэша не затирал namespace) → patch →
  `merged = current ∪ patch`, `meta` сохраняется (`meta[SEED_META_KEY] = version`) → запись **только при фактическом
  изменении** (иначе `skipped`, без UPDATE/истории/NOTIFY) — повторный прогон no-op (тесты);
  чужие overrides/meta сохраняются в обоих путях (bot-путь через кэш и CLI-путь без кэша — тест
  `test_cli_path_preserves_foreign_overrides_without_cache`); `enforce`-ключи применяются всегда, не-enforce —
  только при отсутствии/росте version/`force` (ручная правка уважается — тесты); fail-open (нет PG/файла) ✓;
  запись строго по записям сида (никаких чужих чатов) ✓; id — только в `config/vip_chats.json` (+тесты),
  новых хардкодов в `services/*` нет (тест `TestNoHardcodedId`).
- **Retention-политика:** `retention_state` (0=eternal → purge запрещён, >0 → cap, <0/мусор → invalid → fallback +
  WARNING); ошибка резолва → **fail-closed** (`allowed=False`, `source='error'`) — безопасный дефолт для
  разрушительной операции (тесты: 0/позитив/негатив/исключение).
- **Сводка (R16-аддитивность):** новый `limits` = `key_budget` (direct-контур — `chat_usage.key_status`, D-1:
  контур задаётся явно, а не по имени метрики, иначе ветка была мёртвой), `worker_budget` (строки
  `worker_budget.get_usage(scope=chat:<id>)`), `context` (3 ключа: `unset`→эффективный дефолт 1000/500/16000, D-6 —
  без ложного `limit: 0`; `−1` → `unlimited`), `storage` (`import_forever`/label «Вечно»/«N дней»); каждый
  под-объект fail-open (500 не бывает), старый `budget` сохранён ✓.
- **Guard purge:** fail-closed и отсутствие call-site — честно зафиксированы (D-5) в docstring/ADR; до F7
  деструктивного пути нет.
- **Миграция дефолтов (S10.19-8 из Батча B — закрыта):** `migrate_global_budget_defaults` — идемпотентна,
  правит **только** равенство прежнему дефолту (25/100 000 direct, 35/100 000 фон → 100/500 000 и 60/300 000),
  кастом → WARNING, отсутствующий ключ → skip, PG down → skip (тесты); вызов в `bot.py` **до** `apply_vip_seed`
  (`:944-953`), fail-open-обёртка вокруг сида ✓.
- **Каталог:** интроспекция — **REGISTRY 437 / Settings 407 / categorized 412 / GROUPS 92 / mapped 90 /
  TAB_RULES 20 / CONFIG_TAB_TITLES 20**; осиротевших ключей нет, пустых групп нет, TAB_NAV ↔ TAB_RULES
  совпадают, `TAB_MOD_BUDGETS` есть в `TAB_NAV`/`CONFIG_TAB_TITLES`; перенесённые группы имеют **ровно одного**
  владельца (`limits_chat_key`/`limits_chat_context` → `mod_budgets`; `limits_worker` ушёл из `mod_checkup`
  в `mod_budgets`; в `limits_chat_budgets` остались только доли-`ratio`); `IMPORT_HISTORY_RETENTION_DAYS`
  зарегистрирован (limits/limits_memory, Settings-поле, не секрет).
- **UI:** новый раздел «Бюджеты» (карточка без master-тумблера → бейдж «лимиты»), маршрут `#/modules/budgets`,
  `TAB_SECTION_ORDER` +1; тумблер «Безлимит по чату» доступен только в контексте чата (`isChatContext`, disabled
  иначе) и пишет существующие per-chat ключи (Δ каталога = 0); `budgetRatio` guard (`limit <= 0`/`unlimited` → 0 %),
  `limitsPairText` («Безлимит (∞)»/«Запрещено»/`used / limit`), `storageLabel` («Импорт: Вечно»/«N дней»),
  пояснение «фон vs интеллект» и таблица сентинелов; JS-гейты чистые.
- **R17:** новые строки/логи — ключи/числа/source, без секретов и значений промптов; `global_value` — не секрет
  (секретные ключи его не отдают).
- **Валидатор:** `.venv/Scripts/python.exe -m pytest -q` → **6232 passed / 0 failed** (77.75 c);
  `node --check web/app.js` OK; `routing_test.js` `JS-UNIT-OK`; `vue_mount_test.js` `VUE-MOUNT-OK`;
  `git diff --check` → exit 0. README обновлён (100/500 000, 60/300 000, «Модули → Бюджеты») — **S10.19-7 закрыт**.

### 8.3. Итог Батча C и вердикт

| Severity | Открыто | Закрыто | Коды открытых |
|---|---|---|---|
| Critical | **0** | 0 | — |
| **High** | **1** | 0 | **S10.19-13** (контекст `−1`/`0` → срез «в 1 токен») |
| Medium | **1** | 0 | S10.19-14 |
| Low | **2** | 2 (S10.19-7, S10.19-8) + 1 (S10.18-29 остаётся) | S10.18-29, S10.19-15 |
| Info | **7** | 0 | S10.18-12/-13/-18/-19/-20/-31/-32/-33/-37/-38 (перенос) + S10.19-9…-12 (Батч B) + S10.19-16/-17 |

- **ВЕРДИКТ: переход к Батчу D — БЛОКИРОВАН (High S10.19-13)** до устранения landmine: либо убрать 3 контекст-ключа
  из `config/vip_chats.json` (перенести в сид F4) и не писать `0` для контекста из OFF-ветки тумблера, либо
  реализовать семантику контекстного семейства (`<0 → CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS`, `0/None → глобальный
  дефолт`) в `resolve_chat_limit`/call-sites. После этого достаточно закрыть S10.19-14 (Medium) — и Батч D
  (F4 контекст + F5 UI Статуса) можно продолжать.
- **⏱ Статус после Батча D (16.09.2026): High S10.19-13 и Medium S10.19-14 — CLOSED** (фиксы @Builder + независимая
  проверка @Scanner §9.1: пробы `-1 → 32000/budget 27826`, `0/None → 5000/4347`, фон-контур «пустого дня» → лимит
  из резолвера, а не `0`). Итог Батча D — §9.4.
- **Валидатор:** pytest **6232/0**; JS-гейты OK; `git diff --check` exit 0; каталог 437/407/412/92/90/20.

### 8.4. Что обновлено (Батч C)

- `plans/reports/round10.19_scanner_audit.md` — эта секция (§8) + статусы §7.1 (S10.19-7/-8 → CLOSED).
- `plans/reports/global_map.md` — секция «Round 10.19 — БАТЧ C» + baseline.

*Секция Батча C сгенерирована @Scanner 15.09.2026 (Шаг 6 OpenSpec, Strict Workflow).*

---

## 8.5. Батч D — закрытие High S10.19-13 и Medium S10.19-14 (фиксы @Builder, 16.09.2026)

> **Область:** F4 `direct-context-limit-expansion` (T-1861/T-1862) + High
> **S10.19-13**, Medium **S10.19-14**; + F5 `status-section-ui-merge` (T-1819…T-1824).
> **Метод:** `file:line`-чтение + пробы (полный pytest, JS-гейты, замер контекста).

### S10.19-13 — CLOSED (семантика контекста в потребителях)

Реализована sentinel-семантика семейства «контекст» **во всех call-sites**
(не «убрать ключи из сида»):

| Контур | `< 0` (`-1`) | `0`/`None` | `> 0` |
|---|---|---|---|
| Per-block global/thread | потолок `CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS` (32000) | глоб. дефолт (5000/3000) | cap |
| Total `chat_context_budget_tokens` | агрегатное усечение `_apply_context_budget` НЕ применяется | глоб. дефолт (16000) | cap |

- `services/token_counter.py::resolve_context_tokens` + `resolve_chat_limit`
  (потребляют `budget_limits.context_state`); call-sites:
  `_build_global_context`, `_thread_limit`/`_render_thread`, `summary_generator`.
- `services/direct_chat_service.py::_apply_context_budget` — `-1` = skip;
  `global`/`thread` не режутся по долям при `total ≤ budget` (фикс D-1);
  `_check_context_config_invariant` (ADR-1019-4 D2, фикс D-1) — один WARNING,
  когда доля `ratio × (budget − fixed_tokens)` меньше `safe_budget(cap)`
  (прежняя формула `budget < Σcaps` пропускала реальный случай).
- OFF-ветка тумблера F3 пишет `0` для контекстных ключей → теперь это
  «не задано» (дефолт), а не «срез в 1 токен» (снимает риск S10.19-16 для
  контекста).
- `config/settings.py`: 5000/3000/16000; `config_migrations`
  `migrate_context_limit_defaults` (идемпотентно, 1000/500/4000 → …);
  `bot.py main()` — вызов после `migrate_global_budget_defaults`;
  `oversight.CONTEXT_LIMIT_KEYS` эффективные дефолты 5000/3000; каталог —
  sentinel-описания.

**Доказательство (замер, T-1815):**

```
OLD  cap=1000    resolved=1000   budget=869    block_tokens=855    (raw window 2099)
NEW  cap=5000    resolved=5000   budget=4347   block_tokens=2718
VIP  sentinel=-1 resolved=32000  budget=27826  block_tokens=2718
```

**Двойная обрезка (D-1/D-2, `budget=16000`, неприкосновенный `protected≈3012`):**

```
global_before            = 4408
fixed(protected)         = 3012      → effective = 12988
доля 0.30×effective      = 3896      (< safe_budget(5000)=4347)
global_after OLD         = 3896      ← двойная обрезка (ниже cap)
global_after NEW (D-1)   = 4408      ← без усечения (== before)
```

**Латентность сборки (D-4, медиана 3000 прогонов):**

```
_apply_context_budget (регресс-набор) = 2.69 ms
_apply_context_budget (реальный набор) = 5.69 ms
доп. _truncate_block(global), убранный фиксом = 2.43 ms
→ фикс НЕ увеличивает латентность (дельта ≤ 0)
```

`resolve_chat_limit(-1, 1000, …)` → `("tokens", 32000)` (было `safe_budget(-1)=1`);
`_build_global_context` на 20-сообщениях VIP сохраняет весь фон
(`tests/test_context_limits_round1019.py::TestGlobalContextNotStarved`).

### S10.19-14 — CLOSED (пустой день фон-контура)

`services/oversight.py::_limits_metric(contour='worker')`: при пустом
`day_rows` лимит берётся `chat → global → default`
(`WORKER_DEFAULT_LIMITS` = `settings.WORKER_DAILY_LLM_CALLS/TOKENS_PER_CHAT`),
а не `0` → ложное «Запрещено» устранено. Если строка дня есть — её `limit`
(уже per-chat-резолвнут `worker_budget`) сохраняется, `source` уточняется
best-effort. Тест `test_fail_open_on_source_error` обновлён (limit 60, не 0).

### Валидатор Батча D

- `.venv/Scripts/python.exe -m pytest -q` → **6262 passed / 0 failed** (81 c).
- `node --check web/app.js` OK; `routing_test.js` `JS-UNIT-OK`; `vue_mount_test.js`
  `VUE-MOUNT-OK`; `git diff --check` — clean.
- Каталог-Δ = 0: 437/407/412/92/90/20.

### Фиксы ревью Батча D (D-1…D-8, 16.09.2026)

- **D-1/D-2:** `_apply_context_budget` не режет `global`/`thread` по долям при
  `total ≤ budget`; инвариант учитывает `fixed_tokens` и доли. Регресс-тест:
  блок 4408 ≥ `safe_budget(5000)=4347` + `protected≈3012` при `budget=16000`
  — без усечения (было 4408→3896). Тесты:
  `test_context_limits_round1019.py::TestAggregateBudgetUnlimited::test_budget_does_not_double_cut_global_below_cap`,
  `::test_invariant_accounts_for_fixed_tokens`.
- **D-3:** `.env.example` — активная строка `CHAT_CONTEXT_BUDGET_TOKENS=24000`
  закомментирована; единственный источник `16000` — F4-блок.
- **D-4:** в evidence добавлен замер латентности (медиана 3000 прогонов,
  дельта ≤ 0).
- **D-5:** число pytest синхронизировано (6262); `T-1853` → `[x]`.
- **D-6:** `status-block` inline-style вынесен в класс `.status-block` (CSS).
- **D-7:** безлимит `-1` → `context_limit=None` + `unlimited`; UI «Безлимит (∞)».
- **D-8:** `token_counter` клампит отрицательный `token_default`
  (`max(1, int(...))`), тест `test_negative_default_is_clamped`.

### F5 `status-section-ui-merge` (T-1819…T-1824)

- `web/index.html`: «Сердцебиение» + «Бот» + «Сервер» → один `.status-block`
  с `.status-block__grid` (мобила — столбик, ≥768px — `1.4fr 1fr 1.2fr`);
  строка со служебными полями удалена; API-контракт не менялся (R16).
  **D-6:** `grid-column: 1 / -1` перенесён в CSS-класс `.status-block`
  (inline-стиль убран).
- `web/static/app.css`: `.status-block { grid-column: 1 / -1; }`,
  `.status-block__grid`; `.graph-search` десктоп
  `max-width: 460px`, мобильный input компактный (`padding 0.3rem`,
  `font-size 0.8rem`); `.field` не тронут.

*Секция Батча D — @Builder 16.09.2026 (фиксы по аудиту @Scanner §8.1).*

## 9. БАТЧ D — F4 `direct-context-limit-expansion` + F5 `status-section-ui-merge` (аудит @Scanner 16.09.2026)

> **Область:** `config/settings.py` (5000/3000/16000, `CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS`),
> `services/token_counter.py` (`resolve_context_tokens`, кламп, chars-fallback), `services/direct_chat_service.py`
> (call-sites, `_check_context_config_invariant`, `_apply_context_budget`, D-7-учёт), `services/oversight.py`
> (контекст-дефолты 5000/3000/16000, фон-контур «тихого» чата), `services/config_migrations.py` +
> `bot.py` (`migrate_context_limit_defaults`), `services/param_catalog.py` (тексты), `.env.example`,
> `services/status_service.py` (D-7), `web/index.html`, `web/static/app.css`, `web/app.js`,
> `tests/test_context_limits_round1019.py`, `tests/test_status_section_ui_merge_round1019.py`.
> **Эталон:** `plans/features/direct-context-limit-expansion/{spec.md, adr-1019-4-*.md, tasks.md}`,
> `plans/features/status-section-ui-merge/{spec.md, tasks.md}`, ADR-1019-8 D2/D3, UPD2 п.1 («7000→869»).
> **Метод:** `git diff`/чтения `file:line` + grep **всех** потребителей трёх контекст-ключей + собственные пробы
> (сентинел `-1`/`0`/`None` → `safe_budget`, фон-контур «пустого дня», интроспекция каталога, подсчёт inline-стилей,
> полный pytest, JS-гейты, `git diff --check`).

### 9.1. Проверка закрытия S10.19-13 (High) и S10.19-14 (Medium) — **подтверждаю CLOSED**

| ID | Статус | Доказательство (моя независимая проверка) |
|---|---|---|
| S10.19-13 (High) | **CLOSED** | `services/token_counter.py:131-149` — новый `resolve_context_tokens(token_value, token_default)`: `<0` → `CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS` (env-only, 32000), `0/None/мусор` → `token_default` с клампом `max(1, …)` (D-8 — отрицательный env-дефолт больше не даёт `safe_budget(-1)=1`), `>0` → cap; `resolve_chat_limit` использует его для **всех** токенных значений, а fallback-ветка `None` + chars-env → chars (и переведена в `debug` как «аварийный путь»). **Проба:** `resolve_chat_limit(-1,…,5000) → ('tokens', 32000)`, `budget = 27826` (было **1**); `0/None → 5000`, `budget = 4347` (было **1**); `5000 → 5000/4347` ✓; текст на потолке сохраняется. `_apply_context_budget` (`:1215-1245`) при `unlimited` **не** применяет агрегатное усечение и пишет `record_context_usage(total, None, False, unlimited=True)` (D-7), при `0/None` берёт глобальный дефолт (16000) — прежние «1 токен» для `0` устранены. Потребители контекст-ключей проверены все: `direct_chat_service:2087/2196/2219` (call-sites `resolve_chat_limit`), `:824/:1223` (бюджет), `:865-885` (инвариант через `resolve_context_tokens`), `summary_generator:172` (та же `resolve_chat_limit`), `oversight` (через `context_state`), `status_service` (D-7). Регресс-тесты `TestGlobalContextNotStarved`/`TestAggregateBudgetUnlimited` + `test_vip_seed_keeps_context_unlimited` закрепляют: `−1` в VIP-сиде больше не «срезает контекст до 1 токена». |
| S10.19-14 (Medium) | **CLOSED** | `services/oversight.py` — `WORKER_DEFAULT_LIMITS` (60/300 000) + в `_limits_metric(contour='worker')` при **пустом** `day_rows` лимит резолвится `chat → global → default` и подставляется в `limit` (только когда строки отсутствуют — при наличии строки её per-chat `limit` сохраняется приоритетным). **Проба:** нет строк + per-chat `−1` → `limit=-1, unlimited=True, forbidden=False` (было `limit=0, forbidden=True`); настоящий `0` в строке дня по-прежнему `forbidden=True` ✓. Тест `TestWorkerQuietChatLimit`. |

### 9.2. Новые находки Батча D

| ID | Sev | File:line | Суть | Рекомендация |
|---|---|---|---|---|
| S10.19-18 | Info | `services/direct_chat_service.py:831-885` (`_check_context_config_invariant`) | Инвариант помечает чат «предупреждённым» **до** проверки (`warned.add(chat_id)` в начале) и после первого вызова больше не пересчитывается: если первая сборка ответа имела малый `fixed_est` (предупреждения нет), а позже неприкосновенные блоки разрослись (или оператор снизил `CHAT_CONTEXT_BUDGET_TOKENS` в рантайме), «возможное двойное усечение» останется невидимым до рестарта. Формула при этом совпадает с применяемой логикой (`effective = max(1, budget − fixed)`, доли `max(1, int(effective×ratio))`, `safe_budget`-потолки) ✓, спама нет (ровно 1 WARNING на чат) ✓. | Помечать чат «предупреждённым» после фактической проверки (или сбрасывать флаг при смене конфигурации/по TTL) — тогда поздняя рассинхронизация тоже будет видна один раз. |
| S10.19-19 | Info | `services/token_counter.py:163-172` | Chars-fallback (`токенный лимит не задан нигде` + `*_CHARS` задан в env) понижен с `WARNING` до `debug` и объявлен «аварийным». В дефолтном конфиге путь не срабатывает (токенные лимиты заданы: .env `SUMMARY_MAX_CONTEXT_TOKENS=60000`, code-дефолты 5000/3000), но если оператор задаст только `CHAT_GLOBAL_CONTEXT_MAX_CHARS`/`SUMMARY_MAX_CONTEXT_CHARS` без токенных — фактический режим лимитирования (символы вместо токенов) сменится **незаметно** в journald. | Вернуть `INFO` (rate-limited/один раз на процесс) или валидировать конфиг на старте — «аварийный путь» не должен быть полностью тихим. |
| S10.19-20 | Info | `services/status_service.py:508-520`; `services/config_migrations.py:51-55` | Две мелкие дисплейные/миграционные неоднозначности: (а) виджет «Статуса» берёт `limit = acct.context_limit or ctx_cap`, где `ctx_cap` — **глобальный** `hot.get(limits.chat_context_budget_tokens)`; при глобальном `−1` и отсутствии свежей accounting-записи (`unlimited` ещё не отражён) в API уйдёт `limit: -1`, и UI (проверяет `unlimited`, а не знак) покажет «-1» вместо «Безлимит (∞)» — для per-chat `−1` не воспроизводится (accounting пишет `unlimited=True`); (б) миграция `CONTEXT_LIMIT_MIGRATIONS` правит только `4000→16000`: если в PG лежит легаси-значение из старого `.env` (`CHAT_CONTEXT_BUDGET_TOKENS=24000` эпохи Epic 64), оно считается кастомом → WARNING и остаётся 24000 (больше целевого — не вредно, но «869»-цель достигается за счёт Global/Thread-потолков, а не общего бюджета). | (а) отдавать `limit: None`, если `ctx_cap < 0` (или брать `unlimited` из `context_state(ctx_cap)`); (б) при желании — расширить миграцию вторым признаком «24000 = легаси-дефолт» либо зафиксировать в отчёте @DevOps. |
| S10.19-21 | Info | `plans/ARCHITECTURE.md` (§40/§23) | **Док-пробел эпика:** ARCHITECTURE пока не описывает факты F3/F4/F5 — нет §41 (10.19 продолжение), нет упоминаний `resolve_context_tokens`, `CHAT_CONTEXT_UNLIMITED_CEILING_TOKENS` (env-only ClassVar, 32000), новых контекст-дефолтов 5000/3000/16000 и sentinel-таблицы контекста; §40 покрывает только F2. | Добавить параграфы F3 (Бюджеты/VIP-сид/Сводка), F4 (контекст-sentinel/потолок/дефолты + миграция), F5 (объединённый блок «Статуса») — штатно делает @Memory при merge. |
| S10.19-15 | Low | `services/oversight.py:205-216` | **Остаётся открытым (перенос из Батча C):** `_limits_block` по-прежнему вызывает `chat_usage.key_status` **дважды** на чат (по разу на метрику direct-контура) → 2× `budget_snapshot`/`used_today` на чат за построение «Сводки» (кэш 60 с). | Один `key_status` на чат → забрать обе метрики из результата (2 строки кода). |

### 9.3. Верифицировано чисто (Батч D)

- **Sentinel во всех call-sites:** grep по трём контекст-ключам (`chat_global_context_max_tokens`/`chat_thread_max_tokens`/
  `chat_context_budget_tokens`) — потребители только: 4 call-sites `resolve_chat_limit` (direct ×3 + summary), бюджет
  `_apply_context_budget` (sentinel), инвариант (`resolve_context_tokens`), `oversight` (`context_state`),
  `status_service` (D-7), миграция. Путей, где `−1` всё ещё даёт 1 токен или `0` трактуется как cap, не найдено
  (проба + чтение); `_apply_context_budget` при `0/None` берёт `settings.CHAT_CONTEXT_BUDGET_TOKENS` (16000), не 0.
- **Распределение бюджета и двойное усечение:** доли применяются от `effective = max(1, budget − fixed_tokens)`
  (`fixed` — только неприкосновенные kinds), `share = max(1, int(effective×ratio))`; `global`/`thread` исключены из
  **первого** агрегатного прохода (они уже ограничены своими потолками в сборщиках) и участвуют только в цикле
  фактического переполнения `total > budget`; инвариант сравнивает **те же** доли с `safe_budget(cap)` и учитывает
  `fixed_est` (D-1) → при дефолтах (16000, 0.30/0.20, caps 5000/3000) предупреждений нет, при росте fixed — одно
  WARNING (тесты `test_invariant_warns_when_budget_below_caps`/`test_invariant_accounts_for_fixed_tokens`).
- **Отсутствие тихих усечений:** per-block усечения `_apply_context_budget` и `_build_global_context`,
  а также миграции/инвариант — с WARNING/INFO; единственное понижение уровня — chars-fallback (см. S10.19-19,
  в дефолте не срабатывает).
- **Миграция `migrate_context_limit_defaults`:** идемпотентна, правит только `1000/500/4000 → 5000/3000/16000`,
  кастом → WARNING, `None`/отсутствует → skip, PG down → skip (тесты); порядок в `bot.py`:
  `migrate_dream_thresholds` → `migrate_global_budget_defaults` → `migrate_context_limit_defaults` →
  `apply_vip_seed` (сид применяется **после** миграций; сид пишет per-chat, миграции — глобально, пересечений нет).
- **VIP-сид `−1` (главная проверка S10.19-13):** теперь означает «безлимит до потолка безопасности 32000»
  (`resolve_context_tokens`) + агрегатное усечение отключено + учёт `unlimited` для UI — контекст VIP-чата
  не срезается; `test_vip_seed_keeps_context_unlimited` ✓.
- **F5 UI:** «Сердцебиение + Бот + Сервер» — один блок `.status-block` с `.status-block__grid` (1fr / 1.4fr-1fr-1.2fr
  от 768px), строка «Режим … · версия …» удалена, `prefers-reduced-motion`/EKG/управление сохранены;
  **новых inline-стилей нет** (по грепу: было 44 `style=` в HEAD → стало **43**, `grid-column` переведён в CSS);
  поиск по графу компактен (mobile: `padding .3/.5rem`, `font-size .8rem`; desktop `max-width: 460px`, `flex 1 1 220px`),
  логика поиска/подсветки/сброса не тронута (тесты `TestGraphSearchCompact`), CSP/self-host без изменений
  (правки только CSS/HTML/JS; CDN не добавлен); API-контракт «Статуса» аддитивен (D-7 `unlimited`), поля сохранены
  (`test_api_fields_kept`).
- **D-7:** безлимит → `record_context_usage(..., limit=None, unlimited=True)` → `status_service` отдаёт
  `limit: null, unlimited: true` → UI «Безлимит (∞)» вместо ложных 100 %; `app.js` `cap = unlimited ? 0 : …`,
  `limit: cap || null`, `budgetRatio` → 0 % ✓.
- **Каталог:** Δ Батча D = 0 — **437/407/412/92/90/20** (интроспекция); тексты трёх контекст-ключей обновлены
  («0 — не задано (глобальный дефолт); −1 — безлимит (ограничен потолком безопасности)») — теперь соответствуют
  реализации ✓.
- **Валидатор:** `.venv/Scripts/python.exe -m pytest -q` → **6262 passed / 0 failed** (84.34 c);
  `node --check web/app.js` OK; `routing_test.js` `JS-UNIT-OK`; `vue_mount_test.js` `VUE-MOUNT-OK`;
  `git diff --check` → exit 0.

### 9.4. Итог Батча D и вердикт

| Severity | Открыто | Закрыто | Коды открытых |
|---|---|---|---|
| Critical | **0** | 0 | — |
| High | **0** | **1** (S10.19-13) | — |
| Medium | **0** | **1** (S10.19-14) | — |
| Low | **1** | 0 | S10.19-15 (перенос из Батча C) + S10.18-29 (10.18) |
| Info | **10** | 0 | S10.19-9…-12, -16…-21 + S10.18-* (перенос) |

- **ВЕРДИКТ: переход к финальным фичам (F6 медиа/аватары + F7 retention/здоровье) — РАЗРЕШЁН.**
  High S10.19-13 и Medium S10.19-14 закрыты (проверено независимо, пробы в §9.1); sentinel контекста реализован
  во всех потребителях, «1 токен»-мина устранена, миграция дефолтов идемпотентна, F5 UI чист по CSP/inline/API.
  Открытый Low S10.19-15 — перф «Сводки» (не блокер); Infos — наблюдения/дисплейные нюансы.
- **Валидатор:** pytest **6262/0**; JS-гейты OK; `git diff --check` exit 0; каталог 437/407/412/92/90/20; SQLite v10.

### 9.5. Что обновлено (Батч D)

- `plans/reports/round10.19_scanner_audit.md` — эта секция (§9) + подтверждение статусов §8.5.
- `plans/reports/global_map.md` — секция «Round 10.19 — БАТЧ D» + baseline.

*Секция Батча D сгенерирована @Scanner 16.09.2026 (Шаг 6 OpenSpec, Strict Workflow).*

## 10. БАТЧ E — F6 `media-files-avatars-sync` + F7 `memory-retention-health` (аудит @Scanner 16.09.2026, после UPD4)

> **Область:** `services/chat_settings_seed.py` (renamed из `vip_seed`), `config/chat_settings_seed.json`,
> `services/retention_policy.py`, `services/memory_maintenance.py` (archive/fsync/гейт/purge), `services/database.py`
> (v11, `_delete_fts_rows`, `purge_imported_history`, `select_imported_history`, health-счётчики),
> `services/media_integrity.py` (новый), `services/media_download.py`, `web/api/avatars.py`,
> `web/api/routes.py` (`/api/status/media-health`), `web/api/memory_agi.py` (health + TTL), `services/oversight.py`,
> `config/settings.py` (env-гейты ClassVar), `bot.py`, `manage.py`, `web/app.js`, `web/index.html`,
> прочие тесты (`test_chat_settings_seed_round1019`, `test_memory_retention_round1019`,
> `test_media_integrity_round1019`, `test_memory_health_round1019`, `test_avatars_round1019`).
> **Эталон:** `plans/features/{media-files-avatars-sync,memory-retention-health}/{spec,adr-1019-5,adr-1019-6,tasks}.md`,
> `adr-1019-8`, **`plans/current_task.md` UPD4 (219-240)**, spec F7 §10 (SQL-чеклист @DevOps).
> **Метод:** `git diff`/чтения `file:line` + grep всех call-sites purge/`run_import_retention`/`apply-chat-overrides` +
> **собственная проба SQLite v11** (legacy DB → `initialize()` → изоляция/идемпотентность) + подсчёт inline-стилей +
> полный pytest/JS-гейты/`git diff --check` + интроспекция каталога.

### 10.1. Деструктивные операции — главный блок (данные/безопасность)

**Верифицировано чисто (нет пути «DELETE без архива»):**

| Барьер | Факт (проверено чтением/тестами) |
|---|---|
| Единственный call-site | `run_import_retention` — **единственный** прод-call-site (`summary_memory.compress_and_purge` + CLI `manage.py retention`); `DatabaseService.purge_imported_history` вызывается только оттуда (3×: подсчёт → «fixed»-подсчёт → purge). HTTP-эндпоинта purge нет. |
| Keyword-only allow-list | `purge_imported_history(*, chat_cutoffs: dict, …)` — **без дефолта**: «удалить всем по глобальному сроку» невозможно по построению (`test_structural_guard_no_mapping`). |
| Архив → fsync → DELETE | `_archive_imported_history` обязателен: failure → `reason='archive_failed'`, строки НЕ удаляются, частичный файл `unlink` (`test_archive_failure_keeps_rows`); `fh.flush() + os.fsync` через `asyncio.to_thread` **до** первого DELETE (`test_archive_fsync_before_first_delete`, `test_flush_and_fsync_calls_os_fsync`). |
| Точное множество | `chat_max_ids` → `id <= max_id` (верхняя граница заархивированного) + сверка `candidates(fixed) != archived` → `reason='archive_mismatch'`, purge **не выполняется** (`test_chat_max_ids_limits_to_archived_set`, `test_archive_mismatch_aborts_purge`). |
| Fail-closed (chat-слой) | `retention_policy` при `source='error'` (chat-слой не читается) → `(0, 'error')`; `run_import_retention` при любом таком чате **отменяет прогон целиком** (`reason='chat_layer_unavailable'`) — cutoffs из fail-open дефолта 180 не строятся (`test_real_resolver_chat_layer_unavailable_fail_closed`, `test_real_resolver_unavailable_layer_aborts_whole_run`, D-1). |
| Fail-safe (сид) | `enforce`-чат (`retention` в `enforce`) → `seed_enforced` (purge запрещён всегда, D-1 defence-in-depth); **нечитаемый/битый сид** → `seed_unavailable` → purge запрещён (D-2.4, `test_unreadable_seed_denies_purge`). |
| Sentinel retention | `0` = вечно (никогда не в cutoffs: `test_eternal_zero_never_in_cutoffs`), `>0` = cap, `<0`/мусор → глобальный дефолт + WARNING (без рекурсии — D-2.1, `test_invalid_global_default_no_recursion`). |
| Тройной гейт авто-крона | DELETE только при `IMPORT_RETENTION_ENABLED=true` **И** `IMPORT_RETENTION_DRY_RUN=false` **И** `IMPORT_RETENTION_BACKUP_CONFIRMED=true` (`auto_purge_dry_run`); дефолты — OFF/ON/OFF (`test_env_gate_defaults_safe`, `test_auto_purge_gate_requires_backup`, `test_backup_unconfirmed_forces_dry_run`). CLI: `--apply` обязателен, `--apply --dry-run` → dry-run (`test_manage_cli_retention_dry_run_and_apply`). |
| Per-chat purge | `WHERE chat_id = ? AND import_key IS NOT NULL AND history_processed = 1 AND timestamp < cutoff` — live-сырьё и необработанное не трогаются (`test_purge_only_mapped_chats_and_processed`); `dry_run=True` → только подсчёт (`test_dry_run_counts_without_deleting`). |

**Моя независимая проба SQLite v11** (legacy-БД с глобальным UNIQUE + `import_checkpoints(path PK)` → `initialize()`):
`user_version=11`; глобального `idx_smart_messages_import_key` нет, есть `idx_smart_messages_chat_import_key`;
`import_checkpoints` пересобран в `(path, chat_id)` с legacy-строкой → `chat_id=0` (данные сохранены);
повторный `initialize()` — идемпотентен; **один и тот же `import_key` в двух чатах → 2 строки** (cross-chat дефект
закрыт); FTS/vec не пересоздаются (таблица-источник не rebuild'ится). Rebuild идёт в **одной транзакции**
(`BEGIN → DROP _old → RENAME → CREATE → INSERT → DROP _old → COMMIT`, rollback при ошибке — D-Low).

### 10.2. Новые находки Батча E

| ID | Sev | File:line | Суть | Рекомендация |
|---|---|---|---|---|
| S10.19-23 | Low | `services/memory_maintenance.py:389-425` (`_archive_imported_history`/`_flush_and_fsync`) | **Долговечность архива: fsync есть у ФАЙЛА, нет у КАТАЛОГА.** При сбое питания сразу после создания архива и SQLite-commit запись каталога (имя файла) может не попасть на диск — тогда строки удалены, а файла-архива «нет» (окно крайне узкое; POSIX требует fsync родительского каталога для гарантии имени; ext4/auto_da_alloc обычно спасает). Это единственная недозакрытая щель в заявленном инварианте «архив переживает сбой РАНЬШЕ DELETE». | После `fsync(file)` (best-effort) синхронизировать каталог: `os.open(dir, O_RDONLY)` + `os.fsync` в том же `to_thread` (POSIX; на Windows — no-op), либо явно задокументировать остаточный риск. |
| S10.19-22 | Info | `services/memory_maintenance.py:487-497` | Финальный `purge_imported_history(..., dry_run=False)` **не обёрнут** try/except, хотя docstring `run_import_retention` обещает «Fail-open: ошибки БД → нули (не 500)». Оба вызывающих защищены (авто-крон — try/except + WARNING; CLI — traceback/exit≠0), HTTP-пути нет → 500 невозможен, архив уже записан (данные не теряются). | Обернуть финальный purge (вернуть `reason='purge_failed'`) либо поправить формулировку docstring. |
| S10.19-24 | Info | `services/memory_maintenance.py:368-372`; `services/summary_memory.py:72` | Архивы `MEMORY_BACKUP_DIR/imported_history_<ts>.jsonl` **не ротируются**: каждый прогон создаёт новый файл со всем набором кандидатов (ротация `MEMORY_BACKUP_KEEP` относится только к бэкапам БД). При большом импорте архив может занять ГБ и накапливаться (интервал авто-шага — 6 ч, `_IMPORT_RETENTION_INTERVAL`). | Добавить prune старых `imported_history_*` (N последних/по возрасту) или @DevOps-шаг очистки; метрика `storage.disk_free_bytes` в health уже есть. |
| S10.19-25 | Info | `services/memory_maintenance.py:395-420` | Запись архива идёт **в event loop** (offload только `fsync`): на многогигабайтном архиве цикл батчей периодически упирается в синхронный flush OS-буфера (между батчами await → stall ограничен). Неверных данных не даёт. | Ожидаемо для редкой maintenance-операции; при желании — `asyncio.to_thread` на запись батча. |
| S10.19-26 | Info | `services/media_integrity.py:143-176` | `orphan_files`/`missing_on_disk` считаются от **bounded-выборки** текстов (200 последних непустых) → `orphan_files` систематически завышен (файлы, чьи сообщения не попали в выборку). Контракт честный (`reliable:false`, `basis:'text_scan'`, в логе `reliable=false`), UI-блок по спеке F6 §9.1 — «по желанию». | Если @PM/DevOps будет показывать числа — подписать «эвристика по тексту» (поля `reliable`/`basis` уже в ответе); не выдавать за точный рассинхрон. |
| S10.19-27 | Info | `tests/test_betterstack_handler.py` (`test_real_302_not_followed_by_opener`) | Тест поднимает **реальный локальный HTTP-сервер** (два `ThreadingHTTPServer`) — единственный «сетевой» тест набора; в моём прогоне зелёный, но он чувствителен к занятости портов/таймингам в CI (флейки-риск, не продуктовая проблема — это и есть доказательство D-01). | При повторах — `pytest.mark.flaky`/retry или skip-guard, чтобы флейк не путали с регрессом. |

### 10.3. Верифицировано чисто (Батч E)

- **Универсальность (UPD4 п.1):** код-путь сида generic (`for entry in seed["chats"]`), id — только в
  `config/chat_settings_seed.json` (+тесты); в `services/`/`web/`/`handlers/` конкретный id встречается лишь в
  **legacy** `services/chat_lore.py` (`CHAT_LORE_TARGET_CHAT_ID`, раунд 5 — не VIP-политика, разрешено ADR-1019-8 D4);
  остатков «VIP» в коде нет (grep: только исторические тексты отчёта и tasks.md); CLI переименован
  (`manage.py apply-chat-overrides`), мета-ключ — `chat_settings_seed_version`, источник — `seed_enforced`;
  `__pycache__/vip_seed*.pyc` — локальный stale-артефакт, **untracked/`.gitignore`** (`git ls-files` пуст) → репо чист.
- **SQLite v11 (ADR-1019-6 D1b/D7):** см. §10.1 (проба) — идемпотентность, транзакционный rebuild, `DROP …_old`,
  `user_version` всегда, порядок в `initialize()` после v10, FTS/vec не затронуты; `tools/history_import/checkpoints.py`
  — `get/set/done` с `chat_id` (default 0 для совместимости), таблица создаётся сразу с `(path, chat_id)`.
- **Изоляция памяти между чатами:** `UNIQUE(chat_id, import_key)` (v11) + checkpoint `(path, chat_id)` (проба +
  `TestIsolationV11`: один контент в двух чатах → 2 строки, дубль в одном чате — отклонён, чекпоинты чатов
  независимы); purge — строго per-chat; других новых кросс-чат путей батч не вводит (RAG/KNN/кэши не тронуты).
- **F6 (медиа/аватары):** `local_file_path` — traversal-guard (`is_absolute` + `resolve().is_relative_to(root)`);
  R17 — логи без `<bot_id>:<token>` и без `exc_info` на `OSError` (только `src.name`/тип ошибки);
  `read_local_file_bytes` (чтение в `to_thread`, ≤3 ретрая) + fallback на прежний `bot.get_file/download_file`;
  `fetch_media_to_tmp` переведён на общий `_read_local_source` (поведение прежнее: 3 попытки/1.0 с + `bot.download`);
  `_scan_disk` — в `asyncio.to_thread`, bounded 20 000 записей; метрики честные (`reliable:false`/`basis:'text_scan'`);
  `/api/status/media-health` — аддитивный, TTL 120 с на `chat_id`, fail-open `{available:false}` без БД/бота.
- **Health-метрики (F7):** `/api/memory/health` — аддитивно (`facts_overdue`, `facts_unconfirmed`,
  `smart_messages_total`, `deep_sleep_runs_total`, `storage{db_size_bytes,db_size_mb,disk_free_bytes}`; существующие
  ключи целы), тяжёлые COUNT'ы под TTL 60 с (кэш по идентичности `db`), `storage` — только `stat`/`disk_usage`
  (fail-open нули); `db.db_path` существует ✓; UI-блок «Здоровье памяти» отрисовывает метрики (index.html:2344+).
- **Каталог/инварианты:** Δ Батча E = 0 — **437/407/412/92/90/20** (интроспекция); env-гейты retention —
  `ClassVar` (в каталог не входят); DDL в PG нет, SQLite v11 авто-миграцией при старте; порядок роутеров `bot.py`
  не тронут; сид применяется после миграций (`migrate_*` → `apply_chat_settings_seed`).
- **Валидатор:** `.venv/Scripts/python.exe -m pytest -q` → **6323 passed / 0 failed** (82.31 c);
  `node --check web/app.js` OK; `routing_test.js` `JS-UNIT-OK`; `vue_mount_test.js` `VUE-MOUNT-OK`;
  `git diff --check` → exit 0.

### 10.4. ИТОГОВАЯ СВОДКА ЭПИКА 10.19 (БАТЧИ A–E) — для Merge/деплоя

| Severity | Открыто | Коды |
|---|---|---|
| Critical | **0** | — |
| High | **0** | — |
| Medium | **0** | — |
| Low | **2** | S10.19-15 (двойной `key_status` в «Сводке»), S10.19-23 (fsync каталога архива) + S10.18-29 (10.18, manual-deep-маркер) |
| Info | **16** | S10.18-12/-13/-18/-19/-20/-31/-32/-33/-37/-38; S10.19-9…-12, -16…-22, -24…-27 |

**Закрыто по эпику:** S10.18-1 (High), S10.18-2…-6 (Medium), S10.18-7…-11/-14 (Low/Info), S10.18-15 (Medium),
S10.18-16/-17 (Low), S10.18-21/-22 (Medium), S10.18-23/-24/-25 (Low), S10.18-26 (Info), S10.18-30 (Medium),
S10.18-35 (Low), S10.18-36 (Info); S10.19-1/-2 (Low, Батч A), S10.19-7/-8 (Low, README+миграция дефолтов),
**S10.19-13 (High) и S10.19-14 (Medium) — Батч D (проверено независимо)**.

**Вердикт по эпику: 0 Critical / 0 High / 0 Medium открыто → эпик готов к Merge/архивации и двухэтапному
деплою** (см. §10.5). Открытые Low/Info — не блокеры (S10.19-15 и S10.19-23 рекомендую закрыть в ближайшем
follow-up; S10.18-13 — pre-existing, вне батчей, трекается как R10.18-12).

### 10.5. Обязательные @DevOps-гейты (SQL-чеклист, бэкап, dry-run)

| # | Шаг | Команда/запрос | Ожидание / abort-условие |
|---|---|---|---|
| D1 | Dry-run retention (до любых изменений) | `python manage.py retention --dry-run` | `mode=dry-run`, `reason` ∈ {`dry_run`,`no_candidates`}; кандидаты — без целевого чата (у него retention `0`). Данные не меняются. |
| D2 | Бэкап БД + `.env` | бэкап SQLite/PG (@DevOps-процедура) → `IMPORT_RETENTION_BACKUP_CONFIRMED=true` **только после проверки бэкапа** | Без подтверждённого бэкапа авто-крон остаётся dry-run (WARNING в логе). |
| D3 | Применение миграций/сида | рестарт бота (авто: v11 + `migrate_*` + `apply_chat_settings_seed`) или `python manage.py apply-chat-overrides` | идемпотентно; `applied`/`skipped`; **другие чаты не меняются**; `PRAGMA user_version` (SQLite) = **11**. |
| D4 | **Post-Deploy Gate (боевая БД, строго ДО крона)** | SQL из spec F7 §10 (`chat_params -> 'overrides'` целевого чата, 8 ключей) | ровно: retention **0**, бюджеты ключа/фона и контекст **−1**. Любое расхождение → **abort деплоя + откат**, рестарт/крон НЕ запускать. |
| D5 | BetterStack | `.env`: `BETTERSTACK_HOST` (US-ingest) + `LOGTAIL_SOURCE_TOKEN` = **Source Token**; рестарт | в journald `[betterstack] attached \| host=… \| token_len=…`; нет `send failed \| reason=status=401`; curl-матрикс T-1779 (только коды, маскированно) — US×Bearer = 202. |
| D6 | Live-проверка контекста/бюджетов | написать боту в целевом чате; `GET /api/memory/cognition/status?chat_id=…`, `/api/oversight/summary`, `/api/memory/health` | ответ с расширенным контекстом (симптом «7000→869» снят); в «Сводке» — «Безлимит (∞)» по обоим контурам, «Импорт: Вечно»; health отдаёт `storage`/`facts_overdue`. |
| D7 | Фактический purge (по решению владельца) | `python manage.py retention --apply` (после D1–D4) | `archived == deleted` при `reason=ok`, файл `imported_history_*.jsonl` создан; размер БД падает; целевой чат не затронут. Авто-крон (`IMPORT_RETENTION_ENABLED`) оставить OFF, пока не подтверждён ручной прогон. |
| D8 | Откат (при инциденте) | `git revert`; retention → `0`; индекс v11 обратим (`DROP INDEX …chat_import_key` + `CREATE UNIQUE INDEX idx_smart_messages_import_key`); восстановление из бэкапа/архива | данные не теряются; архив — второй рубеж. |

### 10.6. Что обновлено (Батч E)

- `plans/reports/round10.19_scanner_audit.md` — эта секция (§10) + итоговая сводка эпика (§10.4) + @DevOps-гейты (§10.5).
- `plans/reports/global_map.md` — секция «Round 10.19 — БАТЧ E» + **финальный baseline** (pytest 6323/0,
  каталог 437/407/412/92/90/20, SQLite v11, открытые риски, @DevOps-гейты).

*Секция Батча E и итоговая сводка эпика 10.19 сгенерированы @Scanner 16.09.2026 (Шаг 6 OpenSpec, Strict Workflow).*




