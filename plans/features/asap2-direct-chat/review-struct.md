# Structural review — asap2-direct-chat (кандидат `5ad73933`)

Дата: 23.10.2026 04:05 +12:00. Лейн: `REV-ASAP2-STRUCT` (read-only).
Кандидат: `5ad73933` (код и тесты; HEAD `f7156fee` содержит только docs, diff `services/`/`tests/` после кандидата пуст).
Карта: `requirements-map.json` (source sha256 `8f600767e06877ac…` совпадает с `source-2026-10-22.md`), `slice-graph.json`, `reconciliation.md`.
Семантические прогоны реальной модели — параллельный лейн `ASAP2-PROBE`; здесь их нет и они не подменяются.

## Вердикт

**Needs Fixes.** Структурная часть в основном корректна (каноны, strict boolean, снятие speech-императива, лестницы/rollback/фингерпринт), но есть один остаточный второй сигнал уточнения для L2 и непокрытые обязательные строки матрицы §6.4/§6.3; формальный review-гейт карты не может быть пройден (все 109 required-строк PENDING, `candidate_commit` пуст).

## Что проверено и подтверждено

- `services/chat_prompts.py`: блок §4.1 и абзацы §4.2 совпадают с source байт-в-байт (L1 1930/1930, L2 843/843 символов). L1-диff против W1: только вставка контракта + замена правила 5; L2-диff: только вставка абзацев в «КАК ПИСАТЬ». Секция «ВЫБОР УЧАСТИЯ» ровно одна, схема `needs_clarification` ровно одна, старого императива «Ничего кроме вопроса» в активном каноне нет.
- `services/direct_l1.py:341`: `data.get("needs_clarification") is True` — строка/`null`/список/объект/`0`/`1` → False; `true` → True. `build_l2_plan_block` при пустом target не выдаёт директиву; при непустом — узкую фразу §4.3 (плюс отдельная строка с target; см. Incidental).
- `services/claim_envelope.py`, `services/direct_chat_service.py`: `clarify_action` больше не возвращает `CLARIFY_ASK`, `render_speech_block` не рендерит «задай … вопрос», `_l1_speech_hints` не подаёт `clarify=ask`; `assume` и прочие сигналы сохранены.
- `services/prompt_registry.py` / `prompt_migrations.py`: `FACTORY_SET_SHA256_12 == factory_set_fingerprint() == 24ae494ac422`; сравнение с родителем (`e64ecf5e`, worktree) по всем 89 factory-текстам: changed = 2 (`direct.base.l1_planner`, `direct.base.l2_writer`). `PREV_DIRECT_L1_PLANNER_W1` sha16 `f8ab20121c02`, `PREV_CHAT_VERBALIZER_W1_31` sha12 `be03964322aa`, `PREV_DIRECT_L1_PLANNER_L1D` sha12 `ace6246bd360`; ступени ведут на новый канон, rollback — на W1; точное совпадение байт, кастомы не перетираются (миграция exact-match).
- Diff-скан: 0 секретов/токенов; новых классов, таблиц, regex-ов по формулировкам, квот/счётчиков/порогов нет; `GOV-*` guardrails не нарушены.
- Тесты (venv py3.12): целевой набор 9 файлов — **215 passed** на повторном прогоне; первый прогон дал 1 transient fail `test_asap8_initreply_binding.py::test_case7c_addressee_mismatch_no_rebinding`, standalone и на повторах — pass (не связан с diff; вероятная гонка async/DB). Дополнительно `test_asap7_direct_settings.py`: 2 pre-existing fail (`user_version` 35 vs 37), воспроизводятся на родителе — не регрессия кандидата.

## Блокеры

1. **BLOCKER — остаточный второй сигнал `response_act=clarification` для L2.** `services/direct_l1.py:890-892`: при `needs_clarification=false` (и при пустом target) в `<Response_Plan>` всё равно уходит `смысловой акт ответа: clarification`. Это второй model-facing сигнал уточнения; L2 может задать вопрос вопреки §3.2/T31. Тест `tests/test_asap2_clar_contract.py:93-104` проверяет только русское «уточняющ» и не ловит английский enum. Минимальный фикс: не выводить эту строку, когда `act == "clarification"` и (`clarification` false или target пуст), и добавить assert `"clarification" not in block` для этого сочетания.
2. **BLOCKER — T33 не покрыт.** `tests/test_asap2_clar_contract.py:140-155` заявлен как «Composer/L1 ON-OFF … any path», но проверяет только fallback, speech-блок и два канона; нет Composer ON/OFF и L1 ON payload. §6.4/T33 требует именно эти два режима. Минимальный фикс: тест на итоговые `messages` L1/L2 при Composer ON/OFF (по образцу `test_asap_w1_semantics.py:447`), assert отсутствия `clarify=ask`/«задай».
3. **BLOCKER — T34 не покрыт как заявлено.** `tests/test_asap2_clar_contract.py:160-185` проверяет factory-текст и лестницу, но не `migrate_prompt_canons`/`rollback_prompt_canons` для новых L1/L2-ступеней, не hot resolve и не owner custom для L1. §6.4/T34 и §5 требуют effective global/per-chat/hot + сохранность кастома. Минимальный фикс: переиспользовать `FakeCache`-тесты `test_prompt_migrations.py` для W1→new, rollback→W1, custom untouched, hot resolve; per-chat путь зафиксировать как N/A с причиной, если per-chat prompt override для этих ключей не существует.
4. **BLOCKER — T19–T24/CLAR-CTX-THREE не покрыт.** `tests/test_asap2_clar_contract.py:237-250` — только unit `build_l1_context`; нет service-level второго хода, restart/повторной загрузки истории, ограничения окна/branch/fallback. Это прямое acceptance CLAR-CTX-THREE и §8.1 D1. Минимальный фикс: интеграционный тест двух `handle` (второй — с новым экземпляром service/DB), assert в L1 payload исходной просьбы, вопроса бота и ответа человека; семантика T19–T23 остаётся probe-лейну.
5. **BLOCKER (формальный гейт) — карта не привязана к кандидату.** `requirements-map.json`: `candidate_commit` пуст, все 109 required-строк `PENDING`; `requirements_gate.py check --stage review --slice CLAR-BOOL --candidate 5ad73933 --repo .` → EXIT 1 (`candidate mismatch` + 6 mandatory not VERIFIED). Ни один слайс нельзя формально Approve. Минимальный фикс: PM/Builder после probe выставить `candidate_commit=5ad73933`, заполнить evidence для структурно доказанных строк, остальные оставить `PENDING`/`READY_FOR_LIVE` с конкретным evidence; не помечать probe/live VERIFIED без прогонов.
6. **BLOCKER (артефакт §7) — `GOV-ARCH-AUDIT` не подтверждён.** В `plans/features/asap2-direct-chat/` нет `arch-audit.md`; `slice-graph.json:11` требует аудит actual effective L1/L2 и четырёх мест до Builder. `reconciliation.md` декларирует `ARCH_REUSE_CONFIRMED`, но фактический effective-снимок (хеши, без приватных данных) отсутствует. Минимальный фикс: добавить audit-артефакт или явно закрыть строку с обоснованием, если PM считает W1-аудит достаточным; без этого `GOV-ARCH-AUDIT` не VERIFIED.

## Строки карты, которые нельзя VERIFIED без probe/live

- **Семантика реальной модели:** CLAR-L1-DIST1…DIST5; CLAR-PLAN-ONETARGET (#13–#17); CLAR-L2-ROLE/CANON (семантическая часть); T01–T26; TESTS-METHOD-REAL/PARAPHRASE/SCREENSHOT; DONE-D6/D8; DONE-D1 (в части «не теряет исходную просьбу» — после B4).
- **Production/effective PG и deploy:** MIGR-INSPECT/EFFECTIVE/PAYLOAD/BOTHSIDES/DEVOPS; DONE-D4; DONE-D9 (deploy/rollback/health); T34 (per-chat/hot часть — после B3).
- **Пока PENDING по книгоучёту:** все 109 required-строк; после B1–B6 структурно доказанные GOV/CLAR-BOOL/CLAR-L1/CLAR-SPEECH/CLAR-L2/CLAR-PLAN/MIGR (кроме effective/PG) и T27–T36 (кроме T33/T34) могут быть привязаны к тестам кандидата.
- `evidence/probe/` в дереве отсутствует — ожидается от параллельного лейна; здесь не имитируется.

## Incidental (не блокеры)

- `services/direct_l1.py:935`: дополнительная model-facing строка `недостающий обязательный предмет: <target>` не входит в дословный §4.3; это минимальная необходимая передача цели, но её надо зафиксировать в evidence как осознанную адаптацию (иначе L2 не знает предмет).
- `services/direct_chat_service.py:2779-2781`: мёртвая telemetry-ветка `clarify == CLARIFY_ASK`; функционально безвредна, кандидат на очистку в следующем проходе.
- `CLARIFY_ASK` остаётся в `CLARIFY_ACTIONS`/`clarify_action` signature (`is_group` не используется); совместимость, не новый класс.
- `tests/test_asap2_clar_contract.py:140` название «any_path» завышает фактическое покрытие (см. B2).
- Pre-existing stale `tests/test_asap7_direct_settings.py` (user_version 35 vs 37) — вне скоупа asap2, не регрессия.

## Проверки/источники

- Source: `plans/features/asap2-direct-chat/source-2026-10-22.md` (324 строки), map, reconciliation, slice graph.
- Код/диff: `git show 5ad73933`, сравнение канонов и 89 factory-текстов с worktree `e64ecf5e`.
- Гейты: plan EXIT 0; review EXIT 1 (см. B5).
- Внешние источники не требуются: решение не зависит от версионных внешних контрактов.
