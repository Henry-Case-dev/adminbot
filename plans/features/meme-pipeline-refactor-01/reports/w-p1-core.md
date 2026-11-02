# P1 `MEME-PIPE-CORE` — три этапа мем-пайплайна, бюджет L/T/J, `manual=True`

Ветка `feat/meme-pipe-core`, база `609a3c33`. Пакет P1 карты (`MEME-PIPE-CORE`),
внутри него — серверная часть диагностики, помеченная в карте как этапы
`summary / joke / image / publish` (§7 ТЗ).

## 1. Три этапа — внутри существующего пайплайна

Второй ветки нет: всё живёт в `services/meme_initiative.py#consider_chat`
(единственная точка, которую вызывает `services/initiative_observer.py:1119`
через `on_initiative_cycle`).

| Этап | Где | Что делает |
|---|---|---|
| A — выжимка | `_default_summarize` (`services/meme_initiative.py:1578`), вызов на `:1381` | один LLM-вызов `step="meme_summary"`, **без потолка длины** |
| B — прикол | `_default_joke` (`:1620`), вызов на `:1404` | один LLM-вызов `step="meme_joke"`; промпт = `active_prompt` этапа B + инструкция длины |
| C — картинка | `render_image_prompt` (`:459`) + `_default_image` (`:1641`) | итоговый prompt = шаблон + **прикол**, провайдер получает его |

Ключевое: этап C получает `joke` (переменная `joke` на `:1425`), а не `summary`.
Текст прикола не уходит ни в чат, ни в `as_dict()`, ни в журнал — только числа
(`len`), `trimmed` и источники.

## 2. Потолок снят с выжимки

- В `_default_summarize` больше нет параметра `target`, в payload нет
  `target_chars`, постфактум-обрезки нет (`:1599-1617`).
- Из `MEME_SUMMARY_SYSTEM_PROMPT` убрана фраза «уложись в потолок» — текст
  зарегистрирован заново: метка `meme-summary-nolimit-01`, печать
  `175781ddfd7e` (иначе падает `tests/test_evol018_prompt_audit.py`).
- Старый отказ `exceeded_precomputed_limit` и `build_image_prompt` удалены:
  длинная выжимка больше не может «не влезть».
- Инжектируемый суммаризатор: `summarizer(chat_id, rows, system_prompt)` — цели
  в подписи нет вовсе (тест на длинную выжимку доказывает, что она доходит до
  этапа B целиком).

## 3. Бюджет J = max(0, L − T) — одна функция

`resolve_meme_budget(*, model_chars, admin, explicit, template) -> MemeBudget`
(`services/meme_initiative.py:474`):

- `L` (`ceiling`) — минимум кандидатов `explicit_override` →
  `admin_setting` → `model_capability` (логика и источник прежние);
- `T` (`template_chars`) = `len(render(template, ""))`: при одном `{joke}`
  подстановка на место, без плейсхолдера — историческое «шаблон + пробел +
  прикол» (`T = len(template) + 1`);
- `J` (`joke_budget`) = `max(0, L - T)`; `placeholder ∈ {slot, append, invalid}`
  (два и более `{joke}` — невалидная конфигурация, рантайм работает как append);
- инвариант `T + len(joke) ≤ L` проверяется тестом на реальном провайдере.

Инструкция модели — `joke_instruction` (`:496`):
`<промпт этапа B> + "\n\n" + "Сгенерируй прикол длиной не более N символов. Верни только текст прикола."`
Инструкция дописывается **после** редактируемого промпта: правка в админке не
отменяет потолок.

Защитная обрезка — `trim_joke` (`:503`), только страховка: по границе слова,
факт `trimmed=true` и исходная длина в журнале.

Витрина не разойдётся с рантаймом: `resolve_length_limit` оставлен как тонкая
обёртка (`:554`), которая считает те же числа через `resolve_meme_budget`
(её пока зовёт `web/api/routes.py:3959` — полоса P2 переводит вызов на
`MemeBudget`, тогда обёртку можно удалить). `summary_target` в ней всегда
`None` — потолка у выжимки нет, и это видно в витрине честно.

## 4. Аналитика: четыре различимых этапа без новых колонок

- `STAGE_JOKE = "joke"` (`:146`), порядок `considered → eligible → summary →
  joke → image_generation → publish (+failed/skipped)`.
- Факты этапов — компактный JSON в существующем поле `detail` строки:
  `summary{chars,source}`, `joke{limit,template_chars,ceiling,chars,trimmed,
  source,placeholder}`, `image_generation{chars,template_chars,
  template_revision,template_source,joke_chars}`, `publish{gate,manual}`.
  Сериализация — `compact_facts` (`:1152`), разбор — единственная
  `parse_attempt_facts` (`:1163`) (её же используют тесты и `analytics_snapshot`).
- Терминальные строки сохраняют нынешний текстовый `detail` (код причины),
  пройденные — несут JSON фактов (`_finish`, `:1176`).
- Новые коды: `joke_generation_failed`, `joke_empty`, `no_joke_budget`,
  `template_empty` — провал B не выдаётся за провал выжимки.
- `analytics_snapshot` получил сводку `joke{attempts, avg_chars, trimmed}`.
- Миграции схемы нет: `services/database.py` и таблицы журнала не тронуты.

## 5. `manual=True` (задел под `/meme`, P3)

`consider_chat(..., manual=False)`:
обходит квоту, кулдаун, минимум сообщений, случайный триггер, тихие часы,
in-flight-guard и гейт публикации; **не обходит** права (их проверяет
обработчик), готовность image-модуля/провайдера, наличие журнала и
разрешимость бюджета. Бронь квоты при `manual=True` не создаётся вовсе (в
журнале попытки фиксируется `publish{manual:true}`, `limit_source/value`), день
чата по-прежнему нужен для `job_id`/журнала. Пустое окно сообщений — честный
`low_activity` с `detail="window_empty"` и в ручном режиме тоже.

## 6.Что P2/P3/P5 обязаны переиспользовать

- **P2 (API/UI мем-настроек)**: `resolve_meme_budget` (не считать L/T/J
  заново), `MemeBudget.as_dict()` для среза витрины, `effective_meme_prompt`
  — он уже читает чат/hot-слои по `pg_key` **самого блока реестра**; как только
  в каталоге появятся ключи (`prompts.meme_joke`, `prompts.meme_image`) и
  `pg_key` у блоков `initiative.meme.joke` / `initiative.meme.image`, правка
  заработает без изменения сервиса. Шаблон показывать как `rendered`, а
  `{joke}` валидировать по `joke_placeholder_count` (≥2 → 422).
- **P3 (`/meme`)**: `consider_chat(db, chat_id, manual=True, llm=..., sender=...)`,
  коды `SKIP_*` для карты «код → бытовая причина», `AttemptResult.manually_triggered`.
- **P5 (аналитика/ярлыки)**: `STAGE_JOKE`, `parse_attempt_facts`,
  `analytics_snapshot()["joke"]`; ярлыки новых skip-кодов надо добавить в
  `services/initiative_observer.py::REASON_LABELS` и `web/app.js::memeSkipLabel`
  (эти файлы вне write-scope P1 — сейчас неизвестный код честно показывается
  своим кодом).

## 7. Тесты

`tests/test_meme_pipeline_stages.py` (новый, 18 проверок, CONTRACT):

1. этап A не получает потолка, длинная выжимка доходит до B целиком;
2. точный N = J в инструкции (L из админской настройки) и пересчёт при
   шаблоне с `{joke}`;
3. этап C получает прикол, а не выжимку;
4. защитная обрезка только на перелёте (+ контроль «в бюджете не режем»);
5. четыре строки журнала с нужными полями; провал B — свой код, провайдер не
   вызван, квота не потрачена; `J=0` и пустой прикол — разные пропуски;
6. выдача: ровно один исходящий вызов-фото, без caption/текста, прикол и
   промпт наружу не уходят;
7. `manual=True` при квоте 0 + кулдауне + малом окне + промахе random + тихих
   часах + выключенных тумблерах + закрытом гейте всё равно публикует и не
   тратит квоту; `manual` не обходит image-модуль и журнал;
8. матрица бюджета (0/1/2 плейсхолдера, J=0, L неизвестен) и совпадение
   витрины с рантаймом; дословные заводские промпты и целостность печатей;
   слои промптов (чат → hot → заводской, пустое не обнуляет).

Мутационная проверка (вручную, файл восстановлен побайтово):
этап C на выжимке, отсутствие `trim_joke`, инструкция без N, обрезка выжимки,
отключённый manual-гейт — каждая мутация роняет соответствующий тест.

Обновлены существующие тесты (контракт изменился осознанно):
`tests/test_evol014_meme_initiative.py` (подпись суммаризатора, бюджет вместо
`summary_target`, B в живом мосте), `tests/test_p0_meme_image_only.py`
(фейк этапа B + новые ключи `limit`; ассерты «только картинка» не менялись),
пины отпечатка фабрик в `tests/test_expression_isolation_followup.py` и
`tests/test_p0_prompts_core.py`.

Прогон: `pytest` по девяти затронутым файлам — **144 passed**.
Широкий прогон `pytest tests -k "meme or initiative or prompt or registry"` —
1253 passed, 3 failed; все три падают и без файлов этой задачи
(`test_mca08_style_form::test_declared_events_really_emitted_in_code`,
`test_mca17a_observability_core_round1027::test_registry_event_names_exist_in_code`
— реестр объявляет `mca07_answer_cache`, эмиссии на этой базе нет;
`test_asap8_v6_p1_d11_registry::test_env_off_beats_product_toggle` —
порядко-зависимый, в одиночном прогоне зелёный). Вне скоупа P1.

## 8. Что НЕ сделано (следующие полосы)

- Поля в админке и каталог параметров (`prompts.meme_joke`/`prompts.meme_image`,
  группа `prompts_initiative_meme`): P2/P4. Каталог требует переэмита
  F8-артефактов (`tools/gen_param_registry_round1025.py`) и бампа baseline —
  это их полоса; поэтому P1 читает слои по `pg_key` блока и не вводит литерал.
- Ярлыки новых skip-кодов и меток стадий в UI — P4/P5.
- `/meme`: обработчик, RBAC, автоудаление — P3.

## 9. Риски

- Формат фактов в `detail` — строка JSON (слабee типизированной колонки):
  закрыт одним разборщиком + тестами разбора, миграции не потребовалось.
- `resolve_length_limit` — временная обёртка; после перевода `routes.py`
  (P2) удалить, иначе останется два имени для одних чисел.
