# W1 — семантика слоёв (asap-speech-arch): слайсы P0-A/B/C/D/E/F/G

**Лейн:** ASAP-W1-FACTORY. **Дата:** 22.10.2026. **Кандидат:** рабочее дерево мастера поверх `3b60887c` (коммиты — следующим лейном вместе с W1, п. брифа).
**Первоисточник:** `plans/features/asap-speech-arch/source-2026-10-22.md` §3.1–3.7 (готовые тексты владельца — байт-в-байт), ДОП-1/ДОП-2.
**W0-факты:** `evidence/w0-inventory.md` (прод 2.58.110 @ a8d2a45a; снимок 22.10 ~10:00 UTC).

## Что изменено (фабрики, байт-в-байт тексты владельца)

| block | канон | было (прод 2.58.110, sha12) | стало (sha12, chars) | слепок прежних байтов |
|---|---|---|---|---|
| core.personality | §3.2 (v3, метка `asap-core-full-v3`) | d98e72ec7926 (v2) | 2ab417d11404 / 1925 | `PREV_PERSONALITY_CORE_FULL_V2_TEXT` (+ v1 = `PREV_PERSONALITY_CORE_FULL_TEXT`) |
| core.personality.compact | §3.3 (v3, `asap-core-compact-v3`) | e0529832ba7c (v2) | 9e6a4ec8b1ea / 556 | `PREV_PERSONALITY_CORE_COMPACT_V2_TEXT` (+ v1) |
| direct.base.l2_writer | §3.1 (+ data-reader адаптация P0A-RISK) | d0ef0d376fc3 | be03964322aa / 1982 | `PREV_CHAT_VERBALIZER_W1` |
| direct.base.tool_phase | §3.6 (ролевой блок НАЗНАЧЕНИЕ/ДОСТОВЕРНОСТЬ/ГРАНИЦА ЭТАПА) | 0fe9680ba280 | f30c6d73da82 / 4999 | `PREV_CHAT_W1_SYSTEM_PROMPT` |
| direct.base.l1_planner | §3.7 (секция «ВЫБОР УЧАСТИЯ» вместо «ФОРМА УЧАСТИЯ») | ace6246bd360 | f8ab20121c02 / 4641 | `PREV_DIRECT_L1_PLANNER_L1D` |
| factcheck.base.verbalizer | identity-фраза снята (SOUL1-CLOSE-R1 04.3) | c9b0f431e849 | c090b6956c70 / 1632 | `PREV_FACTCHECK_VERBALIZER_W1` |
| (слой mca_expression) | EXPRESSION_HEADER = §3.4; FOOTER прежний; режимы off/occasional/frequent — НЕ тронуты (байт-сверка §3.4 в тестах) | 7d16e6537563 (новый header) | — | `PREV_EXPRESSION_HEADER` (док.) |

`FACTORY_SET_SHA256_12`: **553a281fe2fd → fd4e88754749** (changed = 6; запись бампа — в prompt_registry, SOUL-AMD.3.2).

## Семантические таблицы (ДОП-2 п.4: каждый удалённый фрагмент — с обоснованием)

- `semantics-core-full.md`, `semantics-core-compact.md` — v2 → v3 (токсичность/цинизм/абсурд сохранены; сняты только мат-регулирование и SOUL-16-ремарка; v3 — авторский текст владельца, не примитивизация).
- `semantics-verbalizer.md` — §3.1; data-reader адаптация (P0A-RISK, разрешено владельцем).
- `semantics-tool-phase.md` — §3.6; сняты СИСТЕМНАЯ РОЛЬ/ПРИОРИТЕТЫ/ПРАВИЛА ОФОРМЛЕНИЯ/блоки A/B; контракты сохранены байт-в-байт.
- `semantics-l1.md` — §3.7; схема/правила L1D не тронуты.
- `semantics-expression.md` — §3.4 шапка; режимы побуквенно прежние.
- `semantics-factcheck-verbalizer.md` — точечная нормализация (прецедент narrator-legfix).

## Матрица P0-F / P0-E

`matrix-p0f.md` — все заводские prompts.* пользовательские каналы: до/после (exact substring + владелец). Честная пометка по W0: **в effective-payload конфликта кавычек не было** (cleaned-тексты чисты) — очистка фабрик превентивная.

## Миграции

`migrations.md` — FACTORY_SET, лестницы PREV_*_W1 (11-я ступень direct_chat; 3-я вербализатора; 4-я L1; первая — factcheck-вербализатор), ROLLBACK на непосредственный прежний прод-канон, гвард superseded-core v1+v2, owner-preserving патч Core (W2).

## §9.1 чек-лист — результат

Файл `tests/test_asap_w1_semantics.py` (21 тест, CONTRACT owner=ASAP-W1) + обновлённые контракт-тесты канонов. Полный набор: **15180 passed, 39 skipped, 7 failed** — все 7 = до-существующий долг схем БД (asap7 v35 + t5150, локальная схема v37; stash-верифицировано: падают на HEAD без изменений W1). Детали — `test-run.md`.

## Гейты

- plan asap-speech-arch: EXIT 0 (strict_evidence=true) — не сломан; soul-1/cfg/asap8 карты не затронуты структурно (тесты их контрактов обновлены под новые байты канонов — правки тестов в этом лейне).
- Связанные наборы (soul-1/cfg-07/asap7/asap8/mca-*/prompt) — зелёные, кроме указанного до-существующего долга.

## Границы лейна (для W2/W3)

1. **Активные PG-значения** (W2): три withheld-кастома прода — verbalizer `091115cadc28`, tool_phase `cf404931f84c`, narrator `43160d5f9c2c` — лестницей НЕ обслуживаются (подлинные кастомы); гасить через `write_speech_value` с провенансом (§5.5), diff — в отчёт W2 (приватные куски маскировать).
2. **Core active** `f59ba0f42a48` (owner_edit rev 6): применить `pm.owner_preserve_core_full_patch` (снимает только SOUL-16-ремарку; тест — `test_91_owner_preserving_core_patch_removes_only_service_remark`), записать с провенансом owner_edit + history, показать diff.
3. **compact_text** на проде пуст → замены фабрики достаточно.
4. **Narrator LEGFIX** (5086ba935081) — вне зоны W1 (поедет релизом 2.58.111); PG-кастом 43160d5f9c2c гасить в W2 уже на LEGFIX-канон.
5. **W3** (живые пробы режимов/жанров) — отдельно, не в этом лейне.
6. **mode-блоки verbilizer_mode_\*** (PG-кастомы 19.09) — не сняты; W1-проверка добавлена (`test_p0d_legacy_mode_blocks_not_pulled_into_payload`): при плане mode-блоки в payload не подтягиваются; W2 — снять/переаттестовать значения.
