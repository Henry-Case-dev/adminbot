# EVOL-REPLY-CONTEXT-INTEGRITY-01 FINAL v5 — замороженный архитектурный контракт

Статус: `ARCHITECT_ADJUSTMENT_REQUIRED` (дизайн владельца реализуем; в коде найдены конкретные точки подмены цели, обязательной медиа-зависимости и выдуманного техстатуса — §1–§3)
Фича: `EVOL-REPLY-CONTEXT-INTEGRITY-01` (FINAL v5)
Ветка сверки: `evol/impl` @ `2cc68a94` (содержит deployed 2.58.153), worktree `…/hotfix-meme-publication-initia-d78f499866ee-6ef91e44`
Источник требований: `plans/owner_inputs/2026-11-03-evol-reply-context-integrity-v5.md` (159 строк, sha `C6AA5CD8…`, извлечён из `plans/current_task.md:5023–5531`)
Внешние источники: **не использовались**. Все решения проверены по фактическому коду и тестам этого worktree; внешних контрактов (провайдеры, лимиты API, версии SDK) ТЗ не затрагивает.
Приоритет: §5.4 / §9.5 (CONTEXT-FIDELITY-01) выше любой оптимизации «чистого вывода».

---

## 0. Итог сверки (три вердикта и один шов)

**0.1. Непрерывность `target_ref` — НЕТ, разорвана в 7 точках.** Явная цель (Reply/forward/quote/медиа) остаётся якорем доставки, но текст Claim уходит от неё трижды: (а) `handlers/factcheck.py:996–1007` подменяет `target_text` найденным «ближайшим» тезисом и помечает публикацию `augmented`, (б) `services/factcheck_orchestrator.py:805–825` подменяет `claim_text` **после** сборки envelope (`:771–788`), поэтому поиск/план идут по одному тексту, а вердикт — по другому, (в) `services/factcheck_planner.py:843` строит поисковые единицы из `decision.claim_items`, которые могут принадлежать **другому автору/сообщению**, чем текст, попавший в вердикт. Плюс: `find_context_claim` ранжирует кандидатов по `abs(tg_id − target)` (`factcheck_suitability.py:595–602`) — прямо запрещённый §4.3 критерий; `_dominant_dispute` (`:441–476`) взвешивает «число ответов» и «длину» — тоже запрещено §4.3.

**0.2. Медиа действительно обязательно на всех текстовых маршрутах.** `resolve_claim_publication(..., allow_adjacent=True)` — это **дефолт сигнатуры** (`factcheck_service.py:694`), поэтому он срабатывает для любой текстовой цели, где нет изображения (`:884–907`). Найденная неоднозначность даёт `media_ambiguous=True` (`:903–907`), а `ClaimPublication.notice()` (`:628–640`) безусловно возвращает «Не понял, какое изображение проверять…», и оно приклеивается к готовому вердикту: `handlers/factcheck.py:263–266, 1164–1167`, `factcheck_orchestrator.py:1087, 1111–1113`. Хуже в v2: `resolve_claim_publication` вызывается без `requester_user_id`/`trigger_tg_message_id` (`orchestrator:753–754`), а `media_readiness._same_author` при неизвестной личности возвращает `True` (`media_readiness.py:427–430`) — то есть **чужое одиночное фото рядом** на v2-маршруте может быть «уверенно» привязано к текстовой цели.

**0.3. Технический статус выдумывается из отсутствия URL.** `classify_retrieval` (`factcheck_service.py:1036–1067`) возвращает `PROCESSING_FAILED` для **любого** `used>0` без evidence (строка `:1063–1064`), не читая `off_topic_sources_dropped`/`stale_sources_dropped`/`fetch_errors`; `PROCESSING_FAILED → source_missing` (`:985`) → заголовок «Проверка не завершена: материалы не удалось разобрать» (`factcheck_renderer.py:75`). То же в envelope-ветке: «внутренний поиск что-то нашёл, но ссылок нет» → `PROCESSING_FAILED` (`factcheck_service.py:1945–1947`). Это нарушает §11.2 п.4/5/6: пустая выдача, нерелевантная выдача и «читаемо, но нечего цитировать» — не поломка парсера.

**0.4. Единый шов речевой проекции — `services/canonical_context.py`** (модуль, который по собственному контракту уже является «единственной точкой рендера строки контекста», `canonical_context.py:1–24, 110–180`). Через него проходит **каждая** строка сообщения/факта во всех пользовательских LLM-payload: Direct (окно/тред/ветка/RAG), FactCheck (широкий фид/узкое окно/цепочка/RAG), tool-результаты, summary-архив, lore, nostalgia. `prompt_composer` швом быть не может — он собирает **system**-слой (`prompt_composer.py:965–988`), а утечка живёт в **user**-части.

---

## 1. FactCheck: непрерывность цели и Claim

### 1.1. Фактический маршрут v1 (handler, `TEMPORAL` ON — прод)

| # | Шаг | Файл:строка | Что происходит с целью |
| --- | --- | --- | --- |
| 1 | Триггер | `handlers/factcheck.py:554–568` (`_parse_trigger`) | `target = message.reply_to_message`; при forward — сам `message`. Target ID фиксируется здесь |
| 2 | Adjacent-цель без Reply | `handlers/factcheck.py:962–974`, `:592–633` | Если Reply/forward нет — ищется **фото** рядом (`resolve_target_media(allow_adjacent=True)`); target подменяется на `_adjacent_target(...)` с `from_user=None`. Явный текстовый тезис в команде (`фактчек: правда ли, что …`) при этом игнорируется — цель становится картинкой (§10.2 «Text-only command without reply» нарушен) |
| 3 | Публикация | `handlers/factcheck.py:992` → `factcheck_service.resolve_claim_publication` (`:683–964`) | Текст/альбом/OCR; `allow_adjacent` не передан → `True` → §0.2 |
| 4 | Пустая/нерелевантная цель | `handlers/factcheck.py:996–1001` → `factcheck_suitability.resolve_context_claim` (`:608–677`) | Ищется «тезис в окружении»: сначала reply-цепочка родителя, иначе `find_context_claim` (расстояние по TG ID) |
| 5 | **Подмена Claim** | `handlers/factcheck.py:1002–1007` | `target_text = probe.claim.text`; `publication` заменяется `dataclasses.replace(..., text=target_text, augmented=True)`. Target ID остаётся прежним, автор/якорь/происхождение найденного текста — только в логе (`:1008–1014`) |
| 6 | Envelope | `handlers/factcheck.py:148–155, 167–168` → `temporal_factcheck.build_envelope` (`:393–530`) | `claim_text` = подменённый текст, `target_tg_message_id` = исходная (пустая) цель → **claim и target расходятся**, даты/происхождение берутся из пустой цели (`:465–488`) |
| 7 | Контекст | `handlers/factcheck.py:192–207` | `<chat_context>` (все строки с `tg:<id>`, `factcheck_context.py:222–228, 261–267`) + `<reply_chains>` (`thread_chain.py:317–330`) + материал медиа |
| 8 | Гейт | `handlers/factcheck.py:1110–1159` | Отказ/уточнение; `decision.claim_items` (с якорями и авторами, `factcheck_suitability.py:680–690`) **не используются** — теряются |
| 9 | Вердикт | `handlers/factcheck.py:1160–1163` / `:243–245` | Тезис = `target_text`; envelope-ветка `check_claim_envelope` **в handler v1 всегда без `retrieval`** → внутренний поиск ветки (`factcheck_service.py:1843–1866`) |
| 10 | Доставка | `handlers/factcheck.py:263–266, 1164–1167` | Reply на `target.message_id` (верно), но к тексту приклеен `publication.notice()` |

### 1.2. Маршрут v2 (`FACTCHECK_PIPELINE_V2` ON)

| # | Шаг | Файл:строка | Разрыв |
| --- | --- | --- | --- |
| 1 | Публикация | `orchestrator.py:752–756` | `resolve_claim_publication(db, chat, target, base_text=req.target_text)` — **без** `trigger_tg_message_id`, `requester_user_id/name` → авторство не проверяется (§0.2) |
| 2 | **Envelope до гейта** | `orchestrator.py:771–788` | Envelope собирается ДО поиска контекстного тезиса |
| 3 | Гейт | `orchestrator.py:793–797` | `claim_text = publication.text` |
| 4 | **Подмена Claim после envelope** | `orchestrator.py:805–825` | `find_context_claim` → `claim_text` заменяется, `decision` пересчитывается, **envelope не пересобирается** → вердикт и verbalizer видят тезис пустой цели (BD-2) |
| 5 | План | `orchestrator.py:1029–1030` → `factcheck_planner.build_retrieval_plan(decision, ctx, claim_text=external_claim)` (`:803–843`) | Поисковые единицы — из `decision.claim_items` (может быть чужое сообщение), `claim` — текущий `claim_text` → третий текст в цепочке (BD-3) |
| 6 | Retrieval | `orchestrator.py:1037–1048` | Поиск по плану; ошибки → `RetrievalOutcome` |
| 7 | Вердикт | `orchestrator.py:1051–1068` | envelope-ветка или legacy (`:1221–1249`, без `factual_verdict`/`reason_code`) |
| 8 | Notice | `orchestrator.py:1087–1095` | `publication.notice()` (медиа) приклеивается к вердикту |
| 9 | Доставка | `orchestrator.py:1111–1113, 1130–1133` | `reply_to = req.target_tg_message_id` |

### 1.3. Отложенное возобновление и tool-маршрут

- Deferred: `orchestrator.py:653–660` — `target_text=""`, `trigger_tg_message_id = target_tg_message_id = id цели`. Публикация резолвится заново (это правильно — «одна правда об OCR»), но `allow_adjacent=True` снова может выставить `media_ambiguous`; `trigger == target` ломает семантику маркера «текущая команда».
- Tool: `tool_router.py:4048–4230` (`_fact_check`). `resolve_claim_publication` **не вызывается** → медиа-неоднозначности на tool-маршруте нет (соответствует §10.3). Но: `claim = reply_text[:300]` (`:4102`) — усечение проверяемого тезиса; и `claim` приходит от LLM, то есть Target может быть пересказом. Это допустимо для tool-ветки, но должно быть видно в трассе как `claim_origin=tool_claim`.

### 1.4. Точки, где цель/тезис сейчас могут быть заменены (заморожённый список)

| ID | Место | Что подменяется | Почему это дефект |
| --- | --- | --- | --- |
| BD-1 | `handlers/factcheck.py:1002–1007` | Claim (текст) | Происхождение/автор найденного текста не попадает ни в envelope, ни в трассу; `publication.augmented=True` маскирует подмену под «расширение публикации» |
| BD-2 | `orchestrator.py:805–825` против `:771–788` | Claim | Поиск и вердикт по разным текстам; §5.3 «Search-план по Claim из Target» нарушен |
| BD-3 | `factcheck_planner.py:843` + `:810–822` | Claim units | План строится по `claim_items` (чужой автор), вердикт — по `claim_text`; §5.3 «каждый Claim привязан к своему фрагменту/автору» |
| BD-4 | `factcheck_suitability.py:595–602` | Выбор антецедента | Ранжирование по `abs(tg − target)` — прямой запрет §4.1/§4.3 |
| BD-5 | `factcheck_suitability.py:453–470` | Выбор антецедента | Вес «число прямых ответов» + «длина текста» — запрещено §4.3 («не выбирать по числу ответов/максимуму слов») |
| BD-6 | `handlers/factcheck.py:962–974` + `:592–633` | Target | Текстовый тезис в команде превращается в фото-цель (§10.2) |
| BD-7 | `handlers/factcheck.py:1045–1062` | Claim | Транскрипция: `target_text = claim` — это законная нормализация (claim из Target), но в трассе нет `claim_origin=transcript` |
| BD-8 | `orchestrator.py:653–660` | Target/trigger | `trigger==target` в deferred-ветке → маркер и `find_context_claim` исключают не то сообщение |
| BD-9 | `tool_router.py:4097–4121` | Claim | Tool-claim усечён до 300 симв. и может быть пересказом LLM; нет `claim_origin` в трассе |

### 1.5. Минимальный набор изменений: одна каноническая цель (заморожено)

**M1. Расширить `ClaimPublication` (не новую сущность), а не создавать `TargetRef`-подсистему.** Аддитивные поля с дефолтами (прецедент `EvidenceRef.claims`):

```python
target_chat_id: int | None = None
target_tg_message_id: int | None = None
target_source: str = "explicit_reply"   # explicit_reply|stored_reply|explicit_quote|
                                        # forward|album|media|command_text|contextual|tool
claim_origin: str = "target_text"       # target_text|target_caption|target_media|
                                        # target_transcript|command_text|reply_parent|
                                        # context_window|adjacent_media|
                                        # tool_claim|external_claim
claim_anchor_tg_message_id: int | None = None   # сообщение, которому принадлежит Claim
claim_anchor_author: str | None = None
claim_anchor_source: str = "literal"    # literal|reply_to|topic|quote|media
text_sufficient: bool = False           # есть самостоятельный проверяемый текст
association_attempted: bool = False     # §10.3 typed media-reasoning
association_status: str = ""            # resolved|ambiguous|missing|not_attempted
association_reason: str = ""
association_candidates: tuple[int, ...] = ()
```

`target_tg_message_id`/`target_source` заполняются в `_resolve_publication` (handler) и в `_run_inner` (v2) из фактических данных, а не из пересказа.

**M2. Единственная допустимая подмена — `contextual`-цель, и она объявляется.** Правило:

```text
explicit target (reply/forward/quote/album/media/command_text)  -> target_ref НЕ меняется
если у explicit target НЕТ текста и НЕТ медиа-материала
    -> target_source="contextual", target_tg_message_id = claim_anchor (= выбранное сообщение),
       delivery_reply_to = trigger
```

Это одна развилка на оба маршрута: в handler `:1002–1007` и в `orchestrator:805–825` вместо «тихой» замены текста выполняется `publication = dataclasses.replace(publication, text=..., claim_origin="context_window", claim_anchor_*=..., target_source="contextual", target_tg_message_id=anchor, text_sufficient=True)`, а `Envelope` строится **после** этого (в v2 — перенос `build_envelope` ниже гейта; в v1 — уже после, там только передать анкор в `InputRef`).

**M3. Envelope и вердикт всегда от одного текста.** В `InputRef`/`build_envelope` (`temporal_factcheck.py:249–262, 393–530`) аддитивно передаётся `claim_anchor_tg_message_id`; при `claim_anchor != target` даты/attribution берутся из анкора, а `target_tg_message_id` = эффективная цель (M2). Инвариант: `envelope.claim_text == publication.text` и `envelope.target_tg_message_id == publication.target_tg_message_id`.

**M4. Ранжирование антецедентов без запрещённых критериев.** `find_context_claim` (`factcheck_suitability.py:576–605`):
1) кандидаты из структурной цепочки (reply/quote/forward относительно target/trigger) — приоритет 1;
2) затем семантические кандидаты существующим `_dispute_scores` (`:410–438`) по стеммам target+hint;
3) `tg_id`-близость — только tie-break при равенстве семантического счёта;
4) неоднозначность → `None` (→ уточнение), а не «первый ближайший».
«Ближайшее по TG ID» перестаёт быть правилом выбора, остаётся детерминированным разрешением ничьей.

**M5. `_dominant_dispute` — без «шумовых» весов.** Убрать `replies_to * 1.5` и `len(tokens)/20` (`:453–470`); оставить дискуссионные маркеры + `_claim_like_text`/`_has_predicate`, сохранив проверку неоднозначности (`top/second`) и порог `2.0`. Это исполняет §4.3 дословно и не убирает существующую функциональность (для «ну и что там?» остаются маркеры спора).

**M6. Привязка Claim к автору доходит до трассы и до плана.** `SuitabilityDecision.claim_items` уже несут `anchor_tg_message_id/anchor_chat_id/author` (`:166–177`); добавить их в `claim_selection`-событие (§7) и в `ClaimUnit.claim_id → anchor` map, которую planner кладёт в `RetrievalPlan` (аддитивное поле). Тогда `claim_coverage` в вердикте показывает, что проверялась часть, принадлежащая конкретному сообщению.

**M7. `claim_origin` во всех точках.** `target_transcript` (BD-7), `tool_claim` (BD-9), `context_window` (M2), `adjacent_media` (adjacent-цель). Без этого §7 (`claim_selection`) недоказуем.

Инварианты контракта:

```text
I1  target_tg_message_id explicit-цели неизменяем на всём маршруте.
I2  Claim всегда имеет claim_origin и claim_anchor (кроме literal-цели с пустым анкором).
I3  envelope.claim_text == publication.text, envelope.target_* == publication.target_*.
I4  План, поиск, вердикт и verbalizer получают ОДИН и тот же набор claim-единиц
    с их анкорами; смена текста после сборки плана запрещена.
I5  Доставка Reply — реальный Telegram ID (target при explicit, trigger при contextual).
```

---

## 2. Медиа: обязательно только при реальной зависимости (FC-MEDIA-OPTIONAL-01)

### 2.1. Где реально течёт `allow_adjacent`/`media_ambiguous`

| Маршрут | Вызов | `allow_adjacent` | `media_ambiguous` попадает в текст |
| --- | --- | --- | --- |
| handler v1 | `handlers/factcheck.py:704–715` | не передан → `True` (`factcheck_service.py:694`) | да: `:263–266`, `:1164–1167` через `_with_publication_notice` (`:799–806`); отдельно `_empty_content_phrase:756–759` |
| handler «нет Reply» | `handlers/factcheck.py:603–608` | явный `True` | да: `:970–972` (уточнение) — законно, цели-текста нет |
| v2 orchestrator | `orchestrator.py:753–754` | не передан → `True`, **без автора/триггера** | да: `:1087` → `:1111–1113` |
| deferred resume | `orchestrator.py:659` → `:753` | `True` | да (повторно) |
| tool | `tool_router.py:4048+` | не используется | нет (соответствует §10.3) |

Сама неоднозначность формируется в `factcheck_service.py:884–907`; «несколько кандидатов» и «чужое фото» приходят из `media_readiness.resolve_target_media:551–611` + `_same_author:410–433`.

### 2.2. Минимальное изменение условия (одна точка + два вызова)

**M8. Один предикат достаточности текста** (переиспользует существующие предикаты, без нового классификатора):

```python
def text_target_sufficient(text: str) -> bool:
    return bool(text) and not _COMMAND_TEXT_RE.match(text) \
        and not is_conservatively_irrelevant(text) \
        and has_checkable_core(text)          # factcheck_suitability
```

`text` = текст самой публикации **до** материала изображений (`publication.caption_text`).

**M9. Условие в резолвере** (`factcheck_service.py:884`):

```python
if (allow_adjacent and db is not None and chat_id is not None
        and not expected_ids and not hint_image
        and not text_target_sufficient(caption_text or base)):
```

Это одна строка условия + один предикат. Покрывает **все** маршруты, потому что handler v1, v2, deferred и tool-ветка (для tool не вызывается) идут через один резолвер.

**M10. `media_ambiguous` — typed и условный.** `ClaimPublication.notice()` (`:628–640`) выдаёт медиа-фразу только если `media_ambiguous` (уже) и `media_dependency() != "none"`; при M9 в этом состоянии `media_ambiguous` просто не выставляется для достаточного текста. Дополнительно `notice()` не должен смешивать media и evidence status — см. §3.2 ES-5.

**M11. Авторство на v2.** `orchestrator.py:753` передаёт `trigger_tg_message_id=req.trigger_tg_message_id`, `requester_user_id/name` — те же данные, что handler (`handlers/factcheck.py:710–714`). Без этого `_same_author` при неизвестной личности возвращает `True` (`media_readiness.py:427–430`), и «чужое фото» приписывается цели.

**M12. Команда с явным тезисом не становится фото-целью.** `_adjacent_target_or_ambiguous` вызывается только когда `user_hint` не содержит проверяемого ядра:

```python
if target is None and not (user_hint and has_checkable_core(user_hint)):
    target, ambiguous = await _adjacent_target_or_ambiguous(message)
```

При найденном ядре цель = `message` (текст команды), `claim_origin="command_text"` (§10.2 «Text-only command without reply»).

Инварианты:

```text
I6  Отсутствие изображения у текстовой цели НИКОГДА не запускает поиск соседних картинок.
I7  media_ambiguous существует только при отсутствии самостоятельного текстового тезиса.
I8  Сильные связи (media_group_id, вложение, reply/quote на медиа, альбом) работают как сейчас:
    они не «соседство» и M9 их не затрагивает.
I9  Для команды с явным тезисом медиа опционально, даже если рядом есть фото (§10.2, сц. 33).
```

---

## 3. Честные техстатусы (FC-EVIDENCE-STATUS-01)

### 3.1. Реальный путь «retrieval → reason-code → заголовок»

```text
factcheck_planner.run_retrieval (:1380–1684)
  -> counters{attempted,used,empty,irrelevant,provider_failures,fetch_errors}
  -> _ClaimRun{attempts,provider_failed,deadline_hit,fetch_failed,bound}
  -> _finalize_claim (:1292–1377): status_detail = verified|partial|conflicting|
       refuted|exact_number|no_relevant_sources|deadline|provider_error|
       source_extract_failed|search_not_started|claim_unidentified
  -> RetrievalOutcome (:1111–1173)
factcheck_service.check_claim_envelope (:1900–1957)
  -> classify_retrieval -> _RETRIEVAL_REASON (:982–988) -> verdict.reason
factcheck_renderer._content (:236–282)
  -> _TECHNICAL_HEADLINE[reason] | _VERDICT_HEADLINE[factual_verdict] | _technical_headline_from_parts
  -> _TECHNICAL_NOTICE / _NO_LINKS_NOTICE
```

### 3.2. Где причина изобретается (2 точки: ES-1, ES-2) + сопутствующее

| ID | Место | Сейчас | Требуется по §11.2 |
| --- | --- | --- | --- |
| ES-1 | `factcheck_service.py:1063–1064` | `used>0 → PROCESSING_FAILED` (→ `source_missing` → «материалы не удалось разобрать») | Технический статус — **только** при реальном `fetch_errors>0`; иначе «нет подходящих/цитируемых материалов» (п.4/5/6) |
| ES-2 | `factcheck_service.py:1945–1947` | «внутренний поиск что-то нашёл, ссылок нет» → `PROCESSING_FAILED` | То же: `NO_RESULTS` + честная оговорка о цитируемости (п.6) |
| ES-3 | `factcheck_planner.py:1578–1599` | Пропуск fetch по дедлайну **не считается** (нет счётчика) → возможен молчаливый пропуск | Типизированный `fetch_skipped_deadline` в трассе; он не превращается в `source_extract_failed` (п.2: назвать прерванную стадию) |
| ES-4 | `factcheck_orchestrator.py:1088–1095` | `_RETRIEVAL_NO_CITABLE_NOTICE` только при `reason_code is None` | Оговорка нужна и при `insufficient_evidence` (это не техсбой) |
| ES-5 | `orchestrator.py:1087` + `ClaimPublication.notice()` | media-уведомление смешано с evidence-ограничением в одну строку `notice` | Продюсер решает, **какая** причина относится к этому прогону (после M9 media-ветка просто не срабатывает при достаточном тексте); схема `FactcheckPresentation` не меняется |
| ES-6 | `factcheck_renderer._content:245–252` + `factcheck_service.py:2015–2017` | Приоритет техзаголовка по `reason_code` над частями существует **в renderer**, но в envelope-ветке он нейтрализован: при наличии evidence `retrieval_state=OK` (`:1941–1942`), а при пустом evidence техпричина снимается для содержательного вердикта (`:2015–2017`). **Дефект не доказан**; требуется закрепить тестом (смешанный прогон → заголовок не противоречит успешной части) | Если тест покажет расхождение — подавлять техзаголовок тем же `_part_is_substantive` |

### 3.3. Минимальная нормализация без новых enum

Нужен точный порядок условий; маршруты различаются источником класса: v2 отдаёт `RetrievalOutcome` (ES-1), v1 handler envelope-ветку вызывает без `retrieval` (`handlers/factcheck.py:243–245`), поэтому там работает только ES-2.

`classify_retrieval` — новый порядок:

```text
refs -> ok
budget_exhausted and used==0            -> BUDGET            (deadline_exceeded)
used==0 and (empty>0 or irrelevant>0)   -> NO_RESULTS        (insufficient_evidence)
used==0 and (attempted>0 or failures>0) -> SEARCH_FAILED     (provider_unavailable)
used>0  and fetch_errors>0              -> PROCESSING_FAILED (source_missing)   # только реальная ошибка парсинга
used>0                                  -> NO_RESULTS        (insufficient_evidence)
иначе                                   -> INSUFFICIENT      (insufficient_evidence)
```

Envelope-ветка (`:1941–1955`): «results есть, evidence нет» → `NO_RESULTS` вместо `PROCESSING_FAILED`.

Матрица §11.2 покрывается существующими значениями:

| §11.2 | Класс/статус | Заголовок |
| --- | --- | --- |
| 1 провайдер недоступен | `SEARCH_FAILED` → `provider_unavailable` | «поиск недоступен» |
| 2 дедлайн | `BUDGET` → `deadline_exceeded` + `fetch_skipped_deadline` | «истёк лимит времени» (+ стадия в трассе) |
| 3 парсер реально упал | `fetch_errors>0` → `source_missing` / `source_extract_failed` | «материалы не удалось разобрать» |
| 4 пустая выдача | `NO_RESULTS` (`empty_results>0`) | «Недостаточно данных» + оговорка о выдаче |
| 5 нерелевантно | `NO_RESULTS` (`off_topic>0`/`stale>0`) | «Недостаточно данных» (не техсбой) |
| 6 читаемо, но нечего цитировать | `NO_RESULTS` (`refs_collected==0`, `search_text`) | «Недостаточно данных» + `_RETRIEVAL_NO_CITABLE_NOTICE` |
| 7 достаточно для условного разбора | `INSUFFICIENT` + содержательный вердикт | без техзаголовка (`:2015–2017` уже так) |
| 8 смешанный прогон | `_technical_headline_from_parts` (`renderer:316–330`) + снятие техпричины (`service:2015–2017`) | заголовок из вердикта; техпричины — в частях и трассе. **Закрепить тестом** (ES-6) |
| 9 vision pending/failed | `ClaimMediaMaterial.image_unchecked/vision_failed` + `media_dependency` | только при реальной media-зависимости (M9/M10) |

Инвариант: `technical_reason` в трассе берётся из фактических счётчиков стадии, а не из «нет URL»; `final_headline_code` пишется в событие прогона (§11.3).

---

## 4. Речевая граница (GLOBAL-OUTPUT-BOUNDARY-01)

### 4.1. Полный инвентарь путей, порождающих пользовательский текст

| # | Путь | Сборка payload | Что попадает в речь сейчас |
| --- | --- | --- | --- |
| P1 | Direct, обычный ответ + ответ на Reply | `direct_chat_service._compose_user_content:8199+` → блоки `Global_Context` (`:8440`), `Conversation_Thread` (`:11728–11766`), `Conversation_Branch` (`:11768+`), `Episode`, `RAG_Memory` (`:11367`) | `_context_row_line:11659–11676` → `[ts \| Имя [uid] \| tg:1234]: текст`; `_chain_line:11704–11710` → `thread_chain.format_chain_line:285–314` (`tg:` + `цитата (автор: <uid>)` числом, `:273–275`); RAG: `summary_memory._format_origin_labeled_line:1771–1799` → `\| fact:ID`/`\| tg:ID`; медиа-строка `[медиа: video tg:123]` (`media_marker.py:77–101`) |
| P2 | Текстовая инициатива | `initiative_observer._act_on_opportunity:2197+` → `handle_initiative` (тот же Direct L1/L2) | тот же контекст, что P1; плюс `build_eval_user_prompt:928–965` подаёт `[msg:N] [user:N] (ответ на msg:N)` — машине это нужно, но `goal`/`rationale` модели затем едут в Writer как текст |
| P3 | FactCheck Writer/renderer | `factcheck_context.render_feed:186–207` (digest `:215–250`, verbatim `:253–292`), `chat_context.format_chat_context:73–160` (узкое окно), `thread_chain.render_reply_chains:317–330`, RAG в `check_claim:1496–1507` | `tg:<id>` в каждой строке; `цитата (автор: <uid>)`; `fact:`/`tg:` в RAG-префиксе; всё это попадает в `<claim>/<chat_context>/<evidence>` analyst-payload (`factcheck_service._temporal_user_payload:2123–2177`), а оттуда — в `parts[].text` и в публикацию |
| P4 | Memory / RAG / GraphRAG | `summary_memory.build_rag_context:1802–1853` (`<context><user_gossip>…`), `lore_compiler_service:267–320`, `nostalgia_prompts`, `video_web_summary` | `[ММ.ГГГГ \| Автор \| tg:ID]`, `fact:ID` |
| P5 | Результаты инструментов | `tool_router._format_rows:4829–4854`, `query_chat_memory:2169/2223`, `dig_into_lore:2127–2132`, `get_recent_history`; `_fact_check` JSON (`:4227+`) | канонические строки с `tg:` возвращаются агенту и пересказываются в ответе |
| P6 | Саммари / история | `summary_generator` архив `format_context_item(kind="archive")` (`:4327–4331`), `summary_xml` (`id="…"` — структурный атрибут, ок) | `tg:` в архивных строках |
| P7 | Мем / картинка | `meme_initiative._default_summarize:2976–2987` | JSON `{"id": <внутр. id>, "text": …}` → шутка может воспроизвести число; `render_image_prompt` кладёт шутку в изображение |

### 4.2. Выбранный шов: одна структура — две проекции в `canonical_context`

`services/canonical_context.py` уже объявлен «единственной точкой рендера строки контекста» и держит реестр `CONTEXT_POINTS` (`:110–180`), из которого генерируется инвентарный тест «нет голого текста». Шов добавляется **в этот же модуль** — нового сервиса/движка нет:

```python
@dataclasses.dataclass
class SpeechProjection:
    """Проекция одного прогона: label -> реальный идентификатор (обратная карта)."""
    run_id: str
    representation: str = "writer"          # writer | internal | explicit_admin_diagnostic
    _msg: dict[str, str] = field(default_factory=dict)   # "M7" -> "tg:1234"/"msg:9"/"fact:4"
    _rev: dict[str, str] = field(default_factory=dict)
    _people: dict[str, str] = field(default_factory=dict)  # "U3" -> user_id
    _people_rev: dict[str, str] = ...

    def message_label(self, item_id: str) -> str        # стабильно в рамках прогона
    def person_label(self, user_id, display_name: str) -> str   # "Имя (U3)"
    def raw_of(self, label: str) -> str | None          # диагностика/адресация
    def manifest(self) -> dict                          # для run-манифеста
```

Правила (заморожено):

1. **Машинная сторона не меняется.** `resolve_item_id` (`:239–249`) продолжает возвращать `tg:/msg:/fact:`; `format_context_item` (`:252–295`) остаётся сырым рендером по умолчанию — его используют L1/планировщик/retrieval/dedup/attribution, которым нужны настоящие ID (§5.4 прямо разрешает типизированные refs специализированным стадиям).
2. **Речевая сторона — новый вызов** `format_speech_item(..., projection=...)` + `render_speech_line(...)`; `media_marker.media_marker(..., projection=...)` (или `label` вместо `ref`). Ни один модуль не строит свою проекцию.
3. **Метки**: `M1..Mn` для сообщений (нумерация по хронологии прогона), `U1..Un` для участников (по первому появлению). Метки — **адресная разметка**, не часть реплики: они стоят в заголовке строки и в явных отношениях, никогда внутри цитируемого текста.
4. **Явные отношения вместо выводимых из порядка** (§5.4 «кому и на что»):
   - `…]: (цель проверки) текст` — роль target;
   - `↳ отвечает на M3 (Telegram Reply)` — только при подтверждённом `reply_to_id`;
   - `↳ относится к теме M3 (семантическая связь, не Reply)` — только при подтверждённом семантическом основании;
   - `↳ родитель вне доступного окна (связь известна, сообщение не извлечено)` — `missing_edge`, без выдуманного ID (§8);
   - `цитата (автор: Имя (U1)): «…»` — вместо числового `quote_author_id`;
   - `Переслано: X` — сохраняется как сейчас (`format_context_item:287–288`);
   - абсолютные даты/время — сохраняются (`_fmt_ts:218–236`), не заменяются порядком в массиве.
5. **Обратная карта живёт ровно один прогон**, хранится в run-манифесте (`prompt_composer` для Direct/инициативы, `tf.stage_event`/`usage_events` для FactCheck). В манифест — только пары `label → tg_id` / `label → user_id` и счётчики, **без текстов** (§7 «логи — ID, коды»). Доставка Reply и URL-ссылки по-прежнему используют реальные ID из handler'а (`handlers/direct_chat.py:290+`, `handlers/factcheck.py:263–266`), обратная карта для этого не требуется.
6. **Диагностика**: `explicit_admin_diagnostic` — тот же `format_context_item` (сырой), доступный по существующему RBAC-каналу; это роль/канал, а не исключение «для всех» (§9.3 п.3).

### 4.3. Как именно сейчас образуется утечка (доказательство по коду)

- `services/direct_chat_service.py:11669–11676` (`_context_row_line`) → `format_context_item(item_id=resolve_item_id(tg_message_id=...))` → заголовок `[30.04.2024 18:00 | вася [10] | tg:1194297]: …`. Это единственное место в Direct-истории, где номер сообщения стоит рядом с текстом реплики, — именно такие числа и были названы в речи.
- `services/thread_chain.py:285–314` + `:268–282`: `tg:<id>` в заголовке хода **и** `цитата (автор: <число>)` внутри тела (тело = «слова участника» по позиции, что и есть нарушение §9.2).
- `services/media_marker.py:77–86`: `[медиа: video tg:123]` — реф в теле, не в заголовке.
- `services/factcheck_context.py:222–228` и `:261–267`: те же `tg:` в `<chat_context>` FactCheck (путь в `parts[].text` → публикация).
- `services/summary_memory.py:1791–1796`: `| fact:ID` / `| tg:ID` в RAG-строке.

Перечисленные пять мест — полный набор источников «служебного ключа в речевом контексте»; остальное (`query_chat_memory`, `dig_into_lore`, archive, lore) идёт через те же `format_context_item`/`format_fact_line`/`media_marker`.

### 4.4. Что обязано остаться (CONTEXT-FIDELITY-01, §9.5)

Проекция не имеет права: свести историю к `speaker: text`; потерять `reply_to`/quote/forward; заменить абсолютные даты порядком; свести одноимённых участников к одному человеку (для этого и нужны `U`-метки); потерять алиасы (резолв — существующий `aliases.resolve`/`row_speaker`, `direct_chat_service:11650–11657`, `thread_chain._default_row_speaker:84–89`, без новых схем идентичности); потерять provenance (`Переслано:`, `fact:`-происхождение — в речь не идёт, но в структуре остаётся); спрятать таблицу отношений от L1/Observer (у них сырой вид).

### 4.5. Наблюдаемость (§9.4)

- `prompt_composer.compose_speech_system` получает аддитивный `context_representation: str = "internal"` и пишет его в `PromptManifest` рядом с `user_parts` — манифест уже эмитится (`:965–988`, `emit_layer_events`). Значения: `internal` | `writer` | `explicit_admin_diagnostic`.
- FactCheck: `tf.stage_event("speech_projection", "success", reason_code=<representation>, chat_id=...)` + `speech_manifest` в run-манифесте: `{representation, labels: n, suppressed_field_types: ["tg_id","msg_id","fact_id","user_id","trace_id"]}` — только типы/счётчики.
- Запрещено писать `not_exposed`, если фактический payload всё ещё содержит внутренний ID в свободном тексте (§9.3 п.7): манифест пишет то, что реально ушло.

---

## 5. CONTEXT-FIDELITY: обязательства по проверке

### 5.1. Эквивалентность «структура → payload → публикация» (для Reviewer)

Один и тот же вход, три границы:

| Проверка | Как | Провал = P0 |
| --- | --- | --- |
| E1. Внутренняя структура | `ConversationContext.messages` / `publication` / `ChainItem`: автор, `reply_to_tg_id`, `timestamp`, `forward_source`, роль | — (эталон) |
| E2. Фактический payload | Перехват `prompt_composer.record_provider_call`/`last_provider_call` (`:2282–2377`) для Direct/инициативы; для FactCheck — фактический `user_payload` аналитика (`factcheck_service:1981–1990`) и `messages` вербализатора (`:2336–2340`) | В payload нет какого-то отношения, которое есть в E1 |
| E3. Обратное отображение | Все метки из E2 разрешаются через `SpeechProjection.raw_of`/`manifest` в **реальные** `tg_id`/`user_id`; множества совпадают с E1 | Метка без обратного отображения; два участника слиты в одну метку |
| E4. Публичный текст | Извлечь из ответа все числовые токены; ни один не равен `tg_id`/`user_id`/`fact_id` из E1/E2 (при отсутствии явного запроса) | Голое число из metadata в речи |
| E5. Содержательные числа | Число/дата/версия из пользовательского текста присутствуют в ответе | Массовая зачистка цифр |
| E6. Composer ON/OFF | Обе ветки: E2–E4 одинаковы по составу отношений | Потеря связи в fallback |
| E7. Fallback-репак | `_dx.build_l2_fallback_adapter` (`direct_chat_service:7136`): цель, адресные связи, обязательные источники на месте | Урезанный payload теряет цель/связи |
| E8. Рестарт | Новый процесс, кеши очищены (`factcheck_context.WIDE_CONTEXT_VERSION`, кеш среза) — E1 собирается из БД и E2 восстанавливается | Зависимость от меток прошлого хода |
| E9. Маршруты FactCheck | v1 handler, v2 orchestrator, deferred resume, tool — все четыре дают одинаковый `target_ref`/`claim_origin` и одинаковый состав связей | Расхождение маршрутов |
| E10. Два чата / два одинаковых ника / два алиаса | §13 сц. 12, 25, 97, 98: `U`-метки различают людей, сообщения не смешиваются | Слияние субъектов |

Обязательные P0-провалы (§9.5 п.1–6): плоский `speaker: text`; потерянный reply-край; потерянная абсолютная дата/таймзона; потерянный алиас/склейка одноимённых; потерянный provenance (`Переслано`, `fact:`-основание, автор цитаты); метка без обратной карты; «no_evidence» при наличии материалов; добавление нового LLM-вызова/перегенерации/regex-чистки.

### 5.2. Отдельные свидетельства, которые обязаны существовать

- `trace-factcheck-target.txt`: `trigger → target_resolution(source) → claim_origin/anchor → plan claim_ids → retrieval counts → verdict.reason → headline_code → delivery.reply_to`.
- `trace-speech-projection.<route>.txt`: 20–50 строк payload с метками + `speech_manifest` (label↔id) + финальный текст.
- Payload-файлы: Direct L2 (Composer ON/OFF), FactCheck analyst (v1/v2), FactCheck verbalizer, tool-ветка.
- Диагностика: `target_kind`, `media_expected`, `media_dependency_source`, `association_attempted/status/reason`, `media_notice_emitted/reason`, `text_claim_resolved`, `source_query_count`, `provider_attempts/failures`, `documents_retrieved`, `extract_attempts/successes/failures`, `relevant_evidence_count`, `citable_evidence_count`, `technical_reason`, `media_state`, `final_headline_code` (§10.3/§11.3). Неизвестное — «нет данных», не нули.

---

## 6. Границы записи и параллельная безопасность

### 6.1. Владение регионами

| Регион | Файл:строки (HEAD) | Владелец |
| --- | --- | --- |
| Проекция/метки/relation-рендер | `services/canonical_context.py` (новый блок после `:295`), `services/media_marker.py:77–101`, `services/thread_chain.py:268–314` | **Lane A** (сериализована первой, все зависят) |
| Direct-поверхности | `services/direct_chat_service.py`: `:8199–8460` (`_compose_user_content`, dedup `:8408–8427`), `:8642–8677`, `:11226–11367`, `:11650–11676`, `:11704–11710` | **Lane B** (после A) |
| FactCheck цель/медиа | `handlers/factcheck.py:962–1007`, `:592–633`; `services/factcheck_service.py:601–964`; `services/factcheck_orchestrator.py:736–1155`; `services/factcheck_suitability.py:441–605, 680–747`; `services/media_readiness.py` (только чтение) | **Lane C** (после A; независима от D по регионам) |
| Evidence status | `services/factcheck_planner.py:1260–1377, 1578–1684`; `services/factcheck_service.py:967–1067, 1900–1957`; `services/factcheck_renderer.py:62–129, 236–330` | **Lane D** |
| Прочие речевые поверхности | `services/tool_router.py:4829–4854`; `services/summary_memory.py:1771–1853`; `services/initiative_observer.py:928–983`; `services/meme_initiative.py:2976–2987`; `services/lore_compiler_service.py:267–320` | **Lane E** (после A) |
| Наблюдаемость | `services/prompt_composer.py:965–1055` (+ поле манифеста), события `mca_events` (аддитивные имена) | **Lane F** |

### 6.2. Классификация

```text
Lane A: SERIALIZE                 (общий контракт проекции; блокирует B/C/E)
Lane B: BLOCKED_BY:A              (direct_chat_service.py — общий горячий файл)
Lane C: PARALLEL_SAFE c D         (разные регионы factcheck_service.py: 601–964 vs 967–1067/1900–1957)
Lane D: PARALLEL_SAFE c C
Lane E: BLOCKED_BY:A              (каждый файл — один владелец)
Lane F: SERIALIZE                 (prompt_composer.py — общий для SOUL/Direct)
Тесты: READ_ONLY_PARALLEL          (каждый лейн пишет свои файлы tests/)
plans/** (этот документ, карты): READ_ONLY_PARALLEL
```

**Не трогать одновременно с другими лейнами:** `services/direct_chat_service.py`, `services/prompt_composer.py`, `services/factcheck_service.py`, `services/tool_router.py`, `config/settings.py`, схема БД (`services/database.py`). Флаги отката — существующие (`flags.factcheck_pipeline_v2`, `flags.factcheck_suitability_gate`, `flags.factcheck_wide_context`, `NATIVE_REPLY_MEDIA_CONTEXT_ENABLED`); новый рубильник нужен **один** — `flags.context_speech_projection` (hot, default ON, откат без рестарта), потому что изменение формата контекста — самое широкое.

### 6.3. Порядок интеграции

```text
A -> (B, E, F параллельно) -> C -> D -> сквозные тесты E1–E10 -> merge
```
C и D — на одной ветке последовательно, если один автор: оба меняют `factcheck_service.py`.

---

## 7. Стоимость, риск и тесты, которые придётся менять осознанно

### 7.1. Риск семантической регрессии

| Риск | Где | Мера |
| --- | --- | --- |
| R1. Потеря машинных refs в L1/планировщике → ломается attribution/dedup | `direct_chat_service:8906–8935` (`tg:`/`fact:` → `resolve_source_ref_ids`), `claim_envelope.parse_finding_identity:585–651`, `social_turn_frame._refs_from_branch:159–174`, `summary_generator._chain_tg_id:289–296`, `target_marking.is_target_item_id:70–83` | L1/Observer/retrieval **остаются на сыром виде** (§5.4). Проекция применяется только к Writer/публикации. Проверяется тестом «L1 payload содержит типизированные refs» |
| R2. Ломается дедуп middle↔tail | `direct_chat_service:8417–8427` (`re.findall(r"tg:(\d+)")`) | Дедуп переводится на структурный ключ: та же `SpeechProjection` даёт `label_of(tg_id)`; при сыром виде — прежний путь. Тест на дубль |
| R3. L1-находки с refs попадают в Writer как текст | `plan_block`, `<Tool_Evidence>` | Трансляция ref→метка на сборке **структурно** (`_tg_id_of_ref:882–890` уже есть), без regex по готовому тексту; ref вне проекции → «реплика вне доступного окна» (честно) |
| R4. Медиа-опциональность отключает реальный Vision | `resolve_claim_publication:926–935` | M9 меняет только ветку «соседнее фото»; `expected_ids`/`hint_image`/`media_group_id`/reply-медиа не затрагиваются. Тесты 34–43 §13 |
| R5. Статусы «смягчились» и скрывают реальный сбой | `classify_retrieval` | Тест, что `fetch_errors>0` → `source_missing` и техзаголовок остаётся; «нет подходящих» никогда не печатает «не удалось разобрать» и наоборот |
| R6. Метки усложняют модели адресацию | payload | Отношения печатаются явно (`↳ отвечает на M3`), роль цели помечена, время абсолютное. Тест E2/E3 проверяет, что модель может ответить «кто кому и когда» (§13 сц. 115) |
| R7. Рост payload | — | Метка короче `tg:1194297`; новых бюджетов нет (запрещено). Ожидаемое изменение размера ≤ 0 |

### 7.2. Тесты, которые фиксируют текущий «шумный» формат (менять осознанно)

Все они утверждают `tg:`/`fact:`/числовой `uid` **в речевом** контексте. Основание для правки — §5.4/§9.5 (не «чтобы позеленело»).

| Файл:строка | Что фиксирует | Действие |
| --- | --- | --- |
| `tests/test_direct_chat.py:622–638, 878–880, 948–955, 977–991` | `Conversation_Thread/Branch` строки `вася [10] \| tg:100` | перевести на метки + проверить relation-клаузу `↳ отвечает на M…` |
| `tests/test_direct_chat.py:532, 574, 685` | заголовки `[ts \| вася [10]]:` (uid в речи) | `Имя (U1)` либо отсутствие uid |
| `tests/test_direct_context_composer_asap3.py:475, 508` | tail/episode `[100 \| Вася [10] \| tg:5]` | метки; фикстуры — по факту payload |
| `tests/test_direct_context_composer_asap3.py:166–168, 468` | `<Target_User>Вася [10]</Target_User>` | `<Target_User>Вася (U1)</Target_User>` либо имя без uid (решить один раз и зафиксировать) |
| `tests/test_factcheck_context_cfg06.py:195` | `assert f"tg:{TARGET_TG}" in feed` | `label` + `projection.raw_of(label) == f"tg:{TARGET_TG}"` |
| `tests/test_factcheck_deep_context_round1023.py:140–156, 330–345, 651–653` | feed/chain строки с `tg:1/5/6/9` | метки; отдельный ассерт на обратную карту |
| `tests/test_evol015_quote_pipeline.py:291–295` | паритет `format_chain_line` ↔ `format_context_item` | паритет сохранить для **сырого** вида; для речевого — новый ассерт (метка + `цитата (автор: Имя (U1))`) |
| `tests/test_mca07_retrieval_context_round1027.py:691` | `<Conversation_Branch>\n[… \| вася \| tg:N]: ок` | метки |
| `tests/test_native_reply_media_context_round1024.py:109` | `[медиа: video tg:123]` в теле | `[медиа: video M7]` (или маркер без ref в речевом виде) |
| `tests/test_target_marking_round1023.py:162–183` | маркер на канонической строке | маркер должен остаться; строку перевести на метку |
| `tests/test_memory_core_round1020.py:320–364` | `thread_chain.format_chain_line`/`chat_context` канон с `tg:` | сырой вид — оставить как есть (эти функции остаются сырыми), речевой — новый тест; **проверить**, не тестируют ли они speech-поверхность |
| `tests/test_factcheck_p0_fc.py:618–635` | `used=1, refs=0, off-topic текст` → `source_missing` + «материалы не удалось разобрать» | **обязательно изменить**: это и есть §11.2 п.5 → `NO_RESULTS`, «Недостаточно данных» + честная оговорка о цитируемости |
| `tests/test_evol_factcheck_critical.py:380` | техзаголовок для `source_extract_failed` | оставить, если фикстура даёт реальный `fetch_errors>0`; иначе — привести фикстуру к реальному сбою |
| `tests/test_evol_vision_sync_core.py:951–976` | `media_ambiguous` для команды без тезиса | **оставить** (законно, §10.2 «Unbound фактчек after media») + добавить обратный кейс: достаточный текст → `media_ambiguous is False` |
| `tests/test_asap5_integration_w3.py:919–1030`, `tests/test_factcheck_media_2026_10_25.py` | соседние медиа/альбом | проверить, нет ли ожиданий «adjacent для текстовой цели»; при наличии — изменить по §10.2 |
| инвентарный тест `CONTEXT_POINTS` (per-point «нет голого текста») | генерируется из `canonical_context.py:110–180` | расширить реестр полем `speech_representation` + второй генератор «в речевом payload нет `tg:/msg:/fact:` и голого uid» |

Отдельно: `tests/test_history_pages.py`, `tests/test_lore_compiler_round1020.py:112`, `tests/test_memory_lookup_round1026.py:484`, `tests/test_asap8_f7_stories.py:98` используют **машинные** refs (`source_id`, `message_keys`) — их менять не нужно, они защищают правильную часть контракта.

---

## 8. Где ТЗ нельзя выполнить без более крупного изменения (честно)

1. **Разделение media-status и evidence-status на публичном DTO.** `FactcheckPresentation`/`CheckedVerdict` заморожены контрактом W3 (`factcheck_renderer.py:32–33`, `factcheck_orchestrator.py:111`). Полное типизированное разделение (два поля `notice`) — это bump схемы и ревизия W4/W5. Обходимся продюсерской стороной (§3.2 ES-5): медиа-оговорка не формируется, когда её нет; evidence-оговорка выбирается по `reason_code`. Если Reviewer потребует именно два поля в DTO — это отдельное решение о смене замороженной схемы, не «мелкая правка».
2. **Один `retrieval_state` не описывает смешанный прогон.** `retrieval_state` до вербализатора действительно доходит (`factcheck_service.py:2108–2110`), но это **глобальное** значение: при хотя бы одной evidence-строке класс `ok`, поэтому `_RETRIEVAL_SITUATION` в payload не попадает, даже если отдельные части упали. Честность смешанного прогона держится на per-claim покрытии (`claim_payload_rows:2295–2297`) и `parts[].status_detail`. Более крупное изменение не нужно: достаточно закрепить тестом отсутствие противоречия «техзаголовок ↔ успешная часть» и при необходимости подавить его (ES-6). Отдельного «per-claim retrieval_state для verbalizer» не вводим: это была бы новая структура ради уже существующего поля `claims`.
3. **Timezone/источник времени в FactCheck отсутствует.** `format_chat_time` (`canonical_context.py:331–355`) подключается только в Direct (`direct_chat_service.py:7553`). §5.4 «когда: известный timezone и источник времени» для FactCheck сейчас невыполним без добавления одной строки времени в analyst user-content. Это маленькая правка (существующая функция), но она меняет payload FactCheck → нужен парный тест.
4. **`quote_author_id` — числовой Telegram user id в теле сообщения** (`thread_chain.py:273–275`). Показ имени возможен только через существующий резолвер (`row_speaker`/`aliases`), которого в `format_chain_line` нет (там только `ChainItem.name` для автора хода, а автор цитаты — только id). Полное исправление требует передать резолвер имени цитируемого в `ChainItem`/`format_chain_line` (аддитивное поле) — иначе останется либо число, либо `автор unknown`. Считаю это частью Lane A (дешёво), но фиксирую: без аддитивного поля «имя автора цитаты» §9.2 не закрыть.
5. **`long-context` полнота в `_render_digest`.** При бюджете 8000 символов часть window-строк вытесняется; §5.4 запрещает «молча потерять критическую атрибуцию». Сейчас вытеснение приоритезирует якорь и свежесть, но не сообщает модели о неполноте. Нужна одна строка «часть окна не показана (N сообщений)» — без нового бюджета. Это меняет `render_feed` (тест `test_factcheck_context_cfg06.py`), но не архитектуру.

---

## 9. Приёмка и следующий шаг

**Обязательные проверки (см. §5):** E1–E10 на фикстурах §13, включая два маршрута FactCheck, deferred, tool; P0-список §5.1; `target_kind`/`media_*`/`evidence_*` в трассе (§10.3/§11.3); отсутствие новых LLM-вызовов/перегенераций/regex-чистки; Personality Core и Emotion/Humor/Expression/алиасы/Memory/GraphRAG-семантика не тронуты.

**Риск:** R2 (средний: широкий формат контекста + dedup) при узких правках; R0 для доставки Reply — реальные ID остаются.

**Следующее действие:** PM — разложить на 6 лейнов §6.1 в порядке `A → (B,E,F) → C → D`; Builder начинает с Lane A (проекция + relation-рендер + флаг `flags.context_speech_projection`), затем C (M1–M7, M9–M12) и D (ES-1…ES-4) как два независимых набора с раздельными тестами. Human gate не требуется: все развилки — программистские и решены здесь.
