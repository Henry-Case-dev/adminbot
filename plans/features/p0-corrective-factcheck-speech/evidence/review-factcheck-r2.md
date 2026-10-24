# REV-P0-FACTCHECK-R2 — повторное ревью F1–F6

- Lane: `REV-P0-FACTCHECK-R2` (read-only; записан только этот файл)
- Candidate: `5b69296743e0a75667de2fb8b8758c4b220e1efa`; parent `9051e9fe`
- Factcheck-baseline r1: `b93f1557`
- Date: 2026-10-24 (local +12), offline; прод/SSH/сеть не использовались
- Verdict: **Approved for controlled deployment (parent not DONE)** — F1–F6 закрыты, код слайса можно везти после привязки evidence в карте (PM) и с пост-деплой канарейкой.

## 1. Проверки на кандидате

- `py -3 -m pytest -q -k "factcheck or search_aggregator or temporal"` → **529 passed**, exit 0, 29.99s.
- `py -3 -m pytest -q tests/test_factcheck_p0_fc.py` → **28 passed** (было 16; +12 новых).
- `py -3 -m pytest -q tests/test_search_aggregator.py` → **16 passed**.
- `git diff 9051e9fe 5b692967 --stat` → 8 файлов, только factcheck/evidence/три тест-файла; чужих правок нет.
- `git merge-base --is-ancestor 9051e9fe 5b692967` → 0: checkup-лейн не откатан; 09f56517 (Expression) тоже предок.
- `requirements_gate.py check --stage review --slice FACTCHECK --candidate 5b692967` → **FAIL 44 errors**: 42 строки FACTCHECK `PENDING`, `candidate_commit` пуст, плюс meta-ошибки `authoritative source changed` (в worktree появился addendum #2 про Core) и `candidate mismatch`. Meta-ошибки — REQUIREMENT_DRIFT/работа PM (пересобрать карту под обновлённый source), не дефект factcheck-кода; но без их закрытия review/release gate останется красным.
- Рабочее дерево вне scope: `source-2026-10-24.md` (addendum #2 про Core), PNG asap-speech-arch, untracked evidence; в ходе ревью другой лейн изменил `services/chat_prompts.py`, `services/prompt_migrations.py`, `services/prompt_registry.py` (Core/PROMPTS, не factcheck). Scoped-файлы factcheck/тесты чистые (`git status --porcelain -- <scoped>` пуст). Деплой — только с коммита.

## 2. F1–F6

| # | Статус | Чем подтверждено |
|---|---|---|
| F1 | **VERIFIED** | `_search_exa`/`_search_ddg` принимают `timeout_budget` и урезают таймаут (`search_aggregator.py:358-408`); `_accepts_budget` (`:242-255`) не ломает каскад на движках без параметра. `TestF1CascadeRealPath` через `search_relevant(..., timeout_budget=3.0)`: Tavily падает → Exa вызван и отдан; `run_retrieval` → `queries_used>=1`, `refs>=1`, все URL есть, класс `ok`. |
| F2 | **VERIFIED** | Envelope-ветка больше не разбирает `search_text`: при `retrieval is not None` evidence только из `evidence_map.refs`, иначе `()` (`factcheck_service.py:809-824`). 0 ссылок → `processing_failed`/`source_missing`; аналитик не вызывается (`TestF2EnvelopeEvidencePath`, оба теста). Внутренняя ветка тоже фильтрует строки без URL. |
| F3 | **VERIFIED** | `TEMPORAL_PIPELINE_VERSION="tf3"` (`temporal_factcheck.py:62`); material входит в ключ через `cache_components["claim"]` (OCR добавляется к claim в `factcheck_orchestrator.py:382-403`). `TestF3TemporalCachePath`: запись под tf2 → чтение под tf3 не отдаёт старый текст; новая tf3-запись читается. Хранилище в тесте — FakeCache, но `build_temporal_cache_key`/`read_temporal_cache`/`write_temporal_cache` реальные. |
| F4 | **VERIFIED (контрпример r1)** | Два прохода: по одному базовому запросу на часть, затем уточнения на остаток (`factcheck_planner.py:341-380`). r1-контрпример «283365/macOS/2024 + Telegram + Дуров» даёт 3 запроса, по одному на часть; бюджет 3 не увеличен. |
| F5 | **VERIFIED (серверные части)** | Синтез `_server_parts` только при `insufficient_evidence` (`factcheck_service.py:954-962`); positive top больше не сопровождается выдуманными «данных недостаточно». `TestF5NoContradictoryParts` (service path). |
| F6 | **VERIFIED** | `image_not_analyzed` только при реальной строке ожидания Vision; готовый анализ без OCR = `image_analyzed=True`, без оговорки (`factcheck_service.py:232-243`). `TestF6ReadyNoText` + обновлённый `TestFC08Image`. |

## 3. FC, числа, тесты

- **FC-01** — механизм подтверждён офлайн (per-part queries + части в вердикте); строка `live_required`, поэтому **READY_FOR_LIVE** — реальная составная публикация в чате после выката.
- **FC-04** — офлайн доказан каскад Tavily→Exa (`TestF1CascadeRealPath`); реальные провайдеры — **READY_FOR_LIVE**.
- **FC-06** — **VERIFIED офлайн** сервисным путём: 0 evidence, `processing_failed`, `url=null` не появляются.
- **FC-09** — **VERIFIED офлайн** на кешевом пути: старый tf2-вердикт не отдаётся.
- FC-02/03/05/07/08 в этом лейне отдельно не переаудированы; регрессионный прогон зелёный, live-строки (02/03/05/08) остаются по карте.
- Обновлённые тесты не ослаблены: `test_semantic_queries_not_raw_slice` по-прежнему требует покрытия частей и года; `test_vaping_plan_queries_by_meaning_not_raw_slice` по-прежнему требует оба числа 16/40 и темы; изменение tf2→tf3 — следствие версии кеша.

## 4. Некритичные остаточные наблюдения (не блокируют выкат)

- **R2-N1 (F4, бюджет):** при двух частях и двух метриках последний слот уточнения достаётся первой части. Пример: «Курс вырос на 5 рублей. Инфляция составила 8 процентов.» → запросы `курс вырос рублей рост`, `инфляция составила процентов`, `курс вырос рублей рост 5`; «8» не попало ни в один запрос. Это следствие жёсткого бюджета 3, а не r1-дефекта «поздние части без запроса»; при желании лечится добавлением чисел части в её базовый запрос.
- **R2-N2 (F5, модельные parts):** `_aggregate_factual_verdict('supported', all-insufficient parts)` → `supported` (`temporal_factcheck.py:699`). Серверные части больше не синтезируются, но если модель сама вернёт positive top + все части `insufficient_evidence`, контраст остаётся; промпт-правило (10) и validator снижают вероятность.
- **R2-N3 (F1, тест):** тест каскада использует одноаргументные фейки и проверяет fallback, но не проверяет напрямую, что реальные `_search_exa`/`_search_ddg` получают бюджет; сигнатуры проверены чтением кода (все три `True`), не тестом.
- **R2-N4 (F2/F6, края):** в `evidence_rows_from_refs` остался fallback на `search_text`, если refs есть, но у всех пустой support (планировщик таких refs не производит — путь фактически мёртвый); при двух изображениях (одно готово, одно pending) notice говорит «проверен только текст сообщения», хотя OCR готового изображения уже в анализе. Локальные края, не влияют на F1–F6.

## 5. Можно ли в поезд и что осталось live

**Код — да, в контролируемый выкат**, при условиях:
1. PM привязывает `candidate_commit=5b692967…`, вносит evidence по F1–F6/FC-01/04/06/09 и r2-артефакту, ставит offline-строки `VERIFIED`, live-строки FC-01..05/08 — `READY_FOR_LIVE`; затем review-gate должен стать зелёным.
2. DevOps выкатывает **коммит**, не грязное дерево; откат — предыдущий `9051e9fe` (в нём checkup-лейн + factcheck-база), не `b93f1557`.
3. Пост-деплой канарейка: реальный фактчек известной публикации → в логах Tavily fail → Exa ok; `pipeline_version=tf3`; evidence с URL; старый tf2-кеш не отдан; на URL-less выдаче — `processing_failed`/`source_missing`; изображение с OCR → текст в claim; реальный LLM даёт части. При провале — откат на `9051e9fe`.

Осталось live: FC-01, FC-02, FC-03, FC-04, FC-05, FC-08 (реальные провайдеры/LLM/Vision/чат). FC-06/09 закрыты офлайн; FC-07 — вне переаудита этого лейна.

## 6. Итог

`Approved for controlled deployment` для слайса FACTCHECK; **parent не DONE**: канонический review-gate красный из-за необновлённой карты (42 строки PENDING, пустой candidate), а live-строки требуют пост-деплой канарейки. F1–F6, ради которых делался rework, закрыты; блокирующих дефектов кода не найдено.
