# Deploy 2.58.105 — VERIFIED @ a6246e33

ЛANE: DEVOPS-DEPLOY-258105 · Release review: REV-REL-258105 **Approved**
(`review-rel.md`) · Дата деплоя: 2026-10-21, T0 = 08:32:14Z

## Что задеплоено

Поезд 2.58.105 (bump-only релиз): фикс мини-линзы fullscreen-кнопки
`6c1dea40` (web-only U08.4d/U08.5.1, класс `.lg-mini-lens`, binding
`toggleFullscreen`/FullscreenPolicy, REV-MINILENS Approved) + prep `7e42c7ee`
+ docs `7a70e41a` (soul-1, runtime не трогает) + bump `a6246e33` (31-файловый
procedure set, SET EQUAL proc-104, dDDL=0, fingerprint `037080375ac8` intact).

- **DEPLOY_SOURCE**: `origin/master @ a6246e33` (запушен перед деплоем);
  на сервере `git fetch` + `git checkout -B master origin/master`.
- **MUTABLE_WORKTREE_REQUIRED**: no (иммутабельный коммит; на сервере
  tracked_mod=0 после checkout).
- Runtime-дельта 8ea6ed4e..a6246e33 — ровно 4 файла: `config/settings.py`
  (версия), `web/app.js`, `web/index.html`, `web/static/app.css`.
  ΔDDL = 0 (services/database.py, scripts/ — без изменений), миграций нет
  (журнальные migration-строки — no-op «уже новый канон/дефолт»).
- Откат: ветка `release/fix-2.58.104` = `8ea6ed4e` (создана и запушена,
  подтверждена на сервере как origin-реф). Процедура: `git checkout -f 8ea6ed4e`
  + `sudo systemctl restart admin_bot`. DDL-откат не требуется.

## Верификация (наблюдаемое, не декларации)

| Проверка | Результат |
|---|---|
| Сервер HEAD после checkout | `a6246e33`, tracked_mod=0 |
| healthz loopback:8000 | 200 `{"status":"ok","version":"2.58.105"}` |
| healthz внешний 443 (admin-bot.duckdns.org) | 200 `2.58.105` |
| Сервис | active/running, MainPID=167058, **NRestarts=0**, старт 08:32:26 UTC, ExecMainStatus=0 |
| Сырые байты на диске (sha256_12) | app.js `b8bc731fab83`, index.html `31d3c30ec25b`, app.css `86b20be01644`, settings.py `96079207f49f`; контролы README `2e68f44858ed`, database.py `b7fdd7615a52` |
| Git blob (sha1_12) | app.js `d218ea8b`, index.html `ed752b3c`, app.css `8f2eb0b3` — 1:1 с ревью-байндом |
| Отдаваемые байты (loopback и внешний 443) | app.js `b8bc731fab83` (lg-mini-lens x3); app.css `86b20be01644` (.lg-mini-lens x9); index.html `3b2d62b691ff` = сырой файл + подстановка `__APP_VERSION__`→`2.58.105` (by design, `web/app.py::_render_index`), класс `header-fs-btn lg-mini-lens` на кнопке — **присутствует 1:1** |
| Журнал с T0 (415 строк) | **0 CRITICAL / 0 Traceback**; ERR=3 — только pre-existing `safe_fetch too_many_bytes` (runtime-инструмент, не деплой); prompt/config migration — no-op, 0 ошибок; graceful stop → старт → polling 08:32:44 |
| Роуты | /healthz 200, /web/ 200 |

## Постдеплой-проба мини-линзы (техническая)

HTTPS-443 проба отдаваемых байтов, без браузера и без сообщений в чаты
(`OPENCODE_WORKFLOW_SCRATCH/deploy-258105/probe443.py` → `probe443-105.txt`):
класс мини-линзы присутствует на прод-байтах, blob-сверки app.js/index.html/
app.css совпали с локальным кандидатом 1:1. Визуальная live-проверка 1:1 —
владельцу добровольно (`plans/owner_live_checks.md`), не гейт.

## Биндинг карты

`requirements-map.json`: U08.4d и U08.5.1 → **VERIFIED @ deployed a6246e33**
(deploy evidence + blob-сверки); `deployed_commit` карты → `a6246e33`.
`candidate_commit` карты оставлен `0b7a0aca` (конвенция review-tailbind:
legacy-строки привязаны к своим wave-кандидатам, перебиндинг запрещён —
прецедент release-25883).

## Гейт

`requirements_gate.py check --stage release --candidate a6246e33
--deployed-commit a6246e33` → exit 1 (`gate-release-check.txt`) — **pre-existing
convention residual** legacy-карты v6 (строки, привязанные к историческим
wave-кандидатам + BLOCKED_REAL_HUMAN_GATE owner-наблюдения), тот же класс RED,
что задокументирован в release-25883/CFG-06. Для поезда 2.58.105 release-биндинг
— REV-REL-258105 Approved + deploy evidence на задеплоенном коммите;
U08.4d/U08.5.1 теперь биндятся чисто к a6246e33 (кандидат-мисматч для них устранён).

## Инциденты по ходу (честно)

1. Попытка 1 (08:26): аборт гейтов SHA/BLOB **до рестарта** — баг локального
   пробера (`dict(re.findall)` инвертировал hash/path). Серверные хэши были
   корректны; дерево безопасно восстановлено в 8ea6ed4e, прод остался живым
   на 2.58.104. Парсер исправлен и доказан на реальном выводе.
2. Попытка 2 (08:32): после успешного рестарта «mismatch» отдаваемого
   index.html — ошибка ожидания пробы (сырой файл vs шаблонизированная отдача
   с подстановкой версии). Ожидаемый rendered-хэш вычислен локально =
   `3b2d62b691ff` — ровно то, что отдаёт прод. Сервис продолжал работать на
   2.58.105, откат не понадобился.

## Дисциплина SSH/fail2ban

4 коннекта (recon → main#1 abort → main#2 → final verify), каждый ≥90с от
предыдущего, одиночный логин `nik`, пароли только через stdin, без поллеров и
ретраев. HTTP/443-пробы — по политике без ограничений.

## Итог

**VERIFIED**: кандидат a6246e33 задеплоен байт-в-байт, обязательные
деплой/live-пробы пройдены, откат-состояние известно (8ea6ed4e, одношаговый).
Эвиденс: `deploy.json` (машина), `journal105-since-T0.raw`,
`probe443-105.txt`, `recon105.txt`, `main105-run.txt`, `final105-run.txt`
(последние три — в OPENCODE_WORKFLOW_SCRATCH/deploy-258105/).
