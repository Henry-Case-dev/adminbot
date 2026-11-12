# F3 — визуальное доказательство матрицы «Самодиагностики» (кандидат `34754c9c`)

- **Кандидат:** `34754c9c4749cdd79da33da20368db9c0dfd028a` (ветка `self-diag/final-fixes`).
- **Docs/база:** `c8784adf1230adea1ffe00f22eccfce64b8cefe3`; база `454727ed…`.
- **Статус:** **визуальное доказательство для независимого вердикта Reviewer**
  (`D7 visual`). Не является приёмкой и не меняет продуктовый код.
- **Провенанс ассетов** (sha256 реальных файлов кандидата, они же отдавались браузеру):

| Файл | sha256 |
|---|---|
| `web/index.html` | `a948b1d17487b73b64482a34a9ed6daaf904648d22ec49bf7c0a278d6fa4e555` |
| `web/app.js` | `712065364abfdddae4f423e09f0bddca8de5526ffdb8f0abfeca3ffefd16ec4a` |
| `web/static/app.css` | `f468bd01b9228455c81cb9b4465a70b67804be00efde0370dccafb3e23c92fed` |

## 1. Как получено (существующий e2e-паттерн, без новой инфраструктуры)

Использован уже принятый в проекте паттерн `tools/ui_round1025_matrix.py`
(статический сервер по worktree + TMA-стаб `M.TMA_STUB` + подмена `**/api/**`),
а не синтетическая разметка:

- сервер отдаёт **настоящие** `web/index.html`, `web/app.js`, `web/static/app.css`
  кандидата (sha256 выше);
- `GET /api/access/diagnostic_policy` отвечает **реальным** payload кандидата:
  `services.diagnostic_policy.matrix_snapshot(pg=None, chat_id=None)` +
  `effective_state()` — то есть та же функция, что вызывает боевой route
  `web/api/access.py::diagnostic_policy_get` (без сохранённых override'ов БД);
- остальные `/api/*` — существующие стабы харнесса (`M._stub_for`);
- идентичность — TMA-стаб `M.TMA_STUB`, `/api/me` стаб `global_admin`
  (`audit`), поэтому карточка «Самодиагностика» (`v-if="isGlobalAdmin"`) видима;
- навигация: `#/access` → клик `[data-self-diag-access-toggle]` → ожидание
  `[data-self-diag-cap]`;
- viewport'ы: **390×844** (`is_mobile`, `has_touch`) и **1536×960**,
  `device_scale_factor=2`;
- сервер и браузер подняты в одном процессе и остановлены в `finally`
  (порт 8899 после прогона закрыт).

Генератор (не коммитится, лежит в run-каталоге):
`WorkspaceData/runs/…/SELF-DIAG-01-25283fad06db/probe-aa3c8758cb/visual_f3_matrix.py`

## 2. Состояния, которые видно на снимках

1. **default** — реальный ответ `matrix_snapshot`: 9 категорий, 48 чекбоксов;
   одновременно присутствуют все три состояния:
   * **checked**: «Участник»/«Админ этого чата» в строках `view/run` для
     публичных классов (фиолетовая галочка дизайн-системы);
   * **disabled**: «Владелец бота (неявно)» (`diagRoleImplicit`) — контрол
     приглушён (`opacity .55`, `cursor: not-allowed`), и все чекбоксы секретной
     категории (`configurable=false`);
   * **unchecked**: строки «Правки» (edit) и промпт-категория для участника.
2. **after toggle** — клик по **unchecked** чекбоксу
   (`prompts` / `view` / «Участник») переводит его в checked **без сохранения**
   (локальный `diagToggleRole`): доказательство, что контрол интерактивен и
   `:disabled` не протёк. Снято «до/после» на одном и том же блоке категории.

## 3. Измерения (машинно, `f3-matrix-measurements-34754c9c.json`)

| Метрика | 390×844 default | 390×844 after toggle | 1536×960 default | 1536×960 after toggle |
|---|---|---|---|---|
| категорий / чекбоксов | 9 / 48 | 9 / 48 | 9 / 48 | 9 / 48 |
| размеры контролов (уникальные) | `18x18` | `18x18` | `18x18` | `18x18` |
| `accent-color` (уникальные) | `rgb(139, 111, 232)` | то же | то же | то же |
| `label.min-height` | `auto` | `auto` | `auto` | `auto` |
| нативных чекбоксов (`nativeCheckboxes`) | **0** | **0** | **0** | **0** |
| `hScroll` (document / body) | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| обрезанный текст (`clippedText`) | **0** | **0** | **0** | **0** |
| console/pageerror | **0** | **0** | **0** | **0** |

Примеры контролов (из JSON, `sample`):

- unchecked: `prompts / edit / Участник` → `18×18`, accent `rgb(139,111,232)`,
  cursor `pointer`, label min-height `auto`, `native=false`;
- checked (после клика): `prompts / view / Участник` → то же, `checked=true`;
- disabled: `bot_server_state / view / Владелец бота (неявно)` → `18×18`,
  `cursor: not-allowed`, `disabled=true`.

Границы замера: `clippedText` считается по текстовым leaf-узлам карточки с
`overflow:hidden` и `scrollWidth > clientWidth + 1`; «нативность» — по
отсутствию класса `ctl-check__box`; `hScroll` — разница
`scrollWidth - clientWidth` у `documentElement` и `body`.

## 4. Снимки (в этой папке)

| Файл | Что показывает |
|---|---|
| `f3-matrix-390x844-default-34754c9c.png` | мобильный экран «Доступы»: карточка «Самодиагностика» + соседняя карточка «Разделы» (плотность), без горизонтального скролла |
| `f3-matrix-390x844-default-block-34754c9c.png` | вся матрица целиком (все 9 категорий) |
| `f3-matrix-390x844-toggle-before-34754c9c.png` | блок `prompts` до клика: «Участник» (просмотр) **не отмечен** |
| `f3-matrix-390x844-toggle-after-34754c9c.png` | тот же блок после клика: «Участник» **отмечен** (DS-контрол) |
| `f3-matrix-390x844-checked-block-34754c9c.png` | вся матрица после клика |
| `f3-matrix-1536x960-*` | то же на десктопном viewport (default / block / before / after / checked-block) |
| `f3-matrix-measurements-34754c9c.json` | все измерения + sha256 ассетов + payload-метаданные + список изображений |

## 5. Что доказано и что — нет

**Доказано (кандидат `34754c9c`, реальные `index.html`/`app.js`/`app.css`):**
контрол матрицы — элемент дизайн-системы `ctl-check__box` (18×18, accent
`--purple-400`, `cursor: pointer`), нативных чекбоксов в матрице нет; состояние
`disabled` использует DS-стиль (`not-allowed`, приглушение); клик по
незаблокированному контролу переключает состояние; строка не теряет плотность
(`label.min-height: auto`), нет горизонтального скролла и обрезанного текста;
ошибок в консоли нет.

**Не доказано:** реальный Telegram WebView/`getInitData`, живые `getChatMember`
и Bot API; сохранение матрицы (`PUT /api/access/diagnostic_policy/{cap}`) — не
вызывалось (клик меняет только локальное состояние до «Сохранить»);
payload без persisted-override'ов БД (реальные значения каталога/дефолтов, но не
данные конкретной инсталляции); пиксельное сравнение с эталоном не
выполнялось. Итоговый визуальный вердикт — за Reviewer (`D7`).

## 6. Побочная находка (не блокирует F3, продуктовый код в этой задаче заморожен)

В карточке матрицы строка «Жёсткие правила» рендерится как
**`[object Object]`** — видно на снимках `*-default-block-*`,
`*-toggle-before-*`, `*-toggle-after-*`.

Причина: `services.diagnostic_policy.matrix_snapshot()` отдаёт
`hard_rules: [{"rule": ..., "message": ...}]`, а шаблон
(`web/index.html:1008`) делает `{{ item.hard_rules.join('; ') }}` — join по
объектам. Это предсуществующий дефект среза D6 (не F1–F3, не связан с
чекбоксом). Классификация: **BACKLOG_ONLY** для текущей задачи (продуктовый код
менять запрещено), рекомендация на ближайшее касание D6:
`item.hard_rules.map(r => (r && (r.message || r.rule)) || r).join('; ')` +
строчный тест рендера. Send to PM/Orchestrator, не прятать.

## 7. Воспроизведение

```
.venv\Scripts\python.exe <rundir>\visual_f3_matrix.py ^
  <worktree self-diag/final-fixes> ^
  <worktree>\plans\features\self-diag-01\evidence\final\visual ^
  34754c9c4749cdd79da33da20368db9c0dfd028a c8784adf1230adea1ffe00f22eccfce64b8cefe3
```

Ожидаемо: `failures: []`, `console_errors: []`, 10 PNG + JSON; порт 8899 после
прогона закрыт.
