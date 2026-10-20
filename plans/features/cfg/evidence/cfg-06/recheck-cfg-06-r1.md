# RECHECK-CFG-06 (раунд R1) — повторное ревью после F1-фикса

Дата: 20.10.2026. Ревьюер: independent Reviewer (RECHECK-CFG06-R1), read-only + этот файл.
Кандидат v3: `83c7abaef88ff4f5ed0cd408d74637a66d5323cf` (= Approved-база `5af56d8b` + F1-фикс + леджер + Saccharomyces-микротест + 07A-1 docs). HEAD == кандидат; дельта сверялась строго `git diff 5af56d8b..83c7abae` (10 файлов: tool_router.py, 2 теста, леджер, evidence). Параллельная samples-ux работа в дереве отсутствует (HEAD == 83c7abae).

## ВЕРДИКТ: Needs Fixes (1 новый блокер — устаревший mca20-тест; F1 закрыт)

Деплой кандидата с флагом OFF остаётся безопасным. Включение `flags.factcheck_pipeline_v2` блокируется единственным новым пунктом F3 (ниже): детерминированный новый фейл теста контракта mca20, внесённый базой `5af56d8b` (W5). Фикс — ~10 строк в одном тест-файле, без сервисного кода.

## 1. F1 — ЗАКРЫТ (по существу, код+тесты)

`services/tool_router.py::_fact_check` (L2441–2489):
- `pipeline_v2_enabled()` (orchestrator L176: hot `flags.factcheck_pipeline_v2` → env → False; не бросает) проверяется ДО `check_claim_envelope` (платный поиск после гейта).
- `fsg.evaluate_with_expansion(db, chat_id, claim_text=…, user_hint=None, target/trigger…, cache=get_smart_cache())` — сигнатура совпадает с factcheck_suitability.py:577; тот же единый gate-объект, что handler-маршрута (оркестратор L302).
- `no_claim/ambiguous` → `{"status":"skipped","reason":…}` + `stage_event("deliver","skipped",…)` БЕЗ `check_claim_envelope` (зеркалит оркестратор L310–329).
- сбой гейта → fail-closed `{"status":"failed","reason":"temporal_insufficient_evidence"}` без обхода гейта платным поиском.
- иначе `check_claim_envelope(envelope, chat_context=feed or None)` — идентично оркестратору L450.
- OFF: литерально прежний вызов `check_claim_envelope(envelope)` (kwargs={}), гейт не вызывается.
- Наружный tool-контракт: набор ключей ready-payload не менялся (тест `test_off_and_v2_ready_payload_keys_identical`); новый статус `skipped` — аддитивный JSON агенту, валидации enum на потребителе нет (прецедент `already_handled`, tool_router L3000).
- Новые/затронутые контракты сверены: `check_claim_envelope(envelope, *, chat_context=None, stage_trace=None)` (factcheck_service.py:512), `context_unavailable` при v2 ON проходит дальше (та же семантика, что оркестратор).

## 2. mca20 — РАЗБОР СПОРНОГО ТЕСТА (важно)

**Классификация: детерминированная регрессия кандидата `5af56d8b` (W5), НЕ порядок-зависимость, НЕ aiosqlite/окружение, НЕ pre-existing.**

Воспроизведение (тест `test_mca20_integration_round1045.py::TestOneEnvelopeThroughBranches::test_analyst_and_verbalizer_get_same_envelope`, изолированный прогон, `KeyError: 'temporal_status'`):

| Дерево | Результат |
|---|---|
| родитель `9f37c15a` (= прод-код 2.58.98) | **PASSED** |
| база `5af56d8b` (CFG-06 v2, W5) | **FAILED** |
| кандидат v3 `83c7abae` | **FAILED** (в изоляции и в наборе; детерминированно) |

Механизм: `5af56d8b` намеренно гуманизировал payload вербализатора (`_temporal_verbalize`, factcheck_service.py): сырые ключи `temporal_status/evaluated_period/assessment_mode/as_of/uncertainty/style_note` удалены (утечка «период проверки (unknown)» — живой дефект 06A.5), добавлены человеческие `freshness/period/caveats`. Новый контракт защищён собственными тестами (test_factcheck_renderer_cfg06.py:381–434, включая байт-снапшот; `temporal_status` там прямо запрещён). Старый mca20-тест (L119–120) ассертит устаревший ключ `payload["temporal_status"]` и при этом защищает ВЕРНУЮ суть контракта MCA-20 — «даты/статус вердикта не стираются при вербализации». Суть W5 соблюдена (freshness+period в человеческом виде, даты не стёрты), но легаси-тест не был обновлён вместе с согласованной сменой контракта. Заявление раунда-1 «322 passed включая mca20» (review-cfg-06.md L19) моим репродуктивным прогоном на 3 чекаутах опровергнуто.

Квалификация по правилу «0 новых failures»: **НОВЫЙ БЛОКЕР F3** (не продуктовый — продуктовое изменение санкционировано и прифито; блокер состояния сьюта/контракта).

### F3 — BLOCKER (минимальный)
- Требование/инвариант: «0 новых failures» на кандидате; контракт MCA-20 «temporal-инфо доходит до вербализатора».
- Локация: `tests/test_mca20_integration_round1045.py` L119–120.
- Фикс: обновить ассерты на W5-контракт с сохранением сути — например: `assert payload["verdict"] == "утверждение подтверждается доступными данными"`; `assert payload["freshness"] == "данные старые, но к утверждению остаются применимы"`; `assert payload["period"]` содержит даты периода (14.05.2022-style), т.е. даты НЕ стёрты. НЕ удалять ассерт молча; сервисный код не трогать.
- Recheck: прогон файла mca20_integration (28/28) + factcheck-семья (130) + tool_route (7).

## 3. Прогоны (кандидат v3, рабочее дерево == HEAD)

| Набор | Результат |
|---|---|
| test_factcheck_tool_route_cfg06.py (новый, F1) | **7 passed** |
| test_tool_router.py | **45 passed** |
| test_factcheck_w7_acceptance_cfg06.py (композит S1–S8) | **8 passed** |
| test_unified_core_route_coverage.py | **18 passed** |
| test_factcheck_orchestrator_cfg06.py | **16 passed** |
| test_factcheck_planner_cfg06.py (вкл. Saccharomyces ×2) | **17 passed** |
| gate+renderer+context+W6+service+handlers | **130 passed / 0 failed** |
| mca20 трио (integration+temporal+rework1) | **79 passed / 1 failed** (F3) |
| Базовая линия (outgoing_guard×2 + asap7_direct_settings×2) | ровно 4 known failed — **не расширена** |

## 4. Леджер (plans/features/cfg/requirements-map.json)

- Состав scoped подтверждён скриптом: 84 items (slice CFG-06: 76V/7RFL/1P) + 9 агрегатов в `additional_requirements` (8V/1RFL: CFG-06.CON, CFG-06E.CON, CFG-06.B postdeploy, CFG-06H.0, CFG-06H.ARCH, CFG-06I.KEY, CFG-06.J-PRIOR, CFG-06.B-HIJ, ADD-1.T6) = **93 строки: 84V/8RFL/1 PENDING** — совпадает с ledger-cut.md §1 байт-в-байт.
- Перерезка: дифф карты 5af56d8b→83c7abae меняет ровно 84 записи, ВСЕ в slice CFG-06; вне слайса не тронуто ни одной (проверено программно).
- `candidate_commit=5af56d8b`: ЧЕСТНО (все W0–W7 evidence-артефакты и фактчек-файлы байт-идентичны между 5af56d8b и 83c7abae; F1-фикс — только tool_router+тесты). Classify-замечание (не блокер): строки 06B.1/06H.2 заявляют Direct/tool-покрытие, но новый тест `tests/test_factcheck_tool_route_cfg06.py` ещё не привязан к ним как evidence — добавить привязку в том же rework, что F3.
- 9 агрегатов: свап path/hash исправлен, выборочно пересчитаны sha256 7 привязок (w2-notes, gate-тесты, w3-schemas, w7-acceptance-тесты, w7-acceptance.md, w5-renderer, planner «после микро-теста») — **все совпали** с текущим деревом.
- Гейт: `check --stage review --slice CFG-06 --candidate 5af56d8b…` → **EXIT 1, ровно 5 ошибок**: 4 канарейки preprod (06E.4, 06F.1, 06G.1, 06G.4 — READY_FOR_LIVE, отложить до включения флага) + 06G.3 (PENDING). Postdeploy-RFL (06F.6, 06G.8, 06J.6, CFG-06.B) легальны на review. Маскировки нет: ни одна обязательная строка не поднята до VERIFIED без доказательства.
- Новая политика owner_optional (plans/owner_live_checks.md, 20.10.2026): владельческие осмотры в строках 06E.4 и пр. пока без формальных метаданных `verification_tier/owner_optional_reason/engineering_req_ids` — bounded-реконсиляция PM вне этого ревью; инженерные строки не пострадали. Classify.

## 5. 06G.3 — честный PENDING подтверждён

Атрибуция/цитата/privacy доказаны (corpus в: автор «Петя», dropped_privacy, tg-якорь; 06I.KEY); выделенный локальный tool «кто сказал» не реализован — задокументирован в w7-acceptance.md §4 (PARTIAL) и в note строки. Композит CFG-06.B от него НЕ зависит: его acceptance (gate→источники→без служебного egress→краткий вердикт со ссылками→единый контракт) доказан S1–S8 через run_factcheck; атрибуция анцедента покрыта S6. Гап корректно передан оркестратору как post-release сервисная работа.

## 6. План включения флага (подтверждён + чекпоинт)

1. Деплой `83c7abae` штатным релизом, `FACTCHECK_PIPELINE_V2_ENABLED` default OFF (settings.py:2717), hot-флаг не задан → байт-паритет 2.58.98 (единственная прод-дельта — санкционированный W5-фикс style_note-утечки вербализатора; заявить в релизных заметках).
2. **Чекпоинт «F1 закрыт»** — ВЫПОЛНЕН (этот документ, §1): tool-маршрут за тем же v2-флагом, контракт-тест 7/7.
3. **Чекпоинт «F3 закрыт»** — обновлённый mca20-тест в кандидате (блокер включения).
4. Hot-включение `flags.factcheck_pipeline_v2=true` сразу во всех подключённых чатах (стоячее согласие PET_PROJECT; без канареечных гейтов). Смоук БЕЗ сообщений в чаты: логи gate/retrieval/deliver, healthz 200, ERR-логи, отсутствие новых reason-кодов `skipped/failed` аномальной частоты.
5. Откат: hot `flags.factcheck_pipeline_v2=false` без рестарта (v2-ветка полностью за флагом, включая tool-маршрут).
6. Платные канарейки 06G.1/06G.4 — в тестовом контуре после включения; строки остаются READY_FOR_LIVE до них; живые проверки владельца — опционально (owner_live_checks.md); агентам тестовые сообщения в реальные чаты запрещены.

## Биндинг

Кандидат `83c7abaef88ff4f5ed0cd408d74637a66d5323cf`; карта `plans/features/cfg/requirements-map.json` @ 83c7abae; любые изменения кода/карты/тестов инвалидируют соответствующие пункты. Внешние источники не требовались (спорных внешних фактов нет). Scratch-worktree проверки удалён.