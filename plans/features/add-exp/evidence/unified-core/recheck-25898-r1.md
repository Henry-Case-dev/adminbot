# RECHECK-25898-R1 — повторное ревью кандидата v2 (закрытие REVIEW-25898)

- Дата: 20.10.2026. Ревьюер: независимый (lane RECHECK-25898-R1, read-only + этот файл).
- Кандидат: `1b23d4c9beb1544169f51781c2c8a45e8797f719` (= HEAD рабочей копии; = `37097f7c` UNIFIED-CORE + R1-фикс).
- Дельта round-1: `git diff 37097f7c..1b23d4c9` — 8 файлов, ровно заявленный скоуп (5 код/тест-файлов + fix-r1.md + review-25898.md + cfg-06-build-plan.md). Логика кода не менялась.

## 1. Блокер 1 (тесты под владельческие изменения) — ЗАКРЫТ

- **chat_id (11 ассертов test_checkup_handlers.py):** реализация реально передаёт `chat_id=message.chat.id` (handlers/checkup.py:143-144; сигнатура `checkup_service.checkup(..., chat_id: int | None = None)`, владелец-блок идёт в канон чек-апа до CHECKUP_FALLBACK_NOTICE). Новые ассерты проверяют ТОЧНОЕ значение `chat_id=CHAT_ID` (-1001234567890 из `_make_msg`) — усиление, не ослабление. Статический RED подтверждён: старый ассерт `("логи", False)` не совпал бы с новой сигнатурой.
- **C6-якорь (test_direct_chat.py):** текст ассерта байт-в-байт = шаблон в direct_chat_service.py:7692-7696 (`...одного и того же слова; настройки выражения владельца важнее образца:`). Старое ожидание `слова:` статически RED (двоеточие заменено точкой с запятой).
- **H11 (test_soul1_w4_humor_craft.py):** все 3 новых ассерта присутствуют в `HUMOR_CRAFT_GUARD` (mca_humor_craft.py:110-118) байт-в-байт (`причинная связность и уместность`, `не частота метафор или оскорблений`, `не растягивай на каждый ответ` — последний добавлен, усиление); `неприкосновенны` и ban-лист сохранены.
- **Отпечаток:** `factory_set_fingerprint()` пересчитан НЕЗАВИСИМО вызовом процедуры контракта на кандидате: **64ec1c60e278** == `FACTORY_SET_SHA256_12`. Diff prompt_registry.py содержит только константу + провенанс-комментарий, метку `humor-craft-guard-w4`→`-h11` (ни один тест метку не пинит) и указатель `checkup_service.py:59→71` (guard `test_registry_consumer_pointers_point_at_real_lines` зелёный: 12 passed test_soul1_registry_completeness.py).

## 2. EXPRESSION_NOTES (web/api/speech.py) — P0-СОВМЕСТИМА

Новая формулировка (`Цитаты и чужой текст передаются как есть; сводки звучат тем же голосом персонажа; просьба «без мата» уважается всегда`) не противоречит `EXPRESSION_HEADER` (P0: вся пользовательская речь без жанровых исключений; цитаты как есть; без мата — override ответа). Жанровая оговорка исчезла полностью. Байт-пинов нет: test_add_exp_expression.py:615 сверяет API с константой (`view["notes"] == S.EXPRESSION_NOTES`); test_soul1_w6_speech_ui.py и e2e-стаб текст не пинят (grep 0).

## 3. Прогон тестов

- Сфокусированно на кандидате (я, 20.10): **test_checkup_handlers + test_direct_chat + test_soul1_w4_humor_craft + test_add_exp_expression + test_soul1_w6_speech_ui + test_unified_core_route_coverage + test_prompt_migrations + test_checkup_service = 367 passed / 0 failed** (15.7s); + test_soul1_registry_completeness = 12 passed.
- Полный pytest не повторялся: fix-r1.md зафиксировал **12f / 14632p / 1s / 7err (651.9s)** = паритет базы (те же 12f+7err; +18 passed = ровно закрытые 18 failures round-1). Ни один из 12f+7err не входит в мои сфокусированные файлы (asap7_direct_settings, mca01_tx, outgoing_guard, summary_asap2/round1026, t5150, p0_vision_ui_e2e — env/timing/pre-existing). Full-run запись fix-r1 принимается при совпадении focused-результатов.

## 4. Блокер 2 (леджер) — ЗАКРЫТ

- Гейт: `requirements_gate.py check --stage review --slice EXP-ACCEPT --candidate 1b23d4c9...` → **EXIT 0** (inventory=20, manual=17, scoped=6, errors=0).
- `candidate_commit` = 1b23d4c9 (полный SHA); `deployed_commit` = 95d11472 — честно: прод ещё на 2.58.97.
- **EXP-ACCEPT.CRITERION = READY_FOR_LIVE** (live postdeploy): честно сохранён FAILED acceptance-96; off-prod eval на новых текстах зафиксирован как false (frequent_majority=false, occasional_lt_frequent=false); predeploy-половина закрыта payload-трассами; postdeploy-план конкретен — повтор F4-матрицы на выкаченном 2.58.98 (off/occasional/frequent, пороги §4), DevOps ставит VERIFIED/FAILED честно, откат — PREV-лестница ADR-1013-3.
- **LIVE-SET/ROUTES/PREVIEW/REVIEW + EXP-REG.QUEUE** имеют v2-привязки; наблюдения не приукрашивают: «набор 27+7 выполнен на ПРЕЖНИХ текстах и для новых не показатель», «поведенческое различие predeploy НЕ заявляется», «обязательный postdeploy — повтор F4-матрицы», очередь продолжается автоматически.
- Целостность v2-артефактов: 5/5 `artifact_sha256` (fix-r1.md, unified-core/README.md, test_unified_core_route_coverage.py, cfg-06-build-plan.md, directives-fix/eval.json) совпали с фактическими файлами.

## Вердикт

**Approved for controlled deployment, parent не DONE.**

Обязательный остаток postdeploy (до закрытия родителя): F4-матрица на выкаченном 2.58.98 (EXP-ACCEPT.CRITERION + повтор набора LIVE-SET), честная фиксация VERIFIED/FAILED, затем `--stage release`.
