# Deploy 2.58.109 — VERIFIED @ a1d8bd62

LANE: DEVOPS-DEPLOY-258109 · Release review: REV-REL-258109 **Approved**
(`release-258109/review-rel.md`) · Дата деплоя: 2026-10-21, T0 = 19:59:10Z (epoch 1792612750).

## Состав и источник

Поезд 2.58.109 (точечный фикс): FIX-INITREPLY `77985666`
(`services/direct_chat_service.py` — reply_to_message_id binding для адресных
инициативных ответов) + docs `1e3e5949` + bump `a1d8bd62` (31-file proc set,
SET EQUAL proc-108, dDDL=0, fingerprint `c19d35a1c093` intact).

- **DEPLOY_SOURCE**: `origin/master @ a1d8bd62` (запушен до деплоя);
  на сервере `git fetch` + `git checkout -B master origin/master`.
- **MUTABLE_WORKTREE_REQUIRED**: no (fetch+checkout+рестарт; на сервере
  tracked_mod=0 после checkout).
- Runtime-дельта be60041f..a1d8bd62 = ровно 2 файла: `config/settings.py`
  (маркер версии), `services/direct_chat_service.py` (фикс). web/ и
  migrations/ — 0 файлов; ΔDDL = 0 (database.py b7fdd7615a52 без изменений,
  schema v37), миграции БД не запускались (prompt_migration no-op only).
- Откат: ветка `release/fix-2.58.108` = `be60041f`, создана и запушена в
  origin **до** деплоя; сервер подтвердил `origin/release/fix-2.58.108`
  == be60041f. Процедура: `git checkout -f be60041f` +
  `sudo systemctl restart admin_bot`. DDL-реверса не требуется.

## Верификация (сервер-наблюдаемая)

| Проверка | Результат |
|---|---|
| Прод-HEAD после checkout | `a1d8bd62`, tracked_mod=0 |
| healthz loopback:8000 | 200 `{"status":"ok","version":"2.58.109"}` |
| healthz внешний 443 (admin-bot.duckdns.org) | 200 `2.58.109` |
| Сервис | active/running, MainPID=304990, **NRestarts=0**, старт 19:59:23 UTC, ExecMainStatus=0 |
| Runtime-хэши (sha256_12) | settings.py `54af94a38923`, direct_chat_service.py `a8ac05bf111e`, README `45e0200ef89f`, database.py `b7fdd7615a52` (контроль dDDL=0) |
| Git blob (sha1_12) | settings.py `462b7ed6376f`, direct_chat_service.py `7ffb9b89468d` — 1:1 с кандидатом |
| Финальная blob-сверка (20:02:10Z, отдельно от деплоя) | SHA_DC `a8ac05bf111e` + BLOB_DC `7ffb9b89468d` == кандидату; REPLY_KWARG=5 |
| Маркеры | APP_VERSION "2.58.109" x1; F8-meta HEAD `1e3e5949` x1; `_initiative_reply_target` x2; fingerprint `c19d35a1c093` x2 |
| Журнал с T0 (212 строк) | **0 CRITICAL / 0 Traceback / 0 ERROR**; RuntimeWarning=0; prompt_migration 16 строк no-op, 0 ошибок |
| Роуты (loopback) | /healthz 200, /web/ 200; rendered index `v=2.58.109` x15 |

## Postdeploy-контур (read-only, без генерации сообщений)

- **Reply-биндинг инициативных ответов — активна с выката**: скан
  `config/settings.py` на initreply/init_reply-флаги = **0 совпадений** —
  конфиг-флагов у фичи нет, она включена всегда при наличии адресата
  (fail-open best-effort). Живое подтверждение (реальная инициатива уйдёт
  reply-цепочкой) — 48ч телеметрия, **не гейт**; ноль сообщений в реальные
  чаты в рамках деплоя отправлено не было (PET_PROJECT-правило).
- Инициативный контур поднят: journal 19:59:40 UTC
  `Added job "MemoryMaintenanceService._tick_initiative_observer"`.
- initreply-строк в журнале с T0 нет — ожидаемо: фикс проявляется только при
  реальных адресных инициативах.

## SSH-дисциплина (fail2ban)

3 коннекта, одиночный nik, без поллеров/ретраев:
recon (read-only) 19:57:07Z → пауза 118 с → main-деплой 19:59:05Z (fetch,
gates, checkout, T0, рестарт, health, journal — один канал) → пауза ~145 с →
final verify (read-only) 20:02:10Z. HTTP/443-пробы — с локальной машины,
вне SSH-бюджета. Пропусков/провокаций нет.

## Release gate

`requirements_gate.py check --stage release --candidate a1d8bd62
--deployed-commit a1d8bd62` → exit 1, `inventory=148 errors=282`
(`release-258109/release-gate.txt`). Задокументированный legacy-класс,
идентичен release-25883/258105: строки openworkflow-coverage-v1 карты
привязаны к историческим кандидатам волн, ребиндинг запрещён
review-tailbind. Поезд 2.58.109 не матчит ни одну строку карты
(легитимный подтверждённый дефект по брику лейна). Поезд-левел биндинг =
REV-REL-258109 Approved + deploy evidence, привязанная к задеплоенному
коммиту; `deployed_commit` карты обновлён на a1d8bd62.

## Итог

Деплой 2.58.109 VERIFIED @ a1d8bd62. Откат-состояние известно и проверено
(ветка запушена, SHA подтверждён сервером). Блокеров доставки нет.
