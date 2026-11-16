# Release train log — `2.58.206` (P0-PROD-DISK-01)

Локальное время сборки: 16.11.2026, UTC+12. Деплой не выполнялся.

1. **База.** Проверены Git root/HEAD и кандидаты: `bca18c1e` (2.58.205,
   schema 47, DDL 0), `122b47de` (retention, один коммит от базы),
   `0cbc5459` (UI, один коммит от базы), шаблон bump `bfcccb38`.
   Старая ветка `release/mod-acl-m21-2.58.206` исключена.
2. **Worktree.** Создан от `bca18c1e` путь
   `.../worktrees/c742e4de9e92c489/p0-prod-disk-01-2a6b1cdc3425-df026980`,
   ветка `release/p0-prod-disk-2.58.206`, unit
   `p0-prod-disk-release-2.58.206` зарегистрирован housekeeping.
3. **Retention.** `git merge --ff-only 122b47de` → HEAD `122b47de`.
4. **UI.** `git cherry-pick 0cbc5459` → `da44543d`, конфликтов нет.
5. **Bump.** `2.58.205 → 2.58.206` по шаблону: 30 файлов / 31 строка,
   `ebd0160b`; исторический текст `Prior 2.58.205` сохранён, BOM/CRLF
   сохранены.
6. **Статика.** DDL 0, `MigrationStep` 47→47, свежая БД `user_version=47`
   (101 таблица), каталог 645/121/119/22, Settings fields 472,
   `deploy_v2.9.2.py` не тронут, новых флагов/hot_config/composer/migrations
   нет.
7. **Тесты.** Retention focused 112 passed; UI+Status 411 passed;
   UI node 7 OK; Playwright 8/8; pin-guard 856 passed / 4 pre-existing
   (те же 4 воспроизведены на `bca18c1e`); JS pins 4 OK; broad 778 passed.
8. **Manifest.** `tools/release_manifest.py --dry-run` на `ebd0160b`:
   `version=2.58.206`, `dirty_tracked=false`,
   `release_branch=release/p0-prod-disk-2.58.206`.
9. **Evidence.** Добавлены `assembly.md`, `tests-2.58.206.json`,
   `manifest-dry-run.json`, `rollback.json`, `train-log.md`,
   `ui-playwright-2.58.206.json`.
10. **Push.** После evidence-коммита — обычный push без force.
11. **Очистка.** Временный base-check worktree `bca18c1e` удалён,
    unit-check complete; probe-скрипты закроются вместе с tool-owned run;
    релизный worktree сохраняется для Reviewer/DevOps.

Статус: **REVIEW**, production не менялся, VERIFIED не заявлен.
