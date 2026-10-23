# REV-REL-258111 — независимое релизное ревью поезда 2.58.111 (23.10.2026)

**Вердикт: Approved for controlled deployment, parent not DONE** (деплой DevOps с ОБЯЗАТЕЛЬНЫМ плановым рестартом; W2-верификация после деплоя; P0-A/B честно PENDING-W2).

**Кандидат:** fbf9013d89b03e38 (= git HEAD; база a8d2a45a = 2.58.110). Карта asap-speech-arch rev 0f3ed53a (strict_evidence); гейт: review P0-C EXIT 0 (воспроизведено), P0-A/B EXIT 1 ровно по 3 PENDING-строкам runtime/W2 — классификация корректна.

## Состав (проверено независимо)
Дельта = 7 заявленных services (chat_prompts/factcheck_prompts/prompt_registry/prompt_migrations/mca_expression/summary_prompts/param_catalog) + web/app.py (только HEAD-роут app.css, 14 строк) + тесты + evidence + бамп (README/settings/F8-meta, SET EQUAL proc-110, 31 файл, 33 пары токенов). direct_chat_service/initiative_observer не тронуты — канон-эволюция их не требует (runtime-дамп w1 подтверждает сборку). Чужой dirty (cfg-06 json, owner_live_checks, workflow_state, node_modules) в диапазоне ОТСУТСТВУЕТ (проверено pathspec). ΔDDL=0 (grep: 0 DDL-строк, database.py вне дельты, schema v37).

## Канонная безопасность (главное) — воспроизведено независимым путём
- FACTORY_SET: git archive 4 коммитов (байт-сверка blob-хэшей) + собственный пересчёт sha256 payload по factory_texts(): e67a58e7~1 = c19d35a1c093, e67a58e7 = 3507bd6f92eb, a1db2991 = 553a281fe2fd, HEAD = fd4e88748749 — все MATCH (runtime==константа==функция, 89 блоков).
- Ступени байт-в-байт против прод-базы a8d2a45a (импорт модулей из archive-дерева): PREV_CHAT_W1=0fe9680ba280==прод tool_phase; PREV_CHAT_VERBALIZER_W1=d0ef0d376fc3==прод; PREV_FACTCHECK_VERBALIZER_W1=c9b0f431e849==прод (новая лестница); PREV_DIRECT_L1_PLANNER_L1D=ace6246bd360==прод. Новые каноны: f30c6d73da82/be03964322aa/c090b6956c70/f8ab20121c02. Идемпотентность в коде: new→no-op, кастом→skip+WARNING, отсутствие ключа→skip.
- owner_preserve_core_full_patch: код снимает ТОЛЬКО v2-ремарку «**Важно:**…см. SOUL-16» + точечные «см. SOUL-NN»; v1/v2 точные байты → superseded-note, не патч; никогда не бросает; идемпотентен. Тест test_91_owner_preserving (синтетическая owner-правка, байт-сверка) зелёный. Применение к реальному rev6 f59ba0f42a48 — честно на W2.
- superseded-core v1+v2: frozenset обеих прежних редакций на поле; core_selection подменяет на фабрику v3, кастом владельца не трогается (тест). PREV_*_W1 покрывают 4 лестничных канона; core full/compact — гвардом; narrator LEGFIX-ступень на месте.

## Сохранность характера (ДОП-1/2)
21 тест читает source-2026-10-22.md ЖИВЫМ файлом и сверяет байт-в-байт (прошли на моём прогоне). Независимый проб: якоря «язвительн/непристойн/абсурд/резким, злым, циничным и неприличным» в §3.2 и compact-аналоги — на месте; SOUL-мета/«**Важно:**» отсутствуют; §3.7 «ВЫБОР УЧАСТИЯ» вместо «ФОРМА УЧАСТИЯ»; §3.6 «НАЗНАЧЕНИЕ КАНАЛА DIRECT» вместо «СИСТЕМНАЯ РОЛЬ»; factcheck-вербализатор и Рассказчик без identity; Expression = «ПРАВИЛА МАНЕРЫ РЕЧИ» §3.4, PROFANITY-режимы побуквенно прежние. §3.1 вербализатор = ровно одна data-reader-добавка (P0A-RISK), без личности/мата/типографики. Semantics-таблицы 7 поверхностей: каждый удалённый фрагмент с судьбой (дублирование/конфликт/перенос); примитивизации нет (v3 = авторский текст владельца, −730 c = авторская редакция).

## Гварды (воспроизведены в venv, Python 3.12.0 / aiogram 3.31.0)
F8 --check 582==REGISTRY ✓ · w1_semantics 21p ✓ · initreply 14p ✓ · l1d 15p ✓ · mca19 полный блок-набор 118p (включает focused 33) ✓ · F2 17p ✓ · app.css HEAD 3p ✓ · narrator 22p ✓ · write_points 1p ✓ · help-sync 24p ✓ · node-пины 4/4 rc=0 ✓ · fingerprint runtime==fd4e88748749 ✓ · pins24 868p/0f за 63.28 c (лог полный; выборочно 2 файла = 37p) ✓.

## Гигиена
Секрет-скан добавленных строк диффа: 0 реальных попаданий (совпадения — документация и sha-фикстуры). Дрейф 15180/15181 задокументирован: набор из 7 failed (схемный долг v35-vs-v37) байт-в-байт воспроизведён на до-W1 базе — поезд отказов не добавил. Evidence release-258111 полна (offline 18/18, bump-verify, SET EQUAL, ddl-check, focused-артефакты, pins24-full).

## Postdeploy (W2) — обязательные шаги
Плановый рестарт (лестницы на старте + owner_preserve_core_full_patch к активной правке rev6); проверка лога ступеней (verbalizer/tool_phase/narrator/core_full_patch — каждая сработала, owner-preserving, diff до/после в отчёт); fingerprint runtime==fd4e88748749; SELECT-сверка активных PG-значений с новыми фабриками; 7 кастомов владельца целы; blob-сверки 6 сервисов; W3-пробы на offline harness. Rollback: ROLLBACK_MIGRATIONS (байт-в-байт на каноны 2.58.110, стек цел) + ветка release/fix-2.58.110 (=a8d2a45a, создать при деплое).

**Блокеры: нет.** Parent asap-speech-arch НЕ закрыт: P0-A/B/ARCH-ADR/W2/W3-строки — после деплоя.