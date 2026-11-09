# Deploy 2.58.171 — EXP-FIX STALE-DEADLOCK (уроки больше не выпадают навсегда), schema v45

Выкладка на **production** (192.255.209.205, `/var/www/admin_bot`), 09.11.2026 04:57Z.

## 1. Границы выкладки

| Поле | Значение |
|---|---|
| DEPLOY_SOURCE | `release/2.58.171` = `4f7428e659f317a849cfbc3fa3b2b40da2328469` |
| Кандидат на ревью | `2779059b` (Reviewer APPROVED; изолированная проверка, 97 passed) |
| Bump-коммит | `4f7428e6` — только `APP_VERSION`, README, F8-мета, version-пины (28 строк) |
| Предыдущий прод | `42f068df` @ `release/2.58.170`, healthz 2.58.170, schema 45 |
| MUTABLE_WORKTREE_REQUIRED | **no** — immutable checkout по SHA, `dirty_tracked=0` |
| Repo write scope | `config/settings.py`, `README.md`, `plans/docs/param-registry-round1025.meta.md`, 24 test-файла |
| Δ DDL | **0** — `user_version` 45 до и после, `schema_migrations` 34, миграций нет |

Дерево `integ/unify-release` (рабочая копия другой полосы, уроки-контракт) **не использовалось**:
сборка релиза шла в отдельном worktree по SHA. Дерево с правкой (`stale-lesson-fix-…`) осталось чистым.

### Дельта `42f068df..2779059b` (2 коммита)

| Коммит | Суть |
|---|---|
| `54640673` | docs: отчёт выкладки 2.58.170 + живое доказательство MAC-EXP-06 (продуктового кода нет) |
| `2779059b` | `services/mca_experience.py`, `services/mca_experience_jobs.py` + новый тест — разрешение `recheck_required` у активных уроков |

Посторонних продуктовых правок в дельте нет; схемы/миграций/флагов не затронуто.

## 2. Предрелизная проверка (точно на кандидате)

| Набор | Результат |
|---|---|
| новый `test_mca16_experience_stale_recheck_hotfix.py` | **6 passed** |
| experience/lesson (mca16 block a–f, asap8 v6 d05, evol020, mca17c oversight, exp-fix checkpoint) | **163 passed** |
| maintenance (memory_maintenance, communities_maintenance, mca17c invariants, mca18 lifecycle, mca17 sleep workers) | **109 passed** |
| после bump: version-пины (13 файлов) | **592 passed** |
| после bump: webapp-пины (11 файлов) + hotfix-тест | **274 passed** |
| после bump: experience + maintenance повторно | **264 passed** |
| F8-каталог `--check` | `CHECK OK: 595 == REGISTRY`, R17-чисто |

Предсуществующих падений в этих наборах не обнаружено — все прогоны зелёные.

## 3. Выкладка

- Снапшот: `/tmp/predeploy-258171.db` — SQLite backup API с read-only источника,
  `user_version 45`, `quick_check ok`, 1 829 609 472 B,
  sha256 `f7051553588467dc19259699b22b1cca25cef4a23ee578b38edb6ca9333e11c5` (read-back на снапшоте).
- `git fetch origin release/2.58.171` → `git checkout -B release/2.58.171 4f7428e6` → `dirty_after=0`
  (единственная «грязь» — untracked `.cache/`, была и до выкладки).
- `systemctl restart admin_bot` → старт 04:57:30Z, `migrations: start | current user_version=45 | pending=[]`,
  цепочка 0.0 s (миграции нет), healthz 2.58.171.

## 4. Пост-деплой

| Проверка | Факт |
|---|---|
| Unit | `active (running)`, **NRestarts=0**, MainPID `3319871`, старт 2026-11-09T04:57:30Z |
| `/healthz` локально | `{"status":"ok","version":"2.58.171"}` |
| `/healthz` публично (`admin-bot.duckdns.org`) | 200, `2.58.171` |
| Served asset | `web/app.js` sha256 `e6fdef1f2210a28fef3dab636e1a866558044cefb1825233825f037802812291` = файл в checkout |
| Схема | `user_version` **45**, `schema_migrations` **34**, `quick_check ok` |
| Планировщик | `[mca16] experience review tick` выполнен после рестарта (05:12:49Z) — джоб зарегистрирован |
| Журнал | `Traceback` **2** — обе строки `services.meme_initiative` `attempt journal failed: database is locked`; в 24 ч до выкладки **28 таких же** (почасовой триггер в :09). Предсуществующее, к дельте не относится |
| Диск | 32G/99G (35 %) |

## 5. Живая проверка исправления (ради неё и делался релиз)

Тик опыта 05:12:49Z (job `3cdf02c7…`), счётчики из payload: `recheck_resolved=3`, `recheck_suspended=1`,
`stale_marked=1`, `proposed=2`, `validated=2`, `activated=2`, `errors=0`.

Состояние до релиза — снапшот 04:57Z (код 2.58.170), после — живая БД 05:15Z.

| Урок | Правило | До (04:57Z) | После (05:15Z) | В `list_scope_candidates` | `mca_lesson_applications` |
|---|---|---|---|---|---|
| `2beea514…d00` | `pref:games.gacha`, user 138811255 | active, recheck=1, compat 2.58.161 | **active, recheck=0**, compat 2.58.171 | **да** (было нет) | 0 строк (было 0) |
| `80abe73f…fc7` | `pref:service.speed`, user 138811255 | active, recheck=1, compat 2.58.79 | **active, recheck=0**, compat 2.58.171 | **да** (было нет) | 0 строк (было 0) |
| `929fe541…845` | failure_pattern, chat −1002661910336 | active, recheck=1, compat 2.58.79 | **suspended**, recheck=1 | нет (и не должно) | 0 строк (было 0) |
| `87d81a6a…073` | `pref:bot.no_slash_commands` (текущий) | active, recheck=0 | **active, recheck=0** | да (было да) | 0 строк (было 0) |

- Два «застрявших» урока снова отбираются; правило не активировалось заново без свидетельств —
  статус `active` сохранён, `validated` не подменялся.
- Третий урок (`failure_pattern`, chat) ушёл в **suspended**: сохранённых независимых эпизодов
  под текущие tool schema/модель не нашлось (свидетельства от 16.10 под старую схему `ec28a277`
  больше правило не подтверждают). Причина — отсутствие проверяемых свидетельств, а не ошибка.
- Новое предложение по тому же правилу **разрешено и прошло**: появился урок `9c97344e…421`
  (failure_pattern, тот же чат, active/recheck=0/compat 2.58.171). Всего за тик предложено 2 урока
  (второй — `e639763a…3f6`, `pref:attitude.ukrainians_neutral`, другой пользователь), оба валидированы
  и активны; строки истории не удалялись (было 4 урока, стало 6).
- Контрактное различие подтверждено живьём: у текущего `87d81a6a…073` сменился только
  `compat_config_version` (2.58.170 → 2.58.171), урок остался active и отбираемым — дрейф версии
  конфига не инвалидирует измерение, а смена tool schema/модели инвалидирует.
- `mca_lesson_applications` пуста и после релиза: применение урока происходит при реальном ответе
  в чате, такого хода с момента тика не было. Ничего не форсировали.

## 6. Откат

- **Код:** `git checkout release/2.58.170` (`42f068df`) + `systemctl restart admin_bot`.
- **Данные:** `/tmp/predeploy-258171.db` (v45, sha256 выше) — состояние до тика, где уроки были
  с `recheck=1`; дневная копия `backups/local_database_20261109.db`. Схема не менялась, откат кода
  схему не ломает. Уроки после тика — 2 новых строки + 1 suspended; откат кода их не удалит
  (восстановление только из снапшота, если понадобится точное прежнее состояние).
- Диск 32G/99G — место под снапшоты есть.

## 7. Что осталось

- Применение уроков в живом ответе (`mca_lesson_applications`) — появится на первом реальном
  ходе в чате, где отбор даёт урок; проверять не форсируя.
- Реализация контракта уроков — отдельный поздний релиз, в этот выкат не входит.
- Предсуществующее (не блокер релиза): `meme_initiative` «attempt journal failed: database is locked»
  каждый час — своя полоса записи, кандидат в бэклог.
