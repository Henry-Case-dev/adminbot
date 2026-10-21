# FC-R1 — реализация и офлайн-верификация (FIX-FACTCHECK-R1, 22.10.2026)

Слайс CFG-06 (волна 2.58.107). Основание: диагноз
`plans/features/factcheck-run-diag-2026-10-21.md` + директива владельца
`plans/features/owner-corrective-followup-2026-10-21.md` §3.2–3.6.
ARCH_REUSE_CONFIRMED: новых контрактов/пайплайнов нет — переиспользованы
VERIFIED planner (`factcheck_planner.build_retrieval_plan/run_retrieval/
EvidenceMap`), `SafeFetcher.fetch_text` (через `fetch_primary_evidence`),
каскад `SearchAggregator`. Второй Factcheck Pipeline не создан
(единственный сервис `FactCheckService.check_claim_envelope`).

## Что изменено (фикс → файл:строка)

1. **FC-UNIFY (§3.2 единый механизм).** Условие `not use_envelope` снято —
   retrieval-план выполняется для ОБЕИХ веток
   (`services/factcheck_orchestrator.py:481`, передача в envelope-ветку
   `:501`, `_run_envelope_branch(..., retrieval=...)` `:557–566`); сервис
   принимает выдачу контура параметром и не строит второй поиск
   (`services/factcheck_service.py:538,576–582`), evidence собирается из
   структурных строк планировщика (`evidence_rows_from_refs`,
   `services/temporal_factcheck.py:1239`) с сохранением primary-выдержек
   SafeFetcher и уже извлечённых дат. Версии контура: `fcv2→fcv3`
   (`factcheck_orchestrator.py:66`), `tf1→tf2` (`temporal_factcheck.py:62`),
   `fp1→fp2` (`factcheck_planner.py:41`) — старые кеш-записи выпадают (D13).
2. **FC-SEMQUERY (§3.3 смысловые запросы).** Запросы строятся от
   самостоятельных частей клейма (claim_items/предложения, privacy-фильтр
   на каждую часть): `factcheck_planner.py:240 (_claim_units)`, `:311–345`
   (per-unit entity/numeric/temporal/origin), generic синонимы без
   предметных терминов `:125–159`; fallback-поиск сервиса тоже смысловой —
   `search_queries_for` переписан (`temporal_factcheck.py:923–972`) вместо
   слайса `normalize_text(claim)[:200]`. Бюджеты сохранены: ≤3 запроса,
   ≤200 символов.
3. **FC-EVIDQ (§3.4 качество выдачи).** Overlap-эвристика без ранжировщика:
   `content_terms`/`is_relevant_result` (`search_aggregator.py:57–99`),
   relevance-вход каскада `search(..., relevance_terms)`/`search_relevant`
   (`:149,193`) — нерелевантная непустая выдача уровня не останавливает
   каскад; вызов из планировщика `factcheck_planner.py:517` и fallback-петли
   сервиса (`factcheck_service.py:592`). URL ≠ доказательство: primary-fetch
   только строк с overlap'ом (`factcheck_planner.py:573`); дубли url=None
   срезаны внутри выдачи и между запросами (`evidence_refs_from_search`
   `:358`, `run_retrieval` `:530–545`, `evidence_rows_from_results`
   `temporal_factcheck.py:1200`); тип источника — лёгкие признаки
   домена/структуры `classify_source_kind` (`search_aggregator.py:101`,
   primary/research/reference/secondary) без LLM.
4. **FC-PERCLAIM (§3.5 per-claim вердикты).** Серверная агрегация enum из
   частей: `_aggregate_factual_verdict` (`temporal_factcheck.py:677–708`) в
   `verdict_from_payload` `:711` — одна стадия-схема для аналитика и
   validator'а, поэтому corrected-коррекция больше не прячет подтверждённые
   части (production-трасса «verdict corrected»). Промпты дополнены
   правилами (9)/(10) и цитатами частей (TEMPORAL_ANALYST_SYSTEM `:975`,
   VALIDATOR `:1019`); текст частей обогащается серверной декомпозицией
   (`verdict_from_payload`, блок «части модели дополняются текстом»);
   `parts.evidence_refs` под тем же allowlist §18G.3.
5. **FC-RENDER (§3.6 оформление).** Renderer привязывает ссылки к
   утверждениям («По утверждениям:», `factcheck_renderer.py:191,246`),
   объясняет роль каждого источника (`_SOURCE_KIND_LABELS` `:71`,
   `_sources_rows` `:219`), показывает только процитированные URL при
   наличии цитат (`_content` `:155`), url=None в источниках не участвует;
   вербализация и даты/числа/оговорки не тронуты. CheckedVerdict получил
   необязательные internal-поля `evidence_refs`/`parts`
   (`factcheck_orchestrator.py:142–143`), заполняются из run.verdict
   (`:566–607`).

## Офлайн-верификация (LLM/поиск — моки, Telegram не использовался, 0 платных вызовов)

Набор `tests/test_factcheck_fc_r1_fix.py` — 22 теста, TEST-LIFECYCLE:
CONTRACT owner=FC-R1. Регрессия: фактчек/temporal/aggregator-наборы 502
passed (`pytest -k "factcheck or temporal or aggregator"`), mca17c 15 passed.

Вейпинг-кейс (replay tfr-b900e314f9024379, полный путь
query → search → fetch → evidence → verdict → response):

| Было (prod 2.58.106) | Стало (кандидат, офлайн-replay) |
|---|---|
| запросы — слайс первых 200 символов («…свис 2026») | смысловые запросы из частей: «болезнь лёгких … вейперов врачи …», «… электронных сигарет … 16 40», интент numeric по числам |
| envelope-ветка не выполняла план (поиск отдельно) | план выполнен единым контуром, выдача в сервисе, второй поиск отсутствует |
| snippet-only, SafeFetcher только для дат, 6/7 date_parse_failed | primary-выдержки SafeFetcher (cdc.gov) с published_at=2026-04-10 (parsed); типы источников reference/primary |
| вся выдача про EVALI, «ХОБЛ/числа» нет, первый непустой уровень — ответ | нерелевантный уровень каскада пропускается (overlap-эвристика), дубли url=None срезаны |
| вердикт insufficient_evidence/unknown (validator «corrected»), reason=null | mixed («Подтверждается частично»): EVALI-часть supported, числа — недостаточно; validator-коррекция части не прячет |
| bold «Недостаточно данных» + список 6 хостов (вкл. instagram) без объяснения | «По утверждениям:» с цитатой ev-1 у подтверждённой части + источники с ролями («— энциклопедия», «— первоисточник»); непроцитированных хостов нет |

Дополнительно: multi-claim варианты (2 синтетических многочастных
сообщения: all-supported → supported; refuted+insufficient → mixed с
видимым разбором), honest insufficient при отказе движков сохранён,
`search()` без relevance_terms — прежнее поведение (сводки не затронуты).

## Ограничения

- Live-часть (реальный Telegram-ответ на живом прогоне) не выполнялась по
  режиму лейна (offline); фиксируется в `owner_live_checks` как
  необязательная наблюдательная позиция, релизу не блокер (PET_PROJECT
  standing rule).
- Исходный JSON аналитика и per-URL провайдер в prod не персистятся —
  поведение до/после сравнено на сохранённых данных диагностики + моках.
