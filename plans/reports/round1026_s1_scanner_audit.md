# Scanner-аудит — Эпик 2 / S1 `summary-filter-round1026` (Step 6, T-3153; итерация 2 — финал)

> Дата: 2026-09-23 · Базис: HEAD `01f3c57` (tag `pre-round1026-s1` → `01f3c57`), правки **НЕ закоммичены**.
> Тип: focused diff-based аудит рабочего дерева (повторный после rework-блока H + ADR-1026-2). Роль: @Scanner. Код не правился.
> Артефакты: `spec.md` (§6.1), `adr-1026-1-*.md`, `adr-1026-2-*.md`, `evidence.md`, `review.md`, `tasks.md`, `round1026_s1_ui.md`.

## Вердикт

**К деплою — ДА.** Critical 0 / High 0 / **Medium 0** / Low 1 (новый, не блокер) / Info 0.
Закрыты: **M-R1026S1-1**, **L-R1026S1-1**, **L-R1026S1-2** (rework @Builder, блок H, T-3160/T-3161)
и **B-1** @Reviewer (governance) через **ADR-1026-2** (Accepted, Step 2b @Architect).
Все инварианты (D4-гейт публикации, 2-вызовность, Δ DDL=0, Δ каталога = 467/426/442/100/98/21,
R17/R18, CSP/zero-build, гигиена) выполнены. Открыт 1 Low (L-R1026S1-3, consistency, non-blocking, owned follow-up).

## Таблица severity (итерация 2)

| ID | Sev | Статус | Суть |
|---|---|---|---|
| M-R1026S1-1 | Medium | **RESOLVED (итер.2)** | Главный тумблер теперь per-chat (`_chat_limit`); A/B независимы; OFF → прежний вход |
| L-R1026S1-1 | Low | **RESOLVED (итер.2)** | `resolve_context_tokens` нормализует потолок токенов (`0`→дефолт, `-1`→безлимит) |
| L-R1026S1-2 | Low | **RESOLVED (итер.2)** | Добавлен интеграционный регресс врезки (7 тестов) |
| B-1 (@Reviewer) | High (governance) | **RESOLVED (итер.2)** | ADR-1026-2 (AMEND ADR-1025-21 D6); ARCHITECTURE §67.6 + ADR-1026-1 AMEND |
| L-R1026S1-3 | Low | **OPEN (new, non-blocking)** | `token_limit` всегда не-`None` → `char_limit` мёртв в `_run`; возможен рассинхрон `budget.kind` с `_run` при chars-fallback |
| I-R1026S1-1/2 | Info | **CLOSED** | Санкция F8 подтверждена ADR-1026-2; meta-провенанс закроется на коммите |

## Доказательства закрытия

### M-R1026S1-1 — RESOLVED
- **Код:** `services/summary_generator.py:343-348` — гейт `bool(await _chat_limit(chat_id, "flags.summary_filter_enabled", hot.get(...)))`
  (было `hot.get(...)` без chat-скоупа), симметрично `reply_context_enabled`. Резолвинг: `chat_params.get_chat_param` → `overrides → hot.get → default`.
- **Спека:** `spec.md:161-165` (§6.1, решение Step 2b) прямо предписывает именно эту конструкцию; каталог `per_chat=True` не ослаблен.
- **Тесты:** `tests/test_summary_filter_integration.py::TestPerChatToggle`:
  - `test_chat_a_override_differs_from_chat_b` — A/C ON, B OFF → `applied == [CHAT_A, CHAT_C]`, `CHAT_B not in applied`;
  - `test_off_chat_flag_keeps_legacy_input` — OFF → `xml.build` получает **тот же объект** `rows`, `_filter_metrics == {}`.
- **Воспроизведение:** `.venv` `pytest tests/test_summary_filter.py tests/test_summary_filter_integration.py` → **38 passed**.

### L-R1026S1-1 — RESOLVED
- **Код:** `summary_generator.py:512-521` — `token_limit = resolve_context_tokens(await _chat_limit(chat_id, "limits.summary_max_context_tokens", …), _SUMMARY_CONTEXT_TOKEN_DEFAULT)`
  (константа 30000, согласована с `_run`).
- **Тесты:** `TestTokenCeilingNormalised::{test_zero_cap_falls_back_to_default,test_negative_cap_is_unlimited_ceiling}` — `0 → resolve_context_tokens(0, 30000)`, `-1 → потолок безлимита`, `fits is True` (нет вырожденной нарезки).

### L-R1026S1-2 — RESOLVED
- Новый `tests/test_summary_filter_integration.py` (7 тестов): per-chat A/B, OFF байт-в-байт, ON — XML=`kept`/RAG по исходному окну (`test_on_filters_xml_but_rag_uses_original_rows`), fail-open (`filter_window` кидает → WARNING `FILTER_ERROR`, окно нефильтрованное, Саммари доставляет), ровно 2 LLM-вызова при ON (`llm.generate.await_count == 2`), sentinel-потолок.

### B-1 — RESOLVED (ADR-1026-2)
- `adr-1026-2-frozen-artifacts-reissue-amend.md` — **Accepted** (Step 2b @Architect): санкция переиздания frozen-артефактов F8 при **санкционированном** Δ каталога; процедура = repin sha256 + regenerate + recount/дельта + обновление фикстур/ассертов (обновление, не отключение).
- `plans/ARCHITECTURE.md §67.6` и AMEND-секция `adr-1026-1` синхронизированы; ADR-1025-21 D1–D5/D7 не меняются, меняется только D6.

## Новый Low (non-blocking)

### L-R1026S1-3 [Low, OPEN] — `char_limit` мёртв; возможен рассинхрон `budget.kind`
- **Локация:** `services/summary_generator.py:516-525` → `services/summary_filter.py:240-249`.
- **Факт:** после нормализации `token_limit` всегда не-`None` (`resolve_context_tokens` гарантирует `≥1`), поэтому `estimate_and_split` всегда идёт по tokens-ветке; `char_limit` в `_run` не используется. Если env-конфиг задаёт chars-fallback (`SUMMARY_MAX_CONTEXT_CHARS` задан, `SUMMARY_MAX_CONTEXT_TOKENS` не задан → `_run` выбирает `kind="chars"` через `resolve_chat_limit`), `budget.kind` фильтра будет `tokens` — рассинхрон.
- **Impact:** только информационный `budget` (логи S1/S8); S1 на него не действует, S3 ещё не реализован → не блокер.
- **Fix:** использовать `resolve_chat_limit` (единый kind + значение) либо убрать неиспользуемый `char_limit`.

## Инварианты (проверено, итер.2)

| Инвариант | Результат | Доказательство |
|---|---|---|
| D4-гейт: публикация не тронута | ✅ | diff `image_generation.py`/`telegram_send.py`/`web/api/routes.py` пуст; среди удалённых строк `summary_generator.py` нет `_deliver_*`/`generate_image`/`build_cover_media`/`send_rich_message`/`send_text` |
| Промпты/XML не тронуты | ✅ | diff `summary_prompts.py`/`summary_xml.py` пуст |
| Ровно 2 LLM-вызова | ✅ | тест `test_on_exactly_two_llm_calls` (`await_count == 2`); `_generate_two_call` не изменён |
| Δ DDL = 0 | ✅ | diff `database.py`/`pg_db.py`/`summary_memory.py` пуст |
| Δ каталога = санкция | ✅ | импорт: REGISTRY **467**, Settings **426**, GROUPS **100**, `_TAB_BY_GROUP` **98**, TAB_RULES **21**; categorized 442 |
| `APP_VERSION` 2.58.18 | ✅ | `config/settings.py`; README `v2.58.18`; JS-тесты; `test_app_version_matches_readme` зелёный |
| Маркер-тесты не ослаблены | ✅ | `git diff -U0 tests/` — только count/version-бампы; удалённых/ослабленных assert и skip/xfail нет |
| R17 (логи) | ✅ | `FILTER_*` — только `run_id/chat_id`/счётчики/`status/duration_ms` |
| R18 (тег/бэкапы/stash) | ✅ | tag `pre-round1026-s1`; `var/backups/s1-round1026-20260923-101108/`; `stash@{0}` цел |
| CSP/zero-build, no-new-libs | ✅ | `summary_filter.py` — stdlib + `token_counter`; в render нет `v-html/innerHTML/eval` |
| Гигиена | ✅ | `git diff --check`=0; в индексе нет `.env`/`current_task.md`/zip/`tools/_ui_*`/`var/backups` |
| F0/F4/F5/F6/F7/F9/F11 | ✅ | полный pytest зелёный |

## Суперсессия round1025 F8 — суждение (итер.2)

**Санкционированная.** ADR-1026-2 (Accepted) явно AMEND-ит ADR-1025-21 D6 и разрешает переиздание при санкционированном Δ каталога.
Байтфризы/строгие пины не ослаблены: `sha256(param_catalog.py)` = `aed3114d…1ccc` == значение в `f8_baseline.json`;
`ROUTES_SHA256_F11` (`web/api/routes.py`) и `pg_db.py` не тронуты; `app_version` фикстуры исторический `2.58.15` (текущая пинится строго);
counts 467/100/98/21, `delta=56`; «459» в генераторе заменены на динамику; фикстуры/ассерты обновлены (не отключены).

## Изменённые файлы (аудит-скоуп, итер.2)

- **Рантайм:** `services/summary_filter.py` (новый), `services/summary_generator.py` (+per-chat гейт, `resolve_context_tokens`, `_apply_filter`),
  `config/settings.py`, `services/param_catalog.py` (+8/+2), `web/app.js`, `web/index.html`.
- **Тесты:** `tests/test_summary_filter.py` (31), **`tests/test_summary_filter_integration.py` (новый, 7)**, 39 файлов count/version-бамп, `tests/fixtures/round1025/*.json`, `tests/js/*`.
- **Доки/артефакты:** `plans/docs/param-registry-round1025.{tsv,meta.md}`, `plans/docs/screen-map-round1025.md`, `tools/gen_param_registry_round1025.py`,
  `plans/ARCHITECTURE.md` (§67.6), `plans/features/summary-filter-round1026/**` (adr-1026-1/1026-2, spec, review, evidence, tasks).

## Прогоны @Scanner (итер.2, воспроизведено)

- `.venv\Scripts\python.exe -m pytest -q` → **8501 passed / 0 failed** (107.37 s)
- `py -3 -m pytest -q` → **8495 passed / 5 failed / 1 skipped** (5 pre-existing env: `outgoing_guard_round1022` ×2 + `summary_cover_round1023` ×3, `ImportError` aiogram rich)
- фильтр-блок (`test_summary_filter.py` + `test_summary_filter_integration.py`) → **38 passed**
- `node --check web/app.js` OK; `node tests/js/*.js` → **42/42**
- импорт каталога 467/426/442/100/98/21; `sha256(param_catalog.py)` совпал с фикстурой; `git diff --check` = 0

## Handoff

**RESULT: SCANNED @Orchestrator** — Critical 0 / High 0 / Medium 0 / Low 1 (L-R1026S1-3, non-blocking) / Info 0.
M-R1026S1-1, L-R1026S1-1, L-R1026S1-2 и B-1 закрыты (rework @Builder + ADR-1026-2). D4-гейт, 2-вызовность,
Δ DDL=0, Δ каталога = 467/426/442/100/98/21, R17/R18, CSP/zero-build, гигиена — ✅. К деплою **ДА**.
