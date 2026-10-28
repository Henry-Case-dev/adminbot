# Локальная уборка рабочего места, 28.10.2026

Прод-сервер не открывался. SSH, деплой и сеть к 198.46.175.136 не использовались. Коммита нет. `git reset --hard`, `git clean`, `git worktree remove --force` и удаление веток не применялись.

Метод замера: Python `scandir`, `followlinks=False`, пропуск reparse point и symlink, префикс длинных путей. До: `C:\Users\main\AppData\Local\Temp\opencode\cleanup-before-size.json` (22:42:25+1200). После: `cleanup-after-size.json` (22:53:15+1200).

## Байты

| Путь | До | После | Освобождено |
| --- | ---: | ---: | ---: |
| `C:\Code\Python` | 52335180864 | 25199230782 | 27135950082 |
| `C:\Code\Python` без `adminbot` | 37930805688 | 13832911102 | 24097894586 |
| `C:\Users\main\.config\opencode\OpenCodeScratch` | 43422623041 | 36608855516 | 6813767525 |
| `C:\Users\main\.config\opencode\OpenCodeCache` | 1550136288 | 0 | 1550136288 |
| `C:\Users\main\AppData\Local\Temp\opencode` | 6405447735 | 4801856960 | 1603590775 |
| `C:\Users\main\.config\opencode` целиком | 45058007457 | 36697156193 | 8360851264 |

`config` включает scratch и cache, это не отдельная куча. Основной выигрыш — 71 снятый worktree рядом с репозиторием (около 27.1 ГБ у `C:\Code\Python`).

## Git

- `git -C C:\Code\Python\adminbot rev-parse --show-toplevel` → `C:/Code/Python/adminbot`
- HEAD основного дерева на старте: `394ce806fa1cc3f89ea101060786ec50fca88b37` (`refs/heads/master`)
- `git status --porcelain`: 154 строки. Чужие грязные файлы не откатывались. В эту цифру входят правка секции гигиены в `AGENTS.md` и этот отчёт.
- `git worktree list`: было 127, стало 56 (1 основное + 55 оставленных).
- `git worktree prune` выполнен после снятий. Основное дерево не трогалось.
- `git fsck --no-progress` завершился быстро. Много dangling commit/blob/tree. Это не чистилось: `git gc` / `git prune` не запускались, чтобы не потерять объекты вне веток.

## Снятые worktree: 71, ошибок 0

Все сняты `git worktree remove` без `--force`. Перед каждым снятием повторно проверен пустой `git status --porcelain`. Ветка, если была, сохранена.

- `C:/Code/Python/ab-258111-check`
- `C:/Code/Python/adminbot/OPENCODE_WORKFLOW_SCRATCH/fs-release-25884`
- `C:/Code/Python/adminbot/OPENCODE_WORKFLOW_SCRATCH/inc83-master`
- `C:/Code/Python/adminbot/OPENCODE_WORKFLOW_SCRATCH/inc83-tests`
- `C:/Code/Python/adminbot/OPENCODE_WORKFLOW_SCRATCH/incident-release-25882`
- `C:/Code/Python/adminbot/OPENCODE_WORKFLOW_SCRATCH/incident-release-25883`
- `C:/Code/Python/adminbot/OPENCODE_WORKFLOW_SCRATCH/prebase-141e1e49`
- `C:/Code/Python/adminbot/OPENCODE_WORKFLOW_SCRATCH/rev-diag-base`
- `C:/Code/Python/adminbot/OPENCODE_WORKFLOW_SCRATCH/rev-rel-25889`
- `C:/Code/Python/adminbot/OPENCODE_WORKFLOW_SCRATCH/w2-before-f1418d7`
- `C:/Code/Python/adminbot-wt-a4`
- `C:/Code/Python/adminbot-wt-asap2probe`
- `C:/Code/Python/adminbot-wt-asap3`
- `C:/Code/Python/adminbot-wt-asap5i`
- `C:/Code/Python/adminbot-wt-asap5m`
- `C:/Code/Python/adminbot-wt-asap5n`
- `C:/Code/Python/adminbot-wt-asap5v`
- `C:/Code/Python/adminbot-wt-asap5w3`
- `C:/Code/Python/adminbot-wt-asap8`
- `C:/Code/Python/adminbot-wt-book`
- `C:/Code/Python/adminbot-wt-cfg`
- `C:/Code/Python/adminbot-wt-cover-review`
- `C:/Code/Python/adminbot-wt-cover400`
- `C:/Code/Python/adminbot-wt-cover400-review`
- `C:/Code/Python/adminbot-wt-coverfix`
- `C:/Code/Python/adminbot-wt-delta-audit`
- `C:/Code/Python/adminbot-wt-fc1`
- `C:/Code/Python/adminbot-wt-fcp`
- `C:/Code/Python/adminbot-wt-gaps`
- `C:/Code/Python/adminbot-wt-map`
- `C:/Code/Python/adminbot-wt-nost1`
- `C:/Code/Python/adminbot-wt-nost1-base`
- `C:/Code/Python/adminbot-wt-p0c2`
- `C:/Code/Python/adminbot-wt-pa5`
- `C:/Code/Python/adminbot-wt-pa5cor`
- `C:/Code/Python/adminbot-wt-pa5cor-rev`
- `C:/Code/Python/adminbot-wt-pemsoc`
- `C:/Code/Python/adminbot-wt-pemsoc-review`
- `C:/Code/Python/adminbot-wt-pm127`
- `C:/Code/Python/adminbot-wt-probe2510`
- `C:/Code/Python/adminbot-wt-rel-p0`
- `C:/Code/Python/adminbot-wt-rel127`
- `C:/Code/Python/adminbot-wt-rel129`
- `C:/Code/Python/adminbot-wt-rel130`
- `C:/Code/Python/adminbot-wt-residual`
- `C:/Code/Python/adminbot-wt-soul43`
- `C:/Code/Python/adminbot-wt-speech-meta`
- `C:/Code/Python/adminbot-wt-speech-p0-b2`
- `C:/Code/Python/adminbot-wt-tgl`
- `C:/Code/Python/adminbot-wt258112`
- `C:/Code/Python/adminbot-wt258113`
- `C:/Code/Python/adminbot-wt258114`
- `C:/Code/Python/adminbot-wt258115`
- `C:/Users/main/.config/opencode/OpenCodeScratch/adminbot-ccef72c25768/cfg1-release-25888/wt`
- `C:/Users/main/.config/opencode/OpenCodeScratch/adminbot-ccef72c25768/deploy-258113/wt-master`
- `C:/Users/main/.config/opencode/OpenCodeScratch/adminbot-ccef72c25768/p0-old-258130`
- `C:/Users/main/.config/opencode/OpenCodeScratch/adminbot-ccef72c25768/release-25887/wt`
- `C:/Users/main/.config/opencode/OpenCodeScratch/adminbot-ccef72c25768/release-25889/wt`
- `C:/Users/main/.config/opencode/OpenCodeScratch/adminbot-ccef72c25768/release-25892/wt`
- `C:/Users/main/.config/opencode/OpenCodeScratch/adminbot-ccef72c25768/release-25893/wt`
- `C:/Users/main/.config/opencode/OpenCodeScratch/adminbot-ccef72c25768/release-25894/wt`
- `C:/Users/main/.config/opencode/OpenCodeScratch/adminbot-ccef72c25768/release-25896/wt`
- `C:/Users/main/.config/opencode/OpenCodeScratch/adminbot-ccef72c25768/release-25896/wt-base`
- `C:/Users/main/.config/opencode/OpenCodeScratch/adminbot-ccef72c25768/release-25897/wt`
- `C:/Users/main/.config/opencode/OpenCodeScratch/adminbot-ccef72c25768/release-25897/wt-base`
- `C:/Users/main/.config/opencode/OpenCodeScratch/adminbot-ccef72c25768/rev-limits-r2/wt`
- `C:/Users/main/.config/opencode/OpenCodeScratch/adminbot-ccef72c25768/soul1-release-25886/wt`
- `C:/Users/main/.config/opencode/OpenCodeScratch/adminbot-ccef72c25768/win-glass-release-25885/base-check`
- `C:/Users/main/AppData/Local/Temp/opencode/adminbot-base`
- `C:/Users/main/AppData/Local/Temp/opencode/headcheck-quotes`
- `C:/Users/main/AppData/Local/Temp/opencode/rev-embed-468d1041`

## Оставленные worktree: 55 + основное

Основное `C:/Code/Python/adminbot` не трогалось.

Два detached-коммита не входят ни в одну ветку, поэтому деревья оставлены:

- `C:/Code/Python/adminbot-wt-nost1-rev` HEAD `a94f1b5914a30e133d1bfad9f02867a94fa5423d`
- `C:/Code/Python/adminbot-wt-rel-final-rev` HEAD `f57cb18ca4c6e55c43b5155835fb8cdc57c46b08`

Остальные 53 оставлены, потому что `git status --porcelain` не пустой (незакоммиченные или неотслеживаемые файлы). Ветки не удалялись. Среди тяжёлых: `Temp\opencode\f10parent` (1013 изменений), `head_check` (1572), `mca19_headcheck` (2113). Полный список с SHA — в `C:\Users\main\AppData\Local\Temp\opencode\worktree-classification.json`.

Процессы: после исправления чтения cwd прочитано 233 каталога из 429 процессов. Ни один читаемый процесс не держал кандидат на снятие. `SeDebugPrivilege` не выдан (ошибка 1300), 192 системных процесса недоступны. Это не помешало снятию чистых деревьев.

## Соседи `C:\Code\Python`

Удалено, это был мусор без уникального кода:

- `C:\Code\Python\.pytest_cache`
- `C:\Code\Python\plans` — только пустые каталоги `features\cfg\evidence`, файлов не было
- `C:\Code\Python\..__junit_review.xml` — обломок pytest от 03.10.2026
- `C:\Code\Python\_commitmsg.txt` — черновик сообщения, уже есть в коммите `0866264c`

Оставлено:

- `C:\Code\Python\Temp\opencode\d2_disk_clean_log.txt` — единственная локальная запись уборки бэкапов на сервере от 07.10.2026. Это не копия из репозитория.
- все грязные `adminbot-wt-*`, перечисленные выше
- сам `C:\Code\Python\adminbot`

## Scratch и cache

`OpenCodeScratch` больше не место для новых записей. Удалены только каталоги без зарегистрированного worktree, без `.db`/`.sqlite`/`.bak`/`.pem` и без файлов, которых нет в основном дереве или которые от него отличаются. Счётчик: удалено 1117 путей, оставлено 437. Журнал: `scratch-deletion.json`.

Не удалялось: каталоги с базами и `pre_migration_*.db`, уникальные probe/json/png, 4 каталога со своим `.git`, оставшиеся зарегистрированные worktree. Поэтому в scratch всё ещё около 36.6 ГБ.

`OpenCodeCache\adminbot-ccef72c25768\repo-intel.sqlite3` (восстановимый индекс, 1550136288 байт вместе с wal) снят после успешного `BEGIN EXCLUSIVE`. Процесс индекс не держал. `node_modules` приложения OpenCode не удалялся.

В `Temp\opencode` удалены одноразовые probe-каталоги. Штампы замера и json этой уборки оставлены. Зарегистрированные грязные worktree там тоже оставлены.

## Политика, чтобы это не повторялось

Корень: каталог установленного глобального конфига + `WorkspaceData/`, переопределяется только `OPENCODE_WORKSPACE_DATA`. Каталоги созданы: `temp/`, `cache/`, `worktrees/`, `runs/`, `backups/`, `registry/` (плюс совместимые `reports/`, `quarantine/`).

- `allocate` пишет в `WorkspaceData/runs/`
- `worktree-path` печатает путь в `WorkspaceData/worktrees/`
- `epic-close --repo <root> --epic <id>` снимает только зарегистрированные чистые worktree этого эпика, уже входящие в HEAD репозитория, без `--force` и без удаления веток. Грязные и уникальные коммиты остаются. Закрытые tool-owned runs этого эпика удаляются только с `--confirmed-complete --confirmed-idle --apply`.
- Orchestrator/DevOps обязаны вызывать `epic-close` после интеграции эпика, не по таймеру.
- Старый `OpenCodeScratch` — только цель разовой уборки, не место записи.

Проверка инструмента: `python -m unittest tools.test_workflow_housekeeping` — 11 тестов, OK, 6.3 с.

Изменённые файлы:

- `C:\Users\main\.config\opencode\tools\workflow_housekeeping.py`
- `C:\Users\main\.config\opencode\AGENTS.md`
- `C:\Users\main\.config\opencode\agents\Builder.md`
- `C:\Users\main\.config\opencode\agents\DevOps.md`
- `C:\Users\main\.config\opencode\agents\PM.md`
- `C:\Users\main\.config\opencode\agents\Reviewer.md`
- `C:\Users\main\.config\opencode\agents\Orchestrator.md`
- `C:\Code\Python\adminbot\AGENTS.md` (только секция гигиены)

## Команды, которые не прошли с первого раза

- `python` в PATH — заглушка Microsoft Store. Дальше использовался `py -3.12`.
- Первый сбор cwd процессов был неверным (усечённый HANDLE и знаковые байты). Снятие worktree началось только после повторной проверки: 233 cwd, 0 занятых кандидатов.
- `SeDebugPrivilege` не назначен (ошибка 1300). На решение не повлияло.
- `git worktree remove` отказов не дал. `--force` не использовался.
