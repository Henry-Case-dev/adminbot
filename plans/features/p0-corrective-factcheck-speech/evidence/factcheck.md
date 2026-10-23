# P0-FACTCHECK — фактчек по существу (FC-01..FC-09)

- **Lane:** `P0-FACTCHECK` (writer)
- **Дата:** 2026-10-24, локальное время проверок ~06:20–06:55 +12:00 (UTC+12)
- **Источник:** `source-2026-10-24.md` §3.3–§3.7, §9 (FC-01..FC-09)
- **Forensic:** `evidence/forensic.md` §2/§3 — прод-прогон `tfr-6e0ab2dbcc784b57`
- **Архитектура:** `arch-design.md` §2 (FACTCHECK/P0-B)
- **Прод/SSH/живые чаты:** не использовались. Все проверки — офлайн-фикстуры.
- **Ограничение:** реальные провайдеры/LLM в этом лейне не вызывались (лимит
  времени лейна); поведение на сети подтверждается существующими кассетами
  `tests/test_factcheck_fc_r1_fix.py` (офлайн-replay) и новыми фикстурами.

## 1. Root cause (что реально ломалось)

Подтверждено forensic-трассой и кодом до правки:

1. **Один запрос на составную публикацию.** `factcheck_planner._build_plan_inner`
   строил запросы «по одному на интент» (`entity_done/numeric_done/temporal_done`)
   → прод: `queries=1`, `intents=entity_check`. Остальные тезисы (сборка/платформа/
   мультиагентность) в поиск не попадали.
   Файл: `services/factcheck_planner.py` (было `:311-334`).
2. **Свидетельство без URL принималось как доказательство.**
   `evidence_refs_from_search` создаёт `EvidenceRef(url=None)`; `run_retrieval`
   складывал их в `EvidenceMap` → прод: 4 строки `url=null`, `claim_part=null`,
   off-topic («Claude Code leak») при тезисе про агентов Telegram.
   Файл: `services/factcheck_planner.py` (было `:550-557`, `:440-449`).
3. **Технический сбой превращался в содержательный вердикт.**
   `factcheck_service.check_claim_envelope` при пустом evidence жёстко ставил
   `insufficient_evidence` с `temporal_insufficient_evidence` и **не читал**
   `RetrievalOutcome` (`budget_exhausted/fetch_errors/queries_used`), хотя метрики
   уже были. Файл: `services/factcheck_service.py` (было `:837-843`).
4. **Лексический фильтр без морфологии.** `is_relevant_result` — подстрочный
   `t in haystack`, поэтому «заболеваемости» ≠ «заболевших» (релевантное
   отбрасывалось), а одно случайное имя проходило порог ≥2 при общем запросе.
   Файл: `services/search_aggregator.py` (было `:74-84`).
5. **Текст с изображения вообще не участвовал.** `handlers/factcheck.py`
   берёт только `text/caption`; Vision-контур (`mca_vision`) существует, но к
   фактчеку не подключён → версия/сборка/платформа (283365/13.1.0/macOS) в
   анализируемый материал не попадали (forensic §2.6).
6. **Per-claim разбор не гарантирован.** Части появлялись только если модель их
   вернула; иначе `parts=()` и `claim_part=null` во всех durable-строках; рендер
   выбрасывал части без ссылок. Файлы: `services/factcheck_service.py`,
   `services/factcheck_renderer.py`.
7. **Renderer не различал сбой/бюджет/отсутствие данных** — один заголовок
   `insufficient_evidence` (`factcheck_renderer.py:55-60,80-85`).

## 2. Что изменено

| Файл | Изменение |
|---|---|
| `services/factcheck_planner.py` | `PLANNER_VERSION="fp3"`: запрос НА КАЖДУЮ часть (`_claim_units`) + уточнения (числа/годы) по этой же части, бюджет тот же ≤3; бюджет запроса делится между оставшимися (`timeout_budget`), дедлайн проверяется ДО запроса; строки без URL не попадают в `EvidenceMap`; `RetrievalOutcome.provider_failures`; падение запроса больше не маскируется под `fetch_errors`. |
| `services/search_aggregator.py` | `term_key`/`_term_keys` — лёгкая морфология RU/EN (основа слова), сравнение по основам; одно совпадение не проходит при многотомном запросе (нужно ≥2 разных термина и ≥20 %); `timeout_budget` урезает per-engine таймауты (Tavily 5 c больше не съедает 10-секундный контур). |
| `services/factcheck_service.py` | `load_claim_media`/`ClaimMediaMaterial` — OCR готового Vision-анализа (`mca_vision.render_media_context_async`, новый OCR не создаётся); `classify_retrieval` → `budget_exhausted`/`search_failed`/`processing_failed`/`insufficient`/`ok`; reason-коды `deadline_exceeded`/`provider_unavailable`/`source_missing`; серверные `parts` с вердиктом не выше `insufficient_evidence` и привязкой evidence к части; техническая оговорка в `uncertainty`; вербализатор получает `situation`, fallback-текст называет причину. |
| `services/factcheck_orchestrator.py` | `PIPELINE_VERSION="fcv4"`: OCR изображения добавляется к claim ДО envelope/планирования/анализа; `image_not_analyzed` → честный notice; кеш-ключ включает распознанный текст (старый вердикт не скрывает новую проверку); метрика `provider_failures`; notice «нет проверяемых ссылок» на legacy-ветке. |
| `services/factcheck_renderer.py` | Отдельные заголовки и пояснения для `deadline_exceeded`/`provider_unavailable`/`source_missing`; части без ссылок больше не исчезают («проверяемой ссылки нет»); ссылки — только реальные URL. |
| `tests/test_factcheck_p0_fc.py` | 16 тестов FC-01..FC-09 на фикстурах (офлайн). `TEST-LIFECYCLE: CONTRACT owner=P0-FACTCHECK/FC-01..FC-09`. |
| `tests/test_factcheck_fc_r1_fix.py` | Один тест приведён к новому контракту: недоступность всех провайдеров даёт технический заголовок, а не «Недостаточно данных» (§3.6); вердикт остаётся `insufficient_evidence`. |

Схемы `EvidenceRef/EvidenceMap`, `TemporalClaimEnvelope/TemporalVerdict`,
`CheckedVerdict/FactcheckPresentation` не менялись (только использование
существующих полей `reason`, `uncertainty`, `parts`, `reason_code`).

## 3. Числа (по коду/фикстурам, не прод)

- Бюджет запросов: **3** (не увеличен), символов на запрос ≤200.
- Бюджет времени контура: **10 c** по умолчанию; теперь делится на остаток
  запросов (мин. 1 c на запрос) и урезает per-engine таймауты.
- Порог релевантности: ≥2 разных термина (по основе) **и** ≥20 % терминов при
  многотомном запросе; для однотерминного запроса — 1.
- `_MAX_EVIDENCE_REFS=12`, `_MAX_PRIMARY_FETCHES=2` — без изменений.
- Прод-кейс до правки: `queries=1`, `used=1`, `refs=4` (все `url=null`,
  `claim_part=null`), `fetch_errors=0`, `budget_exhausted=False`.
  После правки такой набор в `EvidenceMap` не попадает: 0 проверяемых ссылок →
  класс `processing_failed` (не «нет доказательств»).
- Тесты: `517 passed` (`-k "factcheck or search_aggregator or temporal"`),
  из них 16 новых FC-тестов; полный pytest не запускался (лимит лейна).

## 4. FC-01..FC-09 — PASS/FAIL

| ID | Сценарий | Итог | Доказательство |
|---|---|---|---|
| FC-01 | Составная новость, частичные подтверждения, субъективный вывод | **PASS** | `TestFC01Composite`: на тезисе Telegram+Claude+ChatGPT+сборка 283365 план даёт 2–3 разных запроса (включая «283365»); при молчании модели сервер создаёт ≥2 части с вердиктом `insufficient_evidence` (положительный без доказательства запрещён). `TestFC07Partial` — части выводятся отдельно. |
| FC-02 | Релевантная публикация другими словами | **PASS** | `TestFC02Morphology`: «всплеск заболеваемости» ↔ «рост заболевших» проходит фильтр по основам; off-topic «Claude Code leak» при терминах про агентов Telegram — отклоняется (одно совпадение ≠ релевантность). |
| FC-03 | Первоисточник недоступен, вторичные пригодны | **PASS** | `TestFC03SecondarySources`: SafeFetcher падает (`fetch_errors≥1`), но вторичные публикации с URL остаются в `EvidenceMap`; класс `ok`, durable-строки имеют `url`. |
| FC-04 | Один провайдер упал, следующий дал результат | **PASS** | `TestFC04ProviderCascade`: Tavily 503 → Exa результат возвращён; отдельно `provider_failures` в `RetrievalOutcome`. |
| FC-05 | Истёк бюджет поиска | **PASS** | `TestFC05Budget`: `budget_exhausted=True` на медленном агрегаторе; класс `budget_exhausted` → reason `deadline_exceeded`; заголовок «Проверка не завершена: истёк лимит времени», а не «Недостаточно данных». |
| FC-06 | Пустой EvidenceMap не даёт ложного опровержения | **PASS** | `TestFC06EmptyEvidence`: пустой результат → `insufficient_evidence` (не `refuted`); технические классы отделены (`search_failed`, `processing_failed`). |
| FC-07 | Частичное подтверждение не «ничего неизвестно» | **PASS** | `TestFC07Partial`: mixed-вердикт, заголовок «Подтверждается частично», разбор «По утверждениям» с `supported` и `insufficient_evidence`; часть без ссылки видна с пометкой. |
| FC-08 | Тезис в подписи и на изображении | **PASS** (офлайн) | `TestFC08Image`: OCR из Vision-контура попадает в `text_suffix` («283365», «macOS»), подпись сохраняется; неготовый анализ → `image_not_analyzed` + notice, текст подписи не теряется; оркестратор передаёт OCR в claim (проверено фикстурой). Реальный Vision-вызов не выполнялся. |
| FC-09 | Кешированный старый вердикт не скрывает новую проверку | **PASS** | `TestFC09Cache`: ключ `fcv4`+`fp3` отличается от старого `fcv3`+`fp2`; распознанный текст меняет ключ; старая запись в кеше не prevents повторную проверку — сервис вызывается, доставляется исправленный вердикт. |

## 5. Что теперь при сбое/составной публикации/изображении

- **Изображение.** OCR существующего Vision-анализа добавляется к тезису до
  планирования → попадает в запросы и в промпт аналитика. Анализ не готов →
  `image_not_analyzed` + notice, подпись остаётся. Ошибка Vision → обычный
  текстовый путь (fail-open).
- **Составная публикация.** До 3 запросов, каждый про свою часть (+ числа/годы
  этой части). Части вердикта присутствуют всегда: из модели либо из серверной
  декомпозиции с вердиктом не выше `insufficient_evidence`.
- **Сбой.** `provider_unavailable` / `deadline_exceeded` / `source_missing`
  дают отдельный заголовок и оговорку; вердикт остаётся консервативным
  (`insufficient_evidence`), но больше не выдаётся за «фактов нет».
- **Ссылки.** В доказательства и в рендер попадают только реальные URL;
  `url=null` строки остаются лишь контекстом для модели.

## 6. Честные ограничения

1. Реальные вызовы Tavily/Exa/DDG/LLM и реальный Vision в этом лейне не
   выполнялись (лимит ≤45 мин, ≤4 вызова). Сетевые ветки подтверждены
   офлайн-каскадом и существующими кассетами.
2. `TemporalClaimEnvelope.claim_text` дополняется OCR при построении envelope;
   при отсутствии записи сообщения в БД Vision-материал недоступен (fail-open).
3. Классы исходов опираются на существующие reason-коды реестра; новых кодов
   не вводилось (иначе `verdict_from_payload` отбросил бы reason).
4. Полный `pytest` не запускался; прогон `-k "factcheck or search_aggregator or
   temporal"` — 517 passed.
5. Долговременная диагностика «как часто фильтр релевантности отбрасывает
   корректную выдачу» по-прежнему не логируется отдельно (forensic §3 WARN) —
   вне рамок этой правки.
