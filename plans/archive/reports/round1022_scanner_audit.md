# Round 10.22 — Step 6 @Scanner: независимый diff-based аудит (раунд UPD3)

> **Дата:** 19.09.2026 · **Агент:** @Scanner · **Раунд:** 10.22 (F1–F8, System 2 двухвызовные пайплайны + egress-guard + async rebuild досье)
> **Baseline:** HEAD `acd9311` + рабочее дерево (не закоммичено — коммит Шаг 9 @DevOps).
> **Контекст:** @Reviewer — `Approved` (итерация 3); полный `pytest` — **6953 passed / 0 failed** (заявление @Reviewer; я целиком не перегонял).
> **Метод:** `git status`/`git diff`, чтение новых модулей (`dossier_rebuild_jobs`, `outgoing_guard`, `negative_constraints`, `telegram_send`, `system2_handoff`) и интеграций (F1/F3/F4/F5/F6/F7/F8), целевой `pytest` (229 тестов), JS-гейты, `git diff --check`, ad-hoc пробы по спорным веткам (fail-open детектора клише, read-error защиты belief-опор, байт-тест справки, схема БД).
> **R17/R18:** секретов в новом коде/тестах/отчёте/артефактах не найдено (regex-скан новых файлов на `sk-*`/`bot-token`/`Bearer`/DSN — пусто; `backups/` gitignored).

---

## Сводка

| Severity | Кол-во | Открыто на выходе | Блокирует? |
|---|---|---|---|
| Critical | **0** | 0 | — |
| High | **0** | 0 | — |
| Medium | **2** | 2 | нет |
| Low | **4** | 4 | нет |
| Info | **3** | 3 | нет |

**ВЕРДИКТ: 0 Critical / 0 High открыто → рабочий процесс НЕ блокируется (§Шаг 7 разрешён).**
Medium/Low/Info — необязательные follow-up; каждое имеет доказательство и рекомендацию.

Проверенные зоны: F1 (cleanup confirmed: скоуп/пагинация/JSONL+сверка/защита belief-опор/target-guard), F2 (`_ensure_keyvalue_object`), F3–F5 (изоляция Stage-2, fallback, стоимость), F6 (regex/детектор/охват send-точек/валидатор-loop), F7 (канон v3→v4, байт-тест, h1/h2/blockquote), F8 (job-store/rollback/гонки/персистентность/RBAC/retention), инварианты (Δкаталога=0, SQLite v12, порядок роутеров, R17/R18, `git diff --check`).

---

## Находки

### S10.22-1 [Medium] F1: защита belief-опор fail-open — ошибка чтения beliefs молча обнуляет `protected_ids`

- **Файл:** `services/memory_rebuild.py:775-812` (`_belief_source_set`, `except Exception: return out` на `:788-789`); вызывающий `:838-842` (`cleanup_confirmed_dossier_facts`).
- **Суть:** `_belief_source_set` при ЛЮБОЙ ошибке чтения `_list_beliefs` **внутри себя** возвращает уже накопленный (возможно пустой) `set` вместо проброса исключения. Внешний `try/except` в `cleanup_confirmed_dossier_facts` (`:840-844`) так и не срабатывает (он рассчитан на raise), поэтому чат НЕ помечается `read_error` — cleanup продолжает выборку `confirmed`-фактов с пустым набором защиты и **удаляет опоры живых убеждений/парадигм** (ровно класс восстановления прецедента S10.21-3). Удалённое попадает в JSONL-архив, но `belief_meta`/`source_ids` в БД теряют провенанс → в следующем `sanitize_beliefs` убеждение получает `missing_sources` и удаляется каскадом.
- **Доказательство (ad-hoc проба):** monkeypatch `mr._list_beliefs` → `raise RuntimeError('simulated locked')`; `await mr._belief_source_set(object(), 1, 2000)` вернул `set()` (пусто), исключение не поднялось. Т.е. не «fail-closed по докстрингу», а fail-open.
- **Рекомендация:** убрать внутренний `except` (дать ошибке дойти до внешнего обработчика `:840-842`, который выставит `read_error` и пропустит чат), либо возвращать `(out, ok)` и при `ok=False` аварийно прерывать cleanup этого чата (fail-closed как у JSONL-сверки). Затрагивает F1 (CLI) и F8 (раннер вызывает тот же примитив).
- **Почему не High:** триггер — ошибка чтения (сбой/лок БД), вероятность низкая; откат частично обеспечен JSONL-архивом и (для F8) стартовым снапшотом.

### S10.22-2 [Medium] F8: раннер ставит `done` при `cleaned > 0 && rebuilt == 0` — инвариант F1 `rebuild_empty` не зеркалится, откат `done` из UI недостижим

- **Файл:** `services/dossier_rebuild_jobs.py:694-710` (после `written = ... rebuild_dossier_for_user` безусловный `status="done"`); `web/api/chat_lore.py:975-994` (`_rebuild_rollback_retryable` — только `failed`), `:1190-1192` (terminal → 200 без действий).
- **Суть:** F1/ADR-1022-1 §5 прямо запрещает молчаливый «успех»: `reset > 0 & rebuilt == 0 → reason rebuild_empty` + ненулевой exit. В F8 аналога нет: если окно пересборки пустое (`rebuild_dossier_for_user` ранний `return 0` при `not lines`, `services/lore_worker.py:791-794`) или извлечение/бюджет дали 0, но `cleanup_confirmed_dossier_facts` уже удалил confirmed-факты участника, job получает `status=done`. UI показывает «Готово: очищено N, пересобрано 0»; кнопки отката нет (rollback доступен только для `cancelling`/`cancelled`/`interrupted`/`failed`), т.е. пользователь **не может** восстановить досье из стартового снапшота через API. Это расходится и с R4-духом спеки F8 («статус не done» при проблемном исходе).
- **Доказательство:** тесты `tests/test_dossier_rebuild_round1022.py` покрывают `done` с новыми данными, `cancel→rollback`, `snapshot_failed`, `interrupted→manual rollback`, `failed rollback_failed`, но НЕ покрывают `cleaned>0/rebuilt==0` (grep `rebuild_empty`/`empty` — совпадений по этой ветке нет). Код-путь: `:697` (`written=0`) → `:708-710` (`status="done"`).
- **Рекомендация:** зеркалировать инвариант F1 — при `cleaned > 0 && written == 0` переводить job в `failed` (код `rebuild_empty`) либо оставлять `done`, но делать снапшот доступным через ручной откат (расширить `_rebuild_rollback_retryable` на `cleaned>0 && rebuilt==0`). Минимально — WARNING + `error_code=rebuild_empty` в job-view.

### S10.22-3 [Low] F6: `handlers/voice_transcription.py` в allowlist по неверному обоснованию — модель-сгенерированный транскрипт идёт мимо egress-guard

- **Файл:** `services/telegram_send.py:50` (`"handlers/voice_transcription.py": "UX-фразы расшифровки голоса"`); `handlers/voice_transcription.py:202-215` (`await message.reply(f"{label} 🗣: <i>{escaped_text}</i>", parse_mode="HTML")`).
- **Суть:** помимо UX-фраз (строки 163/188/193), этот же файл отправляет **результат ASR-модели** (`text`) через `message.reply` без `sanitize_outgoing`. Тест покрытия (`tests/test_outgoing_guard_round1022.py:104-138`) сверяет только «файл зарегистрирован/в allowlist с непустым обоснованием», поэтому даёт ложную уверенность: точка с модель-сгенерированным текстом формально «обоснована» как UX. Практический риск низкий (ASR-текст редко содержит `<thought>`/`fact:\d+`), но контракт «любой модель-текст через guard» не выполняется.
- **Доказательство:** скан `_SEND_RE` (`.reply(`) находит 4 точки в файле; allowlist-обоснование не отличает transcript (строка 214) от UX-фраз.
- **Рекомендация:** либо перевести отправку транскрипта на `send_text` (с экранированием и `parse_mode`-совместимостью), либо явно расширить обоснование allowlist («ASR-текст, не Stage-2 LLM; технические теги <thought>/ID недостижимы») и добавить тест-инвариант «allowlist-модуль не содержит LLM-вывода». Также стоит явно зафиксировать в allowlist, что caption/media-точки (`send_photo`/`send_video` и т.п.) вне regex-скана.

### S10.22-4 [Low] F6: ложное срабатывание детектора клише `as_ai` на обычном русском тексте

- **Файл:** `services/negative_constraints.py:50-54` (`r"\bкак\s+(?:ии|искусственный\s+интеллект|языковая\s+модель)\b"`).
- **Суть:** паттерн ловит не только само-идентификацию бота («я как ИИ»), но и нейтральные третьеличные сравнения: фраза «Он ведёт себя как искусственный интеллект, без эмоций» → `['as_ai']`. В F3/F4/F5 это запускает до 2 лишних полных регенераций (стоимость/латентность), а при недоступности ретраев — `fallback`; для саммари — ещё и `enabled_rules` с `bullet_list`.
- **Доказательство (ad-hoc проба):** `find_forbidden_cliches("Он ведёт себя как искусственный интеллект, без эмоций.") == ['as_ai']`; при этом «Сегодня я расскажу, как работает искусственный интеллект...» → `[]` (ок), «Я не ИИ, я бот.» → `[]`.
- **Рекомендация:** сузить `as_ai`-ветку до конструкций с субъектом-ботом/первым лицом («я/меня/обо мне … как ИИ») либо добавить отрицательный lookahead на «он/она/оно/это/люди»; либо перевести правило в `secondary` (не блокировать, только статистика).

### S10.22-5 [Low] F8: `interrupted` входит в `_ACTIVE_STATUSES` и не вытесняется retention — блокирует новый старт и копит job-store

- **Файл:** `services/dossier_rebuild_jobs.py:37` (`_ACTIVE_STATUSES` включает `interrupted`), `:291-308` (`_prune` удаляет только не-активные), `:367-375` (`find_active` считает `interrupted` активным); `web/api/chat_lore.py:1107-1115` (409 `already_running`).
- **Суть:** после каждого рестарта процесса незавершённые job'ы навсегда остаются `interrupted`. `find_active` трактует их как активные → пользователь **не может запустить новую пересборку** (409), пока вручную не отменит старый job. Одновременно `_prune` не применяет к ним retention («последние 50 / 7 дней»), т.к. они «активные» — файл `dossier_rebuild_jobs.json` неограниченно растёт при повторных прерываниях.
- **Доказательство:** код `_prune`/`find_active`; тест `test_reconcile_marks_nonterminal_interrupted` фиксирует только статус, не проверяет eviction/разблокировку. UI показывает сообщение и кнопку «Отмена» (интерпретация `dossierRebuildIsActive`), так что обходной путь есть, но неочевиден.
- **Рекомендация:** либо исключить `interrupted` из `find_active` (после чего новый старт вытеснит старый job с обязательным предупреждением), либо дать `interrupted` TTL и prune их по `retention_days`; минимум — авто-подсказка/авто-откат в UI.

### S10.22-6 [Low] F8: kill-switch `DOSSIER_REBUILD_UI_ENABLED=OFF` даёт 404, но кнопка «Пересобрать досье» в UI не скрывается

- **Файл:** `config/settings.py` (комментарий «OFF → rebuild-эндпоинты 404 + кнопка скрыта»); `web/index.html:2730-2780` (карточка рендерится при `dossierUserId != null`, флага нет); `web/app.js` (`startDossierRebuild` → 404 → toast ошибки).
- **Суть:** бэкенд корректно отдаёт 404 (`web/api/chat_lore.py:1002-1007`, тест `test_flag_off_404`), но UI не получает флаг (ClassVar вне `param_catalog`) и продолжает показывать активную кнопку; клик приводит к непонятной ошибке пользователю вместо скрытия фичи.
- **Рекомендация:** отдавать признак доступности (например, `latest` может возвращать `204`/заголовок, или добавить `enabled` в ответ `GET /api/chat_lore/{id}/dossier/...`) и скрывать кнопку при `OFF`, либо убрать из комментария обещание «кнопка скрыта».

### S10.22-7 [Info] `.env.example` не обновлён новыми env-рубильниками раунда

- **Файл:** `.env.example` (188 ключей; `grep` по `SYSTEM2_*`/`TELEGRAM_SEND_GUARD_ENABLED`/`DOSSIER_REBUILD_*` — пусто); `config/settings.py:519-554`.
- **Суть:** прецедент (в файле есть `MULTILAYER_EXTRACTION_ENABLED`, `DEEP_SLEEP_*`) — новые env-only ClassVar-флаги (F6/F3/F4/F5/F8) не задокументированы; оператор не узнает о kill-switch'ах из примера конфига. Не блокер (default ON, осознанно).
- **Рекомендация:** добавить закомментированные строки по образцу `MULTILAYER_EXTRACTION_ENABLED`.

### S10.22-8 [Info] R17: в `summary_generator._llm_generate` остаётся логирование сырого ответа LLM (`raw=%r`)

- **Файл:** `services/summary_generator.py:243-248` (перенесённый из 10.21 код).
- **Суть:** `logger.info("summary LLM raw response | ... | raw=%r", ..., raw)` пишет полный текст ответа (потенциально содержимое чата) в INFO-лог. Не новый дефект (перенос при рефакторинге), но теперь этим же путём логируется и ответ Редактора Stage-1 двухвызовного пайплайна. R17 формально нарушается (логи должны быть counts/коды).
- **Рекомендация:** логировать только `len`/`latency`/класс (прецедент `factcheck_service._invoke_llm`).

### S10.22-9 [Info] Восстановление снапшота строит SQL по именам колонок без allowlist

- **Файл:** `services/dossier_rebuild_jobs.py:513-549` (`restore_user_snapshot`: `cols = [c for c in row.keys()]` → `INSERT OR REPLACE INTO graph_facts ({collist})`).
- **Суть:** имена колонок берутся из JSONL-снапшота и подставляются в SQL напрямую. Файл создаёт само приложение (`SELECT *`, фиксированная схема), поэтому инъекция недостижима без локального вмешательства в каталог `backups/`. Defense-in-depth: white-list колонок `graph_facts`. Унаследованный/accepted остаток (отмечен ревью), не новый блокер.
- **Рекомендация:** сверять `cols` с `PRAGMA table_info` (или фиксированным кортежем) перед построением SQL.

---

## Принятые / унаследованные остаточные (осознанно, не блокеры)

- **R7 ADR-1022-1 (принят владельцем):** F1/F8 удаляют валидные `confirmed`-факты без «swap-порядка» (извлечь→заменить). Компенсация: авто-бэкап `memory_rebuild_*.db`, JSONL-архив `memory_generated_confirmed_*.jsonl`, стартовый снапшот F8. `confirmed`-факты пересборкой НЕ воссоздаются (пайплайн пишет только `chat_meme`/`dossier_portrait`) — это заложено ADR.
- **F8 stale-lock / рестарт:** TTL file-lock (`DOSSIER_REBUILD_LOCK_TTL_SECONDS`, 6ч) допускает «stale takeover» долгого прогона; lock-файл не снимается при рестарте (снимается только ручной отменой job'а). См. S10.22-5.
- **F8 snapshot missing:** если процесс убит во время записи снапшота, `rollback_<job>.jsonl` отсутствует → повторный ручной откат даёт `rollback_failed` (тупик для job'а, но новый старт доступен после отмены).
- **F8 vec-слой не восстанавливается** (best-effort, embeddings не хранятся в снапшоте) — задокументировано.
- **F8 job-store — single-writer in-process:** кросс-процессной защиты самого JSON-файла нет (только per-chat lock). Соответствует однопроцессному запуску web+bot.
- **Caption/media-точки** (`send_photo`/`send_video`/…`) — вне regex-скана egress (подписи без LLM-текста); скан по базам `services/handlers/web` не покрывает `SmartModule/`, `filters/`, `scripts/`, `tools/` — проверено grep'ом, отправок там нет.
- **Pre-existing:** raw-логирование ответов LLM (S10.22-8), подсчёт `total` для прогресса F8 берёт `settings.LORE_WINDOW_MAX_MESSAGES`, тогда как воркер использует `hot.get("limits.lore_window_max_messages")` — возможное расхождение только в отображении X/Y.

---

## Валидатор @Scanner (независимо)

- **Целевой pytest:** **229 passed / 0 failed** — `test_memory_dossiers_cleanup_round1022`, `test_dossier_rebuild_round1022`, `test_outgoing_guard_round1022`, `test_negative_constraints_round1022`, `test_direct_two_call_round1022`, `test_summary_two_call_round1022`, `test_factcheck_two_call_round1022`, `test_aliases_render_round1022`, `test_help_ui_round1022`, `test_prompt_migrations`, `test_param_catalog`.
- **JS-гейты:** `node --check web/app.js` → OK; `round1022_aliases_test.js` → `ALIASES-UNIT-OK`; `round1022_dossier_rebuild_test.js` → `DOSSIER-REBUILD-UNIT-OK`; `round1022_help_test.js` → OK.
- **Инварианты:** `git diff --check` — только LF/CRLF-предупреждения (whitespace-ошибок нет, exit 0); SQLite fresh-DB `PRAGMA user_version = 12`; `info_text.md` **байт-в-байт** равен `DEFAULT_INFO_TEXT`; канон v4 — только `<h1>`×1 / `<h2>`×10 / `<blockquote>`×21, тегов `<h3…h6>` — 0; `KNOWN_INFO_SNAPSHOTS` = 3 (v1/v2/v3) + новый v4.
- **Ad-hoc пробы:** (1) fail-open защиты belief-опор (S10.22-1); (2) 13 кейсов детектора клише, в т.ч. ложное `as_ai` (S10.22-4); (3) схема `graph_facts` (18 колонок, BLOB нет → `restore` не портит данные `default=str`).
- Полный pytest (6953/0) повторно не выполнялся — подтверждён @Reviewer; целевые контуры расхождений не дали.

**ИТОГ КОНТРАКТА: 0 Critical / 0 High открыто. Раунд 10.22 можно передавать @Orchestrator для Шага 7.**
Обязательных пунктов для возврата @Builder нет; S10.22-1/-2 — рекомендуемые Medium-фиксы (при желании закрыть до Merge), S10.22-3…-9 — follow-up.

---

## Re-audit после пост-скан фиксов (раунд 10.22 UPD3, итерация 2, 19.09.2026)

> **Триггер:** @Builder внёс фиксы по 8 находкам. Проверка независимая, по коду/тестам, точечным прогоном.
> **Метод:** повторное чтение изменённых участков, целевой `pytest`, JS-гейты, ad-hoc пробы, инварианты.
> **Baseline:** HEAD `acd9311` + рабочее дерево (не закоммичено).

### Пофакторная верификация

| # | Severity | Вердикт | Доказательство |
|---|---|---|---|
| S10.22-1 | Medium | **закрыто** | `services/memory_rebuild.py:787-814` — внутренний `except` убран, исключение уходит наружу; `:841-847` внешний обработчик пишет `read_error` и делает `continue` (чат пропущен, cleanup не идёт). `_list_beliefs` (`:284-294`) ошибок не глушит → raise доходит. Тест `tests/test_memory_dossiers_cleanup_round1022.py:302-330` (`test_belief_read_error_skips_chat_fail_closed`): `read_error==1`, `cleaned==0`, факт-опора жива (`COUNT(id)==1`). Прошёл. |
| S10.22-2 | Medium | **закрыто** | `services/dossier_rebuild_jobs.py:720-732` — при `cleaned>0 && written==0` job → `status="failed"`, `error_code="rebuild_empty"` (не `done`). Ручной откат достижим: `web/api/chat_lore.py:975-994` (`_rebuild_rollback_retryable` учитывает `cleaned>0`), `:1200-1219` при отсутствии живого task делает `perform_rollback`. UI: `web/index.html:2748-2749,2778-2781` («Повторить откат»), `web/app.js:2841-2847`. Тесты: `tests/test_dossier_rebuild_round1022.py:421-447`, JS `tests/js/round1022_dossier_rebuild_test.js:245-248`. Прошли. |
| S10.22-4 | Low | **закрыто** | `services/negative_constraints.py:50-59` — negative lookbehind `(?<!\bсебя\s)(?<!\bон\s)(?<!\bона\s)(?<!\bоно\s)(?<!\bэто\s)(?<!\bлюди\s)(?<!\bчеловек\s)` перед `как …`. Проба: «Он ведёт себя как искусственный интеллект…» → `[]`; «Оно ведёт себя как…» → `[]`; «я как ИИ, отвечаю» → `['as_ai']`; «Я как искусственный интеллект тут» → `['as_ai']`; «как языковая модель отвечаю» → `['as_ai']`; «Я не ИИ, я бот.» → `[]`. Тест `tests/test_negative_constraints_round1022.py:75-84`. Прошёл. |
| S10.22-5 | Low | **закрыто** | `services/dossier_rebuild_jobs.py:41` — `_ACTIVE_STATUSES = {queued, running, cancelling}`; `find_active` (`:371-379`) больше не считает `interrupted` активным; `_prune` (`:295-312`) теперь применяет retention к `interrupted` (он «терминальный»). API `web/api/chat_lore.py:1116-1125` фиксирует вытеснение WARNING'ом. UI: `web/app.js:2817-2828` (`interrupted` не активен, но отменяем), `web/index.html:2745-2747,2774-2777`. Тесты: `tests/test_dossier_rebuild_round1022.py:167-195` (не блокирует старт + eviction), JS `:88`. Прошли. |
| S10.22-6 | Low | **закрыто** | `web/api/chat_lore.py:1043-1044` — `latest` при `OFF` отдаёт 404 (`_rebuild_disabled`); при отсутствии job — 204 (`:1052-1053`). `web/app.js:2893-2909` — 404 → `dossierRebuildEnabled=false` (прочие ошибки fail-open), 204/200 → `true`. Шаблон `web/index.html:2733` (`v-if="dossierUserId != null && dossierRebuildEnabled"`) прячет карточку. Тесты: `tests/test_dossier_rebuild_round1022.py:1008-1014` (404), JS `:250-264` (скрытие/возврат). Прошли. |
| S10.22-3 | Low | **закрыто (достаточно)** | `services/telegram_send.py:50-56` — обоснование явно отделяет ASR-транскрипт от Stage-2 LLM и фиксирует `html.escape`. Тест `tests/test_outgoing_guard_round1022.py:140-150` — проверяет наличие в обосновании `asr`/`не stage-2`/`html.escape` и `escaped_text = html.escape(text)` + `parse_mode="HTML"` в источнике. Как осознанно accepted-точка этого достаточно. Остаток (Info): инвариант привязан к строкам обоснования, а не к «модуль не содержит LLM-вывода»; при будущем добавлении `.reply(...)` с LLM-текстом тест это не поймает. |
| S10.22-8 | Info | **закрыто** | `services/summary_generator.py:290-296` — лог только `chat_id/len/latency_ms`, сырой `raw` убран. Тесты: `tests/test_summary_generator.py:228-...`, `:881`, `tests/test_summary_two_call_round1022.py:47`. Прошли. |
| S10.22-9 | Info | **закрыто** | `services/dossier_rebuild_jobs.py:526-541` — column-list для INSERT строится из `PRAGMA table_info(graph_facts)`, лишние ключи JSONL молча отбрасываются (`:536`). Тест `tests/test_dossier_rebuild_round1022.py:287-304` (`test_restore_ignores_unknown_columns`). Прошёл. |
| S10.22-7 | Info | **закрыто (сверх плана)** | `.env.example:474-491` — добавлены закомментированные `TELEGRAM_SEND_GUARD_ENABLED`, `SYSTEM2_{VALIDATOR_LOOP,FACTCHECK,SUMMARY,DIRECT}_ENABLED`, `DOSSIER_REBUILD_UI_ENABLED/CHUNK_SIZE/LOCK_TTL_SECONDS`. |

### Новая мелкая находка (не блокер)

- **S10.22-4b [Info]** Детектор `as_ai` всё ещё ложно срабатывает при запятой между субъектом и «как»: «Он, как искусственный интеллект, не устаёт» → `['as_ai']`; «Люди, как искусственный интеллект, ошибаются» → `['as_ai']`. Lookbehind `(?<!\bон\s)` не видит «он, ». Эффект — редкая лишняя регенерация, не блокер. При желании: lookbehind с опциональной запятой/пробелами.

### Валидатор итерации 2 (независимо)

- **Целевой pytest:** `187 passed` (cleanup/dossier/negative/outgoing/summary) + `339 passed` (все 10.22-файлы + webapp_api/js_unit) + `70 passed` (`test_param_catalog`, `test_frontend_tab_mapping`) + `88 passed` (info_service/prompt_migrations/guide/negative) — **0 failed**.
- **JS-гейты:** `node --check web/app.js` OK; `round1022_dossier_rebuild_test.js` → `DOSSIER-REBUILD-UNIT-OK`; `round1022_aliases_test.js` → `ALIASES-UNIT-OK`; `round1022_help_test.js` → OK.
- **Инварианты:** каталог — REGISTRY **439**, Settings-поля **409**, GROUPS **92**, `_TAB_BY_GROUP` **90**, TAB_RULES **20** (spec-база 10.22 — 439/409/414/92/90/20; пин-тесты `test_param_catalog`/`test_frontend_tab_mapping` зелёные, Δ=0); fresh-DB `PRAGMA user_version=12`; `INFO_CANON_VERSION=4`, `info_text.md` **байт-в-байт** == `DEFAULT_INFO_TEXT` (`<h1>×1`, `<h2>×10`, `<h3…h6>`=0, `<blockquote>×21`), `KNOWN_INFO_SNAPSHOTS`=3; `git diff --check` exit 0 (только LF/CRLF-предупреждения).
- **Регрессии F3–F6:** two-call direct/summary/factcheck, aliases-render, help-UI, outgoing-guard, negative-constraints — зелёные.
- Секретов в новом коде/тестах/отчёте не найдено.

### Вердикт итерации 2

**S10.22-1…-9 — все закрыты (0 Medium / 0 Low / 0 Info открыто; одна новая Info S10.22-4b).**
Critical/High открытых нет. **Раунд 10.22 можно передавать на Merge/деплой.** Обязательных пунктов для @Builder нет.
