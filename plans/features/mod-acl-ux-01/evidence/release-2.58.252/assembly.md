# Сборка 2.58.252 — MOD-ACL-UX-01 M1-C (UI-состояния доступа + единая точка принуждения текста промпта)

- **Роль:** Builder, локальная сборка релиза. **Деплоя, SSH, merge в master,
  push force нет.** Deploy/effective-state — DevOps после отдельного handoff.
- **База (production 2.58.251):** `ffdc6eadf38b479509b68ba653b6b0b50200774b`.
- **Ветка:** `release/mod-acl-m1c-2.58.252` от `ffdc6eadf`, registered worktree
  (`WorkspaceData/worktrees/c742e4de9e92c489/mod-acl-ux-01-1e46be007668-f68d0448`,
  unit `m1c-release`). Интеграция — линейный cherry-pick, **без merge-коммитов**.
- **Срез:** `MOD-ACL M1-C`, ветка `feat/mod-acl-m1c`, tip
  `681bf976d36997360cb2a1450a4e294984293a1b` (13 коммитов от базы: код
  `b3d4b95de`, `bd9eb766d`, `ac8d73862`, `25538620e`, `aa80d9654`, `a94005981`;
  остальные — evidence/tests). Ревью r6:
  `plans/features/mod-acl-ux-01/evidence/m1/m1c-review-r6.md`, sha256
  `a074ab48f977cea66e6974f744c34242b51805486cd62d174422ebafed2d9fef`
  (пересчитан в planning-checkout, совпал), вердикт
  `APPROVED_FOR_RELEASE_PREPARATION`.
- **Строки:** `MAC-S10-13` — BINDABLE; `MAC-S4-171` — READY_FOR_LIVE;
  `MAC-S4-172` — остаётся PENDING (без изменений от r1/r6).

```json
{
  "release": "2.58.252",
  "base": {"sha": "ffdc6eadf38b479509b68ba653b6b0b50200774b", "version": "2.58.251"},
  "slice": {
    "id": "MOD-ACL-UX-01 M1-C",
    "branch": "feat/mod-acl-m1c",
    "source_tip": "681bf976d36997360cb2a1450a4e294984293a1b",
    "source_tree": "ed59c13e1d682d590a6d8b7b051bb04f56cdeddd",
    "review": {"artifact": "plans/features/mod-acl-ux-01/evidence/m1/m1c-review-r6.md",
               "sha256": "a074ab48f977cea66e6974f744c34242b51805486cd62d174422ebafed2d9fef",
               "verdict": "APPROVED_FOR_RELEASE_PREPARATION"}
  },
  "integration": "linear cherry-pick: slice (13 git-pristine, author/dates kept) + version wave (1)",
  "slice_commits": 13,
  "pre_bump_head": "fd6eb06577b5f18222560f56381cc58eef477d58",
  "pre_bump_tree": "ed59c13e1d682d590a6d8b7b051bb04f56cdeddd",
  "bump_commit": "5f09390492b254bd129edc68620c1cbece069f0c",
  "bump_tree": "95af313825739521fcd12f6eca23b7a90217b26b",
  "evidence_commit": "tip of release/mod-acl-m1c-2.58.252 (this file)",
  "delta_vs_base": {"files": 80, "insertions": 6324, "deletions": 188}
}
```

`delta_vs_base` = `git diff --shortstat ffdc6eadf 5f0939049`: 48 файлов среза +
32 файла version wave, пересечения нет (`slice ∩ bump = 0`). Evidence-коммит
добавляет один файл `plans/`.

## 1. Порядок интеграции

| # | SHA (новая ветка) | Источник `feat/mod-acl-m1c` | Тип |
|---|---|---|---|
| 1 | `b3d4b95de` | `b3d4b95de` | UI-состояния 401/403/404/503, payload (MAC-S4-171/172) |
| 2 | `9cf3dff99` | `9cf3dff99` | evidence стенда |
| 3 | `a6e55ce70` | `a6e55ce70` | evidence офлайн-стенда |
| 4 | `bd9eb766d` | `bd9eb766d` | промпт по матрице ресурса (F02) |
| 5 | `cc7491b35` | `cc7491b35` | evidence F01/F02 |
| 6 | `ac8d73862` | `ac8d73862` | speech/витрина мемов под общей матрицей |
| 7 | `55948c275` | `55948c275` | evidence R2 |
| 8 | `25538620e` | `25538620e` | choke point текста промпта |
| 9 | `73c38477b` | `73c38477b` | evidence choke point |
| 10 | `aa80d9654` | `aa80d9654` | кэш собранного текста не в обход матрицы (r4) |
| 11 | `0a110a173` | `0a110a173` | evidence R4 |
| 12 | `a94005981` | `a94005981` | AST-инвариант: точечные формы импорта (r5) |
| 13 | `681bf976d` | `681bf976d` | evidence R5 |

Cherry-pick выполнен диапазоном без правок; авторство/даты коммитов сохранены.
После волны `HEAD^{tree}` = `681bf976d^{tree}` = `ed59c13e1…`: дерево
**байт-в-байт** равно дереву среза до bump.

## 2. Byte identity среза (48 файлов)

Все файлы, которые трогает срез (`git diff --name-status ffdc6eadf 681bf976d`
= 48: 27 добавлено, 21 изменено), после version wave имеют ровно те же blob'ы,
что и на `681bf976d`. Проверено `git rev-parse <tip>:<path>` для tip и HEAD.
`git diff --name-only 681bf976d HEAD` на bump-коммите `5f0939049` = **ровно 32
файла version wave**, `slice_changed = []`; evidence-коммит добавляет
только этот файл (`plans/`, не входит в срез);
пересечение `slice ∩ bump = 0`.

| файл | blob@681bf976d | blob@HEAD |
|---|---|---|
| plans/…/m1/m1c/README.md | `8e7ef5ca9439` | `8e7ef5ca9439` |
| plans/…/m1/m1c/base-js-suite.txt | `02085babddc1` | `02085babddc1` |
| plans/…/m1/m1c/candidate-access_403-390x844.png | `35760191fc1a` | `35760191fc1a` |
| plans/…/m1/m1c/candidate-audit_known_fields-1440x900.png | `d97c90cf1c05` | `d97c90cf1c05` |
| plans/…/m1/m1c/candidate-auth_missing-390x844.png | `4cf00faab79e` | `4cf00faab79e` |
| plans/…/m1/m1c/candidate-e2e.txt | `d13544828335` | `d13544828335` |
| plans/…/m1/m1c/candidate-js-suite.txt | `688e4fa6e156` | `688e4fa6e156` |
| plans/…/m1/m1c/choke-point.md | `2b82bc1307f1` | `2b82bc1307f1` |
| plans/…/m1/m1c/probe-prompt-chat-acl.txt | `eb586098d2a7` | `eb586098d2a7` |
| plans/…/m1/m1c/probe_prompt_chat_acl.py | `c2a08663951f` | `c2a08663951f` |
| plans/…/m1/m1c/python-suites.txt | `96bd00864f27` | `96bd00864f27` |
| plans/…/m1/m1c/r4_cache_probe.py | `4eab4dd2e35d` | `4eab4dd2e35d` |
| plans/…/m1/m1c/r5_ast_redgreen.py | `e6d26260b268` | `e6d26260b268` |
| plans/…/m1/m1c/red-base-e2e.txt | `26bbcb77c4ca` | `26bbcb77c4ca` |
| plans/…/m1/m1c/red-base-node.txt | `fb29fa777e25` | `fb29fa777e25` |
| plans/…/m1/m1c/red-choke-probe.txt | `82ac59b265fa` | `82ac59b265fa` |
| plans/…/m1/m1c/red-f02-view.txt | `b48eb4ff1a7c` | `b48eb4ff1a7c` |
| plans/…/m1/m1c/red-r2-speech.txt | `d5dd22914d3c` | `d5dd22914d3c` |
| plans/…/m1/m1c/red-r4-cache.txt | `404df9bafcdc` | `404df9bafcdc` |
| plans/…/m1/m1c/red-r5-ast.txt | `d415e4e1a6e7` | `d415e4e1a6e7` |
| plans/…/m1/m1c/redex_probe.py | `a2c75bd54c96` | `a2c75bd54c96` |
| services/access.py | `3bf957fcc87b` | `3bf957fcc87b` |
| services/capability_registry.py | `d8e0314640d9` | `d8e0314640d9` |
| services/chat_params.py | `9405cefe8af0` | `9405cefe8af0` |
| services/direct_chat_service.py | `bd58231afdea` | `bd58231afdea` |
| services/mca_authorial_speech.py | `0a90221bbb4a` | `0a90221bbb4a` |
| services/mca_expression.py | `5edca886a9ee` | `5edca886a9ee` |
| services/prompt_composer.py | `fb73d1455e3e` | `fb73d1455e3e` |
| services/prompt_factory.py | `2db4e47a5b73` | `2db4e47a5b73` |
| services/prompt_migrations.py | `e7288f9b39e4` | `e7288f9b39e4` |
| services/prompt_readback.py | `e19ac860d2f7` | `e19ac860d2f7` |
| services/prompt_registry.py | `0f4ce403dd4d` | `0f4ce403dd4d` |
| services/prompt_release_policy.py | `b382742126fc` | `b382742126fc` |
| services/prompt_text.py | `a2fe44b243fb` | `a2fe44b243fb` |
| services/style_policy.py | `d713564f14f9` | `d713564f14f9` |
| tests/js/mod_acl_ux_m1c_ui_states_test.js | `b76cb4b57ded` | `b76cb4b57ded` |
| tests/test_mod_acl_ux_01_m1c_prompt_chat_acl.py | `14a45ed11370` | `14a45ed11370` |
| tests/test_mod_acl_ux_01_m1c_prompt_text_invariant.py | `070fdf0598b2` | `070fdf0598b2` |
| tests/test_webapp_access_write_safety.py | `ae054cf61a71` | `ae054cf61a71` |
| tests/test_webapp_deps.py | `86565d9562a3` | `86565d9562a3` |
| tools/ui_mod_acl_m1c_e2e.py | `5e4a410064d7` | `5e4a410064d7` |
| web/api/deps.py | `77473021fcbc` | `77473021fcbc` |
| web/api/prompt_access.py | `f567e6abc05c` | `f567e6abc05c` |
| web/api/routes.py | `106d683eed7c` | `106d683eed7c` |
| web/api/speech.py | `9579099a9ae8` | `9579099a9ae8` |
| web/app.js | `140a0dd6f85e` | `140a0dd6f85e` |
| web/app.py | `7e23e45b6a85` | `7e23e45b6a85` |
| web/index.html | `6eeeca285ee3` | `6eeeca285ee3` |

Итого: **48/48 blob'ов идентичны** (`files=48 identical=48`).

## 3. Version wave 2.58.252 (32 файла / 35 строк)

Только версии; записан коммит `5f0939049`. `git diff --shortstat 1647fe132^..HEAD`
для bump-шага → **32 файла, 35 insertions, 35 deletions** (`config/settings.py`
— 1 строка: pin `APP_VERSION = "2.58.252"` + релизная заметка 2.58.252 в существующей
цепочке `Prior (…)`; `plans/docs/param-registry-round1025.meta.md` — 1;
4 `tests/js/*` — 4 (regex-пины `2\.58\.252`); 24 py-теста — 25
(23 × 1 + `test_webapp_round1026_polygon.py` 2); `tools/ui_mod_acl_m4b2_status_e2e.py`
3 + `tools/ui_mod_acl_m4b3_status_e2e.py` 1). BOM/переводы строк сохранены
(`config/settings.py`: BOM `EF BB BF`, 3665 CRLF / 3665 LF / 0 bare-CR — как
на базе).

**Обратная замена — byte-identical 32/32.** Обратное применение ровно внесённой
дельты (пины `2.58.252 → 2.58.251`, удаление вставленного сегмента заметки
2.58.252 в `config/settings.py`) даёт blob'ы, байт-в-байт равные `681bf976d`
для всех 32 файлов. JS-пины `?v=` в `web/index.html` — шаблон `__APP_VERSION__`
(не пинится); `web/index.html` входит только в срез (byte identity §2).

## 4. Производные артефакты: 0 diff

- `services/param_catalog.py` — **0 diff** (`git diff --numstat ffdc6eadf HEAD` пуст).
- F8: `plans/docs/param-registry-round1025.tsv`, `screen-map-round1025.md`,
  `widget-map-round1025.md` — **0 diff**; `param-registry-round1025.meta.md` —
  ровно `1 1` (строка `APP_VERSION`, часть version wave).
- Frozen-фикстуры: `tests/fixtures/round1025/f8_baseline.json`,
  `catalog_baseline.json` — **0 diff**; hash-константы (`ROUTES_SHA256_F11`,
  `PG_DB_SHA256_B07`, `PARAM_CATALOG_SHA256_*`) **не правились**; в
  `tests/test_round1025_f8_registry.py` единственная изменённая строка —
  `assert APP_VERSION == "2.58.252"`.
- `python tools/gen_param_registry_round1025.py --check` → **CHECK OK**
  (реестр 659 == REGISTRY, карта полна, R17-чисто, TSV/map идемпотентны).
- Hand-edit производных не выполнялся.

## 5. Тесты на точном bumped tip `5f0939049`

Окружение: `C:\Code\Python\adminbot\.venv` (Python 3.12, pytest), `-p no:cacheprovider`,
cwd = worktree релиза. База для сравнения — чистый worktree `ffdc6eadf`
(`…-a833f258`).

| Прогон | Кандидат `5f0939049` | База `ffdc6eadf` | Совпадение FAILED |
|---|---|---|---|
| Lock+invariant (`test_mod_acl_ux_01_m1c_prompt_chat_acl.py` 60 + `…prompt_text_invariant.py` 37) | **97 passed** | файлов нет (новые) | n/a |
| Замок ACL отдельно | **60 passed** | — | n/a |
| AST/инвариант отдельно | **37 passed** | — | n/a |
| Регрессия 41 файл (prompt/ACL/RBAC/speech/composer/style/direct) | **11 failed, 1070 passed, 1 skipped** | 39 общих файлов: **11 failed, 973 passed, 1 skipped** | да: `Compare-Object` — 11 == 11, расхождений 0 |
| Prompt-набор 13 файлов (m1c-модули в алфавитном порядке — последними) | **2 failed, 345 passed, 2 skipped** | 11 общих файлов: **2 failed, 248 passed, 2 skipped** | да (2 == 2) |
| ACL/RBAC-набор 12 файлов | **365 passed** | **365 passed** | да (0) |
| Speech/registry-набор 17 файлов | **13 failed, 392 passed** | 16 общих файлов: **13 failed, 332 passed** | да (13 == 13); +60 passed = замок |
| Version-pin набор 24 py-файла | **7 failed, 853 passed** | **5 failed, 855 passed** | **нет: 2 кандидат-специфичных** — см. §5.2 (A-01) |
| UI unit: `node tests/js/mod_acl_ux_m1c_ui_states_test.js` | `MOD-ACL-M1C-UI-OK` | RED (4) — evidence среза | — |
| Browser harness: `python tools/ui_mod_acl_m1c_e2e.py` | `MOD-ACL-M1C-E2E-OK` (7 сценариев × 2 вьюпорта = 14) | `FAILED (11)` из 14 — evidence среза | — |
| JS-набор `tests/js/**`, `node <file>` | **133 PASS / 7 FAIL / 140 файлов** | **132 PASS / 7 FAIL / 139 файлов** | да: те же 7 FAIL; единственная разница — новый `mod_acl_ux_m1c_ui_states_test.js` PASS |
| `node --check web/app.js` + 4 js-пина + новый UI-тест | rc 0 (6/6) | — | — |
| `py_compile` всех 55 изменённых `.py` (срез+bump) | 55/55 ok | — | — |
| `git diff --check` (worktree) | rc 0 | — | — |

Провалы кандидата = провалы базы (11 в регрессии, 13 в speech, 2 в prompt)
идентичны по node id: `test_mod_acl_ux_01_m4_module_params::test_js_fixture_matches_live_contract`,
`test_prompt_field_audit::test_every_editable_prompt_has_reachable_surface`,
`test_evol018_prompt_audit::test_grep_audit_counts_are_stable`,
`test_soul1_composer_parity_off` ×3, `test_initiative_speech_layers_chat_overrides` ×4,
`test_soul1_capability_registry::test_every_l1_capability_is_known_to_registry`,
`test_asap_speech_i_matrix` ×9.

### 5.1 Состав наборов (воспроизводимо)

Исторические 40/41-файловые списки в артефактах среза записаны только числами
(`m1c-review-r6.md`: «r5 40-file set base=candidate 20 failed/1205 passed;
builder 41-file 22 failed/1096 passed/2 skipped»), списков файлов нет; поэтому
набор восстановлен по тем же доменам (prompt/ACL/RBAC/UI/speech/composer/style/
direct) и прогоняется целиком на обеих сторонах с побитовым сравнением FAILED:

41 файл: `test_mod_acl_ux_01_m1c_prompt_chat_acl`, `…m1c_prompt_text_invariant`,
`…m1_predicate`, `…m1_acl_false_403`, `…m21_gates`, `…m3_module_routes`,
`…m4_catalog`, `…m4_module_params`, `…m4c_acl_hardening` (9 MOD-ACL),
`test_access`, `test_chat_access`, `test_dm_access`,
`test_acl_global_admin_role_permission_gate`, `test_roles_admin`,
`test_chat_params`, `test_webapp_access_effective`, `test_webapp_access_matrix_read`,
`test_webapp_access_write_safety`, `test_webapp_rbac_ui`, `test_webapp_deps`
(11 ACL/RBAC/UI), `test_prompt_baseline`, `test_prompt_versioning_enforcement`,
`test_prompt_readback`, `test_prompt_migrations`, `test_prompt_history_pagination`,
`test_prompt_field_audit`, `test_evol017_prompt_history_ui`, `test_evol018_prompt_audit`,
`test_evol016_prompt_activation`, `test_web_prompts` (10 prompt),
`test_soul1_composer_layers`, `test_soul1_composer_parity_off`,
`test_soul1_core_composer_integration`, `test_soul1_style_policy`,
`test_soul1_style_payload`, `test_speech_inspector_exact`,
`test_speech_mobile_entry_contract` (7 speech/style), `test_direct_chat_prompts`,
`test_direct_context_composer_asap3` (2 direct), `test_initiative_speech_layers_chat_overrides`,
`test_soul1_capability_registry` (2 прочих).

Prompt-набор 13: 2 m1c + `prompt_baseline`, `prompt_versioning_enforcement`,
`prompt_readback`, `prompt_migrations`, `prompt_history_pagination`,
`prompt_field_audit`, `evol016_prompt_activation`, `evol017_prompt_history_ui`,
`evol018_prompt_audit`, `web_prompts`, `asap_prompt_history_integrity`.
ACL/RBAC 12: `access`, `chat_access`, `dm_access`,
`acl_global_admin_role_permission_gate`, `roles_admin`, `acl_audit`,
`acl_legacy_inventory`, `webapp_access_effective`, `webapp_access_matrix_read`,
`webapp_access_write_safety`, `webapp_rbac_ui`, `mod_acl_ux_m4c_acl_hardening`.
Speech/registry 17: `asap_speech_i_matrix`, `asap_speech_r3b_canon`,
`soul1_style_policy`, `soul1_style_payload`, `soul1_composer_layers`,
`soul1_core_composer_integration`, `expression_isolation_followup`,
`speech_inspector_exact`, `speech_mobile_entry_contract`,
`speech_simplify_2026_10_25`, `p0_persistfix_speech_chat_scope`,
`initiative_speech_layers_chat_overrides`, `mca08_character_speech`,
`mca08_style_form`, `meme_pipeline_api`, `meme_joke_speech_layers` + замок.
Version-pin 24: 24 py-файла из списка version wave (без 4 js, meta, settings, 2 tools).

### 5.2 Отклонения от base-идентичности (обязательно к решению)

**A-01 (release-blocking decision).** Два byte-freeze теста `web/api/routes.py`
краснеют **только на кандидате**:

- `tests/test_round1025_f8_registry.py::TestFrozenInvariants::test_routes_file_unchanged`
- `tests/test_mca17c_invariants_round1047.py::test_routes_py_byte_freeze_pin_intact`

Факт: `ROUTES_SHA256_F11 = 8f582128a2c7…4ac09a1`, фактический sha256
`web/api/routes.py` = `606899ac097d3a882b13693860dbe1dad7ad09816dcdd31630eaa88b16700663`
(401 160 B, blob `106d683eed7c`). На базе оба зелёные. Причина — разрешённый
срезом дифф `routes.py` (F02: `_prompt_require_view/edit` через
`prompt_access.decide`; витрина мемов). По инструкции сборки frozen hash
**не перепинен и не редактировался** (0 diff, ручных правок нет), поэтому
оба теста остаются красными. Прецедент проекта (`L-F11S-1`) — осознанный
re-pin константы одним отдельным проверенным дельта-коммитом. Решение
(перепин отдельным ревью-дельта или принятие как известного красного)
оставлено Orchestrator/Reviewer; в текущем кандидате — **не изменено**.

**A-02 (тест-гигиена, backlog).** `tests/test_mod_acl_ux_01_m1c_prompt_text_invariant.py`
оставляет заполненным кэш `param_permissions` (`reset_param_permissions_cache()`
вызывается только на входе, teardown нет). Если этот модуль выполняется **до**
`tests/test_evol017_prompt_history_ui.py::test_chat_isolation`, последний
получает ложный `403 {"detail":"нет права на prompts.factcheck_system_prompt"}`
(изолированно — 200 на обеих сторонах; после замка — 200; после инварианта — 403).
В алфавитном/полном порядке `test_evol017*` идёт раньше `test_mod_acl*`, поэтому
prompt-набор с m1c-модулями последними base-идентичен (§5). Влияния на продукт
нет; правка файла среза нарушила бы byte identity §2, поэтому вынесено в
follow-up (добавить teardown-reset).

## 6. Manifest dry-run

`tools/release_manifest.py --repo-root . --dry-run` на `5f0939049`
(временный untracked seed `.deploy/release.json` с предыдущим деплоем
`ffdc6eadf / 2.58.251`; после прогона удалён, в коммит не попал):

```json
{
  "deployed_at": "2026-11-26T07:37:56.519234Z",
  "deployed_sha": "5f09390492b254bd129edc68620c1cbece069f0c",
  "dirty_tracked": false,
  "effect": "deploy",
  "previous_sha": "ffdc6eadf38b479509b68ba653b6b0b50200774b",
  "previous_version": "2.58.251",
  "release_branch": "release/mod-acl-m1c-2.58.252",
  "schema": 1,
  "version": "2.58.252"
}
```

`deployed_sha` = фактический `git rev-parse HEAD`. После evidence-коммита
(`plans/` only) итоговый tip изменится — DevOps обязан записать манифест
на фактическом checkout.

**OpenAPI: 221 path / 261 operation — и на базе `ffdc6eadf`, и на кандидате**
(`create_app(MagicMock()).openapi()`): **0 новых endpoints**. DDL 0, миграции 0,
новые флаги 0, `models/`, `migrations/`, `services/pg_db.py`,
`services/database.py` вне диффа; `config/settings.py` — только строка версии;
схема v48.

## 7. Откат

- Code-only, `git`-откат на `ffdc6eadf38b479509b68ba653b6b0b50200774b`
  (2.58.251), `tools/release_manifest.py --effect rollback`.
- DDL 0, миграций 0, новых флагов 0 → схема и данные совместимы в обе стороны;
  пользовательские данные/настройки/секреты не затрагиваются; значения промптов
  не переписывались (ACL — только чтение/запись через API).

## 8. Что не проверялось (честно)

- Живой Telegram WebView, живой групповой чат с реальными `chat_admins` —
  стенд локальный (см. границы README среза).
- Реальный PostgreSQL-отказ/401 Telegram — статусы поданы стабом на границе HTTP.
- Полный 23k-набор не прогонялся (как и в ревью среза); покрытие — наборы §5.
- Effective-state прода (фактическая версия, схема, identity, healthz) — DevOps
  после деплоя; production не затрагивался.

## 9. Гигиена

- Worktree `…-f68d0448` — активная линия релиза, зарегистрирован
  (`unit m1c-release`), сохраняется до деплоя/решения.
- Browser harness оставил `tools/_ui_m1c_out/` (15 png/json) — удалён после
  прогона; `git status` чист.
- Overlay-скрипты (bump/reverse/blob-check) и логи наборов — во временном
  каталоге `%TEMP%\opencode\m1c_release` (0.4 MB, 41 файл); в репозиторий не
  копировались. Назначение — воспроизводимость §2–§3 и повторная проверка
  после деплоя; удалить после deploy/binding-решения по 2.58.252.
- `workflow_housekeeping.py inventory --repo` показывает 46 записей прошлых
  сессий (другие unit'ы epic'а); к этой сборке не относятся, не трогались — их
  жизненный цикл у владельцев. Своих registered runs сборка не создавала.
- `.deploy/release.json` (seed) удалён; в коммитах только код среза, version
  wave и этот файл evidence.
