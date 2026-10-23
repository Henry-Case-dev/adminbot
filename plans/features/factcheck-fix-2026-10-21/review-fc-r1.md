# REVIEW — FC-R1 (factcheck fixes), лейн REV-FACTCHECK-R1, 22.10.2026

**Вердикт: Approved.** Кандидат: код **97818475** + карта **50c825ab** (HEAD). База для поезда 2.58.107.

## Леджер приёмки (обязательные позиции — все VERIFIED)

| Требование | Статус | Доказательство (независимо воспроизведено) |
|---|---|---|
| FC-UNIFY §3.2 | VERIFIED | Код: условие `not use_envelope` снято (orchestrator:481), retrieval → `check_claim_envelope(retrieval=)`, сервис не строит второй поиск (service:576–582), evidence из структурных строк (`evidence_rows_from_refs`); версии fcv3/tf2/fp2. Legacy-ветка и не-temporal маршрут не изменены (тот же путь search_results, что в W6). Тест `test_envelope_branch_unified_retrieval` + replay полного пути. |
| FC-SEMQUERY §3.3 | VERIFIED | Запросы от `_claim_units` (claim_items/предложения) с per-unit `_strip_privacy`; generic синонимы без предметных словарей; **немедицинский тест** (криптовалюты/биржи, `forbidden in ("evali","хобл",...)` — не зашито); бюджеты ≤3 запроса/≤200 симв. в коде (`_QUERY_MAX_CHARS=200`) и в тестах (:124–127,148–151); `search_queries_for` переписан (fallback тоже смысловой). |
| FC-EVIDQ §3.4 | VERIFIED | `is_relevant_result` overlap-порог (≥2 и ≥20%); каскад: нерелевантный уровень → ValueError → следующий провайдер (тест `test_irrelevant_first_level_continues_cascade`); all-irrelevant → честный отказ; primary-fetch только overlap-строк, `_MAX_PRIMARY_FETCHES=2`; дедуп url=None на 3 уровнях (внутри блока, между запросами, в evidence_rows); `classify_source_kind` без LLM; **Summary-инвариантность**: `search()` без `relevance_terms` — прежнее поведение (search_service не тронут, тест `test_search_without_terms_unchanged`). |
| FC-PERCLAIM §3.5 | VERIFIED | `_aggregate_factual_verdict` внутри `verdict_from_payload` — одна стадия-схема; `apply_validator` проходит merged (с parts) через тот же guard → **prod-трасса воспроизведена тестом** `test_validator_cannot_bury_supported_parts` (corrected insufficient не прячет supported-часть); parts evidence_refs под allowlist §18G.3 (ev-99 срезан); честный insufficient сохранён (all-parts-insufficient, пустой поиск — серверный форс). |
| FC-RENDER §3.6 | VERIFIED | Replay-тест полного пути: bold «Подтверждается частично», «По утверждениям:» с цитатами у тезисов, роли («— энциклопедия/первоисточник/пересказ»), URL только в href, мусорного списка/instagram нет; url=None исключены (`_refs_by_id` фильтрует без-url); legacy plain-путь без вердикта прежний; egress-guard для internal-полей проверен тестом. Сравнение с тем, что видел владелец (bold «Недостаточно данных» + 6 безадресных хостов) — was/now таблица артефакта соответствует diag tfr-b900e314f9024379. |

## Запущено/проверено (воспроизведено в этом ревью)

- `tests/test_factcheck_fc_r1_fix.py` — **22 passed** (CONTRACT owner=FC-R1; утверждают контракт владельца, не реализацию).
- Регресс `-k "factcheck or temporal or aggregator"` — **502 passed** (exit 0).
- mca17c (oversight_api + invariants) — **23 passed**.
- План-гейт: `requirements_gate.py --stage plan` (cfg map) — **EXIT 0** (inventory=246, errors=0).
- Review-гейт: все 5 FC-строк имеют evidence, привязанный к 97818475, с реальными `artifact_path`+sha256 (оба хеша совпали с файлами).
- Старые тесты cfg06: обновления контракт-драйвены (архитектура §3.2 владельцем отменена — `agg.calls == []` заменён на ассерты единого контура + privacy), ослабления нет.

## Риски (все nonblocking)

1. **Cross-lingual релевантность**: русскоязычные термины запроса не совпадут с англоязычной релевантной выдачей → каскад продолжится и может честно исчерпаться → insufficient (precision>recall, консервативный порог, honest degradation). Не нарушение контракта.
2. **Cache-hit без parts**: temporal-кеш не персистит parts/evidence_refs — повторный прогон по кешу рендерит вербализованный текст без блока «По утверждениям» (TTL-bounded; прежний паттерн W6, не регресс кандидата). Кандидат на будущую доработку.
3. **Whole-slice review-гейт**: `--stage review --slice CFG-06 --candidate 97818475` даёт EXIT 1 по ~46 СТАРЫМ строкам слайса (привязаны к кандидатам своих волн 5af56d8b…), не по FC-*. Известная семантика слайс-скопа (прецедент recheck-r1/r2). На `--stage release` поезда 2.58.107 потребуются двойные записи/перепривязка по устоявшейся процедуре — учесть при релизе.
4. `owner_live_checks.md` не содержит отдельной FC-R1-строки; стоящая политика (§6 файл, PET_PROJECT 18.10.2026) уже покрывает необязательность личной live-проверки — замечание документационное.

## Ограничения (честно зафиксированы Builder'ом)

- Live-часть — owner_optional по standing rule; релизу не блокер.
- Исходный JSON аналитика и per-URL провайдер в prod не персистятся — replay построен на сохранённых данных diag + моках; полного байт-в-байт prod-сравнения нет, контракт покрыт тестами на всём пути query→search→fetch→evidence→verdict→response.

## Параллельный лейн

Незакоммиченные файлы corrective-лейна не ревьюились и не влияют на кандидата; карта requirements-map.json в рабочей копии чиста.

**Блокеров нет. Approved: 97818475 + 50c825ab → поезд 2.58.107.**
