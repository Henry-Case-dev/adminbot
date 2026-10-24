# REV-QUOTA-QUOTES — независимое ревью (read-only)

Дата: 24.10.2026. Ревьюер: REV-QUOTA-QUOTES.
Проверяемый кандидат: `ddd2d9f7` (HEAD на момент ревью), включая целевые
`73963d0c` (QUOTA-REMOVAL, A1–A6), `0315696b` (QUOTES-MODES), плюс
`9f0f6ce8` (QUOTA-UI-CLEANUP, закрыл TypeError в `_core_ref_from_doc`) и
`ddd2d9f7` (docs FREQUENT probe, вне scope). Незакоммиченных изменений кода нет.
Evidence: `evidence/quota-removal.md` (73963d0c), `evidence/quotes.md` (0315696b),
`evidence/quota-ui.md` (9f0f6ce8); `arch-quota-audit.md`.

## Вердикт: Needs Fixes

A1–A6 и кавычки в основном сделаны, B не тронут, новых квот нет. Но остаётся
одна A-квота инструкции (не входившая в A1–A6) и дефект взаимоисключения
кавычек при применении пресета `no_quotes`.

## Acceptance ledger

| Пункт | Статус | Доказательство |
|---|---|---|
| A1 `composer_additive_budget_tokens`/env/дефолт 1200 удалены | VERIFIED | функции нет (`hasattr` false), env игнорируется, тесты 186 |
| A2/A3/A6 вытеснение слоёв и `budget_excluded` удалены | VERIFIED | `prompt_composer.py` без `budget/consumed`; `SKIP_REASONS` без причины; hint рендерится при env=1 |
| A4 Core `full→compact` по квоте удалён | VERIFIED | `core_selection` без `budget_tokens`; `owner_setting` сохраняется; `context_budget` нет |
| A5 few-shot render caps 4/700/140 удалены | VERIFIED | констант нет; все строки в блоке; `ExampleRender` числа честные |
| A6 служебные конфликты бюджета не производятся | VERIFIED | `core_protected_from_budget`/`expression_protected_from_budget` не появляются |
| A7 (обнаружено ревью): квота на owner-инструкцию Expression | **FAILED** | `mca_expression.py:248` `note[:2000]`; 3614-символьное «Пожелание владельца» → 2000, хвост теряется в `<Expression_Settings>` |
| B сохранено | VERIFIED | `model_capacity`/`CHAT_CONTEXT_BUDGET_TOKENS`, summary hybrid, `max_tokens`, retry/fallback/таймауты, rate limits, выборки/ранжирование, модуль «Бюджеты» не менялись |
| Новых квот нет | VERIFIED | новых лимитов инструкций не добавлено; AGENTS.md §2.10 добавлен |
| Кавычки A/B/OFF, содержимое, protected, UI, global/chat | VERIFIED | 29 CONTRACT-тестов; реальные прогоны A/B/OFF; скриншоты 390/1280; save/reload |
| Семантика кавычек удалена | VERIFIED | `_quote_positions`/`_protected_machine_quotes`/`ironic_quotes_removed`/`quotes_require_rephrase` в prod-коде отсутствуют |
| Взаимоисключение кавычек при пресете `no_quotes` | **FAILED (small)** | клик «+ Без кавычек» → Save сохраняет 2 включённых правила: `quotes.hard.factory` normalize + `quotation_marks.hard.no_graphic` strip; runtime collapse спасает от двойной обработки, но «одна настройка = одно правило» нарушено |
| C1/C6 аудита | UNVERIFIED (вне A1–A6) | C1 `chat_style_anchor_max_chars` и C6 `instruction[:500]` оставлены C без решения; полный ADDENDUM #3 не закрыт |
| Payload/реальное окно | UNVERIFIED (live) | рост payload не измерен на боевой модели; `model_capacity` путь есть, но live-проверки не было |

## Blocking findings

### F1 (BLOCKER) — остаточная A-квота: owner-инструкция Expression режется на 2000 символов
- Требование: ADDENDUM #3 §2.2/§2.6, AGENTS.md §2.10 — нельзя искусственно
  обрезать управляющие инструкции; «Пожелание владельца» — именно инструкция.
- Место: `services/mca_expression.py:248` (`normalize_expression`), используется
  в `build_expression_settings` (`:356-358`).
- Воспроизведение: note 3614 символов → `normalize_expression` даёт 2000,
  маркер `_КОНЕЦ` отсутствует; в реальном `<Expression_Settings>` текст тоже
  обрезан. UI-textarea без `maxlength`, т.е. квота скрытая.
- Влияние: владелец пишет длинное пожелание — хвост молча не доходит до модели.
- Минимальное исправление: убрать `[:2000]` (оставить приведение к str);
  добавить REGRESSION-тест «note > 2000 → хвост в `build_expression_settings`».
- Recheck: этот тест + `test_p0e_expression_frequent.py` + `test_add_exp_expression.py`.

### F2 (RELATED_SMALL) — `no_quotes` оставляет два конкурирующих правила кавычек
- Требование: §1 «Режимы взаимоисключающие… без конкурирующей обработки»,
  «одна настройка = одно правило».
- Место: `web/app.js:addStylePreset` (пушит preset-правило, не сворачивая
  существующее `quotes.hard.factory`); `_collapse_quotes_rules` работает только
  в `effective_policy_sync`, не при сохранении.
- Воспроизведение (Playwright probe, `.venv`): открыть «Стиль письма» →
  «+ Без кавычек» → Save; в документе 2 включённых `quotation_marks`
  (normalize + strip); чекбоксы при этом показывают только B.
- Влияние: в списке правил видны два включённых режима, один из них инертен;
  сохранённый документ нарушает заявленное «одно правило». Runtime collapse
  предотвращает двойную обработку, поэтому это small, но контракт витрины
  нарушен.
- Минимальное исправление: при добавлении preset с `kind=quotation_marks`
  заменять существующие quote-правила одним (или нормализовать документ на
  save); UI-тест: preset → ровно одно правило, B включён, A выключен.
- Recheck: тот же probe-сценарий + `tests/test_quotes_modes.py`.

## Nonblocking / risks

- C1 `direct_chat_service.py:7826-7829` (`chat_style_anchor_max_chars`, 400) —
  аудит оставил C; это примеры стиля (данные прошлых ответов), не owner-промпт;
  нужно решение Architect/PM, не удалять вслепую.
- C6 `summary_l2_review.py:390`, `summary_l2_anchor_repair.py:246`
  (`instruction[:500]`) — аудит оставил C; это модельный repair-instruction,
  не owner-системный промпт; решение не принято.
- `EXPRESSION_RESOLVE_MAX_ITEMS=4` (`mca_sample_library.py:71`) — **B**:
  ограничение числа элементов выборки/ранжирования, прямо сохранено §2.6;
  не A. Потеря видна числами `kept=4/N`.
- URL с литеральной кавычкой: `strip` на `https://x/y?q="z"` даёт
  `https://x/y?q=z`; сегментер считает кавычку обычным текстом. URL уже
  невалиден; edge, не блокер, но тест `test_url_is_kept...` этот случай не ловит.
- `web/app.js` всё ещё содержит мёртвые подписи `budget_excluded`/
  `context_budget`; производителя нет, это витрина без настройки (UI-полоса
  уже удалила `_composer_budget` в `9f0f6ce8`). Косметика.
- `tests/test_soul1_style_policy.py:379` всё ещё допускает
  `quotes_require_rephrase` для unparseable JSON; фактический исход —
  `protected_verbatim`, тест проходит, но допущение устарело.
- `requirements-map.json`: все `REQ-ADD3-*` — PENDING, evidence-файлы не
  привязаны к строкам; `slice-graph.json` указывает несуществующие
  `test_p0q_quotes_modes.py`/`test_p0q_composer_quota.py` (фактические —
  `test_quotes_modes.py`/`test_quota_removal_composer.py`). Нужно PM/Orchestrator,
  не код-блокер.

## Числа (что реально прогнано)

- `test_quota_removal_composer.py` + composer/soul1/asap3 набор: **186 passed**
  (179 + 7).
- `test_quotes_modes.py` + `test_quota_removal_composer.py`: **36 passed**
  (29 quotes + 7 quota).
- style-набор (`test_quotes_modes`, `test_soul1_style_policy`,
  `test_soul1_style_payload`, `test_soul1_style_repetition`,
  `test_asap3_style_hint_limits`): **139 passed**.
- `-k "soul1 or inspector or prompt_layers or mca_events"`: **689 passed,
  1 order-flake** (`test_soul1_w5_initiative_vitality...`; в изоляции проходит).
- Pre-existing подтверждены на базе `141e1e49`: 8 failed (5 direct_fallback,
  1 summary, 2 asap7) + 7 errors (нет playwright) — те же и на HEAD.
  Полный набор 2592/9+7 не перепрогонялся; именованные падения проверены.
- UI: скриншоты `OPENCODE_WORKFLOW_SCRATCH/quotes-modes-ui/shots/` 390/1280
  осмотрены; default A=ON/B=OFF, OFF и B читаемы, обрезки нет.

## Можно ли в поезд

**Нет, пока не исправлены F1 и F2.** После них — да для контролируемого
деплоя: A1–A6 и B не вызывают возражений, кавычки детерминированы и защищены.
Перед релизом всё ещё нужны: живой замер payload/окна на боевой модели,
решение по C1/C6 и обновление строк карты/слайс-графа. Полный ADDENDUM #3
сейчас закрывать нельзя.

## Requirements gate (проверено)

`py -3 <OPENCODE_CONFIG>/tools/requirements_gate.py check --stage review
--slice COMPOSER-QUOTA --candidate ddd2d9f7 --repo .` → **EXIT 1**:
`candidate mismatch; map candidate_commit must match --candidate` +
все `REQ-ADD3-CQ-*` PENDING (15 errors).
`--slice QUOTES` → **EXIT 1**: все `REQ-ADD3-Q-*` PENDING (27 errors).
Это не дефект кода, а незакрытая привязка карты: `candidate_commit` в карте
всё ещё `c128675a`, строки ADD3 не переведены в VERIFIED. PM/Orchestrator
должен обновить карту/слайс-граф после исправлений F1/F2 и повторного ревью.

## F0 — регрессия целевого коммита, уже исправлена в HEAD

На `73963d0c` `web/api/speech.py:_core_ref_from_doc` передавал
`budget_tokens=` в `core_selection`, который этот kwarg уже не принимает →
`TypeError`; `POST /api/speech/try` («Попробовать») и preview Inspector падали
при наличии Core-документа. Коммит `9f0f6ce8` (QUOTA-UI-CLEANUP) убрал вызов;
на HEAD `_core_ref_from_doc(None)` возвращает CoreRef, тест
`test_s10_no_composer_budget_plumbing_in_inspector` проходит. Если родитель
связывает вердикт только с `73963d0c`, это отдельный блокер; для `ddd2d9f7`
он закрыт.
