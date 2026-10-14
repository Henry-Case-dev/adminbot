# Round 10.21 — Step 6 @Scanner: независимый diff-based аудит

> **Дата:** 18.09.2026 · **Агент:** @Scanner · **Раунд:** 10.21 (`System 2 Reasoning & Memory Rebuild`)
> **Baseline:** HEAD `21cd54c` + рабочее дерево (не закоммичено; коммит — Шаг 9 @DevOps).
> **Контекст:** @Reviewer дал `Approved` (итерация 3); полный `pytest` — **6775 passed / 0 failed** (заявление @Reviewer, не перепроверял целиком).
> **Метод:** `git status`/`git diff`, чтение новых модулей и интеграций, точечные пробы (213 pytest по новым тестам-файлам, JS-UNIT, `node --check`, ad-hoc проверки `grounding_validator`), анализ инвариантов деструктива.
> **R17/R18:** секретов в новом коде/тестах/отчётах/артефактах не найдено ( `.env` и `plans/current_task.md` — gitignored; в `tools/_ui_audit_raw.json` нет токенов, только `sk_FAKE_*`/маска в исходнике харнесса).

---

## Сводка

| Severity | Кол-во (первичный скан) | Открыто после re-audit |
|---|---|---|
| Critical | **0** | 0 |
| High | **0** | 0 |
| Medium | **2** | **0** |
| Low | **7** | 1 (S10.21-8, вне скоупа фиксов) + 1 новый Low (тест-покрытие) |
| Info | **4** | 4 |

**ВЕРДИКТ (после пост-скан фиксов @Builder): 0 Critical / 0 High / 0 Medium → рабочий процесс НЕ блокируется.**
Оба Medium (S10.21-1, S10.21-2) и 5 из 7 Low закрыты; детали и доказательства — в разделе
«Re-audit после пост-скан фиксов» ниже.

Проверенные зоны: F1 multi-layer, F2 grounding/CoVe, F3 канон-миграция, F4 консолидация/миграция порогов, F5 деструктивный CLI, F6 UI-аудит; порядок роутеров `bot.py`; `git diff --check` (только LF/CRLF-предупреждения); каталог/схема не менялись (Δ=0, SQLite v12).

---

## Находки

### S10.21-1 [Medium] F4: `consolidate` не применяет кап `DEEP_SLEEP_MAX_PARADIGMS` (и `TOP_K`)

- **Файл:** `services/memory_maintenance.py:850-864` (пасс 2 — запись), docstring-обещание `:735-741`.
- **Суть:** Докстринг заявляет «капы `TOP_K`/`MAX_PARADIGMS`/`TOKENS_PER_DAY` не снимаются», но боевой цикл пишет парадигму **для каждого** кандидата без ограничения per chat. Кап реально применяется только в Deep Sleep-пасе `dream_worker.py:1578-1582` (`paradigms[:max(1, max_paradigms)]`). Через CLI `manage.py memory consolidate` (дефолт `--limit 500`, `_add_memory_common`) один прогон может создать до 500 парадигм на чат вместо 3.
- **Доказательство:** `grep MAX_PARADIGMS` — 1 site применения (`dream_worker.py:1582`); в `consolidate` нет ни `DEEP_SLEEP_MAX_PARADIGMS`, ни `deep_sleep_max_paradigms_per_run`. Идемпотентность дедупом ограничивает повторные прогоны, но не один прогон.
- **Рекомендация:** обрезать `candidates`/запись per-chat до `hot.get("limits.deep_sleep_max_paradigms_per_run", settings.DEEP_SLEEP_MAX_PARADIGMS)` (и ограничить `--limit` для consolidate `TOP_K`), либо снять заявление о капах из докстринга и зафиксировать Δ как осознанную девиацию.

### S10.21-2 [Medium] F5: класс «галлюцинация» опирается на неполный ростер `nodes`

- **Файл:** `services/memory_rebuild.py:275-285` (`_chat_roster`), `:531-544` (флаг `target_not_in_roster` → DELETE).
- **Суть:** Ростер участников берётся из `nodes WHERE entity_type='user'`. В проекте `upsert_node` вызывается **только** при извлечении триплетов (`summary_memory.py:3250-3267`), то есть в `nodes` попадают лишь сущности, упомянутые как субъект/объект. Участник, не попавший ни в один триплет, в ростере отсутствует → все его валидные `chat_meme` помечаются «галлюцинацией» и удаляются.
- **Доказательство:** все call-sites `upsert_node` — только триплетный путь (grep). Спека F5 §4.2 п.3 требует «ростер участников», не указывая источник; реализация подменила его графовыми узлами.
- **Рекомендация:** не запускать класс «галлюцинация», если ростер неполон (например, требует совпадения `len(roster)` с числом различных `target_user` мемов), либо cчитать «галлюцинацией» только `target`, отсутствующий и в `nodes`, и в `persona_dossier_overrides`; в отчёте явно выводить `roster_size`.
- **Митигация уже есть:** авто-бэкап + JSONL-архив (`--backup-dir`, gitignored `backups/`), guard целевого чата, `--dry-run`.

### S10.21-3 [Low] F5: каскадное удаление убеждений через orphan-факты

- **Файл:** `services/memory_rebuild.py:253-262` (`_list_orphan_facts`), `:319-339` (`validate_belief_row`, код `missing_sources`).
- **Суть:** `_list_orphan_facts` не исключает факты, являющиеся `source_ids` живых убеждений/парадигм. Если orphan-факт — опора убеждения, он удаляется в прогоне N, а в прогоне N+1 это убеждение становится `missing_sources` и удаляется. Каскад уменьшает мета-слой сильнее, чем «чистка мусора».
- **Доказательство:** `_existing_fact_ids` считается до удаления (в момент валидации факт ещё существует), а `_list_orphan_facts` не связан с `source_ids`.
- **Рекомендация:** исключать из orphan-кандидатов id, входящие в `source_ids`/`evidence` любых `kind='belief'` (или фиксировать в отчёте `belief_sources_dropped` и требовать явного флага).

### S10.21-4 [Low] F2: grounding не режет дату-только теги без `fact:ID`

- **Файл:** `services/grounding_validator.py:118-130` (`_strip_impl` проверяет bracket только при `_FACT_ID_RE.search(inner)`).
- **Суть:** `[04.2023 | Иван]` (без `fact:ID`) сохраняется, даже если `04.2023` отсутствует во входном контексте. Промпт при этом требует ссылаться на даты только из контекста. Ложно-негатив для фантомных дат.
- **Доказательство (проба):** `collect_allowed_anchors('нет дат')` + `strip_phantom_tags('[04.2023 | Иван]')` → строка возвращается без изменений (`kept=0, stripped_phantom=0`).
- **Рекомендация:** для bracket с месячной/ISO-датой, но без `fact:ID`, проверять дату в `_allowed_month_keys` (стrip при отсутствии) — это узкая правка `_strip_impl`.

### S10.21-5 [Low] F2: якоря включают недоверенный `<claim>`/`<user_hint>`

- **Файл:** `services/factcheck_service.py:133-134` (`collect_allowed_anchors(f"{user}\n{tool_context}" ...)`), `grounding_validator.py:64`.
- **Суть:** `user` содержит `<claim>` (текст пользователя) и `<user_hint>`; любой `fact:ID`/`ММ.ГГГГ` из них становится «разрешённым». Пользователь может вписать фейковый `[04.2023 | fact:5]` в своё сообщение, и валидатор не вырежет его, если модель повторит (grounding-обход слабой модели).
- **Рекомендация:** якоря для цитирования собирать только из RAG/`chat_context`/`search_results`/`tool_context`, исключая `<claim>`/`<user_hint>` (или помечать их отдельным множеством «неподтверждённых»).

### S10.21-6 [Low] F5/CLI: `memory audit` не строго READ-ONLY

- **Файл:** `manage.py:893-908` (`_open_memory_db`), описание команды `:700-712`.
- **Суть:** Для несуществующего файла вызывается `db.initialize()` → создаётся полная схема (DDL). Даже для существующей БД `initialize_existing` ставит `PRAGMA journal_mode=WAL` (персистентный режим). При этом CLI-хелп и docstring аудита заявляют «ничего не меняет».
- **Рекомендация:** для `audit` открывать БД в read-only/rw-без-DDL и не фоллбэчить на `initialize()`; при отсутствии файла — явная ошибка.

### S10.21-7 [Low] F1: пустой `memes` Слоя Б перетирается мемами Слоя А

- **Файл:** `services/lore_worker.py:683-684` (`validated.get("memes") or memes_a`).
- **Суть:** Если Слой Б успешно отработал и сознательно вернул пустой список мемов (отфильтровал), из-за `or` записываются мемы Слоя А. Решение Синтезатора об очистке не применяется.
- **Рекомендация:** различать «ключ отсутствует» и «пустой список»: при успешном парсе B использовать `memes` безусловно; fallback на `memes_a` — только в ветке исключения (что уже есть выше).

### S10.21-8 [Low] F4: парадигмы CLI-консолидации без vec-эмбеддингов

- **Файл:** `services/memory_maintenance.py:768` (`DreamWorker(db, memory=None, llm=None)`), `services/dream_worker.py:1943-1947`.
- **Суть:** В проде Deep Sleep кладёт парадигму и в FTS, и в `graph_facts_vec` (через `_save_graph_fact_embedding`). CLI `consolidate` с `memory=None` эмбеддинг пропускает → парадигмы видны FTS-ветке RAG, но не KNN/`vector_search` L3.
- **Рекомендация:** либо задокументировать как осознанное ограничение (CLI офлайн без embedding-клиента), либо прокинуть лёгкий vec-writer/эмбеддер и добить вектор для записанных id.

### S10.21-9 [Low] F6/repo: артефакты UI-аудита не игнорируются гитом

- **Файл:** `tools/_ui_audit_shots/` (33 PNG, ≈9.2 МБ), `tools/_ui_audit_raw.json` (96 КБ) — untracked, не в `.gitignore`.
- **Суть:** При коммите Шага 9 бинарные скриншоты (9+ МБ) и сырой JSON попадут в репозиторий навсегда. Секретов там нет (только фейковый стаб), но это заметный прирост истории.
- **Рекомендация:** добавить `tools/_ui_audit_shots/` и `tools/_ui_audit_raw.json` в `.gitignore` (или хранить как release-артефакт), оставив в репо только `tools/ui_audit_round1021.py` и текстовый `UI_AUDIT_REPORT.md`.

### S10.21-10 [Info] F6: хардкод персонального TG-id в инструменте

- **Файл:** `tools/ui_audit_round1021.py:34` (`ADMIN_ID = 5885953495`).
- **Суть:** Персональный Telegram-id зафиксирован в исходнике инструмента. Не секрет, но приватность/перенос. Не блокер.

### S10.21-11 [Info] F5: `audit` на «чужой» БД молча даёт нули

- **Файл:** `services/database.py:595-607` (`initialize_existing` проверяет лишь наличие любой таблицы).
- **Суть:** БД с единственной посторонней таблицей проходит проверку; `collect_paradigm_audit` затем fail-open'ит все счётчики в 0 → отчёт вида «flags_off / 0 парадигм» на нерелевантной базе. Стоит различать «схема памяти отсутствует» и «пустая память».

### S10.21-12 [Info] F2: `_MONTH_RE` извлекает `MM.YYYY` из `DD.MM.YYYY`

- **Файл:** `services/grounding_validator.py:30`.
- **Суть:** В строке `12.03.2024` матчится `03.2024` (старт с позиции 3, lookbehind `.` не `\d`). Это расширяет множество допустимых месяцев при полных датах — не опасно, но приводит к нестрогому сопоставлению.

### S10.21-13 [Info] F5: класс-счётчик `orphan_fact` считается до перезаписи

- **Файл:** `services/memory_rebuild.py:511, 540-542`.
- **Суть:** `_cls("orphan_fact", kept_orphans)` инкрементируется до того, как часть строк будет переклассифицирована в `hallucination` (dict по id перезаписывает `_class`). Отчётные `classes` могут расходиться с итоговым набором кандидатов — косметика для оператора.

---

## Принятые / унаследованные остаточные отклонения

- **F5 не удаляет сырую историю** — подтверждено по коду: единственная точка DELETE (`_guarded_delete`) с allowlist, `RAW_HISTORY_TABLES` (включая `smart_messages`/FTS/vec/`import_checkpoints`/`smart_messages_archive`) блокируются даже через `extra`; прямых SQL-DELETE по этим таблицам в новом контуре нет.
- **Авто-бэкап ДО DELETE + JSONL + сверка counts** — реализовано (`_safety_backup` → `_archive_generated_rows` → `candidates == archived`), fail-closed при `db_path`/архиве; `create_safety_backup` использует SQLite Backup API + fsync.
- **Guard целевого чата `-1002661910336`** — работает: `--all` исключает его, явный `--chat <target>` требует `--allow-target-chat` (`manage.py:853-878`); тесты `test_all_excludes_target` / `test_explicit_target_requires_flag` зелёные.
- **F4 fail-closed без `db_path`** — есть (`allow_no_backup=False` по умолчанию; CLI всегда прокидывает путь); авто-кронов/HTTP-триггеров консолидации нет (только `manage.py`).
- **F1 изоляция `dossier_portrait`** — подтверждена: `status != 'confirmed'` отсекается в `get_persona_card`, `get_persona_names`, `get_dream_candidates`, `list_recent_beliefs`, KNN-`by_id` (`confirmed/archived_belief`) и FTS-статус-фильтре; `_list_orphan_facts` статус не включает. Приоритет ручных `persona_dossier_overrides` — `portrait_source='manual'` в API/`/persona`.
- **F3 канон-атомарность** — новые `PREV_*_R1021` во всех 8 канонах, добавлены в `PROMPT_MIGRATIONS`; обратный `ROLLBACK_MIGRATIONS` покрывает те же ключи, `COMPRESS_PROMPT`/`extract` не тронуты; `docs/canon/**` синхронны; байт-тесты зелёные.
- **F6 UI** — `_syntheticGroup` перенесён в `methods` (регресс-тест §7 JS-UNIT), `positionScopePanel` + `:style`; Puppeteer MCP честно зафиксирован как недоступный, fallback Playwright использован, выдуманных замеров не обнаружено (сырой JSON + PNG на месте). Полный рендер в реальном WebView не воспроизводился — унаследованное ограничение (отчёт §7).
- **Порядок роутеров `bot.py`** и существующие контуры (retention/budgets) не затронуты.
- Секретов в дифе/новых тестах/отчётах/`tools/_ui_audit_raw.json` не найдено; `.env` и `plans/current_task.md` — gitignored; `.env.example` содержит только комментарии-плейсхолдеры.

---

## Валидатор @Scanner (независимо)

- `pytest` по новым/затронутым файлам: **213 passed** (`test_grounding_validator`, `test_memory_rebuild_round1021`, `test_memory_consolidation_round1021`, `test_multilayer_extraction_round1021`, `test_factcheck_grounding_cove_round1021`, `test_factcheck_tool_grounding_round1021`, `test_de_robotization_round1021`, `test_prompt_migrations`).
- `node tests/js/round1021_ui_audit_test.js` → `JS-UNIT-OK`; `node --check web/app.js` → OK.
- `git diff --check` → только LF→CRLF-предупреждения (whitespace-ошибок нет).
- `py_compile` по всем изменённым python-файлам → OK.
- Полный pytest-прогон (6775/0) повторно не выполнялся — подтверждён @Reviewer; расхождений не искал.

**Итог контракта: 0 Critical / 0 High открыто.**

---

# Re-audit после пост-скан фиксов (Шаг 6, повторный проход)

> **Дата:** 18.09.2026 · **@Scanner** · метод: чтение актуального кода + точечные pytest
> (6+8 целевых файлов) + 7 собственных ad-hoc проб по спорным веткам + `git check-ignore`.
> Полный `pytest` после фиксов **6779 passed / 0 failed** подтверждён @Orchestrator; я его
> повторно не гонял (целевой контур — 217 passed, было 213, +4 новых теста).

## Статус находок

| ID | Severity | Статус | Доказательство |
|---|---|---|---|
| **S10.21-1** | Medium | **ЗАКРЫТО** | `services/memory_maintenance.py:766-776` — `_cap('limits.deep_sleep_max_paradigms_per_run', DEEP_SLEEP_MAX_PARADIGMS)` + `read_limit = min(limit, top_k)`; `:808-814` — `if per_chat >= max_paradigms: reason=cap_reached`. Тест `tests/test_memory_consolidation_round1021.py:191-220` (`test_cap_limits_writes_per_run`: candidates==cap, written==cap, `cap_reached==2`, повторный прогон идемпотентен). Прогон: 23 passed. |
| **S10.21-2** | Medium | **ЗАКРЫТО** (остаточная Low-заметка) | `services/memory_rebuild.py:275-341` (`_chat_roster`: union `nodes` + `dossier_portrait` + `persona_dossier_overrides` через AliasResolver, `independent`-счётчик); `:620-640` — при `unknown and not independent` ставится `roster_incomplete`, «галлюцинация» НЕ применяется; `roster_size` в отчёте (`:559`) и выводе CLI (`manage.py:958`). Мои пробы: `roster_incomplete` защищает мем вне неполного ростера; override-имя попадает в ростер и цель сохраняется; control-кейс с независимым именем — hallucination штатно удаляется. Все 3 — passed. |
| **S10.21-3** | Low | **ЗАКРЫТО** | `services/memory_rebuild.py:561-587` — `belief_sources` собирается из `source_ids` **и** `belief_meta.evidence`; orphan-факт с таким id пропускается с reason `belief_source` до `is_fact_protected`. Моя проба (belief ссылается на orphan-факт → факт сохранён, reason `belief_source`) — passed. |
| **S10.21-4** | Low | **ЗАКРЫТО** | `services/grounding_validator.py:126-131` — тег без `fact:ID`, но с датой (`has_date`), проходит `_segment_ok`; `:99-112` проверяет месяц/ISO по `_allowed_month_keys`. Тесты `tests/test_grounding_validator.py:78-98` (`test_date_only_tag_without_fact_checked`, `test_date_only_iso_tag_checked`) — passed. |
| **S10.21-5** | Low | **ЗАКРЫТО** | `services/factcheck_service.py:129-140` — `trusted_parts` = `rag` + `results` + `chat_context` + `tool_context`; `<claim>`/`<user_hint>` исключены (комментарий прямо про S10.21-5). Тесты `tests/test_factcheck_grounding_cove_round1021.py:43-58` (`test_claim_anchor_is_untrusted_and_stripped`, `test_trusted_search_anchor_kept`) — passed. |
| **S10.21-6** | Low | **ЗАКРЫТО** | `services/database.py:609-639` — новый `initialize_readonly`: URI `?mode=ro`, нет DDL/миграций, **без** `PRAGMA journal_mode`, отсутствие файла/таблиц → исключение (файл не создаётся). `manage.py:893-904, 976` — `audit` идёт только этим путём; `:1011-1018` — явная ошибка `db_unavailable`. Мои пробы: отсутствующий файл не создаётся; `journal_mode` остаётся `delete`, `-wal` не появляется — passed. |
| **S10.21-7** | Low | **ЗАКРЫТО** | `services/lore_worker.py:683-689` — `memes_b = validated.get("memes") if "memes" in validated else None`; пишется `memes_a if memes_b is None else memes_b` (пустой список Слоя Б уважается; fallback только при отсутствии ключа). Моя проба (Слой Б вернул `"memes": []` → в БД 0 `chat_meme`, а не мемы Слоя А) — passed. |
| **S10.21-9** | Low | **ЗАКРЫТО** | `.gitignore:91-96` — `tools/_ui_audit_shots/` и `tools/_ui_audit_raw.json`; `git check-ignore -v` подтверждает оба пути (`.gitignore:95` и `:96`). |
| S10.21-8 | Low | **ОТКРЫТО** (вне скоупа фиксов) | `services/memory_maintenance.py:785` — `DreamWorker(db, memory=None, llm=None)`; vec-эмбеддинг парадигм CLI по-прежнему пропускается. Не блокер, косметика RAG-ветки. |
| S10.21-10…13 | Info | **ОТКРЫТО** | Код не менялся (хардкод `ADMIN_ID` в инструменте; audit на «чужой» БД; `_MONTH_RE`; класс-счётчик orphan до перезаписи). |

## Новые наблюдения (не блокеры)

- **N10.21-1 [Low, тест-покрытие]** Фиксы S10.21-2/-3/-6/-7 корректны по коду и подтверждены моими
  ad-hoc пробами, но **не имеют собственных регрессионных тестов** в `tests/` (нет ни одного теста на
  `_chat_roster`/`roster_incomplete`, `belief_source`, `initialize_readonly`, пустой `memes` Слоя Б).
  Прирост тестов +4 пришёлся на S10.21-1/-4/-5. Рекомендация на усмотрение @Builder (не блокирует
  Merge, но будущая регрессия этих веток не будет поймана CI).
- **N10.21-2 [Low, остаточный риск S10.21-2]** Гард `roster_incomplete` — бинарный по
  `independent > 0`: как только в ростере есть хоть одно имя из портретов/overrides, «неизвестные»
  мемы снова удаляются. Если независимых источников мало, а валидных участников много, false-positive
  теоретически возможен. Страховки (авто-бэкап + JSONL + `--dry-run`) сохраняются.

## Регрессии (не сломаны фиксами)

- **Сырая история:** `test_memory_rebuild_round1021.py` — `test_sanitize_does_not_mutate_smart_messages`,
  `test_rebuild_does_not_mutate_smart_messages`, `test_guarded_delete_aborts_and_keeps_rows` — passed.
- **Ручные overrides:** `test_overrides_untouched_by_default` (rebuild) + `test_manual_overrides_untouched`
  (multilayer) — passed.
- **Схема/каталог:** `PRAGMA user_version` fresh-DB = **12**; `services/param_catalog.py` — `git diff` пуст
  (Δ каталога = 0); новых миграций/DDL фиксы не добавили (`git diff services/database.py` — только метод
  `initialize_readonly`).
- **UI-инварианты:** `node --check web/app.js` → OK; `node tests/js/round1021_ui_audit_test.js` → `JS-UNIT-OK`.

## Валидатор @Scanner (повторно)

- Точечные файлы: **217 passed** (grounding_validator, memory_rebuild, memory_consolidation,
  multilayer_extraction, factcheck_grounding_cove, factcheck_tool_grounding, de_robotization,
  prompt_migrations) — было 213 на первичном скане (+4 теста фиксов).
- Собственные ad-hoc пробы по спорным веткам: **7 passed** (roster guard ×3, belief_source, readonly ×2,
  пустой Слой Б).
- `git check-ignore -v` — оба UI-артефакта игнорируются. `git diff --check` — только LF/CRLF.

**ИТОГ RE-AUDIT: Critical 0 / High 0 / Medium 0 открыто. Раунд 10.21 можно передавать на Merge/деплой.**
Для возврата @Builder обязательных пунктов нет (S10.21-8 + Info + N10.21-1/-2 — необязательные follow-up).
