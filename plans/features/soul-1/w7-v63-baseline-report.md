# SOUL-1 / W7 — реконсиляция наследия v6.3 (SOUL-12 fullscreen, SOUL-13 хвосты)

| Поле | Значение |
|---|---|
| Слайс | W7 (план `plans/features/soul-1/plan.md`, строка W7; вход JB-4 — `web/static` передан W7 после W6) |
| Источник | `plans/features/soul-1/source-current-task.md` §13 (SOUL-12, строки 169–179), §14 (SOUL-13, строки 181–189) |
| Кандидат | HEAD `ba65cbd3f47919857d272c39cab7e9eda97742fa` (ветка `master`) |
| Деплой | **нет** (`deployed_commit` пуст; коммитов/пушей этот лейн не делал) |
| Дата | 2026-10-18 (время среды) |
| Режим | writer, main tree, без коммита/push/деплоя. Fan-out не применялся: вложенные subagent'ы недоступны (depth limit 1) — три «полосы» (fullscreen / embedding / evidence) выполнены последовательно одним исполнителем |

**Что сделано простыми словами:** (1) на клиенте, где кнопка «на весь экран» недоступна,
владелец теперь видит понятное объяснение и конкретную инструкцию, а не просто пропавшую
кнопку; (2) рядом появилась техническая диагностика с фактами для воспроизведения;
(3) закрыт молчаливый сбой конфигурации эмбеддингов (пустой primary-слот при живых
ключах); (4) собран видимый реестр незакрытых живых гейтов v6.3 и сверены git-артефакты;
(5) перепроверены 6 ранее падавших тестов и публичная доступность тестового стенда.

---

## 1. Файлы и отпечатки (sha256, первые 12 hex)

| Файл | Статус | sha256_12 | CRLF |
|---|---|---|---|
| `web/static/fullscreen-policy.js` | изменён (+213/−6) | `b5b14b685cb6` | 0 (LF) |
| `web/app.js` | изменён (+43/−0) | `49b274cf3396` | 0 (LF) |
| `web/index.html` | изменён (+50/−1) | `38071d086d17` | 0 (LF) |
| `tests/js/asap8_w2_fullscreen_policy_test.js` | изменён (+266/−0) | `4faf6f014aca` | 0 (LF) |
| `services/embedding_control_plane.py` | изменён (+117/−16) | `4f892f766f5c` | 0 (LF) |
| `tests/test_soul1_w7_embedding_primary_slot.py` | **новый** | `d79f2851d1d4` | 0 (LF) |
| `tests/test_embedding_control_plane_asap4.py` | изменён (+9/−2, ре-пин shape, §5.4) | `f5a7ed2a7367` | 0 (LF) |
| `tools/ui_soul1_w7_fullscreen_explain_e2e.py` | **новый** | `257d2d97443d` | 0 (LF) |

Артефакты: `plans/features/soul-1/evidence/w7/**` (перечень — §7).

**Прямых записей `prompts.*` нет** (ни одного изменения промптов/каталога: `gen_param_registry_round1025.py --check` → `CHECK OK: реестр 575 == REGISTRY`). **Полигон/стекло не тронуты** — см. §6.4.

---

## 2. SOUL-12 — клауза-за-клаузой

Обозначения состояния: `done` (клауза закрыта локально), `partial` (неживая часть закрыта, живая — нет), `live-open` (закрывается только живьём), `open` (не закрыта).

### SOUL-12.0 — «Fullscreen закрыт только при живом подтверждении»
**Состояние: `live-open` (честно).** Никакого `DONE` не объявляется: в отчёте, в evidence и в docstring нового e2e прямо написано, что моки — только регресс-покрытие. Закрытие строки возможно только после §8 (чек-лист владельцу).

### SOUL-12.1 — «кодовый факт подтверждён и устранён»
Клауза: *«`web/static/fullscreen-policy.js` больше не возвращает `tdesktop_disabled_until_e2e` без объяснения, кнопка присутствует или отсутствует обоснованно, а поведение Launch Mode=Fullscreen на Windows показано владельцу на его клиенте без задержки и ухода UI к левому краю»*.

**Было (RED, воспроизведено до правки):** политика отдавала `reason='tdesktop_disabled_until_e2e'`, кнопка молча исчезала (`v-if="me && fsSlot !== 'hidden'"`), в DOM не было ни одного объяснения, `window.__FullscreenPolicy.explain/diagnostics` не существовали. Реальный рендер (Chromium, мок-клиент tdesktop):
`fs-state-before.json` → `stripPresent=false, hasExplain=false, toasts=[], bodyMentions={}`.

**Сделано (минимальная правка, вся в моей полосе):**
1. `fullscreen-policy.js`: таблицы `REASON_TEXT`/`REASON_NEXT_STEP` и `explainReason()`; `state().reasonText` + `state().nextStep` заполняются в том же решении, что и `reason`; публичные `explain()` и `diagnostics()`. Для tdesktop текст объясняет, почему Windows не получает кнопку (SDK не даёт визуально подтверждённого перехода, CSS не увеличивает родное окно), а `nextStep` даёт конкретную инструкцию: **@BotFather → /mybots → бот → Bot Settings → Main App → Launch Mode «Full» или «Compact» вместо «Fullscreen»** + прямое «бот не может переключить Launch Mode за вас, `expand()` — не замена, родное ✕ остаётся доступным».
2. `web/app.js` (зеркало, ~15 строк): `fsReasonText`/`fsNextStep`/`fsDiag` + одноразовый (дедуп `_fsReasonSeen`) тост с объяснением, **когда слот `hidden` по причине** (вне Telegram — не навязывается).
3. `web/index.html`: один условный свёрнутый `<details data-fs-diagnostics>` сразу под шапкой — «Полноэкранный режим недоступен — почему и что делать» + техническая строка фактов. При `fsSlot !== 'hidden'` не рендерится ничего (DOM поддерживаемого клиента не изменён — проверено).

**Доказательство:** `fs-state-after.json` (toast содержит «@BotFather … Launch Mode «Full» или «Compact»»; `explain().code=tdesktop_disabled_until_e2e`, `explain().nextStep` содержит BotFather; тело страницы содержит BotFather/Launch Mode/Full/Compact); e2e `S1_tdesktop_explained` 33/33 (`_explain_results.json`); скриншоты `S1_tdesktop_explained_1024.png`, `S5_strip_320.png`, `w7_mcp_tdesktop_strip_open.png`.

**Честная граница:** вторая половина клаузы — «поведение Launch Mode=Fullscreen на Windows показано владельцу **на его клиенте**, без задержки и ухода UI к левому краю» — **не проверена и не может быть проверена локально** (нужен реальный Telegram Desktop Windows после деплоя). Состояние: `LIVE_UNVERIFIED` + чек-лист §8.

### SOUL-12.2 — «три операции разделены и не выдаются друг за друга»
Клауза: режим запуска/BotFather (A) ≠ `requestFullscreen/exitFullscreen` + события + `isFullscreen` (B) ≠ responsive CSS (C); `expand()` не замена; нет WinAPI/`moveTo`/`resizeTo` и обещаний контролировать окно Desktop.
**Состояние: `done` на уровне кода** (не менялось этим лейном — подтверждено и защищено сторожем):
- `request()/exit()` — единственные пути к TMA API, повторный `requestFullscreen` при already-fullscreen/launch-mode не отправляется (негатив 5.3b: `wa.__calls == []`);
- `/window\.(moveTo|resizeTo)\(/` отсутствует и в `app.js`, и в политике (раздел 4 node-сторожа);
- `expand()` не используется как fullscreen-фолбэк (раздел 4);
- «BotFather программно не меняется» зафиксировано текстом `nextStep`.
**Честная граница:** визуальное разделение на живом клиенте (реально ли полноэкранное окно ОС, а не CSS-класс `fullscreen-mode`) — `LIVE_UNVERIFIED`.

### SOUL-12.3 — матрица клиентов, записанные факты, SDK-предупреждения в технической диагностике
**Состояние: `partial`.**
- *Нежимая часть* («записывать для воспроизведения…», «предупреждения SDK и UX-причины показать владельцу в технической диагностике») — **сделано**: `diagnostics()` отдаёт `platform`, `sdkVersion`, `launchParams` (только публичные `tgWebApp*` из URL), `isFullscreenSupported`, `actualFullscreen`, `launchFullscreen`, `hasRequestFullscreen`, `hasExitFullscreen`, `hasExpand/hasReady/isExpanded`, `slot`, `reason/reasonText/nextStep`, `width/height/stableHeight`, `safeAreaInset`, `contentSafeAreaInset`, `ackTimeoutMs`, `initCount`, `clickResult`, `hostBehaviour{softExitTried,launchExitIgnored,sdkSubscribed}`, `trace[]`, `warnings[]`. Секретов нет — только булев факт наличия `initData` (проверено негативом 5.2 и мутацией M6/M4).
- *Живая часть* (прогон матрицы по реальным Desktop Windows Compact/Full/Fullscreen, deep link, Android portrait/landscape, Telegram Web, standalone) — **`LIVE_UNVERIFIED`**, ждёт деплоя; «запуск из кнопки и по direct deep link» записан в чек-лист §8.
**Доказательство:** S1 (33 проверки, список полей диагностики) + скриншот раскрытого стрипа в реальном Chromium (MCP Playwright и Browser Use).

### SOUL-12.4 — новая acceptance-политика
Клауза: на поддерживаемом клиенте — рабочий enter/exit с визуально подтверждённым fullscreen (не CSS-класс); на неподдерживаемом — понятное объяснение/вариант нормального запуска без несуществующей кнопки и ложного успеха; для Windows — безопасный workflow запуска и кнопка безопасного выхода с сохранением доступности native ✕; владелец получает конкретную инструкцию по режиму BotFather.
**Состояние: `partial`.**
- *Сделано:* объяснение + конкретный безопасный workflow запуска показываются владельцу (стрип + тост); native ✕ не тронут (крестик мини-аппа по-прежнему закрывается только самим Telegram — собственных «выходов» не добавлялось); кнопка по-прежнему **не** показывается там, где обещать нельзя (негатив: `S3`-совместимый клиент не изменён; tdesktop `S1` — кнопки нет, но есть объяснение).
- *Не проверено:* «визуально подтверждённый fullscreen на поддерживаемом клиенте» и «инструкция с доказательством на клиенте владельца» — postdeploy (`LIVE_UNVERIFIED`).
**Доказательство:** e2e S1/S3/S4; негативы 5.1/5.3 прямо валят сборку, если объяснение исчезает (мутации M1/M2/M3/M6/M9/M10).

### SOUL-12.5 — «не объявлять закрытым; моки — только регресс; safe area; без jump; последовательность; полигон не тронут»
**Состояние: `done` для локально проверяемого + `live-open` для живого подтверждения.**
| Подклауза | Как закрыта |
|---|---|
| Стенд-моки не выдаются за приёмку | docstring `tools/ui_soul1_w7_fullscreen_explain_e2e.py` и `tools/ui_asap8_w2_fullscreen_e2e.py` прямо говорят «mock-only, живые клиенты — postdeploy»; в этом отчёте нет объявления Fullscreen закрытым |
| Mobile safe area, отсутствие перекрытий | float-слот по `csa.top>=36` + резерв header-а; S1 (`y >= csa.top`, hit ≥44×44), S8 ширины 320/390/667×375, S5 узкие ширины — `hOverflow=false` |
| Никаких DOM-вставок в родную шапку Telegram | не добавлялось: единственный узел ⛶ прежний, стрип — в потоке контента приложения |
| Мигалка/перескакивание: зафиксировать `ready`, `expand`, `request`, `viewportChanged`, начальную разметку, двойную инициализацию | `diagnostics().trace[]` пишет `init/request/exit/fullscreenChanged/fullscreenFailed/viewportChanged/softExit/ackTimeout/launchExitIgnored`, `initCount` + WARN `DOUBLE_INIT`; `hasReady/hasExpand/isExpanded/launchFullscreen` — факты SDK (граница: `ready`/`expand` зовёт `telegram-init.js`, политика их не перехватывает — вместо этого фиксирует факт) |
| Убрать внутренний layout jump | шапка не двигается после появления стрипа: S1 сравнивает ранний и поздний замер `headerRect` (`y`, `h`) — совпадение |
| Полигональный фон не трогать | `frozen-check.txt`: 0 «подозрительных» строк диффа, `git diff --numstat web/static/` = только `fullscreen-policy.js`, base64-блоб полигона и блоки `#lg-lens`/`--lg-*` побайтово совпадают с HEAD |

---

## 3. SOUL-13 — клауза-за-клаузой

### SOUL-13.0 / 13.1 — baseline v6.3 и видимый реестр остальных гейтов
**Состояние: `done` (артефактами).**
- `evidence/w7/v63-baseline-record.json` — точный release baseline линии v6.3: задеплоенный canary `c2775a54258512a3e20c97341d3e8a6738b1a33b` (2.58.79), pre-deploy `b9ea4907ffa52e7b2974e9511113e03350820a6e` (2.58.78), поздние изолированные релизы `6d4b9a7d…` (2.58.81) и `448cc81a…` (2.58.83), версия в репозитории `2.58.81`; местоположение 8 отчётных артефактов v6.3 с `blob_HEAD`/`sha256`/флагом `dirty`.
- `evidence/w7/v63-live-gates-ledger.json` — **отдельный видимый реестр**: 65 незакрытых строк (`42 READY_FOR_LIVE`, `18 BLOCKED_REAL_HUMAN_GATE`, `5 PENDING`) с `slice`, `reason`, числом evidence-записей, плюс сопоставление с шестью названными в §14 категориями (live Windows/Android, initiative SEND, Experience load/lag, Cover Style publish, supergroup migration, 24/48h observability) и с пробами V01–V07 / B12.
- **Ни одна строка не переименована в «closed»**; соседняя карта v6.3 не редактировалась (`source_map_working_tree` в ledger — `M` = чужая незакоммиченная правка, зафиксирована как есть).
- ASAP8 v6.3 **не переисполнялся целиком**: этот лейн не запускал релизные прогоны и не менял релизную линию; закрыты только те хвосты, что перечислены в §14.

### SOUL-13.2 — тестовый стенд
**Состояние: `done` для локально проверяемого, `LIVE_UNVERIFIED` для совпадающего с текущим кандидатом прод-пробы** (строка `live_when=postdeploy`).
- 7 анонимных путей (`/static/glass-teststand.{html,css,js}`, `/web/static/glass-teststand.{html,css,js}`, `/web/glass-teststand.html`) → 401/403/404: `pytest tests/test_webapp_teststand_guard.py` → **5 passed** (включая «боевые ассеты того же контура по-прежнему 200»: `/static/glass-probe.js`, `/static/glass.js`, `/static/vendor/lg-lens-map.png`, `/web/`).
- Положительная проверка разрешённой test-среды: фикстура `tests/glass-teststand/` самодостаточна (относительные ссылки на боевые ассеты, без серверных монтов) и **реально рендерится**: `teststand-test-env-local.json` + `teststand-test-env-local-render.png` (2 стилевых листа, 4 `[data-glass]` узла, 0 ошибок страницы).
- Публично смонтированное дерево чисто: `test_stand_absent_from_public_static_tree` + `test_prod_ui_does_not_reference_stand`.
- Независимое прод-подтверждение (не мой прогон, но настоящий прод-факт из релизного лейна 2.58.83): `evidence/release-25883/ev_deploy_run.txt` → `STAND_CODE=404` для всех шести путей на боевом хосте (443).
- **Честная граница:** эта прод-проба сделана на кандидате `448cc81a…`, а не на текущем HEAD; строка остаётся postdeploy-класса — решение о её статусе принимает родитель/Reviewer, а не этот лейн.

### SOUL-13.3 — «живые 14 pending-гейтов v6.3»
**Состояние: `done` (реестр собран, статусы не переименованы).**
- «14» — историческое состояние привязки `225c3c2b` (13 `READY_FOR_LIVE` / 14 `BLOCKED_REAL_HUMAN_GATE`). **Сейчас** в рабочей (незакоммиченной) карте v6.3: **42 `READY_FOR_LIVE` + 18 `BLOCKED_REAL_HUMAN_GATE` + 5 `PENDING`** (135 `VERIFIED`). Оба числа зафиксированы в ledger, без «закрытий».
- Детальный список по категориям §14 — `v63-live-gates-ledger.json` → `category_status`.
- Проверка истории: `BLOCKED_REAL_HUMAN_GATE` остались именно те гейты, что требуют человека/живого клиента (живые Windows/Android, натуральный canary, стилизованная доставка, миграция супергруппы), а не «удобная отговорка»: у каждой строки в ledger приведён `reason`.
- `healthz ≠ полный end-to-end` соблюдено буквально: ни `healthz`, ни зелёные юнит-тесты не использованы как закрытие живых категорий.

### SOUL-13.4 — embedding quota
**Состояние: `partial` — нежимая часть закрыта кодом, провайдерская — `LIVE_UNVERIFIED` (и не выдумана).**
- *Задокументированная фактическая ротация и общий proxy-host* (внешнее доказательство уже собрано в v6.3, цитируется, не переизобретается): коммит `225c3c2b` → `plans/backlog.md`, «v6.3 Wave 4 — ключи эмбеддингов»: каждый alias → своя quota-группа, прод-журнал `primary 429 → fallback_1 429 → fallback_2 429` в 00:05, **все три ключа ведут на один provider-host `apinet.cloud`** (`gemini-embedding-001`) → одновременное исчерпание указывает на кап прокси-апстрима. Вывод «три ключа = три независимые квоты» **не делается**.
- *Различение отсутствующего / доступного через hot-config / деградации пула* — **реализовано** (`services/embedding_control_plane.py`):
  `resolve_key_slot(hot_key, env_name, env_value)` → `(value, source)`, `source ∈ hot|env|absent` (hot перекрывает env, пустая строка = отсутствие); `EmbeddingCredential.key_source`; `pool_rotation_diagnosis()` → `primary_present`, `primary_source`, `degraded`; панель `provider_panel().rotation` → `primary_present`, `primary_source`, `primary_state` (`primary_from_hot|primary_from_env|primary_absent|empty_pool`), `primary_warn`, `primary_hint`, `degraded`; `credential_rows[].key_source`.
- *Недеструктивный WARN* — `_maybe_warn_missing_primary()`: ≤1 раз / 10 мин, под мастер-флагом зоны, только коды/счётчики, без значений ключей; вызывается и в `provider_panel()`, и в горячем пути embed. **Никаких секретов в файл/отчёт не записано.**
- *Понятное состояние владельцу* — в существующей панели «Embedding provider» появился блок `data-embeddings-primary-state` / `data-embeddings-primary-warn` («primary-слот пуст · только fallback · источник: absent» + конкретный hint).
- *Реальный reset horizon* — **не выдуман**: остаётся внешним фактом (нужно подтверждённое поведение/документация провайдера) и явно назван открытым; `EMBED_QUOTA_RESET_HORIZON_SECONDS` не менялся.
- Тесты: `tests/test_soul1_w7_embedding_primary_slot.py` — **7 passed** (маркер `TEST-LIFECYCLE: CONTRACT owner=SOUL-13.4; REGRESSION owner=SOUL-13.4`).
- **Честная граница:** код не меняет фактическую конфигурацию прода (`EMBEDDING_API_KEY` в `.env` по-прежнему не задан; primary приходит из hot-конфига) — это решение владельца, а не дефект лейна.

### SOUL-13.5 — неполнота git-evidence и `225c3c2b`
**Состояние: `done`.**
- *`release-reconciliation`, `final-audit`, `live-canary` «не обнаружены»* — **устаревшее наблюдение**: все три файла существуют, **отслеживаются git** и их рабочая копия чистая (совпадает с блобом HEAD):
  `release-reconciliation.md` = `104faae2adba…`, `final-audit-current-task.md` = `adc9aa19a632…`, `live-canary.md` = `de0dfd151384…` (ещё 5 отчётных файлов — в `v63-baseline-record.json`). Local-uncommitted за GitHub-evidence **не выдаётся**: в отчёте различаются tracked/clean и `dirty`.
- *`225c3c2b`* — **разрешается как настоящий коммит**: `225c3c2bbc8c5065d5a4afc2c4e0b189b403b77c`, родитель `736a8834ccb6…`, содержимое **docs-only** (`plans/backlog.md`, карта v6.3 `requirements-map.json`, `w4-live-probes.md`; 3 файла, +2009/−411), и является **предком `origin/master` (`998bf4e2…`)** — то есть это реально опубликованный коммит, а не выдуманный SHA. Тема коммита и есть тот «B12-биндинг»: карта привязана к кандидату `c2775a54` (112 VERIFIED / 13 READY_FOR_LIVE / 14 BLOCKED_REAL_HUMAN_GATE).
- *Реальный deployed SHA* (вместо механического копирования): `live-canary.md` → DEPLOY_SOURCE `c2775a54258512a3e20c97341d3e8a6738b1a33b` (2.58.79), pre-deploy `b9ea4907…` (2.58.78); далее ветки релизов `6d4b9a7d…` (2.58.81) и `448cc81a…` (2.58.83). Локальный `master` (`ba65cbd3`) в прод не деплоился.
- Никакие пути/значения не выдуманы: все они вычислены командами git и лежат в `v63-baseline-record.json`.

### SOUL-13.6 — 6 падавших pytest
**Состояние: `done`.**
- Перепроверка на текущем дереве (canonical `.venv`, CPython 3.12.0, aiogram 3.31.0, trafilatura 2.2.0, pytest 9.1.1): **6/6 PASSED** (`pytest-6-previously-failing.txt`).
- Классификация «не дефект продукта» не декларирована, а воспроизведена сравнением интерпретаторов (`evidence/v63-tails/tail2-pytest-matrix.json`, перепроверено): под `py -3` тот же набор падает из-за окружения — `aiogram` без `InputRichMessageMedia` (пин `>=3.31.0`), `trafilatura` не импортируется (`lxml.html.clean` → нужен `lxml_html_clean`, модуль отсутствует). Повторно подтверждено командой в этом прогоне.
- Один из шести когда-то был настоящим дефектом (порядок SSRF-сторожа) — закрыт в `9e63b3cf`; один — устаревший пин, пере-пинен на более строгие проверки. Актуального runtime-бага среди шести нет, поэтому «чинить по risk» нечего: минимальный diff не требуется.
- Граница: «pre-existing» употреблено только там, где есть воспроизводимое сравнение на одном дереве, а не «вне области».

---

## 4. Минимальная правка: что именно изменилось

| Файл | Изменение |
|---|---|
| `web/static/fullscreen-policy.js` | `REASON_TEXT`/`REASON_NEXT_STEP`/`explainReason()`; `state().reasonText/nextStep`; `explain()`; `diagnostics()`; трейс (`init/request/exit/fullscreenChanged/fullscreenFailed/viewportChanged/softExit/ackTimeout/launchExitIgnored`), `initCount` + `DOUBLE_INIT`, `warnings[]`, `clickResult`. Прежние API/ключи/поведение и единоличное writer-ство `html.fs-*`/`data-fs-reason` сохранены; новых CSS-классов/переменных нет |
| `web/app.js` | зеркало `fsReasonText/fsNextStep/fsDiag` в `_fsPolicySync` (единственная изменённая функция) + одноразовый тост-объяснение; диагностика берётся из `policy.diagnostics()`, второго сборщика фактов нет |
| `web/index.html` | один условный `<details data-fs-diagnostics>` под шапкой (только `fsSlot==='hidden'` и причина ≠ `no_telegram_context`); **второй** блок — состояние primary-слота в существующей панели «Embedding provider» |
| `services/embedding_control_plane.py` | `resolve_key_slot()`, `key_source`, `primary_present/primary_source/degraded`, `_maybe_warn_missing_primary()`, поля панели, `primary_hint` |
| тесты | новый node-раздел 5 (SOUL-12.1/12.3/12.4/12.5) в существующем стороже; новый python-файл SOUL-13.4; один ре-пин shape в `test_embedding_control_plane_asap4.py` (см. §5.4) |
| `tools/ui_soul1_w7_fullscreen_explain_e2e.py` (новый) | детерминированный e2e владельческого объяснения + снимка диагностики (5 сценариев, 55 проверок) |

### 4.1 Область записи — честная пометка для Reviewer
План §3 отдаёт W7 после JB-4 только `web/static`. Однако acceptance SOUL-12.4 буквально требует **показать** владельцу объяснение и вариант запуска, а SOUL-13.4 — «понятное состояние»; без минимальной additive-вставки в `web/index.html` + `web/app.js` это требование невыполнимо. W6 (владелец этих файлов) закрыт и в дереве не работает; правки сформулированы как добавление (54 и 43 строки, удалений — одно: `</header>`-контекст), без редизайна и без затрагивания замороженных токенов. Если Reviewer считает это выходом за область — это адресное замечание к формулировке плана, а не незамеченный дрейф.

---

## 5. Прогоны

| Прогон | Результат | Артефакт |
|---|---|---|
| Node-сторожа, все `tests/js/*_test.js` | **86 файлов, 0 failed** (в т.ч. `asap8_w2_fullscreen_policy_test.js` → `FS-POLICY-OK`, `asap8_w2_shell_mobile_nav_test.js` → `W2-SHELL-UNIT-OK`, `glass_probe_test.js`, `round1025_design_tokens_test.js`, `round1026_polygon_background_test.js`, `routing_test.js`, `vue_mount_test.js`) | `node-guards-86.txt` |
| Периметр `-k "webapp or ia_ or soul1 or round1025 or round1024 or ui_ or glass or persona or prompt or registry or catalog"` | **3915 passed, 0 failed** (10244 deselected; база AMD26-привязки 3908/0 → +7 = новые SOUL-13.4 тесты) | `pytest-perimeter.txt` |
| Embedding/memory sweep `-k "embedding or graphrag or quota or summary_memory or memory_maintenance"` | **534 passed, 0 failed** | `pytest-embedding-sweep.txt` |
| Embedding-контур адресно | **97 passed** (`test_asap8_f8_embeddings`, `test_embedding_control_plane_asap4`, `test_asap44_graphrag_batch_breaker`, новый `test_soul1_w7_embedding_primary_slot`) | `pytest-embedding-suites.txt` |
| 6 ранее падавших + станд-сторож | **11 passed** | `pytest-6-previously-failing.txt` |
| Реплей существующего mock-e2e v6.3 (`S1`–`S8`), запущен из scratch | **7/7 PASS, 70 проверок** | `w2-e2e-replay.txt` |
| Новый e2e SOUL-12 | **5/5 PASS, 55 проверок** | `_explain_results.json`, скриншоты |
| Мутационный свидетель, fullscreen | **10/10 KILLED** (файлы восстановлены, sha до/после совпал) | `mutation-witness-fullscreen.txt` |
| Мутационный свидетель, embedding | **8/8 KILLED** (источник восстановлен) | `mutation-witness-embedding.txt` |
| `tools/gen_param_registry_round1025.py --check` | `CHECK OK: реестр 575 == REGISTRY` | — |
| Заморозка полигона/стекла | **RESULT: OK** | `frozen-check.txt` |

### 5.1 Мутационные свидетели (что именно ловится)
Fullscreen: пропавший `reasonText`; пустой текст объяснения; выброшенный `nextStep`; безусловный стрип (навязывание вне Telegram); удалённый стрип; утечка `initData` в `diagnostics()`; «вечный» `clickResult='never'`; пропавший `DOUBLE_INIT`; tdesktop без инструкции BotFather; тост-объяснение вне Telegram.
Embedding: «`primary_present` всегда True»; «`primary_source` всегда hot»; отключённый WARN; утечка значения ключа в `credential_rows`; сломанный приоритет env-над-hot; `primary_warn` всегда False; снятый rate-limit WARN; пустой hint.

### 5.2 RED до правки (воспроизведён, не заявлен)
`fs-state-before.json`: tdesktop → `btnPresent=false`, `hiddenClass=true`, `data-fs-reason=tdesktop_disabled_until_e2e`, **`stripPresent=false`, `hasExplain=false`, `hasDiagnostics=false`, `toasts=[]`**; поддерживаемый android → кнопка есть, стрипа нет (эталон «не изменилось»); вне Telegram → `no_telegram_context`.
Плюс source-RED для SOUL-13.4: коммит `225c3c2b` сам фиксирует «`pool_rotation_diagnosis()` НЕ диагностирует пустой primary-слот: при 2 ключах возвращает `degenerate: False` → деградация пула без WARN» (`plans/backlog.md`, v6.3 Wave 4, п.2).

### 5.3 Визуальная приёмка (2 обязательных канала)
- **Playwright (детерминированно, MCP + python-харнесс):** реальный Chromium, реальные `web/index.html`+`web/app.js`+`fullscreen-policy.js`, мок SDK через route. Стрип: `summary` = «Полноэкранный режим недоступен — почему и что делать», в тексте есть «CSS не может увеличить родное окно Telegram…», BotFather, Full/Compact и техническая строка; `headerRect` до/после не меняется (`y=0,h=92`), `hOverflow=false`; 320 px — `stripW=320`, без overflow.
- **Browser Use (реальный рендер):** тот же стенд в настоящем Chrome — стрип виден и читаем, кнопка ⛶ отсутствует, усечений/наложений нет; отдельно проверены 320 px (`overflow=false`, `stripH=328`) и локальный рендер тестового стенда (§3 SOUL-13.2).
- Скриншоты: `S1_tdesktop_explained_1024.png`, `S2_tdesktop_launch_1024.png`, `S3_supported_390.png`, `S5_strip_320.png`, `S5_strip_390.png`, `w7_mcp_tdesktop_strip_open.png`, `teststand-test-env-local-render.png`.
- **Visual Neighborhood Sweep:** вокруг изменённого места дефектов не видно; посторонний пустой прямоугольник-карточка в «Статусе» — артефакт мок-данных стенда (см. §9).

### 5.4 Один ре-пин чужого теста (явно)
`tests/test_embedding_control_plane_asap4.py::test_degenerate_pool_hint` сверяет `pool_rotation_diagnosis()` **точным равенством словаря**. Добавление полей SOUL-13.4 расширяет контракт → тест ре-пинен: прежние поля проверяются как раньше, добавлены `primary_present/primary_source/degraded` для двух пулов. Ослаблений нет (те же значения, плюс новые); `degenerate`-семантика D3 не переопределена (`test_single_known_group_still_degenerate`).

---

## 6. Живые границы и что осталось

1. **Fullscreen закрытым не объявляется** (`SOUL-12.0`, `SOUL-12.1–12.5` живая половина). Всё, что можно было сделать без клиента, сделано и доказано; остальное — §8.
2. **SOUL-13.2** — локальная часть закрыта, прод-проба существует, но относится к другому кандидату; статус строки решает родитель/Reviewer.
3. **SOUL-13.4** — reset horizon провайдера не подтверждён (внешний факт), конфигурация прода не менялась.
4. **SOUL-13.3** — статусы взяты из **незакоммиченной** соседней карты; после её коммита числа могут сдвинуться. Ledger хранит `sha256` карты — расхождение будет видно.
5. `UNIFIED_COMPOSER_ENABLED` и прочие оси этим лейном не включались.

---

## 7. Артефакты evidence

```
plans/features/soul-1/evidence/w7/
  _explain_results.json                    # 5 сценариев e2e SOUL-12 (PASS)
  fs-state-before.json / fs-state-after.json  # RED→GREEN реального рендера
  v63-live-gates-ledger.json               # реестр 65 незакрытых гейтов v6.3
  v63-baseline-record.json                 # baseline v6.3 + git-факты 225c3c2b + deploy-цепочка
  node-guards-86.txt                       # 86/86 node-сторожей
  pytest-perimeter.txt                     # 3915 passed / 0 failed
  pytest-embedding-sweep.txt               # 534 passed / 0 failed
  pytest-embedding-suites.txt              # 97 passed (адресно)
  pytest-6-previously-failing.txt          # 6/6 + станд-сторож
  w2-e2e-replay.txt                        # 7/7 реплей mock-e2e v6.3 (70 проверок)
  mutation-witness-fullscreen.txt          # 10/10 KILLED
  mutation-witness-embedding.txt           # 8/8 KILLED
  frozen-check.txt                         # полигон/стекло не тронуты
  teststand-test-env-local.json / .png     # положительная проверка test-среды (SOUL-13.2)
  S1_...png, S2_...png, S3_...png, S5_...png, w7_mcp_tdesktop_strip_open.png
  _probe_fs_explain.py, _serve_fs.py, _frozen_check.py, _build_v63_ledger.py,
  _make_replay.py, _mutate_fs_witness.py, _mutate_embed_witness.py, _teststand_local_probe.py
```

---

## 8. Чек-лист владельцу: живые проверки (клиенты, никто их не «закрывает» за вас)

**Шаг 0 (подготовка, ничего не меняет в проде):** в BotFather у бота → *Bot Settings → Main App (Configure Mini App)* запомните текущий **Launch Mode**.

**A. Telegram Desktop (Windows) — режимы Compact / Full / Fullscreen**
1. Откройте Mini App из **кнопки** бота. Справа вверху: есть ли ⛶? (ожидание: нет — на Desktop её не обещаем).
2. Раскройте полосу «Полноэкранный режим недоступен — почему и что делать» и перепишите себе строку фактов (`platform`, `SDK`, `fullscreen`, `методы`, `stableHeight`, `safe-area top`, `последний клик`, `init`, `предупреждения`).
3. Переключите Launch Mode на **Full**, перезапустите Mini App. Ожидание: окно открывается обычным окном, UI **не прижат к левому краю**, нет задержки перед появлением интерфейса.
4. Повторите для режимов **Compact** и **Fullscreen**. Ключевое, что нужно зафиксировать: в режиме **Fullscreen** на Windows появляется ли маленькое окно у левого края (исторический дефект v6.3) — если да, нужный лечебный режим = **Full** (или **Compact**).
5. Запустите тем же способом по **прямой deep link** и из **кнопки** — поведение окна должно совпадать.
6. Убедитесь, что родное закрытие окна Telegram (✕) работает и ничего не перекрывает системные зоны (⋮/✕).

**B. Android (portrait и landscape)**
1. Откройте Mini App на **поддерживаемом** клиенте. Ожидание: ⛶ **есть** (справа вверху), тап → экран **реально** разворачивается (без обрезки системных зон), повторный тап → выход.
2. Поверните экран в полноэкранном режиме: UI не «прыгает», кнопка не дублируется, позиция не уезжает под системные зоны.
3. Если кнопка появилась «в потоке» (не у края) — значит `content safe area top < 36`; это ожидаемое честное поведение, но зафиксируйте значение.

**C. Telegram Web / standalone**
1. Откройте Mini App в браузере: ожидание — без ⛶, и **без** навязчивой полосы объяснения (вне Telegram она не показывается).

**D. Launch Mode = Fullscreen на Android**
1. Ожидание: второго запроса на весь экран не происходит, кнопка сразу = **выход**. Отправьте её и убедитесь, что вы вышли, а не «остались на месте».

**Что прислать:** платформу, версию Telegram, Launch Mode, был ли ⛶, что произошло по тапу, и строку фактов из шага A2. Этого достаточно, чтобы закрыть SOUL-12.0/12.1/12.3/12.4/12.5 живой половиной.

**E. (Со стороны контура, не owner-действие):** прод-проба анонимных 6–7 путей стенда на задеплоенном кандидате (SOUL-13.2) и подтверждение reset horizon провайдера эмбеддингов (SOUL-13.4).

---

## 9. Инцидентные находки

| Находка | Класс | Влияние |
|---|---|---|
| Дублирующиеся ключи `_prefersReducedMotion` в `web/app.js` (21220 и 21239) | unrelated/pre-existing (есть и в HEAD: 21177/21196) | Сторож `app_methods_dup_keys_guard_test.js` проходит, но печатает WARN; не трогал |
| Пустой прямоугольник-карточка в «Статусе» на стендe | unrelated/pre-existing, артефакт мок-данных | Не дефект продукта; на живых данных стаб не используется |
| Соседние незакоммиченные файлы v6.3 (`requirements-map.json`, `map-reconciliation-2026-10-16.md`, 12 PNG) | related-nonblocking | Не трогал; реплей e2e запущен из scratch, чтобы не перезаписать их PNG |
| `.playwright-mcp/` растёт в репозитории (untracked) | unrelated/pre-existing | Мусор от прежних прогонов; свои скриншоты складывал в `evidence/w7` |
| Числа «14 pending-гейтов» в §14 устарели относительно рабочей карты (42/18/5) | related | Зафиксировано в ledger, не «исправлено» молча |

---

## 10. Итог для Orchestrator

- **SOUL-12:** нежимые части 12.1/12.2/12.3/12.4/12.5 закрыты и доказаны (RED→GREEN, негативы, мутации 10/10, два визуальных канала, полигон нетронут). Живая приёмка — **`LIVE_UNVERIFIED`**, чек-лист §8; строка SOUL-12.0 **никогда** не объявляется закрытой здесь.
- **SOUL-13:** 13.0/13.1/13.3/13.5 закрыты артефактами; 13.2 закрыта локально (+внешняя прод-проба, относящаяся к другому кандидату); 13.4 закрыта в нежимой части (код+тесты+состояние в UI), провайдерская часть — честно открыта; 13.6 перепроверена (6/6 PASS, интерпретаторные артефакты воспроизведены).
- **Никакого самовольного `DONE`:** не закрыто ни одной строки явно-живого класса; карты `requirements-map*.json`, `plan.md`, `workflow_state.md`, `runtime_task.md` не редактировались.
- **Кандидат для ревью:** `ba65cbd3f47919857d272c39cab7e9eda97742fa` + рабочее дерево этого лейна (см. §1). Коммит/деплой — за родителем.
