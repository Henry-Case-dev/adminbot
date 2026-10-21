# Deploy 2.58.107 (REL-258107) — 21.10.2026

**Результат: VERIFIED.** Кандидат `3a178c6c` (REV-REL-258107 Approved) задеплоен на прод
с плановым рестартом; версия на проде — 2.58.107, все обязательные postdeploy-пробки зелёные.

## Источник и привязка
- `DEPLOY_SOURCE`: origin/master @ `3a178c6c` (запушен до деплоя), прод — `git pull --ff-only`.
- `server HEAD` подтверждён: `3a178c6c0c5fa5bd37092df251de6eafc75330ba` (pre-pull: `dad9afce` = 2.58.106).
- Runtime-дельта поезда: 21 файл (config + 20 services); web/handlers/migrations/scripts = 0;
  ΔDDL = 0 (schema v37 не менялась).
- Blob-идентичность: **21/21 OK** — рабочее дерево прода == HEAD == кандидату по всем runtime-файлам.

## Плановый рестарт — санкционированное отклонение
Обычный ритм релизов этого проекта — без рестарта. Здесь рестарт **обязателен и одобрен
ревьюером** (review-rel.md): `FACTORY_SET` — runtime-константа процесса, горячее применение
новых канонов невозможно. Прецедент — soul-release-prep. Рестарт выполнен один раз в T0,
`NRestarts=0` до и после (автоперезапусков нет), `ExecMainStatus=0`.

## Хронология (UTC)
| время | событие |
|---|---|
| 14:33:43 | recon (read-only): прод 2.58.106, PID 192071, NRestarts 0, healthz 200 |
| 14:35:46 | T0: pull --ff-only → `3a178c6c`, 21/21 blob OK, restart, PID 240598 |
| ~14:36:02–21 | бот поднялся: Started → Bot started → Start polling |
| ~14:36:30 | healthz 443: `200 {"status":"ok","version":"2.58.107"}` |
| 14:40:08 | final (read-only): пробы ниже; loopback healthz 200/2.58.107 |

## Верификация
- **healthz**: loopback и публичный 443 — `200`, `version 2.58.107`.
- **Журнал с T0**: 326 строк, **0 traceback, 0 CRITICAL**; бот-старт чистый.
  Миграции: 16 строк `[prompt_migration]`, ошибок 0 — 12× «кастом юзера — НЕ трогаем»,
  4× «уже новый канон» (перезаписей кастома нет).
- **Fingerprint канонов (read-only проба)**: runtime-константа `FACTORY_SET_SHA256_12` ==
  `factory_set_fingerprint()` == **`c19d35a1c093`** — новый канонический набор реально
  загружен процессом (рестарт сделал своё дело).
- **Effective-сборка (read-only, 0 LLM/0 DB)**: Core без мат-темы в effective-пейлоаде
  (full/compact/PREV-документ), Expression-директива «выраженным использованием мата»
  присутствует, гвард superseded-core активен (`superseded_fields=(full_text, compact_text)`),
  вербализатор чист. Всё True, fingerprint `c19d35a1c093`.
- **7 кастомных ключей владельца (CFG07A)**: SELECT-сверка sha256_12+len против замера
  2.58.101 (cfg-07a/deploy.md F1) — **7/7 EQ_BASELINE**, хранимые байты не тронуты.

## Postdeploy-наблюдение (по плану ревьюера, НЕ гейт)
Контуры L1_PLAN/expression_diag/factcheck-трассы на месте; реальное поведение придёт
со следующими живыми сообщениями (окно наблюдения 48 ч). Ожидания нет, релиз завершён.

## Откат
Ветка `release/fix-2.58.106` = `dad9afce` запушена в origin. Процедура:
`git -C /var/www/admin_bot checkout -f release/fix-2.58.106 && sudo systemctl restart admin_bot`.
ΔDDL=0, миграций данных нет — откат чистый, потерь нет.

## Дисциплина и безопасность
SSH-коннектов: 3 (recon → main → final, паузы 123 с / 262 с, одиночный nik, без поллеров);
HTTP/443-пробы вне лимита. Секреты не печатались и в evidence не попали.
Сообщений в реальные чаты: **0**.

## Сырые прогоны
`OPENCODE_WORKFLOW_SCRATCH/rel-258107/` (recon-run.txt, main-run.txt, final-run.txt, deploy107.py, probe_*.py).
