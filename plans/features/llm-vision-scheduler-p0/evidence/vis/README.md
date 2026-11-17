# P0 Vision download — evidence (VIS / LVS-VIS-01..07)

**Кандидат (R2):** `a4bf7b4bd3341c1ddcdfe387527058a71b665cae` — правки F1/F2/F5 поверх ревьюированного `32af3fe6a3d419388cb6a4e1e922ad6cb3f5c27c`; ветка `fix/p0-vision-download`, база `ea9f760f` (2.58.214, deployed prod).
**Скоуп:** только Vision download-транспорт, классификация отказа, breaker, восстановление/доставка контекста. L1/модель, APScheduler, QRNG, UI — не тронуты. Новых reason-кодов/DDL/флагов каталога нет.
**MAP:** `plans/features/llm-vision-scheduler-p0/requirements-map.json` — `LVS-VIS-01..07` (строки VIS 9); owner input §2 (`plans/owner_inputs/2026-11-17-llm-vision-scheduler-p0.md`, `source_id` MAN-VIS-01..07).
**Статус:** BUILDING/REVIEW (не VERIFIED, не bump, не deploy).

## 1. Что изменено (контракт)

| Файл | Изменение |
|---|---|
| `services/media_download.py` | Новый ЕДИНЫЙ bytes-транспорт `download_api_file_bytes`: (1) локальный Bot API — `local_file_path` (относительный/контейнерный/host-абсолютный → host-корень) + bounded-retry на появление файла; (2) штатный транспорт aiogram `download_file` (cloud HTTP / local диск; для двойников и пустого `file_path` — прежний `bot.download`); (3) облачный fallback `api.telegram.org/file/bot<token>/<path>` (getFile + streaming GET) с env-рубильником `MEDIA_DOWNLOAD_CLOUD_FALLBACK` (default ON). **F5 (security):** оба облачных запроса идут с `follow_redirects=False` — токен в пути не уходит на адрес 302; 3xx → типизированный `provider_error` (`redirect_refused/http_<code>`), TLS-verify не ослабляется. Ошибки — `MediaDownloadError(stage, error_class, retryable)`; `read_local_path_bytes` — единая точка stat→размер→read для `read_host_file_bytes` и транспорта. R17: `safe_path_tail` вместо полного пути в WARNING `_read_local_source` (раньше контейнерный путь печатал `<bot_id>:<token>`). `fetch_media_to_tmp`/voice/video-потребители не изменены по поведению. |
| `services/mca_vision.py` | `download_telegram_file` делегирует в единый транспорт (свой `bot.get_file`+`bot.download` удалён). `process_asset_job`: `MediaDownloadError` → `download_reason_for(class)` (invalid_file_id→`vision_missing_source`, oversized→`vision_unreadable`, временные→retryable `vision_unavailable`); `VisionError` после download → стадия `validate` + класс (`oversized`/`unreadable_raster`/`unsupported_format`/`empty_image`); последний `except Exception` больше не «чёрная дыра» — класс по типу исключения + подстадия. `_finish_analysis_or_job`: `error_json={detail,class,stage}` + `attempt`/`job_id` в событии + `error_code` в `task_jobs` (терминал и retry). `_note_job_outcome`: успех → reset, `vision_unavailable`/`vision_rate_limited` → streak++, контентные исходы нейтральны; все инвертированные вызовы убраны. `runtime_snapshot.last_error` += `error_code`. |
| `services/task_supervisor.py` | `TaskJobStore.set_next_retry(..., error_code=None)` — класс временного отказа виден в очереди ещё до терминала (COALESCE; прочие вызовы не изменены). |

Стадии: событие остаётся на стадии `download` (реестр `mca_process_registry` не расширяется), точное место отказа — `error_json.stage` ∈ `{get_file, local_read, cloud_download}`; отказ валидации — существующая стадия `validate`. Чекап: `runtime_snapshot.last_error.reason_code` + `.error_code`.

## 2. RED на базе `ea9f760f` (до изменений)

`red_probe_ea9f760f.py` (в этой папке; `PYTHONPATH=<worktree> python red_probe_ea9f760f.py`, вывод — факты):

```json
{
  "download": {"raised": "FileNotFoundError", "is_classified": false, "stage": null, "message": "photos/gone.png"},
  "breaker_before": 0,
  "retry_event": {"outcome": "skipped", "reason_code": "vision_unavailable", "error_json": null, "has_job_id": false, "has_attempt": false},
  "queue_retry": {"status": "queued", "reason_code": "vision_unavailable", "error_code": null},
  "breaker_after_failure": 0,
  "terminal_event": {"outcome": "failed", "reason_code": "vision_unavailable", "error_json": null},
  "queue_terminal": {"status": "failed", "reason_code": "vision_unavailable", "error_code": null},
  "checkup_last_error": {"reason_code": "vision_unavailable", "updated_at": 1794917043},
  "analyses": 0,
  "has_media_download_error": false,
  "has_bytes_helper": false
}
```

Подтверждает три дефекта брифа: (1) отсутствующий локальный файл даёт НЕклассифицированный `FileNotFoundError` (generic, без stage/class); (2) `error_json` пуст в retry и terminal, `error_code` пуст, чекап без класса; (3) ошибка скачивания НЕ увеличивает breaker streak (0→0; `_note_breaker(True)`). Плюс на базе нет `MediaDownloadError`/`download_api_file_bytes`.
Тот же файл тестов на базе (`ea9f760f`, отдельный detached-worktree + копия файла): **28/28 errors** (фикстура/символы отсутствуют). На ревьюированном варианте файла (27 тестов) — **27/27 errors**; ранее записанный счётчик «26» был ошибкой (F1 исправлен, перепроверено прогоном).

## 3. GREEN на кандидате (фактические цифры)

Команда (cwd = worktree, `ADMINBOT_SKIP_DOTENV=1`, venv `C:\Code\Python\adminbot\.venv`):

- `pytest tests/test_p0_vision_download_transport.py` → **28 passed** (в т.ч. redirect-тест F5).
- Фокусный свод: `test_p0_vision_download_transport + test_p0_vision_fix_core + test_media_download + test_vision_dl_fix + test_mca19_block_b + test_postgen_diag` → **189 passed, 1 skipped**.
- Vision/media/telemetry/supervisor: `test_evol011_vision_telemetry, test_evol013_reason_quality, test_evol019_vision_recognition, test_evol_vision_sync_core, test_evol_vision_sync_wave2, test_vision_adapt, test_vision_dl_fix, test_media_download, test_media_local_path_round1025, test_mca01_tx_task_supervisor` → **159 passed, 38 skipped, 1 failed** — `test_write_points_go_through_single_writer` (воспроизводится на базе: stale audit-snapshot).
- MCA-19/17a: `block_a/c/d/e/f/g + rework_r1 + mca17a_observability` → **154 passed, 1 failed** — `test_js_mirrors_mod_vision` (воспроизводится на базе: в `ea9f760f:web/app.js` нет `toggleKey: 'flags.vision_enabled'`).
- Пайплайн/админ: `test_addtr_postgen, test_asap5_image_admin, test_p0_vision_ui_e2e, test_postgen_diag` → **87 passed, 1 skipped, 7 errors** — UI-e2e harness (Playwright) требует `data-vision-facts`/`data-conn-configure`, которых нет в `ea9f760f:web/app.js` (0 вхождений) — pre-existing, UI не тронут.
- `test_asap5_integration_w3.py` → **67 passed** (первый совместный прогон дал 1 flake `TestNostalgiaProvenance::test_d14_active_conversation_scenario_a`; изолированно и полным файлом — green; на базе также green).
- Медиа/voice/video/avatar-потребители: `test_avatars_round1017/1019, test_media_integrity_round1019, test_media_transcribe_tool_round1024, test_video_download, test_voice_transcription, test_youtube_multimodal_download_round1024, test_youtube_video_media, test_native_media_tools_round1024, test_native_reply_media_context_round1024, test_media_download, test_media_local_path_round1025, test_vision_dl_fix` → **329 passed, 18 errors** — все 18 в `test_youtube_multimodal_download_round1024::fm_env` (фикстура ждёт `handlers.youtube.get_smart_cache`; в `ea9f760f:handlers/youtube.py` его нет — pre-existing stale test).
- Job lifecycle/heartbeat/watchdogs: `test_media_execution_asap32, test_mca01_tx_task_supervisor, test_smart_corrective_watchdog_events/lifecycle/observability, test_asap8_v6_c06a_heartbeat` → **102 passed, 1 failed** (тот же pre-existing write-points).
- `git diff --check` clean; `py_compile` трёх изменённых модулей и теста — OK.

## 4. Мутации (каждая убивает целевой тест; после мутации код восстановлен, GREEN повторён)

| Мутация | Результат |
|---|---|
| M1 — вернуть `bot.get_file`+`bot.download` в `download_telegram_file` (bypass транспорта) | **9 failed / 18 passed** (`test_vision_module_has_no_download_bypass`, классы/облако/альбом/downstream/повтор/breaker) |
| M2 — `_note_job_outcome(None)` на ошибке скачивания | **1 failed** (`test_download_failure_counts_breaker`: streak 0 вместо 1) |
| M3 — свернуть `error_json` (`payload_json=None`) | **3 failed** (класс в событии download/terminal/validate) |
| M4 — не писать `error_code` в очередь | **1 failed** (`test_download_failure_class_reaches_event_queue_and_checkup`) |
| M5 — вернуть `follow_redirects=True` в облачном GET файла (F5) | **1 failed** (`test_cloud_redirect_not_followed_token_never_leaves`: 302 выполняется, байты чужого хоста; «DID NOT RAISE») |
| M6 — вернуть `follow_redirects=True` в облачном getFile (F5, вторая ступень) | **1 failed** (тот же тест: `redirect_refused` отсутствует / лишний запрос на чужой хост) |

## 5. Покрытая матрица LVS-VIS-07

Локальный относительный путь; контейнерный `/var/lib/telegram-bot-api/<token>/…`; host-абсолютный внутри корня; отсутствие файла → облако; отсутствие файла + облако OFF → `missing_local_file`; `get_file` invalid → `invalid_file_id` (permanent, cloud не вызывается); timeout; permission denied; пустой file_id; oversized (local и cloud); cloud network; облачный 302 → redirect НЕ выполняется, типизированный `provider_error`/`redirect_refused`, токен не уходит на чужой хост (F5); `validate` unreadable → стадия `validate`; альбом из 2 снимков (2 анализа); повтор джобы (1 анализ, 1 вызов провайдера); downstream-контекст без нового вызова; breaker (открытие/пауза pull/успешный cloud fallback после паузы); R17-логи (нет токена/каталога токена/URL/байтов).

## 6. Ограничения и что проверить после деплоя (DevOps; live-прогон 9 asset + backfill)

1. **Локальный Bot API на проде не материализует файлы с 11-16 15:11** — кодом не лечится. Кандидат делает отказ видимым (`missing_local_file`, `get_file_failed`/`timeout`/`network`) и добавляет облачный fallback, который ВОССТАНАВЛИВАЕТ анализ при живом `api.telegram.org`.
2. **Приватность/политика**: облачный fallback отправляет файл на `api.telegram.org` только когда локальный файл недоступен; в облачном режиме он не используется; рубильник `MEDIA_DOWNLOAD_CLOUD_FALLBACK=0` оставляет строго локальный путь (тогда отказ честно классифицируется как `missing_local_file`). Решение о постоянном значении — за владельцем/архитектором.
3. Проверить effective env в unit: `MEDIA_DOWNLOAD_CLOUD_FALLBACK` (ожидается unset/1), `DOWNLOAD_ENABLED`, `TELEGRAM_API_FILES_DIR`, token-каталог; после рестарта — healthz/version/identity/schema.
4. Ре-драйв 9 asset (recon §4: `08898876…8c98`, `86cc901e…2fe`, `37bef817…3e4`, `6df01f88…814`, `3758bc84…9a5`, `e471f16e…047`, `3c670dd4…ea4`, `6aa46816…d90`, `eed4777c…39a`): старше `BACKFILL_MIN_AGE_SECONDS=3600` → следующий `backfill_sweep` поставит `vision:bf:*`; ожидаем `mca_media_analyses.status=ready` и `task_jobs.status=completed` (или честный класс вместо пустого `error_json`).
5. Проверить `vision_media` события: упавшие download-события обязаны иметь `error_json.class/stage`; при срабатывании fallback в journal — WARNING `cloud fallback used` (R17-safe, без URL).
6. Проверить чекап (`runtime_snapshot.last_error.error_code`) и `python manage.py disk audit` + `disk cleanup --apply` (правило P0-PROD-DISK-01).
7. Не проверено в этом increment: реальный сетевой вызов `api.telegram.org` из прод-сети (юнит-путь инъекцирован), фактическая материализация файлов локальным Bot API после рестарта, поведение провайдера Vision после успешного download (route не менялся), backfill-re-arm live (юнит-покрытие: существующий `test_fix2_backfill_rearms_transient_terminal_job` + маппинг классов).

## 7. Очистка

Временные артефакты прогонов — в `%TEMP%\opencode\p0-vision-red` (удалены); в репозиторий добавлены только код, тест и этот evidence + `red_probe_ea9f760f.py`. Detached-worktree базового прогона (`p0-vision-red-base-ea9f760f`) удалён через `git worktree remove` (не force); копия тест-файла в нём удалена. Production не затрагивался, live-вызовов не было.

## 8. R2-правки по ревью (F1/F2/F5) и backlog

- **F1 (evidence):** счётчик базового прогона исправлен и перепроверен: финальный файл (28 тестов) на `ea9f760f` → **28/28 errors**; ревьюированный вариант (27 тестов) → **27/27 errors**; прежнее «26» — ошибка счёта.
- **F2 (docs):** модульный docstring `mca_vision.py` и docstring `download_telegram_file` переформулированы по факту: токен-URL строится ТОЛЬКО в облачном fallback `media_download` (фиксированный хост `api.telegram.org`, redirect не выполняется, TLS-verify не ослабляется); URL/токен не логируются, не отдаются наружу, не передаются модели и не попадают в события (TH-3). Обещаний сверх факта нет.
- **F5 (security hardening, включено):** `follow_redirects=False` в обоих облачных запросах (getFile и файл); 3xx → `provider_error` + `detail=redirect_refused/http_<code>`, `retryable=False`; TLS-verify не ослабляется. Тест `test_cloud_redirect_not_followed_token_never_leaves` (реальный `httpx.AsyncClient`, только HTTP-граница через `MockTransport`): обработчик вызван ровно один раз и только на `api.telegram.org`, `evil.example` не запрашивается, токен отсутствует в тексте ошибки, `follow_redirects is False`, `verify` не False. Мутации M5/M6 убивают тест.
- **Backlog (не делано в этом increment, код не менялся):**
  - **F3** — `pipeline_stage_event("download","started")` против контракта `outcome="start"`: остаётся как есть (существующий контракт стадий).
  - **F4** — унификация avatars на общий bytes-транспорт: вне scope (avatars имеют свой fallback `read_host_file_bytes` → `bot.download`).
  - **F6** — `TelegramRetryAfter` как отдельный класс/уважение `retry_after`: не добавлялось (класс `provider_error`/bounded retry).
  - **F7** — oversized до/после normalize-JPEG: порядок не менялся (oversize определяется до нормализации; rescue-путь `validate_or_normalize` прежний).
  - **F8** — per-call semaphore vs общий на процесс: не менялось.

Итоговый candidate для повторного ревью — `a4bf7b4bd3341c1ddcdfe387527058a71b665cae` (код+тесты R2); tip ветки — коммит с этим README.
