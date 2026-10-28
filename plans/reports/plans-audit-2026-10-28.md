# Аудит plans/ — 28.10.2026

Лейн: PLANS-AUDIT. Только локальная раскладка документов. Прод, SSH, Telegram, деплой и коммит не трогались. `plans/current_task.md`, `plans/workflow_state.md`, `plans/progress_scope.json` и `plans/owner_inputs/` не редактировались.

## Счёт

| | файлов |
|---|---|
| Было всего в `plans/` | 5758 |
| Оставлено на месте (вне `plans/archive/`) | 4508 |
| Уже лежало в `plans/archive/` до этой правки | 1231 |
| Перенесено в архив | 19 |
| Удалено | 0 |
| Стало в `plans/archive/` | 1250 |
| Всего после правки | 5758 |

Размер живого дерева после правки: 4508 файлов, около 361 МБ. Архив: 1250 файлов, около 40 МБ. Плоский архив не схлопывался.

## Перенесено

`git mv` (история сохранится после будущего коммита; коммит из этого лейна не делался):

`plans/features/expression-bisect-2026-10-21-results/` → `plans/archive/features/expression-bisect-2026-10-21-results/`

19 файлов: сырые ответы абляции, системные промпты плеч, офлайн-харнес и два read-only SSH-зонда. Секретов в скриптах нет: они читают серверный `.env` на месте и ничего не вшивают.

Почему это было безопасно: ни одна карта из `progress_scope.json`, ни один `owner_inputs`, ни тест и ни код не ссылались на этот каталог. Единственная живая ссылка была относительной, в отчёте `plans/features/expression-bisect-2026-10-21.md` (строки про сырые данные). Сам отчёт оставлен: его путь цитируют `plans/current_task.md` и карта `plans/features/asap-speech-arch/requirements-map.json`. Две ссылки в отчёте переведены на архивный путь. После переноса поиск старого пути `plans/features/expression-bisect-2026-10-21-results` по картам и `owner_inputs` пуст. Упоминание старого пути осталось только в журнале `plans/archive/INDEX.md` как запись «откуда → куда».

## Удалено

Ничего. Точных дублей (тот же SHA-256, что у оставляемого файла) вне защищённых каталогов не нашлось. Пустые файлы вроде `*-diff-empty.txt` и `glass-identical-to-master.txt` — это доказательства пустого диффа, не мусор. Файлы с «copy»/«draft» в имени лежат внутри активных фич и являются скриншотами или payload-снимками.

## Оставлено: крупные каталоги, которые нельзя было двигать

Активные каталоги карт из `progress_scope.json` оставлены целиком, вместе с доказательствами:

`soul-1`, `asap8-v6-3-live-correction`, `cfg`, `win-glass-hotfix`, `p0-save-init-ux`, `p0-vision-universal`, `add-tr`, `add-exp`, `samples-ux`, `asap-speech-arch`, `asap2-direct-chat`, `embed-identity-compat`, `asap3-corrective`, `p0-corrective-factcheck-speech`, `pemsoc-one-reaction`, `p0-factcheck-media`, `p0-delta-analysis`, `asap5-multimodal`, `post-asap5-corrective`, `p0-nostalgia-rework`, `p0-admin-cache-toggle-save`.

`plans/features/p0-factcheck-post-release/` — задача в scope со статусом BUILDING. Массив `maps` пуст, но каталог и карта на диске есть. Счётчик прогресса отдельно говорит, что карта неполная. Не переносился.

`plans/features/asap8-v6-remediation/` (39 файлов) — на него ссылаются карта `asap8-v6-3-live-correction`, `backlog.md` и `current_task.md`. Журнал архива от 15.10 уже оставил его как базу для сверки v6.3.

`plans/features/corrective-fix-2026-10-21/` — путь есть в картах `add-tr` и `soul-1`.

`plans/features/factcheck-fix-2026-10-21/` — `artifact_path` в карте `cfg`.

`plans/features/residuals-asap23/` — `artifact_path` в картах `asap2-direct-chat` и `asap3-corrective`.

`plans/features/_audit-2026-10-23/` (114 файлов, около 1,7 МБ) — оставлен целиком. Живые карты держат конкретные доказательства:

- `release-258113/guards.txt`, `deploy.md`, `deploy-frozen-b92226cf.md`
- `release-258114/deploy.md`, `binding-final.md`
- `release-258118/e2e-inspector.txt`
- `release-258124/deploy.md`
- `release-258125/` и `release-258125/README.md`

Часть этих файлов даже не в git, но карты на них смотрят. Дополнительно `plans/features/p0-corrective-factcheck-speech/evidence/withheld-postdeploy.md` (сам является `artifact_path`) ссылается на `release-258122/deploy.md`. Внутренние отчёты аудита ссылаются друг на друга (`review-rel.md` → embed-rebuild / embed-fallback / b11 / summary-revision). Резать каталог значит либо порвать привязанное доказательство, либо переписать текст карты. Это запрещено. Нецитированные подкаталоги (`soul1-fixtures`, `summary-triage`, `b11-diag-fix`, `embed-fallback-fix`, `embed-provider`, `embed-rebuild`, `prod-checks`, `summary-revision-fix`, `release-258117`, `release-258121`) оставлены как неопределённые: доказать, что их никто не читает через короткую относительную ссылку из оставляемого файла, нельзя без правки связанных доказательств.

Отдельные отчёты в `plans/features/`, не каталоги, тоже оставлены: `expression-bisect-2026-10-21.md`, `owner-corrective-2026-10-21.md`, `owner-corrective-followup-2026-10-21.md`, `owner-corrective-initreply-2026-10-22.md`, `factcheck-run-diag-2026-10-21.md`, `direct-l1-rootcause-2026-10-21.md`, `nostalgia-audit-2026-10-21.md`, `owner-obs-recon.md`. На них смотрят карты, тесты, `backlog.md` или `current_task.md`. `owner-obs-recon.md` карты цитируют по имени сверки OWNER-OBS-RECON в поле `reason`, без пути. Перенос без правки этих причин спрятал бы основание owner_optional-строк.

## Оставлено: корень, docs, reports

- `plans/current_task.md`, `plans/workflow_state.md`, `plans/progress_scope.json`, `plans/runtime_task.md`, `plans/backlog.md`, `plans/owner_questions.md`, `plans/owner_live_checks.md`, `plans/owner_inputs/` — текущие источники и восстановление. Не трогались.
- `plans/ARCHITECTURE.md` (около 1,9 МБ) — `backlog.md` ссылается на разделы; тест `tests/test_avatars_round1017.py` открывает файл по этому пути. Журнал 15.10 уже запретил перенос без правки теста. Тест вне `plans/` не менялся.
- `plans/MEMORY.md` — на него есть ссылка из `plans/owner_inputs/2026-10-25-plans-reconciliation.md`.
- `plans/project.md`, `plans/metrics.md`, `plans/verification_cache.json` — действующие указатели/кэш, оставлены журналом 15.10. Не мусор.
- `plans/owner-obs-diagnostics-2026-10-21.md` — раздел 9 в `plans/owner_live_checks.md`.
- `plans/docs/**` — оставлен целиком. Тесты и `tools/gen_param_registry_round1025.py` читают `param-registry-round1025.*`, `screen-map-round1025.md`, `widget-map-round1025.md`. `README.md` и `plans/project.md` держат обзоры памяти и research-отчёты. `plans/docs/agentic-audit-round1026.md` по собственному контракту архивации A0 не архивируется. `tools/_d2_mca20_drift.py` сверяет хэш `mca-round1027-arch-frames.md`. Канон `plans/docs/canon/` указан в `project.md` и `MEMORY.md`.
- `plans/reports/` — все текущие файлы закреплены: `plans-reconciliation-2026-10-25.md` и `local-workspace-cleanup-2026-10-28.md` стоят в `recorded_in`; `final-report-p0-cycle-2026-10-27.md` — `artifact_path` нескольких карт; `disk-analysis-2026-10-28.md` цитирует `AGENTS.md` проекта; `round1025_f8_config_diff.md`, контрастные hotfix 6/7/8 и `round10.16_*` читаются тестами или README; `round1025_f10_shots/` — снимки, которые журнал 15.10 явно оставил.

## Проверки после правки

Команды запускались из `C:\Code\Python\adminbot`.

1. `py -3 C:\Users\main\.config\opencode\tools\workflow_housekeeping.py plans-check --plans plans` — код выхода **2**. Команды `plans-check` в инструменте нет. Доступны только `init`, `allocate`, `worktree-path`, `register-worktree`, `epic-close`, `audit`. Это не дефект раскладки.
2. `py -3 C:\Users\main\.config\opencode\tools\workflow_progress.py --scope-file plans\progress_scope.json` — код выхода **0**, но прогресс **не рассчитан**. Причины уже были до аудита: несогласованный вход `OI-2026-10-28-LOCAL-WORKSPACE-CLEANUP` и неполная карта задачи `p0-factcheck-post-release`. Флаг `reconciled` не менялся: его пишет оркестратор.
3. `py -3 C:\Users\main\.config\opencode\tools\requirements_gate.py check --stage plan --map plans/features/pemsoc-one-reaction/requirements-map.json --repo .` — код выхода **1**. Карта не менялась. Сообщение инструмента: `inventory=0`, `manual=4`, `errors=8` (`no inventory items` и несопоставленные строки источника L00011–L00018). Это прежняя дыра карты, не следствие переноса.

Поиск старого пути по активным картам и `plans/owner_inputs` после переноса: совпадений нет. Откат не потребовался.
