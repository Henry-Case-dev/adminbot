# POST-ASAP5 CORRECTIVE — REVIEW W1+W2 (review-w12.md)

Ревьюер: независимый Reviewer (leaf-полоса REVIEW-POST-ASAP5-W12), 27.10.2026.
Кандидат: **dec28b9931b9bbb7b70904ae6cfbb4efdf4d4d04** (feat W1+W2), докс-тип **4a06f612**, база **bd8f9c34** (release/p0-2026-10-26, прод 2.58.135 @ 05c408f6).
Ворктри ревью: `C:\Code\Python\adminbot-wt-pa5-rev` (detached @ dec28b99). Код не менялся; живых LLM/SSH/Telegram-вызовов не было.
Вердикт: **Approved** (по объёму волн W1+W2; родитель НЕ завершён — S2/S9/S10-*/S11/S12 открыты, live-проба и деплой — отдельные полосы).

## 1. Owner-guard (исходник §3/§4/§5/§6/§7/§8/§10)

| Требование | Статус | Независимая проверка |
|---|---|---|
| §8 вербатим-директива (строка 473) РОВНО 1 раз в writer-пути | OK | `WRITER_FOCUS_DIRECTIVE_TEXT` байт-равен L473 снапшота; определение 1× (`prompt_style_blocks.py`), носитель один — plan-блок (`direct_l1.build_l2_plan_block`, безусловный одиночный append); grep фрагмента по services — только файл определения; тесты «ровно 1×» на casual/answer/research/deep + fallback — зелёные |
| Без композиционных приказов, квот, слобных хардкодов | OK | В новых текстах нет «шина/чипы/забей»/чисел инцидента/Crescent (проверено grep-ом по секциям); тесты no_quota/no_incident_words — зелёные; ADDENDUM #3 §2.10 соблюдён (правило 4 не сжато, раскрыто в w2.md) |
| NO_META (announcement-only) и DELTA (research-ready) не регрессировали | OK | Оба текста диффом не тронуты; прогон `-k "delta_depth_instruction or meta_closing or no_meta"` — 20 PASS |
| §10 LPDDR — только тест, не рантайм | OK | Чисел контрольного примера (448/38 400/9600/11.67/Crescent/LPDDR) нет ни в одном runtime-каноне (grep по services); guard-тест `test_writer_42_control_example_not_hardcoded_anywhere` фиксирует отсутствие во всех носителях и в исходнике chat_prompts.py |
| §6.2 гипотезы не запрещены, а помечаются | OK | Секция Writer: «гипотеза, оценка и инженерное рассуждение допустимы… предположением, а не установленным фактом», «формулы… подтверждений не требуют», «нужна достоверность, а не нерешительность»; тест §6.2 зелёный |
| Без новых слоёв/роутеров/LLM-вызовов | OK | Новых файлов сервисов нет; composer/router не расширялись; `gen_param_registry_round1025.py --check` OK (587, TSV/map идемпотентны) |

## 2. Качество фиксов и конвенции

- **§3 (W1)**: секция «ИЗМЕНЕНИЕ ЗАДАЧИ И ВОЗРАЖЕНИЯ» семантическая: пересмотр постановки, различение уточнение/возражение/новый вопрос, снятые условия не обязательны, допущение ≠ требование человека, прежний ответ — контекст а не доказательство, отсутствие ложной симметрии, disagreement только при реальном споре. Словных триггеров нет.
- **§5 (W2)**: первопричины по коду (канон L1 не упоминал web_search; правило 4 смещало к пустому набору; tool-phase фреймил поиск как «новости») исправлены минимально: правило 4 редакции PA5W2 (обе стороны §5.2 + honest-unknown §10.5) + секция tool-phase «ПОИСК И НЕПОДТВЕРЖДЁННЫЕ ХАРАКТЕРИСТИКИ». Правила 1-3 и 5-9 байт-в-байт прежние (проверено сравнением префикса/суффикса).
- **§4 (W2)**: семантика в Writer-каноне: оценка/архитектура/реализация/совместимость (§4.1), размерности и корпуса≠каналы (§4.2), невозможность реализации ≠ невозможность принципа (§4.3); в tool-phase — честная граница при недоступном поиске (§10.5).
- **Лестница ADR-1013-3**: `PREV_DIRECT_L1_PLANNER_PA5W1` = прод-байты базы bd8f9c34 (sha12 `422e9d73d316`, сверено прямым импортом обеих баз); `PREV_DIRECT_L1_PLANNER_PA5W2` = активные байты W1 (`902dd00edf52`); `PREV_CHAT_W2_SYSTEM_PROMPT` = прод tool-phase (`f30c6d73da82`); `PREV_CHAT_VERBALIZER_PA5W2` = прод Writer (`83ff62bbee40`). FACTORY_SET переподтверждён дважды: `82031ca737ed` → (W1) `517ec51bec11` → (W2) `3bc0c543520c`, документировано «Было/стало»; ступени миграции и головы отката слоёные (ред.6→5→4→3→2→1), dry-run покрыт test_prompt_migrations.

## 3. Строки карты (докс-тип 4a06f612)

VERIFIED и байндинги артефактов: sha256 сверены (w1.md `2040423c…`, w2.md `325f45cd…`, тест-файлы `32c12478…`@3c0c4519 / `6cd4d488…` / `e59e6c8b…`); W1-строки байндят кандидата 3c0c4519 с артефактами того состояния — корректно; повторное подтверждение W1-строк на W2-кандидате выполнено PM в 1867045d (вне моего докс-типа, отмечено оркестратору). Структурный гейт requirements_gate `--stage review --candidate dec28b99` — PASS по всем 14 строкам (strict_evidence=true, errors=0).

| Slice | Строки | Статус |
|---|---|---|
| W1 (3c0c4519) | PA5-S3-INTENT, PA5-S3-CONTRA, PA5-S7-AUTHORITY, PA5-S7-CHARACTER, PA5-S7-OBJECTION, PA5-S8-SPEECH | 6 × VERIFIED, гейт PASS |
| W2 (dec28b99) | PA5-S4-MODEL, PA5-S4-DIM, PA5-S4-PRINCIPLE, PA5-S5-DEFECT, PA5-S5-WHEN, PA5-S5-TOOLS, PA5-S6-HALLUC, PA5-S6-HYPOTH | 8 × VERIFIED, гейт PASS |
| Честные PENDING | PA5-QUEUE, PA5-S1/S2, PA5-S9-ALIGN, PA5-S10-1..7, PA5-S11-REVIEWER, PA5-S12-DELIVERY/REPORT (postdeploy), PA5-GOAL | PENDING — ожидаемо (live-проба провайдером — волна 3, отдельная полоса) |

Примечание: в брифе указано «W2 = 7 строк», фактически в карте 8 VERIFIED (S4×3+S5×3+S6×2) — карта внутренне консистентна, расхождение в арифметике брифа (клерикальное, к кандидату не относится).

## 4. Прогоны (ворктри dec28b99)

- `pytest tests/test_post_asap5_w1_writer_core.py tests/test_post_asap5_w2_tech_reasoning.py -q` → **42 passed** (18 W1 + 24 W2).
- Фокус: `pytest tests -k "post_asap5 or direct_l1 or writer or prompt_migration or response_extent" -q` → **294 passed, 1 failed** (`test_mca01_tx_task_supervisor_round1027::test_write_points_go_through_single_writer` — воспроизводится 1-в-1 на базе bd8f9c34, вне области кандидата).
- Изменённые тест-файлы (12 файлов + новые 2) → **255 passed, 1 failed** (тот же класс: `test_p0_prompts_core::test_factory_fingerprint_and_labels_after_p0_changes` — устаревший пин `28e6c619b937`, красный ещё на базе, раскрыт в w2.md «Тесты»; содержательная часть — константа == фактический отпечаток — проходит).
- NO_META/DELTA: `-k "delta_depth_instruction or meta_closing or no_meta"` → **20 passed**.
- `compileall services` → exit 0; `gen_param_registry_round1025.py --check` → CHECK OK.
- Сверка с базой: новых FAIL относительно bd8f9c34 нет (оба провала воспроизведены на базе).

## 5. Находки

Блокирующих нет.

1. **NONBLOCKING (бэклог, Builder — при следующем касании тестов)**: `test_p0_prompts_core.py::test_factory_fingerprint_and_labels_after_p0_changes` пиннит `28e6c619b937` (устарел до базы bd8f9c34, при бампе 2.58-ностальгии). Минимальный фикс: пин → `3bc0c543520c` либо динамическое сравнение с `factory_set_fingerprint()`. Повторная проверка: один тест.
2. **NONBLOCKING (бэклог, вне фичи)**: `test_mca01_tx_task_supervisor_round1027::test_write_points_go_through_single_writer` — предсуществующий провал на базе; не связан с промптами/L1/writer.

## 6. Границы вердикта

Approved обязывает к кандидату dec28b99 + докс 4a06f612. Поведенческое подтверждение (§10.1-10.7, S2, S5-DEFECT live) и связка с прод-интеграцией — волна 3 / DevOps; PA5-S12 — postdeploy. Изменение кода/доков после этого вердикта инвалидирует доказательства.
