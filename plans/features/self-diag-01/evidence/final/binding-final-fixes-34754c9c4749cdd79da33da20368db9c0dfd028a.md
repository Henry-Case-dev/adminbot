# SELF-DIAG-01 — final-fixes: F1–F3 release blockers закрыты (кандидат `34754c9c`)

- **Код/тесты (кандидат):** `34754c9c4749cdd79da33da20368db9c0dfd028a`
  (ветка `self-diag/final-fixes`).
- **Docs-коммит:** этот файл (SHA фиксируется в handoff; код выше не меняется).
- **База:** одобренный финальный кандидат `454727ed` (+ docs `8797cd83`).
- **Ветка/worktree:** `self-diag/final-fixes`,
  `WorkspaceData/worktrees/c742e4de9e92c489/SELF-DIAG-01-25283fad06db-ce263d9b`.
- **Статус:** **REVIEW** — F1–F3 и web-wide набор перепроверяет независимый
  Reviewer. Приёмку/выкат не объявляю.
- **Не делалось:** деплой, прод, `settings`, `prompts`, `models`, DDL/миграции,
  новые требования/хранилища/LLM/агенты. Продуктовая логика не менялась.

## 1. Что было (симптомы DevOps на `454727ed`)

| ID | Тест | Симптом |
|---|---|---|
| F1 | `test_webapp_js_unit.py::test_js_unit_round1025_hotfix6_lens_heartbeat_shell` | guard резал `_hbDraw … loadStatus`; D6 вставил между ними `loadSelfDiagnosis` с `this.api(...)` → ложный RED |
| F2 | `test_webapp_round109_ui.py::TestDescriptions::test_no_forbidden_jargon` | описание `flags.self_diag_repo_origin` содержало запрещённый жаргон «URL» |
| F3 | `test_webapp_evol_w14_states.py::TestUnifiedCheckboxes::test_every_native_checkbox_is_a_design_system_control` | чекбокс матрицы «Самодиагностики» — нативный `<input type="checkbox">` без контрола дизайн-системы |

## 2. F1 — границы guard'а (test contract, продукт не менялся)

Продуктовый инвариант в порядке: `_hbDraw` (`web/app.js:29742-29761`) сети не
делает, загрузчик `loadSelfDiagnosis` — button-only (`web/index.html`, обработчик
кнопки). Ломался **тест**: срез захватывал соседние методы.

Фикс (`tests/js/round1025_hotfix6_lens_heartbeat_shell_test.js`): граница — тело
конкретного метода (от `{` после `name: ` до закрытия члена объект-литерала
`\n      },`), а не «до следующего метода». Проверяются все ступени отрисовки:

- `_hbDrawGrid`, `_hbDrawPremium`, `_hbDrawLegacy`, `_hbDraw` — ни `fetch(`,
  ни `this.api(`, ни `XMLHttpRequest`, ни `axios`;
- **контроль экстрактора**: тот же хелпер на `loadStatus` обязан найти
  `this.api(` — иначе инвариант не может пройти «вхолостую».

RED→GREEN: было `FAILED` (ложный), стало `HOTFIX6-LENS-HEARTBEAT-SHELL-OK`.

**Мутационная проверка (guard не ослеп):**

```
mutation '_hbDraw: function (ts) {'     + this.api('/mutation-probe')  → exit=1 (RED)
mutation '_hbDrawPremium: function ('   + this.api('/mutation-probe')  → exit=1 (RED)
restored tree                                                          → exit=0 (green)
```

## 3. F2 — owner-visible описание + переутверждение F8 (DOC-ONLY)

`services/param_catalog.py:4100-4104` — переписано без «URL»:

> «Канонический репозиторий SELF-DIAG для чтения собственного кода (owner/name).
> Глобальная настройка владельца; значения отдельных чатов не используются.
> **Адрес вида owner/name с логином или секретом в начале нормализуется, сами
> секреты не сохраняются.**»

Смысл сохранён: канонический `owner/name`, credential-часть вырезается, секреты
не сохраняются. Ключ/значение/тип/группа/`secret`/`global_only` не менялись.

Переутверждения (`L-F11S-1`, прецедент DOC-ONLY [M-ASAP41-1]):

- `tools/gen_param_registry_round1025.py` переэмитил артефакты (дифф по 1 строке
  в TSV и meta; screen-map без изменений);
- `tests/fixtures/round1025/f8_baseline.json`: `sha256` →
  `a7d383958175fefcfaa99e49d0d9f7095f3605933460b59a7893d3bee144d9cf`,
  `sha256_artifacts` пересчитан, в `superseded_by` добавлена DOC-ONLY запись;
- `tests/test_round1025_f8_registry.py`:
  `PARAM_CATALOG_SHA256_FOLLOWUP` → `a7d3839…` + комментарий-санкция.

Проверка: `--check` → **`CHECK OK: реестр 644 == REGISTRY, карта полна,
R17-чисто, TSV/map идемпотентны`**; `REGISTRY 644 / GROUPS 121 /
_TAB_BY_GROUP 119 / TAB_RULES 22 / delta 243` без изменений; `FORBIDDEN`-скан
описания и `title_ru` — `none`.

## 4. F3 — контрол дизайн-системы вместо нативного чекбокса

`web/index.html:987` — чекбокс роли матрицы теперь `class="ctl-check__box"`
(тот же контрол, что в access/perms и остальных DS-местах), у `label` добавлен
`cursor-pointer`; `:disabled` / `:checked` / `@change="diagToggleRole(...)"`
сохранены **байт-в-байт по смыслу** — RBAC, диагностическая политика и обработчик
не менялись, новой страницы/компонента нет.

Регрессия: `tests/test_webapp_evol_w14_states.py::TestUnifiedCheckboxes::
test_self_diag_matrix_uses_design_system_checkbox` — берёт блок
`data-self-diag-action=…` и требует `ctl-check__box` у input, наличие `:disabled`
и `@change` (семантика не потеряна).

**Мутационная проверка:** если вернуть нативный input — падают **2** guard'а
(общий + новый), восстановление → 3 passed.

### Визуальная проверка (bounded, реальный `web/static/app.css`)

Компонентный стенд (та же разметка + реальный CSS, Playwright/Chromium):

| | было (`454727ed`) | стало (F3) |
|---|---|---|
| размер контрола | `13×13` | **`18×18`** |
| `accent-color` | `auto` | **`rgb(139, 111, 232)`** (`--purple-400`) |
| курсор | `default` | **`pointer`** |
| disabled | — | `not-allowed` (`.ctl-check__box:disabled`) |
| `label.min-height` | `auto` | `auto` (плотность строки матрицы не выросла: `.ctl-check` не добавлялся) |

Скриншоты компонентного стенда: `f3visual/f3-matrix-checkbox-closeup.png`
(до/после) в run-каталоге прогона (см. §9).

**Визуальное доказательство на реальной странице (кандидат `dae6ffea`,
follow-up к `34754c9c`):** отдельным прогоном по существующему e2e-паттерну
(`tools/ui_round1025_matrix.py`: статический сервер + TMA-стаб + подмена
`**/api/**`) отрендерена настоящая `web/index.html` + `web/app.js` +
`web/static/app.css`; матрица приходит из **реального**
`services.diagnostic_policy.matrix_snapshot()`. Viewport 390×844 и 1536×960:
все 48 контролов `18×18`, accent `rgb(139,111,232)`, нативных чекбоксов `0`,
`label.min-height: auto`, `hScroll=0`, обрезанного текста `0`, `[object Object]`
нет, console-ошибок `0`; сняты unchecked / checked (клик «до/после») / disabled,
плюс исправленная строка «Жёсткие правила». Артефакты:
`evidence/final/visual/f3-visual-evidence-dae6ffea.md` + PNG + JSON.

**Follow-up `dae6ffea` (F3 visual):** строка «Жёсткие правила» печатала
`[object Object]` (`join('; ')` по `{rule, message}`). В кандидате `dae6ffea`
— helper `diagHardRulesText()` (message → fallback rule, устойчив к
строке/пустому/`null`), шаблон без сырого join, JS-тест
`tests/js/self_diag_hard_rules_text_test.js` (мутации: старый join → RED,
нет helper'а → RED). F1–F3 и F8-пин не менялись.

## 5. Web-wide набор: `tests/test_web*.py` (68 файлов)

| Прогон | Итог |
|---|---|
| база **2.58.197** (`25876167`), тот же набор | **11 failed, 1539 passed** |
| кандидат до фиксов (`454727ed`) | 14 failed, 1536 passed (3 = F1–F3) |
| **кандидат `34754c9c` (HEAD)** | **11 failed, 1540 passed** |

Сравнение множеств падений (машинно): `new on candidate: none`,
`fixed on candidate: none`, 11 = 11 — те же предсуществующие тесты, что и на
релизной базе:

```
test_webapp_asap_cover_ui_v21::TestHistoryAndCoverTimer::test_history_shows_activation_date
test_webapp_asap_ui02_delta::test_no_magic_z_index_outside_decorative_in_card
test_webapp_avatars_ui::TestAvatarFrontAudit::test_close_and_fullscreen_buttons
test_webapp_dm_ui::TestDmSummaryGateMarkers::test_s3_scheduler_skips_dm_positive_ids_behavioral
test_webapp_round1020_ui::TestNavigationSnapshot::test_tabs_ids_and_order_unchanged
test_webapp_round1020_ui::TestNavigationSnapshot::test_navbar_legacy_and_v2
test_webapp_round1020_ui::TestHumanReadableLabels::test_examples_from_tz
test_webapp_round1024_nodeflow::TestNodeFlowNaming::test_no_english_jargon
test_webapp_round108_ui::TestCacheBustAndEsc108::test_app_version_matches_readme
test_webapp_ui_rework_round1020::TestNavigationSnapshot::test_tabs_ids_and_order_unchanged
test_webapp_ui_rework_round1020::TestNavigationSnapshot::test_navbar_and_modules_unchanged
```

`+1 passed` относительно базы = новый регрессионный тест F3 (F1–F3 при этом
зелёные: их падений в списке больше нет).

Целевые тесты на HEAD:

```
test_js_unit_round1025_hotfix6_lens_heartbeat_shell           PASSED
test_webapp_round109_ui::TestDescriptions::test_no_forbidden_jargon  PASSED
test_webapp_evol_w14_states::TestUnifiedCheckboxes           3 passed
```

## 6. Focused train — без изменений относительно `454727ed`

| Набор | Кандидат `34754c9c` |
|---|---|
| D6 `test_checkup_contract` | 41 passed |
| D6 broad 22 файла | 946 passed |
| D6 16 файлов | 661 passed, 1 failed (`mca10b` 643/644, pre-existing) |
| D2 (5 / 6 / 2 файла) | 145 / 216 / 42 passed |
| D2 9 файлов | 244 passed, 1 failed (`cfg03` dead knob, pre-existing) |
| D4 (`d4c` / 9 файлов) | 22 / 366 passed |
| D5 (`prompt_readback` / golden / 8 файлов / prompt-контракты) | 62 / 38 / 355 / 56+1s |
| D3 (`bundle+probes` / focused 35 файлов) | 80 / 1325 passed |
| web/api контракты | 190 passed |

Новых падений нет; оба падения — те же известные pre-existing.

## 7. Дифф относительно `454727ed`

```
8 файлов, +59 / −15 (плюс docs-коммит 8797cd83 между кандидатами)

plans/docs/param-registry-round1025.meta.md         |   2 +-
plans/docs/param-registry-round1025.tsv             |   2 +-
services/param_catalog.py                           |   5 +-
tests/fixtures/round1025/f8_baseline.json           |   6 +-
tests/js/round1025_hotfix6_lens_heartbeat_shell_test.js | 28 ++-
tests/test_round1025_f8_registry.py                 |   5 +-
tests/test_webapp_evol_w14_states.py                |  12 ++
web/index.html                                      |   4 +-
```

Никаких DDL/флагов/настроек/промптов/моделей/новых LLM/агентов/хранилищ.

## 8. Классификация находок

- `IN_SCOPE` (исправлено): F1 (границы guard'а), F2 (жаргон + F8 re-pin),
  F3 (нативный чекбокс в матрице).
- `BACKLOG_ONLY` (не блокирует, предсуществует):
  1. 11 падений web-wide набора на релизной базе `2.58.197` — не связаны с
     self-diag (навигационные снимки, nodeflow-жаргон, cache-bust, avatars,
     dm-summary, cover-timer, magic z-index).
  2. Часть web-wide тестов (`*_e2e`/UI-прогоны) перезаписывает **tracked**
     PNG-артефакты в `plans/features/evol/audit/evidence/` — рабочее дерево
     становится грязным после любого web-wide прогона (восстанавливалось
     `git checkout`; предлагается писать в temp).
  3. В корне репозитория присутствуют чужие untracked файлы (`.tmp_head.json`,
     `OPENCODE_WORKFLOW_SCRATCH/`, `_anchors_probe*.py`,
     `tools/_ui_asap43_*.png`) — не создавались этим срезом, не трогал.
- `CRITICAL_OUT_OF_SCOPE`: не обнаружено.

## 9. Housekeeping

- Baseline-прогон выполнялся в одноразовом detached-worktree
  `runs/…/probe-aa3c8758cb/base-25876167` (**снят** после сбора доказательств;
  тестовые перезаписи PNG восстановлены `git checkout` перед удалением).
- Логи прогонов, диффы и F3-стенд (`f3visual/index.html`, `app.css`,
  `f3-matrix-checkbox-closeup.png`) — в
  `WorkspaceData/runs/…/SELF-DIAG-01-25283fad06db/probe-aa3c8758cb/`;
  путь сохранён на время ревью, закрывается после приёмки.
- Локальный `http.server` для F3-стенда остановлен, браузер закрыт; скриншоты
  из корня репозитория перенесены в run-каталог (в репозитории не остались).
- Worktree `self-diag/final-fixes` сохранён для Reviewer; `self-diag/final`
  (`8797cd83`) не изменялся — прежний кандидат воспроизводим.
