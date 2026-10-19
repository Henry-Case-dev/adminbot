# REV-REL-25894 — вердикт (релиз 2.58.94: VISION-DL-FIX — скачивание файлов локального Bot API)

Независимый аудит релиз-пакета. Режим read-only: деплой и push НЕ выполнялись;
этот коммит — только данный документ. Прод до релиза — 2.58.93 @ `b4d30cab`.

Кандидат: bump `70659be3` (код DL-FIX `7c2998b1`; docs-only `34476660`).
Вход: отчёт `release-25894-report.md` (коммит `c06cc3d8`), evidence
`evidence/release-25894/**`, `deploy_25894.py` (`4eb764c8ba0f`),
`rel94_final.sh` (`b788f5e79dfd`), ветка `release/fix-2.58.93` @ `b4d30cab`.
Верификация — в изолированном worktree `wt` @ `70659be3` + мои прогоны.

## 1. Bump — подтверждён

31 файл, +33/−33; каждая изменённая строка — только версия `2.58.93 → 2.58.94`
или HEAD-штамп meta (`bump-verify.txt` + моя независимая проверка).
`2.58.93` вне plans — **0**, включая escaped-пины (`2\.58\.93` → `2\.58\.94`).
`APP_VERSION = "2.58.94"`, meta: 2.58.94 + HEAD `7c2998b1`, README v2.58.94.
HEAD-штамп meta = последний КОД-коммит (`7c2998b1`), за ним docs-only
`34476660` (plans-only, deploy-evidence 2.58.93) — обоснование принято
(прецедент 2.58.91 `88593e9a` при docs-only хвосте).

## 2. Дельта `b4d30cab..HEAD` — изоляция подтверждена

49 файлов = 16 plans + 33 non-plans (3 runtime + 29 tests + README).
Runtime-скоуп скрипта (`config services web handlers` + `bot.py`) = **3**
(`bot.py`, `services/local_bot_api.py` (новый), `config/settings.py`) ==
вайтлист (set-equality — мой прогон + `check_deploy_25894.py`).
Sanity-трио (telegram_send / fullscreen-policy / prompt_composer) — байт-в-байт
(в дельте нет, значения совпадают с прод-2.58.93); строки 3 файлов +166/−6.
**Расширение дифф-фильтра на `bot.py` (корень)** — обосновано и точечно:
`bot.py` — runtime-файл в корне, вне прежнего скоупа, и он реально изменён этим
релизом; расширение закрывает именно этот gap. Остаточный gap (прочие
root-файлы вне скоупа) — пре-существующий, не введён этим релизом; для
контролируемого одиночного push приемлемо (плюс B3-ancestor, TRACKED_MOD_AFTER=0
и EXPECT12-пины 8 артефактов). Дырой не является.

## 3. Числа — перепроверены (лог + мои прогоны)

- Полный pytest (чистый, `pytest-command.txt`: CWD=wt, HEAD=70659be3):
  **9 failed / 14473 passed** (741.60s). FAILED-список = ровно 9 пре-сущ.:
  asap7×2, mca01, t5150×5, history_cli-worktree-артефакт. Баланс с 2.58.93
  (10f/14465p): +7 = новые DL-тесты, +1p/−1f = env-флейк random_source в этом
  прогоне НЕ сработал — атрибуция честная, новых падений нет.
- Мои прогоны (все точные): DL-контракт **7**; свод-195 **195**;
  media-профиль (25 файлов) **741**; t5150 **5 failed / 2 passed**
  (пре-сущ.); F8 **29**; каталог **579 == REGISTRY**; JS-sweep **88/0**.
- Контракт на реальном aiogram 3.29.1: точка применения —
  `aiogram/client/bot.py: wrap_local_file.to_local(file_path)`; поля
  `TelegramAPIServer` включают `wrap_local_file`; тест
  `test_download_reads_host_path_not_container_path` гоняет настоящий
  `Bot.download`: с фиксом — payload из host-каталога, без маппинга —
  `FileNotFoundError` (RED прод-симптома). `HostFilesPathWrapper` fail-safe
  (relative/чужой абсолютный/корень/""/None — как есть) и совпадает по
  нормализации с `media_download.normalize_api_file_path`; `bot.py` без
  прямых `AiohttpSession(` (0).

## 4. Деплой-скрипт (офлайн) — NF-фиксы сохранены

`check_deploy_25894.py` **EXIT 0** (мой прогон): вайтлист 3/3 == дельта,
BUMP == HEAD. **Все 8 хэшей EXPECT12** сверил независимо из git-объекта
`70659be3` — 8/8 OK (bot.py `f9d8306e6034`, local_bot_api `a97e1d3eeab0`,
settings `94b22606a68d`, README `f3acd3e0645b`, meta `0f622688098f` + sanity-3).
Константы: `PROD_REF=b4d30cab`, `PROD_BRANCH=release/fix-2.58.93`,
`BUMP=70659be3`, `ROLLBACK=release/cfg1-2.58.88`/2.58.88, `EXPECT_VER=2.58.94`,
`EXPECT_PAGE_VER=15`, `EXPECT_SUBST_CSS=2`. NF-фиксы 25891/25892/25893 в коде:
`checked_out`-гейт, set-equality, tree-restore → прод-линия 2.58.93
(`release/fix-2.58.93`/detach, без downgrade), WARNINGS-summary, SERVED_EQ,
scrub секретов, B3-ancestor fail-closed, D1-хэши → abort, T0/healthz≠2.58.94 →
`_rb`. **F5-стадия** `F5_local_bot_api_marker` — `grep '[local-bot-api] файлы:'`
since T0 (ожидание ≥1). `rel94_final.sh`: `LOCAL_BOT_API_MARKER` ≥1 +
`LOCAL_BOT_API_WARN`=0, 8 DL-FIX-ожиданий маркеров — я сверил все построчно
против кандидата (совпали), **read-only счётчики `mca_media_analyses`**
(TOTAL + BY_STATUS), `VISION_DL_STAGE`, SKIPS=0, регрессионные маркеры
CFG-02C/2.58.92/2.58.91, SERVED_EQ, `/api/workers/budget`, `/api/vision/state`.

## 5. Док/чеклист §4 — соответствуют

Состав: DL-FIX (фабрика `build_local_api_session` + `HostFilesPathWrapper`:
контейнерный путь → host-каталог bind-mount; `bot.py` — только через фабрику;
стартовая диагностика R17-safe; облачный путь не тронут; Δ DDL=0, Δ каталога=0)
+ доки + bump. Откат: `release/fix-2.58.93` (abort до рестарта, без рестарта) →
`fix-2.58.92` → штатный `cfg1-2.58.88` (после рестарта); альтернатива —
`DOWNLOAD_ENABLED=false` (легаси-облачный путь). §4: (a) healthz/T0/SKIPS=0 +
обязательный маркер DL-FIX; (b) ПОЛОЖИТЕЛЬНОЕ распознавание: цепочка
download→decode→vision→store, наполнение `mca_media_analyses`, доставка
five-facts; (c) postgen по финальному bitmap (не эхо); (d) уборка; (e)
экономика/R17. Риски честные: host-чтение под root (тот же каталог, что у
голосовых/видео; инфра-инструкция при смене пользователя); HTTP-эндпоинт
локала = 404 (не нужен); проба «B» под SSH-пользователем — PermissionError,
закрывается приёмкой (b).

## Наблюдения (не блокирующие)

* Докстринг DL-теста говорит «aiogram 3.31», в venv установлен 3.29.1 —
  косметика; контракт проверен живьём на установленной версии.
* `markers-candidate.txt` показывает `AiohttpSession` (подстрока) = 1 — это
  упоминание в комментарии `bot.py`; проверка rel94_final использует
  `AiohttpSession(` = 0 — согласовано, не проблема.
* Остаточный root-файловый gap скоупа (см. §2) — пре-существующий.

## Леджер/статус

Пакет **готов к контролируемому деплою**. Живые пункты §4 — **READY_FOR_LIVE**:
(a) healthz 2.58.94/SKIPS=0/маркер; (b) положительное распознавание + наполнение
analyses + доставка (главная приёмка DL-FIX); (c) postgen по bitmap; (d) уборка;
(e) экономика. Выполняет DevOps/приёмка ПОСЛЕ выката; родительский DONE — только
после них. Предусловие: push `master` (B3 fail-closed); желательно push
`release/fix-2.58.93` (иначе tree-restore — detach на `b4d30cab`; объект на
проде есть).

## Вердикт

**Approved** — релиз-пакет 2.58.94 (bump `70659be3`, DL-FIX `7c2998b1`) проверен:
bump версионно-чистый, дельта изолирована (3/3, расширение скоупа на `bot.py`
обосновано), хэши 8/8, числа 14473/9 с честной атрибуцией, контракт фикса
подтверждён на реальном aiogram, скрипт с NF-фиксами и fail-closed гейтами,
чеклист/откат полны. Деплой — за DevOps/Orchestrator; DONE — только после §4.
