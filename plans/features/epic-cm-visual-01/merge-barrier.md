# Merge barrier: EPIC-PROMPT-VERSIONING-UX-01 vs EPIC-CM-VISUAL-01

**Зафиксировано:** 2026-11-04, Orchestrator, по решению PM (план пакета версионирования промптов §2).

## Правило

`web/app.js`, `web/index.html`, `web/static/assets` (`web/static/app.css`) — **один писатель в единицу времени**.

Срез `PVR-S4-UX` (единый компонент «История версий» для всех редакторов промптов) входит в эти файлы **раньше**, чем любой срез EPIC-CM-VISUAL-01, которому нужны те же файлы (`CMV-A`, `CMV-B`, `CMV-D`).

## Условия

1. `CMV-A/B/D` не начинаются, пока `PVR-S4-UX` не влит в `evol/impl` и не освободит `web/**`.
2. `CMV-C` (LOD/коллизии в `web/static/cognitive-map.js` + `tests/js/**`) от этого барьера не зависит и может идти параллельно, если не трогает `app.js`.
3. `CMV-E` (тесты/замеры/приёмка) может готовить фикстуры и инструменты параллельно, но замеры производительности делает только на актуальном после слияния `PVR-S4` дереве.
4. Барьер снимает Orchestrator после слияния `PVR-S4` и зелёного прогона затронутых UI-тестов; факт фиксируется в `plans/features/epic-cm-visual-01/merge-barrier.md` (этот файл) строкой «снят: <sha>».

## Почему

Оба пакета меняют разметку и стили одних и тех же экранов админки. При параллельной правке конфликт неизбежен либо в merge, либо в поведении: компонент истории версий вставляется в карточки промптов, а редизайн карты меняет ту же разметку статуса/модалок и общий стек стилей.

## Снятие барьера

Снят: fb19340bac81b191e3385849434a965b75ac1cfa (2026-11-04) — PVR-S4-UX влит в `evol/impl`, `web/**` свободен для `CMV-A`, `CMV-B`, `CMV-D`.

- **Слияние:** `merge(pv-ux): single version-control UI on every prompt editor` — `fb19340b`, второй родитель `27f5045b` (`pv/ux` + `evol/impl` `846ade0f`), исходный одобренный кандидат `pv/ux` @ `217cde65` (код `9aa952dd`), вердикт Reviewer — **Approved** (Re-review 3).
- **Идентичность UI:** `git diff 217cde65 HEAD -- web/index.html web/static/app.css web/app.js tests/js/prompt_version_card_test.js` — пусто (байт-в-байт одобренный кандидат).
- **RC-работа сохранена:** `git diff 846ade0f HEAD` не содержит `services/**`, `web/api/**`, `handlers/**` — factcheck/consumer/self-correction не откатаны.
- **Тесты на смерженном дереве:** `tests/ui_prompt_version_card_e2e.py` — failures=0 (`PVR-S4-OK`); `node tests/js/prompt_version_card_test.js` — `PVR-S4-CARD-OK`; `pytest tests/test_evol017_prompt_history_ui.py tests/test_evol018_prompt_audit.py tests/test_evol_reply_context_consumers.py` — 70 passed.
- **Промпты не изменены:** агрегат `51425b07d299e0be…`, `factory_set 54ac2b8ac34b`; `initiative.meme.joke` 95 байт `2f30ca1f9a6b`, `initiative.meme.image` 51 байт `f81fe7e4b505`.
- **Вердикты ревью сохранены:** `plans/features/prompt-versioning-ux/reports/pv-s4-review.md` (Re-review 2 и 3) + `evidence/pvr-s4/reviewer/**`, sha256 `c4d7c5053bbce695518fd738030ab7e139c813022b26776bf5b93b78d11cb696`.
