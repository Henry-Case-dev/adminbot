# evidence.md — `mca-05-episodes-stories` (Step 3 @Builder, 01.10.2026)

## 0. Binding и базис

- **Binding-хэши (проверены при старте Build, Get-FileHash SHA-256):**
  - `spec.md` — `8177CB0FF3FCEFE5168A82A52690DEB66B0DB8990DA2F047861E342EAE6E9EC0` ✅ (совпал с пином Orchestrator/§11 tasks.md);
  - `adr-1027-12-episodes-stories.md` — `2E7E110B1E2058366C6DD489DD02666988318227C6653F1251615DA0CBB4FC50` ✅;
  - `tasks.md` (на момент старта) — `7564147C0768E68560A2B50F497664EB13861DBFB0393F9DD26E6A70C5133718` ✅ (пин `7564147C…3718` совпал; далее файл изменён только чекбоксами T-4249…T-4270/T-4272 + §12 Build-блок, см. §6).
  - `plans/current_task.md` НЕ изменялся (не открывался на запись; изменения в `git status` по нему отсутствуют).
- **Базис Build:** HEAD **`0b1ae9c`** (`git rev-parse` подтверждён в начале сессии) = прод-паритет 2.58.41, SQLite DDL v20, каталог 488/427/463/105/103/21.
- **Текущее состояние worktree:** без коммитов (R18); все изменения unstaged/untracked; прод не писался; чужой WIP (`plans/docs/mca-round1027-arch-frames.md`, `plans/metrics.md`, `plans/workflow_state.md` — модифицированы ДО начала сессии Orchestrator'ом/PM; `node_modules/`, `extra_images/`, `package*.json`, `.playwright-mcp/`) — не тронут.
- **Runtime:** Python 3.12.0 (`.venv`), Windows, pytest без cacheprovider.

## 1. Изменённые/новые файлы (полный манифест для Reviewer)

**Новые (прод-код):**
- `services/mca_episodes.py` — EpisodeService: EpisodeRepository (весь SQL v21), детерминированная сегментация (`segment_messages`/`dedup_segments`/`split_by_participant_clusters`/`segment_key`), сборка (компоненты по confirmed-связям, `merge_claims`/`detect_contradictions`), provenance (`record_episode_provenance`/`record_story_provenance`/`validate_story_sources`), события (`emit_story_event`/`emit_pipeline_stage` — post-commit), фасад (`list_stories_for_retrieval`/`resolve_story_id`/`build_local_context`/`note_compiler_touch`/`queue_source_recheck`), версии/CAS (`upsert_story`/`update_story_manual`/`StaleUpdateError`/`merge_stories`).
- `services/mca_episode_prompts.py` — канон `episodes_extract-1`/`continuation_confirm-1`, строгие парсеры, офлайн-валидаторы (`validate_extract_payload` — unknown не превращается в факт; `validate_confirm_payload` — fail-closed; `is_continuation_candidate` — участники+сущность+время).
- `services/mca_episode_jobs.py` — `enqueue_episodes_backfill` (coalesce `episodes.backfill:<chat_id>`), `EpisodesBackfillRunner` (keyset `(timestamp,id)`, checkpoint после фиксации, `paused` при LLM-ошибке — никогда ложный completed; `process_rechecks`).
- `tests/test_mca05_episodes_stories_round1027.py` — 59 тестов (ниже).
- `plans/features/mca-05-episodes-stories/evidence.md` — этот файл.

**Изменённые (прод-код):**
- `services/database.py` — v21: константы `_SCHEMA_VERSION_EPISODES_STORIES=21`, DDL 7 таблиц (`mca_episodes`/`mca_stories`/`mca_story_versions`/`mca_story_episode_links`/`mca_story_continuations`/`mca_story_redirects`/`mca_story_legacy_links`), 6 индексов, `_MCA_STORIES_OVERRIDE_COLUMNS` (5 nullable ALTER под guard), закрытые наборы (`EPISODE_STORY_STATES`/`EPISODE_MAPPING_STATUSES`/`EPISODE_CONTINUATION_STATUSES`), `_migrate_episodes_stories_v21` (self-guard sqlite_master/PRAGMA table_info; повтор no-op; PG no-op), запись в `migration_steps()`; 4 новых прямых commit (учтены в аудит-тесте mca-01: 137→141, L-MCA14-3).
- `services/mca_gates.py` — `KILL_SWITCHES` +4 (`MCA_EPISODES_ENABLED`/`_BACKFILL_`/`_CONTINUATION_`/`_COMPILER_FACADE_`, default ON с OFF-семантикой); гейты `episodes_enabled`/`episodes_backfill_enabled` (инертен при master)/`episodes_continuation_enabled`/`episodes_compiler_facade_enabled`/`episodes_batch_max_messages` (500)/`episodes_direct_priority_enabled`.
- `config/settings.py` — те же 4 ClassVar + 2 env-лимита (`MCA_EPISODES_BATCH_MAX_MESSAGES=500`, `MCA_EPISODES_DIRECT_PRIORITY_ENABLED=True`); **APP_VERSION 2.58.41→2.58.42** (release mechanics, комментарий с составом фичи и откатом).
- `services/mca_events.py` — REASON_CODES +10 (финальный набор ADR-1027-12): `episode_extracted`, `story_segment_empty`, `story_continuation_confirmed`, `story_continuation_rejected`, `story_contradiction_found`, `story_legacy_unmapped`, `story_backfill_paused_budget`, `story_source_recheck_queued`, `story_merged`, `story_split`.
- `services/mca_process_registry.py` — процессы `episodes.build` (стадии segment/extract/confirm/assemble/link/index, widget «Эпизоды/lore», state_source task_jobs+mca_episodes, gate MCA_EPISODES_ENABLED, event_names включая витринные story_*) и `episodes.backfill` (gate MCA_EPISODES_BACKFILL_ENABLED); `_GATE_RESOLVERS` +4.
- `services/mca_retrieval_context.py` — AMEND `_episode_candidates`: при `episodes_compiler_facade_enabled()` читает `list_stories_for_retrieval` (excluded/rejected не выдаются, legacy-unmapped видимы), fail-open → legacy `list_lore_stories`; OFF-гейт = прежний путь.
- `services/direct_chat_service.py` — M-MCA07-2: в `_build_evidence_bundle` `local_context` наполняется `build_local_context(...)` (гейт master, fail-open → `()`).
- `services/lore_compiler_service.py` — после `upsert_lore_story` ленивый `note_compiler_touch` (гейт фасада, fail-open; инструмент `compile` не менял контракт).
- `services/message_identity.py` — `record_edit`: после успешной ревизии — `queue_source_recheck` (аддитивно, гейт mca-05, fail-open; очередь без каскада).

**Изменённые (тесты/доки, release mechanics):**
- 23 `tests/*.py` — ре-пин APP_VERSION 2.58.41→2.58.42; `tests/test_mca01_tx_task_supervisor_round1027.py` дополнительно: allowlist `database.py` 137→141 (+4 commit v21, комментарий); `tests/test_mca04b_dossier_rebuild_round1027.py`: v20-тест `user_version == 20` → `>= 20` (хвост реестра сдвинулся на v21); `tests/test_mca17a_observability_core_round1027.py`: сканер реальных имён событий дополнен паттерном `emit_story_event(` (обёртка витринных событий mca-05 — имена литеральные на call-site).
- 4 `tests/js/*_test.js` — ре-пин regex APP_VERSION 2.58.40→2.58.42 (чужой дрейф с ASAP-3.2: файлы не ре-пинились bump'ом 2.58.41 — 4 JS-теста падали и на baseline `0b1ae9c`; фиксация в рамках той же release-механики «version-pin re-pin»).
- `README.md` — версия v2.58.42 + блок mca-05; `plans/docs/param-registry-round1025.meta.md` — APP_VERSION 2.58.42.
- `plans/features/mca-05-episodes-stories/tasks.md` — чекбоксы [x] T-4249…T-4270/T-4272 + §12 Build-блок.

**Вне diff (Δ=0 подтверждено):** `param_catalog.py`, `pg_db.py`, `web/**` (каталог 488/427/463/105/103/21 не менялся; F8 NOT_APPLICABLE), `lore_stories` DDL/методы (`get/list/upsert_lore_story` — байт-в-байт прежние).

## 2. Прогоны (T-4268, FIN-R1)

| Прогон | Результат |
|---|---|
| Полный pytest (`python -m pytest tests -q -p no:cacheprovider`) | **10428 passed / 2 failed**, ~290 c |
| — 2 failed | `test_tool_coordinator_round1026.py::TestBounds::test_forbidden_paths_out_of_diff`, `test_unified_image_request_round1026.py::TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline` — **известные чужие bounds-тесты из анкера** (падают на diff-путях `web/` из чужого WIP; ни один файл `web/**` мной не менялся). Новых failed = 0. Δ к анкеру 10369/2 = **+59** (мой набор), failed-состав не расширился. |
| Фича-набор `tests/test_mca05_episodes_stories_round1027.py` | **59 passed** |
| JS unit (`test_webapp_js_unit.py`) | **36 passed** (после ре-пина js-пинов; до него 4 pre-existing падения — чужой дрейф, файлы `tests/js` не трогались mca-04b) |
| `git diff --check` | чист (exit=0 с `core.whitespace=...,cr-at-eol` — конвенция CRLF репо; дефолтный режим флагует `\r` каждой изменённой CRLF-строки, включая чужой WIP `plans/workflow_state.md:377/379`) |
| Δ каталога | 0 — `git diff --name-only` не содержит `param_catalog.py`/`web/**` |
| Смежные наборы | mca-01/03/04a/04b/07/13/14/17a + database — 392+ passed (после ре-пинов) |

## 3. Покрытие приёмок (T-4266/T-4267 — тест-карта)

`tests/test_mca05_episodes_stories_round1027.py` (59):
- **Миграция v21** (SC-20/A28): 7 таблиц + user_version=21 + книга; повторный `initialize()` — no-op; `lore_stories` с данными не тронуты; реестр упорядочен/бесконтекстен, хвост 21.
- **Kill-switch OFF-паритет** (SC-20, T-4249): master OFF → `process_batch` не пишет, enqueue бросает, под-гейты инертны; фасад-гейт OFF → канал на legacy-пути; 4 записи в `KILL_SWITCHES` default ON.
- **A11** (SC-03, T-4253): событие `T_2022` + discovered_at=`_NOW` — `event_start/end` из исходных сообщений, разница > 300 суток; карточка истории — те же две даты (без LLM).
- **A12** (SC-02/06/09, T-4254/T-4256): параллельные темы → multi_topic → сплит по кластерам участников → 2 истории; confirmed-продолжение через 7 дней склеивает (1 история, 2 эпизода, status=confirmed); rejected остаётся раздельным; кандидат-фильтр по событию (участники+сущность+окно 1ч..90д; дискрет-участники/тот же день/>90д — не кандидат).
- **A13** (SC-05, T-4252): ручная правка (title+state) + повторная сборка → override эффективен, 2+ версии (created_by pipeline/manual, снимок с overrides), no-op rebuild не плодит версии; CAS: stale → `StaleUpdateError`, значение не затёрто; merge → redirect резолвится, фасад скрывает источник, эпизоды не потеряны.
- **SC-04** (`unknown`): `outcome_known=false` → «исход неизвестен»; история `uncertain`; невалидный ответ модели → честный unknown, не факт.
- **SC-07** overlap: тот же сегмент-ключ при другом порядке; повтор окна → дублей нет; 50% overlap → дубль.
- **SC-08**: claim без валидного ref → переносится в unknown; участник вне подборки отбрасывается.
- **SC-10**: противоречие → verification=tentative, оба утверждения сохранены, событие contradiction_found (reason `story_contradiction_found`); repeat_count без роста независимости.
- **SC-11/§8.1** (T-4263): provenance ok при живом сообщении; `unknown` при несуществующем (валидатор существования); валидатор истории ok/unknown.
- **SC-12** (T-4258): coalescing (1 задача на чат); runner → completed с честными счётчиками; LLM-сбой → `paused`/`model_unavailable` (никогда ложный completed); рестарт без дублей (links==stories); revision → recheck=1 → перепроверка обновляет эпизод на месте, discovered_at не меняется; `record_edit` (mca-03) ставит recheck.
- **SC-13/SC-14** (T-4260/T-4261): legacy не склеивается автоматом (mapped=0), unmapped видимы; ленивый маппинг: без LLM → unmapped+событие `story_legacy_unmapped`; с confirm → mapped; отказ → unmapped; канал читает новый store (id=story_id), excluded не выдаются, fail-open при падении фасада; `local_context` наполняется/пусто=`()`; гейт OFF → `()`.
- **SC-15** (T-4262): события только после фиксации (провал транзакции → 0 историй/событий); payload события несёт обе даты + episode_ids; пустой сегмент → INFO `story_segment_empty`.
- **SC-17/SC-18** (T-4264/T-4265): +10 кодов в словаре; маскирование `sk-…` через sanitize; неизвестный reason_code отбрасывается; живой прогон пишет ≥2 стадийных события с pipeline_run_id.
- **SC-16 + границы** (T-4259/T-4267): grep-гейт — в mca_episodes/mca_episode_jobs/mca_episode_prompts нет `telegram_send|send_message|sendMessage|sendRichMessage|bot.send`; ASAP-3 — `direct_context_composer.py`/`model_slots.py` не импортируют mca_episodes; SC-16 — модуль не импортирует web/каталог (нет APIRouter/FastAPI/param_catalog); single-writer coexistence (параллельный alien-writer на write_transaction); chat-scope изоляция.
- **state ≠ job** (T-4251): `set_story_task_ref` не трогает `state` и наоборот; backfill `completed` не закрывает истории; story требует ≥1 эпизода.

## 4. Отклонения от spec/ADR (осознанные, без сужения контракта)

1. **Сплит много-топикового сегмента** — детерминированный по кластерам участников (reply-связность), по LLM-маркеру `multi_topic` из канона извлечения (D4 допускает тематическое суждение LLM внутри/между детерминированными сегментами; порядок/время LLM не меняет). Без LLM сплит не выдумывается.
2. **No-op rebuild не создаёт версию** — «повторная сборка создаёт новую версию» интерпретирована как change-driven (версия при фактическом изменении состава/полей; поля под override в сравнении не участвуют — пересборка их не меняет). A13-гарантии (обе версии доступны, override переживает) покрыты тестами.
3. **LLM-сбой в backfill → `paused`/`model_unavailable`** (не `failed`) — счётчик `errors` батча триггерит честную паузу; retry через requeue/рестарт с checkpoint (прецедент mca-04b D3: «ошибка → paused/failed, никогда ложный completed»).
4. **`validate_extract_payload` переносит claims без валидных refs в `unknown`** (не отбрасывает молча) — усиление §8.1-честности, дроп-счётчик `dropped_claims`.
5. **Сканер имён событий в тесте mca-17a дополнен** паттерном `emit_story_event(` — потому что витринные события эмитятся обёрткой с литеральными именами на call-site (инвариант теста «ни одно имя не выдумано» сохранён и усилен).
6. **Ре-пин 4 JS-тестов** (`tests/js/*`, regex 2.58.40→2.58.42) — чужой pre-existing дрейф (файлы не обновлялись bump'ами 2.58.41), устранён в рамках той же release-механики «version-pin re-pin», что и 23 py-пина.
7. **`update_story_manual` пишет и базовую колонку, и override-маркер** — единый источник значения для всех читателей; override остаётся маркером «пережить пересборку». Эффективное значение идентично.

## 5. Инварианты и роллбек

- **Δ каталога = 0**: `param_catalog.py` вне diff; kill-switches env-only ClassVar, default ON; в `KILL_SWITCHES` манифест внесены 4 записи (реестр «26+1» → «26+1+4 product mca-05»).
- **OFF = паритет baseline**: master OFF → новые пути неактивны (тест), фасад-гейт OFF → компилятор/канал как сегодня (тест).
- **Effective-state §20.2 «Эпизоды и истории — ON»** подтверждаем: `mca_gates.episodes_enabled()` (runtime, per-call) + `runtime_status(episodes.build, event_names_present=…)` реестра.
- **Rollback**: hot — `MCA_EPISODES_ENABLED=false` (все под-гейты инертны; legacy-путь `lore_stories`/компилятор/канал жив — тесты); cold — `git revert` базового коммита Build (v21 аддитивна, старый код её не читает; restore БД — аварийный сценарий).

## 6. Что НЕ сделано / осталось

- **T-4271** (Merge §108+, ADR-1027-12 → Accepted) — @Architect, вне зоны Builder.
- **Живой LLM-прогон** (опциональный офлайн-прогон выбранной модели из D5) — не выполнялся: в Build-среде нет LLM-провайдера; контракт проверен офлайн-валидаторами на фикстурах (санкция «опциональный»).
- **Прод-верификация/деплой** — `DEFERRED_TO_RELEASE` (T-4272); прод не писался.
- 2 известных чужих bounds-failed (см. §2) — вне зоны фичи, состав идентичен анкеру.

## 7. Чек-лист kill-switch/паритета (T-4269)

| Рубильник | Default | OFF-семантика | Тест |
|---|---|---|---|
| `MCA_EPISODES_ENABLED` | ON | весь новый контур неактивен (пайплайн/backfill/фасад/канал/local_context) | `test_master_off_no_pipeline_writes`, `test_local_context_gate_off` |
| `MCA_EPISODES_BACKFILL_ENABLED` | ON | backfill не ставится/не исполняется (инертен при master) | enqueue-RuntimeError; runner→cancelled |
| `MCA_EPISODES_CONTINUATION_ENABLED` | ON | кандидаты/подтверждения не строятся (склейки только вручную подтверждённые ранее) | гейт-функция + инертность при master |
| `MCA_EPISODES_COMPILER_FACADE_ENABLED` | ON | компилятор/mca-07 канал — legacy-путь | `test_facade_gate_off_legacy_channel_path` |
| `MCA_EPISODES_BATCH_MAX_MESSAGES` (лимит) | 500 | <1 → 500 | gate-функция |
| `MCA_EPISODES_DIRECT_PRIORITY_ENABLED` (лимит) | ON | без уступания direct-пути | gate-функция |

Все 4 рубильника внесены в `KILL_SWITCHES` (release-manifest список) с OFF-паритет описаниями; effective-state строка «Эпизоды и истории — ON» резолвится runtime через `mca_gates`.

## 8. Rework round 1 (по Reviewer gate NEEDS FIXES — `review.md` §5, 01.10.2026)

**Базис:** HEAD `0b1ae9c` (не изменился); работа поверх незакоммиченного состояния round 1 (staged = EMPTY проверен); без коммитов/деплоя.

### H-MCA05-1 (High) — split реализован

- **`services/mca_episodes.py:971–1210`** — новый `EpisodeRepository.split_story(source_id, episode_ids, *, extractor_version="", now=None) -> (new_story_id, ok)` (рядом с `merge_stories`):
  - отсоединение эпизодов: ссылки переносятся в новую историю; у источника удаляются `mca_story_episode_links` отделяемых эпизодов (`:1112`);
  - пересчёт оставшихся: источник получает новую версию (полный снимок, `expected_version+1`), карточка детерминированно пересчитана из оставшихся эпизодов теми же правилами, что `assemble_stories` (title/summary/участники/claims-merge/обе даты/outcome/state — `_card()`), override-колонки, `excluded_from_retrieval`, `discovered_at` не трогаются;
  - одиночный эпизод: сплит истории из 1 эпизода — no-op `(“”, False)` (отделять нечего); отделяются ВСЕ эпизоды — источник удалён (история ≥1 эпизода, §9.1) с redirect `story→новая` (spec (h)) и переездом mapped legacy-ссылок;
  - событие: post-commit `emit_story_event` — `story_discovered` (новая) + `story_rebuilt` (источник при частичном сплите), оба с `reason_code="story_split"` — мёртвый санкционированный код получил легитимного эмиттера; имена событий — из фиксированного набора §16.1 (контракт mca-12 не расширялся).
- **Тесты** (`tests/test_mca05_episodes_stories_round1027.py`, +3):
  - `:608` `test_split_story_three_episodes` — **контракт ревью**: 3 эпизода → 2 истории (1+2), обе `open`, redirect НЕ создан (`mca_story_redirects`=0, `resolve_story_id` — тождество), источник = новая версия 2 со снимком оставшихся (состав+даты), новая = версия 1, фасад видит обе, `reason_code='story_split'` в `mca_events` после flush;
  - `:650` `test_split_single_episode_story_noop` — история из 1 эпизода не сплитится (no-op: состав/версия/redirect/события не изменены); пустой и чужой список эпизодов — тоже no-op;
  - `:676` `test_split_all_episodes_redirects_source` — сплит всех эпизодов: источник удалён, redirect резолвится, фасад показывает только новую.

### M-MCA05-1 (Medium, requirement-blocking) — утечка excluded через фолбэк устранена

- **`services/mca_retrieval_context.py:581–607`** — `_episode_candidates` различает три состояния: (a) гейт OFF или (b) исключение фасада → санкционированный legacy-путь `list_lore_stories` (паритет baseline / fail-open mca-07); (c) фасад ответил (в т.ч. **честно пусто**) → ответ и есть результат — legacy-фолбэк на пустом успешном ответе запрещён (раньше excluded/rejected/redirected контент воскрешался через mapped-двойника в `lore_stories`).
- **Тест** `tests/test_mca05_episodes_stories_round1027.py:1281` `test_channel_no_leak_of_excluded_via_legacy_fallback` — **контракт ревью**: история + mapped-legacy двойник → до exclude канал отдаёт ровно `episode:<story_id>`; exclude → фасад пуст → **канал тоже пуст**; дополнительно redirect-ветка: merge источника в приёмник → виден только приёмник; исключённый приёмник → пусто (двойник redirect-источника не воскресает).
- **Адаптация теста mca-07** `tests/test_mca07_retrieval_context_round1027.py:302–329` — `_FakeDB` получил `_FakeFacadeShell` (минимальный `db.db`): legacy-эпизоды теперь приходят через фасад (`kind="legacy_story"`, SC-13), а не через устаревший фолбэк-путь — фейк приведён к пост-AMEND контракту канала. Прод-код mca-07 не менялся сверх `_episode_candidates`.

### Прогоны (rework)

| Прогон | Результат |
|---|---|
| Фича-набор `test_mca05_episodes_stories_round1027.py` | **63 passed** (59 + 4 новых) |
| Канал/смежные (mca-01/03/04b/07/13/14/17a) | **263 passed** (после адаптации фейка mca-07) |
| Полный pytest | **10432 passed / 2 failed** (~282 c) — Δ к анкеру round 1 (10428/2) = **+4** (новые тесты); 2 failed — те же известные чужие bounds (`web/` из чужого WIP), новых failed = 0 |
| JS (`test_webapp_js_unit.py` — гейт JS из review §6 п.3) | **36 passed** (JS-файлы в rework не менялись) |
| F8 `--check` | `CHECK OK: реестр 488 …` exit=0 (Δ каталога = 0) |
| `git diff --check` (`core.whitespace` c `cr-at-eol`, L5) | exit=0 |

### Binding rework-состояния

- **Новый WTH:** см. манифест `plans/reports/mca05_wth_manifest_rework1.txt` (рецепт review-манифеста: HEAD + SHA-256 `git diff HEAD` + per-file SHA-256; состав = 49 файлов round 1 + 1 новый скоуп-файл `tests/test_mca07_retrieval_context_round1027.py` = 50). WTH round 1 (`D98B3780…CCEA`) невалиден с момента rework — повторный Reviewer-гейт обязан перепривязаться к новому.
- Чужой WIP не тронут (`plans/workflow_state.md`, `plans/metrics.md`, `plans/docs/mca-round1027-arch-frames.md`, `web/**`, `package*`, `node_modules/`, `extra_images/`, `.playwright-mcp/`).
- Коммитов нет; прод не писался; deploy — `DEFERRED_TO_RELEASE`.
