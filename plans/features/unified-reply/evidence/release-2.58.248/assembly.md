# Сборка 2.58.248 — P0 (trigger/L1, media F1, media F2, пустые embeddings)

- **Роль:** Builder, локальная сборка. **Без deploy, merge в master, SSH и production.**
  Effective-state прода и post-deploy проверки — DevOps после выкладки; этот
  документ — вход для delta-ревью релизного кандидата.
- **База (production 2.58.247):** `f2cb38c8412506261504b4000f7a7a53be143851`.
- **Ветка:** `release/p0-2.58.248` от `f2cb38c84` в registered worktree
  (`WorkspaceData/worktrees/c742e4de9e92c489/release-p0-2-58-248-0901ccbafd5b-b3a7ac2d`,
  epic `release-p0-2.58.248`). Интеграция — линейные cherry-pick, **без merge-коммитов**.
- **Схема:** четыре независимо одобренных среза (`APPROVED_FOR_RELEASE_PREPARATION`).
  sha256 ревью воспроизведены с planning-checkout (`master`), потому что
  evidence-ревью живут в плановой линии и не входят в код-базу 2.58.247.

```json
{
  "release": "2.58.248",
  "base": {"sha": "f2cb38c8412506261504b4000f7a7a53be143851", "version": "2.58.247"},
  "slices": [
    {"id": "S1", "name": "trigger provenance + L1 autonomy", "branch": "fix/p0-trigger-force",
     "base": "f2cb38c8412506261504b4000f7a7a53be143851",
     "source_tip": "f6d7f4fc16c8c337daebbbfa7a9662bcfd1038ba",
     "product_commits": ["4e5374536", "bbc051fe9"],
     "evidence_commits": ["a40880161", "c7a8931a8", "f6d7f4fc1"],
     "review": {"r1": "plans/features/unified-reply/evidence/p0-trigger-force-review-r1.md",
                "r1_sha256": "b200acca8e959b106093dbd4b371952043ff08ffefe1c6488296723964a20960",
                "r1_verdict": "NEEDS_FIXES (consumer rename, исправлено bbc051fe9)",
                "r2": "plans/features/unified-reply/evidence/p0-trigger-force-review-r2.md",
                "r2_sha256": "3126cec35e29b1a02b532fccdbce4d1c77bd4a66fc4cc1f7ada752c9cf51bdfe",
                "hash_reproduced": true, "verdict": "APPROVED_FOR_RELEASE_PREPARATION"}},
    {"id": "S2", "name": "media F1 — own media = visual asset", "branch": "fix/p0-media-phantom-intent",
     "base": "4e5374536e45bcf97e9aa8544d68493fa2cbe6e0",
     "source_tip": "170f70e3f41940b76e11796cf2f89a40a554800e",
     "product_commits": ["e07fd5c32"], "evidence_commits": ["170f70e3f"],
     "review": {"file": "plans/features/unified-reply/evidence/p0-media-phantom-intent-review-r1.md",
                "sha256": "24528c4b26a99afea06f4d1fa9e5a3e0b06af92b24b584155d7c0433a7c7689e",
                "hash_reproduced": true, "verdict": "APPROVED_FOR_RELEASE_PREPARATION"}},
    {"id": "S3", "name": "media F2 — one binding per media message + author", "branch": "fix/p0-media-bind-f2",
     "base": "f2cb38c8412506261504b4000f7a7a53be143851",
     "source_tip": "6b8795d2699764812622867dd5dba831070ede51",
     "product_commits": ["6b8795d26"], "evidence_commits": ["6b8795d26 (тот же коммит)"],
     "review": {"file": "plans/features/unified-reply/evidence/p0-media-bind-f2-review-r1.md",
                "sha256": "dcfd9cbd7a97be01cf9e3701a25f52618cbc41a54c54f3882ec06e773ca5ab22",
                "hash_reproduced": true, "verdict": "APPROVED_FOR_RELEASE_PREPARATION"}},
    {"id": "S4", "name": "пустой текст — не запрос embedding", "branch": "fix/p0-embed-empty-input",
     "base": "f2cb38c8412506261504b4000f7a7a53be143851",
     "source_tip": "8298c79ba1fdd037d915b7a6b801b0976e902d47",
     "product_commits": ["7686d6fcd"], "evidence_commits": ["8298c79ba"],
     "review": {"file": "plans/features/smart-execution-reliability-01/evidence/p0-embed-empty-input-review-r1.md",
                "sha256": "4c46ab8d0926e81b01170088a97edb24088d35de174c87c27f86d41ec4e6b9b4",
                "hash_reproduced": true, "verdict": "APPROVED_FOR_RELEASE_PREPARATION"}}
  ],
  "integration": "linear cherry-pick: S1 (5), S2 (2), S3 (1), S4 (2), version wave (1)",
  "commits_above_base": 11,
  "delta_vs_base": {"files": 67, "insertions": 2450, "deletions": 274},
  "delta_by_area": {
    "services": {"files": 9}, "tests": {"files": 40}, "plans": {"files": 13},
    "config": {"files": 1}, "handlers": {"files": 1}, "web": {"files": 1}, "tools": {"files": 2}
  }
}
```

## 1. Порядок интеграции

| # | интеграционный SHA | источник | тип |
|---|---|---|---|
| 1 | `d44f6d80e` | S1 `4e5374536` | product (provenance/text + L1 autonomy) |
| 2 | `c105ba655` | S1 `a40880161` | evidence |
| 3 | `7e645bdca` | S1 `c7a8931a8` | evidence (session id) |
| 4 | `963cd1629` | S1 `bbc051fe9` | product (P0T-R1-F1: rename у потребителей) |
| 5 | `8de6cb2b4` | S1 `f6d7f4fc1` | evidence (r1 corrective) |
| 6 | `00f9e075c` | S2 `e07fd5c32` | product (media F1) |
| 7 | `d6d400889` | S2 `170f70e3f` | evidence |
| 8 | `05aa545eb` | S3 `6b8795d26` | product+evidence (media F2) |
| 9 | `aa185309c` | S4 `7686d6fcd` | product (empty-input embeddings) |
| 10 | `d2bc214b2` | S4 `8298c79ba` | evidence |
| 11 | `c3887d0cb` | — | version wave 2.58.248 |

Все cherry-pick прошли без конфликтов; ручных правок кода при сборке не
потребовалось. Порядок — ровно S1 → S2 → S3 → S4, как назначено (S2 ветвился
от первого коммита S1).

## 2. Собственные файлы срезов: побайтовая идентичность

Срезы затрагивают **35 файлов**: 34 принадлежат ровно одному срезу, один общий
(S1+S2). Проверка механическая (`git rev-parse HEAD:<path>` против tip'а среза):

- **35/35 файлов байт-в-байт равны blob'у своего срезового tip'а** (для общего
  файла — tip'у S2, который уже содержит изменения первого коммита S1).
- Ни один срезовый файл не попал в version wave, поэтому «только токен версии»
  расхождений здесь нет (в отличие от 2.58.247, где пины базы были в срезах).
- Общий файл разобран отдельно в §3.

| срез | файл | blob (12) |
|---|---|---|
| S1 | `handlers/direct_chat.py` | `6a8cf5ddd717` |
| S1 | `plans/features/unified-reply/evidence/p0-trigger-force-2026-11-26.md` | `f6da492a147f` |
| S1 | `services/agentic_events.py` | `425c89e9a9ea` |
| S1 | `services/command_prefix.py` | `af1ebb43d8b1` |
| **S1+S2** | **`services/direct_chat_service.py`** | **`dc1583af10bc`** |
| S1 | `services/direct_context_composer.py` | `e19f39ba4008` |
| S1 | `services/direct_l1.py` | `b50f4c7b1bf4` |
| S1 | `tests/test_asap7_direct_l1.py` | `e4b68cc752fd` |
| S1 | `tests/test_direct_chat.py` | `d574342c24d1` |
| S1 | `tests/test_direct_context_composer_asap3.py` | `a9ce83429ef1` |
| S1 | `tests/test_direct_decision_matrix_asap3.py` | `028ad0a97925` |
| S1 | `tests/test_direct_l1_corrective_r1.py` | `4c82a4d4b256` |
| S1 | `tests/test_direct_llm_decision_asap32.py` | `a32096cf15d5` |
| S1 | `tests/test_p0_trigger_force_l1.py` | `04d18bc6fc0a` |
| S1 | `tests/test_rlr_observability.py` | `89487c2c4207` |
| S1 | `tests/test_ur_turn_engine.py` | `30cf75112f78` |
| S1 | `web/app.js` | `9603469cb12d` |
| S2 | `plans/features/unified-reply/evidence/p0-media-phantom-intent-2026-11-26.md` | `e3321cb4fa15` |
| S2 | `tests/test_p0_media_phantom_intent.py` | `8da3b34326aa` |
| S3 | `plans/features/unified-reply/evidence/p0-media-bind-f2-2026-11-26.md` | `14cb09a2e623` |
| S3 | `services/mca_vision.py` | `a414bdb19642` |
| S3 | `services/media_readiness.py` | `dcb8f4b73005` |
| S3 | `tests/test_p0_media_bind_f2.py` | `3e1f491b7051` |
| S4 | `plans/features/smart-execution-reliability-01/evidence/p0-embed-empty-input-2026-11-26.md` | `fd2724fbe5aa` |
| S4 | `.../p0-embed-empty-input-2026-11-26/raw-affected-batch10-candidate.txt` | `05ecb7bcc35b` |
| S4 | `.../raw-affected-batch12-candidate.txt` | `4ff1dcf8bfe5` |
| S4 | `.../raw-affected-batch20-base-f2cb38c84.txt` | `829a74de84b6` |
| S4 | `.../raw-affected-batch20-candidate.txt` | `54223b28c52c` |
| S4 | `.../raw-green-candidate-7686d6fcd.txt` | `87ec86d87da8` |
| S4 | `.../raw-pre-existing-2-base-f2cb38c84.txt` | `de7071dbd09e` |
| S4 | `.../raw-pre-existing-2-candidate.txt` | `ea269b0f6296` |
| S4 | `.../raw-red-base-f2cb38c84.txt` | `014d9596e2a1` |
| S4 | `services/mca_retrieval_context.py` | `47c9104975a2` |
| S4 | `services/summary_memory.py` | `6ebe96e8b955` |
| S4 | `tests/test_p0_embed_empty_input.py` | `b00e3d3507c6` |

## 3. Общий файл: композиция (не «одна сторона победила»)

`services/direct_chat_service.py` — единственный файл, затронутый двумя срезами.
Проверка `git merge-file -p ours base theirs`:

- база — `4e5374536:services/direct_chat_service.py` (фактическая база ветки S2,
  уже содержащая первый коммит S1);
- ours — `f6d7f4fc1:...` (tip S1), theirs — `170f70e3f:...` (tip S2).

| свойство | результат |
|---|---|
| `git merge-file` exit code | **0 (чисто, без конфликтов)** |
| merged sha256 | `5a82c95022e0bea9cd696a3da41fc2e2b85fe8ff0c58cccec1ad529f66991dd8` |
| HEAD sha256 | `5a82c95022e0bea9cd696a3da41fc2e2b85fe8ff0c58cccec1ad529f66991dd8` |
| **assembled == 3-way merge** | **true** |
| tip S1 == база S2 для этого файла | **true** (поздний corrective S1 файл не трогал) |
| HEAD blob | `dc1583af10bc837543d696565ff0e73fd8f60044` |

Швы не пересекаются: S1 меняет provenance/trigger-хендофф
(`trigger_type`, `own_message_text`, удаление forced-text механизмов) и
`_l1_reply_block(preserve=…)`-обвязку; S2 меняет только предикат
`_prepare_turn_media_evidence` (`extract_image_assets` вместо
«транспортного токена»). Обе стороны доказаны по отдельности на composed-дереве:

- маркеры S1: `trigger_type` — 67 вхождений (tip S1: 67, база: 44);
  `TRIGGER_FORCE_KEYWORD`/`FORCE_LINE` — 0; `force_reply_required` — 1
  (keyword-only compat-параметр, семантики не несёт);
- маркеры S2: `extract_image_assets` — 3 (tip S2: 3, база: 0);
- **тест S2 `tests/test_p0_media_phantom_intent.py` присутствует** и зелёный
  (12/12, §5), изменения S1 в `handlers/direct_chat.py`,
  `services/command_prefix.py`, `services/direct_l1.py` — на месте и зелёные.

## 4. Version wave 2.58.248 (32 файла / 35 строк)

Байтовая замена только токена версии; BOM/переводы строк сохранены
(проверено на каждом файле: реверс `2.58.248 → 2.58.247` даёт байт-в-байт
исходник, признак BOM и счётчики CRLF/LF не изменились):

- `config/settings.py` — 1 строка (`APP_VERSION = "2.58.248"` + шапка
  релизных заметок этого выпуска в той же строке; предыдущая запись стала
  `Prior ... 2.58.247`);
- `plans/docs/param-registry-round1025.meta.md` — 1;
- 4 × `tests/js/*` — 4 (экранированный пин `2\.58\.NNN`);
- 24 py-пина — 25 (23 × 1 + `test_webapp_round1026_polygon.py` 2);
- `tools/ui_mod_acl_m4b2_status_e2e.py` 3 + `tools/ui_mod_acl_m4b3_status_e2e.py` 1.

Итог: **32 файла, 35 строк**, `git diff --shortstat` подтверждает
(`32 files changed, 35 insertions(+), 35 deletions(-)`), коммит `c3887d0cb`.

**Честная деталь:** в `tests/test_p0_embed_empty_input.py` (новый тест S4)
есть текст «Прод-сигнал **2.58.247**» — это исторический провенанс сигнала, а
не пин версии; он **сознательно не менялся**. Иначе волна стала бы 33/36, но
переписала бы историческое утверждение теста.

## 5. Тесты на точном кандидате `c3887d0cb`

Кандидат: `c3887d0cbcb9648638a7db1dae41309676d64aef`. Прогон — в этом
worktree, `.venv` (Python 3.12.0, pytest 9.1.1), `pytest -q -p no:cacheprovider`.
Единственный коммит после код-кандидата — этот evidence-файл (код не меняется).

| набор | файлов | passed | failed | skipped |
|---|---|---|---|---|
| собственные тесты срезов + два re-targeted файла (`test_p0_trigger_force_l1`, `test_p0_media_phantom_intent`, `test_p0_media_bind_f2`, `test_p0_embed_empty_input`, `test_rlr_observability`, `test_direct_llm_decision_asap32`) | 6 | **66** | 0 | 0 |
| handler/direct/L1/behaviour (direct_chat*, context_*, decision_matrix, l1_corrective, l1d, fallback_recompose, asap7_direct_*, speech_l1_route, ur_turn_engine, rc_direct_self_correction, asap8_v6_wc_direct_*, agentic_ai) | 22 | **651** | 7 | 0 |
| media/vision (media_*, native_*media*, rc_target_media, p0_vision_*, vision_*, evol011/019, evol_vision_sync_*, p0_goal_media) | 18 | **399** | 0 | 38 |
| memory/embedding (p0_embed_*, embed_*, evol010, asap5/asap6/asap8 embeddings, soul1_w7, summary_memory/fact_package/publish, mca07, memory_unified*, memory_period_vector_leg, memory_contracts, memory_attribution, smart_exec_memory_scope, vmq_mem_retrieval, tool_router) | 26 | **768** | 0 | 0 |
| canon/pins/soul (asap_fc_voice_l1, asap_speech_r3b_canon, evol_evidence_routing, evol_w17, expression_isolation, p0_prompts_core, post_asap5_w1/w2, prompt_migrations, prompt_baseline, speech_p0_core_serious, soul1_direct_prompt_reads, p0_factual_memory_prompts) | 13 | **312** | 1 | 0 |
| пины версии (py) | 22 | **726** | 5 | 0 |
| **итого** | **107 файлов** | **2922** | **13** | **38** |

### 13 падений — все pre-existing, доказано на базе

Все 13 идентификаторов перезапущены на чистом `f2cb38c84`
(worktree `release/p0-2.58.247`, тот же интерпретатор):
**`13 failed in 15.93s`** — те же 13, ни одного нового, ни одного «позеленевшего».

| # | тест | фактическая причина |
|---|---|---|
| 1 | `test_direct_context_scenarios_asap3::TestStaleSummary::test_lag400_middle_topk_under_pressure` | `assert 74 <= 60` — устаревшее ожидание окна |
| 2 | `test_direct_l1_corrective_r1::test_build_l1_context_bot_replies_caps_and_limit` | `assert False` (стр. 247), контракт стаба |
| 3–7 | `test_direct_fallback_recompose_asap32` (5 тестов) | стабы fallback-адаптера: неожиданный kwarg `sent` / `LLMError: primary down` |
| 8 | `test_asap_fc_voice_l1_decision_profile::test_direct_service_l1_payload_gets_profile_from_turn_frame` | стаб без `preserve=` |
| 9–10 | `test_tool_coordinator_round1026::TestBounds::{test_forbidden_paths_out_of_diff, test_canon_twelve_tools}` | старый baseline/канон-пин |
| 11–12 | `test_unified_image_request_round1026::{TestToolDescriptionU21::test_canon_unchanged, TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline}` | пин канона 2.58.247 устарел ещё на базе |
| 13 | `test_webapp_f9_round1025::TestInvariants::test_secrets_count_28` | на базе 34 секрета против пина 32 |

Это известный долг базы (`BACKLOG_ONLY`), не контракт релиза; падения не
маскировались, пины не подгонялись.

### Собственные тесты срезов

`test_p0_trigger_force_l1` (20), `test_p0_media_phantom_intent` (12),
`test_p0_media_bind_f2` (6), `test_p0_embed_empty_input` (8) — **46/46 passed**
на composed-дереве; вместе с re-targeted `test_rlr_observability` (6) и
`test_direct_llm_decision_asap32` (14) — 66/66 (§5, первая строка).

## 6. Structural / static

- `node --check` 5/5: 4 JS-пина + `web/app.js` (изменён S1), rc 0.
- `py_compile` всех 49 изменённых `.py` (base..HEAD): **49/49 ok**.
- `git diff --check` в рабочем дереве после волны: rc 0;
  `git diff --check f2cb38c84..HEAD`: rc 0.
- DDL/миграции/флаги: `migrations/`, `models/`, `services/database.py` не
  затронуты; `config/settings.py` изменён только строкой версии → **DDL 0,
  миграций 0, новых флагов 0**, схема v48.

## 7. Manifest dry-run

Прогон `python tools/release_manifest.py --dry-run` на чистом дереве
код-кандидата `c3887d0cb` (в worktree нет `.deploy/release.json`, поэтому для
`previous_*` использован локальный untracked seed с прод-идентичностью
`f2cb38c84 / 2.58.247`, удалён сразу после прогона; ни одно поле не выдумано):

```json
{
  "deployed_at": "2026-11-25T15:23:00.182856Z",
  "deployed_sha": "c3887d0cbcb9648638a7db1dae41309676d64aef",
  "dirty_tracked": false,
  "effect": "deploy",
  "previous_sha": "f2cb38c8412506261504b4000f7a7a53be143851",
  "previous_version": "2.58.247",
  "release_branch": "release/p0-2.58.248",
  "schema": 1,
  "version": "2.58.248"
}
```

Инструмент берёт `deployed_sha` из `git rev-parse HEAD` момента прогона. Этот
документ — единственный коммит после код-кандидата (меняет только `plans/`),
поэтому повторный dry-run на финальном tip'е ветки даёт те же поля с
`deployed_sha` = фактический HEAD `release/p0-2.58.248`; штатная запись
манифеста — DevOps на сервере, где `deployed_sha` = HEAD выложенного checkout.

Сводка контракта выкладки: **DDL 0, миграций 0, новых флагов 0**, новых
store/эндпоинтов/моделей/планировщиков нет; откат — только код.

## 8. Откат

- **Только код**, `git`-откат на `f2cb38c84` (2.58.247): DDL 0, миграций 0,
  новых флагов 0, новых store нет, формат данных не меняется.
- Промпты не меняются ни одним срезом (canon-файлы не затронуты; у canon-пинов
  нет ни одного нового падения — единственное падение набора доказано
  pre-existing) → сохранённые пользовательские правки не затрагиваются.
- Данные production не мигрируются, восстановление БД не требуется.

## 9. Что осталось непроверенным (честно)

- Effective-state прода (фактическая версия `/healthz`, схема, identity деплоя,
  диск) проверяет DevOps после выкладки; здесь production не затрагивался.
- Реальное поведение моделей на живых чатах (формулировки, «человечность»,
  уместность) не является инженерным критерием приёмки по
  `BOUNDED ACCEPTANCE`; проверяется при обычной эксплуатации.
- Полный `pytest` по всему репозиторию не является практикой проекта; наборы
  выбраны по затронутым контурам, остаточные падения сведены к доказанным
  pre-existing.
- Визуальный слой не менялся (кроме `web/app.js` — удалённые forced-text
  consumer-пути); Playwright/Browser Use не применимы. `node --check` пройден.

## 10. Очистка

- Временный `.deploy/release.json` seed удалён сразу после dry-run
  (`git status --porcelain` пуст).
- Временные файлы сравнения/merge в `WorkspaceData/temp/...` удалены.
- Новых файлов вне срезов, version wave и этого документа нет.
- Deploy/merge в master/SSH не выполнялись.
