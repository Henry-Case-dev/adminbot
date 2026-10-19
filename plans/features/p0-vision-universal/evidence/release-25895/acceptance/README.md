# P0V 2.58.95 — живая приёмка (ACCEPTANCE-95): CFG-03 Ф6 + POSTGEN + VISION-ADAPT + орфан + уборка

Прод: **2.58.95 @ `113f3a629cab54f7fcc261349a7c9af3b90f56d7`** (T0 выката
2026-10-19 13:07:43Z, MainPID **3716545**, NRestarts=0). Волны приёмки
(UTC): **95a 13:47:17–13:55:22**, **95b 14:01:35–14:06:41**, **95c
14:14:23–14:19:13**, финальная 95d 14:31:23–14:31:54, журнальная 95e
14:34:09; UI-проверка (локальный Playwright против живого прода)
14:20–14:42. Метод: контролируемый harness-процесс на проде (проверенный
bootstrap ACCEPTANCE-91/92/93/94: развёрнутые модули, реальная
Telegram-доставка через прод-сессию `build_local_api_session`, реальные
PG/SQLite/провайдеры) + read-only журнальные волны + уборка. Прод-код не
менялся; все временные per-chat настройки сняты точным восстановлением
(`config_matches=true`, `reserve_mode=legacy/budgets_off`). SSH: 5 коннектов
(все успешны, паузы ≥95 c) — fail2ban не задет. Секретов в эвиденсе нет.

## (a) CFG-03 Ф6 live — 03.4 / 03.6 / 03.11 / 03.12 (+ CFG-02B.2/.2.3/.8 UI)

| Пункт | Результат |
|---|---|
| **03.6 витрина честности (API)** | Живой админ-API (`GET /api/config` с X-Chat-Id рабочего чата): все **5** «мёртвых ручек» (`limits.chat_lock_max_entries`, `limits.chat_budget_response_ratio`, `limits.dig_year_back_window_days`, `limits.youtube_transcript_proxy_locations`, `limits.youtube_transcript_proxy_retries`) присутствуют, описание содержит точный маркер «Не влияет: значение сохраняется в конфиге…»; ровно 5 совпадений точного маркера во всём каталоге; served `app.js` == disk (`appjs_same=true`), HTML содержит scope-метку `Обложки сводок здесь не учитываются`. `p6b-showcase-api.json` |
| **03.6 витрина честности (UI, реальная мини-аппа)** | Playwright, живая TMA-сессия админа, реальные данные: вкладка «Память» — `dig_into_lore: окно …` с «Не влияет…» и `memory_backup_keep` с «НЕ действует…»; модалка «Ответы в чате» — обе ручки с «Не влияет…»; модалка «Выжимка видео» — обе youtube-ручки с «Не влияет…». Console errors **0**; скриншоты desktop+mobile; 390px без overflow. `ui-live-check95.json`, `ui/*.png` |
| **03.4 hot `flags.vision_enabled`** | Чат-override OFF → `resolve_effective_state` = `requested=false/vision_disabled`; прямой вызов инструмента `recognize_image` → честный `{"status":"disabled","reason":"vision_disabled"}`; полный ход с документом-картинкой → честный ответ («Глаза мне отключили…»), **0 vision-вызовов, 0 анализов, 0 джоб**. ON (точное восстановление исходного override=true) → анализ запускается. `p2-vision-off.json` |
| **03.4 hot `limits.image_daily_limit`** | Разрешена ровно **1** генерация; вторая попытка — честный отказ **ДО** платного вызова (0 провайдер-вызовов, 0 фото, 0 строк журнала): сработал ранний image-capability-gate (SOUL-1 W10) с заводским шаблоном `message.image_failure.quota_exhausted` («На сегодня картинки закончились…»). Отклонение от эскиза сценария зафиксировано: на проде chat-day уже `used=16` (legacy-путь), поэтому «ровно одна» реализовано chat-scope лимитом `used+1=17`, глобальный слой не тронут; точная строка сброса (reserve-deny путь) в этом сценарии не появлялась — она покрыта ранее CFG-02A.5. Восстановление точное. `p4b-generation.json` |
| **03.11 негативы (выборочно)** | 3 класса live без записи: неверный тип (`image_daily_limit="abc"`) → **422**; недопустимая опция select (`image_freq_limit_mode="bogus"`) → **422**; устаревший optimistic-токен (stale `updated_at`) → **409**. Значения до==после. `p5b-negatives.json` |
| **03.12 OFF/ON по маршрутам** | OFF — маршрут (tool + ход) честно не выполняется (см. 03.4); ON — работает (см. (c)) |
| **CFG-02B.2 (UI)** | Временная ON-предпосылка (budgets ON + freq ON, burst=2, cooldown=120, mode=per_user; восстановлена точно) → в живом UI видны компактные настройки: «Сколько генераций подряд»=2, «Время ожидания»=120 сек, тумблер ON. `ui-live-check95.json` |
| **CFG-02B.2.3 (UI)** | Select «Считать лимит» — ровно **2** взаимоисключающих варианта (`per_user` / `per_chat`, подписи «Для каждого пользователя»/«Общий на весь чат»), чекбоксов нет (`mode_checked_count=0`) |
| **CFG-02B.8 (UI)** | Блок фактов «Лимиты генерации»: «Включено и действует», режим «Для каждого пользователя», источник «Локальный (чат)», остаток «2 из 2», «сейчас доступно»; блок квоты с scope-меткой; mobile 390 — те же факты без overflow; после восстановления — «Выключено (заводской режим)», настройки скрыты, конфиг восстановлен |

Остаток (честно): synthetic-группа «Медиа-шара» (`content_media`) в живом
окне «Выжимка видео» в этих прогонах в DOM-тексте не найдена
(`video_content_media.groups=[]` — состояние вкладки/тайминг; сама группа
покрыта статическим UI-маркером и e2e из релиз-пакета, `UI_missing=0`).
Два диагностических прогона — `ui-diag95.json`, `ui-diag95b.out`.

## (b) Живой повтор пост-генерации — ровно 1 генерация

- **gen1 (95b, 14:04)**: ровно **1** провайдер-вызов генерации
  (`qwen-image-3-pro`, 1 037 752 B, 58.3 c) → фото **mid 1166489**
  (sha12 `0f7bc44fc2e0`) доставлено; журнал `image_reservation`
  `-1002661910336:1166487:direct` = **committed**; бюджет chat
  image_calls **16→17 (+1)**, shared **21→22 (+1)**; дедуп не сломан
  (1 vision-вызов на 1 генерацию).
- **Пост-анализ (адаптивный путь)**: `[vision] normalize in=1037752
  out=104689` → `[vision] adapt strategy=optimize reason=payload_over
  calls=1 stage=A` (Этап A уменьшил payload в ~10 раз) → один вызов
  провайдера → исчерпан bounded-бюджет (20 c) →
  `[vision] postgen status=pending reason=deadline_exceeded` → ответ
  Writer'а честный, без выдуманного содержимого. `error=TimeoutError`
  виден в событии `vision_adapt`; «слепого» `vision_failed` без класса нет.
- **Отказ второй генерации**: 0 провайдер-вызовов, 0 фото (см. (a) 03.4).
- **Остаток**: `status=ready` в постгене live не наблюдался (обе волны —
  `pending/deadline_exceeded`: бесплатная vision-модель на 1024×1024 не
  отвечает за 20 c). Цепочка `[image] generated → postgen → доставка`
  живая, поведение bounded и честное. `p4b-generation.json`.

## (c) Vision-adapt live — длинный PNG-документ

- Фикстуры (ground-truth): `fixture.png` 960×4000, **1 337 017 B**
  (95a/95b) и `fixture95c.png` 960×2600, **1 115 814 B** (95c); обе
  opaque PNG, >700 КБ; download через прод-сессию вернул байт-в-байт
  (sha совпал), intake-ассеты созданы.
- **Адаптивный путь подтверждён live** (журнал + события `vision_adapt`):
  `plan=optimize reason=payload_over`; 95b: Этап A 1 337 017→801 992,
  Этап B `scale=0.90`→**540 078 B**, **1** вызов провайдера, 34.1 c;
  95c: Этап A 1 115 814→**642 544 B** (fits), **1** вызов, 20.6 c.
  События: `strategy=optimize, reason=payload_over, calls=1`.
- **НО: анализ `ready` не получен** — обе попытки провайдер ответил
  НЕ-JSON → `mca_media_analyses failed/parse_error`
  (uncertainty «ответ модели не JSON»), бот честно сообщает, что
  распознать не удалось; ground-truth строки в анализе отсутствуют
  (0/8 и 0/3). Класс устойчивый на двух разных фикстурах. См. Finding 1.
- **Калибровка (прод-ручки НЕ менялись)**: live-значения
  `MCA_VISION_REQUEST_MAX_BYTES=700000`, `MCA_VISION_PREP_MAX_PIXELS=4000000`,
  `MCA_VISION_ADAPT_BUDGET_SECONDS=90`, кодек **ffmpeg**, normalize ON —
  совпадают с дефолтами (`defaults_match=true`).
- **Бонус — непланируемое живое доказательство POSTGEN-DIAG**: 14:30:16 на
  РЕАЛЬНОМ фото пользователя сработал декод-фоллбэк
  `[vision] unreadable rescued via normalization in=242886 out=24021
  detail=not a supported raster image` → `strategy=original reason=fits
  status=ready` (анализ завершён успешно). `p3b-vision-adapt.json`,
  `p3c-vision-adapt.json`, `runs/accept95d-run.log`.

## (d) Орфан `mca_media_analyses running=1`

`id=8`, asset `a32e0331…`, сообщение **1166176** (реальное фото 966×1280,
250 048 B), строка создана **2026-10-19 09:12:42Z**; джоба
`e75c45b78eca47a4aa6d57e9f2aad0cb` = **interrupted / `worker_lost`**
(created 09:12:41, updated **09:14:44** — совпадает с INCIDENT
`vision.media` 09:14:44 из журнала волны ACCEPTANCE-94). Классификация:
**in-flight-орфан эпохи ACCEPTANCE-94 (2.58.94), НЕ от рестарта 2.58.95**
(создан за ~4 часа до T0 13:07:43); строка инертна (нет владельца),
авто-ре-очереди нет (`recover_stale` помечает interrupted); при будущем
tool/manual вызове по этому сообщению анализ завершится новой ревизией.
Рестарт 2.58.95 новых орфанов не создал. `probe95c.json`, `d-orphan-95b.json`.

## (e) Уборка тестовых сообщений

Удалено **16/16** сообщений всех трёх волн (Bot API, прод-сессия):
95a — doc 1166463, ответ 1166464, ответ gen1 **1166471** (mid восстановлен
через `bot_reply_parents`); 95b — doc 1166482, анкеры 1166483/1166486,
ответы 1166485/1166487/1166491/1166495, фото gen1 1166489; 95c — doc
1166496, анкеры 1166497/1166500, ответы 1166499/1166501. Safety-gate
против реальных пользователей соблюдён (0 коллизий; сообщения участников
не тронуты). Residual `smart_messages` = 0; наши строки
`bot_replies`/`bot_reply_parents` добиты вторым проходом (7+7 → 0).
**Остаток (честно)**: одно сообщение 95a — фото генерации gen1 (mid не
сохранён: harness упал до записи фазы; кандидаты 1166467/1166469, среди
них может быть и сообщение реального пользователя — удаление по догадке
запрещено safety-правилом). Фото без подписи, отправлено ~13:54:17Z;
при желании удаляется владельцем вручную. `cleanup-register.json`,
`final95d.json`.

## Базовые маркеры

- `healthz` loopback **и** HTTPS = `2.58.95` в начале/конце каждой волны;
  MainPID 3716545, **NRestarts=0**, active/running; HEAD `113f3a62…`,
  TRACKED_MOD=0.
- `user_version=36` (**ΔDDL=0**); миграций в окнах нет; **SKIPS=0**,
  `402=0`, RuntimeWarning=0; mca_events ERROR/CRITICAL от волн = **0**.
- Журнал ERR построчно разобран: 95a — 8 строк (2 update-фейла aiogram +
  tracebacks), 95b — 2, 95c — 1; **все** — класс `database is locked`
  (SQLite-контеншн окна волны, fail-open: события → bounded spool;
  сообщения не теряются). WARNING `[vision] claim sweep slow/timeout`
  (до 30 c) — наблюдаемость busy-окна, тики не пропускались.

## Findings (не блокеры релиза 2.58.95)

1. **Провайдер vision на тяжёлых длинных изображениях возвращает не-JSON**
   (2 фикстуры, 2 волны → `failed/parse_error`); на маленьких изображениях
   того же чата — `ready`. Живая положительная половина (c) не достигнута;
   адаптивный контур (payload_over → Этап A/B → 1 вызов) работает.
2. **Постген-бюджет 20 c меньше латентности бесплатной модели на 1024×1024**
   → `pending/deadline_exceeded` (bounded, честно); `ready` в постгене не
   наблюдался.
3. **SQLite-контеншн окна волны** (класс известен с ACCEPTANCE-94): 2
   update-фейла aiogram (13:53:44/45) + 4 observer/heartbeat-предупреждения
   (95a), 2 traceback (95b), 1 (95c); один observer-save относился к
   сообщению реального пользователя (13:54:21, user 479167456) — само
   сообщение в чате не потеряно, пропущена только строка наблюдаемости.
   Причина — конкурентные записи harness-процесса в общую SQLite; прод
   fail-open, NRestarts=0.
4. **Бонус-наблюдение**: живое срабатывание декод-фоллбэка POSTGEN-DIAG на
   реальном фото (unreadable→rescued→ready) — см. (c).

## Файлы

- Фазы: `p0-pre-state.json`, `p1-fixture-doc.json`, `p2-vision-off.json`,
  `p3-vision-on-adapt.json` (95a, dedup-находка), `p0b-pre-state.json`,
  `p3b-vision-adapt.json`, `p4b-generation.json`, `p5b-negatives.json`,
  `p6b-showcase-api.json`, `p7b-economics.json`, `d-orphan-95b.json`,
  `p8b-cleanup-register.json`, `summary95b.json`, `probe95c.json`,
  `p3c-vision-adapt.json`, `p8c-register.json`, `summary95c.json`,
  `cleanup-register.json`, `final95d.json`, `ui-live-check95.json`,
  `ui-diag95.json`, `ui-diag95b.out`, `summary.json`.
- Журналы прогонов (scrub): `runs/accept95*-run.log`, `runs/live*.out`.
- Скриншоты: `ui/01…06-*.png` (desktop+mobile).
- Harness-исходники: `harness/**` (включая генераторы фикстур и
  ground-truth JSON; SSH-раннеры креды не содержат).

## Остаток

- (c): позитивное «ready + ground-truth» — заблокировано JSON-несоответствием
  бесплатной vision-модели на тяжёлых кадрах (см. Finding 1); механика
  адаптивного контура подтверждена live.
- (b): `status=ready` постгена — см. Finding 2.
- Одно фото 95a-волны без сохранённого mid (см. (e)).
- CFG-02B.2/.2.3/.8 — UI-часть подтверждена live; строки карт — за леджером
  (карты лейном не правились).
