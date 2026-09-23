# Review — S5 `summary-l2-writer-formatter-round1026` (Step 5 @Reviewer, T-3337, итерация 2)

- **Feature-ID:** `summary-l2-writer-formatter-round1026`
- **Status:** **Approved** (C0 / H0 / блокирующих Medium 0). ON-путь в проде — GATED (флаг default OFF); live-приёмка Эпика 1 — PENDING OWNER VERIFICATION.
- **Дата:** 23.09.2026. Автор: @Reviewer (Step 5, re-review после rework T-3339). Код/тесты не правились.

## Git base и объём проверенного изменения

- **База:** HEAD `e3ea608` (closing-docs S4) == annotated-тег `pre-round1026-s5` (`git rev-parse pre-round1026-s5^{commit}` = `e3ea608e19ea3241569ef640fa296179de10e5e0`). Номинальный baseline `7722d66`; `APP_VERSION` 2.58.23 → **2.58.24**. Правки **не закоммичены** (59 M + 6 ??; `git diff HEAD`). Итерация 2 = то же дерево + закрытие findings B/S/L-R1026S5-*.
- **Re-review scope:** `services/summary_generator.py` (порядок ON/S1/S2, `focus`), `services/summary_l2_writer.py` (`_QUOTE_RE`/`_strip_quotes`), `services/summary_article_formatter.py` (`_split_safe`), `tests/fixtures/round1025/catalog_baseline.json`, новые тесты `TestOnPathAppliesS1S2` / `TestOffPathDirect` / `TestCanon::test_canon_doc_byte_identical` / `test_single_quoted_*` / `test_corner_quoted_*` / `test_chunk_does_not_split_html_entity`.
- **Вне diff (подтверждено `git status`):** `web/**`, `summary_xml.py`, `summary_filter.py`, `summary_context_restore.py`, `image_generation.py`, `pg_db.py`, `database.py`, `plans/current_task.md`.

## Выполненные проверки (воспроизведено лично, итерация 2)

| Проверка | Метод | Результат |
|---|---|---|
| Полный pytest | `.venv\Scripts\python.exe -m pytest -q` | **8807 passed, 0 failed** (108.7 s; S4-baseline 8737 + 64 + 6 rework) ✔ |
| JS | `tests/test_webapp_js_unit.py`; файлов `tests/js/*.js` | **30 passed / 0**; **43** файла ✔ |
| F8/IA/JS набор | 3 файла вместе | **66 passed** ✔ |
| Новые L2-тесты | `tests/test_summary_l2_integration|l2_writer|article_formatter` | **70 passed** (было 64 → +6) ✔ |
| `git diff --check` | git | exit **0** (только CRLF-warnings) ✔ |
| Каталог импортом | `import services.param_catalog` | **469 / 426 / 444** (`category is not None`) **/ 100 / 98 / 21** ✔ |
| F8 `--check` | `tools/gen_param_registry_round1025.py --check` | **CHECK OK** (реестр 469 == REGISTRY; exit 0) ✔ |
| Δ DDL | `pg_db.py`/`database.py` ∉ diff | **0** ✔ |
| Версия | `settings.APP_VERSION` | **2.58.24** ✔ |
| R18 | тег/`stash@{0}` | `pre-round1026-s5` → `e3ea608`; `stash@{0}` цел ✔ |

## Покрытие требований / evidence (итерация 2)

- **B-R1026S5-1 (фикстура F8) — закрыт.** Файл восстановлен из blob `e3ea608`; `git diff HEAD --numstat` = **3 insertions / 2 deletions**. Независимый разбор: UTF-8 **без BOM** (было и стало), отступ **1** (исходный), **0** символов mojibake (диапазоны U+2550–256C/U+2591–2593) и 0 любых U+2500–257F (в базе тоже 0). JSON-дифф к `e3ea608`: изменены ровно `_provenance.note` (дописан S5-абзац), `counts.REGISTRY 468→469`, **+1** ключ `prompts.summary_l2_writer_system_prompt`; секции `group_ids`/`group_tab`/`nav_order`/`nav_titles`/`tab_nav` — **семантически идентичны** базе. `test_round1025_f8_registry.py` + `test_ia_inventory_round1025.py` зелёные; F8 `--check` зелёный.
- **S-R1026S5-1 (архитектурный drift ADR-1026-7 D5 / §80) — закрыт.** В `_run` ON-guard перенесён **после** S1/S2: `rows → (`flags.summary_filter_enabled` → `_apply_filter` = S1 `filter_window` + S2 `restore_context`) → `xml_rows` → `_hybrid_l2_enabled` → `_run_hybrid_l2(chat_id, xml_rows, focus, correlation_id)`. `build_l1_payload` и `run_l1` получают отфильтрованный/восстановленный вход (не сырое окно); `trigger_message_id` учтён S1-фильтром; `focus` прокинут в L1 через `focus_block=_apply_focus("", focus)` (`run_l1` префиксит его к `user_content` — как legacy). Доказано нетривиальным `TestOnPathAppliesS1S2` (спай `filter_window`/`restore_context`: `restore` вызван, `trigger_message_id==555` доехал, L1 получил `filtered_rows`, а не `raw_rows`, focus-блок на месте).
- **ON = ровно 2 вызова.** `TestOnPath` подтверждает L1(1) + L2(1); при L1-`invalid`/пакет не deliverable L2 не вызывается; при L2-ошибке `llm.generate.await_count==1`, публикации нет, legacy-фолбэка/3-го вызова нет.
- **OFF-путь — байт-в-байт.** Diff `_run`: hunk `@@ -370,6 +370,14 @@` — **только вставка 8 строк** (ON-guard + комментарий) перед `xml_context = self.xml.build(...)`; в теле OFF-ветки **ни одной изменённой/удалённой строки**. Новый `TestOffPathDirect` напрямую гоняет `_run` в OFF и сверяет доставленный текст (legacy `_generate_two_call` + postfix).
- **L-R1026S5-1 — закрыт:** в `_deliver_l2_plain` импортируются только `chunk_plain_blocks` и `format_plain_text` (мёртвый `format_plain_html` удалён).
- **S-R1026S5-3 — закрыт:** `TestCanon::test_canon_doc_byte_identical` извлекает `SUMMARY_L2_WRITER_SYSTEM_PROMPT` из `plans/docs/canon/architecture.md` и сравнивает с кодом байт-в-байт (по образцу L1).
- **S-R1026S5-2 — закрыт:** `_QUOTE_RE` расширен (`'…'`, `‚…‘`, `「…」`, `『…』`), `_strip_quotes` знает эти пары; тесты `test_single_quoted_*`/`test_corner_quoted_*` зелёные.
- **S-R1026S5-4 — закрыт:** `_split_safe` при вынужденной нарезке не рвёт HTML-сущность (сдвигает границу к началу `&…;`); `test_chunk_does_not_split_html_entity` зелёный. В проде ветка по-прежнему недостижима (абзац ≤900 < 4096).
- **L-R1026S5-2 — закрыт** (см. `TestOffPathDirect`). **L-R1026S5-4 — обоснованно перенесён в S6:** §106-коды `SUMMARY_GENERATION_FAILED`/`COVER_GENERATION_FAILED`/`RICH_MESSAGE_SEND_FAILED`/`TEXT_FALLBACK_FAILED` в S5 не реализуются; пометка внесена в `tasks.md` (T-3325/T-3339) и `evidence.md`. ON gated (default OFF) → не блокер.

## Focused-audit coverage

- Аудит изменения: ordering ON/S1/S2 (integration edge `summary_generator`↔`summary_filter`↔`summary_context_restore`↔`summary_l1_clusterizer`), анти-цитатный валидатор, форматтер (границы чанков/экранирование), frozen-фикстуры F8. Security: инъекции/экранирование — подтверждено ранее (as-is). R17-логи — без секретов/текстов. §104/обложка/XML/`web/**` — вне diff.

## Блокирующие findings

Нет. Critical 0, High 0, блокирующих Medium 0.

## Non-blocking debt

- **[L-R1026S5-3] Low (без изменений):** `_run` делает один доп. `get_chat_param("flags.summary_hybrid_l2_enabled")` до OFF-ветки (fail-safe → False). Поведение пользователя идентично; «строго байт-в-байт» верно по телам кода.
- **[L-R1026S5-4] Low (S6, закреплено):** §106-классы ошибок — владелец S6 (пометка в `tasks.md`/`evidence.md`).
- **[L-R1026S5-5] Low (без изменений):** rich-путь зовёт `_maybe_sanitize` после `html.escape` (инверсия порядка spec §5.2; функционально безопасно).
- **[L-R1026S5-6] Low (новый, побочный от S-R1026S5-2):** шаблон `'[^']*'` может «склеить» апострофы в англ. сокращениях (`don't, it's` → `dont, its`) как непроверенную «цитату». Текст продукта русскоязычный, ON gated, промпт цитаты запрещает → не блокер; при желании — исключить `'` при латинских сокращениях в S6.

## Unavailable / PENDING

- **ON-путь L2 в проде — GATED:** `SUMMARY_HYBRID_L2_ENABLED` default False + гейт S6/S10 + ADR-1025-24 D4; проверен только на моках.
- **Live-приёмка Эпика 1** — PENDING OWNER VERIFICATION (вне S5).
- **F8 config-diff артефакт** (`plans/reports/round1025_f8_config_diff.md`, baseline 2.58.15) не переиздавался — вне дельты (pinned-тесты зелёные).

## Итог

Оба ревью-контура (требования/корректность + focused change audit) независимо поддерживают **Approved**. Оба блокирующих дефекта итерации 1 ([B-R1026S5-1], [S-R1026S5-1]) и все Low-фиксы подтверждены фактическим кодом и повторными прогонами; тесты не ослаблены (только добавлены/усилены). Новых Critical/High/блокирующих Medium нет.

**Handoff:** @Orchestrator — **APPROVED** (к merge/деплою OFF-безопасного состояния); ON в прод включать только после live-приёмки Эпика 1 (гейт S6/S10+D4).
