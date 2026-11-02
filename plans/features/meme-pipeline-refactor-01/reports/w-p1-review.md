# P1 `MEME-PIPE-CORE`: независимое ревью (Reviewer)

- Кандидат: ветка `feat/meme-pipe-core`, HEAD **b272a63b**, база **609a3c33**
- Дата: 03.11.2026, Reviewer, worktree вне репозитория (`WorkspaceData/worktrees`)
- Источники истины: `plans/owner_inputs/2026-11-03-meme-pipeline-refactor-01.md` (§1-§3, §5-§8),
  `plans/features/meme-pipeline-refactor-01/plan.md`, `requirements-map.json`, `slice-graph.json`,
  решения Architect `arch/integration-decisions.md` (коммит 53537b5f, ветка `evol/impl`),
  отчёт Builder `reports/w-p1-core.md`
- Область ревью: слайс `MEME-PIPE-CORE` (54 обязательные строки карты) и критерии владельца
  §8 №1, 2, 6, 7, 8, 9, плюс серверная часть §7 «аналитика по этапам» и `manual=True` (задел P3)

## Вердикт

**Approved** по поведению слайса. Все 54 обязательные строки `MEME-PIPE-CORE` подтверждены на
кандидате b272a63b, блокирующих замечаний нет.

Отдельно для PM (на качество кода не влияет): в карте у всех строк статус `PENDING` и
`candidate_commit: ""`, поэтому `requirements_gate.py --stage review` падает только на
бухгалтерии: 1 ошибка "candidate mismatch" + 54 "PENDING". Структурных, графовых и scope-ошибок
нет. Нужно связать доказательства с b272a63b и статусами.

## Три опоры приёмки

**Implementation.** Проверен фактический путь исполнения: единственная точка входа
`services/meme_initiative.py:1239 consider_chat`; этап A - `_default_summarize` (`:1577`, вызов
`:1399`); этап B - `_default_joke` (`:1619`, вызов `:1425`); этап C - `render_image_prompt`
(`:448`) плюс `_default_image` (`:1645`, вызов `:1488`). Бюджет считает единственная функция
`resolve_meme_budget` (`:461`). Порядок "дешёвые гейты -> бюджет -> in-flight (`:1389`) ->
A (`:1399`) -> B (`:1425`) -> бронь квоты (`:1464`) -> провайдер" подтверждён и кодом, и пробами:
провал B не создаёт бронь и не вызывает провайдера.

**Test validity.** Прочитаны тела и утверждения тестов: `tests/test_meme_pipeline_stages.py`
(18 тестов, CONTRACT) и обновлённого `tests/test_evol014_meme_initiative.py`. Тесты проверяют
контракт владельца, а не реализацию: отсутствие `target_chars` в реальном payload
`_default_summarize`; дословный N = J в инструкции B; `prompt == шаблон + прикол` у провайдера;
`trimmed` только на перелёте; четыре строки журнала с `limit` и `chars`; отсутствие текстов в
`detail`/`as_dict`; `manual=True` при квоте 0, кулдауне, малом окне, промахе random, тихих часах,
выключенных тумблерах и закрытом гейте; отсутствие брони. Подменены только внешние границы (LLM,
image-провайдер, Telegram); реестр промптов и SQLite-журнал настоящие. Вакуумных `assert True` и
безусловных проверок нет.

**Independent challenge.** 4 мои собственные мутации (файл восстановлен, sha256 сверен:
`B540A59D...A8FCB`) и 55 собственных проверок в отдельных прогонах.
Мутации: M1 убрать директиву длины из `joke_instruction` (падают 2 теста, включая
`test_stage_b_instruction_carries_exact_j_budget`); M2 убрать `trim_joke` (падает
`test_protective_trim_only_when_model_overshoots`); M3 этап C на выжимке
(`render_image_prompt(template, summary)`) (падают 5 тестов, включая
`test_stage_c_image_prompt_uses_joke_not_summary`); M4 вернуть обрезку выжимки (падают
`test_stage_a_summary_has_no_length_ceiling` и
`test_long_summary_is_not_truncated_and_feeds_joke_whole`).
Пробы (собственные, не копии тестов Builder; 45/45, 6/6, 4/4 PASS): выжимка 9000 символов
доходит до B целиком при L=900; N=871 ровно; провайдер получил ровно
`Создай мем с шрифтом импакт: <прикол>`; T+len(joke) <= L для шаблона с `{joke}` и без него;
J=0 даёт `no_joke_budget` без LLM; J=1 даёт обрезку до 1 символа с `trimmed`; пустой прикол даёт
`joke_empty`; обрезка без пробелов равна ровно J; провалы A, B и C не отправляют в чат ничего;
кулдаун и квота 0 отсекают ДО платной выжимки; реальный `_meme_sender` даёт ровно одно фото без
caption и без текстов, прикол и шаблон в Telegram-вызовах не видны; уникальные маркеры выжимки и
прикола отсутствуют в журнале, `as_dict()` и в видимых исходящих данных.

## Приёмочный лист (слайс MEME-PIPE-CORE)

| Требование | Статус | Доказательство |
|---|---|---|
| MEME-PIPE-THREE-STAGES | VERIFIED | `consider_chat:1399/1425/1488`; проба a1 (два шага LLM), c1 |
| MEME-STAGE-A-NO-CEILING | VERIFIED | сигнатура `:1577` без `target`; payload `:1598` без `target_chars`; промпт `:61-67` без "уложись"; мутация M4 |
| MEME-STAGE-B-JOKE-CALL | VERIFIED | `_default_joke:1619`, `step="meme_joke"`; проба a1; тест живого пайплайна в test_evol014 |
| MEME-PROMPT-JOKE-DEFAULT | VERIFIED | `MEME_JOKE_PROMPT:57` дословно; блок `initiative.meme.joke`; `seal_integrity() == {}` |
| MEME-STAGE-C-IMAGE-PROMPT | VERIFIED | `render_image_prompt:448`, `:1451`; пробы c1, c2, f1, f3; мутация M3 |
| MEME-LEN-J-BUDGET | VERIFIED | `resolve_meme_budget:461`, J = max(0, L-T); пробы b2, e1, e2, f2, f4; матричный тест |
| MEME-LEN-TARGET-FINAL-PROMPT | VERIFIED | L применяется только к итоговому prompt; выжимка не ограничена (проба a3, M4) |
| MEME-LEN-INSTRUCTION | VERIFIED | `joke_instruction:497` + `JOKE_LENGTH_DIRECTIVE:74`; проба b1; мутация M1 |
| MEME-LEN-TRUNCATION-GUARD | VERIFIED | `trim_joke:503` срабатывает только после генерации; флаг `trimmed`; пробы d1-d6; мутация M2 |
| MEME-DELIVERY-IMAGE-ONLY | VERIFIED | `_meme_sender` (`services/initiative_observer.py:1147-1171`); пробы dl2-dl5; tests/test_p0_meme_image_only.py |
| MEME-DELIVERY-ERROR-ONLY | VERIFIED | провалы A, B, C не шлют ничего (пробы s1-s3); тексты этапов в чат не уходят |
| MEME-PROHIB-NO-DUP-PIPELINE | VERIFIED | единственная точка `consider_chat:1239`; `on_initiative_cycle:1657`; второго пути нет |
| MEME-PROHIB-NO-HARDCODE | VERIFIED | в изменённом коде нет привязки к chat_id, пользователю или конкретному мему |
| MEME-PROHIB-NO-EXTRA-BUDGET | VERIFIED | единственный лимит - J; новых квот и капов инструкций нет |
| MEME-NOREGRESSION-SETTINGS | VERIFIED | настройки, день, квота и публикация не изменены; реестр зелёный (62 passed) |
| MEME-ACC-01/02/06/07/08/09/13 | VERIFIED | те же доказательства выше плюс широкий прогон: 1253 passed, 3 failed (все три падают на базе) |
| MEME-ANALYTICS-* (серверная часть §7) | VERIFIED (UI-ярлыки - P5) | `STAGE_JOKE:146`, `compact_facts:1145`, `parse_attempt_facts:1156`, `_finish:1173`, `analytics_snapshot:1729`; миграций нет; пробы an1-an3, nl1-nl2 |
| `manual=True` (задел P3) | VERIFIED | `:1301-1362`, `:1389`, `:1460`, `:1521`; пробы m1-m6 |

## Прогоны

- `tests/test_meme_pipeline_stages.py tests/test_evol014_meme_initiative.py tests/test_p0_meme_image_only.py`: **69 passed**
- `pytest tests -k "meme or initiative or prompt or registry"`: **1253 passed, 3 failed**
- Реестр и каталог: `test_evol018_prompt_audit`, `test_soul1_registry_completeness`, `test_soul1_core_registry_api`, `test_round1025_f8_registry`: **62 passed**
- Базовый прогон на 609a3c33 (отдельный worktree): **1234 passed, 3 failed** - те же три теста.
  Классификация: `test_mca08_style_form::test_declared_events_really_emitted_in_code` и
  `test_mca17a_observability_core_round1027::test_registry_event_names_exist_in_code` падают
  детерминированно (реестр объявляет `mca07_answer_cache`, эмиссии на базе нет);
  `test_asap8_v6_p1_d11_registry::test_env_off_beats_product_toggle` порядко-зависим (в одиночном
  прогоне зелёный). Все три вне P1, кандидат их не вызывает.
- Независимая сверка канонов: набор фабричных текстов база -> кандидат изменён ровно на два блока
  (изменён `initiative.meme.summary`, добавлен `initiative.meme.joke`), остальные **109 блоков
  побайтово идентичны**; перепин `FACTORY_SET_SHA256_12` с `630ca46dff76` на `54ac2b8ac34b`
  законен, других канонов правка не коснулась.

## Замечания

Блокирующих нет.

1. **P2 обязателен: витрина и рантайм считают от разных шаблонов.** `web/api/routes.py:3959`
   передаёт заводскую константу `mi.MEME_IMAGE_PROMPT`, тогда как рантайм считает от
   эффективного шаблона (`services/meme_initiative.py:1368`). Пока шаблон равен заводскому,
   числа совпадают (проба card: L и J равны рантайму). При шаблоне `Мем: {joke}` и L=400 витрина
   даёт J=371, рантайм J=395 - расхождение измерено. Это ровно строка `MEME-LEN-UI-DIAG`:
   перевести `routes.py` на `resolve_meme_budget(template=эффективный)` и удалить обёртку
   `resolve_length_limit` (`:554`). Формулировку отчёта Builder "витрина не разойдётся с
   рантаймом" уточнить: сейчас она верна только при шаблоне, равном заводскому.
2. **P2: устаревшая подпись в карточке мемов.** `web/index.html:1789`
   ("считается ДО выжимки, без последующей обрезки") больше не описывает поведение;
   `summary_target` всегда `-` (`:1787-1788`). Карточка правится в P2 (файл сериализован
   `cog-map-s3`, arch §7); тогда же три требуемых числа §3 ТЗ: L, длина шаблона, J.
3. **P5: ярлыки.** `web/app.js::memeStageLabel` не знает стадию `joke`, `memeSkipLabel` - коды
   `joke_generation_failed`, `joke_empty`, `no_joke_budget`, `template_empty`. Сейчас бейдж
   честно показывает сырой код; ярлыки добавить в P5 вместе с `REASON_LABELS`.
4. **P2/P5: имя факта плейсхолдера.** arch §2 называет факт `template_placeholder_invalid`,
   реализация пишет `placeholder:"invalid"` (`:1447`). Информация та же; если карта или UI будут
   ссылаться на имя, привести к одному.
5. **P3: не передавать `prompt_override` без `model_chars`.** `:1376` при заданном
   `prompt_override` не запрашивает capability модели, то есть L считается без потолка модели.
   Сейчас в проде `prompt_override` никто не передаёт (только тесты), поэтому это латентный риск,
   а не дефект: обработчику `/meme` шаблон брать через слои настроек, а не через этот аргумент.
6. **Визуальная проверка карточки.** P1 не меняет `web/**` (в диффе только
   `services/meme_initiative.py`, `services/prompt_registry.py`, тесты и отчёт). Данные, которые
   рендерит карточка, проверены серверно через `routes._meme_settings_payload`: стадия `joke` есть
   в списке, `summary_target = null`, L и J совпадают с рантаймом при заводском шаблоне.
   Отрендеренная проверка карточки (Playwright и Browser Use) относится к P2, где карточка
   реально правится; на P1 визуальных обязательств нет.

## Что переиспользовать дальше

- **P2**: `resolve_meme_budget` и `MemeBudget.as_dict()` (не считать L, T, J заново),
  `effective_meme_prompt`, `joke_placeholder_count` (два и более `{joke}` -> 422),
  `template_chars` для среза витрины; ключи `prompts.meme_joke` и `prompts.meme_image` с
  `pg_key` у блоков.
- **P3**: `consider_chat(..., manual=True)`, коды `SKIP_*` для карты "код -> бытовая причина",
  `AttemptResult.manually_triggered`; не обходить image-модуль и наличие журнала.
- **P5**: `STAGE_JOKE`, `parse_attempt_facts`, `analytics_snapshot()["joke"]`, ярлыки стадии и
  четырёх новых кодов.

## Границы доказательств

- Живой прогон `/meme` в чате владельца не выполнялся: обработчик команды - полоса P3, в этом
  кандидате его нет. Наблюдение владельца по PET_PROJECT остаётся за P3.
- Продовый деплой не проверялся: ревью ограничено кандидатом b272a63b.
7. **База ветки старше решений Architect.** `arch/integration-decisions.md` появился в коммите
   53537b5f (`evol/impl`) и в базе 609a3c33 отсутствует. Реализация при этом совпадает с arch §1
   (B внутри `consider_chat`, до брони), §2 (`resolve_meme_budget`, J = max(0, L-T), инструкция
   после редактируемого промпта, `trim_joke` как страховка), §4 (`manual`-матрица), §5 (стадии и
   факты в `detail`, без миграции). Перед интеграцией ветку нужно ребейзить на актуальную линию,
   иначе документ решений не попадёт в релизный артефакт.
