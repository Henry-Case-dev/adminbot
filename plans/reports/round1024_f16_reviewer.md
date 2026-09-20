# Ревью F16 `youtube-multimodal-download-fallback-round1024` — раунд 10.24, шаг 5

> Коммит: `c06c457` · Baseline HEAD `00eab85` · Файл отчёта: `plans/reports/round1024_f16_reviewer.md`
> Прочитано: `spec.md`, `ADR-1024-17.md`, `tasks.md`, `plans/features/round1024-upd4-architecture.md`, `plans/current_task.md` (UPD4-B + UPD5 п.1/2/3), `git show c06c457 --stat`, `git diff c06c457^ c06c457`.
> Секреты не цитировались. R18 соблюдён (`current_task.md`/`.env` в коммит не попали).
> **Важно:** рабочее дерево на момент ревью **грязное** (незакоммичены правки `handlers/youtube.py`, `services/tool_router.py`, `plans/backlog.md` — чужая фича F14/F19). Полный прогон и построчное ревью выполнены **на самом коммите** `c06c457` через отдельный `git worktree`, а не на текущем HEAD.

---

## Статус

Changes Requested

## Короткое резюме

Ядро F16 сделано честно и по делу: `_canonical_youtube_url` удалён, `summarize_cascade` стал L3-only, YouTube+summary реально скачивает файл и отдаёт мультимодалке **подписанный `/media/`-URL**, а не `watch?v=`; фолбэк на субтитры, тишина для юзера на A/B, `reason`-атрибут движка, отдельный пул `YOUTUBE_AGE_RESTRICTED_PHRASES`, credentialed-гейт `build_ytdlp_base_opts()`/`_transcript_proxy_config()` и R17-safe presence-лог — всё на месте. Тесты не тавтологичны: гоняют реальный `youtube_handler`, проверяют порядок A→B→C, OFF/OFF-allowlist/OFF-media_share, timeout, R17, disjoint пула; полный pytest на коммите — **7731 passed + 1 pre-existing env-фейл** (см. §Прогон). Инварианты (Δ DDL=0, Δ каталога=0, egress, `parse_mode=None`, `imported-history-immutable`) соблюдены.

Но фича **P0 про контроль цены** (R1/NFR-4 — «скачивание + L1/L2 до 240с») не имеет одного очевидного гейта, который есть у нативной ветки: шаг A качает 360p даже когда мультимодальный клиент **недоступен**, то есть файл гарантированно никуда не денется. Плюс сбой публикации не глушится, как требует карта исключений §3.3. Это «почти готово», но для P0 с явным бюджетным риском — отклоняю.

---

## Findings

### [Severity: High]
**File:** `handlers/youtube.py`
**Location:** `_process_youtube_summary`, условие входа шага A/B (коммит: ~:1088–1096); ср. нативная ветка `_process_video_media` (:1019–1020) и `direct_url` (:817–818).
**Problem:** Шаг A входит при `_yt_multimodal_enabled() and media_share.enabled() and _media_downloader is not None and _yt_multimodal_allowed(...)`, но **не проверяет доступность мультимодального клиента**. Если `_service.video_client is None` или `not .available` (пустой/отозванный ключ OpenRouter), `_download_youtube_silent` всё равно скачивает полный ролик (до `YOUTUBE_MULTIMODAL_DOWNLOAD_TIMEOUT_SECONDS`=240с), затем `_publish_and_cascade` публикует копию в `MEDIA_SHARE_DIR`, `summarize_media_url` мгновенно падает с `VideoLevelError("no openrouter key")` — и ветка идёт на субтитры. В отличие от `direct/platform`, где скачанный файл затем нужен для STT-фолбэка, YouTube-субтитровый фолбэк (`summarize_cascade` → `engine.fetch_transcript`) файл **не использует вообще**. Нативная ветка (`:1019`) этот гейт имеет — F16 от неё отстал.
**Why it matters:** Это ровно тот бюджет/диск, из-за которого F16 получил High-риск R1 и per-chat слот пула: каждый запрос «че за видос» в состоянии «нет видео-ключа» тратит до 4 минут на скачивание и кладёт копию на диск, чтобы тут же её выбросить и уйти в субтитры. При недоступном ключе вся ветка превращается в генератор пустых скачиваний — kill-switch `YOUTUBE_MULTIMODAL_DOWNLOAD_ENABLED` тут не поможет, он глобальный. Гейт `media_share.enabled()` от этого не спасает (секрет есть, ключа OpenRouter нет).
**Required fix:** Добавить в условие шага A/B проверку клиента до скачивания (парность с `_process_video_media:1019`):
```python
if (_yt_multimodal_enabled()
        and _service.video_client is not None
        and _service.video_client.available
        and media_share.enabled()
        and _media_downloader is not None
        and _yt_multimodal_allowed(message.chat.id)):
```
Одновременно внести правку в `spec.md §3.1 п.3` (условие входа) как осознанное уточнение. Добавить тест: `service.video_client.available = False` → `downloader.downloaded == []`, `publish_media_file` не вызван, `summarize_cascade` вызван один раз. (Проверка на `None`/недоступность — один if; при этом `_publish_and_cascade` остаётся последней страховкой.)

### [Severity: Medium]
**File:** `handlers/youtube.py`
**Location:** `_process_youtube_summary`, вызов `_publish_and_cascade` (~:1095) и общий `except Exception` (~:1137); `_publish_and_cascade` (:679–711, незакрытый `publish_media_file`).
**Problem:** Карта исключений `spec §3.3` требует: «сбои скачивания/**публикации**/мультимодалки — тихий WARNING + переход на фолбэк (не доходят до юзера)». Скачивание и мультимодалка закрыты, а публикация — нет: `_publish_and_cascade` не оборачивает `media_share.publish_media_file(...)` в try/except, и любое её неожиданное исключение проносится мимо ветки C прямо в общий `except Exception:` хендлера, где юзеру уходит `LLM_ERROR_PHRASES` («LLM упал»), хотя LLM не при чём, а должен был отработать субтитровый фолбэк.
**Why it matters:** Контракт «деградация молчаливая для юзера» ломается на третьем участнике пайплайна. Сегодня `_publish_sync` ловит OSError, поэтому вероятность низкая, но это не гарантия: `asyncio.to_thread` при остановке executor'а бросает `RuntimeError`, а shared-функция используется ещё native/direct/platform. Ложная фраза «LLM упал» + потерянный фолбэк на субтитры — как раз тот класс баг-репортов, из-за которого и завели UPD4.
**Required fix:** Обернуть шаг B целиком, чтобы любая неожиданность уходила тихо:
```python
try:
    ticket, text_out = await _publish_and_cascade(bot, message.chat.id, str(path), _LABEL_YT_URL)
except Exception as exc:
    logger.warning("[youtube] multimodal publish/cascade unexpected | error=%s", type(exc).__name__)
    ticket, text_out = None, None
```
(Либо `try/except` внутри `_publish_and_cascade` на `publish_media_file` — но так как функция общая, безопаснее локально в F16.) Тест: `publish_media_file` бросает → `send_message` содержит текст субтитрового пути, а не `LLM_ERROR_PHRASES`, ровно один `send_message`.

### [Severity: Low]
**File:** `handlers/youtube.py`
**Location:** `_process_youtube_summary`, `finally` (~:1142–1150); `_publish_and_cascade` (:710–711).
**Problem:** `ticket` удаляется **дважды**: `_publish_and_cascade` уже делает `await media_share.delete_file(ticket.file_id)` в собственном `finally` (и файл к моменту возврата `ticket` уже удалён), после чего хендлер повторяет то же в своём `finally`. Локальная переменная `ticket` в хендлере не несёт никакой функции — сразу за удалением в `_publish_and_cascade` она уже мертва.
**Why it matters:** Двойной `delete_file` даёт лишний INFO-лог `[media_share] deleted` на каждый запрос и создаёт ложное впечатление, что хендлер владеет lifecycle публикации (владеет `_publish_and_cascade`). Это скрытая двусмысленность владения, из-за которой следующий разработчик может «починить» удаление не в том слое. Паттерн унаследован из native-ветки, но F16 его тиражирует без нужды.
**Required fix:** Не заводить `ticket` в `_process_youtube_summary` (вызов вида `_, text_out = await _publish_and_cascade(...)`) и убрать `delete_file` из `finally` — удаление целиком на стороне `_publish_and_cascade`. Если хендлерное удаление оставляем сознательно (TTL-страховка из spec §3.1 п.6), добавить комментарий, что это best-effort дубликат, и почему.

### [Severity: Low]
**File:** `plans/ARCHITECTURE.md`
**Location:** §13 (стр. 233), §15 (стр. 252).
**Problem:** Документация всё ещё описывает старую семантику: «`summarize_cascade` — L1 → L2 → L3», «**youtube+summary** — прежний путь … без изменений», «payload `video_url = watch?v=…`». При этом `tasks.md` T-2318/T-2319 помечены `[x]`, а spec §12 прямо выносит эту правку «на шаге 7 @Architect». Получается рассинхрон: код уже живёт по-новому, канон-документ — по-старому.
**Why it matters:** `plans/ARCHITECTURE.md` — источник правды для последующих фич (F19/F14 читают §13/§15). Ложное «watch?v= как `video_url`» в каноне провоцирует рецидив того же бага в tool-пути. Сейчас это не блокер кода F16, но должно быть закрыто до закрытия фичи.
**Required fix:** Обновить §13/§15: `summarize_cascade` — L3-only (сигнатура та же), YouTube+summary = download→`media_share`→`summarize_media_url`→субтитровый L3; убрать «watch?v= как video_url». Либо, если Step 7 ещё впереди, снять `[x]` у T-2318/T-2319 и явно написать в `tasks.md`, что doc-AMEND открыт.

### [Severity: Low]
**File:** `tests/test_youtube_multimodal_download_round1024.py`
**Location:** `TestDownloadPublishMultimodal`, `TestSubtitleFallback`.
**Problem:** Не покрыты ветки, которые легко регрессируют: (a) `video_client.available = False` (Finding High — теста нет вовсе); (b) `media_share.enabled() == True`, но `publish_media_file` вернул `None` (файл > `MEDIA_SHARE_MAX_MB`/не-whitelisted ext) → тихий фолбэк на субтитры; (c) в успешном тесте не проверяется, что скачивание шло с quality `360` (`downloader.quality == ["360"]`); (d) не проверяется, что на мультимодальном успехе память НЕ пишется (spec §3.1 п.4/§3.2 — «паритет с native: память только на путях с транскриптом»).
**Why it matters:** (b) — это поведение при перешагнувшем 200 МБ ролике (реальный кейс), (d) — R16/NFR-1-инвариант, который сейчас держится лишь тем, что вызова памяти в ветке нет; без теста следующий правщик легко «добавит инъекцию для консистентности».
**Required fix:** Дописать 4 теста: `available=False` → download не вызван; `publish_media_file → None` → `summarize_cascade` вызван, фраза/текст субтитрового пути; `downloader.quality == ["360"]`; spy на `fire_and_forget`/`memory` при мультимодальном успехе == отсутствие вызовов.

### [Severity: Low]
**File:** `services/youtube_summarizer_service.py`
**Location:** `_publish_and_cascade` docstring (`handlers/youtube.py:685`: «Успех → (None, text)»).
**Problem:** Docstring утверждает, что при успехе возвращается `(None, text)`, тогда как код возвращает `(ticket, text_out)` (:709). Рассинхрон документации и кода в центральном для F16 хелпере.
**Why it matters:** Мелочь, но именно по этой docstring читатель решает, кто владеет удалением ticket (см. Finding Low про двойной delete). Ошибка в комментарии здесь прямо провоцирует следующую ошибку в коде.
**Required fix:** Привести docstring к факту: «Успех → `(ticket, text)`; ticket уже удалён в `finally`». (Правка pre-existing, но затрагивается F16-веткой — уместно исправить сейчас.)

---

## Контракт (чекбоксы)

- [x] `_canonical_youtube_url` удалён; в OpenRouter уходит опубликованный файл-URL (`…/media/…?s=`), не `watch?v=` (тест T2/T3: `kwargs["video_url"] == MEDIA_URL`, `"watch?v=" not in …`).
- [x] `summarize_cascade` = L3-only, сигнатура сохранена, `video_client` не вызывается (`TestSummarizeCascadeL3Only.test_never_calls_video_client`).
- [x] Порядок A (download 360p, бюджет, allowlist) → B (publish → `summarize_media_url` → `delete_file`) → C (subtitle L3) реализован; при OFF/OFF-`media_share`/allowlist — сразу C.
- [x] Сбои скачивания (класс + safe-`reason`, без URL) и мультимодалки — тихие, юзеру только выжимка/фраза фолбэка (`test_download_failure_silent_then_subtitles`, `test_multimodal_failure_falls_back_to_subtitles`).
- [ ] **Сбой публикации** не глушится — Finding Medium.
- [x] `YouTubeTranscriptUnavailableException.reason ∈ {age_restricted, transient, unavailable}`, позиционный `message` сохранён; `AgeRestricted → age_restricted`, `RequestBlocked/IpBlocked → transient`, иначе `unavailable`; приоритет age → transient → unavailable (`TestReasonClassification`, прод-кейс `1TON5W_SNKY`).
- [x] Пул `YOUTUBE_AGE_RESTRICTED_PHRASES` (3 фразы, строчные, без эмодзи), disjoint с существующими пулами; хендлер выбирает его по `reason=="age_restricted"`.
- [x] Credentialed-гейт `YOUTUBE_CREDENTIALED_LEVEL_ENABLED` реально режет cookies/POT/proxy в `build_ytdlp_base_opts()` и `_transcript_proxy_config()`; значения — только `.env`; presence-лог `set|empty` без значений (тест `TestCredentialedLevel`).
- [x] Флаги `YOUTUBE_MULTIMODAL_DOWNLOAD_ENABLED/_TIMEOUT_SECONDS/_CHAT_IDS`: OFF → сразу субтитры; timeout clamp ≥30; allowlist пусто = все (тесты).
- [ ] **Гейт доступности мультимодального клиента в шаге A** — отсутствует (Finding High).

## Инварианты

- [x] **Δ DDL = 0** — ни одного файла миграций/`database.py`/`CREATE TABLE` в диффе.
- [x] **Δ каталога = 0** — новые рубильники только `ClassVar` вне `param_catalog`; `test_param_catalog` зелёный.
- [x] **egress** — новых send-точек нет: `send_chunked_reply`/`_reply`/`react_moai` уже в реестре; `test_outgoing_guard_round1022` зелёный.
- [x] **R16** — API аддитивен (`reason` keyword-only; флаги `ClassVar`).
- [x] **R17** — логи A/B без URL/подписи, presence-only креды; caplog-тест `TestR17NoSignedUrlInLogs` зелёный. (Полный `logger.exception` возрастной ветки содержит только `video_id`+движковые ошибки — не секрет.)
- [x] **R18** — `current_task.md`/`.env` в коммит не попали.
- [x] **`parse_mode=None`** — текстовая доставка не менялась; локальный HTML-курсив transcript-ветки не тронут.
- [x] **`imported-history-immutable`/`manual-overrides-immutable`** — не затрагивались.
- [x] **Порядок роутеров `bot.py`** — не сдвигался.
- [x] **Байт-в-байт**: transcript/native/direct/platform и немедиа-ветки — существующие регресс-тесты (`test_video_router`, `test_youtube_video_media`, `test_youtube_handlers`) зелёные на коммите.
- [x] **Ступень** `handlers/youtube.py`: F14 (`047481c`) → F16 (`c06c457`) соблюдена; F19 в коммит не влезал.
- [x] F1–F14, F17, F20–F22 не сломаны (полный прогон).

## Тесты

- [x] download → publish → multimodal (реальный `/media/`-URL, label `youtube-file`, субтитры не запускались, кэш записан, tmp-файл удалён).
- [x] мультимодалка `VideoLevelError`/пустой ответ → фолбэк на `summarize_cascade`.
- [x] скачивание `DownloadError`/timeout → тихий фолбэк, ровно один `send_message`, `publish` не вызван.
- [x] `media_share.enabled()==False` и флаг OFF → скачивание не вызывается.
- [x] age-restricted → `YOUTUBE_AGE_RESTRICTED_PHRASES`; `unavailable` → `YOUTUBE_ERROR_PHRASES`; пул disjoint/строчный/без эмодзи.
- [x] credentialed presence `set|empty` без значений; allowlist/clamp.
- [x] cache-hit не запускает A/B/L3.
- [x] reason-классификация движка (age/transient/unavailable, приоритет, прод-кейс).
- [x] youtube+transcript → сырой транскрипт курсивом (`test_video_router.py:276`, T-2340(d)) — покрыт существующим тестом.
- [ ] `video_client.available=False`; publish→`None`; quality `360`; memory-not-written — тестов нет (Finding Low).
- [x] Тесты не тавтологичны: вызывают реальный `youtube_handler`, фейковый bot/cache/downloader, проверяют порядок и факт невызова соседних шагов.

## Полный прогон (на коммите `c06c457`, отдельный worktree)

- `python -m pytest -q` → **7731 passed, 1 failed** (`tests/test_history_cli.py::TestCliFts::test_scope_is_required` — кодировка subprocess на Windows в пути worktree; **не связан с F16**: тот же тест падает и на baseline `c06c457^`, и **проходит в основном дереве репозитория**; заявленные «7732» сходятся: 7731 + env-фейл = 7732).
- `git diff --check c06c457^ c06c457` → чисто.
- JS-гейты для F16 не требуются (web/** не тронут).

---

## Точный список требуемых исправлений

1. **`handlers/youtube.py` — шаг A/B:** добавить в условие входа проверку `_service.video_client is not None and _service.video_client.available` (парность с `_process_video_media:1019`), чтобы недоступность мультимодалки не вызывала бессмысленное скачивание/публикацию на P0-ветке. Синхронно уточнить `spec.md §3.1 п.3`.
2. **`handlers/youtube.py` — шаг B:** обернуть `_publish_and_cascade` в `try/except Exception` → WARNING `type(exc).__name__` + `(None, None)` → шаг C; чтобы сбой публикации не показывал юзеру `LLM_ERROR_PHRASES` в обход субтитрового фолбэка (spec §3.3).
3. **`handlers/youtube.py` — cleanup:** убрать избыточный `ticket`/`delete_file` из `finally` `_process_youtube_summary` (удаление уже сделано в `_publish_and_cascade`) либо явно задокументировать осознанный best-effort дубликат.
4. **`plans/ARCHITECTURE.md` §13/§15:** обновить описание `summarize_cascade` (L3-only) и YouTube+summary (download→file→subtitles), убрать «watch?v= как video_url»; или снять `[x]` у T-2318/T-2319 до Step 7.
5. **Тесты (`tests/test_youtube_multimodal_download_round1024.py`):** добавить (a) `video_client.available=False` → без скачивания; (b) `publish_media_file → None` → фолбэк на субтитры; (c) `downloader.quality == ["360"]`; (d) memory/fire_and_forget не вызывается на мультимодальном успехе.
6. **`handlers/youtube.py:_publish_and_cascade` docstring:** «Успех → `(ticket, text)`; ticket уже удалён в `finally`» вместо «(None, text)».

**Верни исправленную версию. Текущий код отклонён.**

---

# Итерация 2 (коммит `fba2b87`, поверх F14-фикса `744ae4f`)

> Diff: `git diff fba2b87^ fba2b87` — 3 файла: `handlers/youtube.py` (+31/−11), `plans/ARCHITECTURE.md` (+24), `tests/test_youtube_multimodal_download_round1024.py` (+80). F14-фикс `744ae4f` — **чужая фича, F16 не приписываю**; он был в базе до `fba2b87` и лишь проверялся на отсутствие регресса общей ручкой.
> Пометка о процессе: `spec.md`/`ADR-1024-17.md` — untracked (конвенция репо для `plans/features/**`), поэтому правки спеки в коммит не входят; наличие правки проверено в рабочем дереве.

## Статус

**Approved**

## Проверка закрытия findings

- **[High → Закрыт]** Гейт доступности мультимодалки добавлен в условие A/B: `handlers/youtube.py:1105–1110` — `_yt_multimodal_enabled() and _service.video_client is not None and _service.video_client.available and media_share.enabled() and _media_downloader is not None and _yt_multimodal_allowed(...)`. При недоступном/отсутствующем клиенте скачивание не запускается. Спека уточнена: `spec.md:55` (§3.1 п.3) и `spec.md:157` (§4.2). Тесты `test_video_client_unavailable_skips_download`, `test_video_client_none_skips_download` — не тавтологичны (`downloader.downloaded == []`, `publish_media_file.assert_not_awaited()`, `summarize_cascade.assert_awaited_once()`).
- **[Medium → Закрыт]** Шаг B обёрнут в `try/except Exception as exc` → `logger.warning("[youtube] multimodal publish/cascade unexpected | error=%s", type(exc).__name__)` + `text_out = None` → шаг C (`handlers/youtube.py:1114–1125`). R17-safe (только класс исключения, без `str(exc)`). Тест `test_publish_raises_silent_falls_back`: `RuntimeError` из `publish_media_file` → ровно один `send_message`, текст субтитрового фолбэка и **не** `LLM_ERROR_PHRASES`, в caplog есть `multimodal publish/cascade unexpected`.
- **[Low → Закрыт]** Дублирующий `delete_file`/`ticket` убран из `finally` `_process_youtube_summary` (`:1171–1177` — только `os.unlink(path)` + `permit.release()`); lifecycle `ticket` — у `_publish_and_cascade`. Docstring `_publish_and_cascade` (`:693–699`) приведён к факту: «Провал обеих моделей → `(ticket, None)`; Успех → `(ticket, text)`; ticket уже удалён в `finally`».
- **[Low → Закрыт]** `plans/ARCHITECTURE.md`: §13 (стр. 233) и §15 (стр. 252) получили инлайн-пометку `[10.24/F16 AMEND (см. §50)]` (в §15 старое «прежний путь … без изменений» зачёркнуто и заменено на download→`media_share`→`summarize_media_url`→L3; `summarize_cascade` — L3-only); добавлена новая **§50** с полным описанием пайплайна A→B→C, `reason`, credentialed-уровня, флагов и границ «байт-в-байт». AMEND-стиль соответствует принятому в репо.
- **[Low → Закрыт]** Тест-гэпы: добавлены `test_multimodal_success_writes_no_memory` (spy на `fire_and_forget` = `[]`, `memorize_facts.assert_not_called()`), `test_publish_returns_none_falls_back`, `test_publish_raises_silent_falls_back`, quality-ассерт `downloader.quality == ["360"]` в success-тесте, плюс два теста недоступного клиента. Все — поведенческие, не тавтологичные.

## Повторная проверка пайплайна (по существу)

- [x] A→B→C: download (`_download_youtube_silent`, 360p, бюджет/allowlist) → publish+`summarize_media_url` (`/media/`-URL, label `youtube-file`) → субтитровый L3; успех B → `send_chunked_reply` + `cache.set` + `return`.
- [x] Тишина для юзера на A/B: сбои download (класс+safe-reason, без URL) и publish/cascade (`type(exc).__name__`) — только WARNING; юзеру либо выжимка, либо фраза субтитрового пути.
- [x] Фолбэк субтитры: `summarize_cascade` L3-only, `video_client` не вызывается.
- [x] Age-restricted: `reason`-классификация (age → transient → unavailable), отдельный пул `YOUTUBE_AGE_RESTRICTED_PHRASES`.
- [x] Credentialed: `YOUTUBE_CREDENTIALED_LEVEL_ENABLED` режет cookies/POT/proxy в `build_ytdlp_base_opts()`/`_transcript_proxy_config()`; presence-лог `set|empty` без значений.
- [x] Флаги `YOUTUBE_MULTIMODAL_DOWNLOAD_ENABLED/_TIMEOUT_SECONDS/_CHAT_IDS` — OFF/allowlist/clamp работают (тесты зелёные).

## Инварианты (итерация 2)

- [x] Δ DDL = 0 — коммит не трогает БД/миграции.
- [x] Δ каталога = 0 — `test_param_catalog` зелёный.
- [x] egress — новых send-точек нет; `test_outgoing_guard_round1022` зелёный.
- [x] R16/R17/R18 — аддитивность; логи без URL/подписи/секретов; `current_task.md`/`.env` не в коммите.
- [x] `parse_mode=None` / `imported-history-immutable` / порядок роутеров `bot.py` — не затрагивались.
- [x] F1–F14/F17/F20–F22 — полный прогон зелёный.

## Прогон (итерация 2)

- Целевые: `test_youtube_multimodal_download_round1024.py + test_video_cascade + test_video_router + test_youtube_transcript_engine + test_settings_helpers + test_param_catalog` → **351 passed**.
- Новые тесты точечно (`-k "memory or unavailable or none_skips or publish_returns_none or publish_raises"`) → **6 passed**.
- Полный: `.venv/Scripts/python.exe -m pytest -q` → **7746 passed, 0 failed** (1 warning — starlette deprecation, не наш). Совпадает с заявленным.
- `git diff --check fba2b87^ fba2b87` → чисто.

## Остаточные замечания (не блокеры, вне кода F16)

- `handlers/youtube.py:881–882` (direct/platform) и `:1060–1061` (native) сохраняют старый двойной `delete_file` (`_publish_and_cascade` уже удаляет ticket) — pre-existing, вне scope F16, «байт-в-байт» не трогали. Кандидат на отдельную уборку.
- `_publish_and_cascade` — общий хелпер; при желании можно перенести обработку `publish_media_file` внутрь него, но текущий локальный `try/except` в F16 корректен и безопаснее для native/direct.

**Approved** @Orchestrator Код прошёл ревью. Можно двигаться дальше.
