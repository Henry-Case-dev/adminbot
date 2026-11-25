# Сборка 2.58.250 — UR-G/UR-B (трасса доставки инициативы + F1/F2 корректива, v2)

- **Роль:** Builder, локальная сборка. **Без deploy, merge в master, SSH и
  production.** Effective-state прода и post-deploy проверки — DevOps после
  выкладки; этот документ — вход для delta-ревью релизного кандидата.
- **База (production 2.58.249):** `af8de2ac6e59f4c0b899c0c839f02258a9e02236`.
- **Ветка:** `release/ur-gb-2.58.250` от `af8de2ac6` в registered worktree
  (`WorkspaceData/worktrees/c742e4de9e92c489/unified-reply-41500c30aca7-4b645e38`,
  epic `unified-reply`). Интеграция — линейные cherry-pick, **без merge-коммитов**.
- **Срез:** `UR-G/UR-B`, ветка `feat/ur-gb-rows`, tip
  `dcbe2bf18b5697d4b83df58e530bdf3a711f3025` (предыдущий `8929f04cb`;
  функциональные части: `6d10d35de` UR-RES-01 trajectory parity, `8929f04cb`
  корректива `URGB-R1-F1`, `dcbe2bf18` корректива `URGB-DR1-F1/F2`).
- **Интеграционный код-кандидат:** `6cb4026f6b8bb9dc1fcb9fed2d17f98be1957e7b`
  (6 коммитов среза/версии + прежний текст сборки; этот переписанный документ
  идёт отдельным коммитом поверх и меняет только `plans/`).
- **Сессия сборки:** `ses_deb67df3dffe0mJeDC3a7D0yfA`.

```json
{
  "release": "2.58.250",
  "base": {"sha": "af8de2ac6e59f4c0b899c0c839f02258a9e02236", "version": "2.58.249"},
  "slice": {
    "id": "UR-G/UR-B", "name": "initiative turn-trace delivery parity + acceptance proofs (incl. DR1-F1/F2)",
    "branch": "feat/ur-gb-rows",
    "base": "af8de2ac6e59f4c0b899c0c839f02258a9e02236",
    "source_tip": "dcbe2bf18b5697d4b83df58e530bdf3a711f3025",
    "previous_tip": "8929f04cbc91b02ba1b2b9557b24f92a5af5d304",
    "product_commits": ["6d10d35de", "8929f04cb", "dcbe2bf18"],
    "evidence_commits": ["6d10d35de", "1599c77d0", "2837a719f", "8929f04cb",
                         "dcbe2bf18"],
    "review": {
      "slice_r1": "ur-gb-rows-review-r1.md (NEEDS_FIXES URGB-R1-F1, закрыт 8929f04cb)",
      "slice_r2": "ur-gb-rows-review-r2.md",
      "slice_r2_sha256": "6f7114e84cd418b6aa2461357c960b7867eb4566762a998237328d703560713c",
      "delta_r1": "plans/features/unified-reply/evidence/release-2.58.250/delta-review-r1.md",
      "delta_r1_sha256": "45e04fe8df6251d71391bf2f345bfbf875d3c88f8d51db45179878847d816422",
      "delta_r1_verdict": "NEEDS_FIXES (URGB-DR1-F1/F2) — исправлено срезом dcbe2bf18, ожидает re-review r2"
    },
    "per_row": {"UR-RES-01": "PASS", "UR-30.2": "PASS", "UR-07.3": "PASS",
                "UR-17.7": "PASS", "UR-17.8": "PASS"}
  },
  "integration": "linear cherry-pick: slice (5 commits, включая DR1-F1/F2), version wave (1); переписанный текст сборки (1)",
  "commits_above_base": 8,
  "code_candidate": {"sha": "6cb4026f6b8bb9dc1fcb9fed2d17f98be1957e7b",
                     "tree": "9dfc49144a2b5f4c3275ab3f66ef7f9aeeed7d7c"},
  "delta_vs_base": {"files": 41, "insertions": 2446, "deletions": 43}
}
```

sha256 ревью воспроизведены с planning-checkout (`master`).

## 1. Порядок интеграции

| # | интеграционный SHA | источник | тип |
|---|---|---|---|
| 1 | `b9caf9340` | UR-G/UR-B `6d10d35de` | product + tests + evidence (trajectory parity UR-RES-01, acceptance proofs) |
| 2 | `f04acd6bc` | UR-G/UR-B `1599c77d0` | evidence (фиксация кандидата `6d10d35de`) |
| 3 | `b63b6adf2` | UR-G/UR-B `2837a719f` | evidence (cleanup record, retention worktree) |
| 4 | `4638fdc4f` | UR-G/UR-B `8929f04cb` | product + tests + evidence (URGB-R1-F1: стадия доставки на всех терминальных путях) |
| 5 | `86dc25755` | — | version wave 2.58.250 |
| 6 | `9b1071bff` | — | assembly v1 (заменён этим документом; delta-review r1 отметил устаревшие числа) |
| 7 | `6cb4026f6` | UR-G/UR-B `dcbe2bf18` | product + tests + evidence (URGB-DR1-F1/F2: честный исход реакции, легальный mca-13 контекст) |
| 8 | — | — | этот переписанный текст сборки (v2, только `plans/`) |

Cherry-pick прошли без конфликтов; ручных правок кода среза при сборке не
потребовалось. Порядок — ровно как в ветке среза (линейный). Ветка среза несёт
уже отслеживаемые evidence-файлы `ur-gb-rows-2026-11-26.md`,
`ur-gb-retention-2026-11-26.json`, `ur-gb-rows-review-r1.md` и (с `dcbe2bf18`)
`ur-gb-rows-review-r2.md` — все взяты как часть reviewed tip; новых
evidence-файлов сверх среза не создавалось.

## 2. Файлы среза: побайтовая идентичность

Срез затрагивает **8 файлов** (`git diff --name-status af8de2ac6..dcbe2bf18`:
2 product, 2 теста, 4 evidence). Проверка механическая (`git rev-parse`
blob'ов на интеграционном кандидате `6cb4026f6` против tip'а среза):

| файл | blob (12) 6cb4026f6 | blob (12) dcbe2bf18 |
|---|---|---|
| `services/direct_chat_service.py` | `6434483550d7` | `6434483550d7` |
| `services/turn_trace.py` | `a286142891a7` | `a286142891a7` |
| `tests/test_ur_acceptance_trace.py` | `d8a5c6ca0f57` | `d8a5c6ca0f57` |
| `tests/test_ur_search_first.py` | `7355d54812ab` | `7355d54812ab` |
| `plans/features/unified-reply/evidence/ur-gb-rows-2026-11-26.md` | `e068642edd85` | `e068642edd85` |
| `plans/features/unified-reply/evidence/ur-gb-retention-2026-11-26.json` | `674211f3b960` | `674211f3b960` |
| `plans/features/unified-reply/evidence/ur-gb-rows-review-r1.md` | `f9e6cdde272e` | `f9e6cdde272e` |
| `plans/features/unified-reply/evidence/ur-gb-rows-review-r2.md` | `feee17e3e394` | `feee17e3e394` |

Итог: **8/8 файлов байт-в-байт равны blob'у среза**; `git diff --quiet
dcbe2bf18 HEAD -- <каждый из 8 файлов>` → rc 0, `git diff --stat dcbe2bf18 HEAD
-- <8 файлов>` пуст. Полный `git diff --stat dcbe2bf18..HEAD` содержит только
32 файла version wave и этот документ (версия 2.58.250 против 2.58.249 в срезе).

## 3. Version wave 2.58.250 (32 файла / 35 строк, без изменений)

Волна осталась ровно той же, что и в сборке v1; новых правок версии не было.
Токен версии заменён байт-в-байт, BOM/переводы строк сохранены.

- Коммит `86dc25755`: `git diff --shortstat 86dc25755^ 86dc25755` =
  **32 files changed, 35 insertions(+), 35 deletions(-)**.
- Обратная замена (`2.58.250 → 2.58.249`; для `config/settings.py` — обратная
  подстановка головы `APP_VERSION`-строки) даёт **byte-в-byte blob pre-wave**:
  **32/32 файлов reverse-byte-identical**, расхождений 0 (проверено повторно на
  новом кандидате).
- После волны ни один из её 32 файлов не менялся: пересечение
  `git show --name-only 86dc25755` с `git diff --name-only 86dc25755..HEAD`
  пусто (0 файлов) — reverse-byte-проверка на HEAD остаётся валидной.
- `config/settings.py` — 1 строка (`APP_VERSION = "2.58.250"` + релизная заметка
  выпуска, запись 2.58.249 стала `Prior (26.11.2026): ...`), BOM сохранён,
  3665 CRLF / 3665 LF; `plans/docs/param-registry-round1025.meta.md` — 1
  (`APP_VERSION`); 4 × `tests/js/*` — 4; 24 py-файла пинов — 25
  (`test_webapp_round1026_polygon.py` 2); `tools/ui_mod_acl_m4b2_status_e2e.py`
  3 + `tools/ui_mod_acl_m4b3_status_e2e.py` 1.
- JS-пины `?v=` в `web/index.html` — шаблон `__APP_VERSION__` (не литерал),
  отдельных правок не требуют.
- Исторические комментарии `release 2.58.249` в `tests/test_round1025_f8_registry.py`
  (2 строки про UR-F-дельту) не bump'ились: они описывают уже выпущенный релиз.

## 4. Корректива F1/F2, включённая в кандидат

Срез `dcbe2bf18` закрывает оба блокера delta-review r1 в той же зоне
(`services/direct_chat_service.py`, `services/turn_trace.py`), версия не меняется.

**URGB-DR1-F1 — честный исход реакции.** `_execute_initiative_react` раньше
возвращал `status="reacted"` независимо от `reaction_outcome`, и ветка реакции
писала `delivery={"outcome":"success"}` при `forbidden`/`rate_limited`/`unknown`.
Теперь:
- успех реакции — **только** `reaction_outcome == REACTION_OK`; вызывается
  `_initiative_finish(outcome="reacted", delivery={"outcome":"success",
  "channel":"react"})`;
- при любом ином исходе — честный stop: `note_decision(outcome="silent",
  reason_code=<код исхода>)`, `status="silent"`, `reaction_outcome` сохранён в
  результате, в трассе нет `delivery:success`; `_finish_initiative_react`
  различает ветки по фактическому исходу, а не только по `status`.
- `REACTION_OK` импортирован из модуля реакции (нет второго строкового канона
  "ok" в новом коде).

**URGB-DR1-F2 — контекст хода только с легальным mca-13 исходом.** Ранее
`mca_events.build_event` возвращал `None` для `error`/`reacted`, а
`emit_context` ставил `_context_emitted=True` **до** эмиссии — терминальное
событие молча терялось на этих путях. Теперь:
- `services/turn_trace.py::emit_context` возвращает принятое событие или
  `None`; флаг `_context_emitted` закрывается только принятым событием, при
  отказе контракта — WARNING и открытый флаг (закрытие хода повторит эмиссию);
- `direct_chat_service._TRACE_OUTCOMES` приводит смысловые коды хода к словарю
  `mca_events.ALL_OUTCOMES`: `error → failed`, `reacted → success` (доставленная
  реакция — успешный ход), остальные тождественны; неизвестный код даёт
  `failed`, а не потерю события;
- `_initiative_finish` проверяет `built is None` и логирует `[f6] initiative
  context event not persisted`; тесты `test_ur_acceptance_trace.py` теперь
  проверяют `built is not None` и persisted-событие (а не только kwargs
  запроса), включая путь отказа реакции.

Тесты среза на новом кандидате: `tests/test_ur_acceptance_trace.py` — **7 passed**
(было 6), `tests/test_ur_search_first.py` — **8 passed**.

## 5. Производные артефакты: переэмиссия не требуется

- `services/param_catalog.py`: blob `2ffce87a15d9` и на базе `af8de2ac6`, и на
  HEAD; `git diff --stat af8de2ac6 HEAD -- services/param_catalog.py` и
  производные (`param-registry-round1025.tsv`, `screen-map-round1025.md`) —
  пусто (meta меняет только строку версии).
- `python tools/gen_param_registry_round1025.py --check` → **CHECK OK**:
  реестр 659 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны.
- Счётчики: REGISTRY **659** / GROUPS **121** / TAB_RULES **23**, Settings
  **477**, `APP_VERSION` **2.58.250** — идентично базе по структуре, новых
  флагов/ParamSpec нет; `config/settings.py` изменён только строкой версии.

## 6. Тесты на точном код-кандидате `6cb4026f6`

Прогон в этом worktree, интерпретатор `C:\Code\Python\adminbot\.venv`
(Python 3.12, pytest), `-p no:cacheprovider`. Единственный коммит после
код-кандидата — этот текст сборки (код не меняется).

| набор | passed | failed |
|---|---|---|
| `tests/test_ur_acceptance_trace.py` + `tests/test_ur_search_first.py` | **15** (7 + 8) | 0 |
| соседние наборы r2: `asap8_f6_initiative`, `ur_d_writer`, `ur_e_speech`, `ur_turn_engine`, `ur26_init_fc_payloads`, `ur_b_live_wiring`, `mod_acl_ux_01_m21_gates`, `nostalgia_proactive_recall` | **135** | 0 |
| `direct_chat` + `ur_ui_effective_config` + `rlr_observability` | **203** | 0 |
| `evol_social_frame` + `evol_evidence_routing` + `soul1_style_payload` | **143** | 0 |
| пины версии: 24 py-файла волны (включая `test_round1025_f8_registry`) | **855** | **5** (pre-existing) |
| JS: 4 изменённых `tests/js/round1025_hotfix*_test.js` | 4/4 `*-OK` | 0 |
| структурное: `node --check` (`web/app.js`, 2 JS из волны) | 3/3 rc 0 | 0 |
| структурное: `py_compile` всех 31 изменённых `.py` (base..HEAD) | 31/31 ok | 0 |
| структурное: `git diff --check` (worktree и диапазон base..HEAD) | rc 0 / rc 0 | 0 |
| структурное: `tools/gen_param_registry_round1025.py --check` | CHECK OK | 0 |

### 6.1 Падения: доказательство идентичности базе `af8de2ac6`

Списки `FAILED` сравнены построчно с прогонами базы (`Compare-Object`, 0
различий в каждом наборе).

| набор | на кандидате `6cb4026f6` | на базе `af8de2ac6` |
|---|---|---|
| `asap8_initreply_binding` + `initiative_coordination` + `mca09_intents_block_e_round1040` + `initiative_delivery_telemetry` | **25 failed / 78 passed** | **25 failed / 78 passed**, тот же список |
| `nostalgia_worker` + `asap5_integration_w3` | **20 failed / 85 passed** | **20 failed / 85 passed**, тот же список |
| 24 pin-файла версии | **5 failed / 855 passed** | **5 failed / 855 passed**, тот же список |

Пять падений пинов (идентичны базе): `test_tool_coordinator_round1026::
TestBounds::{test_forbidden_paths_out_of_diff,test_canon_twelve_tools}`,
`test_unified_image_request_round1026::{TestToolDescriptionU21::
test_canon_unchanged,TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline}`,
`test_webapp_f9_round1025::TestInvariants::test_secrets_count_28`.
Новых падений относительно базы нет; ни один пин не подгонялся.

Известный долг базы (`BACKLOG_ONLY`, не контракт релиза): устаревшие
пин-каноны `tool_coordinator`/`unified_image_request`, счётчик секретов
`webapp_f9`, падения `initiative_*`/`nostalgia_worker`/`asap5_integration_w3`.

## 7. Manifest dry-run

Прогон `python tools/release_manifest.py --dry-run` на чистом дереве
код-кандидата `6cb4026f6`. В worktree нет `.deploy/release.json`, поэтому для
`previous_*` использован локальный untracked seed с прод-идентичностью
`af8de2ac6 / 2.58.249` (удалён сразу после прогона; поля не выдуманы):

```json
{
  "deployed_at": "2026-11-25T22:29:17.421361Z",
  "deployed_sha": "6cb4026f6b8bb9dc1fcb9fed2d17f98be1957e7b",
  "dirty_tracked": false,
  "effect": "deploy",
  "previous_sha": "af8de2ac6e59f4c0b899c0c839f02258a9e02236",
  "previous_version": "2.58.249",
  "release_branch": "release/ur-gb-2.58.250",
  "schema": 1,
  "version": "2.58.250"
}
```

Инструмент берёт `deployed_sha` из `git rev-parse HEAD` момента прогона. Этот
документ — единственный коммит после код-кандидата (меняет только `plans/`),
поэтому повторный dry-run на финальном tip'е ветки даёт те же поля с
`deployed_sha` = фактический HEAD; подтверждающий прогон выполнен после
evidence-коммита и приведён в handoff сборки. Штатная запись манифеста —
DevOps на сервере, где `deployed_sha` = HEAD выложенного checkout.

Контракт выкладки: **DDL 0, миграций 0, новых флагов 0, новых store/endpoint/
планировщиков нет**; `migrations/`, `models/`, `services/pg_db.py`,
`services/database.py` не затронуты (0 файлов в diff base..HEAD);
`config/settings.py` изменён только строкой версии; схема v48.

## 8. Откат

- **Только код**, `git`-откат на `af8de2ac6e59f4c0b899c0c839f02258a9e02236`
  (2.58.249), `tools/release_manifest.py --effect rollback`. DDL 0, миграций 0,
  новых флагов 0, формат данных не меняется.
- Промпты не затрагиваются ни срезом, ни волной версии (canon-файлы не
  изменены); сохранённые пользовательские правки промптов не страдают.
- Данные production не мигрируются, восстановление БД не требуется.

## 9. Что осталось непроверенным (честно)

- **Delta re-review r2 нового кандидата `6cb4026f6` не проводился** — это
  независимая роль; сборка лишь утверждает, что блокеры `URGB-DR1-F1/F2`
  адресованы срезом `dcbe2bf18` и подтверждаются тестами среза (7 passed,
  включая путь отказа реакции и `built is not None`).
- Effective-state прода (фактическая версия `/healthz`, схема, identity
  деплоя, диск) — DevOps после выкладки; production здесь не затрагивался.
- Визуальный контракт: срез меняет сервисный слой и trace, не UI; `web/*` не
  изменён, поэтому повторный Playwright/Browser Use не требовался.
- Реальное поведение моделей на живых чатах — не инженерный критерий приёмки
  (`BOUNDED ACCEPTANCE`), проверяется при эксплуатации.

## 10. Очистка

- Временный `.deploy/release.json` seed удалён сразу после dry-run; каталог
  `.deploy/` удалён (`git status --porcelain` пуст).
- Базовый worktree для доказательства pre-existing (прогоны на `af8de2ac6`)
  удалён после сборки v1; списки `FAILED` сохранены вне репозитория и
  использованы повторно для сравнения.
- Вспомогательные скрипты bump/verify — в `%TEMP%\opencode`, репозиторий не
  затрагивали.
- Новых файлов вне среза, version wave и этого документа нет. Deploy/merge в
  master/SSH не выполнялись.
