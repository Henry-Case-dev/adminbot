# P2 `MEME-API-SCOPE` — два редактируемых промпта мемов и диагностика L/T/J

- Ветка: `feat/meme-api-scope`, база `242fbd38` (P1 `MEME-PIPE-CORE`), HEAD — см. коммит ниже.
- Пакет карты: `MEME-API-SCOPE` (строки `MEME-PROMPT-THREE-LAYER` L73–L75) +
  серверная часть `MEME-LEN-UI-DIAG` (L114–L121, UI-витрина — полоса `MEME-UI-FIELDS`/P4).
- Решения: `arch/integration-decisions.md` §2–§3; замечания P1-ревью №1, №2, №4.

## 1. Ключи и дефолты

| Ключ каталога | Заводской текст (дословно) | Группа / вкладка | per-chat |
|---|---|---|---|
| `prompts.meme_joke` | `Придумай короткий абсурдный прикол из этой выжимки.` | `prompts_initiative_meme` / «Промпты» | да |
| `prompts.meme_image` | `Создай мем с шрифтом импакт:` | `prompts_initiative_meme` / «Промпты» | да |

Новая `GroupSpec("prompts_initiative_meme", "prompts", "Инициатива: мемы", …, 10)`;
вкладка берётся существующим catch-all `(CATEGORY_PROMPTS, None)` в `TAB_RULES`,
новых экранов/маршрутов нет. Заводской текст обоих промптов **не менялся** —
метки `meme-joke-evol014` / `meme-image-evol014` и печати остались те же
(`seal_integrity() == {}`). Этап A (выжимка) остаётся код-каноном: ТЗ требует
редактируемость только прикола и шаблона картинки.

## 2. Почему шаблон был фактически read-only и как это исправлено

Причина (найдена в P1, подтверждена здесь по коду и поведению):

1. блоки `initiative.meme.image` / `initiative.meme.joke` объявлялись в
   `_CODE_BLOCKS` с `ui="catalog_pending"` и **без `pg_key`**;
2. ключей не было в каталоге → `POST /api/config` отвечал `422 неизвестный ключ`;
3. полей промпта не было в `MemeSettingsUpdate`, а карточка мемов выводила
   шаблон статичным текстом.

Что сделано (без второго хранилища и без правки бизнес-логики чтения):

- `services/param_catalog.py`: две записи `_PROMPTS` (PG-only, `code_source` —
  те же константы) + новая группа. Каталог — единственный источник ключей.
- `services/prompt_registry.py`: у блоков появились `pg_key` и `ui="catalog"`
  через **одну** точку объявления `_PG_BLOCK_META`; прежние `declare_prompt`
  для этих двух блоков удалены (два объявления одного блока = скрытая
  инструкция, контракт EVOL-018).
- `services/meme_initiative.py`: `prompt_setting_key(block_id)` — ключ слоя
  берётся у самого блока реестра (литерала `prompts.*` в сервисе нет);
  `effective_meme_prompt` теперь различает слои `chat` / `global` / `factory`
  (раньше оба слоя схлопывались в `setting_override`), а отличие от заводской
  редакции считает по эффективному тексту, а не «по факту наличия слоя».
- `web/api/routes.py`: `prompt_joke` / `prompt_image` в `MemeSettingsUpdate`;
  пустая строка **снимает** чатовое переопределение (ключ удаляется из
  `overrides`), а не пишет пустоту.

Рантайм не менялся по существу: он уже читал чат/hot-слои по `pg_key` блока —
поэтому после появления ключа правка начинает действовать без правки сервиса.

## 3. Витрина = рантайм (закрыт замер P1-ревью)

`_meme_settings_payload` больше не берёт заводскую константу: шаблон читается
тем же `effective_meme_prompt`, а числа считает `resolve_meme_budget` — уже от
ЭФФЕКТИВНОГО шаблона. Обёртка `resolve_length_limit` и датакласс `LengthLimit`
удалены (второго имени для тех же чисел больше нет).

Замер (тест `test_preview_numbers_equal_runtime_numbers[chat_slot]`):
шаблон `Мем: {joke}`, `L=400` → `T=5`, `J=395`; старое поведение витрины давало
`J=371` (считалось от `MEME_IMAGE_PROMPT`). Тест сравнивает числа витрины с
фактами журнала реального прогона пайплайна, а не с повторным расчётом.

Что отдаёт `GET/POST /api/initiative/meme-settings` для карточки:

- `length_limit`: `ceiling` (L), `template_chars` (T), `joke_budget` (J),
  `source`, `known`, `placeholder`, `candidates`; плюс совместимые
  `value` / `prefix_chars` / `summary_target=null` для **текущей** (залоченной
  COG-MAP) карточки — P4 переводит UI на канонические имена и удаляет алиасы;
- `template`: `text` (эффективный шаблон), `source` (chat/global/factory),
  `placeholders`, `valid`, `error`;
- `prompts.joke` / `prompts.image` / `prompts.summary`: `text`, `source`
  (`chat` / `global` / `factory` / `explicit_override`), `differs_from_factory`,
  `factory_revision`, `revision`, `setting_key`;
- `image_prefix` — заводская константа (оставлена для текущего UI, P4 берёт
  `prompts.image.text`).

Валидация плейсхолдера — один гейт `_meme_template_guard` на **всех** путях
записи шаблона (`POST /api/initiative/meme-settings` и оба пути
`POST /api/config`): ≥2 `{joke}` → `422`, молчаливой записи нет. В рантайме
невалидная конфигурация по-прежнему честно отражается `placeholder="invalid"`
(согласование имени факта `template_placeholder_invalid` — за P5, замечание №4
P1-ревью не меняет поведение).

## 4. Тесты (`tests/test_meme_pipeline_api.py`, новый, 9 проверок, CONTRACT)

| Проверка | Что доказывает |
|---|---|
| `test_prompts_are_catalog_keys_with_single_registry_block` | оба ключа в каталоге, `per_chat`, блок один, `ui="catalog"`, заводские тексты дословны, `seal_integrity() == {}`, нет ключей каталога вне реестра |
| `test_each_prompt_edit_persists_and_reads_back` | правка каждого промпта пишется в ключи каталога, читается обратно в ответе и в повторном GET, `source="chat"` |
| `test_global_layer_then_chat_override_then_factory` | чат сильнее глобального; пустая строка снимает **чатовый** override (ключ удалён), действует глобальный, затем заводской |
| `test_preview_numbers_equal_runtime_numbers[factory/chat_slot/chat_append]` | L/T/J витрины = L/T/J реального прогона (журнал `joke`) = `resolve_meme_budget`; `T + len(прикол) <= L`; регресс 371→395 |
| `test_two_placeholders_are_rejected_without_writing` | ≥2 `{joke}` → 422 без записи; 0 и 1 плейсхолдер допустимы |
| `test_global_edit_saves_and_feeds_runtime` | глобальная правка (`POST /api/config`) сохраняется, читается рантаймом как слой `global`, невалидный шаблон отклоняется 422 |
| `test_post_requires_admin_and_some_change` | 403 без прав; «ничего не менялось» → 422, а не ложный успех |

Обновлены обоснованно:

- `tests/test_meme_pipeline_stages.py`: матрица бюджета больше не проверяет
  удалённую обёртку (assert `not hasattr(meme, "resolve_length_limit")`),
  слой промпта проверяется через штатный `get_chat_param_sourced`
  (`source` = `chat` / `global` / `factory` вместо общего `setting_override`);
- F8-пины каталога: `REGISTRY 595→597`, `GROUPS 120→121`,
  `_TAB_BY_GROUP 118→119`, `TAB_RULES 22` (in-place), `delta 189→191`,
  TSV 596→598, categorized 570→572, prompts 26→28, хэши
  `param_catalog.py`/`routes.py`; артефакты переизданы
  `tools/gen_param_registry_round1025.py`, фикстуры —
  `tools/_meme_p2_reissue_f8.py` (новый, идемпотентный).

Прогоны:

- `pytest tests/test_meme_pipeline_api.py` → **9 passed**
- пакет P2 (api + stages + evol014×2 + p0_meme_image_only + soul1_registry +
  evol018_audit + round1025_f8 + param_catalog + ui_verbilizer_tabs +
  mca19_block_f + ia_inventory + cfg03 + webapp_api) → **399 passed**
- широкий `pytest tests -k "meme or initiative or prompt or registry"` →
  **1262 passed, 3 failed**; все три падают и на базе `242fbd38` (проверено
  отдельным worktree того же коммита): `test_mca08`,
  `test_mca17a` (реестр объявляет событие без эмиссии в коде) и
  `test_asap8_v6_p1_d11` (порядкозависимый). Дополнительно наблюдались
  неустойчивые, не связанные с P2: `test_soul1_w5_initiative_vitality` (тот же
  файл на одинаковом коде даёт 18 passed / 18 passed / 1 failed) и
  `test_round1025_f8_registry::test_check_subprocess_exit_zero` (Windows+pytest
  capture: `subprocess.run` → `OSError WinError 6`; вручную `--check` → rc 0,
  с `-s` тест проходит).

**Тесты умеют падать** (4 мутации, файлы восстановлены, sha256 сверен):

| Мутация | Результат |
|---|---|
| M1 витрина снова считает от `mi.MEME_IMAGE_PROMPT` | 3 failed (все кейсы равенства рантайму) |
| M2 валидатор шаблона отключён (`reason=""`) | 2 failed (422 в обоих путях записи) |
| M3 пустой промпт пишется как значение вместо снятия override | 2 failed (провал слоёв + «нет изменений») |
| M4 чатовый слой игнорируется в `_prompt_layer` | 10 failed (в т.ч. все проверки override) |

## 5. Что P4 (`MEME-UI-FIELDS`) обязан сделать в `web/index.html` + `web/app.js`

Файлы в этой полосе не тронуты (их держит `cog-map-s3`). Готовый чек-лист:

1. **`web/index.html:1760–1791`, блок `data-meme-prompt`.** Сейчас шаблон
   выводится пассивным текстом `{{ memeSettingsView.promptImage.text }}`
   (`data-meme-prompt-text`) — заменить на `<textarea v-model="memeDraft.prompt_image" data-meme-prompt-image>`
   рядом с новым `<textarea v-model="memeDraft.prompt_joke" data-meme-prompt-joke>`
   (поля промпта прикола в карточке нет вообще).
2. **`web/index.html:1787–1789`, устаревшая подпись.** Строка
   `цель выжимки: — (считается ДО выжимки, без последующей обрезки)` неверна
   (потолка у выжимки нет, `summary_target` всегда `null`). Заменить тремя
   числами в формулировках ТЗ (строки 119–121 исходника):
   `Потолок итогового промпта: {lengthLimit.ceiling}`,
   `Длина шаблона картинки: {lengthLimit.template_chars}`,
   `Доступно для прикола: {lengthLimit.joke_budget}`; при
   `lengthLimit.known === false` — «неизвестен» вместо числа.
3. **`web/app.js:6878–6934` (`memeSettingsView`).** Добавить `promptJoke`,
   `promptImage` (уже есть), `template` (текст/источник/валидность/ошибка) и
   числа `ceiling`/`template_chars`/`joke_budget`; показывать источник
   `chat` / `global` / `factory` человеческими словами (сейчас бейдж знает
   только «заводской / изменён вручную»).
4. **`web/app.js:11174–11219` (`memeDraftFromSettings` + `saveMemeSettings`).**
   В черновик добавить `prompt_joke` / `prompt_image` (значения — из
   `prompts.*.text`), в тело сохранения — `put('prompt_joke', …)`,
   `put('prompt_image', …)`; для снятия переопределения отправлять пустую
   строку (сервер удаляет ключ и возвращает слой ниже); показывать `422`
   `template.error` у поля, не молча.
5. **`web/app.js:11285` `memeSkipLabel` и `memeStageLabel`** — ярлыки новых
   кодов/стадии `joke` (это одновременно замечание №3 P1-ревью и
   `MEME-ANALYTICS-STAGES`; полоса P5, но живёт в том же залоченном файле —
   делать одной правкой).
6. **После перевода UI на канонические имена** удалить из ответа
   `_meme_settings_payload` совместимые алиасы `length_limit.value` /
   `prefix_chars` / `summary_target` и обновить
   `tests/test_evol014_ui.py::test_settings_quota_and_analytics_payload`
   (сейчас он проверяет именно алиасы) — тогда останется ровно одно имя на
   одно число.
7. Визуальные обязательства P4 (Playwright + Browser Use) на P2 не возникают:
   `web/**` не менялся, серверные данные проверены API-тестами.

## 6. Риски и границы

- **Совместимость ответа.** `length_limit` теперь несёт и канонические, и
  прежние имена — двойных расчётов нет (одни и те же поля `MemeBudget`), но
  алиасы должны исчезнуть в P4; это записано в чек-лист.
- **Источник слоя.** `chat` / `global` различаются через штатный
  `chat_params.get_chat_param_sourced`; если чат-слой недоступен, значение
  честно помечается `global`/`factory` (fail-open на чтение, как и раньше).
- **Запись промптов идёт мимо матрицы прав `/api/config`** (гейт карточки
  мемов: владелец ЛС / global-local admin) — это решение Architect §3; журнал
  ревизий промптов (`prompt_activations`) для этого пути не пишется, как и до
  полосы. Отдельного требования в ТЗ на ревизии мем-промптов нет.
- **F8-пины** переизданы осознанно (`L-F11S-1`): +2 ключа, +1 группа,
  `routes.py` изменился по содержимому (новых endpoint'ов нет).
- Живой прогон в Telegram не выполнялся: полоса серверная, PET_PROJECT-наблюдение
  относится к `/meme` (P3) и карточке (P4).
