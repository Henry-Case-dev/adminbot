# embed-identity-compat — план (P0, 23.10.2026)

**Приоритет:** P0. Блокирует рестарт и деплой.
**Прод сейчас:** 2.58.111 @ `fbf9013d`, `/healthz` 200; векторная память FTS-only (16 003 старых Google-векторов, 4 048 фактов без векторов, поколения `building` с 29.09).
**Поезд 2.58.112:** собран (`678c0616`, 57 файлов, ΔDDL=0), но **не задеплоен именно из-за этой задачи**.
**Правило:** до реализации ни одного рестарта с текущим identity-кодом — рестарт запустит полную перевекторизацию (~15 819 фактов).

## Что меняется в поведении `5877810d`

Сейчас: `embedding_identity_fingerprint()` = sha256(provider|model|dims|preproc|endpoint) (`services/summary_memory.py:432`); любой другой fingerprint → `classify_identity_compatibility()` = `REINDEX_REQUIRED` **до** canary (`services/embedding_control_plane.py:2264`); `graphrag_rebuild` строит поколение под новый fp, `_index_generation_ok()` (`summary_memory.py:1877`) закрывает vec-поиск.
Хуже: canary-эталоны лежат в `embedding_cache` под identity (`embedding_control_plane.py:2314`) — после смены identity они создаются новым провайдером, т.е. сравниваются new-vs-new. Это ровно запрещённый ТЗ случай (L35).
Должно стать: **сначала canary по старым сохранённым векторам и их текстам**; rebuild — только при доказанном расхождении; при совместимости старый индекс продолжает работать.

## Архитектура

`ARCH_REUSE_CONFIRMED` (`arch-design.md`, 23.10) — контракт зафиксирован без новых таблиц/сервисов: persisted `identity_fingerprint` остаётся провенансом, MSI/PCI разделены, семантика `classify_identity_compatibility` — три исхода + durable-допуск, canary-эталоны — только старые live-векторы, legacy-отпечатки читаются без перезаписи. ΔDDL=0; вопрос владельцу не требовался.

## Слайсы (`slice-graph.json`, 59 required / 13 context / 0 unclassified)

| id | depends_on | write scope | исход |
|---|---|---|---|
| IDENT-SPLIT | — | control plane, summary_memory (identity), unit | R2 |
| CANARY | IDENT-SPLIT | control plane (canary), unit | R2 |
| DECISION | CANARY | control plane, graphrag_rebuild, matrix | R3 |
| INTEGRATION | DECISION | summary_memory, graphrag_rebuild, control plane, MiniApp API | R2 |
| GOV | INTEGRATION | evidence/gov-report.md (аудит) | R1 |
| ACCEPT | все + GOV | accept-тесты, evidence/ | R2 |

**Волны:** W0 Architect → W1 IDENT-SPLIT → W2 CANARY → W3 DECISION → W4 INTEGRATION → W5 GOV → W6 ACCEPT.
**Параллельность:** независимых writer-полос нет — четыре слайса правят `services/embedding_control_plane.py`; ACCEPT-тесты можно писать после DECISION, запускать только на join. Это осознанная сериализация, не микрозадачи.
**Готово к работе сейчас:** ничего — единственный вход `ARCH-EMBED-IDENTITY`; Builder ждёт замороженный контракт.
**Внешний факт:** отдаёт ли apinet/шлюз ревизию модели — проверяется probe'ом, а не предполагается. Недоступная ревизия/параметры **не** делает вердикт неопределённым: если векторная проверка (старые live-векторы + KNN-hit5) уложилась в пороги §3, фиксируется `compatible` с пометками `revision_unknown`/`params_unknown` (frozen `arch-design.md:12` — ревизия «если известна»). `insufficient_data` — только при недостаточности самого векторного доказательства; в обоих случаях автоматического rebuild нет.

## Приёмка и live

10 сценариев ТЗ — отдельные `ACC-01…ACC-10` (включая search-level и реальную семантику). `ACC-10` и `ACC-11` (критерий «индекс работает без полной перевекторизации») — `live_required`, `postdeploy`; остальные — preprod/интеграционные с фикстурой реального индекса. `ACC-13` — отчёт «как определена совместимость и почему», `ACC-14` — запрет заявлять совместимость без измерений.
**Запреты (GOV):** без новых сервисов/таблиц/реестров моделей/агентов, без хардкода под API.NET/Gemini, без сравнения только имён, без ручного переписывания fingerprint, без потери истории/фактов/графа/досье.
**Backlog:** не заводим — это P0-корректировка текущей архитектуры, а не отложенная находка; старые пункты аудита 23.10 не дублируются.

## Что дальше

1. Orchestrator ждёт `ARCH-EMBED-IDENTITY` и передаёт замороженный контракт Builder'у на `IDENT-SPLIT`.
2. Деплой 2.58.112 не выполнять; после реализации — объединённый поезд 2.58.113 и один рестарт, где canary решает «старый индекс / insufficient / миграция».
3. До доказанной совместимости векторный поиск на проде остаётся FTS-only — это ожидаемое состояние, не регресс.

## Статус 23.10.2026 (после ревью)

* Реализация: `30a2f868` + фикс B1/B3 `570e1eee`; контрактные и restart/legacy-тесты — 29 passed, смежные identity/graphrag/API — 39 passed (прогон PM).
* Карта привязана к `570e1eee`: 59 required → **54 VERIFIED**, **2 READY_FOR_LIVE** (`ACC-10`, `ACC-11`, postdeploy), **3 PENDING** (`IDENT-02`, `CANARY-03`, `DEC-09`) с конкретным `next_check`. Детали и evidence — `binding-2026-10-23.md`.
* A0-проба на реальных прод-данных: `compatible`, `checked=12`, `mean/min/hit5=1.0`, top-1 KNN 42/42, прод не изменён (read-only). Проба выполнялась на `30a2f868`; функции пробы/порогов байт-идентичны `570e1eee`.
* B3 остаётся `NEEDS_AGENT_CHECK` до pre-deploy прогона `resolve_index_compat` на read-only копии прод-БД: A0 не фиксировал `state/reason_code/candidate` для реальных legacy-строк.
* Деплой не выполнен. Следующий шаг: закрыть 3 PENDING (малые тесты + решение Architect по revision), выполнить pre-deploy resolve-пробу, затем объединённый поезд 2.58.113 и postdeploy-проверки `ACC-10/11`.
