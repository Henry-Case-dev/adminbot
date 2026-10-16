# Аудит сохранности и «единого workflow» (lane V63-CLOSE, кандидат c2775a54)

Назначение: закрыть доказательственную часть PRIN-PRESERVE, PRIN-ONE-WORKFLOW,
B12.4 («фальшивые SEND/lesson отсутствуют — аудит источников») и обозначить
точные незакрытые клаузы B12.6. Все проверки выполнены на дереве кандидата
`c2775a54258512a3e20c97341d3e8a6738b1a33b` (scratch-worktree, не рабочее дерево).

## 1. PRIN-ONE-WORKFLOW — нет новой очереди/БД, один workflow

| Проверка | Команда | Факт |
|---|---|---|
| ΔDDL в v6.3 | `git diff f58a644..c2775a54 -- services/database.py services/pg_db.py` \| count `^\+.*(CREATE TABLE\|ALTER TABLE)` | **0** |
| Новые очереди/брокеры/воркеры | `git diff --name-only f58a644..c2775a54 -- services web tools config` \| match `celery\|rq\|kafka\|rabbit\|worker_queue\|new_queue` | **0** |
| Объём кодового диффа | `git diff --stat f58a644..c2775a54 -- services web tools config tests` | 158 файлов, +24316/−1893 |
| Хранилища | `services/database.py` (SQLite) + `services/pg_db.py` (PostgreSQL) | используются существующие, новых слоётов нет |
| Workflow | один OpenCode-workflow, один репозиторий, один пакет `plans/features/asap8-v6-3-live-correction/` | новой самостоятельной очереди/БД не введено |
| Human-gate к Architect | `db8dae53` (CORR-1 owner correction: фон заморожен, стекло адаптируется) + `2d68b331`/`d6366e31` (backlog по ревью) | эскалация задокументирована и носит продуктово-архитектурный характер |

Вывод: клаузы «нет новой самостоятельной очереди/БД», «используются existing
SQLite+PostgreSQL», «один workflow» подтверждены. Незакрытой части нет.

## 2. PRIN-PRESERVE — backup / rollback / feature-gate / сохранность

| Клауза | Доказательство |
|---|---|
| Деплой-план с backup/rollback | `live-canary.md`: ΔDDL=0 (backup-шаг не требуется), pre-deploy SHA = `b9ea4907` (bump 2.58.78), механика `git pull --ff-only`, сервис active post-restart, готовый откат-сценарий |
| Feature-gate | по каждому механизму есть env/settings-гейт с emergency-осью (B11-отчёт: `gate effective` + env-axis; B07 `temporal.tool_enabled` через hot; DREAM/DEEP_SLEEP off by default в прогоне на history-БД) |
| Деструктивных операций с сообщениями/памятью/фактами/стилями нет | `tests/test_asap8_v63_b09_migration.py` — 0 DELETE, backup-before-write, chunked backup + hard-cap abort; `tests/test_asap8_v63_b03_memory.py` — `test_infinite_mode_never_deletes`, `test_supersede_version_crossing`, `test_infinite_retention_keeps_vec_row_on_invalidate` (UPDATE vec вместо DELETE) |
| Права Telegram | в диффе v6.3 нет новых BotFather-мутаций (REV-W2: «U07 BotFather не мутируется» — в диффе нет API-вызовов) |
| RBAC/redaction | `web/api` не расширяли поверхности данными (REV-W3 §5: backend логов не тронут; RBAC-проверки в тестах overrides/dossier) |
| Сводка зелёных негативных тестов сохранности на кандидате | `c2775a54-verification-runs.md` §1–§2: 152 + 616 passed (включая b03 11, b09, d06 9, d07 11) |

## 3. B12.4 — аудит источников: нет записи фальшивых SEND/lesson ради счётчиков

Поиск сайтов записи уроков/SEND в коде кандидата:

```
Select-String services\*.py -Pattern 'INSERT INTO (mca_lessons|mca_lesson_applications|smart_messages)'
→ services/database.py:7285,7301,7343,7566,7587,7618,7674
→ services/mca_experience.py:734,794
```

* `services/database.py` — репозиторные методы persistence-слоя (единственный
  писатель), `services/mca_experience.py` — продюсер Experience (реальный
  контур «эпизод → review → кандидат → применение»), не отдельный скрипт.
* `tools/*` подобных записей не содержат: совпадения по `mca_lessons` —
  `ui_asap8_w3_analytics_e2e.py` (декларация реестра процессов, не INSERT) и
  `v63_b11_mechanisms_report.py` (read-only отчёт, SQLite открывается `mode=ro`).
* Скриптов «донабрать счётчиков» (утилит, пишущих строки lesson/SEND в боевую БД)
  в `tools/` и `services/` не найдено; запись в прод возможна только через
  реальный пайплайн.

Вывод: клауза B12.4 «фальшивые SEND/lesson отсутствуют (аудит источников)»
подтверждена на уровне кода кандидата. Живой аспект (live input/output по
журналу) держится на `w4-live-probes.md §1` / `live-canary.md` и агентом не
перепроверялся (нет доступа к journal).

## 4. B12.6 — что осталось незакрытым (честно)

| Клауза | Статус | Незакрытая часть |
|---|---|---|
| Snapshot снят до миграций/массовых пересборок | закрыто | `SNAPSHOT_MANIFEST.md` + `current_task.snapshot_2026-10-15.md` (sha `91f754e3…` = манифест) |
| SQLite/PostgreSQL и старая память не удаляются | закрыто | §2 данного документа (0 DELETE, infinite-retention, ΔDDL=0) |
| Ошибки названий | закрыто | `tests/test_asap8_f7_stories.py`: fallback unknown/ambiguous, fail-open, «no numeric ID dump in main UI» |
| Ошибки адресатов | **не закрыто** | отдельного негативного теста на ошибочного адресата не найдено |
| GraphRAG hallucinated stats | **не закрыто** | негативных тестов именно на «галлюцинированную статистику GraphRAG» не найдено (есть `test_hallucinated_tool_not_allowed` для Direct L1 — другой контур) |
| Side effects измеримы | **не закрыто** | артефакта измерения side-effect’ов миграций/пересборок в пакете нет |

Итог: B12.6 остаётся открытым по трём конкретным пунктам; предложение —
выделить их отдельным маленьким лейном (3 теста + 1 замер), а не смягчать
acceptance.
