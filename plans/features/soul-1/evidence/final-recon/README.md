# Final recon/bind — soul-1 (48 main + 12 amend строк), SOUL1-FINAL-RECON

Дата: 22.10.2026. База: HEAD `a7702559` (после a1d8bd62). Режим: writer (bindings + офлайн-проверки).
Метод: каждая строка из списков лейна сверена с acceptance и открытым evidence; указатели — только реально
существующие файлы/коммиты (префлайт-скрипт проверил каждый путь/тест/статус сиблинга до записи). FACTORY_SET
не менялся; 0 сообщений в Telegram; LLM-вызовы: 0 (все факты — из существующих артефактов).

## Счётчики (items + additional, до → после)

| Карта | VERIFIED | PENDING | READY_FOR_LIVE |
|---|---|---|---|
| main | 139 → **171** | 46 → **15** | 13 → **12** |
| amendment | 67 → **78** | 27 → **16** | 1 → **1** |

Остатки честны: main PENDING = 9 контекст-заголовков (вне скоупа лейна) + 4 user_excluded (конвенция карты) +
2 чужих процессных (EXEC.1/01.0/15.0/21.0 — вне списка 48); RFL = наблюдательные окна/внешние зависимости
(05.6, 08.12, 10.P5, 11.4, 12.1–.5, 19.3 + 14.2 нетронут + owner_optional 12.0/17.4) — ни один не является
кодовой задачей.

## VERIFIED — main (32)

| Строка | Основание биндинга (ключевое evidence) |
|---|---|
| SOUL-21.5 | A/B проведена 21.10: evidence/ab/report.md + final-report §5 (методика/качество/стоимость/регрессии/откат; оценка владельца — добровольное окно) |
| SOUL-EXEC.2/.4/.7 | process-row executed by epic: SOURCE_MANIFEST/plan/review-map Approved + финальный отчёт эпика + gate на release (gate-release-readonly.txt), SOUL-16–18 в отчёте наравне |
| SOUL-EXEC.9/.10/.11/.12 | честные статусы (прецедент 2.58.106 §14.2), evidence с SHA, минимальные фикс-циклы (68cd05b2; P0 29a95173 RED→GREEN+17/17; corrective 355p; vision-fence), Review+rollback на каждом релизе (capture-before, авто-откат, hash-bind) |
| SOUL-BOUND.1/.2/.3 | unified-core `29cc49ba` (11 путей один Core, 4 машинных чисты), withheld=11 + CFG-07A (markers 0), сравнение выборок по путям (окно-2 = AMD.8.1 VERIFIED) + A/B |
| SOUL-BOUND.5/.6/.7 | editorial eligibility (16.4.4 + machine_profile тест), анти-выдумывание (07A «в рамках фактов», 07D.2, фактчек v2/FC-R1, A/B ON отказал), негативы утечек (RBAC 16.4.3, 403-guard F1, 07C.2 67 CONTRACT) |
| SOUL-03.1/.3/.4 | данные целы (W1-реестр, кастом байт-в-байт), never-write + rejected:8 (live 2.58.106) + superseded-гвард, изоляция чатов (окно-2 AC2, w4 scenario_6, 17/17 P0) |
| SOUL-04.1 | UNIFIED-CORE: Search/Web/YouTube/Checkup/Factcheck/Summary через общий шов (final-report §1), manifest с precedence |
| SOUL-05.7 | матрица манер по пунктам: окно-1 §2 (one_word/micro), W3-тесты, A/B 11 типов, W5+corrective `47522e7b` (SILENT/REACT в каноне L1, протокол 4/4), tool-result (AMD.2.7 + 07C.5) |
| SOUL-09.3 | уроки Experience только в слое композера; фактчек нейтрален (machine_profile; cfg-06 фриз; FC-R1); серьёзные ответы не запрещены (A/B tech) |
| SOUL-11.1/.2/.3 | mobile-prompts доставлен и подтверждён: chain 320/390/430/1024 reopen ✓, run-green, _f1_* empty-states, «Ответы в чате» = mod_direct (app.js:597), 25 PG-ключей W1, V2-каталог missing=0 |
| SOUL-15.9 | дети 15.2–15.8 VERIFIED + прод-миграция v36 (capture-before sha, verify-after, авто-откат) |
| SOUL-16.5.1 | w6 F2 + P0-UX (структура, техмусор→Дополнительно, grep-утечек 0, чек-лист 30 пунктов, review Approved); история ревизий — в details (TJ-2/TJ-20; HISTORY_MAX=20); кнопка «История изменений» как отдельный контрол в разделе стиля отсутствует — принятая компоновка зафиксирована честно |
| SOUL-16.5.3 | test_ten_plus_heterogeneous_inputs_on_delivery_contour + initiative-pass ×1 + egress 07C.5 (tool responses) + 07D.4 protected spans; тестовый контур — по формулировке acceptance |
| SOUL-19.1/.2/.4/.5/.6 | поимённые тесты/интеграции/фидбек-гварды (4187 passed протокол, review-corrective-r1 §6), деплой-гейты release-каталогов, LIVE-FUNNEL sent=2, 14.1 доставлен (не брошен в backlog) |
| SOUL-21.11 | композит: A/B связность 33/33 + corrective контроль 0/4 мата при целом абсурде + прод-пробы one_word/trailing_period + фактчек real + initiative sent=2 live; честная оговорка: живое окно юмора (08.12) и живой пример абсурда не захвачены — открыто зафиксированы |

## READY_FOR_LIVE — остаются честно (main; причина обновлена, evidence добавлен)

| Строка | Остаток (класс) |
|---|---|
| SOUL-05.6 | телеметрия one_word (speech_extent) на 2.58.106 ещё отсутствует — реальных сообщений в окне не было; доставочное слово в реальном чате = owner-наблюдаемость (OQ-9) |
| SOUL-08.12 | живое окно 24–48 ч с реальными собеседниками; A/B класс метафоры-подхвата НЕ содержит (scenes.json) — закрыто детерминированно + 1 реальный сигнал |
| SOUL-10.P5 / SOUL-11.4 / SOUL-19.3 | реальный Telegram WebView / Telegram-клиент / TMA Android+Desktop — устройствный класс (owner_optional по plans/owner_live_checks.md), агентами невоспроизводим |
| SOUL-12.1–.5 | дубль покрытия U07/FS: инженерия закрыта asap8 (VERIFIED-набор) + soul-1 fs-релизами; живой клиент консолидирован в SOUL-12.0 (owner_optional) + asap8 owner-строки |
| SOUL-14.2 | НЕ ТРОНУТ (по директиве; ждёт первое реальное сообщение — 2.58.106 уже подтвердил отсутствие событий честно) |

user_excluded (03.5, 04.3, 04.4, 04.6): статус PENDING сохранён по конвенции карты (все 4 существующих user_excluded
строки — PENDING); в reason добавлены VERIFIED-сиблинги выживших частей.

## Amendment (12)

| Строка | Вердикт |
|---|---|
| SOUL-AMD.8.3 | **VERIFIED**: условия окна-2 выполнены — P0-фикс (2.58.90) + 17/17 на реальной базе + chat-scope resolve live + style-правка меняет следующую генерацию (окно-2 S1–S9, rev c6→c7 с откатом); Core-половина: save→перечитать+hot-apply payload; прямой A/B двух текстов Core не проводился (честно зафиксировано) |
| SOUL-AMD.8.11 | **READY_FOR_LIVE** (по формулировке acceptance): search+factcheck реальными сценариями ×3 (окно-1, AMD-PROBES, FC-R1); видео — WAITING_EXTERNAL not_configured, принцип «недоступное не обещается» подтверждён capability-notice; Human Gate не создаётся |
| SOUL-AMD.0.2/1.5/2.2/2.9/2.10/2.11/2.12/2.13 | **VERIFIED**: unified-core + жанровые слои + editorial eligibility + protected spans/egress + registry/Inspector (2.58.106 live) + withheld/07A/fingerprint (детали в reason строк) |
| SOUL-AMD.8.13 | **VERIFIED**: все 6 блокирующих условий закрыты с ссылками; недоказанное остаётся PENDING/RFL (прецедент 2.58.106) |
| SOUL-AMD.8.14 | **VERIFIED**: final-report.md покрывает все 6 обязательных блоков (§1–2, §3, §8, §9, §10) |

## Гейты

- main: `requirements_gate.py check --map plans/features/soul-1/requirements-map.json --stage plan` → **EXIT 0** (inventory=101, manual=97, errors=0)
- amendment: `... --map plans/features/soul-1/requirements-map-amendment.json --stage plan` → **EXIT 0** (inventory=66, manual=29, errors=0)

## Примечание о формате

requirements-map-amendment.json хранился как UTF-16 LE с BOM (артефакт PowerShell-перезаписи прошлых волн);
при записи биндинга приведён к UTF-8 без BOM — как main-карта. Контент идентичен с точностью до строковых
правок этого лейна; гейт plan EXIT 0 на обеих картах после конвертации. Из-за смены кодировки git-дифф карты
показывает перезапись строк — содержательная сверка: счётчики выше и построчные вердикты.

## Не тронуто (по директиве/конвенции)

SOUL-14.2, SOUL-12.0, SOUL-17.4, SOUL-AMD.8.11.OWNEROBS (owner_optional), контекст-заголовки (main 9, amend 15),
SOUL-EXEC.1/SOUL-01.0/SOUL-15.0/SOUL-21.0 (вне списка 48 — зонтики/процесс, закрываются PM/оркестратором),
current_task.md/workflow_state.md/код. REAL_WORK с кодом не обнаружено: все «реальные недоделки» из списков
либо уже доставлены поздними волнами (11.x, 16.5.1, 8.3-P0), либо являются наблюдательными окнами (перечислены выше).
