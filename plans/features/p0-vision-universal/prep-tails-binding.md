# Prep: tails-binding recon — p0-vision-universal (requirements-map.json)

Рекон PM (LANE PM-TAILS-RECON), 2026-10-22. Read-only по карте; файл — рекомендации для биндинг-лейна.
Метод: каждая PENDING/READY_FOR_LIVE-строка просмотрена; evidence указан только реально найденный.
Волны доставки: fix-core 76b156e0 (review 1c4e6675 Approved), UI 88593e9a (review 0df4a4a8 Approved), живые ACCEPTANCE-91 (f2a6248a) / 92 (1d367e4c) / 94 (9072347b) / 95 (113f3a62 = deployed_commit карты; биндинг accept-95 cd4dfb32); postgen-diag retry 61ecd034 (review b2eebead Approved) — в линии 2.58.95.

## Счётчики (11 открытых строк: 10 PENDING + 1 RFL)

| Вердикт | строк |
|---|---|
| REUSE (доставлено волной, нужен только биндинг evidence) | 4 |
| REAL_WORK (есть остаток работы) | 1 (P0V-PIPE-CONTEXT, RFL; ядро acceptance уже имеет live-позитив) |
| CONTEXT (уже disposition=context) | 5 |
| OWNER_OPTIONAL (уже tier=owner_optional) | 1 |

## REUSE — доставлено, биндинг evidence (4)

| Строка | Чем доставлено | Указатель для биндинга |
|---|---|---|
| P0V-WF-QUEUE | Исполнена как приоритетная добавка в общую очередь: не прервала идущие задачи, очередь продолжилась (поезда 2.58.91–95 затем 96–107) | alias cfg:ADD-0.Q/ADD-0.1; git log 8bc8e9b5→35b8b455; accept-95 cd4dfb32 |
| P0V-WF-STANDARD | Существующий workflow соблюдён: независимые ревью Approved, штатные деплои, отдельный эпик не создан, deployed_commit привязан (113f3a62) | review-vision-core.md (1c4e6675), review-vision-ui.md (0df4a4a8), review-postgen-diag (b2eebead), review-accept-95 (112cfcc0) |
| P0V-TEST-MATRIX | Матрица собрана: mock-классы (400/no_vision/таймаут/ключ/URL) — mock-matrix; endpoint-формы/изоляция ключей/ротация — green; live: 429 (91 scenario-2, 92 s5), 5xx (92C nemotron 502), таймаут (95 TimeoutError), смена провайдера без правок кода (92 §5 hot-конфиг). Модель без Vision — только mock-класс (живой no-vision модели не было) — честно покрыть через M-P0V-09 (мок ≠ живой) | evidence/fix-core/mock-matrix-2026-10-19.md; green-2026-10-19.txt; release-25891/acceptance/scenario-2-vision-probe.json; release-25892/acceptance/s5-vision-probe.json; 92C-эвиденс (recon 502/429) |
| P0V-TEST-MOCKS | Отчёты различают мок-контракт и живые пробы (типы test vs production в evidence-записях; mock-матрица явно названа моками) | те же README acceptance 91/92/94/95 + mock-matrix-2026-10-19.md |

## REAL_WORK — остаток (1)

| Строка | Что осталось | Объём |
|---|---|---|
| P0V-PIPE-CONTEXT (RFL) | Ядро acceptance («изображения реально распознаются и используются в контексте») уже наблюдено live: 94 §(b) — анализ id=5 ready (388 симв.) дошёл до ответа (mid 1166167, содержание совпадает). Остаток accept-95: тяжёлые фикстуры (PNG 1.3 MB) — терминальный failed/parse_error (не-JSON ответ free-модели, GT 0/8) и пустой postgen detail (timeout). Retry-alpha (61ecd034, heavy-payload retry) уже в 2.58.95 и не решил не-JSON кейс | Малый–средний: 1 live-окно «тяжёлый кадр → ready+GT» (штатная смена vision-модели или повтор пробы); биндинг-лейн может bindings b1 как выполнение acceptance-as-written с честным residual-пином (не-JSON тяжёлых кадров — бэклог) — решение за биндинг+Reviewer, RFL не снимать молча |

## CONTEXT (5) — disposition=context уже проставлен
L00009 (§1 заголовок), L00018 (§2 заголовок), L00028 (§3 заголовок), L00033 (§4 заголовок; note про несобранный UI-срез устарел — P0V-UI-* закрыты волной 88593e9a), L00040 (§5 заголовок; NF-пины — процессные заметки).

## OWNER_OPTIONAL (1) — уже консолидировано
P0V-OWNER-VISUAL (owner_optional, engineering_req_ids=[P0V-DOD, P0V-PIPE-CONTEXT, P0V-PIPE-E2E], owner_policy_ref=plans/owner_live_checks.md §3–§4).

## Примечания биндинг-лейну
1. P0V-PIPE-E2E/P0V-SYMPTOMS/P0V-DOD уже VERIFIED (91–95) — не трогать.
2. Для P0V-PIPE-CONTEXT допустимый исход биндинга: (а) VERIFIED на b1+95-эвиденсе с честной нотой про тяжёлые кадры, либо (б) остаётся RFL до живого «тяжёлый кадр → ready». Оба варианта честные; выбор фиксировать в reason, не маскировать.
3. Живые пробы — harness-метод ACCEPTANCE-94/95; бюджет платных вызовов фиксировать в отчёте волны.

---

## Исполнение (LANE LEDGER-TAILS-BIND, 22.10.2026)

Все 4 REUSE-строки → VERIFIED, candidate-bound на 113f3a62 (map candidate/deployed) + core-артефакты @76b156e0 и ревью @1c4e6675/0df4a4a8 по prep-указателям. Каждый evidence-файл открыт, SHA256 сверен probe-прогоном. P0V-PIPE-CONTEXT НЕ тронут (REAL_WORK/RFL — решение за отдельным лейном, правило 4 брифа). deployed_commit карты уже был 113f3a62 — не менялся.

Гейты:
- `plan` → EXIT 0 (inventory=24, manual=14, errors=0).
- `review --slice P0V-ACCEPT --candidate 113f3a62` → rc=1, ровно 2 чужих исторических остатка: P0V-SYMPTOMS (bound @76b156e0/1d367e4c), P0V-DOD (bound @76b156e0/9072347b) — VERIFIED-строки прежних волн. Мои 4 строки: 0 собственных ошибок (все bound @113f3a62).
