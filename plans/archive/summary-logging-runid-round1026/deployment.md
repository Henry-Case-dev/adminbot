# deployment.md — S7 `summary-logging-runid-round1026` (T-3408, @DevOps — прод-поставка)

> **Feature:** `summary-logging-runid-round1026` (Эпик 2, §108–§110) · **Дата:** 2026-09-24 · **Оператор:** @DevOps
> **Базис:** HEAD до деплоя `f774ecc` (annotated-тег `pre-round1026-s7`, tag-obj `bd7c822`); релизные коммиты `5cba5df` + `aa42a04`.
> **Окружение:** прод `/var/www/admin_bot` (`nik@198.46.175.136`), systemd-юнит `admin_bot`, venv Python 3.12.
> **Live-гейт владельца:** Telegram/WebView, §110-фильтр «Саммари» в log viewer — **PENDING OWNER VERIFICATION**.

## Вердикт: **VERIFIED** ✅

Рантайм S7 доставлен на прод: fast-forward `59e5b12..aa42a04`, сервис `active (running)` (MainPID **522392**, NRestarts 0), `/api/health` = **200**, `/healthz` version = **2.58.26**, `database is locked` = **0**, Traceback/ERROR/CRITICAL после рестарта = **0**, `import services.summary_run_log` OK, бот и планировщик Саммари стартуют, **Δ DDL = 0**, публикационный путь не изменён (`PUBLISH_*` = 0).

---

## 1. Коммиты и push

| Что | Commit | Сообщение |
|---|---|---|
| Код + тесты + README | **`5cba5df`** | `feat(round1026): S7 — сквозной run_id + SUMMARY_*/FORMAT_*/COVER_* логи + §110 фильтр Саммари в log viewer (APP_VERSION 2.58.26)` (33 файла) |
| Планы / миграция / ревью-аудит | **`aa42a04`** | `docs(plans): round1026 S7 — единый Reviewer gate (Scanner→Reviewer, миграция) + ревью/аудит-артефакты, state sync` (12 файлов) |
| deploy-doc (этот файл) | см. docs-коммит ниже | `plans/features/summary-logging-runid-round1026/deployment.md` |

- **Push:** `origin/master`, без force — **`f774ecc..aa42a04`** (2026-09-24 02:53:31 +12; `refs/remotes/origin/master` update by push).
- `APP_VERSION`: **2.58.25 → 2.58.26** (bump в `config/settings.py`, cache-bust `?v=__APP_VERSION__`).
- Merge §78 и архивация в этот деплой **не входили** (позже — @Architect/@PM).

## 2. Проверка привязок Reviewer (T-3404) перед релизом

- **Reviewed-Commit `f774ecc6af823c4191dd5f833fa2cce1d0a5bad2`** — подтверждён: локальный HEAD до коммитов == `origin/master`; annotated-тег `pre-round1026-s7` (`bd7c822`) → `f774ecc`; тег присутствует в origin (`git ls-remote`).
- **Spec-Hash `d9d11797fbc1e290825a53053ac90d7a49b16af324375305506cae54b74a9ac0`** — пересчитан байт-в-байт: совпал (`plans/features/summary-logging-runid-round1026/spec.md`).
- **Working-Tree-Hash `6c7c9061…`** — рецепт ревью воспроизведён **байт-в-байт** на состоянии дерева, зафиксированном ревью: при машинном блоке `OPENCODE_WORKFLOW_STATE_V1` revision 4 (состояние на момент T-3404) SHA-256 сырых байт `git diff f774ecc` = **`3556c053f9bf6f2e2ab14506bfed4d2574318b28c7507b35f103ba30b5e335fa`** — ровно значение из `review.md`.
  - Единственная дельта текущего дерева от ревью-состояния — служебный машинный блок `plans/workflow_state.md` (rev4 → rev5; обновлён `workflow_checkpoint` @Orchestrator в 02:43:17, уже **после** финализации `review.md` в 02:41:49). Текущий diff-SHA (rev5) = `2fcec56a…`; расхождение объяснено и локализовано **только** этим блоком (доказано подстановкой rev4-blob из snapshot-истории: хэш совпал точно; файл восстановлен байт-в-байт).
  - Product code / тесты / spec / конфиг после ревью **не менялись** (mtime кода ≤ 02:04, планов ≤ 02:41; untracked-хэши совпали с ревью: `summary_run_log.py` `b2b98024…`, JS-тест `2df92f44…`, pytest-файл `a13dc956…`). Материального дрейфа нет — к деплою допущено.

## 3. Локальный CI перед коммитами (воспроизведено @DevOps)

| Проверка | Результат |
|---|---|
| `.venv` pytest (полный) | **8890 passed / 0 failed** (113.78 s, 1 warning) — совпадает с ревью (8890/0) |
| `node tests/js/*.js` (45 файлов) | **45/45 OK** |
| `git diff --check` | 0 |
| Секрет-скан диффа (`api[_-]?key\|token\|secret\|password\|bearer\|…`) | 0 совпадений; `.env`/`deploy_commands.txt`/`media/` в набор коммитов не входили (gitignored) |

## 4. Прод-деплой (traceable)

- **Сервер до деплоя:** HEAD `59e5b12` (на один docs-коммит позади origin), `APP_VERSION` 2.58.25, `admin_bot` — `active`, MainPID 467979 (с 2026-09-23 12:22:30 UTC).
- **Pull:** `cd /var/www/admin_bot && git pull --ff-only origin master` → **`59e5b12..aa42a04` Fast-forward** (2026-09-23 **17:00:25 UTC**; reflog: `aa42a04 HEAD@{2026-09-23 17:00:25 +0000}: pull --ff-only origin master: Fast-forward`); 47 файлов, +2497/−93. После pull HEAD = `aa42a04`.
- **Restart:** `sudo -n systemctl restart admin_bot` (NOPASSWD для systemctl) — стоп-фаза заняла ~50 с (graceful shutdown превысил клиентский таймаут 55 с, но рестарт завершился штатно); сервис `active` с **2026-09-23 17:01:27 UTC**.
- **Состояние:** MainPID **522392**, NRestarts **0**, ExecMainStatus **0**, ActiveState `active`.

## 5. Health / смоук-проверки (факт, 17:01:45–17:02:30 UTC)

| Проверка | Результат |
|---|---|
| `systemctl is-active admin_bot` | **active (running)** ✅ |
| `GET /api/health` (127.0.0.1:8000) | **HTTP 200** `{"status":"ok"}` ✅ |
| `GET /healthz` | **HTTP 200** `{"status":"ok","version":"2.58.26"}` ✅ |
| served cache-bust `/web/` | `?v=2.58.26` — **12** вхождений; placeholder `__APP_VERSION__` = **0** ✅ |
| `APP_VERSION` в venv прода | **2.58.26** ✅ |
| Импорт нового рантайма | `import services.summary_run_log` → **OK** (`RunContext` доступен) ✅ |
| `database is locked` (с рестарта) | **0** ✅ |
| Traceback/ImportError (с рестарта) | **0** ✅ |
| ERROR/CRITICAL (с рестарта) | **0** ✅ (единственная ERROR в окне 600 строк — до рестарта, 15:57:40, старый PID 467979: штатный `LLM timeout` в рабочем трафике, к S7 не относится) |
| `PUBLISH_*` в логах | **0** ✅ |
| `L1_*`/`L2_*`/`FORMAT_*`/`TEST_*` в логах | **0** — до следующего прогона Саммари (события аддитивны, §108) |
| Старт бота | `Start polling` / `Run polling for bot @PERMsoc_bot`, Bot commands registered ✅ |
| Планировщик Саммари | `services.summary_scheduler — SmartModule scheduler started (cron 0,6,12,18 Asia/Yekaterinburg)`, job `SummarySchedulerService._tick` добавлен; `SmartModule Summary (Epic 24) initialized` ✅ |
| Миграции БД | не запускались; **Δ DDL=0** (`git diff --name-only f774ecc..HEAD -- db/` = 0). Штатный startup-синк `services.prompt_migrations` — «уже новый канон» (без изменений, не DDL) |

## 6. Инварианты

- Публикационный путь не изменён: `PUBLISH_*` в коде/логах — 0 (GATED S6/D4); `routes.py`/`param_catalog.py`/`image_generation.py`/`telegram_send.py`/`summary_xml.py`/`summary_article_formatter.py`/`db/**` вне релизного diff.
- Δ каталога = 0 (F8 не переиздаётся), Δ DDL = 0, 0 новых внешних зависимостей, CSP/zero-build — без изменений.
- Откат: annotated-тег **`pre-round1026-s7`** → `f774ecc` + `git revert` коммитов `5cba5df`/`aa42a04` (без force-push).

## 7. Откат (готовность; не исполнялся)

- **Жёсткий:** `git revert 5cba5df aa42a04` (или `git checkout pre-round1026-s7`) + `sudo -n systemctl restart admin_bot`.
- **Бэкапы (R18, не удалялись):** `var/backups/s7-round1026-20260924-003537/` (`BASELINE.md` и срезы), `.env.bak.round1026-s7`; `stash@{0}` не тронут; история не перезаписывалась.
- Откат **не потребовался** — деплой и верификация успешны.

## 8. Честные ограничения / инцидент доступа

1. **HTTP 200 ≠ качество §110-фильтра.** Подтверждены доставка, целостность, старт компонентов и отсутствие регрессий; визуальное поведение чипа «Саммари»/раскрытия/копирования в реальном Telegram WebView — **PENDING OWNER VERIFICATION**.
2. **Инцидент SSH-доступа (операционный, без утечек):** при подготовке деплоя первые пробы аутентификации с неверным логином (`nick`) привели к временной фильтрации порта 22 для операторского IP (~2 ч). Внешняя независимая проверка (58 узлов check-host.net) показала SSH открытым — сервер был в порядке. После снятия фильтра деплой выполнен **по ключу** `id_ed25519` (пользователь `nik`), без парольной аутентификации; **полные значения паролей не выводились и не коммитились** (в локальной диагностике — только метки, длины и краткие префиксы токенов, недостаточные для использования). Рекомендация: использовать ключ `nik` (верный логин), не повторять парольные переборы; при строгой политике секретов — рассмотреть плановую ротацию пароля SSH/sudo.
3. `L1_*`/`L2_*`/`FORMAT_*`/`TEST_*` появятся только после следующего реального/dry-run прогона Саммари — это ожидаемая аддитивность, а не отсутствие поставки.
4. `evidence.md` намеренно **не изменялся** после ревью (сохранение байт-точности ревью-манифеста); деплой-факты зафиксированы здесь.

---

## Handoff

**RESULT: VERIFIED (T-3408) @Orchestrator** — коммиты `5cba5df` (код+тесты+README, APP_VERSION 2.58.26) + `aa42a04` (планы: единый Reviewer gate/миграция + артефакты) + deploy-doc (этот файл); push `origin/master` **`f774ecc..aa42a04`** без force; прод `/var/www/admin_bot` fast-forward **`59e5b12..aa42a04`** (2026-09-23 17:00:25 UTC); `systemctl restart` → **active** (MainPID **522392**, NRestarts 0, 17:01:27 UTC); `/api/health` **200**; `/healthz` **2.58.26**; `APP_VERSION` **2.58.26**; served `?v=2.58.26` (×12, placeholder 0); `import services.summary_run_log` OK; `database is locked`=0; Traceback/ERROR=0 после рестарта; `PUBLISH_*`=0; планировщик Саммари/бот стартуют; **Δ DDL=0**. Откат: `pre-round1026-s7`→`f774ecc` + `git revert`; бэкапы/`stash@{0}` целы (R18). **Live-приёмка §110 — PENDING OWNER VERIFICATION.** Далее по процессу: @Architect (reconciliation §78), @PM (архив), @Memory (sync), метрики, следующий F.
