# Scanner audit — S5 `summary-l2-writer-formatter-round1026` (Step 6, T-3338) — **итерация 2 (re-audit после rework T-3339)**

- **Feature-ID:** `summary-l2-writer-formatter-round1026` (Эпик 2 / S5). **Дата:** 23.09.2026. Автор: @Scanner (Step 6). Код/тесты не правились.
- **База:** HEAD `e3ea608` (closing-docs S4) == annotated-тег `pre-round1026-s5` (`git for-each-ref`: tag `a6be444` → `e3ea608e19ea…`). `APP_VERSION` 2.58.24. Правки **НЕ закоммичены** (59 M + 6 ??; `git status` 70 строк).
- **Итерация 1:** `plans/reports/round1026_s5_scanner_audit.md` (v1: `SCANNED — НЕ к деплою`, B-R1026S5-1 + S-R1026S5-1). Итерация 2 проверяет закрытие находок и отсутствие регрессий.

## Вердикт

**SCANNED — к деплою ДА по коду (OFF-безопасное состояние; ON — GATED, default OFF).** Critical 0 / High 0 / блокирующих Medium 0. Оба прежних блокера (B-R1026S5-1, S-R1026S5-1) **подтверждены закрытыми независимо**. Новых Critical/High нет; новых Low-регрессий нет — единственный побочный эффект Low-фикса (`'[^']*'`) **совпал** с уже заведённым @Reviewer `L-R1026S5-6` (подтверждён моей пробой). ON в проде не активен (default OFF), live-приёмка Эпика 1 — PENDING OWNER VERIFICATION.

| Severity | Кол-во | ID |
|---|---|---|
| Critical | 0 | — |
| High | 0 | — |
| Medium (блокирующий) | 0 | — |
| Low (non-blocking) | 4 | L-R1026S5-3/-4/-5/-6 (все pre-existing/known) |
| Info | 2 | S-R1026S5-5 (env), **S-R1026S5-7 (ON-gated S6-note)** |

## Статус прежних ID (независимая проверка @Scanner, итерация 2)

| ID | Severity | Статус | Доказательство @Scanner |
|---|---|---|---|
| B-R1026S5-1 | Medium (data-integrity, BLOCKING) | **RESOLVED** | см. ниже |
| S-R1026S5-1 | Medium (ON-drift) | **RESOLVED** | см. ниже |
| S-R1026S5-2 | Low | **RESOLVED** | `_QUOTE_RE` ловит `'…'`/`‚…‘`/`「…」`/`『…』`; проба `Он 'придумал такое' на ходу.` → `ok`, кавычки сняты |
| S-R1026S5-3 | Low | **RESOLVED** | `TestCanon::test_canon_doc_byte_identical` присутствует и зелёный (7/7 `-k canon`) |
| S-R1026S5-4 | Low | **RESOLVED** | `_split_safe`; проба limit=20 с `&`/сущностями — 0 «висячих `&`», все осколки ≤ limit |
| S-R1026S5-6 | Info | **RESOLVED** | `git diff HEAD --numstat` = `3 2`; 0 mojibake; отступ 1; LF/CRLF-нормализация |
| S-R1026S5-5 | Info (env) | OPEN (non-blocking) | pytest зелёный только на `.venv` (aiogram 3.31.0) |
| L-R1026S5-1 | Low | **RESOLVED** | `format_plain_html` не импортируется в `summary_generator` (grep: только formatter + тест) |
| L-R1026S5-2 | Low | **RESOLVED** | `TestOffPathDirect::test_run_off_uses_legacy_two_call_and_delivers_etalon` |
| L-R1026S5-3 | Low | OPEN (non-blocking) | `_run` делает +1 `_chat_limit` до OFF-ветки (fail-safe → False) |
| L-R1026S5-4 | Low | OPEN → **S6** | §106-классы не реализованы; закреплено за S6 |
| L-R1026S5-5 | Low | OPEN (non-blocking) | sanitize после escape (функционально безопасно) |
| L-R1026S5-6 | Low | OPEN (non-blocking) | **подтверждён** независимо (проба ниже) |

## B-R1026S5-1 — независимо подтверждён закрытым

- **Файл:** `tests/fixtures/round1025/catalog_baseline.json` (21926 B). **Без BOM** (первые байты `7B 0D 0A` = `{`+CRLF). **Mojibake = 0**: U+2550–256C — 0, U+2591–2593 — 0, байтовая последовательность `E2 95 A8` (`╨М`) — 0. Уникальные не-ASCII файла: только кириллица + `Δ` (U+0394) + `→` (U+2192).
- **`nav_titles` байт-точно корректны:** `modules` = U+041C 043E 0434 0443 043B 0438 = «Модули» (UTF-8 `d09cd0bed0b4d183d0bbd0b8`), `ai` = «ИИ», `memory` = «Память». Двойной перекодировки нет.
- **JSON-дифф к `e3ea608` — ровно санкционированный:** `git diff --numstat` = **3 вставки / 2 удаления**; изменены только `_provenance.note` (добавлен S5-абзац ADR-1026-7 D3), `counts.REGISTRY 468→469`, добавлен ключ `prompts.summary_l2_writer_system_prompt`. `Compare-Object` построчно — те же 3/2. `registry_keys` 468→469 (diff — только L2-промпт).
- **Консистентность:** отступ 1 (как в `e3ea608`); LF↔CRLF нормализуется git (`core.autocrlf=true`, `git diff` показывает 5 строк, не весь файл). `test_round1025_f8_registry.py`/`test_ia_inventory_round1025.py` + F8 `--check` — зелёные.

## S-R1026S5-1 — независимо подтверждён закрытым

- **Порядок (`services/summary_generator.py`):** `rows → xml_rows=rows → [flags.summary_filter_enabled] _apply_filter(S1 filter_window + S2 restore_context) → xml_rows → if _hybrid_l2_enabled: _run_hybrid_l2(chat_id, xml_rows, focus, correlation_id) → return` (стр. 364–380). ON-guard **после** S1/S2, `xml_context`/RAG/memorize ниже не выполняются.
- **Нет обхода фильтра/восстановления:** `_run_hybrid_l2` получает `xml_rows` (пост-S1/S2) и передаёт его в `run_l1(rows=…)` и `build_l1_payload(rows, …)`. `TestOnPathAppliesS1S2` (спай `filter_window`/`restore_context`) — `restore` вызван, `trigger_message_id==555` дошёл до S1, L1 получил `filtered_rows` (не `raw_rows`).
- **`focus`/`trigger_message_id` используются:** `trigger_message_id` → S1 (`_apply_filter(..., trigger_message_id)`); `focus` → `_apply_focus("", focus)` → `focus_block` в `run_l1`, который префиксит его к `user_content` (`summary_l1_clusterizer.py:538-541`) — как legacy. `SUMMARY_FILTER_ENABLED` default **True** → S1/S2 реально исполняются при ON.
- **ON = ровно 2 вызова:** `run_l1` — один `await call(messages)` (`:548`); `run_l2` — один `await call(messages)` (`:757`); оба `call = llm_call or _make_llm_call(...)`. 3-й вызов/legacy-фолбэк невозможен (`_run_hybrid_l2` при `not usable` → return без публикации). `_deliver_l2_rich` использует `generate_image` (картинка) + `sendRichMessage` — не LLM-токены.
- **OFF-путь байт-в-байт:** diff `_run` — только вставленный ON-guard (стр. 373–380); тело OFF (`xml_context → … → _generate_two_call`) не изменено. Ленивые импорты L2-модулей только внутри `_run_hybrid_l2`/`_deliver_*`.

## Новые находки

**Critical/High — нет. Новых блокирующих Medium — нет.**

### [S-R1026S5-7] Info — ON-ветка пропускает `memorize_facts(chat_history)` (ON-gated, S6-note)

- **Где:** `services/summary_generator.py:378-380` (ON-return) vs `:405-409` (OFF `fire_and_forget(memory.memorize_facts(..., "chat_history"))`).
- **Доказательство:** ON-return стоит до `:405`; `grep memorize_facts` — в summary-пути единственный вызов `:407`. ON также пропускает `search_long_term`/`vector_search`/`get_graph_facts`/`get_rag_context` (это ок — они питают legacy-prompt), но `memorize_facts` — независимый side-effect.
- **Оценка:** соответствует принятому ADR-1026-7 D5/spec §7.1 (`rows → §92-payload → run_l1 → package → run_l2 → formatter`, памяти в ON нет) → **не дефект кода**, а spec-вопрос S6: при активации ON память перестанет получать `chat_history`-факты саммари. Прод не затронут (ON default OFF). **Fix (S6):** решить — вызывать `memorize_facts` и в ON, либо зафиксировать изменение в ADR.

### [L-R1026S5-6] Low — подтверждён независимо (без дублирования)

- **Проба @Scanner:** `_QUOTE_RE` с `'[^']*'` снимает апострофы в естественном тексте: `It's John's book.` → `Its Johns book.`; `Don't worry, it's fine.` → `Dont worry, its fine.`; `l'été n'est pas là` → `lété nest pas là`; `rock'n'roll` → `rocknroll`. Удаляются только символы кавычек (содержимое между ними сохраняется) → порча косметическая, не потеря данных. Продукт русскоязычный, ON gated → **не блокер**. **Fix (owner):** уточнить regex (напр. `(?<!\w)'[^']*'(?!\w)`).
- **Побочный от S-R1026S5-2.** Основная цель фикса достигнута: `Он 'придумал такое' на ходу.` → кавычки сняты (`ok`).

### Проба нарезки (S-R1026S5-4) — регрессий нет

- `chunk_plain_blocks(doc, limit=20)` на длинном блоке с `&lt;`/`&amp;` → 13 осколков, **0 висячих `&`**, все ≤ limit. `_split_safe` сохраняет конкатенацию (`"".join(pieces)==text`) на всех пробах; в проде сущности ≤8 символов → осколок ≤4096. Остаточный теоретический edge (`&` без `;` длиной > limit в начале блока) в проде недостижим (вход уже `html.escape` → каждый `&` = `&amp;`).

## Инварианты (независимо воспроизведено @Scanner, итерация 2)

| Инвариант | Метод | Результат |
|---|---|---|
| Полный pytest | `.venv\Scripts\python.exe -m pytest -q` | **8807 passed, 0 failed** (112.4 s) ✔ |
| JS | `tests/test_webapp_js_unit.py`; `node --check tests/js/*.js` | **30 passed**; **43/43** ✔ |
| Новые/целевые тесты | pytest подмножество L1/L2/F8/IA | **222 passed** ✔ |
| Каталог импортом | `services.param_catalog` | **469 / 426 / 444 / 100 / 98 / 21** ✔ (Δ=+1) |
| F8 `--check` | `tools/gen_param_registry_round1025.py --check` | `CHECK OK` (exit 0) ✔ |
| sha256 repin | `f8_baseline.json` | `param_catalog.py`=`8928c1d1…e0e` ✔; `pg_db.py` ✔; `routes.py`=`4b652cb1…` == `ROUTES_SHA256_F11` ✔ (fixture-хэш `33fb6b1c…` исторический, by design L-F9S-4) |
| Δ DDL | `pg_db.py`/`database.py` ∉ `git status` | **0** ✔ |
| `pg_db.py`/`routes.py` не тронуты | `git status`/`git diff` | вне diff ✔ |
| `APP_VERSION` | `settings` == README | **2.58.24** ✔ |
| `git diff --check` | git | exit 0 (только CRLF-warnings) ✔ |
| R18 | тег/stash/backup | `pre-round1026-s5` (annotated → `e3ea608`); `stash@{0}`; `.env.bak.round1026-s5` ✔ |
| R17 | `TestLogs`/`test_no_raw_content_in_logs` | коды/host/модель/токены; без секретов/текстов ✔ |

## Handoff

**RESULT: SCANNED — к деплою ДА по коду (OFF-безопасное состояние; ON — GATED, default OFF; C0/H0; блокирующих Medium 0) @Orchestrator.** B-R1026S5-1 и S-R1026S5-1 закрыты (подтверждено независимо). Low/Info — owned follow-up: L-R1026S5-3/-5/-6, S-R1026S5-5 (env) — не блокируют; L-R1026S5-4 (§106) — S6; S-R1026S5-7 — S6-note. Live-приёмка Эпика 1 — PENDING OWNER VERIFICATION.
