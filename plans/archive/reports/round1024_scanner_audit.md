# Scanner Audit — Round 10.24 «Disaster Recovery: UI & Backend Bloat» (UPD2–UPD6)

- **Дата:** 20.09.2026, Шаг 6, @Scanner (независимый сквозной аудит).
- **Baseline:** `00eab85` (HEAD раунда 10.23). **Текущий HEAD:** `379cfdd`
  (`test(tests): раунд 10.24 F23 — guardrails бюджетов ...`).
- **Объём диффа:** 132 файла, +18 264 / −1 016 строк. Фичи F1–F24 (имена — по ТЗ).
- **Метод:** git-diff по baseline, выборочное чтение изменённых/критичных файлов,
  сквозные прогоны инвариантов, обязательный греп секретов, полный `pytest -q`.
- **Вердикт:** **Critical 0 / High 0 / Medium 0 / Low 3 (open) / Info 5.**
  Блокеров Merge/деплоя нет.

---

## 1. Findings по severity

### Critical — нет

### High — нет

### Medium — нет

### Low

**L10.24-1 — F19: тристейт форс-повтора может «проглотить» причину (тихий пропуск ответа).**
Файл: `handlers/voice_transcription.py::force_repeat_from_reply` (≈370–400) +
`handlers/youtube.py::_handle_voice_command` (≈405–430).
`transcribe_media_message(...)` возвращает `False` не только после отправки фразы
деградации (too-long / empty / all-failed), но и **до** любой отправки — при
`from_user is None` или `user.id == _bot_id` (ранний `return False`). В этом случае
`force_repeat_from_reply` отдаёт `FORCE_REPEAT_HANDLED`, а вызывающий не шлёт
нейтральный ответ (он шлёт его только при `NO_TARGET`) → пользователь получает
**тишину** (ответ на сообщение бота-автора/анонимный пост).
Тристейт корректно различает «деградация уже озвучена» и «цели нет», но не различает
«ранний return без ответа». Практическая частота низкая (реплай именно на ГС/кружок
самого бота), поэтому Low. Минимальный фикс: ввести отдельный исход для «цель была,
но обработка не началась» (или выносить ранние проверки до отправки и возвращать
`NO_TARGET`).

**L10.24-2 — F14: `_DOWNLOAD_NATIVE_MAX_BYTES` заявлен как «лимит Telegram», но
2 ГБ — это лимит **локального** Bot API server.**
Файл: `services/tool_router.py:112`, использование `:1140`.
Для облачного Bot API исходящий лимит бота ~50 МБ, поэтому нативный ресайз файла
размером 50 МБ…2 ГБ пройдёт локальный гейт и упадёт на `send_media`, вернув
обобщённое «Не удалось переслать видео» вместо честного «файл больше лимита».
Смысл гейта (раннее отсечение) не достигается для облачного режима. Low: поведение
безопасно (ошибка ловится), но сообщение о причине неточное.

**L10.24-3 — F12/F2: тело ошибочного ответа при скачивании изображения логируется
без `_redact_secret`.**
Файл: `services/image_generation.py::_download_bytes` (`:441–445`) и
`_generate_get` (`:478–482`): `body=getattr(resp, "text", "")` передаётся в
`log_external_api`, где применяется только `safe_text` (маскирование известных
префиксов/секретов из env). URL изображения выдаётся провайдером и может содержать
подписанный токен в path/query; при ошибочном ответе 4xx/5xx токен может вернуться
в теле и попасть в лог. Сам URL в лог уже не идёт (`safe_url` — только host),
поэтому риск ограничен телом. Low, hardening R17 (обернуть `body` в `_redact_secret`
там, где известен ключ — как уже сделано в POST-ветке).

### Info

**I10.24-1 — F13: медиа-маркер может превысить `cap` при экстремально малом лимите.**
`services/direct_chat_service.py::_build_current_question` (≈1240–1275): при
`room == 0` (`cap` меньше длины суффикса) `body = suffix`, т.е. итог не режется до
`limits.chat_current_question_max_chars`. Дефолт cap 800 при маркере ~15–30 символов —
практического риска нет; инвариант «cap» формально размыт.

**I10.24-2 — F1: неточное сообщение `GraphExtractionError`.**
`services/summary_memory.py:3508`: `all {len(chunks)} chunk(s) failed` может не
соответствовать факту (часть чанков ответила, но без триплетов) — влияет только на
текст исключения/метрики, не на логику.

**I10.24-3 — F4: N+1-резолв в GLOBAL `dossier_feed`.**
`web/api/oversight.py::_feed_user_index` строит `AliasResolver` отдельно на каждый
различный `chat_id` в выдаче (≤ `limit` = 40). Read-path админа, нагрузка мала́;
при росте лимита стоит кэшировать.

**I10.24-4 — F16: полное скачивание видео на каждый youtube+summary (cache-miss).**
`handlers/youtube.py::_process_youtube_summary` (≈1157–1189): при включённых
`YOUTUBE_MULTIMODAL_DOWNLOAD_ENABLED` + `media_share.enabled()` + доступном
video-клиенте выполняется yt-dlp-загрузка до 240 с и публикация файла. Осознанное
решение ADR-1024-17; tmp удаляется в `finally`, при жёстком падении процесса
возможен остаток tmp (pre-existing паттерн).

**I10.24-5 — F19: `bot.send_message` вне обёрток `services/telegram_send`.**
`handlers/voice_transcription.py::_reply_media` (≈216–232) для случая
`reply_to_id != media_message.message_id` зовёт `bot.send_message` напрямую.
`handlers/voice_transcription.py` уже в `SEND_ALLOWLIST` (обоснование: UX-фразы +
ASR-транскрипт, `html.escape`), поэтому статический egress-guard не нарушен; это
review-accepted Low из отчёта F19, беру как Info.

---

## 2. Подтверждённые инварианты

| Инвариант | Статус | Доказательство |
|---|---|---|
| `physical-two-call` | ✅ цел | F1 добавил `LLMClient.generate_background(...)` как отдельный канал; общий `_post` получил `budget`/`max_retries` с дефолтом `None` (байт-в-байт прежним вызовам). System-2 direct/summary по-прежнему 2 вызова (`test_direct_two_call_round1022`, `test_summary_two_call_round1022` — зелёные). |
| `validator-loop` без regex-реза клише | ✅ цел | `services/negative_constraints.py` в раунде не менялся (нет в диффе); `channel_enabled_rules` используется без `forbid_bullets` в direct/factcheck → смена `normalize_response_mode` («» вместо «serious») правила не меняет. |
| egress-реестр | ✅ цел | Новых точек отправки нет; F19 добавлен в уже allowlisted `handlers/voice_transcription.py`; `services/telegram_send.py` SEND_POINTS/ALLOWLIST в диффе не менялись. |
| `imported-history-immutable` | ✅ цел (жёстко) | `services/disk_retention.py`: `IMMUTABLE_PATTERNS` + `HISTORY_DENY_NAME_MARKERS` + content-sniff (fail-closed на `OSError`) + повторная классификация в `apply_cleanup` (блок `immutable`) + `HISTORY_JSONL_IMMUTABLE=false` игнорируется с WARNING. `services/memory_maintenance.py` фиксирует `IMMUTABLE_ARCHIVE_GLOB`. |
| `manual-overrides-immutable` | ✅ цел | F20: `post_config` читает матрицу прав из `perm_overrides`, а базу merge значений — из `overrides`; `set_chat_params` заменяет только `overrides`+`meta`, `perm_overrides`/`gates`/`keys` сохраняются (`services/chat_params.py:330-333`). DELETE-параметр и сид (`chat_settings_seed`) тоже merge-ят. |
| R16 | ✅ | `GET /api/me` → аддитивные `is_global_admin`/`ui_flags` (только bool); `budget_snapshot.budgets_enabled`; `dossier_feed.user_id/user_name`; `deep-sleep.paradigms_status/reason`. |
| R17 | ✅ | Маски `{configured,last4}`; `mask_key_info`; `_redact_secret` для image-ключа; `log_external_api`/`trace_step` — `safe_text`+`redact_url`, только коды причин. Единственная нестыковка — L10.24-3 (тело загрузки изображения). |
| R18 | ✅ | Секретов в диффе/трекаемых файлах нет (см. §3); новые секреты — только `.env`, UI-глобальный ключ пишется в глобальный слой с маской. |
| `parse_mode=None` | ✅ | F19: фразы деградации — plain; HTML-курсив только для успешного транскрипта (`html.escape` присутствует). |
| Порядок роутеров `bot.py` | ✅ цел | В `bot.py` только DI-kwarg `transcriber=voice_service` в `ToolDeps`; новых `include_router`/сдвигов нет. |
| Канон инструментов = 10 | ✅ | `TOOL_CALLING_TOOLS` = 10, первые 9 — прежний порядок байт-в-байт, 10-й `transcribe_video` в хвост; `active_tools` гейтит его env-only `MEDIA_TRANSCRIBE_TOOL_ENABLED`. Канон `plans/docs/canon/architecture.md` и `plans/ARCHITECTURE.md` синхронизированы. |
| `param_catalog` ↔ UI | ✅ | F5 перенёс `flags_module_images` из `mod_direct` в новую `mod_images` (группа ровно на одной вкладке); F21 добавил `flags_module_budgets` на существующую `mod_budgets`; F7 — `limits_anticliche` на `prompts`. Все pg-ключи (`flags.budgets_enabled`, `flags.image_generation_module_enabled`, `limits.anticliche_max_patterns`) присутствуют в каталоге; `toggleKey` в `web/app.js` ссылаются на них. Потерь функциональности при наложении не выявлено. |

## 3. Безопасность

- **Секреты (обязательный греп):** по диффу `00eab85..HEAD` и трекаемым файлам
  найдены только синтетические плейсхолдеры в тестах (`gsk_XYZ789000000`,
  `ghp_01234567890123456789`), реальных ключей/паролей/SSH-приватников нет.
  `.env`/`*.db`/`*.jsonl`/`media/` в дифф не добавлены; `.env.example` содержит
  только имя флага. `git diff --check` — exit 0.
- **RBAC новых/изменённых эндпоинтов:**
  - `POST /api/images/test` — `Depends(requires_global_admin())` + in-memory
    rate-limit 10 с.
  - `/api/config/keys/own` (GET/PUT/DELETE) — при отсутствии `X-Chat-Id`
    global-ветка требует `is_global_admin` (через `roles.access_for`) + allowlist
    `is_global_secret` + `cache.pg_available`; ответ — маска.
  - `/api/anticliche*` — `_require_global_admin` (не менялось).
  - `/api/me` — `get_tma_user`, наружу только свои роль/права и bool-флаги.
  - `/api/info/guide*` — `get_tma_user`/`edit_info` (не менялось).
  - `dossier_feed` — `requires_global_admin`.
- **XSS:** новые/изменённые `v-html`-точки (`web/index.html:3043,3056,3080,3098`)
  проходят через `sanitizeHtml`/`sanitizedInfoHtml`; новых несанитизированных
  `v-html`/`innerHTML` в диффе нет.
- **SQL:** новые запросы CLI/аудита — только SELECT с параметрами (`$1`/`?`);
  пользовательских конкатенаций в SQL не добавлено.

## 4. Критическое (F20) и согласованность F21/F22

- **F20 подтверждён:** два независимых namespace. `perm_overrides` → только
  `effective_matrix`; `value_overrides = root["overrides"]` → база merge. Одиночный
  save больше не стирает остальные per-chat overrides. `set_chat_params` пишет только
  `overrides`+`meta`.
- **F21 подтверждён:** `services/budget_gate.budgets_enabled()` — единая точка
  (chat → global → default ON, fail-open ON). Гейтит direct (`chat_usage`), фон
  (`worker_budget.global_degradation_allows`/`consume`) и усечение контекста
  (`direct_chat_service`). Учёт статистики при OFF сохраняется (UPSERT выполняется до
  проверки гейта в `consume`; snapshot читает usage всегда).
- **F22 подтверждён:** `apply-chat-overrides` merge-ит `current + patch` и не пишет
  `perm_overrides`; `audit-chat-overrides` — READ-ONLY (только SELECT), R17-safe,
  fail-loud на нечитаемом сиде, `--strict` даёт non-zero при дрейфе.
- **F23:** только новые тесты-гейты (`tests/test_budget_guardrails_round1024.py`),
  прод-код не менялся.

## 5. DDL / миграции

- **SQLite:** версия схемы **v12** не тронута (в диффе нет новых `_SCHEMA_VERSION_*`;
  `services/database.py` менялся только сигнатурой `upsert_node(..., commit=True)`).
  «Δ DDL = 0» подтверждено.
- **PG:** новых таблиц/колонок в этом раунде нет (`services/pg_db.py` отсутствует в
  диффе). F9/F11/F21/F22 используют существующие таблицы (`chat_lore_history`,
  `bot_settings`, `chat_params`), т.е. идемпотентность DDL не затрагивалась.
- **Канон-миграции:** `PROMPT_MIGRATIONS`/PREV-слепки в раунде не менялись
  (промпты F6 изменяют только `prompts.verbilizer_default_mode` — значение ключа).

## 6. Тесты

- **Фактический полный прогон:** `.venv/Scripts/python.exe -m pytest -q` →
  **7911 passed, 1 warning in 103.71s** (0 failed). Заявленное число (~7911)
  совпадает. Warning — внешний (`StarletteDeprecationWarning` про httpx2), не наш.
- Подгонки эталонов не обнаружено: изменённые маркерные тесты соответствуют
  фактическим сдвигам (GROUPS 98, канон инструментов 9→10, дефолт режима
  `serious`→`casual`), JS-тесты раунда добавлены по фичам
  (`tests/js/round1024_*`).
- Критичные пути покрыты: F20 merge (`test_budget_overrides_merge_round1024.py`),
  F21/F23 (`test_budget_global_toggle_round1024.py`, `test_budget_guardrails_round1024.py`),
  F9 immutable/fail-closed (`test_disk_retention_round1024.py`), F11 RBAC/kill-switch
  (`test_byok_image_key_round1024.py`), F19 (`test_media_transcribe_tool_round1024.py`).

---

## 7. Итог для @Orchestrator

- **Critical 0 / High 0 / Medium 0 / Low 3 (open) / Info 5.**
- Открытые Low — не блокеры: L10.24-1 (тихий пропуск ответа в F19-тристейте),
  L10.24-2 (неточный лимит 2 ГБ для нативного ресайза), L10.24-3 (тело ошибочного
  ответа image-download без явного `_redact_secret`).
- Меняющиеся данные/инварианты целы: каталог (GROUPS 98; +1 limits, +1 flags, перенос
  `flags_module_images`), SQLite v12 (Δ=0), PG (Δ=0), tool-канон = 10, порядок
  роутеров, egress, `parse_mode=None`.
- Полный pytest: **7911 passed / 0 failed**.
- **Вердикт: раунд 10.24 можно передавать в Merge/деплой.** Обязательных возвратов
  @Builder нет; Low-находки — к решению владельца/tech-debt.
