# evidence.md — mca-asap21-summary-quality-ui-cleanup (Builder, round1028)

- **Baseline:** прод 2.58.33, HEAD `8663214` (docs-коммиты поверх `c0f299c`; код тот же).
  Working tree на старте: незакоммиченный WIP MCA-волны (~150 файлов, §93–§100) —
  **не тронут, не включён** (мои правки поверх WIP только в `web/index.html`, который
  уже был WIP-модифицирован; мои хунки отдельно, WIP-хунки сохранены — см. §Файлы).
- **Верификация spec:** SHA-256 `spec.md` перепроверен `Get-FileHash` —
  `7B7461D0A3648B0D696D9C5813A924D691D505B04F26C091C54C5C901341B0CD` — совпал. ADR-1028-1 прочитан.
- **Коммитов нет** (ревью до коммита); деплой не выполнялся (T-3994+ — вне Builder-скоупа).

## T-3965 — прод-верификация effective prompts (ВЫПОЛНЕНА ПЕРВОЙ)

Процедура spec Q10, read-only (SELECT-only asyncpg к прод-PG через `POSTGRES_DSN`
сервера 198.46.175.136 — тот же доступ, что DevOps-ранбук ASAP-2 deployment.md §4).
R17: содержимое промптов и DSN нигде не печатались/не сохранялись — только sha256-префиксы
и длины. Пробные скрипты с сервера удалены. Полная таблица — `prompt-map-audit.md`.

| Key | Global (bot_settings) | sha256-12 | класс | Per-chat (PERMsoc −1002661910336) |
|---|---|---|---|---|
| prompts.summary_l1_clusterizer_system_prompt | есть, 3778 | `8237880de15f` | custom | отсутствует |
| prompts.summary_l2_writer_system_prompt | есть, 3110 | `c913a4b4c53d` | custom | отсутствует |
| prompts.summary_system_prompt | есть, 3578 | `67344524cd16` | custom | отсутствует |
| prompts.summary_editor_system_prompt | есть, 2063 | `14ae80070e29` | custom | отсутствует |
| prompts.summary_narrator_system_prompt | есть, 1693 | `58c9d4237eaa` | custom | отсутствует |
| prompts.summary_cover_style | есть, 33 | `faed624c9d0b` | custom | **есть**, custom, 110 симв |

Выводы:
1. **Effective Hybrid L2 на проде = глобальный PG genuinely-custom** (`c913a4b4c53d`) — гипотеза
   §11 подтверждена в варианте custom (не канон, ни один PREV; CRLF-нормализация совпадений
   не дала — правки владельца поверх канона).
2. **Per-chat mismatch (расхождение 11):** per-chat-значений stage-ключей на проде НЕТ
   (единственный per-chat prompt — `summary_cover_style`, который рантайм уже читает per-chat).
   **Условный фикс (h) НЕ применён** — условие spec Q10 («аудит найдёт per-chat-значения»)
   не выполнено; по spec цепочка документируется без правки кода. Δ каталога = 0.
3. Следствие для миграций T-3980: прод-ключи genuinely-custom → миграции R1028 их НЕ тронут
   (запрет §26). Новые детерминированные гарантии (typography normalizer, emphasis_spans,
   finale, Rich cut) заработают без промпта; prompt-часть активируется после reset ключей
   владельцем (runbook-шаг T-3994/T-3996). Легаси-Narrator custom может подавлять шиз-строку
   до reset (известный компромисс запрета молчаливой перезаписи).

## Реализация по блокам

### Блок B — prefilter (T-3969–T-3973)
- `services/summary_generator.py`: блок `flags.summary_filter_enabled` в `_run` удалён
  ЦЕЛИКОМ; `xml_rows` не существует — оба контура получают исходное `rows`;
  `_run_legacy_pipeline` потерял параметр `xml_rows`; `_apply_filter`/`_restore`/
  `_collect_extra_parents`/`_is_open_anchor`/`RESTORE_CHAIN_CALLS_MAX`/слот
  `_filter_metrics` удалены; `record_run_from_context(ctx, None)` — узел `algorithm`
  исчез из карты вызовов; `build_test_rows` — без S1/S2 (контракт (j), shape сохранён:
  `filtered=source, dropped=[], restored=[], filter_metrics={}`).
- **`services/summary_filter.py` УДАЛЁН ЦЕЛИКОМ** (score_message НЕ перенесён —
  grep-инвариант (a): `rg "score_message"` по services/ = 0);
  **`services/summary_context_restore.py` УДАЛЁН ЦЕЛИКОМ** — `build_l1_payload`
  перенесён в `summary_l1_clusterizer.py` (сигнатура без изменений; 4 импортера
  переподключены). Grep-критерий Q2 (`summary_context_restore|restore_context|
  RestoreParams|RestoreResult|RESTORE_START|RESTORE_COMPLETE|_collect_extra_parents`
  по services/+tests/) = 0; `rg "build_l1_payload"` = ровно одно определение.
- `services/summary_hybrid_budget.py`: +`estimate_and_split`/`Fragment`/
  `DEFAULT_FRAGMENT_OVERLAP` (имена/сигнатуры без изменений; строковые хелперы не
  дублированы — `services.database.row_get`). Eviction в `pack_l1_input` —
  `(reply_protected, timestamp, db_id)`, «последнее сообщение неприкосновенно» +
  `truncated/skipped_ids/WARN` сохранены (ADR-1027-10 D7).
- `services/summary_test_run.py`: stage-ключ `"filter"` сохранён (UI-совместимость),
  поля `saved_count=filtered_count, restored_count=0, drop_percent=None,
  duration_ms=None`; L1-stage += `skipped` (packing-счётчик).
- `config/settings.py`: 8 env-констант `SUMMARY_FILTER_*` удалены (комментарий-надгробие
  про безопасное игнорирование сирот в БД).
- `services/param_catalog.py`: -8 ключей + -2 группы (`flags/limits_summary_filter`);
  TAB_RULES in-place (21); титулы 6 промптов → §9 + описания «Legacy fallback, не основной
  Hybrid writer» (№3–5); счётчики **481/105/103/21** (санкция Architect).
- Frontend (в объёме T-3973): `web/app.js` — `WORKSPACE_TABS.mod_summary` без `'prep'`,
  label `'prep'` удалён, `workspaceGroupTab` без маппинга filter-групп, sources mod_summary
  без filter-групп, `workspaceCoverage`/`currentTabGroups`/`workspaceTabHasContent`
  обновлены.

### Блок C — Rich cut + emphasis (T-3974–T-3976)
- `services/summary_article_formatter.py`: `_emphasis_spans_of` (список с fallback на
  legacy `emphasis`), `_resolve_span_positions` (start ASC, len DESC, порядок; жадный
  без пересечений), `_render_with_spans` (секвенциальный walk, `<b>` вокруг каждого,
  escape) — один код для rich и plain-HTML; `format_rich_html`: img → h1 → p1 → при
  >1 абзацах ОДИН закрытый `<details><summary>Читать дальше</summary>` (+finale внутри);
  0–1 абзац — без ката; `CUT_SUMMARY_TEXT = "Читать дальше"`; plain-каналы (plain_html/
  chunk_plain_blocks/plain_text) — полный текст без ката; `_finale_of` (последний блок);
  `rich_document_limits` — по полному HTML, семантика fail-closed сохранена.
- `services/summary_l2_writer.py`: `TOP_LEVEL_FIELDS += finale`, `PARAGRAPH_FIELDS +=
  emphasis_spans`; `_canonicalize_spans` (Q3 п.1–7: cleanup карты замен, точная
  подстрока финального текста, len ≤ PARAGRAPH_MAX, тегоподобные отбрасываются
  `</?[A-Za-z]`, invalid → счётчик, дедуп, кап 4, derived-`emphasis` = первый принятый,
  прочие kind не бракуют); `_valid_finale` (строка, одна строка — `\n` отбраковывается,
  1..200 после cleanup+strip; иначе canonical без finale, `finale_present=0`).

### Блок D — стиль/finale/миграции (T-3977–T-3980)
- `services/summary_cleanup.py` (`cleanup_llm_text`) применён к title/paragraphs/finale
  в `_validate` ДО substring-проверок (T-3978, контракт (d); без kill-switch).
- `services/summary_prompts.py`: `_SUMMARY_L2_WRITER_R1028_BASE` (грамматика §15 +
  инструкция владельца §16 дословно + typography §17 + акценты §18–19 + finale §21–24 +
  сохранённые §97/ДЛИНА/АВТОРЫ) → `SUMMARY_L2_WRITER_SYSTEM_PROMPT`;
  `PREV_SUMMARY_L2_WRITER_R1028` = байт-в-байт прежний канон R1027 (проверено sha256
  против локальной карты: `e739433336ed`); Narrator R1028 (§25 — шиза — творческое
  решение модели) + `PREV_SUMMARY_NARRATOR_R1028` (`84941de297f8` — байт-в-байт);
  Legacy Single `_SUMMARY_R1028_BASE` (ФИНАЛ → опциональная строка) → `SYSTEM_PROMPT` +
  `PREV_SUMMARY_SYSTEM_R1028` (`ffbee61a8565` — байт-в-байт). L1-канон НЕ менялся
  (тест-пин). `{username}` из канона удалён (шиза — не шаблон); `{max_symbols}` остался.
- `services/prompt_migrations.py`: +ступени R1028 (L2/Narrator/Single), Narrator — новый
  миграционный ключ; ROLLBACK: L2→PREV_R1028, Narrator→PREV_R1028 (новый), Single→
  PREV_SUMMARY_SYSTEM_R1028 (заменил R1021-цель по конвенции «непосредственный прежний»);
  cover_style — без миграций (§26).
- Канон-эталоны атомарно: `plans/docs/canon/architecture.md` (секция L2 — полный канон
  R1028, byte-identical пин теста зелёный), `plans/docs/canon/backlog.md` (блок ФИНАЛ
  Legacy Single → опциональная строка §25; byte-пин теста зелёный).
- `services/prompt_style_blocks.py`: +`resolve_prompt_with_source` (global/default) —
  источник для L2_START.

### Блок E — Prompt Library (T-3981–T-3985)
- `web/app.js`: `openWorkspacePrompt` — `seg = stage || item.stage || ''` (залипший
  ws.stage убран, Q6.1); `workspacePromptFocus` — фолбэк на полный список модуля при
  ненайденном ключе в stage-списке, нигде → null (Q6.2); `workspacePromptStale`
  (computed) + watcher → `promptBackToList()` redirect `#/ai/prompts/<slug>` (Q7.1);
  `promptBackToList` (method) — явный back (Q7.2); `SUMMARY_PROMPT_META` + `SUMMARY_PROMPT_GROUP_ORDER`
  + computed `workspacePromptGroups` + method `summaryPromptMeta(key)` (витрина §9/§10);
  `promptsShowAccordion`/`promptVisibleItems` — cover_style не прячется под аккордеон
  (§9:3093–3104); log-viewer маркеры: `FILTER_`/`RESTORE_` → `SOURCE_WINDOW`
  (FILTER/RESTORE label'ы удалены).
- `web/index.html`: `is-editing` — только `workspacePromptFocus && workspace.promptKey`
  (валидный фокус + явный ключ; stale не глушит дерево; без ключа mobile показывает
  СПИСОК — flow §13); дерево рендерит группы §9 с бейджами; editor: кнопка
  «← К списку» (`data-prompt-back`, тач ≥44px) + бейдж; metadata-панель
  Pipeline/Stage/Runtime/Key/Source (`data-meta-*`); анти-клише монитор перенесён
  НИЖЕ промпт-контента и свёрнут в `<details>` (state не сохраняется — механика V2
  не тронута). **`web/api/routes.py` НЕ тронут** (граница эскалации соблюдена).
- `web/static/app.css`: +`.prompt-back-btn { min-height: 44px }` + комментарий в
  mobile media-query (≤767px); is-editing механика сохранена.

### Блок F — observability (T-3986)
- `SOURCE_WINDOW` (INFO, в `_run` сразу после чтения окна; run_id/chat_id/messages).
- `L1_CONTEXT_PACK` (INFO, в `run_l1` после `pack_l1_input`; source_messages/
  packed_messages/serialized_tokens/physical_budget/overflow(0|1)/skipped/kind).
- `L2_START` += `prompt_key=`/`prompt_source=` (chat/global/default; `param` — только
  тестовая инъекция); `L2_COMPLETE` += `emphasis_spans=`/`emphasis_dropped=`/
  `finale_present=`; `FORMAT_COMPLETE` += `rich_cut=`/`visible_paragraphs=`/
  `collapsed_paragraphs=` (plain: rich_cut=0, visible=all) — `log_format_complete`
  расширен аддитивно (старые вызовы совместимы).
- `SUMMARY_COMPLETE` минус `saved_count`/`restored_count`; RunContext минус S1-поля.
- JS log-viewer «Саммари»: маркеры без `FILTER_`/`RESTORE_`, +`SOURCE_WINDOW`
  (L1_CONTEXT_PACK покрыт префиксом `L1_`); харнесс
  `tests/js/round1026_s7_log_summary_filter_test.js` переписан (S7-LOG-SUMMARY-OK).

## Тесты (блок G) — новые/переписанные

**Новые файлы:**
- `tests/test_summary_asap21_prefilter_removal.py` — §27: «у кота рак»/«Леха уехал»
  доходят до L1; 500 сообщений — все доступны; physical overflow → technical packing +
  WARN «L1 truncated input» + 0 score_message; eviction-key без веса; каталог 481/105/
  103/21; startup с «грязной» БД ( сироты summary_filter_* читаются raw, импорты живы).
- `tests/test_summary_asap21_rich_cut.py` — §28: 1 абзац без ката; 2 абзаца → p2 в
  закрытом cut (атрибута open нет); 10 абзацев + finale — всё в ОДНОМ cut, ничего не
  потеряно; plain_html/chunks/plain_text — полный текст; rich failure → plain fallback
  несёт ВСЮ статью; limits по полному HTML; too_long fail-closed.
- `tests/test_summary_asap21_emphasis_style_finale.py` — §29: 3 спана bold в rich +
  plain + raw; invalid молча в счётчик; overlap детерминирован; кап 4 (5-й отброшен);
  legacy emphasis — первым в очереди; документы без новых полей валидны; §30: cleanup
  на канонизации (ёлочки→", —→-), идемпотентность; §31: winner из LLM (UserB при A=30/
  B=5), code не подставляет (grep most_active_author=0); finale невалидный → строки нет;
  finale последним блоком во всех каналах.
- `tests/test_summary_asap21_prompt_migrations.py` — (а) canonical-old→new (6 ступеней),
  ROLLBACK new→PREV_R1028 (3 ключа), (б) custom не тронут (migrate+rollback), (в)
  отсутствующий ключ skip, идемпотентность no-op; PREV-снапшоты байт-в-байт; новый
  канон L2 содержит §15–§19/§21–24 маркеры и НЕ содержит запрета сленга; Narrator/Single
  §25; L1-канон не менялся; cover_style вне миграций.

**Переписанные под новую семантику:** `test_summary_generator.py` (ShizPostfix →
grep-инварианты «code не выбирает winner»; ManualFlag/Cleanup без постфикса),
`test_summary_l2_integration.py` (S1/S2-класс → `TestOnPathNoPrefilter`), 
`test_summary_logging_runid.py` (SUMMARY_COMPLETE без S1-полей, +SOURCE_WINDOW,
без FILTER_*; monkeypatch build_l1_payload → summary_l1_clusterizer),
`test_summary_test_run.py` (build_test_rows без S1; каталог-пин), `test_summary_deploy_round1026.py`
(S1 env-слой отсутствует; no-prefilter live-тест; forbidden-пути с NOTE round1028;
AST-пин без `_ensure_shiz_postfix`-токена), `test_summary_asap2_miniapp_round1027.py`
(состав mod_summary без prep-групп), `test_summary_publish_integration_round1026.py`
(теги + details/summary; forbidden с NOTE), `test_summary_execution_graph_round1026.py`
(forbidden NOTE), `test_frontend_tab_mapping.py` (103/105/481, mod_summary без filter),
`test_round1025_f8_registry.py` (481/105/103/21, delta 70, meta 481/411/70, версия),
`test_prompt_migrations.py` (+Narrator-ключ; ROLLBACK-цели R1028), `test_summary_prompts.py`
(byte-пин через обновлённый canon/backlog.md; placeholder {max_symbols} единственный),
`test_summary_l2_writer.py` (canon R1028-маркеры, byte-identical doc, миграции R1028,
grounded quote в нормализованной форме, canonical paragraphs c emphasis_spans),
`test_summary_article_formatter.py` (теги + details/summary), `test_summary_asap2_observability_round1027.py`
(+SOURCE_WINDOW/L1_CONTEXT_PACK; FILTER_*/RESTORE_* эмиттеров нет), `test_summary_concurrency.py`
(публикация == текст модели), `test_summary_two_call_round1022.py` (то же),
`test_outgoing_guard_round1022.py` (+Narrator вне R1022), `test_param_catalog.py`
(422 Settings/105 GROUPS/limits 199/flags 74), `test_webapp_f5_round1025.py`
(mod_summary без prep; label prep отсутствует), `test_webapp_api.py` (456 categorized),
`tests/js/round1027_asap2_summary_sections_test.js` (prep удалён; filter-группы не
маппятся), `tests/js/round1025_f5_workspace_route_test.js` (mod_summary без prep).

**Каталог-пины (санкционированная Δ −8/−2, 481/105/103/21, Settings 422, categorized 456)
обновлены в 44 тест-файлах** прошлых раундов (f4/f5/f7/f9/f11, hotfix6–10, round10xx_ui,
budget_*, tool_*, и др.) — механика ASAP-2 (обновление пинов при санкционированной Δ,
fixture f8_baseline.json обновлён: counts 481/105/103/21/70, sha256 param_catalog,
superseded_by NOTE; catalog_baseline.json: ключи/группы/counters + NOTE; TSV/meta/screen-map
регенерированы `tools/gen_param_registry_round1025.py --check` OK).

## Блок H (T-3993)
- `APP_VERSION = "2.58.34"` (config/settings.py) — ChangeLog-комментарий по домовому
  стилю (полное описание раунда + откат-заметка).
- README.md: новая версионная строка v2.58.34 (полное описание + откат), предыдущая
  раунд-строка свёрнута в «Ранее 10.27 ASAP-2 (v2.58.33)».
- F8-переиздание атомарно: meta.md (APP_VERSION 2.58.34), TSV (481 строк,
  дельта 411→481=70), screen-map, fixture `f8_baseline.json` (counts/sha256/superseded_by),
  `catalog_baseline.json`, маркер-тесты (29 passed), APP_VERSION-пины в тестах
  (2.58.33 → 2.58.34: 12 файлов pytest + 4 JS-харнесса + README-пины).
- Откат-заметка: cold git-revert фича-коммита до 2.58.33; сироты `summary_filter_*`
  в БД не удалялись (8 строк bot_settings + 1 override PERMsoc на проде —
  безвозвратно обратимо); промпты — ROLLBACK на PREV_*_R1028 без рестарта;
  Rich cut/emphasis/finale — revert (персистенции нет; plain fallback инвариантен);
  каталог — revert + повторное F8-переиздание; аварийные режимы
  `flags.summary_legacy_fallback_enabled`/`flags.summary_hybrid_l2_enabled` сохранены.

## Прогоны (финальные)

- **pytest (полный):** `9876 passed, 2 failed` — оба падения pre-existing от ЧУЖОГО
  WIP: `test_webapp_hotfix8_round1025.py::TestShellV3::test_tokens_section4` и
  `test_webapp_hotfix9_round1025.py::TestHeaderGlassTexture::test_graphite_tokens`
  (WIP-волна правит тесты на `saturate(103%)`, app.css волной не менялся — в HEAD
  105%; проверено stash-пробой: падает и без моих изменений; на HEAD-версиях тестов —
  зелёные). К моим изменениям отношения не имеют, НЕ чинил (чужой WIP).
- **pytest summary-пакет:** все summary-* файлы зелёные (генератор 65, l2_writer 44,
  l2_integration 15, logging_runid 36, fact_package 53, publisher+execution 103+47,
  новые 4 файла 8+12+13+20).
- **JS-харнессы: 49/49 OK** (включая переписанные round1026_s7_log_summary_filter,
  round1027_asap2_summary_sections, round1025_f5_workspace_route, hotfix7–10 version-пины);
  `test_webapp_js_unit.py` 34 passed.
- **F8 `--check`:** CHECK OK (реестр 481 == REGISTRY, карта полна, R17-чисто,
  TSV/map идемпотентны); маркер-тесты 29 passed.
- **Δ DDL = 0** (pg_db.py не менялся; DDL-операторов в diff нет); Δ внешних зависимостей = 0.

## Browser-verification (implementation-side smoke; Reviewer повторит независимо)

Окружение per spec §5: standalone uvicorn (`create_app` без Telegram) на
127.0.0.1:8765 + одноразовый docker-PostgreSQL 16 (adminbot-test-pg, удалён после
проверки; чистая БД → DDL + сид каталога, `bot_settings` 417 строк); auth — подписанный
TMA initData (HMAC WebAppData локального .env-токена, юзер id=1 + admin-роль в
bot_admins; инжект через sessionStorage). Playwright MCP; секреты/содержимое промптов
не печатались (значение Cover Style — код-дефолт, не секрет).

- **B1 (desktop 1440×900, `#/ai/prompts/summary`):** PASS — 6 промптов в группах §9
  (Hybrid Summary [L1, L2], Обложка [Cover Style], Legacy Summary Fallback [Single,
  Editor, Narrator]); клик по каждому → editor с непустым textarea (проверены ключи и
  длины: L1 3702, L2 4580, Cover 31, Single 3558, Editor 2023, Narrator 1850),
  корректный Key, metadata-панель Pipeline/Stage/Runtime/Key/Source заполнена;
  бейдж «АКТИВНЫЙ HYBRID OUTPUT» на L2, «Legacy fallback» ×3.
- **B2 (регресс Q6):** PASS — Narrator (URL `…/summary/prompts.summary_narrator_system_prompt`)
  → клик «Кластеризатор (L1)» → editor переключается на L1 (3702), URL
  `…/summary/synthesizer/prompts.summary_l1_clusterizer_system_prompt` (exact-пин).
- **B3 (save-цикл ×6):** PASS — для каждого из 6: edit (native value setter + input
  event) → sticky-save → **ровно 1 POST /api/config с верным ключом** (перехват fetch),
  state clean; после reload маркеры присутствуют во всех 6 (persisted); затем значения
  возвращены к исходным (второй цикл save, state clean).
- **B4 (mobile 390×844):** PASS — без ключа: дерево видимо, editor скрыт; выбор →
  editor fullscreen, дерево скрыто (валидный фокус); «← К списку» → список вернулся,
  hash `#/ai/prompts/summary`; Cover Style на mobile открывается, значение видно.
  Скриншот: `tools/asap21_b4_mobile_list.png`.
- **B5 (stale-guard):** PASS — `#/ai/prompts/summary/verbalizer/prompts.summary_cover_style`
  → НЕ пустой editor: фолбэк-поиск нашёл Cover Style (валидный editor, metadata);
  `…/verbalizer/prompts.bogus_nonexistent_key` → редирект на канонический
  `#/ai/prompts/summary`, редактор-заглушки нет.
- **B6 (анти-клише, mobile):** PASS — блок `<details>` ниже промпт-контента, свёрнут
  по умолчанию (первый экран — промпты), разворачивается/сворачивается, list/editor
  доступны, горизонтального overflow нет (scrollWidth = 390). Скриншот:
  `tools/asap21_b6_mobile_anticliche_expanded.png`.
- **B7 (гигиена):** PASS — console без ошибок на всех шагах (favicon 404 и 503
  /api/chat_lore — особенности standalone-окружения без Telegram-рантайма, fail-open;
  на проде этот endpoint обслуживается); сеть — только ожидаемые GET /api/config,
  /api/me, /api/anticliche и 6 POST /api/config (по одному на save).

## Отклонения/находки для Reviewer

1. **(h) не применён** — per spec Q10 (per-chat stage-значений на проде нет). Metadata-
   панель Source показывает `configSourceLabel` (chat override / global / code default) —
   честно; точный runtime-источник после T-3965 = global для всех 6.
2. **`web/index.html` — файл был WIP-модифицирован** (mca-17a-хунки). Мои хунки:
   prompt-lib блок (группы/бейджи/back/metadata/is-editing), перенос анти-клише в
   `<details>` ниже контента. WIP-хунки (oversight metrics, mca log filters) сохранены
   без изменений.
3. **2 pre-existing тест-падения** (hotfix8/9 tokens, `saturate(103%)`) — внесены чужой
   WIP-волной (тесты WIP-модифицированы, css нет); на HEAD зелёные, с WIP — падают
   независимо от ASAP-2.1. НЕ чинил (чужой WIP); Reviewer сверит с владельцем волны.
4. `test_summary_deploy_round1026.py::test_run_logic_ast_identical_to_baseline` —
   AST-пин функций умышленно ослаблен ТОЛЬКО удалением токена `_ensure_shiz_postfix`
   из пина `_run_legacy_pipeline` (контракт (e)); остальные 13 функций пин не трогал —
   byte-parity зелёный.
5. Deployment-runbook факты для T-3994/T-3996: после деплоя 2.58.34 ожидать в старте
   `[prompt_migration] кастом юзера — НЕ трогаем` для 6 прод-ключей; новые
   deterministic-гарантии активны сразу; prompt-часть (§15–§19 инструкции, §25 шиза) —
   после сброса ключей владельцем (удаление PG-строки → сид канона при рестарте).

## Статусы задач

- T-3964 ✅ (prompt-map-audit.md), T-3965 ✅ (см. выше), T-3966/T-3967/T-3968 ✅ (факты в
  spec §2, подтверждены grep-ами; deliverable — spec + evidence).
- T-3969 ✅, T-3970 ✅, T-3971 ✅, T-3972 ✅, T-3973 ✅.
- T-3974 ✅, T-3975 ✅, T-3976 ✅.
- T-3977 ✅ (канон R1028; effective-проверка — через L2_START effective_prompt_key в проде
  после деплоя; на проде ключ custom — см. T-3965 следствие), T-3978 ✅, T-3979 ✅,
  T-3980 ✅.
- T-3981 ✅ (desktop smoke B1–B3), T-3982 ✅ (mobile smoke B4–B5), T-3983 ✅, T-3984 ✅,
  T-3985 ✅.
- T-3986 ✅.
- T-3987 ✅, T-3988 ✅, T-3989 ✅, T-3990 ✅ (B1–B3), T-3991 ✅ (B4–B7, browser implementation-
  side; Reviewer повторит), T-3992 ✅ (полный регресс: 9876 passed / 2 pre-existing WIP-fail,
  JS 49/49, F8 --check OK, Δ DDL=0).
- T-3993 ✅ (2.58.34 + README + F8 атомарно + откат-заметка).
- T-3994–T-3997 ⏸ НЕ ВЫПОЛНЯЛИСЬ (прод-деплой/live acceptance/log-check — DevOps после
  Reviewer Approved; orchestrator подтвердил: деплой — не Builder).
- T-3998 ⏸ (gate §46 — вне Builder).
