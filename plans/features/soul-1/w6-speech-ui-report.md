# SOUL-1 / W6-SPEECH-UI — отчёт слайса («Речь и характер» в MiniApp)

- **Lane:** W6-SPEECH-UI (writer; join barrier — владелец должен уметь править
  Core/Style/примеры через UI до голосовой канарейки).
- **Кандидат:** рабочее дерево поверх master (коммитов нет, деплоя нет).
- **Покрытые требования:** `requirements-map-amendment.json` W6
  (SOUL-AMD.6.1–6.6, 8.3) + `requirements-map.json` W6
  (SOUL-10.0–10.6, SOUL-11.0, SOUL-16.5.0). Построчное покрытие —
  `evidence/w6/requirements-coverage.md`.

## 1. Точка входа: где именно живёт раздел и почему так

Проведён IA-аудит (`web/app.js`: `NAV_ITEMS_V2`, `HUBS_V2`, `ROUTE_TO_TAB`,
`ROUTE_PARENT`, `canViewTab`, `_routeLabel`) и выбран **логически вложенный
вход**, а не шестая карточка хаба:

* хаб «ИИ» в IA v2 — **ровно 5 страниц в фиксированном порядке**
  (ADR-1025-15 D2/§47, пин `tests/test_webapp_f5_round1025.py:305`); добавление
  шестой карточки = переделка уже принятой навигации, что прямо запрещено и
  брифом («do NOT rework navigation»), и уточнением владельца (§6.3);
* «Личность и стиль» (`#/ai/persona`) — та же зона identity/speech: имя,
  биография, характер, осознание ИИ. «Речь и характер» — речевой слой этой же
  сущности, поэтому вход встроен **внутрь существующего экрана** карточкой
  «Речь и характер» (`data-speech-entry`, tier A) и ведёт на отдельный
  special-screen `#/ai/speech`;
* подпись карточки хаба «Личность и стиль» дополнена упоминанием «Речи и
  характера» — вход различим уже на уровне хаба, при этом состав и порядок
  страниц хаба не изменились;
* маршрут `#/ai/speech` зарегистрирован симметрично прецеденту `#/ai/persona`
  (special-screen, без записи в TABS): `ROUTE_TO_TAB` / `TAB_TO_ROUTE` /
  `ROUTE_PARENT` → «Назад» ведёт в «ИИ», подпись — «Речь и характер», права —
  существующие (`edit_persona` / секция `content` / локальный админ чата),
  новых прав и чекбоксов нет.

Побочный эффект выбора: на мобильном путь «Ещё» → «ИИ» → «Личность и стиль» →
«Речь и характер» (три касания). Альтернатива (шестая карточка) давала бы два
касания, но ломала принятую IA-карту — обмен осознанный.

## 2. Состав экрана (один раздел за раз, «Назад», черновики не теряются)

Витрина: компактные карточки разделов (обычным языком, без «приборки
самолёта») + блок «Для разработчика». Технические поля/ключи/JSON/версии —
только в «Все инструкции» / Inspector.

| Раздел | Состояние | API-привязка |
|---|---|---|
| **Характер** | реализован | `GET /api/speech/core`, `POST /api/speech/core/meta`; правки редакций — `POST /api/speech/block/{core.personality \| core.personality.compact}` → **`prompt_factory.write_speech_value`**; заводской сброс — `POST .../reset` → `plan/apply_factory_reset`; откат — `POST .../rollback` (через тот же write-path); «сбросить переопределение чата» — `reset_chat_override` |
| **Стиль письма** | реализован | `GET/POST /api/speech/style`, `POST /api/speech/style/preview`, `POST /api/speech/style/reset-chat` → `style_policy.save_policy_document` / `reset_chat_policy` / `effective_style_policy` + `apply_style_policy` (0 LLM, `record=false`) |
| **Выражение** | реализован, с честной границей | `GET/POST /api/speech/expression`, `POST .../reset-chat`; owner-документ `character.expression` на существующем контуре (`bot_settings` + `chat_params.overrides`), рендер слоя `<Expression_Settings>` — детерминированный, 0 LLM |
| **Юмор** | включённость + приёмы; библиотека — TODO(W4) | `GET /api/speech/humor` (оси `humor_library_enabled`/`humor_feedback_enabled`, 6 приёмов SOUL-06); отбор примеров и слой few-shot — слайс W4, данные не выдумываются |
| **Примеры** | каркас + схема сущности; TODO(W4) | `GET /api/speech/examples`: `status=not_implemented_w4`, поля карточки = контракт `design-source-of-truth §2.3`; второй стор НЕ создаётся |
| **Попробовать** | реализован | `POST /api/speech/try`: current vs candidate на одном входе (токены одним оценщиком, проход формы, extent, защищённые спаны = сохранность фактов, слои/конфликты = выбранная стратегия); `generate=true` — явный реальный вызов провайдера, иначе 0 LLM; `delivery.telegram_send=false`, `lessons_created=0` |
| **Обучение** | реализован на существующих данных; humor-feedback — TODO(W4) | `GET /api/speech/learning` (уроки Experience: статус/счётчики/применения/версии/confirm), пауза/одобрение — существующий `/api/memory/lessons/action`; контур реакций на шутки (SOUL-08) честно помечен как не поставленный |
| **Все инструкции** | реализован | `GET /api/speech/blocks` (77 блоков реестра), `GET /api/speech/block/{id}`, `POST /api/speech/block/{id}` (+`/reset`, `/rollback`) |
| **Effective Prompt Inspector** | реализован, admin-only | `GET /api/speech/inspector`: предпросмотр (сборка композером сейчас) vs снимок хода (только writer'ы реального хода `l2_writer`/`system2_stage2`/`tool_phase`/`initiative_writer`), слои с источником/ревизией/причиной, версии, порядок, конфликты, ядро сборки, маскировка, retention |
| **Возможности бота** | реализован | `GET /api/speech/capabilities` → `capability_registry.capability_view` (13 способностей, 7 статусов, гейты, `checked_at`, инструмент) + trace из `mca_events` + выделенный блок «доступное действие не было выбрано L1» |

## 3. Путь записи (SOUL-AMD.1.1/4.1)

* Любая правка речевого блока идёт **только** через
  `prompt_factory.write_speech_value` (единственный путь, дающий провенанс
  ревизии); заводской сброс — `apply_factory_reset`; снятие чат-оверрайда —
  `reset_chat_override`; откат — запись ревизии из истории тем же API.
* Прямых записей `prompts.*` из UI-слоя нет (guard-тест
  `test_writes_go_through_registry_api_only`); документы новых сущностей
  (`character.expression`, `character.core.meta`) пишутся на существующий
  контур `bot_settings`/`chat_params` — второго config service нет.
* Итог: значения из MiniApp становятся действующим слоем (не удерживаются
  резолвером), а хранимые легаси-каноны остаются видимыми в диагностике.

## 4. Что проверено исполнением

* **Round-trip** (18 тестов `tests/test_soul1_w6_speech_ui.py`, полный список —
  `evidence/w6/roundtrip-tests.txt`): правка полной/компактной редакции Core →
  чтение → чат-оверрайд без изменения глобального → сброс чата → заводской
  сброс с diff → откат; стиль (правила, шаблоны с сервера, before/after на
  защищённых данных, чат-сброс); выражение (рендер слоя, изоляция чата);
  RBAC 403; «Inspector не выдаёт предпросмотр за реальный вызов»; маскировка.
* **UI-прогон** на реальных `index.html`/`app.js`/`app.css` (Playwright,
  `tools/ui_soul1_w6_speech_e2e.py`, ответы API — из фикстуры, снятой настоящим
  слоем): 320/360/390/430/768/1024/1440 + landscape 667×375, все 10 разделов,
  вход через «Личность и стиль». Факты прогона (`evidence/w6/ui-report.json`):
  `failures=0`; `pageOverflow=0` на каждом viewport (и на экране входа в
  «Личности и стиле»); `minTap=44` везде; `paddingLeft=12px`; витрина —
  1 колонка на 320/360/390/430, 2 на 768 и в landscape, 3 на 1024, 4 на 1440;
  блок «редактор+предпросмотр» — 1 колонка до 768 включительно и **2 колонки на
  1024/1440**; длинные prompt/JSON-строки скроллятся ВНУТРИ компонента
  (`preOverflow>0` при нулевом overflow страницы); POST-вызовы прогона:
  `block/core.personality` ×4, `style/preview` ×2, `style` ×2, `expression` ×2,
  `try` ×2. Кадры — `evidence/w6/shots/` (88 файлов: витрина, вход, каждый
  раздел, сохранение, предпросмотр стиля, Inspector в двух состояниях).
  Черновик и каретка переживают обновление данных и навигацию по разделам —
  и для характера, и для правил стиля (проверено в прогоне).
* **Живой просмотр** (реальный Chrome через Browser Use,
  `--serve-only`): витрина, Inspector и «Возможности бота» осмотрены глазами на
  реальной отрисовке; кнопки действий получили непрозрачную подложку (текст
  читается и на бликах tier A у кромки карточки) — правка внесена по
  результату просмотра, до неё текст на светлом участке линзы читался плохо.
* **Существующие сьюты** (стекло/IA/маркеры/каталог) — см.
  `evidence/w6/glass-and-ui-suites.txt`; `gen_param_registry_round1025.py
  --check` — CHECK OK (Δ каталога = 0: новые ключи каталога в этом слайсе не
  добавлялись, витрина правится через API реестра; прецедент W3/W10).
* **Запреты соблюдены:** `web/static/polygon-background.js`, карта линзы
  (`#lg-lens`/`feDisplacementMap scale=32`), токены `--lg-*` и glass-классы не
  менялись (`git diff` по ним пуст; маркер-тест проверяет отсутствие
  `#lg-lens`/`--lg-tint-hero` в новом CSS-блоке).

## 5. Осознанные границы (что осталось и кому)

1. **Контуры W4** («Юмор»-библиотека, «Примеры», реакции на шутки в
   «Обучении», отбор few-shot) — разделы показывают контракт и честный статус,
   второй стор не создаётся; оживают после W4 без переделки UI (схема полей
   уже отрисована).
2. **Слой «Выражение» на боевом пути Direct** — значения рендерятся
   композером (видно в Inspector/«Попробовать»), но передачу
   `ExpressionSettings` в боевую сборку делает слайс-владелец композера; в UI
   это честно показано (`runtime_wired=false` + причина `expression_absent`),
   а не замаскировано.
3. **«Обращения»** (SOUL-10.2) закрыты мягкими привычками/свободным текстом:
   закрытый набор `kind` движка W3 (`trailing_period`, `quotation_marks`,
   `emoji`, `line_breaks`, `one_word`, `forbidden_chars`) отдельного kind для
   обращений не содержит — это решение движка, а не пропуск UI.
4. **`reset-learning`** для humor-контура — вместе с W4 (данные не удаляются);
   в «Обучении» уже доступны пауза/одобрение уроков Experience.
5. **Живая отправка в Telegram и голосовая канарейка** — гейт владельца: этот
   слайс не отправляет ничего в чаты (тестовая лаборатория это гарантирует
   флагом `delivery.telegram_send=false`).
6. **Ключи каталога** (`content.*`, `character.core`, `character.expression`)
   в `param_catalog` не добавлялись: правки идут через API реестра, generic
   `/api/config` для них не требуется; `--check` каталога остаётся зелёным
   (Δ = 0). Если владелец захочет видеть их в общем реестре параметров —
   отдельный слайс с перегенерацией `plans/docs/param-registry-round1025.*`.

## 7. Инцидентальные находки

1. **По делу (исправлено в слайсе):** кнопки действий на tier A карточках
   (шапка раздела) на светлых участках блика линзы читались плохо — у
   ghost-кнопок внутри нового экрана добавлена непрозрачная подложка
   (`rgba(12,18,30,.72)`), текст читается на всех проверенных участках.
2. **По делу (исправлено в слайсе):** «Обновить данные» изначально
   пересобирал черновик правил стиля из серверного снапшота — несохранённые
   правки правил могли потеряться. Введены явные флаги черновика на раздел
   (`core/style/expression`), обновление данных их больше не затирает; это
   закреплено и тестом, и прогоном.
3. **Не блокирует (unrelated/pre-existing):** в харнессе конфиг-стабы оставляют
   «грязное» состояние экрана «Личность/конфиг» (`stickyDirtyCount=0`, но
   D13-guard считает страницу грязной и спрашивает подтверждение со словами
   «несохранённые изменения (0)»). Экран «Речи и характера» это не затрагивает;
   поведение воспроизводится без нового кода (той же формулировкой на
   существующих экранах). Тексты диалогов сохранены в `ui-report.json`
   (`dialogs`), чтобы это не выглядело скрытым.
4. **Не блокирует:** `prompt_registry.factory_text` для блока-подсказки
   `style.policy.hint` зависит от того, импортирован ли модуль
   `services.prompt_style_blocks` в процессе; при отсутствии импорта функция
   честно пишет WARNING и отдаёт пустой заводской текст (fail-open). В
   рантайме модуль импортируется другими сервисами; UI показывает пустую
   заводскую ревизию вместо выдуманной.

## 8. Файлы слайса и отпечатки кандидата (sha256_12)

```
b85c6d63143e  web/api/speech.py                     (новый, 21 маршрут)
069737d43b89  web/app.py                            (+5: регистрация роутера)
69216b9222f6  web/index.html                        (+866, только добавления)
e094635999cc  web/app.js                            (+784 / −1: маршрут, canViewTab,
                                                     подпись, витрина+разделы)
761274ceaed1  web/static/app.css                    (+227 / −1: только новый экран)
a6ad280ccd0c  tests/test_soul1_w6_speech_ui.py      (новый, 18 тестов,
                                                     вкл. проверку реального
                                                     монтирования роутера)279848076989  tests/test_ia_inventory_round1025.py  (+1: speech в allow-list
                                                     special-screen'ов)
a6dc45f79429  tools/ui_soul1_w6_speech_e2e.py       (новый e2e-харнесс)
c846c73b347f  plans/features/soul-1/evidence/w6/dump_api_fixture.py
a71942e98486  plans/features/soul-1/evidence/w6/api-fixture.json
495f46051165  plans/features/soul-1/evidence/w6/ui-report.json  (failures=[])
c221760d0413  plans/features/soul-1/evidence/w6/ui-run.txt
0a4fa3c69ca7  plans/features/soul-1/w6-speech-ui-report.md
```

Затронутый периметр `web/**` = ровно эти 4 файла (`git diff --numstat`); замороженные
ассеты (`polygon-background.js`, `web/static/vendor/**`, `glass-teststand.html`)
не изменялись (диффа нет). `services/**` этим слайсом не менялся вообще (в
рабочем дереве видны изменения соседних полос — `services/disk_retention.py`,
карты/планы и данные asap8: они НЕ мои, лишних правок я не делал). Правки
каталога параметров не требовались: Δ каталога = 0 (витрина работает через API
реестра), поэтому `plans/docs/param-registry-round1025.*` и
`tests/fixtures/round1025/f8_baseline.json` не переиздавались.

## 9. Прогоны (полный список — `evidence/w6/glass-and-ui-suites.txt`)

| Прогон | Результат |
|---|---|
| `node tests/js/glass_probe_test.js` | JS-UNIT-OK glass-probe |
| `node tests/js/round1025_design_tokens_test.js` | JS-UNIT-OK |
| `node tests/js/routing_test.js` | JS-UNIT-OK |
| `node tests/js/round1025_ia_routing_test.js` | JS-UNIT-OK |
| `node tests/js/vue_mount_test.js` | VUE-MOUNT-OK |
| `node tests/js/asap8_w2_shell_mobile_nav_test.js` | W2-SHELL-UNIT-OK |
| `tools/gen_param_registry_round1025.py --check` | CHECK OK: 572 == REGISTRY |
| `pytest tests/test_soul1_w6_speech_ui.py` | 18 passed |
| `pytest` IA/веб-маркеры (7 файлов, вкл. teststand guard, f8-реестр, round1014/f11) | 127 passed |
| `tools/ui_asap8_w2_shell_e2e.py` (стекло U01/U02) | W2-SHELL-E2E-OK |
| `tools/ui_asap8_w2_fullscreen_e2e.py` | 7/7 PASS |
| Периметр `pytest -k "webapp or ia_ or soul1 or round1025 or round1024 or ui_ or glass or persona or prompt or registry or catalog"` | 3781 passed, 0 failed |
| `tools/ui_soul1_w6_speech_e2e.py` (слайс) | failures=0, POST=12, 88 кадров |

## Fix pass (review-w6 F1–F3)

Ревью `plans/features/soul-1/review-w6.md` (вердикт Needs Fixes) закрыто правкой
трёх блокеров и одного minor'а; всё, что ревью подтвердило исполнением (путь
записи, байт-изоляция global/chat, RBAC, маскировка и preview-vs-sent,
навигация/пин, стекло, TODO-честность, измеренные вьюпорты), не менялось.
Полные прогоны — `evidence/w6/fix-pass-suites.txt`, живой Chrome — скриншоты в
`evidence/w6/shots/` + прогон харнесса на финальных байтах.

| Находка | Правка | Доказательство |
|---|---|---|
| **F1** снимок хода недостижим: `web/api/speech.py` искал манифест по ключу без `run_id`, а рантайм пишет `run_id=correlation_id` (uuid) | `speech.py:990-1042` — `_latest_real_turn_manifest()`: самый свежий манифест чата среди `REAL_TURN_WRITERS` (последняя вставка = последний ход; предпросмотр UI его не подменяет), плюс честный fallback на ключ без run_id. `services/**` не тронут: чтение in-memory кэша композера только-на-чтение, под его локом, при сбое — «снимка нет», а не выдумка | проба: uuid-сид → было `last_run_present=False` (эквивалент старого кода) → стало `True` и `sent.run_id` = uuid; preview ПОСЛЕ хода не вытесняет; чужой чат снимка не видит; харнесс — ветка «есть снимок реального хода» + run_id в разделе |
| **F2** редактор правил рендерился с сервера, а правил черновик | `web/index.html` — список/счётчик/привычки из `speechStyleViewRules()/speechStyleViewSoft()` + бейдж «черновик не сохранён» и строка «показаны ВАШИ правки… на сервере N»; `web/app.js:18584-18673` — view-хелперы, честный тост вместо тихого no-op по индексу, `addStylePreset` больше не сбрасывает уже несохранённые правки, уникальный id мягкой привычки | живой Chrome: снял галку → «Назад» → вернулся: галка снята и бейдж на месте; «+ Без точек на конце» → 1→2 правила сразу, счётчик «2 правил», id `trailing_period.hard.strip` в списке; toggle/смена области по индексу работают после изменения длины; «Убрать» 2→1 и действие по индексу после удаления; привычки 1→2→1 |
| **F3** диалог заводского сброса читал `diff.before_chars/after_chars`, которых в ответе нет | `web/app.js:18466-18486` — `speechFactoryPlanText()` читает реальную форму (`changed`, `current_chars/factory_chars`, `diff{added_lines,removed_lines}`, `applies/reason`); `web/index.html` — карточка блока показывает ту же строку | живой тост: «было 2882 → станет 2835 зн. (строк −2 / +0). Повторный клик — подтверждение»; карточка блока: «заводской сброс: было 2882 → станет 2835 зн. (строк −2 / +0)»; «undefined» нет |
| **Minor** статический guard-тест фальсифицируем записью через переменную | `tests/test_soul1_w6_speech_ui.py` — динамический сторож на round-trip: любой `prompts.*`-ключ пишет только `services.prompt_factory`, а прямые записи документов из UI-слоя не меняют ТЕКСТ (только метаданные); ключ, собранный в переменной, ловится так же | `test_write_path_is_guarded_at_runtime_not_only_statically` + мутационная проверка: откат F1/F2/F3-кода роняет соответствующие тесты (4/4 mutation-guard) |

Найдено рядом и исправлено в том же экране (не из списка ревью, смежная
функциональность F3): кнопка «Вернуть заводской» на «Характере» вызывала
`speechFactoryPlan()` без block-id → клик молча ничего не делал (POST не
уходил, тост не появлялся; харнесс ловил при этом старый тост — проверка была
вакуумной). Теперь `speechFactoryPlan(blockIdFor(speechCoreEdition))`
(`web/index.html:7416`), подтверждение вторым кликом доходит до API.

Отдельно и явно: **F3-fixture больше не рукописный стаб** — `/reset` отдаётся
из `evidence/w6/api-fixture.json`, снятого настоящим эндпоинтом
(`dump_api_fixture.py`), а снимок хода сеется с `run_id=uuid` — то есть
зелёные доказательства теперь воспроизводят рантайм-форму обоих контрактов.

Дисциплина правок: `web/static/app.css` в этом fix-pass'е не менялся
(sha256_12 `761274ceaed1` совпадает с ревьюированным кандидатом),
`polygon-background.js` — тот же blob, что HEAD и ревью, `#lg-lens` байт-идентичен
HEAD (6298 б., `5367ec4566fc9e80`). В `web/**` финального дерева дополнительно
нормализованы окончания строк CRLF→LF (только `web/index.html`, `web/app.js`,
`web/api/speech.py`; содержимое не менялось) — причина и доказательство
авторства в `evidence/w6/fix-pass-suites.txt`, §EOL: это состояние существовало
до fix-pass'а и роняло два node-теста периметра (`round1025_hotfix8_shell_aurora`,
`round1026_s7_log_summary_filter`), после нормализации периметр снова 3786/0.

Финальные отпечатки (sha256_12): `web/api/speech.py d1fec786ee6b`,
`web/index.html 786fe44e4f94`, `web/app.js cea14985241d`,
`web/static/app.css 761274ceaed1`, `tests/test_soul1_w6_speech_ui.py 5b61a663cf65`
(22 теста), `tools/ui_soul1_w6_speech_e2e.py b71312860739`,
`evidence/w6/dump_api_fixture.py a9c2373eda53`,
`evidence/w6/api-fixture.json 226252e643a8`.

Не закрыто этим fix-pass'ом (вне WRITE_SCOPE, честно): запись evidence в карту
W6 и привязка кандидата (`requirements_gate check --stage review --slice W6`) —
за родителем/PM; minor №6 ревью (`_effective_after_write`) не менялся — UI это
поле не читает, отдельной правки в брифе не было.


* `web/api/speech.py` (новый; ~1100 строк, 21 маршрут) + регистрация в
  `web/app.py`;
* `web/index.html` (витрина и разделы, +866 строк, только добавления),
  `web/app.js` (+784), `web/static/app.css` (+227; материалы не менялись,
  добавлены только правила нового экрана);
* `tests/test_soul1_w6_speech_ui.py` (новый, 17 тестов),
  `tests/test_ia_inventory_round1025.py` (в allow-list special-screen'ов
  добавлен `speech` — рядом с существующим `persona`; состав TABS/IA не
  менялся);
* `tools/ui_soul1_w6_speech_e2e.py` (новый e2e-харнесс),
  `plans/features/soul-1/evidence/w6/**` (фикстура API, прогон, 88 кадров,
  покрытие требований, этот отчёт).

## EOL fix (17.10, блокер B1 recheck'а)

Три доставленных web-файла были CRLF-only (`a50854e0c77e` / `b80158b59deb` / `1eaebd6ba0f1`,
одиночных LF = 0), а guard fix-pass'а восстанавливал их через `read_text`→`write_text`
(Windows: LF→CRLF) — уже ПОСЛЕ нормализации, поэтому два node-теста периметра были красными.
Сделано: байтовая LF-нормализация ровно этих трёх файлов (содержимое не менялось; numstat
+836/−1 и +871/−0 совпали с §EOL, raw-отпечатки снова `d1fec786ee6b` / `786fe44e4f94` /
`cea14985241d`, CRLF=0) и guard переведён на байтовый IO с self-check «raw-байты: `\r\n` == 0».
Повтор на финальных байтах: node 8/8 OK (оба прежде красных — зелёные), W6-файл 22 passed,
периметр 3786/0, харнесс failures=0 / POST=16 / shots=94, shell OK, fullscreen 7/7, инварианты
стекла не затронуты (polygon `c2ad97d4`, `#lg-lens` `5367ec4566fc9e80`, `--lg-*` `89cda50a6e618ea5`).
Подробности и полные raw sha256 — `evidence/w6/fix-pass-suites.txt`, раздел FIX-W6-EOL.

Отдельно, НЕ EOL и не чинилось (нужна правка логики владельцем W6): в `web/app.js` дублируется
ключ `lessonAction` — 7728 (память MCA-16, 3 аргумента) и 18884 (блок «Речь», 2 аргумента);
перекрытие ломает `saveLessonCorrection` (payload теряется) и роняет
`tests/js/round1039_experience_lessons_test.js` (на HEAD зелёный, на рабочем дереве red).

## lessonAction fix (17.10, полоса FIX-W6-LESSON)

Дубль ключа из абзаца выше устранён: блок W6 получил собственное имя, реализации НЕ слиты
и НЕ удалены, MCA-16 не тронут.

- `web/app.js:18884` — `lessonAction` → `speechLessonAction` (тело метода прежнее);
- `web/index.html:7878/7881` («Пауза»/«Одобрить» раздела «Речь») → `speechLessonAction(...)`;
- `web/index.html:2817/2820` и `web/app.js:7728/7768` (память MCA-16) — без изменений.
- До/после: `node tests/js/round1039_experience_lessons_test.js` → rc=1
  `TypeError: this.loreErrText is not a function` → `MCA16-EXP-OK`.
- Сторож этого класса дефектов: `tests/js/app_methods_dup_keys_guard_test.js` — падает на
  дубле ключа в любом литерале `methods`, на обработчике `@click` без метода и на
  поведенческой проверке (оба метода — разные: память доводит payload до POST, «Речь»
  шлёт POST и перезагружает раздел learning); на pre-fix байтах красный, на кандидате
  зелёный (известный мёртвый дубль `_prefersReducedMotion` ×2 зафиксирован как явное
  исключение).
- Прогоны на новых байтах: node 85/85 (0 падений), W6-файл 22 passed, харнесс
  failures=0/POST=16/shots=94, периметр 3786 passed/0 failed, стеклянные инварианты
  без изменений, файлы остались LF-only.
- Новые raw sha256: `web/app.js 401a40a5322a…`, `web/index.html 8d86cd1a0a0f…`, сторож
  `68243a476f53…`; подробности и фальсификация — `evidence/w6/fix-pass-suites.txt`,
  раздел FIX-W6-LESSON.
