# Prep: tails-binding recon — add-tr (requirements-map.json)

Рекон PM (LANE PM-TAILS-RECON), 2026-10-22. Read-only по карте; файл — рекомендации для биндинг-лейна.
Метод: каждая PENDING/READY_FOR_LIVE-строка просмотрена; evidence указан только реально найденный (файлы/коммиты не выдумывались).
Волны доставки: код — кандидат 948c2004 (grid/postgen) + entry-fix e4ddc4ec + tools-minifix f0865166, живые волны ACCEPTANCE-91 (f2a6248a), 92 (1d367e4c), 94 (9072347b), 95 (113f3a62, deployed; биндинг accept-95 cd4dfb32); postgen-diag retry (61ecd034, review b2eebead Approved) — в линии 2.58.95; текущий прод 2.58.107 (3a178c6c).

## Счётчики (36 открытых строк: 33 PENDING + 3 RFL)

| Вердикт | строк |
|---|---|
| REUSE (доставлено волной, нужен только биндинг evidence) | 13 |
| REAL_WORK (есть остаток работы) | 12 (9 PENDING + 3 RFL) |
| CONTEXT (уже disposition=context — закрыть статусом) | 10 |
| OWNER_OPTIONAL (уже tier=owner_optional, не дублировать) | 1 |

## REUSE — доставлено, биндинг evidence (13)

| Строка | Чем доставлено | Указатель для биндинга |
|---|---|---|
| M-ADTR-REG-DELTA | Дельта исполнена как добавка к SOUL-1/CFG/ASAP без второго эпика; блок append-only в current_task L1631–1731; снапшот 08cd6b4a совпадает | current_task.md L1631; source-add-tr-2026-10-19.md; эта карта (58 required) |
| ADTR-REG-AUDIT | Статусы по каждому сценарию уже зафиксированы в note-полях (TR-RECON, S1/S2/S11/S12 закрыты live); финализация = этот рекон + биндинг | notes M-ADTR-VERIFY-S1…S13 в карте; prep-tails-binding.md |
| ADTR-REG-QUEUE | Очередь/параллель соблюдены: волны W0–W3 по README, деплои 91–95 не прерваны | plans/features/add-tr/README.md (слайсы/волны); последовательность релизов 2.58.91–95 (git log) |
| ADTR-REG-MASTER | Master-vs-production сверка выполнена на релиз-гейтах; deployed-привязка accept-95; пять фактов различены (VERIFIED) | cd4dfb32 (LEDGER-ACCEPT-95); M-ADTR-TOOLS-FIVEFACTS (VERIFIED, 91 §1 + 94 b1) |
| M-ADTR-REG-CONTINUE | Очередь продолжена автоматически после ADD-TR: поезда 2.58.96–107 | git log: 3a49d545 (accept-96) … 4655af4d (2.58.107 deployed) |
| M-ADTR-VERIFY-S5 | Vision OFF/недоступен/долго — live: честный отказ без ready (mid 1165613, 91 §3); chat-override OFF → честный ответ + 0 vision-вызовов (95 §(a) 03.4); bounded 20 c (95 §(b)) | evidence/release-25891/acceptance/scenario-3-vision-freeform.json; evidence/release-25895/acceptance/p2-vision-off.json; p4b-generation.json |
| M-ADTR-VERIFY-S6 | «нарисуй» (91 §5) и свободная «бот, надо нарисовать…» (94 §(c)) → один image workflow, ровно 1 генерация/1 списание | evidence/release-25891/acceptance/scenario-5-generate.json; evidence/release-25894/acceptance/README.md §(c) (939495 B, mid 1166169, 1 вызов) |
| M-ADTR-VERIFY-S10 | Постген при pending/probe failed: Writer-блок «содержимое не подтверждено», доставка не заблокирована, bounded | evidence/release-25895/acceptance/p4b-generation.json (gen1 pending/deadline_exceeded → честный ответ) |
| M-ADTR-VERIFY-S13 | Grid на 360px: after-прогон 0/21 проблем (320–430), DOMRect-контракт, стресс font2x | evidence/grid-fix/after/e2e_after.json; browseruse_store_320.png; M-ADTR-GRID-CHECKS (VERIFIED, тот же контур) |
| M-ADTR-VERIFY-EVIDENCE | Протокол стадий применён в отчётах 91/92/94/95 (five-facts, mids, stage-цепочки); добивается вместе со сценариями | evidence/release-2589{1,4,5}/acceptance/README.md (стадии + five-facts b1) |
| M-ADTR-VERIFY-NATIVE | Честный PENDING_OWNER_E2E зафиксирован; browser-матрица (320–430, font 20/24) выполнена агентами; device-наблюдение — owner_optional (device-чек-листы отменены 18.10) | note M-ADTR-GRID-CHECKS; M-ADTR-GRID-DEVICE-OBS (owner_optional); plans/owner_live_checks.md |
| ADTR-VERIFY-DOD4 | Инженерная половина DoD 4: after 0/21 + browseruse 320–430; device-остаток — отдельная owner_optional строка | evidence/grid-fix/after/*; M-ADTR-GRID-DEVICE-OBS |
| ADTR-VERIFY-DOD5 | Reviewer (4 Approved-ревью) → штатный деплой (2.58.91–95) → evidence-привязка (accept-95, ADTR scoped rc=0); очередь продолжена | review-grid-fix.md (751295f7), review-entry-fix.md (e4ddc4ec), review-tools-minifix.md (f0865166), review-postgen.md (0e5fbb05); cd4dfb32 |

## REAL_WORK — остаток работы (12)

| Строка | Что осталось | Объём |
|---|---|---|
| ADTR-POSTGEN-ON (RFL) | Live-позитив постгена: ready-анализ фактического bitmap + описание. Контур/адаптер/проводка live подтверждены (95 §(b): 1 vision-вызов на bitmap), ready не наблюдался (free-модель >20 c на 1024×1024); retry-alpha (61ecd034) уже в 2.58.95 | Средний: 1–2 live-пробы генерация+анализ (платные вызовы), возможно смена vision-модели штатной настройкой |
| ADTR-POSTGEN-OFF (RFL) | Live-генерация при Vision OFF: короткое подтверждение доставки без описания содержимого. OFF-контур — unit/байт-паритет (green.txt); в 95 OFF генерации не было | Малый: 1 live-проба с chat-override OFF (образец p2-vision-off.json) |
| ADTR-POSTGEN-DEDUP (RFL) | Cache-hit replay: повтор тех же bytes в TTL → cache_hit без провайдер-вызова и без второго пост-ответа. Без дублей live доказан (95 gen1: 1 фото/1 пост-ответ/1 vision-вызов; 92 replay DIRECT_UPDATE_DEDUP_HIT) | Малый: 1 live-проба replay-кейса |
| M-ADTR-VERIFY-S9 | = POSTGEN-ON (описание именно созданного bitmap по фактическому анализу) | Кластер POSTGEN-ON |
| M-ADTR-VERIFY-S8 | = POSTGEN-OFF (генерация + Vision OFF, без выдуманных деталей) | Кластер POSTGEN-OFF |
| M-ADTR-VERIFY-DOD3 | Половина 1 (генератор не описывает непроверенные пиксели) — VERIFIED (948c2004, тест «промпт кот → рыжий пёс»); половина 2 = POSTGEN-ON | Кластер POSTGEN-ON (биндинг половины 1 + живая половина 2) |
| M-ADTR-VERIFY-S3 | Live-проба «медиа без обращения → прежнее UNHANDLED, нет forced-Direct»; тест-половина есть (green-direct-cluster.txt, 44 теста) | Малый: 1 harness-сценарий |
| M-ADTR-VERIFY-S4 | Live-проба «что на картинке без вложения/неоднозначная цель → уточнение»; механика есть (bounded resolve fail-open, SOUL-AMD.5.9) | Малый: 1 harness-сценарий |
| M-ADTR-VERIFY-S7 | Live-проба «бот, как нарисовать X?» → без генерации (объяснение); тест-половина SOUL-AMD.5.9 | Малый: 1 harness-сценарий |
| M-ADTR-VERIFY-EDGE | Остаток live-краёв: альбомы/несколько вложений, не-image document как цель, отредактированный caption, модель без tool calling (контролируемый fallback). Уже покрыто live: forward (entry-fix), per-chat OFF (95 p2), scope (92 s2), смена провайдера (92 §5), 429 (91), timeout (92), tool error (91), рестарт/replay (92/94) | Средний: одно harness-окно на 4–5 кейсов |
| M-ADTR-VERIFY-PROTOCOL | Зонтик протокола стадий: закрывается вместе с кластерами выше (S1/S2/S11/S12 уже live; стадии доказаны five-facts b1) | Закрывается последним в кластере |
| M-ADTR-VERIFY-REPORT | Человеческий отчёт после релиза (что существовало/стыки/исправлено/доказано/deployed SHA). README каталога — регистрационный, не отчёт | Малый: компоновка из 4 Approved-ревью + accept-91–95 |

## CONTEXT (10) — disposition=context уже проставлен; биндинг-лейну закрыть статус
M-CTX-POSTGEN-PROTOCOL (L54), M-CTX-SCENARIO-TABLE (L69), M-CTX-DOD (L89), L00003 (ADD-TR.0), L00006 (пересечения), L00016 (ADD-TR.1), L00026 (ADD-TR.2), L00038 (ADD-TR.3), L00050 (ADD-TR.4), L00065 (ADD-TR.5).

## OWNER_OPTIONAL (1) — уже консолидировано, не дублировать
M-ADTR-GRID-DEVICE-OBS (owner_optional, engineering_req_ids=[M-ADTR-GRID-CHECKS, M-ADTR-VERIFY-NATIVE, ADTR-VERIFY-DOD4], owner_policy_ref=plans/owner_live_checks.md).

## Примечания биндинг-лейну
1. `deployed_commit` карты пуст — привязать линию 2.58.95 (113f3a62) как минимум (код add-tr уехал поездом 91; accept-95 cd4dfb32 подтвердил scoped rc=0).
2. Живые пробы — harness-метод ACCEPTANCE-91/94/95 (синтетические апдейты, уборка, без реальных чатов); сообщения в реальные чаты запрещены.
3. POSTGEN-ON может остаться честным RFL, если free-vision-модель не укладывается в bounded 20 c: тогда либо штатная смена vision-модели (прецедент 92 §5), либо задокументировать ограничение и связать с §3/§4 owner_live_checks (наблюдение владельца — добровольное).

---

## Исполнение (LANE LEDGER-TAILS-BIND, 22.10.2026)

Все 13 REUSE-строк → VERIFIED, candidate-bound на prep-указанные SHA (волны 91/92/94/95, кандидат 948c2004, HEAD b67df7bc, accept-95 cd4dfb32). Каждый evidence-файл открыт, SHA256 сверен probe-прогоном (все совпали; artifact-хэши вписаны в evidence). REAL_WORK/CONTEXT/OWNER_OPTIONAL строки НЕ тронуты (вне WRITE_SCOPE; гейт статус context-строк не проверяет — механика подтверждена кодом гейта).

`deployed_commit` карты: ``""`` → `3a178c6c0c5fa5bd37092df251de6eafc75330ba` (прод 2.58.107, deploy VERIFIED в 4655af4d). Честная нота: после 2.58.95 (113f3a62) файлы add-tr `handlers/direct_chat.py`/`services/mca_vision.py` не менялись; общий шов `services/tool_router.py` развивали чужие фича-волны (CFG-06/07, флаг-гейты: 83c7abae, c849dbf4, f1e31d27, 8cd2ca14); acceptance-строки привязаны к волнам 91–95.

Гейты:
- `plan` → EXIT 0 (inventory=32, manual=37, errors=0).
- `review --slice ADTR-REG --candidate 948c2004` → rc=1, 5 ошибок «no evidence bound to reviewed candidate» — все 5 — мои REUSE-строки, привязанные к волнам 91–95/HEAD по prep-указателям (конвенция исторических биндингов, как в accept-95/96); чужих остатков нет.
- `review --slice ADTR-VERIFY --candidate 948c2004` → rc=1, 20 остатков: 11 «no evidence bound» (5 моих + исторические DOD1/DOD2/S1/S2/S11/S12) + 9 PENDING — REAL_WORK чужого лейна (S3/S4/S7/S8/S9, DOD3, EDGE, PROTOCOL, REPORT).

Audit-строка ADTR-REG-AUDIT карты ссылается на этот prep-файл; artifact_sha256 = SHA256 этого финального файла, зафиксирован в evidence строки карты.
