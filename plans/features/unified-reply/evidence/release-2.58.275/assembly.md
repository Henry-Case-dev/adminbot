# Release 2.58.275 — assembly (P0T-REPLY-01: смысловая цель reply в Direct + канон R4)

- **Дата:** 2026-11-29
- **Ветка:** `release/2.58.275` (от `release/2.58.274` tip `e612eeed6`; прод-код `731a7e51c` = 2.58.274)
- **Worktree:** `WorkspaceData/worktrees/c742e4de9e92c489/release-2-58-275-1e93594d8edc-386fb7e8` (registered)
- **Единственное продуктовое изменение:** P0T-REPLY-01 — цель reply в Direct берётся из решения L1 по смыслу
  (только `delivery=reply` + существующая цель), канон L1 переведён R3 → R4 (`l1-planner-delivery-scope`,
  sha12 `64a80fb8c4ff`, factory set `1c03efc3e98b`).
- **Остальное:** тестовые контракты (barriers, UR-B, VMQ Q-01/Q-08) и evidence.

## 1. Кандидаты (все с независимыми вердиктами)

| # | ветка | tip | code SHA | вердикт | merge | что внесено |
|---|-------|-----|----------|---------|-------|-------------|
| 1 | `feat/p0t-reply-01-2026-11-28` | `1353a5131` | `cb387ee88` | r1 `APPROVED_FOR_RELEASE_PREPARATION` (`plans/features/unified-reply/evidence/p0t-reply-01-2026-11-28/review-r1.md`) | `6c3fcb254` | 5 продуктовых файлов (`chat_prompts`, `direct_chat_service`, `direct_l1`, `prompt_migrations`, `prompt_registry`), `tests/test_p0t_reply_target.py` (16), обновление 15 пинов канона/фабрики, архитектура/impl/raw-evidence |
| 2 | `fix/release-test-barriers-2026-11-28` | `db5d1bc66` | `69096c451` | r4 `APPROVED_FOR_RELEASE_PREPARATION` (`plans/features/release-test-barriers-2026-11-28/review-r4.md`) | `23dff2ac7` | `tests/routes_contract.py` (+fixture, схема контракта routes 2: direct/helper), `tests/version_contract.py`, `tests/test_routes_contract_barriers.py`, замена 24 whole-file version-пинов на контракт, 6 предсуществующих падений починены |
| 3 | `feat/ur-b-testonly-2026-11-28` | `43646c6cb` | — | r2 `APPROVED_FOR_RELEASE_PREPARATION` (`plans/features/unified-reply/evidence/ur-b-tests-2026-11-28/review-r2.md`) | `5cd90cb60` | test-only UR-03.1/04.3/06.5/14.1: `test_ur_b_tool_evidence.py`, `test_ur_b_observer_no_search.py`, `test_ur_14_bot_output_history.py` (строки остаются REVIEW) |
| 4 | `feat/vmq-q0-2026-11-28` | `f032216d8` | `0d4191227` | r2 `APPROVED_FOR_RELEASE_PREPARATION` (`plans/features/vmq-onto-01/evidence/vmq-q0/review-r2.md`) | `d438adeff` | test-only Q-01/Q-08: `tests/test_vmq_q0_mapping_property.py`, `tests/test_vmq_q0_source_audit.py` + evidence |

Все четыре tip — предки HEAD (`git merge-base --is-ancestor` = 0 для каждого).

## 2. Сборка: фактические мержи и разрешение конфликтов

Мержи выполнены `--no-ff` в порядке P0T → barriers → UR-B → VMQ Q0.

| мерж | результат |
|------|-----------|
| P0T | clean, `6c3fcb254` |
| barriers | **24 конфликта** (см. ниже), разрешены вручную, `23dff2ac7` |
| UR-B | clean, `5cd90cb60` |
| VMQ Q0 | clean, `d438adeff` |

### Конфликты barriers (важно для ревью)

Входная гипотеза «мержатся без конфликтов» для пары P0T+barriers **не подтвердилась**. Причина
механическая, продуктовая логика не затронута:

- barriers заменяет whole-file version-пины (`assert APP_VERSION == "2.58.274"`) на
  `tests.version_contract.assert_version_contract()`; ветка barriers построена от `74ef57ef4` (2.58.273),
- bump-коммит 2.58.274 (`731a7e51c`) в тех же строках поменял литерал `2.58.273` → `2.58.274`.
- «удаление строки» vs «изменение строки» → конфликт в 24 файлах `tests/test_*.py`.

Разрешение: для всех 24 файлов взята сторона barriers (`git checkout --theirs`), т.е. контракт вместо
литерала. Проверено, что единственные изменения этих файлов между базой barriers `74ef57ef4` и прод-кодом
`731a7e51c` — version-литералы:

```
git diff 74ef57ef4 731a7e51c -- <24 conflicted files>
  → только пары `assert APP_VERSION == "2.58.273"` → `"2.58.274"` (и производные `m.group(1)`/`in SETTINGS`)
```

После разрешения файлы побайтово равны версии barriers (`git diff db5d1bc66 -- <files>` пуст), маркеров
конфликтов нет, `git add` + commit.

## 3. Побайтовая идентичность кандидатов в собранном дереве

| проверка | результат |
|----------|-----------|
| `git diff 1353a5131 HEAD -- services/chat_prompts.py services/direct_chat_service.py services/direct_l1.py services/prompt_migrations.py services/prompt_registry.py tests/test_p0t_reply_target.py` | пусто |
| `git diff db5d1bc66 HEAD -- tests/routes_contract.py tests/fixtures/routes_contract.json tests/test_routes_contract_barriers.py tests/version_contract.py` | пусто |
| `git diff 43646c6cb HEAD -- tests/test_ur_14_bot_output_history.py tests/test_ur_b_observer_no_search.py tests/test_ur_b_tool_evidence.py` | пусто |
| `git diff f032216d8 HEAD -- tests/test_vmq_q0_mapping_property.py tests/test_vmq_q0_source_audit.py` | пусто |

## 4. Version bump 2.58.274 → 2.58.275

`raw/_bump.py` (байтовая замена, канонический набор = 29 файлов прошлого bump-коммита `5e38d9b72`,
исключая его evidence), `raw/bump-verify.txt`:

```
files_in_canonical_set=29 files_changed=5 occurrences_replaced=9
skipped_no_occurrence=[24 файла tests/*, у которых литерал заменён на version_contract]
removed_lines=9 added_lines=9
all_removed_map_to_added_by_version=True
non_version_changed_pairs=0 non_version_added_lines=0
remaining_old_occurrences=0 new_occurrences=9
size_changed_files=(none)  crlf_total=3665 bare_lf_total=14644
APP_VERSION_lines=['APP_VERSION = "2.58.275" ...']
```

Файлы: `config/settings.py`, `plans/docs/param-registry-round1025.meta.md`, `tests/test_q07_field_stats.py`
(3 fixture-значения `config_version`), `tools/ui_mod_acl_m4b2_status_e2e.py` (3), `tools/ui_mod_acl_m4b3_status_e2e.py` (1).

Единственное оставшееся упоминание `2.58.274` в продуктовом/тестовом дереве — историческая фраза в docstring
`tests/test_vmq_q0_mapping_property.py:5` («код контура уже в 2.58.274»); это провенанс, не пин, сознательно
не переписан.

Commit: `12c5fc97a chore(release): bump 2.58.274 -> 2.58.275 (version-only, 5 files / 9 occurrences)`.

## 5. Манифест (собранное дерево)

Код/версия: `head=12c5fc97a`, tree `e15e3b935`. Следующий коммит — этот evidence-набор; он меняет только
`plans/features/unified-reply/evidence/release-2.58.275/`, поэтому собранный кандидат остаётся `12c5fc97a`
(актуальный head ветки = `git -C <worktree> log -1`).

```
branch=release/2.58.275
head=12c5fc97ae82b42e419c2dde63721ccf0c34bb07   (собранный кандидат; evidence-коммит сверху планов не меняет)
tree=e15e3b935ba9be20829b2033bf3ac2a79b78de95
version=2.58.275
base_274=e612eeed6648745a00f43930d0813f4393580600
prod_deployed=731a7e51cdb747fb3c0507ec80b885e4217766b0  (2.58.274)
prod_tree=16d79f701767a932bf942c1b49a21650915559bd
dirty_tracked=0
routes_blob=92bb8a7274007a863bd07c7ed635feee70db4d51   (== прод-код 2.58.274, неизменны)
appjs_blob=8d3c535e6c7f9668f41ee27f889e9c47b187ecef     (== прод-код 2.58.274)
index_blob=90499d81cd93a26935f733985636050011193767     (== прод-код 2.58.274)
direct_chat_service_blob=393c673f1d2ae22afac63c95e8dd96a968308554
direct_l1_blob=c0e4bad0bdd9636704fb2d17079644e9ab6618e8
chat_prompts_blob=5ebc470b7fa168e261529ff26844ea819502ac7d
database.py/database/migrations/gen_param_registry изменены? 0 файлов (схема не меняется)
```

`web/api/routes.py`, `web/app.js`, `web/index.html` побайтово равны задеплоенному 2.58.274 — набор маршрутов
и Mini App этим релизом не меняются.
