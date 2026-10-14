# Ревью F14 `native-media-tools-round1024` — раунд 10.24, шаг 5

> Коммит: `047481c` · Baseline HEAD `00eab85` · Файл отчёта: `plans/reports/round1024_f14_reviewer.md`
> Прочитано: `spec.md`, `ADR-1024-15.md`, `tasks.md`, `round1024-upd4-architecture.md`, `current_task.md` (UPD4 A + UPD5 п.3), `git show 047481c --stat`, `git diff 047481c^ 047481c`.
> Секреты не цитировались. R18 соблюдён (`current_task.md` в коммит не попал).

---

## Статус

Approved (итерация 2; итерация 1 была Changes Requested — см. раздел «Итерация 2» ниже)

## Короткое резюме

Функциональное ядро F14 сделано добротно: native-first в Fast-Track работает, невидео-документ (PDF) отсекается, probe-fail получил отдельный пул и R17-safe трассу, схемы `summarize_video`/`download_media` ослаблены корректно, контракт `transcribe_video` объявлен, но не зарегистрирован (ступень F14 → F19), полный pytest — **7698 passed**, `git diff --check` чист, Δ DDL = 0, Δ каталога = 0, egress-реестры не тронуты.

Но **kill-switch фичи дырявый**: флаг `NATIVE_MEDIA_TOOLS_ENABLED` гейтит только Fast-Track, а `services/tool_router.py` его не читает **вообще**. Спека (§9, ADR-1024-15 §2.5) прямо требует гейтить и «native-резолв в tool_router»: при OFF нативные вызовы инструментов без `url` должны возвращать **прежнюю ошибку**, а не работать. Сейчас при OFF инструменты по-прежнему ходят в `fetch_media_to_tmp`/`media_share`/STT. Это ломает план отката (§10 «Флаг OFF») — в проде kill-switch не отключит новую точку расхода. Плюс центральный новый код-путь (публикация `media_share` → мультимодалка) не покрыт ни одним тестом, и отсутствует обязательный caplog-тест R17 нативного пути.

Это не «почти готово», это «фича без рабочего аварийного тормоза». Отклоняю.

---

## Findings

### [Severity: High]
**File:** `services/tool_router.py`
**Location:** `_resolve_tool_source` (:855–867); `ToolContext.__init__` (:378–394); связка `services/direct_chat_service.py:753–756`
**Problem:** `NATIVE_MEDIA_TOOLS_ENABLED` не читается в `tool_router`. `grep` по всем `.py` даёт только `config/settings.py` и `handlers/video_download.py`. Резолвер источника безусловно возвращает `"native"`, если в `ctx.native_media` лежит видео; `direct_chat_service` эмитит `native_media` безусловно.
**Why it matters:** Спека §9: флаг гейтит *(a) native-first Fast-Track* **и** *(b) native-резолв в `tool_router`*; OFF = «urls-first; нативные вызовы без `url` → прежняя ошибка». Сейчас **(b) не реализован**: при `NATIVE_MEDIA_TOOLS_ENABLED=0` пользовательский tool-call без `url` всё равно пойдёт нативным путём. Это не «перф-мелочь»: нативный путь = расход на fetch TG-файла + публикация в `media_share` + STT/LLM-вызовы. При инциденте в проде выключение флага не остановит этот расход, а откат по §10 «Флаг OFF» окажется фиктивным — придётся `git revert`. Kill-switch, который не kill'ит, — опаснее его отсутствия.
**Required fix:** В `_resolve_tool_source` (единственная точка резолва для всех трёх инструментов) добавить проверку флага до нативного резолва:
```python
native_enabled = bool(getattr(settings, "NATIVE_MEDIA_TOOLS_ENABLED", True))
...
if native_enabled and native is not None \
        and getattr(native, "kind", "") in _NATIVE_VIDEO_KINDS:
    return "native", None, native
return None, None, None
```
и при `source is None` в `_summarize_video` возвращать **прежнюю** (до-F14) строку `"ОШИБКА summarize_video: некорректная ссылка"`, когда флаг OFF (сохранить новую «нет источника» только для ON). Для `download_media` строка `"Некорректная ссылка"` уже совпадает с до-F14. Обязательно добавить тест: flag OFF + `ctx.native_media` + `{}` → `download_media` даёт error-статус, `summarize_video` даёт legacy-ошибку, `fetch`/`send` не вызываются.

### [Severity: Medium]
**File:** `tests/test_native_media_tools_round1024.py`
**Location:** `TestToolsNativeSource.test_summarize_video_native_stt_fallback` (:~230)
**Problem:** Протестирован только STT-фолбэк (`video.video_client = None`). Публикационный путь `media_share.publish_media_file` → `service.summarize_media_url` → `media_share.delete_file` (`services/tool_router.py:803–834`) не покрыт ни одним тестом — при том что это ключевой новый код фичи (spec §6(b) явно требует «публикация→мультимодалка→STT-фолбэк»).
**Why it matters:** В этом пути живут: TTL-резолв (`hot.get("limits.media_share_ttl_seconds")`), вызов `media_share.enabled()`, `ticket.abs_url`, гарантированный `delete_file` в `finally`, обработка `VideoLevelError`. Любая опечатка (перепутанный kwarg, не отданный ticket, утечка опубликованного файла при исключении) пройдёт в прод незамеченной. Ровно такие баги потом «файлы не удаляются и жрут диск».
**Required fix:** Добавить тест успешной публикационной ветки: `video_client.available=True`, `media_share.enabled` monkeypatch → `True`, `publish_media_file` → фейковый ticket, `summarize_media_url` → непустой текст; проверить, что `summarize_media_url` вызван с `video_url=ticket.abs_url`, `delete_file` вызван ровно один раз, STT-фолбэк **не** задействован, tmp-файл удалён. Дополнительно — ветку «`summarize_media_url` кинул `VideoLevelError` → delete_file всё равно вызван → STT-фолбэк».

### [Severity: Medium]
**File:** `tests/test_native_media_tools_round1024.py`
**Location:** `TestProbeFail` (весь класс); нативный путь логов — покрытия нет
**Problem:** Spec §6(h) требует: «file_id/URL/локальные пути не появляются в логах нативного пути (caplog)». Есть только caplog-тест probe-fail (быстрая ветка Fast-Track). Нативные логи (`services/native_media.py:139` `bytes=%d`, `services/tool_router.py` native download/summarize, `handlers/video_download.py:792`) caplog'ом не проверяются.
**Why it matters:** R17 — не пожелание, а инвариант раунда. Единственная защита от утечки `file_id`/tmp-пути/подписанного `abs_url` в прод-логи — эти самые вызовы логгера; без теста любой будущий `logger.info(..., path)` останется незамеченным. Подписанный `abs_url` в логе = публичная ссылка на файл (прямая утечка).
**Required fix:** Добавить caplog-тесты: (1) успешный `download_media` native — в `caplog.text` нет `file_id`, нет `abs_url`-хоста, нет `foo.mp4`/tmp-пути; (2) native summarize — то же. Достаточно проверить, что в логах присутствуют только `kind=`/`bytes=`/`chat_id=`.

### [Severity: Medium]
**File:** `services/tool_router.py`
**Location:** `_NATIVE_STT_TIMEOUT = 120.0` (:102), `_native_stt` (:845–853)
**Problem:** Таймаут STT зашит константой, тогда как паритетный путь youtube берёт его из конфига: `handlers/youtube.py:399–405` → `_stt_timeout()` → `hot.get("limits.video_stt_timeout_seconds", ...)`. Spec §3.3.6 требует «лимиты размера/длительности как в `handlers/youtube.py:893-910`», §3.3.8 — «таймауты переиспользуются».
**Why it matters:** Operators меняют видео-STT-таймаут через `limits.video_stt_timeout_seconds`; новый нативный инструмент это изменение проигнорирует. При медленном STT нативный summarize будет рваться на 120s, хотя кнопка в каталоге говорит иное. Двойная семантика таймаута = необъяснимые прод-фейлы.
**Required fix:** Читать тот же ключ: `timeout=float(hot.get("limits.video_stt_timeout_seconds", settings.VIDEO_STT_TIMEOUT_SECONDS))` (проверить имя поля `Settings`) либо переиспользовать существующий хелпер youtube. Константу убрать.

### [Severity: Low]
**File:** `services/native_media.py` (:64–90, :73–99); `handlers/youtube.py` (:277–300)
**Location:** `_has_file_id`, `resolve_reply_video`
**Problem:** Спека §4.1 и ADR §2.3 заявляют «семантика **байт-в-байт** совпадает с текущей `_resolve_video_media`». Фактически поведение изменено: (1) добавлен `_has_file_id` — раньше `message.video` возвращался даже с пустым/нестроковым `file_id`; (2) исключение в первом кандидате теперь `continue`-ится и резолвится второй кандидат, а раньше весь резолв отдавал `None` с логом `UNHANDLED`.
**Why it matters:** «Байт-в-байт» — это обещание регресс-безопасности, зафиксированное в ADR. Недокументированное расхождение с ADR означает, что тест-паритет с youtube не доказан, а reviewer/эстиматор F16 будут опираться на ложную гарантию. Изменения, скорее всего, полезны (защита от MagicMock/битых объектов), но должны быть явно зафиксированы как ревизия, а не выданы за паритет.
**Required fix:** Либо убрать `_has_file_id`/per-candidate-catch (вернуть точную семантику), либо внести правку в ADR §2.3/§4.1 как осознанное изменение семантики и добавить тест-паритет «video без file_id → youtube резолвит/не резолвит так же, как native_media». Молчаливое расхождение недопустимо.

### [Severity: Low]
**File:** `handlers/youtube.py:130`, `handlers/video_download.py:171–172`
**Location:** `_VIDEO_DOC_EXTENSIONS`, `_document_is_video`
**Problem:** После делегирования алиасы `_VIDEO_DOC_EXTENSIONS` в обоих модулях не используются в продакшн-коде (только определение; `_document_is_video` в `video_download` тоже не вызывается — используется `native_media_module` напрямую). Мёртвый код/тени.
**Why it matters:** Мёртвые алиасы создают иллюзию, что локальная квалификация ещё жива; следующий разработчик может поправить «локальную» копию и не понять, почему поведение не меняется. ТД копится незаметно.
**Required fix:** Удалить неиспользуемые алиасы (в т.ч. `_VIDEO_DOC_EXTENSIONS`, `video_download._document_is_video`), если на них не завязаны тесты; если завязаны — оставить только те, что реально проверяются, с комментарием «только для совместимости тестов».

### [Severity: Low]
**File:** `services/tool_router.py:855–867`
**Location:** `_resolve_tool_source`
**Problem:** Аргумент `source: enum["link","reply"]` полностью игнорируется при резолве — учитывается только `url`. Модель может передать `url=<http>` + `source="reply"` (противоречие), и код молча уйдёт по ссылке.
**Why it matters:** Спека §4.5 ставит `source=="reply"` в строку нативного резолва; несогласованность схемы и поведения = скрытый контракт, который LLM будет нарушать непредсказуемо. Декоративное поле в JSON-схеме — техдолг.
**Required fix:** Либо явно реализовать приоритет (`source=="reply"` → native, даже при http-`url`), либо зафиксировать в ADR/spec, что `source` — только подсказка, и добавить тест на противоречивый ввод (какая ветка побеждает). Молчаливый игнор — не вариант.

### [Severity: Low]
**File:** `services/native_media.py:75–99`
**Location:** `resolve_reply_video`, ветки `except Exception ... exc_info=True`
**Problem:** `logger.warning(..., exc_info=True)` на каждом сообщении direct-chat. Трейсбек aiogram-объекта может содержать repr объекта/`file_id`/внутренние пути — формально это R17-риск.
**Why it matters:** Модуль вызывается на **каждом** сообщении (`direct_chat_service:754`), так что при массовом сбое резолва логи быстро раздуются, а трейсбеки могут затащить идентификаторы медиа.
**Required fix:** Оставить `logger.debug` без `exc_info` (или логировать только `type(exc).__name__`), а полный трейс — только при явном флаге отладки.

### [Severity: Low]
**File:** `services/direct_chat_service.py:753–756`
**Location:** эмиссия `ToolContext.native_media`
**Problem:** Спека §5 закрепляет `direct_chat_service.py` за владельцем **F13** (интерфейсная строка T-2295), а правку внёс коммит F14. F13 (`da928d9`) эмиссию не отдал — F14 дописал её в чужой файл.
**Why it matters:** Смешение владения усложняет атрибуцию регрессов и нарушает дисциплину «одна фича — один файл-владелец»; при этом именно эта строка включает live-путь, так что без неё критерий приёмки 5 не выполнялся.
**Required fix:** Не блокирую, но: зафиксировать в `tasks.md`/ADR, что эмиссия T-2295 фактически влита F14 (вместо F13), и убедиться, что F13-коммит не добавит дубль. Это явное изменение границы, а не «попутная правка».

---

## Контракт (чекбоксы)

- [x] native-first: своё/реплай видео приоритетнее caption-URL (`handlers/video_download.py:264–273`; тесты `test_video_with_caption_url_goes_native`, `test_reply_video_with_caption_url_goes_native`).
- [x] невидео-документ (PDF) не уходит в нативный путь → `VD_NO_LINK_PHRASES` (`:276–281`; тесты `test_pdf_document_not_native`, `test_reply_pdf_not_native`).
- [x] флаг OFF → Fast-Track байт-в-байт прежний (`:282–298`; `test_flag_off_urls_first`).
- [x] `services/native_media.py`: единый резолвер (`resolve_reply_video`, `document_is_video`, `media_suffix`, `download_to_tmp`), делегирование из `handlers/youtube.py` без смены общей семантики (тест `test_youtube_resolver_delegates`).
- [x] voice/video_note не квалифицируются как видео (`resolve_reply_video` смотрит только `video`/`document`).
- [x] `summarize_video` без `mode`; `url` необязателен; `+source:["link","reply"]`; `required: []`; `additionalProperties:false`.
- [x] `TOOL_TRANSCRIBE_VIDEO` — только контракт, НЕ в `TOOL_CALLING_TOOLS` (`len(TOOL_CALLING_TOOLS)==9`; тест `test_transcribe_contract_defined_but_not_registered`).
- [x] bytes берутся из `ToolContext.native_media` (разрешённый aiogram-объект), не из текста модели.
- [x] `ToolContext.native_media` / `ToolDeps.transcriber` аддитивны (keyword-параметры; тест `test_deps_context_new_fields_default_none`).
- [x] DI в `bot.py` без сдвига роутеров (`bot.py:496–502`, только DI-kwarg).
- [x] probe-fail: пул `VD_PROBE_FAIL_PHRASES` + R17-safe `trace_step` (`handlers/video_download.py:376–380,445–446`; тесты `TestProbeFail`).
- [ ] **Флаг гейтит native-резолв в `tool_router` (OFF → прежняя ошибка).** — НЕ выполнено (Finding High).
- [x] `summarize_video.description` требует выжимку / `transcribe_video.description` — дословный сырой текст; обе EN; тест `test_definitions_distinguishable`.
- [x] Счётчик-комментарий приведён к фактическому (зарегистрировано 9, канон 10); техдолг I2 закрыт.

## Инварианты

- [x] **Δ DDL = 0** — ни одного файла миграций/`database.py` в диффе.
- [x] **Δ каталога = 0** — `NATIVE_MEDIA_TOOLS_ENABLED` отсутствует в `services/param_catalog.py`.
- [x] **egress** — `SEND_POINTS`/`SEND_ALLOWLIST` не менялись; новых send-точек нет.
- [x] **R16** — API аддитивен (`native_media`, `transcriber` — keyword-поля).
- [x] **R17** — probe-лог R17-safe; BUT см. Finding Low про `exc_info=True` в `native_media`.
- [x] **R18** — `current_task.md` не в коммите.
- [x] **`parse_mode=None`** — новый код отправляет plain-текст; форматирование не менялось.
- [x] **physical-two-call** — не затронуто.
- [x] **imported-history-immutable** — `smart_messages`/FTS/vec/JSONL не мутируются.
- [x] **Порядок роутеров `bot.py`** — без сдвига.
- [x] F1/F2/F7/F8/F9/F12/F13/F17/F20/F21/F22 — полный pytest 7698/0, регрессов нет.

## Тесты

- [x] native-first (своё видео + caption-URL, реплай-видео + caption-URL).
- [x] PDF-документ (своё сообщение и реплай) → «нет ссылки».
- [x] optional `url`/`source`, отсутствие `mode`, определения двух инструментов.
- [x] `native_media` делегирование из youtube, `document_is_video` для PDF.
- [x] probe-fail: маппинг пула + caplog без URL.
- [x] аддитивность `ToolDeps.transcriber`/`ToolContext.native_media`.
- [ ] **Флаг OFF для `tool_router`** — теста нет (следствие Finding High).
- [ ] **Публикационный путь native summarize (`media_share`)** — теста нет (Finding Medium).
- [ ] **R17 caplog нативного пути** — теста нет (Finding Medium).
- [x] Тесты не тавтологичны: используют реальный `video_download_handler`/`ToolRouter.dispatch`, фейковый bot, проверяют отсутствие вызова URL-ветки (`probe.assert_not_awaited`).

## Полный прогон

- `.venv/Scripts/python.exe -m pytest -q` → **7698 passed, 1 warning in 124.80s** (warning — deprecation starlette, не наш).
- `git diff --check 047481c^ 047481c` → чисто.

---

## Точный список требуемых исправлений

1. **`services/tool_router.py`**: гейтить нативный резолв флагом `NATIVE_MEDIA_TOOLS_ENABLED` (эмиссию `ctx.native_media` можно оставить — гейт в `_resolve_tool_source`), при OFF возвращать прежние ошибки (`summarize_video` → `"ОШИБКА summarize_video: некорректная ссылка"`, `download_media` → `_download_status("error", "Некорректная ссылка")`), нативный fetch/STT не запускать. + тест на OFF.
2. **`tests/…round1024.py`**: тест публикационной ветки native summarize (`media_share.publish_media_file` → `summarize_media_url` → `delete_file` в `finally`); тест `VideoLevelError` → STT-фолбэк с гарантированным удалением.
3. **`tests/…round1024.py`**: caplog-тесты R17 для нативного пути (`download_media`/`summarize_video`) — нет `file_id`/tmp-путей/`abs_url`.
4. **`services/tool_router.py`**: убрать `_NATIVE_STT_TIMEOUT=120.0`, читать `limits.video_stt_timeout_seconds` (паритет youtube).
5. **`services/native_media.py` / `handlers/youtube.py`**: либо восстановить точную семантику `_resolve_video_media`, либо явно зафиксировать в ADR-1024-15 §2.3 осознанное изменение (`_has_file_id`, per-candidate catch) + тест-паритет.
6. **`handlers/youtube.py` / `handlers/video_download.py`**: удалить мёртвые алиасы `_VIDEO_DOC_EXTENSIONS`/`_document_is_video` (или обосновать их нужность тестами).
7. **`services/tool_router.py`**: определить и задокументировать приоритет `source` vs `url` + тест на противоречивый ввод.
8. **`services/native_media.py`**: убрать `exc_info=True` из warning (R17).
9. **`tasks.md`/ADR**: зафиксировать, что эмиссия `ToolContext.native_media` (T-2295) фактически влита F14, а не F13.

**Верни исправленную версию. Текущий код отклонён.**

---

# Итерация 2 — повторный аудит (коммит `744ae4f`)

> Родитель коммита — `c06c457` (F16). Правки F14 итерации 1 выделены диффом `git diff c06c457 744ae4f`; изменения F16 (`c06c457`) к F14 **не приписаны**.
> Diff-скоуп итерации 1: `handlers/video_download.py`, `handlers/youtube.py`, `services/direct_chat_service.py`, `services/native_media.py`, `services/tool_router.py`, `tests/test_native_media_tools_round1024.py` (274 insertions / 23 deletions).

## Итоговый статус итерации 2

**Approved** — High/Medium закрыты, Low закрыты (кроме не-блокирующей doc-drift, см. «Остаточные замечания»).

## Проверка исправлений

### [High] Kill-switch `NATIVE_MEDIA_TOOLS_ENABLED` в `tool_router` — ЗАКРЫТО
- `services/tool_router.py:154–160` добавлен `_native_tools_enabled()` — единая точка чтения флага.
- `_resolve_tool_source` (:873–900) гейтит **оба** нативных выхода: ветку `source=="reply"` и ветку «url не-http + ctx.native_media»; при OFF возвращает `(None,None,None)`.
- `_summarize_video` (:763–771): при `source is None` и OFF отдаёт **прежнюю** строку `"ОШИБКА summarize_video: некорректная ссылка"`; `download_media` отдаёт прежний `_download_status("error", "Некорректная ссылка")`.
- Тест `test_flag_off_native_calls_return_legacy_errors` проверяет: точные legacy-строки + `bot.download.await_count == 0` + `send_video == 0` — т.е. нативный fetch реально не стартует. Не тавтологичен (реальный `dispatch`, подмена только settings-прокси).
- Вывод: при OFF native fetch/publish/STT недостижимы (единственные входы в `_video_native_summary`/`_download_native` — за `source=="native"`, который требует флага). План отката §10 «Флаг OFF» снова рабочий.

### [Medium 2] Публикационный путь native summarize — ЗАКРЫТО
`TestNativeSummarizePublish` покрывает три ветки:
- успех: `publish_media_file` → `summarize_media_url(video_url=ticket.abs_url)` → `delete_file(ticket.file_id)`; STT **не** задействован;
- `VideoLevelError` → STT-фолбэк выжимки, `delete_file` всё равно вызван (`finally`);
- `publish_media_file → None` → L1/L2 пропущена, STT-фолбэк, `summarize_media_url` не вызывался.
Проверяются ключевые риски утечки опубликованного файла и корректность kwargs. Не тавтологично.

### [Medium 3] R17 caplog нативного пути — ЗАКРЫТО
`TestNativePathR17` с `caplog.at_level(DEBUG)` на реальном `download_to_tmp` проверяет отсутствие `file_id`/tmp-префикса `nm_`/подписанного `abs_url`/хоста в логах `download_media` и `summarize_video`; положительный якорь `kind=video` подтверждает, что лог-строка реально эмитится (не «пустой» текст).

### [Medium 4] STT-таймаут из конфига — ЗАКРЫТО
`_NATIVE_STT_TIMEOUT` удалена; `_native_stt` (:858–870) читает `hot.get("limits.video_stt_timeout_seconds", settings.VIDEO_STT_TIMEOUT_SECONDS)` с fallback `or settings.VIDEO_STT_TIMEOUT_SECONDS` — паритет с `handlers/youtube.py:474–477`. Поле `Settings.VIDEO_STT_TIMEOUT_SECONDS` существует (`config/settings.py:1282`).

### [Low 5–9]
- **Low 5 (семантика):** `handlers/youtube._resolve_video_media` (:363–392) восстановлен до точной прежней семантики (без `_has_file_id`, без per-candidate catch); строгий `native_media.resolve_reply_video` оставлен для Fast-Track/эмиссии F13. Добавлен тест-паритет `test_youtube_resolver_tolerant_vs_strict_video_without_file_id`. Замечание: ADR §2.3/спека §4.1 в тексте не обновлены — см. «Остаточные».
- **Low 6 (мёртвые алиасы):** `_VIDEO_DOC_EXTENSIONS` удалён из `youtube.py` и `video_download.py`; `video_download._document_is_video` сохранён — он **реально используется** в `_reply_video_media` (OFF-путь, :196), т.е. не мёртвый; `youtube._document_is_video`/`_video_suffix`/`_VideoMedia` используются. ЗАКРЫТО.
- **Low 7 (`source` vs `url`):** `source=="reply"` теперь приоритетнее http-`url`; покрыто `test_source_reply_wins_over_http_url` и `test_source_reply_without_native_is_error`. ЗАКРЫТО.
- **Low 8 (`exc_info`):** `resolve_reply_video` переведён на `logger.debug` без `exc_info`, с `error=%s` (только класс). ЗАКРЫТО.
- **Low 9 (владение эмиссией):** зафиксировано комментарием в `direct_chat_service.py:750–755` (F13→F14, T-2295, F13-коммит эмиссию не отдал). Код-комментарий, не `tasks.md` — см. «Остаточные».

## Инварианты (итерация 2)

- [x] Δ DDL = 0 — дифф не трогает миграции/`database`.
- [x] Δ каталога = 0 — `NATIVE_MEDIA_TOOLS_ENABLED` отсутствует в `services/param_catalog.py`.
- [x] egress — `SEND_POINTS`/`SEND_ALLOWLIST` не затронуты.
- [x] R16 — поля `ToolContext.native_media`/`ToolDeps.transcriber` аддитивны.
- [x] R17 — probe-лог и нативный путь R17-safe (caplog-тесты); `exc_info` убран.
- [x] R18 — `current_task.md` не в коммите.
- [x] `parse_mode=None` — доставка не форматируется; правок нет.
- [x] `physical-two-call` — не затронуто.
- [x] `imported-history-immutable` — не затронуто.
- [x] Порядок роутеров `bot.py` — не менялся.
- [x] F1–F13/F16/F17/F20–F22 — полный pytest зелёный (изменения F16 `c06c457` не атрибутированы F14; конфликтов нет).
- [x] `git diff --check c06c457 744ae4f` — чисто.

## Тесты (итерация 2)

- Целевой файл: `tests/test_native_media_tools_round1024.py` — **26 passed**.
- Полный прогон: `.venv/Scripts/python.exe -m pytest -q` → **7741 passed, 1 warning in 97.68s** (warning — deprecation starlette, не наш). Совпадает с заявленным.
- Новые тесты не тавтологичны: исполняют реальные `ToolRouter.dispatch`/`video_download_handler`, реальный `native_media.download_to_tmp`, фейковые bot/media_share/transcriber; проверяют негативные исходы (`assert_not_awaited`), а не только happy-path.

## Остаточные (не блокирующие) замечания

1. **Doc-drift (Low):** спецификация §4.1/ADR §2.3 всё ещё формулируют «единый источник / семантика байт-в-байт» для `youtube._resolve_video_media`, тогда как фактически их два (толерантный youtube vs строгий `native_media.resolve_reply_video`). Код-комментарий ссылается на «ревизию ADR-15 §2.3», которой в ADR нет. Рекомендация: внести правку в ADR-1024-15 §2.3/§4.1 либо параметризовать резолвер (`require_file_id: bool`), убрав дубль квалификации. На функциональную безопасность не влияет.
2. **Kill-switch edge-case (Low):** при OFF ввод `{"url": <http>, "source": "reply"}` даёт ошибку (native-ветка гейтится и не откатывается на ссылку), тогда как «urls-first» формально подразумевал бы ссылочный путь. Схемы не гейтятся флагом, поэтому теоретически достижимо. Рекомендация: при OFF и `source=="reply"` с валидным http-`url` падать на `link`-ветку.
3. **Doc-drift (Low):** фиксация владения эмиссией сделана только комментарием; `tasks.md`/ADR не обновлены. Приемлемо для закрытия шага, но желательно отразить в `tasks.md`.

## Вердикт итерации 2

**Approved** @Orchestrator. High (kill-switch) и оба Medium закрыты реальными тестами; Low 5–9 закрыты (два doc-drift и один OFF-edge-case — не блокирующие рекомендации). Инварианты соблюдены, полный pytest 7741/0. Код прошёл ревью — можно двигаться дальше.
