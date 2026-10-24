# QUOTA-QUOTES-FIX — F1 (A7) + F2 закрыты, C1/C6 классифицированы

Дата: 24.10.2026. Лейн: QUOTA-QUOTES-FIX. Вход:
`evidence/review-quota-quotes.md` (F1 BLOCKER, F2 small, C1/C6 без решения).
Правки только в `services/mca_expression.py`, `web/app.js`, тестах; прод/SSH
не использовались, живых LLM-вызовов нет.

## A7 / F1 — owner-пожелание Expression больше не режется (CLOSED)

- Факт до: `mca_expression.py:248` `note[:2000]` в `normalize_expression`;
  «Пожелание владельца» — управляющая инструкция (ADDENDUM #3 §2.2, §2.10).
- Правка: `services/mca_expression.py:248-251` — обрезка удалена, остаётся
  приведение к `str`; ограничитель — только реальное окно модели
  (`model_capacity`). Путь `_write_expression` (`web/api/speech.py:3056-3059`)
  идёт через эту же нормализацию, отдельной квоты на `values` нет.
- Тест: `tests/test_quota_removal_composer.py:118`
  `test_owner_expression_note_is_not_truncated` — note 3614 символов,
  проверяется `normalize_expression`, `resolve_effective` и фактический
  `<Expression_Settings>` из `build_expression_settings`; маркер
  `ХВОСТ_МАРКЕР` присутствует.
- RED (до правки, `git stash` кода): тест падает — note 2000, хвост теряется.
- Зелёный после правки: см. числа ниже.

## F2 — пресет `no_quotes` = ровно одно правило кавычек (CLOSED)

- Факт до: `web/app.js:addStylePreset` пушил preset-правило
  (`quotation_marks.hard.no_graphic`) рядом с уже существующим
  `quotes.hard.factory` (normalize) → в документе 2 включённых правила.
- Правка: `web/app.js:20659-20678` — если в пресете есть правило
  `kind=quotation_marks`, прежние правила кавычек из черновика удаляются
  перед добавлением (та же инварианта «одна настройка = одно правило», что в
  `setStyleQuotesMode`). `existing` пересобирается после чистки, поэтому
  повторный клик тем же пресетом не оставляет ноль правил.
- Семантика кавычек не менялась: режимы A/B/OFF и runtime
  `_collapse_quotes_rules` (`style_policy.py:993-1016`) те же.
- Тест: `tests/test_quotes_modes.py:292`
  `test_ui_preset_no_quotes_leaves_exactly_one_quotes_rule` — берёт РЕАЛЬНЫЕ
  функции `web/app.js` (`ensureStyleDraft`, `speechStyleViewRules`,
  `speechQuotesRules`, `speechQuotesMode`, `addStylePreset`) через node;
  пресет-документ — `style_policy.preset_rules("no_quotes")` (один источник
  правды). Проверки: одно правило, `mode=strip`, `enabled=true`, UI-режим
  `strip`, dash-правило не потеряно, повторный клик → всё ещё одно правило,
  пустой черновик → одно правило.
- RED (до правки): тест падает «assert 2 == 1» (factory normalize + preset
  strip).
- Playwright (реальные `web/index.html` + `web/app.js`, route-стабы `/api/*`):
  `OPENCODE_WORKFLOW_SCRATCH/quota-quotes-fix/probe_f2.py` — 390x844 и
  1280x900, сценарий ревью «Стиль письма» → «+ Без кавычек» → Save.
  RED до правки (2 прогона): `в документе 2 правила кавычек:
  ['quotes.hard.factory', 'quotation_marks.hard.no_graphic']`.
  После правки: `failures: []` для обоих размеров, в POST-документе ровно
  одно `quotation_marks` (`mode=strip`, `enabled=true`), dash-правило на
  месте; чекбоксы B=ON/A=OFF, «оба выключены» не показано.
  Скриншоты: `OPENCODE_WORKFLOW_SCRATCH/quota-quotes-fix/shots/`.
- Browser Use (реальный рендер, 1036x906 CSS): «+ Без кавычек» → тост
  «Шаблон добавлен: правил 1», B отмечен, A снят, карточка «Кавычки» в
  списке одна, счётчик «2 правил» (dash + кавычки), ошибок страницы нет.

## C1 — `chat_style_anchor_max_chars` (400): классификация B (сохранить)

- Место: `direct_chat_service.py:7824-7833`; значение —
  `settings.CHAT_STYLE_ANCHOR_MAX_CHARS` (`config/settings.py:2774`,
  env-настраиваемое), плюс hot-ключ `limits.chat_style_anchor_max_chars`;
  витрина настроек — `param_catalog.py:1749` («Обрезка якоря, символов»).
- Что ограничивает: длину КАЖДОГО прошлого ответа бота внутри
  `<style_anchors>`, а не owner-инструкцию и не системный промпт. Это
  выборка данных прошлых ответов для интонации; блок прямо говорит
  «настройки выражения владельца важнее образца».
- Почему не A: §2.6/§2.10 сохраняют ограничения числа/состава элементов
  выборки; здесь режется не инструкция, а образец. Квота не скрытая —
  владелец видит и меняет её в настройках (env/hot/param catalog).
- Остаточный риск (не блокер): обрезка без маркера, хвост длинного ответа в
  якоре не виден; это данные, не инструкция. Решение зафиксировано: не
  удалять; при жалобе на «плохую интонацию» поднять значение, а не менять код.
- Код не менялся. Существующее покрытие: `tests/test_direct_chat.py:1315`,
  `:1362`.

## C6 — `instruction[:500]` (Summary L2 review/repair): классификация B

- Места: `summary_l2_review.py:387-390` (`ReviewFinding.instruction`),
  `summary_l2_anchor_repair.py:241-246`
  (`ReviewIssue.repair_instruction`); далее эти поля уходят в repair-payload
  (`summary_l2_anchor_repair.py:288`, `:328`).
- Что ограничивает: поле `instruction`/`repair_instruction`, которое
  ГЕНЕРИРУЕТ reviewer-модель в JSON (`summary_prompts.py:1053` — схема
  ответа). Это санитайзер вывода модели на одну находку/абзац, а не
  owner-инструкция, не Personality Core/Expression/Style Policy и не
  авторский пример; §2.10 такие поля не защищает.
- Почему не A: удаление снимает защиту от «разогнанного» JSON-поля модели и
  растягивает repair-промпт без требования владельца; доказательств потери
  полезного текста нет (типичный repair_instruction — одна фраза).
- Остаточный риск (не блокер): 500 символов не настраиваются и не
  логируются; если появятся факты урезанной repair-подсказки — вернуться с
  замером, а не удалять вслепую.
- Код не менялся.

## Прогоны (числа)

- `test_quotes_modes.py` — **30 passed** (29 прежних CONTRACT + новый UI F2).
- `test_quota_removal_composer.py` — **8 passed** (7 прежних A1–A6 + новый A7).
- `test_add_exp_expression.py` — 36 passed.
- `test_p0e_expression_frequent.py`, `test_expression_isolation_followup.py`,
  `test_p0_expression_final_contract.py`, `test_soul1_w6_speech_ui.py`,
  `test_unified_core_route_coverage.py`, `test_p0_checkup_core_contract.py`,
  `test_asap3_acceptance.py`, `test_soul1_style_policy.py` — вместе с
  предыдущими **228 passed** (один сводный прогон 11 файлов).
- `tests/ui_asap3_hint_speech_e2e.py` (Playwright, standalone) — PASS,
  10 проверок, JSON `OPENCODE_WORKFLOW_SCRATCH/quota-quotes-fix/ui_asap3.json`.
- RED-подтверждение обоих фиксов: до правки падали ровно два новых теста
  (`test_owner_expression_note_is_not_truncated`,
  `test_ui_preset_no_quotes_leaves_exactly_one_quotes_rule`) и UI-probe
  показывал 2 правила кавычек.

## Вне scope (не менялось)

- `SampleWrite` (`web/api/speech.py:3545-3563`, `max_length=2000/4000`) —
  схема сущности «примеры юмора», не runtime-квота инструкций; в находках
  ревью не значится. Отмечено как incidental.
- `requirements-map.json` / `slice-graph.json`, карты, `plans/current_task.md`
  не трогались — это PM/Orchestrator.
