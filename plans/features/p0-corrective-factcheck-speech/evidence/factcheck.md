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

## 7. Rework r1 (review `review-factcheck.md`, Needs Fixes) — F1–F6

Кандидат базы: `b93f1557`. Все правки проверены офлайн (`pytest`), без сети/прода.

### F1 (BLOCKER, FC-04) — каскад провайдеров
- **Было:** `search()` передавал `timeout_budget=` любому движку, а `_search_exa`/
  `_search_ddg` принимали только `query` → после падения Tavily Exa/DDG падали
  с `TypeError`, пользователь получал «поиск недоступен».
- **Стало:** Exa/DDG принимают `timeout_budget` и урезают свой таймаут; каскад
  передаёт бюджет только движкам, чья сигнатура его принимает
  (`inspect.signature`, поддержка `**kwargs`), остальные вызываются как раньше.
- **Тесты сервисного пути:** `TestF1CascadeRealPath` — `search_relevant(...,
  timeout_budget=3.0)` с одноаргументными движками: Tavily падает → Exa реально
  вызывается, результат возвращён; `run_retrieval` даёт `queries_used>=1`,
  `refs>=1`, класс `ok`, у всех ref есть URL.

### F2 (BLOCKER, FC-06) — evidence без URL на envelope-пути
- **Было:** при пустом `retrieval_refs` сервис заново разбирал `search_text`
  (`evidence_rows_from_results`) и возвращал строки `url=null`; класс оставался
  `ok` вместо `processing_failed`.
- **Стало:** если прогон пришёл из веб-retrieval, evidence строится ТОЛЬКО из
  структурных строк плана; нет проверяемых ссылок → `evidence=()` и
  `processing_failed` (`source_missing`). Внутренний поиск ветки тоже больше не
  принимает строки без URL как доказательство; «нашли текст без ссылок» даёт
  `processing_failed`.
- **Тесты сервисного пути:** `TestF2EnvelopeEvidencePath` — `check_claim_envelope`
  с off-topic `search_text` и 0 refs: `evidence_rows == ()`,
  `factual_verdict=insufficient_evidence`, `reason=source_missing`, заголовок
  «материалы не удалось разобрать»; аналитик не вызывается вовсе (положительный
  вердикт без доказательств невозможен).

### F3 (BLOCKER, FC-09) — основной temporal-кеш
- **Было:** `TEMPORAL_PIPELINE_VERSION="tf2"` не менялся, поэтому старый
  `factcheck_temporal`-вердикт отдавался до 6/720 ч.
- **Стало:** версия `tf3`; material проверки (claim + OCR) входит в ключ через
  `cache_components["claim"]`.
- **Тесты кеша:** `TestF3TemporalCachePath` — запись под `tf2`, затем чтение на
  `tf3`: ключ отличается и старый текст НЕ отдаётся; новая запись читается.

### F4 (RELATED, FC-01) — бюджет на части
- **Было:** первая часть с числом и годом забирала все 3 запроса.
- **Стало:** два прохода — по одному базовому запросу на часть, затем уточнения
  на остаток; если слотов на уточнения нет, числа/годы идут в запрос своей
  части. Год распознаётся как временной контекст, а не «метрика».
- **Тесты:** `TestF4BudgetPerPart` — контрпример ревью (сборка+год+macOS в
  первом предложении) даёт ровно 3 запроса, по одному на часть; при полном
  бюджете уточнения не вытесняют части.

### F5 (RELATED) — противоречивый разбор частей
- **Было:** при положительном топе и молчании модели синтезировались части
  «данных недостаточно» → «Подтверждается» + отрицание каждой части.
- **Стало:** серверный синтез частей только для честного
  `insufficient_evidence`; положительный топ не сопровождается выдуманным
  разбором.
- **Тесты:** `TestF5NoContradictoryParts` — `check_claim_envelope` с evidence и
  `supported` от аналитика: `parts == ()`, в рендере нет «данных недостаточно»;
  при `insufficient_evidence` части по-прежнему создаются (≥2).

### F6 (RELATED, FC-08) — «распознано, текста нет» ≠ «не анализировали»
- **Было:** любой пустой OCR → `image_not_analyzed=True`.
- **Стало:** `image_not_analyzed` только при реальной строке ожидания Vision;
  готовый анализ без текста = `image_analyzed=True`, `ocr_chars=0`, без ложной
  оговорки; подпись сохраняется.
- **Тесты:** `TestF6ReadyNoText` (ready/no-text и pending), плюс обновлён
  `TestFC08Image` под новый контракт.

### Обновлённые существующие тесты (контракт изменился по требованию)
- `tests/test_factcheck_planner_cfg06.py::test_semantic_queries_not_raw_slice`:
  вместо «уникальные интенты» проверяется покрытие частей + уточнение (прежнее
  требование противоречило §3.3/§3.5: частей больше, чем интентов).
- `tests/test_factcheck_fc_r1_fix.py::test_vaping_plan_queries_by_meaning_not_raw_slice`:
  при 3 частях и бюджете 3 числа 16/40 идут уточнением в запрос части —
  проверяется их наличие в поиске, а не отдельный numeric-интент.

### Числа после rework
- `pytest -k "factcheck or search_aggregator or temporal"` → **529 passed**
  (было 517; +12 за счёт новых интеграционных тестов).
- `tests/test_factcheck_p0_fc.py` → **28 passed** (было 16; F1–F6 добавлены).
- Бюджет: 3 запроса / 10 c — не менялся. Версии: `PLANNER_VERSION=fp3`,
  `PIPELINE_VERSION=fcv4`, `TEMPORAL_PIPELINE_VERSION=tf3`.

### FC после rework
| ID | Итог | Чем доказано |
|---|---|---|
| FC-01 | **PASS** (офлайн) | `TestF4BudgetPerPart` + `TestFC01Composite` (по запросу на часть, части в вердикте) |
| FC-04 | **PASS** (офлайн) | `TestF1CascadeRealPath` (Tavily падает → Exa вызван и отдан; `used/refs>=1`, класс `ok`) |
| FC-06 | **PASS** (офлайн) | `TestF2EnvelopeEvidencePath` (0 evidence, `processing_failed`, без `url=null`) |
| FC-09 | **PASS** (офлайн) | `TestF3TemporalCachePath` (старый `tf2`-вердикт не отдаётся) |

Остаётся: реальные провайдеры/LLM/Vision и живой чат — это `live_required`-строки
карты, они закрываются пост-деплой канарейкой, а не офлайн-тестами.
