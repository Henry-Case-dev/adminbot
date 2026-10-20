# RECHECK-CFG-06 (раунд R2) — повторное ревью после F3-фикса

Дата: 20.10.2026. Ревьюер: independent Reviewer (RECHECK-CFG06-R2), read-only + этот файл.
Кандидат v4: `8f220b60d72ea5cfeb77515881a7042c20cbc5b7` (= v3 `83c7abae` + F3). Дельта сверялась строго `git diff 83c7abae..8f220b60`: ровно 2 файла — `tests/test_mca20_integration_round1045.py` (+13/−3) и `plans/features/cfg/requirements-map.json` (+16, две evidence-записи). Сервисный код, снапшоты рендерера и настройки в дельте отсутствуют.

**Метод изоляции samples-ux:** в рабочем дереве есть незакоммиченная параллельная работа (services/mca_sample_library.py, mca_expression.py, web/api/speech.py и др.) — в ревью и прогоны НЕ включалась. Все тесты выполнены в чистом detached-worktree `C:\Users\main\AppData\Local\Temp\opencode\cfg06r2-wt` @ 8f220b60 (`git worktree add`, дерево чистое, импорты `services.*` резолвились в чекаут кандидата — проверено; worktree удалён после проверки). Гейт запускался из корня репо: карта cfg в рабочем дереве байт-равна HEAD (`git diff HEAD --stat` по карте пуст).

## ВЕРДИКТ: Approved (деплой 2.58.99 OFF → чекпоинты F1/F3 закрыты → hot-включение flags.factcheck_pipeline_v2)

## 1. F3 — ЗАКРЫТ

- Новый ассерт-блок ровно по предписанию R1 §F3: `payload["verdict"] == "утверждение подтверждается доступными данными"`; `payload["freshness"] == "данные старые, но к утверждению остаются применимы"`; `assert "09.10.2022" in payload["period"]` и `"10.10.2022" in payload["period"]`. Ассерты не удалены молча — заменены эквивалентами W5-контракта (сырой `temporal_status` в payload больше не требуется — это и был дефект утечки 06A.5; в вердикте-объекте `temporal_status == "old_but_valid"` сохранён).
- Суть MCA-20 сохранена: фикстура проверена — `evaluated_period {from:1665277000, to:1665363400}` → даты 09–10.10.2022, т.е. «период с датами доходит до вербализатора» теперь ассертится по-настоящему (раньше ассертился сырой ключ).
- Сервис не тронут (дельта), renderer-снапшоты целы (не в диффе; байт-снапшот-тест в семье зелёный).
- Прогон mca20-файла: **28 passed** (было 1 failed на v3).

## 2. Леджер (2 новые записи)

- Записи привязаны к строкам **CFG-06B.1** и **CFG-06H.2** (обе VERIFIED, slice CFG-06) — ровно classify-замечание R1 §4.
- `artifact_path=tests/test_factcheck_tool_route_cfg06.py` существует на кандидате; `artifact_sha256=7eeef0358d74205df61e8e0a34328832ffc99ec04b727a414a4f2ece8aca53f5` — пересчитан Get-FileHash в worktree кандидата, **совпал**.
- `candidate_commit=83c7abae…` (не 5af56d8b): отклонение честное — `git cat-file -e 5af56d8b…:tests/test_factcheck_tool_route_cfg06.py` → fatal «not in 5af56d8b» (файл появился только в v3); в v3 существует.
- Карта vs v3 больше не менялась (дифф = только 2 вставки); карта в рабочем дереве == HEAD.

## 3. Прогоны на кандидате v4 (изолированный worktree)

| Набор | Результат |
|---|---|
| test_mca20_integration_round1045.py | **28 passed** |
| factcheck-семья, 9 файлов: gate, renderer, context, w6, service, handlers, orchestrator, planner, tool_route | **170 passed**, FAMILY_EXIT=0 |
| OFF-паритет точечно (-k "off/parity/legacy/skip": gate+context+tool_route+renderer) | **15 passed** |
| W7-композит (8) + route-coverage (18) | **26 passed**, EXIT=0 |
| Итого за сессию | **224 passed / 0 failed** |

Known-4 (outgoing_guard×2 + asap7_direct_settings×2) не перегонялись: дельта v3→v4 не содержит прод-кода (только тест+карта), базовая линия R1 «ровно 4 known failed» остаётся связанной с теми же байтами сервисов. Ограничение честно зафиксировано.

## 4. Гейт

`requirements_gate.py check --stage review --slice CFG-06 --candidate 5af56d8b… --map plans/features/cfg/requirements-map.json` → **EXIT 1, ровно 5 ошибок, состав идентичен R1**: 06E.4, 06F.1, 06G.1, 06G.4 (READY_FOR_LIVE — платные канарейки, тестовый контур после включения флага) + 06G.3 (PENDING — post-release). Маскировки нет; scoped=93.

## 5. План включения (подтверждён, PET_PROJECT стоячее согласие)

1. Деплой 2.58.99 = 8f220b60, `FACTCHECK_PIPELINE_V2_ENABLED` default OFF, hot-флаг не задан.
2. Чекпоинты: «F1 закрыт» — R1 §1; «F3 закрыт» — этот документ §1.
3. Hot-включение `flags.factcheck_pipeline_v2=true` во всех подключённых чатах (без канареечных гейтов). Смоук без сообщений в чаты: healthz 200, логи gate/retrieval/deliver, ERR-логи, аномальная частота reason `skipped/failed`.
4. Откат: hot `flags.factcheck_pipeline_v2=false` без рестарта (вся v2-ветка, включая tool-маршрут, за флагом).
5. Платные канарейки 06G.1/06G.4 — тестовый контур после включения (строки остаются READY_FOR_LIVE); 06G.3 — post-release; живые осмотры владельца — опционально (owner_live_checks.md).

## Биндинг

Кандидат `8f220b60d72ea5cfeb77515881a7042c20cbc5b7`; карта `plans/features/cfg/requirements-map.json` @ 8f220b60. Любое изменение кода/карты/тестов инвалидирует соответствующие пункты. Внешние источники не требовались. Scratch-worktree удалён.
