# P0IM-BAN-CONFLATE — корректива блокера Reviewer (кандидат `2d41f2b3`)

**Эпик:** `P0-INIT-MEME-UX-DIAG`. **Строка:** `P0IM-BAN-CONFLATE` (метка коммита; строки в
карте требований нет — см. `binding-f984f06a.md` §3).
**Кандидат кода:** `2d41f2b3a659da298a506d934e052274f284526e`, ветка `fix/p0im-final-train`.
**База:** production `6c11fc08` (2.58.194). **Предыдущий кандидат:** `926b093a` (код),
`262f7f18` (док) — по нему Reviewer дал ровно один блокер, ниже он закрыт.

## 1. Находка Reviewer (как есть)

`generated` в `web/api/initiative_publications.py` рос от ЛЮБОЙ строки, у которой в `stages`
есть этап `publish`. Историческая строка `publish`/`skipped` без картинки (пустой `job_id`)
считалась сгенерированной: на стенде Reviewer (форма `old-1` из `LEGACY_ATTEMPTS`:
`stage=publish`, `outcome=skipped`, `reason_code=cooldown_active`, `detail` без фактов
публикации) счётчик давал `generated=1` при `published=0`, `delivered=false`.
Это склеивало «попытка дошла до этапа публикации» с «картинка реально получена».

## 2. Что изменено (минимально, без новых запросов и полей БД)

`web/api/initiative_publications.py` (+53/−8, 4 места):

| место | что |
|---|---|
| `:136` | `STAGE_OUTCOME_PASSED = "passed"` — исход ПРОЙДЕННОГО этапа (`_finish` пишет его всем не-терминальным строкам журнала мема) |
| `:141` | `IMAGE_FAILED_REASON = "image_generation_failed"` — код терминального отказа генерации (`meme_initiative.SKIP_IMAGE_FAILED`); равенство проверяется тестом, чтобы словарь не разъехался |
| `:536` | в `_meme_attempts_grouped` по УЖЕ разобранной цепочке `chain` вычисляется `image_ready`: есть пройденный этап `image_generation` И терминальный исход не является отказом генерации (`failed` + `image_generation_failed`) |
| `:566` | у логической попытки появилось аддитивное поле `generated` — доказана ли картинка именно у неё |
| `:873` | `list_publications` суммирует `generated` по этому полю, а не по наличию этапа `publish` |

Никаких новых SQL-запросов, эндпоинтов, полей БД, флагов и настроек нет: используются
существующие строки журнала и существующий `parse_attempt_facts`. `published` и `delivered`
считаются ровно как раньше (их выражения не менялись). Реестр удержания, `record_attempt`,
спул, схема и читатели не тронуты.

**Семантика после правки:** «сгенерировано» = у попытки доказана картинка (пройденный этап
`image_generation`), кроме терминального отказа генерации.

- картинка + публикация отложена реальным конфликтом → `generated=true` (этап картинки есть);
- публикация прошла (`published`) → у попытки есть этап `image_generation` → `true`;
- отказ генерации (`failed` + `image_generation_failed`, этап картинки тоже пишется) → `false`;
- историческая `publish`/`skipped` без этапа картинки → `false` (это и был блокер).

## 3. Регрессия (ровно форма `old-1`)

Новый тест `test_bare_historical_publish_row_is_not_generated` работает на существующем
стенде `api_legacy` и на существующей строке `LEGACY_ATTEMPTS` (`old-1`: пустой `job_id`,
`publish`/`skipped`/`cooldown_active`, без `image_generation`):

- `old-1`: `stages == ["publish"]`, `generated is False`, `outcome != "published"`,
  `delivered is False`, `message_id is None`;
- счётчики этого стенда: `generated == 1` (доказанная картинка есть только у `J1`),
  `generated < checked`; `published` и `delivered` равны прямому пересчёту по тем же строкам.

Сохранены и уточнены существующие случаи (`test_generated_is_not_considered_and_not_published`):
`G2` (картинка + `publish` отложен конфликтом) — `generated is True`; `G3` (отказ генерации) —
`generated is False`, при этом `image_generation` в цепочке есть.

## 4. Мутации (каждая проверена прогоном, файл восстановлен)

| # | мутация | красные тесты |
|---|---|---|
| BAN1 | вернуть правило «есть этап `publish` → generated» | `test_bare_historical_publish_row_is_not_generated` |
| BAN2 | `generated` = любая записанная попытка (`bool(chain)`) | `test_generated_is_not_considered_and_not_published`, `test_bare_historical_publish_row_is_not_generated` |
| BAN3 | убрать исключение отказа генерации | `test_counts_carry_llm_calls_and_images_separately`, `test_generated_is_not_considered_and_not_published` |

Выживших мутаций нет; на прежнем коде (BAN1) красный ровно новый регресс на `old-1`.

## 5. Прогоны

| команда | результат |
|---|---|
| `pytest tests/test_initiative_publications_api.py` | **35 passed** |
| `pytest tests/test_initiative_publications_api.py tests/test_meme_init_diagnostics.py` | **79 passed** |
| 15-файловая серия мемов/инициативы/публикаций/диагностики | **365 passed, 4 failed** |
| `pytest tests/test_evol014_ui.py` | **17 passed** |

Четыре падения серии — те же предсуществующие на базе `6c11fc08`
(`test_act_on_opportunity_conflict_defers_to_intent`, `test_evaluate_phase_precheck_blocks_before_llm`,
`test_t1_nostalgia_delegated_refusal_sends_nothing`, `test_t5_every_text_send_site_passes_publish_guard`);
файлы этой правки их не касаются, новых падений нет. JS-наборы и e2e не перезапускались: UI-файлы
не менялись, e2e подменяет API своим стендом.

## 6. Честные пределы

- **Пре-`P0` история без этапов.** Строка `publish`/`published` без этапа `image_generation`
  теперь даёт `generated=false`: у неё нет фактов картинки, а «вывести из `published`» — снова
  догадка. Это осознанный **недоучёт только для старых записей** (в текущем пайплайне `_finish`
  пишет этап картинки всегда), не переучёт; в окне «7 дней» таких строк практически нет.
- Счётчик `images` не менялся: он по-прежнему считает записанные этапы Image API, включая
  неудачный вызов (это «вызов», а не «картинка»).
- `generated` — счётчик воронки на экране; UI-файлы и их подписи не менялись.
- Живого прода не было: кандидат не выложен. Строка `P0IM-BAN-CONFLATE` **не объявляется
  одобренной** — перепроверка за Reviewer.
- Реестр удержания (`P0IM-ID-FINISH`/`P0IM-ID-CONC`) этой правкой не затронут намеренно.
