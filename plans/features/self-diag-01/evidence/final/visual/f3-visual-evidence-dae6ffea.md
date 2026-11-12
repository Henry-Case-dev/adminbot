# F3 — визуальное доказательство матрицы «Самодиагностики» (кандидат `dae6ffea`)

- **Кандидат:** `dae6ffeae07cbf2b8d533bb99eaeaf267de335a2` (ветка `self-diag/final-fixes`).
- **База этого прогона:** `34754c9c4749cdd79da33da20368db9c0dfd028a`
  (на нём снят предыдущий набор снимков и виден дефект `[object Object]`).
- **Статус:** **визуальное доказательство для независимого вердикта Reviewer**
  (`D7 visual` + перепроверка F3/`hard_rules`). Не является приёмкой.
- **Продуктовый код в этом прогоне не менялся** — снимался готовый кандидат
  `dae6ffea` (в нём только фикс `hard_rules`, см. §5).

## 1. Провенанс ассетов (sha256 реальных файлов кандидата)

| Файл | sha256 |
|---|---|
| `web/index.html` | `e769924aee618524cca3fec9b05d3d4bed9481b2eb997beaacf60849f20eb01c` |
| `web/app.js` | `3cf2c9168c350f49977127a1e6bb19363734e27923efeeeae4bce9fa9895f594` |
| `web/static/app.css` | `f468bd01b9228455c81cb9b4465a70b67804be00efde0370dccafb3e23c92fed` |

## 2. Как получено (существующий e2e-паттерн, без новой инфраструктуры)

`tools/ui_round1025_matrix.py`: статический сервер по worktree + TMA-стаб
`M.TMA_STUB` + подмена `**/api/**`. Отдаются **настоящие** файлы кандидата
(sha256 выше); `GET /api/access/diagnostic_policy` отвечает **реальным** payload
кандидата — `services.diagnostic_policy.matrix_snapshot(pg=None, chat_id=None)`
+ `effective_state()` (та же функция, что у боевого route
`web/api/access.py::diagnostic_policy_get`); прочие `/api/*` — существующие
стабы харнесса.

Навигация: `#/access` → клик `[data-self-diag-access-toggle]` → ожидание
`[data-self-diag-cap]`. Viewport'ы: **390×844** (`is_mobile`, `has_touch`) и
**1536×960**, `device_scale_factor=2`. Сервер и браузер остановлены в `finally`
(порт 8899 после прогона закрыт).

Генератор (не коммитится):
`WorkspaceData/runs/…/SELF-DIAG-01-25283fad06db/probe-aa3c8758cb/visual_f3_matrix.py`

## 3. Состояния на снимках

1. **default** — реальный ответ `matrix_snapshot`: 9 категорий, 48 чекбоксов,
   одновременно видны все три состояния:
   * **checked** — «Участник»/«Админ этого чата» в `view/run` публичных классов;
   * **disabled** — «Владелец бота (неявно)» + все чекбоксы секретной категории
     (`configurable=false`), DS-стиль `not-allowed`/приглушение;
   * **unchecked** — строки «Правки» (edit) и промпт-категория для участника.
2. **after toggle** — клик по unchecked `prompts / view / Участник` переводит его
   в checked **без сохранения** (локальный `diagToggleRole`): контрол
   интерактивен, `:disabled` не протёк. Снято «до/после» на одном блоке.

## 4. Измерения (машинно, `f3-matrix-measurements-dae6ffea.json`)

| Метрика | 390×844 default | 390×844 after toggle | 1536×960 default | 1536×960 after toggle |
|---|---|---|---|---|
| категорий / чекбоксов | 9 / 48 | 9 / 48 | 9 / 48 | 9 / 48 |
| размеры контролов (уникальные) | `18x18` | `18x18` | `18x18` | `18x18` |
| `accent-color` (уникальные) | `rgb(139, 111, 232)` | то же | то же | то же |
| `label.min-height` | `auto` | `auto` | `auto` | `auto` |
| нативных чекбоксов | **0** | **0** | **0** | **0** |
| `hScroll` (document / body) | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| обрезанный текст | **0** | **0** | **0** | **0** |
| `[object Object]` в карточке | **нет** | **нет** | **нет** | **нет** |
| console/pageerror | **0** | **0** | **0** | **0** |

Строка «Жёсткие правила» (из того же JSON, все четыре экрана):

```
prompts -> Жёсткие правила: Текст промптов доступен только администратору
           этого чата по явному запросу; участникам он не выдаётся.
```

Внутренний код правила (`denied_prompt_content_member`) в UI отсутствует —
проверяется и в измерениях, и в JS-тесте.

## 5. Фикс, попавший в кандидата `dae6ffea` (виден на снимках)

`hard_rules` приходят как `[{rule, message}]`, а шаблон делал
`item.hard_rules.join('; ')` → `[object Object]`. Теперь:

- `web/app.js`: `diagHardRulesText(item)` — сначала `message`, код правила только
  как fallback; строки/пустые/`null`/не-массив обрабатываются без исключений;
- `web/index.html`: строка рендерится helper'ом и только когда текст есть;
- `tests/js/self_diag_hard_rules_text_test.js` + обёртка в
  `test_webapp_js_unit.py`: поведенческий тест дергает реальные методы
  `web/app.js` и проверяет шаблон. Мутации: возврат старого `join` → RED;
  удаление helper'а → RED; восстановление → green.

Предыдущий набор снимков (`34754c9c`) фиксировал именно этот дефект; он заменён
этим прогоном (старые PNG остаются в истории git).

## 6. Снимки (в этой папке)

| Файл | Что показывает |
|---|---|
| `f3-matrix-390x844-default-dae6ffea.png` | мобильный экран «Доступы»: карточка «Самодиагностика» + соседняя карточка «Разделы» (плотность), без горизонтального скролла |
| `f3-matrix-390x844-default-block-dae6ffea.png` | вся матрица (9 категорий), включая исправленную строку «Жёсткие правила» |
| `f3-matrix-390x844-toggle-before-dae6ffea.png` | блок `prompts` до клика: «Участник» (просмотр) не отмечен |
| `f3-matrix-390x844-toggle-after-dae6ffea.png` | тот же блок после клика: «Участник» отмечен (DS-контрол) |
| `f3-matrix-390x844-checked-block-dae6ffea.png` | вся матрица после клика |
| `f3-matrix-1536x960-*` | то же на десктопном viewport (default / block / before / after / checked-block) |
| `f3-matrix-measurements-dae6ffea.json` | измерения + sha256 ассетов + `hardRulesRows` + список изображений |

## 7. Что доказано и что — нет

**Доказано (кандидат `dae6ffea`, реальные `index.html`/`app.js`/`app.css`):**
контрол матрицы — DS-элемент `ctl-check__box` (18×18, accent `--purple-400`,
`cursor: pointer`), нативных чекбоксов нет; `disabled` использует DS-стиль; клик
переключает состояние; плотность строки не изменилась (`label.min-height:auto`);
нет горизонтального скролла и обрезанного текста; строка «Жёсткие правила»
показывает человекочитаемый текст правила без `[object Object]` и без внутренних
кодов; ошибок в консоли нет.

**Не доказано:** реальный Telegram WebView/`getInitData`, живые `getChatMember`
и Bot API; сохранение матрицы (`PUT /api/access/diagnostic_policy/{cap}`) не
вызывалось (клик меняет только локальное состояние до «Сохранить»); payload без
persisted-override'ов БД; пиксельное сравнение с эталоном не выполнялось.
Итоговый визуальный вердикт — за Reviewer (`D7`).

## 8. Воспроизведение

```
.venv\Scripts\python.exe <rundir>\visual_f3_matrix.py ^
  <worktree self-diag/final-fixes> ^
  <worktree>\plans\features\self-diag-01\evidence\final\visual ^
  dae6ffeae07cbf2b8d533bb99eaeaf267de335a2 34754c9c4749cdd79da33da20368db9c0dfd028a
```

Ожидаемо: `failures: []`, `console_errors: []`, 10 PNG + JSON; порт 8899 после
прогона закрыт.
