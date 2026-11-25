# Релиз 2.58.247 — сборка (P0: ответ / память / цель+медиа)

- **Роль:** Builder, локальная сборка. **Без деплоя, SSH и production.** Выкладка,
  effective-state проверки и post-deploy — DevOps после независимого
  delta-ревью этого кандидата.
- **База (production 2.58.246, подтверждён live):**
  `78abc866cc11ffba2ffaea2558080149859ce6ad` (release `release/2.58.246`).
- **Ветка:** `release/p0-2.58.247` от `78abc866c` в отдельном registered worktree
  (`WorkspaceData/worktrees/c742e4de9e92c489/release-p0-2-58-247-a4252464c5c7-0ee2a6bb`,
  epic `release-p0-2.58.247`, unit `release-2.58.247`). Интеграция — линейный
  cherry-pick, **без merge-коммитов**.
- **Срезы:** три независимо одобренных линии, все
  `APPROVED_FOR_RELEASE_PREPARATION`; sha256 файлов ревью сверены до начала
  сборки (файлы ревью лежат в planning-checkout `master`, как и в 2.58.246 —
  на релизную ветку они не импортируются).

```json
{
  "release": "2.58.247",
  "base": {"sha": "78abc866cc11ffba2ffaea2558080149859ce6ad", "version": "2.58.246",
           "state": "deployed_live_verified (вход Orchestrator)"},
  "slices": [
    {"id": "A", "name": "answer finalization", "branch": "fix/p0-answer-finalization",
     "base": "e3467ccb787709650af3f493a88861e60ac51684",
     "source_tip": "6f8b2dfad225b370dd44e1cc9835ee673db54609",
     "product_commits": ["a613e3569", "dc1b4ac89"], "evidence_commits": ["7b936d75c"],
     "rows": ["P0-AQ-4.1", "P0-AQ-4.2", "P0-AQ-4.3", "P0-AQ-2.1"],
     "review": {"file": "plans/features/unified-reply/evidence/p0-answer-finalization-review-r2.md",
                "sha256": "3148dbd8875fcffad8bec517537dcb246d7ee3973e7f99d659f71b94ddb3c15d",
                "hash_reproduced": true, "verdict": "APPROVED_FOR_RELEASE_PREPARATION"}},
    {"id": "B", "name": "memory relevance", "branch": "fix/p0-memory-relevance",
     "base": "e3467ccb787709650af3f493a88861e60ac51684",
     "source_tip": "39ba8bd4a870cf93433be0d4bcad24768461d938",
     "product_commits": ["709e15b74", "8334291c6", "c2a1d15da"],
     "evidence_commits": ["f9d3cc72b", "351c298c7", "c893bb295"],
     "rows": ["P0M-REL-01", "P0M-TIME-01", "P0M-DIAG-01", "MEM-REL-IDENTITY", "MEM-REL-TIME",
              "MEM-REL-ROLE", "MEM-COMPOSER-TYPED", "MEM-ANTI-FIRST-N", "MEM-NO-GLOBAL-CAPS",
              "RC-CF-WHO", "RC-SHARED-ROLES"],
     "review": {"file": "plans/features/vmq-onto-01/evidence/p0-memory-relevance-review-r3.md",
                "sha256": "af33081c1054dc18c3e2d6bc24b33ce216f315cc8790dc200ce92af4b0534e0b",
                "hash_reproduced": true, "verdict": "APPROVED_FOR_RELEASE_PREPARATION"}},
    {"id": "C", "name": "goal + media", "branch": "fix/p0-goal-media",
     "base": "78abc866cc11ffba2ffaea2558080149859ce6ad",
     "source_tip": "c0dc8349e3b7c0692cf9c648edd2b2117426b629",
     "product_commits": ["542f54820", "c0dc8349e"], "evidence_commits": [],
     "rows": ["P0I-GOAL-01", "P0I-GOAL-02", "P0R-MEDIA-01", "P0R-MEDIA-02"],
     "review": {"file": "plans/features/unified-reply/evidence/p0-goal-media-review-r2.md",
                "sha256": "c7f259b3271f6559f71e2191adf74bc7e23b455c1a13bd00d11015b6ce57b77c",
                "hash_reproduced": true, "verdict": "APPROVED_FOR_RELEASE_PREPARATION"}}
  ],
  "integration": "linear cherry-pick (no merge commits): C 78abc866c..c0dc8349e (2), A e3467ccb7..6f8b2dfad (3), B e3467ccb7..39ba8bd4a (6), then version wave, then assembly corrective A247-ASM-F1",
  "commits_above_base": 13,
  "delta_vs_base": {"files": 79, "insertions": 4057, "deletions": 759},
  "delta_by_area": {
    "services": {"files": 12, "insertions": 958, "deletions": 409},
    "tests": {"files": 56, "insertions": 1859, "deletions": 344},
    "plans": {"files": 8, "insertions": 1235, "deletions": 1},
    "config": {"files": 1, "insertions": 1, "deletions": 1},
    "tools": {"files": 2, "insertions": 4, "deletions": 4}
  }
}
```

## 1. Линия и порядок интеграции

| # | релизный коммит | источник | тип |
|---|---|---|---|
| 1 | `2607ede95` | C `542f54820` | product (goal в плане, медиа-опы) |
| 2 | `5019e945b` | C `c0dc8349e` | product+evidence (re-pin factory fingerprint) |
| 3 | `3c87e4210` | A `a613e3569` | product (программные реплики, gate «Летописца») |
| 4 | `27b0c3129` | A `7b936d75c` | evidence |
| 5 | `dc1b4ac89` | A `6f8b2dfad` | product (F6: доставленный артефакт = отвечено) |
| 6 | `80fcb6e89` | B `709e15b74` | product (автор/роль, период originals, prefix-OR) |
| 7 | `051439ac7` | B `f9d3cc72b` | evidence |
| 8 | `3c829fd5a` | B `8334291c6` | product (author_window) |
| 9 | `8560561a7` | B `351c298c7` | evidence |
| 10 | `5629ff6a4` | B `c2a1d15da` | product (originals-only RAG, zero-facts payload) |
| 11 | `c893bb295` | B `39ba8bd4a` | evidence |
| 12 | `27491b1e3` | — | version wave 2.58.247 |
| 13 | `9f5813084` | — | assembly corrective A247-ASM-F1 (см. §6) |

Конфликтов cherry-pick не было: два общих файла слились автоматически
(`Auto-merging services/direct_l1.py`, `Auto-merging services/direct_chat_service.py`,
`Auto-merging tests/test_tool_coordinator_round1026.py`).

## 2. Собственные файлы срезов: побайтовая идентичность

Замер на композиционном дереве (`9f5813084`): 48 файлов затронуты линиями,
распределение по владению — A 13, B 14, C 19, A+B 1, A+C 1.

- **43 файла байт-в-байт равны blob'у своего срезового tip** (`git rev-parse`).
- **1 файл** (`tests/test_tool_coordinator_round1026.py`, владелец A) отличается
  от tip A **только строкой версии**: diff = единственная замена
  `2.58.245` → `2.58.246` (пин базы 2.58.246), которую линия A не могла
  унаследовать, т.к. ветвилась от `e3467ccb7`; после version wave строка стала
  `2.58.247`. Продуктовые правки линии A в файле сохранены байт-в-байт.
- **2 файла** (общие, §3) — композиция, а не равенство одному tip.
- **2 файла** (`tests/test_p0_delta_routing.py`, `tests/test_tool_loop.py`) —
  владение A, изменены ассемблерной коррективой A247-ASM-F1 (§6): только
  ожидаемые строки служебного блока/метки, продуктовые байты не тронуты.
- Остальные файлы version wave (24 py-пина, 4 escaped JS-пина, F8-мета,
  2 tools) отличаются от tip'ов своих линий **только токеном версии** —
  это и есть стандартная волна (32 файла / 35 строк, §4).

## 3. Общие файлы: композиция (не «одна сторона победила»)

Проверка механическая: собранный blob сравнивается с результатом
`git merge-file -p ours base theirs` (база — общий предок `e3467ccb7`,
стороны — tip'ы двух линий). Совпадение означает, что **ни один хунк не
потерян и не отредактирован руками**.

| файл | линии | база | merge-file | assembled == 3-way merge | blob | sha256 |
|---|---|---|---|---|---|---|
| `services/direct_chat_service.py` | A+B | `e3467ccb7` | exit 0 (чисто) | **true** | `81943b9bcbd290a2785bedc5802e1cd560cdf819` | `752f9d575d9985144f978efaa966d210cc3f8bf807bacdc33f4a992b70062108` |
| `services/direct_l1.py` | C+A | `e3467ccb7` | exit 0 (чисто) | **true** | `b3cd02cc5eeb477569dcbca9670584fdb37ee8b9` | `cdcd6c8579f13bf842df2c558a3dc8687a768513390b02c053408d461f6a8ed7` |

Швы в `direct_chat_service.py` не пересекаются по построению:
- линия A — импорт (`structured_partial_from_result` → `media_delivered`),
  docstring'и гейтов «Летописца» (≈2015/2055) и ветка пустого финала (≈7857);
- линия B — период в live-ноге (≈13158), `_rag_originals` (≈17317), пул/
  author window и обёртка originals (17275–18599), `_plan_target_message_id`
  (≈20581).
После композиции `structured_partial_from_result` в `services/` отсутствует
(удалён линией A), и линия B его не возвращает — проверено `git grep`.
`direct_l1.py`: линия C добавляет `FINAL_GOAL_MAX`/`L1Plan.final_goal`/
нормализацию/строку цели в L2-блок, линия A меняет `LORE_STORY_ACTS` и
`lore_story_delivery_allowed` (fail-closed) — регионы не пересекаются.

## 4. Канон L1: ровно одна ступень

Канон трогает **только линия C** (в диффах A и B нет
`chat_prompts.py`/`prompt_migrations.py`/`prompt_registry.py`/`tool_schemas.py`),
поэтому второй ступени взяться неоткуда. Проверка на исполнении
(`config/settings.py:APP_VERSION`, `services.prompt_registry`, `services.prompt_migrations`):

```json
{
 "app_version": "2.58.247",
 "l1_canon_sha12": "ce6931304b24",
 "factory_set_sha12": "10efa51a8dae",
 "ladder_steps_for_l1": 21,
 "steps_pointing_at_live_canon": 21,
 "ladder_head_is_live_canon": true,
 "ladder_head_prev_sha12": "619290834387",
 "final_goal_present": true,
 "evr6_prev_sha12": "619290834387",
 "rule7_p0gm_present": true,
 "media_actions_p0gm_present": true
}
```

- единственная новая ступень: `(PREV_DIRECT_L1_PLANNER_EVR6 → активный канон)`,
  т.е. `EVR6 → P0GM`; все 21 ступени лестницы указывают на одни и те же
  живые байты (одна голова, конкурирующей цели нет);
- активная ревизия `ce6931304b24` (P0GM: правило 7 «продукт vs материал»,
  поле `final_goal`, абзацы цели и действий с медиа);
- заводской отпечаток набора `10efa51a8dae` — пересчитан линией C и совпадает
  с пином в тестах; изменения линий A/B его не двигают (они не меняют
  заводские тексты промптов).

## 5. Version wave 2.58.247 (32 файла / 35 строк)

Байтовая замена только токена версии, BOM/переводы строк сохранены
(`config/settings.py`: BOM `true`, CRLF 3665 = LF 3665):

- `config/settings.py` — 1 строка: `APP_VERSION = "2.58.247"` + шапка
  релизных заметок этого выпуска (предыдущая запись стала `Prior ... 2.58.246`);
- `plans/docs/param-registry-round1025.meta.md` — 1;
- 4 × `tests/js/*` — 4 (экранированный пин `2\.58\.NNN`);
- 24 py-пина — 25 (23 × 1 + `test_webapp_round1026_polygon.py` 2);
- `tools/ui_mod_acl_m4b2_status_e2e.py` 3 + `tools/ui_mod_acl_m4b3_status_e2e.py` 1.

Итог волны: **32 файла, 35 строк**, `git diff --stat` подтверждает
(`32 files changed, 35 insertions(+), 35 deletions(-)`).

## 6. Ассемблерная коррeктива A247-ASM-F1 (честно)

**Найдено на сборке, не в линиях:** 4 теста проходили на базе и на каждом tip'е
по отдельности, но падали на составленном дереве.

- **Причина (общая, а не частная):** линия B по своему же evidence
  (`p0-memory-relevance-2026-11-25.md`, §«служебные метаданные») переносит
  метод/счётчик/показано/период из **первой строки** результата в хвостовой
  блок `<поиск_служебное>` и уточняет метку производного слоя
  («Отдельные сведения из памяти…»). Линия B обновила свои тесты
  (`test_tool_router.py`), но два файла с прежними формулировками принадлежат
  линии A (`test_p0_delta_routing.py`, `test_tool_loop.py`) — каждая линия
  зелёная сама по себе, композиция — нет.
- **Правка:** только ожидаемые строки в этих двух файлах; дискриминаторы
  сохранены или усилены: проверяются наличие служебного блока,
  `совпадений=312`, `показано=1`, маркер `выдача неполная` (раньше — одна
  подстрока прозы), отдельная метка провенанса, и что число совпадений
  по-прежнему доезжает до модели.
- **Продуктовые байты не менялись**; ни одно поведение линии не отключено и
  не ослаблено. Коммит `9f5813084`.
- Регресс-проверка: `test_p0_delta_routing.py` + `test_tool_loop.py` —
  **80 passed**, 0 failed.

## 7. Тесты на точном кандидате `9f5813084` (дерево `1ffb39e83`)

Кандидат: `9f5813084d4b7fb0e37a105167672e69144b5e50`, дерево
`1ffb39e83cc7068884750ec303e06b94163cacfa`. Прогон — в этом worktree,
тем же интерпретатором (`.venv`, Python 3.12.0, pytest 9.1.1),
`pytest -q -p no:cacheprovider`. Единственный коммит после код-кандидата —
этот evidence-файл (код не меняется).

| набор | файлов | passed | failed | падения |
|---|---|---|---|---|
| собственные тесты срезов (`test_p0_answer_finalization`, `test_p0_memory_relevance{,_r1,_r2}`, `test_p0_goal_media_2026_11_25`) | 5 | **55** | 0 | — |
| канон / пины / soul (lane C + factory fingerprint) | 16 | **369** | 2 | pre-existing |
| tool_loop / финализация / lore / nostalgia | 18 | **490** | 7 | pre-existing |
| память / retrieval / mca | 11 | **438** | 0 | — |
| tool-routing / media / direct | 12 | **463** | 5 | pre-existing |
| UR / планировщик | 11 | **202** | 0 | — |
| пины версии (py) | 23 | **809** | 3 | pre-existing |
| **итого** | **96 файлов** | **2826** | **17** | все 17 — pre-existing |

Состав наборов:
`canon_pins_soul` — `test_asap_fc_voice_l1_decision_profile`, `test_asap_speech_r3b_canon`,
`test_direct_l1_corrective_r1`, `test_direct_l1_l1d_contract`, `test_evol_evidence_routing`,
`test_evol_w17_small_canon_reqs`, `test_expression_isolation_followup`, `test_p0_prompts_core`,
`test_post_asap5_w1_writer_core`, `test_post_asap5_w2_tech_reasoning`, `test_prompt_migrations`,
`test_prompt_baseline`, `test_speech_p0_core_serious`, `test_speech_p0_corrective_l1_route`,
`test_soul1_direct_prompt_reads`, `test_asap7_direct_l1`;
`tool_loop_finalization_lore` — `test_tool_loop`, `test_smoke_round1016_tool_loop`,
`test_tool_calling_round1015`, `test_agentic_ai_round1020`, `test_smart_g_finalize_round1114`,
`test_smart_corrective_s7_reply`, `test_smart_p0_checkup`, `test_p0_delta_routing`,
`test_tool_coordinator_round1026`, `test_chat_lore{,_api}`, `test_lore_compiler_round1020`,
`test_lore_prompts`, `test_lore_worker`, `test_p0_old_lore_quarantine`,
`test_nostalgia_corrective_r1`, `test_nostalgia_w2`, `test_nostalgia_proactive_recall`;
`memory_retrieval_mca` — `test_tool_router`, `test_mca15_chat_statistics_round1028`,
`test_mca07_retrieval_context_round1027`, `test_mca18_memory_subject_block_b_round1042`,
`test_memory_unified_retrieval{,_06}`, `test_memory_period_vector_leg`, `test_memory_attribution`,
`test_memory_contracts`, `test_smart_exec_memory_scope`, `test_vmq_mem_retrieval_fixes`;
`routing_media_direct` — `test_media_download`, `test_media_execution_asap32`,
`test_native_media_tools_round1024`, `test_native_reply_media_context_round1024`,
`test_rc_target_media_evidence`, `test_direct_chat{,_handlers,_lore_inject,_prompts}`,
`test_checkup_prompts`, `test_direct_fallback_recompose_asap32`, `test_direct_context_composer_asap3`;
`ur_planning` — `test_ur_c_clock`, `test_ur_c_sched`, `test_ur_per_chat_schedule`,
`test_exp_e_lag_scheduling`, `test_ur_turn_engine`, `test_ur_11_single_owner`,
`test_ur_11_writer_fallback`, `test_ur_context_selection`, `test_ur_d_writer`,
`test_ur_e_speech`, `test_ur_g_acceptance`.

### Доказательство «падения те же самые»

Все 17 идентификаторов падений перезапущены на базе `78abc866c` (чистый
worktree `release/2.58.246`): **17 из 17 падают там точно так же**
(`17 failed, 1 warning in 11.20s`), ни один не «позеленел» на базе и ни один
не появился только в кандидате → **новых падений 0**.

| # | тест | статус |
|---|---|---|
| 1 | `test_asap_fc_voice_l1_decision_profile::test_direct_service_l1_payload_gets_profile_from_turn_frame` | pre-existing (stub без `preserve=`) |
| 2 | `test_direct_l1_corrective_r1::test_build_l1_context_bot_replies_caps_and_limit` | pre-existing |
| 3 | `test_chat_lore_api::TestHistory::test_history_shape_and_is_ai` | pre-existing |
| 4–7 | `test_nostalgia_w2` (max_send_chars, diagnostics_meta, diversity, same_episode) | pre-existing |
| 8–9 | `test_tool_coordinator_round1026::TestBounds::{test_canon_twelve_tools, test_forbidden_paths_out_of_diff}` | pre-existing |
| 10–14 | `test_direct_fallback_recompose_asap32` (5 тестов) | pre-existing |
| 15–16 | `test_unified_image_request_round1026::{test_forbidden_paths_out_of_diff_vs_baseline, test_canon_unchanged}` | pre-existing (пин канона 2.58.246 устарел ещё на базе) |
| 17 | `test_webapp_f9_round1025::test_secrets_count_28` | pre-existing (на базе 34 секрета против пина 28) |

Эти 17 — известный долг базы (`BACKLOG_ONLY`), не контракт этого релиза;
они не маскировались и не переписывались.

### Собственные тесты срезов: 55/55

Запускались ровно файлы, которыми линии доказали свою приёмку:
`tests/test_p0_answer_finalization.py` (A), `tests/test_p0_memory_relevance.py`,
`_r1`, `_r2` (B), `tests/test_p0_goal_media_2026_11_25.py` (C) — 55 passed,
0 failed на составленном дереве (это и есть сквозная проверка того, что
поведение каждой линии дожило до композиции).

## 8. Structural / static

- `node --check` на 4 JS-пинах: rc 0 ×4.
- `py_compile` всех изменённых `.py`: **69/69 ok** (включая два файла A247-ASM-F1).
- `git diff --check` в рабочем дереве: rc 0 (дерево чистое).
- `git diff --check 78abc866c..HEAD`: 2 замечания trailing whitespace —
  **внутри markdown-evidence линии B** (`p0-memory-relevance-2026-11-25.md:139`,
  `p0-memory-relevance-review-r2-fixes.md:41`), где хвостовые пробелы — разрыв
  строки markdown; продуктовый код не затронут, файлы линии не переписаны.
- DDL/миграции/флаги: `git diff` базы и кандидата по `migrations/`, `models/`,
  `services/database.py` не содержит `CREATE/ALTER/DROP TABLE`, `CREATE INDEX`,
  `schema_version`; единственное изменение в `services/database.py` — аддитивный
  `years=` и `ORDER BY timestamp DESC` в read-only чтении. `config/settings.py`
  изменён только строкой версии → новых полей/флагов/секретов нет.
  Схема остаётся **v48**.

## 9. Manifest dry-run

```json
{
  "schema": 1,
  "deployed_sha": "9f5813084d4b7fb0e37a105167672e69144b5e50",
  "version": "2.58.247",
  "deployed_at": "2026-11-25T11:47:11.407839Z",
  "effect": "deploy",
  "previous_sha": "78abc866cc11ffba2ffaea2558080149859ce6ad",
  "previous_version": "2.58.246",
  "dirty_tracked": false,
  "release_branch": "release/p0-2.58.247"
}
```

Dry-run выполнен на чистом дереве код-кандидата (`git status --porcelain`
пуст); `dirty_tracked=false`, `effect=deploy`, версия `2.58.247`,
`previous=78abc866c/2.58.246`. Инструмент берёт `deployed_sha` из
`git rev-parse HEAD` момента прогона; на финальном tip'е ветки (после этого
evidence-коммита, который меняет только `plans/`) тот же прогон даёт
`deployed_sha` = фактический HEAD ветки. `previous_*` читаются из
`.deploy/release.json` checkout'а; в worktree его нет, поэтому для dry-run
использован локальный (untracked, удалён после) seed с прод-идентичностью
`78abc866c/2.58.246` — в него не выдумано ни одного поля.

Сводка контракта выкладки: **DDL 0, миграций 0, новых флагов 0**, новых
store/эндпоинтов/моделей/планировщиков нет, формат данных не меняется,
откат — только код: `78abc866c`.

`previous_*` берётся инструментом из `.deploy/release.json` checkout'а, которого
в worktree нет; ожидаемые прод-значения на момент сборки —
`78abc866c… / 2.58.246`. Штатная запись манифеста выполняется DevOps на
сервере (`tools/release_manifest.py`), где `deployed_sha` = фактический HEAD
выложенного checkout.

## 10. Откат

- **Только код**, `git`-откат на `78abc866c` (2.58.246): DDL 0, миграций 0,
  новых флагов 0, новых store нет, формат данных не меняется.
- Промпты: единственное изменение канона — шаг `EVR6 → P0GM`; при откате кода
  ступень исчезает из лестницы, сохранённые пользовательские правки промптов
  не сбрасываются (ступень трогает только точное совпадение байт).
- Данные production не мигрируются, поэтому откат не требует восстановления БД.

## 11. Что осталось непроверенным (честно)

- Реальное поведение моделей на живых чатах (формулировки, «человечность»,
  уместность) — не является инженерным критерием приёмки по
  `BOUNDED ACCEPTANCE`; определяется при обычной эксплуатации.
- Effective-state прода (фактически включённое, версия `/healthz`, схема,
  identity деплоя, диск) проверяет DevOps после выкладки; в этой сборке
  production не затрагивался.
- Прогон полного `pytest` по всему репозиторию не является практикой проекта;
  наборы выбраны по затронутым контурам (см. §7), остаточные падения сведены
  к доказанным pre-existing.
