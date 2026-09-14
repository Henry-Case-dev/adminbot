# Step 6 — SCANNER AUDIT раунда 10.16 (diff-аудит F1–F5, независимый от @Reviewer)

> **Сканер:** @Scanner (фоновый аудитор логических ошибок). **Дата:** 14.09.2026.
> **Baseline:** HEAD `18a9aa1`. **Объём:** незакоммиченный `git diff` (54 файла) + untracked
> (5 фич `plans/features/*-round1016/`, 3 отчёта, `tailwind.config.js`, 10 новых test-файлов,
> `tests/js/vue_mount_test.js`, `web/static/app.css` + `telegram-init.js` + `web/static/vendor/*`).
> **Метод:** построчный аудит диффа/untracked с `file:line`; независимое воспроизведение кейсов
> через `.venv/Scripts/python.exe`; полный pytest + JS-гейты. **Код НЕ правился.**

## 0. Валидатор (независимый прогон)

| Команда | Результат | Exit |
|---|---|---|
| `.venv/Scripts/python.exe -m pytest -q` | **5931 passed, 0 failed**, 1 warning (`StarletteDeprecationWarning` — не наш код), 69.3 c | 0 |
| `node --check web/app.js` | OK | 0 |
| `node tests/js/routing_test.js` | `JS-UNIT-OK` | 0 |
| `node tests/js/vue_mount_test.js` | `VUE-MOUNT-OK` | 0 |
| `git diff --check` | чисто (только штатные LF→CRLF) | — |
| `git status --porcelain media/ .env` | пусто | 0 |

Целевые новые файлы (`test_download_round1016`, `test_guide_delivery_round1016`,
`test_smoke_round1016_*` ×7) — **134 passed / 0 failed**.

## 1. Findings

| ID | Severity | File:line | Описание | Рекомендация |
|---|---|---|---|---|
| **S10.16-1** | **High** | `handlers/youtube.py:695-703` (лог-сайты); raise-сайты `tools/video_downloader.py:405-408,424-426,451-453,569-573,583-586,597-608,624-625,705` | **R17-нарушение: `str(exc)` c URL логируется на youtube-пути пересказа ссылки.** `_download_or_phrase` для `DownloadTooBigError` (`:696-697`) и `DownloadError` (`:702-703`) пишет в лог сам `exc`, а сообщения этих исключений до сих пор вкладывают `| url={url}` (signed/CDN-ссылки с query-токенами). Воспроизведено: `str(DownloadError('… | url=https://cdn.example.com/v?token=TOPSECRET'))` → `…url=https://cdn.example.com/v?token=TOPSECRET`. Это противоречит F1 §3 («в лог — только `error=<Class> reason=<reason>`, никогда `str(exc)`») и заявлению Reviewer-итерации 2 (residual #2: «ни один лог-сайт его не печатает»). Строки не менялись в диффе (pre-existing), но входят в заявленный скоуп «R17 на ВСЕХ сайтах»; caplog-тест `TestNoSecretsLogging` покрывает только `tools.video_downloader`. | Заменить оба лога на `error=%s reason=%s` (`type(exc).__name__`, `exc.reason`); в защиту в глубину — убрать `url={url}` и из текстов исключений (см. Info-1); добавить caplog-тест на `handlers/youtube.py`-путь. |
| **S10.16-2** | **Medium** | `services/config_cache.py:285-293` + `:300-312` | **F2: одноразовая форс-доставка канона затирает текущий ручной текст БЕЗ бэкапа `prev_html`.** Маркер `canon_delivered_version` защищает последующие правки (`save_text` его выставляет), но сама форс-доставка (`_write_info_canon`) перезаписывает неизвестный прод-текст текущим каноном и не сохраняет `prev_html`/`prev_updated_at` (в отличие от явного `InfoService.reset_canon`, `info_service.py:277-291`). Владелец разрешил перезапись, но текущая ручная правка теряется безвозвратно (только WARNING в логе). | В ветке `not delivered_done` сохранять прежний `html`/`updated_at` в `prev_html`/`prev_updated_at` (как в `reset_canon`) либо проводить форс-доставку через тот же write-хелпер с бэкапом. |
| **S10.16-3** | Low | `handlers/direct_chat.py:113-127`; `bot.py:745-761` | **R10.15-4: вторая половина гейта `download_available()` недостижима.** `bot.py` теперь ВСЕГДА вызывает `setup_video_download(...)`, поэтому `_downloader` не `None` и `download_available()` всегда `True`; условие «service available» — мёртвый defensive-код (не тестируемо). Функционального дефекта нет (hot-гейт в хендлере работает). | Либо убрать `download_available()` из гейта (оставить только hot-флаг), либо документировать как защиту от будущего условного DI. |
| **S10.16-4** | Low | `handlers/video_download.py:463` vs `:299` | **Bounded fallback жжёт кулдаун ПОСЛЕ полного успеха, а direct-ветка — ДО старта скачивания.** F1 spec §4.4 говорит «touch — только после успешного старта (как в direct-ветке)». Если fallback-скачивание удалось, но `_send_file` упал (Telegram), кулдаун не сжигается → пользователь может немедленно повторять тяжёлое скачивание. Глобальный лок/таймаут ограничивают риск. | Привести осемантике: `cooldown_touch` сразу после старта `download` (или явно зафиксировать расхождение в ADR). |
| **S10.16-5** | Low | `handlers/video_download.py:414` | Недостижимый маппинг `reason == "probe_unavailable"` в `_probe_error_phrase`: probe не эмитит такой токен (`probe_timeout`/`probe_bot_check`/`probe_failed`). | Удалить мёртвую ветку или добавить токен в probe-raise (если планировался). |
| **S10.16-6** | Low | `handlers/youtube.py:100` | `from tools.video_downloader import _is_platform_url` — импорт приватного символа через модульную границу; ломается при рефакторинге модуля. | Экспортировать публичный хелпер (`is_platform_url`) или инкапсулировать классификацию цели в `tools.video_downloader`. |
| **S10.16-7** | Low | `handlers/video_download.py:690-692` | `_handle_native_media` логирует `str(exc)` (R17-смежно: возможны локальные temp-пути/file_id). Не в диффе, но на пути «скачай <видео-сообщение>». | Логировать `type(exc).__name__` (по образцу обновлённых участков). |
| **S10.16-8** | Low | `web/app.js:1637-1638`; `web/app.py:56` (`img-src 'self' data: blob:`) | **F4: `me.photo_url` из initData — внешний Telegram-CDN**, а CSP `img-src` его запрещает → браузер пишет CSP-violation и блокирует первый запрос; аватар появляется только через `onMeAvatarError`-фолбек на blob-прокси. Функционально не ломается (fallback есть), но это лишний внешний запрос и шум в консоли при строгом CSP. | Либо сразу использовать blob-прокси `/api/avatar` (без CDN), либо добавить origin Telegram-CDN в `img-src`. |

### Info
- **Info-1 (hardening, residual @Reviewer #2):** raise-сайты `DownloadError`/`DownloadUnavailableError`/
  `DownloadTooBigError` по-прежнему вкладывают `url={url}` в `args` (`tools/video_downloader.py:405-408,424-426,
  451-453,569-573,583-586,597-608,624-625,705`). Лог-сайты в `tools/video_downloader.py`/`handlers/video_download.py`/
  `services/tool_router.py` его не печатают, но любой будущий `logger.*(..., exc)` или `exc_info` вернёт утечку.
  Рекомендация: убрать URL из текстов исключений (reason-код достаточно).
- **Info-2 (docs):** `plans/reports/round10.16_security_scan.md:133` сохраняет исторический счётчик `5910`
  (прогон до +21 теста итерации 1); мастер-эвиденс `round10.16_audit.md:12` = 5931 = фактический прогон.
- **Info-3:** репозиторий-wide авто-R17-тест отсутствует; «R17-скан» в F1 выполнен вручную scope-ограниченно
  (caplog только на `tools.video_downloader`), из-за чего youtube-путь (S10.16-1) не пойман.

## 2. Что подтверждено (по фичам)

- **F1 контракт:** `_normalize_quality` (`tools/video_downloader.py:778-799`) — `None/""/auto/best/max/direct` → `max`,
  `1080p/1080/1080` → `1080`, границы `144…4320`, мусор → `DownloadError(reason="invalid_quality")` БЕЗ сети;
  ветвление direct(URL)/YouTube/cobalt — до нормализации только для direct, нормализация до сети для платформ
  (`:363-372`). `quality="direct"` в прод-вызовах не передаётся (grep: только тест-align).
- **F1 probe-fallback:** одна bounded-попытка без меню, `_download_without_menu` (`:438-480`), probe-fail кулдаун
  не жжёт; классифицированные фразы `_fallback_phrases`/`_probe_error_phrase`; мёртвая direct-ветка удалена.
- **F1 env-preflight:** `download_env_summary` (`tools/video_downloader.py:187-204`) — только `set/absent`,
  единый `get_ytdlp_pot_provider()` (паритет с `build_ytdlp_base_opts`), однократный WARNING.
- **F2:** `canon_version=2`, `normalize_canon`, `KNOWN_INFO_SNAPSHOTS` (PREV), идемпотентность no-op, добор версии,
  миграция слепка, drift-preserve для ручных правок ПОСЛЕ доставки; `reset_canon` с `prev_html`+аудитом;
  PG-only `save_text` (файл `info_text.md` не пишется — `git status` файла пуст); RBAC `edit_info` на reset;
  `normalize_value` (type=`json`) сохраняет новые поля значения.
- **F3:** FIX-техдолг реален — S10.13-6b (`database.py:3761-3768`, NOT LIKE-фильтр), S10.13-13 (единый
  `parse_belief_meta` + делегаты), R10.15-4 (`bot.py` — только снятие startup-гейта, позиция 4e между
  `common_router` и `slavik_router` не сдвинута), R10.15-10 (`split_prefix_anywhere(url_before)`), R10.15-11
  (`_has_video_target`). Смоуки in-process, без сети/секретов.
- **F4:** external CDN в `web/` — 0 (`grep` чист); бандлы self-host с пинами (Vue 3.5.42, Chart.js 4.5.1,
  telegram-web-app.js, Tailwind prebuilt); inline `<style>`/`<script>` отсутствуют (404-совместимый маркер);
  CSP `script-src 'self' 'unsafe-eval'` (полная Vue-сборка использует `Function()`), `frame-ancestors` Telegram,
  `style-src 'unsafe-inline'`, CSP только на HTML; 105/105 baseline-селекторов в `app.css`; Tailwind покрывает
  используемые `md:`/`lg:`/arbitrary-утилиты.
- **F5:** `plans/current_task.md` не tracked (`.gitignore:70`), `.env` не tracked; новых секретов в untracked
  файлах фич не найдено; README ротации — в честной модальности «процедура (выполняется @DevOps)».

## 3. Инварианты (независимо подтверждены)

| Инвариант | Статус | Доказательство |
|---|---|---|
| R17 (секреты/URL в логах) | ❌ (partial) | новые лог-сайты F1 чисты, но `handlers/youtube.py:695-703` логирует `str(exc)` с `url=` — **S10.16-1 (High)**. Автотеста на этот путь нет |
| R16 (id — ключ) | ✅ | `updated_by=user.id` (`web/api/routes.py:1111,1137`, `handlers/info.py:173`); смоуки |
| Порядок роутеров `bot.py` | ✅ | `include_router` — 4e (`:756`) между `common_router` (`:730`) и `slavik_router` (`:765`); изменён только startup-гейт |
| `media/` и `.env` не тронуты | ✅ | `git status --porcelain media/ .env` — пусто |
| Каталог 435/406/411/90/88/19 (Δ=0) | ✅ | полный pytest (вкл. пин-тесты каталога) зелёный; новых Settings-полей/ключей нет (`get_ytdlp_pot_provider` — функция) |
| SQLite v9 / DDL нет | ✅ | `git diff -- services/database.py` — только SELECT/NOT LIKE и модульный хелпер, без `CREATE/ALTER/user_version`; `pg_db.py` не в диффе |
| tool-set 7 / PREV / `PROMPT_MIGRATIONS` | ✅ | `tool_schemas.py` — 7 инструментов; `PREV_DEFAULT_INFO_TEXT` сохранён; `prompt_migrations.py` не в диффе |
| Новых внешних CDN нет | ✅ | `grep` по `web/` — 0 (кроме Telegram-`photo_url` из initData, см. S10.16-8) |
| Vue-монтирование под CSP | ✅ | `tests/js/vue_mount_test.js` реально компилирует шаблон self-host-бандлом и ловит `EvalError` без `unsafe-eval` |
| XSS | ✅ | `v-html` только через fail-closed `sanitizeHtml`/DOMPurify (`web/app.js:4228-4240`) |

## 4. Итог

- **Critical: 0. High: 1. Medium: 1. Low: 6. Info: 3.**
- **ВЕРДИКТ по контракту: открытых Critical — НЕТ; открытый High — ЕСТЬ (S10.16-1, R17-утечка URL в
  `handlers/youtube.py`).**
- S10.16-1 — pre-existing (строки не в диффе раунда), но нарушает R17-инвариант и DoD F1 («R17-скан чист»);
  фикс минимальный (2 лог-сайта) и рекомендуется до шага 7. S10.16-2 — фактическое затирание текущего ручного
  текста без бэкапа (данные теряются, но владелец разрешил перезапись); остальное — Low/Info, не блокеры.
- Регрессий смежных подсистем не выявлено: pytest 5931/0, JS-гейты чистые, каталог/роутеры/PREV/tool-set/SQLite
  целы, `media/`/`.env` не тронуты.

---

## Повторный аудит (итерация 2) — после правок @Builder

> **Дата:** 14.09.2026. **Метод:** проверка правок по коду (`file:line`) + независимый прогон
> валидаторов. Код НЕ правился.

### 1. Статус findings

| ID | Было | Статус | Доказательство |
|---|---|---|---|
| **S10.16-1** | High | **CLOSED** | Лог-сайты `handlers/youtube.py:697-699,705-707` теперь пишут только `error=<Class> reason=<reason>` (`type(exc).__name__` + `getattr(exc,"reason","-")`); `handlers/video_download.py:312-313,320-321,329-330,355-357,475-480,585-606,613,700-701`, `services/tool_router.py:600-607` — тот же паттерн, `str(exc)` не печатается. Тексты `DownloadError` больше не несут `url={url}` (grep `url=\{url\}` — 0 в raise-сайтах). `str(exc)` в `tools/video_downloader.py:332,580` — только локальная классификация, в сообщение/лог не попадает. caplog-тест `tests/test_download_round1016.py:711-730,733-748` реально гоняет путь `yt._download_or_phrase` при «грязном» `DownloadError(f"… url={url}")` и проверяет отсутствие токена/домена — тест исполняется в полном прогоне. Signed-URL в лог не утекает. |
| **S10.16-2** | Medium | **CLOSED** | Force-доставка бэкапит текущий текст: `services/config_cache.py:292` (`_write_info_canon(backup_of=current)`), `:317-323` сохраняют `prev_html`/`prev_updated_at`; явный reset — `services/info_service.py:285-291`. Ручная правка восстановима (`save_text(prev_html)`). |
| S10.16-3 | Low | **CLOSED** | `download_available()` задокументирован (`handlers/video_download.py:126-136`): defensive-DI, всегда `True` в текущем DI, осознанно оставлен. |
| S10.16-4 | Low | **CLOSED** | Кулдаун жжётся после успешного старта и ДО `_send_file`: `handlers/video_download.py:462-468`; probe/fallback-fail кулдаун не жжёт. |
| S10.16-5 | Low | **CLOSED** | Мёртвый `probe_unavailable` удалён, маппинг документирован — `handlers/video_download.py:415-426`. |
| S10.16-6 | Low | **CLOSED** | `is_platform_url` публичный (`tools/video_downloader.py:235`), импорт без подчёркивания (`handlers/youtube.py:99`). |
| S10.16-7 | Low | **CLOSED** | Нативный путь логирует только класс — `handlers/video_download.py:698-701` (`type(exc).__name__`). |
| S10.16-8 | Low | **CLOSED** | Аватар через same-origin прокси: `web/app.js:1564-1590` (`fetch('/api/avatar/…')` + initData) и `:828-831`; CSP `img-src 'self' data: blob:` (`web/app.py:53`) больше не конфликтует с внешним CDN. |

### 2. Остаточный Low (новое, не блокер)

| ID | Severity | File:line | Описание |
|---|---|---|---|
| **S10.16-9** | Low | `tools/video_downloader.py:767,772,899,904` | Заявление «убраны `str(exc)` во ВСЕХ raise-сайтах» неточно: 4 raise-сайта всё ещё интерполируют `{exc}` (`cobalt unreachable`, `cobalt transport error`, `tunnel unreachable`, `stream transport error`). Доступного лог-пути, печатающего сообщение, нет (все лог-сайты — класс+reason), поэтому утечки НЕТ; это hardening на будущее (residual Info-1). Аналогично `:835` интерполирует до 500 символов тела cobalt-ответа, `:776` — удалённый error-dict; тела не логируются (`:832` — только status/code/len). |

### 3. Инварианты (итерация 2)

| Инвариант | Статус | Доказательство |
|---|---|---|
| R17 (секреты/URL в логах) | ✅ | Все лог-сайты download-путей — класс+reason; youtube/видео/tool_router покрыты caplog; S10.16-9 — только latent. |
| R16 (id — ключ) | ✅ | `updated_by=user.id` (`web/api/routes.py:1111,1137`), аудит сохранён. |
| Порядок роутеров `bot.py` | ✅ | 4e `video_download_router` остаётся между `common_router` и `slavik_router` (`bot.py:756` → `:765`); изменён только startup-гейт (безусловная регистрация). |
| `media/` и `.env` не тронуты | ✅ | `git status --porcelain media/ .env` пусто; `.env` не tracked. |
| Каталог 435/406/411/90/88/19 | ✅ | Пин-тесты зелёные (`tests/test_help_guide_round1014.py:196-203` и др.), полный pytest 0 fail. |
| tool-set 7 / PREV / `PROMPT_MIGRATIONS` | ✅ | `tests/test_tool_schemas.py:90` — 7 инструментов; `PREV_DEFAULT_INFO_TEXT` (`info_service.py:148`) и `prompt_migrations.py` целы. |
| SQLite v9 | ✅ | `_SCHEMA_VERSION_AGI_MEMORY = 9` (`services/database.py:57`), миграция 8→9 (`:940-1014`). |
| F1–F5 не сломаны | ✅ | Полный pytest 5936/0; JS-гейты и `git diff --check` чисты. |

### 4. Валидатор (независимый прогон итерации 2)

| Команда | Результат | Exit |
|---|---|---|
| `.venv/Scripts/python.exe -m pytest -q` | **5936 passed, 0 failed**, 1 warning (`StarletteDeprecationWarning` — не наш код), 69.4 c | 0 |
| `node --check web/app.js` | OK | 0 |
| `node tests/js/routing_test.js` | `JS-UNIT-OK` | 0 |
| `node tests/js/vue_mount_test.js` | `VUE-MOUNT-OK` | 0 |
| `git diff --check` | чисто (только штатные LF→CRLF) | 0 |
| `git status --porcelain media/ .env` | пусто | 0 |

### 5. Итог итерации 2

- **Critical: 0. High: 0. Medium: 0. Low: 1 (S10.16-9, latent hardening). Info: 0.**
- **ВЕРДИКТ по контракту: открытых Critical/High/Medium — НЕТ. Блокеров нет.** S10.16-1 и S10.16-2
  закрыты фактически; все Low предыдущей итерации закрыты без регрессий.
- Регрессий F1–F5 не выявлено; валидаторы чистые.

*Round 10.16 scanner audit (iteration 2) generated by @Scanner on 2026-09-14.*
