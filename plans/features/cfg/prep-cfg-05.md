# PREP-CFG-05 — бриф исполнения: сверка Liquid Glass (Verify, без нового кода)

**Лейн:** PM-PREP-CFG-05 (read-only по коду; единственные записи — этот документ и notes/write_scope CFG-05-Verify в карте/графе; статусы строк не менялись; SSH и прод не использовались).
**Дата:** 20.10.2026, 04:47 (UTC+12) · master `5b86517e` (код прода в `web/**` = `95d11472`) · прод **2.58.96** @ `95d11472` · CFG-04 в полёте (рабочее дерево: `web/{app.js,index.html,static/app.css}` dirty, evidence `cfg-04/**`), его релиз — ожидаемо **2.58.97**.
**Источники:** `plans/features/cfg/source-cfg-addendum.md` L10/L24/L35/L181–L192/L392 (в `plans/current_task.md` — L1241/L1255/L1412–L1423/L1623); `requirements-map.json` (8 строк слайса: 5 `items` + 3 `additional_requirements`); `slice-graph.json`; `plan.md` v0.7.1; `prep-cfg-03.md` / `prep-cfg-04.md`; `plans/features/soul-1/{glass-tiera-hotfix.md, review-tiera.md, review-tiera-strengthened.md, evidence/glass-tiera/**, release-2.58.86-report.md}`; `plans/features/asap8-v6-3-live-correction/{w2-reports/W2-GLASS.md, w2-evidence-glass/ui-acceptance.md}`; `plans/features/win-glass-hotfix/review-wg.md`; код/пины (только чтение): `web/index.html`, `web/app.js`, `web/static/{app.css,glass-probe.js,glass-refraction.js,polygon-background.js,aurora-flow.js}`, `tests/{test_webapp_design_tokens_round1025.py,test_webapp_round1026_polygon.py,test_webapp_hotfix6_round1025.py,test_webapp_js_unit.py,ui_soul1_glass_tiera_e2e.py}`, `tests/js/{glass_probe_test.js,glass_refraction_test.js,round1025_design_tokens_test.js,round1026_polygon_background_test.js}`, `config/settings.py`.
**Правило статусов:** `AIV` = механизм/доказательство уже есть (нужна сверка, не переписывание), `PARTIAL` = есть частично, `BROKEN` = воспроизводимое несоответствие источнику, `NEW` = работы ещё нет. `AIV ≠ VERIFIED`; все 8 строк карты остаются `PENDING` до фактов.

---

## 1. Что такое «CFG-05-Verify» по-человечески

`plan.md` ставит **CFG-05-Verify седьмым**, сразу после CFG-04, в линейной очереди ADD-0.1:

`CFG-01 → 02A → 02B → 02C → 03 → 04 → 05-Verify → 06 → 07A → 07B → 07C → CFG-FINAL`.

Это **не задача по стеклу**. Источник (L181–L192) прямо отменяет новую реализацию: владелец 18.10.2026 на живом проде увидел, что усиленное оптическое искажение уже отчётливо читается на реальной карточке «Бот» страницы «Статус», и прежняя жалоба «на реальных карточках искажение едва видно» больше не актуальна. Решение по очереди: `CFG-05 = OBSERVED_FIXED / NO_NEW_IMPLEMENTATION`.

Поэтому CFG-05-Verify — это **регистрация изменившегося состояния с однократной сверкой**:

1. сверить **фактически задеплоенный SHA** (после релиза CFG-04; ожидается 2.58.97) с тем, что в нём лежит именно отревьюенное усиленное стекло, а не другая сборка;
2. переиспользовать **существующие U08 и SOUL-17 результаты** (в т.ч. WIN-GLASS-слой Android-рефракции) и новое наблюдение владельца, не перепрогоняя их;
3. подтвердить, что **CFG-04 и прочие UI-правки не регрессировали** стекло и полигональный фон;
4. закрыть 8 строк как `REUSED_EXISTING / OWNER_VISUAL_CONFIRMED` — **без нового кода, без отдельного деплоя стекла и без исследовательского gate**.

Чего в CFG-05 **нет**: повторного исследования SVG-фильтров, `Glass Test Stand`, оптического рендерера, массовых A/B, tier-тестов на всех карточках, CSS-«улучшений» (L188). Новый конкретный воспроизводимый дефект не держит CFG-05 открытым и не задерживает очередь (L190): он фиксируется отдельно с доказательствами и исправляется точечно в **существующей** задаче-владельце (CFG-04 / U08 / SOUL-17 / WIN-GLASS).

---

## 2. Состав слайса (8 строк) — что именно доказывать

| # | req_id (источник) | Обязательство (сжато) | Этап закрытия |
|---|---|---|---|
| 1 | **ADD-1.C6** (L35) | Реализация, геометрия, цвета, анимация, плотность и размещение полигонального фона не изменяются; glass исправляется **поверх** него, а не вместо него | preprod (deployed) |
| 2 | **CFG-05.1** (L187) | Один раз сверить текущий deployed SHA, имеющиеся U08/SOUL-17 результаты и новое наблюдение владельца; при завершённой работе — `REUSED_EXISTING / OWNER_VISUAL_CONFIRMED` со ссылкой на evidence; закрыть CFG-05 **без нового кода и отдельного деплоя** | postdeploy |
| 3 | **CFG-05.2** (L188) | Повторное исследование SVG-фильтров, `Glass Test Stand`, оптического рендерера, массовых A/B, tier-тестов и CSS-улучшений ради CFG-05 **не запускалось** (негативное обязательство, доказывается диффом/индексом evidence) | код/review |
| 4 | **CFG-05.3** (L189) | Полигональный фон, палитра, стеклянные карточки, прозрачность, размытие, блики и компоновка не изменены; регрессионная проверка после CFG-04/прочих UI-работ подтверждает прежний glass | preprod (deployed) |
| 5 | **CFG-05.4** (L190) | Новая **конкретная воспроизводимая** регрессия фиксируется отдельно с доказательствами и чинится точечно в существующей задаче; гипотетический дефект не держит CFG-05 открытым и не задерживает очередь | код/review (процедурная) |
| 6 | **ADD-1.T5** (L24) | CFG-05 = `OBSERVED_FIXED / REUSE_EXISTING`: сверка с U08/SOUL evidence; без новых рендеров, CSS и повторного A/B, если не возник конкретный воспроизводимый дефект | код/review (dedup-guard) |
| 7 | **CFG-05.D** (L185) | `OBSERVED_FIXED / NO_NEW_IMPLEMENTATION`: не запускать отдельную реализацию стекла; однократная сверка deployed SHA + U08/SOUL-17 + наблюдения; закрытие `REUSED_EXISTING/OWNER_VISUAL_CONFIRMED` без нового кода/деплоя | postdeploy |
| 8 | **CFG-05.B** (L192) | Критерий CFG-05: текущее наблюдаемое поведение соответствует запросу владельца; рефракция и полигональный фон сохранены при последующих UI-изменениях; новых обязательств по стеклу и блокировки очереди нет | postdeploy (composite) |

Смежные строки **других слайсов**, которые нельзя присвоить CFG-05:

- **ADD-2.5** (L392) — слайс **CFG-FINAL**: принимает итог CFG-05 (скриншот владельца + U08/SOUL evidence, без переработки/гейта) на финальной сквозной сверке. CFG-05-Verify поставляет evidence, но не закрывает ADD-2.5.
- **CFG-04C.5** — слайс **CFG-04**: before/after и пиксельная инварианта фона — вход для CFG-05.3, не его закрытие.
- **ADD-0.2** — слайс **CFG-FINAL**: «не второй SOUL-1/стекло» проверяется сквозным диффом в конце.

---

## 3. Мастер-состояние на HEAD `5b86517e` / прод 2.58.96 (`95d11472`)

**Коротко:** все 8 строк — **AIV**, кодовой работы нет. Усиленное стекло и полигональный фон уже в проде и не менялись после отревьюенных кандидатов; «дыра» только в том, что факт этот нигде не сведён в один CFG-evidence-пакет и не привязан к deployed SHA релиза CFG-04.

### 3.1 Проверенные факты (git-объекты, без SSH)

| Что | Факт | Чем проверено |
|---|---|---|
| Фильтр линзы `#lg-lens` | блок **6298 байт**, sha256 `5367ec4566fc9e80ad08…` — **идентичен** на `HEAD`, `a5902b15` (отревьюенный SOUL-кандидат TIERA-STRONG), `95d11472` (прод 2.58.96), `915aa3c7`, `0ca661fe` (WG) | `git show <rev>:web/index.html` + извлечение `<filter id="lg-lens">…</filter>` |
| Усиление | в блоке `scale="32"` (пик карты 16 px, плато у кромки) — это TIERA-STRONG, а не старый `scale=16` | тот же блок + `soul-1/evidence/glass-tiera/_strong_evidence.md` |
| Полигональный фон | `web/static/polygon-background.js` git blob **`c2ad97d446f5…`** идентичен на `HEAD`, `95d11472`, `a5902b15`, `0ca661fe`, `915aa3c7`, `95526863` | `git rev-parse <rev>:web/static/polygon-background.js` |
| Android-рефракция (WIN-GLASS-P0) | `web/static/glass-refraction.js` blob **`0c57cc25265e…`** на `HEAD`/`95d11472`/`95526863` | `git rev-parse` |
| Probe | `web/static/glass-probe.js` на `HEAD`/`95d11472` = **`4eab69ac4aa0…`** (WG-версия); SOUL-кандидат `a5902b15` нёс более ранний probe `78e6e069…` — в релиз 2.58.86 осознанно пошла WG-версия, обе отревьюены | `git rev-parse` + `release-2.58.86-report.md` (WG byte-equal) |
| Токены стекла | блок `app.css` L60–130 (`--glass-*`, `--lg-*`) **побайтово равен** на `HEAD` и `a5902b15` | построчное сравнение git-объектов |
| `web/**` на master | после `95d11472` коммитов в `web/` нет (`5b86517e` — `services/mca_expression.py` + тесты/доки); рабочее дерево `web/*` dirty только у CFG-04 | `git log 95d11472..HEAD -- web/`; `git diff --stat` |
| CFG-04-дифф | на момент брифа (рабочее дерево, CFG-04 в полёте) из glass-чувствительного задет только `.tech-key__copy:hover { border-color: var(--glass-border-color) }` — токены/материал/линза/фон не тронуты; после завершения CFG-04 сверку повторить на его финальном кандидате | `git diff -- web/static/app.css` |

**Вывод:** усиленное стекло (SOUL-17/TIERA-STRONG) и полигональный фон уже находятся в проде 2.58.96 и де-факто неизменны с момента ревью. CFG-05-Verify остаётся только **зафиксировать это относительно deployed SHA релиза CFG-04** и визуально подтвердить, что CFG-04 ничего не сломал.

### 3.2 Состояние по строкам

| req_id | Состояние | Якоря и что именно осталось |
|---|---|---|
| **ADD-1.C6** | **AIV (protected)** | `polygon-background.js` blob `c2ad97d446f5…` неизменен на всех релевантных ревизиях; инварианты геометрии/палитры/топологии закреплены `tests/test_webapp_round1026_polygon.py` (palette/topology/TOPO_* /vendor/CSP) и `tests/js/round1026_polygon_background_test.js`; рендерер один, `aurora-flow.js` — soft-откат. Осталось: прогнать пины на deployed-кандидате и зафиксировать blob-равенство в evidence. |
| **CFG-05.1** | **AIV (evidence существует)** | Слои: (а) прод-SHA → `95d11472` сейчас, после CFG-04 — релизный коммит 2.58.97; (б) U08/SOUL-17 evidence: `soul-1/evidence/glass-tiera/**` (`_strong_verify.json` 77/1, `_strong_visibility.json`, `_strong_legibility.json`, `_strong_webview.json`, `_strong_*.png`), `review-tiera.md` + `review-tiera-strengthened.md` (Approved), `w2-reports/W2-GLASS.md`, `w2-evidence-glass/ui-acceptance.md`; (в) WG: `win-glass-hotfix/review-wg.md` (Approved; живой WebView — `PENDING_OWNER_E2E`); (г) наблюдение владельца 18.10.2026 — source L183 (скриншот в чате, **в repo не хранится**). Осталось: один сверочный пакет + формулировка `REUSED_EXISTING / OWNER_VISUAL_CONFIRMED`. |
| **CFG-05.2** | **AIV (negative guard)** | Новых рендеров/стенда/A-B/tier-тестов в CFG-05 быть не должно; доказывается диффом (нет правок `web/**`, `tests/js/**`, `tests/ui_soul1_*`, `tests/glass-teststand/**`) и индексом evidence. |
| **CFG-05.3** | **AIV (protected) + verify** | Материал (нумерация на HEAD `5b86517e`): `app.css` L69 (W2-GLASS токены), L1597 (Tier A), L3570 (lg-panel), L3667 (массовые карточки Tier B), L3695–3739 (HOTFIX-TIERA), L3741 (mini-lens), L3776 (pause/деградация); `web/index.html` L54–61 (`#lg-lens`, `scale=32`), `web/app.js` `_probeTierA` (22552), `_lgGlassSelector` (22666), `_syncLensFilters` (22716), `reconcileLiquidGlass` (22799). Легитимные дельты после SOUL-кандидата: WG-носитель `.lg-refract`/`data-refract-layer` и поздний FS-HOTFIX (fullscreen без стеклянной подложки) — это **не** регрессии. Осталось: визуальная инварианта после CFG-04 (CFG-04 обязан дать before/after фона/glass; иначе CFG-05 снимает свои кадры). |
| **CFG-05.4** | **AIV (процедура)** | Правило триажа: воспроизводимая регрессия → отдельная запись с evidence + точечный фикс в задаче-владельце; гипотеза не блокирует очередь. Реализации нет — проверяется наличием правила в evidence и отсутствием «подвешенных» гипотез. |
| **ADD-1.T5** | **AIV (alias/dedup)** | CFG-05 не создаёт второй реализации стекла; владельцы — SOUL-17 (TIERA-STRONG) и U08/WG. Проверяется диффом: CFG-05 не меняет `web/**` и не добавляет glass-тестов. |
| **CFG-05.D** | **AIV (decision)** | `OBSERVED_FIXED / NO_NEW_IMPLEMENTATION` — регистрация, не разработка; отдельного деплоя стекла нет. |
| **CFG-05.B** | **AIV / composite** | Собирается из `.1` + `.3` + наблюдения владельца; по частичным зелёным не объявлять. |

### 3.3 Честные остатки, которые CFG-05 **не** закрывает

- **SOUL-17.4** — `READY_FOR_LIVE`: перф на реальном Android/Windows, reduced-motion, overdraw. Это строка SOUL-1; CFG-05 её не перепрогоняет и не закрывает.
- **U08-карта** (`asap8-v6-3-live-correction/requirements-map.json`) привязана к `0b7a0aca` (2.58.84) и содержит residue: `REQ-U08`, `U08.3e`, `U08.5.4`, `REQ-U08-DOD`, `B10-R19` = `READY_FOR_LIVE`; `U08.4d`, `U08.5.1`, `REQ-U08-4` = `PENDING`. Это bookkeeping-долг старой карты (аналогично 14 PENDING CFG-03), а не отсутствие кода: TIERA-STRONG инвентарь показывает 16–17 tier-A поверхностей на страницу. CFG-05 ссылается на **артефакты** (verify/inventory/shots/visibility/legibility/webview/perf + ревью), а не на статусы этой карты, и **не** переписывает её строки.
- **WG живой WebView** — `PENDING_OWNER_E2E` в `review-wg.md`; наблюдение владельца 18.10 (L183) снимает именно этот вопрос в части «видно ли на реальном проде», но не превращает perf/иные устройства в проверенные.
- **Клиент наблюдения 18.10 в источнике не назван** (сказано «живой production», карточка «Бот» на «Статусе»). Evidence не должен домысливать платформу: пишем ровно то, что подтвердил владелец.

---

## 4. Алиасы, пересечения и «не закрывать ложно»

| Владелец/алиас | Что уже покрыто | Что делает CFG-05 | Чего делать нельзя |
|---|---|---|---|
| **SOUL-17 / TIERA-STRONG** (`soul-1/glass-tiera-hotfix.md`, `review-tiera-strengthened.md`, `evidence/glass-tiera/_strong_*`) | Усиленная карта (±16 px, `scale=32`), инвентарь 10 маршрутов, verify 77/1, legibility Δrect=0, visibility ×1.76–3.40, perf, честный фолбэк | Ссылается как на evidence; сверяет, что блок линзы в проде тот же | Не переделывать карту/материал, не гонять повторный A/B/perf, не объявлять SOUL-17.4 закрытой |
| **U08 / W2-GLASS** (`W2-GLASS.md`, `w2-evidence-glass/ui-acceptance.md`) | Аудит до правок, слоистая модель, probe, tier-карта, fallback, контраст | Переиспользует как исторический слой доказательств | Не запускать `Glass Test Stand`/оптический рендерер заново |
| **WIN-GLASS-P0** (`win-glass-hotfix/**`, `review-wg.md`) | Android-рефракция через `.lg-refract` (canvas полигонального фона + `url(#lg-lens)`), Windows-диагностика fullscreen | Учитывает как часть задеплоенного стекла; живой WebView-пункт считается покрытым наблюдением владельца | Не менять `glass-refraction.js`, не «улучшать» слой в CFG-05 |
| **FS-HOTFIX 18.10** | Кнопка fullscreen намеренно без стеклянной подложки; шапка не растёт | Считает это легитимной дельтой, а не регрессией glass | Не возвращать стекло на fullscreen и не трогать шапку |
| **CFG-04** | Мобильные формы/save/dirty/keyboard/orientation; обязан дать before/after фона/glass (prep-cfg-04 §5.1, R6) | Потребляет его before/after как вход для CFG-05.3 | Не чинить CFG-04-дефекты внутри CFG-05; регрессия glass → возврат в CFG-04 |
| **ADD-2.5 / CFG-FINAL** | Итоговая сквозная приёмка, в т.ч. принятие скриншота владельца | Поставляет evidence и статус `REUSED_EXISTING/OWNER_VISUAL_CONFIRMED` | Не закрывать ADD-2.5 на CFG-05 |
| **ADD-0.2 / ADD-1.C6** | «Не второй SOUL-1/стекло»; фон неизменен | Подтверждает отрицание диффом и blob-равенством | Не трактовать CFG-05 как разрешение на glass-разработку |
| **CFG-FINAL / ADD-0.5** | Статусная таксономия | Ведёт строки по фактам (`REUSED_EXISTING`, `OWNER_VISUAL_CONFIRMED`) | Не объявлять `VERIFIED` по одному скриншоту без deployed-SHA сверки |

---

## 5. Write scope (файлы, evidence, монополии)

### 5.1 Основной scope

| Путь/glob | Роль | Ограничение |
|---|---|---|
| `plans/features/cfg/evidence/cfg-05/**` | `README.md` (метод и честные границы), `deployed-sha.json` (версия + SHA + sha256_12/блоб-равенство линзы/фона), `reuse-map.md` (U08/SOUL-17/WG → какие артефакты и какие остатки), `glass-invariant.json`/`bg-invariant.json` (результаты пинов и визуальной сверки), `ui/*.png` (прод/локальные кадры «Статуса» и др. поверхностей), `owner-observation.md` (что именно подтвердил владелец, source L183, чего он не подтверждал), `reviewer-summary.md`, `failures.md` | Только факты; без фиктивных PASS и без «нарисованных» скриншотов |
| `plans/features/cfg/prep-cfg-05.md` | Этот бриф | Плановый документ; не источник истины |

### 5.2 Read-only / переиспользование (не писать)

- `web/**` (в т.ч. `index.html`, `app.js`, `static/app.css`, `static/glass-probe.js`, `static/glass-refraction.js`, `static/polygon-background.js`) — **ноль изменений**.
- `tests/**`, `tests/js/**`, `tests/glass-teststand/**` — **не редактировать**; только прогон. Любой необходимый re-pin — прерогатива CFG-04 (если причина в его правках) или отдельного фикс-лейна владельца.
- `plans/features/soul-1/**`, `plans/features/asap8-v6-3-live-correction/**`, `plans/features/win-glass-hotfix/**` — свидетельства читаются, но **не переписываются** (исторические evidence-пакеты).
- `services/param_catalog.py`, `config/settings.py`, `web/api/**` — без изменений; Δ каталога 0, DDL 0.

### 5.3 Монополии и особые случаи

1. **Никакого писателя продуктового кода.** CFG-05-Verify — единственный CFG-слайс без runtime-диффа; появление правок `web/**` = нарушение слайса.
2. **Харнесс `tests/ui_soul1_glass_tiera_e2e.py` пишет в `plans/features/soul-1/evidence/glass-tiera/`** (константа `EVIDENCE`). Запускать его в основном дереве нельзя — это чужая evidence-зона. Основной путь: прогнать харнесс в **scratch-worktree на deployed-коммите** (или на локальном кандидате CFG-04) с `--prefix cfg05_`, затем **скопировать** нужные кадры/JSON в `plans/features/cfg/evidence/cfg-05/`. Допустимая альтернатива — съёмка через browser/Playwright на `https://admin-bot.duckdns.org/web/` (read-only, без SSH; fail2ban не затрагивается).
3. **Новый инструмент — только по амендменту.** Если без тонкого раннера сверки не обойтись, он добавляется отдельным scope-амендментом (`tools/ui_cfg05_glass_evidence.py`, без прод-кода); по умолчанию его нет.
4. **Прод-наблюдения — read-only.** `GET /healthz`, `GET /web/`, скриншоты; никаких записей настроек, никаких массовых генераций.

---

## 6. Фазы Ф0–Ф6

### Ф0 — Вход и база

- Подтвердить: CFG-04 прошёл `release`-гейт и выкачен (ожидается **2.58.97**); `web/**` чист; нет параллельного UI-писателя; CFG-04 evidence `cfg-04/**` содержит before/after фона/glass (если нет — зафиксировать и снимать свои кадры).
- Зафиксировать deployed commit релиза CFG-04 (из release-evidence, не из локального дерева) и `/healthz` == APP_VERSION.
- Прогнать базовые пины (на deployed-коммите в чистом worktree): см. Ф3-команды. При красном пине — сначала выяснить, чей это дефект (CFG-04 / чужой лейн / реальная регрессия glass), а не «подкручивать» тест.

### Ф1 — Deployed-SHA и отпечатки стекла

- `git show <deployed>:web/index.html` → извлечь блок `<filter id="lg-lens">…</filter>`; проверить: длина **6298**, sha256 **`5367ec4566fc9e80…`**, `scale="32"`.
- `git rev-parse <deployed>:web/static/polygon-background.js` → ожидается **`c2ad97d446f5…`**; `glass-refraction.js` → **`0c57cc25265e…`**; `glass-probe.js` → **`4eab69ac4aa0…`** (если релиз не менял web — значения совпадут с 2.58.96).
- Сверить `sha256_12` деплой-файлов из release-evidence CFG-04 с локальным git-деревом `<deployed>` (app.js/index.html/app.css) — расхождение = стоп и эскалация, а не «примерно то же».
- **Δ = 0** по glass-чувствительным путям: `web/static/polygon-background.js`, `web/static/glass-refraction.js`, `web/static/glass-probe.js`, блок `#lg-lens`, блок токенов `app.css` L60–130.

### Ф2 — Reuse-map U08/SOUL-17/WG (без перепрогона тяжёлых замеров)

- Свести в `reuse-map.md`: какие артефакты соответствуют какому требованию (verify/visibility/legibility/webview/perf/shots + ревью-вердикты), с честными статусами: что `VERIFIED`, что `READY_FOR_LIVE`, что `PENDING_OWNER_E2E`.
- Зафиксировать: CFG-05 **не** переигрывает TIERA-STRONG, не пересобирает U08-карту, не закрывает SOUL-17.4.
- Проверить, что `review-tiera.md`, `review-tiera-strengthened.md`, `review-wg.md` — Approved и относятся к тем же блобам/кандидатам, что в проде.

### Ф3 — Регрессионные пины и визуальная инварианта

```powershell
py -3 -m pytest tests/test_webapp_design_tokens_round1025.py tests/test_webapp_round1026_polygon.py ^
  tests/test_webapp_hotfix6_round1025.py tests/test_webapp_js_unit.py -q
node tests/js/glass_probe_test.js
node tests/js/round1025_design_tokens_test.js
node tests/js/round1026_polygon_background_test.js
node tests/js/glass_refraction_test.js
# опционально (измерение сдвига, а не «tierA=true»):
.venv\Scripts\python.exe tests\ui_soul1_glass_tiera_e2e.py verify --prefix cfg05_ --dpr 1
```

- Визуальная часть: замороженный фон (`?bgseed=…` + `__PolygonBackground.pause()`, только внутри харнесса/скриншотного прогона) → сравнить «Статус» (карточка «Бот») и ещё 1–2 поверхности до/после CFG-04 либо с эталоном `_strong_*` на неизменных маршрутах.
- **Харнесс `ui_soul1_glass_tiera_e2e.py` запускать только из scratch-worktree на deployed-коммите** (§5.3.2): он пишет в `plans/features/soul-1/evidence/glass-tiera/`; результаты копируются в `cfg-05/**`, основной worktree не трогается.
- Отдельно: 390 px и 1440 px; зафиксировать, что центр линзы ~0, кромки дают сдвиг, blur/alpha/rim не изменились, фон совпадает по геометрии/палитре.
- Если CFG-04 дал собственный pixel-diff фона/glass — переиспользовать его, а не дублировать массовые замеры; свой прогон — только как страховка/на deployed.

### Ф4 — Прод-наблюдение (postdeploy, read-only)

- `GET https://admin-bot.duckdns.org/healthz` → APP_VERSION == deployed; `GET /web/` → 200.
- Снять «Статус» (карточка «Бот») в проде: desktop + мобильный viewport (эмуляция или реальный браузер), сохранить кадры в `ui/prod-*.png` с подписью «кто/чем/когда снял».
- Зафиксировать в `owner-observation.md`: владелец 18.10.2026 сообщил, что усиленное искажение отчётливо видно на реальной карточке (source L183); **платформа в источнике не названа**; скриншот владельца в repo отсутствует и не подменяется своим кадром.
- Любая новая конкретная воспроизводимая регрессия → `failures.md` (шаги, кадры, причина, владелец-задача), строка CFG-05.4 закрывается фактом регистрации, а не «исправлено здесь».

### Ф5 — Evidence + независимый Review

`plans/features/cfg/evidence/cfg-05/`:

- `README.md` — метод, что сверялось, что переиспользовано, что **не** проверялось, почему нет нового кода/деплоя.
- `deployed-sha.json` — версия, deployed commit, блоб-хеши/`sha256_12`, `/healthz`, дата/время съёма.
- `reuse-map.md` — U08/SOUL-17/WG → evidence + остатки (`READY_FOR_LIVE`, `PENDING`, `PENDING_OWNER_E2E`).
- `pins.txt` / `pins.json` — команды и результаты Ф3 (включая честные skip, если окружение недоступно).
- `glass-invariant.json`, `ui/*.png` — визуальная сверка (локально/прод), с указанием, где фон заморожен.
- `owner-observation.md`, `reviewer-summary.md`, `failures.md`.
- Reviewer независимо проверяет: deployed-SHA и блоб-равенство (сам, не по выводам лейна), отсутствие правок `web/**`/тестов, честность reuse-map (не выданы ли READY_FOR_LIVE за VERIFIED), реальность кадров и подписей, корректность формулировки `OWNER_VISUAL_CONFIRMED`.
- Гейт: `requirements_gate.py check --stage review --slice CFG-05-Verify --candidate <evidence-commit>` (кандидат = docs/evidence-коммит; продуктового диффа нет).

### Ф6 — Закрытие строк и release-гейт

- Закрыть 8 строк по фактам: 3 код/review, 2 preprod, 3 postdeploy; `ADD-2.5` оставить `PENDING` до CFG-FINAL.
- `requirements_gate.py check --stage release --slice CFG-05-Verify --candidate <evidence-commit> --deployed-commit <2.58.97-sha>`.
- Передать в CFG-06: стекло/фон заморожены, новых обязательств нет; в CFG-FINAL — evidence-пакет и формулировку для ADD-2.5.

---

## 7. Какие req_id закрываются/остаются

| Этап | req_id | Условие |
|---|---|---|
| **Код/review** (3) | `CFG-05.2`, `CFG-05.4`, `ADD-1.T5` | Diff-scope guard (нет правок `web/**`/тестов/стенда), наличие правила триажа, dedup-подтверждение; candidate-bound evidence |
| **Preprod/deployed** (2) | `ADD-1.C6`, `CFG-05.3` | Блоб-равенство фона + пины палитры/топологии/рендерера; визуальная инварианта glass после CFG-04 (кадры + неизменные токены/линза/материал) |
| **Postdeploy** (3) | `CFG-05.1`, `CFG-05.D`, `CFG-05.B` | Deployed SHA + U08/SOUL-17 evidence + наблюдение владельца → `REUSED_EXISTING / OWNER_VISUAL_CONFIRMED`; composite B — только после `.1`/`.3` |

**Итого:** 8 строк; **3 код/review + 2 preprod + 3 postdeploy**. Ни одна не закрывается «по зелёным пинам» без deployed-привязки; `ADD-2.5` остаётся в CFG-FINAL.

---

## 8. Риски

| ID | Риск | Митигация |
|---|---|---|
| **R1** | **«Уже исправлено» превращается в фиктивное VERIFIED** без deployed-привязки | Обязательный `deployed-sha.json` с версией, коммитом, блоб-хешами и `/healthz`; Reviewer сверяет сам |
| **R2** | **Повторная glass-разработка под видом проверки** (новые CSS/фильтры/стенды) | Жёсткий diff-guard: ноль правок `web/**`, `tests/js/**`, `tests/glass-teststand/**`; любое отклонение — стоп |
| **R3** | **Чужая evidence-зона:** харнесс пишет в `soul-1/evidence/glass-tiera/` | Запуск только в scratch-worktree с `--prefix`; копирование результатов в `cfg-05/**`; основной worktree не трогать |
| **R4** | **Регрессия от CFG-04** (правки `app.css`/`index.html` задели материал) | CFG-04 обязан дать before/after фона/glass; CFG-05 проверяет токены/линзу/фон и снимает кадры; найденная регрессия → возврат в CFG-04, не «косметика» здесь |
| **R5** | **Смешение платформ:** скриншот владельца выдан за Android/iOS-доказательство | В `owner-observation.md` платформа не домысливается; SOUL/U08 `READY_FOR_LIVE`/`PENDING` остаются видимыми |
| **R6** | **Ложное закрытие U08/SOUL-17** (их карты — другие владельцы, часть строк residue) | CFG-05 ссылается на артефакты, а не на статусы; строки SOUL-17/U08 не переписываются; в README — честный список остатков |
| **R7** | **Гипотетический дефект держит очередь** | Правило L190: только конкретная воспроизводимая регрессия; остальное — в backlog-наблюдения, очередь идёт дальше |
| **R8** | **«Замер по скриншоту»** вместо измеримого сдвига | Если измерение нужно — только существующий харнесс (edge/center, A vs A-без-линзы); кадр без чисел = иллюстрация, не доказательство |
| **R9** | **Fail2ban/прод-дисциплина** при живых проверках | Никакого SSH в этом лейне; только HTTPS `/healthz`, `/web/`, браузер; один-два запроса, без поллеров |
| **R10** | **Раздувание слайса** (массовые A/B, tier на всех карточках, perf-лаборатория) | Прямо запрещено L188; переиспользование `_strong_*` + пины + один визуальный прогон |

---

## 9. Барьеры, зависимости и owner-вход

1. **Вход-барьер:** CFG-04 прошёл `release`-гейт и выкачен (ожидается 2.58.97). `D.4` CFG-04 может остаться `PENDING_OWNER_E2E` по PET — это **не** блокер CFG-05.
2. **Вход-данные:** before/after фона/glass от CFG-04 (prep-cfg-04 R6). Если их нет — CFG-05 снимает свои кадры, но **не** переписывает CFG-04-evidence.
3. **Нет отдельного деплоя:** CFG-05-Verify не создаёт релиз; проверка идёт на уже выкаченном 2.58.97.
4. **Owner-вход: none (PET).** Наблюдение владельца от 18.10.2026 уже зафиксировано в immutable source (L183); повторный вопрос не задаётся. Скриншот в repo не хранится — цитируется source + сообщается честно; при желании Orchestrator может сохранить оригинал в `evidence/cfg-05/owner/` с пометкой происхождения, но это **не** gate.
5. **Device/perf-остатки** (реальный Android/Windows perf, iOS WebKit) остаются у SOUL-17/U08/WG как `READY_FOR_LIVE`/`PENDING_OWNER_E2E`; CFG-05 их не присваивает и не блокирует очередь.
6. **Прод-дисциплина:** только HTTPS-наблюдение; SSH не используется; fail2ban не затрагивается; никаких записей настроек.

---

## 10. Точное действие Orchestrator

1. **Не запускать CFG-05 сейчас:** вход — завершённый релиз CFG-04 (2.58.97) и его `release`-гейт.
2. После релиза: запустить **CFG-05-Verify** как отдельный короткий лейн (verify/evidence, без Builder-кода) на deployed-коммите; write_scope — только `plans/features/cfg/evidence/cfg-05/**`.
3. Проверить по Ф1: `#lg-lens` блок (6298 б, `5367ec4566fc9e80…`, `scale=32`), `polygon-background.js` `c2ad97d446f5…`, `glass-refraction.js` `0c57cc25265e…`, `glass-probe.js` `4eab69ac4aa0…`, `/healthz` = 2.58.97.
4. Прогнать пины Ф3 (design tokens / polygon / hotfix6 / js_unit + 4 node-теста); визуальную инварианту — из CFG-04 before/after + один контрольный прогон; при находке регрессии — вернуть в CFG-04, а CFG-05.4 закрыть записью с evidence.
5. Evidence `cfg-05/**`, независимый Reviewer, `check --stage review --slice CFG-05-Verify --candidate <evidence-commit>`; затем `--stage release ... --deployed-commit <2.58.97>`.
6. **Не смешивать** CFG-05 с CFG-06/07 и не запускать повторную glass-разработку; `ADD-2.5` закрывать только в CFG-FINAL.

---

*Документ подготовительный; единственный источник истины — `plans/features/cfg/requirements-map.json` + `slice-graph.json` + гейт `requirements_gate.py`. В этом лейне код, `current_task.md` и прод не изменялись; SSH не использовался; единственные записи — этот документ, notes/write_scope CFG-05-Verify в карте/графе и docs-коммит `--only`.*
