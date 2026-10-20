# CFG-06 Build Brief — Temporal + Factcheck: единый runtime pipeline

Подготовлено: PM, lane CFG-06-PREP, 20.10.2026. Режим read-only; этот файл — единственная запись.
Старт билда — после вердикта ревью кандидата 2.58.98 (`37097f7c`). Бриф для оркестратора; билд не назначается.

## 0. Входы и guard уже сделанного

- Карта: `plans/features/cfg/requirements-map.json` — все строки `slice=CFG-06` (90 required-строк, все PENDING; 9 live_required).
- Источник: `plans/features/cfg/source-cfg-addendum.md` L195–L331 (CFG-06…CFG-06J + приоритет трактовки + блокирующие критерии).
- Граф: `plans/features/cfg/slice-graph.json` сейчас держит CFG-06 одним слайсом (depends_on CFG-05-Verify).
- **Уже влито в 2.58.98 (`37097f7c`) — НЕ повторять и НЕ ломать:**
  - `speech_owner_block` (Core+Expression) подключён в `_check_claim_pipeline` (single, L214–216) и `_check_claim_two_call` (L271–279) — шов UNIFIED-CORE;
  - C14-строка safety-bypass вычищена по ADR-1013-3 (PREV-лестница, byte-tests);
  - `tests/test_unified_core_route_coverage.py` — 18 CONTRACT route-coverage тестов, включая фактчек: новый pipeline обязан их сохранить/расширить, не ослаблять.

## 1. Текущее состояние кода (аудит, deployed-база для волн)

Ключевые факты (проверено по коду 20.10.2026):

| Зона | Факт | Требование-владелец |
|---|---|---|
| `handlers/factcheck.py` | Развилка `_temporal_on()` → `check_claim_envelope` (MCA-20) либо legacy `check_claim`; кулдаун per (chat,user); кеш slugs `factcheck`/`factcheck_temporal`; доставка `send_chunked_reply` **без** parse_mode; семантического suitability-гейта нет | CFG-06A.1, 06H.1/05, 06B.1 |
| `handlers/factcheck.py::_fetch_chat_context` | Узкое окно: `before/after` + жёсткий кап `FACTCHECK_CONTEXT_TOTAL_CAP=40`; reply-chain через `thread_chain` | CFG-06I.2 (нужно 200–500) |
| `services/factcheck_service.py::_temporal_verbalize` L753–758 | `style_note` ТРЕБУЕТ «период проверки (… unknown)» в ответе — подтверждённый источник утечки технической лексики; temporal-вербализатор НЕ получает `speech_owner_block` | CFG-06A.5, 06D.2, 06F.5 |
| `services/temporal_factcheck.py::search_queries_for` | Запрос = `normalize_text(claim)[:200]` + годы — несмысловой; `decompose_claim` — сплит по предложениям | CFG-06A.4, 06C.3 |
| `services/search_aggregator.py::_format_hits` | Выдача — форматированный текст `title\nsnippet\nurl`; структура URL/текста не разделена | CFG-06A.6, 06C.5 |
| `services/smartmodule_utils.py::send_chunked_reply` | `parse_mode` kwarg уже есть (Epic 43), но `_chunk_by_whitespace` может рвать теги/entities | CFG-06E.4 |
| `services/safe_fetch.py::SafeFetcher` | Существует — открытие первоисточников доступно (`enrich_evidence_dates` уже им пользуется) | CFG-06C.7 |
| `services/temporal_factcheck.py` | Уже есть: `StageTrace`/`stage_event`/`record_temporal_run`, evidence-строки ev-N с allowlist refs, `verdict_from_payload`, validator (CoVe REUSE), composite cache key с freshness bucket | CFG-06F.1, 06D.5/06, 06F.3 — переиспользовать |
| `services/prompt_style_blocks.py` L138+ | Фактчек объявлен text-only/plain («нет safe-HTML-доставки») — seam для 06E, менять точечно | CFG-06E.CON |
| UI B07 | Отдельная карточка Temporal уже убрана (B07.3, тест `test_asap8_v63_b07_temporal_factcheck.py` защищает) | CFG-06H.0 — закрыто, не трогать |

## 2. Декомпозиция на рабочие пакеты (wave-план)

Все пакеты остаются в map-слайсе `CFG-06` (владелец всех 90 строк). Рекомендация перед стартом билда: уточнить граф на подпакеты W0–W7 (это правка `slice-graph.json` вне write-скоупа этого лейна — делает Orchestrator/PM на план-гейте). Ограничение: ≤3 writer-лэйна; фактически параллель только W4∥W5 после контракта-фриза в W3.

### W0 — Аудит двух маршрутов на deployed-коде (read-only evidence)
- **Scope:** только `plans/features/cfg/evidence/cfg-06/audit/**` (запись документов, код не трогается).
- **Закрывает:** CFG-06A.1–10, CFG-06H.1 (таблица различий маршрутов: контекст/поиск/инструменты/проверка источников/генерация/кеш/доставка; фактический deployed SHA + effective flags из `mca_gates.temporal_*`).
- **Acceptance (наблюдаемое):** таблица различий с пруфами на deployed SHA; каждая гипотеза 06A.1–10 подтверждена/опровергнута с указанием файла/строки deployed-коммита.
- **Risk:** R1. **Next:** W1.

### W1 — Широкая реконструкция контекста (CFG-06I)
- **Scope:** новый `services/factcheck_context.py` (сборщик широкого окна + индексация), `handlers/factcheck.py` (подмена `_fetch_chat_context` за гейтом), `services/chat_context.py` (аддитивно), `services/temporal_factcheck.py` (envelope-поле context_slice), тесты `tests/test_factcheck_context_cfg06.py`, evidence.
- **Закрывает:** CFG-06I.1–9, частично CFG-06I.KEY.
- **Acceptance (наблюдаемое):** на фикстуре спора 200/500 сообщений без reply-chain gate-вход получает Target+ConversationContext с якорями message_id/author/timestamp; «тезис 50 сообщений раньше» находится; окно адаптивное, двухуровневое (дешёвая хронология → дословные сегменты LLM); срез кешируется с версией/диапазоном/ID; чужие чаты не читаются; приватное не уходит наружу.
- **Deps:** W0. **Risk:** R2 (бюджет токенов — обязателен двухуровневый feed). **Next:** W2.

### W2 — Suitability gate + ContextualClaimResolution
- **Scope:** новый `services/factcheck_suitability.py` (типизированный gate: decision/claim_items/scope/reason_code/confidence/target_ref; типы 06B.2; многоступенчатость 06J.1), `services/factcheck_prompts.py` (gate/CR-промпты), интеграция входа в `handlers/factcheck.py`, тесты + регрессионный корпус `tests/test_factcheck_gate_cfg06.py`, corpus fixture.
- **Закрывает:** CFG-06B.1–7, CFG-06J.1–4, CFG-06I.6, ADD-1.C2.
- **Acceptance:** короткая саркастичная цель при наличии спора → `checkable_in_context` с выделенным тезисом; чистая ругань после просмотра контекста → короткая реплика персонажа (через `speech_owner_block` — шов 2.58.98 сохраняется) без веб-поиска; «бессмыслица»/мат не regex-блокиратор; корпуса 20/100/200/500+ (кейсы а–з) с метриками false_refusal_rate/false_contextual_claim_rate/target_attribution_errors/unnecessary_search_rate; отвергнутое возвращает needs_context, а не уверенный отказ.
- **Deps:** W1 (gate получает контекст). **Risk:** R2. **Next:** W3.

### W3 — Единый оркестратор (объединение маршрутов) — контракты и фриз
- **Scope:** `services/factcheck_service.py` (единый вход `run_factcheck(FactcheckRequest)`: ResolveTarget → ResolveTimeAndProvenance (всегда, дешёвая) → Context → Suitability → Plan → Retrieval → Evidence/Temporal Verification → GroundedVerdict → Writer → Presentation → Render → Delivery; legacy/`check_claim_envelope` — внутренние ветки за флагом отката), `services/system2_handoff.py` (whitelist payload — egress машинных полей), `services/factcheck_prompts.py`, `services/mca_gates.py` (унифицированный флаг перехода/отката), тесты.
- **Закрывает:** CFG-06H.2–7, CFG-06H.ARCH, CFG-06.CON, CFG-06.T1–T3, CFG-06.J-PRIOR, ADD-1.C1, CFG-06A.2/3/9.
- **Acceptance:** все входы (reply/репост/команда/Direct-tool/транскрипция) идут через один оркестратор; продуктовая развилка «временной или обычный» устранена (правила инструментов/evidence/style/egress/кеша одинаковы); CoVe/System2, grounding, SourceRef, Tool Router, лимиты, идемпотентность сохранены; до EvidenceMap нет утверждающего вердикта; после GroundedVerdict Writer/Renderer не меняют факты/числа/ссылки; fallback (single-call) под теми же guard'ами; откат флагом без двух публичных контрактов; route-coverage тесты 2.58.98 зелёные.
- **Deps:** W2. **JOIN BARRIER:** здесь фризятся схемы `FactcheckRequest/ClaimEnvelope/FactcheckPlan/EvidenceMap/CheckedVerdict/FactcheckPresentation` — после него W4∥W5. **Risk:** R1 (главный архитектурный шов; байт-паритет legacy-ветки до переключения). **Next:** W4∥W5.

### W4 — Планировщик, осмысленные запросы, структурированный evidence
- **Scope:** `services/factcheck_plan.py` (новый: выбор инструментов web/chat_history/memory-RAG/both/no_evidence_needed), `services/temporal_factcheck.py` (search_queries_for → смысловые запросы от claim_items; privacy-фильтр), `services/search_aggregator.py` (аддитивный структурированный возврат title/snippet/url рядом со старым форматом), `services/factcheck_service.py` (потребление; SafeFetcher-открытие первоисточников), тесты.
- **Закрывает:** CFG-06C.1–9, CFG-06A.4/6/7, CFG-06D.4–6 (evidence-привязка), CFG-06G.3.
- **Acceptance:** запросы не копируют кусок сообщения: «дрожжи — грибы» → `Saccharomyces boulardii` сохранён, ругань/имена участников/кавычки вычищены; 2–4 запроса с различающей целью; сниппет не готовое доказательство — спорные тезисы открывают первоисточник, недоступность понижает уверенность; evidence-объекты с url_or_message_ref отдельно от текста; закрытый чат не уходит в веб; «вызвал инструмент, но использовал выдумку» = FAIL.
- **Deps:** W3 (фриз схем). **CAN_PARALLEL_WITH:** W5 (скоупы не пересекаются, кроме чтения фриз-схем). **Risk:** R2. **Next:** W6.

### W5 — Presentation + Telegram-safe renderer + доставка
- **Scope:** новый `services/factcheck_render.py` (детерминированный FactcheckPresentation → безопасный HTML/entities; bold/text_link только по evidence map; entity-safe чанки; текстовая деградация), `services/factcheck_delivery.py` (отправка pre-split чанков через существующий `send_chunked_reply(parse_mode=...)`; общий `send_chunked_reply` в `smartmodule_utils.py` НЕ меняется), `services/prompt_style_blocks.py` (factcheck-канал: формат разрешён, прочие каналы не тронуты), `services/factcheck_prompts.py` (anti-Markdown для фактчека заменён на жанровый контракт), `services/negative_constraints.py` (channel-правила нового формата), тесты.
- **Закрывает:** CFG-06E.1–7, CFG-06E.CON, ADD-1.C3, CFG-06D.2/3 (filtered verbalize: убрать `style_note`-утечку L753–758; unknown → человеческие слова), CFG-06A.5/8, CFG-06G.5.
- **Acceptance:** renderer выдаёт работающий bold/список/inline-ссылки только на URL из evidence map текущего прогона; LLM не генерирует HTML; forced temporal JSON (unknown/null/reason_code/style_note) не просачивается; чанки не рвут entities/Unicode, библиография не дублируется; при отсутствии ссылки она убирается и вердикт честно ограничен; непредусмотренный клиент — безопасный plain; reply-to на целевое сохранён; другие каналы (Direct обычный, Summary) байт-не-изменны.
- **Deps:** W3 (фриз схем). **CAN_PARALLEL_WITH:** W4. **Risk:** R2. **Next:** W6.

### W6 — Наблюдаемость, кеш, бюджеты
- **Scope:** `services/temporal_factcheck.py` (StageTrace/счётчики консолидация), `services/factcheck_service.py` (единый trace на каждый run; метрики attempted/succeeded/relevant/used/verified; bounded retry + time/tool budget), `services/smart_cache.py` (консолидация slug + версии схемы/prompt + as_of; инвалидация legacy/temporal), тесты.
- **Закрывает:** CFG-06F.1–5, CFG-06H.6, CFG-06I.9 (кеш среза), CFG-06C.8 (счётчики), CFG-06A.9 (остаточно).
- **Acceptance:** трасса стадий записана для каждого run, пользователю публикуется результат, а не трасса; «инструмент существует» ≠ «инструмент сработал»; cache-hit чужого чата/даты/цели невозможен; старые результаты не переживают смену pipeline; легаси-fallback не расходится по egress.
- **Deps:** W4+W5 (join). **Risk:** R1 (миграция/инвалидация двух существующих кешей). **Next:** W7.

### W7 — Приёмка, блокирующий критерий, релиз
- **Scope:** тесты сценариев, evidence `plans/features/cfg/evidence/cfg-06/**`, отчёт.
- **Закрывает:** CFG-06G.1–8, CFG-06J.5–6, CFG-06.B, CFG-06.B-HIJ, ADD-1.T6, CFG-06F.6.
- **Acceptance:** см. §3/§4 — композит блокирующего критерия закрывается только целиком.

## 3. Покрытие acceptance-требований: где реализуется, чем доказывается

| Группа | Реализуется в | Доказательство (агентское, офлайн/техническое) | Владельцу (live, опционально по правилу owner_live_checks) |
|---|---|---|---|
| 06A.1–10 | W0 аудит + целевые волны | audit-таблица на deployed SHA, трассы | — |
| 06B.1–7, 06J.1–4 | W2 | RED/GREEN на корпусе; unit gate-типов; метрики корпуса | — |
| 06I.1–9, 06I.KEY | W1+W2 | фикстуры 20/100/200/500+; якорная привязка; кеш-срез тест | — |
| 06H.1–7, 06H.ARCH, 06.CON, T1–T3, J-PRIOR | W3 | таблица маршрутов → один оркестратор; negative-тесты «второго пути нет»; route-coverage 2.58.98; contract-version тест | — |
| 06C.1–9 | W4 | unit/интеграционные с мок-агрегатором + SafeFetcher; privacy-тест утечки; трасса маршрутов skip_search/web_used/chat_used/both_used (06G.7) | — |
| 06D.1–9 | W3+W4+W5 | schema-validation до вербализации; allowlist evidence refs; forced-metadata тест 06G.5; «insufficient_evidence, а не разоблачение»; конфликт источников; honest degradation при отказе поиска | — |
| 06E.1–7, 06E.CON | W5 | renderer unit-тесты (escape, whitelist URL, entity-safe chunks, деградация); 06E.4 — интеграционный тест транспорта с parse_mode | **06G.8/06E.4 глазами владельца:** фактчек-сообщение с жирным/списком/кликабельными ссылками на мобильном+десктопе |
| 06F.1–6 | W6 | trace-тест каждого run; метрики разведены; cache-инвалидация тесты; **06F.6** — технический postdeploy-смоук на проде (логи/трасса/healthz, без сообщений в чат) | наблюдения по живым запускам — по желанию |
| 06G.1 | W2+W4 (сценарий) | офлайн-стенд: фиксированный спор + bounded live-canary веб-поиска в тестовом контуре (2–3 запроса, по прецеденту CFG-02 «безопасная песочница») | может повторить в чате, когда удобно |
| 06G.2 | W2 | корпус кейсов «тёлка/печень/бессвязный набор» — контекст изучен, поиск не запущен, короткий ответ в образе | — |
| 06G.3 | W4 | локальный tool с цитатой/датой/автором; негатив: участники чата не утекают в запрос | — |
| 06G.4 | W4+W5 | live-canary веб (новость/дата) + inline-ссылка на реально полученный источник; при отключённом вебе — честный вердикт | — |
| 06G.6 | W5+W6 | таблица негативов (невалидный JSON, битый evidence_id, сломанный URL, HTML-инъекция, пустой поиск, таймаут, кеш-хит, правка сообщения, chunks) | — |
| 06G.7 | W6 | trace-дайджест по каждому контрольному кейсу | — |
| 06J.5 | W2 | corpus+метрики артефактом в evidence | — |
| 06J.6, 06H.1(live), 06.B | W7 | postdeploy: технические live-проверки на проде (прецедент 2.58.97: прод-байты/логи/дайджесты, БЕЗ сообщений в чат); спор 200+ воспроизводится синтетически в тестовом контуре deployed-кода | «фактчек» на короткой реплике реального спора — владелец когда удобно |

Учёт лимита владельца: `plans/owner_live_checks.md` — все живые проверки в чате делает владелец сам, они информационные и не блокируют очередь. Агентские live-обязательства = технические (prod-байты/логи/трассы/healthz) + ограниченные платные canary в тестовом контуре, без сообщений в чаты.

## 4. Блокирующий критерий CFG-06.B → наложение на pipeline

Композит (L290) разворачивается в 5 проверяемых условий:

1. «сначала решает, имеет ли смысл проверка» → W2: suitability gate после контекстной реконструкции, многоступенчатый, `needs_context` вместо уверенного отказа (06J.1, ADD-1.C2). Шов: новая стадия между `_fetch_chat_context` и первым платным вызовом; из кулдаун/кеш-путей gate не выпилен (кеш-hit — тот же контракт версии).
2. «подтверждает реальными источниками или честно сообщает ограничение» → W4 (реальный поиск/локальный tool/первоисточники) + W3 (нет утверждающего вердикта до EvidenceMap; `insufficient_evidence` серверно, как уже в temporal TH-5 — расширить на legacy-ветку).
3. «не выпускает служебные данные» → W3 `stage2_payload` whitelist + W5 presentation/renderer (машиные поля не проходят в публичный текст) + удаление `style_note`-утечки `_temporal_verbalize`.
4. «краткий читаемый Telegram-вердикт с проверяемыми ссылками» → W5 renderer: inline-ссылки только на реально полученные URL evidence map; plain-деградация.
5. «единый контракт на всех маршрутах и fallback» → W3 один оркестратор; W6 — fallback/кеш/байпас под теми же guard'ами; флаг отката не создаёт второй публичный контракт.

Правило закрытия: композит объявляется VERIFIED только после зелёных всех пяти условий на deployed-контуре; частичные зелёные не закрывают (прецедент CFG-04.B).

## 5. Переиспользование и удаления

**Переиспользовать:**
- Из 2.58.98/UNIFIED-CORE: `speech_owner_block` — подключить к единому Writer и коротким refusal-репликам (сейчас temporal-вербализатор его НЕ получает — добрать, не дублируя); PREV-лестницу и byte-tests не ломать.
- Из temporal-контура: StageTrace/stage_event/record_temporal_run, evidence ev-N + allowlist refs, validator (CoVe), composite cache key + freshness bucket, `enrich_evidence_dates`, `SafeFetcher`.
- Из CFG-01: паттерн горячего effective-параметра (`chat_params`/ConfigCache) для новых настроек окна/gate без рестарта.
- Из CFG-03: обязательную трассу параметра UI→…→consumer для любого нового MiniApp-параметра (без него параметр не выводить).
- Из CFG-04/05: технику live-эвиденса (прод-байты, digest JSON, diff-guard) и reuse-map стиль; CFG-06 вообще не должен трогать `web/**` (B07-карточка уже закрыта) — diff-guard на нулевой web-дифф.
- Из существующего: `send_chunked_reply(parse_mode=)` без правки общей функции; `thread_chain`, `chat_context` (аддитивно), `negative_constraints.verbalize_validated`, `strip_phantom_tags`/grounding, smartmodule concurrency pool, кулдаун.

**Удалить/не делать:**
- Второй запуск B07 UI / отдельную карточку Temporal — запрещено (тест защищает).
- Продуктовую развилку «временной vs обычный фактчек» как пользовательский контракт (06H.5) — handler-развилка `_temporal_on()` сворачивается в один вход за флагом миграции.
- `style_note` «период проверки (… unknown)» в `_temporal_verbalize` (L753–758) — первопричина утечки.
- Третий независимый фактчек — запрещено (ADD-0.2, 06A.10): объединение, не клон.
- Дублирование `fetch_article`: в deployed-коде примитив — `SafeFetcher.fetch_text` (06A-цитата относилась к публичному master; отдельный вопрос не требуется).

## 6. Риски и неоднозначности исходника (с цитатами; Human Gate только при реальном выборе)

1. **Размер слияния.** «…текущий код различает check_claim/System2 и check_claim_envelope/Temporal Factcheck. Это допустимо как историческая реализация, но **не как целевая архитектура**» (L296). Риск регрессии швов 2.58.98 → митигируется флагом миграции, байт-паритет legacy-ветки до переключения, route-coverage тесты.
2. **Окно контекста.** «например, кандидаты из последних 200–500 сообщений при соответствующих настройках и хранении… Не привязываться к произвольному фиксированному числу: окно адаптивное» (L311). Адаптивность оставлена инженерному решению W1 (бюджеты/дедлайны 06I.9) — не владелец-выбор; выносится в MiniApp только при эксплуатационной необходимости (06B.7).
3. **Стиль отказа vs CFG-07B.** «при включённом мате — допустима грубая ирония» (L226) при том, что переключатель «Мат» — CFG-07B (позже в очереди). До CFG-07B действует текущий effective-режим (ADD-EXP F3 off/occasional/frequent); W2 обязан лишь НЕ блокировать грубую иронию и не форсировать мат. Стык зафиксирован; отдельного вопроса владельцу не требует.
4. **Live vs запрет сообщений в чат.** «Живая проверка… в целевом deployed-контуре (новой команды владельца ждать не нужно)» (L277) + постоянное правило 20.10 «живые тесты в чате выполняет владелец сам». Разрешено прецедентом 2.58.97: агентские live = технические проверки без сообщений в чат; противоречия нет, Human Gate не создаётся.
5. **Платные canary.** 06G.1/06G.4 требуют реального веба: ограниченные прогоны в тестовом контуре (прецедент CFG-02 «безопасную песочницу и точно ограниченные live-canary», L77); массовые прод-прогоны запрещены.
6. **Корпус «реальных» последовательностей** (L326): размеченные цепочки берутся из локальной БД-копии/синтетики; приватные тексты в evidence не публикуются (06F.1).
7. **Кеш-миграция** (L303): legacy slug `factcheck` + temporal `factcheck_temporal` → единый версионированный ключ; устаревшие записи инвалидируются при смене pipeline (06H.6) — риск stale-хитов на переходе, покрывается тестом W6.

## 7. Handoff для оркестратора

- Готово к планированию билда: волны W0→W7, скоупы, зависимости, параллель только W4∥W5 после фриза схем в W3.
- Перед назначением Builder: (а) вердикт ревью 2.58.98; (б) уточнить `slice-graph.json` подпакетами W0–W7 (запись вне этого лейна); (в) прогнать `requirements_gate.py check --stage plan`.
- Заблокированные предпосылки: CFG-06 стартует строго после CFG-05-Verify (уже VERIFIED) и вердикта 2.58.98; новых Human Gate план не требует — все потенциальные неоднозначности закрыты существующими решениями (§6.3–6.4).
