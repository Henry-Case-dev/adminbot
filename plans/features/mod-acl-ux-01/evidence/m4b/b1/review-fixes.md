# M4B B1 — исправления по review r1

- **Review:** `plans/features/mod-acl-ux-01/evidence/m4b/b1/review-r1.md`,
  вердикт NEEDS_FIXES, findings `B1-R1-F01`, `B1-R1-F02`, `B1-R1-F03`.
- **Исходный candidate:** `333b18da3a4e45e99b7e50b2f947d0c40ffe1953`
  (branch tip `95e4c101`, base `40fe603f` / 2.58.223).
- **Новый candidate:** `5f8026b2f` (full SHA в `tests.json`);
  ветка `release/mod-acl-m4b1-2.58.224`, fast-forward push, без force.
- **Scope:** product — только `web/app.js`; tests — 4 Python-контракта +
  2 JS; tools — w10/w15/B1 e2e. Backend/API/DDL/flags/prompts не менялись.

## B1-R1-F03 — cross-scope stale досье (исправлено)

**Причина.** `_resetDossierFeedScope` вызывался только из ветки
`activeTab === 'status'`. Смена чата на другой вкладке не очищала общий
`dossierFeed`; при возврате в «Статус» старые строки жили до ответа нового
`dossier_feed` (MAC-S15-03).

**Исправление (`web/app.js`).**
- `_resetDossierFeedScope()` вызывается сразу после `scopeEpoch++` в
  `setActiveChat` — при **любой** смене чата/области, не только на «Статусе».
- `dossierFeedSeq` (generation снимка) инвалидирует in-flight ответ;
  `loadDossierFeed` применяет данные только при совпадении epoch **и**
  generation; старый `finally` не снимает `dossierFeedBusy` у нового запроса
  (N08).
- Ветка «Статуса» больше не делает повторный reset — только запускает
  polling новой области; ветка «Аналитики» сохранена.
- Устаревший комментарий «все четыре ленты» исправлен (N02).

**RED на `95e4c101` (до фикса).**
- `node tests/js/mod_acl_ux_m4b_feeds_test.js`:
  `AssertionError: на «Модулях» старые строки досье не переезжают в новый чат`.
- `tools/ui_mod_acl_m4b_status_e2e.py` (только F03-сценарий):
  `{"ok": false, "checks": 138, "failures":
  ["cross_scope_no_old_rows", "cross_scope_no_old_names",
  "cross_scope_honest_empty"]}`.
  Сценарий: Audit Chat (4 строки) → `#/modules` → «Тихий чат» → `#/` при
  задержанном ответе нового scope; старые `["Аня","Борис","Гость",
  "Участники не определены"]` видны до ответа.
- На базе `40fe603f` новый node-тест падает на отсутствии пятой секции
  (`4 != 5`) — контракт новый.

**GREEN на `5f8026b2f`.**
- `mod_acl_ux_m4b_feeds_test.js` — `MOD-ACL-UX-M4B-B1-FEEDS-OK`.
- B1 e2e — **138 checks, 0 failures**; `cross_scope_during.rows=0`,
  `cross_scope_during.text` содержит «В выбранном чате…» и не содержит
  «Аня»/«Борис»; после задержки — тот же честный пустой экран; возврат
  Audit Chat — 4 строки.
- Скриншот: `shots/status-dossier-cross-scope.png`.

## B1-R1-F01 — 14 зелёных Python-тестов (исправлено)

Обновлены осознанно, без удаления тестов и без ослабления покрытия:

| Было (review) | Стало / статус |
|---|---|
| `test_css_vertical_marker_and_reduced_motion` | `test_css_shared_sfeed_and_reduced_motion` |
| `test_css_seamless_uses_gap_var` | `test_css_five_ribbon_grid` |
| `test_css_speed_var_used_by_track` | `test_css_no_dead_ticker` |
| `test_index_gates_flag_and_keeps_off_branch` | `test_index_five_sections_and_tablist` |
| `test_appjs_speed_and_click_path` | `test_appjs_person_projection_and_click_path` |
| `test_dossier_feed_lives_in_status` | обновлён (5 секций, person-проекция) |
| `test_chat_title_instead_of_raw_id` | обновлён (`dossierPeopleFeed`) |
| `test_order_health_map_widget_others` | обновлён (dossier внутри intel) |
| `test_one_widget_with_four_sections` | `test_one_widget_with_five_sections` |
| `test_phone_switcher_markup_and_css` | обновлён (`aria-selected`, 3/2/1) |
| `test_dossier_ticker_row_aligned_with_feeds` | `test_dossier_row_aligned_with_feeds` (`.sfeed-item`) |
| `TestLiquidGlassAndGrid::test_reduced_motion` | обновлён (`.sfeed-*`, не тикер) |
| `TestDossierTicker::test_markup_and_css` | обновлён (пятая лента, тикера нет) |
| `TestDossierTicker::test_reactivity_markers` | обновлён (`dossierPeopleFeed`, без loop/speed) |

Дополнительно `tests/js/asap6_wave2_ux_tabs_test.js` переведён с
`dossier-ticker-wrap` на `data-intel-section="dossier"` в «Статусе» и
уникальный `data-experience-windows`; файл теперь зелёный (baseline 4→3).

**Результаты 6-файлового контракта** (`test_dossier_feed_round1024.py`,
`test_webapp_evol_w10_sections.py`, `test_webapp_evol_w15_composition.py`,
`test_webapp_round1020_ui.py`, `test_webapp_js_unit.py`,
`test_webapp_f11_round1025.py`):

| Прогон | Результат |
|---|---|
| base `40fe603f` + обновлённые тесты | **26 failed / 154 passed** — RED новых assertions |
| candidate `5f8026b2f` | **9 failed / 171 passed** |
| новые падения vs base | **0** |

9 остающихся — ровно прежние base-падения (catalog 4, live e2e 1, role
classes 1, tabs/nav 2, catalog label 1); 14 review-падений зелёные.
Логи: `f01-6files-base.txt`, `f01-6files-candidate.txt`.

## B1-R1-F02 — e2e-инструменты w10/w15 (исправлено)

- `tools/ui_evol_w10_sections_e2e.py`: `dossier` считает
  `[data-intel-section="dossier"]`; порядок без нижней карточки; 5 секций;
  `aria-selected`; mobile ≤767 и 5 кнопок; wide — 5 видимых.
- `tools/ui_evol_w15_composition_e2e.py`: `ROW_SEL` без
  `.dossier-ticker__item`; `dossier`/`dossierHere` — пятая секция;
  record-click и video-step — `[data-intel-section="dossier"] [data-sfeed-row]`.
- **w10 прогон (temp out):** остались только 3 прежних module/catalog
  падения; B1-проверки («нет пятой ленты», «кнопок переключателя») зелёные.
- **w15 прогон (temp out):** B1-папка «Досье» и record-шаг проходят;
  остаются 72 прежних cog-map/adaptive prompt-editor падения (вне B1),
  ни одного dossier/record. Точный итог — `f02-w15.txt`, `tests.json`.

## Прочие non-blocking

- **N01** `DOSSIER_LIVE_FEED_ENABLED` остаётся backend env-only; UI не
  читает, значение не менялось. Cleanup — отдельной задачей.
- **N03** broad suite исправлен: **125** `*_test.js` (было ошибочно 126;
  `module_fixture.js` — фикстура). 122 passed + **3** baseline (asap6
  исправлен, стало меньше).
- **N07** `plans/features/evol/audit/evidence/w10-sec-*` восстановлены из
  HEAD; в коммит B1 не входят.
- **N04/N05/N06/N09** — косметика/подписи/визуальный diff; не блокируют.

## Повторные прогоны

- mandatory 24-file pytest: **386 passed, 0 failed**.
- broad 125 JS: **122 passed, 3 pre-existing** (`evol_cog_scene`,
  `round1025_ia_routing`, `ur_ui_settings`).
- W2a **141**, W2c **84**, W2b **397** — rc=0.
- B1 e2e: **138 checks, 0 failures**.
- `node --check web/app.js` rc=0; `git diff --check` rc=0.

## Остаётся release/live

- Deploy 2.58.224 на точный SHA; live S6-307 (5 лент, 3+2/2+2+1/1) и
  S15-03 (пустой/непустой чат) на deployed bytes.
- Натуральный 503/пустой чат — RFL; M6/live TMA — после M4B+M4C.
