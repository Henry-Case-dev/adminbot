# SXR-C3-02 / SXR-C2-01 — context/payload caps (Direct + фактчек)

- **Эпик:** SMART-EXECUTION-RELIABILITY-01, срез **S3-EVIDENCE**, корректирующий
  срез **C2-01 / C3-02** (context/payload family).
- **Кандидат кода:** `eab6aefdaa1dec9327e972c1b622c0205991b4ef` (branch
  `smart/caps-context`, base `aca1370250a7579cd3cc969679852cf2b1d2608b`).
- **Коммиты:** `98d1e810` (фактчек-контекст), `75ea8ff2` (Current_Question/L1),
  `33d656f4` (evidence pack/40%/4000), `07daae48` (protected reserve + boundary
  tests), `529d56cc` (tool-loop output), `db6896f4` (L2 digest/claim), `eab6aefd`
  (fallback repack), `0cb65988` (`.gitattributes`, chore).
- **Соседний lane:** файлы `search_aggregator.py`, `tool_router.py`,
  `voice_transcripts.py`, `mca_vision.py` не изменялись (caps-tools lane).

## 1. Карта cap → решение

| # | Cap (файл:строка в кандидате) | Было | Решение | Замена / источник | Тест |
|---|---|---|---|---|---|
| 1 | `handlers/factcheck.py:477` `_clamp_window` | `before+after ≤ FACTCHECK_CONTEXT_TOTAL_CAP=40`, якорь сверх | **Удалён** код-кап и `settings.FACTCHECK_CONTEXT_TOTAL_CAP`; окно = операторские before/after | реальное окно режет ёмкостный фид фактчека | `TestFactcheckContextCaps::test_total_cap_40_removed`, `test_no_total_cap_keeps_configured_window` |
| 2 | `services/factcheck_context.py:92` `resolve_feed_capacity_chars` | фиксированные 8k/12k символов, 600 симв./сообщение, 40 фрагментов, 120 симв. digest | **Удалены** 600/40; фид = реальная ёмкость маршрута (`model_capacity.resolve_evidence_window_tokens` → `evidence_window_for_tokens`); дословные фрагменты полным текстом; якорь-предмет сохраняется всегда; вытесненные названы числом | `_VERBATIM_BUDGET_SHARE=0.6` только распределяет реальную ёмкость; 8k/12k остались лишь явным kill-switch-откатом (`EVIDENCE_WINDOW_DYNAMIC_ENABLED=false`) | `test_render_feed_uses_capacity_not_fixed_20k`, `test_anchor_survives_even_if_larger_than_capacity`, `test_digest_truncated_verbatim_full` |
| 3 | `services/direct_chat_service.py:11945` `_render_current_question` | `CHAT_CURRENT_QUESTION_MAX_CHARS=800`, маркеры могли вытеснить текст | **Удалён** потолок и замена числом; полный текст + маркеры; L1 получает тот же полный вопрос (нет L1/Writer divergence) | физический лимит Telegram и реальное окно композера | `test_long_claim_over_800_and_2981_reaches_block`, `test_media_markers_do_not_replace_text`, `test_current_question_escape_and_no_char_cap` |
| 4 | `services/direct_l1.py` `build_l1_context` bot_replies | каждая прежняя реплика бота `[:L1_REPLY_BLOCK_CHARS=400]` | **Удалён** символьный срез; полный текст, сжатие — `_cap_context` по реальному бюджету L1 | реальный бюджет L1 | `test_l1_bot_reply_not_clipped_to_400` |
| 5 | `services/direct_execution.py:2693` `DEFAULT_EVIDENCE_CAP_CHARS` | неизвестное окно → 4000 | **0 = без искусственного среза**; caller с реальным бюджетом передаёт положительное значение | D1: неизвестная модель = planning 1M, не 4000 | `test_unknown_capacity_delivers_all_evidence` |
| 6 | `services/direct_execution.py:2697` `l2_evidence_budget_chars` | `min(40% окна, window−others−reserve)` | **Удалён 40%-потолок**; evidence = весь остаток реального входного бюджета минус прочие блоки, floor 300 | реальное окно стадии | `test_no_40pct_ceiling_in_budget_formula`, `test_large_evidence_reaches_payload_at_real_capacity` |
| 7 | `services/direct_execution.py:3047` `build_l2_fallback_adapter` | фиксированный evidence floor 400 и срез `evidence[:1600]` при переполнении; полный evidence мог игнорировать бюджет | Evidence получает реальную долю остатка окна (пропорционально фактическим размерам), floor — гарантия минимума; system/часы/`<Current_Question>` защищены; при срезе — явный маркер `показано N/M токенов` и CAPACITY-строка | реальный fallback-бюджет | `test_fallback_evidence_uses_real_remaining_not_fixed_floor`, `test_fallback_keeps_full_evidence_when_fits`, `TestContextOverflowRecovery::test_l2_recomposes_once_under_proven_limit` |
| 8 | `services/direct_chat_service.py:13430` `_truncate_block` | при protected spans всегда отнимал 48 токенов, даже если спаны переживают срез | Сначала полный лимит; резерв 48 — только когда защищённый спан реально потерян | — | `test_protected_reserve_does_not_double_truncate` |
| 9 | `services/direct_chat_service.py:10338`, `:15031` L2 digest | `CHAT_LEVEL2_MAX_CHARS=1500` keep-head cap в обоих путях | **Удалён** символьный срез; L2-пересказ едет полным, упаковка — композер | реальное окно | `test_level2_not_capped_by_char_budget`, `test_parts_keep_head_and_marker` |
| 10 | `services/direct_execution.py:630` fact_check args | `claim_text[:300]` | **Полный claim**; семантический отбор — L1, не символьный срез | — | `test_caps_context` + `test_evol_evidence_routing` |
| 11 | `services/direct_chat_service.py:6314` tool-loop output | longform-4096 как `max_output_tokens` | физически допустимый `writer_max_output_tokens` фактической модели; unknown → `None` (дефолт провайдера) | провайдерский `max_output`/окно | `test_ur_d_writer` (max_output не 700/4096/16384) |

### Что НЕ удалено и почему

- `factcheck_context._WIDE_WINDOW_MAX = 500` и `_DIGEST_LINE_MAX_CHARS = 120` —
  это **выборка окна вокруг цели** и представление уровня 1 (компакт-хронология);
  предмет проверки и релевантные фрагменты идут полным текстом (см. тесты).
  `factcheck_suitability` использует 500 как потолок расширения окна.
- `/persona` card `_PERSONA_MAX_ITEMS=10`, `_PERSONA_DOSSIER_MAX_CHARS=1200` —
  формат пользовательской команды, не payload модели; не менялись.
- `_EVIDENCE_NOTE_RESERVE_CHARS=260` — резерв под машинную строку, не потеря.
- `_BUNDLE_*_MAX_REFS` — метаданные scoped-envelope, сам контекст не режут.
- `CHAT_CURRENT_QUESTION_MAX_CHARS` / `CHAT_LEVEL2_MAX_CHARS` остались в
  `settings`/каталоге как совместимые ключи; код их больше не применяет.
  Честная подпись каталога — кандидат в backlog PM (BACKLOG_ONLY).

## 2. Config-bound evidence

| Настройка / гейт | Заводское | Эффективно в тестах | Примечание |
|---|---|---|---|
| `EVIDENCE_WINDOW_DYNAMIC_ENABLED` | `True` (ClassVar) | `True` | `False` — явный откат к 8k/12k фиду фактчека |
| `DIRECT_CONTEXT_COMPOSER_ENABLED` | `True` | `True` | legacy-путь не удалён, но искусственные 4000/1500 в нём удалены |
| `flags.budgets_enabled` | per-chat/global/factory | default ON в тестах; отдельный тест `enabled=False` | OFF не уничтожает секции (`test_legacy_budget_off_returns_every_block`) |
| `CHAT_CURRENT_QUESTION_MAX_CHARS` | 800 | 800 (в тесте 10) | значение игнорируется, поведение — полный текст |
| `CHAT_LEVEL2_MAX_CHARS` | 1500 | 1500/40 | значение игнорируется, поведение — полный L2 |
| `L2_EVIDENCE_FLOOR_TOKENS` | 400 | 400 | гарантия минимума evidence, не потолок |
| `EVIDENCE_FLOOR_CHARS` | 300 | 300 | минимум источника при известной ёмкости |

Production effective config и реальный provider payload в этом lane не
наблюдались (см. §5).

## 3. Тесты

- Широкий затронутый набор (29 файлов Direct/context/factcheck/evidence/
  capacity): **1135 passed** (`raw/pytest-caps-context-final.txt`).
- `tests/test_caps_context.py`: **16 passed**.
- RED на базе `aca13702` тем же файлом: **11 failed, 5 passed**
  (`raw/red-base-caps-context-final.txt`); падают именно новые границы
  (Current_Question, фактчек-кап 40, фид 600/40, evidence 4000/40%, fallback
  fixed floor, protected reserve).
- Мутация (возврат `stripped[:800]` в `_render_current_question`):
  **2 failed, 1 passed** в `TestCurrentQuestionFullText`, после restore —
  **3 passed** (`raw/mutation-red-final.txt`,
  `raw/mutation-current-question-cap800.diff`).
- `git diff --check aca13702 HEAD -- services tests` — пусто
  (`raw/git-diff-check.txt`, 0 байт); `git diff -w` содержательно совпадает
  (расхождение только в 1–2 строках форматирования на файл).
- Pre-existing на базе (воспроизведены там же, не вызваны кандидатом):
  `tests/test_direct_fallback_recompose_asap32.py` — 5 failed;
  `tests/test_speech_p0_a2_memory.py::test_style_anchors_not_broken`;
  `tests/test_104_backend_additions.py::test_user_facing_text_updated`.

## 4. Наблюдаемое поведение (примеры)

- Вопрос 3500+ символов проходит в `<Current_Question>` целиком; медиа-маркер
  не заменяет текст.
- Корректирующая рамка содержит claim/quote 3000+ символов целиком (тест).
- `claim_text` для fact_check tool — без `[:300]`.
- Evidence 100 000 символов при реальном окне 32 768 токенов доходит до
  `pack.text` целиком (`l2_evidence_budget_chars` > 100k символов).
- При неизвестной ёмкости (`capacity_chars=0`) evidence не режется.
- Factcheck feed при `char_budget=200 000` содержит полный предмет проверки;
  при ёмкости 200 символов предмет сохраняется, а остальные фрагменты честно
  помечены как не показанные.
- Fallback: медиана бюджета 2000 токенов отдаёт evidence больше floor 400
  (маркер `показано N/M токенов`), при переполнении — CAPACITY-строка, а
  `<Current_Question>` не теряется.
- Budgets OFF: `_apply_context_budget(enabled=False)` возвращает все блоки.

## 5. Остаточные items (честно)

1. **Cross-lane residual:** `services/tool_router.py:4804` всё ещё делает
   `reply_text[:300]` при деривации claim для fact_check. Это файл caps-tools
   lane; не редактировался по правилу координации. Требуется закрыть в его
   кандидате либо отдельным ограниченным патчем.
2. **Live/provider step 1:** тесты используют fake provider; фактический
   финальный payload реального провайдера и production effective-state в этом
   lane не снимались. Кандидат — `REVIEW`, не `VERIFIED`.
3. **legacy kill-switch:** при `EVIDENCE_WINDOW_DYNAMIC_ENABLED=false` фид
   фактчека возвращается к 8k/12k — это явный операторский откат, не
   заводской путь; отдельного теста отката нет (функция возвращает `None`,
   ветка покрыта кодом, но не отдельным RED).
4. **UI/catalog honesty:** `CHAT_CURRENT_QUESTION_MAX_CHARS` и
   `CHAT_LEVEL2_MAX_CHARS` больше не влияют на payload, но остаются
   редактируемыми в каталоге. BACKLOG_ONLY для PM.
5. **`/persona` display caps** оставлены как продуктовый формат команды;
   если PM считает их частью C3-02 — отдельный срез, не текущий кандидат.
6. Деплой/merge в master/train не выполнялись.

## 6. External sources

Не использовались: все утверждения проверены по коду/тестам репозитория.
