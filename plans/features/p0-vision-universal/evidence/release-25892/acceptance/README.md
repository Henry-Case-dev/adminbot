# P0V 2.58.92 — live acceptance (ACCEPTANCE-92, RE-ACCEPTANCE-92)

Прод: **2.58.92**, HEAD **`1d367e4c561b5d1bc224c4c5ee64261945ed83bd`**, T0 **2026-10-18 23:25:48 UTC**,
PID **3548159**. Приёмка: **2026-10-18 23:53:22 → 2026-10-19 00:04:51 UTC**.
Метод: один контролируемый harness-процесс на проде (импортирует развёрнутые модули;
реальная Telegram-доставка, реальные PG/SQLite, реальные провайдеры) + отдельная
read-only журнальная волна + уборка. Секретов в отчёте/эвиденсе нет (скан ключей/паролей: 0).
Сообщения — синтетические апдейты от пользователя `990002001` в рабочем чате
`-1002661910336` (per-chat `flags.vision_enabled=true`, глобально OFF).

## Таблица 1–8 (факты)

| # | Сценарий | Факт | Статус |
|---|---|---|---|
| 1 | SKIPS-формализация (§a/b) | окно 39 мин: **SKIPS=0** (`maximum number of running instances`; в 2.58.91 было 36); `claim sweep slow` = **10** (5.65–14.23 с, WARNING — допустимо §4b); `claim sweep timeout`=0; `maintenance stage timeout`=0; очередь двигается (2 manual vision-джобы: claim→retry→терминал; 5×initiative.observe completed; WATCHDOG_SWEEP 31); journal ERR/CRIT/Traceback=0, 402=0, RuntimeWarning=0, `database is locked`=0; миграции `complete user_version=36` (ΔDDL=0); MainPID=3548159 стабилен, NRestarts=0; healthz `2.58.92` (loopback+HTTPS) | **VERIFIED** |
| 2 | Per-chat state + проба (§c) | `GET /api/vision/state` с `X-Chat-Id` чата владельца → `requested=true`, reason≠`vision_disabled`; `POST /api/vision/test` с тем же заголовком → HTTP 200, `state.requested=true` (контекст НЕ перетёрт); после пробы GET → снова `requested=true`; без заголовка → глобальный слой (`requested=false/vision_disabled`); чужой ЛС (990002001, нет доступа) → глобальный слой; юзер без прав → 403; сырой ключ в ответах отсутствует (только маска) | **VERIFIED** |
| 3 | Reply-на-фото (§d) | `recognize_image` **target = `{chat_id: -1002661910336, message_id: 1165606}`** — фото из reply (не текущий вопрос 1165721); повтор (1165607) — то же; доставка ответа mid **1165722** / **1165724** («картинка не обработалась, висит в очереди» — честно); replay того же апдейта: 0 новых отправок (дедуп работает, `DIRECT_UPDATE_DEDUP_HIT`) | **VERIFIED (target/доставка)**; положительное распознавание не состоялось — см. finding 1 |
| 4 | «Это правда?» reply (§e) | `fact_check` claim = **«Вода закипает при 100 °C на уровне моря.»** (текст replied-сообщения, не вопрос), target = **1165725** (replied); результат **`ready`**, `factual_verdict=supported`, `temporal_status=old_but_valid` (паритет registered-пути ACCEPTANCE-91); доставка mid **1165727** | **VERIFIED** |
| 5 | Живая Vision-проба (§f) | текущая `google/gemma-4-31b-it:free` → **`rate_limited/http_429`** (честно; ключ OpenRouter: `is_free_tier=false`, лимит $2, остаток ~$2 — 429 не про баланс); альтернатива **`nvidia/nemotron-3.5-super-vl:free`** (подтверждена в живом списке free+image, 11 моделей): смена штатной настройкой `POST /api/config` (`updated: models.vision_model`, журнал `[api] config updated | by=5885953495`) → проба **`ok`/`image_input=true`** («Распознавание работает», revision `a3ed06b38a021513`) → **оставлена по PET**. Положительное распознавание: не состоялось (провайдер для анализа не вызывался — см. finding 1) | **VERIFIED (проба)**; модель оставлена; положительное распознавание — не достигнуто |
| 6 | Уборка тестовых сообщений (§g) | удалено **7/7** (mid 1165721–1165727) через Bot API; остаток тестовых = **0**; синтетическая fidelity-строка `smart_messages` (rowid 2351893, mid 1165725) удалена; сообщения владельца не тронуты (safety-гейт: пересечений с реальными юзерами нет); регистр — `cleanup-register.json` | **VERIFIED** |
| 7 | Экономика/журнал (§h) | генераций/резерваций нет (`image_reservation` since T0 = 0; бюджет `image_calls` не изменился); LLM за окно: `single` 8, `l1_planner` 3, `l2_writer` 3, `temporal_*` 1+1+1 (малый бюджет, без генераций); `mca_errors` since T0 = 2 — оба `safe_fetch failed/too_many_bytes` (обработка слишком больших страниц в factcheck, 23:56:21; уровень ERROR у SafeFetcher by design), журнальный ERR/CRIT/402 = 0; миграции не выполнялись (уже 36) | **VERIFIED (наблюдений)** |
| 8 | Границы (§8) | **WebView**: агент-сайд граница — served `app.js` sha12 `b14ef48ab16a` == blob деплой-коммита `1d367e4c` (бит-в-бит), PAGE_VER=15, SUBST_CSS=2, healthz 200/2.58.92; браузера на сервере нет, TMA-initData без токена недоступен — нативный WebView остаётся агенту «после» (PET). **SCEN-B (ностальгия)**: за окно естественного затишья не было — `nostalgia_log` since T0 пуст, `mca_events` nostalgia — 0, журнал `[nostalgia]` — 0 строк → `WAITING_EXTERNAL` (не блокер) | **BOUNDARY** / **WAITING_EXTERNAL** |

## Findings

1. **Положительное распознавание не состоялось — блокер на СТАДИИ DOWNLOAD (не модель, не код 2.58.92).**
   Обе reply-джобы (ассеты 1165606/1165607 — реальные фото, переиспользованы из ACCEPTANCE-91)
   прошли state-гейт (`capability=ok`) и упали на скачивании Telegram-файла:
   `vision_media skipped stage=download reason=vision_unavailable` ×4 (bounded-retry) →
   терминал `failed` (attempt 3/4, 23:57:35 и 23:58:50). FIX2-механика сработала штатно
   (retry с backoff → честный терминал; тул отдал честный pending, пользователь получил
   человеческую причину). Анализы: `mca_media_analyses` — пусто (ни одной строки за всю историю).
   Вероятная причина — недоступный `file_id`/удалённое исходное сообщение у легаси-ассетов
   (данные, не релиз). Для положительного распознавания нужен повтор с **свежим** фото
   (например, ассеты 1165720/1165719 — свежие фото чата); целевой фикс reply-на-фото при этом уже доказан.
2. **LOW/UX (пре-существующее, не регрессия 2.58.92):** при терминальном `failed` после
   pending-окна тул уже вернул «pending/job_linked», и ответ бота говорит «висит в очереди» —
   формулировка D23; поведение не блокирует.
3. **Модель прода изменена штатной настройкой** (`models.vision_model` → `nvidia/nemotron-3.5-super-vl:free`),
   оставлена по PET (проба ok). Откат — той же штатной настройкой на `google/gemma-4-31b-it:free`
   (значение зафиксировано в `s5-vision-probe.json`).
4. **429 у gemma — лимит модели у провайдера, не кода и не баланса** (ключ: `is_free_tier=false`,
   `limit_remaining≈2.0`): окно ретрая/backoff и честная причина работают; альтернативная free-модель
   даёт `capability=ok` (штатный путь смены модели подтверждён).

## Затраты

- Генерации изображений: 0; `image_reservation` since T0: 0; бюджеты `image_calls` без изменений.
- LLM: 17 вызовов за окно (см. §7); vision-пробы бесплатных моделей: gemma (429) + nemotron (ok) ×3
  (web ×2 + harness ×1); анализ-вызов провайдера не состоялся (упал на download).
- Уборка: 7 удалений Bot API, 1 удаление синтетической строки БД.

## Журнал / стабильность / откат

- Journal since T0 (39 мин): `SKIPS=0`, `CLAIM_SLOW=10` (WARNING-наблюдаемость), `MAINT_TIMEOUT=0`,
  `ERR/CRIT/Traceback=0`, `402=0`, `RUNTIMEWARN=0`, `LOCKED=0`, миграции `complete user_version=36`.
- Сервис: `MainPID=3548159`, `NRestarts=0`, `active/running`, healthz `2.58.92`; HEAD `1d367e4c`,
  tracked mod=0 (до и после).
- Откат релиза не требовался и не использовался. Рубежи прежние: `release/fix-2.58.91` (`f2a6248a`),
  `release/fix-2.58.90`, авто-рубеж `release/cfg1-2.58.88`. «Мягкая дверь» для модели — п.3 findings.

## Файлы

- `s2-perchat-state.json` — §c (все ветки, leak-check);
- `s3-vision-reply.json`, `s3b-vision-reply-repeat.json` — §d (target/replay/анализ-строки);
- `s4-factcheck-reply.json` — §e (claim/target/ready/доставка);
- `s5-vision-probe.json` — §f (429, смена модели, проба ok, key-status, состояние);
- `s7-econ.json`, `summary.json` — §h и сводка;
- `journal-since-t0.txt` — журнальные проверки и счётчики (2 дампа: 23:57:20Z / 00:04:49Z);
- `webview-agent-check.json` — §8 (served-bytes == деплой-коммит, маркеры, границы);
- `live.out` — stdout harness-процесса;
- `cleanup-register.json` — §g (регистр mid→удалён, диагностика, SCEN-B, верификация);
- `harness/` — исходники контролируемых вызовов (accept92_live.py + base 2.58.91-bootstrap,
  accept92_clean2.py, accept92_journal.sh, accept92_dbcheck.py). SSH-раннеры (с креденшелами)
  не промотированы — прецедент ACCEPTANCE-91.

## Волна B — добивка положительного Vision + пост-генерации (ACCEPTANCE-92B)

Прод: **2.58.92 @ `1d367e4c`** (тот же T0 23:25:48 UTC); окно **2026-10-19 00:15:24 → 00:22:30 UTC**;
модель прода — `nvidia/nemotron-3.5-super-vl:free` (PET); 2 SSH-сессии (прогон + уборка).

| # | Сценарий | Факты | Статус |
|---|---|---|---|
| B1 | Положительное распознавание | свежий ассет **1165720** (54960 B, image/jpeg, 736×384): **реальная загрузка Telegram OK** (пре-чек до хода, 54960 B). announce mid **1165728**; turn-1 — планировщик не выбрал `image_understanding` (честный ответ, mid 1165729); turn-2 (announce mid 1165730): `capabilities=image_understanding` (conf 0.85, 2.3 c), `recognize_image` **target=1165720** ✓, но проба провайдера → **`disabled/vision_unavailable`** (`http_502`, «Провайдер временно недоступен (ошибка сервера)»), 456 мс; джоба не создавалась; честный ответ mid **1165731** | **BLOCKED_EXTERNAL (провайдер 502)**; путь/target — VERIFIED |
| B2 | Пост-генерация (ON) | `postgen_enabled=true` (бюджет 20 c); пре-гейт «бот, нарисуй …лимон…» → **1 генерация** (`qwen-image-3-pro`, 612086 B, 41.5 c) → **фото mid 1165733** (sha12 `92e501705bec`) → `image_postgen_vision` → **failed/vision_unavailable** (тот же класс 502) → блок честно запретил утверждать содержимое; ответ mid **1165734** | **VERIFIED (генерация+доставка)**; postgen-описание — BLOCKED_EXTERNAL |
| B3 | Журнал/экономика | SKIPS=**0** сохраняется (весь T0+окно, ~57 мин); CLAIM_SLOW=22; **CLAIM_TIMEOUT=1** (00:00:30, 30.0 c) и **MAINT_TIMEOUT=1** (00:00:55, recover_stale) — WARNING-наблюдаемость (пропусков тика нет); ERR/CRIT/Traceback=0, 402=0; `image_generate success n=1` (бюджет +1 генерация); `safe_fetch too_many_bytes`=2 (те же, окно A — повторов нет); `mca_media_analyses` — по-прежнему пусто | **VERIFIED (наблюдений)** |

**Корневая причина обеих неудач волны B — внешняя и транзиентная:** проба `POST /api/vision/test`
и пост-генерация получили **HTTP 502** от OpenRouter для `nvidia/nemotron-3.5-super-vl:free`
(события `vision_capability_probe failed … detail=http_502` в 00:19:11 и `image_postgen_vision
failed` в 00:20:14). Через ~3 минуты провайдер восстановился: в 00:22:27 проба **`ok`**
(«Распознавание работает», `state.requested=true`) — зафиксировано в `cleanup-register-b.json`
(`probe_now`). Код 2.58.92 отработал честно во всех точках (тул `disabled/vision_unavailable`,
постген-блок «не утверждай, что получилось», доставка — с честной формулировкой).

**Уборка волны B (правило владельца):** **7/7 удалено** (mid 1165728–1165734, включая фото
генерации), остаток тестовых **0**; ассет владельца 1165720 не тронут. Регистр — `cleanup-register-b.json`.

**Остаток/рецепт:** бюджет генераций волны израсходован (1/1) — позитивное postgen-описание требует
новой генерации; повтор B1 возможен сразу (провайдер ok): тот же ассет 1165720, фраза «бот, что тут?»,
ожидание `ready` (анализ в `mca_media_analyses` + ответ с описанием). Файлы волны: `b1-recognition.json`,
`b2-postgen.json`, `b3-final.json`, `b-summary.json`, `b-live.out`, `journal-since-t0-b.txt`,
`cleanup-register-b.json`, `harness/` (accept92b_live.py, accept92b_clean.py, accept92b_journal.sh,
accept92b_dbcheck.py; база идентична accept92_base.py).
