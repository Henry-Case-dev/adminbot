# SAC-REV-R1/R1B — корректива r2 (28.11.2026)

- Кандидат: `2d4bb2427c957f53e957f72481d09fcffd75d918` (tree `a668c54f16dc0754bdee38e4435f2c70895509b9`)
- База кандидата: `0f59db8e1` (SAC-S1/SAC-CORE); ветка `feat/speech-applicability-core-ux`;
  worktree `WorkSpaceData/worktrees/.../speech-applicability-core-ux-fb0425f048bb-6f9fc4ad`
- Закрываемые находки:
  - `SAC-REV-R1-F1` (IN_SCOPE, HIGH, блокирующая): «Куда сохранить» = «Глобально» при
    активном чате, первый Save Core писал `scope:"global"`.
  - `SAC-REV-R1-F1b` (в r1b — `F1`, блокирующая): обязательный Playwright-harness
    `tests/ui_p0a_ux_speech_compact_e2e.py` красный на кандидате (двойной toggle `details`).
  - `SAC-REV-R1B-F2` (IN_SCOPE, блокирующая): строка «действует … редакция» описывала
    ПРОСМАТРИВАЕМУЮ редакцию, противореча runtime-строке; просмотр не был назван отдельно.
  - Подпись редакции из дополнения к r1b: «действует» = runtime (`selection.level`),
    просмотр — отдельной строкой и не меняет подпись «действует».
- Политика: PET_PROJECT (стоячее согласие), прод не разворачивался; production не
  использовался вовсе (никаких SSH/БД/деплой-действий в этой коррективе).

## 1. Что изменено

| Файл | Изменение |
|---|---|
| `web/app.js` | `chatCtxReady`/`_chatCtxWaiters`: контекст области известен только после `loadAccessCtx`; `loadPersona`/`loadSpeechOverview`/`_loadSpeechCore` ждут его до первого `api()` (первый Core-запрос уходит уже с `X-Chat-Id`); после готовности дефолт цели сохранения = фактическая область (`speechScopeDefault()`), явный выбор владельца (`speechScopeTouched`) не трогается; `lockAuth` отпускает ожидание, чтобы без авторизации загрузка честно упиралась в 401, а не висела в «Загружаем…» |
| `web/index.html` | runtime-строка «Действует: … · ваша/заводская редакция» читает только `speechCore.selection.level`; просматриваемая редакция — отдельная строка `Просмотр: …` (+ «не влияет на ответы», если просмотр ≠ runtime). Ранее начатая правка `data-speech-core-readonly` (disabled Save без `can_edit`) сохранена |
| `tests/js/speech_core_scope_ctx_test.js` | Новый поведенческий JS-тест F1 (реальные `methods` из `web/app.js`, стаб только на сетевой границе) |
| `tests/test_webapp_js_unit.py` | Регистрация JS-теста `test_js_unit_speech_core_scope_ctx` (маркер `SPEECH-CORE-SCOPE-CTX-OK`) |
| `tests/test_speech_applicability_core_ux.py` | Статические проверки F1/F2b с осмысленными сообщениями (дефолт цели — `speechScopeDefault()`) |
| `tests/ui_p0a_ux_speech_compact_e2e.py` | Одно открытие `details`; «Вернуть заводской» — видимая кнопка; новый сценарий `runtime-vs-view` (runtime=компактная+заводская, просмотр=полная владельческая) с проверкой неизменности подписи «действует» и runtime-селектора |

## 2. RED/GREEN по блокерам

### F1 — первый вход в чат (поведенческий JS-тест)

`tests/js/speech_core_scope_ctx_test.js` дергает реальные `methods` (`_loadSpeechCore`,
`loadAccessCtx`, `saveSpeechCore`), подменяя только `api()`.

RED на базовом `web/app.js` (`git show 0f59db8e1:web/app.js`, `APP_JS=<файл> node ...`):

```
 - A: /api/speech/core не должен уходить до разрешения области (иначе target scope фиксируется как global)
 - A: Core запрошен уже в контексте чата (["/api/speech/core","/api/access/me","/api/access/chats"])
 - A: «Куда сохранить» по умолчанию = этот чат, не «Глобально» (получено: global)
 - A: первый Save Core в чате уходит scope="chat" (получено: "global")
 - B: ожидание области действует и без сохранённого чата
```

GREEN на кандидате: `SPEECH-CORE-SCOPE-CTX-OK` (rc 0).

Проверяемые утверждения (A — чатовая область, B — негативный контроль):

1. до `loadAccessCtx` запроса `/api/speech/core` нет;
2. Core запрошен ПОСЛЕ `/api/access/chats` (в контексте чата);
3. `activeChatId` применён; `speechScopeFor('core') === 'chat'`;
4. реальный `saveSpeechCore()` шлёт POST с `scope:"chat"` и текстом черновика;
5. B: глобальная область (`activeChatId == null`, `inheritance=global`) — цель остаётся
   `global`, сохранение уходит `scope:"global"` (фикс не «прибивает» чат везде);
6. C: после `lockAuth` ожидание разрешается, загрузка отвергается 401 (нет вечного
   «Загружаем…»).

### F2 — обязательный e2e-харнесс

```
.venv/Scripts/python.exe tests/ui_p0a_ux_speech_compact_e2e.py            -> == ИТОГ: failures=0, POST=21
.venv/Scripts/python.exe tests/ui_p0a_ux_speech_compact_e2e.py --shots …  -> == ИТОГ: failures=0, POST=21
```

Прогон реальных `web/index.html` + `web/app.js` + `web/static/app.css`, route-стабы `/api/*`;
выполняются все сценарии (layout 320…1280, save-409/503, scope/изоляция чатов, core-extras,
history, humor/learning, examples, expression, readonly, runtime-vs-view).

### F2b — подпись «действует» vs просмотр

Стаб сценария `runtime-vs-view`: runtime = компактная **заводская**
(`differs_from_factory=false`), просмотр полной = **владельческая** (`true`) — ровно
противоречивый случай ревью r1b.

GREEN-проверки сценария: `[data-speech-core-runtime]` содержит «компактная» и «заводская
редакция», не содержит «ваша редакция»; после клика `[data-speech-core-view="full"]`
runtime-строка побайтово та же, `[data-speech-core-view-state]` = «Просмотр: полная
редакция · не влияет на ответы», runtime-select остаётся `compact`.

Визуально (Playwright, 390×844, скриншоты этой сессии):
`evidence/corrective-r2/runtime_vs_view_390.png` — «Действует: компактная редакция — выбрана
вами · заводская редакция» + «Просмотр: компактная редакция»;
`evidence/corrective-r2/runtime_vs_view_full_390.png` — та же runtime-строка + «Просмотр:
полная редакция · не влияет на ответы».

RED: статический тест `test_runtime_edition_label_is_not_the_viewed_one` на базовом
`web/index.html` — «подпись «действует» не должна читать просматриваемую редакцию»
(база использует `editions[speechCoreEdition]`). RED-проба: 2/2 (F1 + F2b) на базовых
`web/app.js`/`web/index.html`.

## 3. Профильные прогоны (кандидат, `.venv` py3.12, node v24.16.0)

| Прогон | Результат |
|---|---|
| `pytest tests/test_speech_applicability_core_ux.py -q` | **15 passed** |
| `pytest tests/test_ur_ui_effective_config.py tests/test_soul1_w6_speech_ui.py tests/test_evol017_prompt_history_ui.py -q` | **68 passed** |
| `pytest tests/test_persona_api.py tests/test_round1025_f8_registry.py tests/test_mca23_planned_vs_actual.py tests/test_webapp_api.py tests/test_speech_mobile_entry_contract.py -q` | **242 passed** (пины `ROUTES_SHA256_F11`, `PARAM_CATALOG_SHA256_FOLLOWUP` включены) |
| `pytest tests/test_webapp_js_unit.py` (JS-набор) | **43 passed, 7 failed — все 7 предсуществующие** (см. §4) |
| `pytest tests/test_webapp_evol_w10_sections.py -k "not live_render"` | **39 passed, 5 failed — все 5 предсуществующие** (см. §4) |

## 4. Предсуществующие падения (не вызваны диффом)

Проверено на базовых `web/app.js`/`web/index.html` (0f59db8e1), вне репозитория:

- `tests/js/routing_test.js`, `tests/js/round1024_image_key_test.js` →
  `TypeError: this._embedModelSwapGuard is not a function` — воспроизведено на базовом
  `app.js` в зеркале (`tests/js` + `web/app.js` + `web/static/cog-visual.js`), rc=1.
- `round1025_hotfix7/8/9/10_shell_*` — пины `APP_VERSION = "2.58.255"`, фактически
  `APP_VERSION = "2.58.258"`; `config/settings.py` кандидатом не менялся (`git diff` пуст).
- `tests/test_webapp_evol_w10_sections.py`: `TestEvol027Catalog` (4 теста) и
  `TestEvol030AccessAndAnalytics::test_audit_before_changing_rights` — 4 подтверждены
  байт-идентично на базовых файлах; 5-й требует `matrixRoleToggle: async function`,
  которого нет ни в базе, ни в кандидате (в обоих `matrixRoleToggle: function`).

## 5. Ограничения и честность доказательств

- Стенд — реальные `web/*` кандидата + route-стабы `/api/*` (playwright), не production.
  Кандидат не разворачивался; production не затрагивался.
- Browser Use для этой правки не применялся: изменены две текстовые строки внутри
  существующего блока, а состояние требует стабов `/api/*` (в реальном Chrome без
  Playwright-стабов страница не аутентифицируется). Визуальный контроль выполнен
  детерминированным Playwright-прогоном и скриншотами выше; компоновка блока не менялась.
- `test_live_render_sections_e2e` (тот же файл, живой `tools/ui_evol_w10_sections_e2e.py`,
  subprocess 1800 с) не завершён: pytest-timeout в этом окружении; к диффу не относится
  (W10-разметка не менялась). Побочный эффект прогона — перезапись tracked PNG в
  `plans/features/evol/audit/evidence/` — восстановлена (`git checkout --`), worktree чист.
- `_embedModelSwapGuard`/версионные пины — существующий долг вне scope (BACKLOG, не чинился).
- Временные копии базовых файлов и RED-пробы лежали в
  `%TEMP%/opencode/sac-r2` и удалены после фиксации результатов; воспроизведение:
  `git show 0f59db8e1:web/app.js > base.js` + `APP_JS=base.js node tests/js/speech_core_scope_ctx_test.js`.

## 6. Covered IDs

- `SAC-REV-R1-F1`, `SAC-REV-R1-F1b`, `SAC-REV-R1-F2`, `SAC-REV-R1B-F1`, `SAC-REV-R1B-F2`
- P0A-UX §6.3 (дефолт цели сохранения = текущая область), §6.4 (изоляция чатов),
  §5.2 (409/503), §5.3/§5.4 (черновики редакций) — прогнаны на кандидате
- SAC-CORE-FIRST / SAC-CORE-ON-TAB (единый редактор на вкладке «Личность») — без регрессий

---

# Корректива r3 (28.11.2026) — SAC-REV-R2-F1

- Исправляющий кодовый коммит: `b404d7b1f4e8b6cf3f289d1831c3c3f595425841`
  (tree `1435310b194f53eccb777a84a7f214f5ded5bb2d`); `b404d7b1f..HEAD` — этот md
  и его `.sha256`.
- Предыдущий кандидат ревью r3: `1b28fa4d602d3d61592f59c532cfe79d422eacff`
  (tree `ef483c6edf315cc4be097762c072275522250dff`); ревью:
  `evidence/review-r2/review-r1.md` (коммит `470a645b`).
- Закрываемая находка: `SAC-REV-R2-F1` (IN_SCOPE, MEDIUM, блокирующая) — latch
  `chatCtxReady` после `lockAuth`: после «Попробовать снова» `retryInitData()`
  синхронно вызывал `setTab()`, и первый `/api/speech/overview` `/api/persona`
  уходили до `/api/access/*` без `X-Chat-Id`; `scope` оставался `global` при
  активном чате. Остальные находки r2 (`SAC-REV-R1-F1` основной путь, F2 e2e,
  F2b подпись) в ревью r3 уже RESOLVED и не переделывались.
- Политика: PET_PROJECT; production не разворачивался и не использовался
  (read-only, никаких SSH/БД/деплой-действий). Карты/progress не менялись.

## 1. Фикс (минимальный, без переделки закрытого)

| Файл | Изменение |
|---|---|
| `web/app.js` | `lockAuth()` больше НЕ вызывает `_markChatCtxReady()`: сбрасывает `chatCtxReady=false` и отпускает ожидающих через новый `_releaseChatCtxWaiters()` (следующий шаг загрузчика — `api()`, который при `authLocked` честно бросает 401, вечного «Загружаем…» нет). `_markChatCtxReady()` = готовность + отпускание ожидающих. `_whenChatCtxReady()` не ждёт, когда `authLocked` (область сама не разрешится), но готовой её не объявляет. `retryInitData()`: `setTab(self.activeTab)` перенесён внутрь `loadAccessCtx().then(...)` — вкладка/её загрузчики стартуют только после применения области. |
| `tests/js/speech_core_scope_ctx_test.js` | Сценарий C ужесточён (`chatCtxReady === false` после `lockAuth`); добавлены D (lockAuth → навигация в «Личность» → retry с управляемыми промисами области: overview/persona/Core не уходят до `/api/access/*`, `scope = chat`) и E (реальный `api()`, `fetch`-рекордер: первый overview/persona после retry несёт `X-Chat-Id = -100500`, личность читается в области чата). Существующие A/B/C сохранены. |

`makeCtx()` в тесте теперь не подменяет `api` при пустом аргументе (нужно для E);
поведение A–D не изменилось.

## 2. RED/GREEN (node v24.16.0)

RED — тест против неизменённого кандидата `1b28fa4d` (`git show 1b28fa4d:web/app.js`,
`APP_JS=<файл> node tests/js/speech_core_scope_ctx_test.js`), 10 провалов:

```
- C: lockAuth не объявляет контекст области известным
- D: /api/speech/overview не должен уходить до /api/access/* (ушло: ["/api/access/me","/api/speech/overview","/api/persona"])
- D: /api/persona не должен уходить до /api/access/* (ушло: …)
- D: overview ждёт полного разрешения области (/api/access/chats)
- D: overview только после области (["/api/speech/overview@401","/api/speech/core@401","/api/persona@401","/api/persona/self-model@401","/api/access/me@sent","/api/speech/overview@sent","/api/persona@sent","/api/access/chats@sent"])
- D: persona только после области
- E: overview уходит после области (["/api/access/me","/api/speech/overview","/api/persona","/api/access/chats"])
- E: persona уходит после области
- E: первый overview несёт X-Chat-Id активного чата (получено: null)
- E: первый persona несёт X-Chat-Id активного чата (получено: null)
```

Это ровно `SENT_BEFORE_ACCESS_CTX` из ревью: overview/persona уходят раньше области
и без заголовка. GREEN — `SPEECH-CORE-SCOPE-CTX-OK`, rc=0 (5 сценариев A–E).

Повтор ревьюерской пробы `evidence/review-r2/probe_retry_ctx5.js` на фиксе:

```
SENT_BEFORE_ACCESS_CTX=["/api/access/me"]
PROBE=OK
```

(в этой пробе стаб `api()` намеренно всегда отдаёт глобальные payload'ы — она
показывает только порядок; фактический `X-Chat-Id`/`scope=chat` доказывает сценарий E).

## 3. Прогоны (worktree ветки, `.venv` py3.12, node v24.16.0)

| Прогон | Результат |
|---|---|
| `node tests/js/speech_core_scope_ctx_test.js` | **OK** (`SPEECH-CORE-SCOPE-CTX-OK`, rc 0) |
| `pytest tests/test_webapp_js_unit.py -q` | **43 passed, 7 failed** — ровно те же предсуществующие (см. §4) |
| `pytest tests/test_speech_applicability_core_ux.py -q` | **15 passed** |
| `pytest tests/test_webapp_deps.py tests/test_webapp_back_button.py -q` | **passed** (статические контракты `retryInitData`/`lockAuth`/`setTab` сохранены) |
| `pytest tests/test_webapp_js_unit.py tests/test_speech_applicability_core_ux.py tests/test_webapp_deps.py tests/test_webapp_back_button.py -q` | **125 passed, 7 failed** (те же 7) |
| `python tests/ui_p0a_ux_speech_compact_e2e.py` | **failures=0, POST=21** |
| `node --check web/app.js`, `node --check tests/js/speech_core_scope_ctx_test.js` | rc 0 |

Предсуществующие red — без изменений и не связаны с диффом:
`test_js_unit_routing_and_scope_guard`, `test_js_unit_round1024_image_key`,
`test_js_unit_round1025_hotfix7_shell_glass_heartbeat`, `...hotfix8...`,
`...hotfix9...`, `...hotfix10...`, `test_js_unit_round1025_f7_permsoc_local`
(`_embedModelSwapGuard is not a function` — метод отсутствует и в базовом `app.js`;
hotfix7–10 — пины `APP_VERSION = 2.58.255` при фактической 2.58.258).

## 4. Ограничения

- Проверки — реальные `web/app.js|index.html|css` + route-стабы `/api/*` и
  node-пробы с реальными `methods`; production/бэкенд не использовались.
- Визуальная компоновка не менялась (правка поведения инициализации), поэтому
  отдельный Browser Use/Playwright визуальный проход не требовался; e2e-харнесс
  (обязательный) зелёный.
- Проверен и известный перекрёстный сценарий из ревью: после 401 раздел сам не
  перезагружается при повторном входе (нужен «Обновить данные») — это
  предсуществующее свойство экрана (BACKLOG_ONLY в ревью), фиксом не
  затрагивалось; запись в неверную область при этом устранена.
- Временная копия кандидатского `app.js` лежала в `%TEMP%` и удалена после
  фиксации результатов.

## 5. Covered IDs

- `SAC-REV-R2-F1` (закрыт), регрессии `SAC-REV-R1-F1`/`F2`/`F2b` — сохранены
- P0A-UX §6.3 (цель сохранения = фактическая область), §6.4 (изоляция чатов),
  SAC-CORE-FIRST / SAC-CORE-ON-TAB — без изменений
