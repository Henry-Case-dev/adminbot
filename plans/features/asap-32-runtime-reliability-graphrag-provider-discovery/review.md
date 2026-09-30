# review.md — `asap-32-runtime-reliability-graphrag-provider-discovery` (ASAP-3.2)

> **Feature-ID:** `asap-32-runtime-reliability-graphrag-provider-discovery`
> **Risk-Level:** R3
> **Статус:** **Approved for release** (Round 2, 01.10.2026 — H-ASAP32-1 закрыт, M-ASAP32-2 закрыт; production-acceptance пункты остаются DevOps-гейтами T-4227/T-4232…T-4236). Round 1 (01.10.2026): **Needs Fixes** — 1 High blocking (H-ASAP32-1), 1 Medium non-blocking, 5 Low; ревью+focused audit — единый независимый гейт @Reviewer (код ревьюером не правился; прогоны/скриншоты — evidence, кеш `__pycache__` чистился как тестовая гигиена).

## Binding

- **Reviewed-Commit:** `1287130b8f88dd9809ae440e2e7859af139e1de0` (HEAD; bbdee1c — предок, между ними 3 docs-коммита EXTRA round1029 — чужая закрытая фича, вне скоупа).
- **Working-Tree-Hash:** `2e61d7407d1a70f9c526b97b43310885f367bb46215f0a1b448ae1e33397d967` = SHA-256 манифеста `plans/reports/asap32_wth_manifest_review.txt` (HEAD + staged=EMPTY + SHA-256 `git diff HEAD` = `99afcea8c558a77…` + per-file SHA-256 всех 336 untracked, кроме чужого WIP `node_modules/`, `.playwright-mcp/`, `extra_images/`; review-скриншоты `rev_*.png` включены в состояние).
- **Spec-Hash:** `E0F752CBAABF932011C77166BA6FF0465865AE718671D311B5571BDE7FA878AA` ✓ (пересчитан Get-FileHash, совпадает с binding @PM).
- **ADR-1028-5:** `24FD73A442B59917A1A673DED8C065868985D3050F55A9A5CA769C2B31A6874D` ✓.
- **tasks.md:** текущий `C4BF1E24…` ≠ заявленным Orchestrator'ом «~E7293237…» (hash на старте Pass 2 по evidence) — объяснимо чекбоксами T-4229/T-4231, проставленными при закрытии Pass 2; содержание соответствует evidence. Некритичный doc-drift (L-ASAP32-5).
- **`plans/current_task.md`:** SHA-256 `E828A092…B6750A` ✓ НЕ изменён (R17). Чужой WIP (`mca-04b`, `extra_images/`, `node_modules/`, `package*`, `.playwright-mcp/`, plans/backlog|metrics|workflow_state|mca-round1027-*) не тронут Builder'ом (diff-сверка).

## Git base и inspected change scope

Незакоммиченный ASAP-3.2-скоуп: 78 tracked-modified (3 новых сервиса, 8 новых тест-файлов, E2E-инструмент; web/api/cover_styles.py +313, web/index.html ~599, app.js +109, app.css +67, pg_db +DDL, settings/param_catalog/pytest.ini/conftest, ~30 обновлённых якорей) + untracked (feature-доки). Diff читан по зонам D1–D14; полные diff-файлы зон сохранены в process-логе ревью.

## Checks performed (команда → факт → вывод)

| # | Проверка | Команда/метод | Факт | Вывод |
|---|---|---|---|---|
| 1 | D1–D3 GraphRAG | чтение `services/graphrag_rebuild.py` (882 стр.) + diff `summary_memory.py` + DDL-шаблоны | shadow `…_g{N}` идемпотентный CREATE; полный re-embed (cursor, НЕ fill-missing); CAS state machine на `task_jobs` (queued→running→checkpoint→validated→activated/failed, +paused/cancelled); race-guard: criterion-1 `fp==current` в `_validate` + mismatch → `failed/fingerprint_changed`, shadow drop, checkpoint reset, re-schedule; 9 критериев (1 fp, 2 dim из DDL, 3/4 provider+model+preproc из реестра, 5 coverage id≤frontier + `added_after_scan` allowed-missing, 6 no-orphans анти-join в swap, 7 counts, 8 KNN self-match smoke, 9 swap-транзакция); атомарная активация: ОДНА `write_transaction` (DROP live + CREATE live + INSERT..SELECT c анти-orphan + superseded/active, `rowcount!=1` → rollback); severity-коалесинг (1 WARNING → DEBUG при неизменном (status,fp12) в cooldown 300с, WARNING на state-change); rerank strict JSON + robust parser; `EMBEDDING_GENERATION_*` события | Соответствует D1–D3; `UPDATE … SET status='active'` — единственный writer, только после критериев 1–8 (grep по `services/` подтверждает); FTS-гейт не удалялся; read-path фильтрует expires_at/chat_id — семантика сохранена |
| 2 | Rerank latent positional fix | `select_by_rerank` (mca_retrieval_context.py:118) + diff `rerank_rag_facts` | `id_of` — pre-existing kw-параметр; фикс = call-site `id_of=lambda c,i: str(i+1)` (позиции промпта, НЕ row-id); `apply_retrieval_rerank` не тронут (id-семантика другая); тест «регресс продовых row-id dict-фактов» в test_rerank_contract (14/14) | **Фикс легитимен**, объясняет прод-симптом kept=8/10 при валидном ответе; якоря F4 сохранены |
| 3 | D4–D5 Media | чтение `services/media_execution.py` (874 стр.) + diff image_generation/cover_style_edit/cover_style_jobs | 4 окна (connect/read-inactivity/poll/total); sync-only → read=total (честный `remote_progress=none`, fake ping отсутствует); stage-aware key provider+model+operation; estimator ТОЛЬКО успешные длительности (`record_media_outcome`: timeout/failures — отдельные счётчики); формула clamp(max(cold,p95×safety),min,ceiling); durable `MediaJobState` на REUSE `task_jobs` (ΔDDL=0); `recover_media_jobs`: job-id + supports_status → RECOVERED (0 resubmit), sync-only → `unknown_after_disconnect` без платного retry; fallback только после terminal failure (`primary_running` guard); kill-switch `MEDIA_EXECUTION_POLICY_ENABLED` OFF → legacy 90/180/240 | Соответствует D4–D5; адаптеры без выдуманных маршрутов (NanoGPT — только верифицированные кодом routes; OpenRouter — discovery-only, `route_unverified` честно) |
| 4 | D6–D7 Capacity | diff `model_capacity.py` + внешняя верификация | `PROVIDER_NANOGPT`/`PROVIDER_DEEPSEEK` — отдельные identity; NanoGPT live-каталог `GET /api/v1/models?detailed=true` → `context_length`/`max_output_tokens`, miss → registry/fallback с честным source; DeepSeek registry-hit → `source=verified_registry` (НЕ provider_catalog); unknown без URL-угадывания; timeout 2с + TTL (не блокирует hot path) | Соответствует D6–D7. **Независимая документарная верификация:** официальные docs.nano-gpt.com (`/api-reference/endpoint/models`, `/api-reference/endpoint/image-models`) подтверждают route и схему полей — заявление Builder'а о live-верификации схемы corroborated первоисточником |
| 5 | D8–D9 Summary | чтение `summary_semantic_reduction.py` (209 стр.) + diff summary_fact_package/summary_generator/summary_test_run | ON-путь: `_apply_fragment_caps`/`_enforce_budget` НЕ вызываются; reduce (stable-ID merge, topic dedupe, cross-thread fragment dedupe, evidence-union) → при превышении бюджета paged L2 (`_build_pages`, oversized-тема делится lossless, continuation — скелет без дублей); coverage-метрики (unique_before/after, merged, unique_dropped, passes, pages, segmented); позиционный каскад — только kill-switch OFF + видимое `FACT_PACKAGE_POSITIONAL_FAILSOFT`+`SUMMARY_COVERAGE_DEGRADED reason=positional_failsoft`; empty-guard (`_emit_near_empty_package`, fail-closed EMPTY) не тронут; сегментация §42 (part/part_total, конкатенация=исходник) вместо `text[:1000]` | Архитектура соответствует D8/D9. **H-ASAP32-1 (blocking) — см. Findings:** повреждение UTF-8 в runtime-строках этого модуля |
| 6 | D10 Recompose | diff llm_client/tool_loop + hunks direct_chat_service | `generate_chat(+fallback_payload_adapter)` — вызов ровно один при переключении, shape-валидация, громкий oversized-risk лог при failure (усиление против тихого fail-open); `chat_with_tools` прокидывает адаптер в КАЖДЫЙ раунд + FR-15 plain (`generate`); tool-ветка Direct: `extra_reserve=tools_tokens` вычитается до recompose (§45); regression-тест §46 (1M→32K+tools) 8/8; M-ASAP31-2 закрыт | Соответствует D10 |
| 7 | D11 Decision | diff direct_llm_react + hunks direct_chat_service + обновлённые якоря | Decision Task в ТОТ ЖЕ Stage-1 (парсинг после генерации; call count не растёт — тесты §74); force → REPLY hard gate ДО (decision task не вводится); SILENT conscious-LLM → `_execute_silent_ack` (🗿, конъюнкция гейтов; фон/not-addressed — hard gate без LLM); allowed-set runtime (REACT при toggles.reactions, SILENT при ignore_trivial); INVALID-sentinel — битая JSON не уходит пользователем, детерминированный fallback demoted-матрицы; LLMError → fallback; plain-text = сознательный REPLY (соответствует §52 спека — «REPLY отвечает текстом в том же вызове»); kill-switch `DIRECT_LLM_DECISION_ENABLED` + конъюнкция со старыми гейтами, OFF-паритет (`<Reaction_Task>`); якоря D11 обновлены точно по санкции (mock SILENT-JSON, 1 вызов, OFF-строки сохранены) | Соответствует D11; все отклонения легитимны |
| 8 | D14 контракт/seed/права/assets | grep `web/api/cover_styles.py` + diff registry/jobs/pg_db/routes/bot | `def _pool(` / `registry.*(_pool` — 0 вхождений (хелпер удалён); 42 registry-вызова на `_pg(cache)`; static guard-тесты §121; integration-тесты §120 без monkeypatch registry + обязательный RED-on-pre-fix regression; seed: startup call-site в bot.py (ранее ОТСУТСТВОВАЛ в проде — корень «seeded absent», подтверждено), existing→no-op, прямой is_deleted-чек (не воскрешает), `COVER_STYLE_SEED_INCOMPLETE`; read/select → `requires_permission('access')` (6 роутов), ВСЕ мутации → `requires_global_admin()` (11 роутов) — §135 backend-enforced, тест non-admin bypass; asset GET 200/байты + DB-без-файла → 404 + `COVER_STYLE_ASSET_MISSING`; события §128 все присутствуют; `prompts.summary_cover_style_id` hidden + 422 на ОБЕИХ ветках /api/config; erratum §123 appended (история сохранена) | Соответствует D14; ослабление read/select до access — легитимно по §135 (обычный пользователь выбирает/использует) |
| 9 | D14 connection model | diff registry/pipeline/jobs | PG-DDL +1 `cover_style_connections` идемпотентный (Δ-лист: 5→6); профиль хранит FK, секрет НЕ хранит; `resolve_style_slot(profile, connection)` — raw URL не интерпретируется; per-connection api_key в edit; API /cover/connections (admin) + 422 на raw-URL в профиле | Соответствует §103–§105; секрет в Connections — в рамках существующего паттерна хранения ключей (bot_settings), наружу отдаётся маска |
| 10 | Санкции | F8 `--check`; тесты DDL | F8 **CHECK OK, 488/427/463/105/103/21** (Δ каталога = 0; 18 новых env-only ClassVar — не каталог); SQLite v19 (тест ассертит user_version=19; shadow — идемпотентный CREATE, v20-бронь mca-04b цела); PG +1 таблица (санкция D14/§104) | Санкции соблюдены |
| 11 | Тесты | `pytest tests -q` (после очистки `__pycache__`) | **10316 passed / 2 failed** — оба fail якорные чужие forbidden-paths (`test_tool_coordinator_round1026.py::TestBounds::test_forbidden_paths_out_of_diff`, `test_unified_image_request_round1026.py::TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline`); новые наборы: Pass-1 **57/57**, Pass-2 **45/45**; `-k`-срезы Builder подтверждены косвенно (полный прогон) | Совпадает с evidence; suite зелёный включая все ASAP-3.2-зоны |
| 12 | JS | `node --test` 52 файла | **52/52 passed** | ✓ |
| 13 | UI E2E инструмент | `tools/ui_asap32_cover_styles_e2e.py` | **OK, RC=0**, failures=[], console_errors=[] | Implementation-loop §115 подтверждён |
| 14 | Browser (НЕЗАВИСИМО, Playwright MCP) | свой stub-сервер (127.0.0.1:8798, статика web/ + серверные стабы cover-API, TMA server-side; БЕЗ route-interception Builder'а) + реальные клики | **§107** management screen: «Стиль этого чата» (селектор + Применить), «Мои стили» карточками (Пример-бейдж, референсов:1, Открыть/⋯), «Без дополнительного стиля» — selection state; **§108** dedicated full-screen overlay (`.cover-overlay` teleport, ← Закрыть); **§109** «Модель и подключение»/collapse; **§110** Before→After рендер **256×256px** (≥200px) + подписи «Базовая обложка → После стиля»; **§111** ref-card «Медведь Press/Логотип издательства»; **§112** two-step: «Создать и продолжить» (disabled до имени) → full-editor с активными file-inputs референсов (нет dead-end «Сначала сохраните стиль»); **§113** ровно 1 «Сохранить стиль» в футере оверлея; глобальный sticky-save перекрыт оверлеем (elementFromPoint → DIV.cover-overlay) и disabled; save e2e: dirty→enable→POST→toast «Стиль сохранён»; **§114** mobile 390×844: full-screen, БЕЗ horizontal overflow, Save полностью в вьюпорте (y=794+38≤844), футер с safe-area (padding-bottom 12px+env), весь контент скроллится выше футера (scroller 58–782, max-scroll 412/412); Test Style unconfigured → «Настроить подключение» (§126); console errors **0**; скриншоты `rev_mgmt_desktop.png`, `rev_editor_desktop.png`, `rev_editor_mobile.png` в каталоге фичи | UI-редизайн подтверждён независимо на stub-данных. **Production authenticated acceptance (§116–§119/§130 20 пунктов, §133) на real backend НЕ выполнялась** — недоступна в контуре ревью; честно остаётся за T-4227/T-4232/T-4234+ (DevOps). По инструкции Orchestrator — не блокёр для код-гейта |
| 15 | R17 секреты | скан всех added-строк `git diff` + 12 untracked py | **CLEAN** (sk-/xox/ghp/AKIA/PRIVATE KEY/tg-token/assigned-secret/bearer — 0; в стабах только маски «sk-…xy») | ✓ |
| 16 | Байт-гигиена | hex-дампы + round-trip cp1251→utf-8 по 78 файлам | `summary_fact_package.py` — mojibake (107+ строк, вкл. 3 runtime-сайта); conftest.py — content-clean, FULL-CRLF; ~28 тест-файлов + settings.py + llm_client.py — FULL-CRLF (контент чист); остальные файлы чистые | **H-ASAP32-1**; CRLF-шум — L-ASAP32-3 |

## Requirement/evidence coverage

D1–D14 все проверены на коде+тестах (таблица выше); spec §0–§135 трассирован через tasks T-4191…T-4233 → диффы. Заявленные Builder'ом счётчики (10316/2, 57+45, JS 52/52, F8 488, E2E OK) — воспроизведены. Заявление «Set-Content … восстановлено» для `summary_fact_package.py` — **опровергнуто** (см. H-ASAP32-1); заявление BOM-free — верно, но недостаточно.

## Focused audit coverage

Интеграционные кромки: single-writer (3 commit'а graphrag_rebuild внутри `serialized()` — allowlist mca01 обновлён корректно); CAS-переходы и takeover stale-running (600с); resume-семантика checkpoint (identity из coalesce_key); KNN-gate vs shadow; httpx.Timeout ↔ wait_for-дедлайн совместимость; asset blob-флоу и initData-зависимость (production initData присутствует — не дефект); Vue-редукция без ошибок консоли.

## Counterexamples checked (контрпримеры)

1. «UPDATE active без provenance» — единственный writer `_activate` после критериев 1–8; альтернативных writers нет (grep). ✗ не воспроизведён.
2. «Fallback при RUNNING primary» — guard `primary_running` + тест D. ✗
3. «Silent drop в редукции» — `unique_dropped` вычисляется set-difference; paged L2 вместо drop; тесты §72/§39. ✗
4. «Второй LLM-call на emoji/decision» — парсинг того же вызова; тесты ассертят 1 вызов. ✗
5. «Recompose-дыра на каком-то пути» — все 4 пути прокрыты (generate/generate_chat/tool_loop rounds/FR-15; plain-ветка Direct передаёт adapter). ✗
6. «Невалидная реакция/JSON уходит пользователю» — INVALID-sentinel + allowed-set + deterministic fallback. ✗
7. «Seed воскрешает удалённое» — прямой is_deleted-чек до создания. ✗
8. «Non-admin мутирует seeded прямым API» — requires_global_admin на всех мутациях + контракт-тест 403. ✗
9. «Глобальный Save конкурирует с editor» — перекрыт opaque-оверлеем + disabled (измерено). ✗
10. «fp меняется между validate и activate» — **воспроизводим концептуально** (hot-конфиг embedding): регистр получит active-строку старого fp, НО read-gate (`fingerprint==current`) не отдаст векторы → FTS-only, self-heal на следующем startup-schedule → M-ASAP32-2 (non-blocking hardening: re-check fp внутри транзакции активации).

## Findings

### Blocking

- **[H-ASAP32-1] [High, blocking] Mojibake (двойное UTF-8-кодирование) в runtime-строках `services/summary_fact_package.py` — контент-коррапция нормального Summary-пути.**
  - **Локация/доказательство (hex, неоспоримо):** строка 84 `FALLBACK_TOPIC_NAME = "РћР±С‰РёР№ С…РѕРґ РѕР±СЃСѓР¶РґРµРЅРёСЏ"` (байты `d0a0 d19b …` = CP1251-рендер UTF-8 «Общий…», корректные байты `d0 9e d0 b1 …` в файле ОТСУТСТВУЮТ); строка 118 `DESCRIPTION_SEPARATOR = " В· "` (байты `20 d092 c2b7 20` вместо `20 c2b7 20`); строка 279 `cut.rstrip(" В·")`; плюс ~23 docstring и ~32 комментария/строк файла с тем же классом повреждения (107+ строк всего).
  - **Свежий импорт без байткод-кеша** (`python -B`, reload) возвращает повреждённые константы — устаревший `__pycache__` маскировал дефект при разработке (та самая «stale-bytecode ловушка» из evidence §8).
  - **Нарушенные требования:** §96 (description = детерминированная агрегация), §40/§42 (lossless, без искажения контента), §133-дух честности; D8 — subject самой зоны 4.
  - **Impact:** (а) NORMAL-путь: каждая тема с >1 фактом получает description с мусорным разделителем «В·» (Cyrillic Ve + middle dot) → загрязнение L2-промпта/статьи на каждом саммари; (б) fallback-путь (L1 unusable, LEVEL-2 — контур инцидента ASAP-3.1): имя темы пакета «Общий ход обсуждения» — mojibake → пользовательский артефакт. Тесты НЕ ловят: единственный покрывающий тест сплитит ПО САМОЙ константе (тавтология), литералы нигде не ассертятся.
  - **Contradiction с evidence.md (Pass 2 §7):** «PowerShell Set-Content дважды портил UTF-8 (BOM/CRLF) в conftest.py/summary_fact_package.py — восстановлено; финальные файлы BOM-free» — восстановление НЕПОЛНОЕ; формулировка вводит в заблуждение (BOM-free ≠ контент-целостность).
  - **Corrective action (точное):** (1) байт-уровневый ремонт `services/summary_fact_package.py`: для каждого повреждённого фрагмента `fragment.encode('cp1251').decode('utf-8')` (минимум L84, L118, L279 + docstrings/комментарии; контрольный скрипт — round-trip по всем строкам должен дать 0); (2) добавить НЕтавтологический тест: `assert FALLBACK_TOPIC_NAME == 'Общий ход обсуждения'` и `assert DESCRIPTION_SEPARATOR == ' · '`; (3) прогон с очищенным `__pycache__`: `tests/test_summary_fact_package.py`, `tests/test_summary_semantic_reduction_asap32.py`, `tests/test_l2_budget_asap31.py`, `-k summary`, затем полный pytest (ожидание 10316/2+1 новый тест).
  - **Verification Reviewer:** hex-check + свежий импорт + прогон suites (WTH пересчитан после фикса).

### Non-blocking

- **[M-ASAP32-2] [Medium, non-blocking] Race-окно validate→activate в `graphrag_rebuild.py`:** criterion-1 (fp==current) проверяется в `_validate`, но НЕ перепроверяется внутри транзакции `_activate`; hot-изменение embedding-конфига в миллисекундном окне активирует генерацию старого fp. Функционально безопасно: read-gate требует fingerprint==current → векторы не обслуживаются, FTS работает; self-heal при следующем startup-schedule. Рекомендация: re-check `memory._identity_fingerprint() == fp` первой строкой `_body` (дешёво, закрывает окно полностью).
- **[L-ASAP32-1]** `maybe_media_fallback`: recompile промпта = тупой `prompt[:limit]` вместо компилятора под capabilities fallback-модели; активен только при настроенном `IMAGE_FALLBACK_*` (default off → поведение прежнее).
- **[L-ASAP32-2]** `reduce_threads` работает на shallow-копиях (`dict(thread)`): `setdefault("chronology"/"evidence_ids", …).append` может мутировать списки входа вопреки докстрингу «Вход НЕ мутируется»; в рамках одного run FactPackage вход далее не переиспользуется, метрики считаны до мутации — на результат не влияет.
- **[L-ASAP32-3]** FULL-CRLF перезапись ~30 файлов (settings.py, llm_client.py, conftest.py, ~28 тестов) — шум diff'а (осадок Set-Content-инцидента), runtime-эффекта нет; content-clean.
- **[L-ASAP32-4]** Мобильные тач-таргеты кнопок редактора 32–38px (<44px гайда); §117 не задаёт порог — косметический долг.
- **[L-ASAP32-5]** Doc-drift: tasks.md текущий hash C4BF1E24… vs E7293237… (Pass-2 старт) — чекбоксы T-4229/T-4231; binding-пара spec/ADR совпадает байт-в-байт. Плюс: dry-run merge (`summary_test_run`) не переносит `finale` объединённого документа (live-путь переносит) — косметика dry-run.

## Счётчики

- pytest полный: **10316 passed / 2 failed** (оба — чужие якорные forbidden-paths vs старый baseline web/-диффа; имена выше; воспроизведены с очищенным `__pycache__`).
- Новые наборы: Pass-1 **57/57**; Pass-2 **45/45**.
- JS: **52/52**. F8: **CHECK OK 488** (Δ каталога = 0). SQLite: **v19** (v20-бронь mca-04b цела). PG: **+1 таблица** (санкция D14).
- UI E2E Builder: **OK RC=0**. Независимый браузер: **PASS** на stub (0 console errors).
- R17 секреты: **CLEAN** (unstaged diff + untracked).
- Findings: **Critical 0 / High 1 (blocking) / Medium 1 (non-blocking) / Low 5**.

## Browser статус

- **Выполнено независимо (Playwright MCP, stub-данные):** §107/§108/§109/§110 (256×256)/§111/§112/§113/§114 + §126 unconfigured-ветка; desktop 1280×900 + mobile 390×844; скриншоты в каталоге фичи (`rev_*.png`); console 0 ошибок. Builder'овский stub-backend признан достаточным для implementation-loop §115 и геометрии §106–§114.
- **Unavailable (честно):** authenticated E2E против real FastAPI+PostgreSQL+managed assets (§116 27-шаговый сценарий, §117, §118, §119, §130 — 20 пунктов, §133) — контур real-backend в ревью недоступен; это обязательный production-acceptance гейт DevOps (T-4227/T-4232), НЕ закрытый ни Builder'ом, ни данным ревью. Никаких «production accepted» claims на этом основании не делается.
- **Unavailable (live):** NanoGPT async image contract live-ключом (§16/T-4195 — код честно держит sync-only), платные image/embedding вызовы (§76), полный GraphRAG rebuild на проде (§77/§85/T-4235), live Summary/Direct acceptance (§78/§79/T-4236).

## Staging-перечень для DevOps (deploy 2.58.40 — смешанные файлы)

1. **Backend-ядро:** `services/summary_generator.py`, `services/summary_fact_package.py` (+обязательный фикс H-ASAP32-1 ДО деплоя), `services/summary_semantic_reduction.py` (новый), `services/summary_memory.py`, `services/summary_test_run.py`, `services/llm_client.py`, `services/tool_loop.py`, `services/direct_chat_service.py`, `services/direct_llm_react.py`.
2. **GraphRAG/Media/Capacity:** `services/graphrag_rebuild.py` (новый), `services/media_execution.py` (новый), `services/image_generation.py`, `services/image_capabilities.py`, `services/cover_style_edit.py`, `services/cover_style_jobs.py`, `services/model_capacity.py`, `services/mca_retrieval_context.py` (без диффа — зависит от id_of), `services/param_catalog.py`.
3. **EXTRA/storage:** `services/pg_db.py` (PG-DDL +1 таблица `cover_style_connections` — идемпотентный; проверить применение на staging PG), `services/cover_style_registry.py`, `services/cover_style_pipeline.py`, `services/model_capacity.py`, `web/api/cover_styles.py`, `web/api/routes.py`.
4. **Запуск/конфиг:** `bot.py` (media bind_db + recover_media_jobs + seed ensure — порядок после `db.initialize()`), `config/settings.py` (APP_VERSION 2.58.40; 18 env-only ClassVar — все default ON/OFF-паритет).
5. **Frontend:** `web/index.html`, `web/app.js`, `web/static/app.css` (+UI-редизайн, один Save, teleport-оверлей).
6. **Тесты/инфра:** `pytest.ini` (+маркер asap32), `tests/conftest.py` (autouse-флаги), ~30 обновлённых якорей, 8 новых тест-файлов, `tools/ui_asap32_cover_styles_e2e.py`.
7. **Доки:** `README.md`, `plans/docs/param-registry-round1025.{meta.md,tsv}` (F8 488, hidden-ключ), `plans/docs/screen-map-round1025.md`, `plans/archive/extra-cover-style-pipeline-round1029/deployment.md` (erratum §123).
8. **Env-проверки после деплоя:** новые kill-switches дефолтны (MEDIA_EXECUTION_POLICY_ENABLED/GRAPHRAG_SHADOW_REBUILD_ENABLED/SUMMARY_SEMANTIC_REDUCTION_ENABLED/DIRECT_LLM_DECISION_ENABLED = ON; IMAGE_FALLBACK_* пусто = fallback выключен); первый startup должен засеять medved_press (идемпотентно) и поднять media-recovery; наблюдать `EMBEDDING_GENERATION_*` и отсутствие WARNING-спама `not serviceable`.
9. **Наглядно:** GraphRAG rebuild на проде (~2 млн фактов) — запускать по §85/T-4235 (resumable, фоново, FTS live); наблюдать checkpoint/PROGRESS до активации.

## Оценка отклонений Builder (все — легитимны)

1. Якоря D11 обновлены по санкции ✓ (SILENT-JSON mock, 1 вызов, OFF-паритет сохранён).
2. Plain-text REPLY = сознательная отправка ✓ (прямо следует из §52 спека: «REPLY отвечает текстом в том же вызове»); битая JSON — sentinel, не отправляется (усиление).
3. read/select → access, мутации → global-admin ✓ (соответствует §135: три раздельные возможности; дефолт «системное admin-only» без обходных путей; делегируемая гранулярность не вводилась — допустимо).
4. PG-DDL 51→52 — санкция D14/§104, Δ-лист в evidence и pg_db ✓.
5. UI E2E на stub-backend ✓ как implementation-loop §115; production acceptance честно не заявлена (передана T-4227/T-4232) — соответствует §133.
6. AST-гвард исключение generate/generate_image_verbose ✓ — санкция ADR-1028-5 D5 (Accepted), прецедент A5 того же гварда; провайдер-канон `_generate_post/_generate_get` не менялся.
7. Typed reranker positional fix вне ТЗ ✓ — легитимен, покрыт тестом, call-site-локален, объясняет прод-симптом.
8. **НЕ подтверждено:** «Set-Content … восстановлено» для summary_fact_package.py → H-ASAP32-1.

## MEMORY_DELTA

Не требуется (OpenViking/legacy-memory не использовались — авторитетные артефакты проекта полны; конфликтов memory↔артефакты не обнаружено).

## Handoff

@Orchestrator: маршрут **review → build** — исправить H-ASAP32-1 (байт-ремонт + нетавтологический тест + чистый прогон), опционально M-ASAP32-2 (одна строка re-check в `_activate`); затем re-check @Reviewer (новый WTH), после — DevOps (T-4234+, staging-перечень выше) и production acceptance T-4227 (§130 20 пунктов) на real backend.

---

## Round 2 (01.10.2026) — точечная ревалидация: только фикс H-ASAP32-1 (+ закрыт M-ASAP32-2); остальное Round 1 в силе

### Binding (Round 2)

- **Reviewed-Commit:** `1287130b8f88dd9809ae440e2e7859af139e1de0` (HEAD не изменился с Round 1).
- **Working-Tree-Hash:** `0f6e0f5fddc229c6fe626d663fb7e5cf7f16097dca045400deec3a5ae384bfa6` = SHA-256 LF-нормализованного контента `plans/reports/asap32_wth_manifest_review.txt` (уточнённый рецепт Builder'а, evidence §246); воспроизведён независимо, идемпотентен (двойной прогон — байт-в-байт).
- **Spec-Hash:** `E0F752CBAABF932011C77166BA6FF0465865AE718671D311B5571BDE7FA878AA` ✓ не изменён; `plans/current_task.md` `E828A092…B6750A` ✓ не изменён (R17).
- **Стейдж:** пустой (`git diff --cached` = 0). review.md исключён из манифеста (самореференц) — данное обновление отчёта WTH не инвалидирует.

### Проверки Round 2 (команда/метод → факт → вывод)

| # | Проверка | Факт | Вывод |
|---|---|---|---|
| 1 | Hex-чистота `services/summary_fact_package.py` | Сигнатуры повреждений: `d0 92 c2 b7` = 0; `c3 92` = 0; `ef bf bd` = 0; повреждённый сепаратор `20 d092 c2b7 20` = 0. Корректные байты: сепаратор `20 c2 b7 20` = 1 (site L118), префикс «Об» `d0 9e d0 b1` = 4. Round-trip-детектор cp1251→utf-8 (с учётом 0x98-дыры) по всему файлу: **0 строк** (до фикса — 221); U+FFFD: 0; BOM: нет | **H-ASAP32-1 закрыт** на байт-уровне |
| 2 | Runtime-литералы | AST-литерал `FALLBACK_TOPIC_NAME` = кодпоинты `0x41E 0x431 0x449 0x438 0x439 0x20 0x445 0x43E 0x434 0x20 0x43E 0x431 0x441 0x443 0x436 0x434 0x435 0x43D 0x438 0x44F` = «Общий ход обсуждения» ✓; `DESCRIPTION_SEPARATOR` = `[0x20, 0xB7, 0x20]` = « · » ✓; сайт `rstrip(" ·")` (L279) корректен | Оба runtime-сайта из Round 1 восстановлены точно |
| 3 | ASCII-проекция кода | AST парсится; все идентификаторы (Name/Attribute/FunctionDef/ClassDef) — ASCII: 0 не-ASCII; файл 59652 байт | Структура кода не тронута (заявление Builder'а подтверждено) |
| 4 | Нетавтологичность `TestSourceEncodingIntegrity` (tests/test_summary_fact_package.py:662–691) | 3 теста ассертят против литералов, записанных В САМОМ тесте («Общий ход обсуждения», `" · "`), + кодпоинт-проверки (первый символ 0x041E, sep[1]==0xB7, len==3), + явное неравенство повреждённому варианту « В· », + байт-аудит исходника (3 сигнатуры) + round-trip-детектор с 0x98-обработкой. Хелпер `_mojibake_lines` корректен | Нетавтологичен: тавтология исключена конструктивно |
| 5 | Чувствительность теста (temp-копия) | Воспроизведён pre-fix: повреждённая копия модуля (двойное UTF-8 с 0x98-маппингом — 223 повреждённые строки, сигнатура `d0 92 c2 b7` присутствует); тест-копия с перенаправленным импортом: **3/3 FAILED** на повреждённой; контроль на чистой копии: **3/3 PASSED** (подмена импорта сама по себе тесты не ломает) | Тест действительно ловит регрессию, а не проходит всегда |
| 6 | M-ASAP32-2 fp-recheck | `graphrag_rebuild.py:474–478` — re-check `memory._identity_fingerprint() != fp` ПЕРВОЙ операцией `_body`; `_body` исполняется внутри `memory.db.write_transaction` (L508–509); `RuntimeError("fingerprint_changed")` → except → `False` → run_job: `failed/activation_failed, terminal=True` (L689–696) | Фикс на месте и в правильном месте (внутри транзакции активации) |
| 7 | M-ASAP32-2 поведенчески (стаб write_transaction, транзакционный DDL) | mismatch: activate=False, live НЕ тронута (маркерная строка «unknown» цела), shadow цела, поколение остаётся building — 4/4; match: activate=True, копия с анти-orphan (2 строки, orphan-77 отброшен), shadow удалена, поколение active — 4/4. Итого **8/8** | Окно validate→activate закрыто: side effects при смене fp отсутствуют |
| 8 | Полный pytest (`.venv`, `__pycache__` очищен) | **10319 passed / 2 failed** — оба fail ровно те же чужие якорные forbidden-paths (`test_tool_coordinator_round1026.py::TestBounds::test_forbidden_paths_out_of_diff`, `test_unified_image_request_round1026.py::TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline`), что и в Round 1; 4:25 | Совпадает с ожиданием и evidence Builder'а |
| 9 | Целевой тест-файл | `tests/test_summary_fact_package.py`: **56 passed** (вкл. 3 новых TestSourceEncodingIntegrity) | ✓ |
| 10 | `-k summary` | **1179 passed / 0 failed** | ✓ |
| 11 | WTH-манифест: пофайловый аудит | 336/336 записей: файл существует, SHA-256 совпадает с живым деревом (0 mismatch, 0 missing); HEAD/staged/tracked-modified-count (79) в заголовке сходятся; полнота: 0 непокрытых untracked (манифест — супермножество: включает git-игнорируемые `.playwright-mcp/*.log` — безвредно) | Манифест честно покрывает живое состояние |
| 12 | WTH-манифест: агрегат git-diff | Агрегатный хеш `git diff HEAD` в заголовке (06e4466b…, 485424 B) ≠ живой (adb04baa…, 484865 B). Атрибуция полная: единственный tracked-файл, изменённый ПОСЛЕ записи манифеста — `plans/workflow_state.md` (mtime 08:21:30 vs манифест 08:18:43; mtime-скан других кандидатов — 0); арифметика сходится: всё-остальное 477569 B + старый checkpoint-блок 7855 B = 485424 B; текущий diff файла = machine-checkpoint Orchestrator'а (маршрутизация Round 2), 0 строк кода фичи | Дрейф — чужая бухгалтерия (Orchestrator), фичу не затрагивает; все файлы фичи — untracked и покрыты per-file хешами. Учёт при релизе: DevOps переизмеряет binding на commit-моменте (прецедент wave-1027) |
| 13 | Секреты (R17, дельта Round 2) | Изменённые зоны фикса: только литералы/строки `summary_fact_package.py`, тест-класс, 1 hunk `graphrag_rebuild.py` — секретов нет; new WTH-манифест секретов не содержит (только хеши) | CLEAN |

### Контрпримеры Round 2

1. «Тест тавтологичен (сплит по самой константе)» — ассерты против тест-локальных литералов + кодпоинты; воспроизведение pre-fix валит 3/3. ✗
2. «Фикс сломал rich/cover-путь» — первоначальные 5 fail в `-k summary` воспроизведены, НО A/B с pre-fix-эквивалентом модуля (import-hook) даёт те же 5 fail → причина не в фиксе; реальная причина: запуск НЕ тем интерпретатором (см. N2). ✗
3. «fp-recheck ломает штатную активацию» — контрольный сценарий match: полная активация 4/4. ✗
4. «Манифест потерял файлы после фикса» — 336/336 хешей сходятся, полнота 0 непокрытых. ✗
5. «WTH невоспроизводим» — воспроизведён независимо + идемпотентен. ✗

### Findings Round 2

**Blocking: нет.**

**Non-blocking (к регистратуре):**

- **[N-ASAP32-6] [Low] Тестовая дыра: окно validate→activate GraphRAG не покрыто выделенным тестом.** Существующий `test_config_change_mid_build_blocks_activation` покрывает смену fp ДО validate; фикс M-ASAP32-2 (re-check внутри `_activate`) поведенчески верифицирован ревьюером (8/8 на стабе), но регрессионного теста на само окно нет. Рекомендация: follow-up тест (fp-патч между validate и activate → activation_failed, shadow цел). Не блокёр: фикс одноточечный и верифицирован.
- **[N-ASAP32-7] [Low, окружение] Глобальный интерпретатор Python имеет aiogram 3.29.1 < пола requirements (`aiogram>=3.31.0,<4`)** → вне `.venv` rich/cover-тесты (5 шт.: TestRichDelivery×3, publish-integration L2-rich, asap2-failsoft T-3959-10) падают с ImportError `InputRichMessageMedia` → downgrade rich→plain. `.venv` (3.31.0) — корректен; продукт не затронут (деплой идёт из venv). Рекомендация: ран/CI-документы фиксируют использование `.venv`; глобальный python для прогонов не использовать.
- **[N-ASAP32-8] [Low, процесс] WTH-манифест: агрегатный git-diff-хеш дрейфует от любого tracked-изменения после снапшота** (демонстрировано на `plans/workflow_state.md`); per-file покрытие — только untracked. Ожидаемое свойство рецепта; компенсируется переизмерением binding на commit-моменте (T-deploy). Действий нет.

**Статус Round-1 findings:** H-ASAP32-1 — **RESOLVED** (пункты 1–3 таблицы); M-ASAP32-2 — **RESOLVED** (пункты 6–7); L-ASAP32-1…5 — в силе без изменений (вне скоупа Round 2).

### Счётчики Round 2

- pytest полный (`.venv`, чистый `__pycache__`): **10319 passed / 2 failed** (2 — известные чужие якорные).
- `tests/test_summary_fact_package.py`: **56 passed**. `-k summary`: **1179 passed / 0 failed**.
- Sensitivity: pre-fix temp-копия → **3/3 FAILED**, контроль → **3/3 PASSED**.
- M-ASAP32-2 behavioral: **8/8 PASS**.
- WTH: `0f6e0f5fddc229c6fe626d663fb7e5cf7f16097dca045400deec3a5ae384bfa6` — воспроизведён, идемпотентен; манифест 336/336 пофайлово.
- Findings: **Critical 0 / High 0 / Medium 0 / Low 3 (новые N-6…N-8)**.

### Unavailable checks (Round 2)

- Без изменений с Round 1: authenticated production-acceptance (§116–§119/§130/§133) и live-контур (NanoGPT live, платные embedding/image, полный GraphRAG rebuild на проде) — остаются за DevOps T-4227/T-4232…T-4236. К Round 2 не относятся (фикс байт-уровня + 1 строка guard'а).

### MEMORY_DELTA

Не требуется (OpenViking/legacy-memory не использовались; конфликтов memory↔артефакты не обнаружено).

### Handoff Round 2

@Orchestrator: **Approved for release** (код-гейт). Binding: HEAD `1287130b`, WTH `0f6e0f5f…4bfa6`, Spec `E0F752CB…`. Далее — DevOps: T-4234+ (staging-перечень Round 1 §Staging; `summary_fact_package.py` деплоится УЖЕ БЕЗ оговорки «+обязательный фикс»), затем production acceptance T-4227 (§130, 20 пунктов). N-ASAP32-6/7/8 — в `audit_backlog` как bounded follow-up, релизу не мешают.
