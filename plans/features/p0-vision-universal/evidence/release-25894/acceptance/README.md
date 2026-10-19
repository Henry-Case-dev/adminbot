# P0V 2.58.94 — live acceptance (ACCEPTANCE-94): положительный Vision + CFG-02C §Ф6

Прод: **2.58.94 @ `9072347b986b91f05d580a11c1aae6646b250e29`** (T0 выката
**2026-10-19 08:18:20 UTC**, MainPID 3657672, NRestarts=0). Волна:
**2026-10-19 09:08:45 → 09:26:19 UTC** (основной прогон + фикс-волна).
Метод: один контролируемый harness-процесс на проде через проверенный
bootstrap ACCEPTANCE-91/92/93 (импортирует развёрнутые модули; реальная
Telegram-доставка через **локальную Bot API-сессию** — прод-конфигурация
`build_local_api_session`, реальные PG/SQLite, реальные провайдеры) +
read-only журнальная волна + уборка. Секретов в отчёте/эвиденсе нет.
Сообщения — синтетические апдейты от пользователя `990002001` в рабочем чате
`-1002661910336`; harness запускался **от root** (прод-сервис работает под
root: `USER=root`, `NIK_READABLE=1`), т.е. скачивание файлов локального Bot
API проверено той же ФС-перспективой, что у прода.

Платный бюджет волны: **1 генерация + 1 обложка + 1 мем** — израсходован
ровно (global image_calls 16→19; chat 13→15; cover_used 1→2).

## Таблица 1–5 (факты)

| # | Сценарий | Факт | Статус |
|---|---|---|---|
| 1 | **(b) Положительное распознавание** | Ассет `69cbefd42e166aa6d68a819bb2f60da7` (mid **1166163**, 131641 B, image/jpeg, 800×600): **локальная сессия скачала файл OK** (in-process пре-чек, 131641 B) → reply «бот, что тут?» → `recognize_image` **target={chat,1166163}** → **ready** (5.1 с; auto-probe ok) → прод-воркер: джоба `44455202…` vision.media **completed** (09:09:27→09:09:47, download→decode→vision→store) → `mca_media_analyses` id=5 **ready**, revision 2, `nvidia/nemotron-3.5-super-vl:free`, **описание 388 симв.** («A dog with white, tan, and black fur… doghouse… pig… red brick wall… blue frame… dry leaves») → **доставка mid 1166167** (русское описание совпадает по содержанию: пёс/будка/свинья/кирпичная стена/синее окно/листья). `MCA_ANALYSES_TOTAL` **4→5** | **VERIFIED** |
| 2 | **(c) Postgen** | «бот, надо нарисовать картинку: жёлтый лимон на белом фоне» → **1 генерация** (`qwen-image-3-pro`, 939495 B, 54 с) → **фото mid 1166169** (sha12 `3ad9a2a644b7`) → `image_postgen_vision` → **failed/`vision_failed`** → **честный блок mid 1166170** («содержимое распознаванием не подтверждено»). Генерация+доставка — VERIFIED; позитивное описание по bitmap — не состоялось (честный блок, см. Finding 1) | **VERIFIED (генерация+доставка+честный блок)** |
| 3 | **(d) CFG-02C §Ф6** | **Витрина**: served `app.js` содержит «Обложки сводок здесь не учитываются» (1), served==disk (`SERVED_EQ=SAME`); `GET /api/workers/budget` (админ): `global.image_calls.cover_used`, chat-разбивка `cover{requests,success}`. **Изоляция (обложка)**: temp-предпосылка budgets ON + user daily=**0** + freq ON → **1 базовая обложка** (summary test-run `c9ac3c57…`, превью 1739973 B, sha12 `1c4b3d46034a`) → журнал `source='summary_cover:base'` **committed**; **chat_used 15→15 (не вырос)**, shared 18→19 (+1), cover_used 1→2 (+1), freq-заряды не тронуты. **Изоляция (мем)**: при daily=0 — **честный отказ** (0 платных вызовов, новых строк журнала нет, cover-агрегат не тронут); при daily=20 — **1 мем** → строка `source='direct'` committed, **chat 14→15**, cover-агрегат без изменений. **Восстановление**: точный возврат настроек (`config matches`, reserve `legacy/budgets_off`, freq `switch_off`) — дважды (C4 и C5) | **VERIFIED** |
| 4 | **(e) Экономика/журнал** | Δ бюджета: global 16→**19** (+3 = ген+мем+обложка), chat 13→**15** (+2), cover_used 1→**2** (+1); журнал: `direct`×2 + `summary_cover:base`×1 committed (+1 real-user `direct` в приватном чате); **SKIPS=0**, **402=0**, RuntimeWarning=0, `vision_capability_probe failed`=0; **ERR=2** — 1 Traceback (vision-фоновая задача, `OperationalError`) + 1 строка `INCIDENT` (watchdog takeover после `worker_lost`, авто-восстановление, NRestarts=0; см. Finding 3); маркер `[local-bot-api] файлы:`=**1**; миграции `complete`, `user_version=36` (**ΔDDL=0**); `VISION_DL_STAGE=6` — все `reason=vision_unreadable` (валидация/декод реальных форматов), ни одного путь-класса (см. Finding 4) | **VERIFIED** (с наблюдениями 3–4) |
| 5 | **(f) Уборка** | Удалено **9/9** (7 сообщений волны: 1166165/1166167/1166168/1166169/1166170/1166177/1166178 + долг ACCEPTANCE-93: 1166064/1166066) через Bot API (прод-сессия); residual smart_messages=**0**, residual bot_replies=**0**; safety-gate против реальных пользователей соблюдён (сообщения владельца/участников не тронуты); убраны 3 служебные строки `bot_replies` тестовых mid | **VERIFIED** |

## Five-facts (b) — полностью

1. **Target**: ассет `69cbefd4…`, mid 1166163; tool target `{chat_id:
   -1002661910336, message_id: 1166163}` (reply-на-фото);
2. **Цепочка**: пре-чек скачивания локальной сессией OK (131641 B,
   800×600) + джоба воркера `44455202c5ca4235aacf01ac1fbb7012`
   (vision.media, **completed**, 09:09:27→09:09:47) — download→decode→
   vision→store прошли; класс `FileNotFoundError`/`vision_unavailable`
   отсутствует;
3. **Анализ**: `mca_media_analyses` id=5, **ready**, revision 2, модель
   `nvidia/nemotron-3.5-super-vl:free`, `visual_description` 388 симв.;
4. **Доставка**: mid **1166167**, ответ бота описывает реальное содержимое
   фото (совпадает с анализом: пёс, будка, свинья, кирпичная стена, синее
   окно, листья);
5. **Счётчики**: `MCA_ANALYSES_TOTAL` **4→5** (базовая линия на старте
   волны = 4, а не 0: между пост-смоком 08:22Z и волной прод сам завершил
   4 анализа — фикс работает в проде; первый успешный download→store после
   выката — джоба `e9b400…` в 08:37:31Z).

## Второстепенные факты §Ф6 (числа)

- Обложка: `cover:-1002661910336:c9ac3c57…:base:2dd5bdafc001`
  (summary_cover:base, committed); user-день чата 15 не изменён.
- Мем: `-1002661910336:990940102:direct` (committed, delivery_failed=true —
  фото 1.58 МБ не доставлено, см. Finding 2); chat 14→15; freq 3→2→1.
- Генерация B2: `-1002661910336:1166168:direct` (committed).
- Предпосылки конфигурации (все временные, восстановлены): G0
  {budgets ON, daily 20, freq ON} → C2/C5 {daily 0, freq ON} → C3 {daily 20}
  → C4/C5 restore {budgets OFF (chat), daily 5 (global), freq OFF}.

## Findings / наблюдения (не блокеры релиза)

1. **Postgen-описание по bitmap не состоялось**: `image_postgen_vision` →
   `failed/vision_failed` (адаптер получил финальный bitmap 939495 B; вызов
   провайдера не дал подтверждённого результата). Поведение честное
   (блок «содержимое не подтверждено», mid 1166170), контур не заблокировал
   ход. Позитивная проверка требует новой генерации (бюджет волны — 1
   генерация). Класс `vision_failed` (не 502/429) — кандидат на отдельный
   разбор в след. окне.
2. **Доставка мема (фото 1.58 МБ) — `TelegramBadRequest`** при `sendPhoto`
   через локальную сессию (в отличие от 0.94 МБ B2-фото, доставленного OK).
   Обработка честная: `delivery_failed=true` в журнале, без повторного
   списания, честный блок mid 1166178. Детали ошибки R17-лог не раскрывает;
   наблюдение для инфра/лимитов отправки.
3. **SQLite-контеншн в окне волны**: 4×WARNING `database is locked`,
   1 Traceback (vision-фоновая задача, `OperationalError`, 09:14:12) и
   1 interrupted vision-джоба (`worker_lost`, 09:14:44) → watchdog
   `takeover_recovered` + `INCIDENT incident_opened` (авто-восстановление;
   NRestarts=0, сервис стабилен). Усилено приёмочными записями (harness от
   root); прод восстановился сам.
4. **`VISION_DL_STAGE=6`**: все 6 строк `stage=download` имеют
   `reason=vision_unreadable` (валидация/декод — реальные форматы чата),
   путь-класс (`vision_unavailable`/FileNotFound) с момента выката не
   наблюдается (кроме 1 джобы в 08:22:03 сразу после рестарта). За окно:
   7 vision-джоб completed, 6 failed(unreadable), 1 interrupted.
5. **C2-инцидент лейна**: первичная проверка обложки не отправила cover-POST
   из-за ожидания статуса `completed` (прод-ран отдаёт `ok`); обложка
   добита фикс-волной C5 (бюджет обложки не был потрачен). `c2-*.json`
   сохранён как есть, актуальный результат — `c5-cover-fix.json`.

## Журнал/стабильность/откат

- Journal since T0 (08:18:20Z, валидный прогон 09:24:16Z):
  `SKIPS=0`, `CLAIM_SLOW=25`/`CLAIM_TIMEOUT=3`/`MAINT_TIMEOUT=2` (WARNING —
  наблюдаемость busy-окна, пропусков тика нет), `ERR=2` (см. Finding 3),
  `402=0`, `RUNTIMEWARN=0`, `DB_LOCKED=4`, `VISION_PROBE_FAIL=0`,
  `LOCAL_BOT_API_MARKER=1`/`WARN=0`, миграции `complete user_version=36`.
- Сервис: MainPID=3657672 (без изменений за волну), NRestarts=0,
  active/running; healthz loopback+HTTPS `2.58.94`; HEAD `9072347b…`,
  tracked_mod=0.
- Откат релиза не требовался; рубежи прежние (`release/fix-2.58.93` и
  авто-рубеж `release/cfg1-2.58.88`).

## Файлы

- `p0-pre-state.json`, `g0-generation-ready.json` — вход/предпосылка;
- `b1-recognition.json` — (b), five-facts; `b2-postgen.json` — (c);
- `c1-showcase.json`, `c2-cover-isolation.json` (первичный, superseded),
  `c3-meme-isolation.json`, `c4-restore.json`, `c5-cover-fix.json` — (d);
- `e-economics.json` — (e); `journal-since-t0.txt` — журнал/БД (валидный);
- `f-cleanup-register.json`, `cleanup-register.json`,
  `cleanup-register-2.json` — (f); `summary.json` — сводка волны;
- `cover94-base.png` — превью базовой обложки (1739973 B, sha12
  `1c4b3d46034a`);
- `harness/` — исходники контролируемых вызовов (`accept94_*`,
  `accept94b_*`, `run_accept94*.py`); SSH-раннеры с креденшелами не
  промотированы — прецедент ACCEPTANCE-91/92.

## Остаток

- Позитивное postgen-описание по bitmap (нужна новая генерация) и
  доставка крупного мема — отдельные наблюдения, не блокируют приёмку (b) и
  изоляцию CFG-02C. Пункты карт — за леджером (карты лейном не правились).
