# PM binding: срез E (S5-LOCAL-FIRST) и срез I3 (S10-LEARNING-INCIDENTS)

Дата: 2026-11-14 (UTC+12). Интеграционное дерево: `master` @ `44d2fb30`.
Область правки: карта `requirements-map.json` + этот evidence-файл + `plans/backlog.md`.
Код, production, `plans/progress_scope.json`, `plans/current_task.md` не изменялись.

## 1. Что сделано

1. Опубликованы в интеграционном дереве три ранее живших только в ветках артефакта:
   - `evidence/binding-e-18fa4d593591b8438b2e3832fd7aa8e6af478064.md` (sha256 `ed024ec788b1b7d035eb9d2248ac4bd9ded313176ee3a44e2208d8b1b5583d4a`);
   - `evidence/binding-i3-89a37168.md` (sha256 `63279742b45e006f23160d8d8e54111f941e340382cdc86ae9c0c55941665e95`);
   - `evidence/review-i3-89a37168.md` (sha256 `13ea42fcc523aab3ed3bc24109dead81dd80e0e010522bd4694f46db960571a9`).
2. В `slice_candidate_bindings` добавлены `S5-LOCAL-FIRST` и `S10-LEARNING-INCIDENTS` с точными SHA, базой, веткой, worktree и суммами артефактов.
3. Строки `SXR-I3-01` (17) и `SXR-I3-02` (3) переведены `PENDING` → `REVIEW`: приложены review-evidence (реальный вердикт Reviewer) и implementation-evidence (binding).
4. В 45 строк `SXR-E1-01..SXR-E4-01` записана implementation-evidence; статус оставлен `PENDING` (причина — §2).

## 2. E: кандидат привязан, но ревью не существует (единственный блокер)

Задание исходило из наличия `evidence/review-e-18fa4d59.md` с вердиктом Approved. Фактически такого артефакта нет. Проверено:

- в worktree среза (`…-9a0f2c2b`, ветка `smart/e-local`, HEAD `44258430`) каталог `evidence/` содержит только `binding-c-source-ab42343e.md`, `binding-e-18fa4d59…md`, `e-cleanup-retention.json`; `git status` чистый, untracked-файлов нет;
- `git grep -l "SXR-E1-01"` по 12 головам (`smart/e-local`, `smart/i3-lessons`, `smart/i4-codes`, `smart/g-finalize`, `smart/i2-stream`, `smart/d-capacity`, `smart/c-source`, `smart/i1-journal`, `smart/ab`, `smart/f-github`, `release/2.58.199`, `master`) находит **только** `binding-e-18fa4d59…md`;
- `git log --all --diff-filter=A -- '…/evidence/review-e-*'` и `-- '…/evidence/review-i3-*'` — пусто: файл никогда не добавлялся ни в одну ветку;
- в `WorkspaceData/runs/**` одноимённых артефактов нет; сам binding прямо фиксирует: «`VERIFIED`/`DONE` не ставим — это слово Reviewer».

Поэтому строки E **не** переведены в `REVIEW`: статус без независимого Approved-вердикта был бы ложным, а `independent_approval` в гейте таких доказательств не признаёт. Регресс E и мутационная фальсификация мной не проводились (это не задача PM).

Что уже зафиксировано по E фактически: кандидат `18fa4d59` (docs `2d6878bf`, HEAD `44258430`, база `36dd6b23`, ветка `smart/e-local`), 29 focused passed, 583 broad passed, RED на базе `36dd6b23` — 28 errors + probe `provider=github`/`ref_source=remote_default_branch`.

**Минимальное действие для снятия блокера:** один проход Reviewer по HEAD `44258430` (docs-only поверх `18fa4d59`) и публикация `evidence/review-e-18fa4d59.md`; после этого строки E переводятся в `REVIEW` без повторного анализа реализации.

## 3. I3: привязан и переведён в REVIEW, но остаётся вердикт Needs Fixes

`review-i3-89a37168.md` — реальный независимый вердикт: поведение проверено по трём столпам (`_forbidden_effects`, machine-applicability regex, contour-pair regex, валидатор/активатор, 7 тестов, независимый прогон по реальному DB/service-пути), **Needs Fixes только по candidate-bound привязке и гейту**. Деплой не выполнялся.

Строки переведены в `REVIEW` с честно сохранённым вердиктом `Needs Fixes`, поэтому review-гейт остаётся красным ровно на строке «missing candidate-bound independent Reviewer approval» — это и есть тот повторный проход Reviewer, который требует сам review (§ Next action).

## 4. Точные результаты гейтов (после правки)

```
--stage plan   → inventory=509 manual=359 scoped=0 errors=0
--stage review --slice S5-LOCAL-FIRST --candidate 18fa4d59… → scoped=45 errors=45
    45× "mandatory not ['REVIEW','VERIFIED'] (got PENDING)" — ровно строки E из §2;
    "candidate mismatch" исчез: привязка среза работает.
--stage review --slice S10-LEARNING-INCIDENTS --candidate d471309a… → scoped=30 errors=30
    20× "missing candidate-bound independent Reviewer approval" — строки I3 (§3);
    10× "mandatory not ['REVIEW','VERIFIED'] (got PENDING)" — соседние строки SXR-I5-01, ожидаемо PENDING;
    "candidate mismatch" исчез.
```

До правки оба scoped-прогона давали `candidate mismatch` + PENDING на всех строках среза.

## 5. Source lineage / owner-input

`--stage plan` подтверждает источник карты: `plans/owner_inputs/2026-11-14-smart-execution-reliability-01.md`, sha256 `32ef8c8289cf3f66e8949048a449178223cc0f058c3701e60cda72f8a60ecaf1` — совпадает на интеграционном дереве. Замечание review о «lack of strict inventory owner-input source» относится к worktree среза: ветви E и I3 стоят на базе `d20a7f73`, где файла `plans/owner_inputs/**` ещё нет. В интеграционном дереве пробела нет, новых требований не выдумывалось.

`plans/progress_scope.json` не изменялся (единственный писатель — Orchestrator). Read-only проверка: `owner_inputs` 90 зарегистрировано / 90 reconciled / pending `[]`; `source_coverage` 67/67 accounted, `unmapped_tasks` `[]`, `execution_queue.complete=true` (40 открытых задач, issues `[]`).

## 6. Postdeploy-остатки (не заявляются выполненными)

- E: `systemd`-пользователь процесса и GitHub API по deployed commit (binding §8). Деплоя не было, `live_required=false`, `live_when=preprod` — поля строк намеренно не менялись.
- I3: восстановление уже лежащих в production candidate-строк после деплоя (binding §8). Деплоя не было.

Ни один из остатков не выдан за выполненный, `VERIFIED` не выставлялся, эпик не помечен DONE.

## 7. Следующее действие

1. Reviewer: проход по E (HEAD `44258430`) → публикация review-артефакта → строки E в `REVIEW`.
2. Reviewer: повторный проход по I3 gate/binding (поведение уже одобрено) → снятие единственного блокера.
3. DevOps: только после Approved — деплой и postdeploy-остатки §6.

## 8. Housekeeping

Анализ и скрипт привязки выполнялись в выделенной run-директории
`WorkspaceData/runs/c742e4de9e92c489/smart-execution-reliability-01-45d7d5f19c3b/temp-5e0267b0e4` (allocate → run-close после завершения проверки).
Worktree срезов E и I3 не удалялись и не изменялись: они нужны Reviewer.
