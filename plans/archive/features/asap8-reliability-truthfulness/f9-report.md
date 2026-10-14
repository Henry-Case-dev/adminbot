# F9 — YouTube proxy classification + health (отчёт Builder)

Wave: asap8-reliability-truthfulness, lane F9 (LEAF writer).
Baseline: master `7fdeaaf` на старте лейна; HEAD рабочего дерева на момент сдачи `d204ccb`
(в работе параллельные лейны). Кандидат НЕ закоммичен — коммит после Reviewer.

## 1. Candidate fingerprint

| файл | sha256 (12) | bytes |
|---|---|---|
| services/youtube_transcript_engine.py | F2210A395F0C | 55248 |
| web/api/routes.py | 1B04E524374B | 138552 |
| web/app.js | B2CC19E22BF3 | 938648 |
| web/index.html | 5041E84F5050 | 625628 |
| tests/test_youtube_transcript_engine.py | 69F67037889A | 60685 |
| tests/test_asap8_f9_youtube_proxy.py (NEW) | 0CDF4B02DB42 | 30069 |
| tests/js/asap8_f9_youtube_proxy_health_test.js (NEW) | FDF3ED1214DD | 10904 |

## 2. Retry-матрица (зафиксирована ТАБЛИЦЕЙ в докстринге модуля)

Классификация — `_failure_class(exc)` по корневой причине (unwrap `__cause__`);
**специфичный парс ДО generic-классов**. Ретраебельность =
`класс in _TRANSIENT_FAILURE_CLASSES`; retry = каскадный backoff `_RETRY_BACKOFFS`
(1/2/4/8с), ≤ `_MAX_CASCADE_RETRIES` = 4 ретрая = 5 попыток.

| сигнал (по корневой причине) | failure_class | retry |
|---|---|---|
| HTTP 407 / «Proxy Authentication Required» (вкл. yt-dlp `DownloadError` «HTTP Error 407», `ProxyError` с маркером 407) — парсится ДО generic «http error»-чека и до `ProxyError→True` | `proxy_auth_failed` | НЕТ |
| HTTP 403 | `forbidden` | НЕТ |
| HTTP 429 / TooManyRequests | `rate_limited` | ДА |
| timeout / «timed out» / TimeoutError | `timeout` | ДА |
| «connection reset» / «reset by peer» | `reset` | ДА |
| ProxyError / TransportError (не 407) | `proxy_unavailable` | ДА |
| HTTP 500/502/503/504 | `server_error` | ДА |
| известные транзиентные паттерны (bot-check, empty transcript, extract_info=None, JSONDecodeError, ParseError(no element), FailedToCreateConsentCookie) | `transient` | ДА |
| прочее / неизвестное | `permanent` | НЕТ |

Семантика каскада: **407 перманентен ДЛЯ ЗАПРОСА** — 407 на ЛЮБОМ движке
останавливает каскад (transient-фейл второго движка больше не делает его
ретраебельным; прежде OR-правило `_is_transient(a) or _is_transient(b)` при
yt-dlp-407 + transcript-api RequestBlocked давало retry storm 5 попыток / ~27.5с).
РОВНО ОДИН WARN на запрос (`[youtube engine] proxy auth failed (407) — permanent
for this request, no retry | … | ytdlp=<class> | transcript_api=<class>` — только
коды классов, без секретов). Итоговый `reason` исключения: приоритет
age_restricted → **proxy_auth_failed** → transient → unavailable; хендлер
unknown-reason безопасно деградирует в общий пул фраз (handlers/youtube.py не менялся).

Retry storm (§16.1 live: 407 → yt-dlp fail → api fail → 1/2/4/8s → ~27.5s)
закрыт: одна попытка, 0 backoff, один WARN (§28.20, §28.21).

## 3. Единый effective proxy profile (Y4)

`effective_proxy_profile()` — один резолвер для ОБОИХ путей; приоритет:

1. `YOUTUBE_CREDENTIALED_LEVEL_ENABLED=False` → прокси нет (оба пути).
2. Resident-поля (hot → env): username/password + domain+port →
   `http://[user:pass@]domain:port` — **оба пути** (прежде только transcript-api).
3. URL (hot `keys.youtube_transcript_proxy_url` → env `YOUTUBE_TRANSCRIPT_PROXY_URL`) —
   **оба пути** (прежде только yt-dlp; hot-оверрайд играл роль только в presence-логе).
4. Ничего → egress-guard (MCA-02) применяется движками по-старому
   (yt-dlp `apply_egress_to_ytdlp_opts`, api `GenericProxyConfig(guard)`).

Потребители: `_ytdlp_opts()` → `opts["proxy"] = profile["proxy_url"]`;
`_transcript_proxy_config()` → `GenericProxyConfig(http_url=url, https_url=url)`.
R17/Y5: `proxy_url` (может нести user:pass) — внутреннее поле движка; наружу
только `endpoint_masked` (`mask_proxy_endpoint`: первые 2 + «…» + последние 2
символа хоста, порт целиком).

**Документированная смена контракта** (минимально-рискованный вариант по брифу):
до F9 URL-прокси не попадал в transcript-api (D320) — тесты, пиннившие расщепление
(`test_proxy_and_cookies_passed_to_transcript_api`,
`test_proxy_url_passed_verbatim_to_both_proxies_keys`), обновлены намеренно под
Y4 «оба пути получают один и тот же effective proxy». Если заданы И resident-поля,
И URL — resident-поля выигрывают для обоих путей (правило «более специфичный
конфиг сильнее»; зафиксировано в докстринге).

## 4. Proxy health — контракт

Engine (`services/youtube_transcript_engine.py`):
- `run_proxy_health_check(video_id="dQw4w9WgXcQ")` — шаги:
  1. `auth` — HTTP GET `https://www.youtube.com/generate_204` ЧЕРЕЗ прокси
     (urllib ProxyHandler, timeout 15с): 407/маркер → `fail(proxy_auth_failed)`;
     любой ответ цели (вкл. 4xx/5xx от YouTube) → `ok` (auth принимает прокси);
     refused/timeout/DNS → `unreachable`.
  2. `ytdlp_path` — РЕАЛЬНЫЙ `_fetch_ytdlp(video_id)`; фейл →
     `{status:fail, code:<failure_class>, http_status, exc_type}` (только классы —
     никогда `str(exc)`, он может нести proxy URL с кредами).
  3. `transcript_api_path` — `list(video_id)` через `_transcript_proxy_config()`.
- Прокси не настроен → все шаги `skipped(no_proxy)`; результат кэшируется в
  `_PROXY_HEALTH_LAST` (последний снимок = `last_check`, поле `checked_at` ISO +
  `checked_at_ts` epoch для UI `fmtTs`).
- `run_proxy_health_check_locked()` — singleflight (параллельный вызов →
  последний результат + `in_progress:true`).
- Ответ содержит ТОЛЬКО: configured/source/endpoint(маскированный)/auth_configured/
  auth/ytdlp_path/transcript_api_path/checked_at(+_ts)/took_ms. Секретов нет (Y5).

API (`web/api/routes.py`, существующий `api_router`):
- `GET /api/youtube/proxy/health` — global-admin (`requires_global_admin`,
  fail-closed 403), без побочных эффектов: последний снимок или
  `{"status":"never_run"}`.
- `POST /api/youtube/proxy/test` — global-admin, rate-limit ≥10с на пользователя
  (прецедент `/api/images/test`), общий бюджет `asyncio.wait_for(90s)`; всегда 200
  с результатом шагов (фейл прокси/движка — это поля, не HTTP-ошибка); 429 при
  повторе чаще 10с. Тестовая точка `reset_youtube_proxy_test_rate_limit()`.

## 5. MiniApp-блок (web/index.html + web/app.js)

Вкладка «Выжимка видео» (`mod_video_summary`), ДО общих групп настроек; виден
только global admin (`v-if="activeTab === 'mod_video_summary' && isGlobalAdmin"` —
зеркало server-гейта; прецедент mod_direct context-блока). Поля: Прокси
настроен/не настроен + masked endpoint + источник; Авторизация прокси OK/ОШИБКА
(при 407 — next action «проверьте логин/пароль прокси в группе „YouTube: прокси
и пропуска“ ниже», §18I.6); Путь yt-dlp; Путь transcript-api (OK/человеческий код);
Последняя проверка (`fmtTs(checked_at_ts)`). Кнопка «Проверить подключение» →
POST; busy-guard против дублей; ленивый GET при первом открытии вкладки (setTab).
Состояния: never_run / busy(spinner) / ok / fail(407, красные акценты + текстовые
метки, не только цвет) / noproxy (честное «не настроен» + прочерки).
Секреты в UI не рендерятся (нет доступа к `proxy_url`, нет raw-дампа ответа).

Direct/no-proxy fallback: НЕ добавлен (default — fallback нет, как сейчас);
единственный proxy-источник — явная конфигурация owner'а (п.2/3) либо egress-guard
MCA-02 (уже существовавший). §16 «Direct/no-proxy fallback только если owner явно
разрешил» — соблюдено по умолчанию.

## 6. Тесты

### NEW `tests/test_asap8_f9_youtube_proxy.py` — 41 тест
- Y1: 407-варианты (HTTPError 407 / регэксп / DownloadError / ProxyError-маркер /
  TransportError-маркер / __cause__-обёртка) → `proxy_auth_failed`, не transient;
  both-407 → 1 попытка, 0 sleep, 0 on_retry, reason=`proxy_auth_failed`,
  РОВНО 1 WARN; **регресс retry storm**: yt-dlp 407 + api 429 → всё равно 1 попытка.
- Y2: 429 → `rate_limited` transient; backoff (1,2,4,8) × 5 попыток; recovery на 2-й.
- Y3: timeout → bounded 5 попыток, backoff [1,2,4,8]; reset/proxy_unavailable —
  transient-классы.
- Y4: webshare-поля → один URL в opts и proxy_config; URL-only → одинаковый
  effective proxy в обоих путях; credentialed OFF → нет прокси у обоих; пусто → нет;
  endpoint маскирован.
- Y5: секреты (user:pass/host) отсутствуют в WARN-логах, в health-ответе, в
  JSON профиля UI-полей.
- Health unit: auth-probe (407→fail; 403 от цели→ok; 204→ok; URLError с
  маркером 407→fail; refused→unreachable); no_proxy→skipped; полный прогон с
  классифицированными фейлами; singleflight in_progress; snapshot.
- API (TestClient + ConfigCache-стаб): 403 moderator на GET/POST (fail-closed);
  never_run; snapshot без пробы; POST с маскированным ответом; rate-limit 429.

### NEW `tests/js/asap8_f9_youtube_proxy_health_test.js` — 6 групп
Методы/состояние существуют; подписи шагов/кодов (ok/ОШИБКА·407/недоступен/—);
runYoutubeProxyTest → POST + busy-guard; setTab-хук (ленивый GET только
global-admin и один раз); index.html гейты/кнопка/next-action/без секретов;
**реальная компиляция шаблона блока через Vue.compile** (runtime-compiler,
прецедент vue_mount_test). Запуск: `node tests/js/... → F9-PROXY-UI-OK`.

### Обновлён `tests/test_youtube_transcript_engine.py` (2 осознанные правки)
- `(HTTPError(status=403), True)` → `False` + комментарий F9 (матрица: 403 без retry).
- D320-тесты URL→api: обновлены на контракт Y4 (см. §3).

### Числа
- `pytest tests/test_asap8_f9_youtube_proxy.py tests/test_youtube*.py -q` →
  **265 passed** (41 новых + 224 существующих youtube-тестов, 0 просадок).
- + webapp/routes: `test_webapp_api.py` + epic33/37 router isolation →
  суммарный прогон **440 passed**.
- `node --check web/app.js` → OK; `node tests/js/asap8_f9_youtube_proxy_health_test.js`
  → F9-PROXY-UI-OK.

## 7. Live/UI evidence

- Playwright (детерминированный поток, изолированный инстанс): стенд из РЕАЛЬНОГО
  шаблона блока (extract из index.html) — 5 сценариев (fail/ok/never/busy/noproxy)
  отрендерены и проверены по DOM-snapshot; скриншоты desktop 1280px и narrow 390px
  (перенос строк корректен, без overflow). Scratch:
  `OpenCodeScratch/adminbot-ccef72c25768/f9/` (gen_harness.js, f9_harness.html,
  f9_fail_desktop.png, f9_fail_narrow.png).
- Browser Use (реальный Chrome, вторая вкладка, закрыта после проверки): сценарий
  fail отрендерен идентично — red-акценты + next-action читаемы.
- **LIVE_UNVERIFIED (остаётся за owner/Reviewer):** живой прогон кнопки против
  прод-прокси (реальный 407/OK от Webshare) и блока внутри реального TMA-контекста
  (initData-авторизация) — в этой среде недоступны; API-контур покрыт
  TestClient-тестами, шаблон — Vue.compile + двумя браузерными каналами.
- Live-проверка самого retry storm на проде (одна попытка при 407) — после деплоя
  волны (лог-маркер `proxy auth failed (407) — permanent`).

## 8. Incidental findings

- **related-nonblocking:** 7 JS-тестов + 4 обёртки в `test_webapp_js_unit.py`
  падают в ОБЩЕМ рабочем дереве (`round1020_ui_*`, `round1024_budget_toggle`,
  `round1025_hotfix7/8/9/10`): меню-пины «вкладок 26/27» vs фактические
  `mod_initiative`/`mod_vision` — добавлены ДРУГИМИ лейнами этой волны (F6/…);
  мои диффы app.js/index.html меню/TABS не трогают (проверено `git diff`).
  Пины обновят владельцы соответствующих слайсов.
- **unrelated/pre-existing:** `tests/test_asap7_f9_help_resync.py`,
  `tools/_asap7_f7_routes_pin.py`, `tools/_mca18_repin_routes.py` — чужие
  untracked-артефакты в дереве; не трогал.
- **related, фикс в рамках Y5:** сырые тексты исключений в логах движка
  (`error=%s`, финальное сообщение «both engines failed») могли нести proxy URL с
  user:pass — обёрнуты в `log_ring.sanitize` (`_safe_exc_text`), лимит 500 символов.

## 9. Остаточный риск

- URL-прокси теперь идёт и в transcript-api (Y4): если у owner'а URL указывает на
  прокси, несовместимый с youtube-transcript-api (например socks без extra) — api
  путь станет фейлить там, где раньше ходил через guard/напрямую; health-блок это
  честно покажет (`proxy_unavailable`), классификация не деградирует.
- Смена приоритета «resident-поля > URL» при ОДНОВРЕМЕННО заданных конфигах
  меняет effective proxy yt-dlp; в проде, судя по live-логу, сконфигурирован один
  источник (URL) — расхождение не проявляется.
