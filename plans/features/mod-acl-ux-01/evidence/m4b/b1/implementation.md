# M4B B1 — пять лент «Статуса»: досье, дедупликация, сетка

- **Фича:** MOD-ACL-UX-01, M4B B1 (MAC-S6-307, MAC-AC-16, MAC-S6-FEED-01/02/03,
  MAC-S15-03, MAC-S15-04 (компонентная часть), MAC-S0-11 (частично),
  MAC-S15-15).
- **База:** `40fe603f0aac853af99656bac1934ec5f3d160f9` / 2.58.223
  (выкаченный W3/F-1 503 fix уже в `web/app.js`/`index.html`).
- **Исходный candidate r0:** `333b18da3a4e45e99b7e50b2f947d0c40ffe1953`.
- **Кандидат r1 (после review):** `5f8026b2fb9a1509c09df834b2154d8c3c71d393`,
  ветка `release/mod-acl-m4b1-2.58.224`; target 2.58.224
  (bump/deploy не делались). Исправления F01–F03 — `review-fixes.md`.
- **Worktree:** `WorkspaceData/worktrees/.../mod-acl-ux-01-1e46be007668-512d7d77`.

## Что изменено

| Файл | Δ | Суть |
|---|---|---|
| `web/app.js` | +271/−80 | общий маппер записи досье; person-centric `dossierPeopleFeed`; пятая вкладка; tablist-клавиатура; пустые состояния/aria; scope-guard + generation `dossierFeedSeq` (сброс снимка при ЛЮБОЙ смене чата, N08); удалены `dossierFeedLoop`/`dossierFeedSpeed` |
| `web/index.html` | +63/−76 | пятая секция `data-intel-section="dossier"`; tablist/aria-current/roving tabindex; удалена нижняя карточка «Живая лента досье» (тикер + клоны) |
| `web/static/app.css` | +35/−138 | сетка 3+2 ≥1280, 2+2+1 768–1279, 1 колонка ≤767 + вкладки; touch 44; бейдж досье; удалён CSS мёртвого тикера |

### Пятая лента — person-centric проекция (D4)

Источник — тот же `GET /api/oversight/dossier_feed?limit=16`
(+`chat_id` при выбранном чате). Новых endpoint/store/DDL нет.

- identity: `user_id` → имя → честная строка «Участники не определены»;
- одна строка = один участник: последняя запись, число записей, чат
  (один чат / «разные чаты» / «чат неизвестен»);
- дата строки — `created_at`; `message_timestamp`/`last_confirmed_at`
  остаются отдельными полями окна записи и не подменяют дату записи;
- клик открывает существующее окно записи (`openStatusRecord('fact', …)`),
  вторичное действие — существующее «Досье субъекта» (`openFeedDossier`);
- пусто: глобально — причина экстракции/«лента ещё не запрашивалась»;
  в выбранном чате — «данные других чатов не подставляются»;
- 503/ошибка — причина в ленте, а не «0 записей».

### Сетка и a11y

- `≥1280`: 3 колонки → 3+2; `768–1279`: 2 → 2+2+1; `≤767`: 1 + вкладки.
- Все пять лент постоянно отрисованы на общем `v-sfeed`; переключение меняет
  только видимость, позиции прокрутки сохраняются (W2a-механика не тронута).
- `role="tablist"/"tab"`, `aria-selected`, `aria-current="page"`, roving
  tabindex, стрелки/Home/End без wrap, модификаторы не перехватываются,
  touch-цель ≥44 px, reduced-motion сохранён.
- Смена чата на «Статусе» очищает `dossierFeed` и перечитывает новую область;
  in-flight ответ прошлой области отбрасывается epoch-guard'ом (S15-03).

## Проверки

| Проверка | Результат |
|---|---|
| `tests/js/mod_acl_ux_m4b_feeds_test.js` | `MOD-ACL-UX-M4B-B1-FEEDS-OK` |
| `asap_ui02_status_ribbons_test.js` | `ASAP-UI02-RIBBONS-OK` |
| `round1024_dossier_feed_test.js` | `DOSSIER-FEED-OK` |
| `round1025_f11_status_grid_test.js` | `F11-STATUS-GRID-OK` / `F11-HEARTBEAT-OK` |
| `soul1_w5_initiative_panel_test.js` | `SOUL1-W5-PANEL-OK` |
| `round1020_ui_test.js` | `JS-UNIT-OK` |
| `evol001_005_widgets_test.js` | `EVOL-001-005-OK` |
| `asap6_wave2_ux_tabs_test.js` | `WAVE2-UX-TABS-OK` (baseline-падение снято) |
| broad node suite | **125** `*_test.js`: 122 passed, **3** pre-existing падения (`evol_cog_scene`, `round1025_ia_routing`, `ur_ui_settings`) |
| 6-file Python contract | base+updated tests 26/154; candidate **9/171**; **0 новых** падений |
| W2a tab-memory/keyboard | 141 проверка, rc=0 |
| W2c layout/nav | 84 проверки, rc=0 |
| W2b history | 397 проверок, rc=0 |
| mandatory pytest (24 файла) | **386 passed**, 0 failed |
| `tools/ui_mod_acl_m4b_status_e2e.py` | **138 check, 0 failures**, 6 viewport + F03 cross-scope |
| w10 e2e | B1-проверки зелёные; остались 3 прежних module/catalog падения |
| w15 e2e | B1-«Досье»/record зелёные; остались прежние adaptive/prompt-editor падения |
| Browser Use (real Chrome, 1440) | 5 секций, 3+2, 4 строки досье, detail+provenance, no h-scroll |
| Browser Use (real Chrome, 390) | 1 колонка, 5 вкладок, touch 63×44, aria-current, dossiers 4 |

### RED на базе `40fe603f`

`red-base.txt`: 7 node-файлов падают на базовых продуктовых байтах
(5≠4 лент, отсутствие `dossierPeopleFeed`, `data-intel-section="dossier"`,
удалённая нижняя карточка); e2e timeout на отсутствующей пятой секции.
После review r1 добавлены `f03-red.txt`/`f03-red.json` (RED на `95e4c101`:
cross-scope stale rows) и `f01-6files-{base,candidate}.txt`
(base 26/154, candidate 9/171; 0 новых падений).

### Мутации

`mutations.txt`: убрать 5-ю ленту → fail; вернуть 4 колонки/1100 → fail;
1:1 проекция без группировки → fail (4≠3); убрать `chat_id` из запроса → fail;
M5 reset только в status-ветке → fail (cross-scope); M6 убрать generation
из `finally` → fail (stale busy). Каждая мутация откатывалась побайтово;
`node --check`/`git diff --check` rc=0.

## Evidence

- `plans/features/mod-acl-ux-01/evidence/m4b/b1/tests.json` — машинные результаты;
- `.../red-base.txt`, `.../f03-red.txt`, `.../f03-red.json`, `.../mutations.txt`,
  `.../f01-6files-{base,candidate}.txt`, `.../review-fixes.md`;
- `.../e2e-report.json` — 138 check по 6 viewport + F03;
- `.../shots/` — 6 viewport-скриншотов Playwright, 503/empty-chat/
  pause-resume/cross-scope, 3 снимка реального Chrome (Browser Use).

## Ограничения

- Деплой/бump/2.58.224-сборка не выполнялись; VERIFIED не заявляется.
- Playwright и Browser Use работают на локальном стенде с синтетическими API;
  это не живая TMA/Telegram-сессия. Live-привязка S6-307/S15-03 — на
  выкаченных байтах силами release-lane.
- `DOSSIER_LIVE_FEED_ENABLED` больше не читается UI (он выбирал только стиль
  удалённого тикера и никогда не скрывал данные); значение backend-флага не
  менялось.
- W3 `unavailable/off/empty/denied` контракты не тронуты; backend/API/DDL/
  flags/prompts не изменялись.
- `requirements-map.json`, `workflow_state.md`, `progress_scope.json` не
  изменялись (по указанию dispatch).

## Очистка

Временный RED-worktree и локальный стенд остановлены/удалены после проверок;
новых production-артефактов нет.
