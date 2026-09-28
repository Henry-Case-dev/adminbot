# review.md — mca-asap21-summary-quality-ui-cleanup (Reviewer, round1028)

- **Feature-ID:** `mca-asap21-summary-quality-ui-cleanup`
- **Risk-Level:** R3 (эскалация с R1 спека: живая доставка статьи Rich cut/emphasis/fallback + обязательный прод-деплой 2.58.34 + Prompt Library user-visible UI; по факту диффа blast radius подтверждён — глубокий аудит выполнен)
- **Status: Approved** (обе обязательные линзы — requirements/correctness и focused change-audit — подтверждены независимо; блокеров нет)
- **Reviewed-Commit:** `8663214289fba89b9bfd509d557c7bca0ae529e0` (HEAD `8663214`) + незакоммиченное дерево (ревью до коммита)
- **Working-Tree-Hash (Builder-scope diff manifest):** `9ABE432FCB214A10C6998A1BD4C9949C437A640B14B128D30FC21F88C66091B3`
  (SHA-256 канонического манифеста: `git diff HEAD -- <файл>` для каждого файла Builder-скоупа, порядок из раздела «Staging-перечень», UTF-8, разделитель `файл\n` + дифф + пустая строка)
- **Spec-Hash:** `7B7461D0A3648B0D696D9C5813A924D691D505B04F26C091C54C5C901341B0CD` (пересчитан `Get-FileHash` — совпал с заявленным; tasks.md PLANNING_CONSISTENT подтверждён, ADR-1028-1 `0F7CE3DE…164E458` совпал)
- **Прод-базис:** 2.58.33; целевой релиз **2.58.34** (`config/settings.py:2172` подтверждён живым импортом и `/healthz` стенда)

## Git base и inspected change scope

База: HEAD `8663214` (docs-коммиты поверх код-коммита ASAP-2 `c0f299c`; код 2.58.33). Рабочее дерево содержит: (1) изменения фичи — 82 файла Builder-скоупа (перечень ниже); (2) чужой незакоммиченный WIP MCA-волны §93–§100 (~150 файлов: handlers/, services/mca_*, database, direct_chat, routes.py +58 строк mca-17a, lore/video/youtube-сервисы, ~30 WIP-доменных тестов, untracked mca_*) — **вне скоупа, отделён и не ревьюился как фича**; (3) `web/index.html` — СМЕШАННЫЙ дифф, разделён (ниже).

Метод разделения: маркер-эвристика по диффам (`ASAP-2.1|round1028|R1028` → Builder; `mca-17a|oversight|message_identity|provenance|safe_fetch|saturate(103` → WIP) + потестовая классификация + точечное чтение хунок. Builder-контента в WIP-файлах не обнаружено; WIP-контента в Builder-файлах — только 2 задокументированных теста hotfix8/9 (см. Findings/For-wave).

## Checks performed (обязательные пункты → факт → вывод)

**1. §40 — 20 инвариантов (по отдельности):**

| # | Инвариант | Evidence | Вывод |
|---|---|---|---|
| 1 | Prefilter отсутствует в live Hybrid path | `services/summary_filter.py` физически отсутствует; `summary_generator.py:466–492` — Hybrid и Legacy получают исходное `rows`; `xml_rows` не существует (grep = 0 в коде); `record_run_from_context(ctx, None)` :522 | ✅ |
| 2 | Old heuristic scoring не переехал | `rg score_message services/` = 1 совпадение — комментарий-инвариант `summary_hybrid_budget.py:134`; burst/mention/weight-членов в budget нет (модуль прочитан целиком, 210 строк: только длина/токены/нарезка) | ✅ |
| 3 | Technical overflow protection осталась | `pack_l1_input` :474–499: serialized-учёт §92, eviction при `total > limit`, `truncated/skipped_ids` + WARN `L1 truncated input` :784; тест prefilter_removal:174 | ✅ |
| 4 | Короткие важные сообщения доходят до L1 | Тест «у кота рак»/«Леха уехал» (prefilter_removal, §27) — до L1; в budget < лимита eviction не запускается (:474) | ✅ |
| 5 | >1 paragraph → deterministic cut | `format_rich_html` :242–251: `cut = len(paragraphs) > 1` → ОДИН закрытый `<details><summary>Читать дальше</summary>` (атрибута `open` нет), p2..N + finale внутри | ✅ |
| 6 | Cut не теряет body | Абзацы 2..N рендерятся полностью внутри details :248–249; `_iter_paragraphs` без среза; тест 10 абзацев + finale «всё в одном cut, ничего не потеряно» | ✅ |
| 7 | Plain fallback содержит полный текст | `_plain_html_blocks`/`format_plain_text` — весь текст без ката (:290–339); тест §28.4 rich failure → plain вся статья | ✅ |
| 8 | L2 Writer — текущий Hybrid output | `summary_l2_writer.py:897+` (`resolve_prompt_with_source` PROMPT_PG_KEY), вызывается из `_run_hybrid_l2`; UI-бейдж «АКТИВНЫЙ HYBRID OUTPUT» (SUMMARY_PROMPT_META, browser B1) | ✅ |
| 9 | PL правильно показывает runtime roles | Browser B1: metadata-панель Pipeline/Stage/Runtime/Key/Source у всех 6 (Hybrid ×2 Primary, Cover Primary, Legacy ×3 Fallback); Q9-карта «дублей нет» подтверждена | ✅ |
| 10 | Desktop prompts все открываются | Browser B1 (1440×900): 6/6 клик → editor непустой (3702/4580/31/3558/2023/1850), URL точный | ✅ |
| 11 | Mobile prompts все открываются | Browser B4 (390×844): 6/6 → editor fullscreen при валидном фокусе, дерево скрывается, «← К списку» возвращает список | ✅ |
| 12 | Cover Style editor открывается | Browser B1/B4: клик → editor, textarea 31 симв., metadata Pipeline: Cover; B5 stale-комбинация verbalizer+cover → валидный editor | ✅ |
| 13 | Cover Style save/reload работает | Browser B3: edit→save→1 POST→reload→persisted; затем восстановлено | ✅ |
| 14 | Summary — нормальная грамматика | Канон L2 R1028: маркеры заглавной/грамматики (живой импорт канона); deterministic `cleanup_llm_text` на канонизации L2 (writer :683/:708/:661); тест §30 | ✅ |
| 15 | Двачерский голос/сленг/мат сохранены | Канон L2 содержит инструкцию владельца §16 (сарказм/сленг/двачерские обороты); запрета сленга НЕТ (проверено 4 формулировками запрета = 0) | ✅ |
| 16 | Direct Chat style не изменён | `direct_chat_service.py`/direct-промпты — только WIP-диффы (0 маркеров ASAP-2.1); дифф `prompt_migrations.py` = +25/−4 только R1028-ступени | ✅ |
| 17 | Names/key events deterministic bold | `_emphasis_spans_of`+`_resolve_span_positions`+`_render_with_spans` (formatter :125–184) — единый код rich/plain-HTML; тест §29: 3 спана bold | ✅ |
| 18 | LLM не обязана генерировать Markdown | Канон L2: «Никакого HTML и никакого \*\*Markdown\*\*… жирность делает код форматтера»; тегоподобные спаны отбрасываются (`_TAGLIKE_RE` :592) | ✅ |
| 19 | Code больше не выбирает «главного шиза» | `_ensure_shiz_postfix`/`_most_active_author`/`_SHIZ_AT_RE` — 0 в исполняемом коде (grep: только docstring-упоминание + комментарии-инварианты); `_SHIZ_MARKER` = strip-константа :368/:1664 (контракт (e)) | ✅ |
| 20 | Effective production prompt source проверен | T-3965 (prompt-map-audit §2): 6/6 прод-ключей = глобальный PG genuinely-custom (не канон/PREV), per-chat stage-значений нет; (h) не применён по условию spec Q10; runbook сброса задокументирован | ✅ |

**2. DoD §41 1–22:** все 22 закрыты — маппинг spec раздел 8 свернут к фактам: 1–4 (блок B, grep+тесты §27), 5–7 (блок C, formatter+тесты §28), 8–10 (§99 v1.1 + §29), 11–13 (канон R1028 + normalizer + §30), 14–15 (шиз-удаление + §31), 16 (витрина §9, B1–B2), 17–18 (B1/B4 6/6), 19 (B3/B4 Cover), 20 (backend cover не тронут: image_generation/cover-резолверы вне Builder-диффа; тест-регресс зелёный), 21 (prompt-map-audit + L2_START effective_prompt_key в коде), 22 (прогоны ниже). **Cover backend**: `web/api/routes.py` дифф = только mca-17a WIP (+58); `/api/config` save-path не менялся.

**3. Запреты §38 (13):** не «выключен» — модуль/флаги/8 env-констант удалены (env leftovers = 0 живым импортом); `score_message` не реинкарнирован; thresholds не увеличены (их не существует); article не обрезается алгоритмически (formatter не имеет пути усечения; `rich_document_limits` fail-closed → plain полный); на Telegram-collapse не надеемся (details в HTML); L2 не пишет `**`; `_most_active_author` удалён; сленг/мат не запрещены; random lowercase в Summary не перенесён (канон L2 требует заглавную; Direct-канон не тронут); исправлены ОБА desktop и mobile; Cover Style проверен на mobile (B4/B6). ✅ 13/13.

**4. Удаления/переносы:** подтверждены (см. п.1 №1–2 + `build_l1_payload` = ровно 1 определение `summary_l1_clusterizer.py:368`, 4 импортера переподключены; `estimate_and_split`/`Fragment`/`DEFAULT_FRAGMENT_OVERLAP` в `summary_hybrid_budget.py:138/148/158` сигнатурно без изменений; eviction `(reply_protected, timestamp, db_id)` :341–350; Legacy-вход — исходные `rows` :490–492; dry-run паритет (j): `summary_test_run.py:535–558` stage-ключ «filter» сохранён, `filtered=source`).

**5–11.** Rich cut / emphasis §99 v1.1 / шиз / миграции / PL / каталог / observability — построчно проверены в коде + браузере (детали в п.1 и разделах ниже). Kлючевые контрпримеры:
- 2+ абзаца с finale → finale ВНУТРИ cut (formatter :250) — не создаёт второй точки «после абзаца»;
- документ без новых полей (legacy-адаптер `document_from_plain_text`) → валиден, рендер по legacy `emphasis` (formatter :143–146);
- overlap-спаны → сортировка `(start ASC, length DESC, порядок)` + жадный приём, детерминировано в валидаторе (:633–645) И в рендере (:154–168);
- спан-«строка» вместо массива → не бракует документ (посимвольно в счётчик, документ валиден);
- rollback дважды → no-op («уже на прежнем»), custom → WARNING skip (`prompt_migrations.py:296–326`) — ROLLBACK безопасен и идемпотентен;
- «грязная» БД (сироты `summary_filter_*`) → startup зелёный (тест prefilter_removal + живой импорт каталога).

**12. 2 failing теста — stash-проба воспроизведена независимо:** `git diff HEAD` тестов hotfix8/9 = ожидания `saturate(105%)`→`saturate(103%)` (чужой WIP); `web/static/app.css` дифф = +4 строки `.prompt-back-btn` (Builder), `--shell-blur` не менялся (105%). С `git stash push` двух тестов: оба токен-теста PASS. → падения внесены WIP-волной, к фиче отношения не имеют, **не блокёр** (зафиксировано для волны).

**13. Прогоны (повторены самостоятельно):**
- Полный pytest: **9876 passed / 2 failed** (те самые hotfix8/9) — совпало с заявкой Builder;
- summary-срез (`-k summary`): **1133 passed**;
- 4 новых файла: **53 passed** (8+12+13+20);
- JS-харнессы: **49/49 OK**;
- F8 `--check`: **CHECK OK** (реестр 481 == REGISTRY);
- Живой импорт каталога: **481/105/103/21**, `summary_filter_*` ключей/групп = 0, env-констант = 0; 6 промпт-титулов §9 подтверждены.

**14. BROWSER PASS — выполнен НЕЗАВИСИМО (REQUIRED):** собственный стенд с нуля: docker PostgreSQL 16 (одноразовый контейнер `adminbot-review-pg`, удалён после проверки), standalone `create_app` uvicorn на 127.0.0.1:8765 (`ADMINBOT_SKIP_DOTENV=1` — репо-.env/секреты/прод-DSN не читались), чистая БД → DDL+сид (417 строк bot_settings, сид-админ global_admin), auth = подписанный HMAC WebAppData initData синтетического токена (инжект sessionStorage). Playwright MCP:
- **B1 desktop 1440×900:** 6/6 промптов в группах §9 (Hybrid Summary/Обложка/Legacy Summary Fallback), клик по каждому → editor непустой, Key корректный, metadata-панель заполнена; бейджи «АКТИВНЫЙ HYBRID OUTPUT» (L2) и «Legacy fallback» ×3. PASS
- **B2:** Narrator(verbalizer) → клик L1 → editor переключился, URL `…/summary/synthesizer/prompts.summary_l1_clusterizer_system_prompt` (exact-пин). PASS
- **B3:** для каждого из 6: edit → save → **ровно 1 POST /api/config** (инструментированный fetch) → reload → persisted (проверка по БД стенда psql + GET /api/config + UI). После теста значения возвращены (стенд пересиден в канон при рестарте). PASS
- **B4 mobile 390×844:** без ключа — список виден, editor скрыт (computed display); выбор → editor fullscreen, дерево скрыто (is-editing только при валидном фокусе); «← К списку» → список, hash `#/ai/prompts/summary`; все 6 открываются; на глобальной `#/ai/prompts` анти-клише свёрнуто на y≈10406px — карточки групп достижимы без прокрутки сквозь него. PASS
- **B5 stale-guard:** `…/verbalizer/prompts.summary_cover_style` → НЕ пустой editor: фолбэк нашёл Cover Style (Pipeline: Cover, ta 31); `…/verbalizer/prompts.bogus_nonexistent_key` → редирект на `#/ai/prompts/summary`, дерево видно, заглушки нет. PASS
- **B6:** анти-клише = `<details>` НИЖЕ промпт-контента (DOM-порядок проверен), свёрнут по умолчанию, разворачивается/сворачивается, дерево доступно при развёрнутом, scrollWidth 390 = viewport (горизонтального overflow нет). Скриншоты сняты (viewport-факты, в review-артефактах не хранятся). PASS
- **B7:** console — 0 ошибок приложения на всех шагах (единственные 401/404 — артефакты моей инжект-процедуры initData и пробного fetch до инжекта; на реальном TMA-launch отсутствуют). Сеть — ожидаемые GET /api/config|/api/me и по 1 POST /api/config на save. PASS

**15. T-3965/runbook:** процедура подтверждена по prompt-map-audit.md (read-only, sha256-префиксы, без содержимого — R17 соблюдён по описанию метода; содержимое прод-промптов независимо недоступно из среды ревью — отмечено в Unavailable). Все 6 прод-ключей genuinely-custom → R1028-миграции их не тронут (exact-match механика `prompt_migrations.py:279–289` + тесты), rollback-путь ROLLBACK работает (идемпотентность проверена чтением кода + тест). Runbook сброса промптов владельцем задокументирован (evidence «Отклонения/находки» №5 + prompt-map-audit §2.4: удаление PG-строки → сид канона при рестарте; после сброса активируются новые code-гарантии — deterministic-часть работает и без сброса). Подтверждаю.

## Requirement/evidence coverage

current_task §1–§47 → spec (Q1–Q10, контракты (a)–(j)) → tasks T-3964–T-3993 → дифф → тесты/browser: цепочка без противоречий. Исключения по скоупу подтверждены: `routes.py`, PG-DDL (Δ DDL=0 — pg_db.py вне Builder-диффа), backend cover, Direct Chat — не тронуты фичей. T-3994–T-3998 (деплой/live/gate) — вне ревью, корректно ⏸.

## Focused audit coverage

Все 12 изменённых backend-файлов прочитаны в ключевых сечениях (генератор: поток `_run`, legacy-пайплайн, dry-run, шиз-удаление, cover-strip; clusterizer: eviction/payload/packing; budget: целиком; formatter: целиком; writer: валидация/канонизация; prompts: маркеры канонов + отсутствие запретов; migrations: ступени+rollback+custom-защита; catalog: счётчики/титулы/группы; test_run: паритет; run_log: S1-поля удалены; settings: версия+удаления). Frontend: полные диффы app.js (17 хунок) и index.html (6 хунок) прочитаны построчно, app.css (+4). Интеграционные кромки: `execution_graph_source` толерантен к отсутствующим S1-полям (getattr-None); JS log-viewer маркеры согласованы с эмиттерами; тест-файлы переписаны без ослабления защитных ассертов (AST-пин ослаблен ровно на 1 токен `_ensure_shiz_postfix` — задокументировано, контракт (e); остальные пины byte-parity зелёные).

## Counterexamples checked

(сводка) короткие сообщения до L1; physical overflow WARN+eviction без веса; 1/2/N абзацев cut-семантика; rich failure → plain полный; invalid/overlap/кап-спаны; документ прежнего канона; legacy-адаптер; пустой title/абзацы; multiline/длинный/невалидный finale; custom-промпт при migrate и rollback; двойной rollback; отсутствующий ключ; грязная БД на startup; stale/богус route mobile; анти-клише поверх/ниже; desktop залипший stage. Все покрыты кодом/тестами/browser — контрпримеров, ломающих инварианты, не найдено.

## Blocking findings

**Нет.** Critical 0 / High 0 / Medium 0.

## Non-blocking debt (Low, зарегистрирован в full_audit_results.md)

1. **[L-R1028-1, low, evidence-hygiene]** `evidence.md:229` — счётчики «новые 4 файла 52+12+22+32» не соответствуют факту (8+12+13+20 = 53 passed, перепроверено). Статусы зелёные, суть не меняется. Действие: поправить строку в evidence при следующей ревизии документа (не блокирует).
2. **[L-R1028-2, low, stale-docstring]** `services/summary_cleanup.py:5` docstring всё ещё упоминает удалённую `_ensure_shiz_postfix`. Не исполняемый код (grep-инвариант соблюдён). Действие: косметическая правка в фоне.
3. **[L-R1028-3, low, pre-existing, вне диффа]** GET `/api/config` не отдаёт `Cache-Control: no-store` — при полном reload страницы браузер может показать кэшированный срез конфига (наблюдено в автоматизации; сервер всегда консистентен, in-app flow обновляется через loadConfig). Поведение существует и до фичи, endpoint фичей не трогался. Кандидат в backlog для UI-волны.

## For the MCA WIP wave (вне этой фичи)

- 2 падения `test_webapp_hotfix8_round1025.py::TestShellV3::test_tokens_section4` и `test_webapp_hotfix9_round1025.py::TestHeaderGlassTexture::test_graphite_tokens`: тесты волны ожидают `saturate(103%)`, `app.css` волной не менялся (105%) — stash-проба независимо воспроизведена. Владельцу волны: либо править app.css на 103%, либо тесты на 105% до влития волны.
- `web/index.html` содержит 2 WIP-хунки (oversight-метрики `@@ -2227`, mca log filters `@@ -4146`) вперемешку с 4 хунками Builder — см. staging-перечень.

## Staging-перечень для DevOps (коммит/деплой 2.58.34 — ТОЛЬКО Builder-скоуп)

**Удаления (6):** `services/summary_filter.py`, `services/summary_context_restore.py`, `tests/test_summary_filter.py`, `tests/test_summary_filter_integration.py`, `tests/test_summary_context_restore.py`, `tests/test_summary_context_restore_integration.py`

**Backend (12):** `services/summary_generator.py`, `services/summary_hybrid_budget.py`, `services/summary_l1_clusterizer.py`, `services/summary_article_formatter.py`, `services/summary_l2_writer.py`, `services/summary_prompts.py`, `services/prompt_migrations.py`, `services/prompt_style_blocks.py`, `services/param_catalog.py`, `services/summary_test_run.py`, `services/summary_run_log.py`, `config/settings.py`

**Frontend (3):** `web/app.js`, `web/static/app.css`, `web/index.html` — **ЧАСТИЧНО**: в индекс брать только 4 ASAP-2.1-хунки (prompt-lib: `@@ -732/-785` is-editing guard + группы §9 + «← К списку»; metadata-панель; перенос анти-клише: удаление со старого места `@@ -1040` + вставка в `<details>` ниже `@@ -1312`). **НЕ брать** WIP-хунки mca-17a: mca-метрики (~строка 2297) и mca log filters (~строка 4244).

**Реестр/доки (6):** `plans/docs/param-registry-round1025.meta.md`, `plans/docs/param-registry-round1025.tsv`, `plans/docs/screen-map-round1025.md`, `plans/docs/canon/architecture.md`, `plans/docs/canon/backlog.md`, `README.md`

**Фикстуры (2):** `tests/fixtures/round1025/catalog_baseline.json`, `tests/fixtures/round1025/f8_baseline.json`

**Тесты переписанные (~45):** `tests/test_summary_{generator,l2_writer,l2_integration,logging_runid,test_run,deploy_round1026,execution_graph_round1026,publish_integration_round1026,fact_package,l1_clusterizer,article_formatter,prompts,two_call_round1022,concurrency,asap2_miniapp_round1027,asap2_observability_round1027}.py`, `tests/test_tool_coordinator_round1026.py`, `tests/test_outgoing_guard_round1022.py`, `tests/test_unified_image_request_round1026.py`, `tests/test_frontend_tab_mapping.py`, `tests/test_param_catalog.py`, `tests/test_prompt_migrations.py`, `tests/test_round1025_f8_registry.py`, `tests/test_webapp_f5_round1025.py`, `tests/test_webapp_api.py`, каталог-пины APP_VERSION/counts в `test_webapp_f4/f6/f7/f9/f11/hotfix6..10/round10xx_ui/round109/1010–1014/1020/1026_polygon/parity_smoke/design_tokens/help_guide/ia_inventory/scope_selector/settings_persistence/self_reflection_provider/budget_*/decision_making/memory_lookup/image_context_memory/telegram_reactions/tool_chains/agentic_ai/round106_ia_smoke` (полный машинный перечень — по маркерам `2.58.34|481|105|103|21` в `git diff HEAD -- tests/`), JS: `tests/js/round1025_f5_workspace_route_test.js`, `round1026_s7_log_summary_filter_test.js`, `round1027_asap2_summary_sections_test.js`, version-пины `round1025_hotfix7/8/9/10_*_test.js`

**Новые (9):** `tests/test_summary_asap21_prefilter_removal.py` `3e416ecf887c…`, `tests/test_summary_asap21_rich_cut.py` `3bd6b9d76406…`, `tests/test_summary_asap21_emphasis_style_finale.py` `d61f06772d4b…`, `tests/test_summary_asap21_prompt_migrations.py` `55015d0901ea…`, + папка `plans/features/mca-asap21-summary-quality-ui-cleanup/` (spec `7b7461d0…`, tasks `f99ba092…`, evidence `4a1498e0…`, prompt-map-audit `6e1f40cd…`, adr-1028-1 `0f7ce3de…`)

**НЕ включать в коммит фичи (чужой WIP):** все прочие модифицированные файлы (handlers/, services/{database,direct_chat_service,chat_lore,image_generation,lore_*,memory_*,mca_*,search_service,smartmodule_*,dossier_*,dream_worker,persistent_throttling,token_counter,web_content_extractor,youtube_transcript_engine,memory_backup}.py, `web/api/routes.py`, `web/api/oversight.py`, WIP-тесты test_database/direct_chat/video_download/web_content_extractor/multilayer_extraction/graphrag_memory/graph_scoring/image_generation/lore_compiler/smartmodule_concurrency/memory_commands, hotfix8/9 правки тестов) и untracked WIP-артефакты (services/mca_*, node_modules/, package*.json, plans/archive/mca-*, tests/test_mca*, tools/ui_round1027* и пр.).

## Unavailable checks

- **Live-поведение Telegram Bot API RichMessage `<details>`** (реальный рендер сворачивания в клиентах Telegram) — локально неверифицируемо без отправки реального RichMessage; структурная часть проверена (aiogram 3.31.0 в venv содержит `InputRichMessage`/`InputRichBlockDetails`; sanitize не трогает теги; тесты форматтера). Закрывается прод-acceptance §43 (T-3995).
- **Содержимое прод-PG значений промптов** (T-3965) — принято по документированной read-only процедуре Builder (R17-совместимой); независимо из среды ревью прод-DSN недоступен и сознательно не использовался. Риск компенсирован тем, что вывод (custom → миграции не трогают) консервативен и проверен юнит-тестами механики.
- Пины прод-переменных деплоя (§42 preflight) — вне ревью (DevOps).

## Binding

- Commit: `8663214289fba89b9bfd509d557c7bca0ae529e0`; Working-Tree-Hash (Builder-scope diff manifest): `9ABE432FCB214A10C6998A1BD4C9949C437A640B14B128D30FC21F88C66091B3`; Spec-Hash: `7B7461D0A3648B0D696D9C5813A924D691D505B04F26C091C54C5C901341B0CD`.
- Любое изменение перечисленных в staging перечне файлов, спецификации или чужие правки поверх этих же файлов инвалидируют аппрув и требуют повторного binding-пересчёта.

**Вердикт: Approved** → следующий шаг контура: `delivery` (DevOps: preflight → checkpoint → 2.58.34 → прод-деплой → §43/§44 live acceptance → §45 log check → §46 gate). До успешного деплоя и live acceptance фича остаётся ACTIVE (§42/§46).
