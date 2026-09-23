# Evidence — S2 `summary-context-restore-round1026`

## T-3224 @DevOps — точка отката + бэкап + baseline ДО правок

- **Дата:** 2026-09-23, ts-суффикс `20260923-164410`
- **HEAD:** `7895e77b05f75072e9ae85d61eb76ed7333bc5a2`
- **Тег отката:** `pre-round1026-s2` → `git rev-parse pre-round1026-s2` = `8aa7b2b980256cb6bf62bf73841e0fc29b21cb7f`; `git rev-parse pre-round1026-s2^{commit}` = `7895e77b05f75072e9ae85d61eb76ed7333bc5a2`
- **Origin:** `git ls-remote --tags origin pre-round1026-s2` = `8aa7b2b980256cb6bf62bf73841e0fc29b21cb7f`
- **Бэкап:** `var/backups/s2-round1026-20260923-164410/` (`git archive HEAD`) — `services/summary_generator.py`, `services/summary_filter.py`, `services/summary_memory.py`, `services/summary_xml.py`, `services/thread_chain.py`, `config/settings.py` + `BASELINE.md`; blob-хеши всех 6 файлов == HEAD.
- **`.env`:** `.env.bak.round1026-s2`, размер 7131 = 7131, SHA256 совпадает; содержимое не печаталось.
- **Baseline:** `APP_VERSION` 2.58.20; pytest `.venv` (Python 3.12.0) **8525 / 0** / 1 warning; JS (node v24.16.0) **43/43**; `database is locked` = 0; Δ DDL = 0; каталог **467/426/442/100/98/21**.
- **Git:** ничего не закоммичено; `deploy_commands.txt` не трогался; R18 соблюдён (теги/бэкапы/`stash@{0}` не удалялись).
- **Статус:** VERIFIED (baseline зафиксирован, точка отката опубликована).

## Step 4 @Builder — блоки A–G (T-3227…T-3243) + bump

- **Дата:** 2026-09-23. **Diff base:** HEAD `7895e77` (рабочее дерево, без коммита/деплоя).
- **Новые файлы:**
  - `services/summary_context_restore.py` — pure-core `restore_context(...) -> RestoreResult`
    (ADR-1026-4 D1), `RestoreParams`, `build_l1_payload` (§92), `RESTORE_CHAIN_DEPTH=10`.
  - `tests/test_summary_context_restore.py` — 34 unit-теста.
  - `tests/test_summary_context_restore_integration.py` — 10 интеграционных тестов.
- **Изменённые файлы (runtime):** `services/summary_generator.py` (врезка S2 в
  `_apply_filter` после `filter_window` и до `xml.build`; адаптер `_restore` /
  `_collect_extra_parents` на reuse `thread_chain.collect_thread_chain`; логи
  `RESTORE_START/COMPLETE/ERROR`; `restored_count` в `_filter_metrics`);
  `config/settings.py` (`APP_VERSION` 2.58.20 → **2.58.21**); `README.md` (v2.58.21);
  `plans/docs/param-registry-round1025.meta.md` (провенанс APP_VERSION → 2.58.21,
  реестр/каталог НЕ переиздавался).
- **Блоки:**
  - **A (T-3227…T-3229):** reply-родители транзитивно (§90 пример 100→101→102),
    проход сквозь бот-ответы (in-window) + родители вне окна через `extra_parents`
    (адаптер `collect_thread_chain`, глубина ≤10); `restored_count`/`parent_count`/
    `neighbor_count`/`restored_tg_ids`; гейт `flags.summary_filter_reply_context_enabled`.
  - **B (T-3230…T-3231):** соседи `context_neighbors` с каждой стороны (только `dropped`),
    cap `context_max_messages` на добавления (тест cap=50 при 200 кандидатах).
  - **C (T-3232…T-3233):** ASC `(timestamp,id)`, дедуп по `id`, двойной прогон
    байт-идентичен; `id`/`tg_message_id`/`reply_to_id` не подменяются (те же объекты строк).
  - **D (T-3234…T-3237):** короткий тред восстановлен; всплеск → только ближайшие;
    параллельные треды не склеиваются; медиа/подпись/транскрипт сохранены;
    бот-ответ и прошлое Саммари (`user_id==bot_id`) не восстанавливаются.
  - **E (T-3238…T-3239):** бюджет `token_limit`/`char_limit` (`resolve_context_tokens`/
    `resolve_chat_limit` — без новых ключей); усечение → `status='truncated'` +
    `skipped_ids`; `kept` не удаляется никогда (тест «tiny budget»).
  - **F (T-3240…T-3241):** `build_l1_payload` — поля §92 только из реальных
    (`message_id←tg_message_id`, `author_id←user_id`, `display_name←author_name`,
    `message_type←media_type`), `mentions` не выдумывается, `chat_id` из запуска.
  - **G (T-3242…T-3243):** unit-матрица + интеграция (детерминизм, fail-open,
    OFF байт-в-байт, A/B per-chat, XML получает restored, RAG — исходные rows,
    ровно 2 LLM-вызова).
  - **H (T-3244):** **NOT_APPLICABLE** (ADR-1026-4 D6/D7: новых параметров нет;
    Δ каталога=0, новых API/JS-блоков нет).
- **Команды и фактические результаты:**
  - `py -3 -m pytest tests/test_summary_context_restore.py -q` → **34 passed**.
  - `.venv\Scripts\python.exe -m pytest -q` → **8569 passed, 0 failed** (baseline 8525 + 44 новых).
  - JS: `node tests/js/*.js` (43 файла) → **43/43 OK**; `node --check` на 4 правленых
    тест-скриптах → OK.
  - Каталог: REGISTRY **467** / Settings **426** / categorized **442** / GROUPS **100** /
    `_TAB_BY_GROUP` **98** / TAB_RULES **21** → **Δ каталога=0**.
  - `git diff --check` → exit 0; **Δ DDL=0** (`services/database.py`, миграции — вне diff).
  - Вне diff: `services/summary_xml.py`, `services/summary_prompts.py`, публикация
    (`image_generation.py`/`telegram_send.py`/`media_send.py`/`build_cover_media`) — не тронуты.
- **Правки тестов (только версия/изоляция слоёв, без ослабления):**
  - `tests/test_summary_filter_integration.py` — 2 S1-кейса изолированы от S2
    (`flags.summary_filter_reply_context_enabled=false`), ассерты S1 сохранены.
  - Версия-пиннинг 2.58.20 → 2.58.21 в 18 файлах тестов (Python + JS) — штатный bump.
- **Не проверено / ограничения:** deploy не выполнялся (T-3250 @DevOps); live-проверки
  Telegram — PENDING OWNER VERIFICATION; независимое ревью @Reviewer/@Scanner — T-3245/T-3246.
  Примечание: в реальном `_run` reply-родитель в окне обычно уже сохранён S1-критерием
  «answered»; S2 критичен для родителей **вне окна** / сквозь бот-ответы и при `min_weight>1`.
