# round1025 — Хотфикс-3 `hotfix3-summary-stt-anticliche-round1025`, Step 6 @Scanner

- **База:** `HEAD = fe0f7bb`; изменения хотфикса-3 — **в рабочем дереве, не закоммичены** (диффа `fe0f7bb..HEAD` нет). Аудит по `git diff` (unstaged) + untracked.
- **Область:** `services/system2_handoff.py`, `services/summary_generator.py`, `services/anticliche_worker.py`, `web/api/anticliche.py`, `services/llm_client.py`, `config/settings.py`, `SmartModule/service.py`, `SmartModule/transcriber/audio_prep.py` (new), `web/app.js`, `web/index.html`, новые тесты. `services/telegram_send.py`, `handlers/{youtube,voice_transcription}.py`, `services/negative_constraints.py` — **не менялись (реюз)**, регресс-риск из хотфикса = 0.
- **Итог: Critical 0 / High 0 / Medium 2 / Low 4 / Info 1 → к деплою — ДА** (Medium/Low — техдолг, не блокеры).

## Факты (прогоны)

- pytest: **8037 passed / 0 failed** (100.28 s; 1 сторонний Starlette-warning) — заявленные 8037/0 **подтверждены**.
- JS: **22/22 OK** (`node tests/js/*.js`, включая `round1025_hotfix3_cliche_report_test.js`).
- `git diff --check` = exit 0. Секретов/`<id>:<token>`/ключей в добавленных строках нет (R17 по логам — только числа/коды/hostname/класс ошибки).

## Critical — 0

Нет.

## High — 0

Нет.

## Medium — 2 (не блокеры)

1. **M-1. Аудио-подготовка держит слот STT-семафора.** `SmartModule/service.py:105-128`: `_prepare_for_stt` вызывается **внутри** `async with self._semaphore`. ffmpeg синхронный (`asyncio.to_thread`), таймаут `_COMPRESS_TIMEOUT_S = 300.0`, а `_chunk` делает до **2** попыток → в худшем случае один большой файл занимает слот до ~15 мин. При малой `SMARTMODULE_CONCURRENCY_*` это заметно сокращает пропускную способность STT/кружков. *Фикс:* вынести подготовку до входа в семафор (или отдельный пул/лимит + укоротить prep-таймаут).
2. **M-2. Fail-fast `LLM_FALLBACK_TIMEOUT_SECONDS` 120→60 — это per-attempt, а не бюджет цепочки.** `config/settings.py:1087-1089` и ADR/комментарий `services/llm_client.py:133-135` говорят про «бюджет фоллбэк-цепочки»; фактически `asyncio.timeout(self._fallback_timeout)` оборачивает **один** POST (`llm_client.py:879`), ретраи (до 3 попыток) не менялись. Риск: для легитимно медленного провайдера (ранее до 120 с) возможны **ложные таймауты** → фоллбэк. *Фикс:* привести комментарии/ADR к реальности; наблюдать `llm_stats().timeout_share` / `reason=total_budget_exceeded` в проде, при росте — вернуть/поднять per-attempt.

## Low — 4

3. **L-1. Temp-каталог чанкинга не удаляется.** `SmartModule/transcriber/audio_prep.py::_chunk`: на успехе возвращает `parts`, но `outdir` (`tempfile.mkdtemp(prefix="stt_seg_")`) не удаляется; `AudioPrepResult.cleanup()` (`:60-70`) удаляет только **файлы** (`os.remove`), без `rmtree`. Пустые `%TEMP%/stt_seg_*` копятся на каждый чанкованный файл. *Фикс:* хранить каталог в результате и делать `shutil.rmtree` в `cleanup()` (fail-open).
4. **L-2. Лишнее сжатие 20–25 МБ.** `SmartModule/service.py::_compress_target_mb` берёт `min(limits)` доступных стратегий, т.е. сжимает файл, который **влезает** в более мягкий гейт (напр. Groq 25 МБ при OpenRouter 20 МБ), вопреки докстрингу «не влезает во ВСЕ стратегии». *Фикс:* сжимать только при `size_mb > max(limits)` (иначе гейт-цикл сам выберет подходящую стратегию).
5. **L-3. Нет теста на baseline `SYSTEM2_SUMMARY_ENABLED=False`.** `_resolve_cover_prompt` (`summary_generator.py:692-701`) явно возвращает `""` для выключенного System 2 — это и есть «OFF = baseline», но ветка не покрыта (тесты фиксируют `SYSTEM2_SUMMARY_ENABLED=True`). *Фикс:* добавить кейс «single-путь без обложки → plain».
6. **L-4. Слабое JS-покрытие.** `tests/js/round1025_hotfix3_cliche_report_test.js` — grep по исходникам (`indexOf`) без исполнения `saveCliche`; логика «Сохранено N из M» реально не проверяется (паттерн уже в техдолге прошлых раундов). *Фикс:* поведенческий тест с моком `api()`.

## Info — 1

- `_chunk` сортирует `glob("part_*.ogg")` лексикографически — при >999 частей порядок сломается (нереалистично при 24 kbps; не фикс).

## Что чисто (проверено)

- **Двойной отправки/потери текста нет:** `summary_generator.py:397-403` — строго либо `_deliver_rich`, либо `_deliver_plain`; rich не стримит, при ошибке ровно один откат `_plain_fallback` (rich→plain с `downgrade_rich_to_plain`).
- **`parse_summary_handoff_ex`:** ветви `empty` / `invalid_json` / `invalid_digest` / `ok` корректны; обёртка `parse_summary_handoff` — байт-в-байт прежнее поведение.
- **OFF = baseline:** `SUMMARY_COVER_FALLBACK_ENABLED=False` → plain (тест); `STT_AUDIO_COMPRESS_ENABLED=False` → старый гейт без вызова сжатия (тест); оба флага — env-only `ClassVar`, вне `param_catalog`.
- **Анти-клише C:** ручные фразы не фильтруются хардкодом, но помечаются (`hardcoded_flagged`); авто-путь фильтрует (`manual=False`); честный `saved/dropped/count/total` — тихой потери нет; канон 120 согласован (`negative_constraints.DYNAMIC_PHRASE_MAX`, API `PatternIn.max_length`, UI `maxLen=120`, подсказка в `index.html`).
- **ffmpeg безопасен:** аргументы списком, без `shell=True` → инъекция аргументов/пути с пробелами/спецсимволами исключена; вывод через `mkstemp`(0600)/`mkdtemp`(0700); traversal-примитивов не добавлено; вход ограничен 1000 паттернов/120 символов (`_manual_input_cap`), `build_patterns` авто-путь ограничен ответом LLM.
- **R17:** новые логи — только счётчики/коды причин/hostname/тип исключения; сырые фразы в лог не пишутся (`web/api/anticliche.py:142-151`); `_LLM_STATS` — процессные числа без секретов.
- **Тест-качество:** новые Python-тесты нетривиальны (reference `build_patterns_report`/`parse_summary_handoff_ex`/`llm_stats`/`extract_audio_for_stt` отсутствовали → падают на старом коде); красная зона покрыта.
- **Регрессии:** rich-путь, генерация картинок, F0/F1/P0, Эпик 2/промпты — не тронуты; `handlers/*`, `services/telegram_send.py` без изменений.
- **Инварианты:** Δ DDL = 0 (миграции не менялись); Δ каталога = 0 (`test_settings_field_count` = 418 проходит; новые флаги — `ClassVar`, вне `dataclasses.fields`); `stash@{0}` цел; zip/бинарников в изменениях нет.

## Для @DevOps (без вердикта по коду)

- `database is locked` по коду не оценивается — проверить по проду/WAL-метрикам после деплоя (в hotfix2 зафиксировано 0).
- Наблюдать `llm_stats().timeout_share` после снижения fallback-таймаута (M-2).

## Вердикт

**К деплою — ДА** (Critical 0 / High 0). Medium/Low — в техдолг; блокирующих рисков не найдено.
