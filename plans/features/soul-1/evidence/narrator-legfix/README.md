# Narrator-канон LEGFIX — закрытие backlog «narrator-канон identity-фраза»

Лейн: FIX-SMALL-DEFECTS (leaf). Дата: 2026-10-22. База: HEAD `804f4963`
(рабочее дерево + дельта лейна). Платных вызовов 0, Telegram-сообщений 0.

## 1. Оценка (до правки): дефект, не легитимная фраза

Finding — `plans/features/cfg/evidence/cfg-final/bindings.md` §6 (CFG-FINAL,
21.10.2026): активный канон `SUMMARY_NARRATOR_SYSTEM_PROMPT`
(потребитель `services/summary_generator.py:4063`, ключ
`prompts.summary_narrator_system_prompt`) несёт identity-фразу
«Ты — токсичный, ироничный участник чата (бот-абьюзер) и завсегдатай
двача» — вне корпуса SF (17 SOURCE_FIX) и 7 маршрутов 07A-2.

Вердикт **дефект** (класс SF-07 «identity legacy-личности»), не
not-a-defect. Основания — собственные принятые контракты проекта:

1. **CFG-07A-2 (20.10.2026, ADR-1013-3)** — та же фраза (маркер SF-07
   «участник чата (бот-абьюзер) и завсегдатай двача») вычищена из 7
   маршрутов; Рассказчик остался вне того корпуса — §6 классифицировал как
   related-nonblocking backlog-кандидат (отложено, НЕ легитимизировано).
2. **UNIFIED-CORE P0 (20.10.2026)** — «Рассказчик — пользовательская речь →
   ТЕ ЖЕ Core + Expression; жанровые исключения сняты»: голос/характер
   задаёт Core, а не канон (прецедент suppress-правила 10
   `summary.l2_legacy_voice_reference`: «сохраняй характер бота…» →
   «держи голос Core»).
3. **Реестр prompt_registry** — блок `summary.base.narrator` помечен
   `speech=True, legacy_persona=True` и входит в `withholding_blocks`
   (машина сама классифицирует канон как legacy-persona); suppress-правило 1
   `persona.identity_sentence` удаляет ровно это предложение из
   persisted-значений.
4. Публичный egress (public_speech_guard) защищает OUTPUT, но не заменяет
   канон: identity-инструкция в system-промпте публичной речи — источник
   риска самоназвания («бот-абьюзер», «завсегдатай двача») в тексте
   саммари — класс honesty, от которого проект чистит каноны.

## 2. Правка (минимальная, по прецеденту CFG-07A-2)

* `services/summary_prompts.py`: активная база переведена на
  `_SUMMARY_NARRATOR_LEGFIX_BASE` — снято ТОЛЬКО identity-предложение
  (задача строки сохранена: «Ты получаешь ТОЛЬКО готовую выжимку…»);
  жанровые правила 1–4, `{max_symbols}`, TYPOGRAPHY/STYLE-блоки —
  без изменений. Прежняя база R1028 не тронута (байт-в-байт).
* Лестница/откат (`services/prompt_migrations.py`): ступень LEGFIX
  `(PREV_SUMMARY_NARRATOR_LEGFIX → SUMMARY_NARRATOR_SYSTEM_PROMPT)`;
  откат ведёт на НЕПОСРЕДСТВЕННЫЙ прежний канон (стек ступеней цел,
  ADR-1013-3).
* `services/prompt_registry.py`: метка ревизии
  `summary.base.narrator: summary-narrator-legfix`; FACTORY_SET-бамп
  **3507bd6f92eb → 553a281fe2fd** (changed = 1, SOUL-AMD.3.2).

## 3. Хэши и идемпотентность

| Значение | SHA256[:12] | Длина |
|---|---|---|
| Новый канон (`SUMMARY_NARRATOR_SYSTEM_PROMPT`) | `5086ba935081` | 1788 |
| Прежний канон (`PREV_SUMMARY_NARRATOR_LEGFIX`) | `f02b6ca755a4` | 1863 |
| PREV_R1028 / PREV_R1023 (не менялись) | `9798de3f6b33` / `91ff9a67f700` | — |

Оба байта в `known_canon_hashes()` (ступень узнаёт прод-PG-значения,
откат работает). Прод-PG `prompts.summary_narrator_system_prompt` = прежний
код-канон (сид по `code_source`) → миграция LEGFIX обновит его при старте;
владельческий кастом не трогается (known-canon гейт подавления).

## 4. Проверки

* REGRESSION `test_summary_asap21_prompt_migrations.py::
  test_narrator_canon_has_no_identity_legacy` — активный канон без
  «токсичн/бот-абьюзер/двач», `legacy_persona_present == False`, жанровые
  контракты целы, PREV несёт снятую фразу (RED-эквивалент: на pre-fix
  дереве маркеры присутствовали в каноне по определению).
* Лестница/откат: `narr_legfix` в `_CANON_CASES` + откат `_ROLLBACK_CASES`
  на `PREV_SUMMARY_NARRATOR_LEGFIX` (asap21 + prompt_migrations).
* Пин-тесты SOUL-1 обновлены по прецеденту CFG-07A-2 (фабрика вычищена —
  подавление проверяется на persisted-байтах PREV): `_PERSISTED_BYTES`,
  `cleaned_factories` в `test_soul1_registry_completeness`.
* Фабрики/фингерпринт: `factory_set_fingerprint() == FACTORY_SET_SHA256_12`
  (`test_soul1_registry_completeness` зелёный).
* Focused-семья 22.10.2026 (venv, aiogram 3.31.0): cfg03/f8/cfg02b/hot-
  migration/webapp/soul1/asap21/prompt_migrations/backstage/route-coverage/
  verbilizer/target-marking/two-call/l2/l1/fewshot/selfhost — **823 passed**.
  2 падения `test_outgoing_guard_round1022` на системном python — известный
  pre-existing aiogram 3.29.1 `InputRichMessageMedia` (backlog W1), на
  проектном venv 25 passed.

## 5. Не входит в слайс

Factcheck-канон «завсегдатай двача» (W3-freeze, CFG-06) и прочие
checkup/youtube/web/search-хвосты — вне дельты (уже покрыты 07A-2 либо
фризом); kill-switch OFF-путь (`PREV_SUMMARY_NARRATOR_R1023`) —
намеренно байт-в-байт прежний (OFF-паритет W2).
