# SOUL-1 / W4 — отчёт слайса: Humor Craft, Few-Shot библиотека, Feedback Loop

- **Lane:** W4-BUILD (writer; веер дочерних полос невозможен — в этой сессии
  достигнут предел вложенности агентов, работа выполнена одной полосой
  последовательными этапами); закрытие C1 и финальные отпечатки — COMMIT-W4.
- **Кандидат:** коммит слайса W4 поверх `c5900874a4d8319d1066a2a548a2450449eb8712`
  (SHA коммита и привязка в обеих картах — §«W4 binding» в `plan.md`; деплоя нет).
- **Покрытые требования:** `requirements-map.json` W4 (SOUL-06.0–06.7,
  07.0–07.3, 08.0–08.12) + `requirements-map-amendment.json` W4 (SOUL-AMD.2.6).
  Построчное покрытие — `evidence/w4/requirements-coverage.md`.

## 1. Что сделано (простыми словами)

1. **Ремесло юмора** (SOUL-06): пять приёмов стали управляемым ситуационным
   слоем. Технику по-прежнему советует L1 (`ResponsePlan.comic_strategy`), а
   слайс добавляет: заводские тексты приёмов, общую рамку «критерий —
   связность и уместность, а не частота мата», выключение ремесла отдельным
   тумблером (характер при этом жив), проверку отдельного приёма в два клика и
   **ноль дополнительных вызовов модели** на обычный ответ.
2. **Библиотека примеров** (SOUL-07): появилась одна новая таблица
   `humor_samples` (миграция v36), 18 заводских примеров заведены как
   **черновики без одобрения владельца**, работают добавление/правка/
   архивирование/удаление, отметка «эталон», A/B версий библиотеки,
   «почему выбраны именно эти примеры», защита от попадания чужих чатов и
   персональных данных.
3. **Обратная связь по шуткам** (SOUL-08): контур живёт ВНУТРИ существующего
   Experience (те же таблицы и тот же фоновый проход, второго «самообучения»
   нет). Сохраняются только короткие метаданные отправки; реакции
   классифицируются семантически; тишина — это `unknown`, а не провал;
   выводы делаются консервативно (нужны независимые наблюдения, один человек
   не накручивает успех, повторные реакции не считаются, «наоборот» во
   времени отбрасывается); ослабление приёма действует только в своём чате и
   затухает; характер владельца никогда не переписывается автоматически.
4. **Авторские тексты** (SOUL-AMD.2.6): жанровые рамки для снов, ностальгии,
   лора и историй зарегистрированы как заводские редакции; путь «Ностальгия»
   проведён через общий композер (получает Core + жанр), при выключенном
   композере остаётся прежний канон байт-в-байт.
5. **Интерфейс**: разделы «Юмор», «Примеры» и «Обучение» в «Речи и характере»
   больше не заглушки — они показывают и меняют реальные данные.

## 2. Соблюдённые контракты (цитаты требований)

| Требование | Как выполнено |
|---|---|
| SOUL-06.6 «главный критерий — причинная связность и уместность, а не частота мата» | Текст рамки + тест, что в редакциях нет предписаний частоты/мата; серый контекст (report/code/serious) и `one_word`/`micro` гасят приём |
| SOUL-06.7 «toggle … при сохранении Personality Core» | `humor.craft.enabled` + ось `HUMOR_CRAFT_ENABLED`; Core рендерится, приём — нет (`humor_disabled`) |
| SOUL-06.7 «дополнительных LLM-вызовов на обычный ответ по умолчанию — 0» | Тест с заглушкой модели: ровно 1 вызов (Writer) при включённых осях; оценка кандидатов выключена по умолчанию, bounded (≤2/≤1/таймаут) |
| SOUL-07.1 «не генерировать синтетическую библиотеку, объявляя её проверенной владельцем» | Сиды: `source_kind=bot_suggested`, `owner_approved=0`, в API `approval="proposed"`; в runtime не попадают до отметки владельца |
| SOUL-07.2 «защита от утечки и cross-chat контекста/персональных данных» | Двойная защита: отказ на записи (`sensitive:*`) + отбор (`leakage_guard`), жёсткая изоляция chat-скоупа |
| SOUL-08.1 «НЕ создавать отдельный самодельный контур» | Своих таблиц нет; проход окна вызывается существующим review-джобом опыта; счётчики добавлены в его payload |
| SOUL-08.2 «bounded-метаданные … не сохранять секретные prompts или сырые данные» | `bounded_send_metadata` пропускает только закрытый набор типизированных полей; текст/секреты отбрасываются тестом |
| SOUL-08.6 «отсутствие ответа как unknown, а не failure» | Отдельные тесты: пустое окно закрывается `unknown`; исход эпизода `unknown`, не `failure` |
| SOUL-08.8 «ошибка/недоступность оценщика не блокирует беседу» | Оценщик зовётся только в фоновом проходе; при недоступности — честный `unknown` и счётчик, исключений нет |
| SOUL-08.9 «никакой автоматической переписи Core» | Тест: после активации предпочтения документ `character.core` не меняется (записей нет) |
| SOUL-08.10 «ослабляет стратегию в контексте, а не глобальный запрет» | Урок скоупа `chat`+приём; другой чат и другой приём не затронуты; затухание возвращает вес |
| SOUL-AMD.2.6 «получают Core и жанровые правила» | `authorial_system()` + зарегистрированные `genre.*.rules`; проводка «Ностальгии» подтверждена тестом на реальном пути |

## 3. Файлы и отпечатки (sha256_12)

**Final, commit-time** — пересчитаны на финальных байтах слайса (после C1);
полный список — `evidence/w4/parity-off.json`. Ключевое:

| Файл | sha256_12 | Роль |
|---|---|---|
| `services/mca_humor_craft.py` (новый) | `64840174880e` | приёмы, рамка, отбор, проверка приёма, опц. оценка кандидатов |
| `services/mca_sample_library.py` (новый) | `033fb5c40541` | таблица/CRUD/сиды/отбор/A-B/телеметрия |
| `services/mca_humor_feedback.py` (новый) | `59b7ac37a8d8` | метаданные отправки, окно, классификация, защиты, уроки, decay |
| `services/mca_authorial_speech.py` (новый) | `7705e7009eda` | жанровые рамки и сборка авторского system |
| `services/prompt_composer.py` | `fd8a2a70d5d7` | ось `humor_craft_enabled`, слой гасится флагом |
| `services/prompt_registry.py` | `9dd5628dd4d0` | 12 новых заводских редакций + бамп отпечатка набора |
| `services/mca_gates.py` | `34bff28e9071` | `HUMOR_CRAFT_ENABLED`, `HUMOR_CANDIDATE_EVAL_ENABLED` (OFF) |
| `services/mca_experience.py` | `a8879d1cbef7` | `humor_fit`, `humor_instruction`, 10 канонических правил |
| `services/mca_experience_jobs.py` | `e69efdb36f82` | проход окна внутри существующего джоба |
| `services/database.py` | `a30853ff1525` | миграция v36 (таблица `humor_samples`) |
| `services/direct_chat_service.py` | `d2bf56f22478` | провайдеры слоёв + захват метаданных отправки |
| `services/nostalgia_worker.py` | `5ed877a123b5` | авторский system для «Ностальгии» |
| `services/permissions.py` | `da6938f88860` | право-действие `edit_humor_library` |
| `web/api/speech.py` | `a69a67536ebe` | разделы «Юмор»/«Примеры»/«Обучение» + контролы; F1-guard и F3-карточки |
| `web/app.js` | `11215e3a4d10` | методы ремесла, библиотеки, обучения |
| `web/index.html` | `9e0b761104ff` | три раздела без заглушек |

Тесты, инструменты и evidence (те же финальные байты):

| Файл | sha256_12 | Роль |
|---|---|---|
| `tests/test_soul1_w4_humor_craft.py` | `776db1918e0a` | 23 теста приёмов |
| `tests/test_soul1_w4_sample_library.py` | `6cafbee40e9d` | 20 тестов библиотеки |
| `tests/test_soul1_w4_humor_feedback.py` | `76d47cd7489f` | 27 тестов контура (включая пин `SEND_FIELDS` и C1-вызов) |
| `tests/test_soul1_w4_authorial_genre.py` | `199733d1a615` | 8 тестов жанровых рамок |
| `tests/test_soul1_w4_examples_scope.py` | `1f901335ce45` | 5 F1/F2/F3-регрессий (+C1-набор в фикстуре) |
| `tools/ui_soul1_w4_speech_e2e.py` | `945021a965a6` | Playwright-харнесс 6 viewport |
| `tools/ui_soul1_w4_dump_fixture.py` | `189d2f8692c5` | снятие api-фикстуры настоящим слоем (это фактический хеш; в §10 первого ревью фигурировал `b14985dcf8a0` — см. RECHECK-W4 §0) |
| `tools/soul1_w4_mutation_witness.py` | `9ffcf661d730` | мутационный свидетель (14 мутаций, включая C1) |
| `tools/soul1_w4_parity_witness.py` | `fd13d50594cd` | паритет осей OFF + отпечатки |
| `tools/soul1_w4_frozen_check.py` | `71333f9a3293` | заморозка фоновых ассетов |
| `evidence/w4/api-fixture.json` | `d6f10447de3e` | реальные ответы слоя для UI-прогона |
| `evidence/w4/parity-off.json` | `f29eea14d13e` | паритет флагов + отпечатки |
| `evidence/w4/mutation-witness.json` | `1f86e713509f` | 14/14 убито |
| `evidence/w4/ui-report.json` | `2332521a0aca` | UI-прогон, failures=0 |
| `evidence/w4/requirements-coverage.md` | `8fe3e8cb27f5` | построчное покрытие требований |
| `evidence/w4/focused-tests.txt` | `a37daf8b3196` | 83 passed (5 файлов, commit-time) |

## 4. Матрица прогонов (точные команды и счёт)

| Прогон | Команда | Результат |
|---|---|---|
| Тесты слайса | `py -3 -m pytest tests/test_soul1_w4_humor_craft.py tests/test_soul1_w4_sample_library.py tests/test_soul1_w4_humor_feedback.py tests/test_soul1_w4_authorial_genre.py tests/test_soul1_w4_examples_scope.py -q` | **83 passed** (23+20+27+8+5) — `evidence/w4/focused-tests.txt` (final, commit-time) |
| Установленный периметр | `py -3 -m pytest -k "webapp or ia_ or soul1 or round1025 or round1024 or ui_ or glass or persona or prompt or registry or catalog" -q` | **3869 passed, 0 failed** (было 3786 на базе → +83) — `evidence/w4/perimeter.txt` (final, commit-time; см. наблюдение о флейке ниже) |
| Паритет флагов | `py -3 tools/soul1_w4_parity_witness.py` | все оси OFF; в манифесте `humor_craft: humor_disabled`, `few_shot: samples_disabled`; ни один новый слой не рендерится — `evidence/w4/parity-off.json` |
| 0 доп. LLM-вызовов | `test_zero_extra_llm_calls_on_normal_answer` (в тестах слайса) | ровно 1 вызов модели при включённых осях |
| Мутационный свидетель | `py -3 tools/soul1_w4_mutation_witness.py` | **14/14 убито** (изоляция чатов, leakage, черновики в runtime, явное указание, бригандинг, один пользователь, контекстный штраф, серьёзный контекст, гейт отправки + F1/F2/F3 + M11/C1) — `evidence/w4/mutation-witness.json` |
| Каталог параметров | `py -3 tools/gen_param_registry_round1025.py --check` | `CHECK OK: реестр 572 == REGISTRY` — Δ каталога = 0 (`evidence/w4/catalog-check.txt`) |
| JS-сторожа | `node tests/js/app_methods_dup_keys_guard_test.js` + 9 парных JS-тестов (glass_probe, shell/mobile nav, D05 experience UI, aliases, tabs, save-contract…) | все OK, дублей ключей нет, LF сохранён |
| UI-прогон (Playwright) | `.venv\Scripts\python.exe tools/ui_soul1_w4_speech_e2e.py` | **failures=0**, 6 viewport (320/390/430/1024/1440/landscape) × 3 раздела + интеракции; 9 реальных POST'ов — `evidence/w4/ui-report.json`, 22 кадра `evidence/w4/shots/` |
| Живой просмотр (Chrome) | Browser Use на `http://127.0.0.1:8815` (реальная отрисовка, `activate_tab` + `Page.captureScreenshot`) | 1024 (три раздела) и 390 (Примеры): раскладка читаема, overflow=0, minTap=44 — 4 кадра `evidence/w4/shots_live/` |
| Замороженные ассеты | `py -3 tools/soul1_w4_frozen_check.py` | polygon-фон, `#lg-lens`, `lg-lens-map`, `feDisplacementMap`, `--lg-*` — без изменений; index.html/app.js LF-only (0 CRLF) — `evidence/w4/frozen-assets.txt` |

## 5. До/после

* **Юмор:** было «библиотека не поставлена, приёмы — контракт»; стало реальное
  состояние каждого приёма (`применяется/не применяется`, причина, объём слоя
  в токенах) и кнопка «Проверить приём», показывающая точный текст слоя и
  версию без вызова модели.
* **Примеры:** было пустое поле с описанием схемы; стало 20 карточек
  (4 эталона, 16 черновиков), фильтры, редактор, архив, A/B, «почему
  выбраны», честные пустые состояния при недоступной базе.
* **Обучение:** было «контур не поставлен»; стало: сколько ответов под
  наблюдением, какие сигналы зафиксированы (`metaphor_continuation: 1` на
  реальном прогоне окна), окна без реакции, предпочтения чата с затуханием,
  пауза и сброс.
* **Fail-open:** при недоступном оценщике окно закрывается `unknown`, беседа
  не блокируется (тест); при выключенных осях — прежнее поведение бит-в-бит.

## 6. Живой прогон окна реакций (артефакт, не мок модели-провайдера)

`tools/ui_soul1_w4_dump_fixture.py` снимает фикстуру настоящим слоем на
временной БД (миграция v36 → сид → отметка эталонов → захват отправки →
проход окна с оценщиком-заглушкой). Итог прогона: `humor_sends_scanned=1`,
`humor_signals=1`, `humor_unknown=0`, `humor_lessons_applied=0` (одно
наблюдение — гипотеза, не вывод). Это НЕ доказательство живого провайдера:
строка-маркер в отчёте ниже.

## 7. Семь обязательных сценариев SOUL-08.12 (симуляции + честные маркеры)

| Сценарий | Тест | Что проверено | Live-маркер (нужно канарейке) |
|---|---|---|---|
| Подхватили бюрократическую метафору | `test_scenario_1_metaphor_picked_up` | сигнал `metaphor_continuation` с техникой и доменом, вес не поднят с одного наблюдения | нужен живой собеседник, продолжающий образ в ветке |
| Просьба не повторять грубость | `test_scenario_2_stop_request_weakens_only_in_context` | `stop_request` записан, приём ослаблен только в своём чате | нужен реальный участник с просьбой |
| Бурная реакция на спор без шутки | `test_scenario_3_dramatic_reaction_without_joke_is_not_success` | сигнал `unrelated`, гипотез/применений нет | нужен реальный спор без приёма |
| Сообщения никто не комментирует | `test_scenario_4_nobody_comments_is_unknown_not_failure` | окно закрыто `unknown`, исход не failure | наблюдение 24–48 ч на тишине |
| Группа обсуждает другое без reply | `test_scenario_5_group_talks_elsewhere_is_not_success` | нет связи → не успех | нужен чат с параллельной темой |
| Похожие шутки в двух чатах | `test_scenario_6_two_chats_evaluate_differently` | ослабление в A, чат B не затронут | нужны два живых чата |
| Реакции одного лица | `test_scenario_7_one_person_reactions_do_not_inflate_success` | сторожа `small_n/single_user/single_topic/brigading` | нужны реальные повторные реакции |

Живые маркеры видны владельцу в разделе «Обучение» (блок «Обязательные
сценарии и что проверяется живьём») — `scenario_summary()`.

## 8. Осознанные границы и решения

1. **Новый тип feedback не создавался на уровне SQL**: таблица
   `mca_experience_feedback` фиксирует `source_kind` CHECK-констрейнтом, а
   пересборка v28-таблицы ради нового значения рискует данными без выгоды.
   Вид сигнала юмора живёт в типизированном `signal_json`
   (`domain=humor`, класс, приём, уверенность, маркеры), а класс источника
   выбирается по правам автора (`social_reaction` / `participant_correction`
   / `owner_correction`). Расширение контура — новые типы evidence, канонические
   правила уроков, измерение `humor_fit` и вид валидации `humor_instruction`.
2. **Черновики не идут в runtime**: осознанно. Библиотека наполняется без
   ложного «владелец одобрил»; эталонами становятся только помеченные.
3. **Классификатор реакций** работает в существующем фоновом проходе опыта;
   на обычном ответе LLM не зовётся (проверено тестом).
4. **SOUL-AMD.2.6 — частично**: жанровые рамки (4) и путь «Ностальгия»;
   проводка снов/глубокого сна/лора/историй — следующий слайс, граница
   честно записана в `note` блоков реестра и в `requirements-coverage.md`.

## 9. Инцидентальные находки

1. **По делу (исправлено):** карточки приёмов в тесной сетке схлопывались
   (текст «по буквам» в узкой колонке). Причина — контент-rich карточки в
   `.speech-card` (строка) + `speech-grid-tight`. Переведены на плотные ряды
   `.speech-rule` (тот же визуальный язык, что у правил стиля). Найдено живым
   просмотром, подтверждено кадрами `shots_live/`.
2. **По делу (исправлено):** `manifest_for_events(..., include_text=False)` —
   такого параметра нет; предпросмотр приёма терял манифест. Исправлено,
   покрыто прогоном (в фикстуре `probe.manifest` присутствует).
3. **По делу (исправлено):** поля-`input` в новых разделах были ниже 44px на
   широких экранах; добавлен `min-height:44px` (в новых контролах).
4. **Обновления сторожей соседних наборов (непреложно, по конвенции волн):**
   хвост реестра миграций `35 → 36` (`test_mca05_episodes_stories_round1027`,
   `test_mca17c_invariants_round1047`), список действий RBAC
   (`test_permissions`, `test_webapp_api`), ожидания W6 по разделам
   «Юмор/Примеры/Обучение» (`test_soul1_w6_speech_ui`), состав GateState в
   `test_soul1_composer_layers`. Каждое изменение — следствие нового
   контракта, а не ослабление проверки: сторож записи `prompts.*` **усилен**
   (закрытый набор документов у `_write_document`).
5. **Не блокирует (unrelated/pre-existing):** в ops-окружении `playwright`
   установлен в `.venv`, а не в системном `py -3` — харнессы слайса
   запускаются через `.venv\Scripts\python.exe` (то же и у W6-харнесса).

## 10. FIX-W4 — закрытие блокеров REVIEW-W4 (Needs Fixes)

Ревью: `plans/features/soul-1/review-w4.md` (3 блокера + заметка §6.1).
Правки — минимальные, ровно по находкам.

### F1 — SOUL-07.2: approve/archive не проверяли принадлежность чату

- **Репро до правки (моё):** `tests/test_soul1_w4_examples_scope.py` →
  `assert approve_status == 403` дало **`AssertionError: 200`**: контент-админ
  чата A утвердил chat-scoped пример чата B (и перевёл бы его в архив).
  Транскрипт RED: `evidence/w4/fix-repro-red.txt`.
- **Правка:** `web/api/speech.py` — один хелпер `_guard_sample_chat_scope()`
  (404 нет примера / 403 чужой chat-scoped) вызывается в approve, archive,
  update и delete: граница изоляции больше не расходится между обработчиками.
- **Проверка (GREEN):** `test_foreign_chat_approve_and_archive_are_forbidden`
  (403 + данные не изменились; симметрия с update/delete),
  `test_own_chat_approve_and_archive_still_work` (свой чат — ok),
  `test_global_samples_are_editable_by_any_chat_admin` (глобальный пример не
  привязан к чату).

### F2 — SOUL-08.11: `telemetry().sends` всегда 0 (битый биндинг)

- **Репро до правки (моё):** `repro_f2.py` — эпизод реально записан
  (`raw episodes humor_send: 1`), но `telemetry(chat).sends = 0` и
  `telemetry(global).sends = 0`; причина видна: `ProgrammingError: Incorrect
  number of bindings supplied. The current statement uses 2, and there are 1`.
- **Правка:** `services/mca_humor_feedback.py` — биндинг
  `(SEND_TASK_TYPE,) + args`; тихий `except` заменён честным WARNING (сбой
  счётчика больше не выглядит как «ноль наблюдений»).
- **Проверка:** проба после правки → `sends: 1` (по чату) и `1` (глобально),
  EXIT 0; тест `test_telemetry_counts_captured_sends` (0 → 1 → 1 → 2 по двум
  чатам); в обновлённой фикстуре слайса «Обучение» больше не противоречит
  себе: `sends: 1` при `signals={metaphor_continuation: 1}`.

### F3 — хаб «Речь и характер» врал о поставленном

- **Правка:** `web/api/speech.py` — `_examples_card()` (реальная библиотека:
  счётчики эталонов/черновиков, при недоступной базе честные `off` + причина)
  и `_learning_card()` (уроки опыта + реакции на шутки по своей оси).
- **Проверка:** payload настоящего `get_overview`: «Примеры · готово ·
  карточек: 20 · эталонов: 4 · черновиков: 16», «Обучение · готово · уроки
  опыта и реакции на шутки включены…»; тест
  `test_overview_cards_reflect_delivered_sections`; живой кадр хаба
  `evidence/w4/shots_live/fix_hub_1024.png` (Chrome, реальная отрисовка);
  в UI-прогоне добавлена проверка хаба (`notes[*].label = "<vw>/hub"`),
  `failures=0`.

### Заметка §6.1 — пин закрытого набора полей

`test_send_metadata_is_bounded_and_typed` пинует **точный** кортеж
`SEND_FIELDS` и точный набор ключей результата: дрейф кортежа убивается
тестом. Расширение итератора в `bounded_send_metadata` (исходная M11
ревьюера) добито в C1 — см. ниже.

Пять правок добавлены и в мутационный свидетель
(`tools/soul1_w4_mutation_witness.py`): снятие проверки чата на approve (F1),
порча биндинга счётчика (F2), возврат `not_implemented` в карточку «Примеры»
(F3), расширение итератора секрето-именами (M11) и проход всех переданных
kwargs (C1) — все убиты тестами (**14/14** суммарно).

### C1 (RECHECK-W4) — M11 убита на коммите

RECHECK-W4 §0 («Коррекция C1») установил: пин кортежа закрывает дрейф
`SEND_FIELDS`, но расширение итератора полей (`list(SEND_FIELDS) +
["secret_prompt","raw_text"]`) выживало — тест не передавал секрето-подобный
неизвестный kwarg.

- **Правка по рецепту ревьюера:** в dirty-вызов добавлены
  `api_key="sk_live_abcdef"` (рецепт) и `secret_prompt`/`raw_text` (имена из
  M11) — значения подобраны так, чтобы прошли `_SAFE_TOKEN`, иначе утечку
  маскировал бы сам фильтр токенов. Ассерты: ключей нет в результате; пин
  кортежа не тронут.
- **Мутационная проверка:** в свидетель добавлены обе формы расширения
  итератора (буквальная M11 ревьюера и «все переданные kwargs»); прогон —
  **14/14 KILLED** (`mutation-witness.json`), включая M11.
- **Прогоны (commit-time, те же байты, что в коммите):** файл — 27 passed;
  пять W4-файлов — **83 passed** (`focused-tests.txt`); мутационный свидетель —
  **14/14**; периметр — **3869/0**, два прогона подряд на одних байтах
  (`perimeter.txt`); паритет OFF — новые слои не рендерятся (`parity-off.json`).
- **Границы:** это инструмент, а не runtime; живого пути у M11 не было и нет
  (вызовы фиксированы, фильтр токенов на месте) — правка закрывает слабость
  теста, а не дефект поставки.

### Прогоны FIX-W4 (мои счётчики)

| Прогон | Результат |
|---|---|
| W4-файлы (5 файлов, включая новый) | **83 passed** (`focused-tests.txt`) |
| Новый файл F1-регрессии | 5 passed |
| Периметр `-k "webapp or ia_ or soul1 or round1025 or round1024 or ui_ or glass or persona or prompt or registry or catalog"` | **3869 passed, 0 failed** (`perimeter.txt`) |
| Мутационный свидетель (F1/F2/F3 + C1/M11) | **14/14 убито** (`mutation-witness.json`) |
| Замороженные ассеты и LF | `FROZEN-ASSETS-OK` (`frozen-assets.txt`) |
| Паритет осей и отпечатки | без изменений: новые слои не рендерятся (`parity-off.json` обновлён) |
| JS-сторож дублей ключей | OK (`app.js`/`index.html` в этой правке не менялись) |
| UI-прогон (Playwright) + живой Chrome | `failures=0`; хаб-кадр `fix_hub_1024.png` |
| Каталог параметров | `CHECK OK` (Δ = 0) |

**Наблюдение (uncertain / не блокирует):** в одном промежуточном прогоне
периметра упал соседний тест
`tests/test_nostalgia_worker.py::TestLLMAndSend::test_send_failure_logs_error`
(«nostalgia» попадает в `-k` через `ia_`). Воспроизвести не удалось: тест
проходит отдельно, в паре с новым файлом и в двух последующих полных прогонах
периметра (3869/0 оба раза). **Повторилось в commit-time (C1):** первый прогон дал `2 failed, 3867 passed`; одна из упавших строк — того же файла (`TestCandidatesAndThreshold::test_golden_candidate_sent`), вторая строка в обрезанном логе не сохранилась; сразу следующий прогон на тех же байтах — `3869/0`, изолированный `tests/test_nostalgia_worker.py` — 26 passed. Диффом слайса его зависимости не затронуты (`services/nostalgia_worker.py` в FIX/C1-раундах не менялся); при следующем появлении — отдельный мини-слайд с фиксацией seed/порядка.

### Изменённые файлы FIX-W4/C1 и финальные отпечатки (sha256_12, final, commit-time)

| Файл | sha256_12 | Что изменилось |
|---|---|---|
| `web/api/speech.py` | `a69a67536ebe` | F1: `_guard_sample_chat_scope` в approve/archive/update/delete; F3: `_examples_card`/`_learning_card` |
| `services/mca_humor_feedback.py` | `59b7ac37a8d8` | F2: биндинг счётчика отправок + WARNING вместо тихого `except` |
| `tests/test_soul1_w4_examples_scope.py` (новый) | `1f901335ce45` | F1/F2/F3-регрессия (5 тестов, `TEST-LIFECYCLE: REGRESSION owner=soul-1/W4`) |
| `tests/test_soul1_w4_humor_feedback.py` | `76d47cd7489f` | пин `SEND_FIELDS` (§6.1) + C1: секрето-подобные kwargs отбрасываются |
| `tools/soul1_w4_mutation_witness.py` | `9ffcf661d730` | +F1/F2/F3-мутации и +обе C1-мутации (14 всего) |
| `tools/ui_soul1_w4_speech_e2e.py` | `945021a965a6` | хаб-проверка и кадр хаба |
| `tools/ui_soul1_w4_dump_fixture.py` | `189d2f8692c5` | фикстура включает реальный `get_overview`; JSON пишется LF (это фактический хеш; расхождение с заявкой `b14985dcf8a0` зафиксировано RECHECK-W4 §0 — инструмент, не runtime) |
| `plans/features/soul-1/evidence/w4/api-fixture.json` | `d6f10447de3e` | пере-снята настоящим слоем (хаб + `sends: 1`), LF-only |
| `plans/features/soul-1/evidence/w4/mutation-witness.json` | `1f86e713509f` | 14/14 KILLED (commit-time) |
| `plans/features/soul-1/evidence/w4/parity-off.json` | `f29eea14d13e` | паритет OFF + финальные отпечатки |
| `plans/features/soul-1/evidence/w4/focused-tests.txt` | `a37daf8b3196` | 83 passed (5 файлов) |
| `plans/features/soul-1/evidence/w4/perimeter.txt` | `1a9a7ad046e0` | 3869 passed / 0 failed (commit-time) |
| `plans/features/soul-1/evidence/w4/frozen-assets.txt` | `a18ae5058ec9` | `FROZEN-ASSETS-OK` + LF (commit-time) |

Кандидат зафиксирован коммитом слайса W4 поверх
`c5900874a4d8319d1066a2a548a2450449eb8712`; привязка строк в картах —
`plan.md` §«W4 binding».

## 11. Что осталось для канарейки/следующего слайса

1. Включить оси (`HUMOR_CRAFT_ENABLED`, `HUMOR_LIBRARY_ENABLED`,
   `HUMOR_FEEDBACK_ENABLED`) на одном чате и наблюдать реальные сигналы;
   закрыть **SOUL-08.12** (7 сценариев) на живых людях.
2. Провести публикующие пути снов/лора/историй через `authorial_system`
   (жанровые рамки уже в реестре) → закрыть SOUL-AMD.2.6 полностью.
3. Собрать 1–3 эталона владельцу и сравнить форму ответов до/после (A/B
   библиотеки) на реальных репликах.
