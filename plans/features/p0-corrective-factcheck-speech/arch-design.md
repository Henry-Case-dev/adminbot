# P0 CORRECTIVE — архитектурный разбор (ARCH-P0-FACTCHECK)

Дата: 2026-10-24 05:53 +12:00. HEAD: `849eeed9`. Режим: read-only, прод/SSH не трогался.
Источник: `source-2026-10-24.md` (§2–§8). Диагноз по фактическому коду + production-логам в репозитории.

**Вердикт: `ARCHITECT_ADJUSTMENT_REQUIRED`** — три из четырёх областей требуют расширения существующих
контрактов (provenance-kind, retrieval-outcome→вердикт, Style-Policy-инъекция вне композера), а не
новых подсистем. Ни одна коррекция не отменяет owner-ограничения §1.

## 1. PROMPTS (P0-A) — почему `provenance_missing` и что он значит

**Механика (code).** Значение из PG становится активным слоем только при наличии записи в
`character.prompt_history.provenance` с `sha256_12`, совпадающим с текстом: `prompt_registry.py:109`
(`PROVENANCE_WRITE_KINDS = owner_edit|factory_reset`), `:2182-2197` (`attested_revision`),
`:2200-2216` (`provenance_state`: нет записи → `provenance_missing`, sha≠ → `provenance_mismatch`),
`:2292-2310` (`resolve_speech_value` удерживает значение, отдаёт заводскую редакцию, пишет WARNING,
в PG ничего не меняет). Класс удержания — 11 ключей с `legacy_persona=True` (`withholding_required`,
`:2132-2146`; исключение — префикс `verbilizer.mode.`).

**Единственный путь, дающий провенанс** — `prompt_factory.write_speech_value` (`prompt_factory.py:424-500`,
докстринг `:431-435`: «значение, попавшее в PG иным путём (старый UI, SQL), остаётся без провенанса»).
`_mark_provenance` вызывается только из factory reset/owner edit/chat edit (`:397,475,538,552`).

**Факт по двум ключам.** В логе прод-рестарта (`_audit-2026-10-23/prod-checks/raw/main2.txt:88-98`)
оба ключа уже классифицированы миграцией как **кастом юзера**, а не канон:
`checkup_system_prompt | chars=2312`, `factcheck_verbalizer_system_prompt | chars=1712` — те же размеры,
что `stored_chars` в withheld-логе (source §B). Сверка с зарегистрированными ревизиями: checkup factory
`2077`/`38d63d86b54d`, `PREV_CHECKUP_CFG07A` `2347`/`0ce06cb149f8`; verbalizer factory `1632`/`c090b6956c70`,
`PREV_FACTCHECK_VERBALIZER_W1` `1725`/`c9b0f431e849` — **совпадений нет**. Значит это не «частично
мигрированный канон», а дореестровые правки владельца: запись сделана старым UI/сидом до появления
журнала, а лестница `PROMPT_MIGRATIONS` (`prompt_migrations.py:220-226,290-291`) такие байты не узнаёт
и намеренно не трогает (`:541-544`).

**Полный список `withheld_values()`** — не два ключа: класс удержания 11 блоков, в проде кастомными были
10 ключей, под удержание попадают **8** (`summary_editor` — `speech=False`, `summary_l2_writer` — без
`legacy_persona`): `direct_chat`, `direct_chat_verbalizer`, `factcheck_single`, `factcheck_verbalizer`,
`summary_single`, `summary_narrator`, `search`, `checkup`, `youtube`, `youtube_video`, `webpage`.
Витрина уже есть (`web/api/speech.py:2559`; строки — `prompt_registry.py:2321-2371`, без текстов) —
§2.1 «полный список» выполняется её вызовом на проде. **Скрытая вторая причина:** `migrate_prompt_canons`
пишет канон напрямую `cache.set(...)` (`prompt_migrations.py:549`) **без** `_mark_provenance` → любой
смигрированный канон формально недействителен и даёт `persisted_value_withheld` (§11: «исправлен» ложно).

**Штатное восстановление без отключения защиты и без перезаписи кастома** — новый вид аттестации
`legacy_adopt` + writer `prompt_factory.adopt_persisted_revision(block_id, *, expect_sha12, actor, reason)`:
провенанс пишется только при точном совпадении sha текущего PG-значения с объявленным `expect_sha12`
(«благословить» произвольный будущий текст нельзя), исходник уходит в `character.prompt_history.items`.
Два входа: (а) одноразовая идемпотентная миграция с **замороженным allowlist** аудированных sha
(`5fbf61cea310`, `1e8a3c69cf7b` + добытые витриной), (б) кнопка владельца «применить сохранённую
редакцию» в редакторе/Inspector (§2.3: сохранённая, действующая, причина, ревизия). Плюс аттестация
`factory_reset` в `migrate_prompt_canons` после `cache.set`. Без аттестации значение по-прежнему не действует.

**Побочный факт для §C/§4.** Checkup в проде исполняет **заводской** канон (`2077`), а не удержанный
`2312`; «удачная манера» из source §C — это заводской канон + Core + Expression
(`checkup_service.py:56-57,67-69`), и правило маленькой буквы лежит именно в заводском каноне
(`checkup_prompts.py:81`). Удержанный кастом не причина ни манеры, ни дефекта.

## 2. FACTCHECK (P0-B) — где теряется доказательство и где врётся вердикт

Цепочка: `target → envelope/decompose → retrieval plan → run_retrieval → evidence rows → analyst JSON
→ validator → verbalizer → renderer`.

| Точка | Сейчас | Требуется | file:line |
|---|---|---|---|
| План | `_MAX_QUERIES=3`, `_MAX_PRIMARY_FETCHES=2` | оставить, бюджет сделать честным | `factcheck_planner.py:51,54` |
| Бюджет | один дедлайн 10 c на все запросы+fetch; проверка **между** запросами; per-engine 5/10/15 c | остаток на запрос; `budget_exhausted` — отдельная причина | `:472,508-510,524-527,577-581`; `search_aggregator.py:126-128` |
| Лексический фильтр | `is_relevant_result`: подстрочный `t in haystack`, порог ≥2 и ≥20 %; при провале уровень **считается упавшим** | морфология/стемы через существующий `content_terms`; «нерелевантно» ≠ «провайдер упал» | `search_aggregator.py:74-84,172-177,189-191` |
| Потеря выдачи | при отказе всех уровней — `AllSearchEnginesFailedException` → в planner это `fetch_errors`, `search_text=""` | вернуть лучшую непустую выдачу с меткой `low_relevance` | `factcheck_planner.py:531-541` |
| Evidence | `retrieval_refs` → `evidence_rows_from_refs`, иначе разбор текста | без изменений схемы | `factcheck_service.py:628-634` |
| **Вердикт** | если `evidence` пуст → жёстко `insufficient_evidence` с reason `temporal_insufficient_evidence`; метрики `RetrievalOutcome` (`budget_exhausted/fetch_errors/queries_*`) **не читаются** | пробросить метрики и разделить: нет доказательств / поиск не удался / бюджет / обработка | `factcheck_service.py:668-672`; `factcheck_planner.py:475-489` |
| Единый вердикт | один `factual_verdict` + `parts` из JSON аналитика | per-claim без нового классификатора: `parts` из `decompose_claim` + вердикт части из аналитика | `temporal_factcheck.py:711-784` |
| Рендер | универсальный заголовок `insufficient_evidence` скрывает технический сбой | отдельные заголовки/примечания для сбоя и бюджета, разбор частей | `factcheck_renderer.py:55-60,80-85,262-285` |

**Ключевой вывод.** Гипотеза §3.3 подтверждается частично и в более жёсткой форме: недостаточно
«лексический фильтр отбросил» — при пустом результате **любая** техническая причина превращается в
содержательный вердикт об отсутствии доказательств (`:668-672`). Отличить сбои сейчас невозможно не
из-за отсутствия данных, а из-за отсутствия их передачи: `RetrievalOutcome` уже несёт всё нужное.

**Per-claim уже существует** (схема `parts`, серверная агрегация `:764-770,774`, рендер
`_part_bindings`): новый классификатор не нужен. Нужно (1) не short-circuit'ить стадию в один
бесструктурный payload, (2) заполнять части серверной декомпозицией там, где модель их не дала,
с вердиктом не выше `insufficient_evidence` (positive без evidence запрещён), (3) список из 2–4 частей
уже ограничен рендером (`_MAX_BOUND_PARTS=4`).

## 3. CHECKUP / CORE / STYLE (P0-C, P0-D)

**Проверенный шов.** `speech_owner_block` отдаёт **только** Core + Expression
(`prompt_composer.py:871-913`); Style Policy в нём нет — она живёт отдельным слоем композера
(`:1627-1663`) и в Checkup/фактчек/саммари/search/youtube/web не попадает. Поэтому Checkup вынужден
сам задавать типографику: `checkup_prompts.py:81-85` (пункты 1–5) + `STYLE_BLOCKS_SUFFIX`
(`prompt_style_blocks.py:28-55`). Отсюда же конфликт §4.2: жанровый промпт владеет тем, чем должен
владеть Style Policy, и добавляет «начинай с маленькой буквы» (`:81`).

**Требуемое распределение.** Жанровый канон Checkup — только: работа с логами, отделение неисправности
от предупреждения и гипотезы, точность, допустимая ирония, запрет markdown/списков в отчёте, лимит
длины. Всё про пунктуацию/кавычки/тире/капитализацию — Style Policy. Мат/резкость — Expression.

**Минимальный дифф:** (1) новый `speech_style_block(chat_id)` рядом с `speech_owner_block`, тот же
рендер, что у слоя композера (второго рендера нет); порядок вставки в не-композерных маршрутах:
жанровый канон → Core → Expression → Style Policy → служебная приписка (у Checkup —
`CHECKUP_FALLBACK_NOTICE` строго последней, `checkup_service.py:70-71`);
(2) из заводского канона Checkup убрать пункты 1–3 и «маленькую букву», поднять
`FACTORY_REVISION_LABELS` + ступень `PREV_*` (кастом не перезаписывается — `prompt_migrations.py:541-544`);
(3) Core Full/Compact: дописать недостающие качества §5.1 в **существующие** разделы
(заводские тексты `chat_prompts.py`: Full 1925 c, Compact 556 c). Уже есть: развивающийся абсурд,
язвительность, ритм/асимметрия, «не шути каждый раз», ограничение на выдумывание фактов.
Не хватает: явное «не автор справки/пресс-релиза», «противоречия, неудачные оправдания, странные
подробности», «образ привязан к деталям этого разговора». Compact получает те же три смысла, не список
прилагательных.
(4) **В проде действует owner-документ Core** (`character.core`, owner_edit, doc rev 6, 2327 c —
`prompt_migrations.py:451-459`), а не заводская константа. Поэтому правка фабрики §5.1 **не изменит
речь**, пока owner-документ не обновлён. Обновление — owner-preserving additive patch существующим
приёмом (`owner_preserve_core_full_patch`, `:480-515`) с сохранением исходника в
`character.migration_snapshots` и diff'ом в Inspector; без перезаписи авторских формулировок.

## 4. EXPRESSION (P0-E) — что доказано, а что нет

**Доказано (plumbing цел):** слой рендерится детерминированно (`mca_expression.py:313-340`), читается
из `character.expression` через chat→global (`prompt_composer.py:830-868`), попадает в L2 Writer,
маркер проверяется в финальном system (`direct_chat_service.py:4770-4778`); в проде за 48 ч
`policy_not_injected`/`composer_excluded` = 0 (`plans/owner-obs-diagnostics-2026-10-21.md:13`),
а проба FREQUENT дала `probes=9, mat_roots=0, marker_present_l2=true, class=model_ignored_instruction`
(`plans/features/add-exp/requirements-map.json:488`). Значит «12 проб без различия» объясняются не
потерей слоя, а поведением модели.

**Реальный дефект кода (единственный найденный в пути):** Expression — soft-слой, его можно молча
выбросить по бюджету: `prompt_composer.py:1501-1509` (`skip_reason="budget_excluded"`). Core защищён,
Expression — нет; это скрытая точка потери и ложный «ноль различий».

**Семантика FREQUENT** сейчас: «выраженным использованием мата… привычная часть твоего словаря»
(`mca_expression.py:82-87`). Формулировки зафиксированы 21.10, но новое указание владельца 24.10 (§6.3)
их перекрывает: нужна привычка речи, а не разрешение. Минимальный дифф — правка текста FREQUENT (без
квот, постпроцессора, второго источника настроек) + запрет `budget_excluded` для слоя. Если после этого
на реальном провайдере FREQUENT не отличается от OCCASIONAL по ≥5 подряд пробам — фиксируется как
ограничение модели (§6.4), а не «работает».

## 5. OPS (P0-F, §8)

| Пункт | Класс | Факт |
|---|---|---|
| Betterstack `401` | факт | `system_logs_fetcher.py:109` ловит ошибку → journalctl (`:113-237`); `used_fallback` → приписка (`checkup_service.py:70-71`). Fallback **сработал** |
| Причина 401 | гипотеза | ключ/права/конфиг; не проверена, к фактчеку отношения не имеет |
| `vision claim sweep slow` 7–25 c | предупреждение | в HEAD строки лога нет → нужна фазовая телеметрия; отдельный perf-дефект заводить только после неё (§8) |

## 6. Пересечения и что нельзя дублировать

- ASAP3/Style Policy: один владелец правил оформления; здесь — **подключить** его к не-композерным
  маршрутам, не писать второй hint. Speech R3/R3B: порядок слоёв и профили композера не меняем.
- Embed-identity (`_audit-2026-10-23/embed-*`) и summary L2 review — отдельные дефекты, не переоткрывать.
- Уже сделано, дублировать нельзя: per-claim схема/рендер, provenance-защита, Expression-диагностика,
  `withheld_values()`-витрина, owner-preserving Core patch.

## 7. Риски и порядок
1. **R2 (главный):** `legacy_adopt` может стать лазейкой «благословить любой текст». Защита: жёсткий
   `expect_sha12`, замороженный allowlist, actor/reason, исходник в истории, отказ при несовпадении.
2. **R2:** Core-патч owner-документа — аддитивный, со снапшотом и diff'ом; откат — восстановление снапшота.
   **R1:** удаление пунктов 1–3 из канона Checkup — ступень `PREV_*` + rollback-запись, кастом не трогаем.
3. **R1:** «нерелевантно» как деградация — вердикт остаётся консервативным (positive без evidence запрещён),
   меняется только причина.
4. Порядок: PROMPTS (аттестация) → FACTCHECK (метрики→вердикт→рендер) → CHECKUP/Style → CORE → EXPRESSION.
   Ветки независимы по файлам, кроме `prompt_migrations.py` (точка сериализации) и
   `prompt_composer.py` (стиль-блок + budget).

## 8. Тест-план (существующие контуры)

- **PR-01..03:** adoption идемпотентен; mismatch `expect_sha12` → отказ; после рестарта ревизия действует;
  `withheld_values()` пуст для аттестованных; кастом не перезаписан (сравнение байт).
- **FC-01..09:** пустой EvidenceMap не даёт `refuted`; `AllSearchEnginesFailed` → reason ≠ «нет
  доказательств»; бюджет — отдельный reason; частичный evidence → `parts` с разными вердиктами;
  морфологический кейс (FC-02) проходит фильтр; кеш не скрывает новый вердикт.
- **SP-01..06:** Checkup получает Core+Expression+Style Policy в этом порядке; нет навязанной маленькой
  буквы; Full/Compact не примитивизированы; остальные маршруты сохраняют характер.
- **EX-01..03:** postprocess не вставляет/удаляет мат; `budget_excluded` невозможен для expression;
  ≥5 разнообразных ситуаций × 3 режима на реальном провайдере (иначе — model limitation).
- **OPS-01..02:** Checkup называет 401 фактом, fallback — успехом, причину — гипотезой; Vision sweep
  диагностируется отдельно.

## 9. Что builder'у запрещено менять

Тексты OFF/OCCASIONAL без указания владельца; порядок слоёв и профили композера; схему
`EvidenceRef/EvidenceMap`; порог доказательности; `PROVENANCE_EXEMPT_PREFIXES`; `plans/current_task.md`, карты, `workflow_state.md`.
