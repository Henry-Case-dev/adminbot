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
