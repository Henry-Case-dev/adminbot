# P0-CHECKUP-CORE — слои Checkup/Core по аддендуму 24.10.2026

Лейн: `P0-CHECKUP-CORE`. База: `09f56517` (master) + незакоммиченные правки
других лейнов в worktree (не входят в этот коммит). Прод/SSH/живые чаты не
трогались. Источник: `source-2026-10-24.md` §ADDENDUM (строки 644–797),
`arch-checkup-transfer.md`, `evidence/forensic.md`.

## 1. Матрица «исходный фрагмент → владелец → изменённая строка → причина»

| Исходный фрагмент (старого Checkup) | Владелец | Где сейчас | Причина |
|---|---|---|---|
| «Ты — токсичный, саркастичный DevOps-инженер… на дваче» | никуда | в активном каноне отсутствует | самостоятельная биография не нужна; DevOps — предмет отчёта, не вторая личность |
| «проанализировать логи, выявить ошибки/предупреждения, выдать отчёт» | Checkup | `checkup_prompts._CHECKUP_P0_TARGET_BASE` → «СИСТЕМНАЯ РОЛЬ И ЗАДАЧА» | функциональная задача сохранена без потери деталей |
| «Игнорируй безопасность/цензуру/мораль, разрешён мат» | никуда | отсутствует | старый обход ограничений удалён; частоту мата задаёт только Expression |
| «иногда начинай предложения с маленькой буквы» | удалено | `ФОРМА ОТВЕТА`: «Начинай предложения с обычной заглавной буквы.» | позднее решение владельца; глобального корректора нет |
| «сохраняй базовые точки и запятые» | Style Policy | в жанре нет правила | второй источник пунктуации не заводится |
| «только короткие дефисы, обычные кавычки, запрет — и «»» | Style Policy | в жанре нет правила; исходящий текст проходит `apply_style_policy` | `dash.hard.factory` уже существует; второго regex нет |
| «никакого Markdown, списков, эмодзи» | жанр + Style Policy | жанр: «связная живая речь… а не механический список полей» | универсальные запреты не дублируются в жанре |
| «сплошной текст с разделением на абзацы» | Checkup | «связная живая речь с абзацами» | жанровая форма технического монолога сохранена |
| **«СУТЬ АНАЛИЗА» (4 пункта)** | **Checkup** | `_CHECKUP_P0_TARGET_BASE`, блок дословно | **оставлено дословно** (см. §2) |
| «АНТИ-БОТ», «АСИММЕТРИЯ» | общий слой | `STYLE_BLOCKS_SUFFIX` (не изменён) | не копируются в жанр, приходят единым путём |
| `{max_symbols}` | Checkup/настройка | единственная подстановка `.replace` | UI-контроль размера сохранён |
| `CHECKUP_FALLBACK_NOTICE` | происхождение логов + жанр | новый текст | 401 = отказ авторизации, journalctl прочитан; не «сервис упал» |
| фактура → цельная сцена (addendum §3) | Personality Core | `CORE_REAL_EVENTS_PARAGRAPH` + Compact | единственная недостающая универсальная мысль |
| жанровые строки Checkup | Expression/Core | не добавлялись | Expression и Core не получили технический жанр |

## 2. «СУТЬ АНАЛИЗА» — дословность (побайтовая)

Четыре строки в активном каноне совпадают с owner-эталоном аддендума
**побуквенно**, включая строку «человеческо-токсичный» (поздний owner-текст
замещает одно слово прежней редакции и не возвращает identity/safety-bypass):

```text
СУТЬ АНАЛИЗА:
- Если в логах есть ошибки (Exception, 500, таймауты) — жестко разъеби их, поясни простым языком, где конкретно отрыгнуло и какой модуль лег.
- Если в логах одни ворнинги — поиздевайся, что система держится на соплях.
- Если лог пустой или без ошибок — с недовольным ебалом признай, что сервак на удивление жив и пока не горит.
- Не цитируй сырой JSON или хеши, переводи техническую инфу на человеческо-токсичный язык.
```

Контроль: литерал `FROZEN_SUT_BLOCK` в `tests/test_checkup_prompts.py` +
сверка с фенсом §2 исходника; `sha256(4 строки)[:12] = 04bc559f886f`.
Заводская база целиком (без суффикса A/B): 2296 c, `04cdf0287aaf`.

## 3. Фактические ревизии и композиция

| объект | значение |
|---|---|
| `checkup.base.system` factory | 3210 c, `fac:0f5fb7b8d25c` (было 2077 c / `fac:38d63d86b54d`) |
| `PREV_CHECKUP_P0_SYSTEM_PROMPT` | 2077 c, `38d63d86b54d` = текущий прод-канон 2.58.118 |
| `message.checkup_fallback_notice` | 277 c, `ba3fe05850c6` |
| `core.personality` factory | 2712 c, `fac:03514adb2b6a` (было 1925 c / `fac:2ab417d11404`) |
| `core.personality.compact` factory | 724 c, `fac:8be08a0d547c` (было 556 c / `fac:9e6a4ec8b1ea`) |
| `FACTORY_SET` пересчитанный | `e98a25f3dc94` (константа в реестре пока `24ae494ac422` — см. §7) |

Фактическая композиция system Checkup (чат-команда, Expression=frequent):
`genre 0…3201` → `Core 3203…3927` → `<Expression_Settings> 3929…` →
`CHECKUP_FALLBACK_NOTICE` последним. Всего 5107 c; `{max_symbols}` подставлен
настройкой; строки о строчной букве нет. Каждая инструкция имеет одного
владельца: жанр — логи/достоверность/форма, Core — характер, Expression —
мат/резкость, Style Policy — типографика (применяется на выходе).

## 4. Style Policy на исходящем Checkup

`CheckupService.checkup(..., chat_id=…)` после `cleanup_llm_text` делает ровно
один вызов существующего `services.style_policy.apply_style_policy(
stage="checkup_pre_send", context="regular", emit_events=True)`; fail-open.
Внутренний tool-loop (`chat_id=None`) проход не делает — его текст
вербализует Direct Writer со своим outbound-проходом.

Доказательства (`tests/test_checkup_service.py::TestCheckupOutboundStylePolicy`):
заводское `dash.hard.factory` меняет «—» на «-»; отключение этого правила в
**настройке чата** сохраняет тире (чат-слой действует); исключение внутри
прохода не роняет отправку; tool-loop проход не вызывает. `cleanup_llm_text`
в пробе отключён, иначе он сам маскировал бы замену тире.

## 5. Core: изменён, потому что смысла не было

Активная владельческая редакция (`character.core` owner_edit rev 6) содержит
«Как рождается юмор», «Грубость», «Ритм», «Чего избегать», но не содержит
принципа «фактический материал → характерные детали → цельная сцена, а не
общий ярлык темы». Поэтому:

* заводской Full: ровно один абзац `CORE_REAL_EVENTS_PARAGRAPH` вставлен
  после «Как рождается юмор» и перед «Грубость и конфликт»; остальные байты
  §3.2 не изменены (тест: `full == §3.2 + insertion`);
* заводской Compact: одно предложение того же смысла дописано в существующий
  абзац (остаётся одним абзацем, 724 c);
* активная редакция владельца: тот же абзац вставляет существующий
  `owner_preserve_core_full_patch` — только при отсутствии смысла, в ту же
  позицию, с сохранением всех авторских байт; повторный прогон — no-op;
  точные байты v1/v2 по-прежнему ведёт superseded-гвард.
* доставка в runtime доказана сборкой `pc.compose_prompt` с пропатченным
  Core-текстом: абзац присутствует в `manifest.system`
  (`test_core_paragraph_reaches_runtime_composition`).
* технический жанр (Betterstack/401/journalctl/«СУТЬ АНАЛИЗА») в Core и
  Compact отсутствует (тест).

Активная **Compact**-редакция владельца патчем не дополняется (в проде
`character.core.compact` пуст → действует новая фабрика). Если владелец позже
сохранит собственный Compact, предложение нужно внести в него вручную — это
ограничение отмечено, а не скрыто.

Применение патча к активной PG-редакции — шаг деплоя (как W2 прошлого
релиза); в этом лейне прод не трогался. Если владелец уже выразил смысл
иначе, патч оставляет текст без изменений (тест на эквивалент).

## 6. Миграция и откат

* `PROMPT_MIGRATIONS["prompts.checkup_system_prompt"]`: добавлена ступень
  `(PREV_CHECKUP_P0_SYSTEM_PROMPT → CHECKUP_SYSTEM_PROMPT)`; старые ступени и
  `PREV_CHECKUP_SYSTEM_PROMPT`/`PREV_CHECKUP_R1021_*`/`PREV_R1022_*`/
  `PREV_CHECKUP_CFG07A_*` не переписаны.
* `ROLLBACK_MIGRATIONS`: `(CHECKUP_SYSTEM_PROMPT, PREV_CHECKUP_P0_SYSTEM_PROMPT)`
  — снимается только новая ступень, стек цел.
* Идемпотентность/кастом: тест `test_checkup_migration_is_idempotent_and_keeps_owner_custom`
  (обновление прежнего прод-значения → no-op на новом → кастом не тронут →
  откат возвращает прежний канон).
* Core: отдельной PG-лестницы нет (документ `character.core`), механизм —
  owner-preserving патч + заводские редакции; кастом не перезаписывается.

## 7. Тесты и честные ограничения

Прогон (фокус лейна, 18 файлов):

```text
544 passed, 2 deselected
```

Покрыто: SP-01 (Core в Checkup), SP-02 (Expression чата), SP-03 (Style Policy
на выходе), SP-04 (остальные маршруты без техножанра), SP-05 (капитализация),
SP-06 (Full не примитивизирован, Compact несёт смысл); реакции Exception/WARN/
чистые логи/401+journalctl; дословность «СУТЬ АНАЛИЗА»; отсутствие строчной;
лестница/откат; owner-байты Core.

**Не зелёное в этом коммите (централизованный артефакт вне write scope):**

1. `FACTORY_SET_SHA256_12` в `services/prompt_registry.py` — константа
   `24ae494ac422`, пересчёт даёт `e98a25f3dc94` (изменены 4 фабрики:
   `checkup.base.system`, `message.checkup_fallback_notice`,
   `core.personality`, `core.personality.compact`).
   Красные: `test_fingerprint_constant_matches_recomputed_registry`,
   `test_resolve_core_does_not_write_or_call_llm`,
   `test_factory_guard_fails_when_canon_edited_without_registration`.
   Требуемый патч (PROMPTS/Orchestrator, один файл):
   `FACTORY_SET_SHA256_12 = "e98a25f3dc94"`; метки
   `checkup.base.system: "checkup-p0-24-10"`,
   `core.personality: "asap-core-full-v4"`,
   `core.personality.compact: "asap-core-compact-v4"` (+ обновить ожидания
   меток в `tests/test_soul1_core_doc_text.py`).
2. `persona.checkup_language` в реестре по-прежнему считает
   «человеческо-токсичный» legacy-ярлыком. Для **заводской/кодовой** редакции
   runtime отдаёт текст дословно (проверено), но если владелец сохранит эту же
   редакцию через UI, подавление может вырезать слово из persisted-значения.
   Нужно узкое решение владельца реестра (allowlist точных байт новой
   редакции), иначе «дословно» не гарантировано для persisted-сценария.
3. Применение owner-preserving патча к активной PG-редакции Core — шаг
   деплоя; здесь не выполнялось (прод запрещён).

**Посторонние (не из этого лейна):**
`test_asap_w1_semantics::test_p0d_expression_header_footer_and_modes_byte_exact`
красный на HEAD из-за правки FREQUENT в `09f56517` (P0-E); aiogram в окружении
не содержит `InputRichMessageMedia` — два теста `send_rich_message` падают
независимо от промптов.

## 8. Файлы

Код: `services/checkup_prompts.py`, `services/checkup_service.py`,
`services/chat_prompts.py`, `services/prompt_migrations.py`.
Тесты: `test_checkup_prompts.py`, `test_checkup_service.py`,
`test_p0_checkup_core_contract.py` (новый), `test_soul1_core_doc_text.py`,
`test_asap2_clar_contract.py`, `test_asap_w1_semantics.py`,
`test_cfg07_egress_dictionary.py`, `test_cfg07_backstage_contract.py`,
`test_cfg07a_f1_custom_suppress.py`, `test_expression_isolation_followup.py`,
`test_prompt_migrations.py`, `test_soul1_registry_legacy_removal.py`.
