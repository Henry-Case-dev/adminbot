# Сверка устаревших строк progress_scope.json (PM, 30.10.2026, один ограниченный проход)

Проверка: статусы required-строк в картах каждой задачи + краткий git log (HEAD 3193b657). Файл — рекомендация;
`plans/progress_scope.json` НЕ редактировался (единый писатель — оркестратор). Итог: **9 строк, из них 4 —
«уже завершена, нужен статус-фикс», 1 — «закрыта за одним внешним наблюдением», 4 — содержат реально открытый
остаток (частично поглощается EVOL)**.

| Задача | Статус в scope | Факт по карте required | Верdict | Остаток и связь с EVOL |
|---|---|---|---|---|
| soul-1 | BUILDING | 259 VERIFIED, 1 READY_FOR_LIVE (SOUL-AMD.8.11) | **(b) завершена — статус-фикс** | R4L — постдеплой-наблюдение на естественных событиях; по правилу PET_PROJECT не блокер. Оркестратору: статус → VERIFIED (инженерно) либо документированное WAITING_EXTERNAL-наблюдение |
| asap8-v6.3 | BUILDING | 196 VERIFIED, 3 READY_FOR_LIVE (REQ-B09-BODY, B10-R10, REQ-B11-E2E) | **(b) завершена — статус-фикс** | аналогично soul-1: постдеплой-наблюдения, не блокеры |
| cfg-01-07 | BUILDING | 247 VERIFIED, открытых 0 | **(b) завершена — статус-фикс** | BUILDING устарел; проверить отсутствие неразнесённого evidence и закрыть |
| asap-speech-arch | BUILDING | 331 VERIFIED, 76 PENDING, 7 FAILED, 1 READY_FOR_LIVE | **(a)+(c) частично поглощается EVOL, остаток открыт** | UI-хвосты (T-UI-MATRIX/TEXT/STATE, T-GLASS-PERF, T-PREVIEW, REP-FORMAT) покрываются EVOL-041/042/043/045 и контрактом 033; миграционные MIGR-CACHE/MIGR-VERIFY — механизмом EVOL-016/018. Неперекрытые строки (REQ-PREFIX-SEP, REQ-SCOPE, REQ-EMBED, ANTIPATTERN-MATRIX, ADD-EXPR-INTENSITY и др., ~полсотни) остаются отдельной работой под asap-speech-arch; перед EVOL-UI-SPEECH/INSPECTOR нужна точечная ревизия этой карты, чтобы дубли не строились дважды |
| asap2-direct-chat | BUILDING | 108 VERIFIED, 2 PENDING (MIGR-PAYLOAD, MIGR-HOTAPPLY) | **(c) малый отдельный остаток** | только миграционные/DevOps-снимки; EVOL не покрывает; закрыть точечным DevOps-evidence вне EVOL |
| asap3-corrective | BUILDING | 232 VERIFIED, 2 PENDING (MIG-SCOPES, AUD-PROD-VERIFY) | **(c) малый отдельный остаток** | миграция scopes + прод-аудит; смежно с темой EVOL-040, но acceptance — собственные строки; закрывать вне EVOL |
| p0-factcheck-speech | BUILDING | 581 VERIFIED, 2 PENDING, 1 FAILED (REQ-EX-STABLE-EFFECT) | **(a)+(c)** | механизм «инструкция реально доходит до модели» перекрывается EVOL-012/016/018; конкретные Expression-приёмки (REQ-EX-STABLE-EFFECT, REQ-ADD3-EX-ACC-EFFECT) остаются собственным долгом задачи; REQ-DONE-MAIN-CRITERION — общий критерий закрытия, закроется итогом EVOL/эпика |
| p0-factcheck-media | BUILDING | 151 PENDING (реализация не начиналась) | **(c) отдельная всё ещё открытая работа** | фактчек изображений/альбомов/пересылок в EVOL не входит; не маппить в EVOL, не закрывать — назначить отдельную волну после/параллельно W1 (scope disjoint) |
| p0-factcheck-post-release | BUILDING | 60 VERIFIED, 1 READY_FOR_LIVE (FC-05B) | **(b) инженерно закрыта** | FC-05B — наблюдение частоты ложных отрицаний на живой поисковой выдаче (естественные события); статус → WAITING_EXTERNAL с условием наблюдения, инженерного блокера нет |

## Рекомендации оркестратору (без правки из PM)

1. Статус-фикс для soul-1, asap8-v6.3, cfg-01-07, p0-factcheck-post-release — одна командная правка `progress_scope.json`
   (BUILDING → VERIFIED/WAITING_EXTERNAL по фактическим статусам карт).
2. Контракт запуска EVOL (строка 13 источника) требует подтвердить завершение предыдущих задач до изменения кода:
   открытые остатки (c)/(a) — asap-speech-arch (~83 строки), asap2 (2), asap3 (2), p0-factcheck-speech (3),
   p0-factcheck-media (151) — **не блокируют** слайсы EVOL с непересекающимся scope, но: (а) EVOL-UI-SPEECH/
   INSPECTOR/CONTROLS обязаны свериться с картой asap-speech-arch перед реализацией; (б) p0-factcheck-media
   целесообразно поставить в очередь отдельным лейном, не теряя из виду.
3. Дублирования источников нет: у всех девяти задач свои immutable-снапшоты и карты; в EVOL перенесены только те
   обязательства, которые прямо названы в EVOL-документе.
