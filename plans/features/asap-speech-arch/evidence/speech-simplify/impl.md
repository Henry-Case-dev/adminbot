# SPEECH-SIMPLIFY — реализация (lane SPEECH-IMPL-2, 25.10.2026)

База: `f0160fd8` (worktree `adminbot-wt-simpl2510`, ветка `task/speech-impl-2`).
Источник: `plans/features/asap-speech-arch/source-owner-speech-simplify-2026-10-25.md`.
Аудит: `evidence/speech-simplify/audit.md`; baseline: `probe-A-baseline.md`.

## 1. Точные runtime-тексты (байт-в-байт, §2/§5)

| Блок | Файл:строка | Носитель в payload |
|---|---|---|
| `BASE_SPEECH` | `services/mca_expression.py:99` | `<Speech_Base>` (`services/prompt_style_blocks.py:65`) |
| `HUMOR` | `services/mca_expression.py:105` | тот же блок, ровно один раз |
| `RESPONSE_LENGTH` | `services/mca_expression.py:111` | тот же блок |
| `FACTUAL_SPEECH` | `services/mca_expression.py:117` | тот же блок |
| `PROFANITY_OFF` | `services/mca_expression.py:77` | `<Expression_Settings>` / финальный контракт режима |
| `PROFANITY_OCCASIONAL` | `services/mca_expression.py:81` | то же |
| `PROFANITY_FREQUENT` | `services/mca_expression.py:86` | то же |
| `STYLE_DVACH` | `services/mca_expression.py:126`; пресет `services/style_policy.py:239` | `<Style_Policy_Hint>` при выбранном пресете |

Длина/краткость — только поведенческая инструкция: `max_chars`, токенных
бюджетов, обрезки ответа и дополнительных LLM-вызовов для неё нет.
Few-shot не обязателен: профили рендерятся без примеров (см. тест
`test_payload_has_single_short_speech_block`).

## 2. Как собирается payload (один блок, без второго слоя)

`services/prompt_composer.py`:
- `speech_base_text` добавляется один раз перед Expression (`:1525`);
- `simplify_core_for_prompt` (`:1249`) применяется к Core на сборке: из
  активной/заводской редакции уходят только три оперативных абзаца
  (техника шутки, драматургия реальных событий, ритм/длина). Биография,
  характер, свобода речи и «чего избегать» остаются; хранимый Core в БД не
  перезаписывается;
- если короткая `HUMOR` уже вошла в базовый блок, отдельный humor-слой не
  дублируется: `skip_reason=humor_folded_into_speech_base` (`:1610`);
- `speech_owner_block` (`:887`) отдаёт тот же `<Speech_Base>` нефлексивным
  речевым маршрутам (фактчек/сводки/авторские тексты) — один источник текста.

Фактический замер (offline, `compose_prompt`, profile=`speech_plain`):
`BASE_SPEECH=1, HUMOR=1, RESPONSE_LENGTH=1, FACTUAL_SPEECH=1`,
system `2172` симв., `sha12=1f34b42d0051`. До правки тот же план давал
`system=1473` симв. без этих блоков (базовые тексты отсутствовали), т.е.
дельта — ровно короткий блок, без длинных дублей.

## 3. Core: before / after

До (заводская Full-редакция, `services/chat_prompts.py`, база `f0160fd8`):
абзацы «Как рождается юмор…» (техника: ищи интерпретацию, развивай,
наращивай абсурд), «Как говорить о реальных событиях…» (цельная сцена,
метафора, развязка), «Ритм…» (длина/композиция). Они дублировали
Humor/Response Length и провоцировали драматургию.

После: заводская Full/Compact-редакция **не переписана** — авторские байты
сохранены. Фильтр сборки `simplify_core_for_prompt` вырезает эти три абзаца
из любой активной/заводской редакции только в payload; хранимый Core в БД не
меняется. Сохранены:
- вступление о характере (остроумие, абсурдное мышление, язвительность,
  непристойный юмор, «замечать нелепое»);
- «Свобода речи» (голос, не факты);
- «Грубость и конфликт»;
- «Чего избегать» (включая «не пытайся шутить в каждом сообщении»);
- фактические границы (не выдумывать события/людей/статистику).
Идемпотентность: повторный проход не находит точных абзацев и ничего не
меняет; авторские переформулировки не совпадают с точными строками и
остаются. Тест: `test_speech_simplify_2026_10_25.py` (Core payload),
`tests/test_p0_checkup_core_contract.py` (активный Core не перезаписан).

## 4. Семь конфликтов аудита — решение

| # | Конфликт аудита | Факт в коде `f0160fd8` | Решение |
|---|---|---|---|
| 1 | `EXPRESSION_CONTRACT` ~1200 симв. и «обязательный мат» | такого блока в `mca_expression.py` уже нет; были длинные тексты режимов | заменены на три коротких точных текста; «обязательный мат» отсутствует |
| 2 | `mca_humor.py`: 5–6 обязательных приёмов, кульминация | файла нет; владелец — `mca_humor_craft.py` | guard сокращён, техники сокращены; базовая `HUMOR` — один короткий блок; кульминации/квоты удалены |
| 3 | `STYLE_POLICY` + `LENGTH_GUIDE` требуют «развёрнуто» | `LENGTH_GUIDE` нет; style hint не задаёт длину | длина — только `RESPONSE_LENGTH`; SERIOUS/DEEP_RESEARCH больше не требуют иронии/токсичного стиля |
| 4 | Core: «сыпь шутками», «строй истории», «демонстрируй характер» | оперативные абзацы присутствовали | точечно сняты три абзаца (см. §3), личность сохранена |
| 5 | `style_policy.py` может резать мат | постобработка мат не удаляет | проверено тестом `test_profanity_survives_style_policy_postprocess`; файл не менялся |
| 6 | Direct/L2: «будь выразительным», «добавь метафору» | длинные дубли в каноне Вербализатора | заменены/убраны; короткий блок один раз, без «литературности» |
| 7 | `INITIATIVE_TONE` протекает в обычные ответы | тон инициативы отделён существующим путём | не подмешивается: обычный ответ собирается композером без initiative-блока; тест матрицы речи |

`mca_prompts.py`/`mca_humor.py`, упомянутые в аудите, в репозитории
отсутствуют; правки сделаны в фактических владельцах. Это уточнение
аудита, а не новый слой.

## 5. STYLE_DVACH

- пресет в существующем реестре `style_policy.PRESET_SPECS` (`:239`),
  библиотека отдаётся через `available_presets` того же редактора «Стиль
  письма»; отдельного обработчика/pipeline нет;
- выбор — существующим документом `style.policy` глобально и override для
  чата; по умолчанию пресет не применён (`build_document()` без dvach);
- при другом пресете текст Двача не попадает в `soft_instructions`
  (тест `test_other_style_does_not_leak_dvach_instruction`);
- мат не переопределяется: в тексте пресета нет правил мата, режим берётся
  только из `character.expression` (`test_dvach_does_not_override_profanity_mode`);
- «Медведь Press», пользовательские стили и права не тронуты.

## 6. Тесты (фактический прогон)

```
py -3 -m pytest tests -k "speech or expression or prompt or checkup or \
  factcheck or unified_core" -q
1443 passed; 3 падения — только Windows capture/subprocess OSError
(те же тесты проходят с -s; к коду речи не относятся).
```

Контрактный файл фичи: `tests/test_speech_simplify_2026_10_25.py` — **16 passed**.
Смежный фокус (13 файлов) — **275 passed**; единственный
`test_asap_speech_i_matrix.py::test_i05...` — межфайловая order-зависимость
глобального конфига, в своём файле проходит (`25 passed`), не речевая
регрессия. После восстановления UTF-8 в двух файлах пинов
(`test_expression_isolation_followup`, `test_p0_prompts_core`) широкий набор
даёт 1443 passed без функциональных падений.


Обновлены пины, которые защищали прежний owner-контракт и были перекрыты
источником 25.10: `test_asap_w1_semantics`, `test_p0_expression_final_contract`,
`test_p0e_expression_frequent`, `test_add_exp_expression`,
`test_unified_core_route_coverage`, `test_soul1_w4_humor_craft`,
`test_soul1_style_policy`, `test_samples_fewshot`. Новые проверки —
`tests/test_speech_simplify_2026_10_25.py` (`TEST-LIFECYCLE: CONTRACT
owner=SPEECH-SIMPLIFY/§2/§3/§8`).

## 7. Остаток и риски

- Реальные LLM-пробы A/B/C в этом лейне не запускались (жёсткая рамка: без
  LLM-проб). Готовое evidence B/C: `probe-BC` коммит `a521e2e5` (22 вызова,
  11 сценариев).
- Деплой/прод не трогались (вне рамки): нужен штатный release с проверкой
  загрузки текстов и пресета.
- UI: выбор пресета идёт через существующий редактор «Стиль письма»
  (`available_presets`); отдельная карточка в мини-аппе не добавлялась,
  чтобы не создавать второй механизм.
- Детектор мата остаётся диагностическим и даёт ложные срабатывания на
  обычных словах (`страхуется`); на генерацию не влияет.
