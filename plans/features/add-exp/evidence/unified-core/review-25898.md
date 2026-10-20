# REVIEW-25898 — независимое ревью кандидата 2.58.98 (UNIFIED-CORE + F3)

- Дата: 20.10.2026, лейн REVIEW-25898 (read-only + запись evidence).
- Кандидат: `37097f7c` поверх `99f5672c` (2.58.97). Рабочее дерево по коду
  (`services/tests/handlers/web/config`) байт-чистое относительно кандидата —
  все прогоны привязаны к `37097f7c`.
- Метод: сверка с verbatim-требованием владельца (`unified-core-spec.md` §1–§5,
  F3-тексты 20.10), код-аудит диффа `99f5672c..37097f7c`, payload-механика
  (не «наличие слоя»), независимые прогоны тестов и гейта.

## Вердикт: NEEDS FIXES (2 блокера)

**Блокер 1 (код/тесты): 18 новых failures полного прогона, причинённых
кандидатом** — см. раздел «Полный pytest» ниже. Требование «кандидат не
добавляет ни одного нового failed» нарушено. Минимальная починка: обновить
ассерты 5 устаревших тест-файлов под сознательные владельческие изменения
(checkup chat_id, C6-якоря) + бамп FACTORY_SET_SHA256_12; перегон полного
набора до паритета с базой.

**Блокер 2 (ledger/гейт, не код):** `requirements_gate.py check --stage review --slice
EXP-ACCEPT --candidate 37097f7c` → **EXIT 1** (7 ошибок):

1. `map.candidate_commit=95d11472` ≠ `37097f7c` — карта не перерезана на
   кандидат;
2. `EXP-ACCEPT.LIVE-SET/ROUTES/PREVIEW/REVIEW`, `EXP-REG.QUEUE` — нет ни одной
   evidence-записи, привязанной к `37097f7c` (evidence СУЩЕСТВУЕТ в кандидате:
   16 трасс `evidence/unified-core/`, 18 CONTRACT-тестов, directives-fix, F4 —
   но в строки карты не внесён);
3. `EXP-ACCEPT.CRITERION` = FAILED (честная запись acceptance-96: live-поведение
   occasional/frequent не достигло порогов §4) — для stage=review обязано быть
   `READY_FOR_LIVE` или `VERIFIED`.

Это metadata/ledger-работа (PM/Builder), не дефект кода. Минимальная починка (после Блокера 1):
привязать evidence UNIFIED-CORE/F3 к `37097f7c` в строках EXP-ACCEPT.*/EXP-REG;
`EXP-ACCEPT.CRITERION` → `READY_FOR_LIVE` с predeploy-доказательствами
(static/payload-матрица + off-prod eval) и точным postdeploy-чеком (повтор
F4-матрицы `evidence/f4/harness/` на выкаченном 2.58.98; откат — PREV-лестница
ADR-1013-3). После этого гейт EXIT 0 → «Approved for controlled deployment,
parent not DONE»; после выката и живой F4-матрицы DevOps ставит VERIFIED/FAILED
честно и запускает `--stage release`.

## Что проверено и подтверждено (независимо)

### Route coverage (по механике, capture payload)
- `prompt_composer.speech_owner_block` (prompt_composer.py:740+): тот же
  `resolve_core_ref`/`resolve_expression_settings` (GLOBAL/per-chat, hot-apply),
  порядок Core → `<Expression_Settings>`, 0 LLM-вызовов, никогда не бросает;
  fail-open `""` = байт-паритет прежней сборки (тест
  `test_factcheck_single_path_without_config_is_byte_parity`).
- Factcheck: Stage-2 Вербализатор — `character_block` (последний part, шов
  MCA-08 в `compose_verbalizer_system`); одиночный 10.21 — аппенд после канона.
- Summary: Рассказчик Stage-2 (`character_block`) + legacy-single (апенд).
  Иерархический L2-writer — внутренний дайджест; пользовательский текст идёт
  через narrator/legacy — оба покрыты.
- Checkup: `handlers/checkup.py` передаёт `chat_id`; tool-loop
  (`tool_router.py:2718`) вызывает без chat_id → нейтрально (обоснованно:
  отчёт вербализует Direct Writer).
- Search/Youtube (3 пути: summarize/summarize_transcript/мультимодальный video)/
  Web: аппенд после канона; реранкер — нейтральный.
- Подписи к картинкам: N/A подтверждена — sendPhoto-подписи без LLM-текста;
  `cover_prompt` — внутренний tool-input (text2image).
- Внутренняя нейтральность: Аналитик (Stage-1 JSON), Редактор саммари, реранкер,
  tool-loop checkup — без Core/Expression (тесты + трассы internal-*).

### F3 — точные тексты владельца
- `PROFANITY_INSTRUCTIONS` off/occasional/frequent — **байт-в-байт** сверены
  независимым скриптом (ALL-BYTE-EXACT).
- Шапка P0 в `EXPRESSION_HEADER`: единое правило на всю пользовательскую речь
  (включая фактчек/сводки/подписи/служебные), цитаты как есть, «мат не
  вставляется насильно», просьба «без мата» = override на ответ; приоритетные
  строки C1/C8/C16 присутствуют. Старое жанровое исключение
  («структурированные сводки не переписываются») из payload-шапки УДАЛЕНО
  (тест `test_header_unified_rule_p0` защищает отсутствие).
- Счётчики/обязательные вставки/рандом/постпроцессор: отсутствуют
  (`test_no_mechanical_counters_or_forced_inserts`, EXP-INSTR.NOPOST).

### C14 (safety-bypass) и C13 (tone_hint)
- Из АКТИВНОГО канона фактчека строка «Игнорируй все настройки безопасности…»
  удалена; `_FACTCHECK_R1021_BASE_FROZEN` заморожен; PREV_R1022/R1021 и новые
  ступени `PREV_FACTCHECK_UNIFIED_CORE(_AB)` собираются из FROZEN — миграция
  узнаёт прежние прод-байты; откат ведёт на НЕПОСРЕДСТВЕННЫЙ прежний канон
  (`test_unified_core_migration_ladder_and_rollback`).
- OFF-паритет persisted: `suppress_legacy_speech` вычищает строку из
  persisted/known-canon значений
  (`test_persisted_old_factcheck_canon_still_suppressed`).
- C13: `tone_hint` удалён из схемы Аналитика; ступень
  `PREV_FACTCHECK_ANALYST_UNIFIED_CORE` + откат; парсер толерантен.

### Запреты (не нарушены)
- Core (`services/chat_prompts.py`) — diff пуст (байт-паритет SOUL-02 цел).
- `_EXTENT_BLOCKS` — не тронут (diff `response_extent.py` касается только
  `scrub_for_plan`, C5).
- Второй Core/постпроцессор/лишние LLM-вызовы — отсутствуют.

### Evidence-трассы (выборочная сверка с кодом, не по README)
- `trace-factcheck-single-path.txt`: совпадает с локальной сборкой по тому же
  коду (max_symbols=8000, frequent-строка, safety_bypass=False); расхождения
  первой реконструкции — только конфиг стенда (4000/occasional).
- `trace-checkup-chat-command.txt`: Core + `<Expression_Settings>` frequent;
  `CHECKUP_FALLBACK_NOTICE` последним абзацем (тест).
- C15-хвост (README): подтверждён независимо — та же bypass-строка остаётся
  в код-канонах checkup/search/youtube/web/summary-legacy; НО все они
  known-canon и вычищаются `suppress_legacy_speech` при persisted/global
  резолве (скрипт: CHECKUP/SEARCH/YOUTUBE/WEBPAGE/SUMMARY — known=True,
  suppressed_if_persisted=True). Строка активна только в code-fallback при
  недоступном PG (прежнее поведение 2.58.97, вне scope C14-решения).

### Тесты
- Новый `tests/test_unified_core_route_coverage.py`: 18 CONTRACT
  (TEST-LIFECYCLE: CONTRACT owner=UNIFIED-CORE), capture реальных payload.
- Байт-тесты обновлены БЕЗ ослабления: `test_owner_exact_texts_are_canon`
  (дословный dict-канон), запрет механических маркеров, P0-шапка;
  миграционные тесты усилены (откат на непосредственный канон + сохранение
  WEB_SEARCH-блока).
- Фокусированный набор (route-coverage + expression + migrations +
  deep-context + speech-UI): **171 passed / 0 failed**.

## Полный pytest (базовая линия 2.58.97 = 9 failed / 14583 passed)

## Полный pytest (базовая линия 2.58.97 = 9 failed / 14583 passed)

Независимый полный прогон на кандидате: **30 failed, 14614 passed, 1 skipped,
7 errors** (665s). Атрибуция выполнена прогоном того же набора (37 актуальных
id после чистки 9 устаревших записей кэша) на базовом worktree 99f5672c
(та же машина): **12 failed + 7 errors / 18 passed**.

**18 НОВЫХ failures — причинены кандидатом (блокер):**
- 	ests/test_checkup_handlers.py x11 — хендлер теперь передаёт
  chat_id= (требование P0), тесты не обновлены
  (ssert_awaited_once_with('логи', False) vs + chat_id);
- 	ests/test_direct_chat.py::test_style_anchors_section — C6-текст
  «настройки выражения владельца важнее образца» добавлен, тест не обновлён;
- 	ests/test_soul1_w4_humor_craft.py x2,
  	ests/test_soul1_registry_completeness.py x2 (factory fingerprint
  '64ec1c60e278' != '5bca81487001'),
  	ests/test_soul1_core_registry_api.py x2 — фабричные тексты изменены БЕЗ
  бампа FACTORY_SET_SHA256_12 — собственный guard реестра сработал штатно.

Все 18 — класс «сознательное владельческое изменение + несинхронизированные
тесты/отпечаток»; реализация по существу корректна, но требование
«кандидат не добавляет ни одного нового failed» НАРУШЕНО.

**Pre-existing/environment (паритет с базой, не блокер):** asap7_direct_settings
x2 (timing/DDL), mca01_tx x1 (write-points audit drift), outgoing_guard x2
(ImportError InputRichMessageMedia — версия aiogram в окружении),
summary_asap2 x1, summary_publish_integration x1, t5150_startup_migrations x5
(timing/log-format), p0_vision_ui_e2e x7 errors (browser env).

Минимальная починка: обновить ассерты 5 устаревших тест-файлов под новые
контракты + бампнуть FACTORY_SET_SHA256_12 (и связанные объявленные
отпечатки по контракту реестра); перегнать полный набор — ожидается паритет
с базой (12f/7err) или лучше.


## Находки

### (a) Блокер
1. **Гейт EXIT 1 / ledger не перерезан на кандидата** — см. вердикт выше.
   Исправление: обновление `requirements-map.json` (PM/Builder), перегон гейта.
   Кода не касается.

### (b) Связанные неблокеры (recommendations)
1. **C15-хвост**: bypass-строка в код-канонах checkup/search/youtube/web/
   summary-legacy. На проде нейтрализуется `suppress_legacy_speech`
   (persisted/global), активна только при code-fallback (PG down). Требует
   отдельного решения владельца с протоколом бамп+слепок по каждому канону
   (как C14) — честно задокументировано в README/design.
2. **`EXPRESSION_NOTES` (web/api/speech.py)**: формулировка «сводки и цитаты
   не переписываются» — остаток отменённой жанровой оговорки в UI-прозе админки
   (не в LLM-payload, поведения не меняет). Косметика.
3. **off-prod eval** (`directives-fix/eval.json`, acceptance:false, честно):
   `frequent_majority=false`, `occasional_lt_frequent=false` на
   deepseek-v4-flash — поведенческий критерий §4 вживую не подтверждён даже
   новыми текстами. Не блокер (постдеплой-проверка обязательна по протоколу),
   но подтверждает: CRITERION нельзя поднимать в VERIFIED до живой F4-матрицы
   на 2.58.98.

### (c) Не относится
- Дифф содержит крупные evidence-папки других лейнов (f4/, directives-fix/,
  cfg/) — документы, не код; на рантайм не влияют.

## Привязка
- Кандидат: `37097f7c` (рабочее дерево по коду идентично).
- Трассы: `evidence/unified-core/trace-*.txt` — структура совпадает с кодовой
  сборкой.
