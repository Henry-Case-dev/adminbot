# Хотфикс-3 `hotfix3-summary-stt-anticliche-round1025` — локальная спецификация

> **Раунд:** 10.25 (внеплановый, после F1/hotfix2, перед F2). **Задачи:** T-2482…T-2506 (`tasks.md`).
> **Мастер-ТЗ:** `plans/current_task.md` (untracked — **не коммитить**, секреты не цитировать, R17/R18).
> **Тип:** backend (summary/media/anticliche/LLM) + web (UI анти-клише) + ops (деплой/верификация).
> **Статус:** Step 2 @Architect — спроектировано. Реализация — @Builder (Step 4).
> **ADR:** `adr-1025-7-summary-fallback-stt-anticliche.md` (решения D1–D5).
> **Baseline (hotfix2):** HEAD `fe0f7bb` (+`fea2daa`), pytest **8003/0**, JS **21/21**, matrix 0, `database is locked`=0, APP_VERSION **2.58.2**.

## Инварианты (нарушать нельзя)
1. **Δ DDL = 0**, **Δ каталога (ParamSpec/GROUPS) = 0** (флаги — env-only `ClassVar`).
2. **Рабочий rich-путь саммари не ломать** (эталон в логах 01:03/05:13/07:03: rich+обложка уходит успешно).
3. **Ручные фразы анти-клише не терять**; никаких «молчаливых» дропов.
4. Не трогать F0/П0-fix/F1-контракты, Эпик 2, каноны промптов. R16/R17/R18; секреты не логировать/не выводить; бэкапы/теги/`stash@{0}` не удалять.

---

## 1. [P0] A — Саммари: обложка и rich на fallback-пути (T-2483…T-2487)

**Факты (принято):** Stage-1 «Редактор» (`parse_summary_handoff`, `services/summary_generator.py:480`) невалиден из-за таймаутов `nano-gpt.com` → лог `:483` «невалидная выжимка редактора — fallback» → одиночный путь `:362-376` → `cover_prompt=""` (`:389`) → условие `:393-396` ложно → `_deliver_rich` (`:667-716`) не вызывается → plain. На успешном пути обложка/rich работают (`services/telegram_send.py:168-187` `build_cover_media`, `:190-215` `send_rich_message`).

**Решение (рекомендация @Architect — «оба», ADR-1025-7 D1):**
- **(a) Устойчивость Stage-1:** безопасный разбор handoff (невалидный JSON/выжимка → явная ошибка с причиной, не молча) + **ограниченный повтор** (`≤1`) только при таймауте/транзиентной ошибке провайдера; при валидном повторе одиночный путь НЕ включается; число попыток и причина — в лог (R17-safe). Без роста расходов/зависаний (bounded).
- **(b) Fallback-путь не теряет обложку:** при фолбэке **не** выставлять `cover_prompt=""`: сгенерировать `cover_prompt` и отправить **rich с обложкой** через существующие `build_cover_media`/`send_rich_message`. Plain — только если обложка/rich реально недоступны (`SUMMARY_COVER_ARTICLE_ENABLED` OFF, rich-unsupported и т.п.), с **явной залогированной причиной**.
- **Почему «оба»:** (a) снижает частоту фолбэков (корень — провайдер), (b) даёт **пользовательскую гарантию** обложки независимо от Stage-1; по отдельности каждое закрывает лишь половину класса. `(b)` — основное для приёмки.
- **Kill-switch `SUMMARY_COVER_FALLBACK_ENABLED`** (env-only `ClassVar`, default **ON**, вне `param_catalog`): ON → новое поведение (rich на fallback); OFF → прежнее plain-поведение **байт-в-байт**. Обоснование: обратимость без `git revert`, соответствие паттерну §53/§54.1.

**Точки изменения:** `services/summary_generator.py` (ветки `:362-376`, `:389-399`, `:460-504`, `_deliver_rich` `:667-716`), `config/settings.py` (флаг), `services/system2_handoff.py::parse_summary_handoff` (диагностика ошибки), тесты.

## 2. [P0] C — Анти-клише: честный отчёт (T-2488…T-2493)

**Факты (принято):** `build_patterns` (`services/anticliche_worker.py:226-258`) тихо дропает: длина (<2/>120 — `services/negative_constraints.py:217-218`), совпадение с хардкод-клише (`find_forbidden_cliches` `:297-335`, напр. «подводя итог»), дубли, cap. API `web/api/anticliche.py:29-42,130-141` → 200 + уменьшенный `count`; UI `web/app.js:4938-4959` всегда «Сохранено».

**Решения (ADR-1025-7 D2):**
- **Единый канон длины фразы:** `normalize_dynamic_phrase` — **2…120 символов** (`DYNAMIC_PHRASE_MIN/MAX` — канон). UI/API приводятся к **120** (`maxlength`, подсказка); расхождения «500 vs 120» нет. **Разведены:** «лимит длины фразы» (120) ≠ «число паттернов» (вместимость `limits.anticliche_max_patterns`).
- **Ручные фразы НЕ фильтровать хардкод-правилами:** `find_forbidden_cliches` применяется только к **автогенерации**; фразы, добавленные пользователем вручную, **сохраняются** (в т.ч. «подводя итог») — максимум помечаются `hardcoded` в отчёте, но не дропаются. Ограничения ручного ввода: только длина/дубли/cap.
- **Честный контракт API:** `{saved: [...], dropped: {invalid, hardcoded, duplicate, over_limit}, count}`; `200 ≠ «всё сохранено»`; частичное сохранение отличимо от полного.
- **UI warn:** «Сохранено N из M» + причины отброса; **не** писать «Сохранено», если что-то отброшено. При полном сохранении — прежний успех.

**Точки изменения:** `services/anticliche_worker.py:226-258`, `services/negative_constraints.py:217-237,297-335`, `web/api/anticliche.py:29-42,130-141`, `web/app.js:4938-4959` (единственная правка `web/app.js` в хотфиксе), тесты API/UI.

## 3. [P0] B — STT: извлечение/сжатие аудио (T-2494…T-2499)

**Факты (принято):** сырой файл 28 МБ > лимитов провайдеров (Groq 25 — `config/settings.py:1373`, OpenRouter 20 — `:1374`); извлечения/сжатия нет. Гейт `SmartModule/service.py:94-148` (отказ по `size_mb > max_mb`); вызовы `handlers/youtube.py:607-655,1082-1206`, `handlers/voice_transcription.py:272-280`. ffmpeg на проде есть (`/usr/bin/ffmpeg` 6.1.1).

**Решение (ADR-1025-7 D3):**
- **Helper `extract_audio_for_stt(path, max_mb)`** (в `SmartModule/transcriber/`): ffmpeg `-vn -ac 1 -ar 16000 -c:a libopus -b:a 24k -f ogg` → ogg/opus mono 16 kHz ~24 kbps; если после сжатия всё ещё > лимита — **fallback-чанкинг**; без ffmpeg → чанкинг, иначе **честная ошибка** (не молчаливый отказ).
- **Врезка в `VoiceTranscriber.transcribe_voice`** — покрывает **и видео, и ГС/кружки** (единая точка); вызывающие ветки (`youtube.py`/`voice_transcription.py`) не дублируют логику. Логировать `reason=compressed` + размеры до/после; `reason=no_ffmpeg`/`reason=chunked` при фолбэках.
- **Kill-switch `STT_AUDIO_COMPRESS_ENABLED`** (env-only `ClassVar`, default **ON**): OFF → прежний размерный гейт/OFF-поведение байт-в-байт.

**Точки изменения:** `SmartModule/transcriber/` (новый helper + `base.py`/`groq_transcriber.py`/`openrouter_transcriber.py`), `SmartModule/service.py:94-148`, `handlers/youtube.py:607-655,1082-1206`, `handlers/voice_transcription.py:272-280`, `config/settings.py` (флаг), тесты.

## 4. [P1] D — LLM-таймауты `nano-gpt.com` (T-2500…T-2501)

**Факты (принято):** 24ч — `ReadTimeout=189`, `LLMTimeoutError=28`, `GraphExtractionError=10`; корень провайдерский.
**Решение (ADR-1025-7 D4):** **fail-fast** вместо долгого ожидания — оценить и (при обосновании) снизить `LLM_FALLBACK_TIMEOUT_SECONDS` (`config/settings.py:1079-1080`, default 120) и/или `LLM_TIMEOUT` (`:379`, default 30)/`LLM_MAX_RETRIES` (`:381`, default 2) с числами «до/после»; логику/контракт ретраев не менять по смыслу. **Пометить корень как провайдерский**; R17-safe лог причины (`ReadTimeout`/`LLMTimeoutError`). Добавить событие/метрику доли таймаутов и fallback-срабатываний. **Второй резервный провайдер — вывод «внедряем/нет + почему»** (эскалация владельцу), не расширять хотфикс.

**Точки изменения:** `config/settings.py:379,381,1079-1080`, `services/llm_client.py` (лог причины/метрика), тесты.

---

## 5. Точные точки изменения (сводно) и границы

| Причина | Файлы (основные) |
|---|---|
| A | `services/summary_generator.py:362-376,389-399,460-504,667-716`; `services/system2_handoff.py`; `services/telegram_send.py:168-215` (только чтение/реюз) |
| C | `services/anticliche_worker.py:226-258`; `services/negative_constraints.py:217-237,297-335`; `web/api/anticliche.py:29-42,130-141`; `web/app.js:4938-4959` |
| B | `SmartModule/{service.py:94-148,transcriber/*}`; `handlers/youtube.py:607-655,1082-1206`; `handlers/voice_transcription.py:272-280`; `config/settings.py` |
| D | `config/settings.py:379,381,1079-1080`; `services/llm_client.py` |
| Флаги | `config/settings.py` (env-only `ClassVar`, вне `param_catalog`) |

**Границы:** не менять контракты F0 (`write_transaction`/save-слой), П0-fix (container→host путь), F1 (nav/shell), Эпик 2 (Саммари-алгоритмы? — правим только **ветвление доставки/парсинг**, не пайплайн Stage-1/Stage-2 как таковой; промпты не трогаем), каноны. `web/app.js` — только C (T-2492).

## 6. Как докажем (verification)
1. **A:** при фолбэке Stage-1 сообщение уходит **rich с обложкой** (тест + лог); успешный rich-путь не изменён; при недоступности rich — plain с залогированной причиной.
2. **B:** видео **28 МБ** транскрибируется (сжатие `reason=compressed`); ГС/кружок > лимита — тоже; малый файл не деградирует; без ffmpeg — корректный фолбэк/честная ошибка.
3. **C:** ручная фраза «подводя итог» **сохраняется**; API отдаёт `saved`+`dropped` по причинам; UI — «Сохранено N из M» + причины.
4. **D:** таймауты логируются с причиной; метрика доли таймаутов/fallback есть.
5. **Регресс:** pytest **8003/0 (+ новые)**, JS **21/21**, matrix 0, `database is locked`=0, `node --check web/app.js` OK, `git diff --check` exit 0; нет регрессий F0/hotfix2/F1.

## 7. Риски и откат
| Риск | Ур. | Снятие |
|---|---|---|
| Ломка рабочего rich-пути | Critical | `SUMMARY_COVER_FALLBACK_ENABLED` ON/OFF; тест «успешный rich не изменён» (T-2487) |
| Тихий фолбэк остаётся | High | T-2483/T-2484: событие с причиной; plain только с логом |
| Ложное «Сохранено» (C) | High | T-2490/T-2491/T-2492: ручные не фильтровать; API `saved`+`dropped`; UI warn |
| ffmpeg/чанкинг | High | T-2494/T-2495: проверка ffmpeg + корректный фолбэк; тест без ffmpeg |
| Секреты в логах | Critical | R17-safe логи; `.env`/`current_task.md` не коммитить |
| Расширение скопом (D/инфра) | Medium | D — P1, после A/B/C; не расширять |

**Откат:** тег `pre-round1025-hotfix3` (T-2482) + `git revert`; флаги OFF — байт-в-байт прежнее поведение; при правке ассетов — bump `APP_VERSION`/`?v=`.

## 8. Покрытие задач
T-2482 → §0 (откат/baseline); T-2483…T-2487 → §1 (ADR D1); T-2488…T-2493 → §2 (D2); T-2494…T-2499 → §3 (D3); T-2500…T-2501 → §4 (D4); T-2502…T-2505 → §5/§6; T-2506 → архивация/интеграция. **Все 25 задач покрыты.**

## 9. Ответы на open questions @PM
1. **Stage-1:** делаем **оба** (a+b); основное для приёмки — (b) «обложка на fallback». Флаг `SUMMARY_COVER_FALLBACK_ENABLED` ON.
2. **Канон длины:** **2…120** (backend-канон); UI/API к 120; «длина фразы» ≠ «число паттернов».
3. **Ручные фразы:** **не фильтруются** `find_forbidden_cliches`; помечаются `hardcoded`, но сохраняются.
4. **STT-формат:** ogg/opus mono 16 kHz ~24 kbps достаточно; **чанкинг — только fallback** после сжатия.
5. **ffmpeg:** есть на проде; если недоступен — чанкинг/честная ошибка (не тихий отказ).
6. **D:** fail-fast (снижение таймаутов при обосновании) + лог/метрика; второй провайдер — решение «внедряем/нет» в отчёт.
7. **Флаги:** env-only `ClassVar` достаточно (UI-флаги ADR-1024-13 не требуются).

## 10. Ссылки
- `plans/features/hotfix3-summary-stt-anticliche-round1025/{tasks.md, adr-1025-7-summary-fallback-stt-anticliche.md}`
- `plans/ARCHITECTURE.md` §52 (F0), §53 (hotfix media), §54/§54.1 (F1/P0-fix); `plans/round1025-architecture.md`
- Отчёты: `plans/reports/round1025_hotfix2_scanner_audit.md`, `round1025_f1_scanner_audit.md`
