# Release 2.58.258 — UR-BAN-02 (адаптивная цепочка: физический предел шагов)

- **Дата сборки:** 2026-11-27
- **Роль:** Builder (сборка релиза, без деплоя)
- **Основание:** независимое ревью UR-инкремента `APPROVED_FOR_RELEASE_PREPARATION`
  (0 blocking, 5 nonblocking; REV-01/05 закрыты, REV-03/04 — backlog)
- **База (deployed):** `9516c912554bb1062f62a63b6689f418c1cb5425` = 2.58.257
  (прод подтверждён read-only: `healthz {"status":"ok","version":"2.58.257"}`,
  `git rev-parse HEAD` = 9516c9125; см.
  `../ur-e-accept-2026-11-27/raw/prod-cleanup-verification.txt`)
- **Ветка:** `release/ur-ban02-2.58.258`
- **Кандидат (reviewed):** `8a41c32c032aa2b5129722c3bfcd93b9651cec56`
  (`feat/ur-e-accept-2026-11-27`: `87215cb4a` тест-онли батч → `aeac505b4`
  UR-BAN-02 → `8a41c32c0` правки R1)
- **Tip релиза (bump):** `50df797da6f20ba4599bec7c46f43067c8a7d00e`
- **Evidence-коммит** идёт отдельно поверх (`plans/` only, прецедент
  `release-2.58.249/250`). Если деплоится его tip, `deployed_sha` = этот SHA,
  но продуктовые байты идентичны `50df797da` (проверяется
  `git diff 50df797da..<tip> -- services/` = пусто); поэтому manifest dry-run
  ниже снят на `50df797da`, а боевой манифест пишет DevOps на сервере уже по
  фактическому HEAD.
- **Tree релиза:** см. `raw/identity.txt` (`head`/`tree`), дерево чистое
  (`dirty_tracked=false` в манифесте)
- **Статус:** ASSEMBLED, не деплоился. Деплой — DevOps/Orchestrator.

## 1. Состав релиза

Мерж только fast-forward: `9516c9125` → `8a41c32c0` (`git merge --ff-only`),
reviewed-код не менялся; сверху один version-only bump-коммит `50df797da`.

Изменения относительно выложенной базы (66 файлов, `raw/changed-files.txt`):

| Категория | Файлы | Суть |
|---|---|---|
| **Продукт** | `services/direct_execution.py` (1 файл) | UR-BAN-02: физический предел шагов adaptive-цепочки (`max_steps = explicit_steps or safety_steps`, `safety_steps = orchestrator_budget_for_window(window).max_steps`, пол 4 / потолок 16), честный `stop_reason="max_steps"`, `chain_meta["max_steps"]` = фактический предел; fuse/дедлайны не вводились |
| Тесты | 5 файлов + фикстура | `test_unified_reply_ur_b_search_first.py` (+8 тестов), `test_bgs05_budgets.py` (2 теста под новый контракт), `test_ur_c_sched.py` (снятый schema-pin), `test_webapp_js_unit.py` + `tests/js/ur_ban08_ui_test.js`, `tests/test_ur_17_historical_dialog.py` + `tests/fixtures/unified_reply/historical_dialog_2026_11_04.json` |
| Bump | 29 файлов (`config/settings.py`, `plans/docs/param-registry-round1025.meta.md`, 24 test-файла, 2 tools) | 2.58.257 → 2.58.258 |
| Evidence | `plans/features/unified-reply/evidence/ur-e-accept-2026-11-27/**` | доказательства инкремента (не продуктовые) |

Не входит: `web/api/routes.py`, `services/database.py`, `services/*scheduler*`,
`web/app.js`, промпты — не менялись (см. п. 3–5).

## 2. Bump — version-only (доказано)

```
raw/bump-verify.txt
changed lines: -34 / +34
pairs differing ONLY by version: 34
pairs with other changes: 0
files in commit: 29
VERSION-ONLY BUMP: OK (34 pairs / 29 files)
```

- Набор пинов = ровно список файлов предыдущего релизного bump-коммита
  `9516c9125` (критерий проекта), 29 файлов / 34 вхождения — те же числа, что
  у прошлого бампа.
- `config/settings.py`: `APP_VERSION = "2.58.258"` (единственное изменение в
  файле; CRLF-окончания сохранены, иначе файл дал бы 3665-строчный diff).
- Провенанс-файлы **намеренно** остаются на 2.58.257 (это версия, выложенная в
  момент измерения): `tests/fixtures/unified_reply/historical_dialog_2026_11_04.json`,
  `tests/test_ur_17_historical_dialog.py`, evidence `ur-e-accept-2026-11-27/**`.
- `plans/features/vmq-onto-01/**/next2final-embeddings.json` содержит строку
  `2.58.258` независимо от этого релиза (чужая линия, не трогали).

## 3. Routes-пин (ROUTES_SHA256_F11) — re-pin не нужен

```
raw/routes-pin.txt
routes_sha256_head=6b5391e5d51af52cb4c49f9452ca2c2d30f8a2a3660ca7cb6d94be4623f6aa30
routes_sha256_base_9516c9125=6b5391e5d51af52cb4c49f9452ca2c2d30f8a2a3660ca7cb6d94be4623f6aa30
routes_byte_identical=True
ROUTES_SHA256_F11=6b5391e5d51af52cb4c49f9452ca2c2d30f8a2a3660ca7cb6d94be4623f6aa30
pin_matches_head=True
decision=no re-pin (routes.py unchanged; route-set/inventory delta 0)
```

Пин-тесты (`test_round1025_f8_registry.py`, `test_asap7_cover_preview.py`,
`test_mca17c_*`, `test_mca23_planned_vs_actual.py`) — зелёные в наборе ниже.

## 4. DDL Δ = 0

```
raw/ddl-check.txt
changed files total: 66
changed DDL/schema files: []
migration steps: 49 max version: 49
self_diag_samples version: 49
{"ddl_delta": 0}
```

`services/database.py`, `services/pg_db.py`, `migrations/` не менялись; прод
уже на v49 (выложен 2.58.257) → миграций при деплое нет, откат кода безопасен
по схеме.

## 5. Прогоны

| Набор | Команда (в worktree релиза) | Результат |
|---|---|---|
| Пины релиза (25 файлов) | `py -m pytest <25 files> -q` | **864 passed, 6 failed** — все 6 предсуществующие (доказано на чистой базе, `raw/tests-pins-base.txt`) |
| Затронутая зона (36 файлов, `direct_execution`/`tool_loop`) | `py -m pytest <36 files> -q` | **1062 passed, 9 failed** — все 9 предсуществующие (те же node id, что на кандидате и на базе) |
| UR-инкремент | `pytest ur_c_sched+per_chat+clock+ur_17+acceptance_trace` + `TestAdaptivePhysicalStepBound` | **85 passed** (`raw/tests-ur.txt`) |
| JS витрины «Прямых ответов» | `node tests/js/ur_ban08_ui_test.js` | `UR-BAN08-UI-OK` (`raw/tests-ur-js.txt`) |

**Предсуществующие red-ы набора пинов** (все воспроизведены на чистой базе
`9516c9125` в отдельном detached-дереве, `raw/tests-pins-base.txt: 6 failed`):

1. `test_mca17c_invariants_round1047.py::test_no_ddl_catalog_ks_tools_delta` —
   устаревший schema-pin `assert 49 == 48`.
2. `test_tool_coordinator_round1026.py::TestBounds::test_forbidden_paths_out_of_diff`
3. `test_tool_coordinator_round1026.py::TestBounds::test_canon_twelve_tools`
   (`18 != 17` инструментов — канон устарел).
4. `test_unified_image_request_round1026.py::TestToolDescriptionU21::test_canon_unchanged`
5. `test_unified_image_request_round1026.py::TestBoundsA3::test_forbidden_paths_out_of_diff_vs_baseline`
6. `test_webapp_f9_round1025.py::TestInvariants::test_secrets_count_28`
   (34 секрета против пина 32).

**Предсуществующие red-ы затронутой зоны** (идентичны кандидату и базе,
подробности в `raw/tests-affected.txt`): `test_addtr_tools_minifix.py::test_l1_seam_announce_then_execute_once`,
5 × `test_direct_fallback_recompose_asap32.py` (`DirectChatService.llm`,
`fb_retries(sent)`, `LLMError: primary down`), 2 ×
`test_selfdiag_corrective_research.py`, `test_ur_f_inspector_step1.py::test_identical_quotes_credit_only_the_surviving_item`.

Известный `tests/test_webapp_js_unit.py` (7 failed на базе/кандидате,
версионные пины `2.58.255`) в наборы релиза не входит как гейт; на релизном
дереве поведение то же (пины этих 4 JS-файлов относятся к 2.58.255 и не
обновлялись этим релизом — backlog REV-03/04-класса, не блокер).

## 6. Manifest dry-run

Затравка «предыдущего» манифеста: в релизном worktree на базе `9516c9125`
однократно выполнен `tools/release_manifest.py` (не `--dry-run`), что записало
`.deploy/release.json` с ровно теми значениями, что держит прод
(`deployed_sha=9516c9125`, `version=2.58.257`) — так `previous_*` в dry-run
отражает фактический переход. `.deploy/` не отслеживается git и в коммит не
входит; боевой манифест пишет DevOps на сервере перед рестартом.

```
raw/manifest-deploy.json
{
  "deployed_at": "2026-11-27T11:11:35.656584Z",
  "deployed_sha": "50df797da6f20ba4599bec7c46f43067c8a7d00e",
  "dirty_tracked": false,
  "effect": "deploy",
  "previous_sha": "9516c912554bb1062f62a63b6689f418c1cb5425",
  "previous_version": "2.58.257",
  "release_branch": "release/ur-ban02-2.58.258",
  "schema": 1,
  "version": "2.58.258"
}
```

`raw/manifest-rollback.json` — тот же `--dry-run --effect rollback`
(deployed_sha/version те же, `effect=rollback`; `previous_*` = 9516c9125 /
2.58.257, то есть откат возвращает на выложенную версию).

**Rollback = code-only:** DDL Δ=0 (п. 4), схема на проде уже v49, поэтому
откат — `git checkout 9516c9125` (или `git pull` на предыдущий SHA) +
`systemctl restart admin_bot`; миграции/данные не откатываются и не нужны.

## 7. План выката (НЕ выполнен, для DevOps)

```bash
cd /var/www/admin_bot
git fetch --prune origin
git status -sb && git rev-parse HEAD          # ожидается 9516c9125
git pull --ff-only                             # до 50df797da (ветка релиза)
python tools/release_manifest.py               # effect=deploy, previous=9516c9125
sudo systemctl restart admin_bot
curl -fsS http://127.0.0.1:8000/healthz        # ожидается version 2.58.258
python manage.py disk audit && python manage.py disk cleanup --apply   # P0-PROD-DISK-01
```

Проверить после рестарта: `healthz.version=2.58.258`, `deployed_sha=50df797da`,
`.deploy/release.json` (`previous_sha=9516c9125`), отсутствие ошибок схемы в
логах (DDL не ожидается), свободное место.

Наблюдаемый эффект UR-BAN-02 на проде: в логах `[direct-exec] adaptive chain
budget | … max_steps=<4…16>` и `adaptive chain done | reason=max_steps` вместо
неограниченного роста при «новый запрос каждый раунд».

## 8. Ограничения

- Деплой не выполнялся; прод не затрагивался (только read-only проверки).
- Модельное поведение (качество исследования при пределе) — live-наблюдение;
  детерминированно доказаны только предел, честная причина останова и
  сохранение материала.
- Предел шагов — анти-цикл, не дедлайн: длинная цепочка дорогих шагов по
  времени по-прежнему не ограничена (owner-политика сохранена).
- 6 red-ов набора пинов и 9 red-ов затронутой зоны предсуществующие на базе;
  они не связаны с релизом и остаются backlog'ом.

## Артефакты

`raw/`: `identity.txt`, `changed-files.txt`, `routes-pin.txt`, `ddl-check.txt`,
`bump-verify.txt`, `tests-pins.txt`, `tests-pins-base.txt`, `tests-affected.txt`,
`tests-ur.txt`, `tests-ur-js.txt`, `manifest-deploy.json`,
`manifest-rollback.json`, `SHA256SUMS`.
