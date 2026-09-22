# deployment.md — HOTFIX8 `hotfix8-shell-glass-aurora-round1025`

> **Статус:** `NOT_APPLICABLE` (для подзадачи **T-2745** — pre-change baseline; релиз **не выполнялся**).
> **Задача:** T-2745 [@DevOps], Блок 0 «Точка отката и baseline перед кодом». **Дата:** 22.09.2026, 18:00 (`+12:00`).

## Почему NOT_APPLICABLE

T-2745 — подготовительный шаг **до** правок (rollback-точка, бэкап, baseline). Задеплоенного артефакта в этой задаче нет: изменения кода HOTFIX8 появятся позже, а их прод-выпуск выполняет **T-2787** [@DevOps] (Step 9: push, прод `/var/www/admin_bot`, `systemctl restart`, health, `APP_VERSION` 2.58.11, `VERIFIED`). Поэтому текущий файл фиксирует checkpoint и будет **заменён/дополнен** записью T-2787 при релизе.

## Что сделано (T-2745)

| Артефакт | Значение |
|---|---|
| Тег отката | `pre-round1025-hotfix8` → `a1e6db3141dc81843309400af66a06f363ddadd3` (запушен в origin) |
| Бэкап (git archive HEAD) | `var/backups/hotfix8-round1025-20260922-180028/` (5 файлов + `BASELINE.md`) |
| Бэкап окружения | `.env.bak.round1025-hotfix8` (размер/SHA256 == `.env`; содержимое не печаталось) |
| Baseline pytest | **8251 passed / 0 failed / 0 skipped** (перепроверено; 1 warning Starlette, не блокер) |
| Baseline прочего | `APP_VERSION` **2.58.10**; JS **32/32** `node --check` OK; `git diff --check` 0; Δ DDL=0; Δ каталога=0 (459/98/96/21/418) |
| Git | ничего не коммитилось; `current_task.md`/`deploy_commands.txt` не изменялись (R18) |

> Полные детали, хэши и оговорки — в `BASELINE.md` каталога бэкапа. Прод в T-2745 не опрашивался (нет авторизации на SSH в этой подзадаче); `database is locked`=0 — по последнему подтверждённому состоянию F5.

## Handoff

**RESULT: baseline готов (deploy = NOT_APPLICABLE для T-2745).** Точка отката, бэкап и baseline зафиксированы; релиз HOTFIX8 — за T-2787 после зелёного регресса/ревью.
